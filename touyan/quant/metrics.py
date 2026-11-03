"""收益与风险指标。全部基于复权价（Bar.adj_close），分红不会被算成亏损。

几条口径约定：
- 区间收益按**自然日**回看（近 1 月 = 30 天前那天的收盘），历史不够长就给 None，
  不拿「成立以来」冒充「近一年」。
- 年化系数用数据自己的交易日频率（最近一年有多少根 K 线），A 股约 242、美股约 252、
  加密货币 365，比写死 252 更准。
- 不足 3 个月的收益不年化——把两周的涨幅年化成几百个百分点没有意义。
- 夏普 / 索提诺用日超额收益（扣除无风险利率），无风险利率默认 2%，可在设置里改。
"""

from __future__ import annotations

import bisect
import math
from datetime import date, timedelta

from market.models import Bar
from quant.indicators import stdev

WINDOWS = {"1y": 365, "3y": 1095, "all": None}
WINDOW_LABELS = {"1y": "近1年", "3y": "近3年", "all": "全部数据"}


def _d(text: str) -> date:
    return date.fromisoformat(text[:10])


def bar_on_or_before(bars: list[Bar], target: date) -> Bar | None:
    """最后一根日期 ≤ target 的 K 线；target 早于全部数据时返回 None。"""
    dates = [b.date[:10] for b in bars]
    i = bisect.bisect_right(dates, target.isoformat()) - 1
    return bars[i] if i >= 0 else None


def periods_per_year(bars: list[Bar]) -> float:
    if len(bars) < 2:
        return 252.0
    end = _d(bars[-1].date)
    span = (end - _d(bars[0].date)).days
    if span >= 365:
        cutoff = (end - timedelta(days=365)).isoformat()
        count = sum(1 for b in bars if b.date > cutoff)
    else:
        count = (len(bars) - 1) / max(span, 1) * 365
    return float(min(365, max(200, count)))


