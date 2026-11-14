"""实验 4：买入方式。① 按开盘跳空分组 ② 挂低价单接盘中下跌。"""
from feat import *
import numpy as np

def grp_stats(mask, ret, base_t, label):
    """mask: [T,N] 事件；ret: [T,N] 每笔收益；base_t: [T] 当天基准。"""
    m = mask & np.isfinite(ret)
    n = m.sum()
    if n == 0:
        print(f"{label}: 无"); return
    r = ret[m]
    ex = (ret - base_t[:, None])[m]
    cnt = m.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        day_ex = np.where(cnt > 0, np.where(m, ret - base_t[:, None], 0).sum(1) / cnt, np.nan)
        day_r = np.where(cnt > 0, np.where(m, ret, 0).sum(1) / cnt, np.nan)
    print(f"{label}: n={n} 天数={int((cnt>0).sum())} 每笔均值 {r.mean()*100:+.2f}% 胜率 {(r>0).mean()*100:.0f}% | 按天: 收益 {np.nanmean(day_r)*100:+.2f}% 超额 {np.nanmean(day_ex)*100:+.2f}% t={nw_t(day_ex, 5):.1f}")

# ① 开盘跳空：e 日开盘相对昨收的幅度分组，之后（开盘买入）到当日收盘、次日收盘、第5日收盘
print("===== ① 按开盘跳空分组（开盘价买入；全市场） =====")
U = UALL
Ue = shift(U.astype(np.float32), 1) > 0       # 昨天在池内
gap = OV
buyable = np.isfinite(O) & ~open_up & ~open_dn & ~one_line & Ue
def fwd_from_open(k):      # 当日开盘买，k 日后收盘卖（k=0 当日收盘——实际 T+1 做不到，仅作参考）
    with np.errstate(invalid="ignore", divide="ignore"):
        return shift(Cf, -k) / O * (1 - COST) - 1
for k in (0, 1, 2, 5):
    f = fwd_from_open(k)
    base = np.nanmean(np.where(buyable, f, np.nan), axis=1)
    print(f"-- 开盘买入，持有到第 {k} 天收盘（0=当天，仅参考）；基准(所有可买) {np.nanmean(base)*100:+.2f}%")
    for lo, hi in ((-1, -0.05), (-0.05, -0.03), (-0.03, -0.02), (-0.02, -0.01), (-0.01, -0.003), (-0.003, 0.003), (0.003, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 1)):
        grp_stats(buyable & (gap >= lo) & (gap < hi), f, base, f"   跳空 [{lo*100:+.1f}%, {hi*100:+.1f}%)")

# 相对大盘的跳空（个股跳空 − 当日全市场平均跳空）
print("===== ①b 相对全市场平均的跳空 =====")
mg = np.nanmean(np.where(buyable, gap, np.nan), axis=1)
rel = gap - mg[:, None]
for k in (1, 2, 5):
    f = fwd_from_open(k)
    base = np.nanmean(np.where(buyable, f, np.nan), axis=1)
    print(f"-- 持有到第 {k} 天收盘")
    for lo, hi in ((-1, -0.04), (-0.04, -0.02), (-0.02, -0.01), (-0.01, 0.01), (0.01, 0.02), (0.02, 1)):
        grp_stats(buyable & (rel >= lo) & (rel < hi), f, base, f"   相对跳空 [{lo*100:+.1f}%, {hi*100:+.1f}%)")

# 大盘整体低开的日子
print("===== ①c 全市场平均跳空分组：当天开盘买入全市场的平均收益 =====")
for k in (1, 2, 5):
    f = fwd_from_open(k)
    base = np.nanmean(np.where(buyable, f, np.nan), axis=1)
    for lo, hi in ((-1, -0.02), (-0.02, -0.01), (-0.01, -0.005), (-0.005, 0), (0, 0.005), (0.005, 0.01), (0.01, 1)):
        m = (mg >= lo) & (mg < hi) & np.isfinite(base)
        if m.sum():
            print(f"   持有{k}天 大盘跳空 [{lo*100:+.1f}%, {hi*100:+.1f}%): 天数 {int(m.sum())} 平均 {base[m].mean()*100:+.2f}% 胜率 {(base[m]>0).mean()*100:.0f}%")

# ② 挂低价单：以 昨收×(1−δ) 挂买单，盘中最低价低于它就成交（开盘就低于它按开盘价成交）
print("===== ② 挂低价单接盘中下跌（全市场 / 市值前1000） =====")
for uname, U in (("全市场", UALL), ("市值前1000", UMV1000), ("市值前300", U300)):
    Ue = shift(U.astype(np.float32), 1) > 0
    for delta in (0.02, 0.03, 0.05, 0.07):
        limit = PC * (1 - delta)
        filled = Ue & np.isfinite(L) & (L < limit * 0.999) & ~open_dn & ~one_line
        price = np.where(O < limit, O, limit)
        for k in (1, 2, 5):
            with np.errstate(invalid="ignore", divide="ignore"):
                f = shift(Cf, -k) / price * (1 - COST) - 1
            fo = fwd_from_open(k)
            base = np.nanmean(np.where(Ue & np.isfinite(O), fo, np.nan), axis=1)
            grp_stats(filled, f, base, f"   {uname} 挂 −{delta*100:.0f}% 持有到第{k}天收盘")
