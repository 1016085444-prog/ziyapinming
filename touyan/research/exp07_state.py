"""实验 7：市场状态。①大盘急跌之后，随便买的收益；②不同状态下「跌得多的」是否反弹。"""
from feat import *
import numpy as np
U = UALL
mr = np.nanmean(np.where(U, R, np.nan), axis=1)            # 全市场平均日涨跌
lvl = np.cumprod(1 + np.nan_to_num(mr))                    # 等权指数
def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
m1, m3, m5, m10, m20 = mret(1), mret(3), mret(5), mret(10), mret(20)
dn_share = np.nansum(np.where(U, dn_lim, 0), axis=1) / U.sum(1)       # 跌停占比
r5 = F("r5")
down5 = np.nanmean(np.where(U, r5 < -0.10, np.nan), axis=1)           # 5 天跌超 10% 的占比
ma20 = roll_mean(Cf, 20)
below = np.nanmean(np.where(U, Cf < ma20, np.nan), axis=1)            # 在 20 日线下方的占比
lo20 = np.nanmean(np.where(U, Cf <= roll_min(L, 20, 10) * 1.01, np.nan), axis=1)   # 创 20 日新低附近的占比
HS = (2, 4, 6, 11, 21)
B = {h: base_of(fwd(h), U) for h in HS}
def show(name, x, bins):
    print(f"--- 按「{name}」分组：之后在全市场随便买（次日开盘买，扣费）的平均收益 / 胜率(天) ---")
    for lo, hi in bins:
        m = (x >= lo) & (x < hi)
        row = f"  [{lo:+.3f},{hi:+.3f}) 天数 {int(m.sum()):4d}: "
        for h in HS:
            b = B[h][m]; b = b[np.isfinite(b)]
            row += f"h{h-1}: {b.mean()*100:+.2f}%/{(b>0).mean()*100:.0f}%  " if len(b) else "h: -  "
        print(row)
show("当日大盘涨跌", m1, [(-1, -0.04), (-0.04, -0.025), (-0.025, -0.015), (-0.015, -0.005), (-0.005, 0.005), (0.005, 0.015), (0.015, 0.025), (0.025, 1)])
show("3日大盘涨跌", m3, [(-1, -0.08), (-0.08, -0.05), (-0.05, -0.03), (-0.03, -0.01), (-0.01, 0.01), (0.01, 0.03), (0.03, 0.05), (0.05, 1)])
show("5日大盘涨跌", m5, [(-1, -0.10), (-0.10, -0.07), (-0.07, -0.04), (-0.04, -0.02), (-0.02, 0.02), (0.02, 0.04), (0.04, 0.07), (0.07, 1)])
show("20日大盘涨跌", m20, [(-1, -0.15), (-0.15, -0.10), (-0.10, -0.05), (-0.05, 0), (0, 0.05), (0.05, 0.10), (0.10, 1)])
show("跌停占比", dn_share, [(0, 0.002), (0.002, 0.01), (0.01, 0.03), (0.03, 0.08), (0.08, 1)])
show("5天跌超10%的占比", down5, [(0, 0.02), (0.02, 0.05), (0.05, 0.15), (0.15, 0.3), (0.3, 1)])
show("20日线下方占比", below, [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 0.9), (0.9, 1.01)])
show("20日新低附近占比", lo20, [(0, 0.05), (0.05, 0.15), (0.15, 0.3), (0.3, 0.5), (0.5, 1.01)])
# 分年度：5日大盘跌超7% 之后
for nm, cond in (("5日大盘跌超7%", m5 < -0.07), ("3日大盘跌超5%", m3 < -0.05), ("20日线下方占比>90%", below > 0.9), ("跌停占比>3%", dn_share > 0.03)):
    print(f"--- 分年度：{nm} 之后随便买 5 天 / 10 天 ---")
    for y in sorted(set(year.tolist())):
        m = cond & (year == y)
        if m.sum():
            b6 = B[6][m]; b11 = B[11][m]
            print(f"   {y}: 天数 {int(m.sum()):3d}  5天 {np.nanmean(b6)*100:+.2f}%  10天 {np.nanmean(b11)*100:+.2f}%")
# ② 不同状态下，个股 5 日跌幅最大的 10%，相对随便买的超额
print("--- 个股 5 日跌幅最大 10% 的超额（按 5 日大盘涨跌分组） ---")
for h in (3, 6, 11):
    Fh = fwd(h); M = U & np.isfinite(Fh) & np.isfinite(r5)
    pr = pct_rank(r5, M); b = base_of(Fh, M)
    G = M & (pr < 0.1); cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dex = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan) - b
    for lo, hi in [(-1, -0.07), (-0.07, -0.04), (-0.04, -0.02), (-0.02, 0.02), (0.02, 0.04), (0.04, 1)]:
        m = (m5 >= lo) & (m5 < hi) & np.isfinite(dex)
        print(f"   h={h-1} 大盘5日 [{lo:+.2f},{hi:+.2f}) 天数 {int(m.sum()):4d}: 超额 {dex[m].mean()*100:+.2f}%  随便买 {b[m].mean()*100:+.2f}%")
