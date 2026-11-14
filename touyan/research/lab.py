"""研究用工具箱：载入大表、算派生量、按真实交易规则模拟、和「同一天随便买」比。

约定（和软件里的方法体检一致）：
- 信号只用到 t 日收盘为止的数据；t+1 日开盘买入；
- 开盘就涨停（或一字板）买不进；T+1，买入当天不能卖；
- 手续费+滑点合计按 COST 计（来回一次）。
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.environ.get("LAB_PANEL", "panel2")
TAG = "" if PANEL == "panel2" else "_old"
P = os.path.join(HERE, PANEL)
COST = 0.002

cal = np.load(os.path.join(P, "cal.npy"))
codes = json.load(open(os.path.join(P, "codes.json")))
T, N = len(cal), len(codes)
year = cal // 10000
O = np.load(os.path.join(P, "o.npy"))
H = np.load(os.path.join(P, "h.npy"))
L = np.load(os.path.join(P, "l.npy"))
C = np.load(os.path.join(P, "c.npy"))
A = np.load(os.path.join(P, "a.npy"))
TR = np.load(os.path.join(P, "t.npy"))
V = np.load(os.path.join(P, "v.npy"))
RC = np.load(os.path.join(P, "rc.npy"))        # 不复权收盘
PCREF = np.load(os.path.join(P, "pcref.npy"))  # 不复权的昨收参考价（除权日已调整）
valid = np.isfinite(C)


def ffill(X):
    """沿时间向前填充。"""
    idx = np.where(np.isfinite(X), np.arange(T)[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    out = X[idx, np.arange(N)[None, :]]
    return out


Cf = ffill(C)                       # 停牌日沿用上一个收盘价
PC = np.vstack([np.full((1, N), np.nan, np.float32), Cf[:-1]])   # 上一个有效收盘
with np.errstate(invalid="ignore", divide="ignore"):
    R = C / PC - 1                  # 当日涨跌（跨停牌按复牌算）
    OV = O / PC - 1                 # 隔夜（开盘相对昨收）
    ID = C / O - 1                  # 日内（收盘相对开盘）

# ---- 涨跌停幅度 ----
lim = np.full((T, N), 0.10, np.float32)
for j, code in enumerate(codes):
    if code.startswith(("688", "689")):
        lim[:, j] = 0.20
    elif code.startswith("30"):
        lim[cal >= 20200824, j] = 0.20


def roll_sum(X, k):
    """最近 k 个交易日（含当天）的和，NaN 当 0；同时返回有效天数。"""
    Z = np.where(np.isfinite(X), X, 0).astype(np.float64)
    cs = np.vstack([np.zeros((1, N)), np.cumsum(Z, axis=0)])
    cn = np.vstack([np.zeros((1, N)), np.cumsum(np.isfinite(X), axis=0)])
    lo = np.maximum(np.arange(T) + 1 - k, 0)
    s = cs[1:] - cs[lo]
    n = cn[1:] - cn[lo]
    return s, n


def roll_mean(X, k, minp=None):
    s, n = roll_sum(X, k)
    minp = minp or max(1, int(k * 0.6))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n >= minp, s / n, np.nan).astype(np.float32)


def roll_std(X, k, minp=None):
    minp = minp or max(2, int(k * 0.6))
    s, n = roll_sum(X, k)
    s2, _ = roll_sum(X * X, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (s2 - s * s / n) / (n - 1)
        return np.where(n >= minp, np.sqrt(np.maximum(var, 0)), np.nan).astype(np.float32)


def roll_max(X, k, minp=1):
    return pd.DataFrame(X).rolling(k, min_periods=minp).max().to_numpy(np.float32)


def roll_min(X, k, minp=1):
    return pd.DataFrame(X).rolling(k, min_periods=minp).min().to_numpy(np.float32)


def shift(X, k):
    """把 X 往后挪 k 天（t 日看到的是 t-k 日的值）。"""
    out = np.full_like(X, np.nan)
    if k > 0:
        out[k:] = X[:-k]
    elif k < 0:
        out[:k] = X[-k:]
    else:
        out[:] = X
    return out


def ret_k(k, skip=0):
    """到 t-skip 为止的 k 日涨幅（用填充后的收盘，停牌不影响）。"""
    a = shift(Cf, skip)
    b = shift(Cf, skip + k)
    with np.errstate(invalid="ignore", divide="ignore"):
        return a / b - 1


# ---- 涨跌停：用不复权价按交易所的算法算涨跌停价（四舍五入到分） ----
def _round2(x):
    return np.floor(x * 100 + 0.5) / 100


with np.errstate(invalid="ignore", divide="ignore"):
    RO = O * RC / C                  # 不复权开盘
    RH = H * RC / C
    RL = L * RC / C


def _limits(lm):
    up = _round2(PCREF.astype(np.float64) * (1 + lm))
    dn = _round2(PCREF.astype(np.float64) * (1 - lm))
    return up, dn


# ST 的近似识别：最近 60 个交易日涨跌从不超过 5.3%，却至少两次收在 ±5% 的涨跌停价上
absr = np.abs(R)
up5, dn5 = _limits(0.05)
hit5 = valid & ((RC >= up5 - 0.0015) | (RC <= dn5 + 0.0015)) & (absr >= 0.044)
mx60 = roll_max(np.where(valid, absr, np.nan), 60, 30)
n5, _ = roll_sum(np.where(hit5, 1.0, 0.0), 60)
st_like = (mx60 <= 0.053) & (n5 >= 2)
lim = np.where(st_like, 0.05, lim).astype(np.float32)
UPP, DNP = _limits(lim)
up_lim = valid & (RC >= UPP - 0.0015) & (R > 0.03)           # 收盘封涨停
dn_lim = valid & (RC <= DNP + 0.0015) & (R < -0.03)          # 收盘封跌停
open_up = np.isfinite(O) & (RO >= UPP - 0.0015) & (OV > 0.03)   # 开盘就涨停
open_dn = np.isfinite(O) & (RO <= DNP + 0.0015) & (OV < -0.03)  # 开盘就跌停
one_line = valid & (H <= L * 1.0001)                          # 一字板

# ---- 上市天数 ----
first = np.argmax(valid, axis=0)
has = valid.any(axis=0)
age = np.cumsum(valid, axis=0).astype(np.int32)
age[:, first == 0] += 1000        # 一开始就在的，当作老股票
age[:, ~has] = 0

# ---- 流通市值、成交额 ----
with np.errstate(invalid="ignore", divide="ignore"):
    FMV = ffill(np.where(TR > 0, A / (TR / 100.0), np.nan).astype(np.float32))
amt60 = roll_mean(A, 60, 40)
amt20 = roll_mean(A, 20, 12)


def rank_desc(X, mask):
    """每天在 mask 里按 X 从大到小排名（1 开始），不在 mask 或 NaN 的给大数。"""
    Z = np.where(mask & np.isfinite(X), X, -np.inf)
    order = np.argsort(-Z, axis=1, kind="stable")
    rk = np.empty((T, N), np.int32)
    rows = np.arange(T)[:, None]
    rk[rows, order] = np.arange(1, N + 1)[None, :]
    rk[~(mask & np.isfinite(X))] = 10 ** 6
    return rk


eligible = valid & (age >= 120) & ~st_like & np.isfinite(amt60)
rk_amt = rank_desc(amt60, eligible)
rk_mv = rank_desc(FMV, eligible)
U300 = eligible & (rk_mv <= 300)
U800 = eligible & (rk_amt <= 800)
U1000 = eligible & (rk_amt <= 1000)
U1500 = eligible & (rk_amt <= 1500)
UALL = eligible & (amt20 >= 3e7)
rk_amt20 = rank_desc(amt20, eligible)
UREL = eligible & (rk_amt20 <= 0.7 * np.maximum(eligible.sum(1), 1)[:, None])     # 成交额排在前七成（剔除最不活跃的三成）


def pct_rank(X, mask):
    """每天在 mask 内的百分位（0~1，越大值越大）。"""
    Z = np.where(mask & np.isfinite(X), X, np.nan)
    r = pd.DataFrame(Z).rank(axis=1, pct=True).to_numpy(np.float32)
    return r


# ---- 向前看的收益 ----
_fw = {}


def can_buy():
    """t 日发信号，t+1 日开盘能不能买进。"""
    nxt_open = shift(O, -1)
    ok = np.isfinite(nxt_open) & ~shift(open_up, -1).astype(bool) & ~shift(one_line, -1).astype(bool)
    return ok


def fwd(h, cost=COST):
    """t 日收盘发信号，t+1 开盘买，t+h 收盘卖（h>=2），扣成本。买不进的为 NaN。"""
    key = (h, cost)
    if key not in _fw:
        entry = shift(O, -1)
        exitp = shift(Cf, -h)
        with np.errstate(invalid="ignore", divide="ignore"):
            f = exitp / entry * (1 - cost) - 1
        f[~can_buy()] = np.nan
        _fw[key] = f.astype(np.float32)
    return _fw[key]


def base_of(F, U):
    """同一天在股票池里随便买的平均收益。"""
    Z = np.where(U, F, np.nan)
    with np.errstate(invalid="ignore"):
        return np.nanmean(Z, axis=1)


def nw_t(x, lag):
    """日序列均值的 Newey-West t 值。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return np.nan
    m = x.mean()
    d = x - m
    v = (d * d).sum() / n
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        v += 2 * w * (d[k:] * d[:-k]).sum() / n
    return m / np.sqrt(v / n) if v > 0 else np.nan


