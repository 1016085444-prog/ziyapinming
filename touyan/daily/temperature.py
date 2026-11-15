"""市场温度：全市场的估值，在最近十年里排在什么位置（0 最便宜，100 最贵）。

为什么要它：把二十二年的行情翻下来，买入之后一到三年赚不赚钱，主要取决于「买的时候整个市场贵不贵」，
其次才是买了什么。温度低于 20 的日子买入，之后两年、三年几乎没有亏过；80 以上买入，之后两年没有赚过。
它变得很慢（几个月才换一档），所以管的是长期和定投；短期、中期只用它把关——市场很热时不出手。

怎么算：
- 取股票池里每只股票的市净率，求中位数；再取流通市值最大的 300 只，也求中位数；
- 两个中位数各自在「最近十年每天的读数」里排百分位，取平均，就是温度。
  用两个，是因为大盘股和小盘股经常不同步：2020–2021 年大盘股极贵而小盘股不贵，只看一个会漏掉。
- 历史读数（2005 年起每个交易日）随软件一起发，见 market_temp.json；之后每次生成会把当天的读数记下来。

百分位只和「当时已经知道的历史」比，所以回头检验时没有偷看未来。
"""

from __future__ import annotations

import bisect
import json
from functools import lru_cache
from pathlib import Path

from . import evidence_data as ed
from .pool import Stock, day_int, day_text

HISTORY_FILE = Path(__file__).with_name("market_temp.json")
WINDOW = 2440              # 十年
MIN_HISTORY = 750          # 至少攒够三年才给温度
BIG_N = 300
MIN_STOCKS = 500           # 有市净率的股票太少就不算（数据源出了问题）
STORE_KEY = "markettemp:readings"
ZONES = ((20, "cold", "很冷"), (40, "cool", "偏冷"), (60, "mild", "不冷不热"), (80, "warm", "偏热"), (101, "hot", "很热"))
ADVICE = {
    "cold": "很便宜。历史上这种时候买入，之后两三年几乎没有亏过——长期可以买，定投加倍投。",
    "cool": "偏便宜。长期可以分批买，定投多投一些。",
    "mild": "不贵不便宜。已经持有的继续拿；新买的少买、慢买，定投正常投。",
    "warm": "偏贵。长期不再新买，定投减半；短线信号的优势也变小了。",
    "hot": "很贵。历史上这种时候买入，之后两年没有赚过——长期分批卖出，定投停投并止盈，短线不出手。",
}


def zone_of(value: float) -> tuple[str, str]:
    for hi, key, label in ZONES:
        if value < hi:
            return key, label
    return ZONES[-1][1], ZONES[-1][2]


@lru_cache(maxsize=1)
def history() -> dict:
    """随软件发的历史读数：dates（20261113 这样的整数）、all、big（中位数市净率，早年有空值）、index（中证全指）。"""
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def rolling_pct(values: list[float | None], window: int = WINDOW, minp: int = MIN_HISTORY) -> list[float | None]:
    """每个值在「到它为止最近 window 个值」里的百分位（0–100）；历史不够 minp 个的给 None。"""
    out: list[float | None] = [None] * len(values)
    ordered: list[float] = []
    for t, v in enumerate(values):
        if v is not None:
            bisect.insort(ordered, v)
        if t >= window and values[t - window] is not None:
            del ordered[bisect.bisect_left(ordered, values[t - window])]
        if v is not None and len(ordered) >= minp:
            out[t] = 100.0 * bisect.bisect_right(ordered, v) / len(ordered)
    return out


