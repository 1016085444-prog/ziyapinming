"""股票池：全市场里成交够活跃的股票（约三四千只）的日线。大盘预估、短期、中期三样都从这里来。

为什么要这么大的池子：
- 「大盘预估」看的是全市场的状态——多少只涨停跌停、整体放量还是缩量——只看几百只大盘股量不出来；
- 短期、中期的选股规则在中小市值的股票里才有效（在市值最大的那批里基本无效），池子里得有它们；
- 「冷热分」是在全市场里排名次，池子越全，名次越准。

池子按「成交够不够活跃」来定（近 20 个交易日日均成交 5000 万以上、上市满一年、不是 ST），
和今天有没有信号无关——拿今天看着不错的那批股票回头检验，结果必然好看。

行情用等比复权（见 market/tencent.py 的 kline_true），每天的涨跌幅和当时实际发生的一样。
几千只股票的日线占内存，所以每只只留 开/高/低/收/成交额 五列，用紧凑数组存；当天下载过的整池存成一个文件，
同一个交易日里重新生成不用再下载。
"""

from __future__ import annotations

import json
import zlib
from array import array
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from market.models import Bar

from .common import limit_pct, tradable

POOL_DAYS = 640            # 约两年半；腾讯证券一次请求最多 640 根
MIN_BARS = 260             # 上市满一年（冷热分要回看 250 个交易日）
MIN_AMOUNT = 5e7           # 近 20 个交易日的日均成交额
MAX_POOL = 4500            # 防御：快照异常时不至于去下载整个市场
MAGIC = b"TYPOOL1\n"


def day_int(text: str) -> int:
    return int(text[:4]) * 10000 + int(text[5:7]) * 100 + int(text[8:10])


def day_text(d: int) -> str:
    return f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"


def _usable(rows: list[dict], field: str) -> bool:
    """这一列是不是真有数据（盘中倒推的快照没有成交额；接口变了某列可能全空）。"""
    have = sum(1 for r in rows if r.get(field))
    return have >= len(rows) * 0.5


def build_pool(rows: list[dict]) -> list[dict]:
    """要下载日线的名单：可交易、今天成交不太冷清的。最终进不进池子，下载之后按 20 日均成交额和上市时间再定。"""
    rows = [r for r in rows if tradable(r)]
    if _usable(rows, "amount"):
        rows = sorted((r for r in rows if (r.get("amount") or 0) >= MIN_AMOUNT * 0.6), key=lambda r: -r["amount"])
    elif _usable(rows, "total_mv"):                 # 盘中倒推的快照没有成交额：按市值取
        rows = sorted((r for r in rows if r.get("total_mv")), key=lambda r: -r["total_mv"])[:4000]
    return rows[:MAX_POOL]


class Stock:
    """一只股票的日线（等比复权）。dates 是 20261113 这样的整数；a 是成交额（元）。"""

    __slots__ = ("code", "market", "name", "dates", "o", "h", "l", "c", "a", "limit", "n", "float_mv")

    def __init__(self, code: str, market: str, name: str, dates, o, h, l, c, a, float_mv: float | None = None):
        self.code, self.market, self.name = code, market, name
        self.dates, self.o, self.h, self.l, self.c, self.a = dates, o, h, l, c, a
        self.n = len(dates)
        self.limit = limit_pct(code, market)
        self.float_mv = float_mv

    @classmethod
    def from_bars(cls, bars: list[Bar], code: str, market: str = "SH", name: str = "") -> "Stock":
        last = bars[-1] if bars else None
        mv = last.amount / (last.turnover / 100) if last and last.amount and last.turnover else None
        return cls(code, market, name,
                   array("i", (day_int(b.date) for b in bars)),
                   array("f", (b.open for b in bars)), array("f", (b.high for b in bars)),
                   array("f", (b.low for b in bars)), array("f", (b.close for b in bars)),
                   array("f", (b.amount or 0.0 for b in bars)), mv)

    @property
    def key(self) -> str:
        return f"{self.market}:{self.code}"

    def index(self, day: int) -> int:
        """这一天是第几根；当天没交易（停牌、还没上市）返回 -1。"""
        i = bisect_left(self.dates, day)
        return i if i < self.n and self.dates[i] == day else -1

    def ret(self, t: int) -> float:
        return self.c[t] / self.c[t - 1] - 1 if t > 0 and self.c[t - 1] > 0 else 0.0

    def limit_up(self, t: int) -> bool:
        """收盘封在涨停：涨幅到了涨停幅度，并且收在全天最高。"""
        return t > 0 and self.ret(t) >= self.limit - 0.004 and self.c[t] >= self.h[t] * 0.9995

    def limit_down(self, t: int) -> bool:
        return t > 0 and self.ret(t) <= -self.limit + 0.004 and self.c[t] <= self.l[t] * 1.0005

    def opens_at_limit(self, t: int) -> int:
        """开盘就在涨停（1）或跌停（-1）价上，否则 0。"""
        if t <= 0 or self.c[t - 1] <= 0:
            return 0
        gap = self.o[t] / self.c[t - 1] - 1
        return 1 if gap >= self.limit - 0.004 else -1 if gap <= -self.limit + 0.004 else 0

    def avg_amount(self, t: int, k: int = 20) -> float:
        a = max(0, t - k + 1)
        return sum(self.a[a:t + 1]) / (t - a + 1)


