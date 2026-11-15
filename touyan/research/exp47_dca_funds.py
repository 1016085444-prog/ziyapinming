"""实验 47：用真实的指数基金净值（含分红）复核定投规则。

境内指数基金：按「市场温度」（全市场估值分位）投和卖；境外指数基金（纳指、标普、恒生）：市场温度管不到它们，
比较普通定投、按它自己的「定投成本温度」、赚够了就卖这几种。
"""
import json, os
import numpy as np, pandas as pd
from dcalab import *

z = np.load("temps.npz", allow_pickle=True)
d = z["d"]; names = list(z["names"]); TEMP = z[f"t{names.index('两者平均(近10年)')}"]; n = len(d)
HERE = os.path.dirname(os.path.abspath(__file__))


def nav(code):
    x = json.load(open(os.path.join(HERE, "fundnav", code + ".json"), encoding="utf-8"))
    m = {int(a.replace("-", "")): b for a, b in zip(x["d"], x["c"])}
    s = pd.Series([m.get(int(t), np.nan) for t in d])
    firstv = s.first_valid_index()
    s = s.ffill()
    return x["name"], s.to_numpy(), int(firstv)


start = int(np.nonzero(np.isfinite(TEMP))[0][0])
A = ["160706", "110020", "160119", "161022", "090010", "100032", "005561", "110003", "161017"]
Q = ["270042", "050025", "000071"]
OUT = {}
print("===== 境内指数基金：按市场温度 =====")
rules = {
    "普通定投，不卖": dict(buy="plain"),
    "按温度加减码，不卖": dict(buy="temp"),
    "普通定投 + 温度80以上全卖": dict(buy="plain", sell=("temp", 80)),
    "80以上停投并全卖": dict(buy="pause80", sell=("temp", 80)),
    "按温度加减码 + 80以上全卖": dict(buy="temp", sell=("temp", 80)),
    "按温度加减码 + 80以上且赚20%才卖": dict(buy="temp", sell=("temp_gain", 80, 0.20)),
    "按温度加减码 + 70以上全卖": dict(buy="temp", sell=("temp", 70)),
    "普通定投 + 赚30%全卖再重来": dict(buy="plain", sell=("gain", 0.30)),
    "普通定投 + 赚50%全卖再重来": dict(buy="plain", sell=("gain", 0.50)),
}
for code in A:
    name, c, f0 = nav(code)
    first = max(f0, start)
    print(f"--- {name}（{d[first]} 起，{(n - first) / 245:.1f} 年）---")
    for rn, kw in rules.items():
        s = run(c, TEMP, first, **kw); OUT[f"{code}|{rn}"] = s
        print(f"  {rn:<28} 期末是投入的 {s['multiple']:.2f} 倍  年化 {s['irr']*100:+5.1f}%  最深浮亏 {s['worst']*100:+4.0f}%  卖出 {s['sells']} 次  期末持仓 {s['in_stock']*100:3.0f}%")
print("===== 境外指数基金：市场温度不适用，用它自己的定投成本温度 =====")
for code in Q:
    name, c, f0 = nav(code)
    own = cost_temp(c)
    first = f0
    print(f"--- {name}（{d[first]} 起，{(n - first) / 245:.1f} 年）---")
    qrules = {
        "普通定投，不卖": (None, dict(buy="plain")),
        "按自己的成本温度加减码，不卖": (own, dict(buy="temp", back=40)),
        "成本温度80以上且赚20%全卖": (own, dict(buy="plain", sell=("temp_gain", 80, 0.20), back=40)),
        "成本温度80以上且赚50%全卖": (own, dict(buy="plain", sell=("temp_gain", 80, 0.50), back=40)),
        "赚30%全卖再重来": (None, dict(buy="plain", sell=("gain", 0.30))),
        "赚50%全卖再重来": (None, dict(buy="plain", sell=("gain", 0.50))),
        "（对照）按A股市场温度加减码+80卖": (TEMP, dict(buy="temp", sell=("temp", 80))),
    }
    for rn, (tp, kw) in qrules.items():
        s = run(c, tp, first, **kw); OUT[f"{code}|{rn}"] = s
        print(f"  {rn:<28} 期末是投入的 {s['multiple']:.2f} 倍  年化 {s['irr']*100:+5.1f}%  最深浮亏 {s['worst']*100:+4.0f}%  卖出 {s['sells']} 次  期末持仓 {s['in_stock']*100:3.0f}%")
# 境内基金：软件原来的做法（按它自己的定投成本温度）和按市场温度比
print("===== 境内指数基金：原来的「定投成本温度」对比「市场温度」（都是加减码 + 80以上全卖）=====")
for code in A:
    name, c, f0 = nav(code)
    own = cost_temp(c)
    first = max(f0, start)
    f2 = max(first, int(np.nonzero(np.isfinite(own))[0][0]) if np.isfinite(own).any() else first)
    a = run(c, own, f2, buy="temp", sell=("temp", 80)); b = run(c, TEMP, f2, buy="temp", sell=("temp", 80)); p = run(c, None, f2, buy="plain")
    print(f"  {name:<18}（{d[f2]} 起）普通 {p['irr']*100:+5.1f}% | 成本温度 {a['irr']*100:+5.1f}%（浮亏 {a['worst']*100:+.0f}%） | 市场温度 {b['irr']*100:+5.1f}%（浮亏 {b['worst']*100:+.0f}%）")
    OUT[f"{code}|cmp"] = {"plain": p["irr"], "own": a["irr"], "market": b["irr"]}
json.dump(OUT, open("exp47_dca_funds.json", "w"), ensure_ascii=False, indent=1)
