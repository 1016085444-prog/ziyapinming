"""研究用：把财报数据铺成「交易日 × 股票」的表（每天只用当天已经公告的最新一期）。"""
from lab import *
import numpy as np, pandas as pd, os

def build():
    rep = pd.read_pickle(os.path.join(HERE, f"rep{TAG}.pkl"))
    rep = rep[rep["live"]].sort_values(["i", "t0", "per"])
    out = {k: np.full((T, N), np.nan, np.float32) for k in ("sq_yoy", "np_yoy", "rev_yoy", "roe", "eps_ttm", "bps", "surp_raw", "rep_t0", "per", "gm", "cfps")}
    # 每股收益的滚动 12 个月：本期累计 + 去年全年 − 去年同期累计
    key = {(int(i), int(p)): k for k, (i, p) in enumerate(zip(rep["i"].to_numpy(), rep["per"].to_numpy()))}
    eps = rep["eps"].to_numpy(); per = rep["per"].to_numpy(); ii = rep["i"].to_numpy(); t0 = rep["t0"].to_numpy()
    ttm = np.full(len(rep), np.nan)
    for k in range(len(rep)):
        p = int(per[k]); y = p // 10000; md = p % 10000
        if md == 1231:
            ttm[k] = eps[k]
        else:
            a = key.get((int(ii[k]), (y - 1) * 10000 + 1231)); b = key.get((int(ii[k]), (y - 1) * 10000 + md))
            if a is not None and b is not None:
                ttm[k] = eps[k] + eps[a] - eps[b]
    rep = rep.assign(eps_ttm=ttm)
    adj = (C / RC)                       # 复权系数
    for i, g in rep.groupby("i"):
        g = g.sort_values(["t0", "per"])
        for _, r in g.iterrows():
            t = int(r["t0"])
            if t >= T:
                continue
            f = adj[min(t, T - 1), i]
            if not np.isfinite(f):       # 公告日没交易，用之后第一个有效的系数
                later = np.nonzero(np.isfinite(adj[t:, i]))[0]
                f = adj[t + later[0], i] if len(later) else np.nan
            out["sq_yoy"][t:, i] = r["sq_yoy"]; out["np_yoy"][t:, i] = r["np_yoy"]; out["rev_yoy"][t:, i] = r["rev_yoy"]
            out["roe"][t:, i] = r["roe"]; out["gm"][t:, i] = r["gm"]; out["cfps"][t:, i] = r["cfps"] * f if np.isfinite(f) else np.nan
            out["eps_ttm"][t:, i] = r["eps_ttm"] * f if np.isfinite(f) else np.nan
            out["bps"][t:, i] = r["bps"] * f if np.isfinite(f) else np.nan
            out["surp_raw"][t:, i] = r["sq"] - r["sq_ly"]
            out["rep_t0"][t:, i] = t; out["per"][t:, i] = r["per"]
    os.makedirs(os.path.join(HERE, f"fpanel{TAG}"), exist_ok=True)
    for k, a in out.items():
        np.save(os.path.join(HERE, f"fpanel{TAG}", k + ".npy"), a)
    print("done", {k: float(np.isfinite(a).mean()) for k, a in out.items()})

if __name__ == "__main__":
    build()
