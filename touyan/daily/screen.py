"""股票初筛与决策仪表盘。

1. 全市场快照 → 硬条件（剔除 ST、成交太少、估值离谱、当天涨跌过大……）
2. 因子打分：估值 / 流动性 / 规模按全市场分位排名；动量 / 活跃度 / 稳定性 / 超跌反转按打分曲线
3. 初选的前几十只取 K 线：均线排列、乖离率、MACD、RSI、波动与回撤 → 技术信号分
4. 风险扣分 + 本项目量化体检的综合分 → 最终分；同一行业只留一只
5. 每只入选的股票生成「决策仪表盘」：一句话结论、检查清单、参考价位

打分曲线与技术信号分改编自 daily_stock_analysis 的 screening/scorer.py、daily.py（源自 AlphaSift，
Apache-2.0）；检查清单与「乖离率超过 5% 不追高」的纪律来自它的决策仪表盘提示词。
"""

from __future__ import annotations

import math
import re
from collections import Counter

from market.models import Bar
from quant import indicators as ind

from .strategies import profile as strategy_profile

ST_RE = re.compile(r"ST|退")
NEW_RE = re.compile(r"^[NC][一-鿿]")      # 上市首日 N、注册制前 5 日 C
INF = float("inf")


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ── 1. 硬条件 ─────────────────────────────────────────────────────

def _reject(r: dict, h: dict) -> str:
    name = r.get("name") or ""
    if ST_RE.search(name):
        return "ST / 退市风险"
    if NEW_RE.match(name):
        return "上市不足一周的新股"
    price = r.get("price")
    if price is None or price < h.get("price_min", 0) or price > h.get("price_max", INF):
        return "股价不在范围内"
    if (r.get("amount") or 0) < h.get("amount_min", 0):
        return "成交额太小"
    mv = r.get("total_mv")
    if h.get("mv_min") and (mv is None or mv < h["mv_min"]):
        return "市值偏小"
    if h.get("mv_max") and mv is not None and mv > h["mv_max"]:
        return "市值过大"
    for key, label in (("pe", "市盈率"), ("pb", "市净率")):
        if f"{key}_min" in h or f"{key}_max" in h:
            v = r.get(key)
            if v is None or v <= h.get(f"{key}_min", -INF) or v > h.get(f"{key}_max", INF):
                return f"{label}不在范围内（含亏损）" if key == "pe" else f"{label}不在范围内"
    change = r.get("change_pct")
    if change is None:
        return "缺少涨跌幅"
    if change < h.get("change_min", -INF):
        return "当天跌得太多"
    if change > h.get("change_max", INF):
        return "当天涨得太多（不追高）"
    if h.get("turnover_min") and (r.get("turnover") or 0) < h["turnover_min"]:
        return "换手太低"
    return ""


def hard_filter(rows: list[dict], hard: dict) -> tuple[list[dict], dict[str, int]]:
    kept, dropped = [], Counter()
    for r in rows:
        reason = _reject(r, hard)
        if reason:
            dropped[reason] += 1
        else:
            kept.append(r)
    return kept, dict(dropped.most_common())


# ── 2. 因子打分 ───────────────────────────────────────────────────

def pct_rank(values: list[float | None], higher_better: bool = True, na: float = 50.0) -> list[float]:
    """分位排名，0–100，并列取平均名次（与 pandas rank(pct=True) 一致）。"""
    valid = sorted(((v if higher_better else -v), i) for i, v in enumerate(values)
                   if v is not None and math.isfinite(v))
    out = [float(na)] * len(values)
    n = len(valid)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valid[j + 1][0] == valid[i][0]:
            j += 1
        pct = ((i + j) / 2 + 1) / n * 100
        for k in range(i, j + 1):
            out[valid[k][1]] = pct
        i = j + 1
    return out


def _positive_log(v):
    return math.log10(v) if v and v > 0 else None


