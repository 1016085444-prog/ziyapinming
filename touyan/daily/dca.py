"""定投（3 年以上，每月一次）· 看温度定投

对手盘：自己的情绪。定投不需要判断涨跌，它靠的是「跌的时候同样的钱买到更多份额」；它怕的是在低点停投、
以及涨上去了不知道卖——A 股宽基指数十几年来回坐过山车，只买不卖，定投的年化只有 3%–7%。

拿指数基金的真实净值（含分红）比了几种做法（research/exp46–48），结论分三类：
- 境内宽基（沪深300、中证500、中证1000、创业板、科创50、上证50）：关键在卖。市场温度（temperature.py）到 80 以上全部卖出，
  回到 40 以下再分 12 个月投回去——年化从 3%–7% 提到 9%–12%，投满 5 年赚钱的概率从七成提到九成以上。
  买的时候按温度多投少投（越冷越多），收益只多半个点，但途中的浮亏小一截。
- 红利类（中证红利、红利低波）：一直定投、不卖最好。它们没有宽基那种大起大落，止盈反而少赚。
- 境外（纳斯达克100、标普500、恒生）：市场温度量的是 A 股，管不到它们。美股指数过去十几年一直定投不卖最好；
  「赚 20%/30%/50% 就卖」的目标止盈法在哪一类上都没有稳定的好处。

每只基金都拿它自己的净值把上面的做法重新模拟一遍，结果直接写在页面上：任意一个月开始、投满 3 年和 5 年，
赚钱的概率、中位收益、差的一成情况。这是统计，不是预测。
"""

from __future__ import annotations

import bisect
import math
import re
from datetime import date, timedelta

from market.models import Bar

from . import evidence as ev
from . import temperature as tp
from .common import clip, pct, quantile
from .pool import day_int

KEY, TITLE, NAME = "dca", "定投", "看温度定投"
HORIZON = "3 年以上，每月一次"
STEP = 21                  # 一个月约 21 个交易日
MONTHS = 36                # 「定投成本温度」回看 3 年
MIN_YEARS = 5
CASH_M = 0.02 / 12         # 没投出去的钱放货币基金，年化 2%
FEE = 0.001                # 买卖各扣 0.1%
SELL_AT, BACK_AT = 80, 40  # 温度到 80 以上卖出；回到 40 以下再投回去
REDEPLOY = 12              # 卖出的钱分 12 个月投回
MIN_IRR = 0.03             # 按各自的方法一直投到现在，年化不到 3% 的不推荐

IDEA = ("定投不用判断涨跌，但要会卖。境内宽基指数基金按「市场温度」来：越冷投得越多，温度到 80 以上全部卖出，回到 40 以下再投回去；"
        "红利类和美股指数基金一直投、不用卖。每只基金都用它自己十几年的真实净值把这套做法模拟了一遍，结果写在下面。")
HOW = [
    "候选：沪深300、中证500、中证1000、创业板、科创50、上证50、中证红利、红利低波、恒生、恒生科技、纳斯达克100、标普500 的指数基金（A 类份额，选成立最早的那只）",
    "至少要有 5 年净值，才模拟得出像样的结果",
    "境内宽基：这个月投多少看市场温度——20 以下 2 倍，20–40 是 1.5 倍，40–60 正常，60–80 减半，80 以上停投并全部卖出；卖出的钱等温度回到 40 以下，分 12 个月投回去",
    "红利类、美股指数：每月固定投，一直不卖（历史上加了止盈反而少赚）",
    "排序：按各自的方法在它自己历史上投满 5 年的赚钱概率和年化；境内宽基最多两只，红利、港股、美股各一只",
    "定投日建议放在每月 26 号以后：历史上月末那几天平均比当月均价便宜 0.25%–0.5%",
]

# (大类, 方法, [(指数名, 基金名里要出现的字)])；方法：temp 看市场温度，hold 一直投不卖
GROUPS = [
    ("A股宽基", "temp", [("沪深300", ("沪深300",)), ("中证500", ("中证500",)), ("中证1000", ("中证1000",)),
                       ("创业板", ("创业板",)), ("科创50", ("科创板50", "科创50")), ("上证50", ("上证50",))]),
    ("红利", "hold", [("中证红利", ("中证红利",)), ("红利低波", ("红利低波动", "红利低波"))]),
    ("港股", "hold", [("恒生指数", ("恒生指数", "恒生"))]),
    ("港股科技", "hold", [("恒生科技", ("恒生科技",))]),
    ("美股", "hold", [("纳斯达克100", ("纳斯达克100", "纳指100")), ("标普500", ("标普500",))]),
]
METHOD_OF = {g: m for g, m, _ in GROUPS}
GROUP_LIMIT = {"A股宽基": 2}
METHOD_LABEL = {"temp": "看市场温度：越冷投得越多，80 以上卖出", "hold": "每月固定投，一直不卖"}
_REST = re.compile(r"(ETF|联接|指数|发起式|发起|成份|成分|LOF|QDII|FOF|人民币|份额|[()（）\-])*(A类?)?")
_PREFIX = re.compile(r"[一-鿿]{2,10}")


