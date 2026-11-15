import os, json
os.environ["LAB_PANEL"] = "panel2"
from feat import *
import numpy as np
U = eligible & (amt20 >= 5e7) & (age >= 250)
def _composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)
COLD = _composite([("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]); cold = pct_rank(COLD, U)
EPS = np.load(os.path.join(HERE, "fpanel", "eps_ttm.npy"))
ps = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
oks = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(ps) & (cold >= 0.5) & (EPS > 0)
uni = json.load(open("universe.json", encoding="utf-8")); name_of = {r["code"]: r["name"] for r in uni}
for day in (20261030, 20261023, 20260731):
    t = int(np.searchsorted(cal, day))
    idx = np.nonzero(oks[t])[0]; order = idx[np.argsort(-ps[t, idx])][:8]
    print(day, "池内", int(U[t].sum()), "候选", len(idx))
    for j in order:
        e = t + 1
        entry = O[e, j]; gap = entry / C[t, j] - 1
        f5 = C[e + 5, j] / entry * 0.998 - 1 if e + 5 < T else float("nan")
        print(f"   {codes[j]} {name_of.get(codes[j], '?'):<8} 分 {ps[t, j]/4*100:.1f} r5 {F('r5')[t, j]*100:+.1f}% r20 {F('r20')[t, j]*100:+.1f}% hi {F('hi250')[t, j]*100:+.0f}% cold {cold[t, j]*100:.0f} 次日跳空 {gap*100:+.1f}% → 5天 {f5*100:+.1f}%")
