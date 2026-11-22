"""实验 67：第二轮改进定稿后的检验数字（ship4_{which}.json），软件里 evidence.py 的新数字从这里来。

短期：选股不变；出手分四档——
  强：分数 ≥4 且温度 <60，或分数 ≥3 且温度 <40；
  一般：分数 3、温度 40–60；
  轻仓：分数 ≥3、温度 60–80，或分数 2、温度 <60；
  不出手：温度 ≥80，分数 2 且温度 ≥60，分数 ≤1。
  （早年没有温度的日子：≥4 算强、3 算一般、2 算轻仓。）
中期：候选改成冷热分 ≥85、不是大盘股、在赚钱、没涨停跌停；按「超预期（单季利润比去年同季多出的部分 ÷ 流通市值）、
  单季利润同比、成交额小、近 20 天没涨停、冷热分」五项名次的平均排序；建仓时机：温度 <40 随时买，40–80 只在大盘分 ≥2 的日子买，≥80 不买。
另外：入选名次 1–10 各自之后的收益（页面上用来说明「排第几没有区别，等额买」）。
python exp67_ship4.py new|old
"""
import os, sys, json
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from xlab import *   # noqa
import xlab

OUT = {"period": [int(cal[0]), int(cal[-1])]}
NT = ~np.isfinite(TEMP)


def full(tr, label, hb):
    r = brief(tr, label, hb=hb)
    if not r:
        return None
    ret, t = tr["ret"], tr["t"]
    b = base_of(fwd(hb), U)[t]
    r["base"] = float(np.nanmean(b))
    r["by_year_n"] = {int(y): int((year[t] == y).sum()) for y in ys if (year[t] == y).sum()}
    r["by_year_win"] = {int(y): float((ret[year[t] == y] > 0).mean()) for y in ys if (year[t] == y).sum()}
    r["by_year_base"] = {int(y): float(np.nanmean(b[year[t] == y])) for y in ys if (year[t] == y).sum()}
    r["hist"] = np.histogram(np.clip(ret, -0.3, 0.5), bins=np.arange(-0.30, 0.5001, 0.05))[0].tolist()
    r["exit"] = {int(k): int((tr["reason"] == k).sum()) for k in np.unique(tr["reason"])}
    return r


def pick_ranked(okmask, key, days=None, n=10, cap=2):
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


def by_rank(tr, Pn):
    rk_ = Pn[tr["t"], tr["i"]]
    return {int(r): {"n": int((rk_ == r).sum()), "mean": float(tr["ret"][rk_ == r].mean()), "win": float((tr["ret"][rk_ == r] > 0).mean())}
            for r in range(1, int(Pn.max()) + 1) if (rk_ == r).sum()}


# ---------------- 短期 ----------------
strong = ((S >= 4) & ((TEMP < 60) | NT)) | ((S >= 3) & (TEMP < 40))
normal = (S == 3) & (((TEMP >= 40) & (TEMP < 60)) | NT)
light = ((S >= 3) & (TEMP >= 60) & (TEMP < 80)) | ((S == 2) & ((TEMP < 60) | NT))
none_ = ~(strong | normal | light)
OUT["short"] = {}
for lab, m in (("strong", strong), ("normal", normal), ("light", light), ("go", strong | normal), ("act", strong | normal | light),
               ("skip_s2_hot", (S == 2) & (TEMP >= 60)), ("skip_hot80", (S >= 2) & (TEMP >= 80))):
    OUT["short"][lab] = full(trades(pick(oks, ps, days=m), max_days=5, stop=0.08, max_gap=0.02), f"短期 {lab}（{int(m.sum())} 天）", 6)
    if OUT["short"][lab] is not None:
        OUT["short"][lab]["days_n"] = int(m.sum()); OUT["short"][lab]["per_year"] = float(m.sum() / (T / 245))
Pn = pick_ranked(oks, ps, days=strong | normal)
OUT["short"]["rank"] = by_rank(trades(Pn > 0, max_days=5, stop=0.08, max_gap=0.02), Pn)
print("短期 名次：", {k: round(v["mean"] * 100, 2) for k, v in OUT["short"]["rank"].items()}, flush=True)

