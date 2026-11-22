"""把研究结果（results/*.json）里软件要用的数字整理成 daily/evidence_data.py。数字只从这里生成，不手抄。

用法：python gen_evidence.py > ../touyan/daily/evidence_data.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results") if os.path.isdir(os.path.join(HERE, "results")) and os.path.exists(os.path.join(HERE, "results", "ship3_new.json")) else HERE
J = lambda name: json.load(open(os.path.join(R, name), encoding="utf-8"))
S = {"new": J("ship3_new.json"), "old": J("ship3_old.json")}
S4 = {"new": J("ship4_new.json"), "old": J("ship4_old.json")}         # 第二轮：短期分档、中期新方法（实验 67）


def rnd(x, nd=4):
    if isinstance(x, float):
        return None if x != x else round(x, nd)
    if isinstance(x, dict):
        return {(int(k) if isinstance(k, str) and k.lstrip("-").isdigit() else k): rnd(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v, nd) for v in x]
    return x


def trade(x):
    """一组交易的统计：只留页面上要用的。"""
    keys = ("n", "mean", "median", "win", "avg_win", "avg_loss", "days", "p5", "basket_mean", "basket_win", "basket_worst", "base", "excess")
    out = {k: x[k] for k in keys if k in x}
    out["bad_years"] = sorted(int(y) for y, v in x["by_year"].items() if v < 0)
    return rnd(out)


def both(path, fn=trade, src=None):
    src = src or S

    def get(d):
        for p in path:
            if p not in d or d[p] is None:
                return None
            d = d[p]
        return fn(d)
    return {w: get(src[w]) for w in ("new", "old")}


def both4(path, fn=trade):
    return both(path, fn, S4)


def ranks(x):
    """入选名次 1..10 之后的收益，按名次排成列表：[{rank, n, mean, win}, ...]。"""
    return [dict(rank=int(k), **rnd(v)) for k, v in sorted(x.items(), key=lambda kv: int(kv[0]))]


out = {}
out["POOL"] = {w: {"stocks": S[w]["pool"], "days": S[w]["days"], "period": S[w]["period"]} for w in S}
out["SCORE_TABLE_RAW"] = {w: rnd(S[w]["score_table"]) for w in S}
# ── 大盘预估分 ──
out["SCORE_BY_TEMP"] = {w: rnd(S[w]["score_by_temp"]) for w in S}
# ── 短期 ──
sh = {
    # 现在的规则（实验 67）：强 = 分数 ≥4 且温度 <60，或分数 ≥3 且温度 <40；一般 = 分数 3、温度 40–60；
    # 轻仓 = 分数 ≥3、温度 60–80，或分数 2、温度 <60；go = 强 + 一般（满仓的两档）；act = 三档都算
    "go": both4(("short", "go")), "strong": both4(("short", "strong")), "normal": both4(("short", "normal")), "light": both4(("short", "light")),
    "act": both4(("short", "act")), "skip_s2_hot": both4(("short", "skip_s2_hot")), "skip_hot80": both4(("short", "skip_hot80")),
    "days_per_year": {k: {w: round(S4[w]["short"][k]["per_year"], 1) for w in S4} for k in ("strong", "normal", "light", "go")},
    "rank": {w: ranks(S4[w]["short"]["rank"]) for w in S4},
    # 上一版的规则（只看分数 ≥3，不分温度），留作对照
    "ge3": both(("short", "ge3")), "ge2": both(("short", "ge2")),
    "nostop": both(("short", "ge3_nostop")), "hold10": both(("short", "ge3_hold10")),
    "everyday": both(("short", "everyday")), "bad_days": both(("short", "le-1")),
    "by_year": {w: rnd(S4[w]["short"]["go"]["by_year"]) for w in S4},
    "by_year_win": {w: rnd(S4[w]["short"]["go"]["by_year_win"]) for w in S4},
    "by_year_n": {w: rnd(S4[w]["short"]["go"]["by_year_n"]) for w in S4},
    "hist": {w: S4[w]["short"]["go"]["hist"] for w in S4},
    "by_temp": {k: both(("short", f"temp_{k}")) for k in ("lt40", "40to60", "60to80", "ge60", "ge80", "lt80", "lt60")},
}
out["SHORT"] = sh
# ── 中期 ──
_exit = lambda e: {"limit_or_hot": int(e.get("3", 0)), "expire": int(e.get("0", 0))}
md = {
    # 现在的方法（实验 67）：冷热分 ≥85 的中小盘、在赚钱，按超预期等五项排序；温度 <40 随时买，40–80 只在大盘分 ≥2 的日子买
    "all": both4(("mid", "new")), "every_day": both4(("mid", "new_all")), "stop12": both4(("mid", "stop12")),
    "prev": both4(("mid", "old_all")), "prev_policy": both4(("mid", "old_policy")),
    "tiers": {k: both4(("mid", "tiers", k)) for k in ("best", "good", "ok", "wait", "avoid")},
    "by_temp": {k: both4(("mid", "by_temp", k)) for k in ("lt20", "20to40", "lt40", "40to60", "60to80", "40to80", "ge80")},
    "rank": {w: ranks(S4[w]["mid"]["rank"]) for w in S4},
    "picked": {w: rnd(S4[w]["mid"]["picked"]) for w in S4},
    "old_plan": both(("mid", "old60")), "stop20": both(("mid", "stop20")),
    "by_score": {k: both(("mid", f"score_{k}")) for k in ("ge2", "0to1", "le-1")},
    "by_year": {w: rnd(S4[w]["mid"]["new"]["by_year"]) for w in S4},
    "by_year_win": {w: rnd(S4[w]["mid"]["new"]["by_year_win"]) for w in S4},
    "by_year_base": {w: rnd(S4[w]["mid"]["new"]["by_year_base"]) for w in S4},
    "hist": {w: S4[w]["mid"]["new"]["hist"] for w in S4},
    "exit_reasons": {w: _exit(S4[w]["mid"]["new"]["exit"]) for w in S4},
    "candidates": {w: round(S4[w]["mid"]["candidates"]) for w in S4},
    "cold": {k: {w: rnd({a: b for a, b in S[w]["cold"][k].items() if a != "by_year"}) for w in S} for k in ("hot10_h20", "hot10_h60", "hot20_h120", "cold10_h60", "cand_h20", "cand_h60", "cand_h120")},
    "hot_by_year": {w: rnd(S[w]["cold"]["hot10_h60"]["by_year"]) for w in S},
}
out["MID"] = md
# ── 长期 ──
lg = {"steady_n": {w: S[w]["long"]["steady_n"] for w in S}, "hot_share": {w: round(S[w]["long"]["hot_share"], 3) for w in S}}
for hn in ("1y", "2y", "3y"):
    for nm in ("steady", "all", "hot"):
        lg[f"{nm}_{hn}"] = {w: rnd(S[w]["long"].get(f"{nm}_{hn}")) for w in S}
for nm in ("steady", "all", "hot"):
    lg[f"{nm}_cagr"] = {w: round(S[w]["long"][f"{nm}_cagr"], 4) for w in S}
    lg[f"{nm}_by_year"] = {w: rnd(S[w]["long"][f"{nm}_by_year"]) for w in S}
out["LONG"] = lg
# ── 市场温度 ──
t = J("exp42_temperature.json"); name = "两者平均(近10年)"
tot = sum(t[f"{name}|一年|中证全指|{lo}"]["n"] for lo in (0, 20, 40, 60, 80))
zones = []
for lo, hi, label in ((0, 20, "很冷"), (20, 40, "偏冷"), (40, 60, "不冷不热"), (60, 80, "偏热"), (80, 100, "很热")):
    row = {"lo": lo, "hi": hi, "label": label, "share": round(t[f"{name}|一年|中证全指|{lo}"]["n"] / tot, 3)}
    for g, gk in (("中证全指", "index"), ("沪深300", "hs300"), ("全池等权", "pool")):
        for hn, hk in (("一年", "y1"), ("两年", "y2"), ("三年", "y3")):
            x = t[f"{name}|{hn}|{g}|{lo}"]
            row[f"{gk}_{hk}"] = [round(x["mean"], 4), round(x["win"], 3), round(x["worst"], 3)]
    zones.append(row)
st = J("exp44_strategy.json")
strat = {}
for an, ak in (("中证全指(指数)", "index"), ("沪深300(指数)", "hs300"), ("稳健", "steady"), ("全池等权", "pool"), ("红利低波", "divlow")):
    strat[ak] = {}
    for rn, rk in (("一直拿着", "hold"), ("低于40买、高于80卖", "rule"), ("低于30买、高于70卖", "rule3070"), ("低于50买、高于80卖", "rule5080")):
        v = st[f"{an}|{rn}"]
        strat[ak][rk] = rnd({k: v[k] for k in ("cagr", "mdd", "neg_years", "years", "worst_year", "roll3_win", "in_mkt", "trades")})
        if rk in ("hold", "rule"):
            strat[ak][rk]["by_year"] = rnd(v["by_year"], 3)
out["TEMP"] = {"zones": zones, "strategy": strat}
# ── 定投 ──
f47 = J("exp47_dca_funds.json"); w48 = J("exp48_dca_windows.json")
names47 = {"160706": "嘉实沪深300ETF联接A", "110020": "易方达沪深300ETF联接A", "160119": "南方中证500ETF联接A", "161022": "富国创业板指数A", "090010": "大成中证红利指数A",
           "100032": "富国中证红利指数增强A", "005561": "创金合信红利低波A", "110003": "易方达上证50增强A", "161017": "富国中证500指数增强", "270042": "广发纳指100ETF联接A",
           "050025": "博时标普500ETF联接A", "000071": "华夏恒生ETF联接A"}
dca = {"funds": {}, "windows": {}}
for code, nm in names47.items():
    rows = {k.split("|", 1)[1]: rnd({a: b for a, b in v.items() if a in ("multiple", "irr", "worst", "sells", "months")}) for k, v in f47.items() if k.startswith(code + "|") and not k.endswith("|cmp")}
    dca["funds"][code] = {"name": nm, "rules": rows}
for k, v in w48.items():
    dca["windows"][k] = rnd(v)
out["DCA"] = dca
# ── 主动基金 ──
out["FUND"] = rnd(J("exp53_fund_persist.json"))
# ── 行业 ──
i54 = J("exp54_industry.json"); i55 = J("exp55_industry_more.json"); i56 = {"new": J("exp56_new.json"), "old": J("exp56_old.json")}
ind = {"under": {k: rnd(v) for k, v in i54.items() if k.startswith("under")},
       "groups": {k: rnd({a: b for a, b in v.items() if a in ("ex", "low_beat", "high_beat", "years")}) for k, v in i54.items() if "|" in k and not k.startswith(("under", "split"))},
       "cond": {k[5:]: rnd(v) for k, v in i55.items() if k.startswith("cond|")},
       "grid": {k[5:]: rnd(v) for k, v in i55.items() if k.startswith("grid|")},
       "filter": {w: {k: rnd({a: b for a, b in v.items() if a in ("ret", "ex", "win", "beat_years", "years", "n", "mean", "median")}) for k, v in i56[w].items() if k.startswith("long|")} for w in i56}}
out["INDUSTRY"] = ind

print('"""方法检验的原始数字。由 research/gen_evidence.py 从 research/results/*.json 生成，不要手改。\n\n所有收益都是小数（0.0286 = 2.86%）。new = 2016.8–2026.11，old = 2005–2016.7。\n"""\n')
for k, v in out.items():
    text = json.dumps(v, ensure_ascii=False, separators=(", ", ": "))
    text = text.replace("null", "None").replace("true", "True").replace("false", "False")
    # JSON 的键都是字符串；年份这类整数键还原回整数
    import re
    text = re.sub(r'"(-?\d{4})": ', r"\1: ", text)
    print(f"{k} = {text}\n")
