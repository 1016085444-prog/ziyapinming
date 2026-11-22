"""实验 64：中期——用实验 63 里两个十年都站得住的特征（业绩超预期 surp、单季利润同比 sq_yoy、成交额小 amt、近期没涨停 up_n20、冷热分），
重新组合候选和排序，按软件里的完整卖出规则（第二天开盘买、高开 3% 放弃；冷热分 <30 或收盘涨停的第二天卖；最多 120 个交易日）检验。

python exp64_mid_composite.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

EXIT = up_lim | (cold < 0.3)
candA = okm
candB = U & valid & (cold >= 0.8) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim
candC = U & valid & (cold >= 0.9) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim                   # 最冷一成，不要求增长
candD = U & valid & (cold >= 0.8) & (szp < 0.7) & PROFIT & (GROW > 0.10) & ~up_lim & ~dn_lim   # 最冷两成 + 增长


def rk(nm, sign, mask):
    p = pct_rank(X(nm) * sign, mask)
    return np.where(np.isfinite(p), p, 0.5)


def comp(parts, mask):
    acc = np.zeros((T, N), np.float32); w = 0.0
    for nm, sg, wt in parts:
        acc += wt * rk(nm, sg, mask); w += wt
    return acc / w


VARS = [
    ("现在：最冷一成+增长>10%，按冷热分排", candA, None),
    ("A 候选，按 超预期+冷热分 排", candA, [("surp", 1, 1), ("cold", 1, 1)]),
    ("A 候选，按 超预期+单季同比+成交额小+冷热分 排", candA, [("surp", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("cold", 1, 1)]),
    ("C 最冷一成不要求增长，按 超预期+冷热分 排", candC, [("surp", 1, 1), ("cold", 1, 1)]),
    ("C 最冷一成，按 超预期+单季同比+成交额小+冷热分 排", candC, [("surp", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("cold", 1, 1)]),
    ("B 最冷两成，按 超预期+冷热分 排", candB, [("surp", 1, 1), ("cold", 1, 1)]),
    ("B 最冷两成，按 超预期+单季同比+冷热分 排", candB, [("surp", 1, 1), ("sq_yoy", 1, 1), ("cold", 1, 1)]),
    ("B 最冷两成，按 超预期+单季同比+成交额小+冷热分 排", candB, [("surp", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("cold", 1, 1)]),
    ("B 最冷两成，按 超预期+单季同比+成交额小+没涨停+冷热分 排", candB, [("surp", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("up_n20", -1, 1), ("cold", 1, 1)]),
    ("D 最冷两成+增长，按 超预期+成交额小+冷热分 排", candD, [("surp", 1, 1), ("amt", -1, 1), ("cold", 1, 1)]),
    ("B 最冷两成，只按超预期排", candB, [("surp", 1, 1)]),
]
OUT = {}
print(f"===== {which}：中期组合（候选平均 A {candA.sum(1)[300:].mean():.0f} / B {candB.sum(1)[300:].mean():.0f} / C {candC.sum(1)[300:].mean():.0f} / D {candD.sum(1)[300:].mean():.0f} 只）=====", flush=True)
for lab, cand, parts in VARS:
    key = COLD if parts is None else comp(parts, cand)
    tr = sim_mid(pick(cand, key), 120, flag=EXIT)
    r = brief(tr, lab, hb=65)
    lt40 = TEMP[tr["t"]] < 40
    if lt40.any():
        x = tr["ret"][lt40]; r["lt40"] = {"n": int(lt40.sum()), "mean": float(x.mean()), "win": float((x > 0).mean())}
        print(f"      温度<40 建仓：{r['lt40']['n']} 笔 平均 {r['lt40']['mean']*100:+.2f}% 胜率 {r['lt40']['win']*100:.0f}%", flush=True)
    OUT[lab] = r
json.dump(OUT, open(f"exp64_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
