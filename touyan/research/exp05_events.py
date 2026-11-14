"""实验 5：业绩公告之后的漂移。信号在公告后第一个交易日（t0）收盘确认，t0+1 开盘买入。"""
from feat import *
import numpy as np, pandas as pd
rep = pd.read_pickle("rep.pkl"); pre = pd.read_pickle("pre.pkl")
rep = rep[rep["live"]].copy()
U = UALL
mR = np.nanmean(np.where(U, R, np.nan), axis=1)          # 当日全市场平均涨跌
mOV = np.nanmean(np.where(U, OV, np.nan), axis=1)
HS = (2, 6, 11, 21, 41, 61)
FW = {h: fwd(h) for h in HS}
BS = {h: base_of(FW[h], U) for h in HS}

def attach(df):
    t0 = df["t0"].to_numpy(); i = df["i"].to_numpy()
    ok = (t0 >= 1) & (t0 < T - 1)
    df = df[ok].copy(); t0 = t0[ok]; i = i[ok]
    df["inU"] = U[t0 - 1, i] & valid[t0, i]
    df["ar0"] = R[t0, i] - mR[t0]                          # 公告日（第一个可反应的交易日）的超额
    df["ar_1"] = R[t0 - 1, i] - mR[t0 - 1]
    df["gap0"] = OV[t0, i] - mOV[t0]
    df["id0"] = ID[t0, i]
    df["pre20"] = (Cf[t0 - 1, i] / Cf[np.maximum(t0 - 21, 0), i] - 1)
    df["mv"] = FMV[t0 - 1, i]
    df["turn0"] = TR[t0, i] / roll_turn60[t0 - 1, i]
    for h in HS:
        df[f"f{h}"] = FW[h][t0, i]
        df[f"x{h}"] = FW[h][t0, i] - BS[h][t0]
    df["year"] = cal[t0] // 10000
    return df[df["inU"]]

roll_turn60 = roll_mean(TR, 60)
rep = attach(rep)
rep["surp"] = (rep["sq"] - rep["sq_ly"]) / rep["mv"]         # 单季利润同比增量 / 流通市值
print("财报事件数（在池内）:", len(rep))

def table(df, col, bins, labels=None, hs=(6, 21, 61), title=""):
    print(f"--- {title} ---")
    cut = pd.cut(df[col], bins)
    g = df.groupby(cut, observed=True)
    out = g.agg(n=("x6", "size"), ar_1=("ar_1", "mean"), ar0=("ar0", "mean"),
                **{f"x{h}": (f"x{h}", "mean") for h in hs}, **{f"f{h}": (f"f{h}", "mean") for h in hs},
                **{f"w{h}": (f"f{h}", lambda s: (s > 0).mean()) for h in hs})
    with pd.option_context("display.width", 250, "display.float_format", lambda v: f"{v*100:+.2f}" if abs(v) < 5 else f"{v:.0f}"):
        print(out.to_string())

table(rep, "sq_yoy", [-1e9, -1, -0.5, -0.2, 0, 0.1, 0.2, 0.3, 0.5, 1, 2, 1e9], title="财报：单季净利润同比（分组） → 公告日反应、之后的超额(x)和原始收益(f)、胜率(w)")
table(rep, "surp", [-1e9, -0.02, -0.01, -0.004, -0.001, 0, 0.001, 0.004, 0.01, 0.02, 1e9], title="财报：单季利润增量/流通市值")
table(rep, "ar0", [-1, -0.05, -0.03, -0.015, -0.005, 0.005, 0.015, 0.03, 0.05, 0.08, 1], title="财报：公告日相对大盘的涨跌")
table(rep, "gap0", [-1, -0.03, -0.015, -0.005, 0.005, 0.015, 0.03, 0.05, 1], title="财报：公告日相对大盘的跳空")

# 组合：增长好 + 公告日反应好
good = rep[(rep["sq_yoy"] > 0.3) & (rep["surp"] > 0.002)]
table(good, "ar0", [-1, -0.03, -0.01, 0.01, 0.03, 0.05, 0.08, 1], title="财报：单季同比>30% 且 增量/市值>0.2% 的，再按公告日反应分")
def by_year(df, label, hs=(21, 61)):
    g = df.groupby("year").agg(n=("x21", "size"), **{f"x{h}": (f"x{h}", "mean") for h in hs}, **{f"f{h}": (f"f{h}", "mean") for h in hs},
                               **{f"w{h}": (f"f{h}", lambda s: (s > 0).mean()) for h in hs})
    print(f"--- 按年：{label} ---")
    with pd.option_context("display.width", 250, "display.float_format", lambda v: f"{v*100:+.2f}" if abs(v) < 5 else f"{v:.0f}"):
        print(g.to_string())
sel = rep[(rep["sq_yoy"] > 0.3) & (rep["surp"] > 0.002) & (rep["ar0"] > 0.02)]
by_year(sel, "单季同比>30%、增量/市值>0.2%、公告日超额>2%")
sel2 = rep[(rep["surp"] > 0.004)]
by_year(sel2, "增量/市值>0.4%")

# ---------- 业绩预告 ----------
p = pre[(pre["fcode"] == "004") & (pre["t0"] >= 0)].copy()
p["g_mid"] = (p["g_lo"] + p["g_hi"]) / 2 / 100
p = p.sort_values(["i", "per", "nd"]).drop_duplicates(["i", "per"], keep="first")      # 每个报告期只取第一次预告
p = attach(p)
p["surp"] = ((p["lo"] + p["hi"]) / 2 - p["ly"]) / p["mv"]          # 预告利润中值相对去年同期的增量 / 流通市值（累计口径）
print("业绩预告事件数（在池内，归母净利润口径，首次）:", len(p))
table(p, "g_mid", [-1e9, -1, -0.5, -0.2, 0, 0.2, 0.5, 1, 2, 1e9], title="预告：净利润同比中值")
table(p, "surp", [-1e9, -0.02, -0.01, -0.004, 0, 0.004, 0.01, 0.02, 0.04, 1e9], title="预告：利润增量/流通市值")
table(p, "ar0", [-1, -0.05, -0.03, -0.015, -0.005, 0.005, 0.015, 0.03, 0.05, 0.08, 1], title="预告：公告日相对大盘的涨跌")
g = p.groupby("ptype").agg(n=("x6", "size"), ar0=("ar0", "mean"), x6=("x6", "mean"), x21=("x21", "mean"), x61=("x61", "mean"), f61=("f61", "mean"))
with pd.option_context("display.width", 250, "display.float_format", lambda v: f"{v*100:+.2f}" if abs(v) < 5 else f"{v:.0f}"):
    print(g.to_string())
sel = p[(p["g_mid"] > 0.5) & (p["surp"] > 0.004) & (p["ar0"] > 0.02)]
by_year(sel, "预告：同比>50%、增量/市值>0.4%、公告日超额>2%")
rep.to_pickle("rep_ev.pkl"); p.to_pickle("pre_ev.pkl")
