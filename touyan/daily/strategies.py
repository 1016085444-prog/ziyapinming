"""选股风格。参数改编自 daily_stock_analysis 的 balanced_alpha / quality_value / shrink_pullback 策略
（其参数源自 AlphaSift，Apache-2.0）。

hard: 全市场快照上的硬条件；daily: 取到 K 线后的硬条件；weights: 因子权重；
profile: 打分曲线参数；risk: 风险扣分阈值。金额单位元，涨跌幅单位 %。
"""

from __future__ import annotations

STRATEGIES: dict[str, dict] = {
    "balanced": {
        "label": "均衡多因子",
        "desc": "估值、资金、动量、稳定性都不差的股票，不追求单项极端突出",
        "hard": {"amount_min": 1e8, "mv_min": 5e9, "pe_min": 0, "pe_max": 80, "pb_min": 0, "pb_max": 8,
                 "change_min": -4.0, "change_max": 8.5, "price_min": 3, "price_max": 220},
        "daily": {},
        "weights": {"value": 0.22, "liquidity": 0.18, "momentum": 0.20, "activity": 0.15, "stability": 0.12,
                    "reversal": 0.05, "size": 0.03},
        "profile": {"momentum_chase_start_pct": 5.5, "momentum_chase_penalty_slope": 12.0,
                    "activity_ideal_volume_ratio": 2.0, "activity_ideal_turnover_rate": 4.0,
                    "stability_hot_change_pct": 7.0},
        "risk": {"chase_change_pct": 8.0, "abnormal_volume_ratio": 6.0, "high_turnover_rate": 15.0},
        "hold": {"min": 10, "max": 30, "label": "2–6 周"},   # 持有期（交易日）
        "pool": 30,
    },
    "value": {
        "label": "稳健价值",
        "desc": "估值合理、成交充足、走势不过热的大中盘股，偏防守",
        "hard": {"amount_min": 8e7, "mv_min": 1e10, "mv_max": 8e11, "pe_min": 0, "pe_max": 25, "pb_min": 0, "pb_max": 4,
                 "change_min": -3.5, "change_max": 5.0, "price_min": 3, "price_max": 180},
        "daily": {},
        "weights": {"value": 0.32, "stability": 0.24, "liquidity": 0.18, "momentum": 0.08, "activity": 0.08,
                    "reversal": 0.04, "size": 0.06},
        "profile": {"momentum_chase_start_pct": 3.0, "momentum_chase_penalty_slope": 16.0,
                    "activity_ideal_volume_ratio": 1.4, "activity_ideal_turnover_rate": 2.5,
                    "stability_hot_change_pct": 4.5, "stability_high_turnover_rate": 8.0,
                    "stability_high_volume_ratio": 4.0},
        "risk": {"chase_change_pct": 5.5, "abnormal_volume_ratio": 4.5, "high_turnover_rate": 10.0},
        "hold": {"min": 20, "max": 60, "label": "1–3 个月"},
        "pool": 30,
    },
    "trend": {
        "label": "趋势回踩",
        "desc": "上升趋势中缩量回踩均线、趋势没有走坏的股票，找顺势的买点",
        "hard": {"amount_min": 8e7, "turnover_min": 1.0, "price_min": 3, "change_min": -5.0, "change_max": 6.0},
        "daily": {"require_ma_bullish": True, "require_above_ma20": True, "signal_min": 65,
                  "vol_ratio_20d_max": 1.5, "pullback_ma20_min": -2.0, "pullback_ma20_max": 8.0,
                  "volatility_20d_max": 45.0, "drawdown_20d_min": -12.0, "atr_pct_max": 6.5},
        "weights": {"momentum": 0.32, "stability": 0.22, "activity": 0.18, "liquidity": 0.15, "value": 0.08,
                    "reversal": 0.05},
        "profile": {"momentum_60d_overheat_pct": 35.0, "momentum_chase_start_pct": 5.0,
                    "momentum_chase_penalty_slope": 14.0, "activity_ideal_volume_ratio": 1.0,
                    "activity_ideal_turnover_rate": 2.5, "activity_high_volume_ratio": 4.5,
                    "stability_hot_change_pct": 5.5, "stability_high_volatility_pct": 40.0,
                    "stability_max_drawdown_floor_pct": -10.0, "stability_high_atr_pct": 5.5},
        "risk": {"chase_change_pct": 6.5, "abnormal_volume_ratio": 4.5, "high_turnover_rate": 12.0,
                 "weak_signal_score": 60.0},
        "hold": {"min": 5, "max": 15, "label": "1–3 周"},
        "pool": 45,                    # 日 K 条件会刷掉一大半，初选多留一些
    },
}

DEFAULT_STRATEGY = "balanced"

PROFILE_DEFAULTS = {
    "momentum_base": 60.0, "momentum_intraday_slope": 5.0, "momentum_chase_start_pct": 5.0,
    "momentum_chase_penalty_slope": 10.0, "momentum_downside_start_pct": -2.0, "momentum_downside_penalty_slope": 3.0,
    "momentum_60d_base": 55.0, "momentum_60d_slope": 0.9, "momentum_60d_overheat_pct": 45.0,
    "momentum_60d_overheat_penalty_slope": 0.8, "momentum_60d_breakdown_pct": -20.0,
    "momentum_60d_breakdown_penalty_slope": 0.7, "macd_bullish_bonus": 6.0, "macd_bearish_penalty": 8.0,
    "reversal_ideal_change_pct": -3.0, "reversal_distance_penalty_slope": 13.0, "reversal_collapse_start_pct": -8.0,
    "reversal_collapse_penalty_slope": 10.0, "reversal_chase_start_pct": 1.0, "reversal_chase_penalty_slope": 8.0,
    "rsi_oversold_bonus": 10.0, "rsi_overbought_penalty": 14.0,
    "activity_ideal_volume_ratio": 2.0, "activity_volume_ratio_distance_slope": 15.0, "activity_high_volume_ratio": 5.0,
    "activity_high_volume_ratio_penalty_slope": 8.0, "activity_ideal_turnover_rate": 4.0,
    "activity_turnover_distance_slope": 8.0, "activity_high_turnover_rate": 12.0,
    "activity_high_turnover_penalty_slope": 5.0,
    "stability_base": 78.0, "stability_change_abs_penalty_slope": 3.0, "stability_hot_change_pct": 7.0,
    "stability_hot_change_penalty_slope": 5.0, "stability_high_turnover_rate": 10.0,
    "stability_high_turnover_penalty_slope": 2.0, "stability_high_volume_ratio": 5.0,
    "stability_high_volume_ratio_penalty_slope": 4.0, "stability_invalid_pe_penalty": 18.0,
    "stability_high_volatility_pct": 45.0, "stability_high_volatility_penalty_slope": 0.45,
    "stability_max_drawdown_floor_pct": -12.0, "stability_drawdown_penalty_slope": 1.2,
    "stability_high_atr_pct": 6.0, "stability_high_atr_penalty_slope": 2.0,
}

FACTOR_LABELS = {"value": "估值", "liquidity": "流动性", "momentum": "动量", "reversal": "超跌反转",
                 "activity": "活跃度", "stability": "稳定性", "size": "规模"}


def get(key: str | None) -> tuple[str, dict]:
    key = key if key in STRATEGIES else DEFAULT_STRATEGY
    return key, STRATEGIES[key]


def profile(strategy: dict) -> dict:
    p = dict(PROFILE_DEFAULTS)
    p.update(strategy.get("profile") or {})
    return p


def public() -> list[dict]:
    return [{"key": k, "label": s["label"], "desc": s["desc"]} for k, s in STRATEGIES.items()]
