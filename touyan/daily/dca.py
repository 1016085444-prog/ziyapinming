"""定投（3 年以上，每月一次）· 模拟出来的定投

对手盘：自己的情绪。定投不需要判断涨跌，它靠的是「跌的时候同样的钱买到更多份额」，
所以适合的是覆盖很多公司、长期向上、中途波动又不小的指数基金；它怕的是在低点停投、甚至割肉。

这里不看市盈率分位之类的估值表，直接用每只指数基金十几年的真实净值做两件事：
1. 模拟定投：历史上任意一个月开始、每月投一次、投满 3 年，结果怎么样——赚钱的概率、中位收益、最差的一成情况。
   这就是「预期收益」的来源，是统计，不是预测。
2. 量现在贵不贵：把现在的净值，和「过去三年每月定投的人的平均成本」比。比他们的成本还低，说明现在买比他们划算。
   这个比值在它自己历史上排第几，就是「温度」（0 最便宜，100 最贵）。温度决定这个月投多少：便宜多投，贵了少投或停投。
   按温度调整倍数到底有没有用，也拿它自己的历史检验一遍，结果直接写出来。
"""

from __future__ import annotations

import bisect
import math
import re
from datetime import date, timedelta

from market.models import Bar

from .common import clip, pct, quantile

KEY, TITLE, NAME = "dca", "定投", "模拟出来的定投"
HORIZON = "3 年以上，每月一次"
STEP = 21                  # 一个月约 21 个交易日
MONTHS = 36                # 模拟定投 3 年
MIN_YEARS = 5

IDEA = ("定投不用判断涨跌，靠的是「跌的时候同样的钱买到更多份额」。这里拿每只指数基金十几年的真实净值模拟定投，"
        "看历史上投满 3 年的结果；再量一量现在比「过去三年一直定投的人」的成本高还是低，决定这个月多投还是少投。")
HOW = [
    "候选：沪深300、中证500、中证1000、创业板、科创50、上证50、中证红利、红利低波、恒生、恒生科技、纳斯达克100、标普500 的指数基金（A 类份额，选成立最早的那只）",
    "至少要有 5 年净值，才模拟得出像样的结果",
    "温度 = 现在的净值 ÷ 过去三年每月定投的平均成本，在它自己历史上的排位（0 最便宜，100 最贵）",
    "排序：现在越便宜、历史上定投 3 年越容易赚钱、年化越高的越靠前；A 股宽基最多两只，红利、港股、美股各一只",
    "温度 80 以上的不入选（现在不便宜），但会列在排名表里",
]

GROUPS = [
    ("A股宽基", [("沪深300", ("沪深300",)), ("中证500", ("中证500",)), ("中证1000", ("中证1000",)),
               ("创业板", ("创业板",)), ("科创50", ("科创板50", "科创50")), ("上证50", ("上证50",))]),
    ("红利", [("中证红利", ("中证红利",)), ("红利低波", ("红利低波动", "红利低波"))]),
    ("港股", [("恒生指数", ("恒生指数", "恒生"))]),
    ("港股科技", [("恒生科技", ("恒生科技",))]),
    ("美股", [("纳斯达克100", ("纳斯达克100", "纳指100")), ("标普500", ("标普500",))]),
]
GROUP_LIMIT = {"A股宽基": 2}
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
    for group, indexes in GROUPS:
        for label, words in indexes:
            found = [r for r in rank_rows if r.get("inception") and r["inception"] <= cutoff
                     and match_index(r.get("name", ""), words)]
            if found:
                best = min(found, key=lambda r: r["inception"])
                out.append(dict(best, index=label, group=group))
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


def dca_cost(closes: list[float], t: int) -> float:
    """到第 t 天为止，过去三年每月定投一次的平均成本（调和平均：每次投一样的钱）。"""
    return MONTHS / sum(1 / closes[t - STEP * k] for k in range(MONTHS))