# ---------------- 中期 ----------------
EXIT = up_lim | (cold < 0.3)
with np.errstate(invalid="ignore", divide="ignore"):
    xlab._xc["surp_mv"] = (fund("surp_raw") / FMV).astype(np.float32)
candN = U & valid & (cold >= 0.85) & (szp < 0.7) & PROFIT & ~up_lim & ~dn_lim


def rk(nm, sign, mask):
    p = pct_rank(X(nm) * sign, mask)
    return np.where(np.isfinite(p), p, 0.5)


KEYN = (rk("surp_mv", 1, candN) + rk("sq_yoy", 1, candN) + rk("amt", -1, candN) + rk("up_n20", -1, candN) + rk("cold", 1, candN)) / 5
POLICY = (TEMP < 40) | ((TEMP >= 40) & (TEMP < 80) & (S >= 2)) | (NT & (S >= 0))
OUT["mid"] = {"candidates": float(candN.sum(1)[300:].mean())}
OUT["mid"]["new_all"] = full(sim_mid(pick(candN, KEYN), 120, flag=EXIT), "中期 新方法 每天", 65)
OUT["mid"]["new"] = full(sim_mid(pick(candN, KEYN, days=POLICY), 120, flag=EXIT), "中期 新方法 按时机", 65)
OUT["mid"]["old_all"] = full(sim_mid(pick(okm, COLD), 120, flag=EXIT), "中期 原方法 每天", 65)
OUT["mid"]["old_policy"] = full(sim_mid(pick(okm, COLD, days=POLICY), 120, flag=EXIT), "中期 原方法 按时机", 65)
OUT["mid"]["stop12"] = full(sim_mid(pick(candN, KEYN, days=POLICY), 120, flag=EXIT, stop=0.12), "中期 新方法 按时机 + 12% 止损", 65)
tiers = {"best": (TEMP < 40) & (S >= 2), "good": (TEMP < 40) & (S < 2), "ok": (TEMP >= 40) & (TEMP < 80) & (S >= 2),
         "wait": (TEMP >= 40) & (TEMP < 80) & (S < 2), "avoid": TEMP >= 80, "early": NT}
OUT["mid"]["tiers"] = {}
for lab, m in tiers.items():
    if m.sum() >= 20:
        OUT["mid"]["tiers"][lab] = full(sim_mid(pick(candN, KEYN, days=m), 120, flag=EXIT), f"中期 新方法 建仓 {lab}（{int(m.sum())} 天）", 65)
OUT["mid"]["by_temp"] = {}
for tl, tm in (("lt20", TEMP < 20), ("20to40", (TEMP >= 20) & (TEMP < 40)), ("lt40", TEMP < 40), ("40to60", (TEMP >= 40) & (TEMP < 60)),
               ("60to80", (TEMP >= 60) & (TEMP < 80)), ("40to80", (TEMP >= 40) & (TEMP < 80)), ("ge80", TEMP >= 80)):
    if tm.sum() >= 20:
        OUT["mid"]["by_temp"][tl] = full(sim_mid(pick(candN, KEYN, days=tm), 120, flag=EXIT), f"中期 新方法 温度 {tl}（{int(tm.sum())} 天）", 65)
PnM = pick_ranked(candN, KEYN, days=POLICY)
OUT["mid"]["rank"] = by_rank(sim_mid(PnM > 0, 120, flag=EXIT), PnM)
print("中期 名次：", {k: round(v["mean"] * 100, 2) for k, v in OUT["mid"]["rank"].items()}, flush=True)
# 入选的里面：超预期、单季同比的分布（给页面上的「看数字」用）
P = pick(candN, KEYN, days=POLICY)
sm = xlab._xc["surp_mv"][P]; sq = X("sq_yoy")[P]
OUT["mid"]["picked"] = {"surp_mv_median": float(np.nanmedian(sm)), "sq_yoy_median": float(np.nanmedian(sq)), "sq_pos": float(np.nanmean(sq > 0))}
json.dump(OUT, open(f"ship4_{which}.json", "w"), ensure_ascii=False, indent=1)
print("saved")
