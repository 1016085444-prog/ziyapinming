"""研究用：下载不复权日线 + 除权除息记录（腾讯证券在除权日那一行里带着分红送转内容）。
每只 4 次请求（每次 640 根，按结束日往前翻）。存 raw/{code}.npz 和 events/{code}.json，可断点续传。
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw"); EVT = os.path.join(HERE, "events")
os.makedirs(RAW, exist_ok=True); os.makedirs(EVT, exist_ok=True)
cal = np.load(os.path.join(HERE, "index", "sh000001.npz"))["d"]
ends = [int(cal[-1]), int(cal[-640]), int(cal[-1279]), int(cal[-1918])]
ends = [f"{e // 10000}-{e // 100 % 100:02d}-{e % 100:02d}" for e in ends]
rows = json.load(open(os.path.join(HERE, "allcodes.json"), encoding="utf-8"))
rows = [r for r in rows if r["status"] != "U"]
todo = [r for r in rows if not os.path.exists(os.path.join(RAW, r["code"] + ".npz"))]
print("all", len(rows), "todo", len(todo), "ends", ends, flush=True)
client = httpx.Client(timeout=20, headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"},
                      limits=httpx.Limits(max_connections=16, max_keepalive_connections=16))
URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

def seg(sym, end):
    for attempt in range(4):
        try:
            r = client.get(URL, params={"param": f"{sym},day,,{end},640,"})
            j = r.json()
            data = j.get("data")
            if not isinstance(data, dict):
                return []            # 这个结束日之前没有数据
            node = data.get(sym) or {}
            return node.get("day") or []
        except Exception as exc:
            err = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"{sym} {end}: {type(err).__name__} {err}")

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
                break                 # 更早已经没有了
        if not merged:
            return r["code"], "empty"
        ds = sorted(merged)
        f = lambda k: np.array([float(merged[d][k]) for d in ds], dtype=np.float32)
        np.savez_compressed(os.path.join(RAW, r["code"] + ".npz"),
                            d=np.array([int(d.replace("-", "")) for d in ds], dtype=np.int32),
                            o=f(1), c=f(2), h=f(3), l=f(4), v=f(5))
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
