"""实验 23：大小盘、板块能不能预判。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = UREL if which == "old" else UALL
sz = pct_rank(F("size"), U)
big = U & (sz >= 0.8); small = U & (sz < 0.4); mid = U & (sz >= 0.4) & (sz < 0.8)
def gmean(G, X):
    cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, np.where(G & np.isfinite(X), X, 0).sum(1) / np.maximum((G & np.isfinite(X)).sum(1), 1), np.nan)
F6 = fwd(6); F3 = fwd(3); F21 = fwd(21)
fs6, fb6 = gmean(small, F6), gmean(big, F6); rel6 = fs6 - fb6
fs21, fb21 = gmean(small, F21), gmean(big, F21); rel21 = fs21 - fb21
rs, rb = gmean(small, np.where(valid, R, np.nan)), gmean(big, np.where(valid, R, np.nan))
def cum(x, k):
    c = np.cumsum(np.nan_to_num(np.log1p(x))); return c - np.concatenate([np.full(k, np.nan), c[:-k]])
m = dict(np.load(f"mkt_{which}.npz"))
mr = m["mr"]
print(f"===== {which}: 小盘(市值后40%) vs 大盘(市值前20%)：之后5天 小盘 {np.nanmean(fs6)*100:+.2f}% 大盘 {np.nanmean(fb6)*100:+.2f}% 差 {np.nanmean(rel6)*100:+.2f}%；之后20天 差 {np.nanmean(rel21)*100:+.2f}% =====")
def buckets(nm, x, nb=5):
    ok = np.isfinite(x) & np.isfinite(rel6) & np.isfinite(rel21)
    qs = np.nanquantile(x[ok], np.linspace(0, 1, nb + 1))
    row = f"  {nm:<16}"
    for g in range(nb):
        mm = ok & (x >= qs[g]) & ((x < qs[g + 1]) if g < nb - 1 else (x <= qs[g + 1]))
        row += f" | [{qs[g]*100:+6.1f},{qs[g+1]*100:+6.1f}] 5天:小{np.nanmean(fs6[mm])*100:+.2f} 大{np.nanmean(fb6[mm])*100:+.2f} 差{np.nanmean(rel6[mm])*100:+.2f} 20天差{np.nanmean(rel21[mm])*100:+.2f}"
    print(row)
buckets("小−大 当日", rs - rb); buckets("小−大 5日", cum(rs, 5) - cum(rb, 5)); buckets("小−大 20日", cum(rs, 20) - cum(rb, 20)); buckets("小−大 60日", cum(rs, 60) - cum(rb, 60))
buckets("大盘当日涨跌", mr); buckets("成交额/20日均", m["amt_rel"]); buckets("跌停占比", m["dnshare"]); buckets("涨停占比", m["upshare"])
mon = (cal // 100) % 100
print("  按月份（之后5天 小−大）: " + " ".join(f"{k}月 {np.nanmean(rel6[mon == k])*100:+.2f}" for k in range(1, 13)))
ys = sorted(set(year.tolist()))
print("  按年（之后5天 小−大）: " + " ".join(f"{y%100:02d}:{np.nanmean(rel6[year == y])*100:+.2f}" for y in ys))
# ---------- 板块 ----------
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
names = sorted(set(ind.values())); ix = {n: i for i, n in enumerate(names)}
lab = np.array([ix.get(ind.get(c), -1) for c in codes]); K = len(names)
cols = [np.nonzero(lab == k)[0] for k in range(K)]
keep = [k for k in range(K) if len(cols[k]) >= 8]
def ind_mean(X, mask=None):
    out = np.full((T, len(keep)), np.nan)
    Z = np.where(U & np.isfinite(X), X, np.nan) if mask is None else np.where(mask & np.isfinite(X), X, np.nan)
    for j, k in enumerate(keep):
        sub = Z[:, cols[k]]; n = np.isfinite(sub).sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, j] = np.where(n >= 5, np.nansum(sub, axis=1) / np.maximum(n, 1), np.nan)
    return out
print(f"  板块数 {len(keep)}")
IF6 = ind_mean(F6); IF3 = ind_mean(F3); IF21 = ind_mean(F21)
IR1 = ind_mean(np.where(valid, R, np.nan))
ilvl = np.cumprod(1 + np.nan_to_num(IR1), axis=0)
def ipast(k):
    out = np.full_like(ilvl, np.nan); out[k:] = ilvl[k:] / ilvl[:-k] - 1; return out
ILU = ind_mean(up_lim.astype(np.float32))            # 板块内涨停占比
IDL = ind_mean(dn_lim.astype(np.float32))
IAMT = ind_mean(A / amt20)                          # 板块平均「当日成交额/20日均」
IQ = ind_mean(F("turn20"))
def xs(nm, X, hs=((IF3, "2天"), (IF6, "5天"), (IF21, "20天")), nb=5):
    row = f"  {nm:<18}"
    rk = np.full_like(X, np.nan)
    for t in range(T):
        v = X[t]; ok = np.isfinite(v)
        if ok.sum() >= 20:
            r = np.argsort(np.argsort(v[ok])) / (ok.sum() - 1); rk[t, ok] = r
    for Fh, labh in hs:
        base = np.nanmean(Fh, axis=1)
        vals = []
        for g in range(nb):
            G = (rk >= g / nb) & ((rk < (g + 1) / nb) if g < nb - 1 else (rk <= 1.0)) & np.isfinite(Fh)
            cnt = G.sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                d = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / np.maximum(cnt, 1), np.nan) - base
            vals.append((np.nanmean(d), nw_t(d, 6)))
        row += f" | {labh}: " + " ".join(f"{v*100:+.2f}" for v, _ in vals) + f" (t {vals[0][1]:+.1f}/{vals[-1][1]:+.1f})"
    print(row)
print("  --- 板块横截面：按线索把板块分 5 组（低→高），之后相对全部板块平均的超额% ---")
xs("当日涨幅", IR1); xs("5日涨幅", ipast(5)); xs("20日涨幅", ipast(20)); xs("60日涨幅", ipast(60)); xs("120日涨幅", ipast(120))
xs("板块内涨停占比", ILU); xs("板块内跌停占比", IDL); xs("板块放量程度", IAMT); xs("板块换手水平", IQ)
# 最热板块（当日涨停占比最高的 3 个板块）之后的表现
top3 = np.zeros_like(ILU, bool)
for t in range(T):
    v = ILU[t]; ok = np.isfinite(v)
    if ok.sum() >= 20 and np.nanmax(v) > 0.05:
        idx = np.argsort(-np.where(ok, v, -1))[:3]; top3[t, idx] = True
for Fh, labh in ((IF3, "2天"), (IF6, "5天"), (IF21, "20天")):
    base = np.nanmean(Fh, axis=1); G = top3 & np.isfinite(Fh); cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / np.maximum(cnt, 1), np.nan)
    print(f"  当日涨停最集中的3个板块（板块内涨停≥5%）之后{labh}: 收益 {np.nanmean(d)*100:+.2f}% 超额 {np.nanmean(d - base)*100:+.2f}% t={nw_t(d - base, 6):+.1f} 天数 {int((cnt>0).sum())}")