def blend(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return a if b is None else b
    return (a + b) / 2


def series(extra: dict[int, tuple[float, float]] | None = None) -> tuple[list[int], list[float | None]]:
    """(日期, 温度)。extra：发布之后新记下的读数 {日期: (全部, 大盘股)}，接在历史后面一起算。"""
    h = history()
    dates, all_, big = list(h["dates"]), list(h["all"]), list(h["big"])
    for day in sorted(extra or {}):
        a, b = extra[day]
        if day > dates[-1]:
            dates.append(day), all_.append(a), big.append(b)
        elif day == dates[-1]:
            all_[-1], big[-1] = a, b
    pa, pb = rolling_pct(all_), rolling_pct(big)
    return dates, [blend(x, y) for x, y in zip(pa, pb)]


@lru_cache(maxsize=1)
def base_series() -> tuple[list[int], list[float | None]]:
    return series()


def temps_on(days: list[int], extra: dict[int, tuple[float, float]] | None = None) -> list[float | None]:
    """给一串日期，返回每天的温度（取那天或之前最近的一个读数；比历史还早的给 None）。"""
    dates, temps = series(extra) if extra else base_series()
    out = []
    for day in days:
        i = bisect.bisect_right(dates, day) - 1
        out.append(temps[i] if i >= 0 else None)
    return out


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def reading(stocks: dict[str, Stock], rows: dict[str, dict]) -> dict | None:
    """今天的读数：股票池的中位数市净率、流通市值最大 300 只的中位数市净率。数据不够返回 None。"""
    have = [(s, rows[c]["pb"]) for c, s in stocks.items() if c in rows and (rows[c].get("pb") or 0) > 0]
    if len(have) < MIN_STOCKS:
        return None

    def size(item):
        s = item[0]
        return s.float_mv or (rows[s.code].get("float_mv") or rows[s.code].get("total_mv") or 0)

    big = sorted(have, key=size, reverse=True)[:BIG_N]
    return {"all": round(_median([pb for _, pb in have]), 3), "big": round(_median([pb for _, pb in big]), 3), "n": len(have),
            "below_book": round(sum(1 for _, pb in have if pb < 1) / len(have), 3)}


def load_extra(cache) -> dict[int, tuple[float, float]]:
    hit = cache.get_stale(STORE_KEY, 20 * 365 * 86400) if cache is not None else None
    return {int(k): (v[0], v[1]) for k, v in (hit[0] if hit else {}).items()}


def save_extra(cache, extra: dict[int, tuple[float, float]]) -> None:
    if cache is not None:
        cache.set(STORE_KEY, {str(k): list(v) for k, v in sorted(extra.items())})


def pct_in(values: list[float | None], value: float) -> float | None:
    """value 在 values 最近十年（含它自己）里的百分位。"""
    window = [v for v in values[-(WINDOW - 1):] if v is not None] + [value]
    if len(window) < MIN_HISTORY:
        return None
    return 100.0 * sum(1 for v in window if v <= value) / len(window)


def zone_table(current: str | None = None) -> list[dict]:
    """每一档温度在历史上（2008.4–2026.11）之后一到三年的结果：中证全指的平均涨跌、赚钱的日子占比。"""
    out = []
    for z in ed.TEMP["zones"]:
        key, _ = zone_of(z["lo"])
        out.append({"key": key, "label": z["label"], "range": f"{z['lo']}–{z['hi']}", "share": z["share"], "current": key == current,
                    **{f"y{k}": {"mean": z[f"index_y{k}"][0], "win": z[f"index_y{k}"][1], "worst": z[f"index_y{k}"][2]} for k in (1, 2, 3)}})
    return out


def monthly(dates: list[int], temps: list[float | None], index: list[float | None] | None = None) -> list[list]:
    """给图用的月度序列：[年月, 温度, 指数]（每月最后一个读数）。"""
    out: list[list] = []
    for i, (day, t) in enumerate(zip(dates, temps)):
        if t is None:
            continue
        row = [day // 100, round(t, 1), index[i] if index and i < len(index) else None]
        if out and out[-1][0] == row[0]:
            out[-1] = row
        else:
            out.append(row)
    return out


def compute(stocks: dict[str, Stock], rows: dict[str, dict], as_of: str, cache=None) -> dict:
    """今天的市场温度。取不到今天的市净率时，用最近一次的读数并注明日期。"""
    h = history()
    today = day_int(as_of)
    extra = load_extra(cache)
    now = reading(stocks, rows)
    stale = None
    if now:
        extra[today] = (now["all"], now["big"])
        save_extra(cache, extra)
    extra = {d: v for d, v in extra.items() if d <= today}
    dates, temps = series(extra)
    i = bisect.bisect_right(dates, today) - 1
    while i >= 0 and temps[i] is None:
        i -= 1
    if i < 0:
        raise ValueError("市场温度算不出来：没有可用的历史读数")
    if dates[i] != today or not now:
        stale = day_text(dates[i])
    value = temps[i]
    key, label = zone_of(value)
    all_hist = list(h["all"]) + [extra[d][0] for d in sorted(extra) if d > h["dates"][-1]]
    big_hist = list(h["big"]) + [extra[d][1] for d in sorted(extra) if d > h["dates"][-1]]
    cur_all, cur_big = (now["all"], now["big"]) if now else (all_hist[-1], big_hist[-1])
    # 连续多少个交易日待在这一档
    stay = 0
    for t in reversed(temps[:i + 1]):
        if t is None or zone_of(t)[0] != key:
            break
        stay += 1
    return {
        "value": round(value, 1), "zone": key, "label": label, "advice": ADVICE[key], "as_of": day_text(dates[i]), "stale": stale,
        "all": {"pb": cur_all, "pct": _round(pct_in(all_hist[:-1] if now and dates[i] == today else all_hist, cur_all))},
        "big": {"pb": cur_big, "pct": _round(pct_in(big_hist[:-1] if now and dates[i] == today else big_hist, cur_big))},
        "stocks": now["n"] if now else None, "below_book": now["below_book"] if now else None, "stay_days": stay,
        "table": zone_table(key), "history": monthly(dates[:i + 1], temps[:i + 1], h["index"]),
        "span": "2008 年 4 月 – 2026 年 11 月",
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 1)
