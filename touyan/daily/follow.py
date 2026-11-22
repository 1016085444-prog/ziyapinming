"""之前入选的，现在该怎么办。

选股只是一半，另一半是按规则卖。这里把前些天短期、中期板块选出来的股票拿出来，按各自的规则往后走一遍：
- 短期：入选后第二天开盘买（高开 2% 以上按规则放弃），拿 5 个交易日，收盘跌破买入价 8% 止损；
- 中期：第二天开盘买（高开 3% 以上放弃），冷热分掉到 30 以下卖、收盘涨停次日卖、最多拿 120 个交易日。
还在持有的，告诉你现在赚亏多少、还要拿几天；今天触发卖出条件的，提醒卖；已经按规则卖掉的，记下结果。

买入价按「入选后第二天的开盘价」算——和方法检验时的口径一样。你实际的买入价不同的话，止损位要按自己的买入价算。
只对照这个版本的方法选出来的股票（以前版本用的是别的方法，规则不一样）。
"""

from __future__ import annotations

from . import features, mid, short
from .features import Cross
from .pool import Stock, day_int, day_text
from .sim import COST

MIN_VERSION = 3
SHORT_LOOKBACK = 12        # 短期：只看最近 12 个交易日里入选的
MAX_ITEMS = 40
FUND_PREFIX = ("15", "16", "18", "50", "51", "52", "56", "58")     # 场内基金的代码开头


def _base(s: Stock, code_key: str, name: str, picked: str, t: int, max_gap: float) -> dict | None:
    """入选那天之后有没有买进去。返回带买入信息的条目；还没到买入日的 status=wait，按规则放弃的 status=skip。"""
    e = t + 1
    item = {"key": code_key, "code": s.code, "name": name, "picked": picked, "last": round(s.c[-1], 2)}
    if e >= s.n:
        return {**item, "status": "wait", "action": "明天开盘买入（高开太多就放弃）", "days": 0}
    entry, prev = s.o[e], s.c[t]
    if entry <= 0 or prev <= 0 or entry > prev * (1 + max_gap) or s.opens_at_limit(e):
        return {**item, "status": "skip", "action": f"第二天高开超过 {max_gap * 100:.0f}% 或开盘涨跌停，按规则放弃了", "days": 0}
    return {**item, "entry_date": day_text(s.dates[e]), "entry": round(entry, 2), "e": e}


def _done(item: dict, s: Stock, j: int, px: float, why: str) -> dict:
    entry = item["entry"]
    return {**item, "status": "done", "exit_date": day_text(s.dates[j]), "exit": round(px, 2), "ret": px / entry * (1 - COST) - 1,
            "days": j - item["e"], "action": why}


def follow_short(s: Stock, key: str, name: str, picked: str) -> dict | None:
    t = s.index(day_int(picked))
    if t < 0:
        return None
    item = _base(s, key, name, picked, t, short.MAX_GAP)
    if item is None or "e" not in item:
        return item
    e, entry = item["e"], s.o[item["e"]]
    last = e + short.HOLD
    pending = ""
    for j in range(e + 1, min(last, s.n - 1) + 1):
        if pending:
            return _done(item, s, j, s.o[j], pending)
        if s.c[j] <= entry * (1 - short.STOP):
            if not s.limit_down(j):
                return _done(item, s, j, s.c[j], "收盘跌破止损位，当天收盘卖出")
            pending = "跌停卖不掉，第二天开盘卖出"
        elif j == last:
            if not s.limit_down(j):
                return _done(item, s, j, s.c[j], f"拿满 {short.HOLD} 个交易日，收盘卖出")
            pending = "到期那天跌停卖不掉，第二天开盘卖出"
    nxt = min(last, s.n - 1) + 1
    if pending and nxt < s.n:
        return _done(item, s, nxt, s.o[nxt], pending)
    held = s.n - 1 - e
    ret = s.c[-1] / entry - 1
    stop_px = entry * (1 - short.STOP)
    if pending:
        return {**item, "status": "sell", "ret": ret, "days": held, "action": "明天开盘卖出（" + pending[:pending.index("，")] + "）"}
    left = short.HOLD - held
    return {**item, "status": "hold", "ret": ret, "days": held, "stop": round(stop_px, 2),
            "action": (f"继续拿，还有 {left} 个交易日到期；" if left > 0 else "") + f"哪天收盘低于 {stop_px:.2f} 就卖"}