def temperatures(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
    """每一天的 (净值 ÷ 定投成本, 温度)。温度只用到当天为止的数据，回测时不会偷看未来。"""
    n = len(closes)
    ratios: list[float | None] = [None] * n
    temps: list[float | None] = [None] * n
    seen: list[float] = []
    for t in range(STEP * (MONTHS - 1), n):
        ratio = closes[t] / dca_cost(closes, t)
        ratios[t] = ratio
        bisect.insort(seen, ratio)
        if len(seen) >= 250:                       # 至少攒够一年的样本才给温度
            temps[t] = 100 * bisect.bisect_right(seen, ratio) / len(seen)
    return ratios, temps


def multiplier(temp: float | None) -> float:
    if temp is None:
        return 1.0
    return 2.0 if temp < 20 else 1.5 if temp < 40 else 1.0 if temp < 60 else 0.5 if temp < 80 else 0.0


def advice(temp: float | None) -> str:
    if temp is None:
        return "历史不够长，算不出温度，按正常金额投"
    if temp < 20:
        return "很便宜，投 2 倍"
    if temp < 40:
        return "偏便宜，投 1.5 倍"
    if temp < 60:
        return "不贵不便宜，正常投"
    if temp < 80:
        return "偏贵，减半投"
    return "贵了，这个月不买，已经买的继续拿着"


def _irr(amounts: list[float], value: float) -> float | None:
    """每月投 amounts[k]，最后值 value：求月收益率，再折成年化。"""
    if value <= 0 or sum(amounts) <= 0:
        return None
    m = len(amounts)
    lo, hi = -0.5, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        grown = sum(a * (1 + mid) ** (m - k) for k, a in enumerate(amounts))
        if grown < value:
            lo = mid
        else:
            hi = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def simulate(closes: list[float], temps: list[float | None] | None = None, first: int = 0) -> list[tuple[float, float]]:
    """从 first 起每隔一个月取一个起点，各模拟一次 3 年定投。返回 [(累计收益, 年化)]。
    给了 temps 就按温度调整每月的金额（智能定投），否则每月投一样多。"""
    out = []
    span = STEP * MONTHS
    for s in range(first, len(closes) - span, STEP):
        amounts = [multiplier(temps[s + STEP * k]) if temps else 1.0 for k in range(MONTHS)]
        invested = sum(amounts)
        if invested <= 0:
            continue
        units = sum(a / closes[s + STEP * k] for k, a in enumerate(amounts))
        value = units * closes[s + span]
        irr = _irr(amounts, value)
        if irr is not None:
            out.append((value / invested - 1, irr))
    return out


def summarize(results: list[tuple[float, float]]) -> dict | None:
    if len(results) < 12:
        return None
    totals = sorted(r[0] for r in results)
    irrs = sorted(r[1] for r in results)
    n = len(results)
    return {"n": n, "win_rate": sum(1 for x in totals if x > 0) / n, "median": quantile(totals, 0.5),
            "p10": quantile(totals, 0.1), "p75": quantile(totals, 0.75), "p90": quantile(totals, 0.9),
            "irr": quantile(irrs, 0.5)}


def evaluate(row: dict, bars: list[Bar]) -> dict | None:
    closes = [b.adj_close for b in bars if b.adj_close > 0]
    if len(closes) < MIN_YEARS * 245:
        return None
    plain = summarize(simulate(closes))
    if not plain:
        return None
    ratios, temps = temperatures(closes)
    temp, ratio = temps[-1], ratios[-1]
    first = next((i for i, t in enumerate(temps) if t is not None), None)
    smart = same = None
    if first is not None:
        smart = summarize(simulate(closes, temps, first))
        same = summarize(simulate(closes, None, first))       # 同样的起点，普通定投，用来公平比较
    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 750), len(closes))]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) * 245)
    years = len(closes) / 245
    score = ((100 - (temp if temp is not None else 50)) * 0.45 + plain["win_rate"] * 100 * 0.25
             + clip(plain["irr"] / 0.12, 0, 1) * 100 * 0.20 + clip(years / 12, 0, 1) * 100 * 0.10)
    return {"row": row, "plain": plain, "smart": smart, "same": same, "temp": temp, "ratio": ratio,
            "from_high": closes[-1] / max(closes) - 1, "vol": vol, "years": years, "score": round(score, 1)}


