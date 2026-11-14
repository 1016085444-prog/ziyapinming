"""实验 25：短期板块的完整规则模拟。大盘预估分达标的日子，按「跌得多、离高点远、没人追捧」选 5 只，次日开盘买，按计划卖。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, pandas as pd, mscore
U = UREL if which == "old" else UALL
d = dict(np.load(f"mkt_{which}.npz")); S = mscore.score(d); comp = mscore.components(d)
ys = sorted(set(year.tolist()))
# 冷热分：四项「被追捧程度」的反向平均百分位
def composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.75, acc / cnt, np.nan)
COLD = composite([("id60", -1), ("abn20_250", -1), ("pvc20", -1), ("clv20", -1)])
np.save(f"cold{TAG}.npy", COLD)
cold = pct_rank(COLD, U)
EPS = np.load(os.path.join(HERE, f"fpanel{TAG}", "eps_ttm.npy"))
pick_score = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
ok_stock = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(pick_score) & (cold >= 0.5)
ok_profit = ok_stock & (EPS > 0)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
def select(day_mask, okm, n=5, cap=2):
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
def report(label, tr, hbase):
    if len(tr["ret"]) == 0: print(f"  {label}: 无"); return
    ret = tr["ret"]; t = tr["t"]
    b = base_of(fwd(hbase), U)[t]
    df = pd.DataFrame({"t": t, "r": ret, "ex": ret - b}); g = df.groupby("t").mean()
    yr = year[g.index.to_numpy()]
    yrow = " ".join(f"{y%100:02d}:{g['r'].to_numpy()[yr == y].mean()*100:+.1f}({int((yr == y).sum())})" for y in ys if (yr == y).sum())
    neg = sum(1 for y in ys if (yr == y).sum() and g['r'].to_numpy()[yr == y].mean() < 0)
    reasons = {k: int((tr['reason'] == v).sum()) for k, v in (("到期", 0), ("止盈", 1), ("止损", 2))}
    print(f"  {label:<40} 笔 {len(ret):5d} 每笔均值 {ret.mean()*100:+.2f}% 中位 {np.median(ret)*100:+.2f}% 胜率 {(ret>0).mean()*100:.0f}% 平均拿 {tr['days'].mean():.1f}天 最差5% {np.percentile(ret,5)*100:+.1f}% | 按天(5只一篮子): 均值 {g['r'].mean()*100:+.2f}% 上涨 {(g['r']>0).mean()*100:.0f}% 最差 {g['r'].min()*100:+.1f}% 超额 {g['ex'].mean()*100:+.2f}% | {reasons} | 亏损年 {neg} | {yrow}")
print(f"===== {which}: 分数分布: " + " ".join(f"{k}:{int((S == k).sum())}" for k in range(int(S.min()), int(S.max()) + 1)) + " =====")
for thr in (3, 2):
    days = S >= thr
    print(f"--- 分数≥{thr}（{int(days.sum())} 天）---")
    for nm, okm in (("只看技术条件", ok_stock), ("加：在赚钱", ok_profit)):
        P = select(days, okm)
        for plan_nm, kw in (("拿5天", dict(max_days=5)), ("拿5天 止盈6%", dict(max_days=5, target=0.06)), ("拿5天 止盈6% 止损7%", dict(max_days=5, target=0.06, stop=0.07)),
                            ("拿8天 止盈8%", dict(max_days=8, target=0.08)), ("拿8天 止盈8% 止损8%", dict(max_days=8, target=0.08, stop=0.08)), ("拿3天", dict(max_days=3))):
            tr = trades(P, max_gap=0.02, **kw)
            report(f"{nm} | {plan_nm}", tr, int(round(tr['days'].mean())) + 1 if len(tr['ret']) else 6)
    # 对照：同样的日子随便买 5 天
    b = base_of(fwd(6), U)[days]; b = b[np.isfinite(b)]
    print(f"  对照：同样的日子全市场随便买拿5天: {b.mean()*100:+.2f}% 上涨 {(b>0).mean()*100:.0f}% 最差 {b.min()*100:+.1f}%")
# 对照：不看大盘分数，每天都按同样规则选 5 只
P = select(np.ones(T, bool), ok_profit)
tr = trades(P, max_gap=0.02, max_days=5, target=0.06)
report("对照：每天都选（不看大盘）| 拿5天 止盈6%", tr, 6)
P = select(S <= -1, ok_profit)
tr = trades(P, max_gap=0.02, max_days=5, target=0.06)
report("对照：只在分数≤-1的日子选 | 拿5天 止盈6%", tr, 6)
