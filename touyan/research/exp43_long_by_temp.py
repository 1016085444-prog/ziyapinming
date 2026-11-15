"""实验 43：长期组合按「建仓时的市场温度」分开看——拿一年、两年、三年各是什么结果。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

z = np.load("temps.npz", allow_pickle=True)
names = list(z["names"]); tv = z[f"t{names.index('两者平均(近10年)')}"]
tmap = dict(zip(z["d"].tolist(), tv.tolist()))
TEMP = np.array([tmap.get(int(x), np.nan) for x in cal])

COLDR = np.load(f"cold{TAG}.npy"); cold = pct_rank(COLDR, U)
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r3r = pct_rank(F("r750"), U); r3r = np.where(np.isfinite(r3r), r3r, 0.5)
epr = pct_rank(EP, U); bpr = pct_rank(BP, U); dyr = pct_rank(np.where(DY > 0, DY, np.nan), U)
profit = NPTTM > 0
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r3r >= 0.8)
BIG = U & (rk_mv <= 800)
rules = {
    "全池": U,
    "只做回避": U & ~hot,
    "红利低波+三年分红+赚钱": U & (dyr >= 0.7) & (volr < 0.5) & DIV3Y & profit,
    "稳健(赚钱+分红+不热+ROE三年≥8)": U & ~hot & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "大市值稳健": BIG & ~hot & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "被回避掉的": U & hot,
}
OUT = {}
for h, hn in ((245, "一年"), (490, "两年"), (735, "三年")):
    if T - h - 262 < 150:
        continue
    days = form_days(h)
    print(f"===== {which}：拿{hn}；建仓日 {len(days)} 个 =====")
    for nm, m in rules.items():
        df = port(m, h, days)
        tt = TEMP[df["t"].to_numpy()]
        row = f"  {nm:<26}"
        for lo, hi in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101)):
            k = np.isfinite(tt) & (tt >= lo) & (tt < hi)
            if k.sum() < 3:
                row += f" | {lo:>2}-{min(hi,100):<3} 样本少            "; continue
            x = df["ret"].to_numpy()[k]; e = df["ex"].to_numpy()[k]
            row += f" | {lo:>2}-{min(hi,100):<3} {x.mean()*100:+6.1f}% 赚{(x>0).mean()*100:3.0f}% 最差{x.min()*100:+4.0f}% n={int(k.sum()):<3d}"
            OUT[f"{nm}|{hn}|{lo}"] = {"n": int(k.sum()), "mean": float(x.mean()), "win": float((x > 0).mean()), "worst": float(x.min()), "ex": float(e.mean())}
        print(row, flush=True)
json.dump(OUT, open(f"exp43_{which}.json", "w"), ensure_ascii=False, indent=1)
