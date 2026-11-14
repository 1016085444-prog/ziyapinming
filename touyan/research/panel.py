"""研究用：把每只股票的 npz 拼成「交易日 × 股票」的大表，存成 panel/*.npy（可 mmap）。"""
import glob, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "panel")
START = 20160801


def build():
    os.makedirs(OUT, exist_ok=True)
    cal = np.load(os.path.join(HERE, "index", "sh000001.npz"))["d"]
    cal = cal[cal >= START]
    files = sorted(glob.glob(os.path.join(HERE, "data", "*.npz")))
    codes = [os.path.basename(f)[:-4] for f in files]
    T, N = len(cal), len(files)
    arrs = {k: np.full((T, N), np.nan, np.float32) for k in "ohlcvat"}
    bad = 0
    for j, f in enumerate(files):
        z = np.load(f)
        d = z["d"]
        idx = np.searchsorted(cal, d)
        ok = (idx < T)
        ok[ok] &= cal[idx[ok]] == d[ok]
        # 没成交的那些天（停牌却留了一根线）不算交易日
        ok &= (z["v"] > 0) & (z["c"] > 0) & (z["o"] > 0) & (z["h"] > 0) & (z["l"] > 0)
        if (z["c"] <= 0).any():
            bad += 1
        for k in "ohlcvat":
            arrs[k][idx[ok], j] = z[k][ok]
    np.save(os.path.join(OUT, "cal.npy"), cal)
    json.dump(codes, open(os.path.join(OUT, "codes.json"), "w"))
    for k, a in arrs.items():
        np.save(os.path.join(OUT, k + ".npy"), a)
    print("panel", T, N, "bad-price files", bad, "valid share", float(np.isfinite(arrs["c"]).mean()))


if __name__ == "__main__":
    build()