def ev(S, h, U, label="", years=True, cost=COST, quiet=False):
    """布尔信号 S 的效果：原始收益、相对同日随便买的超额，按年分解。"""
    F = fwd(h, cost)
    S = S & U & np.isfinite(F)
    b = base_of(F, U)
    ex = F - b[:, None]
    n_day = S.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        day_ret = np.where(n_day > 0, np.nansum(np.where(S, F, 0), 1) / n_day, np.nan)
        day_ex = np.where(n_day > 0, np.nansum(np.where(S, ex, 0), 1) / n_day, np.nan)
    f = F[S]
    e = ex[S]
    res = {"label": label, "h": h, "n": int(S.sum()), "days": int((n_day > 0).sum()),
           "mean": float(np.mean(f)) if len(f) else np.nan, "median": float(np.median(f)) if len(f) else np.nan,
           "win": float((f > 0).mean()) if len(f) else np.nan,
           "ex": float(np.mean(e)) if len(e) else np.nan, "beat": float((e > 0).mean()) if len(e) else np.nan,
           "day_ret": float(np.nanmean(day_ret)), "day_ex": float(np.nanmean(day_ex)), "t": float(nw_t(day_ex, h)),
           "base": float(np.nanmean(b))}
    if not quiet:
        print(f"[{label}] h={h} n={res['n']} days={res['days']} | 每笔: 均值 {res['mean']*100:+.2f}% 中位 {res['median']*100:+.2f}% 胜率 {res['win']*100:.0f}% "
              f"| 超额 {res['ex']*100:+.2f}% 跑赢 {res['beat']*100:.0f}% | 按天平均: 收益 {res['day_ret']*100:+.2f}% 超额 {res['day_ex']*100:+.2f}% t={res['t']:.1f} | 随便买 {res['base']*100:+.2f}%")
    if years:
        rows = []
        for y in sorted(set(year.tolist())):
            m = year == y
            Sy = S[m]
            if Sy.sum() == 0:
                rows.append((y, 0, np.nan, np.nan, np.nan, np.nan))
                continue
            fy = F[m][Sy]
            ey = ex[m][Sy]
            dy = day_ex[m]
            rows.append((y, int(Sy.sum()), float(fy.mean()), float((fy > 0).mean()), float(ey.mean()), float(np.nanmean(dy))))
        res["years"] = rows
        if not quiet:
            print("    年份   次数   均值    胜率   超额   按天超额")
            for y, n, m_, w, e_, d_ in rows:
                if n:
                    print(f"    {y} {n:6d} {m_*100:+6.2f}% {w*100:4.0f}% {e_*100:+6.2f}% {d_*100:+6.2f}%")
    return res


