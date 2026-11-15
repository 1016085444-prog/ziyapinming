"""实验 49：短期的交易方法细化——拿几天、止损放哪、怎么买（开盘价 / 挂低价等）、分数越高是不是越该重仓、买几只。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *

OUT = {}
GO = S >= 3
P = pick(oks, ps, days=GO)
print(f"===== {which}：分数≥3 的日子 {int(GO.sum())} 天 =====")
print("--- 拿几天 × 止损 ---")
for hold in (2, 3, 5, 8, 10):
    for stop in (None, 0.06, 0.08, 0.10):
        OUT[f"hold{hold}|stop{stop}"] = brief(trades(P, max_days=hold, stop=stop, max_gap=0.02), f"拿{hold}天 止损{'无' if stop is None else f'{stop*100:.0f}%'}")
print("--- 高开多少以内才买 ---")
for gap in (-0.01, 0.0, 0.01, 0.02, 0.03, 0.10):
    OUT[f"gap{gap}"] = brief(trades(P, max_days=5, stop=0.08, max_gap=gap), f"开盘涨幅 ≤{gap*100:+.0f}% 才买")


def limit_entry(Pm, disc, max_days=5, stop=0.08, cost=COST):
    """信号次日不在开盘买，而是挂「昨收 × (1−disc)」的限价单：开盘低于限价按开盘成交，盘中最低价到了限价按限价成交，没到就不买。"""
    tt, ii = np.nonzero(Pm); e = tt + 1
    keep = e + max_days + 1 < T; tt, ii, e = tt[keep], ii[keep], e[keep]
    pc = PC[e, ii].astype(np.float64); o = O[e, ii].astype(np.float64); lo = L[e, ii].astype(np.float64)
    lim_px = pc * (1 - disc)
    filled = np.isfinite(o) & ~open_up[e, ii] & ~one_line[e, ii] & (lo <= lim_px)
    entry = np.where(o <= lim_px, o, lim_px)
    tt, ii, e, entry = tt[filled], ii[filled], e[filled], entry[filled]
    n = len(tt); alive = np.ones(n, bool); exitp = np.full(n, np.nan); days = np.zeros(n, np.int32); pend = np.zeros(n, bool)
    for k in range(1, max_days + 7):
        dd = np.minimum(e + k, T - 1); oo = O[dd, ii].astype(np.float64); c = C[dd, ii].astype(np.float64); trading = np.isfinite(c) & (e + k < T)
        m = alive & pend & trading; exitp[m] = oo[m]; days[m] = k; alive[m] = False
        locked = dn_lim[dd, ii]
        if stop is not None:
            m = alive & trading & (c <= entry * (1 - stop)); mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; alive[mm] = False
            pend[m & locked] = True
        if k >= max_days:
            m = alive & trading & ~pend; mm = m & ~locked
            exitp[mm] = c[mm]; days[mm] = k; alive[mm] = False
            pend[m & locked] = True
        if not alive.any():
            break
    m = alive
    if m.any():
        dd = np.minimum(e + max_days + 6, T - 1); exitp[m] = Cf[dd[m], ii[m]]; days[m] = max_days + 7
    return {"t": tt, "i": ii, "ret": exitp / entry * (1 - cost) - 1, "days": days, "reason": np.zeros(n, np.int8)}, float(filled.mean())


print("--- 怎么买：开盘价 对比 挂低价 ---")
OUT["entry|open"] = brief(trades(P, max_days=5, stop=0.08, max_gap=0.02), "开盘买（高开 2% 以上放弃）")
for disc in (0.0, 0.01, 0.02, 0.03):
    tr, fill = limit_entry(P, disc)
    r = brief(tr, f"挂昨收价下方 {disc*100:.0f}% 买（成交 {fill*100:.0f}%）"); r["fill"] = fill; OUT[f"entry|limit{disc}"] = r
    # 没成交的那部分钱等于空着：按「每个信号」算的平均收益
    print(f"      按每个信号算（没成交记 0）：{r.get('mean', 0) * fill * 100:+.2f}%")
print("--- 分数越高越好吗 ---")
for lab, m in (("分数=2", S == 2), ("分数=3", S == 3), ("分数=4", S == 4), ("分数≥5", S >= 5)):
    OUT[f"score|{lab}"] = brief(trades(pick(oks, ps, days=m), max_days=5, stop=0.08, max_gap=0.02), f"{lab}（{int(m.sum())} 天）")
print("--- 买几只 ---")
for n in (1, 3, 5, 8, 10):
    OUT[f"n|{n}"] = brief(trades(pick(oks, ps, days=GO, n=n), max_days=5, stop=0.08, max_gap=0.02), f"每次 {n} 只")
print("--- 卖在哪：第 5 天收盘 对比 第 6 天开盘 ---")
tr = trades(P, max_days=5, stop=0.08, max_gap=0.02)
nxt_open = O[np.minimum(tr["t"] + 1 + tr["days"] + 1, T - 1), tr["i"]]; last_close = C[np.minimum(tr["t"] + 1 + tr["days"], T - 1), tr["i"]]
ok = np.isfinite(nxt_open) & np.isfinite(last_close)
print(f"  卖出日收盘卖 对比 再等一晚第二天开盘卖：第二天开盘平均比收盘 {np.mean(nxt_open[ok] / last_close[ok] - 1) * 100:+.2f}%（{(nxt_open[ok] > last_close[ok]).mean() * 100:.0f}% 的时候更高）")
json.dump(OUT, open(f"exp49_{which}.json", "w"), ensure_ascii=False, indent=1)
