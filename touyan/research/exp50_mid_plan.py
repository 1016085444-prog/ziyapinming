"""实验 50：中期的交易方法细化（拿多久、变热了要不要卖、买几只、分批买）+ 市场温度对短期、中期的影响。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *

z = np.load("temps.npz", allow_pickle=True)
names = list(z["names"]); tv = z[f"t{names.index('两者平均(近10年)')}"]
tmap = dict(zip(z["d"].tolist(), tv.tolist())); TEMP = np.array([tmap.get(int(x), np.nan) for x in cal])
OUT = {}


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


P = pick(okm, COLD)
print(f"===== {which}：中期 =====")
print("--- 拿多久（涨停次日卖）---")
for h in (20, 40, 60, 90, 120):
    OUT[f"mid|hold{h}"] = brief(sim_mid(P, h, flag=up_lim), f"最多拿 {h} 天")
print("--- 卖出信号（最多拿 60 天）---")
OUT["mid|exit_none"] = brief(sim_mid(P, 60), "到期才卖")
OUT["mid|exit_limit"] = brief(sim_mid(P, 60, flag=up_lim), "涨停次日卖")
OUT["mid|exit_hot50"] = brief(sim_mid(P, 60, flag=up_lim | (cold < 0.5)), "涨停次日卖 + 冷热分掉到 50 以下卖")
OUT["mid|exit_hot30"] = brief(sim_mid(P, 60, flag=up_lim | (cold < 0.3)), "涨停次日卖 + 冷热分掉到 30 以下卖")
OUT["mid|exit_hot10"] = brief(sim_mid(P, 60, flag=up_lim | (cold < 0.1)), "涨停次日卖 + 冷热分掉到 10 以下卖")
OUT["mid|exit_hot30_120"] = brief(sim_mid(P, 120, flag=up_lim | (cold < 0.3)), "最多 120 天：涨停次日卖 + 冷热分<30 卖")
OUT["mid|exit_only_hot30_120"] = brief(sim_mid(P, 120, flag=(cold < 0.3)), "最多 120 天：只在冷热分<30 时卖")
r20 = F("r20")
OUT["mid|exit_run20"] = brief(sim_mid(P, 60, flag=up_lim | (r20 > 0.25)), "涨停次日卖 + 20 天涨超 25% 卖")
print("--- 买几只 ---")
for n in (3, 5, 8, 10):
    OUT[f"mid|n{n}"] = brief(sim_mid(pick(okm, COLD, n=n), 60, flag=up_lim), f"每天 {n} 只")
print("--- 建仓日的市场温度 ---")
for lab, m in (("温度<20", TEMP < 20), ("温度 20-40", (TEMP >= 20) & (TEMP < 40)), ("温度 40-60", (TEMP >= 40) & (TEMP < 60)), ("温度 60-80", (TEMP >= 60) & (TEMP < 80)), ("温度≥80", TEMP >= 80)):
    if m.sum() < 20:
        print(f"  中期 {lab}: 天数太少（{int(m.sum())}）"); continue
    OUT[f"mid|temp|{lab}"] = brief(sim_mid(pick(okm, COLD, days=m), 60, flag=up_lim), f"中期 {lab}（{int(m.sum())} 天）")
print(f"===== {which}：短期（分数≥3，拿 5 天，止损 8%）按市场温度 =====")
for lab, m in (("温度<20", TEMP < 20), ("温度 20-40", (TEMP >= 20) & (TEMP < 40)), ("温度 40-60", (TEMP >= 40) & (TEMP < 60)), ("温度 60-80", (TEMP >= 60) & (TEMP < 80)), ("温度≥80", TEMP >= 80), ("没有温度的早年", ~np.isfinite(TEMP))):
    dm = (S >= 3) & m
    if dm.sum() < 8:
        print(f"  短期 {lab}: 天数太少（{int(dm.sum())}）"); continue
    OUT[f"short|temp|{lab}"] = brief(trades(pick(oks, ps, days=dm), max_days=5, stop=0.08, max_gap=0.02), f"短期 {lab}（{int(dm.sum())} 天）")
print("--- 大盘预估分各档的日子，按温度分：之后 5 天全池平均 ---")
B6 = base_of(fwd(6), U)
for lab, m in (("温度<40", TEMP < 40), ("温度 40-60", (TEMP >= 40) & (TEMP < 60)), ("温度≥60", TEMP >= 60)):
    row = f"  {lab:<10}"
    for sl, sm in (("≤-1", S <= -1), ("0-1", (S >= 0) & (S <= 1)), ("2", S == 2), ("≥3", S >= 3)):
        k = m & sm & np.isfinite(B6)
        row += f" | 分数{sl}: {np.nanmean(B6[k])*100:+.2f}% 上涨{np.nanmean(B6[k] > 0)*100:3.0f}% ({int(k.sum())}天)" if k.sum() >= 10 else f" | 分数{sl}: 样本少"
        if k.sum() >= 10:
            OUT[f"score_temp|{lab}|{sl}"] = {"n": int(k.sum()), "mean": float(np.nanmean(B6[k])), "up": float(np.nanmean(B6[k] > 0))}
    print(row)
json.dump(OUT, open(f"exp50_{which}.json", "w"), ensure_ascii=False, indent=1)
