"""实验 1：数据体检 + 「随便买」的基准水平。"""
import time; t0 = time.time()
from lab import *
print("load", round(time.time() - t0, 1), "s")
for name, U in (("市值前300", U300), ("成交额前800", U800), ("成交额前1000", U1000), ("成交额前1500", U1500), ("全市场(日均成交>3000万)", UALL)):
    print(name, "平均每天只数", round(U.sum(1)[130:].mean()))
print("近似识别为ST的平均只数", round(st_like.sum(1).mean()), " 最后一天", int(st_like[-1].sum()))
print("收盘封涨停占比", float(up_lim.sum() / valid.sum()), "封跌停占比", float(dn_lim.sum() / valid.sum()))
print("开盘即涨停占比", float(open_up.sum() / valid.sum()))
# 隔夜 / 日内 的平均值
for name, U in (("市值前300", U300), ("成交额前1000", U1000), ("全市场", UALL)):
    ov = np.nanmean(np.where(U, OV, np.nan)); idr = np.nanmean(np.where(U, ID, np.nan)); r = np.nanmean(np.where(U, R, np.nan))
    print(f"{name}: 平均每天 隔夜 {ov*1e4:+.1f}bp 日内 {idr*1e4:+.1f}bp 合计 {r*1e4:+.1f}bp")
# 基准：随便买
for h in (2, 3, 5, 8, 10, 20, 40, 60):
    row = []
    for name, U in (("市值前300", U300), ("成交额前1000", U1000), ("全市场", UALL)):
        F = fwd(h); b = base_of(F, U)
        Z = np.where(U, F, np.nan)
        row.append(f"{name} 均值 {np.nanmean(b)*100:+.2f}% 胜率 {np.nanmean(Z > 0) / np.mean(np.isfinite(Z)) * 100:.0f}%")
    print(f"随便买 持有{h}天:", " | ".join(row))
# 按年
print("按年（成交额前1000，随便买拿 8 天 / 60 天）")
for y in sorted(set(year.tolist())):
    m = year == y
    b8 = base_of(fwd(8), U1000)[m]; b60 = base_of(fwd(60), U1000)[m]
    print(y, f"8天 {np.nanmean(b8)*100:+.2f}%  60天 {np.nanmean(b60)*100:+.2f}%")
print("total", round(time.time() - t0, 1), "s")
