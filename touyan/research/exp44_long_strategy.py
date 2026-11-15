"""实验 44b：长期的「交易方法」——按市场温度决定买不买、卖不卖，和一直拿着比（2008.4–2026.11 连续模拟）。

温度每 5 个交易日看一次，信号出来的下一个交易日执行。空仓的钱按年化 2% 计（货币基金）。换仓一次扣 0.2%。
"""
import numpy as np, pandas as pd, json
a, b = np.load("basket_old.npz"), np.load("basket_new.npz")
d = np.concatenate([a["d"], b["d"]]); n = len(d); na = len(a["d"])
z = np.load("temps.npz", allow_pickle=True)
names = list(z["names"]); temp = z[f"t{names.index('两者平均(近10年)')}"]
assert (z["d"] == d).all()
all_ = z["all_"]; hs = z["hs300"]


def series(k):
    s = np.concatenate([a[k], b[k]])
    if k != "all":                       # 近十年的头一年还在攒数据，用全池的收益补上
        gap = slice(na, na + 262)
        s[gap] = np.concatenate([a["all"], b["all"]])[gap]
    return s


def idx_ret(c):
    r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1; return np.nan_to_num(r)


assets = {"中证全指(指数)": idx_ret(all_), "沪深300(指数)": idx_ret(hs), "全池等权": series("all"), "只做回避": series("calm"),
          "稳健": series("steady"), "红利低波": series("divlow"), "大市值稳健": series("bigsteady")}
start = int(np.nonzero(np.isfinite(temp))[0][0])
CASH = 0.02 / 245


def run(ret, rule, cost=0.002):
    """rule(temp, 当前仓位) → 目标仓位（0–1）。返回每天的组合收益和仓位。"""
    w = 0.0; out = np.zeros(n); ws = np.zeros(n); pending = None; trades = 0
    for t in range(start, n):
        if pending is not None:
            if abs(pending - w) > 1e-9:
                out[t] -= abs(pending - w) * cost; trades += 1
            w = pending; pending = None
        out[t] += w * ret[t] + (1 - w) * CASH
        ws[t] = w
        if (t - start) % 5 == 0 and np.isfinite(temp[t]):
            tgt = rule(temp[t], w)
            if abs(tgt - w) > 1e-9:
                pending = tgt
    return out, ws, trades


def stats(r, ws=None):
    r = r[start:]; eq = np.cumprod(1 + r); yrs = len(r) / 245
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    yy = d[start:] // 10000
    by = {int(y): float(np.prod(1 + r[yy == y]) - 1) for y in sorted(set(yy.tolist()))}
    # 任意一天买入拿满 3 年
    h = 735; roll = eq[h:] / eq[:-h] - 1
    return {"cagr": float(eq[-1] ** (1 / yrs) - 1), "mdd": float(dd), "by_year": by, "neg_years": int(sum(1 for v in by.values() if v < 0)), "years": len(by),
            "worst_year": float(min(by.values())), "roll3_win": float((roll > 0).mean()), "roll3_min": float(roll.min()),
            "in_mkt": float(ws[start:].mean()) if ws is not None else 1.0, "final": float(eq[-1])}


def hyst(lo, hi):
    return lambda t, w: 1.0 if t < lo else (0.0 if t >= hi else w)


def ladder(t, w):                        # 分档：越冷仓位越高
    return 1.0 if t < 30 else 0.7 if t < 50 else 0.4 if t < 70 else 0.0 if t >= 80 else 0.2


def ladder_keep(t, w):                   # 分档但只在两头动：<40 满仓，40–70 维持，70–80 减到一半，≥80 清仓
    return 1.0 if t < 40 else (min(w, 0.5) if 70 <= t < 80 else (0.0 if t >= 80 else w))


rules = {"一直拿着": lambda t, w: 1.0, "低于40买、高于80卖": hyst(40, 80), "低于40买、高于70卖": hyst(40, 70), "低于50买、高于80卖": hyst(50, 80),
         "低于30买、高于70卖": hyst(30, 70), "低于60买、高于80卖": hyst(60, 80), "低于40买、高于60卖": hyst(40, 60), "按温度分档": ladder, "两头动(40满/70半/80清)": ladder_keep}
OUT = {}
print(f"{d[start]}..{d[-1]}，{(n - start) / 245:.1f} 年")
for an, ret in assets.items():
    print(f"===== {an} =====")
    for rn, rule in rules.items():
        r, ws, tr = run(ret, rule)
        s = stats(r, ws); s["trades"] = tr
        OUT[f"{an}|{rn}"] = s
        print(f"  {rn:<22} 年化 {s['cagr']*100:+5.1f}% 最大回撤 {s['mdd']*100:+4.0f}% 亏钱的年 {s['neg_years']}/{s['years']} 最差一年 {s['worst_year']*100:+4.0f}% | 任意一天买入拿满三年：赚钱 {s['roll3_win']*100:3.0f}% 最差 {s['roll3_min']*100:+4.0f}% | 持仓时间 {s['in_mkt']*100:3.0f}% 换仓 {tr} 次")
        if rn in ("一直拿着", "低于40买、高于80卖", "两头动(40满/70半/80清)"):
            print("      按年: " + " ".join(f"{y%100:02d}:{v*100:+.0f}" for y, v in s["by_year"].items()))
json.dump(OUT, open("exp44_strategy.json", "w"), ensure_ascii=False, indent=1)
