"""实验 2：现有的「错杀反弹」「悄悄走强」在真实数据上的体检。"""
from lab import *
import numpy as np

def clipa(x, lo, hi): return np.minimum(np.maximum(x, lo), hi)

with np.errstate(invalid="ignore", divide="ignore"):
    LIN = np.log(C / O); LON = np.log(O / PC)
# ---------- 短期：错杀反弹 ----------
drop = ret_k(5)
sig = shift(roll_std(R, 120, 100), 5)
with np.errstate(invalid="ignore", divide="ignore"):
    z = drop / (sig * np.sqrt(5))
    share = roll_sum(LIN, 5)[0] / np.log1p(drop)
edge_up = valid & (R >= lim - 0.004); edge_dn = valid & (R <= -lim + 0.004)
ups10 = roll_sum(edge_up.astype(float), 10)[0]; dns10 = roll_sum(edge_dn.astype(float), 10)[0]
gapmin = roll_min(OV, 5)
r120 = ret_k(120)
S = valid & (drop <= -0.04) & (z <= -1.6) & (ups10 == 0) & (dns10 == 0) & (gapmin >= -0.03) & (share >= 0.6) & (r120 >= -0.15)
d = -drop
target = clipa(0.5 * d / (1 - d), 0.03, 0.10); stop = clipa(0.75 * d, 0.04, 0.08)
for name, U in (("市值前300", U300), ("成交额前1000", U1000), ("全市场", UALL)):
    print(f"===== 短期·错杀反弹 @ {name} =====")
    tr = trades(S & U, 8, target=target, stop=stop, max_gap=0.02)
    st = tr_stats(tr, U, h_base=int(round(tr['days'].mean())) + 1, label="完整规则(止盈+止损+8天)")
    ev(S, 6, U, label="同样的信号, 只拿5天不设止盈止损", years=False)
# ---------- 中期：悄悄走强 ----------
i300 = index_close("sh000300")
b60 = i300 / np.concatenate([np.full(60, np.nan), i300[:-60]]) - 1
r60 = ret_k(60)
excess = r60 - b60[:, None]
ups60 = roll_sum(edge_up.astype(float), 60)[0]; dns60 = roll_sum(edge_dn.astype(float), 60)[0]
r5 = ret_k(5)
upr = roll_sum(np.where(valid, (R > 0).astype(float), np.nan), 60)[0] / 60
# 60 日对数价格对时间的拟合优度
y = np.log(Cf.astype(np.float64)); tt = np.arange(T, dtype=np.float64)[:, None] * np.ones((1, N))
k = 60
sy = roll_sum(y, k)[0]; syy = roll_sum(y * y, k)[0]; sxy = roll_sum(tt * y, k)[0]; sx = roll_sum(tt, k)[0]; sxx = roll_sum(tt * tt, k)[0]
cov = sxy - sx * sy / k; vx = sxx - sx * sx / k; vy = syy - sy * sy / k
with np.errstate(invalid="ignore", divide="ignore"):
    r2 = np.where((vx > 0) & (vy > 1e-12), cov * cov / (vx * vy), 0.0); slope = cov / vx
abn = roll_mean(V, 20) / roll_mean(V, 120)
gain = roll_max(R, 60, 40)
s60 = roll_std(R, 60, 40)
M = (valid & (r60 >= 0.08) & (excess >= 0.05) & (ups60 == 0) & (dns60 == 0) & (np.abs(r5) <= 0.06) & (upr >= 0.53)
     & (slope > 0) & (r2 >= 0.60) & (abn <= 1.3) & (gain <= 0.07) & (s60 <= 0.03))
trail = clipa(2.6 * s60 * np.sqrt(5), 0.06, 0.12)
for name, U in (("市值前300", U300), ("成交额前1000", U1000), ("全市场", UALL)):
    print(f"===== 中期·悄悄走强 @ {name} =====")
    tr = trades(M & U, 60, stop=trail, trail=trail, max_gap=0.03)
    st = tr_stats(tr, U, h_base=int(round(tr['days'].mean())) + 1, label="完整规则(移动止损, 最长60天)")
    ev(M, 21, U, label="同样的信号, 固定拿20天", years=False)
    ev(M, 61, U, label="同样的信号, 固定拿60天", years=False)
