"""实验 55：行业「冷了很久」再细看——去掉最近一年的涨跌只看更早的、冷了很久但开始回暖的、盈利由降转升的；
以及同一个行业自己和自己比（估值在自己历史低位时买，和高位时买）。"""
import numpy as np, pandas as pd, json
z = np.load("indsig.npz", allow_pickle=True)
d, names, idx, rel, ok = z["d"], list(z["names"]), z["idx"], z["rel"], z["ok"]
under, pbpct, g, down, roepct = z["under"], z["pbpct"], z["g"], z["down"], z["roepct"]
n, K = idx.shape
year = d // 10000
tz = np.load("temps.npz", allow_pickle=True); tn = list(tz["names"]); TEMP = tz[f"t{tn.index('两者平均(近10年)')}"]
assert (tz["d"] == d).all()


def lag(x, k):
    out = np.full(x.shape, np.nan); out[k:] = x[:-k]; return out


def chg(x, a, b):
    """从 a 天前到 b 天前的涨幅（a > b）。"""
    return lag(x, b) / lag(x, a) - 1 if b else x / lag(x, a) - 1


def fwd(x, k):
    out = np.full(x.shape, np.nan); out[:-k] = x[k:] / x[:-k] - 1; return out


forms = np.arange(1300, n, 21)


def groups(X, h, nb=5, forms=forms, mask=None):
    F = fwd(idx, h); acc = np.zeros(nb); c = np.zeros(nb); yrs = {}
    for t in forms:
        if t + h >= n:
            break
        m = ok[t] & np.isfinite(X[t]) & np.isfinite(F[t])
        if mask is not None:
            m &= mask[t]
        if m.sum() < 20:
            continue
        base = F[t][ok[t] & np.isfinite(F[t])].mean()
        r = pd.Series(X[t][m]).rank(pct=True, method="first").to_numpy(); gi = np.minimum((r * nb).astype(int), nb - 1); f = F[t][m]
        for k in range(nb):
            if (gi == k).any():
                acc[k] += f[gi == k].mean() - base; c[k] += 1
                if k in (0, nb - 1):
                    yrs.setdefault((int(year[t]), k), []).append(f[gi == k].mean() - base)
    ys = sorted({y for y, _ in yrs})
    return acc / np.maximum(c, 1), sum(1 for y in ys if np.mean(yrs.get((y, 0), [0])) > 0), sum(1 for y in ys if np.mean(yrs.get((y, nb - 1), [0])) > 0), len(ys)


def flag(B, h, forms=forms):
    """布尔条件成立的行业：之后的绝对收益、相对全部行业平均的超额、赚钱比例、跑赢的年数。"""
    F = fwd(idx, h); rs, es, yy = [], [], []
    for t in forms:
        if t + h >= n:
            break
        m = ok[t] & np.isfinite(F[t])
        k = m & B[t]
        if m.sum() < 20 or k.sum() < 2:
            continue
        rs.append(F[t][k].mean()); es.append(F[t][k].mean() - F[t][m].mean()); yy.append(int(year[t]))
    if not rs:
        return None
    df = pd.DataFrame({"y": yy, "e": es}); by = df.groupby("y")["e"].mean()
    return {"abs": float(np.mean(rs)), "ex": float(np.mean(es)), "win": float(np.mean(np.array(rs) > 0)), "beat_years": int((by > 0).sum()), "years": len(by), "n": len(rs)}


OUT = {}
sig = {
    "过去 1 年（最近 12 个月）": chg(idx, 250, 0),
    "更早的两年（3 年前到 1 年前）": chg(idx, 750, 250),
    "更早的四年（5 年前到 1 年前）": chg(idx, 1250, 250),
    "最近半年": chg(idx, 125, 0),
    "最近一个月": chg(idx, 21, 0),
}
for h, hn in ((250, "一年"), (500, "两年"), (750, "三年")):
    print(f"===== 之后{hn}：五组超额（%），从涨得最少到涨得最多 =====")
    for nm, X in sig.items():
        ex, lb, hb, ny = groups(X, h); OUT[f"{nm}|{hn}"] = {"ex": ex.tolist(), "low_beat": lb, "high_beat": hb, "years": ny}
        print(f"  {nm:<26} " + " ".join(f"{v*100:+6.1f}" for v in ex) + f"   （最冷组 {lb}/{ny} 年跑赢，最热组 {hb}/{ny} 年跑赢）")
