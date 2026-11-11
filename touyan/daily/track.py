"""历史表现：过去每天精选出来的标的，之后实际涨了多少、有没有跑赢沪深300。

口径：入场价取精选当天（数据日期）的收盘，之后第 1、5、20 个交易日的收盘算持有收益，
同期沪深300 收益相减得到超额收益。还没走完的期限不计入该期限的统计。
样本少于 30 个时胜率没有统计意义，页面会提示。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from market import symbols
from market.models import Bar

HORIZONS = (1, 5, 20)
GROUPS = (("stocks", "股票"), ("etfs", "ETF"), ("funds", "场外基金"))
MIN_SAMPLES = 30


def _index_on_or_before(bars: list[Bar], day: str) -> int | None:
    idx = None
    for i, b in enumerate(bars):
        if b.date <= day:
            idx = i
        else:
            break
    return idx


def outcome(bars: list[Bar], as_of: str, bench: list[Bar]) -> dict | None:
    i = _index_on_or_before(bars, as_of)
    if i is None:
        return None
    entry = bars[i].adj_close
    bench_map = {b.date: b.adj_close for b in bench}
    b0 = bench_map.get(bars[i].date)
    out = {"entry_date": bars[i].date, "days": len(bars) - 1 - i}
    marks = {f"t{h}": i + h for h in HORIZONS}
    marks["now"] = len(bars) - 1
    for key, j in marks.items():
        if j >= len(bars) or j == i:
            continue
        ret = bars[j].adj_close / entry - 1
        out[key] = ret
        b1 = bench_map.get(bars[j].date)
        if b0 and b1:
            out[f"{key}_excess"] = ret - (b1 / b0 - 1)
    return out


def summarize(rets: list[float], excess: list[float]) -> dict:
    n = len(rets)
    if not n:
        return {"n": 0}
    return {"n": n, "avg": sum(rets) / n, "win_rate": sum(1 for r in rets if r > 0) / n,
            "avg_excess": sum(excess) / len(excess) if excess else None,
            "beat_rate": sum(1 for e in excess if e > 0) / len(excess) if excess else None}


def picks_of(payload: dict) -> dict[str, list[dict]]:
    return {
        "stocks": [{"key": p["key"], "name": p["name"], "kind": "stock"} for p in payload["stocks"]["picks"]],
        "etfs": [{"key": p["key"], "name": p["name"], "kind": "etf"} for p in payload["etfs"]["picks"]],
        "funds": [{"key": p["key"], "name": p["name"], "kind": "fund"}
                  for g in payload["funds"]["groups"] for p in g["picks"]],
    }


def performance(store, router, limit: int = 40) -> dict:
    runs = [store.get_daily(r["id"]) for r in store.list_daily(limit)]
    runs = [r for r in runs if r]
    if not runs:
        return {"runs": [], "groups": {}, "min_samples": MIN_SAMPLES}
    keys: dict[str, dict] = {}
    for run in runs:
        for items in picks_of(run).values():
            for it in items:
                keys.setdefault(it["key"], it)

    def series(item):
        inst = symbols.from_key(item["key"], item["kind"], item["name"])
        bars, _ = router.series(inst, 300)
        return bars

    bars_by_key: dict[str, list[Bar]] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {k: ex.submit(series, it) for k, it in keys.items()}
        for k, fut in futures.items():
            try:
                bars_by_key[k] = fut.result()
            except Exception:
                continue
    bench, _ = router.series(symbols.CSI300, 300)

    stats: dict[str, dict[str, tuple[list, list]]] = {g: {h: ([], []) for h in ("t1", "t5", "t20", "now")}
                                                     for g, _ in GROUPS}
    run_rows = []
    for run in runs:
        groups = picks_of(run)
        row = {"id": run["id"], "as_of": run["as_of"], "strategy": run["strategy"]["label"], "items": []}
        for g, _ in GROUPS:
            for it in groups[g]:
                bars = bars_by_key.get(it["key"])
                res = outcome(bars, run["as_of"], bench) if bars else None
                row["items"].append({"group": g, "key": it["key"], "name": it["name"],
                                     "return": (res or {}).get("now"), "excess": (res or {}).get("now_excess"),
                                     "days": (res or {}).get("days")})
                if not res:
                    continue
                for h in ("t1", "t5", "t20", "now"):
                    if h in res:
                        stats[g][h][0].append(res[h])
                        if f"{h}_excess" in res:
                            stats[g][h][1].append(res[f"{h}_excess"])
        stock_rets = [x["return"] for x in row["items"] if x["group"] == "stocks" and x["return"] is not None]
        row["stocks_avg"] = sum(stock_rets) / len(stock_rets) if stock_rets else None
        run_rows.append(row)
    return {
        "runs": run_rows, "min_samples": MIN_SAMPLES,
        "groups": {g: {"label": label, **{h: summarize(*stats[g][h]) for h in ("t1", "t5", "t20", "now")}}
                   for g, label in GROUPS},
    }
