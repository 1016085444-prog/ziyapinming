"""研究用：更早那十年的财报表，改用「法定披露截止日」对齐。

东方财富的业绩报表里，2010 年以前各期的「公告日」实际上是下一年同一期报告的日期（晚了约一年），
按它对齐的话 2005–2010 年几乎没有可用的财报。这里的规则：
- 公告日在报告期结束后 0–150 天内的，认为是真实公告日，照用；
- 否则用法定披露截止日：一季报 4 月 30 日、中报 8 月 31 日、三季报 10 月 31 日、年报次年 4 月 30 日。
截止日是「最晚」的日子，所以不会用到当时还不知道的信息。
"""
import os
os.environ.setdefault("LAB_PANEL", "panel_old")
from lab import *
import numpy as np, pandas as pd

OUT = f"fpanel{TAG}2"


def deadline(per):
    y, md = per // 10000, per % 10000
    return {331: y * 10000 + 430, 630: y * 10000 + 831, 930: y * 10000 + 1031, 1231: (y + 1) * 10000 + 430}[md]


def build():
    rep = pd.read_pickle(os.path.join(HERE, f"rep{TAG}.pkl"))
    ok = (rep["lag"] >= 0) & (rep["lag"] <= 150)
    eff = np.where(ok, rep["nd"].to_numpy(), np.array([deadline(int(p)) for p in rep["per"].to_numpy()]))
    t0 = np.searchsorted(cal, eff)
    rep = rep.assign(eff=eff, t0=np.where(t0 < T, t0, -1), dated=ok)
    rep["live"] = rep["t0"] >= 0
    rep.to_pickle(os.path.join(HERE, f"rep{TAG}2.pkl"))
    rep = rep[rep["live"]].sort_values(["i", "t0", "per"])
    out = {k: np.full((T, N), np.nan, np.float32) for k in ("sq_yoy", "np_yoy", "rev_yoy", "roe", "eps_ttm", "bps", "surp_raw", "rep_t0", "per", "gm", "cfps", "np_ttm")}
    key = {(int(i), int(p)): k for k, (i, p) in enumerate(zip(rep["i"].to_numpy(), rep["per"].to_numpy()))}
    eps = rep["eps"].to_numpy(); per = rep["per"].to_numpy(); ii = rep["i"].to_numpy(); npy = rep["np_ytd"].to_numpy()
    ttm = np.full(len(rep), np.nan); nttm = np.full(len(rep), np.nan)
    for k in range(len(rep)):
        p = int(per[k]); y = p // 10000; md = p % 10000
        if md == 1231:
            ttm[k] = eps[k]; nttm[k] = npy[k]
        else:
            a = key.get((int(ii[k]), (y - 1) * 10000 + 1231)); b = key.get((int(ii[k]), (y - 1) * 10000 + md))
            if a is not None and b is not None:
                ttm[k] = eps[k] + eps[a] - eps[b]; nttm[k] = npy[k] + npy[a] - npy[b]
    rep = rep.assign(eps_ttm=ttm, np_ttm=nttm)
    adj = (C / RC)
    for i, g in rep.groupby("i"):
        g = g.sort_values(["t0", "per"])
        for _, r in g.iterrows():
            t = int(r["t0"])
            if t >= T:
                continue
            f = adj[min(t, T - 1), i]
            if not np.isfinite(f):
                later = np.nonzero(np.isfinite(adj[t:, i]))[0]
                f = adj[t + later[0], i] if len(later) else np.nan
            out["sq_yoy"][t:, i] = r["sq_yoy"]; out["np_yoy"][t:, i] = r["np_yoy"]; out["rev_yoy"][t:, i] = r["rev_yoy"]
            out["roe"][t:, i] = r["roe"]; out["gm"][t:, i] = r["gm"]; out["cfps"][t:, i] = r["cfps"] * f if np.isfinite(f) else np.nan
            out["eps_ttm"][t:, i] = r["eps_ttm"] * f if np.isfinite(f) else np.nan
            out["bps"][t:, i] = r["bps"] * f if np.isfinite(f) else np.nan
            out["surp_raw"][t:, i] = r["sq"] - r["sq_ly"]; out["np_ttm"][t:, i] = r["np_ttm"]
            out["rep_t0"][t:, i] = t; out["per"][t:, i] = r["per"]
    os.makedirs(os.path.join(HERE, OUT), exist_ok=True)
    for k, a in out.items():
        np.save(os.path.join(HERE, OUT, k + ".npy"), a)
    print("done", OUT, {k: round(float(np.isfinite(a).mean()), 3) for k, a in out.items()})
    U = UREL if TAG == "_old" else UALL
    for y in sorted(set(year.tolist())):
        m = year == y
        u = U[m]
        print(y, "EPS %.2f BPS %.2f NPY %.2f NPTTM %.2f" % tuple(float((np.isfinite(out[k][m]) & u).sum() / max(u.sum(), 1)) for k in ("eps_ttm", "bps", "np_yoy", "np_ttm")))


if __name__ == "__main__":
    build()
