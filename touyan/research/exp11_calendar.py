"""实验 11：月初效应、星期效应在指数长历史（2005–2026）上是否成立。"""
import numpy as np, os, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
def load(sym, start=20050101):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); m = z["d"] >= start
    return z["d"][m], z["o"][m], z["c"][m]
def tstat(x):
    x = x[np.isfinite(x)]; return x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if len(x) > 5 else np.nan
for sym, name in (("sh000985", "中证全指"), ("sh000852", "中证1000"), ("sh000300", "沪深300"), ("sh000001", "上证指数")):
    d, o, c = load(sym); n = len(d)
    r = np.full(n, np.nan); r[1:] = c[1:] / c[:-1] - 1
    ov = np.full(n, np.nan); ov[1:] = o[1:] / c[:-1] - 1
    idr = c / o - 1
    dates = [datetime.date(int(x) // 10000, int(x) // 100 % 100, int(x) % 100) for x in d]
    ym = np.array([x.year * 100 + x.month for x in dates]); yr = d // 10000
    pos = np.zeros(n, int); rev = np.zeros(n, int)
    for v in np.unique(ym):
        idx = np.nonzero(ym == v)[0]; pos[idx] = np.arange(1, len(idx) + 1); rev[idx] = np.arange(len(idx), 0, -1)
    wd = np.array([x.weekday() for x in dates])
    print(f"===== {name} {d[0]}–{d[-1]}：日均 {np.nanmean(r)*1e4:+.1f}bp；隔夜 {np.nanmean(ov)*1e4:+.1f}bp 日内 {np.nanmean(idr)*1e4:+.1f}bp =====")
    def line(lab, m):
        seg = [(2005, 2010), (2011, 2016), (2017, 2021), (2022, 2026)]
        s = " ".join(f"{a%100:02d}-{b%100:02d}:{np.nanmean(r[m & (yr >= a) & (yr <= b)])*1e4:+.0f}" for a, b in seg)
        print(f"   {lab:<10} 天数 {int(m.sum()):4d} 平均 {np.nanmean(r[m])*1e4:+6.1f}bp 上涨 {np.nanmean(r[m] > 0)*100:.0f}% t={tstat(r[m]):+.1f} | 分段(bp) {s}")
    for lab, m in (("月初第1天", pos == 1), ("月初第2天", pos == 2), ("月初第3天", pos == 3), ("倒数第2天", rev == 2), ("月末最后1天", rev == 1), ("其余", (pos > 3) & (rev > 2))):
        line(lab, m)
    for k, nm in enumerate("周一 周二 周三 周四 周五".split()):
        line(nm, wd == k)
    # 月末最后一天开盘买，下月第一天收盘卖
    last = np.nonzero(rev == 1)[0]; last = last[last + 1 < n]
    tr = c[last + 1] / o[last] - 1
    y2 = yr[last]
    print(f"   【月末最后1天开盘买，下月第1天收盘卖】次数 {len(tr)} 平均 {tr.mean()*100:+.2f}% 胜率 {(tr>0).mean()*100:.0f}% t={tstat(tr):+.1f} 最差 {tr.min()*100:+.1f}% | 05-10:{tr[(y2<=2010)].mean()*100:+.2f}% 11-16:{tr[(y2>=2011)&(y2<=2016)].mean()*100:+.2f}% 17-21:{tr[(y2>=2017)&(y2<=2021)].mean()*100:+.2f}% 22-26:{tr[y2>=2022].mean()*100:+.2f}%")
    # 倒数第2天收盘买 → 下月第1天收盘卖
    l2 = np.nonzero(rev == 2)[0]; l2 = l2[l2 + 2 < n]
    tr = c[l2 + 2] / c[l2] - 1; y2 = yr[l2]
    print(f"   【倒数第2天收盘买，下月第1天收盘卖】次数 {len(tr)} 平均 {tr.mean()*100:+.2f}% 胜率 {(tr>0).mean()*100:.0f}% t={tstat(tr):+.1f} | 05-10:{tr[(y2<=2010)].mean()*100:+.2f}% 11-16:{tr[(y2>=2011)&(y2<=2016)].mean()*100:+.2f}% 17-21:{tr[(y2>=2017)&(y2<=2021)].mean()*100:+.2f}% 22-26:{tr[y2>=2022].mean()*100:+.2f}%")
    # 周五收盘买 → 周二收盘卖（用周内位置近似）
    fri = np.nonzero((wd == 4))[0]; fri = fri[fri + 2 < n]
    tr = c[fri + 2] / c[fri] - 1; y2 = yr[fri]
    print(f"   【周五收盘买，隔两个交易日收盘卖】次数 {len(tr)} 平均 {tr.mean()*100:+.2f}% 胜率 {(tr>0).mean()*100:.0f}% t={tstat(tr):+.1f} | 05-10:{tr[(y2<=2010)].mean()*100:+.2f}% 11-16:{tr[(y2>=2011)&(y2<=2016)].mean()*100:+.2f}% 17-21:{tr[(y2>=2017)&(y2<=2021)].mean()*100:+.2f}% 22-26:{tr[y2>=2022].mean()*100:+.2f}%")
