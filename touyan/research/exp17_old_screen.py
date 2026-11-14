"""实验 17：样本外十年里，「该躲开的」是否同样成立；恐慌日横截面在两个十年是否一致。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from feat import *
import numpy as np
U = UREL if which == "old" else UALL
names = ["r5", "r20", "r60", "id20", "id60", "ov20", "ov60", "vol60", "max20", "turn20", "abn5_60", "abn20_250", "pvc20", "amt", "illiq20", "size", "clv20", "hi250"]
screen(names, (6, 21, 61), U, f"{which} 成交额前七成" if which == "old" else "new 全市场")
# 恐慌日横截面
dnshare = np.nansum(np.where(U, dn_lim, 0), axis=1) / np.maximum(U.sum(1), 1)
panic = dnshare >= 0.02
QB = np.load(f"qb{TAG}_urel.npy") if which == "old" else np.load("qb_all.npy")
feats = {"5日跌幅": F("r5"), "20日跌幅": F("r20"), "60日涨幅": F("r60"), "当日涨跌": F("r1"), "20日波动": F("vol20"), "20日换手": F("turn20"), "流通市值": F("size"),
         "无人追捧打分": QB, "离250日高点": F("hi250"), "5日日内累计": F("id5"), "5日隔夜累计": F("ov5")}
for h in (6, 9):
    Fh = fwd(h)
    print(f"===== {which} 大面积跌停日（跌停占比≥2%，{int(panic.sum())} 天）横截面 5 组，持有 {h-1} 天原始收益；全体 {np.nanmean(base_of(Fh, U)[panic])*100:+.2f}% =====")
    for nm, x in feats.items():
        M = U & np.isfinite(Fh) & np.isfinite(x); pr = pct_rank(x, M)
        row = f"  {nm:<14}"
        for g in range(5):
            G = M & (pr >= g / 5) & ((pr < (g + 1) / 5) if g < 4 else (pr <= 1.0)); cnt = G.sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
            row += f" {np.nanmean(dr[panic])*100:+6.2f}%"
        print(row)
    # 当日跌停的 / 没跌停的
    for nm, G in (("当日跌停的股票", U & dn_lim), ("当日没跌停、5日跌幅最大20%", U & ~dn_lim & (pct_rank(F("r5"), U) < 0.2)), ("当日没跌停的全部", U & ~dn_lim),
                  ("流通市值最大20%", U & (pct_rank(F("size"), U) >= 0.8)), ("无人追捧前20%", U & (pct_rank(QB, U) >= 0.8))):
        Gh = G & np.isfinite(Fh); cnt = Gh.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            dr = np.where(cnt > 0, np.where(Gh, Fh, 0).sum(1) / cnt, np.nan)
        x = dr[panic]; x = x[np.isfinite(x)]
        print(f"  {nm:<26} 平均 {x.mean()*100:+.2f}% 上涨天数占比 {(x>0).mean()*100:.0f}% 最差 {x.min()*100:+.1f}% 最差一成 {np.percentile(x, 10)*100:+.1f}%")
