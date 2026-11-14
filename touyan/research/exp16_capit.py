"""实验 16：「大面积跌停」之后。两个十年合并看；按阈值、持有期、分年度、最差情况。"""
import os, sys, subprocess, json
import numpy as np
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
U = UREL if which == "old" else UALL
dnshare = np.nansum(np.where(U, dn_lim, 0), axis=1) / np.maximum(U.sum(1), 1)
upshare = np.nansum(np.where(U, up_lim, 0), axis=1) / np.maximum(U.sum(1), 1)
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
lvl = np.cumprod(1 + np.nan_to_num(mr))
def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
m1, m5, m20 = mret(1), mret(5), mret(20)
HS = (3, 4, 6, 9, 11, 21)
B = {h: base_of(fwd(h), U) for h in HS}
ys = sorted(set(year.tolist()))
out = {"cal": cal.tolist(), "dnshare": dnshare.tolist(), "m1": np.nan_to_num(m1).tolist(), "m5": np.nan_to_num(m5).tolist(), "m20": np.nan_to_num(m20).tolist(),
       **{f"b{h}": np.where(np.isfinite(B[h]), B[h], 0).tolist() for h in HS}, **{f"ok{h}": np.isfinite(B[h]).tolist() for h in HS}}
json.dump(out, open(f"capit_{which}.json", "w"))
def state(nm, cond):
    cond = cond & np.isfinite(B[21])
    if cond.sum() == 0: print(f"  {nm}: 无"); return
    idx = np.nonzero(cond)[0]
    first = [i for k, i in enumerate(idx) if k == 0 or i - idx[k - 1] > 5]
    row = f"  {nm:<30} 天数 {int(cond.sum()):3d} 轮 {len(first):3d} | " + " ".join(f"h{h-1}: {np.nanmean(B[h][cond])*100:+.2f}%/{np.nanmean(B[h][cond] > 0)*100:.0f}%" for h in HS)
    b6 = B[6][cond]
    row += f" | 5天: 中位 {np.median(b6)*100:+.1f}% 最差 {b6.min()*100:+.1f}% 最差一成 {np.percentile(b6, 10)*100:+.1f}%"
    row += " | 分年: " + " ".join(f"{y%100:02d}:{np.nanmean(B[6][cond & (year == y)])*100:+.1f}({int((cond & (year == y)).sum())})" for y in ys if (cond & (year == y)).sum())
    print(row)
print(f"===== {which}: {cal[0]}–{cal[-1]}，池内平均 {int(U.sum(1).mean())} 只；跌停占比分布: ≥1% {int((dnshare>=0.01).sum())}天 ≥2% {int((dnshare>=0.02).sum())} ≥3% {int((dnshare>=0.03).sum())} ≥5% {int((dnshare>=0.05).sum())} ≥8% {int((dnshare>=0.08).sum())} =====")
state("全部日子", np.ones(T, bool))
for th in (0.01, 0.02, 0.03, 0.05, 0.08, 0.15):
    state(f"跌停占比≥{th*100:.0f}%", dnshare >= th)
state("跌停占比 1%~3%", (dnshare >= 0.01) & (dnshare < 0.03))
state("跌停占比 3%~8%", (dnshare >= 0.03) & (dnshare < 0.08))
state("跌停≥3% 且 5日跌≥5%", (dnshare >= 0.03) & (m5 <= -0.05))
state("跌停≥3% 且 5日跌<5%", (dnshare >= 0.03) & (m5 > -0.05))
state("跌停≥2% 且 当日跌≥3%", (dnshare >= 0.02) & (m1 <= -0.03))
state("当日跌≥4%（全市场平均）", m1 <= -0.04)
state("当日跌≥3%", m1 <= -0.03)
state("当日跌≥5%", m1 <= -0.05)
state("涨停占比≥5%", upshare >= 0.05)
state("当日涨≥3%", m1 >= 0.03)
