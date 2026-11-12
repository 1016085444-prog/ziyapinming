"""场外基金与场内 ETF 的每日精选。

场外基金：看长期业绩，不追短期冠军。天天基金排行里先按近 3 年 / 2 年 / 1 年 / 6 个月的同类分位
打一个业绩分，剔除成立不满 3 年、有锁定期、A/C 重复份额的，前几名再取完整档案做量化体检
（规模、经理任期、最大回撤、夏普），两者合成最终分。

场内 ETF：一篮子覆盖宽基、行业、海外、商品的 ETF 做「双动量」轮动——相对动量排名，
绝对动量为正且站上 20 日线才入选；一个都不合格时转向国债 ETF 防守。
思路来自 daily_stock_analysis 的 ETF 轮动（规则化双动量）。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from market.models import Bar
from quant import indicators as ind

from .screen import pct_rank

# (键, 显示名, 天天基金类型, 选几只)
FUND_PLAN = [
    ("equity", "偏股基金", ("gp", "hh"), 2),
    ("index", "指数基金", ("zs",), 2),
    ("bond", "债券基金", ("zq",), 2),
    ("qdii", "QDII（海外）", ("qdii",), 1),
]
LOCKUP_RE = re.compile(r"持有|定开|封闭|定期开放|养老目标")
# 场外基金怎么拿：(建议持有多久, 用来算历史参照的持有交易日数)
FUND_HOLD = {"equity": ("至少 1 年，最好 3 年以上", 250), "index": ("至少 1 年", 250),
             "bond": ("至少半年", 125), "qdii": ("至少 1 年", 250)}
ACTIVE_TYPES = ("gp", "hh")


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


def fund_verdict(row: dict, report: dict | None) -> tuple[float | None, list[str], list[str]]:
    """体检后的最终分、亮点、扣分项。返回分数为 None 表示应剔除。"""
    pros, cons = [], []
    if row.get("y3") is not None:
        pros.append(f"近 3 年 {row['y3']:+.1f}%（同类前 {max(row.get('y3_rank_pct', 50), 1):.0f}%）")
    if not report:
        return None, pros, ["取不到基金档案，无法体检"]
    fund = report.get("fund") or {}
    profile = fund.get("profile") or {}
    scale = profile.get("scale")
    if scale is not None and scale < 2:
        return None, pros, [f"规模只有 {scale:.2f} 亿，有清盘风险"]
    managers = profile.get("managers") or []
    tenures = [m["tenure_years"] for m in managers if m.get("tenure_years") is not None]
    tenure = max(tenures) if tenures else None      # 与量化体检同口径：看任职最久的那位
    if row.get("ft") in ACTIVE_TYPES and tenure is not None and tenure < 2:
        return None, pros, [f"现任经理只管了 {tenure:.1f} 年，业绩未必是他的"]
    rating = report["scores"]["rating"]["code"]
    if rating in ("Underweight", "Sell"):
        return None, pros, [f"量化体检评级为{report['scores']['rating']['label']}"]
    m3 = (report.get("metrics") or {}).get("3y") or {}
    if m3.get("max_drawdown") is not None:
        (pros if m3["max_drawdown"] > -0.25 else cons).append(f"近 3 年最大回撤 {m3['max_drawdown'] * 100:.1f}%")
    if m3.get("sharpe") is not None:
        (pros if m3["sharpe"] >= 0.8 else cons).append(f"夏普 {m3['sharpe']:.2f}")
    if managers:
        mgr = max(managers, key=lambda m: m.get("tenure_years") or 0)
        text = f"经理 {mgr.get('name', '')}" + (f" 任职 {tenure:.1f} 年" if tenure is not None else "")
        (pros if tenure is None or tenure >= 3 else cons).append(text)
    if scale is not None:
        pros.append(f"规模 {scale:.1f} 亿")
    composite = report["scores"]["composite"]
    return round(0.55 * row["perf_score"] + 0.45 * composite, 1), pros, cons


# ── ETF 双动量 ────────────────────────────────────────────────────

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
ETF_RULES = [
    "每周看一次排名（这个页面每天都会更新）",
    "卖出：跌出动量前 3 名，或者不再满足「近 60 日上涨、站上 20 日线」，就换成新的前 3 名",
    "一只都不合格时，换成国债 ETF 防守，等有合格的再换回来",
]


def fund_plan(group_key: str, ft: str, max_drawdown_3y: float | None, history: dict | None) -> dict:
    label, horizon = FUND_HOLD.get(group_key, ("至少 1 年", 250))
    rules = [f"计划持有{label}，短期涨跌不用天天看；持有不满 7 天卖出要交 1.5% 的惩罚性赎回费",
             "基金经理换人、规模跌破 2 亿、或者近 1 年业绩掉到同类后一半，就重新评估、考虑换一只"]
    if group_key == "bond":
        rules.append("下跌超过 2% 时停下来复查：债券基金平时波动很小，跌这么多通常是出了问题")
    elif max_drawdown_3y is not None:
        rules.append(f"从买入价下跌超过 {abs(max_drawdown_3y) * 100:.0f}%（它近 3 年最大的一次回撤）时停下来复查，"
                     "不是一跌就卖")
    rules.append("赚到自己定的目标（比如年化 8%–10%）可以分批赎回，落袋为安")
    return {"hold_label": label, "horizon_days": horizon, "rules": rules, "history": history}


def _ret(closes: list[float], n: int) -> float | None:
    return (closes[-1] / closes[-1 - n] - 1) * 100 if len(closes) > n and closes[-1 - n] > 0 else None


def etf_momentum(bars: list[Bar]) -> dict | None:
    closes = [b.adj_close for b in bars]
    if len(closes) < 130:
        return None
    r20, r60, r120 = _ret(closes, 20), _ret(closes, 60), _ret(closes, 120)
    ma20 = ind.sma(closes, 20)[-1]
    peak, dd = 0.0, 0.0
    for c in closes[-120:]:
        peak = max(peak, c)
        dd = min(dd, c / peak - 1)
    return {"r20": r20, "r60": r60, "r120": r120, "above_ma20": closes[-1] >= ma20,
            "drawdown_120d": dd * 100, "score": round(0.5 * r60 + 0.3 * r20 + 0.2 * r120, 2),
            "eligible": r60 > 0 and closes[-1] >= ma20}


def etf_picks(rows: list[dict], n: int = 3) -> tuple[list[dict], str]:
    """rows: 每只含 momentum。返回 (入选, 说明)。"""
    ranked = sorted((r for r in rows if r.get("momentum")), key=lambda r: -r["momentum"]["score"])
    good = [r for r in ranked if r["momentum"]["eligible"]][:n]
    if len(good) == n:
        note = f"动量前 {n} 名且都站上 20 日线、近 60 日上涨，等权配置"
    elif good:
        note = f"只有 {len(good)} 只同时满足近 60 日上涨、站上 20 日线，其余仓位建议放国债 ETF 防守"
    else:
        note = "没有一只同时满足近 60 日上涨、站上 20 日线，市场偏弱，建议以国债 ETF 防守为主"
    return good, note
