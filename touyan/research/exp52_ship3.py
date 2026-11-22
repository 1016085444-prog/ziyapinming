"""实验 52：四个板块最终规则的检验数字（ship3_{which}.json），软件里 evidence.py 的数字从这里抄。

短期：规则不变（分数≥3 出手，拿 5 天，收盘跌破 8% 止损），加上按市场温度分开看。
中期：选股不变；卖出改成「最多拿 120 个交易日；收盘涨停次日卖；冷热分掉到 30 以下次日卖；不设价格止损」。
长期：稳健名单（赚钱 + 近一年分红 + 三年 ROE 不低于 8% + 最新财报利润同比不低于 −20% + 不属于四种热 + 行业不在长期走弱里），
      按建仓时的市场温度看一年、两年、三年。
      「四种热」用软件里拿得到的口径：250 日波动最高两成、250 日换手最高两成、冷热分最低两成、两年半（600 日）涨幅最高两成。
"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *
from exp50_mid_plan import sim_mid, TEMP          # noqa: E402

print(f"@@@@@ {which} ship3 @@@@@")
OUT = {"period": [int(cal[0]), int(cal[-1])], "days": int(T), "pool": int(U.sum(1)[300:].mean())}
B6 = base_of(fwd(6), U)


def full(tr, label, hb):
    r = brief(tr, label, hb=hb)
    ret, t = tr["ret"], tr["t"]
    b = base_of(fwd(hb), U)[t]
    df = pd.DataFrame({"t": t, "r": ret, "ex": ret - b}); g = df.groupby("t").mean(); yr = year[g.index.to_numpy()]
    r["base"] = float(np.nanmean(b)); r["excess"] = float(g["ex"].mean())
    r["by_year_n"] = {int(y): int((year[t] == y).sum()) for y in ys if (year[t] == y).sum()}
    r["by_year_win"] = {int(y): float((ret[year[t] == y] > 0).mean()) for y in ys if (year[t] == y).sum()}
    r["by_year_base"] = {int(y): float(np.nanmean(b[year[t] == y])) for y in ys if (year[t] == y).sum()}
    r["hist"] = np.histogram(np.clip(ret, -0.3, 0.5), bins=np.arange(-0.30, 0.5001, 0.05))[0].tolist()
    return r


# ---------- 大盘预估分 ----------
tab = {}
for lab, m in (("le-1", S <= -1), ("0", S == 0), ("1", S == 1), ("2", S == 2), ("ge3", S >= 3)):
    ok = m & np.isfinite(B6)
    tab[lab] = {"days": int(ok.sum()), "share": float(ok.mean()), "h5": float(np.nanmean(B6[ok])), "up5": float(np.nanmean(B6[ok] > 0))}
OUT["score_table"] = tab
st = {}
for tl, tm in (("lt40", TEMP < 40), ("40to60", (TEMP >= 40) & (TEMP < 60)), ("60to80", (TEMP >= 60) & (TEMP < 80)), ("ge80", TEMP >= 80)):
    for sl, sm in (("le-1", S <= -1), ("0to1", (S >= 0) & (S <= 1)), ("2", S == 2), ("ge3", S >= 3)):
        k = tm & sm & np.isfinite(B6)
        if k.sum() >= 5:
            st[f"{tl}|{sl}"] = {"days": int(k.sum()), "h5": float(np.nanmean(B6[k])), "up5": float(np.nanmean(B6[k] > 0))}
OUT["score_by_temp"] = st
# ---------- 短期 ----------
OUT["short"] = {}
for thr in (3, 2):
    OUT["short"][f"ge{thr}"] = full(trades(pick(oks, ps, days=S >= thr), max_days=5, stop=0.08, max_gap=0.02), f"短期 分数≥{thr}", 6)
OUT["short"]["ge3_nostop"] = full(trades(pick(oks, ps, days=S >= 3), max_days=5, max_gap=0.02), "短期 分数≥3 不止损", 6)
OUT["short"]["ge3_hold10"] = full(trades(pick(oks, ps, days=S >= 3), max_days=10, stop=0.08, max_gap=0.02), "短期 分数≥3 拿 10 天", 11)
OUT["short"]["everyday"] = full(trades(pick(oks, ps), max_days=5, stop=0.08, max_gap=0.02), "短期 每天都选", 6)
OUT["short"]["le-1"] = full(trades(pick(oks, ps, days=S <= -1), max_days=5, stop=0.08, max_gap=0.02), "短期 分数≤-1", 6)
for tl, tm in (("lt40", TEMP < 40), ("40to60", (TEMP >= 40) & (TEMP < 60)), ("60to80", (TEMP >= 60) & (TEMP < 80)), ("ge60", TEMP >= 60), ("ge80", TEMP >= 80), ("lt80", TEMP < 80), ("lt60", TEMP < 60)):
    dm = (S >= 3) & tm
    if dm.sum() >= 8:
        OUT["short"][f"temp_{tl}"] = full(trades(pick(oks, ps, days=dm), max_days=5, stop=0.08, max_gap=0.02), f"短期 分数≥3 温度 {tl}（{int(dm.sum())} 天）", 6)
# ---------- 中期 ----------
P = pick(okm, COLD)
EXIT = up_lim | (cold < 0.3)
OUT["mid"] = {"candidates": int(okm.sum(1)[300:].mean())}
OUT["mid"]["all"] = full(sim_mid(P, 120, flag=EXIT), "中期 新方案：最多120天/涨停次日卖/冷热分<30卖", 65)
OUT["mid"]["old60"] = full(sim_mid(P, 60, flag=up_lim), "中期 原方案：最多60天/涨停次日卖", 50)
OUT["mid"]["stop12"] = full(sim_mid(P, 120, flag=EXIT, stop=0.12), "中期 新方案 + 12% 止损", 40)
OUT["mid"]["stop20"] = full(sim_mid(P, 120, flag=EXIT, stop=0.20), "中期 新方案 + 20% 止损", 50)
tr = sim_mid(P, 120, flag=EXIT)
OUT["mid"]["exit_reasons"] = {"limit_or_hot": int((tr["reason"] == 3).sum()), "expire": int((tr["reason"] == 0).sum())}
for lab, m in (("ge2", S >= 2), ("0to1", (S >= 0) & (S <= 1)), ("le-1", S <= -1)):
    OUT["mid"][f"score_{lab}"] = full(sim_mid(pick(okm, COLD, days=m), 120, flag=EXIT), f"中期 建仓日分数 {lab}", 65)
for tl, tm in (("lt20", TEMP < 20), ("20to40", (TEMP >= 20) & (TEMP < 40)), ("lt40", TEMP < 40), ("40to60", (TEMP >= 40) & (TEMP < 60)), ("60to80", (TEMP >= 60) & (TEMP < 80)), ("40to80", (TEMP >= 40) & (TEMP < 80)), ("ge80", TEMP >= 80)):
    if tm.sum() >= 20:
        OUT["mid"][f"temp_{tl}"] = full(sim_mid(pick(okm, COLD, days=tm), 120, flag=EXIT), f"中期 建仓日温度 {tl}（{int(tm.sum())} 天）", 65)


def grp(G, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M; cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {int(y): float(np.nanmean(dex[year == y])) for y in ys if np.isfinite(dex[year == y]).any()}
    return {"ret": float(np.nanmean(dr)), "ex": float(np.nanmean(dex)), "win": float(np.nanmean(np.where(G, Fh > 0, np.nan))), "by_year": ye, "pos_years": int(sum(1 for v in ye.values() if v > 0)), "years": len(ye)}


OUT["cold"] = {"hot10_h20": grp(cold < 0.1, 21), "hot10_h60": grp(cold < 0.1, 61), "hot20_h120": grp(cold < 0.2, 121), "cold10_h60": grp(cold >= 0.9, 61), "cand_h20": grp(okm, 21), "cand_h60": grp(okm, 61), "cand_h120": grp(okm, 121)}
for k, v in OUT["cold"].items():
    print(f"  {k}: 收益 {v['ret']*100:+.2f}% 超额 {v['ex']*100:+.2f}% 个股胜率 {v['win']*100:.0f}% 赢 {v['pos_years']}/{v['years']}")
# ---------- 长期 ----------
FPD2 = os.path.join(HERE, f"fpanel{TAG}2")
LC = os.path.join(HERE, f"lpanel{TAG}2")
DIVD = np.load(os.path.join(LC, "divd.npy")); DIV12 = roll_sum(DIVD, 250)[0]
ann = np.load(os.path.join(LC, "annual.npy")); ROE_MIN3 = ann[1]
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r6 = pct_rank(F("r600"), U); r6 = np.where(np.isfinite(r6), r6, 0.5)
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r6 >= 0.8)
sound = PROFIT & (DIV12 > 0) & (ROE_MIN3 >= 8) & (GROW >= -0.20)          # 最新财报累计净利润同比没有大幅下滑（实验 57）
# 行业长期走弱的不要（实验 54–56）：行业两年半的相对表现排在后三成、最近半年也在后一半
_z = np.load(os.path.join(HERE, "indsig.npz"), allow_pickle=True)
_pos = np.searchsorted(_z["d"], cal); _rel = _z["rel"]; _okI = _z["ok"]
def _lag(x, k):
    out = np.full(x.shape, np.nan); out[k:] = x[:-k]; return out
_rank = lambda X: pd.DataFrame(np.where(_okI, X, np.nan)).rank(axis=1, pct=True).to_numpy()
_weakI = (_rank(_rel / _lag(_rel, 600) - 1) < 0.3) & (_rank(_rel / _lag(_rel, 125) - 1) < 0.5)
_col = {nm: k for k, nm in enumerate(list(_z["names"]))}
_ik = np.array([_col.get(x, -1) for x in ind_of])
WEAK = np.zeros((T, N), bool); WEAK[:, _ik >= 0] = _weakI[_pos][:, _ik[_ik >= 0]]
steady = U & ~hot & sound & ~WEAK
with np.errstate(invalid="ignore", divide="ignore"):
    DY = DIV12 / Cf
OUT["long"] = {"steady_n": int(steady.sum(1)[300:].mean()), "hot_share": float((U & hot).sum(1)[300:].mean() / U.sum(1)[300:].mean())}


def form_days(h, step=21, warm=260):
    return np.arange(warm, T - h - 2, step)


def port(sel, h):
    Fh = fwd(h); rows = []
    for t in form_days(h):
        ok = np.isfinite(Fh[t]); s = sel[t] & ok; b = U[t] & ok
        if s.sum() == 0 or b.sum() == 0:
            continue
        rows.append((int(t), float(Fh[t][s].mean()), float(Fh[t][b].mean()), float((Fh[t][s] > 0).mean())))
    return pd.DataFrame(rows, columns=["t", "ret", "base", "win"])


for h, hn in ((245, "1y"), (490, "2y"), (735, "3y")):
    if T - h - 262 < 150:
        continue
    for nm, m in (("steady", steady), ("all", U), ("hot", U & hot)):
        df = port(m, h); tt = TEMP[df["t"].to_numpy()]
        y = year[df["t"].to_numpy()]
        res = {"n": len(df), "ret": float(df["ret"].mean()), "base": float(df["base"].mean()), "win_days": float((df["ret"] > 0).mean()), "worst": float(df["ret"].min()), "stock_win": float(df["win"].mean()),
               "by_year": {int(k): float(v) for k, v in df.groupby(y)["ret"].mean().items()}, "by_year_base": {int(k): float(v) for k, v in df.groupby(y)["base"].mean().items()}}
        for lo, hi in ((0, 20), (20, 40), (0, 40), (40, 60), (60, 80), (40, 80), (80, 101)):
            k = np.isfinite(tt) & (tt >= lo) & (tt < hi)
            if k.sum() >= 3:
                x = df["ret"].to_numpy()[k]
                res[f"temp_{lo}_{min(hi, 100)}"] = {"n": int(k.sum()), "mean": float(x.mean()), "median": float(np.median(x)), "win": float((x > 0).mean()), "worst": float(x.min())}
        OUT["long"][f"{nm}_{hn}"] = res
        print(f"  长期 {nm} {hn}: 平均 {res['ret']*100:+.1f}%（全池 {res['base']*100:+.1f}%）建仓日里赚钱 {res['win_days']*100:.0f}% 最差 {res['worst']*100:+.0f}% | " +
              " ".join(f"{k[5:]}: {v['mean']*100:+.0f}%/{v['win']*100:.0f}%" for k, v in res.items() if k.startswith("temp_")))
# 连续持有、每 21 天换一次成分的年化
Rz = np.where(valid, R, 0.0)
for nm, m in (("steady", steady), ("all", U), ("hot", U & hot)):
    series = np.zeros(T); members = None
    for t in range(260, T - 1):
        if (t - 260) % 21 == 0 and m[t].any():
            members = np.nonzero(m[t])[0]
        if members is not None:
            series[t + 1] = float(np.mean(Rz[t + 1, members]))
    eq = np.cumprod(1 + series[261:]); yy = cal[261:] // 10000
    OUT["long"][f"{nm}_cagr"] = float(eq[-1] ** (245 / len(eq)) - 1)
    OUT["long"][f"{nm}_by_year"] = {int(y): float(np.prod(1 + series[261:][yy == y]) - 1) for y in sorted(set(yy.tolist()))}
    print(f"  长期 {nm} 连续持有年化 {OUT['long'][f'{nm}_cagr']*100:+.1f}%")
json.dump(OUT, open(f"ship3_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
