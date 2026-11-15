"""实验 54b：行业「冷了多久 / 不景气了多久」，和之后一到三年的表现（2005–2026 连续，申万二级行业，成员不少于 8 只的才算）。

每 21 个交易日排一次队。行业收益 = 成员等权。「超额」= 行业之后的收益 − 同期全部行业的平均。
"""
import numpy as np, pandas as pd, json
a, b = np.load("indser_old.npz", allow_pickle=True), np.load("indser_new.npz", allow_pickle=True)
names = list(a["names"]); assert names == list(b["names"])
cat = lambda k: np.concatenate([a[k], b[k]])
d = cat("d"); n = len(d); K = len(names)
ret, pb, cnt, loss, nps, npp, roe = cat("ret"), cat("pb"), cat("cnt"), cat("loss"), cat("npsum"), cat("npsum_prev"), cat("roe")
ok = cnt >= 8
idx = np.cumprod(1 + np.nan_to_num(ret), axis=0)                 # 行业指数
idx[~np.isfinite(np.where(np.cumsum(np.isfinite(ret), axis=0) > 0, 1.0, np.nan))] = np.nan
mret = np.nanmean(np.where(ok, ret, np.nan), axis=1); mkt = np.cumprod(1 + np.nan_to_num(mret))
rel = idx / mkt[:, None]                                         # 相对全部行业平均的强弱线
year = d // 10000


def past(k):
    out = np.full((n, K), np.nan); out[k:] = idx[k:] / idx[:-k] - 1; return out


def past_rel(k):
    out = np.full((n, K), np.nan); out[k:] = rel[k:] / rel[:-k] - 1; return out


def fwd(k):
    out = np.full((n, K), np.nan); out[:-k] = idx[k:] / idx[:-k] - 1; return out


def roll_max(x, k, minp):
    return pd.DataFrame(x).rolling(k, min_periods=minp).max().to_numpy()