def match_index(name: str, words: tuple[str, ...]) -> bool:
    """名字是不是「某公司 + 指数名 + ETF联接/指数 + A」这种纯粹跟踪指数的基金（不要增强、行业、C 类）。"""
    for w in words:
        i = name.find(w)
        if i > 0 and _PREFIX.fullmatch(name[:i]) and _REST.fullmatch(name[i + len(w):]):
            return True
    return False


def find_candidates(rank_rows: list[dict], today: date | None = None) -> list[dict]:
    """每个指数挑一只：成立满 5 年的里面成立最早的（净值历史最长）。"""
    cutoff = ((today or date.today()) - timedelta(days=MIN_YEARS * 365)).isoformat()
    out = []
    for group, method, indexes in GROUPS:
        for label, words in indexes:
            found = [r for r in rank_rows if r.get("inception") and r["inception"] <= cutoff
                     and match_index(r.get("name", ""), words)]
            if found:
                best = min(found, key=lambda r: r["inception"])
                out.append(dict(best, index=label, group=group, method=method))
    return out


def rolling_stats(bars: list[Bar], horizon: int) -> dict | None:
    """历史上任意一天买入、持有 horizon 个交易日的收益分布（复权净值）。"""
    closes = [b.adj_close for b in bars]
    rets = sorted(closes[i + horizon] / closes[i] - 1 for i in range(len(closes) - horizon) if closes[i] > 0)
    if len(rets) < 60:
        return None
    n = len(rets)
    return {"horizon": horizon, "windows": n, "years": round(len(closes) / 245, 1),
            "win_rate": sum(1 for r in rets if r > 0) / n, "median": rets[n // 2],
            "p10": rets[int(n * 0.1)], "p90": rets[min(n - 1, int(n * 0.9))]}


# ── 这只基金自己的「定投成本温度」（只作参考：现在比过去三年定投的人的成本高还是低） ──

def dca_cost(closes: list[float], t: int) -> float:
    """到第 t 天为止，过去三年每月定投一次的平均成本（调和平均：每次投一样的钱）。"""
    return MONTHS / sum(1 / closes[t - STEP * k] for k in range(MONTHS))


def temperatures(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
    """每一天的 (净值 ÷ 定投成本, 在它自己历史上的分位)。只用到当天为止的数据。"""
    n = len(closes)
    ratios: list[float | None] = [None] * n
    temps: list[float | None] = [None] * n
    seen: list[float] = []
    for t in range(STEP * (MONTHS - 1), n):
        ratio = closes[t] / dca_cost(closes, t)
        ratios[t] = ratio
        bisect.insort(seen, ratio)
        if len(seen) >= 250:                       # 至少攒够一年的样本才给分位
            temps[t] = 100 * bisect.bisect_right(seen, ratio) / len(seen)
    return ratios, temps


# ── 按市场温度定投 ────────────────────────────────────────────────

def multiplier(temp: float | None) -> float:
    if temp is None:
        return 1.0
    return 2.0 if temp < 20 else 1.5 if temp < 40 else 1.0 if temp < 60 else 0.5 if temp < 80 else 0.0


def advice(temp: float | None, method: str = "temp") -> str:
    if method != "temp":
        return "每月固定投，不用看温度"
    if temp is None:
        return "市场温度没算出来，按正常金额投"
    if temp < 20:
        return "市场很冷，投 2 倍"
    if temp < 40:
        return "市场偏冷，投 1.5 倍"
    if temp < 60:
        return "不冷不热，正常投"
    if temp < 80:
        return "市场偏热，减半投"
    return "市场很热：这个月不买，已经买的分批卖出"


def monthly(closes: list[float], temps: list[float | None]) -> tuple[list[float], list[float | None]]:
    """每 21 个交易日取一个点（从最新一天往回数），模拟都在这条月线上做。"""
    idx = list(range(len(closes) - 1, -1, -STEP))[::-1]
    return [closes[i] for i in idx], [temps[i] for i in idx]


def _irr(months: int, value: float) -> float | None:
    """每月投 1 份、投了 months 个月，最后值 value：求月收益率，折成年化。"""
    if value <= 0 or months <= 0:
        return None
    lo, hi = -0.5, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        grown = sum((1 + mid) ** (months - k) for k in range(months))
        if grown < value:
            lo = mid
        else:
            hi = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def run(c: list[float], t: list[float | None], method: str, start: int = 0, end: int | None = None) -> dict:
    """在月线上模拟：从第 start 个月到第 end 个月（不含），每个月有 1 份新钱。

    method = hold：每月投 1 份，不卖。
    method = temp：按市场温度的倍数投（钱不够就有多少投多少，少投的攒着）；温度到 80 以上全部卖出；
                   攒下的钱和卖出的钱，在温度回到 40 以下时分 12 个月投回去。没有温度的月份按正常投。
    返回 {multiple: 期末总值 ÷ 累计投入, irr: 年化, worst: 途中最深浮亏, sells: 卖出次数, months}。
    """
    end = len(c) if end is None else end
    units = cash = pile = 0.0
    sells, worst = 0, 0.0
    months = 0
    for k in range(start, end):
        cash = cash * (1 + CASH_M) + 1.0
        pile *= 1 + CASH_M
        months += 1
        temp = t[k]
        if method == "temp":
            amount = min(cash, multiplier(temp))
            cash -= amount
            if temp is not None and temp < BACK_AT:
                if cash > 1e-9:
                    part = min(cash, max(cash / REDEPLOY, 0.5))
                    cash -= part
                    amount += part
                if pile > 1e-9:
                    part = min(pile, max(pile / REDEPLOY, 1.0))
                    pile -= part
                    amount += part
        else:
            amount, cash = cash, 0.0
        units += amount * (1 - FEE) / c[k]
        if method == "temp" and temp is not None and temp >= SELL_AT and units > 0:
            pile += units * c[k] * (1 - FEE)
            units = 0.0
            sells += 1
        worst = min(worst, (units * c[k] + cash + pile) / months - 1)
    total = units * c[end - 1] + cash + pile
    return {"multiple": total / months, "irr": _irr(months, total), "worst": worst, "sells": sells, "months": months,
            "in_fund": units * c[end - 1] / total if total > 0 else 0.0}


def windows(c: list[float], t: list[float | None], method: str, months: int, first: int = 0) -> dict | None:
    """任意一个月开始、投满 months 个月的结果分布。"""
    results = sorted(run(c, t, method, s, s + months)["multiple"] - 1 for s in range(first, len(c) - months + 1))
    if len(results) < 12:
        return None
    n = len(results)
    return {"n": n, "months": months, "win_rate": sum(1 for x in results if x > 0) / n, "median": quantile(results, 0.5),
            "p10": quantile(results, 0.1), "p90": quantile(results, 0.9), "worst": results[0]}


def evaluate(row: dict, bars: list[Bar], temp_now: float | None = None) -> dict | None:
    closes, days = [], []
    for b in bars:
        if b.adj_close > 0:
            closes.append(b.adj_close)
            days.append(day_int(b.date))
    if len(closes) < MIN_YEARS * 245:
        return None
    method = row.get("method") or METHOD_OF.get(row.get("group", ""), "hold")
    market = tp.temps_on(days)
    if temp_now is not None:
        market[-1] = temp_now
    c, t = monthly(closes, market)
    first = next((i for i, x in enumerate(t) if x is not None), 0) if method == "temp" else 0
    plain3, plain5 = windows(c, t, "hold", 36, first), windows(c, t, "hold", 60, first)
    if not plain3:
        return None
    rule3 = rule5 = None
    full_plain = run(c, t, "hold", first)
    full_rule = None
    if method == "temp":
        rule3, rule5 = windows(c, t, "temp", 36, first), windows(c, t, "temp", 60, first)
        full_rule = run(c, t, "temp", first)
    ratios, own = temperatures(closes)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 750), len(closes))]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) * 245)
    years = len(closes) / 245
    best = (rule5 or rule3) if method == "temp" else (plain5 or plain3)
    irr = (full_rule or full_plain)["irr"] or 0.0
    score = best["win_rate"] * 100 * 0.6 + clip(irr / 0.12, 0, 1) * 100 * 0.3 + clip(years / 12, 0, 1) * 100 * 0.1
    return {"row": row, "method": method, "plain3": plain3, "plain5": plain5, "rule3": rule3, "rule5": rule5,
            "full_plain": full_plain, "full_rule": full_rule, "since": days[-1 - (len(c) - 1 - first) * STEP] if method == "temp" else days[0],
            "own_temp": own[-1], "ratio": ratios[-1], "market_temp": market[-1] if method == "temp" else None,
            "from_high": closes[-1] / max(closes) - 1, "vol": vol, "years": years, "score": round(score, 1)}


