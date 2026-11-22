"""研究用（第二轮）：在 shiplab 的基础上，加上行业层面的量、贝塔、基本面比值，以及「只在某些日子里」的分组检验。

用法：先设环境变量 LAB_PANEL（panel2 / panel_old），再 from xlab import *
"""
from shiplab import *          # noqa: F401,F403
import numpy as np, pandas as pd

z = np.load(os.path.join(HERE, "temps.npz"), allow_pickle=True)
_names = list(z["names"]); _tv = z[f"t{_names.index('两者平均(近10年)')}"]
_tmap = dict(zip(z["d"].tolist(), _tv.tolist())); TEMP = np.array([_tmap.get(int(x), np.nan) for x in cal])

# ---- 行业：把股票映射到行业编号，按天算行业等权涨跌 ----
_inds = sorted(set(x for x in ind_of if x))
IND_ID = np.array([(_inds.index(x) if x else -1) for x in ind_of])
NI = len(_inds)


def ind_mean(X, mask):
    """每天每个行业（mask 内）的等权平均，返回 [T, NI] 和每格的股票数。"""
    out = np.full((T, NI), np.nan, np.float32); cnt = np.zeros((T, NI), np.int32)
    ok_i = IND_ID >= 0
    for t in range(T):
        m = mask[t] & ok_i & np.isfinite(X[t])
        if not m.any():
            continue
        g = IND_ID[m]; s = np.bincount(g, weights=X[t][m], minlength=NI); n = np.bincount(g, minlength=NI)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[t] = np.where(n > 0, s / n, np.nan); cnt[t] = n
    return out, cnt


def to_stock(Y):
    """[T, NI] 的行业量 → [T, N]，每只股票取它所在行业的值。"""
    out = np.full((T, N), np.nan, np.float32)
    ok = IND_ID >= 0
    out[:, ok] = Y[:, IND_ID[ok]]
    return out


_IR, _ICNT = ind_mean(np.where(valid, R, np.nan), U)
_IR = np.where(_ICNT >= 5, _IR, np.nan)
_ILVL = np.cumprod(1 + np.nan_to_num(_IR), axis=0)


def ind_ret(k):
    a = _ILVL; b = np.vstack([np.full((k, NI), np.nan), _ILVL[:-k]])
    with np.errstate(invalid="ignore", divide="ignore"):
        return to_stock(a / b - 1)


_IDN, _ = ind_mean(dn_lim.astype(np.float32), U)
_IUP, _ = ind_mean(up_lim.astype(np.float32), U)
IND_DN = to_stock(_IDN); IND_UP = to_stock(_IUP)
IND_N = to_stock(_ICNT.astype(np.float32))

# ---- 市场（池内等权）收益、贝塔 ----
MR = np.nanmean(np.where(U & valid, R, np.nan), axis=1)


