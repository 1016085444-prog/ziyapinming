"""实验 14：恐慌日里买什么。状态用全市场等权统计；横截面分组看之后 5/10 天。"""
from feat import *
import numpy as np, os
U = UALL
mr = np.nanmean(np.where(U, R, np.nan), axis=1)
lvl = np.cumprod(1 + np.nan_to_num(mr))
def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
m3, m5, m20 = mret(3), mret(5), mret(20)
ma20 = roll_mean(Cf, 20)
below = np.nanmean(np.where(U, Cf < ma20, np.nan), axis=1)
down5 = np.nanmean(np.where(U, F("r5") < -0.10, np.nan), axis=1)
np.save("state_m5.npy", m5); np.save("state_below.npy", below); np.save("state_m3.npy", m3); np.save("state_m20.npy", m20); np.save("state_down5.npy", down5)
panic = (m5 <= -0.07) | (below >= 0.90) | (down5 >= 0.30)
print("恐慌日数:", int(np.nansum(panic)), "（5日跌≥7%:", int(np.nansum(m5 <= -0.07)), " 20日线下≥90%:", int(np.nansum(below >= 0.9)), " 5天跌超10%的占比≥30%:", int(np.nansum(down5 >= 0.3)), "）")
ys = sorted(set(year.tolist()))
print("按年:", " ".join(f"{y}:{int(np.nansum(panic & (year == y)))}" for y in ys))
QB = np.load("qb_all.npy"); EP = np.load("ep.npy")
SQ = np.load(os.path.join(HERE, "fpanel", "sq_yoy.npy"))
feats = {"5日跌幅(越低跌越多)": F("r5"), "3日跌幅": F("r3"), "当日涨跌": F("r1"), "20日跌幅": F("r20"), "60日涨幅": F("r60"), "250日涨幅": F("r250"),
         "20日波动": F("vol20"), "20日换手": F("turn20"), "流通市值": F("size"), "无人追捧打分": QB, "盈利收益率": EP, "单季利润同比": SQ,
         "离250日高点": F("hi250"), "当日收盘位置": np.where(valid, CLV, np.nan), "5日内跌停天数": roll_sum(dn_lim.astype(float), 5)[0], "5日隔夜累计": F("ov5"), "5日日内累计": F("id5")}
for h in (6, 11):
    Fh = fwd(h)
    print(f"===== 恐慌日（{int(panic.sum())} 天）横截面：按线索分 5 组，之后持有 {h-1} 天的收益（原始，非超额）；全体平均 {np.nanmean(base_of(Fh, U)[panic])*100:+.2f}% =====")
    for nm, x in feats.items():
        M = U & np.isfinite(Fh) & np.isfinite(x)
        pr = pct_rank(x, M)
        row = f"  {nm:<16}"
        for g in range(5):
            G = M & (pr >= g / 5) & (pr < (g + 1) / 5 if g < 4 else pr <= 1.0)
            cnt = G.sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
            row += f" {np.nanmean(dr[panic])*100:+6.2f}%"
        # 最低组 − 最高组 在恐慌日的差，及按年
        print(row)
# 候选买法在恐慌日的表现（按天平均），分年度
print("===== 恐慌日的几种买法（持有 5 天 / 10 天；按天平均；括号内为上涨天数占比） =====")
r5 = F("r5"); pr5 = pct_rank(r5, U); qb = pct_rank(QB, U)
lim5 = roll_sum(dn_lim.astype(float), 5)[0]
cands = {
    "全市场随便买": U,
    "5日跌幅最大20%": U & (pr5 < 0.2),
    "5日跌幅最大20% 且 近5日没跌停": U & (pr5 < 0.2) & (lim5 == 0),
    "5日跌幅最大20% 且 赚钱": U & (pr5 < 0.2) & (EP > 0),
    "5日跌幅最大20% 且 无人追捧前50%": U & (pr5 < 0.2) & (qb >= 0.5),
    "5日跌幅最大20% 且 赚钱 且 无人追捧前50% 且 没跌停": U & (pr5 < 0.2) & (EP > 0) & (qb >= 0.5) & (lim5 == 0),
    "无人追捧前20%": U & (qb >= 0.8),
    "流通市值前300": U300,
    "流通市值1000名以外": U & ~UMV1000,
}
for nm, G in cands.items():
    row = f"  {nm:<40}"
    for h in (6, 11):
        Fh = fwd(h); Gh = G & np.isfinite(Fh); cnt = Gh.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            dr = np.where(cnt > 0, np.where(Gh, Fh, 0).sum(1) / cnt, np.nan)
        x = dr[panic]; x = x[np.isfinite(x)]
        row += f" h{h-1}: {x.mean()*100:+.2f}% ({(x>0).mean()*100:.0f}%) 最差 {x.min()*100:+.1f}% |"
        if h == 6:
            yrow = " ".join(f"{y%100:02d}:{np.nanmean(dr[panic & (year == y)])*100:+.1f}" for y in ys if np.isfinite(dr[panic & (year == y)]).any())
    print(row + " 5天分年: " + yrow)
