"""实验 34：短期选股里，跌得特别狠的（自由落体）要不要排除。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd, mscore
U = ((eligible & (amt20 >= 5e7)) if which == "new" else UREL) & (age >= 250)
ys = sorted(set(year.tolist()))
def _composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)
COLD = _composite([("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]); cold = pct_rank(COLD, U)
d = dict(np.load(f"mkt_{which}.npz"))
n_u = np.maximum(U.sum(1), 1)
d["mr"] = np.nanmean(np.where(U, R, np.nan), axis=1); d["upshare"] = (up_lim & U).sum(1) / n_u; d["dnshare"] = (dn_lim & U).sum(1) / n_u
_amt = np.nansum(np.where(U, A, 0), axis=1)
d["amt_rel"] = _amt / np.concatenate([np.full(20, np.nan), np.convolve(_amt, np.ones(20) / 20, "valid")[:-1]])
S = mscore.score(d)
EPS = np.load(os.path.join(HERE, f"fpanel{TAG}", "eps_ttm.npy"))
r5 = F("r5"); r20 = F("r20"); hi = F("hi250")
ps = (1 - pct_rank(r5, U)) + (1 - pct_rank(r20, U)) + (1 - pct_rank(hi, U)) + cold
oks = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(ps) & (cold >= 0.5) & (EPS > 0)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
def pick(okm, days, n=5, cap=2):
    P = np.zeros((T, N), bool)
    for t in np.nonzero(days)[0]:
        idx = np.nonzero(okm[t])[0]
        if len(idx) == 0: continue
        order = idx[np.argsort(-ps[t, idx])]; used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap: continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n: break
    return P
def rep(label, P):
    tr = trades(P, max_days=5, stop=0.08, max_gap=0.02)
    ret = tr["ret"]; t = tr["t"]
    if len(ret) == 0: print(f"  {label}: 无"); return
    df = pd.DataFrame({"t": t, "r": ret}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]; gr = g["r"].to_numpy()
    neg = [f"{y%100:02d}:{gr[yr == y].mean()*100:+.1f}" for y in ys if (yr == y).sum() and gr[yr == y].mean() < 0]
    print(f"  {label:<34} 笔 {len(ret):5d} 均值 {ret.mean()*100:+.2f}% 中位 {np.median(ret)*100:+.2f}% 胜率 {(ret>0).mean()*100:.0f}% 最差5% {np.percentile(ret,5)*100:+.1f}% | 篮子 {gr.mean()*100:+.2f}% 上涨 {(gr>0).mean()*100:.0f}% 最差 {gr.min()*100:+.1f}% | 亏损年 {' '.join(neg) or '无'}", flush=True)
days = S >= 3
print(f"===== {which} 分数≥3（{int(days.sum())} 天） =====")
# 全部候选按 20 日跌幅分组的平均（不限 5 只）
F6 = fwd(6)
for lab, lo, hi_ in (("20日跌>40%", -1, -0.40), ("跌30–40%", -0.40, -0.30), ("跌20–30%", -0.30, -0.20), ("跌10–20%", -0.20, -0.10), ("跌0–10%", -0.10, 0.0), ("涨", 0.0, 9)):
    G = oks & (r20 >= lo) & (r20 < hi_) & np.isfinite(F6) & days[:, None]
    v = F6[G]
    if len(v): print(f"  候选里 {lab}: {len(v)} 次 平均 {v.mean()*100:+.2f}% 中位 {np.median(v)*100:+.2f}% 胜率 {(v>0).mean()*100:.0f}% 最差5% {np.percentile(v,5)*100:+.1f}%")
rep("原规则", pick(oks, days))
for cap in (-0.40, -0.30, -0.25, -0.20):
    rep(f"加：近20日跌幅不超过 {-cap*100:.0f}%", pick(oks & (r20 >= cap), days))
for cap in (-0.20, -0.15, -0.12):
    rep(f"加：近5日跌幅不超过 {-cap*100:.0f}%", pick(oks & (r5 >= cap), days))
rep("加：20日≤30% 且 5日≤15%", pick(oks & (r20 >= -0.30) & (r5 >= -0.15), days))
rep("加：离一年高点不超过 60%", pick(oks & (hi >= -0.60), days))