def _since_text(e: dict) -> str:
    d = e["since"]
    return f"{d // 10000} 年 {d // 100 % 100} 月"


def build_pick(e: dict) -> dict:
    row, method = e["row"], e["method"]
    temp = e["market_temp"]
    mult = multiplier(temp) if method == "temp" else 1.0
    best = (e["rule5"] or e["rule3"]) if method == "temp" else (e["plain5"] or e["plain3"])
    plain = e["plain5"] if best["months"] == 60 and e["plain5"] else e["plain3"]
    span = f"{best['months'] // 12} 年"
    full = e["full_rule"] or e["full_plain"]
    evidence = [{"label": "怎么投", "status": "info", "detail": METHOD_LABEL[method]}]
    if method == "temp":
        evidence += [
            {"label": "这个月", "status": "pass" if (temp or 50) < 40 else "warn" if (temp or 50) >= 60 else "info",
             "detail": (f"市场温度 {temp:.0f}：{advice(temp)}" if temp is not None else advice(None))},
            {"label": f"投满 {span}", "status": "pass" if best["win_rate"] >= 0.8 else "warn",
             "detail": f"按这个方法，它自己历史上 {best['n']} 个起点里 {best['win_rate'] * 100:.0f}% 赚钱，中位 {best['median'] * 100:+.0f}%；"
                       f"只买不卖是 {plain['win_rate'] * 100:.0f}%、{plain['median'] * 100:+.0f}%"},
            {"label": "一直投到现在", "status": "pass" if (e["full_rule"]["irr"] or 0) > (e["full_plain"]["irr"] or 0) else "warn",
             "detail": f"从 {_since_text(e)}起每月投：按这个方法年化 {(e['full_rule']['irr'] or 0) * 100:+.1f}%（中途卖出 {e['full_rule']['sells']} 次，最深浮亏 {e['full_rule']['worst'] * 100:.0f}%）；"
                       f"只买不卖年化 {(e['full_plain']['irr'] or 0) * 100:+.1f}%（最深浮亏 {e['full_plain']['worst'] * 100:.0f}%）"},
        ]
    else:
        evidence += [
            {"label": f"投满 {span}", "status": "pass" if best["win_rate"] >= 0.8 else "warn",
             "detail": f"每月固定投、不卖，它自己历史上 {best['n']} 个起点里 {best['win_rate'] * 100:.0f}% 赚钱，中位 {best['median'] * 100:+.0f}%，差的一成情况 {best['p10'] * 100:+.0f}%"},
            {"label": "一直投到现在", "status": "pass" if (full["irr"] or 0) >= 0.05 else "warn",
             "detail": f"从 {_since_text(e)}起每月投到现在：年化 {(full['irr'] or 0) * 100:+.1f}%，途中最深浮亏 {full['worst'] * 100:.0f}%"},
        ]
        if e["own_temp"] is not None:
            evidence.append({"label": "现在贵不贵", "status": "info",
                             "detail": f"现在的净值比过去三年每月定投的人的平均成本{'低' if e['ratio'] < 1 else '高'} {abs(e['ratio'] - 1) * 100:.0f}%"
                                       f"（在它自己历史上排 {e['own_temp']:.0f}%）。只作参考：对这类基金，按这个调整金额并没有多赚"})
    evidence += [
        {"label": "离高点", "status": "info", "detail": f"距历史最高净值 {e['from_high'] * 100:.0f}%"},
        {"label": "波动", "status": "info", "detail": f"近三年年化波动 {e['vol'] * 100:.0f}%；{e['years']:.0f} 年净值数据"},
    ]
    risks = ["这笔钱要三年内用不着：中途急用钱、被迫卖在低点，是定投亏钱最常见的原因"]
    if row.get("ft") == "qdii" or row.get("group") in ("美股", "港股", "港股科技"):
        risks.append("投的是境外市场：有申购限额，汇率涨跌也会影响收益；市场温度量的是 A 股，对它不适用")
    if row.get("group") == "美股":
        risks.append("过去十几年是美股的大牛市，「一直投不卖最好」是在这段行情里得出来的，以后未必")
    if method == "temp":
        text = (f"按这个方法，它自己历史上任意一个月开始、投满 {span}（{best['n']} 个起点）：赚钱的概率 {best['win_rate'] * 100:.0f}%，"
                f"累计收益中位 {best['median'] * 100:+.0f}%；差的一成情况 {best['p10'] * 100:+.0f}%，最差 {best['worst'] * 100:+.0f}%。"
                f"同样的起点只买不卖：{plain['win_rate'] * 100:.0f}% 赚钱，中位 {plain['median'] * 100:+.0f}%。这是过去的统计，不是承诺。")
        rules = [
            "每月固定一天投（建议 26 号以后）。投多少看市场温度：20 以下 2 倍，20–40 是 1.5 倍，40–60 正常，60–80 减半",
            f"止盈：市场温度到 {SELL_AT} 以上，停投，并把已经买的全部卖出（可以分两三个月卖完）——这是这个方法里最要紧的一条",
            f"卖出的钱先放货币基金，等温度回到 {BACK_AT} 以下，分 {REDEPLOY} 个月投回去",
            "不设止损：下跌时同样的钱买到更多份额，这正是定投赚钱的来源（前提是指数，不是单只股票）",
            "每月回来看一次温度就够了，不用天天看",
        ]
    else:
        text = (f"每月固定投、不卖，它自己历史上任意一个月开始、投满 {span}（{best['n']} 个起点）：赚钱的概率 {best['win_rate'] * 100:.0f}%，"
                f"累计收益中位 {best['median'] * 100:+.0f}%；差的一成情况 {best['p10'] * 100:+.0f}%，最差 {best['worst'] * 100:+.0f}%。这是过去的统计，不是承诺。")
        rules = [
            "每月固定一天投一样多的钱（建议 26 号以后），不用看温度",
            "不止盈：检验下来，这类基金加了止盈反而少赚。要用钱的时候再卖",
            "不设止损：下跌时同样的钱买到更多份额",
            "每年回来看一眼就够了",
        ]
    return {
        "key": f"OF:{row['code']}", "code": row["code"], "name": row["name"], "kind": "fund",
        "industry": f"{row['group']} · {row['index']}", "price": row.get("nav"), "as_of": row.get("nav_date", ""),
        "score": e["score"], "temp": None if temp is None else round(temp), "multiplier": mult, "method": method,
        "headline": f"{row['index']}：{advice(temp, method)}",
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": None,
            "entry": f"每月固定一天投。这个月：{advice(temp, method)}",
            "ref_price": row.get("nav"), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "position": "每月投的钱，以「连投三年也不心疼」为准", "fee": row.get("fee"),
            "rules": rules,
            "expected": {"available": True, "reliable": True, "kind": "dca", "median": best["median"], "low": best["p10"],
                         "high": best["p90"], "win_rate": best["win_rate"], "annual": full["irr"], "years": best["months"] // 12, "text": text},
        },
    }


