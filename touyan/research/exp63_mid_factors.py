"""实验 63：中期——在「冷门蓄势」的候选里（冷热分最冷一成、不是大盘股、在赚钱、利润增长 >10%），哪些特征决定了之后一到三个月的输赢。
另外放宽一点的候选（冷热分最冷两成）也看一遍，看看别的特征能不能替代「最冷」。

每 5 个交易日取一天（减少重叠），看和之后 20 / 60 个交易日收益的秩相关、最低一成和最高一成相对候选平均的超额。
python exp63_mid_factors.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

DAYS = np.zeros(T, bool); DAYS[260:T - 70:5] = True
candA = okm                                         # 软件现在的候选
candB = U & valid & (cold >= 0.8) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim          # 放宽：最冷两成，不要求增长
print(f"===== {which}：取样 {int(DAYS.sum())} 天；候选 A 平均 {candA[DAYS].sum() / DAYS.sum():.0f} 只，B 平均 {candB[DAYS].sum() / DAYS.sum():.0f} 只 =====", flush=True)
FEATS = ["r5", "r20", "r60", "r120", "r250", "mom250_20", "hi250", "lo250", "vol20", "vol60", "vol250", "dvol20", "max20", "skew20",
         "turn20", "turn250", "abn5_60", "vabn20_250", "id20", "ov20", "id60", "clv20", "pvv20", "size", "amt", "illiq20", "cold", "beta60",
         "ep", "bp", "cfp", "roe", "np_yoy", "rev_yoy", "sq_yoy", "surp", "gm", "since_rep", "up_n20",
         "ind_r20", "ind_r60", "ind_r250", "rel_ind20", "rel_ind60"]
OUT = {}
for cl, cand in (("A", candA), ("B", candB)):
    for h in (21, 61):
        print(f"--- 候选 {cl}，之后 {h - 1} 天 ---", flush=True)
        print(f"{'特征':<12} {'IC':>7} {'t':>6} | {'最低一成':>8} {'t':>5} | {'最高一成':>8} {'t':>5} | 各年 IC 为正", flush=True)
        for nm in FEATS:
            x = X(nm)
            ic, t_ic, by, _ = cond_ic(x, DAYS, cand, h=h)
            g, ts, _ = cond_groups(x, DAYS, cand, h=h, nb=5)
            pos = sum(1 for v in by.values() if v > 0)
            OUT[f"{cl}|{h}|{nm}"] = {"ic": ic, "t": t_ic, "q1": float(g[0]), "q5": float(g[-1]), "t1": float(ts[0]), "t5": float(ts[-1]), "by_year": by, "pos": pos, "years": len(by)}
            print(f"{nm:<12} {ic:+7.3f} {t_ic:+6.1f} | {g[0]*100:+7.2f}% {ts[0]:+5.1f} | {g[-1]*100:+7.2f}% {ts[-1]:+5.1f} | {pos:2d}/{len(by):2d}", flush=True)
json.dump(OUT, open(f"exp63_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
