"""实验 9：恐慌之后「等止跌信号再买」是否比直接抄底稳。指数长历史 2005–2026。"""
import numpy as np, os
HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.002
def load(sym, start=20050101):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); m = z["d"] >= start
    return z["d"][m], z["o"][m], z["c"][m], z["h"][m], z["l"][m]
def sim(d, o, c, sig, hold, stop=None, target=None):
    """sig[t] 为真 → t+1 开盘买，持有到第 hold 天收盘；收盘跌破止损就卖。不重叠持仓。返回 [(信号日下标, 收益, 天数)]。"""
    n = len(d); out = []; t = 0
    while t < n - 1:
        if not sig[t] or t + 1 + hold >= n:
            t += 1; continue
        e = t + 1; entry = o[e]; ex = None
        for j in range(e + 1, e + hold + 1):
            if target and c[j] >= entry * (1 + target): ex = j; break
            if stop and c[j] <= entry * (1 - stop): ex = j; break
        if ex is None: ex = e + hold
        out.append((t, c[ex] / entry * (1 - COST) - 1, ex - e))
        t = ex            # 卖出后才看下一个信号
    return out
def report(name, d, tr):
    if not tr: print(f"  {name}: 无"); return
    r = np.array([x[1] for x in tr]); yr = np.array([d[x[0]] // 10000 for x in tr])
    ys = sorted(set(yr.tolist()))
    ysum = {y: r[yr == y].sum() for y in ys}
    neg = [f"{y}:{v*100:+.0f}" for y, v in ysum.items() if v < 0]
    print(f"  {name:<46} 笔数 {len(r):3d} 均值 {r.mean()*100:+.2f}% 中位 {np.median(r)*100:+.2f}% 胜率 {(r>0).mean()*100:.0f}% 最差 {r.min()*100:+.1f}% | 有信号的年份 {len(ys)} 其中亏损年 {len(neg)} ({' '.join(neg)}) | 2005-16 均值 {r[yr<=2016].mean()*100 if (yr<=2016).any() else float('nan'):+.2f}% 2017-26 均值 {r[yr>=2017].mean()*100 if (yr>=2017).any() else float('nan'):+.2f}%")
for sym, name in (("sh000985", "中证全指"), ("sh000852", "中证1000"), ("sh000300", "沪深300")):
    d, o, c, h, l = load(sym); n = len(d)
    def ret(k):
        out = np.full(n, np.nan); out[k:] = c[k:] / c[:-k] - 1; return out
    r1, r5, r20 = ret(1), ret(5), ret(20)
    def recent(x, k):       # 最近 k 天内出现过
        out = np.zeros(n, bool)
        for j in range(k): out[j:] |= x[:n - j] if j else x
        return out
    clv = (c - l) / np.maximum(h - l, 1e-9)
    print(f"===== {name} =====")
    panic = np.nan_to_num(r5, nan=0) <= -0.07
    panic20 = np.nan_to_num(r20, nan=0) <= -0.12
    for hold in (5, 10):
        report(f"A 直接抄底: 5日跌≥7% 次日买 拿{hold}天", d, sim(d, o, c, panic, hold))
        report(f"A' 同上 + 收盘亏5%止损", d, sim(d, o, c, panic, hold, stop=0.05))
        for up in (0.01, 0.02, 0.03):
            sig = recent(panic, 5) & (r1 >= up)
            report(f"B 等止跌: 近5天内恐慌过 且 当日涨≥{up*100:.0f}% 拿{hold}天", d, sim(d, o, c, sig, hold))
        sig = recent(panic, 5) & (r1 >= 0.02)
        report(f"B' 当日涨≥2% + 收盘亏5%止损 拿{hold}天", d, sim(d, o, c, sig, hold, stop=0.05))
        sig = recent(panic | panic20, 5) & (r1 >= 0.02)
        report(f"C 近5天内(5日跌≥7%或20日跌≥12%) 且 当日涨≥2% 拿{hold}天", d, sim(d, o, c, sig, hold))
        sig = recent(panic | panic20, 5) & (r1 >= 0.015) & (clv >= 0.7)
        report(f"D 同C但 当日涨≥1.5%且收在高位 拿{hold}天", d, sim(d, o, c, sig, hold))
        sig = (r1 >= 0.025)
        report(f"E 不管有没有恐慌: 当日涨≥2.5% 拿{hold}天", d, sim(d, o, c, sig, hold))
