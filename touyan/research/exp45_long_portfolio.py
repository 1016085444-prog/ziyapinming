"""实验 45：长期的买卖规则——10 只股票的组合，多久检查一次、什么情况下换股，哪种做法好。

组合：从「稳健名单」（赚钱 + 分红 + 三年 ROE 不低于 8% + 不属于四种热）里按排序取 N 只，同行业最多 2 只，等权买入。
每隔 review 个交易日检查一次：触发卖出条件的卖掉，空出来的位置从名单里补。换股来回扣 0.2%。
"""
import os, sys
which = sys.argv[1]
os.environ["LAB_PANEL"] = "panel2" if which == "new" else "panel_old"
from longlab import *

z = np.load("temps.npz", allow_pickle=True)
names = list(z["names"]); tv = z[f"t{names.index('两者平均(近10年)')}"]
tmap = dict(zip(z["d"].tolist(), tv.tolist())); TEMP = np.array([tmap.get(int(x), np.nan) for x in cal])
COLDR = np.load(f"cold{TAG}.npy"); cold = pct_rank(COLDR, U)
volr = pct_rank(F("vol250"), U); turnr = pct_rank(F("turn250"), U); r3r = pct_rank(F("r750"), U); r3r = np.where(np.isfinite(r3r), r3r, 0.5)
dyr = pct_rank(np.where(DY > 0, DY, np.nan), U); epr = pct_rank(EP, U); roer = pct_rank(ROE_MIN3, U); szr = pct_rank(F("size"), U)
profit = NPTTM > 0
hot = (volr >= 0.8) | (turnr >= 0.8) | (cold < 0.2) | (r3r >= 0.8)
very_hot = (volr >= 0.9) | (turnr >= 0.9) | (cold < 0.1)
sound = profit & (DY > 0) & (ROE_MIN3 >= 8)
steady = U & ~hot & sound
ind = json.load(open(f"industry{TAG}.json", encoding="utf-8")) if os.path.exists(f"industry{TAG}.json") else json.load(open("industry.json", encoding="utf-8"))
ind_of = np.array([ind.get(c, "") for c in codes])
rng = np.random.default_rng(7)
noise = rng.random(N).astype(np.float32)
z0 = lambda x: np.where(np.isfinite(x), x, 0.0)
scores = {
    "股息率": np.where(steady, dyr, np.nan),
    "综合(股息+低波+ROE+便宜)": np.where(steady, z0(dyr) + (1 - z0(volr)) + z0(roer) + z0(epr), np.nan),
    "随机": np.where(steady, noise[None, :], np.nan),
    "低波": np.where(steady, 1 - volr, np.nan),
    "大市值": np.where(steady, szr, np.nan),
}
Rz = np.where(valid, R, 0.0)
START = 260


