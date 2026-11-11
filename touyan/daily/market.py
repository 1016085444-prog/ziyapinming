"""大盘概况：主要指数、涨跌家数、涨跌停、行业强弱，以及一个粗略的「市场温度」。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from statistics import median

from market.models import Bar, Instrument
from market.net import SourceError
from quant import indicators as ind

INDICES = [
    Instrument("000001", "SH", "index", "上证指数", "1.000001"),
    Instrument("399001", "SZ", "index", "深证成指", "0.399001"),
    Instrument("399006", "SZ", "index", "创业板指", "0.399006"),
    Instrument("000300", "SH", "index", "沪深300", "1.000300"),
    Instrument("000688", "SH", "index", "科创50", "1.000688"),
]

REGIME_ADVICE = {
    "偏强": "市场环境偏强，可以按计划关注精选标的",
    "震荡": "市场震荡，精选标的宜轻仓、分批买入",
    "偏弱": "市场偏弱，控制仓位，优先考虑债券基金和防守品种",
}


def limit_pct(code: str, market: str, name: str) -> float:
    if "ST" in name:
        return 5.0
    if market == "BJ":
        return 30.0
    if code.startswith(("30", "688", "689")):
        return 20.0
    return 10.0


def breadth(rows: list[dict]) -> dict:
    changes = [r["change_pct"] for r in rows if r.get("change_pct") is not None]
    up = sum(1 for c in changes if c > 0)
    down = sum(1 for c in changes if c < 0)
    limit_up = limit_down = 0
    for r in rows:
        c = r.get("change_pct")
        if c is None:
            continue
        lim = limit_pct(r["code"], r["market"], r.get("name", "")) - 0.15   # 四舍五入后 9.9x% 也算涨停
        limit_up += c >= lim
        limit_down += c <= -lim
    return {
        "total": len(changes), "up": up, "down": down, "flat": len(changes) - up - down,
        "limit_up": limit_up, "limit_down": limit_down,
        "up_ratio": round(up / (up + down), 3) if up + down else None,
        "median_change": round(median(changes), 2) if changes else None,
        "amount_yi": round(sum(r.get("amount") or 0 for r in rows) / 1e8),
    }


def regime(bench: list[Bar], br: dict | None) -> dict:
    notes, score = [], 0
    closes = [b.adj_close for b in bench]
    if len(closes) >= 60:
        close, ma20, ma60 = closes[-1], ind.sma(closes, 20)[-1], ind.sma(closes, 60)[-1]
        r20 = (close / closes[-21] - 1) * 100
        score += 1 if close >= ma20 else -1
        notes.append("沪深300 " + ("站上" if close >= ma20 else "跌破") + " 20 日线")
        score += 1 if ma20 >= ma60 else -1
        notes.append("中期均线" + ("向上" if ma20 >= ma60 else "向下"))
        score += 1 if r20 > 0 else -1
        notes.append(f"近 20 日 {r20:+.1f}%")
    ratio = (br or {}).get("up_ratio")
    if ratio is not None:
        if ratio > 0.6:
            score += 1
        elif ratio < 0.4:
            score -= 1
        notes.append(f"上涨家数占 {ratio * 100:.0f}%")
    label = "偏强" if score >= 2 else "偏弱" if score <= -2 else "震荡"
    return {"label": label, "score": score, "notes": notes, "advice": REGIME_ADVICE[label]}


def index_quotes(router) -> tuple[list[dict], list[str]]:
    def one(inst: Instrument):
        q, _ = router.quote(inst)
        return {"name": inst.name, "code": inst.code, "key": inst.key, "price": q.price,
                "change_pct": q.change_pct}

    out, warnings = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [(inst, pool.submit(one, inst)) for inst in INDICES]
        for inst, fut in futures:
            try:
                out.append(fut.result())
            except SourceError as exc:
                warnings.append(f"{inst.name}行情取不到：{exc}")
    return out, warnings


def overview(router, rows: list[dict], boards: list[dict], bench: list[Bar]) -> dict:
    indices, warnings = index_quotes(router)
    br = breadth(rows) if rows else None
    return {
        "indices": indices,
        "breadth": br,
        "sectors_up": boards[:5],
        "sectors_down": sorted(boards[-5:], key=lambda b: b["change_pct"]) if len(boards) >= 10 else [],
        "regime": regime(bench, br),
        "warnings": warnings,
    }
