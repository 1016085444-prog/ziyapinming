"""研究用：软件里短期、中期两个板块的选股口径（和实验 35 一致），给交易方法的细化实验共用。

用法：先设环境变量 LAB_PANEL（panel2 / panel_old），再 from shiplab import *
"""
import json, os
from feat import *
import numpy as np, pandas as pd, mscore

which = "new" if PANEL == "panel2" else "old"
U = (eligible & (amt20 >= 5e7) & (age >= 250)) if which == "new" else (UREL & (age >= 250))
ys = sorted(set(year.tolist()))


def _composite(parts):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    return np.where(cnt >= len(parts), acc / np.maximum(cnt, 1), np.nan)


COLD = _composite([("id60", -1), ("vabn20_250", -1), ("pvv20", -1), ("clv20", -1)]); cold = pct_rank(COLD, U)
d = dict(np.load(os.path.join(HERE, f"mkt_{which}.npz")))
n_u = np.maximum(U.sum(1), 1)
with np.errstate(invalid="ignore", divide="ignore"):
    d["mr"] = np.nanmean(np.where(U, R, np.nan), axis=1); d["upshare"] = (up_lim & U).sum(1) / n_u; d["dnshare"] = (dn_lim & U).sum(1) / n_u
    _amt = np.nansum(np.where(U, A, 0), axis=1)
    d["amt_rel"] = _amt / np.concatenate([np.full(20, np.nan), np.convolve(_amt, np.ones(20) / 20, "valid")[:-1]])
S = mscore.score(d)
FPD = os.path.join(HERE, f"fpanel{TAG}2")
GROW = np.load(os.path.join(FPD, "np_yoy.npy")) / 100.0          # 累计净利润同比
PROFIT = np.load(os.path.join(FPD, "np_ttm.npy")) > 0            # 滚动 12 个月净利润为正
szp = pct_rank(F("size"), U)
_ind = json.load(open(os.path.join(HERE, f"industry{TAG}.json"), encoding="utf-8")) if os.path.exists(os.path.join(HERE, f"industry{TAG}.json")) else json.load(open(os.path.join(HERE, "industry.json"), encoding="utf-8"))
ind_of = np.array([_ind.get(c, "") for c in codes])
# 短期：排序分和候选
ps = (1 - pct_rank(F("r5"), U)) + (1 - pct_rank(F("r20"), U)) + (1 - pct_rank(F("hi250"), U)) + cold
oks = U & valid & ~up_lim & ~dn_lim & (R < 0.05) & np.isfinite(ps) & (cold >= 0.5) & PROFIT
# 中期：候选
okm = U & valid & (cold >= 0.9) & (szp < 0.7) & PROFIT & (GROW > 0.10) & ~up_lim & ~dn_lim


def pick(okmask, key, days=None, n=5, cap=2):
    P = np.zeros((T, N), bool)
    for t in (range(T) if days is None else np.nonzero(days)[0]):
        idx = np.nonzero(okmask[t])[0]
        if len(idx) == 0:
            continue
        order = idx[np.argsort(-key[t, idx])]; used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap:
                continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n:
                break
    return P


def brief(tr, label, hb=None, quiet=False):
    """一行结果：笔数、均值、中位、胜率、盈亏、篮子（同一天买的平均）、亏钱的年。"""
    ret = tr["ret"]; t = tr["t"]
    if len(ret) == 0:
        print(f"  {label:<40} 没有交易"); return {}
    df = pd.DataFrame({"t": t, "r": ret}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]; gr = g["r"].to_numpy()
    by = {int(y): float(gr[yr == y].mean()) for y in ys if (yr == y).sum()}
    res = {"n": int(len(ret)), "mean": float(ret.mean()), "median": float(np.median(ret)), "win": float((ret > 0).mean()), "avg_win": float(ret[ret > 0].mean()),
           "avg_loss": float(ret[ret <= 0].mean()), "days": float(tr["days"].mean()), "p5": float(np.percentile(ret, 5)), "worst": float(ret.min()),
           "basket_mean": float(gr.mean()), "basket_win": float((gr > 0).mean()), "basket_worst": float(gr.min()), "by_year": by,
           "per_day": float(ret.mean() / max(tr["days"].mean(), 1e-9))}
    if hb:
        b = base_of(fwd(hb), U)[t]; res["base"] = float(np.nanmean(b))
    neg = [str(y) for y, v in by.items() if v < 0]
    if not quiet:
        print(f"  {label:<40} 笔 {res['n']:5d} 均值 {res['mean']*100:+.2f}% 中位 {res['median']*100:+.2f}% 胜率 {res['win']*100:.0f}% 赚 {res['avg_win']*100:+.1f}% 亏 {res['avg_loss']*100:+.1f}% "
              f"拿 {res['days']:.1f}天 每天 {res['per_day']*100:+.2f}% 最差5% {res['p5']*100:+.1f}% | 篮子 {res['basket_mean']*100:+.2f}% 上涨 {res['basket_win']*100:.0f}% 最差 {res['basket_worst']*100:+.1f}% | 亏钱的年 {' '.join(neg) or '无'}", flush=True)
    return res
