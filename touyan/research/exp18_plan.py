"""实验 18：恐慌日买入的完整计划（持有期、止盈、止损）——用指数（对应 ETF）和等权全市场两种口径，2005–2026。"""
import json, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
COST_ETF, COST_STK = 0.001, 0.002
# 合并两个十年的状态
st = {}
for w in ("old", "new"):
    j = json.load(open(os.path.join(HERE, f"capit_{w}.json")))
    for k, v in j.items():
        st.setdefault(k, []).extend(v)
cal = np.array(st["cal"]); dn = np.array(st["dnshare"]); m1 = np.array(st["m1"]); m5 = np.array(st["m5"])
print("合并交易日:", len(cal), cal[0], cal[-1])
def load(sym):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); return z["d"], z["o"], z["c"]
def sim(d, o, c, sig_dates, hold, stop=None, target=None, cost=COST_ETF, overlap=False):
    pos = {int(x): i for i, x in enumerate(d)}
    out = []; busy_until = -1
    for sd in sig_dates:
        t = pos.get(int(sd))
        if t is None or t + 1 + hold >= len(d): continue
        if not overlap and t < busy_until: continue
        e = t + 1; entry = o[e]; ex = None; why = "到期"
        for j in range(e + 1, e + hold + 1):
            if target and c[j] >= entry * (1 + target): ex = j; why = "止盈"; break
            if stop and c[j] <= entry * (1 - stop): ex = j; why = "止损"; break
        if ex is None: ex = e + hold
        out.append((int(sd), c[ex] / entry * (1 - cost) - 1, ex - e, why))
        busy_until = ex
    return out
def rep(name, tr):
    if not tr: print(f"  {name}: 无"); return
    r = np.array([x[1] for x in tr]); yr = np.array([x[0] // 10000 for x in tr]); dd = np.array([x[2] for x in tr])
    ys = sorted(set(yr.tolist())); ysum = {y: r[yr == y].sum() for y in ys}
    neg = [f"{y}:{v*100:+.0f}" for y, v in ysum.items() if v < 0]
    a, b = r[yr <= 2016], r[yr >= 2017]
    stop_n = sum(1 for x in tr if x[3] == "止损")
    print(f"  {name:<42} 笔 {len(r):3d} 均值 {r.mean()*100:+.2f}% 中位 {np.median(r)*100:+.2f}% 胜率 {(r>0).mean()*100:.0f}% 平均拿 {dd.mean():.1f}天 最差 {r.min()*100:+.1f}% 最差一成 {np.percentile(r,10)*100:+.1f}% 止损 {stop_n} 笔 | 年份 {len(ys)} 亏损年 {len(neg)} ({' '.join(neg)}) | 05-16: {a.mean()*100 if len(a) else float('nan'):+.2f}%({len(a)}) 17-26: {b.mean()*100 if len(b) else float('nan'):+.2f}%({len(b)})")
trig = {"跌停占比≥2%": dn >= 0.02, "跌停占比≥3%": dn >= 0.03, "跌停≥2% 或 全市场当日跌≥4%": (dn >= 0.02) | (m1 <= -0.04), "全市场当日跌≥4%": m1 <= -0.04}
for sym, name in (("sh000852", "中证1000"), ("sh000905", "中证500"), ("sh000985", "中证全指"), ("sh000300", "沪深300"), ("sz399006", "创业板指")):
    d, o, c = load(sym)
    print(f"===== {name} =====")
    for tn, cond in trig.items():
        dates = cal[cond]
        dates = dates[dates >= d[0]]
        for hold in (5, 8):
            rep(f"{tn} 拿{hold}天", sim(d, o, c, dates, hold))
        rep(f"{tn} 拿8天 止损6%", sim(d, o, c, dates, 8, stop=0.06))
        rep(f"{tn} 拿8天 止盈6%", sim(d, o, c, dates, 8, target=0.06))
        rep(f"{tn} 拿8天 止盈6% 止损6%", sim(d, o, c, dates, 8, stop=0.06, target=0.06))
        rep(f"{tn} 拿8天 止盈8% 止损8%", sim(d, o, c, dates, 8, stop=0.08, target=0.08))
