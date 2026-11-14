"""实验 22：「大盘预估分」。用几条两个十年都成立的线索加分，在一个十年上定权重、另一个十年上检验。"""
import numpy as np
D = {w: dict(np.load(f"mkt_{w}.npz")) for w in ("old", "new")}
def feats(d):
    mr = d["mr"]; n = len(mr)
    lvl = np.cumprod(1 + np.nan_to_num(mr))
    def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
    m5 = mret(5); m20 = mret(20)
    rev_n = np.concatenate([d["rev"][1:], [0]]); pos_n = np.concatenate([d["pos"][1:], [0]])
    f = {
        "放量(成交额≥20日均×1.15)": d["amt_rel"] >= 1.15,
        "缩量(成交额≤20日均×0.85)": d["amt_rel"] <= 0.85,
        "大涨日(当日≥+1.5%)": mr >= 0.015,
        "大跌日(当日≤-1.5%)": mr <= -0.015,
        "平淡日(|当日|<0.5%)": np.abs(mr) < 0.005,
        "跌停多(占比≥2%)": d["dnshare"] >= 0.02,
        "涨停多(占比≥2%)": d["upshare"] >= 0.02,
        "5日跌≥4%": m5 <= -0.04,
        "5日涨≥4%": m5 >= 0.04,
        "20日跌≥8%": m20 <= -0.08,
        "月末月初窗口(明天是月末最后1天或月初第1天)": (rev_n == 1) | (pos_n == 1),
        "明天周一": d["wd_next"] == 0,
        "明天周四": d["wd_next"] == 3,
        "小盘近5日落后大盘≥2%": d["style5"] <= -0.02,
    }
    return f
for w in ("old", "new"):
    d = D[w]; f = feats(d)
    base2, base6 = np.nanmean(d["b2"]), np.nanmean(d["b6"])
    print(f"===== {w}: 平时 2天 {base2*100:+.2f}% 5天 {base6*100:+.2f}% =====")
    for nm, m in f.items():
        ok = m & np.isfinite(d["b6"])
        print(f"   {nm:<34} 天数 {int(ok.sum()):4d} 占 {ok.mean()*100:4.1f}% | 2天 {np.nanmean(d['b2'][ok])*100:+.2f}%（上涨 {np.nanmean(d['b2'][ok] > 0)*100:.0f}%） 5天 {np.nanmean(d['b6'][ok])*100:+.2f}%（上涨 {np.nanmean(d['b6'][ok] > 0)*100:.0f}%） | 不满足时 5天 {np.nanmean(d['b6'][~m & np.isfinite(d['b6'])])*100:+.2f}%")
# 线性回归：一个十年拟合，另一个十年检验
names = None
def design(d):
    global names
    f = feats(d); names = list(f.keys())
    X = np.column_stack([np.where(f[k], 1.0, 0.0) for k in names]); return X
def fit(X, y):
    ok = np.isfinite(y); A = np.column_stack([np.ones(ok.sum()), X[ok]])
    coef, *_ = np.linalg.lstsq(A, y[ok], rcond=None); return coef
for tr, te in (("old", "new"), ("new", "old")):
    Xtr, Xte = design(D[tr]), design(D[te])
    for key, lab in (("b2", "2天"), ("b6", "5天")):
        coef = fit(Xtr, D[tr][key])
        pred = coef[0] + Xte @ coef[1:]
        y = D[te][key]; ok = np.isfinite(y)
        qs = np.quantile(pred[ok], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
        row = f"   用 {tr} 拟合、在 {te} 上检验（{lab}）：按预测值分 5 档的真实收益 → "
        for g in range(5):
            m = ok & (pred >= qs[g]) & ((pred < qs[g + 1]) if g < 4 else (pred <= qs[g + 1]))
            row += f"{np.nanmean(y[m])*100:+.2f}%({np.nanmean(y[m] > 0)*100:.0f}%) "
        top = ok & (pred >= np.quantile(pred[ok], 0.9)); bot = ok & (pred <= np.quantile(pred[ok], 0.3))
        row += f"| 预测最高10%: {np.nanmean(y[top])*100:+.2f}%({np.nanmean(y[top] > 0)*100:.0f}%) 预测最低30%: {np.nanmean(y[bot])*100:+.2f}%  相关系数 {np.corrcoef(pred[ok], y[ok])[0,1]:.3f}"
        print(row)
    print("   " + tr + " 上的权重（5天，%）：" + "  ".join(f"{n.split('(')[0]}:{c*100:+.2f}" for n, c in zip(names, fit(Xtr, D[tr]['b6'])[1:])))
# 简单打分制（不拟合）：每条 +1 / -1
def score(d):
    f = feats(d)
    s = (f["放量(成交额≥20日均×1.15)"].astype(int) + f["大涨日(当日≥+1.5%)"].astype(int) + f["大跌日(当日≤-1.5%)"].astype(int) + 2 * f["跌停多(占比≥2%)"].astype(int)
         + f["涨停多(占比≥2%)"].astype(int) + f["5日跌≥4%"].astype(int) + f["月末月初窗口(明天是月末最后1天或月初第1天)"].astype(int)
         + f["明天周一"].astype(int) - f["明天周四"].astype(int) - f["平淡日(|当日|<0.5%)"].astype(int) - f["缩量(成交额≤20日均×0.85)"].astype(int))
    return s
print("===== 简单打分制（不拟合权重）=====")
for w in ("old", "new"):
    d = D[w]; s = score(d); ok = np.isfinite(d["b6"])
    print(f"  {w}:")
    for lo, hi, lab in ((-9, -1, "≤-1 分"), (0, 0, "0 分"), (1, 1, "1 分"), (2, 2, "2 分"), (3, 9, "≥3 分")):
        m = ok & (s >= lo) & (s <= hi)
        if m.sum():
            print(f"     {lab}: 天数 {int(m.sum()):4d}（{m.mean()*100:.0f}%） 明开买→后天收 {np.nanmean(d['b2'][m])*100:+.2f}%（{np.nanmean(d['b2'][m] > 0)*100:.0f}%） →3天 {np.nanmean(d['b3'][m])*100:+.2f}% →5天 {np.nanmean(d['b6'][m])*100:+.2f}%（{np.nanmean(d['b6'][m] > 0)*100:.0f}%）")
    yr = d["cal"] // 10000
    m = ok & (s >= 2)
    print("     ≥2 分的日子，5天收益分年: " + " ".join(f"{y%100:02d}:{np.nanmean(d['b6'][m & (yr == y)])*100:+.1f}({int((m & (yr == y)).sum())})" for y in sorted(set(yr.tolist())) if (m & (yr == y)).sum()))
    m = ok & (s <= -1)
    print("     ≤-1 分的日子，5天收益分年: " + " ".join(f"{y%100:02d}:{np.nanmean(d['b6'][m & (yr == y)])*100:+.1f}({int((m & (yr == y)).sum())})" for y in sorted(set(yr.tolist())) if (m & (yr == y)).sum()))
