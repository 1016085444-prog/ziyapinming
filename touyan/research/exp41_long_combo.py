"""实验 41：长期的组合规则——红利低波、便宜的好公司、冷门价值、只做回避……各拿一年、两年，分年度看。"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

COLDR = np.load(f"cold{TAG}.npy")
cold = pct_rank(COLDR, U)
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r3r = pct_rank(F("r750"), U)
epr = pct_rank(EP, U); bpr = pct_rank(BP, U); dyr = pct_rank(np.where(DY > 0, DY, np.nan), U); szr = pct_rank(F("size"), U)
r3r = np.where(np.isfinite(r3r), r3r, 0.5)
profit = NPTTM > 0
BIG = U & (rk_mv <= 800)
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])


def topn(mask, key, n, cap=None):
    """每个建仓日在 mask 里按 key 从大到小取前 n 只（cap：同一行业最多几只）。"""
    P = np.zeros((T, N), bool)
    for t in form_days(245):
        idx = np.nonzero(mask[t] & np.isfinite(key[t]))[0]
        if len(idx) == 0:
            continue
        order = idx[np.argsort(-key[t, idx])]
        if cap is None:
            P[t, order[:n]] = True
            continue
        used = {}; k = 0
        for j in order:
            g = ind_of[j]
            if used.get(g, 0) >= cap:
                continue
            used[g] = used.get(g, 0) + 1; P[t, j] = True; k += 1
            if k >= n:
                break
    return P


hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r3r >= 0.8)          # 四种「热」：波动最大、换手最高、被追捧、三年涨得最多
calm = U & ~hot
rules = {
    "全池": U,
    "只做回避（去掉四种热的）": calm,
    "被回避掉的那些": U & hot,
    "分红的（近一年有现金分红）": U & (DY > 0),
    "连续三年分红": U & DIV3Y,
    "股息率前 20%": U & (dyr >= 0.8),
    "红利低波：股息率前30% + 波动后一半": U & (dyr >= 0.7) & (volr < 0.5),
    "红利低波 + 连续三年分红 + 赚钱": U & (dyr >= 0.7) & (volr < 0.5) & DIV3Y & profit,
    "便宜的好公司：三年ROE≥10 + EP前40%": U & (ROE_MIN3 >= 10) & (epr >= 0.6),
    "便宜的好公司 + 不热": calm & (ROE_MIN3 >= 10) & (epr >= 0.6),
    "稳健：赚钱+分红+不热+ROE三年≥8": calm & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "稳健 + 股息率前一半": calm & profit & (dyr >= 0.5) & (ROE_MIN3 >= 8),
    "稳健 + 便宜(BP或EP前一半)": calm & profit & (DY > 0) & (ROE_MIN3 >= 8) & ((bpr >= 0.5) | (epr >= 0.5)),
    "冷门价值：最冷三成 + BP前一半 + 赚钱": U & (cold >= 0.7) & (bpr >= 0.5) & profit,
    "三年跌得最多的两成 + 赚钱 + 分红": U & (r3r < 0.2) & profit & (DY > 0),
    "大市值(前800) 股息率前 20%": BIG & (pct_rank(np.where(DY > 0, DY, np.nan), BIG) >= 0.8),
    "大市值(前800) 稳健": BIG & ~hot & profit & (DY > 0) & (ROE_MIN3 >= 8),
    "高 ROE（三年最低≥15）": U & (ROE_MIN3 >= 15),
    "高 ROE + 不贵（EP前一半）": U & (ROE_MIN3 >= 15) & (epr >= 0.5),
}
OUT = {}
for h in (245, 490):
    if T - h - 262 < 250:
        continue
    print(f"===== {which}：拿 {h} 个交易日 =====")
    for nm, m in rules.items():
        OUT[f"{nm}|{h}"] = show(nm, port(m, h), years=(h == 245))
# 排序取前 N 只：看篮子小的时候结果有多分散
score = np.where(calm & profit & (DY > 0) & (ROE_MIN3 >= 8), dyr + np.where(np.isfinite(epr), epr, 0) + np.where(np.isfinite(bpr), bpr, 0) + cold + (1 - volr), np.nan)
print(f"===== {which}：稳健池里按（股息率+EP+BP+冷+低波）排序取前 N 只，拿 245 天 =====")
for n, cap in ((100, None), (30, 3), (10, 2), (5, 2)):
    OUT[f"稳健前{n}|245"] = show(f"稳健 前 {n} 只" + (f"（同行业≤{cap}）" if cap else ""), port(topn(U, score, n, cap), 245))
score2 = np.where(U & (dyr >= 0.7) & (volr < 0.5) & DIV3Y & profit, dyr + (1 - volr), np.nan)
for n, cap in ((30, 3), (10, 2), (5, 2)):
    OUT[f"红利低波前{n}|245"] = show(f"红利低波 前 {n} 只（同行业≤{cap}）", port(topn(U, score2, n, cap), 245))
json.dump(OUT, open(f"exp41_{which}.json", "w"), ensure_ascii=False, indent=1)
