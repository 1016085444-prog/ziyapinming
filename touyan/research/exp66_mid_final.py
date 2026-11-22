"""实验 66：中期定稿前的最后几个变体。
- 「超预期」改成按流通市值折算：(最新单季归母净利润 − 去年同季) ÷ 流通市值（实验 63/64 用的是 ÷ 股价，混进了股本大小）；
- 要不要加「最新单季比去年同季多赚」这条硬条件（说起来简单）；
- 建仓时机：温度 <40 随时买；40–80 只在大盘预估分 ≥2 的日子买；≥80 不买。
python exp66_mid_final.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

EXIT = up_lim | (cold < 0.3)
SURP_RAW = fund("surp_raw")
with np.errstate(invalid="ignore", divide="ignore"):
    SURP_MV = SURP_RAW / FMV
import xlab; xlab._xc["surp_mv"] = SURP_MV.astype(np.float32)
candB = U & valid & (cold >= 0.8) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim
candB_up = candB & (SURP_RAW > 0)
candB85 = U & valid & (cold >= 0.85) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim
POLICY = (TEMP < 40) | ((TEMP >= 40) & (TEMP < 80) & (S >= 2)) | (~np.isfinite(TEMP) & (S >= 0))


def rk(nm, sign, mask):
    p = pct_rank(X(nm) * sign, mask)
    return np.where(np.isfinite(p), p, 0.5)


def comp(parts, mask):
    acc = np.zeros((T, N), np.float32); w = 0.0
    for nm, sg, wt in parts:
        acc += wt * rk(nm, sg, mask); w += wt
    return acc / w


P5 = [("surp", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("up_n20", -1, 1), ("cold", 1, 1)]
P5m = [("surp_mv", 1, 1), ("sq_yoy", 1, 1), ("amt", -1, 1), ("up_n20", -1, 1), ("cold", 1, 1)]
P4m = [("surp_mv", 1, 1), ("amt", -1, 1), ("up_n20", -1, 1), ("cold", 1, 1)]
VARS = [
    ("现在：最冷一成+增长>10%，按冷热分排", okm, None),
    ("B5（超预期按股价折算）", candB, P5),
    ("B5（超预期按市值折算）", candB, P5m),
    ("B5 市值折算 + 最新单季比去年同季多赚", candB_up, P5m),
    ("B4 市值折算（不要单季同比）", candB, P4m),
    ("B5 市值折算，冷热分≥85", candB85, P5m),
]
OUT = {}
for lab, cand, parts in VARS:
    key = COLD if parts is None else comp(parts, cand)
    for dl, days in (("每天", None), ("按时机", POLICY)):
        tr = sim_mid(pick(cand, key, days=days), 120, flag=EXIT)
        r = brief(tr, f"{lab}｜{dl}", hb=65)
        OUT[f"{lab}|{dl}"] = r
json.dump(OUT, open(f"exp66_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
