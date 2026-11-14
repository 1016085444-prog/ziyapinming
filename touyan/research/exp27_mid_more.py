"""实验 27：中期——候选排序方式、卖出规则（宽止损、业绩转差卖出）、建仓日是否要看大盘预估分。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd, mscore
U = UREL if which == "old" else UALL
ys = sorted(set(year.tolist()))
COLD = np.load(f"cold2{TAG}.npy"); cold = pct_rank(COLD, U)
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
d = dict(np.load(f"mkt_{which}.npz")); S = mscore.score(d)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
okm = U & valid & (cold >= 0.9) & (SQ > 0) & (EPS > 0) & ~up_lim & ~dn_lim
sqc = np.minimum(SQ, 2.0)
orders = {"按冷热分": COLD, "按利润增速": sqc, "冷热分+增速各半": pct_rank(COLD, okm) + pct_rank(sqc, okm), "随机(候选里任取)": None}
rng = np.random.default_rng(7)
def select(key, n=5, cap=2, days=None):
    P = np.zeros((T, N), bool)
    for t in (range(T) if days is None else np.nonzero(days)[0]):
        idx = np.nonzero(okm[t])[0]
        if len(idx) == 0: continue
        order = idx[rng.permutation(len(idx))] if key is None else idx[np.argsort(-key[t, idx])]
        used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap: continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n: break
    return P
def sim_mid(P, max_days, stop=None, flag=None, max_gap=0.03, cost=COST):
    tt, ii = np.nonzero(P); e = tt + 1
    keep = e + max_days + 1 < T; tt, ii, e = tt[keep], ii[keep], e[keep]
    eo = O[e, ii]; pc = PC[e, ii]
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = eo / pc - 1
    ok = np.isfinite(eo) & (gap <= max_gap) & ~open_up[e, ii] & ~open_dn[e, ii] & ~one_line[e, ii]
    tt, ii, e, eo = tt[ok], ii[ok], e[ok], eo[ok]
    n = len(tt); entry = eo.astype(np.float64)
    alive = np.ones(n, bool); exitp = np.full(n, np.nan); days = np.zeros(n, np.int32); reason = np.zeros(n, np.int8); pend = np.zeros(n, bool); pr = np.zeros(n, np.int8)
    for k in range(1, max_days + 7):
        dd = np.minimum(e + k, T - 1); o = O[dd, ii].astype(np.float64); c = C[dd, ii].astype(np.float64); trading = np.isfinite(c) & (e + k < T)
        m = alive & pend & trading; exitp[m] = o[m]; days[m] = k; reason[m] = pr[m]; alive[m] = False
        locked = dn_lim[dd, ii]
        if stop is not None:
            m = alive & trading & (c <= entry * (1 - stop)); mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 2; alive[mm] = False
            mm = m & locked; pend[mm] = True; pr[mm] = 2
        if flag is not None:
            m = alive & trading & ~pend & flag[dd, ii]; pend[m] = True; pr[m] = 3
        if k >= max_days:
            m = alive & trading & ~pend; mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 0; alive[mm] = False
            mm = m & locked; pend[mm] = True; pr[mm] = 0
        if not alive.any(): break
    m = alive
    if m.any():
        dd = np.minimum(e + max_days + 6, T - 1); exitp[m] = Cf[dd[m], ii[m]]; days[m] = max_days + 7
    return {"t": tt, "i": ii, "ret": exitp / entry * (1 - cost) - 1, "days": days, "reason": reason}
def report(label, tr):
    ret = tr["ret"]; t = tr["t"]; hb = int(round(tr["days"].mean())) + 1
    b = base_of(fwd(hb), U)[t]
    df = pd.DataFrame({"t": t, "r": ret, "ex": ret - b}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]; gr = g["r"].to_numpy(); ge = g["ex"].to_numpy()
    negx = [f"{y%100:02d}" for y in ys if (yr == y).sum() and ge[yr == y].mean() < 0]; negr = [f"{y%100:02d}" for y in ys if (yr == y).sum() and gr[yr == y].mean() < 0]
    rs = {k: int((tr['reason'] == v).sum()) for k, v in (("到期", 0), ("止损", 2), ("提前卖", 3))}
    print(f"  {label:<40} 笔 {len(ret):5d} 均值 {ret.mean()*100:+.2f}% 中位 {np.median(ret)*100:+.2f}% 胜率 {(ret>0).mean()*100:.0f}% 赚 {ret[ret>0].mean()*100:+.1f}% 亏 {ret[ret<=0].mean()*100:+.1f}% 拿 {tr['days'].mean():.0f}天 最差5% {np.percentile(ret,5)*100:+.1f}% | 篮子 {gr.mean()*100:+.2f}% 上涨 {(gr>0).mean()*100:.0f}% 超额 {ge.mean()*100:+.2f}% 跑赢 {(ge>0).mean()*100:.0f}% | {rs} | 超额为负的年 {' '.join(negx) or '无'} | 亏钱的年 {' '.join(negr) or '无'}", flush=True)
hot = up_lim
hot2 = up_lim | (cold < 0.2)
bad = (SQ <= 0)
print(f"===== {which} =====")
print("--- A. 候选怎么排序（拿60天，涨停次日卖） ---")
PS = {}
for nm, key in orders.items():
    PS[nm] = select(key); report(nm, sim_mid(PS[nm], 60, flag=hot))
P = PS["冷热分+增速各半"]
print("--- B. 卖出规则（候选按 冷热分+增速各半） ---")
for nm, kw in (("拿60天", dict(max_days=60)), ("拿60天 涨停次日卖", dict(max_days=60, flag=hot)), ("拿60天 涨停或变热次日卖", dict(max_days=60, flag=hot2)),
               ("拿60天 涨停/变热/业绩转差 次日卖", dict(max_days=60, flag=hot2 | bad)), ("拿60天 涨停次日卖 止损20%", dict(max_days=60, flag=hot, stop=0.20)),
               ("拿60天 涨停次日卖 止损25%", dict(max_days=60, flag=hot, stop=0.25)), ("拿40天 涨停次日卖", dict(max_days=40, flag=hot)), ("拿20天 涨停次日卖", dict(max_days=20, flag=hot))):
    report(nm, sim_mid(P, **kw))
print("--- C. 建仓日的大盘预估分（拿60天 涨停次日卖；拿20天 涨停次日卖） ---")
for lab, days in (("分数≥2", S >= 2), ("分数0~1", (S >= 0) & (S <= 1)), ("分数≤-1", S <= -1)):
    Pd = select(orders["冷热分+增速各半"], days=days)
    report(f"{lab}（{int(days.sum())}天）拿60天", sim_mid(Pd, 60, flag=hot))
    report(f"{lab}（{int(days.sum())}天）拿20天", sim_mid(Pd, 20, flag=hot))
