"""短期（3–8 个交易日）· 错杀反弹

对手盘：急着卖的人——止损盘、被动减仓、恐慌盘。他们不在乎价格，只要马上卖掉，
于是把价格压到合理水平以下；等他们卖完，价格会往回走一段。我们接他们的货，赚这段回程。
学术上叫「短期反转」，是给愿意在别人急卖时接盘的人的补偿，在散户多、波动大的市场里更明显。

难点是分清「被砸下来的」和「真出事了的」。日线上能看到的线索：
- 坏消息多在收盘后公布，第二天直接低开；被动抛售则是盘中一路卖下来。
  所以把这几天的跌幅拆成「隔夜跳空」和「盘中下跌」，盘中跌出来的占大头才要。
- 跌幅要拿它自己平时的波动来量：平时一天动 1% 的股票 5 天跌 6% 很反常，平时一天动 4% 的就不算什么。
- 跌停说明想卖的人还没卖完，不接；近期涨停过的是被炒过的，不碰。
- 大方向没坏：半年来没怎么跌。一路阴跌的股票，反弹多半只是下跌途中歇口气。
"""

from __future__ import annotations

import math

from . import sim
from .common import bucket_of, clip, diversify, pct, price
from .pool import Series

KEY, TITLE, NAME = "short", "短期", "错杀反弹"
HORIZON = "3–8 个交易日"
K = 5                      # 看最近 5 个交易日的下跌
WARMUP = 130
MAX_DAYS = 8
MAX_GAP = 0.02

IDEA = ("找被急着卖的人砸下来、而公司本身没出事的股票，赚一段反弹。止损盘、被动减仓的人不在乎价格，"
        "会把股价压到合理水平以下，等他们卖完，价格会往回走一段。")
HOW = [
    "5 天跌幅至少 4%，并且是它自己平时 5 天波动的 1.6 倍以上（跌得反常）",
    "跌幅的六成以上是盘中跌出来的，没有 3% 以上的低开（坏消息通常表现为跳空低开）",
    "近 10 天没有涨停或跌停（跌停说明还没卖完；涨停过的是被炒过的）",
    "近半年跌幅不超过 15%（大方向没坏），公司在盈利，市值在全市场前 300",
]


def evaluate(s: Series, t: int) -> tuple[dict | None, str]:
    """返回 (特征, 没通过的原因)。跌得不够深的直接返回 (None, "")。"""
    if t < WARMUP:
        return None, ""
    drop = s.ret(t, K)
    if drop > -0.04:
        return None, ""
    sig = s.sigma(t)
    if not sig:
        return None, ""
    z = drop / (sig * math.sqrt(K))
    if z > -1.6:
        return None, "跌幅对它来说不算反常"
    ups, downs = s.limit_days(t, 10)
    if downs:
        return None, "近 10 天有跌停，卖盘可能还没完"
    if ups:
        return None, "近 10 天涨停过，是被炒过的"
    share = s.intraday_share(t, K)
    gap = s.worst_gap(t, K)
    if gap < -0.03:
        return None, "有 3% 以上的低开，可能是出了坏消息"
    if share is None or share < 0.6:
        return None, "跌幅主要来自隔夜低开，不是盘中卖出来的"
    r120 = s.ret(t, 120)
    if r120 < -0.15:
        return None, "近半年一直在跌，大方向不好"
    clv = s.clv(t)
    score = (min(-z, 3.2) * 18 + clip((share - 0.6) / 0.4, 0, 1) * 14 + clv * 12
             + clip((r120 + 0.15) / 0.45, 0, 1) * 16)
    return {"drop": drop, "z": z, "share": min(share, 1.5), "gap": gap, "r120": r120, "clv": clv,
            "score": round(score, 1)}, ""


def signal(s: Series, t: int) -> dict | None:
    return evaluate(s, t)[0]


def plan(f: dict) -> dict:
    """止盈：收复这轮跌幅的一半。止损：再跌掉这轮跌幅的四分之三，说明不是错杀。"""
    drop = -f["drop"]
    return {"max_days": MAX_DAYS, "max_gap": MAX_GAP,
            "target": clip(0.5 * drop / (1 - drop), 0.03, 0.10), "stop": clip(0.75 * drop, 0.04, 0.08)}


def checkup(pool: list[Series], regimes: dict[str, str], regime_now: str) -> dict:
    return sim.checkup(pool, signal, plan, WARMUP, regimes, regime_now)


