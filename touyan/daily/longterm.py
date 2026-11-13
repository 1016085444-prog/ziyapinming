"""长期（1–3 年）· 耐心溢价

对手盘：没有耐心的人。大部分资金按月、按季度被考核，对「三年后大概率更值钱、但下个月涨不涨不知道」的公司
出价偏低。个人没有考核压力，可以拿时间换这部分差价——前提是公司真的经得起时间。

所以这里不看 K 线形态，只看三件事：
- 生意稳不稳：连续几年的净资产收益率（ROE）不掉队，毛利率不大起大落；
- 利润是不是真钱：经营现金流跟得上净利润，负债不过高；
- 价格贵不贵：盈利收益率（市盈率的倒数）够高。

预期收益不猜股价，拆成两部分算：每年分到手的股息，加上留在公司里的利润带来的增长。
分红比例不用另找数据：一年里每股净资产增加了多少，没增加的那部分利润就是分掉了。
估算偏保守（增长打七折、封顶 12%），并给出悲观和乐观两个情形。

长期基金用另一把尺子：不比谁涨得多，比「大盘涨的时候跟不跟得上、跌的时候少不少亏」。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .common import bucket_of, clip, diversify, is_financial, pct, pct_rank, price, tradable
from .dca import rolling_stats

KEY, TITLE, NAME = "long", "长期", "耐心溢价"
HORIZON = "1–3 年"
GROWTH_CAP, GROWTH_HAIRCUT = 0.12, 0.7
DEFAULT_PAYOUT = 0.30

IDEA = ("找生意稳、利润是真钱、价格不贵的公司，拿时间换回报。多数资金按季度考核，"
        "对「三年后大概率更值钱、下个月不知道」的公司出价偏低；个人没有考核压力，可以赚这份耐心的钱。")
HOW = [
    "市值 150 亿以上、市盈率 40 倍以内、按市净率和市盈率推算的 ROE 不低于 10%（先从全市场初选 40 只）",
    "近三年年报 ROE 最低不低于 8%、平均不低于 12%（银行、保险、券商放宽到 7% 和 9%）",
    "利润是真钱：经营现金流平均不低于净利润的六成；负债率不超过 70%（金融企业不看这两项）",
    "最新一期净利润同比没有下滑超过 10%",
    "按「股息 + 内生增长」估算的预期年化从高到低排，同一大类最多两只",
]
FUND_HOW = [
    "偏股基金：成立满 3 年、没有锁定期、A/C 份额只留一个，按近 3 年、2 年、1 年、6 个月的同类排名初选",
    "比的是「涨的时候跟不跟得上、跌的时候少不少亏」：大盘上涨的月份平均跟上多少，下跌的月份平均跌多少",
    "规模不到 2 亿、现任经理任职不到 2 年、量化体检评级为减持或卖出的不要",
]


# ── 股票 ──────────────────────────────────────────────────────────

def prefilter(rows: list[dict], n: int = 80) -> list[dict]:
    """全市场快照上的初选：够大、在赚钱、不太贵、推算的 ROE 过得去。"""
    ok = []
    for r in rows:
        pe, pb, mv = r.get("pe"), r.get("pb"), r.get("total_mv")
        if not tradable(r) or not pe or not pb or not mv or pe <= 0 or pe > 40 or pb <= 0 or mv < 1.5e10:
            continue
        roe = pb / pe                                   # 每股收益 / 每股净资产
        if 0.10 <= roe <= 0.60:
            ok.append(dict(r, roe_proxy=roe))
    ep = pct_rank([1 / r["pe"] for r in ok])
    roe = pct_rank([r["roe_proxy"] for r in ok])
    for r, a, b in zip(ok, ep, roe):
        r["pre_score"] = 0.5 * a + 0.5 * b
    return sorted(ok, key=lambda r: -r["pre_score"])[:n]


def annuals(periods: list) -> list:
    return [p for p in periods if p.report_date.endswith("12-31")]


def infer_payout(years: list) -> float | None:
    """分红比例 ≈ 1 −（每股净资产一年的增加额 ÷ 每股收益）。"""
    values = []
    for cur, prev in zip(years, years[1:]):
        if not cur.eps or cur.eps <= 0 or cur.bps is None or prev.bps is None or prev.bps <= 0:
            continue
        delta = cur.bps - prev.bps
        if cur.bps < prev.bps * 0.8 or delta > cur.eps * 1.05:
            continue                       # 送转股让每股净资产变小、增发让它猛增：这两种年份推不出分红
        values.append(clip(1 - delta / cur.eps, 0.0, 0.9))
    return sum(values) / len(values) if values else None


def ttm_pe(row: dict, periods: list) -> float:
    """滚动市盈率 = 现价 ÷ 最近四个季度的每股收益（最新一期累计 + 上年年报 − 上年同期累计）。
    算不出来、或者和行情给的市盈率差得离谱（多半是送转过）时，用行情给的。"""
    quoted = row["pe"]
    latest, px = periods[0], row.get("price")
    if not px or latest.eps is None:
        return quoted
    if latest.report_date.endswith("12-31"):
        eps = latest.eps
    else:
        year = int(latest.report_date[:4])
        last_annual = next((p for p in periods if p.report_date == f"{year - 1}-12-31"), None)
        same = next((p for p in periods if p.report_date == f"{year - 1}{latest.report_date[4:]}"), None)
        if not last_annual or not same or last_annual.eps is None or same.eps is None:
            return quoted
        eps = latest.eps + last_annual.eps - same.eps
    if eps <= 0:
        return quoted
    pe = px / eps
    return pe if 0.5 <= pe / quoted <= 2 else quoted


def expected_return(pe: float, roe: float, payout: float) -> dict:
    """roe、payout 都是小数。返回年化收益的估算和拆解。"""
    ep = 1 / pe
    dividend = payout * ep
    raw_growth = max(roe * (1 - payout), 0.0)
    growth = min(raw_growth, GROWTH_CAP) * GROWTH_HAIRCUT
    return {"dividend": dividend, "growth": growth, "base": dividend + growth,
            "low": dividend + 0.4 * growth - 0.02,           # 增长不及预期，估值还往下掉一点
            "high": dividend + min(raw_growth, 0.15)}


def assess(row: dict, periods: list | None, financial: bool) -> tuple[dict | None, str]:
    """返回 (评估结果, 没通过的原因)。"""
    if not periods:
        return None, "财报没有取到"
    years = annuals(periods)[:3]
    roes = [y.roe for y in years if y.roe is not None]
    if len(roes) < 2:
        return None, "年报不足两年"
    roe_min, roe_mean = min(roes), sum(roes) / len(roes)
    need_min, need_mean = (7.0, 9.0) if financial else (8.0, 12.0)
    if roe_min < need_min or roe_mean < need_mean:
        return None, "ROE 不够高或者不够稳"
    latest = periods[0]
    if latest.net_profit_yoy is not None and latest.net_profit_yoy < -10:
        return None, "最新一期利润下滑超过 10%"
    cash = None
    if not financial:
        ratios = [y.ocf_per_share / y.eps for y in years if y.ocf_per_share is not None and y.eps and y.eps > 0]
        cash = sum(ratios) / len(ratios) if ratios else None
        if cash is not None and cash < 0.6:
            return None, "经营现金流跟不上利润"
        debt = latest.debt_ratio if latest.debt_ratio is not None else years[0].debt_ratio
        if debt is not None and debt > 70:
            return None, "负债率超过 70%"
    payout = infer_payout(years)
    assumed = payout is None
    roe_use = min(roe_mean, roes[0]) / 100 if roes[0] < roe_mean * 0.8 else roe_mean / 100   # 最近一年明显变差就按最近的算
    pe = ttm_pe(row, periods)
    exp = expected_return(pe, roe_use, DEFAULT_PAYOUT if assumed else payout)
    margins = [y.gross_margin for y in years if y.gross_margin is not None]
    stable = None if financial or len(margins) < 2 else (max(margins) - min(margins)) / max(sum(margins) / len(margins), 1)
    growth_ok = latest.net_profit_yoy is None or latest.net_profit_yoy >= 0
    score = (clip(exp["base"] / 0.15, 0, 1) * 55 + clip(roe_min / roe_mean, 0, 1) * 15
             + (10 if cash is None or cash >= 1 else 5) + (10 if stable is None or stable <= 0.15 else 4)
             + (10 if growth_ok else 0))
    return {"years": years, "latest": latest, "pe": pe, "roe_min": roe_min, "roe_mean": roe_mean, "cash": cash,
            "payout": DEFAULT_PAYOUT if assumed else payout, "payout_assumed": assumed, "exp": exp,
            "margins": margins, "debt": None if financial else (latest.debt_ratio or years[0].debt_ratio),
            "financial": financial, "score": round(score, 1)}, ""


def drawdown_info(closes: list[float]) -> dict | None:
    if len(closes) < 120:
        return None
    peak, worst = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return {"max_drawdown": worst, "from_high": closes[-1] / max(closes) - 1, "days": len(closes)}


def build_pick(row: dict, a: dict, dd: dict | None) -> dict:
    exp, pe = a["exp"], a["pe"]
    years = a["years"]
    span = f"{years[-1].report_date[:4]}–{years[0].report_date[:4]}" if len(years) > 1 else years[0].report_date[:4]
    evidence = [
        {"label": "生意稳", "status": "pass",
         "detail": f"{span} 年报 ROE 最低 {a['roe_min']:.1f}%、平均 {a['roe_mean']:.1f}%"},
        {"label": "价格", "status": "pass" if pe <= 25 else "warn",
         "detail": f"市盈率 {pe:.1f} 倍，每投 100 元一年对应 {100 / pe:.1f} 元利润"},
    ]
    if a["cash"] is not None:
        evidence.append({"label": "利润是真钱", "status": "pass" if a["cash"] >= 0.8 else "warn",
                         "detail": f"经营现金流平均是净利润的 {a['cash']:.1f} 倍"})
    if a["debt"] is not None:
        evidence.append({"label": "负债", "status": "pass" if a["debt"] <= 55 else "warn", "detail": f"资产负债率 {a['debt']:.0f}%"})
    if len(a["margins"]) >= 2:
        evidence.append({"label": "毛利率", "status": "pass",
                         "detail": f"这几年在 {min(a['margins']):.0f}%–{max(a['margins']):.0f}% 之间"})
    latest = a["latest"]
    if latest.net_profit_yoy is not None:
        evidence.append({"label": "最新财报", "status": "pass" if latest.net_profit_yoy >= 0 else "warn",
                         "detail": f"{latest.report_name or latest.report_date}净利润同比 {latest.net_profit_yoy:+.1f}%"})
    evidence.append({"label": "分红", "status": "warn" if a["payout_assumed"] else "pass",
                     "detail": (f"分红比例推算不出来，按 {DEFAULT_PAYOUT * 100:.0f}% 估算" if a["payout_assumed"] else
                                f"按净资产的增长推算，约 {a['payout'] * 100:.0f}% 的利润分给了股东")
                               + f"，对应股息率约 {exp['dividend'] * 100:.1f}%"})
    risks = ["这是按过去几年的经营情况估算的，行业变坏、公司变差时估算会落空"]
    if dd:
        evidence.append({"label": "回撤", "status": "warn" if dd["max_drawdown"] < -0.3 else "pass",
                         "detail": f"过去 {dd['days'] / 245:.1f} 年最大跌过 {dd['max_drawdown'] * 100:.0f}%，"
                                   f"现在距高点 {dd['from_high'] * 100:.0f}%"})
        risks.insert(0, f"持有期间出现 {abs(dd['max_drawdown']) * 100:.0f}% 左右的浮亏是正常的，这笔钱要三年内用不着")
    sell_pe = max(round(pe * 1.8), 33)
    text = (f"预期年化约 {exp['base'] * 100:.1f}%（悲观 {exp['low'] * 100:.1f}%，乐观 {exp['high'] * 100:.1f}%）："
            f"股息约 {exp['dividend'] * 100:.1f}% + 留存利润带来的增长约 {exp['growth'] * 100:.1f}%。"
            "这是按财报推算的估计，不含估值涨跌，不是承诺。")
    return {
        "key": f"{row['market']}:{row['code']}", "code": row["code"], "name": row.get("name", ""), "kind": "stock",
        "industry": row.get("industry", ""), "price": price(row.get("price")), "as_of": "", "score": a["score"],
        "headline": f"ROE 多年稳定在 {a['roe_min']:.0f}% 以上，市盈率 {pe:.0f} 倍，估算年化约 {exp['base'] * 100:.0f}%",
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": None,
            "entry": "分 3 次买入，每次隔一个月。短期涨跌没人知道，分批买是为了买在平均价，不是为了抄底",
            "ref_price": price(row.get("price")), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "position": "单只不超过总资金的两成",
            "rules": [
                "不设价格止损：价格下跌本身不是卖出的理由。跌幅超过 25% 时，把下面几条重新检查一遍，没触发就继续拿",
                "卖出条件一：连续两期财报扣非净利润同比下滑",
                f"卖出条件二：年度 ROE 跌破 {8 if not a['financial'] else 7}%，或者经营现金流连续两年不到净利润的一半",
                f"卖出条件三（止盈）：涨得太贵——市盈率超过 {sell_pe} 倍时分批卖出",
                "每个财报季（4 月底、8 月底、10 月底）回来看一次，平时不用盯",
            ],
            "expected": {"available": True, "reliable": True, "kind": "model", "annual": exp["base"], "low": exp["low"],
                         "high": exp["high"], "dividend": exp["dividend"], "growth": exp["growth"], "text": text},
        },
    }


def select(rows: list[dict], n: int, financials=None, fill_industries=None, closes_of=None) -> dict:
    """financials(rows) → {代码: 财报列表}；closes_of(row) → 收盘价序列（都可能取不到）。"""
    short = prefilter(rows)
    warning = fill_industries(short) if fill_industries and short else ""
    for r in short:
        r["bucket"] = bucket_of(r.get("industry", ""), r.get("name", ""))
    short = diversify(short, 40, per_bucket=5)             # 初选名单也别被一个行业占满
    fin = financials(short) if financials and short else {}
    cands, reasons = [], {}
    for row in short:
        a, why = assess(row, fin.get(row["code"]), is_financial(row.get("industry", ""), row.get("name", "")))
        if a is None:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        cands.append({"row": row, "a": a, "name": row.get("name", ""), "industry": row.get("industry", ""),
                      "bucket": row["bucket"]})
    cands.sort(key=lambda c: -c["a"]["score"])
    picks = []
    for c in diversify(cands, n):
        dd = None
        if closes_of:
            try:
                dd = drawdown_info(closes_of(c["row"]) or [])
            except Exception:
                dd = None
        picks.append(build_pick(c["row"], c["a"], dd))
    return {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "checkup": {"level": "model", "verdict": "长期收益没法用一年半的行情检验，这里的预期收益是按财报推算的：股息 + 留存利润带来的增长，"
                                                "增长打七折、封顶 12%。它回答的是「如果公司继续像过去几年这样经营」，不含估值的涨跌。"},
        "picks": picks,
        "funnel": {"pool": len(rows), "candidates": len(short), "passed": len(cands), "picked": len(picks),
                   "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))},
        "warnings": [warning] if warning else [],
    }


# ── 长期持有的基金 ────────────────────────────────────────────────

LOCKUP_RE = re.compile(r"持有|定开|封闭|定期开放|养老目标")


def share_class_key(name: str) -> str:
    """「易方达蓝筹精选混合A」「易方达蓝筹精选混合C」视为同一只。"""
    return re.sub(r"[（(]?[A-Z][)）]?$", "", name.strip())


def fund_prefilter(rows: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    cutoff = (today - timedelta(days=3 * 365 + 1)).isoformat()
    stale = (today - timedelta(days=15)).isoformat()
    out = []
    for r in rows:
        if not r.get("inception") or r["inception"] > cutoff:
            continue                       # 成立不满 3 年，看不出长期能力
        if r.get("y3") is None or r.get("y1") is None or (r.get("nav_date") or "") < stale:
            continue
        if LOCKUP_RE.search(r.get("name") or ""):
            continue                       # 有锁定期，不适合大多数人
        out.append(r)
    return out


def fund_perf_scores(rows: list[dict]) -> list[dict]:
    """同类分位合成业绩分，并去掉重复份额（保留分高的那个）。"""
    if not rows:
        return []
    ranks = {k: pct_rank([r.get(k) for r in rows], True, 30) for k in ("y3", "y2", "y1", "m6")}
    for i, r in enumerate(rows):
        r["perf_score"] = round(0.40 * ranks["y3"][i] + 0.25 * ranks["y2"][i] + 0.20 * ranks["y1"][i]
                                + 0.15 * ranks["m6"][i], 1)
        r["y3_rank_pct"] = round(100 - ranks["y3"][i], 1)    # 前百分之几
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: -x["perf_score"]):
        key = share_class_key(r["name"])
        if key in seen or r["code"] in seen:
            continue
        seen.update((key, r["code"]))
        out.append(r)
    return out


def capture(nav: list, bench: list) -> dict | None:
    """按月比较：大盘上涨的月份基金平均跟上多少，下跌的月份平均跌多少。"""
    def monthly(bars):
        last = {}
        for b in bars:
            last[b.date[:7]] = b.adj_close
        months = sorted(last)
        return {m: last[m] / last[p] - 1 for p, m in zip(months, months[1:])}

    f, b = monthly(nav), monthly(bench)
    months = [m for m in f if m in b]
    ups = [(f[m], b[m]) for m in months if b[m] > 0]
    downs = [(f[m], b[m]) for m in months if b[m] < 0]
    if len(months) < 24 or len(ups) < 6 or len(downs) < 6:
        return None
    up = sum(x for x, _ in ups) / sum(y for _, y in ups)
    down = sum(x for x, _ in downs) / sum(y for _, y in downs)
    return {"up": up, "down": down, "edge": up - down, "months": len(months)}


def fund_pick(row: dict, report: dict | None, nav: list, bench: list) -> tuple[dict | None, str]:
    """体检 + 涨跌跟随度 → 入选或剔除。"""
    if not report:
        return None, "取不到基金档案"
    profile = (report.get("fund") or {}).get("profile") or {}
    scale = profile.get("scale")
    if scale is not None and scale < 2:
        return None, f"规模只有 {scale:.2f} 亿，有清盘风险"
    managers = profile.get("managers") or []
    tenures = [m["tenure_years"] for m in managers if m.get("tenure_years") is not None]
    tenure = max(tenures) if tenures else None
    if tenure is not None and tenure < 2:
        return None, f"现任经理只管了 {tenure:.1f} 年，业绩未必是他的"
    if report["scores"]["rating"]["code"] in ("Underweight", "Sell"):
        return None, f"量化体检评级为{report['scores']['rating']['label']}"
    cap = capture(nav, bench)
    m3 = (report.get("metrics") or {}).get("3y") or {}
    evidence = [{"label": "长期业绩", "status": "pass",
                 "detail": f"近 3 年 {row['y3']:+.1f}%，排在同类前 {max(row.get('y3_rank_pct', 50), 1):.0f}%"}]
    cap_score = 50.0
    good = False
    if cap:
        cap_score = clip(50 + cap["edge"] * 100, 0, 100)
        good = cap["up"] >= 0.8 and cap["edge"] > 0.1
        down_text = (f"下跌的月份它跌了大盘的 {cap['down'] * 100:.0f}%" if cap["down"] > 0.05 else "下跌的月份它平均没有跟着跌")
        evidence.append({"label": "涨跌跟随", "status": "pass" if good else "warn",
                         "detail": f"近 {cap['months']} 个月里，沪深300 上涨的月份它跟上 {cap['up'] * 100:.0f}%，{down_text}"
                                   + ("" if cap["up"] >= 0.8 else "——涨的时候跟不上")})
    if m3.get("max_drawdown") is not None:
        evidence.append({"label": "最大回撤", "status": "pass" if m3["max_drawdown"] > -0.25 else "warn",
                         "detail": f"近 3 年最大回撤 {m3['max_drawdown'] * 100:.1f}%"})
    if managers:
        mgr = max(managers, key=lambda m: m.get("tenure_years") or 0)
        evidence.append({"label": "基金经理", "status": "pass" if tenure is None or tenure >= 3 else "warn",
                         "detail": f"{mgr.get('name', '')}" + (f"，任职 {tenure:.1f} 年" if tenure is not None else "")})
    if scale is not None:
        evidence.append({"label": "规模", "status": "pass" if scale <= 150 else "warn",
                         "detail": f"{scale:.1f} 亿" + ("，偏大，调仓不灵活" if scale > 150 else "")})
    hist = rolling_stats(nav, 250)
    if hist:
        text = (f"过去 {hist['years']} 年里任意一天买入、拿满一年：赚钱的概率 {hist['win_rate'] * 100:.0f}%，"
                f"中位 {hist['median'] * 100:+.1f}%（较差的一成情况 {hist['p10'] * 100:+.1f}%，较好的一成 {hist['p90'] * 100:+.1f}%）。"
                "基金的过去不代表未来，经理换人后尤其如此。")
        expected = {"available": True, "reliable": True, "kind": "history", "median": hist["median"], "low": hist["p10"],
                    "high": hist["p90"], "win_rate": hist["win_rate"], "text": text}
    else:
        expected = {"available": False, "text": "净值历史太短，给不出预期收益。"}
    score = round(0.4 * row["perf_score"] + 0.3 * report["scores"]["composite"] + 0.3 * cap_score, 1)
    dd = abs(m3["max_drawdown"]) * 100 if m3.get("max_drawdown") is not None else 25
    return {
        "key": f"OF:{row['code']}", "code": row["code"], "name": row["name"], "kind": "fund",
        "industry": row.get("type", ""), "price": row.get("nav"), "as_of": row.get("nav_date", ""), "score": score,
        "headline": ("涨的时候跟得上、跌的时候少亏" if good else "长期业绩靠前，经理稳定")
                    + f"，近 3 年 {row['y3']:+.0f}%",
        "evidence": evidence, "risks": ["主动基金靠的是基金经理，经理换人就要重新评估"],
        "plan": {
            "horizon": "3 年以上", "hold_max": None,
            "entry": "一次买入或分 3 个月买入都可以；持有不满 7 天卖出要交 1.5% 的惩罚性赎回费",
            "ref_price": row.get("nav"), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "position": "单只不超过总资金的两成", "fee": row.get("fee"),
            "rules": [
                "基金经理换人、规模跌破 2 亿、或者近 1 年业绩掉到同类后一半：重新评估，考虑换一只",
                f"从买入价下跌超过 {dd:.0f}%（它近 3 年最大的一次回撤）时停下来复查，不是一跌就卖",
                "赚到自己定的目标（比如年化 8%–10%）可以分批赎回",
            ],
            "expected": expected,
        },
    }, ""
