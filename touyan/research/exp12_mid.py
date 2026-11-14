"""实验 12：中期「无人追捧」打分的稳健性。"""
from feat import *
import numpy as np, sys

def composite(parts, U):
    acc = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    for nm, sg in parts:
        p = pct_rank(F(nm) * sg, U); ok = np.isfinite(p); acc[ok] += p[ok]; cnt[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt >= len(parts) * 0.8, acc / cnt, np.nan)

def yearly(score, U, h, q=0.9, topn=None):
    Fh = fwd(h); M = U & np.isfinite(Fh) & np.isfinite(score)
    b = base_of(Fh, M)
    if topn:
        rk = rank_desc(score, M); G = M & (rk <= topn)
    else:
        pr = pct_rank(score, M); G = M & (pr >= q)
    cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ys = sorted(set(year.tolist()))
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    win = np.nanmean(np.where(G, Fh > 0, np.nan))
    return {"ret": np.nanmean(dr), "base": np.nanmean(b), "ex": np.nanmean(dex), "t": nw_t(dex, h), "win": win, "ye": ye,
            "dev": np.nanmean(dex[year <= 2021]), "oos": np.nanmean(dex[year >= 2022]), "G": G}

def show(label, res):
    ye = res["ye"]; pos = sum(1 for v in ye.values() if v > 0)
    print(f"{label:<44} 收益 {res['ret']*100:+.2f}% 超额 {res['ex']*100:+.2f}% t={res['t']:.1f} 个股胜率 {res['win']*100:.0f}% | 到2021 {res['dev']*100:+.2f}% 2022起 {res['oos']*100:+.2f}% | 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items()), flush=True)

U = UALL
print("===== A. 组件怎么选都差不多吗？（全市场，前10%，持有60天） =====")
variants = {
    "B4 原版(id60,ov60,abn20_250,pvc20)": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1)],
    "只用到2021年表现好的3项(id60,ov60,pvc20)": [("id60", -1), ("ov60", 1), ("pvc20", -1)],
    "2项(id60,ov60)": [("id60", -1), ("ov60", 1)],
    "2项(abn20_250,pvc20)": [("abn20_250", -1), ("pvc20", -1)],
    "窗口换成120/120/20_250/40": [("id120", -1), ("ov120", 1), ("abn20_250", -1), ("pvc40", -1)],
    "窗口换成40/40/10_120/20": [("id40", -1), ("ov40", 1), ("abn10_120", -1), ("pvc20", -1)],
    "窗口换成20/20/5_60/10": [("id20", -1), ("ov20", 1), ("abn5_60", -1), ("pvc10", -1)],
    "B4 + 低换手": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1), ("turn20", -1)],
    "B4 + 近20日没大涨(r20低)": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1), ("r20", -1)],
    "B4 + 上影线短(ush20低)": [("id60", -1), ("ov60", 1), ("abn20_250", -1), ("pvc20", -1), ("ush20", -1)],
}
scores = {}
for label, parts in variants.items():
    sc = composite(parts, U); scores[label] = sc
    show(label, yearly(sc, U, 61))
QB = scores["B4 原版(id60,ov60,abn20_250,pvc20)"]
np.save("qb_all.npy", QB)
print("===== B. 持有期与分组 =====")
for h in (11, 21, 41, 61, 121):
    show(f"B4 前10% 持有{h-1}天", yearly(QB, U, h))
for q in (0.8, 0.95, 0.98):
    show(f"B4 前{(1-q)*100:.0f}% 持有60天", yearly(QB, U, 61, q=q))
for n in (10, 20, 50):
    show(f"B4 每天得分最高的{n}只 持有60天", yearly(QB, U, 61, topn=n))
    show(f"B4 每天得分最高的{n}只 持有20天", yearly(QB, U, 21, topn=n))
print("===== C. 换股票池 =====")
for uname, UU in (("成交额>1亿", eligible & (amt20 >= 1e8)), ("流通市值前1500", UMV1500), ("流通市值前1000", UMV1000), ("流通市值前500", UMV500), ("流通市值1000名以外(且成交>3000万)", UALL & ~UMV1000)):
    sc = composite(variants["B4 原版(id60,ov60,abn20_250,pvc20)"], UU)
    show(f"{uname} 前10% 60天", yearly(sc, UU, 61))
    show(f"{uname} 前10% 20天", yearly(sc, UU, 21))
print("===== D. 入选股票长什么样（全市场前10%，最后一天和全期平均） =====")
G = yearly(QB, U, 61)["G"]
def avg_in(x, G): return np.nanmean(np.where(G, x, np.nan)), np.nanmean(np.where(U, x, np.nan))
for nm, x in (("流通市值(亿)中位数近似(均值)", FMV / 1e8), ("20日均成交额(亿)", amt20 / 1e8), ("20日换手率%", F("turn20")), ("60日波动(日)", F("vol60")), ("近60日涨幅", F("r60")), ("近250日涨幅", F("r250"))):
    a, b = avg_in(x, G); print(f"   {nm}: 入选 {a:.3f} / 全池 {b:.3f}")
print("   入选的流通市值中位数(亿):", np.nanmedian(np.where(G, FMV / 1e8, np.nan)), " 全池:", np.nanmedian(np.where(U, FMV / 1e8, np.nan)))
# 留存率：今天在前10%，20/60 天后还在的比例
for k in (20, 60):
    stay = (G[:-k] & G[k:]).sum() / max(1, G[:-k].sum()); print(f"   {k} 天后仍在前10% 的比例: {stay*100:.0f}%")
