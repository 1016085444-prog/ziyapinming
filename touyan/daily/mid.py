"""中期（1–3 个月）· 悄悄走强

对手盘：还没注意到它的人。好消息不是一下子反映进股价的——研究的人少、不上热搜的股票，
要靠一批批资金慢慢发现、慢慢买进，表现出来就是不声不响地沿着一条斜线往上走。
等它连续涨停、上了热搜，后知后觉的人冲进来，这段行情也就差不多了。
所以买在「没人注意的稳步上涨」，卖在「大家都来了」。

研究里的依据：靠许多根小阳线慢慢涨上来的股票，之后更容易接着涨；靠一两根大阳线拉上来的，更容易跌回去
（人们对连续的小消息反应不足，对抓眼球的大消息反应过度）。A 股整体的「强者恒强」并不明显，
但在换手不高、没被炒作的股票里是有的。这里不用均线金叉、MACD 之类的指标，直接量四件事：
涨得稳不稳（走势贴不贴一条直线、上涨的天数占比）、强不强（比大盘多涨多少）、
冷不冷（成交有没有突然放大、有没有涨停）、有没有业绩撑着（最新财报的利润在增长）。
"""

from __future__ import annotations

import math

from . import sim
from .common import bucket_of, clip, diversify, pct, price
from .pool import Series

KEY, TITLE, NAME = "mid", "中期", "悄悄走强"
HORIZON = "1–3 个月"
W = 60                     # 看最近 60 个交易日（约三个月）的走势
WARMUP = 130
MAX_DAYS = 60
MAX_GAP = 0.03

STOCK_RULE = {"r_min": 0.08, "excess_min": 0.05, "r2_min": 0.60, "up_min": 0.53, "abn_max": 1.3, "gain_max": 0.07}
ETF_RULE = {"r_min": 0.04, "excess_min": 0.0, "r2_min": 0.50, "up_min": 0.50, "abn_max": 1.5, "gain_max": 0.06}

IDEA = ("找没人注意、却在稳步上涨、并且有业绩撑着的股票。好消息是被一批批资金慢慢发现的，"
        "股价会不声不响地沿着一条斜线走；等它涨停、放巨量、上热搜，就是该卖给后来者的时候。")
HOW = [
    "近 60 个交易日涨了 8% 以上，并且比沪深300 多涨 5 个百分点",
    "涨得稳：走势贴近一条向上的直线（拟合度 0.6 以上），上涨的天数超过 53%",
    "涨得冷：这 60 天没有涨停、没有单日涨 7% 以上，近 20 天成交量不超过半年均量的 1.3 倍",
    "最近 5 天没有急拉或急跌（±6% 以内），不在冲高的时候买",
    "最新一期财报的扣非净利润同比在增长（取不到财报的会标出来）",
]
ETF_HOW = [
    "同样的量法，门槛放宽：近 60 个交易日涨 4% 以上、不弱于沪深300、走势拟合度 0.5 以上",
    "一只都不合格时不硬选，建议拿国债 ETF 等着",
]

ETF_POOL = [
    ("510300", "沪深300ETF", "宽基"), ("510500", "中证500ETF", "宽基"), ("512100", "中证1000ETF", "宽基"),
    ("159915", "创业板ETF", "宽基"), ("588000", "科创50ETF", "宽基"), ("510880", "红利ETF", "红利"),
    ("512880", "证券ETF", "行业"), ("512800", "银行ETF", "行业"), ("512480", "半导体ETF", "行业"),
    ("159819", "人工智能ETF", "行业"), ("512010", "医药ETF", "行业"), ("512690", "酒ETF", "行业"),
    ("515030", "新能源车ETF", "行业"), ("512660", "军工ETF", "行业"),
    ("513100", "纳指ETF", "海外"), ("513500", "标普500ETF", "海外"), ("159920", "恒生ETF", "海外"),
    ("513180", "恒生科技ETF", "海外"), ("513050", "中概互联网ETF", "海外"), ("518880", "黄金ETF", "商品"),
]
SAFE_ETF = ("511010", "国债ETF", "防守")


