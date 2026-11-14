"""实验 21：收盘后能不能预估大盘接下来的走势。把各种「情绪/状态」线索按高低分 5 档，看之后全市场随便买的收益。"""
import os, sys, datetime, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = UREL if which == "old" else UALL
n_u = np.maximum(U.sum(1), 1)
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
mov = np.nanmean(np.where(U, OV, np.nan), axis=1); mid_ = np.nanmean(np.where(U, ID, np.nan), axis=1)
lvl = np.cumprod(1 + np.nan_to_num(mr))
def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
lu = up_lim & U; dl = dn_lim & U
touched = (valid & U & (RH >= UPP - 0.0015) & (R > 0.03)) | lu
upshare = lu.sum(1) / n_u; dnshare = dl.sum(1) / n_u
fail_rate = np.where(touched.sum(1) >= 10, (touched & ~lu).sum(1) / np.maximum(touched.sum(1), 1), np.nan)
prev_lu = shift(lu.astype(np.float32), 1) > 0
zt_perf = np.nanmean(np.where(prev_lu & valid, R, np.nan), axis=1)          # 昨日涨停股今天的表现
streak = np.zeros((T, N), np.int16)
for t in range(T):
    streak[t] = np.where(lu[t], (streak[t - 1] if t else 0) + 1, 0)
max_streak = streak.max(1).astype(float)
adv = np.nanmean(np.where(U, R > 0, np.nan), axis=1)
ma20 = roll_mean(Cf, 20); above = np.nanmean(np.where(U, Cf > ma20, np.nan), axis=1)
amt_tot = np.nansum(np.where(U, A, 0), axis=1)
amt_rel = amt_tot / np.concatenate([np.full(20, np.nan), np.convolve(amt_tot, np.ones(20) / 20, "valid")[:-1]])
big = U & (pct_rank(F("size"), U) >= 0.8); small = U & (pct_rank(F("size"), U) < 0.4)
rb = np.nanmean(np.where(big, R, np.nan), axis=1); rs = np.nanmean(np.where(small, R, np.nan), axis=1)
def cum(x, k):
    c = np.cumsum(np.nan_to_num(np.log1p(x))); return c - np.concatenate([np.full(k, np.nan), c[:-k]])
style5 = cum(rs, 5) - cum(rb, 5); style20 = cum(rs, 20) - cum(rb, 20)
dates = [datetime.date(int(d) // 10000, int(d) // 100 % 100, int(d) % 100) for d in cal]
wd_next = np.array([dates[min(i + 1, T - 1)].weekday() for i in range(T)])
ym = np.array([d.year * 100 + d.month for d in dates]); rev = np.zeros(T, int); pos = np.zeros(T, int)
for v in np.unique(ym):
    idx = np.nonzero(ym == v)[0]; rev[idx] = np.arange(len(idx), 0, -1); pos[idx] = np.arange(1, len(idx) + 1)
HS = (2, 3, 6)
B = {h: base_of(fwd(h), U) for h in HS}
with np.errstate(invalid="ignore"):
    nxt_id = np.concatenate([mid_[1:], [np.nan]]); nxt_cc = np.concatenate([mr[1:], [np.nan]]); nxt_ov = np.concatenate([mov[1:], [np.nan]])
print(f"===== {which} {cal[0]}–{cal[-1]}：平时 次日隔夜 {np.nanmean(nxt_ov)*1e4:+.0f}bp 次日盘中 {np.nanmean(nxt_id)*1e4:+.0f}bp；明开买→后天收盘卖(扣费) {np.nanmean(B[2])*100:+.2f}%  →第3天 {np.nanmean(B[3])*100:+.2f}%  →第6天 {np.nanmean(B[6])*100:+.2f}% =====")
def buckets(nm, x, nb=5):
    ok = np.isfinite(x) & np.isfinite(B[6])
    qs = np.nanquantile(x[ok], np.linspace(0, 1, nb + 1))
    row = f"  {nm:<18}"
    for g in range(nb):
        m = ok & (x >= qs[g]) & ((x < qs[g + 1]) if g < nb - 1 else (x <= qs[g + 1]))
        row += f" | [{qs[g]*100:+6.1f},{qs[g+1]*100:+6.1f}] 次日盘中 {np.nanmean(nxt_id[m])*1e4:+4.0f}bp 2天 {np.nanmean(B[2][m])*100:+.2f} 5天 {np.nanmean(B[6][m])*100:+.2f}"
    print(row)
buckets("当日涨跌", mr); buckets("3日涨跌", mret(3)); buckets("5日涨跌", mret(5)); buckets("20日涨跌", mret(20))
buckets("当日隔夜跳空", mov); buckets("当日盘中", mid_)
buckets("涨停占比", upshare); buckets("跌停占比", dnshare); buckets("涨停−跌停", upshare - dnshare)
buckets("炸板率", fail_rate); buckets("昨日涨停表现", zt_perf); buckets("最高连板数/100", max_streak / 100)
buckets("上涨家数占比", adv); buckets("20日线上方占比", above); buckets("成交额/20日均−1", amt_rel - 1)
buckets("小盘−大盘 5日", style5); buckets("小盘−大盘 20日", style20)
print("  --- 日历 ---")
for k, nm in enumerate("周一 周二 周三 周四 周五".split()):
    m = (wd_next == k) & np.isfinite(B[6])
    print(f"  明天是{nm}: 天数 {int(m.sum())} 次日盘中 {np.nanmean(nxt_id[m])*1e4:+.0f}bp 次日收盘对收盘 {np.nanmean(nxt_cc[m])*1e4:+.0f}bp  明开买→后天收 {np.nanmean(B[2][m])*100:+.2f}% →5天 {np.nanmean(B[6][m])*100:+.2f}%")
for lab, m in (("明天是月末最后1天", np.concatenate([rev[1:], [0]]) == 1), ("明天是月初第1天", np.concatenate([pos[1:], [0]]) == 1), ("明天是月初第2天", np.concatenate([pos[1:], [0]]) == 2), ("其它", (np.concatenate([rev[1:], [0]]) > 1) & (np.concatenate([pos[1:], [0]]) > 2))):
    m = m & np.isfinite(B[6])
    print(f"  {lab}: 天数 {int(m.sum())} 次日盘中 {np.nanmean(nxt_id[m])*1e4:+.0f}bp 次日收对收 {np.nanmean(nxt_cc[m])*1e4:+.0f}bp  明开买→后天收 {np.nanmean(B[2][m])*100:+.2f}% →5天 {np.nanmean(B[6][m])*100:+.2f}%")
# 存下来给后面的组合模型用
np.savez(f"mkt_{which}.npz", cal=cal, mr=mr, mov=mov, mid=mid_, upshare=upshare, dnshare=dnshare, fail=fail_rate, zt=zt_perf, streak=max_streak, adv=adv, above=above,
         amt_rel=amt_rel, style5=style5, style20=style20, rb=rb, rs=rs, wd_next=wd_next, rev=rev, pos=pos, b2=B[2], b3=B[3], b6=B[6])
