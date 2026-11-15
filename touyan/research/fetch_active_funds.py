"""研究用：下载一批主动偏股基金（2016 年底以前成立、现在还在的）的复权净值，看「过去业绩好的，以后是不是还好」。

注意：已经清盘的基金不在名单里（拿不到），所以结果偏乐观——这一点在结论里要说明。
"""
import sys, os, re, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '/home/user/ziyapinming/touyan')
import config
from market import universe, fundem
from market.cache import Cache

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fundnav_active")
os.makedirs(OUT, exist_ok=True)
cache = Cache(config.DATA_DIR / "cache.db")
rows = []
for ft in ("gp", "hh"):
    rows += [dict(x, ft=ft) for x in universe.fund_rank(cache, ft)]
pat = re.compile(r"指数|ETF|联接|债|货币|保本|定开|持有|封闭|FOF|QDII|量化对冲|养老|[C-Z]$")
act = [r for r in rows if r.get("inception") and r["inception"] <= "2016-12-31" and not pat.search(r["name"])]
act.sort(key=lambda r: r["code"])
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(act)
step = max(1, len(act) // limit)
pick = act[::step][:limit]
json.dump(pick, open(os.path.join(OUT, "_list.json"), "w"), ensure_ascii=False)
print("candidates", len(act), "fetching", len(pick), flush=True)


def one(r):
    path = os.path.join(OUT, r["code"] + ".json")
    if os.path.exists(path):
        return "cached"
    for attempt in range(3):
        try:
            profile, bars, _ = fundem.pingzhong(r["code"])
            json.dump({"code": r["code"], "name": r["name"], "ft": r["ft"], "inception": r["inception"], "scale": getattr(profile, "scale", None),
                       "d": [b.date for b in bars], "c": [b.adj_close for b in bars]}, open(path, "w"), ensure_ascii=False)
            return "ok"
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return "fail " + err[:80]


t0 = time.time(); done = {"ok": 0, "cached": 0, "fail": 0}
with ThreadPoolExecutor(max_workers=5) as ex:
    for i, res in enumerate(ex.map(one, pick), 1):
        done[res.split()[0]] += 1
        if i % 50 == 0 or i == len(pick):
            print(i, done, round(time.time() - t0), "s", res if res.startswith("fail") else "", flush=True)
