"""实验 19：中期打分的几种组合，在两个十年里分别看（前10% + 最新单季利润同比>0）。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = UREL          # 两个十年用同一口径：成交额排在前七成
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
ys = sorted(set(year.tolist()))
def composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.8, acc / cnt, np.nan)
def yearly(G, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    return int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0, np.nanmean(dr), np.nanmean(dex), nw_t(dex, h), np.nanmean(np.where(G, Fh > 0, np.nan)), ye
def show(label, res):
    n, ret, ex, t, win, ye = res; pos = sum(1 for v in ye.values() if v > 0)
    print(f"{label:<52} {n:4d}只 收益 {ret*100:+.2f}% 超额 {ex*100:+.2f}% t={t:.1f} 胜率 {win*100:.0f}% | 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items()), flush=True)
variants = {
    "B4 (id60,ov60,abn20_250,pvc20)": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1)],
    "B3 (id60,abn20_250,pvc20)": [("id60", -1), ("abn20_250", -1), ("pvc20", -1)],
    "B3' (id20,abn20_250,pvc20)": [("id20", -1), ("abn20_250", -1), ("pvc20", -1)],
    "B3+近5日量没放大 (id60,abn20_250,abn5_60,pvc20)": [("id60", -1), ("abn20_250", -1), ("abn5_60", -1), ("pvc20", -1)],
    "B3+收盘不在高位 (id60,abn20_250,pvc20,clv20)": [("id60", -1), ("abn20_250", -1), ("pvc20", -1), ("clv20", -1)],
    "B3+换手低 (id60,abn20_250,pvc20,turn20)": [("id60", -1), ("abn20_250", -1), ("pvc20", -1), ("turn20", -1)],
    "反向：最热门的 10%（B3 打分最低）": None,
}
print(f"===== {which}: {cal[0]}–{cal[-1]} 池内平均 {int(U.sum(1).mean())} 只 =====")
for label, parts in variants.items():
    if parts is None:
        sc = pct_rank(composite(variants["B3 (id60,abn20_250,pvc20)"]), U)
        for h in (21, 61):
            show(f"{label} h{h-1}", yearly(sc < 0.1, h))
        continue
    sc = pct_rank(composite(parts), U)
    for h in (21, 61):
        show(f"{label} 前10% h{h-1}", yearly(sc >= 0.9, h))
    for h in (21, 61):
        show(f"{label} 前10%+单季同比>0 h{h-1}", yearly((sc >= 0.9) & (SQ > 0), h))
    if which == "new" or True:
        show(f"{label} 前20%+单季同比>0 h60", yearly((sc >= 0.8) & (SQ > 0), 61))