def rank_factors(rows: list[dict]) -> None:
    """估值、流动性、规模是相对全市场的分位，只能在完整的候选池上算一次，结果存进 row["_rank"]。"""
    has_pe = any(r.get("pe") is not None for r in rows)
    has_pb = any(r.get("pb") is not None for r in rows)
    pe = pct_rank([r["pe"] if r.get("pe") is not None and 0 < r["pe"] < 500 else None for r in rows], False, 25)
    pb = pct_rank([r["pb"] if r.get("pb") is not None and 0 < r["pb"] < 50 else None for r in rows], False, 25)
    liq = pct_rank([_positive_log(r.get("amount")) for r in rows], True, 20)
    size = pct_rank([_positive_log(r.get("total_mv")) for r in rows], True, 35)
    for r, a, b, c, d in zip(rows, pe, pb, liq, size):
        value = 50.0
        if has_pe:
            value = value * 0.35 + a * 0.65
        if has_pb:
            value = value * 0.55 + b * 0.45
        r["_rank"] = {"value": clip(value, 0, 100), "liquidity": c, "size": d}


def factor_scores(r: dict, feats: dict | None, p: dict) -> dict[str, float]:
    f = dict(r["_rank"])
    feats = feats or {}
    change = r.get("change_pct") or 0.0
    c60 = feats.get("change_60d", r.get("change_60d"))
    signal, macd, rsi_status = feats.get("signal_score"), feats.get("macd_status"), feats.get("rsi_status")

    m = 50.0
    intraday = p["momentum_base"] + change * p["momentum_intraday_slope"]
    intraday -= max(change - p["momentum_chase_start_pct"], 0) * p["momentum_chase_penalty_slope"]
    intraday -= max(-change + p["momentum_downside_start_pct"], 0) * p["momentum_downside_penalty_slope"]
    m = m * 0.35 + clip(intraday, 5, 100) * 0.65
    if c60 is not None:
        t = p["momentum_60d_base"] + c60 * p["momentum_60d_slope"]
        t -= max(c60 - p["momentum_60d_overheat_pct"], 0) * p["momentum_60d_overheat_penalty_slope"]
        t -= max(-c60 + p["momentum_60d_breakdown_pct"], 0) * p["momentum_60d_breakdown_penalty_slope"]
        m = m * 0.60 + clip(t, 5, 100) * 0.40
    if signal is not None:
        m = m * 0.70 + clip(signal, 0, 100) * 0.30
    m += {"bullish": p["macd_bullish_bonus"], "bearish": -p["macd_bearish_penalty"]}.get(macd, 0)
    f["momentum"] = clip(m, 5, 100)

    rv = 100 - abs(change - p["reversal_ideal_change_pct"]) * p["reversal_distance_penalty_slope"]
    rv -= max(-change + p["reversal_collapse_start_pct"], 0) * p["reversal_collapse_penalty_slope"]
    rv -= max(change - p["reversal_chase_start_pct"], 0) * p["reversal_chase_penalty_slope"]
    rv += {"oversold": p["rsi_oversold_bonus"], "overbought": -p["rsi_overbought_penalty"]}.get(rsi_status, 0)
    if c60 is not None:
        rv -= max(c60 - 35, 0) * 0.5 + max(-c60 - 35, 0) * 0.8
    f["reversal"] = clip(rv, 5, 100)

    a = 50.0
    if "volume_ratio" in r:
        vr = r["volume_ratio"] if r["volume_ratio"] is not None else 1.0
        vs = 100 - abs(vr - p["activity_ideal_volume_ratio"]) * p["activity_volume_ratio_distance_slope"]
        vs -= max(vr - p["activity_high_volume_ratio"], 0) * p["activity_high_volume_ratio_penalty_slope"]
        a = a * 0.45 + clip(vs, 5, 100) * 0.55
    if "turnover" in r:
        to = r["turnover"] or 0.0
        ts = 100 - abs(to - p["activity_ideal_turnover_rate"]) * p["activity_turnover_distance_slope"]
        ts -= max(to - p["activity_high_turnover_rate"], 0) * p["activity_high_turnover_penalty_slope"]
        a = a * 0.55 + (clip(ts, 5, 100) if to > 0 else 40) * 0.45
    f["activity"] = clip(a, 0, 100)

    s = p["stability_base"] - min(abs(change), 10) * p["stability_change_abs_penalty_slope"]
    s -= max(change - p["stability_hot_change_pct"], 0) * p["stability_hot_change_penalty_slope"]
    s -= max((r.get("turnover") or 0) - p["stability_high_turnover_rate"], 0) * p["stability_high_turnover_penalty_slope"]
    s -= max((r.get("volume_ratio") or 1) - p["stability_high_volume_ratio"], 0) * p["stability_high_volume_ratio_penalty_slope"]
    if r.get("pe") is not None and r["pe"] <= 0:
        s -= p["stability_invalid_pe_penalty"]
    if signal is not None:
        s += (signal - 50) * 0.12
    if feats.get("volatility_20d") is not None:
        s -= max(feats["volatility_20d"] - p["stability_high_volatility_pct"], 0) * p["stability_high_volatility_penalty_slope"]
    if feats.get("drawdown_20d") is not None:
        s -= max(p["stability_max_drawdown_floor_pct"] - feats["drawdown_20d"], 0) * p["stability_drawdown_penalty_slope"]
    if feats.get("atr_pct") is not None:
        s -= max(feats["atr_pct"] - p["stability_high_atr_pct"], 0) * p["stability_high_atr_penalty_slope"]
    f["stability"] = clip(s, 0, 100)
    return {k: round(v, 1) for k, v in f.items()}


