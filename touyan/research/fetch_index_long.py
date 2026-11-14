"""研究用：指数的长历史（尽量早），腾讯接口每次 640 根，按结束日往前翻。"""
import json, os, sys, time
import numpy as np, httpx
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "index_long"); os.makedirs(OUT, exist_ok=True)
client = httpx.Client(timeout=20, headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"})
URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
idx = {"sh000001": "上证指数", "sz399001": "深证成指", "sh000300": "沪深300", "sh000905": "中证500", "sh000852": "中证1000",
       "sz399006": "创业板指", "sh000985": "中证全指", "sz399106": "深证综指", "sh000016": "上证50", "sz399005": "中小100"}
for sym, name in idx.items():
    merged = {}
    end = "2026-11-13"
    for _ in range(20):
        for attempt in range(4):
            try:
                j = client.get(URL, params={"param": f"{sym},day,,{end},640,"}).json(); break
            except Exception as exc:
                time.sleep(1 + attempt)
        data = j.get("data")
        rows = (data.get(sym) or {}).get("day") if isinstance(data, dict) else None
        if not rows:
            break
        for r in rows:
            merged[r[0]] = r
        first = rows[0][0]
        if len(rows) < 640:
            break
        y, m, d = map(int, first.split("-"))
        import datetime
        end = (datetime.date(y, m, d) - datetime.timedelta(days=1)).isoformat()
    ds = sorted(merged)
    np.savez_compressed(os.path.join(OUT, sym + ".npz"), d=np.array([int(x.replace("-", "")) for x in ds], dtype=np.int32),
                        o=np.array([float(merged[x][1]) for x in ds]), c=np.array([float(merged[x][2]) for x in ds]),
                        h=np.array([float(merged[x][3]) for x in ds]), l=np.array([float(merged[x][4]) for x in ds]))
    print(sym, name, len(ds), ds[0], ds[-1], flush=True)
