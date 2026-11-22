"""实验 65：
1) 入选的 5 只里，排第 1 的历史上是不是比排第 5 的好？（决定页面上的「分数」有没有意义）——短期、中期都看；
2) 短期：按出手日的强弱（分数 × 温度）分档，拿 3 / 5 / 7 / 10 天哪个好；一天选 5 只还是 10 只；按波动分仓位（波动大的少买）有没有用；
3) 中期：新的排序（实验 64 的 B5）下，一天选 5 只还是 10 只；建仓日分数 × 温度。
python exp65_rank_hold.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa

OUT = {}


def pick_ranked(okmask, key, days=None, n=5, cap=2):
    """和 pick 一样，但返回每个入选的名次（1..n），没入选是 0。"""
    Pn = np.zeros((T, N), np.int8)
    for t in (range(T) if days is None else np.nonzero(days)[0]):
        idx = np.nonzero(okmask[t])[0]
        if len(idx) == 0:
            continue
        order = idx[np.argsort(-key[t, idx])]; used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap:
                continue
            used[g] = used.get(g, 0) + 1; k += 1; Pn[t, j] = k
            if k >= n:
                break
    return Pn


def by_rank(tr, Pn, lab):
    rk_ = Pn[tr["t"], tr["i"]]
    res = {}
    row = f"  {lab:<26}"
    for r in range(1, int(Pn.max()) + 1):
        m = rk_ == r
        if m.sum():
            x = tr["ret"][m]; res[r] = {"n": int(m.sum()), "mean": float(x.mean()), "win": float((x > 0).mean())}
            row += f" | 第{r}名 {x.mean()*100:+.2f}% {(x > 0).mean()*100:.0f}%"
    print(row, flush=True)
    return res


GO = S >= 3
# ---------- 1) 名次 ----------
print(f"===== {which}：入选名次和之后的收益 =====")
Pn = pick_ranked(oks, ps, days=GO, n=10)
tr = trades(Pn > 0, max_days=5, stop=0.08, max_gap=0.02)
OUT["short_rank"] = by_rank(tr, Pn, "短期（分数≥3，前 10 名）")
EXIT = up_lim | (cold < 0.3)
candB = U & valid & (cold >= 0.8) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim


def rk(nm, sign, mask):
    p = pct_rank(X(nm) * sign, mask)
    return np.where(np.isfinite(p), p, 0.5)


KEYB = (rk("surp", 1, candB) + rk("sq_yoy", 1, candB) + rk("amt", -1, candB) + rk("up_n20", -1, candB) + rk("cold", 1, candB)) / 5
PnA = pick_ranked(okm, COLD, n=10)
trA = sim_mid(PnA > 0, 120, flag=EXIT)
OUT["mid_rank_now"] = by_rank(trA, PnA, "中期 现在的排序（前 10 名）")
PnB = pick_ranked(candB, KEYB, n=10)
trB = sim_mid(PnB > 0, 120, flag=EXIT)
OUT["mid_rank_new"] = by_rank(trB, PnB, "中期 新排序（前 10 名）")

# ---------- 2) 短期：拿几天、选几只、按波动分仓 ----------
print(f"===== {which}：短期 出手日强弱 × 拿几天 =====")
tiers = {"强（分数≥4，或≥3 且温度<40）": (S >= 4) | ((S >= 3) & (TEMP < 40)),
         "一般（分数 3，温度 40–60）": (S == 3) & (TEMP >= 40) & (TEMP < 60),
         "偏热（分数 3，温度≥60）": (S == 3) & (TEMP >= 60),
         "早年没温度（分数≥3）": (S >= 3) & ~np.isfinite(TEMP),
         "轻（分数 2，温度<60）": (S == 2) & (TEMP < 60),
         "轻（分数 2，温度≥60）": (S == 2) & (TEMP >= 60)}
for tl, tm in tiers.items():
    if tm.sum() < 8:
        print(f"  {tl}: 天数太少（{int(tm.sum())}）"); continue
    P5 = pick(oks, ps, days=tm)
    for hold in (3, 5, 7, 10):
        OUT[f"short|{tl}|hold{hold}"] = brief(trades(P5, max_days=hold, stop=0.08, max_gap=0.02), f"{tl}（{int(tm.sum())} 天）拿 {hold} 天", hb=hold + 1)
print(f"===== {which}：短期 选几只 =====")
for n in (3, 5, 10, 20):
    OUT[f"short|n{n}"] = brief(trades(pick(oks, ps, days=GO, n=n, cap=max(2, n // 3)), max_days=5, stop=0.08, max_gap=0.02), f"分数≥3 每天 {n} 只", hb=6)
print(f"===== {which}：短期 按波动分仓位（每天那一篮子：等额 vs 波动倒数加权）=====")
tr5 = trades(pick(oks, ps, days=GO), max_days=5, stop=0.08, max_gap=0.02)
v = X("vol60")[tr5["t"], tr5["i"]]
df = pd.DataFrame({"t": tr5["t"], "r": tr5["ret"], "w": 1 / np.clip(np.nan_to_num(v, nan=np.nanmedian(v)), 0.01, None)})
eq = df.groupby("t")["r"].mean()
iv = df.groupby("t").apply(lambda g: float((g["r"] * g["w"]).sum() / g["w"].sum()))
for lab, sr in (("等额", eq), ("波动倒数加权", iv)):
    print(f"  {lab}: 篮子平均 {sr.mean()*100:+.2f}% 上涨 {(sr > 0).mean()*100:.0f}% 波动 {sr.std()*100:.2f}% 最差 {sr.min()*100:+.1f}% 收益/波动 {sr.mean() / sr.std():.3f}", flush=True)
    OUT[f"short|weight|{lab}"] = {"mean": float(sr.mean()), "up": float((sr > 0).mean()), "sd": float(sr.std()), "worst": float(sr.min())}

# ---------- 3) 中期：选几只、建仓日 ----------
print(f"===== {which}：中期 新排序 选几只 / 建仓日 =====")
for n in (5, 10):
    OUT[f"mid|n{n}"] = brief(sim_mid(pick(candB, KEYB, n=n, cap=max(2, n // 3)), 120, flag=EXIT), f"新排序 每天 {n} 只", hb=65)
for lab, m in (("温度<40 且 分数≥2", (TEMP < 40) & (S >= 2)), ("温度<40 且 分数<2", (TEMP < 40) & (S < 2)),
               ("温度 40–80 且 分数≥2", (TEMP >= 40) & (TEMP < 80) & (S >= 2)), ("温度 40–80 且 分数<2", (TEMP >= 40) & (TEMP < 80) & (S < 2)),
               ("温度≥80", TEMP >= 80), ("早年没温度", ~np.isfinite(TEMP))):
    if m.sum() < 20:
        print(f"  {lab}: 天数太少（{int(m.sum())}）"); continue
    OUT[f"mid|entry|{lab}"] = brief(sim_mid(pick(candB, KEYB, days=m), 120, flag=EXIT), f"新排序 建仓日 {lab}（{int(m.sum())} 天）", hb=65)
json.dump(OUT, open(f"exp65_{which}.json", "w"), ensure_ascii=False, indent=1, default=float)
print("saved")