def simulate(score, n=10, review=63, exit_rule="leave", cap=2, cost=0.002, temp_rule=None):
    """exit_rule: none（一直拿）/ leave（不在稳健名单里就卖）/ hot（变热才卖）/ veryhot（很热才卖）/ bad（基本面变差才卖）/ hot_or_bad
    temp_rule=(lo, hi)：温度低于 lo 才建仓，高于 hi 清仓。"""
    hold = {}                      # j -> 权重（随价格漂移）
    cash = 1.0; eq = np.ones(T); trades = 0; invested = temp_rule is None; held_days = []
    since = {}
    for t in range(START, T - 1):
        # 当天收盘后检查
        total = cash + sum(hold.values())
        if temp_rule is not None and np.isfinite(TEMP[t]) and (t - START) % 5 == 0:
            if invested and TEMP[t] >= temp_rule[1]:
                invested = False
                for j in list(hold):
                    cash += hold.pop(j) * (1 - cost / 2); trades += 1; held_days.append(t - since.pop(j))
            elif not invested and TEMP[t] < temp_rule[0]:
                invested = True
        if invested and (t - START) % review == 0:
            for j in list(hold):
                out = False
                if exit_rule == "leave":
                    out = not steady[t, j]
                elif exit_rule == "hot":
                    out = bool(hot[t, j])
                elif exit_rule == "veryhot":
                    out = bool(very_hot[t, j])
                elif exit_rule == "bad":
                    out = not sound[t, j]
                elif exit_rule == "hot_or_bad":
                    out = bool(very_hot[t, j]) or not sound[t, j]
                if not valid[t, j] and not np.isfinite(Cf[t, j]):
                    out = True
                if out:
                    cash += hold.pop(j) * (1 - cost / 2); trades += 1; held_days.append(t - since.pop(j))
            need = n - len(hold)
            if need > 0:
                idx = np.nonzero(np.isfinite(score[t]))[0]
                order = idx[np.argsort(-score[t, idx])]
                used = {}
                for j in hold:
                    used[ind_of[j]] = used.get(ind_of[j], 0) + 1
                per = cash / need
                for j in order:
                    if need == 0:
                        break
                    if j in hold or used.get(ind_of[j], 0) >= cap:
                        continue
                    used[ind_of[j]] = used.get(ind_of[j], 0) + 1
                    hold[j] = per * (1 - cost / 2); cash -= per; need -= 1; since[j] = t
        # 下一天的收益
        for j in hold:
            hold[j] *= 1 + Rz[t + 1, j]
        cash *= 1 + 0.02 / 245 if not hold else 1.0
        eq[t + 1] = cash + sum(hold.values())
    r = eq[START + 1:] / eq[START:-1] - 1
    yrs = len(r) / 245; e = eq[START:] / eq[START]
    yy = cal[START + 1:] // 10000
    by = {int(y): float(np.prod(1 + r[yy == y]) - 1) for y in sorted(set(yy.tolist()))}
    return {"cagr": float(e[-1] ** (1 / yrs) - 1), "mdd": float((e / np.maximum.accumulate(e) - 1).min()), "by_year": by, "trades_per_year": trades / yrs,
            "avg_hold_days": float(np.mean(held_days)) if held_days else float("nan"), "neg_years": int(sum(1 for v in by.values() if v < 0)), "years": len(by)}


def line(label, s):
    print(f"  {label:<44} 年化 {s['cagr']*100:+5.1f}% 最大回撤 {s['mdd']*100:+4.0f}% 亏钱的年 {s['neg_years']}/{s['years']} 每年卖出 {s['trades_per_year']:4.1f} 次 平均拿 {s['avg_hold_days']:4.0f} 天 | " +
          " ".join(f"{y%100:02d}:{v*100:+.0f}" for y, v in s["by_year"].items()), flush=True)


base = np.cumprod(1 + np.nanmean(np.where(U & valid, R, np.nan), axis=1)[START + 1:])
print(f"===== {which}：{cal[START]}..{cal[-1]}；全池等权年化 {(base[-1] ** (245 / len(base)) - 1) * 100:+.1f}% =====")
OUT = {}
print("--- 排序方式（10 只，每季度检查，不在名单里就换）---")
for sn, sc in scores.items():
    OUT[f"rank|{sn}"] = simulate(sc); line(sn, OUT[f"rank|{sn}"])
sc = scores["综合(股息+低波+ROE+便宜)"]
print("--- 卖出规则（综合排序，10 只，每季度检查）---")
for er, en in (("none", "买了一直拿，不换"), ("leave", "不在稳健名单里就换"), ("hot", "变热（四种热之一）才换"), ("veryhot", "很热（前一成）才换"), ("bad", "基本面变差才换"), ("hot_or_bad", "很热或基本面变差才换")):
    OUT[f"exit|{er}"] = simulate(sc, exit_rule=er); line(en, OUT[f"exit|{er}"])
print("--- 多久检查一次（综合排序，10 只，很热或基本面变差才换）---")
for rv in (21, 63, 126, 245):
    OUT[f"review|{rv}"] = simulate(sc, review=rv, exit_rule="hot_or_bad"); line(f"每 {rv} 个交易日", OUT[f"review|{rv}"])
print("--- 买几只（综合排序，每季度检查，很热或基本面变差才换）---")
for n in (5, 10, 20, 30):
    OUT[f"n|{n}"] = simulate(sc, n=n, exit_rule="hot_or_bad"); line(f"{n} 只", OUT[f"n|{n}"])
print("--- 加上温度（低于 40 才建仓，高于 80 清仓）---")
for er, en in (("none", "买了一直拿"), ("hot_or_bad", "很热或基本面变差才换"), ("leave", "不在名单里就换")):
    OUT[f"temp|{er}"] = simulate(sc, exit_rule=er, temp_rule=(40, 80)); line(en + " + 温度", OUT[f"temp|{er}"])
json.dump(OUT, open(f"exp45_{which}.json", "w"), ensure_ascii=False, indent=1)
