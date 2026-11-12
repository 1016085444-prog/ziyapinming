"""历史参照：把同一套买卖规则放回过去的行情里走一遍，看看「通常」会怎样。

这不是预测。它回答的是：过去几年里出现类似买点时，照这份持有计划操作，
多少次赚、多少次亏、平均赚多少、通常拿几天。样本少、行情变了，结论都会失效，页面上会写明。

- plan_history：单只股票。买点 = 均线多头排列（MA5 > MA10 > MA20）、站上 20 日线、乖离率在 −3% 到 5% 之间，
  按收盘价买入；之后止盈 / 止损 / 保本 / 到期四条规则先触发哪条按哪条卖。一笔卖出后才找下一个买点，样本互不重叠。
- rotation_backtest：ETF 双动量轮动，每 5 个交易日按收盘调一次仓，下一个交易日起生效（不用当天还不知道的价格）。
- rolling_stats：场外基金。历史上任意一天买入、持有满一段时间的收益分布。
"""

from __future__ import annotations

from statistics import median

from market.models import Bar
from quant import indicators as ind


def _setup_flags(bars: list[Bar]) -> list[bool]:
    closes = [b.close for b in bars]
    ma5, ma10, ma20 = ind.sma(closes, 5), ind.sma(closes, 10), ind.sma(closes, 20)
    flags = []
    for c, a, b, d in zip(closes, ma5, ma10, ma20):
        flags.append(a is not None and d is not None and a > b > d and c >= d and -3 < (c / a - 1) * 100 < 5)
    return flags


def plan_history(bars: list[Bar], target_pct: float, stop_pct: float, max_days: int,
                 breakeven_pct: float | None = None, lookback: int = 750) -> dict:
    """target_pct / stop_pct / breakeven_pct 都是百分数（5 表示 5%）。最后一根 K 线是「今天」，不参与回测。"""
    if len(bars) < 80 or target_pct <= 0 or stop_pct <= 0:
        return {"trades": 0}
    flags = _setup_flags(bars)
    last = len(bars) - 1
    start = max(20, last - lookback)
    trades = []
    i = start
    while i < last:
        if not flags[i]:
            i += 1
            continue
        entry = bars[i].close
        target, stop = entry * (1 + target_pct / 100), entry * (1 - stop_pct / 100)
        protect = entry * (1 + breakeven_pct / 100) if breakeven_pct else None
        exit_j = None
        for j in range(i + 1, i + max_days + 1):
            if j > last:
                break                           # 还没走完的交易不算
            b = bars[j]
            if b.close <= stop:                 # 同一天既摸到目标又收在止损下方，按止损算（保守）
                exit_j, ret, why = j, b.close / entry - 1, "stop"
            elif b.high >= target:
                exit_j, ret, why = j, target / entry - 1, "target"
            elif j == i + max_days:
                exit_j, ret, why = j, b.close / entry - 1, "time"
            if exit_j is not None:
                trades.append({"ret": ret, "days": j - i, "why": why})
                break
            if protect and b.high >= protect:   # 次日起止损提到买入价
                stop = max(stop, entry)
        if exit_j is None:
            break
        i = exit_j + 1
    if not trades:
        return {"trades": 0, "years": round((last - start) / 245, 1)}
    rets = [t["ret"] for t in trades]
    n = len(trades)
    return {
        "trades": n, "years": round((last - start) / 245, 1),
        "win_rate": sum(1 for r in rets if r > 0) / n, "avg": sum(rets) / n, "median": median(rets),
        "target_hits": sum(1 for t in trades if t["why"] == "target"),
        "stop_hits": sum(1 for t in trades if t["why"] == "stop"),
        "time_exits": sum(1 for t in trades if t["why"] == "time"),
        "avg_days": sum(t["days"] for t in trades) / n, "best": max(rets), "worst": min(rets),
    }


def _drawdown(curve: list[float]) -> float:
    peak, dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    return dd


def _cagr(total: float, days: int) -> float | None:
    years = days / 245
    return (1 + total) ** (1 / years) - 1 if years >= 0.5 and total > -1 else None


def rotation_backtest(series: dict[str, list[Bar]], bench: list[Bar], safe: list[Bar] | None = None,
                      top_n: int = 3, step: int = 5, cost: float = 0.001) -> dict | None:
    """series: {代码: K 线}。按沪深300 的交易日历走；没满 120 根 K 线的 ETF 不参与排名。"""
    from .funds import etf_momentum

    calendar = [b.date for b in bench]
    idx = {code: {b.date: i for i, b in enumerate(bars)} for code, bars in series.items()}
    safe_px = {b.date: b.adj_close for b in safe} if safe else {}

    def day_ret(px: dict, d0: str, d1: str) -> float:
        a, b = px.get(d0), px.get(d1)
        return b / a - 1 if a and b else 0.0

    prices = {code: {b.date: b.adj_close for b in bars} for code, bars in series.items()}
    first = next((k for k, d in enumerate(calendar) if sum(1 for c in series if idx[c].get(d, -1) >= 130) >= top_n), None)
    if first is None or len(calendar) - first < 60:
        return None
    equity, curve, holds, switches, rebalances = 1.0, [1.0], [], 0, 0
    held_weeks: dict[str, int] = {}
    finished_weeks: list[int] = []
    k = first
    while k < len(calendar) - 1:
        d = calendar[k]
        scored = []
        for code, bars in series.items():
            i = idx[code].get(d)
            if i is None or i < 130:
                continue
            m = etf_momentum(bars[: i + 1])
            if m and m["eligible"]:
                scored.append((m["score"], code))
        new = [c for _, c in sorted(scored, reverse=True)[:top_n]]
        changed = len(set(new) - set(holds))
        if rebalances:
            switches += changed
        for c in set(holds) - set(new):
            finished_weeks.append(held_weeks.pop(c, 1))
        for c in new:
            held_weeks[c] = held_weeks.get(c, 0) + 1
        equity *= 1 - cost * changed / top_n
        holds = new
        rebalances += 1
        for kk in range(k + 1, min(k + step, len(calendar) - 1) + 1):
            d0, d1 = calendar[kk - 1], calendar[kk]
            r = sum(day_ret(prices[c], d0, d1) for c in holds)
            r += (top_n - len(holds)) * day_ret(safe_px, d0, d1)
            equity *= 1 + r / top_n
            curve.append(equity)
        k += step
    finished_weeks += list(held_weeks.values())
    days = len(curve) - 1
    b0, b1 = bench[first].adj_close, bench[min(first + days, len(bench) - 1)].adj_close
    bench_curve = [b.adj_close / b0 for b in bench[first:first + days + 1]]
    total = equity - 1
    return {
        "start": calendar[first], "end": calendar[min(first + days, len(calendar) - 1)], "years": round(days / 245, 1),
        "total": total, "cagr": _cagr(total, days), "max_drawdown": _drawdown(curve),
        "bench_total": b1 / b0 - 1, "bench_cagr": _cagr(b1 / b0 - 1, days), "bench_max_drawdown": _drawdown(bench_curve),
        "rebalances": rebalances, "switches": switches,
        "avg_hold_weeks": sum(finished_weeks) / len(finished_weeks) if finished_weeks else None,
    }


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
