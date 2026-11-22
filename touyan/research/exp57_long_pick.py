"""实验 57：长期名单里具体挑哪几只——高股息里混着「利润在垮、分红保不住」的，要不要加条件。

在稳健名单（赚钱 + 分红 + 三年 ROE ≥ 8% + 不属于四种热）上比几种加法和排序：
  利润没有大幅下滑（最新累计净利润同比 ≥ −20% / ≥ 0）、滚动 ROE 不低于 6%、
  按「近两年里较少的那一年的分红」算股息率（防一次性的大额分红）。
看三样：整组拿一年 / 两年；按排序取前 10、前 30 只拿一年 / 两年；10 只的组合连续持有（每季度检查、不在名单里就换）。
"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *

print(f"@@@@@ {which} 长期挑哪几只 @@@@@")
LC = os.path.join(HERE, f"lpanel{TAG}2")
DIVD = np.load(os.path.join(LC, "divd.npy")); DIV12 = roll_sum(DIVD, 250)[0]; DIVP = shift(DIV12.astype(np.float32), 250)
ROE_MIN3 = np.load(os.path.join(LC, "annual.npy"))[1]
EPS = np.load(os.path.join(FPD, "eps_ttm.npy")); BPS = np.load(os.path.join(FPD, "bps.npy"))
with np.errstate(invalid="ignore", divide="ignore"):
    ROET = np.where(BPS > 0, EPS / BPS, np.nan)
    DY = DIV12 / Cf
    DYS = np.minimum(DIV12, np.where(np.isfinite(DIVP), DIVP, 0)) / Cf           # 近两年里较少的一年
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r6 = pct_rank(F("r600"), U); r6 = np.where(np.isfinite(r6), r6, 0.5)
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r6 >= 0.8)
steady = U & ~hot & PROFIT & (DIV12 > 0) & (ROE_MIN3 >= 8)
g20 = GROW >= -0.20; g0 = GROW >= 0; r6ok = ROET >= 0.06
variants = {
    "V0 稳健名单，按股息率": (steady, DY),
    "V1 + 利润同比 ≥ −20%": (steady & g20, DY),
    "V2 + 利润同比 ≥ 0": (steady & g0, DY),
    "V3 + 滚动 ROE ≥ 6%": (steady & r6ok, DY),
    "V4 + 利润 ≥ −20% + 滚动 ROE ≥ 6%": (steady & g20 & r6ok, DY),
    "V5 按近两年较少的分红排": (steady & (DYS > 0), DYS),
    "V6 V4 + 按近两年较少的分红排": (steady & g20 & r6ok & (DYS > 0), DYS),
    "V7 V2 + 滚动 ROE ≥ 6% + 较少的分红": (steady & g0 & r6ok & (DYS > 0), DYS),
}
OUT = {}


def form_days(h, step=21, warm=520):
    return np.arange(warm, T - h - 2, step)


def evalsel(sel, h):
    Fh = fwd(h); rows = []
    for t in form_days(h):
        okf = np.isfinite(Fh[t]); s = sel[t] & okf; b = U[t] & okf
        if s.sum() < 3 or b.sum() == 0:
            continue
        rows.append((int(t), float(Fh[t][s].mean()), float(Fh[t][b].mean()), int(s.sum())))
    df = pd.DataFrame(rows, columns=["t", "ret", "base", "n"])
    if not len(df):
        return None
    y = year[df["t"].to_numpy()]; ex = df["ret"] - df["base"]; by = ex.groupby(y).mean()
    return {"ret": float(df["ret"].mean()), "ex": float(ex.mean()), "win": float((df["ret"] > 0).mean()), "beat": int((by > 0).sum()), "years": len(by), "n": float(df["n"].mean()), "worst": float(df["ret"].min())}


def topn(mask, key, n, cap=2):
    P = np.zeros((T, N), bool)
    for t in form_days(245):
        idx = np.nonzero(mask[t] & np.isfinite(key[t]))[0]
        if len(idx) == 0:
            continue
        order = idx[np.argsort(-key[t, idx])]; used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if cap and used.get(g, 0) >= cap:
                continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n:
                break
    return P


Rz = np.where(valid, R, 0.0)


def portfolio(mask, key, n=10, review=63, cap=2, cost=0.002, start=520):
    hold = {}; cash = 1.0; eq = np.ones(T)
    for t in range(start, T - 1):
        if (t - start) % review == 0:
            for j in list(hold):
                if not mask[t, j]:
                    cash += hold.pop(j) * (1 - cost / 2)
            need = n - len(hold)
            if need > 0:
                idx = np.nonzero(mask[t] & np.isfinite(key[t]))[0]
                order = idx[np.argsort(-key[t, idx])]; used = {}
                for j in hold:
                    used[ind_of[j]] = used.get(ind_of[j], 0) + 1
                per = cash / need
                for j in order:
                    if need == 0:
                        break
                    if j in hold or used.get(ind_of[j], 0) >= cap:
                        continue
                    used[ind_of[j]] = used.get(ind_of[j], 0) + 1; hold[j] = per * (1 - cost / 2); cash -= per; need -= 1
        for j in hold:
            hold[j] *= 1 + Rz[t + 1, j]
        eq[t + 1] = cash + sum(hold.values())
    e = eq[start:] / eq[start]; r = e[1:] / e[:-1] - 1; yy = cal[start + 1:] // 10000
    by = {int(y): float(np.prod(1 + r[yy == y]) - 1) for y in sorted(set(yy.tolist()))}
    return {"cagr": float(e[-1] ** (245 / (len(e) - 1)) - 1), "mdd": float((e / np.maximum.accumulate(e) - 1).min()), "neg": int(sum(1 for v in by.values() if v < 0)), "years": len(by), "by": by}


base = np.cumprod(1 + np.nanmean(np.where(U & valid, R, np.nan), axis=1)[521:])
print(f"  全池等权连续持有年化 {(base[-1] ** (245 / len(base)) - 1) * 100:+.1f}%")
for nm, (m, key) in variants.items():
    g1, g2 = evalsel(m, 245), evalsel(m, 490)
    t10 = topn(m, key, 10); t30 = topn(m, key, 30)
    a1, a2 = evalsel(t10, 245), evalsel(t10, 490); b1, b2 = evalsel(t30, 245), evalsel(t30, 490)
    pf = portfolio(m, key)
    OUT[nm] = {"group_1y": g1, "group_2y": g2, "top10_1y": a1, "top10_2y": a2, "top30_1y": b1, "top30_2y": b2, "portfolio": pf}
    f = lambda x: f"{x['ret']*100:+5.1f}%(超额{x['ex']*100:+5.1f} 赢{x['beat']}/{x['years']})" if x else "—"
    print(f"  {nm:<34} 每期 {g1['n']:4.0f} 只 | 整组 1年 {f(g1)} 2年 {f(g2)} | 前30 1年 {f(b1)} 2年 {f(b2)} | 前10 1年 {f(a1)} 2年 {f(a2)} | 10只组合 年化 {pf['cagr']*100:+5.1f}% 回撤 {pf['mdd']*100:.0f}% 亏 {pf['neg']}/{pf['years']} 年", flush=True)
json.dump(OUT, open(f"exp57_{which}.json", "w"), ensure_ascii=False, indent=1)