def weighted(factors: dict[str, float], weights: dict[str, float]) -> float:
    used = {k: w for k, w in weights.items() if k in factors and w > 0}
    total = sum(used.values())
    return round(sum(factors[k] * w for k, w in used.items()) / total, 1) if total else 50.0


def prescreen(rows: list[dict], strategy: dict) -> list[dict]:
    """在通过硬条件的股票上打快照分，按分数排好序返回。"""
    p = strategy_profile(strategy)
    rank_factors(rows)
    for r in rows:
        r["factors"] = factor_scores(r, None, p)
        r["screen_score"] = weighted(r["factors"], strategy["weights"])
    return sorted(rows, key=lambda r: -r["screen_score"])


# ── 3. K 线特征 ───────────────────────────────────────────────────

def signal_score(change_60d, ma_bullish: bool, above_ma20: bool, macd_status: str, rsi_status: str) -> float:
    score = 50.0 + (14 if ma_bullish else 0) + (10 if above_ma20 else 0)
    score += {"bullish": 12, "bearish": -12}.get(macd_status, 0)
    if change_60d is not None:
        if 0 <= change_60d <= 35:
            score += min(change_60d * 0.35, 12)
        elif change_60d > 60:
            score -= min((change_60d - 60) * 0.20, 12)
        elif change_60d < -25:
            score -= min(abs(change_60d + 25) * 0.25, 10)
    score += {"oversold": 4, "overbought": -6}.get(rsi_status, 0)
    return clip(score, 0, 100)


def daily_features(bars: list[Bar]) -> dict | None:
    if len(bars) < 60:
        return None
    closes = [b.close for b in bars]
    highs, lows, vols = [b.high for b in bars], [b.low for b in bars], [b.volume for b in bars]
    close = closes[-1]
    ma = {n: ind.sma(closes, n)[-1] for n in (5, 10, 20, 60)}
    dif, dea, _ = ind.macd(closes)
    macd_status = "neutral"
    if dif[-1] is not None and dea[-1] is not None:
        macd_status = "bullish" if dif[-1] > dea[-1] else "bearish" if dif[-1] < dea[-1] else "neutral"
    rsi = ind.rsi(closes)[-1]
    rsi_status = "oversold" if rsi is not None and rsi < 30 else "overbought" if rsi is not None and rsi > 70 else "neutral"
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes)) if closes[i - 1] > 0]
    vol20 = ind.stdev(rets) * math.sqrt(252) * 100 if len(rets) > 2 else None
    peak, dd = 0.0, 0.0
    for c in closes[-20:]:
        peak = max(peak, c)
        dd = min(dd, c / peak - 1)
    atr = ind.atr(highs, lows, closes)[-1]
    v5, v20 = sum(vols[-5:]) / 5, sum(vols[-20:]) / 20
    change_20d = (close / closes[-21] - 1) * 100
    change_60d = (close / closes[-61] - 1) * 100 if len(closes) > 60 else (close / closes[0] - 1) * 100
    ma_bullish = ma[5] >= ma[20] >= ma[60]
    above_ma20 = close >= ma[20]
    return {
        "close": close, "ma5": ma[5], "ma10": ma[10], "ma20": ma[20], "ma60": ma[60],
        "ma_aligned": ma[5] > ma[10] > ma[20],          # 检查清单口径：MA5 > MA10 > MA20
        "ma_bullish": ma_bullish,                       # 选股口径：MA5 ≥ MA20 ≥ MA60
        "above_ma20": above_ma20,
        "bias_ma5": (close / ma[5] - 1) * 100, "bias_ma10": (close / ma[10] - 1) * 100,
        "bias_ma20": (close / ma[20] - 1) * 100,
        "change_20d": change_20d, "change_60d": change_60d,
        "macd_status": macd_status, "rsi14": rsi, "rsi_status": rsi_status,
        "volatility_20d": vol20, "drawdown_20d": dd * 100,
        "atr": atr, "atr_pct": atr / close * 100 if atr else None,
        "vol_ratio_5_20": v5 / v20 if v20 > 0 else None,
        "signal_score": signal_score(change_60d, ma_bullish, above_ma20, macd_status, rsi_status),
    }


