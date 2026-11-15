"""研究用（长期）：长期持有要用到的量——估值、分红、盈利质量——都只用到当天已经公告的数据。

用法：which = "new" / "old"，先设 LAB_PANEL 再 import。
"""
import json, os, sys
import numpy as np, pandas as pd
from feat import *
from adjust import parse_content

U = UREL if TAG == "_old" else UALL          # 股票池：成交活跃的（和短期、中期的检验一致）
FPD = os.path.join(HERE, f"fpanel{TAG}2")        # 财报按「真实公告日，否则法定截止日」对齐（见 fundpanel2.py）
LCACHE = os.path.join(HERE, f"lpanel{TAG}2")
os.makedirs(LCACHE, exist_ok=True)


def FP(k):
    return np.load(os.path.join(FPD, k + ".npy"))


EPS, BPS, NPY, SQY, REVY, GM, CFPS, PER, NPTTM = (FP(k) for k in ("eps_ttm", "bps", "np_yoy", "sq_yoy", "rev_yoy", "gm", "cfps", "per", "np_ttm"))
with np.errstate(invalid="ignore", divide="ignore"):
    EP = (EPS / Cf).astype(np.float32)                       # 盈利收益率（市盈率的倒数；亏损为负）
    BP = np.where(BPS > 0, BPS / Cf, np.nan).astype(np.float32)
    ROE = np.where(BPS > 0, EPS / BPS, np.nan).astype(np.float32)   # 滚动 12 个月的净资产收益率


def _cached(name, build):
    path = os.path.join(LCACHE, name + ".npy")
    if os.path.exists(path):
        return np.load(path)
    x = build()
    np.save(path, x)
    return x


def _build_div():
    """除息日当天的每股现金分红（折成复权价的口径）。"""
    D = np.zeros((T, N), np.float32)
    adj = ffill((C / RC).astype(np.float32))
    edir = os.path.join(HERE, "events" + TAG)
    for j, code in enumerate(codes):
        path = os.path.join(edir, code + ".json")
        if not os.path.exists(path):
            continue
        for ds, info in json.load(open(path, encoding="utf-8")).items():
            di = int(ds.replace("-", ""))
            k = int(np.searchsorted(cal, di))
            if k >= T or cal[k] != di or k == 0:
                continue
            pc = parse_content(info.get("FHcontent"))
            if not pc or pc[0] <= 0:
                continue
            f = adj[k - 1, j]
            if np.isfinite(f):
                D[k, j] += pc[0] * f
    return D


DIVD = _cached("divd", _build_div)
DIV12 = roll_sum(DIVD, 250)[0].astype(np.float32)             # 最近一年的现金分红
with np.errstate(invalid="ignore", divide="ignore"):
    DY = (DIV12 / Cf).astype(np.float32)                      # 股息率
    PAYOUT = np.where(EPS > 0, DIV12 / EPS, np.nan).astype(np.float32)
# 连续分红的年数（最近 k 年每年都有现金分红）
_d1 = (roll_sum(DIVD, 250)[0] > 0)
DIV3Y = _d1 & shift(_d1.astype(np.float32), 250).astype(bool) & shift(_d1.astype(np.float32), 500).astype(bool)


def _build_annual():
    """年报的净资产收益率：最新一年、近三年最低、近三年平均（公告日起生效）。"""
    rep = pd.read_pickle(os.path.join(HERE, f"rep{TAG}2.pkl"))
    ann = rep[(rep["per"] % 10000 == 1231) & (rep["t0"] >= 0)].sort_values(["i", "per"])
    last = np.full((T, N), np.nan, np.float32); mn = last.copy(); mean = last.copy(); cf = last.copy(); gmn = last.copy()
    for i, g in ann.groupby("i"):
        roe = g["roe"].to_numpy(); t0 = g["t0"].to_numpy(); per = g["per"].to_numpy()
        eps = g["eps"].to_numpy(); cfps = g["cfps"].to_numpy(); gm = g["gm"].to_numpy()
        for k in range(len(g)):
            t = int(t0[k])
            if t >= T:
                continue
            t = max(t, 0)
            win = [roe[m] for m in range(max(0, k - 2), k + 1) if np.isfinite(roe[m]) and per[k] - per[m] <= 20000]
            last[t:, i] = roe[k]
            if len(win) >= 2:
                mn[t:, i] = min(win); mean[t:, i] = sum(win) / len(win)
            else:
                mn[t:, i] = np.nan; mean[t:, i] = np.nan
            rr = [cfps[m] / eps[m] for m in range(max(0, k - 2), k + 1) if np.isfinite(cfps[m]) and np.isfinite(eps[m]) and eps[m] > 0]
            cf[t:, i] = sum(rr) / len(rr) if rr else np.nan
            gg = [gm[m] for m in range(max(0, k - 2), k + 1) if np.isfinite(gm[m])]
            gmn[t:, i] = (max(gg) - min(gg)) if len(gg) >= 2 else np.nan
    return np.stack([last, mn, mean, cf, gmn])