def ranking_row(e: dict) -> dict:
    row, method = e["row"], e["method"]
    best = (e["rule5"] or e["rule3"]) if method == "temp" else (e["plain5"] or e["plain3"])
    full = e["full_rule"] or e["full_plain"]
    temp = e["market_temp"]
    return {"key": f"OF:{row['code']}", "code": row["code"], "name": row["name"], "index": row["index"], "group": row["group"],
            "method": "看温度" if method == "temp" else "一直投",
            "temp": None if temp is None else round(temp), "multiplier": multiplier(temp) if method == "temp" else 1.0,
            "advice": advice(temp, method), "years": best["months"] // 12,
            "win_rate": pct(best["win_rate"], 0), "median": pct(best["median"], 0), "p10": pct(best["p10"], 0),
            "irr": pct(full["irr"]), "irr_plain": pct(e["full_plain"]["irr"]), "from_high": pct(e["from_high"], 0),
            "history": round(e["years"]), "score": e["score"]}


def checkup(evaluated: list[dict]) -> dict:
    wide = [e for e in evaluated if e["method"] == "temp" and e["rule5"] and e["plain5"]]
    lines = []
    if wide:
        lines.append("今天候选里的境内宽基，投满 5 年赚钱的概率（按温度 / 只买不卖）：" + "；".join(
            f"{e['row']['index']} {e['rule5']['win_rate'] * 100:.0f}% / {e['plain5']['win_rate'] * 100:.0f}%" for e in wide) + "。")
        lines.append("一直投到现在的年化（按温度 / 只买不卖）：" + "；".join(
            f"{e['row']['index']} {(e['full_rule']['irr'] or 0) * 100:+.1f}% / {(e['full_plain']['irr'] or 0) * 100:+.1f}%" for e in wide) + "。")
    return {
        "level": "ok",
        "verdict": ("定投的关键不在怎么买，在会不会卖。境内宽基指数基金一直定投不卖，十几年下来年化只有 3%–7%；"
                    "市场温度到 80 以上全部卖出、回到 40 以下再投回去，年化 9%–12%，投满 5 年赚钱的概率从七成提到九成以上。"
                    "红利类和美股指数基金正相反：一直投不卖最好。下面每只基金的数字，都是拿它自己的净值重新模拟出来的。"),
        "more": lines + [ev.FACTS["dca_sell"], ev.FACTS["dca_hold"], ev.FACTS["dca_day"],
                         "开始定投那天的市场温度也很要紧：温度 40 以下开始、投满 3 年，沪深300 有八成赚钱、中证500 九成；60 以上开始的只有两三成。"
                         "所以市场很热的时候别急着开始，先攒着。",
                         "口径：每月（每 21 个交易日）有 1 份钱；没投出去的放货币基金（年化 2%）；买卖各扣 0.1%；用的是含分红的复权净值。"
                         "卖出只发生过四五轮（2010、2015、2021、2026 年前后），次数不多，但每一轮方向都一样。"],
    }


