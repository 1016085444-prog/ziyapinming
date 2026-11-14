"""实验 15：样本外十年（2005–2016，或用 LAB_PANEL 切换）的检验。股票池：成交额排在前七成的股票。"""
from feat import *
import numpy as np, os, sys
U = UREL
print("每天池内只数（平均）:", int(U.sum(1)[260:].mean()), " ST近似只数:", int(st_like.sum(1).mean()))
ov = np.nanmean(np.where(U, OV, np.nan)); idr = np.nanmean(np.where(U, ID, np.nan))
print(f"平均每天 隔夜 {ov*1e4:+.1f}bp 日内 {idr*1e4:+.1f}bp")
ys = sorted(set(year.tolist()))
for h in (6, 21, 61):
    b = base_of(fwd(h), U)
    print(f"随便买 持有{h-1}天: {np.nanmean(b)*100:+.2f}% | " + " ".join(f"{y%100:02d}:{np.nanmean(b[year==y])*100:+.1f}" for y in ys))

def composite(parts, U):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.8, acc / cnt, np.nan)
def yearly(G, U, h):
    Fh = fwd(h); M = U & np.isfinite(Fh); b = base_of(Fh, M); G = G & M
    cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    return {"n": int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0, "ret": np.nanmean(dr), "ex": np.nanmean(dex), "t": nw_t(dex, h), "win": np.nanmean(np.where(G, Fh > 0, np.nan)), "ye": ye}
def show(label, res):
    ye = res["ye"]; pos = sum(1 for v in ye.values() if v > 0)
    print(f"{label:<40} 每天{res['n']:4d}只 收益 {res['ret']*100:+.2f}% 超额 {res['ex']*100:+.2f}% t={res['t']:.1f} 个股胜率 {res['win']*100:.0f}% | 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items()), flush=True)

print("===== 中期「无人追捧」打分 =====")
B4 = [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1)]
QB = composite(B4, U); qb = pct_rank(QB, U)
np.save(f"qb{TAG}_urel.npy", QB)
for h in (21, 61):
    show(f"B4 前10% 持有{h-1}天", yearly(qb >= 0.9, U, h))
show("B4 前5% 持有60天", yearly(qb >= 0.95, U, 61))
for nm, parts in (("id60 单项", [("id60", -1)]), ("ov60 单项", [("ov60", 1)]), ("abn20_250 单项", [("abn20_250", -1)]), ("pvc20 单项", [("pvc20", -1)]),
                  ("窗口 40/40/10_120/20", [("id40", -1), ("ov40", 1), ("abn10_120", -1), ("pvc20", -1)])):
    sc = pct_rank(composite(parts, U), U)
    show(f"{nm} 前10% 持有60天", yearly(sc >= 0.9, U, 61))
FPD = f"fpanel{TAG}"
SQ = np.load(os.path.join(HERE, FPD, "sq_yoy.npy")); EPS = np.load(os.path.join(HERE, FPD, "eps_ttm.npy"))
for h in (21, 61):
    show(f"B4 前10% + 单季利润同比>0 持有{h-1}天", yearly((qb >= 0.9) & (SQ > 0), U, h))
    show(f"B4 前10% + 赚钱 + 单季同比>0 持有{h-1}天", yearly((qb >= 0.9) & (SQ > 0) & (EPS > 0), U, h))
show("单季利润同比>0（不看打分）60天", yearly((SQ > 0), U, 61))

print("===== 短期：恐慌之后 =====")
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
lvl = np.cumprod(1 + np.nan_to_num(mr))
def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
m1, m3, m5, m20 = mret(1), mret(3), mret(5), mret(20)
ma20 = roll_mean(Cf, 20)
below = np.nanmean(np.where(U, Cf < ma20, np.nan), axis=1)
down5 = np.nanmean(np.where(U, F("r5") < -0.10, np.nan), axis=1)
dnshare = np.nansum(np.where(U, dn_lim, 0), axis=1) / np.maximum(U.sum(1), 1)
HS = (4, 6, 11, 21)
B = {h: base_of(fwd(h), U) for h in HS}
def state(nm, cond):
    cond = cond & np.isfinite(B[21])
    row = f"  {nm:<34} 天数 {int(cond.sum()):4d} | " + " ".join(f"h{h-1}: {np.nanmean(B[h][cond])*100:+.2f}%/{np.nanmean(B[h][cond] > 0)*100:.0f}%" for h in HS)
    row += " | 5天分年: " + " ".join(f"{y%100:02d}:{np.nanmean(B[6][cond & (year == y)])*100:+.1f}({int((cond & (year == y)).sum())})" for y in ys if (cond & (year == y)).sum())
    print(row)
state("平时（全部日子）", np.ones(T, bool))
state("5日跌≥7%", m5 <= -0.07)
state("5日跌≥10%", m5 <= -0.10)
state("20日线下方≥90%", below >= 0.90)
state("5天跌超10%的占比≥30%", down5 >= 0.30)
state("三者任一", (m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30))
state("当日跌停占比≥8%", dnshare >= 0.08)
state("当日跌停占比≥3%", dnshare >= 0.03)
state("三者任一 且 当日跌停占比<3%", ((m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30)) & (dnshare < 0.03))
state("三者任一 且 当日跌停占比<1%", ((m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30)) & (dnshare < 0.01))
state("三者任一 且 当日全市场上涨", ((m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30)) & (m1 > 0))
state("当日全市场涨≥2.5%", m1 >= 0.025)
np.save(f"state{TAG}_panic.npy", ((m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30)))
np.save(f"state{TAG}_dnshare.npy", dnshare); np.save(f"state{TAG}_m5.npy", m5); np.save(f"state{TAG}_m1.npy", m1); np.save(f"state{TAG}_below.npy", below); np.save(f"state{TAG}_down5.npy", down5)
