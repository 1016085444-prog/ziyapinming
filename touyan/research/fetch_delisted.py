"""研究用：下载已退市股票的历史日线（腾讯证券仍然保留），存到 data/ 里，和在市的格式一致。"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TOUYAN_DATA_DIR"] = os.path.join(HERE, "appdata")
sys.path.insert(0, ROOT)
from market import tencent  # noqa: E402

DATA = os.path.join(HERE, "data")
rows = [r for r in json.load(open(os.path.join(HERE, "allcodes.json"), encoding="utf-8")) if r["status"] == "D"]
todo = [r for r in rows if not os.path.exists(os.path.join(DATA, r["code"] + ".npz"))]
print("delisted", len(rows), "todo", len(todo), flush=True)

def one(r):
    for attempt in range(3):
        try:
            bars = tencent.kline(r["sym"], 2500)
            break
        except Exception as exc:
            err = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        return r["code"], f"{type(err).__name__}: {err}", 0
    if not bars:
        return r["code"], "empty", 0
    np.savez_compressed(os.path.join(DATA, r["code"] + ".npz"),
                        d=np.array([int(b.date.replace("-", "")) for b in bars], dtype=np.int32),
                        o=np.array([b.open for b in bars], dtype=np.float32), h=np.array([b.high for b in bars], dtype=np.float32),
                        l=np.array([b.low for b in bars], dtype=np.float32), c=np.array([b.close for b in bars], dtype=np.float32),
                        v=np.array([b.volume or 0 for b in bars], dtype=np.float32),
                        a=np.array([b.amount if b.amount is not None else np.nan for b in bars], dtype=np.float64),
                        t=np.array([b.turnover if b.turnover is not None else np.nan for b in bars], dtype=np.float32))
    return r["code"], "", len(bars)

if len(sys.argv) > 1:
    r = next(x for x in rows if x["code"] == sys.argv[1])
    print(one(r)); sys.exit()
t0 = time.time(); ok = empty = fail = 0; errs = []
with ThreadPoolExecutor(max_workers=4) as ex:
    for code, err, n in ex.map(one, todo):
        if not err: ok += 1
        elif err == "empty": empty += 1
        else: fail += 1; errs.append((code, err))
print(f"DONE ok={ok} empty={empty} fail={fail} {time.time() - t0:.0f}s", flush=True)
for e in errs[:10]: print("ERR", e)
