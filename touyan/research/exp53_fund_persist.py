"""实验 53：主动偏股基金——过去业绩好的，以后还好吗？

样本：2016 年底以前成立、现在还在的主动股票型/混合型基金里抽 800 只（已清盘的拿不到，结果偏乐观）。
做法：每年 6 月底、12 月底排一次队（2012–2024），按过去的指标分五组，看之后一年、三年的收益（相对同期全部样本的平均）。
"""
import json, os, glob
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
series = {}
for f in glob.glob(os.path.join(HERE, "fundnav_active", "*.json")):
    if os.path.basename(f).startswith("_"):
        continue
    x = json.load(open(f, encoding="utf-8"))
    if len(x["d"]) < 750:
        continue
    s = pd.Series(x["c"], index=pd.to_datetime(x["d"])); s = s[~s.index.duplicated()]
    series[x["code"]] = s.resample("ME").last()
M = pd.DataFrame(series).sort_index()
M = M.loc["2008-01-31":]
# 偏股：过去三年月波动年化 > 12% 的才算（去掉偏债混合）
ret = M.pct_change(fill_method=None)
vol36 = ret.rolling(36, min_periods=30).std() * np.sqrt(12)
z = np.load(os.path.join(HERE, "index_long", "sh000300.npz")); hs = pd.Series(z["c"], index=pd.to_datetime(z["d"].astype(str))).resample("ME").last().reindex(M.index).ffill()
hret = hs.pct_change()
print("funds", M.shape[1], "months", M.shape[0], M.index[0].date(), M.index[-1].date())


def past_ret(k):
    return M / M.shift(k) - 1


def fut_ret(k):
    return M.shift(-k) / M - 1


def max_dd(k):
    out = pd.DataFrame(np.nan, index=M.index, columns=M.columns)
    arr = M.to_numpy()
    for i in range(k, len(M)):
        w = arr[i - k:i + 1]
        peak = np.maximum.accumulate(w, axis=0)
        out.iloc[i] = np.nanmin(w / peak - 1, axis=0)
    return out


def capture_edge(k=36):
    out = pd.DataFrame(np.nan, index=M.index, columns=M.columns)
    r = ret.to_numpy(); h = hret.to_numpy()
    for i in range(k, len(M)):
        rr = r[i - k + 1:i + 1]; hh = h[i - k + 1:i + 1]
        up = hh > 0; dn = hh < 0
        if up.sum() < 6 or dn.sum() < 6:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            u = np.nansum(rr[up], axis=0) / hh[up].sum(); d = np.nansum(rr[dn], axis=0) / hh[dn].sum()
        ok = np.isfinite(rr).sum(axis=0) >= k - 2
        out.iloc[i] = np.where(ok, u - d, np.nan)
    return out


p12, p36, p60 = past_ret(12), past_ret(36), past_ret(60)
dd36 = max_dd(36)
metrics = {
    "过去 1 年收益": p12, "过去 3 年收益": p36, "过去 5 年收益": p60,
    "过去 3 年最大回撤（越小越好）": dd36, "过去 3 年收益/回撤": (p36 / dd36.abs()),
    "涨跌跟随（涨时跟上−跌时跟跌）": capture_edge(36),
    "过去 3 年波动（越低越好）": -vol36,
    "综合（3年40%+1年20%+收益回撤比40%）": None,
}
forms = [d for d in M.index if d.month in (6, 12) and d.year >= 2012 and d.year <= 2024]
OUT = {}
for hz, hn in ((12, "之后 1 年"), (36, "之后 3 年")):
    fr = fut_ret(hz)
    print(f"===== {hn} =====")
    for nm, X in metrics.items():
        acc = np.zeros(5); cnt = 0; top_beat = 0; top_vs_bot = 0; rank_acc = []; ic = []
        for d in forms:
            ok = (vol36.loc[d] > 0.12) & fr.loc[d].notna() & p36.loc[d].notna()
            if nm.startswith("综合"):
                r1 = p12.loc[d][ok].rank(pct=True); r3 = p36.loc[d][ok].rank(pct=True); rc = (p36 / dd36.abs()).loc[d][ok].rank(pct=True)
                x = 0.4 * r3 + 0.2 * r1 + 0.4 * rc
            else:
                x = X.loc[d][ok]
            x = x.dropna()
            if len(x) < 100:
                continue
            f = fr.loc[d][x.index]
            g = np.minimum((x.rank(pct=True) * 5).astype(int), 4)
            base = f.mean()
            v = np.array([f[g == k].mean() - base for k in range(5)])
            acc += v; cnt += 1
            top_beat += v[4] > 0; top_vs_bot += v[4] > v[0]
            fr_rank = f.rank(pct=True)
            rank_acc.append(fr_rank[g == 4].mean()); ic.append(np.corrcoef(x.rank(), f.rank())[0, 1])
        if cnt == 0:
            continue
        v = acc / cnt
        OUT[f"{nm}|{hn}"] = {"groups": v.tolist(), "n": cnt, "top_beat": int(top_beat), "top_vs_bot": int(top_vs_bot), "top_future_rank": float(np.mean(rank_acc)), "ic": float(np.mean(ic))}
        print(f"  {nm:<28} 五组超额（最差→最好）: " + " ".join(f"{a*100:+5.1f}" for a in v) + f" | 最好组跑赢平均 {top_beat}/{cnt} 次，跑赢最差组 {top_vs_bot}/{cnt} 次 | 最好组之后排在 {np.mean(rank_acc)*100:.0f}% 分位 | 秩相关 {np.mean(ic):+.2f}")
# 样本本身：之后一年、三年的平均收益和赚钱比例
for hz, hn in ((12, "一年"), (36, "三年")):
    fr = fut_ret(hz); vals = []
    for d in forms:
        ok = (vol36.loc[d] > 0.12) & fr.loc[d].notna()
        vals.append((d.date(), int(ok.sum()), float(fr.loc[d][ok].mean()), float((fr.loc[d][ok] > 0).mean()), float(hs.shift(-hz).loc[d] / hs.loc[d] - 1) if d in hs.index and pd.notna(hs.shift(-hz).loc[d]) else np.nan))
    print(f"--- 样本基金拿{hn}：" + " ".join(f"{str(a)[:7]}:{c*100:+.0f}%(沪深300 {e*100:+.0f}%)" for a, b, c, dd, e in vals))
    OUT[f"sample|{hn}"] = {"mean": float(np.mean([c for _, _, c, _, _ in vals])), "win": float(np.mean([dd for _, _, _, dd, _ in vals])), "hs300": float(np.nanmean([e for *_, e in vals]))}
json.dump(OUT, open("exp53_fund_persist.json", "w"), ensure_ascii=False, indent=1)
