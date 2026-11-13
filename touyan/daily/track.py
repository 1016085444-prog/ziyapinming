"""历史表现：过去每天四个板块选出来的标的，之后实际涨了多少、有没有跑赢沪深300。

口径和「方法体检」一致：收盘后才知道入选，所以按**下一个交易日**算买入——股票和 ETF 用开盘价，
场外基金用那天的净值（今天申购，拿到的就是下一个交易日的净值）。每个板块看和它持有期相称的两个时间点：
短期第 3、8 个交易日，中期第 20、60 个，长期和定投第 60、250 个；还没走到的不计入。

这是真正的「样本外」记录：方法定下来之后才发生的行情，比任何回头检验都更有说服力。
样本少于 30 个时胜率没有统计意义，页面会提示。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from market import symbols
from market.models import Bar

HORIZONS = {"short": (3, 8), "mid": (20, 60), "long": (60, 250), "dca": (60, 250)}
LABELS = {"short": "短期", "mid": "中期", "long": "长期", "dca": "定投"}
MIN_SAMPLES = 30


def outcome(bars: list[Bar], as_of: str, bench: list[Bar], horizons: tuple[int, ...], is_fund: bool) -> dict | None:
    i = None
    for k, b in enumerate(bars):
        if b.date <= as_of:
            i = k
        else:
            break
    if i is None or i + 1 >= len(bars):
        return None                                   # 入选之后还没有新的行情
    e = i + 1
    entry = bars[e].adj_close if is_fund else (bars[e].open or bars[e].close)
    if not entry or entry <= 0:
        return None
    bench_at = {b.date: b for b in bench}
    b0 = bench_at.get(bars[e].date)
    base = (b0.adj_close if is_fund else b0.open) if b0 else None
    out = {"entry_date": bars[e].date, "days": len(bars) - 1 - e}
    marks = {f"h{n + 1}": e + h for n, h in enumerate(horizons)}
    marks["now"] = len(bars) - 1
    for key, j in marks.items():
        if j >= len(bars) or j <= e and key != "now":
            continue
        ret = bars[j].adj_close / entry - 1
        out[key] = ret
        b1 = bench_at.get(bars[j].date)
        if base and b1:
            out[f"{key}_excess"] = ret - (b1.adj_close / base - 1)
    return out


def summarize(rets: list[float], excess: list[float]) -> dict:
    n = len(rets)
    if not n:
        return {"n": 0}
    return {"n": n, "avg": sum(rets) / n, "win_rate": sum(1 for r in rets if r > 0) / n,
            "avg_excess": sum(excess) / len(excess) if excess else None,
            "beat_rate": sum(1 for e in excess if e > 0) / len(excess) if excess else None}


def picks_of(payload: dict) -> dict[str, list[dict]]:
    out = {}
    for key, board in (payload.get("boards") or {}).items():
        picks = list(board["picks"]) + (board.get("etfs") or {}).get("picks", []) + (board.get("funds") or {}).get("picks", [])
        out[key] = [{"key": p["key"], "name": p["name"], "kind": p.get("kind", "stock")} for p in picks]
    return out


def performance(store, router, limit: int = 60) -> dict:
    runs = [store.get_daily(r["id"]) for r in store.list_daily(limit)]
    runs = [r for r in runs if r and r.get("boards")]
    if not runs:
        return {"runs": [], "boards": {}, "min_samples": MIN_SAMPLES}
    items: dict[str, dict] = {}
    for run in runs:
        for picks in picks_of(run).values():
            for it in picks:
                items.setdefault(it["key"], it)

    def series(item):
        inst = symbols.from_key(item["key"], item["kind"], item["name"])
        return router.series(inst, 400)[0]

    bars_by_key: dict[str, list[Bar]] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {k: ex.submit(series, it) for k, it in items.items()}
        for k, fut in futures.items():
            try:
                bars_by_key[k] = fut.result()
            except Exception:
                continue
    bench, _ = router.series(symbols.CSI300, 400)

    stats = {b: {h: ([], []) for h in ("h1", "h2", "now")} for b in HORIZONS}
    run_rows = []
    for run in runs:
        row = {"id": run["id"], "as_of": run["as_of"], "items": []}
        for board, picks in picks_of(run).items():
            if board not in HORIZONS:
                continue
            for it in picks:
                bars = bars_by_key.get(it["key"])
                res = outcome(bars, run["as_of"], bench, HORIZONS[board], it["key"].startswith("OF:")) if bars else None
                row["items"].append({"board": board, "key": it["key"], "name": it["name"],
                                     "return": (res or {}).get("now"), "excess": (res or {}).get("now_excess"),
                                     "days": (res or {}).get("days")})
                for h in ("h1", "h2", "now"):
                    if res and h in res:
                        stats[board][h][0].append(res[h])
                        if f"{h}_excess" in res:
                            stats[board][h][1].append(res[f"{h}_excess"])
        run_rows.append(row)
    return {
        "runs": run_rows, "min_samples": MIN_SAMPLES,
        "boards": {b: {"label": LABELS[b], "horizons": list(HORIZONS[b]),
                       **{h: summarize(*stats[b][h]) for h in ("h1", "h2", "now")}} for b in HORIZONS},
    }