def days_since_high(x, k):
    """离过去 k 天里的最高点过去了多少天。"""
    out = np.full(x.shape, np.nan)
    df = pd.DataFrame(x)
    am = df.rolling(k, min_periods=k // 2).apply(lambda w: len(w) - 1 - np.nanargmax(w), raw=True)
    return am.to_numpy()


def pct_own(x, window=2440, minp=750):
    """每个行业的值在它自己过去十年里的分位（0–100）。"""
    out = np.full(x.shape, np.nan)
    for k in range(x.shape[1]):
        col = x[:, k]
        import bisect
        srt = []
        for t in range(len(col)):
            v = col[t]
            if np.isfinite(v):
                bisect.insort(srt, v)
            if t >= window and np.isfinite(col[t - window]):
                del srt[bisect.bisect_left(srt, col[t - window])]
            if np.isfinite(v) and len(srt) >= minp:
                out[t, k] = 100.0 * bisect.bisect_right(srt, v) / len(srt)
    return out


# 连续跑输的年数：最近 1、2、3、4、5 个「250 日」里，行业相对强弱线是不是每年都在跌
relY = [past_rel(250)] + [np.vstack([np.full((250 * j, K), np.nan), past_rel(250)[:-250 * j]]) for j in range(1, 5)]
under = np.zeros((n, K)); alive = np.ones((n, K), bool); known = np.isfinite(relY[0])
for j in range(5):
    lose = relY[j] < 0
    alive &= lose
    under += alive
under = np.where(known, under, np.nan)
with np.errstate(invalid="ignore", divide="ignore"):
    g = np.where(npp > 0, nps / npp - 1, np.nan)                 # 行业合计净利润同比
# 盈利下滑持续了几个季度（每 63 天看一次，连续为负的次数，最多 8）
down = np.zeros((n, K)); alive = np.ones((n, K), bool)
for j in range(8):
    gj = np.vstack([np.full((63 * j, K), np.nan), g[:n - 63 * j]]) if j else g
    alive &= gj < 0
    down += alive
down = np.where(np.isfinite(g), down, np.nan)
sig = {
    "过去 1 年涨幅": past(250), "过去 3 年涨幅": past(750), "过去 5 年涨幅": past(1250),
    "连续跑输的年数": under,
    "离三年高点的跌幅": idx / roll_max(idx, 750, 375) - 1,
    "相对强弱线离五年高点的跌幅": rel / roll_max(rel, 1250, 500) - 1,
    "离三年高点过去了多少天": days_since_high(idx, 750),
    "市净率在自己十年里的分位": pct_own(pb),
    "合计净利润同比": g, "盈利下滑持续的季度数": down, "亏损公司占比": loss, "净资产收益率在自己十年里的分位": pct_own(roe),
}
forms = np.arange(1300, n, 21)
OUT = {}


def test(X, h, lo_is_cold=True, nb=5, forms=forms, label=""):
    F = fwd(h); acc = np.zeros(nb); cntg = np.zeros(nb); yrs = {}; absacc = np.zeros(nb); wins = np.zeros(nb)
    for t in forms:
        if t + h >= n:
            break
        m = ok[t] & np.isfinite(X[t]) & np.isfinite(F[t])
        if m.sum() < 25:
            continue
        x = X[t][m]; f = F[t][m]; base = f.mean()
        r = pd.Series(x).rank(pct=True, method="first").to_numpy(); gidx = np.minimum((r * nb).astype(int), nb - 1)
        for k in range(nb):
            if (gidx == k).any():
                v = f[gidx == k].mean()
                acc[k] += v - base; absacc[k] += v; cntg[k] += 1; wins[k] += (v > 0)
                if k in (0, nb - 1):
                    yrs.setdefault((int(year[t]), k), []).append(v - base)
    ex = acc / np.maximum(cntg, 1)
    ys = sorted({y for y, _ in yrs})
    lowbeat = sum(1 for y in ys if np.mean(yrs.get((y, 0), [0])) > 0); highbeat = sum(1 for y in ys if np.mean(yrs.get((y, nb - 1), [0])) > 0)
    return {"ex": ex.tolist(), "abs": (absacc / np.maximum(cntg, 1)).tolist(), "win": (wins / np.maximum(cntg, 1)).tolist(), "low_beat": lowbeat, "high_beat": highbeat, "years": len(ys), "n": int(cntg[0])}


print(f"{d[0]}..{d[-1]}；排队日从 {d[forms[0]]} 起；行业数（成员≥8）平均 {int(ok[forms].sum(1).mean())}")
for h, hn in ((250, "一年"), (500, "两年"), (750, "三年")):
    print(f"===== 之后{hn}：五组超额（%），从指标最小的一组到最大的一组；括号里是最小组/最大组跑赢平均的年数 =====")
    for nm, X in sig.items():
        r = test(X, h); OUT[f"{nm}|{hn}"] = r
        print(f"  {nm:<24} " + " ".join(f"{v*100:+6.1f}" for v in r["ex"]) + f"   （最小组 {r['low_beat']}/{r['years']} 年，最大组 {r['high_beat']}/{r['years']} 年）")
# 连续跑输年数：按具体年数看（不是分组）
print("===== 连续跑输了几年的行业，之后的表现（绝对收益 / 相对全部行业平均 / 赚钱的比例）=====")
for h, hn in ((250, "一年"), (500, "两年"), (750, "三年")):
    F = fwd(h); row = f"  之后{hn}:"
    for yv in (0, 1, 2, 3, 4):
        rs, es = [], []
        for t in forms:
            if t + h >= n:
                break
            m = ok[t] & np.isfinite(under[t]) & np.isfinite(F[t])
            if m.sum() < 25:
                continue
            base = F[t][m].mean()
            k = m & ((under[t] == yv) if yv < 4 else (under[t] >= 4))
            if k.any():
                rs.append(F[t][k].mean()); es.append(F[t][k].mean() - base)
        if rs:
            row += f" | 跑输{yv}{'+' if yv == 4 else ''}年: {np.mean(rs)*100:+5.1f}% 超额 {np.mean(es)*100:+5.1f}% 赚钱 {np.mean(np.array(rs) > 0)*100:3.0f}% (n={len(rs)})"
            OUT[f"under{yv}|{hn}"] = {"abs": float(np.mean(rs)), "ex": float(np.mean(es)), "win": float(np.mean(np.array(rs) > 0)), "n": len(rs)}
    print(row)
# 两段分开看：2016 年以前排的队 / 以后排的队
cut = int(np.searchsorted(d, 20160101))
for nm in ("过去 3 年涨幅", "过去 5 年涨幅", "连续跑输的年数", "相对强弱线离五年高点的跌幅", "市净率在自己十年里的分位", "合计净利润同比", "盈利下滑持续的季度数", "净资产收益率在自己十年里的分位"):
    for h, hn in ((500, "两年"),):
        r1 = test(sig[nm], h, forms=forms[forms < cut]); r2 = test(sig[nm], h, forms=forms[forms >= cut])
        print(f"  [分段] {nm:<22} 之后{hn} | 2016 年以前: " + " ".join(f"{v*100:+5.1f}" for v in r1["ex"]) + f"（{r1['low_beat']}/{r1['years']}, {r1['high_beat']}/{r1['years']}） | 2016 年以后: " + " ".join(f"{v*100:+5.1f}" for v in r2["ex"]) + f"（{r2['low_beat']}/{r2['years']}, {r2['high_beat']}/{r2['years']}）")
        OUT[f"split|{nm}|{hn}"] = {"early": r1, "late": r2}
json.dump(OUT, open("exp54_industry.json", "w"), ensure_ascii=False, indent=1)
np.savez("indsig.npz", d=d, names=np.array(names), idx=idx, rel=rel, ok=ok, under=under, pbpct=sig["市净率在自己十年里的分位"], g=g, down=down, r3=sig["过去 3 年涨幅"], r5=sig["过去 5 年涨幅"], dd5=sig["相对强弱线离五年高点的跌幅"], roepct=sig["净资产收益率在自己十年里的分位"], loss=loss, pb=pb, roe=roe)
