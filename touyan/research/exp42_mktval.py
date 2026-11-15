"""实验 42a：全市场每天的估值读数（中位数市净率、破净比例、股息率……）和全池等权的日收益，存成序列，给「市场温度」用。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

# 和软件里的股票池同一个口径：近 20 日日均成交 5000 万以上、上市满一年（更早的十年成交额小，用「成交额排在前七成」）
U = (eligible & (amt20 >= 5e7) & (age >= 250)) if which == "new" else (UREL & (age >= 250))
n_u = np.maximum(U.sum(1), 1)


def med(X, m=None):
    Z = np.where(U if m is None else m, X, np.nan)
    with np.errstate(invalid="ignore"):
        return np.nanmedian(Z, axis=1)


with np.errstate(invalid="ignore", divide="ignore"):
    PB = np.where(BP > 0, 1 / BP, np.nan)
    out = {
        "d": cal,
        "med_bp": med(BP), "med_pb": med(PB), "below1": (U & (PB < 1)).sum(1) / np.maximum((U & np.isfinite(PB)).sum(1), 1),
        "med_ep": med(EP), "med_dy": med(np.where(DY > 0, DY, np.nan)), "payers": (U & (DY > 0)).sum(1) / n_u,
        "p25_pb": np.nanpercentile(np.where(U, PB, np.nan), 25, axis=1), "p75_pb": np.nanpercentile(np.where(U, PB, np.nan), 75, axis=1),
        "ew_ret": np.nanmean(np.where(U & valid, R, np.nan), axis=1),
        "n": U.sum(1),
        "loss_share": (U & (NPTTM <= 0)).sum(1) / np.maximum((U & np.isfinite(NPTTM)).sum(1), 1),
    }
    # 大市值（前 300）的中位数估值
    B3 = U & (rk_mv <= 300)
    out["med_pb_big"] = med(PB, B3); out["med_ep_big"] = med(EP, B3)
np.savez(f"mktval_{which}.npz", **out)
print(which, "saved", {k: (round(float(np.nanmean(v)), 4) if k != "d" else len(v)) for k, v in out.items()})
