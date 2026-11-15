"""实验 42b：市场温度——全市场估值在历史上的位置，和之后一到三年收益的关系（2005–2026，连续看）。"""
import numpy as np, pandas as pd, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
a, b = np.load("mktval_old.npz"), np.load("mktval_new.npz")
S = {k: np.concatenate([a[k], b[k]]) for k in a.files}
d = S["d"]; n = len(d)
ew = np.cumprod(1 + np.nan_to_num(S["ew_ret"]))
def idx(sym):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); m = dict(zip(z["d"].tolist(), z["c"].tolist()))
    return np.array([m.get(int(x), np.nan) for x in d])
all_ = pd.Series(idx("sh000985")).ffill().to_numpy(); hs300 = pd.Series(idx("sh000300")).ffill().to_numpy()


def pct_expanding(x, minp=750, window=None):
    """每天的值在它自己过去（含当天）历史里的百分位（0–100）。"""
    out = np.full(len(x), np.nan)
    for t in range(len(x)):
        lo = 0 if window is None else max(0, t - window + 1)
        h = x[lo:t + 1]; h = h[np.isfinite(h)]
        if len(h) >= minp and np.isfinite(x[t]):
            out[t] = 100.0 * (h <= x[t]).mean()
    return out


def dca_ratio(c, months=36, step=21):
    out = np.full(len(c), np.nan)
    for t in range(step * (months - 1), len(c)):
        out[t] = c[t] / (months / sum(1 / c[t - step * k] for k in range(months)))
    return out


def fwdret(c, h):
    out = np.full(len(c), np.nan); out[:-h] = c[h:] / c[:-h] - 1; return out


tall, tbig = pct_expanding(S["med_pb"]), pct_expanding(S["med_pb_big"])
tall10, tbig10 = pct_expanding(S["med_pb"], window=2440), pct_expanding(S["med_pb_big"], window=2440)
temps = {
    "中位数PB分位(全部历史)": tall,
    "中位数PB分位(近10年)": tall10,
    "大市值PB分位(全部历史)": tbig,
    "大市值PB分位(近10年)": tbig10,
    "两者平均(全部历史)": (tall + tbig) / 2,
    "两者平均(近10年)": (tall10 + tbig10) / 2,
    "两者取高(近10年)": np.maximum(tall10, tbig10),
    "定投成本比分位(中证全指)": pct_expanding(dca_ratio(all_), minp=250),
    "价格/五年均线(中证全指)分位": pct_expanding(all_ / pd.Series(all_).rolling(1250, min_periods=500).mean().to_numpy(), minp=250),
}
targets = {"中证全指": all_, "全池等权": ew, "沪深300": hs300}
OUT = {}
print(f"{d[0]}..{d[-1]}，{n} 天")
for tn, tv in temps.items():
    first = d[np.nonzero(np.isfinite(tv))[0][0]]
    print(f"===== {tn}（{first} 起）=====")
    for h, hn in ((245, "一年"), (490, "两年"), (735, "三年")):
        for gn, g in targets.items():
            f = fwdret(g, h)
            row = f"  之后{hn} {gn:<5}"
            for lo, hi in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101)):
                m = np.isfinite(tv) & np.isfinite(f) & (tv >= lo) & (tv < hi)
                if m.sum() < 30:
                    row += f" | {lo:>2}-{min(hi,100):<3}  样本少      "; continue
                x = f[m]
                row += f" | {lo:>2}-{min(hi,100):<3} {x.mean()*100:+6.1f}% 赚{(x>0).mean()*100:3.0f}% 最差{x.min()*100:+4.0f}%"
                OUT[f"{tn}|{hn}|{gn}|{lo}"] = {"n": int(m.sum()), "mean": float(x.mean()), "win": float((x > 0).mean()), "worst": float(x.min()), "median": float(np.median(x))}
            print(row)
    m = np.isfinite(tv)
    for h, hn in ((245, "一年"), (490, "两年")):
        f = fwdret(all_, h); ok = m & np.isfinite(f)
        print(f"    温度与之后{hn}中证全指收益的相关系数 {np.corrcoef(tv[ok], f[ok])[0,1]:+.2f}；天数 {int(ok.sum())}")
# 现在的读数
print("现在：", {k: round(float(v[-1]), 1) for k, v in temps.items()}, "med_pb", round(float(S["med_pb"][-1]), 2), "below1", round(float(S["below1"][-1]), 3), "med_dy", round(float(S["med_dy"][-1]), 4))
json.dump(OUT, open("exp42_temperature.json", "w"), ensure_ascii=False, indent=1)
np.savez("temps.npz", d=d, med_pb_big=S["med_pb_big"], below1=S["below1"], med_dy=S["med_dy"], **{f"t{i}": v for i, v in enumerate(temps.values())}, names=np.array(list(temps.keys())), all_=all_, ew=ew, hs300=hs300, med_pb=S["med_pb"])
