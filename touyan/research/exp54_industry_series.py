"""实验 54a：把股票按行业（申万二级，128 个）归并成行业序列——每天的等权收益、中位数市净率、盈利、亏损面——
存下来，给「行业冷了多久 / 不景气多久」的检验用。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

U = (eligible & (amt20 >= 5e7) & (age >= 250)) if which == "new" else (UREL & (age >= 250))
ind_new = json.load(open("industry.json", encoding="utf-8")); ind_old = json.load(open("industry_old.json", encoding="utf-8"))
names = sorted(set(ind_new.values()) | set(ind_old.values()))
ind = {**ind_old, **ind_new} if which == "old" else {**ind_old, **ind_new}
col = {nm: k for k, nm in enumerate(names)}
ik = np.array([col.get(ind.get(c, ""), -1) for c in codes])
K = len(names)
ret = np.full((T, K), np.nan); pb = np.full((T, K), np.nan); cnt = np.zeros((T, K), np.int32); loss = np.full((T, K), np.nan)
npsum = np.full((T, K), np.nan); npsum_prev = np.full((T, K), np.nan); roe = np.full((T, K), np.nan); dy = np.full((T, K), np.nan); amt = np.full((T, K), np.nan)
with np.errstate(invalid="ignore", divide="ignore"):
    PB = np.where(BP > 0, 1 / BP, np.nan)
NP_prev = shift(NPTTM, 250)
for k in range(K):
    js = np.nonzero(ik == k)[0]
    if len(js) == 0:
        continue
    m = U[:, js]
    cnt[:, k] = m.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[:, k] = np.nanmean(np.where(m & valid[:, js], R[:, js], np.nan), axis=1)
        pb[:, k] = np.nanmedian(np.where(m, PB[:, js], np.nan), axis=1)
        roe[:, k] = np.nanmedian(np.where(m, ROE[:, js], np.nan), axis=1)
        dy[:, k] = np.nanmedian(np.where(m & (DY[:, js] > 0), DY[:, js], np.nan), axis=1)
        both = m & np.isfinite(NPTTM[:, js]) & np.isfinite(NP_prev[:, js])
        npsum[:, k] = np.where(both.sum(1) >= 3, np.where(both, NPTTM[:, js], 0).sum(1), np.nan)
        npsum_prev[:, k] = np.where(both.sum(1) >= 3, np.where(both, NP_prev[:, js], 0).sum(1), np.nan)
        have = m & np.isfinite(NPTTM[:, js])
        loss[:, k] = np.where(have.sum(1) >= 3, (have & (NPTTM[:, js] <= 0)).sum(1) / np.maximum(have.sum(1), 1), np.nan)
        amt[:, k] = np.nansum(np.where(m, A[:, js], 0), axis=1)
np.savez(f"indser_{which}.npz", d=cal, names=np.array(names), ret=ret, pb=pb, cnt=cnt, loss=loss, npsum=npsum, npsum_prev=npsum_prev, roe=roe, dy=dy, amt=amt,
         mkt=np.nanmean(np.where(U & valid, R, np.nan), axis=1))
print(which, "industries with >=8 stocks (avg):", int((cnt >= 8).sum(1).mean()), "of", K)