def bench_returns(bench, k: int = W) -> dict[str, float]:
    closes = [b.adj_close for b in bench]
    return {bench[i].date: closes[i] / closes[i - k] - 1 for i in range(k, len(bench))}


def evaluate(s: Series, t: int, bench60: dict[str, float], rule: dict = STOCK_RULE) -> tuple[dict | None, str]:
    """返回 (特征, 没通过的原因)。涨幅不够的直接返回 (None, "")。"""
    if t < WARMUP:
        return None, ""
    r60 = s.ret(t, W)
    if r60 < rule["r_min"]:
        return None, ""
    excess = r60 - bench60.get(s.dates[t], 0.0)
    if excess < rule["excess_min"]:
        return None, "没有比大盘强多少"
    ups, downs = s.limit_days(t, W)
    if ups or downs:
        return None, "这段时间有过涨停或跌停，已经被注意到了"
    r5 = s.ret(t, 5)
    if abs(r5) > 0.06:
        return None, "最近 5 天急拉或急跌"
    up = s.up_ratio(t, W)
    if up < rule["up_min"]:
        return None, "上涨的天数不够多，是靠少数几天拉上来的"
    r2, slope = s.trend(t, W)
    if slope <= 0 or r2 < rule["r2_min"]:
        return None, "走势起伏大，不够稳"
    long_vol = s.avg_vol(t, 120)
    abn = s.avg_vol(t, 20) / long_vol if long_vol > 0 else 1.0
    if abn > rule["abn_max"]:
        return None, "成交量明显放大，已经热起来了"
    gain = s.max_gain(t, W)
    if gain > rule["gain_max"]:
        return None, "有过单日大涨，是靠少数几天拉上来的"
    var = (s.span(s.p_r2, t - W + 1, t) - s.span(s.p_r, t - W + 1, t) ** 2 / W) / (W - 1)
    sigma = math.sqrt(max(var, 0.0))
    if sigma > 0.03:
        return None, "波动太大"
    score = (r2 * 35 + clip((up - 0.5) / 0.15, 0, 1) * 15 + clip(excess / 0.25, 0, 1) * 20
             + clip((rule["abn_max"] - abn) / 0.6, 0, 1) * 15)
    return {"r60": r60, "excess": excess, "r2": r2, "up": up, "abn": abn, "gain": gain, "sigma": sigma, "r5": r5,
            "score": round(score, 1)}, ""


def plan(f: dict) -> dict:
    """跟踪止损：从买入后的最高收盘价回落「它一周正常波动的 2.6 倍」就卖，夹在 6%–12% 之间。"""
    trail = clip(2.6 * f["sigma"] * math.sqrt(5), 0.06, 0.12)
    return {"max_days": MAX_DAYS, "max_gap": MAX_GAP, "stop": trail, "trail": trail, "hot_exit": True}


def checkup(pool: list[Series], bench60: dict[str, float], regimes: dict[str, str], regime_now: str,
            rule: dict = STOCK_RULE, span_label: str = "一年半") -> dict:
    return sim.checkup(pool, lambda s, t: evaluate(s, t, bench60, rule)[0], plan, WARMUP, regimes, regime_now,
                       span_label)


