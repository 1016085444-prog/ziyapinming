"""研究用：用不复权价 + 除权除息记录，还原每只股票真实的日涨跌幅（等比复权）。

腾讯的前复权是「减法」复权：除权日之前的价格统一减去每股分红。分红累计多了以后，早年的价格被减得很低，
算出来的涨跌幅会被放大好几倍。这里改成「等比」复权：除权日之前的价格统一乘一个系数，涨跌幅不变。

除权日的参考价有两个来源，互相印证：
  A. 解析分红内容（10派x元、10送x股、10转x股）：参考价 = (前收盘 − 每股派息) / (1 + 每股送转)
  B. 用腾讯前复权价反推：除权日之后那一段里，不复权价 p 和前复权价 q 是一条直线 p = α·q + β，
     参考价 = α·q(除权前一天) + β。配股之类没有文字内容的只能靠 B。
"""
import json, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PAT_CASH = re.compile(r"10派([\d.]+)元")
PAT_SONG = re.compile(r"10送([\d.]+)股")
PAT_ZHUAN = re.compile(r"10转(?:增)?([\d.]+)股")


def parse_content(txt):
    """返回 (每股派息, 每股送转)；解析不了返回 None。"""
    if not txt:
        return None
    cash = sum(float(x) for x in PAT_CASH.findall(txt)) / 10
    bonus = (sum(float(x) for x in PAT_SONG.findall(txt)) + sum(float(x) for x in PAT_ZHUAN.findall(txt))) / 10
    if cash == 0 and bonus == 0:
        return None
    return cash, bonus


def load(code):
    raw = np.load(os.path.join(HERE, "raw", code + ".npz"))
    qf = np.load(os.path.join(HERE, "data", code + ".npz"))
    ev = json.load(open(os.path.join(HERE, "events", code + ".json"), encoding="utf-8"))
    return raw, qf, ev


def factors(code, verbose=False):
    """返回 dict：d（日期）、F（等比复权系数，最后一天为 1）、诊断信息。"""
    raw, qf, ev = load(code)
    d = raw["d"]
    p = raw["c"].astype(np.float64)
    n = len(d)
    # 前复权收盘对齐到不复权的日期
    q = np.full(n, np.nan)
    pos = np.searchsorted(d, qf["d"])
    ok = pos < n
    ok[ok] &= d[pos[ok]] == qf["d"][ok]
    q[pos[ok]] = qf["c"][ok].astype(np.float64)
    ev_idx = {}
    for ds, info in ev.items():
        di = int(ds.replace("-", ""))
        k = int(np.searchsorted(d, di))
        if k < n and d[k] == di:
            ev_idx[k] = info
    cuts = sorted(k for k in ev_idx if k > 0)
    bounds = [0] + cuts + [n]
    F = np.ones(n)
    diag = {"events": len(cuts), "parsed": 0, "fit": 0, "both": 0, "disagree": 0, "nofix": 0, "max_resid": 0.0, "notes": []}
    # 从后往前：每个除权日算参考价
    for si in range(len(bounds) - 2, 0, -1):
        t, e = bounds[si], bounds[si + 1]          # 这一段是 [t, e)，t 是除权日
        seg_p, seg_q = p[t:e], q[t:e]
        m = np.isfinite(seg_q) & np.isfinite(seg_p)
        ref_fit = None
        if m.sum() >= 3 and np.ptp(seg_q[m]) > 0.02 and np.isfinite(q[t - 1]):
            a, b = np.polyfit(seg_q[m], seg_p[m], 1)
            if abs(a - 1) < 0.004:
                a = 1.0
                b = float(np.mean(seg_p[m] - seg_q[m]))
            resid = np.abs(seg_p[m] - (a * seg_q[m] + b)) / seg_p[m]
            diag["max_resid"] = max(diag["max_resid"], float(resid.max()))
            if resid.max() < 0.012:
                ref_fit = a * q[t - 1] + b
        ref_par = None
        pc = parse_content(ev_idx[t].get("FHcontent", ""))
        if pc:
            cash, bonus = pc
            ref_par = (p[t - 1] - cash) / (1 + bonus)
        if ref_par is not None:
            diag["parsed"] += 1
        if ref_fit is not None:
            diag["fit"] += 1
        if ref_par is not None and ref_fit is not None:
            diag["both"] += 1
            if abs(ref_par / ref_fit - 1) > 0.006:
                diag["disagree"] += 1
                diag["notes"].append((int(d[t]), ev_idx[t].get("FHcontent", ""), round(ref_par, 3), round(float(ref_fit), 3), round(p[t - 1], 3)))
        ref = ref_fit if ref_fit is not None else ref_par      # 两者不一致时以反推为准（文字内容偶尔漏记送转）
        if ref is None or not (0.05 * p[t - 1] < ref <= 1.02 * p[t - 1]):
            diag["nofix"] += 1
            diag["notes"].append((int(d[t]), "NOFIX", ev_idx[t].get("FHcontent", ""), None if ref is None else round(float(ref), 3), round(p[t - 1], 3)))
            continue
        F[:t] *= ref / p[t - 1]
    if verbose:
        print(code, diag)
    return {"d": d, "F": F, "diag": diag}


if __name__ == "__main__":
    for code in sys.argv[1:]:
        out = factors(code, verbose=True)
        raw, qf, ev = load(code)
        p = raw["c"].astype(np.float64)
        adj = p * out["F"]
        print("  first", out["d"][0], "raw", round(p[0], 2), "adj", round(adj[0], 3), "F", round(out["F"][0], 4), "| last", out["d"][-1], round(p[-1], 2))
        r = adj[1:] / adj[:-1] - 1
        k = int(np.argmax(np.abs(r)))
        print("  max |ret|", round(float(np.abs(r).max()), 4), "on", out["d"][k + 1], " total", round(adj[-1] / adj[0] - 1, 3))
