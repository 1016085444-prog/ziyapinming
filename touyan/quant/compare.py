"""多品种对比：同一区间的累计收益曲线、关键指标、收益相关性。

不同市场的交易日不同（A 股、港股、美股假期各异），所以：
- 曲线按所有日期的并集画，某品种当天休市就沿用前一天的值；
- 相关系数只用两者都交易的日子计算。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from market.models import Bar, Instrument
from quant import metrics
from quant.indicators import stdev

PERIODS = {"3m": 91, "6m": 182, "1y": 365, "3y": 1095, "5y": 1826}


def _returns_by_date(bars: list[Bar]) -> dict[str, float]:
    out = {}
    for prev, cur in zip(bars, bars[1:]):
        out[cur.date] = cur.adj_close / prev.adj_close - 1
    return out


def _corr(a: dict[str, float], b: dict[str, float]) -> float | None:
    common = sorted(set(a) & set(b))
    if len(common) < 20:
        return None
    xs, ys = [a[d] for d in common], [b[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx, sy = stdev(xs), stdev(ys)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)
    return round(cov / (sx * sy), 3)


def compare(items: list[tuple[Instrument, list[Bar]]], period: str = "1y", rf: float = 0.02) -> dict:
    days = PERIODS.get(period, 365)
    end = max(date.fromisoformat(bars[-1].date) for _, bars in items)
    start = end - timedelta(days=days)
    windows = []
    for inst, bars in items:
        anchor = metrics.bar_on_or_before(bars, start)
        sub = [b for b in bars if b.date >= (anchor.date if anchor else bars[0].date)]
        windows.append((inst, sub, anchor is not None))

    all_dates = sorted({b.date for _, sub, _ in windows for b in sub})
    series = []
    rows = []
    rets = []
    for inst, sub, full in windows:
        by_date = {b.date: b.adj_close for b in sub}
        base = sub[0].adj_close if sub else None
        line, last = [], None
        for d in all_dates:
            if d in by_date:
                last = by_date[d] / base * 100 if base else None
            line.append(None if last is None else round(last, 3))
        series.append({"key": inst.key, "name": inst.name or inst.code, "values": line})
        m = metrics.risk_metrics(sub, rf) if len(sub) > 21 else {}
        r = metrics.period_returns(sub) if sub else {}
        rows.append({
            "instrument": inst.to_dict(),
            "full_window": full,
            "start": sub[0].date if sub else None,
            "end": sub[-1].date if sub else None,
            "return": (sub[-1].adj_close / sub[0].adj_close - 1) if len(sub) > 1 else None,
            "cagr": m.get("cagr"),
            "volatility": m.get("volatility"),
            "max_drawdown": m.get("max_drawdown"),
            "sharpe": m.get("sharpe"),
            "calmar": m.get("calmar"),
            "returns": {k: r.get(k) for k in ("1m", "3m", "6m", "ytd", "1y")},
        })
        rets.append(_returns_by_date(sub))
    n = len(items)
    corr = [[1.0 if i == j else _corr(rets[i], rets[j]) for j in range(n)] for i in range(n)]
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, float) and not math.isfinite(v):
                row[k] = None
    return {"period": period, "dates": all_dates, "series": series, "rows": rows, "correlation": corr}
