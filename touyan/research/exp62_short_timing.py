"""实验 62：短期——出手的时机还能不能更准：
1) 大盘预估分每一档（≤−1 … ≥5）× 市场温度：之后 5 天全池平均、按现在规则选 5 只的结果；
2) 分数 ≥3 的日子里，再按其它大盘状态分两半，哪些状态让结果明显更好或更差；
3) 分数 2 的日子里，有没有一部分其实和 ≥3 一样好（可以升级成出手日）。
python exp62_short_timing.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

d = dict(np.load(os.path.join(HERE, f"mkt_{which}.npz")))
B6 = base_of(fwd(6), U)
oksx = oks
P_ALL = pick(oksx, ps)          # 每天都按现在的规则选 5 只
TR = trades(P_ALL, max_days=5, stop=0.08, max_gap=0.02)
df = pd.DataFrame({"t": TR["t"], "r": TR["ret"]})
day_pick = df.groupby("t")["r"].mean().reindex(range(T)).to_numpy()      # 每天那一篮子的平均
lvl = np.cumprod(1 + np.nan_to_num(d["mr"]))


def mret(k):
    return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1


OUT = {}


def row(lab, m):
    m = m & np.isfinite(B6)
    k = m & np.isfinite(day_pick)
    if m.sum() < 8:
        print(f"  {lab:<28} 天数太少（{int(m.sum())}）"); return None
    r = {"days": int(m.sum()), "base": float(np.nanmean(B6[m])), "base_up": float(np.nanmean(B6[m] > 0)),
         "pick": float(np.nanmean(day_pick[k])), "pick_up": float(np.nanmean(day_pick[k] > 0)), "pick_worst": float(np.nanmin(day_pick[k])) if k.any() else None}
    print(f"  {lab:<28} 天数 {r['days']:4d} | 全池 5 天 {r['base']*100:+.2f}% 上涨 {r['base_up']*100:3.0f}% | 选 5 只 {r['pick']*100:+.2f}% 赚钱的篮子 {r['pick_up']*100:3.0f}% 最差 {r['pick_worst']*100:+.1f}%", flush=True)
    return r


print(f"===== {which}：大盘预估分每一档 =====")
for lab, m in (("≤−1", S <= -1), ("0", S == 0), ("1", S == 1), ("2", S == 2), ("3", S == 3), ("4", S == 4), ("≥5", S >= 5)):
    OUT[f"S|{lab}"] = row(f"分数 {lab}", m)
print("--- 分数 × 温度 ---")
for sl, sm in (("2", S == 2), ("3", S == 3), ("≥4", S >= 4)):
    for tl, tm in (("<40", TEMP < 40), ("40–60", (TEMP >= 40) & (TEMP < 60)), ("≥60", TEMP >= 60), ("无温度", ~np.isfinite(TEMP))):
        OUT[f"ST|{sl}|{tl}"] = row(f"分数 {sl} 温度 {tl}", sm & tm)

print("--- 分数 ≥3 的日子：按其它大盘状态分两半（低一半 / 高一半）---")
GO = S >= 3
states = {"当天涨跌": d["mr"], "5日涨跌": mret(5), "20日涨跌": mret(20), "60日涨跌": mret(60), "上涨家数占比": d["adv"], "20日线上方占比": d["above"],
          "涨停占比": d["upshare"], "跌停占比": d["dnshare"], "成交额相对20日": d["amt_rel"], "小盘−大盘5日": d["style5"], "炸板率": d["fail"],
          "昨日涨停今天表现": d["zt"], "温度": TEMP}
for nm, x in states.items():
    ok = GO & np.isfinite(x)
    if ok.sum() < 20:
        continue
    med = np.nanmedian(x[ok])
    a = row(f"{nm} 低于 {med:+.3f}", ok & (x < med)); b = row(f"{nm} 高于 {med:+.3f}", ok & (x >= med))
    OUT[f"GO|{nm}"] = {"median": float(med), "low": a, "high": b}

print("--- 分数 2 的日子：哪些能升级 ---")
for nm, x in states.items():
    ok = (S == 2) & np.isfinite(x)
    if ok.sum() < 20:
        continue
    med = np.nanmedian(x[ok])
    a = row(f"[2分] {nm} 低于 {med:+.3f}", ok & (x < med)); b = row(f"[2分] {nm} 高于 {med:+.3f}", ok & (x >= med))
    OUT[f"S2|{nm}"] = {"median": float(med), "low": a, "high": b}
json.dump(OUT, open(f"exp62_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
