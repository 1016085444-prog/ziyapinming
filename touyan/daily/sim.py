"""方法体检：把一条规则放回过去的行情里，按真实能做到的方式模拟买卖，看结果。

模拟时刻意按「吃亏的」口径来：
- 信号在收盘后才知道，所以买在**第二天开盘**，不是信号当天的收盘价；高开太多就放弃。
- A 股当天买的当天不能卖（T+1），买入当天不检查任何卖出条件。
- 止盈是挂在目标价的卖单，盘中碰到就成交；止损和跟踪止损看收盘价，收盘跌破才卖。
- 每笔扣 0.2%（买卖两次的佣金、印花税，再加一点滑点）。
- 一笔没卖出之前，同一只股票上的新信号不重复算。
- 到数据末尾还没走完的交易不算。

「随便买」对照：同一批股票，不看信号，任意一天开盘买入、拿同样长的时间。
这批股票本身的涨跌都算在对照里，方法比对照多出来的部分才是它的功劳。
"""

from __future__ import annotations

from .common import quantile
from .pool import Series

COST = 0.002
MIN_SAMPLES = 40


def run_trade(s: Series, t: int, max_days: int, max_gap: float = 0.02, target: float | None = None,
              stop: float | None = None, trail: float | None = None, hot_exit: bool = False):
    """信号日 t，返回 (扣费后收益, 持有交易日数, 卖出原因)，没法成交或没走完返回 None。

    target / stop / trail 都是相对买入价的小数：target=0.05 → 涨 5% 止盈；stop=0.04 → 跌 4% 止损；
    trail=0.08 → 从买入后的最高收盘价回落 8% 卖出。hot_exit：已经赚了一成以上时，
    出现涨停或者成交量超过 20 日均量 3 倍，第二天开盘卖。
    """
    e = t + 1
    if e >= s.n:
        return None
    entry, prev = s.o[e], s.c[t]
    if entry <= 0 or entry > prev * (1 + max_gap) or entry <= prev * (1 - s.limit + 0.004):
        return None                                      # 高开太多不追；开盘就跌停的不接
    target_price = entry * (1 + target) if target else None
    floor = entry * (1 - stop) if stop else 0.0
    peak = s.c[e]
    last = e + max_days
    for j in range(e + 1, min(last, s.n - 1) + 1):
        if target_price:
            if s.o[j] >= target_price:
                return s.o[j] / entry - 1 - COST, j - e, "target"
            if s.h[j] >= target_price:
                return target - COST, j - e, "target"
        level = max(floor, peak * (1 - trail)) if trail else floor
        if level and s.c[j] <= level:
            return s.c[j] / entry - 1 - COST, j - e, "stop"
        peak = max(peak, s.c[j])
        if hot_exit and s.c[j] >= entry * 1.10 and j + 1 < s.n and j >= 20 \
                and (s.r[j] >= s.limit - 0.004 or s.v[j] > 3 * s.avg_vol(j - 1, 20) > 0):
            return s.o[j + 1] / entry - 1 - COST, j + 1 - e, "hot"
        if j == last:
            return s.c[j] / entry - 1 - COST, j - e, "time"
    return None


def backtest(pool: list[Series], signal, plan, warmup: int, regimes: dict[str, str] | None = None) -> list[tuple]:
    """signal(s, t) → 特征或 None；plan(特征) → run_trade 的参数。返回 [(收益, 天数, 原因, 当时的市场环境)]。"""
    trades = []
    for s in pool:
        t = warmup
        while t < s.n - 1:
            feats = signal(s, t)
            if feats is None:
                t += 1
                continue
            res = run_trade(s, t, **plan(feats))
            if res is None:
                t += 1
                continue
            trades.append((*res, (regimes or {}).get(s.dates[t], "")))
            t += 1 + res[1]                              # 卖出之后才看下一个信号
    return trades


