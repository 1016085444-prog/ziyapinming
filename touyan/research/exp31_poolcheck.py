"""实验 31：软件里的股票池口径（20 日均成交额≥5000万、上市满250天）下，规则是否照样成立；增长条件用「累计同比」行不行。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, mscore
ys = sorted(set(year.tolist()))
thr = 5e7 if which == "new" else None
U = (eligible & (amt20 >= 5e7) & (age >= 250)) if which == "new" else (UREL & (age >= 250))
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); NPY = np.load(os.path.join(HERE, FPD, "np_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
def composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)
COLD = composite([("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]); cold = pct_rank(COLD, U)
szp = pct_rank(F("size"), U)
def yearly(G, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    pos = sum(1 for v in ye.values() if v > 0)
    return f"每天{int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0:4d}只 收益 {np.nanmean(dr)*100:+.2f}% 超额 {np.nanmean(dex)*100:+.2f}% t={nw_t(dex, h):.1f} 胜率 {np.nanmean(np.where(G, Fh > 0, np.nan))*100:.0f}% 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items())
print(f"===== {which}: 池内平均 {int(U.sum(1)[300:].mean())} 只 =====")
base = (cold >= 0.9) & (szp < 0.7) & (EPS > 0)
print("  单季同比>10% h60: " + yearly(base & (SQ > 0.10), 61))
print("  累计同比>10% h60: " + yearly(base & (NPY > 10), 61))
print("  单季>10% 且 累计>0 h60: " + yearly(base & (SQ > 0.10) & (NPY > 0), 61))
print("  单季同比>10% h20: " + yearly(base & (SQ > 0.10), 21))
print("  累计同比>10% h20: " + yearly(base & (NPY > 10), 21))
print("  最热10% h60: " + yearly(cold < 0.1, 61))
# 大盘预估分（在这个口径的池子上重新算全市场统计）
n_u = np.maximum(U.sum(1), 1)
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
upshare = (up_lim & U).sum(1) / n_u; dnshare = (dn_lim & U).sum(1) / n_u
amt_tot = np.nansum(np.where(U, A, 0), axis=1)
amt_rel = amt_tot / np.concatenate([np.full(20, np.nan), np.convolve(amt_tot, np.ones(20) / 20, "valid")[:-1]])
d0 = dict(np.load(f"mkt_{which}.npz"))
d = dict(d0); d.update(mr=mr, upshare=upshare, dnshare=dnshare, amt_rel=amt_rel)
S = mscore.score(d); S0 = mscore.score(d0)
print(f"  分数和原口径一致的天数占比: {(S == S0).mean()*100:.0f}%；相差不超过1分: {(np.abs(S - S0) <= 1).mean()*100:.0f}%")
B6 = base_of(fwd(6), U)
for lab, m in (("≤-1", S <= -1), ("0", S == 0), ("1", S == 1), ("2", S == 2), ("≥3", S >= 3)):
    ok = m & np.isfinite(B6)
    print(f"  分数 {lab}: 天数 {int(ok.sum())} 5天 {np.nanmean(B6[ok])*100:+.2f}% 上涨 {np.nanmean(B6[ok] > 0)*100:.0f}%")
