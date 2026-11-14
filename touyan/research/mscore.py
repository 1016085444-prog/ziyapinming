"""大盘预估分（研究版）。输入 mkt_{which}.npz 里的序列，输出每天的分数和各项是否触发。"""
import numpy as np
def components(d):
    mr = d["mr"]
    lvl = np.cumprod(1 + np.nan_to_num(mr))
    def mret(k): return lvl / np.concatenate([np.full(k, np.nan), lvl[:-k]]) - 1
    m5 = mret(5)
    rev_n = np.concatenate([d["rev"][1:], [0]]); pos_n = np.concatenate([d["pos"][1:], [0]])
    return {
        "vol_up": (d["amt_rel"] >= 1.15, 1), "vol_dn": (d["amt_rel"] <= 0.85, -1),
        "big_up": (mr >= 0.015, 1), "big_dn": (mr <= -0.015, 1), "flat": (np.abs(mr) < 0.005, -1),
        "dn_many": (d["dnshare"] >= 0.02, 2), "up_many": (d["upshare"] >= 0.02, 1),
        "drop5": (m5 <= -0.04, 1), "month": ((rev_n == 1) | (pos_n == 1), 1),
        "mon": (d["wd_next"] == 0, 1), "thu": (d["wd_next"] == 3, -1),
    }
def score(d):
    s = np.zeros(len(d["mr"]), int)
    for k, (m, w) in components(d).items():
        s += w * np.where(m, 1, 0)
    return s
