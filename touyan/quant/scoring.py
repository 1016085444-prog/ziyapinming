"""多维评分与五档评级。

口径（改评分逻辑时别破坏）：
- 每个维度从中性 50 分起，按信号加减，夹在 **5–95**。没有 0 分也没有满分——
  规则模型没资格说「绝对好」或「绝对差」。
- **每一分都有依据**：维度分 = 50 + 各条信号的加减，界面上逐条列出。
- 数据缺失的维度不参与加权（而不是按 50 分计入），并相应降低置信度。
- 五档评级沿用 TradingAgents 的 Buy / Overweight / Hold / Underweight / Sell，
  中文用国内研报惯例：买入 / 增持 / 持有 / 减持 / 卖出。
"""

from __future__ import annotations

from quant.technical import Signal

DIMENSION_LABELS = {
    "trend": "趋势",
    "momentum": "动量",
    "risk": "风险",
    "valuation": "估值",
    "quality": "质量",
    "growth": "成长",
    "performance": "业绩",
    "risk_control": "回撤控制",
    "efficiency": "性价比",
    "stability": "稳定性",
}

DIMENSION_HINTS = {
    "trend": "均线排列、长期趋势、MACD 位置",
    "momentum": "近期涨跌、MACD/KDJ 交叉、RSI、量价",
    "risk": "分数越高风险越低：波动、回撤、贝塔",
    "valuation": "市盈率、市净率、PEG（未做行业比较）",
    "quality": "ROE、毛利率、负债率、现金流",
    "growth": "营收与利润增速及其变化",
    "performance": "相对基准、同类排名、长期年化",
    "risk_control": "最大回撤、波动率",
    "efficiency": "夏普、卡玛：每份风险换来的收益",
    "stability": "基金经理任期、规模、持仓集中度",
}

WEIGHTS = {
    "stock": {"trend": 0.20, "momentum": 0.15, "risk": 0.15, "valuation": 0.20, "quality": 0.15, "growth": 0.15},
    "etf": {"trend": 0.30, "momentum": 0.25, "risk": 0.25, "stability": 0.20},
    "index": {"trend": 0.40, "momentum": 0.30, "risk": 0.30},
    "fund": {"performance": 0.30, "risk_control": 0.20, "efficiency": 0.25, "stability": 0.15, "trend": 0.10},
}

# (英文代码, 中文, 量化含义)
RATINGS = [
    ("Buy", "买入", "多数维度显著偏好，量化信号强"),
    ("Overweight", "增持", "整体偏好，正面因素多于负面"),
    ("Hold", "持有", "多空因素大致相当，信号中性"),
    ("Underweight", "减持", "负面因素占优，信号偏弱"),
    ("Sell", "卖出", "多数维度显著偏弱，量化信号差"),
]
RATING_LABELS = {code: label for code, label, _ in RATINGS}
_THRESHOLDS = [(68, "Buy"), (57, "Overweight"), (43, "Hold"), (32, "Underweight")]

SCORE_MIN, SCORE_MAX, NEUTRAL = 5.0, 95.0, 50.0


def rating_for(score: float) -> str:
    for floor, code in _THRESHOLDS:
        if score >= floor:
            return code
    return "Sell"


def score(kind: str, signals: list[Signal], bars_count: int, missing: list[str] | None = None) -> dict:
    weights = WEIGHTS.get(kind, WEIGHTS["index"])
    by_dim: dict[str, list[Signal]] = {}
    for s in signals:
        by_dim.setdefault(s.dimension, []).append(s)

    dimensions = []
    for key, weight in weights.items():
        sigs = by_dim.get(key, [])
        if not sigs:
            dimensions.append({"key": key, "label": DIMENSION_LABELS[key], "hint": DIMENSION_HINTS[key],
                               "score": None, "weight": weight, "evidence": []})
            continue
        raw = NEUTRAL + sum(s.impact for s in sigs)
        value = round(min(SCORE_MAX, max(SCORE_MIN, raw)), 1)
        dimensions.append({
            "key": key, "label": DIMENSION_LABELS[key], "hint": DIMENSION_HINTS[key],
            "score": value, "weight": weight,
            "evidence": [{"name": s.name, "value": s.value, "text": s.detail, "impact": s.impact}
                         for s in sorted(sigs, key=lambda x: -abs(x.impact))],
        })

    scored = [d for d in dimensions if d["score"] is not None]
    total_w = sum(d["weight"] for d in scored)
    composite = round(sum(d["score"] * d["weight"] for d in scored) / total_w, 1) if total_w else NEUTRAL
    code = rating_for(composite)

    coverage = total_w / sum(weights.values())
    if bars_count < 120 or coverage < 0.5:
        confidence = "低"
    elif coverage < 0.85 or missing:
        confidence = "中"
    else:
        confidence = "高"
    reasons = []
    if bars_count < 120:
        reasons.append(f"历史数据只有 {bars_count} 个交易日")
    for d in dimensions:
        if d["score"] is None:
            reasons.append(f"缺少{d['label']}维度的数据")
    reasons.extend(missing or [])

    meaning = next(m for c, _, m in RATINGS if c == code)
    pros = sorted((s for s in signals if s.impact > 0), key=lambda s: -s.impact)[:4]
    cons = sorted((s for s in signals if s.impact < 0), key=lambda s: s.impact)[:4]
    return {
        "dimensions": dimensions,
        "composite": composite,
        "rating": {"code": code, "label": RATING_LABELS[code], "meaning": meaning},
        "confidence": confidence,
        "confidence_reasons": reasons,
        "pros": [{"name": s.name, "text": s.detail, "impact": s.impact} for s in pros],
        "cons": [{"name": s.name, "text": s.detail, "impact": s.impact} for s in cons],
    }
