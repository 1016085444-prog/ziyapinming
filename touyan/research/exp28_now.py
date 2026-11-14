"""看看按最终规则，最近的状态和今天的入选。"""
import os, json
os.environ["LAB_PANEL"] = "panel2"
from feat import *
import numpy as np, mscore
U = UALL
d = dict(np.load("mkt_new.npz")); S = mscore.score(d); comp = mscore.components(d)
names = {"vol_up": "放量", "vol_dn": "缩量", "big_up": "大涨", "big_dn": "大跌", "flat": "平淡", "dn_many": "跌停多", "up_many": "涨停多", "drop5": "5日跌≥4%", "month": "月末月初", "mon": "明天周一", "thu": "明天周四"}
print("最近 30 个交易日：日期 全市场当日涨跌 成交额/20日均 涨停占比 跌停占比 → 分数（触发项） | 之后5天全市场")
for t in range(T - 30, T):
    trig = [names[k] for k, (m, w) in comp.items() if m[t]]
    b6 = d["b6"][t]
    print(f"  {cal[t]} {d['mr'][t]*100:+.2f}% {d['amt_rel'][t]:.2f} {d['upshare'][t]*100:.1f}% {d['dnshare'][t]*100:.1f}% → {S[t]:+d} ({'、'.join(trig) or '无'}) | {'%+.2f%%' % (b6*100) if np.isfinite(b6) else '—'}")
print("2026 年各月：分数≥3 天数 / 分数≥2 天数 / 分数≤-1 天数")
ym = cal // 100
for v in sorted(set(ym[year == 2026].tolist())):
    m = ym == v
    print(f"  {v}: {int((S[m] >= 3).sum())} / {int((S[m] >= 2).sum())} / {int((S[m] <= -1).sum())}  共 {int(m.sum())} 天")
codes_arr = np.array(codes)
uni = json.load(open("universe.json", encoding="utf-8")); name_of = {r["code"]: r["name"] for r in uni}
ind = json.load(open("industry.json", encoding="utf-8"))
COLD = np.load("cold2.npy"); cold = pct_rank(COLD, U)
SQ = np.load(os.path.join(HERE, "fpanel", "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, "fpanel", "eps_ttm.npy"))
t = T - 1
print(f"===== {cal[t]} 池内 {int(U[t].sum())} 只 =====")
# 中期候选
okm = U[t] & valid[t] & (cold[t] >= 0.9) & (SQ[t] > 0) & (EPS[t] > 0) & ~up_lim[t] & ~dn_lim[t]
idx = np.nonzero(okm)[0]; order = idx[np.argsort(-COLD[t, idx])]
print(f"中期候选 {len(idx)} 只；冷热分最高的 12 只：")
for j in order[:12]:
    print(f"  {codes[j]} {name_of.get(codes[j], '?'):<8} {ind.get(codes[j], ''):<8} 冷热分位 {cold[t, j]*100:.0f} 市值 {FMV[t, j]/1e8:.0f}亿 20日均成交 {amt20[t, j]/1e8:.1f}亿 近60日 {F('r60')[t, j]*100:+.1f}% 单季利润同比 {SQ[t, j]*100:+.0f}% 盘中60日 {F('id60')[t, j]*100:+.1f}% 量比 {F('abn20_250')[t, j]:.2f}")
# 短期候选（假设今天分数达标）
ps = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
oks = U[t] & valid[t] & ~up_lim[t] & ~dn_lim[t] & (R[t] < 0.05) & np.isfinite(ps[t]) & (cold[t] >= 0.5) & (EPS[t] > 0)
idx = np.nonzero(oks)[0]; order = idx[np.argsort(-ps[t, idx])]
print(f"短期候选（若今天分数达标）{len(idx)} 只；得分最高的 10 只：")
for j in order[:10]:
    print(f"  {codes[j]} {name_of.get(codes[j], '?'):<8} {ind.get(codes[j], ''):<8} 5日 {F('r5')[t, j]*100:+.1f}% 20日 {F('r20')[t, j]*100:+.1f}% 离一年高点 {F('hi250')[t, j]*100:+.0f}% 冷热分位 {cold[t, j]*100:.0f} 市值 {FMV[t, j]/1e8:.0f}亿")
# 最热的
hot_idx = np.nonzero(U[t] & (cold[t] < 0.02))[0]
print("今天最热的几只（冷热分位最低）：" + "、".join(f"{name_of.get(codes[j], codes[j])}" for j in hot_idx[np.argsort(COLD[t, hot_idx])][:12]))