def period_returns(bars: list[Bar]) -> dict[str, float | None]:
    if not bars:
        return {}
    last = bars[-1]
    end = _d(last.date)
    out: dict[str, float | None] = {}
    for key, days in (("1w", 7), ("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365), ("3y", 1095), ("5y", 1826)):
        start = bar_on_or_before(bars, end - timedelta(days=days))
        out[key] = (last.adj_close / start.adj_close - 1) if start is not None and start is not last else None
    prev_year_end = bar_on_or_before(bars, date(end.year - 1, 12, 31))
    out["ytd"] = (last.adj_close / prev_year_end.adj_close - 1) if prev_year_end is not None else None
    out["all"] = last.adj_close / bars[0].adj_close - 1
    return out


def drawdown(bars: list[Bar]) -> dict:
    """最大回撤及其起止、修复日期，以及当前距最高点的回撤。"""
    if len(bars) < 2:
        return {}
    peak, peak_i = bars[0].adj_close, 0
    mdd, mdd_peak_i, mdd_trough_i = 0.0, 0, 0
    for i, b in enumerate(bars):
        p = b.adj_close
        if p > peak:
            peak, peak_i = p, i
        dd = p / peak - 1
        if dd < mdd:
            mdd, mdd_peak_i, mdd_trough_i = dd, peak_i, i
    recover = None
    target = bars[mdd_peak_i].adj_close
    for j in range(mdd_trough_i + 1, len(bars)):
        if bars[j].adj_close >= target:
            recover = bars[j].date
            break
    high = max(b.adj_close for b in bars)
    return {
        "max_drawdown": mdd,
        "peak_date": bars[mdd_peak_i].date,
        "trough_date": bars[mdd_trough_i].date,
        "recover_date": recover,
        "current_drawdown": bars[-1].adj_close / high - 1,
    }


def drawdown_series(bars: list[Bar]) -> list[float]:
    out, peak = [], 0.0
    for b in bars:
        peak = max(peak, b.adj_close)
        out.append(b.adj_close / peak - 1 if peak else 0.0)
    return out


def percentile(values: list[float], pct: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def risk_metrics(bars: list[Bar], rf: float = 0.02, ppy: float | None = None) -> dict:
    """一个区间内的收益风险指标。不足 20 个交易日返回空 dict。"""
    if len(bars) < 21:
        return {}
    ppy = ppy or periods_per_year(bars)
    prices = [b.adj_close for b in bars]
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    n = len(rets)
    sd = stdev(rets)
    years = (_d(bars[-1].date) - _d(bars[0].date)).days / 365.25
    total = prices[-1] / prices[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years >= 0.25 and total > -1 else None
    rf_d = (1 + rf) ** (1 / ppy) - 1
    excess = [r - rf_d for r in rets]
    downside = math.sqrt(sum(min(0.0, e) ** 2 for e in excess) / n)
    dd = drawdown(bars)
    mdd = dd.get("max_drawdown", 0.0)
    return {
        "start": bars[0].date,
        "end": bars[-1].date,
        "days": n,
        "total_return": total,
        "cagr": cagr,
        "volatility": sd * math.sqrt(ppy),
        "sharpe": _mean(excess) / sd * math.sqrt(ppy) if sd > 0 else None,
        "sortino": _mean(excess) / downside * math.sqrt(ppy) if downside > 0 else None,
        "max_drawdown": mdd,
        "drawdown_peak": dd.get("peak_date"),
        "drawdown_trough": dd.get("trough_date"),
        "drawdown_recover": dd.get("recover_date"),
        "calmar": cagr / abs(mdd) if cagr is not None and mdd < 0 else None,
        "var95": -percentile(rets, 5),
        "win_rate": sum(1 for r in rets if r > 0) / n,
        "best_day": max(rets),
        "worst_day": min(rets),
    }


def relative_metrics(bars: list[Bar], bench: list[Bar], rf: float = 0.02, ppy: float | None = None) -> dict:
    """相对基准：贝塔、相关系数、年化阿尔法、超额收益、跟踪误差、信息比率。按交易日对齐。"""
    if not bench:
        return {}
    ppy = ppy or periods_per_year(bars)
    bmap = {b.date[:10]: b.adj_close for b in bench}
    pairs: list[tuple[float, float]] = []
    prev = None
    for b in bars:
        m = bmap.get(b.date[:10])
        if m is None:
            continue
        if prev is not None:
            pairs.append((b.adj_close / prev[0] - 1, m / prev[1] - 1))
        prev = (b.adj_close, m)
    if len(pairs) < 20:
        return {}
    r = [p[0] for p in pairs]
    mk = [p[1] for p in pairs]
    mr, mm = _mean(r), _mean(mk)
    n = len(pairs)
    cov = sum((x - mr) * (y - mm) for x, y in pairs) / (n - 1)
    var_m = sum((y - mm) ** 2 for y in mk) / (n - 1)
    sd_r, sd_m = stdev(r), stdev(mk)
    rf_d = (1 + rf) ** (1 / ppy) - 1
    beta = cov / var_m if var_m > 0 else None
    diff = [x - y for x, y in pairs]
    te = stdev(diff) * math.sqrt(ppy)
    total_r = math.prod(1 + x for x in r) - 1
    total_m = math.prod(1 + y for y in mk) - 1
    return {
        "beta": beta,
        "correlation": cov / (sd_r * sd_m) if sd_r > 0 and sd_m > 0 else None,
        "alpha": (mr - rf_d - beta * (mm - rf_d)) * ppy if beta is not None else None,
        "benchmark_return": total_m,
        "excess_return": total_r - total_m,
        "tracking_error": te,
        "information_ratio": _mean(diff) * ppy / te if te > 0 else None,
    }


def windowed(bars: list[Bar], days: int | None) -> list[Bar]:
    """最近 days 个自然日的 K 线，起点是窗口开始那天（或之前最近一个交易日）的收盘。

    历史不够覆盖整个窗口时返回空列表——与 period_returns 同一口径：
    只有两年半数据时没有「近 3 年」，而不是把两年半当三年。
    """
    if days is None or not bars:
        return bars
    cutoff = _d(bars[-1].date) - timedelta(days=days)
    start = bar_on_or_before(bars, cutoff)
    if start is None:
        return []
    return [b for b in bars if b.date[:10] >= start.date[:10]]


def all_windows(bars: list[Bar], bench: list[Bar], rf: float = 0.02) -> dict[str, dict]:
    ppy = periods_per_year(bars)
    out = {}
    for key, days in WINDOWS.items():
        sub = windowed(bars, days)
        if len(sub) < 21:
            continue
        m = risk_metrics(sub, rf, ppy)
        if bench:
            m.update(relative_metrics(sub, bench, rf, ppy))
        out[key] = m
    return out


def monthly_returns(bars: list[Bar], months: int = 24) -> list[dict]:
    """最近若干个月的月度收益（每月最后一个交易日对比上月最后一个交易日）。"""
    month_end: dict[str, float] = {}
    for b in bars:
        month_end[b.date[:7]] = b.adj_close
    keys = sorted(month_end)
    out = []
    for prev, cur in zip(keys, keys[1:]):
        out.append({"month": cur, "return": month_end[cur] / month_end[prev] - 1})
    return out[-months:]
