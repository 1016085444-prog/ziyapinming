"""研究用：2005-01 ~ 2016-07 的不复权日线（含成交额、换手率）+ 除权除息记录，存 raw_old/ 和 events_old/。"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, httpx
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw_old"); EVT = os.path.join(HERE, "events_old")
os.makedirs(RAW, exist_ok=True); os.makedirs(EVT, exist_ok=True)
cal = np.load(os.path.join(HERE, "index_long", "sh000001.npz"))["d"]
cal = cal[(cal >= 20041001) & (cal < 20160801)]
ends = [int(cal[-1 - 639 * k]) for k in range(0, 5) if 1 + 639 * k <= len(cal)]
ends = [f"{e // 10000}-{e // 100 % 100:02d}-{e % 100:02d}" for e in ends]
rows = json.load(open(os.path.join(HERE, "allcodes.json"), encoding="utf-8"))
rows = [r for r in rows if r["status"] != "U"]
todo = [r for r in rows if not os.path.exists(os.path.join(RAW, r["code"] + ".npz")) and not os.path.exists(os.path.join(RAW, r["code"] + ".none"))]
print("all", len(rows), "todo", len(todo), "ends", ends, flush=True)
client = httpx.Client(timeout=20, headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"},
                      limits=httpx.Limits(max_connections=16, max_keepalive_connections=16))
URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
def seg(sym, end):
    for attempt in range(4):
        try:
            j = client.get(URL, params={"param": f"{sym},day,,{end},640,"}).json()
            data = j.get("data")
            if not isinstance(data, dict):
                return []
            return (data.get(sym) or {}).get("day") or []
        except Exception as exc:
            err = exc; time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"{sym} {end}: {type(err).__name__} {err}")
def num(x):
    try: return float(x)
    except Exception: return float("nan")
def one(r):
    sym = r["sym"]
    try:
        merged, events = {}, {}
        for end in ends:
            got = seg(sym, end)
            for row in got:
                merged[row[0]] = row
                if len(row) > 6 and isinstance(row[6], dict) and row[6]:
                    events[row[0]] = row[6]
            if len(got) < 640:
                break
        if not merged:
            open(os.path.join(RAW, r["code"] + ".none"), "w").close()
            return r["code"], ""
        ds = sorted(merged)
        f = lambda k: np.array([num(merged[d][k]) if len(merged[d]) > k else float("nan") for d in ds], dtype=np.float32)
        np.savez_compressed(os.path.join(RAW, r["code"] + ".npz"),
                            d=np.array([int(d.replace("-", "")) for d in ds], dtype=np.int32),
                            o=f(1), c=f(2), h=f(3), l=f(4), v=f(5), t=f(7),
                            a=np.array([num(merged[d][8]) * 1e4 if len(merged[d]) > 8 else float("nan") for d in ds], dtype=np.float64))
        json.dump(events, open(os.path.join(EVT, r["code"] + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
        return r["code"], ""
    except Exception as exc:
        return r["code"], f"{type(exc).__name__}: {exc}"
t0 = time.time(); done = fail = 0; errs = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for code, err in ex.map(one, todo):
        done += 1
        if err:
            fail += 1; errs.append((code, err))
        if done % 200 == 0:
            print(f"{done}/{len(todo)} fail={fail} {time.time() - t0:.0f}s", flush=True)
print(f"DONE {done} fail={fail} {time.time() - t0:.0f}s", flush=True)
for e in errs[:20]:
    print("ERR", e, flush=True)
