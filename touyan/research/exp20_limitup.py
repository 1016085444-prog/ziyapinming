"""实验 20：涨停股。「昨日涨停指数」口径 vs 真实能买到的口径。两个十年分别跑。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = UREL if which == "old" else UALL
ys = sorted(set(year.tolist()))
COSTS = 0.002
nxt = lambda X, k=1: shift(X, -k)
# t 日的涨停类型
lu = up_lim & U                                   # 收盘封住涨停
touched = valid & U & (RH >= UPP - 0.0015) & (R > 0.03) | lu      # 盘中碰过涨停价
failed = touched & ~lu                            # 炸板：碰过但没封住
yizi = lu & one_line                              # 一字板（全天没开过）
opened = lu & ~one_line                           # 开过板或者不是一开盘就封死的
prev_lu = shift(lu.astype(np.float32), 1) > 0
streak = np.zeros((T, N), np.int16)               # 连板数
for t in range(T):
    streak[t] = np.where(lu[t], (streak[t - 1] if t else 0) + 1, 0)
first = lu & (streak == 1)
multi = lu & (streak >= 2)
print(f"===== {which}: 每天平均 涨停 {lu.sum(1).mean():.1f} 只（一字 {yizi.sum(1).mean():.1f}，首板 {first.sum(1).mean():.1f}，连板 {multi.sum(1).mean():.1f}），炸板 {failed.sum(1).mean():.1f} 只；封板成功率 {lu.sum()/max(1,touched.sum())*100:.0f}% =====")
with np.errstate(invalid="ignore", divide="ignore"):
    c2c1 = nxt(Cf) / Cf - 1                       # 今收 → 明收（「昨日涨停指数」口径）
    gap1 = nxt(O) / Cf - 1                        # 明天开盘跳空
    o2c1 = nxt(Cf) / nxt(O) - 1                   # 明开 → 明收（当天卖不了，仅参考）
    o2o2 = nxt(O, 2) / nxt(O) * (1 - COSTS) - 1   # 明开买 → 后天开盘卖
    o2c2 = nxt(Cf, 2) / nxt(O) * (1 - COSTS) - 1  # 明开买 → 后天收盘卖
    o2c5 = nxt(Cf, 5) / nxt(O) * (1 - COSTS) - 1
    lim_buy_c1o = nxt(O) / np.where(touched, UPP * C / RC, np.nan) * (1 - COSTS) - 1     # 涨停价买（打板）→ 明天开盘卖
    lim_buy_c1c = nxt(Cf) / np.where(touched, UPP * C / RC, np.nan) * (1 - COSTS) - 1    # 涨停价买 → 明天收盘卖
buy_ok = np.isfinite(nxt(O)) & ~(shift(open_up, -1).astype(bool)) & ~(shift(one_line, -1).astype(bool))   # 明天开盘不是涨停、不是一字
def stat(G, x, label, need=None):
    M = G & np.isfinite(x)
    if need is not None: M &= need
    n = int(M.sum())
    if n == 0: print(f"   {label}: 无"); return
    v = x[M]; cnt = M.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dm = np.where(cnt > 0, np.where(M, x, 0).sum(1) / cnt, np.nan)
    yrow = " ".join(f"{y%100:02d}:{np.nanmean(dm[year==y])*100:+.1f}" for y in ys if np.isfinite(dm[year == y]).any())
    print(f"   {label:<44} 次数 {n:7d} 均值 {v.mean()*100:+.2f}% 中位 {np.median(v)*100:+.2f}% 胜率 {(v>0).mean()*100:.0f}% | 按天平均 {np.nanmean(dm)*100:+.2f}% | {yrow}")
print("--- A.「昨日涨停指数」口径：今天收盘涨停的股票，今收→明收（假设能按涨停价买到） ---")
stat(lu, c2c1, "全部涨停股")
stat(yizi, c2c1, "其中：一字板（实际买不到）")
stat(opened, c2c1, "其中：非一字板")
stat(first, c2c1, "首板")
stat(multi, c2c1, "连板(≥2)")
print("--- B. 明天开盘的情况 ---")
stat(lu, gap1, "涨停股次日开盘跳空（平均高开多少）")
print(f"   涨停股次日开盘就涨停/一字（买不进）的比例: {(lu & np.isfinite(nxt(O)) & ~buy_ok).sum() / max(1, (lu & np.isfinite(nxt(O))).sum())*100:.0f}%")
print("--- C. 真实口径：明天开盘买（开盘就涨停的买不进），T+1 之后才能卖 ---")
for nm, G in (("全部涨停股", lu), ("首板", first), ("连板(≥2)", multi), ("首板且非一字", first & ~one_line)):
    stat(G, o2c1, f"{nm}: 明开→明收（当天卖不了，仅参考）", buy_ok)
    stat(G, o2o2, f"{nm}: 明开买→后天开盘卖", buy_ok)
    stat(G, o2c2, f"{nm}: 明开买→后天收盘卖", buy_ok)
    stat(G, o2c5, f"{nm}: 明开买→第5天收盘卖", buy_ok)
print("--- D. 打板口径：盘中碰到涨停价就按涨停价买入（含后来炸板的），第二天卖 ---")
stat(touched & ~one_line, lim_buy_c1o, "碰过涨停价的（非一字）: 涨停价买→明天开盘卖")
stat(touched & ~one_line, lim_buy_c1c, "碰过涨停价的（非一字）: 涨停价买→明天收盘卖")
stat(opened, lim_buy_c1o, "  其中最后封住的: 涨停价买→明天开盘卖")
stat(failed, lim_buy_c1o, "  其中炸板的: 涨停价买→明天开盘卖")
print("--- E. 对照：全市场随便买 明开买→后天收盘卖 ---")
stat(U, o2c2, "全市场", buy_ok)