def clean(bars: list[Bar]) -> bool:
    """开高低收都是正数。个别数据源偶尔会给出 0，带着它算涨跌幅会出错。"""
    return all(b.open > 0 and b.close > 0 and b.high > 0 and b.low > 0 for b in bars)


# ── 整池存成一个文件 ──────────────────────────────────────────────

def save_pool(path: Path | str | None, as_of: str, stocks: dict[str, Stock]) -> None:
    if path is None:
        return
    head = {"as_of": as_of, "stocks": [[s.code, s.market, s.name, s.n, s.float_mv] for s in stocks.values()]}
    body = b"".join(col.tobytes() for s in stocks.values() for col in (s.dates, s.o, s.h, s.l, s.c, s.a))
    blob = MAGIC + zlib.compress(json.dumps(head, ensure_ascii=False).encode("utf-8") + b"\n" + body, 1)
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def load_saved(path: Path | str | None, as_of: str) -> dict[str, Stock] | None:
    """同一个交易日存下的整池；不是这一天的、读不了的都返回 None（重新下载）。"""
    try:
        blob = Path(path).read_bytes() if path is not None else b""
        if not blob.startswith(MAGIC):
            return None
        raw = zlib.decompress(blob[len(MAGIC):])
        cut = raw.index(b"\n")
        head = json.loads(raw[:cut].decode("utf-8"))
        if head.get("as_of") != as_of:
            return None
        out, pos = {}, cut + 1
        for code, market, name, n, mv in head["stocks"]:
            cols = []
            for typecode in "ifffff":
                col = array(typecode)
                size = col.itemsize * n
                col.frombytes(raw[pos:pos + size])
                pos += size
                cols.append(col)
            out[code] = Stock(code, market, name, *cols, float_mv=mv)
        return out
    except (OSError, ValueError, KeyError, zlib.error):
        return None


# ── 下载 ──────────────────────────────────────────────────────────

def load_pool(fetch, rows: list[dict], as_of: str, partial: str | None = None, progress=None,
              path: Path | str | None = None, days: int = POOL_DAYS, workers: int = 8) -> tuple[dict[str, Stock], dict]:
    """返回 ({代码: Stock}, 统计)。fetch(row, days) → 日线（等比复权）。
    取不到、今天没交易（停牌）、上市不满一年、成交太冷清的都不进池子。"""
    saved = load_saved(path, as_of)
    if saved is not None and len(saved) >= len(rows) * 0.5:
        return saved, {"wanted": len(rows), "loaded": len(saved), "failed": 0, "stale": 0, "short": 0, "thin": 0, "cached": True}

    def one(r):
        bars = fetch(r, days)
        if partial and bars and bars[-1].date == partial:
            bars = bars[:-1]                                # 今天还没走完的那根不用
        return bars

    out: dict[str, Stock] = {}
    failed = stale = short = thin = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [(r, ex.submit(one, r)) for r in rows]
        for i, (r, fut) in enumerate(futures, 1):
            if progress and (i % 20 == 0 or i == len(futures)):
                progress(i, len(futures))
            try:
                bars = fut.result()
            except Exception:
                failed += 1
                continue
            if not bars or bars[-1].date != as_of:
                stale += 1                                  # 停牌，或者这只的数据没更新到这一天
            elif len(bars) < MIN_BARS or not clean(bars):
                short += 1                                  # 上市不满一年，或者行情里有 0 这样的坏数据
            else:
                s = Stock.from_bars(bars, r["code"], r["market"], r.get("name", ""))
                if s.avg_amount(s.n - 1) < MIN_AMOUNT:
                    thin += 1                               # 成交太冷清
                else:
                    out[r["code"]] = s
    info = {"wanted": len(rows), "loaded": len(out), "failed": failed, "stale": stale, "short": short, "thin": thin, "cached": False}
    if out and failed <= len(rows) * 0.2:                   # 下载得不全的不存，下次重新来
        try:
            save_pool(path, as_of, out)
        except OSError:
            pass
    return out, info
