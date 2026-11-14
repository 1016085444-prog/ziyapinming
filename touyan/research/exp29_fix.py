"""实验 29：冷热分改用「成交股数」；候选按近 60 日跌幅、市值、上市时间分组看。"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U0 = UREL if which == "old" else UALL
U = U0 & (age >= 250)             # 上市满 250 个交易日
ys = sorted(set(year.tolist()))
def composite(parts, U):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)     # 四项都要有
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
def yearly(G, h, UU):
    Fh = fwd(h); M = UU & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    pos = sum(1 for v in ye.values() if v > 0)
    return f"每天{int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0:4d}只 收益 {np.nanmean(dr)*100:+.2f}% 超额 {np.nanmean(dex)*100:+.2f}% t={nw_t(dex, h):.1f} 胜率 {np.nanmean(np.where(G, Fh > 0, np.nan))*100:.0f}% 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items())
print(f"===== {which}（上市满250天；池内平均 {int(U.sum(1)[300:].mean())} 只）=====")
variants = {"换手率版(id60,abn20_250,pvr20,clv20)": [("id60", -1), ("abn20_250", -1), ("pvr20", -1), ("clv20", -1)],
            "成交股数版(id60,vabn20_250,pvv20,clv20)": [("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]}
keep = None
for nm, parts in variants.items():
    COLD = composite(parts, U); cold = pct_rank(COLD, U)
    for h in (21, 61):
        print(f"  {nm} 最冷10% h{h-1}: " + yearly(cold >= 0.9, h, U))
        print(f"  {nm} 最冷10%+赚钱+增长 h{h-1}: " + yearly((cold >= 0.9) & (SQ > 0) & (EPS > 0), h, U))
        print(f"  {nm} 最热10% h{h-1}: " + yearly(cold < 0.1, h, U))
    keep = (COLD, cold)
COLD, cold = keep
np.save(f"cold3{TAG}.npy", COLD)
cand = U & (cold >= 0.9) & (SQ > 0) & (EPS > 0)
r60 = F("r60"); r20 = F("r20"); szp = pct_rank(F("size"), U)
print("  --- 候选（成交股数版）按近 60 日涨跌分组，之后 60 天 / 20 天 ---")
for lo, hi in ((-1, -0.30), (-0.30, -0.20), (-0.20, -0.10), (-0.10, 0.0), (0.0, 1.0)):
    G = cand & (r60 >= lo) & (r60 < hi)
    print(f"    近60日 [{lo*100:+.0f}%,{hi*100:+.0f}%): h60 " + yearly(G, 61, U)[:110] + " || h20 " + yearly(G, 21, U)[:90])
print("  --- 候选按市值分组（之后 60 天） ---")
for lo, hi, lab in ((0, 0.3, "小(后30%)"), (0.3, 0.7, "中"), (0.7, 1.01, "大(前30%)")):
    print(f"    {lab}: " + yearly(cand & (szp >= lo) & (szp < hi), 61, U)[:150])
print("  --- 候选按 单季利润同比 分组（之后 60 天） ---")
for lo, hi in ((0, 0.1), (0.1, 0.3), (0.3, 1.0), (1.0, 1e9)):
    print(f"    同比 [{lo*100:.0f}%,{hi*100 if hi < 1e8 else float('inf'):.0f}%): " + yearly(cand & (SQ > lo) & (SQ <= hi), 61, U)[:150])
