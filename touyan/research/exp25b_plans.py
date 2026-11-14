"""实验 25b：短期规则的卖出方案比较 + ETF 版本。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd, mscore
U = UREL if which == "old" else UALL
d = dict(np.load(f"mkt_{which}.npz")); S = mscore.score(d)
ys = sorted(set(year.tolist()))
COLD = np.load(f"cold{TAG}.npy"); cold = pct_rank(COLD, U)
EPS = np.load(os.path.join(HERE, f"fpanel{TAG}", "eps_ttm.npy"))
pick_score = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
okm = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(pick_score) & (cold >= 0.5) & (EPS > 0)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
def select(day_mask, n=5, cap=2):
    P = np.zeros((T, N), bool)
    for t in np.nonzero(day_mask)[0]:
        idx = np.nonzero(okm[t])[0]
        if len(idx) == 0: continue
        order = idx[np.argsort(-pick_score[t, idx])]
        used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap: continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n: break
    return P
def report(label, tr):
    ret = tr["ret"]; t = tr["t"]
    df = pd.DataFrame({"t": t, "r": ret}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]; gr = g["r"].to_numpy()
    neg = [f"{y%100:02d}:{gr[yr == y].mean()*100:+.1f}" for y in ys if (yr == y).sum() and gr[yr == y].mean() < 0]
    reasons = {k: int((tr['reason'] == v).sum()) for k, v in (("到期", 0), ("止盈", 1), ("止损", 2))}
    print(f"  {label:<28} 笔 {len(ret):5d} 均值 {ret.mean()*100:+.2f}% 中位 {np.median(ret)*100:+.2f}% 胜率 {(ret>0).mean()*100:.0f}% 赚的平均 {ret[ret>0].mean()*100:+.1f}% 亏的平均 {ret[ret<=0].mean()*100:+.1f}% 拿 {tr['days'].mean():.1f}天 最差5% {np.percentile(ret,5)*100:+.1f}% 最差 {ret.min()*100:+.0f}% | 篮子: {gr.mean()*100:+.2f}% 上涨 {(gr>0).mean()*100:.0f}% 最差 {gr.min()*100:+.1f}% 最差一成 {np.percentile(gr,10)*100:+.1f}% | {reasons} | 亏损年: {' '.join(neg) or '无'}")
for thr in (3, 2):
    P = select(S >= thr)
    print(f"===== {which} 分数≥{thr}（{int((S >= thr).sum())} 天） =====")
    for nm, kw in (("拿5天", dict(max_days=5)), ("拿5天 止损8%", dict(max_days=5, stop=0.08)), ("拿5天 止盈8%", dict(max_days=5, target=0.08)), ("拿5天 止盈8% 止损8%", dict(max_days=5, target=0.08, stop=0.08)),
                   ("拿5天 止盈10% 止损8%", dict(max_days=5, target=0.10, stop=0.08)), ("拿5天 止盈10% 止损6%", dict(max_days=5, target=0.10, stop=0.06)), ("拿8天 止盈10% 止损8%", dict(max_days=8, target=0.10, stop=0.08)),
                   ("拿5天 不限高开", dict(max_days=5, max_gap=0.10)), ("拿5天 只买平开或低开", dict(max_days=5, max_gap=0.0))):
        kw = dict(kw); mg = kw.pop("max_gap", 0.02)
        report(nm, trades(P, max_gap=mg, **kw))
# ETF 版本：同样的日子买指数
def load_idx(sym):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); return z["d"], z["o"], z["c"]
print(f"===== {which} ETF 版本（买指数，次日开盘买，拿5天，扣 0.1%）=====")
for sym, name in (("sh000852", "中证1000"), ("sh000905", "中证500"), ("sh000300", "沪深300"), ("sh000985", "中证全指")):
    dd, o, c = load_idx(sym); pos = {int(x): i for i, x in enumerate(dd)}
    for thr in (3, 2):
        rets = []; yrs = []
        for t in np.nonzero(S >= thr)[0]:
            i = pos.get(int(cal[t]))
            if i is None or i + 6 >= len(dd): continue
            rets.append(c[i + 6] / o[i + 1] * 0.999 - 1); yrs.append(int(cal[t]) // 10000)
        r = np.array(rets); yy = np.array(yrs)
        neg = [f"{y%100:02d}:{r[yy == y].mean()*100:+.1f}" for y in sorted(set(yy.tolist())) if r[yy == y].mean() < 0]
        print(f"  {name} 分数≥{thr}: 天数 {len(r)} 均值 {r.mean()*100:+.2f}% 中位 {np.median(r)*100:+.2f}% 上涨 {(r>0).mean()*100:.0f}% 最差 {r.min()*100:+.1f}% | 亏损年: {' '.join(neg) or '无'}")
    allr = np.array([c[i + 6] / o[i + 1] * 0.999 - 1 for i in range(len(dd) - 7) if cal[0] <= dd[i] <= cal[-1]])
    print(f"  {name} 对照(任意一天): {allr.mean()*100:+.2f}% 上涨 {(allr>0).mean()*100:.0f}%")