def follow_mid(s: Stock, key: str, name: str, picked: str, cold_at, cold_now: float | None) -> dict | None:
    t = s.index(day_int(picked))
    if t < 0:
        return None
    item = _base(s, key, name, picked, t, mid.MAX_GAP)
    if item is None or "e" not in item:
        return item
    e, entry = item["e"], s.o[item["e"]]
    last = e + mid.HOLD
    pending = ""
    for j in range(e + 1, min(last, s.n - 1) + 1):
        if pending:
            return _done(item, s, j, s.o[j], pending)
        cold = cold_at(j)
        if s.limit_up(j):
            pending = "前一天收盘涨停，开盘卖出"
        elif cold is not None and cold < mid.EXIT_COLD:
            pending = f"前一天冷热分掉到 {cold:.0f}（变热了），开盘卖出"
        elif j == last:
            if not s.limit_down(j):
                return _done(item, s, j, s.c[j], f"拿满 {mid.HOLD} 个交易日，收盘卖出")
            pending = "到期那天跌停卖不掉，开盘卖出"
    nxt = min(last, s.n - 1) + 1
    if pending and nxt < s.n:
        return _done(item, s, nxt, s.o[nxt], pending)
    held = s.n - 1 - e
    ret = s.c[-1] / entry - 1
    out = {**item, "ret": ret, "days": held, "cold": None if cold_now is None else round(cold_now)}
    if pending:
        why = "今天收盘涨停" if s.limit_up(s.n - 1) else f"冷热分掉到 {cold_now:.0f}，变热了" if cold_now is not None and cold_now < mid.EXIT_COLD else "到期"
        return {**out, "status": "sell", "action": f"明天开盘卖出（{why}）"}
    left = mid.HOLD - held
    return {**out, "status": "hold",
            "action": f"继续拿：冷热分 {cold_now:.0f}，还没变热（掉到 {mid.EXIT_COLD} 以下才卖）；最多再拿 {left} 个交易日" if cold_now is not None
            else f"继续拿；最多再拿 {left} 个交易日"}


def _summary(items: list[dict]) -> dict:
    done = [x for x in items if x["status"] == "done"]
    open_ = [x for x in items if x["status"] in ("hold", "sell")]
    return {"open": len(open_), "sell": sum(1 for x in items if x["status"] == "sell"), "done": len(done),
            "done_mean": sum(x["ret"] for x in done) / len(done) if done else None,
            "done_win": sum(1 for x in done if x["ret"] > 0) / len(done) if done else None,
            "open_mean": sum(x["ret"] for x in open_) / len(open_) if open_ else None}


def collect(runs: list[dict], board: str, method: str) -> list[tuple[str, str, str]]:
    """以前各次里这个板块选出来的：[(入选日, key, 名字)]，从早到晚。只要这个版本、同一个方法选出来的。"""
    out = []
    for r in sorted(runs, key=lambda r: r["as_of"]):
        if (r.get("pv") or 0) < MIN_VERSION or (r.get("methods") or {}).get(board) != method:
            continue
        for p in (r.get("boards") or {}).get(board) or []:
            code = p["key"].split(":")[-1]
            if p["key"].startswith("OF:") or code.startswith(FUND_PREFIX):
                continue                                  # 一起推荐的 ETF、基金不在股票池里，不跟踪
            out.append((r["as_of"], p["key"], p["name"]))
    return out


def windows(runs: list[dict], calendar: list[int] | None) -> tuple[set[str], str]:
    """(短期要对照的那些天, 中期从哪天起对照)。短期拿 5 天，看最近 12 次就够；中期最多拿 120 天，看最近半年多。"""
    short_days = set(sorted({r["as_of"] for r in runs}, reverse=True)[:SHORT_LOOKBACK])
    k = mid.HOLD + 10
    mid_since = day_text(calendar[-k]) if calendar and len(calendar) > k else ""
    return short_days, mid_since


