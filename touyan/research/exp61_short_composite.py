"""实验 61：短期——把实验 60 里两个十年都站得住的特征组合起来，按完整的买卖规则（第二天开盘买、高开 2% 放弃、拿 5 天、收盘跌破 8% 止损）
在「可以出手」的日子里选 5 只（同一行业最多 2 只），和软件现在的排序比。

python exp61_short_composite.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

GO = (S >= 3)
LIGHT = (S == 2)
cand0 = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & PROFIT


def rk(nm, sign, mask):
    p = pct_rank(X(nm) * sign, mask)
    return np.where(np.isfinite(p), p, 0.5)


def comp(parts, mask=cand0):
    acc = np.zeros((T, N), np.float32); w = 0.0
    for nm, sg, wt in parts:
        acc += wt * rk(nm, sg, mask); w += wt
    return acc / w


BASE = [("r5", -1, 1), ("r20", -1, 1), ("hi250", -1, 1), ("cold", 1, 1)]
VARS = {
    "现在的排序（r5 r20 hi250 冷热分）": BASE,
    "+贝塔": BASE + [("beta60", 1, 1)],
    "+成交没放大": BASE + [("abn5_60", -1, 1)],
    "+比行业跌得多": BASE + [("rel_ind5", -1, 1)],
    "+收盘在低位": BASE + [("clv5", -1, 1)],
    "+偏度低": BASE + [("skew20", -1, 1)],
    "+近期没涨停": BASE + [("up_n20", -1, 1)],
    "+行业跌得多": BASE + [("ind_r5", -1, 1)],
    "r5 换成日内 id5": [("id5", -1, 1), ("r20", -1, 1), ("hi250", -1, 1), ("cold", 1, 1)],
    "+贝塔+成交没放大+比行业跌得多": BASE + [("beta60", 1, 1), ("abn5_60", -1, 1), ("rel_ind5", -1, 1)],
    "+贝塔+成交没放大+比行业跌得多+收盘低位": BASE + [("beta60", 1, 1), ("abn5_60", -1, 1), ("rel_ind5", -1, 1), ("clv5", -1, 1)],
    "全部十项": BASE + [("beta60", 1, 1), ("abn5_60", -1, 1), ("rel_ind5", -1, 1), ("clv5", -1, 1), ("skew20", -1, 1), ("id5", -1, 1)],
}
OUT = {}
for days_lab, days in (("分数≥3", GO), ("分数=2", LIGHT)):
    print(f"===== {which}：{days_lab}（{int(days.sum())} 天）=====", flush=True)
    for lab, parts in VARS.items():
        key = comp(parts)
        okm = cand0 & (cold >= 0.5)
        tr = trades(pick(okm, key, days=days), max_days=5, stop=0.08, max_gap=0.02)
        OUT[f"{days_lab}|{lab}"] = brief(tr, lab, hb=6)
json.dump(OUT, open(f"exp61_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
