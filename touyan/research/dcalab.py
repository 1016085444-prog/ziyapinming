"""研究用（定投）：按月投入的模拟器。

设定：每 21 个交易日有 1 份新钱；没投出去的钱放货币基金（年化 2%）；买卖各扣 0.1%。
衡量：期末总值 ÷ 累计投入（倍数）、按现金流算的年化（IRR）、途中总值相对累计投入的最深浮亏。
"""
import numpy as np

STEP, CASH, FEE = 21, 0.02 / 245, 0.001


def irr(flows, value, end):
    if value <= 0:
        return float("nan")
    lo, hi = -0.9, 2.0
    for _ in range(80):
        mid = (lo + hi) / 2
        g = sum(a * (1 + mid) ** ((end - t) / 245) for t, a in flows)
        if g < value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def mult5(t):
    return 2.0 if t < 20 else 1.5 if t < 40 else 1.0 if t < 60 else 0.5 if t < 80 else 0.0


def run(c, temp, first, buy="plain", sell=None, back=40, redeploy=12, last=None):
    """c：净值/指数；temp：温度序列（0–100，NaN 当 50）。
    buy：plain 每月 1 份 / temp 按温度倍数 / pause80 温度 80 以上不投（攒着）。
    sell：None / ("temp", x) 温度到 x 以上全部卖出 / ("gain", g) 浮盈到 g 全部卖出 / ("temp_gain", x, g) 两个条件同时满足。
    卖出的钱和攒下的钱：温度回到 back 以下时分 redeploy 个月投回（sell 是 gain 类型时不看温度）。"""
    n = len(c) if last is None else last
    units = cash = pile = contributed = basis = 0.0
    flows = []; sells = 0; worst = 0.0
    for t in range(first, n):
        cash *= 1 + CASH; pile *= 1 + CASH
        if not np.isfinite(c[t]):
            continue
        tp = temp[t] if temp is not None and np.isfinite(temp[t]) else 50.0
        if (t - first) % STEP == 0:
            cash += 1.0; contributed += 1.0; flows.append((t, 1.0))
            if buy == "plain":
                amt = 1.0
            elif buy == "temp":
                amt = mult5(tp)
            elif buy == "pause80":
                amt = 0.0 if tp >= 80 else 1.0
            else:
                raise ValueError(buy)
            amt = min(amt, cash); cash -= amt
            if cash > 1e-9 and tp < back:                         # 之前少投攒下的钱，冷的时候分批补上
                part = min(cash, max(cash / redeploy, 0.5)); cash -= part; amt += part
            if pile > 1e-9 and (tp < back or (sell is not None and sell[0] == "gain")):
                part = min(pile, max(pile / redeploy, 1.0)); pile -= part; amt += part
            if amt > 0:
                units += amt * (1 - FEE) / c[t]; basis += amt
        value = units * c[t]
        if sell is not None and units > 0 and (t - first) % 5 == 0:
            gain = value / basis - 1 if basis > 0 else 0.0
            hit = ((sell[0] == "temp" and tp >= sell[1]) or (sell[0] == "gain" and gain >= sell[1]) or
                   (sell[0] == "temp_gain" and tp >= sell[1] and gain >= sell[2]))
            if hit:
                pile += value * (1 - FEE); units = 0.0; basis = 0.0; sells += 1; value = 0.0
        if contributed > 0:
            worst = min(worst, (value + cash + pile) / contributed - 1)
    total = units * c[n - 1] + cash + pile
    return {"multiple": float(total / contributed), "irr": float(irr(flows, total, n - 1)), "worst": float(worst), "sells": int(sells),
            "months": int(contributed), "in_stock": float(units * c[n - 1] / total)}


def cost_temp(c, months=36, step=21, minp=250):
    """软件里原来的温度：净值 ÷ 过去三年每月定投的平均成本，在它自己历史上的分位（只用到当天为止）。"""
    out = np.full(len(c), np.nan); seen = []
    import bisect
    for t in range(step * (months - 1), len(c)):
        if not np.isfinite(c[t]) or not all(np.isfinite(c[t - step * k]) for k in range(months)):
            continue
        r = c[t] / (months / sum(1 / c[t - step * k] for k in range(months)))
        bisect.insort(seen, r)
        if len(seen) >= minp:
            out[t] = 100.0 * bisect.bisect_right(seen, r) / len(seen)
    return out