def build_pick(e: dict) -> dict:
    row, plain, temp = e["row"], e["plain"], e["temp"]
    mult = multiplier(temp)
    take = max(round(plain["p75"] * 100), 15)
    evidence = [
        {"label": "现在贵不贵", "status": "pass" if (temp or 50) < 40 else "warn" if (temp or 50) >= 60 else "info",
         "detail": (f"温度 {temp:.0f}：现在的净值比过去三年每月定投的人的平均成本"
                    f"{'低' if e['ratio'] < 1 else '高'} {abs(e['ratio'] - 1) * 100:.0f}%") if temp is not None
                   else "历史不够长，算不出温度"},
        {"label": "离高点", "status": "info", "detail": f"距历史最高净值 {e['from_high'] * 100:.0f}%"},
        {"label": "定投 3 年", "status": "pass" if plain["win_rate"] >= 0.7 else "warn",
         "detail": f"历史上 {plain['n']} 个起点里 {plain['win_rate'] * 100:.0f}% 赚钱，累计收益中位 {plain['median'] * 100:+.0f}%"},
        {"label": "波动", "status": "info", "detail": f"近三年年化波动 {e['vol'] * 100:.0f}%；{e['years']:.0f} 年净值数据"},
    ]
    if e["smart"] and e["same"]:
        better = e["smart"]["irr"] - e["same"]["irr"]
        evidence.append({"label": "按温度投", "status": "pass" if better > 0.003 else "warn",
                         "detail": f"按温度调整每月金额，在它自己的历史上中位年化 {e['smart']['irr'] * 100:.1f}%，普通定投 {e['same']['irr'] * 100:.1f}%"
                                   + ("" if better > 0.003 else "——对它帮助不大，按正常金额投也可以")})
    risks = ["这笔钱要三年内用不着：中途急用钱、被迫卖在低点，是定投亏钱最常见的原因"]
    if row.get("ft") == "qdii" or row.get("group") in ("美股", "港股", "港股科技"):
        risks.append("投的是境外市场：有申购限额，汇率涨跌也会影响收益")
    text = (f"历史上任意一个月开始、每月定投满 3 年（{plain['n']} 个起点）：赚钱的概率 {plain['win_rate'] * 100:.0f}%，"
            f"累计收益中位 {plain['median'] * 100:+.0f}%（折合年化约 {plain['irr'] * 100:.1f}%）；"
            f"较差的一成情况 {plain['p10'] * 100:+.0f}%，较好的一成 {plain['p90'] * 100:+.0f}%。这是过去的统计，不是承诺。")
    return {
        "key": f"OF:{row['code']}", "code": row["code"], "name": row["name"], "kind": "fund",
        "industry": f"{row['group']} · {row['index']}", "price": row.get("nav"), "as_of": row.get("nav_date", ""),
        "score": e["score"], "temp": None if temp is None else round(temp), "multiplier": mult,
        "headline": f"{row['index']}：{advice(temp)}",
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": None,
            "entry": f"每月固定一天投（比如发薪日后）。这个月：{advice(temp)}",
            "ref_price": row.get("nav"), "target_price": None, "target_pct": take, "stop_price": None, "stop_pct": None,
            "position": "每月投的钱，以「连投三年也不心疼」为准", "fee": row.get("fee"),
            "rules": [
                "倍数跟着温度走：低于 20 投 2 倍，20–40 投 1.5 倍，40–60 正常投，60–80 减半，80 以上不买、只拿着",
                "不设止损：下跌时同样的钱买到更多份额，这正是定投赚钱的来源（前提是指数，不是单只股票）",
                f"止盈：累计收益达到 +{take}%（历史上定投三年较好的那四分之一情况）并且温度高于 80 时，分 3 个月卖出，然后从头再来",
                "每月回来看一次温度就够了，不用天天看",
            ],
            "expected": {"available": True, "reliable": True, "kind": "dca", "median": plain["median"], "low": plain["p10"],
                         "high": plain["p90"], "win_rate": plain["win_rate"], "annual": plain["irr"], "text": text},
        },
    }


def select(candidates: list[dict], nav_of, n: int = 5) -> dict:
    """candidates 来自 find_candidates；nav_of(row) → 净值序列。"""
    evaluated, reasons = [], {}
    for row in candidates:
        try:
            bars = nav_of(row)
        except Exception:
            reasons["净值没有取到"] = reasons.get("净值没有取到", 0) + 1
            continue
        e = evaluate(row, bars)
        if e is None:
            reasons["净值历史不足 5 年"] = reasons.get("净值历史不足 5 年", 0) + 1
            continue
        evaluated.append(e)
    evaluated.sort(key=lambda e: -e["score"])
    picks, used = [], {}
    for e in evaluated:
        group = e["row"]["group"]
        if e["temp"] is not None and e["temp"] >= 80:
            continue
        if used.get(group, 0) >= GROUP_LIMIT.get(group, 1) or len(picks) >= n:
            continue
        used[group] = used.get(group, 0) + 1
        picks.append(build_pick(e))
    ranking = [{"key": f"OF:{e['row']['code']}", "code": e["row"]["code"], "name": e["row"]["name"],
                "index": e["row"]["index"], "group": e["row"]["group"],
                "temp": None if e["temp"] is None else round(e["temp"]), "multiplier": multiplier(e["temp"]),
                "advice": advice(e["temp"]), "win_rate": pct(e["plain"]["win_rate"], 0), "median": pct(e["plain"]["median"], 0),
                "irr": pct(e["plain"]["irr"]), "p10": pct(e["plain"]["p10"], 0), "from_high": pct(e["from_high"], 0),
                "years": round(e["years"]), "score": e["score"]} for e in evaluated]
    hot = sum(1 for e in evaluated if e["temp"] is not None and e["temp"] >= 80)
    note = ""
    if evaluated and not picks:
        note = "候选的指数现在都不便宜（温度 80 以上）。已经在定投的继续拿着，这个月先不买。"
    elif hot:
        note = f"有 {hot} 只现在温度在 80 以上，没有入选，排名表里能看到。"
    return {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "checkup": {"level": "model", "verdict": "定投的预期收益来自每只基金自己的历史模拟：任意一个月开始、每月投一次、投满 3 年。"
                                                "A 股过去十几年大起大落，模拟结果包含了几轮牛熊；以后不一定重复。"},
        "picks": picks, "ranking": ranking, "note": note,
        "funnel": {"pool": len(candidates), "candidates": len(evaluated), "picked": len(picks), "reasons": reasons},
        "warnings": [],
    }