# 冷了很久（更早的两年排在后三成）之后：现在回暖了 / 还在跌
old2 = sig["更早的两年（3 年前到 1 年前）"]; r6 = chg(rel, 125, 0); r12 = chg(rel, 250, 0)
rank = lambda X: pd.DataFrame(np.where(ok, X, np.nan)).rank(axis=1, pct=True).to_numpy()
ro, r6r, r12r, pbr, roer = rank(old2), rank(r6), rank(r12), rank(pbpct), rank(roepct)
turn_up = (g > 0) & (lag(g, 250) < 0)                # 盈利同比由负转正
still_dn = (g < 0) & (lag(g, 250) < 0)               # 连着两年都在降
conds = {
    "前两年跌得多（后三成）": ro < 0.3,
    "前两年跌得多 + 最近半年转强（前一半）": (ro < 0.3) & (r6r >= 0.5),
    "前两年跌得多 + 最近半年还弱（后一半）": (ro < 0.3) & (r6r < 0.5),
    "前两年跌得多 + 最近一年转强（前三成）": (ro < 0.3) & (r12r >= 0.7),
    "前两年涨得多（前三成）": ro >= 0.7,
    "前两年涨得多 + 最近半年还强": (ro >= 0.7) & (r6r >= 0.5),
    "前两年涨得多 + 最近半年转弱": (ro >= 0.7) & (r6r < 0.5),
    "连续跑输 3 年以上": under >= 3,
    "连续跑输 3 年以上 + 最近半年转强": (lag(under, 125) >= 3) & (r6r >= 0.7),
    "盈利同比由负转正": turn_up,
    "盈利连着两年下滑": still_dn,
    "盈利连着两年下滑 + 估值在自己低位（<30）": still_dn & (pbpct < 30),
    "盈利由负转正 + 估值在自己低位（<30）": turn_up & (pbpct < 30),
    "ROE 在自己低位（<20）": roepct < 20,
    "ROE 在自己低位 + 盈利由负转正": (roepct < 30) & turn_up,
    "ROE 在自己高位（>80）": roepct > 80,
    "估值在自己低位（<20）": pbpct < 20,
    "估值在自己高位（>80）": pbpct > 80,
}
for h, hn in ((250, "一年"), (500, "两年"), (750, "三年")):
    print(f"===== 之后{hn}：满足条件的行业 =====")
    for nm, B in conds.items():
        r = flag(B, h)
        if r:
            OUT[f"cond|{nm}|{hn}"] = r
            print(f"  {nm:<32} 平均 {r['abs']*100:+6.1f}%  相对全部行业 {r['ex']*100:+5.1f}%  赚钱 {r['win']*100:3.0f}%  跑赢的年份 {r['beat_years']}/{r['years']}  (n={r['n']})")
# 行业自己的估值分位 × 市场温度：同样的市场温度下，行业自己便宜不便宜有没有用
print("===== 行业自己的估值分位 × 市场温度：之后两年的绝对收益（赚钱比例）=====")
F = fwd(idx, 500)
for tl, tm in (("市场温度<40", TEMP < 40), ("市场温度 40-60", (TEMP >= 40) & (TEMP < 60)), ("市场温度≥60", TEMP >= 60)):
    row = f"  {tl:<12}"
    for pl, lo, hi in (("行业估值<30", 0, 30), ("30-70", 30, 70), ("≥70", 70, 101)):
        vals = []
        for t in forms:
            if t + 500 >= n or not tm[t]:
                continue
            k = ok[t] & np.isfinite(F[t]) & (pbpct[t] >= lo) & (pbpct[t] < hi)
            if k.sum() >= 2:
                vals.append(F[t][k].mean())
        if vals:
            row += f" | {pl}: {np.mean(vals)*100:+6.1f}% ({np.mean(np.array(vals) > 0)*100:3.0f}%, n={len(vals)})"
            OUT[f"grid|{tl}|{pl}"] = {"abs": float(np.mean(vals)), "win": float(np.mean(np.array(vals) > 0)), "n": len(vals)}
    print(row)
json.dump(OUT, open("exp55_industry_more.json", "w"), ensure_ascii=False, indent=1)
