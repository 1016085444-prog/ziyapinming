"""研究用：下载全市场快照和历史日线（腾讯证券，前复权，含成交额和换手率），存成每只一个 npz，可断点续传。
用法：fetch.py <起始名次> <结束名次> <交易日数>
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TOUYAN_DATA_DIR"] = os.path.join(HERE, "appdata")
sys.path.insert(0, ROOT)
from market import tencent, universe, net          # noqa: E402
from market.cache import Cache                      # noqa: E402

DATA = os.path.join(HERE, "data")
lo, hi, days = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])

uni_path = os.path.join(HERE, "universe.json")
if os.path.exists(uni_path):
    rows = json.load(open(uni_path, encoding="utf-8"))
else:
    rows = universe.stocks_datacenter()
    json.dump(rows, open(uni_path, "w", encoding="utf-8"), ensure_ascii=False)
print("universe", len(rows), flush=True)
rows = [r for r in rows if r.get("total_mv")]
rows.sort(key=lambda r: -r["total_mv"])
todo = [r for r in rows[lo:hi] if not os.path.exists(os.path.join(DATA, r["code"] + ".npz"))]
print("to fetch", len(todo), "of", hi - lo, flush=True)

def one(r):
    sym = ("sh" if r["market"] == "SH" else "sz" if r["market"] == "SZ" else "bj") + r["code"]
    for attempt in range(3):
        try:
            bars = tencent.kline(sym, days)
            break
        except Exception as exc:
            err = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        return r["code"], f"{type(err).__name__}: {err}"
    if not bars:
        return r["code"], "empty"
    np.savez_compressed(os.path.join(DATA, r["code"] + ".npz"),
                        d=np.array([int(b.date.replace("-", "")) for b in bars], dtype=np.int32),
                        o=np.array([b.open for b in bars], dtype=np.float32), h=np.array([b.high for b in bars], dtype=np.float32),
                        l=np.array([b.low for b in bars], dtype=np.float32), c=np.array([b.close for b in bars], dtype=np.float32),
                        v=np.array([b.volume or 0 for b in bars], dtype=np.float32),
                        a=np.array([b.amount if b.amount is not None else np.nan for b in bars], dtype=np.float64),
                        t=np.array([b.turnover if b.turnover is not None else np.nan for b in bars], dtype=np.float32))
    return r["code"], ""

t0 = time.time()
done = fail = 0
errors = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for code, err in ex.map(one, todo):
        done += 1
        if err:
            fail += 1
            errors.append((code, err))
        if done % 100 == 0:
            print(f"{done}/{len(todo)} fail={fail} {time.time() - t0:.0f}s", flush=True)
print(f"DONE {done} fail={fail} {time.time() - t0:.0f}s", flush=True)
for e in errors[:20]:
    print("ERR", e, flush=True)
