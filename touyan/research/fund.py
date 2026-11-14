"""研究用：把业绩报表、业绩预告整理成「事件表」，对齐到交易日历。
公告日 D 的含义：公告的刊登日（晚上发的公告记在第二天）。市场第一次能反应的交易日 t0 = 第一个 >= D 的交易日。
"""
import glob, json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def build(cal, codes):
    col = {c: j for j, c in enumerate(codes)}
    # ---------- 业绩报表 ----------
    recs = []
    industry = {}
    for f in sorted(glob.glob(os.path.join(HERE, "fin", "yjbb_*.json"))):
        per = int(os.path.basename(f)[5:15].replace("-", ""))
        for r in json.load(open(f, encoding="utf-8")):
            code = r["SECURITY_CODE"]
            if code not in col or not r.get("NOTICE_DATE"):
                continue
            if r.get("PUBLISHNAME"):
                industry[code] = r["PUBLISHNAME"]
            recs.append((col[code], per, int(r["NOTICE_DATE"][:10].replace("-", "")),
                         r.get("PARENT_NETPROFIT"), r.get("SJLTZ"), r.get("YSTZ"), r.get("TOTAL_OPERATE_INCOME"),
                         r.get("WEIGHTAVG_ROE"), r.get("BASIC_EPS"), r.get("DEDUCT_BASIC_EPS"), r.get("MGJYXJJE"), r.get("XSMLL"), r.get("BPS")))
    rep = pd.DataFrame(recs, columns=["i", "per", "nd", "np_ytd", "np_yoy", "rev_yoy", "rev_ytd", "roe", "eps", "deps", "cfps", "gm", "bps"])
    for c in ("np_ytd", "np_yoy", "rev_yoy", "rev_ytd", "roe", "eps", "deps", "cfps", "gm", "bps"):
        rep[c] = pd.to_numeric(rep[c], errors="coerce")
    rep = rep.drop_duplicates(["i", "per"], keep="last").sort_values(["i", "per"]).reset_index(drop=True)
    # 单季利润、单季营收
    key = rep.set_index(["i", "per"])
    def prev_per(per):
        y, md = per // 10000, per % 10000
        return {331: None, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}[md]
    idx_map = {(i, p): k for k, (i, p) in enumerate(zip(rep["i"].to_numpy(), rep["per"].to_numpy()))}
    npy = rep["np_ytd"].to_numpy(); rvy = rep["rev_ytd"].to_numpy()
    sq = np.full(len(rep), np.nan); sqr = np.full(len(rep), np.nan)
    ii = rep["i"].to_numpy(); pp = rep["per"].to_numpy()
    for k in range(len(rep)):
        pv = prev_per(int(pp[k]))
        if pv is None:
            sq[k] = npy[k]; sqr[k] = rvy[k]
        else:
            j = idx_map.get((int(ii[k]), pv))
            if j is not None:
                sq[k] = npy[k] - npy[j]; sqr[k] = rvy[k] - rvy[j]
    rep["sq"] = sq; rep["sqr"] = sqr
    # 去年同期的单季
    sq_ly = np.full(len(rep), np.nan); sqr_ly = np.full(len(rep), np.nan); sq_prev = np.full(len(rep), np.nan)
    for k in range(len(rep)):
        j = idx_map.get((int(ii[k]), int(pp[k]) - 10000))
        if j is not None:
            sq_ly[k] = sq[j]; sqr_ly[k] = sqr[j]
    rep["sq_ly"] = sq_ly; rep["sqr_ly"] = sqr_ly
    with np.errstate(invalid="ignore", divide="ignore"):
        rep["sq_yoy"] = np.where(np.abs(sq_ly) > 0, (sq - sq_ly) / np.abs(sq_ly), np.nan)
        rep["sqr_yoy"] = np.where(sqr_ly > 0, (sqr - sqr_ly) / sqr_ly, np.nan)
    # 对齐到交易日
    t0 = np.searchsorted(cal, rep["nd"].to_numpy())
    rep["t0"] = np.where(t0 < len(cal), t0, -1)
    # 报告期结束到公告的天数太长的（上市前补披露的历史报告）不算事件
    per_dt = pd.to_datetime(rep["per"].astype(str), format="%Y%m%d")
    nd_dt = pd.to_datetime(rep["nd"].astype(str), format="%Y%m%d")
    rep["lag"] = (nd_dt - per_dt).dt.days
    rep["live"] = (rep["lag"] >= 0) & (rep["lag"] <= 150) & (rep["t0"] >= 0)

    # ---------- 业绩预告 ----------
    recs = []
    for f in sorted(glob.glob(os.path.join(HERE, "fin", "yjyg_*.json"))):
        per = int(os.path.basename(f)[5:15].replace("-", ""))
        for r in json.load(open(f, encoding="utf-8")):
            code = r["SECURITY_CODE"]
            if code not in col or not r.get("NOTICE_DATE"):
                continue
            recs.append((col[code], per, int(r["NOTICE_DATE"][:10].replace("-", "")), r.get("PREDICT_FINANCE_CODE"), r.get("PREDICT_FINANCE"),
                         r.get("PREDICT_AMT_LOWER"), r.get("PREDICT_AMT_UPPER"), r.get("ADD_AMP_LOWER"), r.get("ADD_AMP_UPPER"),
                         r.get("PREDICT_TYPE"), r.get("PREYEAR_SAME_PERIOD")))
    pre = pd.DataFrame(recs, columns=["i", "per", "nd", "fcode", "fname", "lo", "hi", "g_lo", "g_hi", "ptype", "ly"])
    for c in ("lo", "hi", "g_lo", "g_hi", "ly"):
        pre[c] = pd.to_numeric(pre[c], errors="coerce")
    pre = pre.drop_duplicates(["i", "per", "nd", "fcode"]).reset_index(drop=True)
    t0 = np.searchsorted(cal, pre["nd"].to_numpy())
    pre["t0"] = np.where(t0 < len(cal), t0, -1)
    per_dt = pd.to_datetime(pre["per"].astype(str), format="%Y%m%d")
    nd_dt = pd.to_datetime(pre["nd"].astype(str), format="%Y%m%d")
    pre["lag"] = (nd_dt - per_dt).dt.days
    return rep, pre, industry


if __name__ == "__main__":
    PANEL = os.environ.get("LAB_PANEL", "panel2"); TAG = "" if PANEL == "panel2" else "_old"
    cal = np.load(os.path.join(HERE, PANEL, "cal.npy"))
    codes = json.load(open(os.path.join(HERE, PANEL, "codes.json")))
    rep, pre, industry = build(cal, codes)
    print(len(rep), "reports;", int(rep["live"].sum()), "live;", len(pre), "pre-announcements;", len(industry), "industries for stocks,", len(set(industry.values())), "distinct")
    print(rep[rep["i"] == codes.index("600519")].tail(3).to_string())
    print(rep["lag"].describe())
    pass
    print(pre["fname"].value_counts().head(8))
    rep.to_pickle(os.path.join(HERE, f"rep{TAG}.pkl")); pre.to_pickle(os.path.join(HERE, f"pre{TAG}.pkl"))
    json.dump(industry, open(os.path.join(HERE, f"industry{TAG}.json"), "w", encoding="utf-8"), ensure_ascii=False)