def daily_reject(feats: dict, daily: dict) -> str:
    if not daily:
        return ""
    if daily.get("require_ma_bullish") and not feats["ma_bullish"]:
        return "均线不是多头排列"
    if daily.get("require_above_ma20") and not feats["above_ma20"]:
        return "跌破 20 日线"
    if feats["signal_score"] < daily.get("signal_min", 0):
        return "技术信号偏弱"
    vr = feats.get("vol_ratio_5_20")
    if vr is not None and vr > daily.get("vol_ratio_20d_max", INF):
        return "没有缩量"
    if not daily.get("pullback_ma20_min", -INF) <= feats["bias_ma20"] <= daily.get("pullback_ma20_max", INF):
        return "离 20 日线太远"
    for key, field, label in (("volatility_20d_max", "volatility_20d", "波动太大"), ("atr_pct_max", "atr_pct", "振幅太大")):
        if feats.get(field) is not None and feats[field] > daily.get(key, INF):
            return label
    if feats["drawdown_20d"] < daily.get("drawdown_20d_min", -INF):
        return "近期回撤太深"
    return ""


# ── 4. 风险扣分与最终分 ───────────────────────────────────────────

def risk_penalty(r: dict, feats: dict, risk: dict) -> tuple[float, list[str]]:
    notes, pen = [], 0.0
    change = r.get("change_pct") or 0
    if change >= risk.get("chase_change_pct", INF):
        pen += 8
        notes.append(f"当天已涨 {change:.1f}%，有追高风险")
    if (r.get("volume_ratio") or 0) >= risk.get("abnormal_volume_ratio", INF):
        pen += 5
        notes.append(f"量比 {r['volume_ratio']:.1f}，成交异常放大")
    if (r.get("turnover") or 0) >= risk.get("high_turnover_rate", INF):
        pen += 4
        notes.append(f"换手率 {r['turnover']:.1f}%，筹码不稳")
    if feats["bias_ma5"] > 5:
        pen += 6
        notes.append(f"乖离率 {feats['bias_ma5']:.1f}% 超过 5%，不追高")
    if feats["signal_score"] < risk.get("weak_signal_score", 0):
        pen += 5
        notes.append("技术信号偏弱")
    if feats["rsi_status"] == "overbought":
        pen += 3
        notes.append(f"RSI {feats['rsi14']:.0f}，短线超买")
    if (feats.get("volatility_20d") or 0) > 60:
        pen += 3
        notes.append(f"近 20 日年化波动 {feats['volatility_20d']:.0f}%，波动很大")
    return min(pen, 20.0), notes


def final_score(screen: float, signal: float, quant: float | None, penalty: float) -> float:
    q = quant if quant is not None else 50.0
    return round(clip(0.45 * screen + 0.25 * signal + 0.30 * q - penalty, 0, 100), 1)