def deciles(X, h, U, label="", nb=10, cost=COST, quiet=False):
    """连续指标：每天在池内分 nb 组，看各组相对随便买的超额（按天平均）。X 越大组号越大。"""
    F = fwd(h, cost)
    M = U & np.isfinite(F) & np.isfinite(X)
    pr = pct_rank(X, M)
    b = base_of(F, M)
    ex = F - b[:, None]
    grp = np.minimum((pr * nb).astype(np.int32), nb - 1)
    out, ts = [], []
    for g in range(nb):
        G = M & (grp == g)
        cnt = G.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            d = np.where(cnt > 0, np.where(G, ex, 0).sum(1) / cnt, np.nan)
        out.append(float(np.nanmean(d)))
        ts.append(float(nw_t(d, h)))
    # 秩相关
    if not quiet:
        print(f"[{label}] h={h} 各组超额(%)：" + " ".join(f"{v*100:+.2f}" for v in out))
        print(f"{'':>{len(label)+2}}       t 值：" + " ".join(f"{v:+.1f}" for v in ts))
    return out, ts


def group_years(X, h, U, lo, hi, cost=COST):
    """指标落在 [lo, hi) 百分位的那组，按年的超额（按天平均）。"""
    F = fwd(h, cost)
    M = U & np.isfinite(F) & np.isfinite(X)
    pr = pct_rank(X, M)
    b = base_of(F, M)
    ex = F - b[:, None]
    G = M & (pr >= lo) & (pr < hi)
    cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.where(cnt > 0, np.where(G, ex, 0).sum(1) / cnt, np.nan)
    return {int(y): float(np.nanmean(d[year == y])) for y in sorted(set(year.tolist())) if np.isfinite(d[year == y]).any()}


