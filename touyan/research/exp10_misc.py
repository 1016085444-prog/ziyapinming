"""实验 10：其它短线思路的排查。"""
from feat import *
import numpy as np, json, datetime
U = UALL
# ---------- (i) 冷门股里的急跌 / (ii) 强势股回调 ----------
def composite(parts, U):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.8, acc / cnt, np.nan)
QB = composite([("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1)], U)
qb = pct_rank(QB, U)
np.save("qb_all.npy", QB)
r5 = F("r5"); r3 = F("r3"); r1 = F("r1"); r120 = F("r120"); r20 = F("r20")
print("===== (i)(ii) 双重条件（全市场，超额按天平均） =====")
tests = {
    "无人追捧前30% 且 5日跌幅最大10%": (qb >= 0.7) & (pct_rank(r5, U) < 0.1),
    "无人追捧前30% 且 5日跌≥8%": (qb >= 0.7) & (r5 <= -0.08),
    "无人追捧前30% 且 当日跌≥4%": (qb >= 0.7) & (r1 <= -0.04),
    "无人追捧前10% 且 3日跌≥5%": (qb >= 0.9) & (r3 <= -0.05),
    "无人追捧前10%（不加条件）": (qb >= 0.9),
    "无人追捧后30% 且 5日跌≥8%": (qb < 0.3) & (r5 <= -0.08),
    "半年涨幅前30% 且 5日跌≥6%": (pct_rank(r120, U) >= 0.7) & (r5 <= -0.06),
    "半年涨幅前30% 且 20日跌≥10%": (pct_rank(r120, U) >= 0.7) & (r20 <= -0.10),
}
for nm, S in tests.items():
    for h in (3, 6, 11):
        ev(S & valid, h, U, label=f"{nm}", years=False)
# ---------- (v) 日历效应 ----------
print("===== (v) 日历效应：全市场等权（2016-08 起），收盘到收盘的当日平均涨跌 =====")
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
dates = [datetime.date(int(d) // 10000, int(d) // 100 % 100, int(d) % 100) for d in cal]
wd = np.array([d.weekday() for d in dates])
for k, nm in enumerate("周一 周二 周三 周四 周五".split()):
    m = wd == k
    print(f"   {nm}: 天数 {int(m.sum())} 平均 {np.nanmean(mr[m])*1e4:+.1f}bp 上涨占比 {np.nanmean(mr[m] > 0)*100:.0f}%  前半段(到2021) {np.nanmean(mr[m & (year <= 2021)])*1e4:+.1f}bp 后半段 {np.nanmean(mr[m & (year >= 2022)])*1e4:+.1f}bp")
# 月内第几个交易日 / 倒数第几个
ym = np.array([d.year * 100 + d.month for d in dates])
pos = np.zeros(T, int); rev = np.zeros(T, int)
for v in np.unique(ym):
    idx = np.nonzero(ym == v)[0]
    pos[idx] = np.arange(1, len(idx) + 1); rev[idx] = np.arange(len(idx), 0, -1)
print("   月内位置：")
for lab, m in (("月初第1天", pos == 1), ("第2天", pos == 2), ("第3天", pos == 3), ("第4-5天", (pos >= 4) & (pos <= 5)), ("月中", (pos > 5) & (rev > 5)),
               ("倒数第5-4天", (rev <= 5) & (rev >= 4)), ("倒数第3天", rev == 3), ("倒数第2天", rev == 2), ("月末最后1天", rev == 1)):
    print(f"   {lab}: 天数 {int(m.sum())} 平均 {np.nanmean(mr[m])*1e4:+.1f}bp 上涨占比 {np.nanmean(mr[m] > 0)*100:.0f}%  前半段 {np.nanmean(mr[m & (year <= 2021)])*1e4:+.1f}bp 后半段 {np.nanmean(mr[m & (year >= 2022)])*1e4:+.1f}bp")
mon = np.array([d.month for d in dates])
print("   各月份（日均）：" + " ".join(f"{k}月 {np.nanmean(mr[mon == k])*1e4:+.0f}bp" for k in range(1, 13)))
# ---------- (vii) 行业的短期惯性 ----------
print("===== (vii) 行业惯性：行业等权指数，按前 k 日涨幅排，之后 h 日（次日开盘到 h 日后收盘用行业内个股平均近似） =====")
ind = json.load(open("industry.json", encoding="utf-8"))
names = sorted(set(ind.values()))
ix = {n: i for i, n in enumerate(names)}
lab = np.array([ix.get(ind.get(c), -1) for c in codes])
K = len(names)
indR = np.full((T, K), np.nan)
cnt = np.zeros((T, K))
Rz = np.where(U, R, np.nan)
for k in range(K):
    cols = np.nonzero(lab == k)[0]
    if len(cols) >= 8:
        with np.errstate(invalid="ignore"):
            indR[:, k] = np.nanmean(Rz[:, cols], axis=1)
ok = np.isfinite(indR).mean(0) > 0.9
print("   行业数", int(ok.sum()))
indR = indR[:, ok]; K2 = indR.shape[1]
lvl = np.cumprod(1 + np.nan_to_num(indR), axis=0)
def past(k):
    out = np.full((T, K2), np.nan); out[k:] = lvl[k:] / lvl[:-k] - 1; return out
def futr(h):          # t+1 收盘 → t+h 收盘（跳过次日隔夜，偏保守地近似「次日买入」）
    out = np.full((T, K2), np.nan); out[:T - h] = lvl[h:] / lvl[1:T - h + 1] - 1; return out
for k in (1, 3, 5, 20, 60):
    p = past(k)
    rk = np.argsort(np.argsort(p, axis=1), axis=1) / (K2 - 1)
    row = f"   按前{k:2d}日行业涨幅: "
    for h in (2, 6, 21):
        f = futr(h); base = np.nanmean(f, axis=1)
        top = np.nanmean(np.where(rk >= 0.9, f, np.nan), axis=1) - base
        bot = np.nanmean(np.where(rk <= 0.1, f, np.nan), axis=1) - base
        row += f"h{h-1}: 最强10% {np.nanmean(top)*100:+.2f}%(t{nw_t(top, h):+.1f}) 最弱10% {np.nanmean(bot)*100:+.2f}%(t{nw_t(bot, h):+.1f}) | "
    print(row)
