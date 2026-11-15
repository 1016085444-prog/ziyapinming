"""实验 33：大小盘预判的简单打分，在两个十年里检验。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = ((eligible & (amt20 >= 5e7)) if which == "new" else UREL) & (age >= 250)
sz = pct_rank(F("size"), U)
big = U & (sz >= 0.8); small = U & (sz < 0.4)
def gmean(G, X):
    M = G & np.isfinite(X); n = M.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, np.where(M, X, 0).sum(1) / np.maximum(n, 1), np.nan)
F6 = fwd(6); F21 = fwd(21)
rel6 = gmean(small, F6) - gmean(big, F6); rel21 = gmean(small, F21) - gmean(big, F21)
fs6, fb6 = gmean(small, F6), gmean(big, F6)
Rv = np.where(valid, R, np.nan)
rs, rb = gmean(small, Rv), gmean(big, Rv)
def cum(x, k):
    c = np.cumsum(np.nan_to_num(np.log1p(x))); return c - np.concatenate([np.full(k, np.nan), c[:-k]])
style5 = cum(rs, 5) - cum(rb, 5)
n_u = np.maximum(U.sum(1), 1)
mr = np.nanmean(np.where(U, R, np.nan), axis=1); upshare = (up_lim & U).sum(1) / n_u
mon = (cal // 100) % 100
score = (style5 >= 0.013).astype(int) + ((mr >= 0.01) | (upshare >= 0.018)).astype(int) - (upshare < 0.007).astype(int) + (mon == 2).astype(int) - np.isin(mon, (4, 6, 12)).astype(int)
ys = sorted(set(year.tolist()))
print(f"===== {which}: 小盘−大盘 之后5天 平均 {np.nanmean(rel6)*100:+.2f}%，之后20天 {np.nanmean(rel21)*100:+.2f}% =====")
for lab, m in (("≤-1", score <= -1), ("0", score == 0), ("≥1", score >= 1), ("≥2", score >= 2)):
    ok = m & np.isfinite(rel6) & np.isfinite(rel21)
    print(f"  风格分 {lab}: 天数 {int(ok.sum())}（{ok.mean()*100:.0f}%） 5天: 小盘 {np.nanmean(fs6[ok])*100:+.2f}% 大盘 {np.nanmean(fb6[ok])*100:+.2f}% 差 {np.nanmean(rel6[ok])*100:+.2f}%（小盘赢的天数 {np.nanmean(rel6[ok] > 0)*100:.0f}%） 20天差 {np.nanmean(rel21[ok])*100:+.2f}% | 分年(5天差): " +
          " ".join(f"{y%100:02d}:{np.nanmean(rel6[ok & (year == y)])*100:+.1f}" for y in ys if (ok & (year == y)).sum() > 5))
