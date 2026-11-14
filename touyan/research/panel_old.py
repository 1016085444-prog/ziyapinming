"""研究用：2005-01 ~ 2016-07 的等比复权大表，存 panel_old/。除权参考价只靠解析分红内容；
解析不了（配股等）或解析后当天涨跌仍超出涨跌停的，把除权日当天的涨跌按 0 处理（不让假跳空混进来）。"""
import glob, json, os
import numpy as np
from adjust import parse_content
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "panel_old")
START, END = 20050104, 20160729

def build():
    os.makedirs(OUT, exist_ok=True)
    cal = np.load(os.path.join(HERE, "index_long", "sh000001.npz"))["d"]
    cal = cal[(cal >= START) & (cal <= END)]
    files = sorted(glob.glob(os.path.join(HERE, "raw_old", "*.npz")))
    codes = [os.path.basename(f)[:-4] for f in files]
    T, N = len(cal), len(files)
    arrs = {k: np.full((T, N), np.nan, np.float32) for k in ("o", "h", "l", "c", "a", "t", "v", "rc", "pcref")}
    tot = {"events": 0, "parsed": 0, "neutral": 0}
    for j, f in enumerate(files):
        z = np.load(f)
        d = z["d"]; o, h, l, c, v = (z[k].astype(np.float64) for k in "ohlcv")
        a = z["a"]; t = z["t"]
        n = len(d)
        ev = json.load(open(os.path.join(HERE, "events_old", codes[j] + ".json"), encoding="utf-8"))
        Fc = np.ones(n)
        idx_ev = []
        for ds, info in ev.items():
            di = int(ds.replace("-", "")); k = int(np.searchsorted(d, di))
            if 0 < k < n and d[k] == di:
                idx_ev.append((k, info))
        for k, info in sorted(idx_ev, reverse=True):
            tot["events"] += 1
            pc = parse_content(info.get("FHcontent", ""))
            ref = None
            if pc:
                ref = (c[k - 1] - pc[0]) / (1 + pc[1])
                if not (0.05 * c[k - 1] < ref <= 1.001 * c[k - 1]) or abs(c[k] / ref - 1) > 0.115:
                    ref = None
            if ref is None:
                ref = c[k]; tot["neutral"] += 1          # 当天涨跌按 0
            else:
                tot["parsed"] += 1
            Fc[:k] *= ref / c[k - 1]
        ok_bar = (v > 0) & (c > 0) & (o > 0) & (h > 0) & (l > 0)
        pc = np.full(n, np.nan); last_c = np.nan; last_F = np.nan
        for i in range(n):
            if ok_bar[i]:
                if np.isfinite(last_c):
                    pc[i] = last_c * last_F / Fc[i]
                last_c, last_F = c[i], Fc[i]
        idx = np.searchsorted(cal, d)
        ok = idx < T
        ok[ok] &= cal[idx[ok]] == d[ok]
        ok &= ok_bar
        rows = idx[ok]
        arrs["o"][rows, j] = (o * Fc)[ok]; arrs["h"][rows, j] = (h * Fc)[ok]; arrs["l"][rows, j] = (l * Fc)[ok]; arrs["c"][rows, j] = (c * Fc)[ok]
        arrs["v"][rows, j] = v[ok]; arrs["rc"][rows, j] = c[ok]; arrs["pcref"][rows, j] = pc[ok]
        arrs["a"][rows, j] = a[ok]; arrs["t"][rows, j] = t[ok]
    np.save(os.path.join(OUT, "cal.npy"), cal)
    json.dump(codes, open(os.path.join(OUT, "codes.json"), "w"))
    for k, x in arrs.items():
        np.save(os.path.join(OUT, k + ".npy"), x)
    C = arrs["c"]; R = arrs["rc"] / arrs["pcref"] - 1
    age = np.cumsum(np.isfinite(C), axis=0)
    print("panel_old", T, N, tot, "valid share", float(np.isfinite(C).mean()))
    m = np.isfinite(R) & (age > 10)
    print("share |R|>10.5%:", float((np.abs(R[m]) > 0.105).mean()), "count |R|>11%:", int((np.abs(R[m]) > 0.11).sum()), "mean R", float(R[m].mean()))
    n_day = np.isfinite(C).sum(1)
    for k in (0, 500, 1000, 1500, 2000, 2500, T - 1):
        print(cal[k], int(n_day[k]), "只在交易, 成交额(亿)", round(float(np.nansum(arrs["a"][k])) / 1e8), "换手率缺失占比", round(float((np.isfinite(C[k]) & ~np.isfinite(arrs["t"][k])).sum() / max(1, n_day[k])), 3))

if __name__ == "__main__":
    build()
