"""实验 6：把「该躲开的特征」反过来，组合成一个「冷静度」打分，看最冷静的那一组能不能稳定跑赢。"""
from feat import *
import numpy as np

def prank(x, U):          # 池内百分位
    return pct_rank(x, U)

def composite(parts, U):
    """parts: [(name, sign)]，sign=-1 表示越小越好。返回平均百分位（越大越「冷静」）。"""
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = prank(F(nm) * sg, U)
        ok = np.isfinite(p)
        acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.8, acc / cnt, np.nan)

def report(score, U, uname, label, q=0.9, hs=(21, 61)):
    for h in hs:
        Fh = fwd(h)
        M = U & np.isfinite(Fh) & np.isfinite(score)
        pr = pct_rank(score, M)
        b = base_of(Fh, M)
        G = M & (pr >= q)
        cnt = G.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
        dex = dr - b
        ys = sorted(set(year.tolist()))
        yrow = " ".join(f"{y%100:02d}:{np.nanmean(dex[year==y])*100:+.1f}" for y in ys)
        pos = sum(1 for y in ys if np.nanmean(dex[year == y]) > 0)
        print(f"[{uname}|{label}|前{(1-q)*100:.0f}%] h={h-1}: 组合收益 {np.nanmean(dr)*100:+.2f}% 随便买 {np.nanmean(b)*100:+.2f}% 超额 {np.nanmean(dex)*100:+.2f}% t={nw_t(dex, h):.1f} 胜率(组内个股) {np.nanmean(np.where(G, Fh > 0, np.nan))*100:.0f}% | 赢的年份 {pos}/{len(ys)} | {yrow}")

sets = {
    "换手低":      [("turn20", -1)],
    "波动低":      [("vol60", -1)],
    "盘中不拉":    [("id60", -1)],
    "隔夜强":      [("ov60", 1)],
    "量能没放大":  [("abn20_250", -1)],
    "没有暴涨日":  [("max20", -1)],
    "量价背离":    [("pvc20", -1)],
    "综合A(换手+波动+盘中+隔夜+量能+暴涨+量价)": [("turn20", -1), ("vol60", -1), ("id60", -1), ("ov60", 1), ("abn20_250", -1), ("max20", -1), ("pvc20", -1)],
    "综合B(盘中+隔夜+量能+量价)": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1)],
    "综合C(换手+波动+暴涨)": [("turn20", -1), ("vol60", -1), ("max20", -1)],
}
for uname, U in (("全市场", UALL), ("市值前1000", UMV1000), ("市值前300", U300)):
    for label, parts in sets.items():
        sc = composite(parts, U)
        report(sc, U, uname, label, q=0.9)
    print()
