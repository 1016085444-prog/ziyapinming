"""实验 26：中期板块完整规则。冷热分最高的一成 + 在赚钱 + 最新单季利润同比增长；每天取 5 只（同板块最多 2 只）。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd
U = UREL if which == "old" else UALL
ys = sorted(set(year.tolist()))
def composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.75, acc / cnt, np.nan)
COLD = composite([("id60", -1), ("abn20_250", -1), ("pvr20", -1), ("clv20", -1)])
np.save(f"cold2{TAG}.npy", COLD)
cold = pct_rank(COLD, U)
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
def yearly(G, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    pos = sum(1 for v in ye.values() if v > 0)
    return f"每天{int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0:4d}只 收益 {np.nanmean(dr)*100:+.2f}% 超额 {np.nanmean(dex)*100:+.2f}% t={nw_t(dex, h):.1f} 个股胜率 {np.nanmean(np.where(G, Fh > 0, np.nan))*100:.0f}% 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items())
print(f"===== {which}: 冷热分（盘中拉升、放量、量价同向、收在高位 四项反向）=====")
for h in (21, 41, 61):
    print(f"  最冷10% h{h-1}: " + yearly(cold >= 0.9, h))
    print(f"  最冷10%+赚钱+单季同比>0 h{h-1}: " + yearly((cold >= 0.9) & (SQ > 0) & (EPS > 0), h))
print(f"  最热10% h20: " + yearly(cold < 0.1, 21)); print(f"  最热10% h60: " + yearly(cold < 0.1, 61))
print(f"  最热20% h60: " + yearly(cold < 0.2, 61))
# 每天 5 只的完整模拟
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
okm = U & valid & (cold >= 0.9) & (SQ > 0) & (EPS > 0) & ~up_lim & ~dn_lim
def select(n=5, cap=2):
    P = np.zeros((T, N), bool)
    for t in range(T):
        idx = np.nonzero(okm[t])[0]
        if len(idx) == 0: continue
        order = idx[np.argsort(-COLD[t, idx])]
        used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap: continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n: break
    return P
P = select()
def sim_mid(P, max_days, stop=None, flag=None, max_gap=0.03, cost=COST):
    """flag[t,i] 为真（收盘后确认）→ 第二天开盘卖。stop：收盘跌破买入价的 stop 就在收盘卖。"""
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
    negx = sum(1 for y in ys if (yr == y).sum() and ge[yr == y].mean() < 0)
    yrow = " ".join(f"{y%100:02d}:{gr[yr == y].mean()*100:+.1f}/{ge[yr == y].mean()*100:+.1f}" for y in ys if (yr == y).sum())
    rs = {k: int((tr['reason'] == v).sum()) for k, v in (("到期", 0), ("止损", 2), ("涨停/变热卖出", 3))}
    print(f"  {label:<34} 笔 {len(ret):5d} 均值 {ret.mean()*100:+.2f}% 中位 {np.median(ret)*100:+.2f}% 胜率 {(ret>0).mean()*100:.0f}% 赚的平均 {ret[ret>0].mean()*100:+.1f}% 亏的平均 {ret[ret<=0].mean()*100:+.1f}% 拿 {tr['days'].mean():.0f}天 最差5% {np.percentile(ret,5)*100:+.1f}% | 篮子: {gr.mean()*100:+.2f}% 上涨 {(gr>0).mean()*100:.0f}% 超额 {ge.mean()*100:+.2f}% 跑赢随便买 {(ge>0).mean()*100:.0f}% | {rs} | 超额为负的年份 {negx} | 分年(收益/超额): {yrow}")
hot_flag = up_lim
hot_flag2 = up_lim | (cold < 0.2)
print(f"--- 每天 5 只的完整模拟 ---")
for nm, kw in (("拿60天", dict(max_days=60)), ("拿40天", dict(max_days=40)), ("拿20天", dict(max_days=20)),
               ("拿60天 止损12%", dict(max_days=60, stop=0.12)), ("拿60天 止损15%", dict(max_days=60, stop=0.15)),
               ("拿60天 涨停次日卖", dict(max_days=60, flag=hot_flag)), ("拿60天 涨停或变热次日卖", dict(max_days=60, flag=hot_flag2)),
               ("拿60天 止损15% 涨停次日卖", dict(max_days=60, stop=0.15, flag=hot_flag)), ("拿40天 止损12% 涨停次日卖", dict(max_days=40, stop=0.12, flag=hot_flag)),
               ("拿60天 高开≤1%才买", dict(max_days=60, max_gap=0.01))):
    report(nm, sim_mid(P, **kw))