def baseline(pool: list[Series], horizon: int, warmup: int) -> float | None:
    """不看信号：任意一天开盘买入、拿 horizon 个交易日的平均收益（同样扣费）。"""
    total, count = 0.0, 0
    for s in pool:
        for e in range(warmup + 1, s.n - horizon):
            if s.o[e] > 0:
                total += s.c[e + horizon] / s.o[e] - 1
                count += 1
    return total / count - COST if count else None


def stats(trades: list[tuple]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    rets = sorted(t[0] for t in trades)
    return {"n": n, "win_rate": sum(1 for r in rets if r > 0) / n, "mean": sum(rets) / n,
            "median": quantile(rets, 0.5), "p25": quantile(rets, 0.25), "p75": quantile(rets, 0.75),
            "avg_days": sum(t[1] for t in trades) / n}


def checkup(pool: list[Series], signal, plan, warmup: int, regimes: dict[str, str] | None = None,
            regime_now: str = "", span_label: str = "一年半") -> dict:
    """一条规则的体检报告。"""
    trades = backtest(pool, signal, plan, warmup, regimes)
    out = stats(trades)
    out.update({"stocks": len(pool), "span": span_label, "regime": regime_now, "cost": COST})
    if not trades:
        out.update({"level": "thin", "verdict": f"过去{span_label}里这批股票没有出现过符合条件的情况，没法检验。"})
        return out
    out["reasons"] = {why: sum(1 for t in trades if t[2] == why) for why in ("target", "stop", "time", "hot")}
    base = baseline(pool, max(1, round(out["avg_days"])), warmup)
    out["baseline"] = base
    out["edge"] = out["mean"] - base if base is not None else None
    by = {}
    for label in ("偏强", "震荡", "偏弱"):
        sub = [t for t in trades if t[3] == label]
        if sub:
            by[label] = stats(sub)
    out["by_regime"] = by
    now = by.get(regime_now)
    out["now"] = now if now and now["n"] >= MIN_SAMPLES else None
    use = out["now"] or out
    if out["n"] < MIN_SAMPLES:
        out["level"] = "thin"
        out["verdict"] = f"过去{span_label}只出现过 {out['n']} 次，样本太少，下面的数字只能看个大概。"
    elif use["median"] <= 0 or (out["edge"] is not None and out["edge"] <= 0.001):
        out["level"] = "weak"
        out["verdict"] = (f"过去{span_label}里，这个方法没有比随便买更好"
                          + (f"（目前的市场环境「{regime_now}」下尤其如此）" if out["now"] and out["now"]["median"] <= 0 else "")
                          + "。今天入选的只适合观察，不建议照着买。")
    else:
        out["level"] = "ok"
        out["verdict"] = (f"过去{span_label}里出现过 {out['n']} 次，平均每笔 {out['mean'] * 100:+.1f}%，"
                          f"比随便买多 {out['edge'] * 100:.1f} 个百分点。这是历史统计，不保证以后还这样。")
    return out


def expected(report: dict) -> dict:
    """给单笔交易看的「预期收益」：优先用当前市场环境下的统计。"""
    use = report.get("now") or report
    if not use.get("n"):
        return {"available": False, "text": "历史上没有足够的同类情况，给不出预期收益。"}
    scope = f"目前「{report['regime']}」的市场环境下" if report.get("now") else "过去" + report.get("span", "")
    return {
        "available": True, "n": use["n"], "win_rate": use["win_rate"], "median": use["median"], "mean": use["mean"],
        "low": use["p25"], "high": use["p75"], "avg_days": use["avg_days"], "reliable": report.get("level") == "ok",
        "text": (f"{scope}同类情况 {use['n']} 次：中位 {use['median'] * 100:+.1f}%，赚钱的占 {use['win_rate'] * 100:.0f}%；"
                 f"四分之一的情况低于 {use['p25'] * 100:+.1f}%，四分之一高于 {use['p75'] * 100:+.1f}%；"
                 f"平均拿 {use['avg_days']:.0f} 个交易日。已扣交易成本。"),
    }
