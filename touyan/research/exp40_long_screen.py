"""实验 40：长期（拿一年）什么管用——估值、分红、质量、成长、波动、冷热，逐个分五组看。

每 21 个交易日建一次仓，下一交易日开盘买、拿 245 个交易日（约一年）、扣 0.2%，和同一天全池平均比。
"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

H1 = 245
COLD = np.load(f"cold{TAG}.npy")
BIG = U & (rk_mv <= 800)            # 流通市值最大的 800 只
MID = U & (rk_mv > 300) & (rk_mv <= 1500)
with np.errstate(invalid="ignore", divide="ignore"):
    CASHQ = np.where(EPS > 0, CFPS / EPS, np.nan)     # 注意：cfps 是累计值，只做粗略参考
factors = {
    "EP 盈利收益率": EP, "BP 净资产/市值": BP, "DY 股息率": DY, "ROE 滚动": ROE, "ROE 年报": ROE_ANN, "ROE 三年最低": ROE_MIN3,
    "净利同比": NPY, "单季净利同比": SQY, "营收同比": REVY, "毛利率": GM, "现金流/利润(三年)": CASH3,
    "波动(250日,取负)": -F("vol250"), "换手(250日,取负)": -F("turn250"), "市值(取负)": -F("size"), "冷热(越冷越大)": COLD,
    "一年涨幅": F("r250"), "一年动量(跳过20日)": F("mom250_20"), "三年涨幅(取负)": -F("r750"), "离一年高点(取负)": -F("hi250"),
}
print(f"===== {which}: {cal[0]}..{cal[-1]}，建仓日 {len(form_days(H1))} 个（{cal[form_days(H1)[0]]}..{cal[form_days(H1)[-1]]}） =====")
base = port(U, H1)
print(f"全池拿一年：平均 {base['ret'].mean()*100:+.1f}%，建仓日里赚钱的占 {(base['ret'] > 0).mean()*100:.0f}%，按年：" +
      " ".join(f"{int(k)%100:02d}:{v*100:+.0f}" for k, v in base.groupby(year[base['t'].to_numpy()])['ret'].mean().items()))
for uname, um in (("全池", U), ("市值前800", BIG), ("市值300-1500名", MID)):
    print(f"--- 股票池：{uname}；五组超额（从指标最小到最大，%），最高组/最低组跑赢全池的年数 ---")
    for nm, X in factors.items():
        out, tb, bb, ny = quint(X, H1, um)
        print(f"  {nm:<22} " + " ".join(f"{v*100:+6.1f}" for v in out) + f"   最高组 {tb}/{ny} 年跑赢，最低组 {bb}/{ny} 年跑赢", flush=True)
# 半年、两年
for h in (122, 490):
    if T - h - 262 < 200:
        continue
    print(f"--- 全池，拿 {h} 个交易日 ---")
    for nm in ("EP 盈利收益率", "BP 净资产/市值", "DY 股息率", "ROE 滚动", "波动(250日,取负)", "冷热(越冷越大)", "市值(取负)", "净利同比"):
        out, tb, bb, ny = quint(factors[nm], h, U)
        print(f"  {nm:<22} " + " ".join(f"{v*100:+6.1f}" for v in out) + f"   最高组 {tb}/{ny} 年跑赢，最低组 {bb}/{ny} 年跑赢", flush=True)