def confirm(periods: list | None) -> tuple[bool | None, list[dict], float]:
    """最新财报撑不撑得住这段上涨。返回 (通过 / 不通过 / 不知道, 依据, 加分)。"""
    if not periods:
        return None, [{"label": "业绩", "status": "warn", "detail": "财报没有取到，没法确认上涨有没有业绩支撑"}], 0.0
    latest = periods[0]
    growth = latest.deduct_profit_yoy if latest.deduct_profit_yoy is not None else latest.net_profit_yoy
    name = latest.report_name or latest.report_date
    if growth is None:
        return None, [{"label": "业绩", "status": "warn", "detail": f"{name}没有利润增速数据"}], 0.0
    if growth <= 0:
        return False, [{"label": "业绩", "status": "fail", "detail": f"{name}扣非净利润同比 {growth:+.1f}%，上涨没有业绩支撑"}], 0.0
    evidence = [{"label": "业绩", "status": "pass", "detail": f"{name}扣非净利润同比 {growth:+.1f}%"}]
    bonus = 8.0
    prev = periods[1] if len(periods) > 1 else None
    prev_growth = None
    if prev is not None:
        prev_growth = prev.deduct_profit_yoy if prev.deduct_profit_yoy is not None else prev.net_profit_yoy
    if prev_growth is not None:
        slower = growth < prev_growth - 0.5
        trend = "增速在放慢" if slower else "增速在加快" if growth > prev_growth + 0.5 else "增速持平"
        evidence.append({"label": "增速变化", "status": "warn" if slower else "pass",
                         "detail": f"上一期 {prev_growth:+.1f}%，{trend}"})
        bonus += 0.0 if slower else 4.0
    if latest.ocf_per_share is not None:
        ok = latest.ocf_per_share > 0
        evidence.append({"label": "现金流", "status": "pass" if ok else "warn",
                         "detail": "经营现金流为正，利润不是纸面上的" if ok else "经营现金流为负，利润还没变成钱"})
        bonus += 3.0 if ok else 0.0
    return True, evidence, bonus


def build_pick(s: Series, f: dict, row: dict, report: dict, fin_evidence: list[dict], kind: str = "stock",
               key: str | None = None, group: str = "") -> dict:
    close = s.c[-1]
    p = plan(f)
    stop_price = price(close * (1 - p["trail"]))
    evidence = [
        {"label": "涨得稳", "status": "pass",
         "detail": f"近 {W} 个交易日 {f['r60'] * 100:+.1f}%，走势拟合度 {f['r2']:.2f}，{f['up'] * 100:.0f}% 的日子在涨"},
        {"label": "比大盘强", "status": "pass", "detail": f"比沪深300 多涨 {f['excess'] * 100:.1f} 个百分点"},
        {"label": "还没热", "status": "pass",
         "detail": f"没有涨停，单日最大涨幅 {f['gain'] * 100:.1f}%，近 20 天成交量是半年均量的 {f['abn']:.2f} 倍"},
    ] + fin_evidence
    return {
        "key": key or f"{s.market}:{s.code}", "code": s.code, "name": row.get("name") or s.name, "kind": kind,
        "industry": row.get("industry", "") or group, "price": price(close), "as_of": s.dates[-1], "score": f["score"],
        "headline": f"三个月稳步涨了 {f['r60'] * 100:.0f}%，没涨停、没放量，还没被注意到",
        "evidence": evidence,
        "risks": ["大盘转弱时，这类稳步上涨的股票也会被一起卖，跌破跟踪止损就走",
                  "下一期财报如果利润增速转负，不等止损价，直接卖"] if kind == "stock" else
                 ["行业 ETF 受政策和海外市场影响大，跌破跟踪止损就走"],
        "plan": {
            "horizon": HORIZON, "hold_max": MAX_DAYS,
            "entry": f"明天开盘后买入；开盘价高于 {price(close * (1 + MAX_GAP))}（比今天收盘高 3%）就等回落再买",
            "ref_price": price(close), "target_price": None, "target_pct": None,
            "stop_price": stop_price, "stop_pct": pct(p["trail"]),
            "position": "单只不超过总资金的 15%" if kind == "stock" else "单只不超过总资金的两成",
            "rules": [
                f"止损：先设在 {stop_price}（−{p['trail'] * 100:.1f}%）；股价涨上去以后，改成「从买入后的最高收盘价回落 "
                f"{p['trail'] * 100:.1f}%」就卖，让利润跟着涨、亏损有上限",
                "热了就走：已经赚了一成以上，又出现涨停或成交量突然放大到平时的 3 倍，第二天开盘卖——后知后觉的人来了",
                f"到期：最多拿 {MAX_DAYS} 个交易日（约三个月），到期卖出，重新评估",
                "不设固定的止盈价：这种走势涨多少不知道，用跟踪止损让它自己走完",
            ],
            "expected": sim.expected(report),
        },
    }


