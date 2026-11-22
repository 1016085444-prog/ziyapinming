"""实验 60：短期——在「可以出手」的日子里（大盘预估分 ≥3），候选股之间哪些特征决定了之后 5 天的输赢。

候选（比软件宽一点，好检验每个条件本身）：池内、没涨停跌停、当天涨幅 <5%、在赚钱。
每个特征：每天在候选里排名，看和之后收益（第二天开盘买、第 6 天收盘卖、扣 0.2%）的秩相关，以及最低一成、最高一成相对候选平均的超额。
两个十年分别跑：python exp60_short_factors.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

GO = (S >= 3)
LIGHT = (S == 2)
cand0 = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & PROFIT
print(f"===== {which}：出手日 {int(GO.sum())} 天，轻仓日 {int(LIGHT.sum())} 天；候选平均 {cand0[GO].sum() / max(GO.sum(), 1):.0f} 只 =====", flush=True)

FEATS = ["r1", "r3", "r5", "r10", "r20", "r60", "r120", "r250", "mom250_20", "hi250", "hi60", "lo250",
         "vol20", "vol60", "dvol20", "min5", "max20", "skew20", "turn5", "turn20", "turn250", "abn5_60", "vabn5_60", "vabn20_250",
         "id1", "ov1", "id5", "ov5", "id20", "ov20", "gapn5", "clv1", "clv5", "clv20", "lsh1", "lsh5", "ush5",
         "size", "amt", "illiq20", "cold", "id60", "pvv20", "beta60", "beta250",
         "ep", "bp", "cfp", "roe", "np_yoy", "rev_yoy", "sq_yoy", "surp", "gm", "since_rep", "dn_n5", "up_n20",
         "ind_r1", "ind_r5", "ind_r20", "ind_r60", "ind_r250", "rel_ind1", "rel_ind5", "rel_ind20", "ind_dn", "ind_up"]
OUT = {}
print(f"{'特征':<12} {'IC':>7} {'t':>6} | {'最低一成':>8} {'t':>5} | {'最高一成':>8} {'t':>5} | 各年 IC 为正的比例 | 轻仓日 IC", flush=True)
for nm in FEATS:
    try:
        x = X(nm)
    except Exception as e:  # noqa
        print(f"{nm:<12} 出错 {e}"); continue
    ic, t_ic, by, _ = cond_ic(x, GO, cand0)
    g, ts, _ = cond_groups(x, GO, cand0)
    ic2, t2, _, _ = cond_ic(x, LIGHT, cand0)
    pos = sum(1 for v in by.values() if v > 0)
    OUT[nm] = {"ic": ic, "t": t_ic, "d1": float(g[0]), "t1": float(ts[0]), "d10": float(g[-1]), "t10": float(ts[-1]), "groups": [float(v) for v in g],
               "by_year": by, "pos_years": pos, "years": len(by), "ic_light": ic2, "t_light": t2}
    print(f"{nm:<12} {ic:+7.3f} {t_ic:+6.1f} | {g[0]*100:+7.2f}% {ts[0]:+5.1f} | {g[-1]*100:+7.2f}% {ts[-1]:+5.1f} | {pos:2d}/{len(by):2d} | {ic2:+.3f} ({t2:+.1f})", flush=True)
json.dump(OUT, open(f"exp60_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
