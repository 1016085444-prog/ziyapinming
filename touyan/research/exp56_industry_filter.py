"""实验 56：行业的长期走势能不能帮长期、中期选股——同样的选股规则，分别落在「长期走弱」「长期走强」「其余」行业里，结果差多少。

行业走势用软件里算得出来的口径（股票池只有约 640 根日线）：行业等权指数相对全部行业平均的强弱线，
看过去 600 个交易日（约两年半）和最近 125 个交易日（半年）的涨跌，在全部行业里排名。
- 长期走弱：两年半排在后三成，最近半年也在后一半；
- 长期走强：两年半排在前三成，最近半年也在前一半。
"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *
from exp50_mid_plan import sim_mid, TEMP          # noqa: E402

print(f"@@@@@ {which} 行业过滤 @@@@@")
z = np.load("indsig.npz", allow_pickle=True)
dd, inames, rel, okI = z["d"], list(z["names"]), z["rel"], z["ok"]
pos = np.searchsorted(dd, cal); assert (dd[pos] == cal).all()


def lag(x, k):
    out = np.full(x.shape, np.nan); out[k:] = x[:-k]; return out


rank = lambda X: pd.DataFrame(np.where(okI, X, np.nan)).rank(axis=1, pct=True).to_numpy()
r600 = rank(rel / lag(rel, 600) - 1); r125 = rank(rel / lag(rel, 125) - 1); r250 = rank(rel / lag(rel, 250) - 1)
weakI = (r600 < 0.3) & (r125 < 0.5); strongI = (r600 >= 0.7) & (r125 >= 0.5)
col = {nm: k for k, nm in enumerate(inames)}
ik = np.array([col.get(x, -1) for x in ind_of])
has = ik >= 0


def to_stock(BI):
    out = np.zeros((T, N), bool)
    out[:, has] = BI[pos][:, ik[has]]
    return out


WEAK, STRONG = to_stock(weakI), to_stock(strongI)
KNOWN = to_stock(np.isfinite(r600) & np.isfinite(r125))
print(f"  行业状态已知的股票占 {KNOWN[U].mean()*100:.0f}%；其中长期走弱 {WEAK[U & KNOWN].mean()*100:.0f}%，长期走强 {STRONG[U & KNOWN].mean()*100:.0f}%")
OUT = {}
# ---- 长期：稳健名单 ----
LC = os.path.join(HERE, f"lpanel{TAG}2")
DIVD = np.load(os.path.join(LC, "divd.npy")); DIV12 = roll_sum(DIVD, 250)[0]
ROE_MIN3 = np.load(os.path.join(LC, "annual.npy"))[1]
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r6 = pct_rank(F("r600"), U); r6 = np.where(np.isfinite(r6), r6, 0.5)
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r6 >= 0.8)
steady = U & ~hot & PROFIT & (DIV12 > 0) & (ROE_MIN3 >= 8) & KNOWN


def port(sel, h, days):
    Fh = fwd(h); rows = []
    for t in days:
        okf = np.isfinite(Fh[t]); s = sel[t] & okf; b = U[t] & okf
        if s.sum() < 3 or b.sum() == 0:
            continue
        rows.append((int(t), float(Fh[t][s].mean()), float(Fh[t][b].mean())))
    return pd.DataFrame(rows, columns=["t", "ret", "base"])


for h, hn in ((245, "一年"), (490, "两年")):
    days = np.arange(max(260, int(np.nonzero(KNOWN.any(1))[0][0])), T - h - 2, 21)
    print(f"--- 长期（稳健名单），拿{hn} ---")
    ref = port(steady, h, days)
    for nm, m in (("稳健：全部", steady), ("稳健 ∩ 行业长期走弱", steady & WEAK), ("稳健 ∩ 行业长期走强", steady & STRONG), ("稳健 ∩ 其余行业", steady & ~WEAK & ~STRONG), ("稳健 去掉走弱行业", steady & ~WEAK),
                  ("全池 ∩ 行业长期走弱", U & KNOWN & WEAK), ("全池 ∩ 行业长期走强", U & KNOWN & STRONG)):
        df = port(m, h, days)
        if not len(df):
            continue
        y = year[df["t"].to_numpy()]; ex = df["ret"] - df["base"]; by = ex.groupby(y).mean()
        OUT[f"long|{nm}|{hn}"] = {"ret": float(df["ret"].mean()), "ex": float(ex.mean()), "win": float((df["ret"] > 0).mean()), "beat_years": int((by > 0).sum()), "years": len(by)}
        print(f"  {nm:<22} 平均 {df['ret'].mean()*100:+6.1f}%  相对全池 {ex.mean()*100:+5.1f}%  建仓日里赚钱 {(df['ret'] > 0).mean()*100:3.0f}%  跑赢全池的年份 {int((by > 0).sum())}/{len(by)}   按年: " + " ".join(f"{int(k)%100:02d}:{v*100:+.0f}" for k, v in by.items()))
# ---- 中期：冷门蓄势 ----
print("--- 中期（冷门蓄势，新方案）---")
EXIT = up_lim | (cold < 0.3)
for nm, m in (("全部候选", okm & KNOWN), ("行业长期走弱", okm & WEAK), ("行业长期走强", okm & STRONG), ("其余行业", okm & KNOWN & ~WEAK & ~STRONG), ("去掉走弱行业", okm & KNOWN & ~WEAK)):
    OUT[f"mid|{nm}"] = brief(sim_mid(pick(m, COLD), 120, flag=EXIT), f"中期 {nm}")
# ---- 短期：出手日 ----
print("--- 短期（分数≥3）---")
for nm, m in (("全部候选", oks & KNOWN), ("行业长期走弱", oks & WEAK), ("行业长期走强", oks & STRONG), ("去掉走弱行业", oks & KNOWN & ~WEAK)):
    OUT[f"short|{nm}"] = brief(trades(pick(m, ps, days=S >= 3), max_days=5, stop=0.08, max_gap=0.02), f"短期 {nm}")
json.dump(OUT, open(f"exp56_{which}.json", "w"), ensure_ascii=False, indent=1)