# 行业归到大类：同一大类只选一只。顺序有讲究——先匹配的先归类（「电网设备」归新能源而不是公用事业，
# 「航天航空」归军工而不是交通，「工程机械」归机械而不是基建）。思路来自 daily_stock_analysis 的组合分散规则。
BUCKETS = (
    ("金融", ("银行", "证券", "券商", "保险", "多元金融", "信托", "期货")),
    ("医药", ("医药", "医疗", "生物", "中药", "制药", "疫苗")),
    ("食品饮料", ("酿酒", "白酒", "啤酒", "食品", "饮料", "乳", "调味")),
    ("大消费", ("家电", "零售", "百货", "旅游", "酒店", "餐饮", "美容", "纺织", "服装", "家居")),
    ("半导体电子", ("半导体", "电子", "元件", "芯片", "光学")),
    ("新能源", ("电池", "光伏", "风电", "储能", "能源金属", "电网", "电源设备", "电机")),
    ("通信计算机", ("通信", "计算机", "软件", "互联网", "游戏", "传媒", "文化")),
    ("资源周期", ("钢铁", "煤炭", "有色", "金属", "石油", "化工", "化学", "化纤", "塑料", "橡胶", "建材", "水泥", "玻璃")),
    ("公用事业", ("电力", "燃气", "水务", "环保", "公用")),
    ("军工", ("航天", "军工", "船舶", "国防")),
    ("交通运输", ("航运", "港口", "航空", "机场", "铁路", "公路", "物流")),
    ("汽车", ("汽车", "零部件")),
    ("机械设备", ("机械", "设备", "仪器", "仪表")),
    ("地产基建", ("房地产", "建筑", "装修", "工程")),
    ("农业", ("农牧", "饲料", "养殖", "种植", "渔业", "农业")),
)


def guess_industry(name: str) -> str:
    """取不到行业时，从名字猜最常见的几类：银行、券商、保险的名字几乎都带这几个字。"""
    for word, industry in (("银行", "银行"), ("证券", "证券"), ("保险", "保险"), ("人寿", "保险")):
        if word in (name or ""):
            return industry
    return ""


def bucket_of(industry: str, name: str = "") -> str:
    industry = industry or guess_industry(name)
    for bucket, words in BUCKETS:
        if any(w in industry for w in words):
            return bucket
    return industry


def diversify(cands: list[dict], n: int) -> list[dict]:
    """按最终分取前 n 只，同一大类（金融、医药、新能源……）只留一只；凑不够再放宽。"""
    picked, seen = [], set()
    for c in cands:
        bucket = c.get("bucket") or bucket_of(c.get("industry") or "", c.get("name") or "")
        if bucket and bucket in seen:
            continue
        picked.append(c)
        if bucket:
            seen.add(bucket)
        if len(picked) == n:
            return picked
    for c in cands:
        if c not in picked:
            picked.append(c)
            if len(picked) == n:
                break
    return picked


# ── 5. 决策仪表盘 ─────────────────────────────────────────────────

def _price(x: float | None) -> float | None:
    if x is None:
        return None
    return round(x, 3 if x < 1 else 2)


def _mark(ok: bool | None) -> str:
    return "pass" if ok is True else "fail" if ok is False else "warn"


def _topic(text: str) -> str:
    m = re.match(r"[A-Za-z]+|[\u4e00-\u9fff]{2}", text)
    return m.group(0) if m else text[:2]


def _merge_notes(first: list[str], extra: list[str], limit: int = 4) -> list[str]:
    """合并两组风险提示，同一话题（RSI、乖离、换手……）只留先出现的那条。"""
    out, topics = [], set()
    for t in first + extra:
        key = _topic(t)
        if key in topics:
            continue
        topics.add(key)
        out.append(t)
    return out[:limit]


