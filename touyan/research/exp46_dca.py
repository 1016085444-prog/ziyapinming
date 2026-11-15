"""实验 46：定投怎么投最划算——普通定投、按市场温度加减码、止盈规则，2008.4–2026.11 连续模拟。

设定：每个月（每 21 个交易日）有 1 份新钱。没投出去的钱放货币基金（年化 2%）。买卖各扣 0.1%（指数基金的申赎费、冲击都算在里面）。
比的是：18 年半以后，账户总值是累计投入的多少倍，以及按现金流算的年化收益（IRR）。
指数是价格指数，不含分红，真实的基金收益每年还要高 1.5–2.5 个点。
"""
import numpy as np, pandas as pd, json, os
z = np.load("temps.npz", allow_pickle=True)
d = z["d"]; names = list(z["names"]); temp = z[f"t{names.index('两者平均(近10年)')}"]; n = len(d)
HERE = os.path.dirname(os.path.abspath(__file__))


def idx(sym):
    zz = np.load(os.path.join(HERE, "index_long", sym + ".npz")); m = dict(zip(zz["d"].tolist(), zz["c"].tolist()))
    return pd.Series([m.get(int(x), np.nan) for x in d]).ffill().to_numpy()


assets = {"沪深300": idx("sh000300"), "中证500": idx("sh000905"), "中证1000": idx("sh000852"), "中证全指": idx("sh000985"), "创业板指": idx("sz399006"), "全池等权": z["ew"]}
start = int(np.nonzero(np.isfinite(temp))[0][0])
STEP, CASH, FEE = 21, 0.02 / 245, 0.001


def irr(flows, value):
    """flows：[(第几天, 金额)]（投入为正），value：期末总值。返回年化。"""
    if value <= 0:
        return np.nan
    lo, hi = -0.9, 2.0
    T = n - 1
    for _ in range(80):
        mid = (lo + hi) / 2
        g = sum(a * (1 + mid) ** ((T - t) / 245) for t, a in flows)
        if g < value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def mult_temp(t):
    return 2.0 if t < 20 else 1.5 if t < 40 else 1.0 if t < 60 else 0.5 if t < 80 else 0.0


def run(c, buy="plain", sell=None, redeploy=12, first=None):
    """buy：plain 每月投 1 份；temp 按温度倍数（钱不够就有多少投多少）；cold 只在温度<60 时投，其余攒着。
    sell：None 不卖；("temp", x) 温度到 x 以上全卖；("gain", g) 账户浮盈到 g 全卖。
    卖出后的钱和攒着的钱，在温度低于 40 时分 redeploy 个月重新投入（sell 为 gain 时不看温度，直接分批投回）。"""
    first = start if first is None else first
    units = 0.0; cash = 0.0; contributed = 0.0; cost_basis = 0.0; flows = []; pile = 0.0; sells = 0
    worst = 0.0; eq_curve = []
    for t in range(first, n):
        cash *= 1 + CASH; pile *= 1 + CASH
        if not np.isfinite(c[t]):
            continue
        if (t - first) % STEP == 0:
            cash += 1.0; contributed += 1.0; flows.append((t, 1.0))
            tp = temp[t] if np.isfinite(temp[t]) else 50.0
            if buy == "plain":
                amt = min(cash, 1.0)
            elif buy == "temp":
                amt = min(cash, mult_temp(tp))
            elif buy == "cold":
                amt = min(cash, 1.0) if tp < 60 else 0.0
            else:
                raise ValueError(buy)
            # 之前卖出/攒下的钱分批投回
            if pile > 1e-9 and (sell is None or sell[0] == "gain" or tp < 40):
                part = min(pile, max(pile / redeploy, 1.0)); pile -= part; amt += part
            if buy != "plain" and cash - min(cash, amt) > 12 and tp < 40:      # 攒了一年以上的钱，冷的时候加快投
                extra = (cash - amt) / 6; amt += extra
            amt = min(amt, cash + 0.0) if amt <= cash else amt
            use = min(amt, cash + 1e9)
            from_cash = min(use, cash); cash -= from_cash
            units += use * (1 - FEE) / c[t]; cost_basis += use
        value = units * c[t]
        if sell is not None and units > 0 and (t - first) % 5 == 0:
            hit = (sell[0] == "temp" and np.isfinite(temp[t]) and temp[t] >= sell[1]) or (sell[0] == "gain" and cost_basis > 0 and value / cost_basis - 1 >= sell[1])
            if hit:
                pile += value * (1 - FEE); units = 0.0; cost_basis = 0.0; sells += 1; value = 0.0
        total = value + cash + pile
        eq_curve.append(total / max(contributed, 1e-9))
        worst = min(worst, total / max(contributed, 1e-9) - 1)
    total = units * c[-1] + cash + pile
    return {"multiple": total / contributed, "irr": irr(flows, total), "worst": worst, "sells": sells, "contributed": contributed,
            "in_stock": units * c[-1] / total, "final_cash": (cash + pile) / total}


rules = {
    "普通定投，不卖": dict(buy="plain"),
    "按温度加减码，不卖": dict(buy="temp"),
    "温度低于60才投，不卖": dict(buy="cold"),
    "普通定投 + 温度80以上全卖": dict(buy="plain", sell=("temp", 80)),
    "按温度加减码 + 温度80以上全卖": dict(buy="temp", sell=("temp", 80)),
    "按温度加减码 + 温度70以上全卖": dict(buy="temp", sell=("temp", 70)),
    "温度低于60才投 + 温度80以上全卖": dict(buy="cold", sell=("temp", 80)),
    "普通定投 + 赚20%全卖再重来": dict(buy="plain", sell=("gain", 0.20)),
    "普通定投 + 赚30%全卖再重来": dict(buy="plain", sell=("gain", 0.30)),
    "普通定投 + 赚50%全卖再重来": dict(buy="plain", sell=("gain", 0.50)),
}
OUT = {}
print(f"{d[start]}..{d[-1]}，{(n - start) / 245:.1f} 年，共 {len(range(start, n, STEP))} 份")
for an, c in assets.items():
    first = start
    if not np.isfinite(c[start]):
        first = int(np.nonzero(np.isfinite(c))[0][0])
    print(f"===== {an}（{d[first]} 起）=====")
    for rn, kw in rules.items():
        s = run(c, first=first, **kw)
        OUT[f"{an}|{rn}"] = s
        print(f"  {rn:<26} 期末是投入的 {s['multiple']:.2f} 倍  年化(IRR) {s['irr']*100:+5.1f}%  途中最深浮亏 {s['worst']*100:+4.0f}%  卖出 {s['sells']} 次  期末持仓 {s['in_stock']*100:3.0f}%")
json.dump({k: {a: float(b) for a, b in v.items()} for k, v in OUT.items()}, open("exp46_dca.json", "w"), ensure_ascii=False, indent=1)