_ann = _cached("annual", _build_annual)
ROE_ANN, ROE_MIN3, ROE_MEAN3, CASH3, GM_RANGE = _ann[0], _ann[1], _ann[2], _ann[3], _ann[4]


def form_days(h, step=21, warm=260):
    return np.arange(warm, T - h - 2, step)


def port(sel, h, days=None, base_mask=None):
    """每个建仓日：选中的股票下一交易日开盘买入、拿 h 个交易日的平均收益（扣 0.2%），和同日全池平均比。
    sel：[T,N] 布尔。返回 DataFrame(t, n, ret, base, ex)。"""
    Fh = fwd(h)
    days = form_days(h) if days is None else days
    bm = U if base_mask is None else base_mask
    rows = []
    for t in days:
        ok = np.isfinite(Fh[t])
        s = sel[t] & ok
        b = bm[t] & ok
        if s.sum() == 0 or b.sum() == 0:
            continue
        r = float(Fh[t][s].mean()); bb = float(Fh[t][b].mean())
        rows.append((int(t), int(s.sum()), r, bb, r - bb, float(np.median(Fh[t][s])), float((Fh[t][s] > 0).mean())))
    return pd.DataFrame(rows, columns=["t", "n", "ret", "base", "ex", "med", "win"])


def show(label, df, years=True):
    if not len(df):
        print(f"  {label:<34} 没有样本"); return {}
    y = year[df["t"].to_numpy()]
    by = df.groupby(y)["ex"].mean()
    byr = df.groupby(y)["ret"].mean()
    beat = int((by > 0).sum()); pos = int((byr > 0).sum())
    out = {"n_days": len(df), "avg_n": float(df["n"].mean()), "ret": float(df["ret"].mean()), "base": float(df["base"].mean()), "ex": float(df["ex"].mean()),
           "win_days": float((df["ret"] > 0).mean()), "beat_days": float((df["ex"] > 0).mean()), "beat_years": beat, "pos_years": pos, "years": len(by),
           "worst": float(df["ret"].min()), "stock_win": float(df["win"].mean()), "by_year_ex": {int(k): float(v) for k, v in by.items()}, "by_year_ret": {int(k): float(v) for k, v in byr.items()}}
    s = (f"  {label:<34} 每期 {out['avg_n']:6.0f} 只 | 平均 {out['ret']*100:+6.1f}% 全池 {out['base']*100:+6.1f}% 超额 {out['ex']*100:+5.1f}% | "
         f"建仓日里赚钱 {out['win_days']*100:3.0f}% 跑赢 {out['beat_days']*100:3.0f}% | 跑赢的年份 {beat}/{len(by)} 赚钱的年份 {pos}/{len(by)} | 最差 {out['worst']*100:+.0f}% 个股胜率 {out['stock_win']*100:.0f}%")
    if years:
        s += "\n      超额按年: " + " ".join(f"{int(k)%100:02d}:{v*100:+.0f}" for k, v in by.items())
    print(s, flush=True)
    return out


def quint(X, h, mask, nb=5, days=None):
    """指标从小到大分 nb 组，各组的平均超额（相对 mask 内的平均）。"""
    Fh = fwd(h)
    days = form_days(h) if days is None else days
    acc = np.zeros(nb); cnt = np.zeros(nb); yrs = {}
    for t in days:
        m = mask[t] & np.isfinite(Fh[t]) & np.isfinite(X[t])
        if m.sum() < nb * 10:
            continue
        x = X[t][m]; f = Fh[t][m]
        r = pd.Series(x).rank(pct=True).to_numpy()
        g = np.minimum((r * nb).astype(int), nb - 1)
        b = f.mean()
        for k in range(nb):
            if (g == k).any():
                v = f[g == k].mean() - b
                acc[k] += v; cnt[k] += 1
                if k in (0, nb - 1):
                    yrs.setdefault((int(year[t]), k), []).append(v)
    out = acc / np.maximum(cnt, 1)
    ys = sorted({y for y, _ in yrs})
    top_beat = sum(1 for y in ys if np.mean(yrs.get((y, nb - 1), [0])) > 0)
    bot_beat = sum(1 for y in ys if np.mean(yrs.get((y, 0), [0])) > 0)
    return out, top_beat, bot_beat, len(ys)
