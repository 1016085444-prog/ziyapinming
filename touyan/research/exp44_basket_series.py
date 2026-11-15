"""实验 44a：几个长期组合的日收益序列（每 21 个交易日换一次成分，等权），存下来给「按温度进出」的模拟用。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

COLDR = np.load(f"cold{TAG}.npy"); cold = pct_rank(COLDR, U)
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r3r = pct_rank(F("r750"), U); r3r = np.where(np.isfinite(r3r), r3r, 0.5)
dyr = pct_rank(np.where(DY > 0, DY, np.nan), U)
profit = NPTTM > 0
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r3r >= 0.8)
BIG = U & (rk_mv <= 800)
rules = {
    "all": U,
    "calm": U & ~hot,
    "divlow": U & (dyr >= 0.7) & (volr < 0.5) & DIV3Y & profit,
    "steady": U & ~hot & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "bigsteady": BIG & ~hot & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "hot": U & hot,
}
Rz = np.where(valid, R, 0.0)          # 停牌当天收益记 0（复牌那天的涨跌已经算在 R 里）
out = {"d": cal}
for nm, m in rules.items():
    series = np.zeros(T); members = None; turn = []
    for t in range(T):
        if t >= 260 and (t - 260) % 21 == 0:
            new = np.nonzero(m[t])[0]
            if members is not None and len(new):
                turn.append(1 - len(np.intersect1d(members, new)) / max(len(new), 1))
            members = new if len(new) else members
        elif t < 260 and nm == "all" and t % 21 == 0:
            members = np.nonzero(m[t])[0] if m[t].any() else members
        if members is not None and len(members) and t + 1 < T:
            series[t + 1] = float(np.mean(Rz[t + 1, members]))       # 成分在 t 日收盘后定下，t+1 日起算收益
    out[nm] = series
    print(which, nm, "年化 %.1f%%" % ((np.prod(1 + series[261:]) ** (245 / max(T - 261, 1)) - 1) * 100), "每次换手 %.0f%%" % (np.mean(turn) * 100 if turn else 0))
np.savez(f"basket_{which}.npz", **out)
