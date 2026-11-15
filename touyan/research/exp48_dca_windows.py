"""实验 48：任意一个月开始定投、投满 3 年 / 5 年，结果的分布——普通定投 对比 按市场温度（加减码 + 80 以上卖出）。"""
import json, os
import numpy as np, pandas as pd
from dcalab import *

z = np.load("temps.npz", allow_pickle=True)
d = z["d"]; names = list(z["names"]); TEMP = z[f"t{names.index('两者平均(近10年)')}"]; n = len(d)
HERE = os.path.dirname(os.path.abspath(__file__))
start = int(np.nonzero(np.isfinite(TEMP))[0][0])


def nav(code):
    x = json.load(open(os.path.join(HERE, "fundnav", code + ".json"), encoding="utf-8"))
    m = {int(a.replace("-", "")): b for a, b in zip(x["d"], x["c"])}
    s = pd.Series([m.get(int(t), np.nan) for t in d]); f0 = s.first_valid_index()
    return x["name"], s.ffill().to_numpy(), int(f0)


def idx(sym, name):
    zz = np.load(os.path.join(HERE, "index_long", sym + ".npz")); m = dict(zip(zz["d"].tolist(), zz["c"].tolist()))
    s = pd.Series([m.get(int(x), np.nan) for x in d]); f0 = s.first_valid_index()
    return name, s.ffill().to_numpy(), int(f0)


assets = [idx("sh000300", "沪深300指数"), idx("sh000905", "中证500指数"), idx("sh000852", "中证1000指数"), idx("sz399006", "创业板指"),
          nav("160706"), nav("160119"), nav("110003"), nav("090010"), nav("100032"), nav("270042"), nav("050025")]
rules = {"普通定投": dict(buy="plain"), "按温度加减码": dict(buy="temp"), "普通 + 80以上卖": dict(buy="plain", sell=("temp", 80)), "加减码 + 80以上卖": dict(buy="temp", sell=("temp", 80))}
OUT = {}
for h, hn in ((735, "3 年"), (1225, "5 年")):
    print(f"===== 投满 {hn} =====")
    for name, c, f0 in assets:
        first = max(f0, start)
        starts = list(range(first, n - h, STEP))
        if len(starts) < 24:
            continue
        row = f"  {name:<16}（{len(starts)} 个起点）"
        for rn, kw in rules.items():
            res = np.array([run(c, TEMP, s, last=s + h, **kw)["multiple"] - 1 for s in starts])
            OUT[f"{name}|{hn}|{rn}"] = {"n": len(res), "win": float((res > 0).mean()), "median": float(np.median(res)), "p10": float(np.percentile(res, 10)), "worst": float(res.min()), "mean": float(res.mean())}
            row += f" | {rn}: 赚钱 {(res > 0).mean()*100:3.0f}% 中位 {np.median(res)*100:+5.1f}% 差的一成 {np.percentile(res, 10)*100:+5.1f}% 最差 {res.min()*100:+4.0f}%"
        print(row, flush=True)
# 按开始定投时的温度分
print("===== 开始定投那天的温度 和 3 年后的结果（普通定投）=====")
for name, c, f0 in assets[:6]:
    first = max(f0, start); h = 735
    starts = np.array(list(range(first, n - h, STEP)))
    res = np.array([run(c, TEMP, s, last=s + h, buy="plain")["multiple"] - 1 for s in starts])
    tt = TEMP[starts]
    row = f"  {name:<16}"
    for lo, hi in ((0, 40), (40, 60), (60, 101)):
        k = (tt >= lo) & (tt < hi)
        if k.sum() >= 5:
            row += f" | 温度 {lo}-{min(hi, 100)}: 赚钱 {(res[k] > 0).mean()*100:3.0f}% 中位 {np.median(res[k])*100:+5.1f}% (n={int(k.sum())})"
            OUT[f"{name}|start|{lo}"] = {"n": int(k.sum()), "win": float((res[k] > 0).mean()), "median": float(np.median(res[k]))}
    print(row)
json.dump(OUT, open("exp48_dca_windows.json", "w"), ensure_ascii=False, indent=1)
