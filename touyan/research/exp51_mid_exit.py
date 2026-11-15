"""实验 51：中期「变热了就卖」的参数稳不稳——冷热分阈值 20/30/40，最长持有 90/120/180/250 天。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from shiplab import *
from exp50_mid_plan import sim_mid          # noqa: E402（exp50 会顺带把自己的结果再打印一遍，这里不看）

print(f"@@@@@ {which}：中期卖出参数 @@@@@")
P = pick(okm, COLD)
OUT = {}
for cap in (90, 120, 180, 250):
    for thr in (0.2, 0.3, 0.4):
        OUT[f"{cap}|{thr}"] = brief(sim_mid(P, cap, flag=up_lim | (cold < thr)), f"最多 {cap} 天，涨停次日卖，冷热分<{thr*100:.0f} 卖")
print("--- 加价格止损还亏不亏（最多 120 天，涨停次日卖，冷热分<30 卖）---")
for st in (None, 0.12, 0.20, 0.30):
    OUT[f"stop|{st}"] = brief(sim_mid(P, 120, flag=up_lim | (cold < 0.3), stop=st), f"止损 {'无' if st is None else f'{st*100:.0f}%'}")
json.dump(OUT, open(f"exp51_{which}.json", "w"), ensure_ascii=False, indent=1)
