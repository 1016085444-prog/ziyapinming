"""研究用：枚举沪深 A 股代码段，找出所有存在过的股票（含已退市），存 allcodes.json。"""
import json, os, sys, time, re
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TOUYAN_DATA_DIR"] = os.path.join(HERE, "appdata")
sys.path.insert(0, ROOT)
import httpx

ranges = [("sz", 1, 4999), ("sz", 300001, 302999), ("sh", 600000, 605999), ("sh", 688000, 689999)]
syms = [f"{p}{n:06d}" for p, lo, hi in ranges for n in range(lo, hi + 1)]
batches = [syms[i:i + 80] for i in range(0, len(syms), 80)]
client = httpx.Client(timeout=20, headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"})
pat = re.compile(r'v_s_(\w+)="([^"]*)"')

def one(batch):
    for attempt in range(4):
        try:
            r = client.get("https://qt.gtimg.cn/q=" + ",".join("s_" + s for s in batch))
            text = r.content.decode("gbk", "replace")
            out = []
            for sym, body in pat.findall(text):
                f = body.split("~")
                if len(f) < 11:
                    continue
                out.append({"sym": sym, "name": f[1], "code": f[2], "price": f[3], "status": f[8], "mv": f[9], "type": f[10]})
            return out
        except Exception as exc:
            err = exc
            time.sleep(1 + attempt)
    print("FAIL", batch[0], err, flush=True)
    return []

rows = []
with ThreadPoolExecutor(max_workers=4) as ex:
    for i, out in enumerate(ex.map(one, batches)):
        rows += out
print("found", len(rows))
from collections import Counter
print(Counter(r["type"] for r in rows).most_common(12))
print(Counter(r["status"] for r in rows).most_common(8))
json.dump(rows, open(os.path.join(HERE, "allcodes.json"), "w", encoding="utf-8"), ensure_ascii=False)