def wanted(store, as_of: str, calendar: list[int] | None) -> list[tuple[str, str]]:
    """要对照的股票：[(key, 名字)]。runner 用它把掉出股票池的那几只单独取一下日线。"""
    runs = [r for r in store.list_daily(250) if r["as_of"] < as_of]
    if not runs:
        return []
    short_days, mid_since = windows(runs, calendar)
    out = {key: name for d, key, name in collect(runs, "short", short.NAME) if d in short_days}
    out.update({key: name for d, key, name in collect(runs, "mid", mid.NAME) if d >= mid_since})
    return sorted(out.items())


def build(picks: list[tuple[str, str, str]], stocks: dict[str, Stock], follow_one) -> dict | None:
    """同一只股票连着几天入选的，只算第一次（已经拿着了）；按规则卖掉之后再入选的，算新的一笔。"""
    latest: dict[str, dict] = {}
    for picked, key, name in picks:
        code = key.split(":")[-1]
        s = stocks.get(code)
        prev = latest.get(code)
        if prev and prev["status"] in ("hold", "sell", "wait"):
            continue
        if prev and prev["status"] == "done" and picked <= prev["exit_date"]:
            continue
        if s is None:
            if not prev:
                latest[code] = {"key": key, "code": code, "name": name, "picked": picked, "status": "unknown", "days": 0,
                                "action": "日线没取到（可能停牌或退市），请自己查看"}
            continue
        item = follow_one(s, key, name, picked)
        if item:
            item.pop("e", None)
            latest[code] = item
    items = [x for x in latest.values() if x["status"] != "skip"]
    if not items:
        return None
    order = {"sell": 0, "hold": 1, "wait": 2, "unknown": 3, "done": 4}
    items.sort(key=lambda x: (order[x["status"]], x["picked"]))
    done = sorted((x for x in items if x["status"] == "done"), key=lambda x: x["exit_date"], reverse=True)
    rest = [x for x in items if x["status"] != "done"]
    return {"items": (rest + done)[:MAX_ITEMS], "summary": _summary(items)}


def attach(store, boards: dict, stocks: dict[str, Stock], crosses: dict[int, Cross], as_of: str,
           extra: dict[str, Stock] | None = None, calendar: list[int] | None = None) -> None:
    """给短期、中期板块加上 following。没有以前的记录就不加。
    extra：不在股票池里、单独取了日线的那几只（比如成交缩到门槛以下的冷门股）。"""
    runs = [r for r in store.list_daily(250) if r["as_of"] < as_of]
    if not runs:
        return
    extra = extra or {}
    everyone = {**extra, **stocks}
    today = crosses.get(day_int(as_of))
    short_days, mid_since = windows(runs, calendar)
    b = boards.get("short")
    if b is not None:
        picks = [p for p in collect(runs, "short", short.NAME) if p[0] in short_days]
        got = build(picks, everyone, follow_short)
        if got:
            got["note"] = "买入价按入选后第二天的开盘价算；你的买入价不同的话，止损位按自己的买入价重新算（买入价 × 0.92）。"
            b["following"] = got
    b = boards.get("mid")
    if b is not None:
        def one(s, key, name, picked):
            if s.code in stocks:
                i = today.pos.get(s.code) if today is not None else None
                cold_now = today.cold[i] if i is not None and today.cold else None
                return follow_mid(s, key, name, picked, mid.cold_lookup(s, crosses), cold_now)
            known = features.cold_series(s, crosses)             # 掉出了池子：放回每一天的池子里估冷热分
            return follow_mid(s, key, name, picked, known.get, known.get(s.n - 1))

        got = build([p for p in collect(runs, "mid", mid.NAME) if p[0] >= mid_since], everyone, one)
        if got:
            got["note"] = ("买入价按入选后第二天的开盘价算。冷热分每次生成时算一次：中间几天没有生成的，那几天的冷热分按每 5 个交易日一次补算，"
                           "所以卖出日可能比严格按规则晚几天。")
            b["following"] = got