def trades(S, max_days, target=None, stop=None, trail=None, max_gap=0.02, cost=COST, hot_exit=None):
    """按完整的买卖规则模拟每个信号。
    target/stop/trail 可以是标量，也可以是 [T,N] 数组（按信号当天取值）。
    止盈：盘中触价成交（开盘就过了按开盘价）；止损/移动止损：收盘确认；封死跌停卖不掉顺延到下一天开盘。
    买入后第 max_days 个交易日收盘还没卖的，收盘卖出（和软件里 sim.run_trade 的口径一致）。
    days = 买入后过了几个交易日。
    返回 dict：t, i, ret(扣成本), days, reason(0 时间 1 止盈 2 止损 3 移动止损)。
    """
    tt, ii = np.nonzero(S)
    e = tt + 1
    keep = e + max_days + 1 < T      # 走不完的不要
    tt, ii, e = tt[keep], ii[keep], e[keep]
    eo = O[e, ii]
    pc = PC[e, ii]
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = eo / pc - 1
    ok = np.isfinite(eo) & (gap <= max_gap) & ~open_up[e, ii] & ~open_dn[e, ii] & ~one_line[e, ii]
    tt, ii, e, eo = tt[ok], ii[ok], e[ok], eo[ok]

    def per(x):
        if x is None:
            return None
        return x[tt, ii].astype(np.float64) if isinstance(x, np.ndarray) else np.full(len(tt), float(x))

    tg, st, trl = per(target), per(stop), per(trail)
    n = len(tt)
    entry = eo.astype(np.float64)
    alive = np.ones(n, bool)
    exitp = np.full(n, np.nan)
    days = np.zeros(n, np.int32)
    reason = np.zeros(n, np.int8)
    peak = np.maximum(entry, np.nan_to_num(C[e, ii].astype(np.float64), nan=0))
    pending = np.zeros(n, bool)        # 收盘想卖但封跌停，等下一天开盘
    pend_reason = np.zeros(n, np.int8)
    for k in range(1, max_days + 7):
        d = e + k
        inb = d < T
        d2 = np.minimum(d, T - 1)
        o = O[d2, ii].astype(np.float64)
        h = H[d2, ii].astype(np.float64)
        c = C[d2, ii].astype(np.float64)
        trading = inb & np.isfinite(c)
        # 1) 之前卖不掉的，今天开盘卖
        m = alive & pending & trading
        exitp[m] = o[m]; days[m] = k; reason[m] = pend_reason[m]; alive[m] = False
        # 2) 止盈
        if tg is not None:
            tp = entry * (1 + tg)
            m = alive & trading & (o >= tp)
            exitp[m] = o[m]; days[m] = k; reason[m] = 1; alive[m] = False
            m = alive & trading & (h >= tp)
            exitp[m] = tp[m]; days[m] = k; reason[m] = 1; alive[m] = False
        locked = dn_lim[d2, ii]
        # 3) 止损（收盘确认）
        if st is not None:
            m = alive & trading & (c <= entry * (1 - st))
            mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 2; alive[mm] = False
            mm = m & locked
            pending[mm] = True; pend_reason[mm] = 2
        if trl is not None:
            peak = np.where(trading, np.maximum(peak, c), peak)
            m = alive & trading & ~pending & (c <= peak * (1 - trl))
            mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 3; alive[mm] = False
            mm = m & locked
            pending[mm] = True; pend_reason[mm] = 3
        # 4) 到期
        if k >= max_days:
            m = alive & trading & ~pending
            mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; reason[mm] = 0; alive[mm] = False
            mm = m & locked
            pending[mm] = True; pend_reason[mm] = 0
        if not alive.any():
            break
    # 还没出来的（长期停牌等）按最后价格算
    m = alive
    if m.any():
        dd = np.minimum(e + max_days + 6, T - 1)
        exitp[m] = Cf[dd[m], ii[m]]; days[m] = max_days + 7
    ret = exitp / entry * (1 - cost) - 1
    return {"t": tt, "i": ii, "ret": ret, "days": days, "reason": reason}


