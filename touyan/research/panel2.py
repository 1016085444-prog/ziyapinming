"""研究用：用等比复权价重建大表，存 panel2/*.npy。
o/h/l/c 为等比复权价；rc 为不复权收盘（看价位、算涨跌停用）；pcref 为当日的「昨收参考价」（不复权，除权日已调整）。
"""
import glob, json, os, sys
import numpy as np
from adjust import factors

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "panel2")
START = 20160801


def build():
    os.makedirs(OUT, exist_ok=True)
    cal = np.load(os.path.join(HERE, "index", "sh000001.npz"))["d"]
    cal = cal[cal >= START]
    files = sorted(glob.glob(os.path.join(HERE, "raw", "*.npz")))
    codes = [os.path.basename(f)[:-4] for f in files]
    T, N = len(cal), len(files)
    arrs = {k: np.full((T, N), np.nan, np.float32) for k in ("o", "h", "l", "c", "a", "t", "v", "rc", "pcref")}
    tot = {"events": 0, "parsed": 0, "fit": 0, "both": 0, "disagree": 0, "nofix": 0}
    notes = []
    noq = 0
    for j, f in enumerate(files):
        code = codes[j]
        raw = np.load(f)
        if not os.path.exists(os.path.join(HERE, "data", code + ".npz")):
            noq += 1
            continue
        res = factors(code)
        for k in tot:
            tot[k] += res["diag"][k]
        for nt in res["diag"]["notes"]:
            notes.append((code,) + tuple(nt))
        d, F = raw["d"], res["F"]
        o, h, l, c, v = (raw[k].astype(np.float64) for k in "ohlcv")
        ok_bar = (v > 0) & (c > 0) & (o > 0) & (h > 0) & (l > 0)
        # 昨收参考价（不复权）：上一个有效收盘 × 系数之比
        pc = np.full(len(d), np.nan)
        last_c, last_F = np.nan, np.nan
        for i in range(len(d)):
            if ok_bar[i]:
                if np.isfinite(last_c):
                    pc[i] = last_c * last_F / F[i]
                last_c, last_F = c[i], F[i]
        idx = np.searchsorted(cal, d)
        ok = idx < T
        ok[ok] &= cal[idx[ok]] == d[ok]
        ok &= ok_bar
        rows = idx[ok]
        arrs["o"][rows, j] = (o * F)[ok]
        arrs["h"][rows, j] = (h * F)[ok]
        arrs["l"][rows, j] = (l * F)[ok]
        arrs["c"][rows, j] = (c * F)[ok]
        arrs["v"][rows, j] = v[ok]
        arrs["rc"][rows, j] = c[ok]
        arrs["pcref"][rows, j] = pc[ok]
        # 成交额、换手率来自之前下载的文件
        qf = np.load(os.path.join(HERE, "data", code + ".npz"))
        qi = np.searchsorted(cal, qf["d"])
        qok = qi < T
        qok[qok] &= cal[qi[qok]] == qf["d"][qok]
        A = np.full(T, np.nan, np.float32); TRN = np.full(T, np.nan, np.float32)
        A[qi[qok]] = qf["a"][qok]; TRN[qi[qok]] = qf["t"][qok]
        arrs["a"][rows, j] = A[rows]
        arrs["t"][rows, j] = TRN[rows]
    np.save(os.path.join(OUT, "cal.npy"), cal)
    json.dump(codes, open(os.path.join(OUT, "codes.json"), "w"))
    for k, a in arrs.items():
        np.save(os.path.join(OUT, k + ".npy"), a)
    json.dump(notes, open(os.path.join(OUT, "notes.json"), "w"), ensure_ascii=False)
    print("panel2", T, N, "no-qfq-file", noq, tot)
    print("valid share", float(np.isfinite(arrs["c"]).mean()), "missing amount among valid",
          float((np.isfinite(arrs["c"]) & ~np.isfinite(arrs["a"])).sum() / np.isfinite(arrs["c"]).sum()))
    print("notes", len(notes))
    for nt in notes[:25]:
        print("  ", nt)


if __name__ == "__main__":
    build()