def dashboard(r: dict, feats: dict, report: dict | None, score: float, risk_notes: list[str],
              hold: dict | None = None) -> dict:
    close = feats["close"]
    bias = feats["bias_ma5"]
    checks = []

    def add(label: str, status: str, detail: str):
        checks.append({"label": label, "status": status, "detail": detail})

    ma5, ma10, ma20 = feats["ma5"], feats["ma10"], feats["ma20"]
    if feats["ma_aligned"]:
        add("多头排列", "pass", f"MA5 {_price(ma5)} > MA10 {_price(ma10)} > MA20 {_price(ma20)}")
    elif ma5 > ma20:
        add("多头排列", "warn", "短期均线在 20 日线上方，但还没完全排开")
    else:
        add("多头排列", "fail", "MA5 在 20 日线下方，趋势偏弱")
    if abs(bias) < 2:
        add("乖离率", "pass", f"距 MA5 {bias:+.1f}%，贴近均线，是较好的买点区")
    elif bias < 5:
        add("乖离率", "pass", f"距 MA5 {bias:+.1f}%，在 5% 以内")
    elif bias < 8:
        add("乖离率", "warn", f"距 MA5 {bias:+.1f}%，超过 5%，不追高")
    else:
        add("乖离率", "fail", f"距 MA5 {bias:+.1f}%，偏离过大，严禁追高")
    vr = feats.get("vol_ratio_5_20")
    if vr is None:
        add("量能", "warn", "没有成交量数据")
    elif vr > 2.5:
        add("量能", "warn", f"近 5 日成交是 20 日均量的 {vr:.1f} 倍，放量过猛")
    elif vr < 0.5:
        add("量能", "warn", f"近 5 日成交只有 20 日均量的 {vr:.1f} 倍，交投清淡")
    else:
        add("量能", "pass", f"近 5 日 / 20 日均量 {vr:.2f}，" + ("缩量回调，抛压不大" if vr < 0.9 else "量能正常"))
    add("站上 20 日线", _mark(feats["above_ma20"]),
        f"收盘 {_price(close)}，20 日线 {_price(ma20)}（{feats['bias_ma20']:+.1f}%）")
    macd = feats["macd_status"]
    add("MACD", {"bullish": "pass", "bearish": "fail"}.get(macd, "warn"),
        {"bullish": "DIF 在 DEA 上方", "bearish": "DIF 在 DEA 下方"}.get(macd, "方向不明"))
    rsi = feats.get("rsi14")
    if rsi is not None:
        add("RSI", "pass" if rsi < 70 else "warn" if rsi < 80 else "fail",
            f"RSI {rsi:.0f}" + ("" if rsi < 70 else "，短线超买" if rsi < 80 else "，严重超买"))
    pe = r.get("pe")
    if pe is None:
        add("估值", "warn", "没有市盈率数据")
    elif pe <= 0:
        add("估值", "fail", "亏损（市盈率为负）")
    else:
        add("估值", "pass" if pe <= 40 else "warn", f"市盈率 {pe:.1f}" + ("" if pe <= 40 else "，偏高"))
    composite = report["scores"]["composite"] if report else None
    if composite is not None:
        label = report["scores"]["rating"]["label"]
        add("量化体检", "pass" if composite >= 57 else "warn" if composite >= 43 else "fail",
            f"综合 {composite:.0f} 分（{label}）")

    fails = sum(1 for c in checks if c["status"] == "fail")
    atr = feats.get("atr") or close * 0.03
    entry = min(close, ma5) if bias > 0 else close
    ideal = _price(entry)
    second = _price(ma10 if ma10 < entry else ma20)
    # 止损：跌破 20 日线 3%，但离买点不超过 2.5 倍 ATR，免得一次止损亏太多
    stop = _price(min(max(min(ma20, entry) * 0.97, entry - 2.5 * atr), entry * 0.99))
    # 目标只看前高（波段高点、52 周高点），均线和布林上轨在上升趋势里算不上压力
    lv = (report or {}).get("levels", {})
    highs = [x["price"] for x in lv.get("resistances", []) if x.get("label", "").startswith("波段高点")]
    if lv.get("high_52w"):
        highs.append(lv["high_52w"])
    resist = sorted({x for x in highs if x > close * 1.01})
    target = next((t for t in resist if (t - entry) >= 1.5 * (entry - stop)), resist[-1] if resist else close + 3 * atr)
    # 持有期内够不着的目标没有意义：按近 20 日波动，最多算 1.5 倍「持有期内一个标准差」的涨幅
    hold = hold or {"min": 10, "max": 30, "label": "2–6 周"}
    if feats.get("volatility_20d"):
        reach = feats["volatility_20d"] / 100 / math.sqrt(252) * math.sqrt(hold["max"]) * 1.5
        target = min(target, entry * (1 + max(reach, 0.03)))
    target = _price(target)
    rr = round((target - entry) / (entry - stop), 1) if entry > stop else None
    room_ok = rr is None or rr >= 1.0
    if rr is not None:
        add("盈亏比", "pass" if rr >= 1.5 else "warn" if rr >= 1.0 else "fail",
            f"目标 {target} / 止损 {stop}，盈亏比 {rr}" + ("" if rr >= 1.0 else "，上方空间不够"))
        fails = sum(1 for c in checks if c["status"] == "fail")
    buyable = score >= 60 and bias < 5 and feats["above_ma20"] and fails <= 1 and room_ok

    if buyable:
        signal, label = "buy", "可以关注"
        one = (f"多头排列、乖离率 {bias:+.1f}%，{ideal} 附近可分批关注，跌破 {stop} 止损" if feats["ma_aligned"]
               else f"综合分 {score:.0f} 靠前，{ideal} 附近可分批关注，跌破 {stop} 止损")
        no_pos = f"在 {ideal}（MA5）到 {second} 之间分批买入，单只不超过两成仓位，跌破 {stop} 止损"
        has_pos = f"继续持有，{target} 附近可分批止盈，跌破 {stop} 离场"
    else:
        signal, label = "watch", "等待买点"
        if bias >= 5:
            one = f"走势不错但乖离率 {bias:+.1f}% 偏高，不追高，等回踩 {second} 附近"
        elif not room_ok:
            one = f"上方压力位 {target} 离得很近，盈亏比只有 {rr}，等回调或放量突破再看"
        elif not feats["above_ma20"]:
            one = f"综合分靠前但还在 20 日线下方，等站回 {_price(ma20)} 再考虑"
        else:
            weak = next((c["label"] for c in checks if c["status"] == "fail"), "部分条件未满足")
            one = f"综合分 {score:.0f}，但{weak}未达标，先观察"
        no_pos = f"先不买，等回踩 {second} 附近企稳、或乖离率回到 5% 以内再看"
        has_pos = f"持有观察，跌破 {stop} 减仓"

    plan = holding_plan(entry, target, stop, hold)
    return {
        "signal": signal, "signal_label": label, "one_sentence": one, "checklist": checks,
        "levels": {"ideal_buy": ideal, "secondary_buy": second, "stop_loss": stop, "target": target,
                   "reward_risk": rr},
        "plan": plan,
        "advice": {"no_position": no_pos, "has_position": has_pos},
        "risks": _merge_notes(risk_notes, [c["text"] for c in ((report or {}).get("scores", {}).get("cons") or [])[:3]]),
        "highlights": [c["text"] for c in ((report or {}).get("scores", {}).get("pros") or [])[:3]],
    }


def holding_plan(entry: float, target: float, stop: float, hold: dict) -> dict:
    """买了以后怎么办：什么时候止盈、止损、保本、到期卖。四条规则和「历史参照」回测用的完全一样。"""
    target_pct = (target / entry - 1) * 100
    stop_pct = (1 - stop / entry) * 100
    be_pct = round(target_pct / 2, 1)
    be_price = _price(entry * (1 + be_pct / 100))
    return {
        "entry": _price(entry), "target": target, "target_pct": round(target_pct, 1),
        "stop": stop, "stop_pct": round(stop_pct, 1), "breakeven_pct": be_pct,
        "hold_min": hold["min"], "hold_max": hold["max"], "hold_label": hold["label"],
        "rules": [
            f"止盈：涨到 {target}（+{target_pct:.1f}%）就卖",
            f"止损：收盘跌破 {stop}（−{stop_pct:.1f}%）就卖，不抱幻想",
            f"保本：涨过 {be_price}（+{be_pct:.1f}%）以后，止损提到买入价 {_price(entry)}，这笔不再亏钱",
            f"到期：持有满 {hold['max']} 个交易日（约 {hold['label']}）还没到目标，按收盘价卖出",
        ],
    }
