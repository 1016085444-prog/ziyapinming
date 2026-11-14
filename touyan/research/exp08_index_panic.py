"""实验 8：用指数的长历史（2005 年起，含 2008、2015 两次股灾）检验「恐慌之后买入」。
信号在收盘后确认，第二天开盘买入指数，持有 h 天后收盘卖出，扣 0.2%。"""
import numpy as np, os
HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.002
def load(sym):
    z = np.load(os.path.join(HERE, "index_long", sym + ".npz")); return z["d"], z["o"], z["c"], z["h"], z["l"]
def run(sym, name, start=20050101):
    d, o, c, h, l = load(sym)
    m0 = d >= start
    d, o, c = d[m0], o[m0], c[m0]
    n = len(d)
    def ret(k):
        out = np.full(n, np.nan); out[k:] = c[k:] / c[:-k] - 1; return out
    r1, r3, r5, r10, r20 = ret(1), ret(3), ret(5), ret(10), ret(20)
    def fw(hh):
        out = np.full(n, np.nan)
        e = np.arange(n) + 1; x = np.arange(n) + hh
        ok = x < n
        out[ok] = c[x[ok]] / o[e[ok]] * (1 - COST) - 1
        return out
    F = {hh: fw(hh) for hh in (3, 5, 10, 20)}
    yr = d // 10000
    print(f"===== {name}（{d[0]}–{d[-1]}，{n} 个交易日）；平时任意一天买入: " + " ".join(f"h{hh}: {np.nanmean(F[hh])*100:+.2f}%/{np.nanmean(F[hh][np.isfinite(F[hh])] > 0)*100:.0f}%" for hh in F) + " =====")
    conds = {"1日跌≥4%": r1 <= -0.04, "3日跌≥5%": r3 <= -0.05, "5日跌≥7%": r5 <= -0.07, "5日跌≥10%": r5 <= -0.10, "10日跌≥10%": r10 <= -0.10, "20日跌≥15%": r20 <= -0.15,
             "任一(3日≥5% 或 5日≥7% 或 20日≥15%)": (r3 <= -0.05) | (r5 <= -0.07) | (r20 <= -0.15)}
    for nm, cond in conds.items():
        cond = cond & np.isfinite(F[20])
        idx = np.nonzero(cond)[0]
        if len(idx) == 0: continue
        # 每轮恐慌只算第一次（之前 10 个交易日内没有触发过）
        first = [i for k, i in enumerate(idx) if k == 0 or i - idx[k - 1] > 10]
        row = f"  {nm:<28} 天数 {len(idx):4d} 轮数 {len(first):3d} | 所有触发日: " + " ".join(f"h{hh}: {F[hh][idx].mean()*100:+.2f}%/{(F[hh][idx] > 0).mean()*100:.0f}%" for hh in F)
        row += " | 每轮第一次: " + " ".join(f"h{hh}: {F[hh][first].mean()*100:+.2f}%/{(F[hh][first] > 0).mean()*100:.0f}%" for hh in F)
        print(row)
    cond = ((r3 <= -0.05) | (r5 <= -0.07) | (r20 <= -0.15)) & np.isfinite(F[20])
    print("  分年度（任一条件；所有触发日）: 年份 天数 h5 h10 h20")
    line = "   "
    for y in sorted(set(yr.tolist())):
        m = cond & (yr == y)
        if m.sum():
            line += f" {y}:{int(m.sum())}天 {F[5][m].mean()*100:+.1f}/{F[10][m].mean()*100:+.1f}/{F[20][m].mean()*100:+.1f} |"
    print(line)
    # 最差的几次
    idx = np.nonzero(cond)[0]
    worst = sorted(idx, key=lambda i: F[10][i])[:6]
    print("  持有 10 天最差的 6 次: " + ", ".join(f"{d[i]}({F[10][i]*100:+.1f}%)" for i in worst))
for sym, name in (("sh000985", "中证全指"), ("sh000852", "中证1000"), ("sh000300", "沪深300"), ("sh000905", "中证500")):
    run(sym, name)
run("sh000001", "上证指数(1997起)", start=19970101)