def beta(k=60):
    x = np.where(valid, R, np.nan).astype(np.float64); m = np.broadcast_to(MR[:, None], x.shape).astype(np.float64)
    m = np.where(np.isfinite(x), m, np.nan)
    sx, n = roll_sum(x, k); sm, _ = roll_sum(m, k); sxm, _ = roll_sum(x * m, k); smm, _ = roll_sum(m * m, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxm - sx * sm / n; vm = smm - sm * sm / n
        b = cov / vm
    return np.where(n >= k * 0.6, b, np.nan).astype(np.float32)


# ---- 基本面比值（都按当时能看到的财报） ----
FP = os.path.join(HERE, f"fpanel{TAG}2")


def fund(name):
    return np.load(os.path.join(FP, name + ".npy"))


def extra(name):
    """xlab 里新加的量。"""
    with np.errstate(invalid="ignore", divide="ignore"):
        if name.startswith("ind_r"):
            return ind_ret(int(name[5:]))
        if name.startswith("rel_ind"):          # 相对行业：k 日涨幅 − 行业 k 日涨幅
            k = int(name[7:]); return F(f"r{k}") - ind_ret(k)
        if name == "ind_dn":
            return IND_DN
        if name == "ind_up":
            return IND_UP
        if name.startswith("beta"):
            return beta(int(name[4:]))
        if name == "ep":
            return fund("eps_ttm") / Cf
        if name == "bp":
            return fund("bps") / Cf
        if name == "cfp":
            return fund("cfps") / Cf
        if name in ("roe", "np_yoy", "rev_yoy", "sq_yoy", "gm"):
            return fund(name)
        if name == "surp":
            return fund("surp_raw") / Cf
        if name == "since_rep":                  # 离最近一次财报公布过了几个交易日
            return np.arange(T, dtype=np.float32)[:, None] - fund("rep_t0")
        if name == "cold":
            return cold
        if name == "dn_n5":                      # 近 5 天跌停的次数
            return roll_sum(np.where(dn_lim, 1.0, 0.0), 5)[0].astype(np.float32)
        if name == "up_n20":
            return roll_sum(np.where(up_lim, 1.0, 0.0), 20)[0].astype(np.float32)
        if name == "clv1":
            return np.where(valid, CLV, np.nan).astype(np.float32)
        if name == "lsh1":
            return np.where(valid, LSH, np.nan).astype(np.float32)
        if name == "id1":
            return np.where(valid, LIN, np.nan).astype(np.float32)
        if name == "ov1":
            return np.where(valid, LON, np.nan).astype(np.float32)
    return F(name)


_xc = {}


def X(name):
    if name not in _xc:
        _xc[name] = extra(name)
    return _xc[name]


def cond_groups(Xv, days, cand, h=6, nb=10, cost=COST):
    """只在 days 那些天、只在 cand 里：按 Xv 分 nb 组，各组相对同日候选平均的超额（按天平均）与 t 值。"""
    Fh = fwd(h, cost)
    out = np.full((nb, T), np.nan)
    for t in np.nonzero(days)[0]:
        m = cand[t] & np.isfinite(Fh[t]) & np.isfinite(Xv[t])
        if m.sum() < nb * 3:
            continue
        x = Xv[t][m]; f = Fh[t][m]
        r = pd.Series(x).rank(pct=True).to_numpy()
        g = np.minimum((r * nb).astype(int), nb - 1)
        ex = f - f.mean()
        s = np.bincount(g, weights=ex, minlength=nb); n = np.bincount(g, minlength=nb)
        out[:, t] = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    means = np.nanmean(out, axis=1)
    ts = np.array([nw_t(out[g], h) for g in range(nb)])
    return means, ts, out


def cond_ic(Xv, days, cand, h=6, cost=COST):
    """只在 days 那些天：候选里 Xv 和之后收益的秩相关（每天一个），返回平均、t 值、按年平均。"""
    Fh = fwd(h, cost)
    ic = np.full(T, np.nan)
    for t in np.nonzero(days)[0]:
        m = cand[t] & np.isfinite(Fh[t]) & np.isfinite(Xv[t])
        if m.sum() < 30:
            continue
        a = pd.Series(Xv[t][m]).rank().to_numpy(); b = pd.Series(Fh[t][m]).rank().to_numpy()
        ic[t] = np.corrcoef(a, b)[0, 1]
    by = {int(y): float(np.nanmean(ic[year == y])) for y in ys if np.isfinite(ic[year == y]).any()}
    return float(np.nanmean(ic)), float(nw_t(ic, h)), by, ic


def sim_mid(P, max_days, flag=None, max_gap=0.03, cost=COST, stop=None):
    tt, ii = np.nonzero(P); e = tt + 1
    keep = e + max_days + 1 < T; tt, ii, e = tt[keep], ii[keep], e[keep]
    eo = O[e, ii]; pc = PC[e, ii]
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = eo / pc - 1
    ok = np.isfinite(eo) & (gap <= max_gap) & ~open_up[e, ii] & ~open_dn[e, ii] & ~one_line[e, ii]
    tt, ii, e, eo = tt[ok], ii[ok], e[ok], eo[ok]
    n = len(tt); entry = eo.astype(np.float64)
    alive = np.ones(n, bool); exitp = np.full(n, np.nan); days = np.zeros(n, np.int32); reason = np.zeros(n, np.int8); pend = np.zeros(n, bool); pr = np.zeros(n, np.int8)
    for k in range(1, max_days + 7):
        dd = np.minimum(e + k, T - 1); o = O[dd, ii].astype(np.float64); c = C[dd, ii].astype(np.float64); trading = np.isfinite(c) & (e + k < T)
        m = alive & pend & trading; exitp[m] = o[m]; days[m] = k; reason[m] = pr[m]; alive[m] = False
        locked = dn_lim[dd, ii]
        if flag is not None:
            m = alive & trading & ~pend & flag[dd, ii]; pend[m] = True; pr[m] = 3
        if stop is not None:
            m = alive & trading & ~pend & (c <= entry * (1 - stop)); mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 2; alive[mm] = False
            mm = m & locked; pend[mm] = True; pr[mm] = 2
        if k >= max_days:
            m = alive & trading & ~pend; mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 0; alive[mm] = False
            mm = m & locked; pend[mm] = True; pr[mm] = 0
        if not alive.any():
            break
    m = alive
    if m.any():
        dd = np.minimum(e + max_days + 6, T - 1); exitp[m] = Cf[dd[m], ii[m]]; days[m] = max_days + 7
    return {"t": tt, "i": ii, "ret": exitp / entry * (1 - cost) - 1, "days": days, "reason": reason}
