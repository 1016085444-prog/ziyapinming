"""把一条买卖计划放回过去的行情里，按真实能做到的方式模拟。短期、中期两个板块的「最近表现」都靠它。

刻意按「吃亏的」口径来（和 research/ 里定方法时用的一致）：
- 信号在收盘后才知道，所以买在**第二天开盘**；高开太多就放弃，开盘就涨停买不进，开盘就跌停的不接；
- A 股当天买的当天不能卖（T+1），买入当天不检查任何卖出条件；
- 止损看收盘价：收盘跌破才卖；收盘封死在跌停卖不掉，顺延到下一天开盘卖；
- 每笔扣 0.2%（买卖两次的佣金、印花税，再加一点滑点）；
- 到数据末尾还没走完的交易不算。
"""

from __future__ import annotations

from statistics import median

from .pool import Stock

COST = 0.002


def trade(s: Stock, t: int, hold: int, max_gap: float = 0.02, stop: float | None = None,
          sell_on_limit_up: bool = False) -> tuple[float, int, str] | None:
    """信号日 t，返回 (扣费后收益, 买入后过了几个交易日, 卖出原因)；买不进或者没走完返回 None。

    hold：买入后第 hold 个交易日收盘还没卖的，收盘卖出。stop=0.08 → 收盘比买入价低 8% 就卖。
    sell_on_limit_up：收盘封涨停的，第二天开盘卖（涨停股第二天平均高开 2%，之后往回走）。
    """
    e = t + 1
    last = e + hold
    if last >= s.n:
        return None
    entry, prev = s.o[e], s.c[t]
    if entry <= 0 or prev <= 0 or entry > prev * (1 + max_gap) or s.opens_at_limit(e):
        return None
    pending = ""
    for j in range(e + 1, last + 1):
        if pending:                                        # 昨天就该卖但卖不掉 / 昨天涨停：今天开盘卖
            return s.o[j] / entry * (1 - COST) - 1, j - e, pending
        locked = s.limit_down(j)
        if stop and s.c[j] <= entry * (1 - stop):
            if not locked:
                return s.c[j] / entry * (1 - COST) - 1, j - e, "stop"
            pending = "stop"
        elif sell_on_limit_up and s.limit_up(j):
            pending = "limit_up"
        elif j == last:
            if not locked:
                return s.c[j] / entry * (1 - COST) - 1, j - e, "time"
            pending = "time"
    if last + 1 < s.n:
        return s.o[last + 1] / entry * (1 - COST) - 1, last + 1 - e, pending
    return s.c[last] / entry * (1 - COST) - 1, hold, pending


def hold_return(s: Stock, t: int, hold: int) -> float | None:
    """不看任何条件：第二天开盘买、拿 hold 个交易日的收益（同样扣费）。给「随便买」做对照用。"""
    e = t + 1
    if e + hold >= s.n or s.o[e] <= 0 or s.opens_at_limit(e) > 0:
        return None
    return s.c[e + hold] / s.o[e] * (1 - COST) - 1


def stats(rets: list[float]) -> dict:
    n = len(rets)
    if not n:
        return {"n": 0}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    return {"n": n, "win_rate": len(wins) / n, "mean": sum(rets) / n, "median": median(rets),
            "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(losses) / len(losses) if losses else None}
