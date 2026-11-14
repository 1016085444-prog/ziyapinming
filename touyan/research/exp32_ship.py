"""实验 30：两个板块的最终规则，输出要写进软件的数字（final_{which}.json）。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd, mscore
U = (eligible & (amt20 >= 5e7) & (age >= 250)) if which == "new" else (UREL & (age >= 250))
ys = sorted(set(year.tolist()))
d = dict(np.load(f"mkt_{which}.npz")); S = mscore.score(d); comp = mscore.components(d)
if which == "new":                    # 数据最后一个月不完整，月末判断会错，最后 3 天的月末项去掉
    pass
def _composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)
COLD = _composite([("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]); cold = pct_rank(COLD, U)
# 大盘预估分：在这个口径的池子上重新统计
n_u = np.maximum(U.sum(1), 1)
d["mr"] = np.nanmean(np.where(U, R, np.nan), axis=1); d["upshare"] = (up_lim & U).sum(1) / n_u; d["dnshare"] = (dn_lim & U).sum(1) / n_u
_amt = np.nansum(np.where(U, A, 0), axis=1)
d["amt_rel"] = _amt / np.concatenate([np.full(20, np.nan), np.convolve(_amt, np.ones(20) / 20, "valid")[:-1]])
S = mscore.score(d); comp = mscore.components(d)
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "np_yoy.npy")) / 100.0; EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))      # 这里的 SQ 是累计净利润同比
szp = pct_rank(F("size"), U)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
OUT = {"period": [int(cal[0]), int(cal[-1])], "days": int(T), "pool": int(U.sum(1)[300:].mean())}
def pick(okm, key, days=None, n=5, cap=2):
    P = np.zeros((T, N), bool)
    for t in (range(T) if days is None else np.nonzero(days)[0]):
        idx = np.nonzero(okm[t])[0]
        if len(idx) == 0: continue
        order = idx[np.argsort(-key[t, idx])]; used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap: continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n: break
    return P
def summarize(tr, label, hb=None):
    ret = tr["ret"]; t = tr["t"]; hb = hb or int(round(tr["days"].mean())) + 1
    b = base_of(fwd(hb), U)[t]
    df = pd.DataFrame({"t": t, "r": ret, "ex": ret - b}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]; gr = g["r"].to_numpy(); ge = g["ex"].to_numpy()
    by = {int(y): {"n": int((yr == y).sum()), "ret": float(gr[yr == y].mean()), "ex": float(ge[yr == y].mean())} for y in ys if (yr == y).sum()}
    res = {"n": int(len(ret)), "mean": float(ret.mean()), "median": float(np.median(ret)), "win": float((ret > 0).mean()), "avg_win": float(ret[ret > 0].mean()), "avg_loss": float(ret[ret <= 0].mean()),
           "days": float(tr["days"].mean()), "p5": float(np.percentile(ret, 5)), "p25": float(np.percentile(ret, 25)), "p75": float(np.percentile(ret, 75)), "worst": float(ret.min()),
           "basket_days": int(len(gr)), "basket_mean": float(gr.mean()), "basket_win": float((gr > 0).mean()), "basket_worst": float(gr.min()), "basket_p10": float(np.percentile(gr, 10)),
           "base": float(np.nanmean(b)), "excess": float(ge.mean()), "beat": float((ge > 0).mean()), "by_year": by,
           "stops": int((tr["reason"] == 2).sum()), "early": int((tr["reason"] == 3).sum())}
    neg = [str(y) for y, v in by.items() if v["ret"] < 0]
    print(f"  {label:<36} 笔 {res['n']:5d} 均值 {res['mean']*100:+.2f}% 中位 {res['median']*100:+.2f}% 胜率 {res['win']*100:.0f}% 赚 {res['avg_win']*100:+.1f}% 亏 {res['avg_loss']*100:+.1f}% 拿 {res['days']:.1f}天 | 篮子 {res['basket_mean']*100:+.2f}% 上涨 {res['basket_win']*100:.0f}% 最差 {res['basket_worst']*100:+.1f}% | 随便买 {res['base']*100:+.2f}% 超额 {res['excess']*100:+.2f}% 跑赢 {res['beat']*100:.0f}% | 亏钱的年 {' '.join(neg) or '无'}", flush=True)
    return res
print(f"===== {which} =====")
# ---------- 大盘预估分 ----------
B = {h: base_of(fwd(h), U) for h in (3, 6, 11)}
tab = {}
for lab, m in (("le-1", S <= -1), ("0", S == 0), ("1", S == 1), ("2", S == 2), ("ge3", S >= 3)):
    ok = m & np.isfinite(B[6])
    tab[lab] = {"days": int(ok.sum()), "share": float(ok.mean()), **{f"h{h-1}": float(np.nanmean(B[h][ok])) for h in B}, **{f"up{h-1}": float(np.nanmean(B[h][ok] > 0)) for h in B}}
    print(f"  分数 {lab}: 天数 {tab[lab]['days']} 占 {tab[lab]['share']*100:.0f}% | 2天 {tab[lab]['h2']*100:+.2f}%({tab[lab]['up2']*100:.0f}%) 5天 {tab[lab]['h5']*100:+.2f}%({tab[lab]['up5']*100:.0f}%) 10天 {tab[lab]['h10']*100:+.2f}%({tab[lab]['up10']*100:.0f}%)")
OUT["score_table"] = tab
OUT["score_parts"] = {k: {"days": int((m & np.isfinite(B[6])).sum()), "h5": float(np.nanmean(B[6][m & np.isfinite(B[6])])), "up5": float(np.nanmean(B[6][m & np.isfinite(B[6])] > 0)), "h5_else": float(np.nanmean(B[6][~m & np.isfinite(B[6])]))} for k, (m, w) in comp.items()}
# ---------- 短期 ----------
ps = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
oks = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(ps) & (cold >= 0.5) & (EPS > 0)
OUT["short"] = {}
for thr in (3, 2):
    P = pick(oks, ps, days=S >= thr)
    OUT["short"][f"ge{thr}"] = summarize(trades(P, max_days=5, stop=0.08, max_gap=0.02), f"短期 分数≥{thr} 拿5天 止损8%", hb=6)
    OUT["short"][f"ge{thr}_nostop"] = summarize(trades(P, max_days=5, max_gap=0.02), f"短期 分数≥{thr} 拿5天 不止损", hb=6)
OUT["short"]["everyday"] = summarize(trades(pick(oks, ps), max_days=5, stop=0.08, max_gap=0.02), "短期 对照：每天都选", hb=6)
OUT["short"]["le-1"] = summarize(trades(pick(oks, ps, days=S <= -1), max_days=5, stop=0.08, max_gap=0.02), "短期 对照：只在分数≤-1的日子", hb=6)
# ---------- 中期 ----------
okm = U & valid & (cold >= 0.9) & (szp < 0.7) & (EPS > 0) & (SQ > 0.10) & ~up_lim & ~dn_lim
def sim_mid(P, max_days, flag=None, max_gap=0.03, cost=COST):
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
OUT["mid"] = {"candidates": int(okm.sum(1)[300:].mean())}
P = pick(okm, COLD)
OUT["mid"]["all"] = summarize(sim_mid(P, 60, flag=up_lim), "中期 每天选 拿60天 涨停次日卖")
OUT["mid"]["all_bad"] = summarize(sim_mid(P, 60, flag=up_lim | (SQ <= 0)), "中期 再加：业绩转差次日卖")
OUT["mid"]["hold20"] = summarize(sim_mid(P, 20, flag=up_lim), "中期 拿20天 涨停次日卖")
for lab, m in (("ge2", S >= 2), ("0to1", (S >= 0) & (S <= 1)), ("le-1", S <= -1)):
    OUT["mid"][lab] = summarize(sim_mid(pick(okm, COLD, days=m), 60, flag=up_lim), f"中期 建仓日分数 {lab}")
# 冷热分各组
def grp(G, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {int(y): float(np.nanmean(dex[year == y])) for y in ys if np.isfinite(dex[year == y]).any()}
    return {"ret": float(np.nanmean(dr)), "ex": float(np.nanmean(dex)), "t": float(nw_t(dex, h)), "win": float(np.nanmean(np.where(G, Fh > 0, np.nan))), "by_year": ye, "pos_years": int(sum(1 for v in ye.values() if v > 0)), "years": len(ye)}
OUT["cold"] = {"hot10_h20": grp(cold < 0.1, 21), "hot10_h60": grp(cold < 0.1, 61), "cold10_h20": grp(cold >= 0.9, 21), "cold10_h60": grp(cold >= 0.9, 61),
               "cand_h20": grp(okm, 21), "cand_h60": grp(okm, 61)}
for k, v in OUT["cold"].items():
    print(f"  {k}: 收益 {v['ret']*100:+.2f}% 超额 {v['ex']*100:+.2f}% t={v['t']:.1f} 个股胜率 {v['win']*100:.0f}% 赢 {v['pos_years']}/{v['years']}")
json.dump(OUT, open(f"ship_{which}.json", "w"), ensure_ascii=False, indent=1)