def tr_stats(tr, U=None, h_base=None, label="", years=True, quiet=False):
    """模拟结果的统计；如给了 U 和 h_base，就和同一天随便买、拿 h_base 天比。"""
    ret = tr["ret"]
    t = tr["t"]
    out = {"label": label, "n": len(ret)}
    if len(ret) == 0:
        print(f"[{label}] 没有交易")
        return out
    out.update(mean=float(ret.mean()), median=float(np.median(ret)), win=float((ret > 0).mean()), days=float(tr["days"].mean()),
               p25=float(np.percentile(ret, 25)), p75=float(np.percentile(ret, 75)), p5=float(np.percentile(ret, 5)),
               worst=float(ret.min()))
    b = None
    if U is not None and h_base:
        bt = base_of(fwd(h_base), U)
        b = bt[t]
        out["base"] = float(np.nanmean(b))
        out["edge"] = out["mean"] - out["base"]
        # 按天平均
        df = pd.DataFrame({"t": t, "ex": ret - b, "ret": ret})
        g = df.groupby("t").mean()
        out["day_ex"] = float(g["ex"].mean()); out["day_ret"] = float(g["ret"].mean())
        full = np.full(T, np.nan); full[g.index.to_numpy()] = g["ex"].to_numpy()
        out["tstat"] = float(nw_t(full, h_base))
    if not quiet:
        s = (f"[{label}] n={out['n']} 均值 {out['mean']*100:+.2f}% 中位 {out['median']*100:+.2f}% 胜率 {out['win']*100:.0f}% "
             f"平均拿 {out['days']:.1f} 天 | 25%分位 {out['p25']*100:+.1f}% 75%分位 {out['p75']*100:+.1f}% 最差5% {out['p5']*100:+.1f}%")
        if b is not None:
            s += f" | 随便买 {out['base']*100:+.2f}% 优势 {out['edge']*100:+.2f}% 按天超额 {out['day_ex']*100:+.2f}% t={out['tstat']:.1f}"
        print(s)
    if years:
        rows = []
        for y in sorted(set(year.tolist())):
            m = year[t] == y
            if m.sum() == 0:
                continue
            r = ret[m]
            rows.append((int(y), int(m.sum()), float(r.mean()), float((r > 0).mean()), float((r - b[m]).mean()) if b is not None else np.nan))
        out["years"] = rows
        if not quiet:
            print("    年份   次数   均值    胜率   优势")
            for y, n, m_, w, e_ in rows:
                print(f"    {y} {n:6d} {m_*100:+6.2f}% {w*100:4.0f}% {e_*100:+6.2f}%")
    return out


def index_close(sym):
    z = np.load(os.path.join(HERE, "index", sym + ".npz"))
    pos = np.searchsorted(cal, z["d"])
    out = np.full(T, np.nan)
    ok = (pos < T)
    ok[ok] &= cal[pos[ok]] == z["d"][ok]
    out[pos[ok]] = z["c"][ok]
    return out


print(f"lab ready: {T} days x {N} stocks, {cal[0]}..{cal[-1]}", flush=True)