def build_pick(s: Series, f: dict, row: dict, report: dict, regime_now: str) -> dict:
    close = s.c[-1]
    p = plan(f)
    tp, sp = price(close * (1 + p["target"])), price(close * (1 - p["stop"]))
    pe = row.get("pe")
    evidence = [
        {"label": "跌得反常", "status": "pass",
         "detail": f"{K} 天跌了 {-f['drop'] * 100:.1f}%，是它平时 {K} 天波动的 {-f['z']:.1f} 倍"},
        {"label": "怎么跌的", "status": "pass",
         "detail": f"{min(f['share'], 1) * 100:.0f}% 是盘中跌出来的，"
                   + (f"最大的一次低开只有 {-f['gap'] * 100:.1f}%" if f["gap"] < -0.002 else "这几天没有低开")},
        {"label": "今天收盘", "status": "pass" if f["clv"] >= 0.5 else "warn",
         "detail": f"收在当天最低到最高之间 {f['clv'] * 100:.0f}% 的位置，"
                   + ("下方有人接" if f["clv"] >= 0.5 else "还没看到明显的承接")},
        {"label": "大方向", "status": "pass" if f["r120"] >= 0 else "warn", "detail": f"近半年 {f['r120'] * 100:+.1f}%"},
        {"label": "公司盈利", "status": "pass" if pe and pe > 0 else "warn",
         "detail": f"市盈率 {pe:.0f} 倍，在赚钱" if pe and pe > 0 else "没有取到市盈率"},
    ]
    risks = []
    if f["clv"] < 0.3:
        risks.append("今天收在最低附近，卖盘可能还没完，可以等一天、看到止跌再买")
    if regime_now == "偏弱":
        risks.append("市场偏弱时反弹容易半途而废，仓位减半")
    risks.append("如果买入后出了利空公告，不等止损价，直接卖")
    return {
        "key": f"{s.market}:{s.code}", "code": s.code, "name": row.get("name") or s.name, "kind": "stock",
        "industry": row.get("industry", ""), "price": price(close), "as_of": s.dates[-1], "score": f["score"],
        "headline": f"{K} 天被卖下来 {-f['drop'] * 100:.1f}%，没有坏消息的迹象，博一个收复半程的反弹",
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": MAX_DAYS,
            "entry": f"明天开盘后买入；开盘价高于 {price(close * (1 + MAX_GAP))}（比今天收盘高 2%）就放弃，不追",
            "ref_price": price(close), "target_price": tp, "target_pct": pct(p["target"]),
            "stop_price": sp, "stop_pct": pct(p["stop"]),
            "position": "单只不超过总资金的一成",
            "rules": [
                f"止盈：涨到 {tp}（+{p['target'] * 100:.1f}%，收复这轮跌幅的一半）就卖，买入后可以直接挂好卖单",
                f"止损：收盘跌破 {sp}（−{p['stop'] * 100:.1f}%）就卖——说明它不是被错杀，是真有问题",
                f"到期：买入后第 {MAX_DAYS} 个交易日收盘还没到目标，卖出，不恋战",
                "买入当天不能卖（T+1），所以宁可错过也不要追高",
            ],
            "expected": sim.expected(report),
        },
    }


def select(pool: dict[str, Series], rows_by_code: dict[str, dict], report: dict, regime_now: str, n: int,
           fill_industries=None) -> dict:
    """今天的入选和没入选的原因。"""
    cands, reasons = [], {}
    for code, s in pool.items():
        f, why = evaluate(s, s.n - 1)
        row = rows_by_code.get(code, {})
        if f is None:
            if why:
                reasons[why] = reasons.get(why, 0) + 1
            continue
        pe = row.get("pe")
        if pe is not None and pe <= 0:
            reasons["公司在亏损"] = reasons.get("公司在亏损", 0) + 1
            continue
        cands.append((s, f, row))
    cands.sort(key=lambda x: -x[1]["score"])
    warning = fill_industries([c[2] for c in cands[:n * 4]]) if fill_industries and cands else ""
    items = [{"s": s, "f": f, "row": row, "name": row.get("name", ""), "industry": row.get("industry", ""),
              "bucket": bucket_of(row.get("industry", ""), row.get("name", ""))} for s, f, row in cands[:n * 4]]
    picks = [build_pick(c["s"], c["f"], c["row"], report, regime_now) for c in diversify(items, n)]
    return {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "checkup": report, "picks": picks,
        "funnel": {"pool": len(pool), "candidates": len(cands), "picked": len(picks),
                   "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))},
        "warnings": [warning] if warning else [],
    }