def select(candidates: list[dict], nav_of, n: int = 5, temp: dict | None = None) -> dict:
    """candidates 来自 find_candidates；nav_of(row) → 净值序列；temp：temperature.compute 的结果。"""
    evaluated, reasons = [], {}
    temp_now = temp["value"] if temp else None
    for row in candidates:
        try:
            bars = nav_of(row)
        except Exception:
            reasons["净值没有取到"] = reasons.get("净值没有取到", 0) + 1
            continue
        e = evaluate(row, bars, temp_now)
        if e is None:
            reasons["净值历史不足 5 年"] = reasons.get("净值历史不足 5 年", 0) + 1
            continue
        evaluated.append(e)
    evaluated.sort(key=lambda e: -e["score"])
    picks, used = [], {}
    paused = weak = 0
    for e in evaluated:
        group = e["row"]["group"]
        if e["method"] == "temp" and temp_now is not None and temp_now >= SELL_AT:
            paused += 1
            continue
        if ((e["full_rule"] or e["full_plain"])["irr"] or 0) < MIN_IRR:
            weak += 1                                     # 历史上定投回报太低的（比如恒生），只列在排名表里
            continue
        if used.get(group, 0) >= GROUP_LIMIT.get(group, 1) or len(picks) >= n:
            continue
        used[group] = used.get(group, 0) + 1
        picks.append(build_pick(e))
    note = ""
    if paused:
        note = (f"市场温度 {temp_now:.0f}（很热）：{paused} 只境内宽基这个月不买，已经买的分批卖出；卖出的钱等温度回到 {BACK_AT} 以下再投回去。"
                "排名表里能看到它们。")
    if weak:
        note += f"{'' if not note else ' '}有 {weak} 只历史上定投的年化不到 {MIN_IRR * 100:.0f}%，没有入选，排名表里能看到。"
    return {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "temp": temp_brief(temp), "checkup": checkup(evaluated),
        "picks": picks, "ranking": [ranking_row(e) for e in evaluated], "note": note,
        "funnel": {"pool": len(candidates), "candidates": len(evaluated), "picked": len(picks), "reasons": reasons},
        "faq": [
            {"q": "为什么不按「赚够 20%/30% 就卖」来止盈？", "a": ev.FACTS["dca_hold"]},
            {"q": "行业指数、不景气的行业适合定投吗？", "a": ev.FACTS["industry"] + "所以定投还是选宽基和红利，不去押某个冷门行业。" + ev.FACTS["industry_cheap"]},
            {"q": "为什么不推荐主动基金？", "a": ev.FACTS["fund"]},
        ],
        "warnings": [],
    }


def temp_brief(temp: dict | None) -> dict | None:
    """定投板块顶上那一行：现在的温度和这个月的倍数。"""
    if not temp:
        return None
    return {"value": temp["value"], "label": temp["label"], "multiplier": multiplier(temp["value"]),
            "text": f"市场温度 {temp['value']:.0f}（{temp['label']}）：境内宽基这个月{advice(temp['value'])[5:] if temp['value'] < 80 else '不买，已经买的分批卖出'}。"}
