"""实验 24：大盘预估分高的日子里买什么。按状态分别看横截面。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np, mscore
U = UREL if which == "old" else UALL
d = dict(np.load(f"mkt_{which}.npz")); s = mscore.score(d); comp = mscore.components(d)
panic = comp["dn_many"][0]; strong = (comp["big_up"][0] | comp["up_many"][0]) & ~panic & (s >= 2); month = comp["month"][0] & ~panic
states = {"分数≥3": s >= 3, "分数=2": s == 2, "分数≤-1": s <= -1, "恐慌日(跌停≥2%)": panic, "强势日(大涨或涨停多,分数≥2,非恐慌)": strong, "月末月初窗口(非恐慌)": month}
QB = np.load(f"qb{TAG}_urel.npy") if which == "old" else np.load("qb_all.npy")
feats = {"当日涨跌": F("r1"), "5日涨跌": F("r5"), "20日涨跌": F("r20"), "流通市值": F("size"), "20日波动": F("vol20"), "20日换手": F("turn20"),
         "当日换手/20日": np.where(valid, TR, np.nan) / F("turn20"), "无人追捧打分": QB, "离250日高点": F("hi250"), "当日收盘位置": np.where(valid, CLV, np.nan)}
for h in (3, 6):
    Fh = fwd(h); b = base_of(Fh, U)
    for snm, sm in states.items():
        sm = sm & np.isfinite(b)
        print(f"===== {which} | {snm}（{int(sm.sum())} 天）| 明开买，第 {h-1} 天收盘卖 | 全体平均 {np.nanmean(b[sm])*100:+.2f}%，上涨天数 {np.nanmean(b[sm] > 0)*100:.0f}% =====")
        for nm, x in feats.items():
            M = U & np.isfinite(Fh) & np.isfinite(x); pr = pct_rank(x, M)
            row = f"  {nm:<12}"
            for g in range(5):
                G = M & (pr >= g / 5) & ((pr < (g + 1) / 5) if g < 4 else (pr <= 1.0)); cnt = G.sum(1)
                with np.errstate(invalid="ignore", divide="ignore"):
                    dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
                row += f" {np.nanmean(dr[sm])*100:+6.2f}%"
            print(row)
        for nm, G in (("当日涨停的", U & up_lim), ("当日涨≥5%但没涨停", U & ~up_lim & (R >= 0.05)), ("当日跌停的", U & dn_lim)):
            Gh = G & np.isfinite(Fh); cnt = Gh.sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                dr = np.where(cnt > 0, np.where(Gh, Fh, 0).sum(1) / cnt, np.nan)
            x = dr[sm]; x = x[np.isfinite(x)]
            if len(x): print(f"  {nm:<16} 平均 {x.mean()*100:+.2f}%（{len(x)} 天有）")