def select(pool: dict[str, Series], rows_by_code: dict[str, dict], bench60: dict[str, float], report: dict, n: int,
           financials=None, fill_industries=None) -> dict:
    """financials(rows) → {代码: 财报列表}，取不到的不在字典里。"""
    cands, reasons = [], {}
    for code, s in pool.items():
        f, why = evaluate(s, s.n - 1, bench60)
        if f is None:
            if why:
                reasons[why] = reasons.get(why, 0) + 1
            continue
        cands.append((s, f, rows_by_code.get(code, {})))
    cands.sort(key=lambda x: -x[1]["score"])
    short = cands[:max(n * 4, 12)]
    warning = fill_industries([c[2] for c in short]) if fill_industries and short else ""
    fin = financials([c[2] for c in short]) if financials and short else {}
    items = []
    for s, f, row in short:
        ok, evidence, bonus = confirm(fin.get(s.code))
        if ok is False:
            reasons["利润在下滑，上涨没有业绩支撑"] = reasons.get("利润在下滑，上涨没有业绩支撑", 0) + 1
            continue
        f = dict(f, score=round(f["score"] + bonus, 1))
        items.append({"s": s, "f": f, "row": row, "evidence": evidence, "name": row.get("name", ""),
                      "industry": row.get("industry", ""),
                      "bucket": bucket_of(row.get("industry", ""), row.get("name", ""))})
    items.sort(key=lambda c: -c["f"]["score"])
    picks = [build_pick(c["s"], c["f"], c["row"], report, c["evidence"]) for c in diversify(items, n)]
    return {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "checkup": report, "picks": picks,
        "funnel": {"pool": len(pool), "candidates": len(cands), "picked": len(picks),
                   "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))},
        "warnings": [warning] if warning else [],
    }


def select_etfs(series: dict[str, Series], meta: dict[str, tuple[str, str, str]], bench60: dict[str, float],
                report: dict, n: int = 3) -> dict:
    """meta: {代码: (key, 名称, 类别)}。返回 ETF 小节：入选的、全部的排名、体检。"""
    ranking, picks = [], []
    for code, s in series.items():
        key, name, group = meta[code]
        t = s.n - 1
        f, why = evaluate(s, t, bench60, ETF_RULE)
        r60 = s.ret(t, W) if t >= W else None
        r2 = s.trend(t, W)[0] if t >= W else None
        ranking.append({"key": key, "code": code, "name": name, "group": group, "price": price(s.c[-1]),
                        "r60": pct(r60), "excess": pct(r60 - bench60.get(s.dates[t], 0.0)) if r60 is not None else None,
                        "r2": round(r2, 2) if r2 is not None else None, "score": f["score"] if f else None,
                        "why_not": "" if f else (why or "涨幅不够")})
        if f:
            picks.append((f["score"], build_pick(s, f, {"name": name}, report, [], "etf", key, group)))
    ranking.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), -(r["r60"] or -999)))
    picks = [p for _, p in sorted(picks, key=lambda x: -x[0])[:n]]
    safe = None
    if len(picks) < n:
        safe = {"key": "SH:" + SAFE_ETF[0], "code": SAFE_ETF[0], "name": SAFE_ETF[1]}
    note = (f"有 {len(picks)} 只 ETF 在稳步走强" if picks else "没有一只 ETF 符合条件，不硬选") + \
           ("" if len(picks) >= n else "；空出来的仓位可以先放国债 ETF")
    return {"picks": picks, "ranking": ranking, "checkup": report, "how": ETF_HOW, "note": note, "safe": safe}
