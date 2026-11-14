"""实验 13：财务条件 × 「无人追捧」打分。"""
from feat import *
import numpy as np, os
FP = {k: np.load(os.path.join(HERE, "fpanel", k + ".npy")) for k in ("sq_yoy", "np_yoy", "rev_yoy", "roe", "eps_ttm", "bps", "rep_t0")}
U = UALL
QB = np.load("qb_all.npy")
qb = pct_rank(QB, U)
with np.errstate(invalid="ignore", divide="ignore"):
    EP = FP["eps_ttm"] / Cf            # 盈利收益率（市盈率的倒数）
    BP = FP["bps"] / Cf
since = np.arange(T)[:, None] - FP["rep_t0"]      # 距离上次财报公告的交易日数

def yearly_mask(G, U, h):
    Fh = fwd(h); M = U & np.isfinite(Fh)
    b = base_of(Fh, M); G = G & M
    cnt = G.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where(cnt > 0, np.where(G, Fh, 0).sum(1) / cnt, np.nan)
    dex = dr - b
    ys = sorted(set(year.tolist()))
    ye = {y: np.nanmean(dex[year == y]) for y in ys if np.isfinite(dex[year == y]).any()}
    return {"n": int(np.nanmean(cnt[cnt > 0])) if (cnt > 0).any() else 0, "ret": np.nanmean(dr), "ex": np.nanmean(dex), "t": nw_t(dex, h),
            "win": np.nanmean(np.where(G, Fh > 0, np.nan)), "ye": ye, "dev": np.nanmean(dex[year <= 2021]), "oos": np.nanmean(dex[year >= 2022])}
def show(label, res):
    ye = res["ye"]; pos = sum(1 for v in ye.values() if v > 0)
    print(f"{label:<46} 每天{res['n']:4d}只 收益 {res['ret']*100:+.2f}% 超额 {res['ex']*100:+.2f}% t={res['t']:.1f} 个股胜率 {res['win']*100:.0f}% | 到2021 {res['dev']*100:+.2f}% 2022起 {res['oos']*100:+.2f}% | 赢 {pos}/{len(ye)} | " + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in ye.items()), flush=True)

print("===== 财务条件单独的效果（全市场，持有60天） =====")
conds = {
    "在赚钱(滚动每股收益>0)": EP > 0,
    "亏损(滚动每股收益<=0)": EP <= 0,
    "单季利润同比>0": FP["sq_yoy"] > 0,
    "单季利润同比>30%": FP["sq_yoy"] > 0.3,
    "单季利润同比<-30%": FP["sq_yoy"] < -0.3,
    "ROE(累计)>8%": FP["roe"] > 8,
    "便宜(盈利收益率在前30%)": pct_rank(np.where(EP > 0, EP, np.nan), U) >= 0.7,
    "贵(盈利收益率在后30%,且赚钱)": pct_rank(np.where(EP > 0, EP, np.nan), U) < 0.3,
    "市净率最低30%": pct_rank(BP, U) >= 0.7,
    "财报公告后20天内": (since >= 0) & (since <= 20),
}
for nm, G in conds.items():
    show(nm, yearly_mask(G & U, U, 61))
print("===== 无人追捧前10% 再加财务条件（持有60天） =====")
top = (qb >= 0.9)
for nm, G in [("（不加条件）", np.ones((T, N), bool))] + list(conds.items()):
    show("前10% + " + nm, yearly_mask(top & G & U, U, 61))
print("===== 组合条件 =====")
combos = {
    "前10% + 赚钱 + 单季同比>0": top & (EP > 0) & (FP["sq_yoy"] > 0),
    "前10% + 赚钱 + 单季同比>-30%": top & (EP > 0) & (FP["sq_yoy"] > -0.3),
    "前10% + 赚钱 + 不贵(盈利收益率前70%)": top & (pct_rank(np.where(EP > 0, EP, np.nan), U) >= 0.3),
    "前10% + 赚钱 + 便宜(前30%)": top & (pct_rank(np.where(EP > 0, EP, np.nan), U) >= 0.7),
    "前20% + 赚钱 + 单季同比>0 + 便宜(前50%)": (qb >= 0.8) & (EP > 0) & (FP["sq_yoy"] > 0) & (pct_rank(np.where(EP > 0, EP, np.nan), U) >= 0.5),
    "前10% + 赚钱 + 单季同比>30%": top & (EP > 0) & (FP["sq_yoy"] > 0.3),
}
for nm, G in combos.items():
    for h in (21, 61):
        show(f"{nm} h{h-1}", yearly_mask(G & U, U, h))
np.save("ep.npy", EP.astype(np.float32))
