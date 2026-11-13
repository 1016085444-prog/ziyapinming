"""核心池：市值最大的几百只股票的日 K 线。短期、中期两个板块从这里找机会，也用它检验方法。

为什么用一个固定的池子，而不是「今天看着不错的那几十只」：检验方法要回到过去每一天去看当时有没有信号。
只拿今天的候选回头检验，结果必然好看——它们正是因为过去走得好才入选的。
池子按市值选，和今天有没有信号无关；检验时再拿「同一批股票随便哪天买」做对照，
把这批股票本身涨得好的部分扣掉，剩下的才算方法的功劳。
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

from market import symbols
from market.models import Bar
from market.router import bars_to_rows, rows_to_bars
from quant import indicators as ind

from .common import limit_pct, tradable

POOL_SIZE = 300
POOL_DAYS = 380            # 约一年半；腾讯证券一次请求就能取全
MIN_BARS = 200


def _usable(rows: list[dict], field: str) -> bool:
    """这一列是不是真有数据（盘中倒推的快照没有成交额；接口变了某列可能全空）。"""
    have = sum(1 for r in rows if r.get(field))
    return have >= len(rows) * 0.5


def build_pool(rows: list[dict], size: int = POOL_SIZE) -> list[dict]:
    """可交易、成交够活跃的股票里，市值最大的 size 只。"""
    rows = [r for r in rows if tradable(r)]
    if _usable(rows, "amount"):
        rows = [r for r in rows if (r.get("amount") or 0) >= 1e8]
    key = "total_mv" if _usable(rows, "total_mv") else "amount"
    return sorted((r for r in rows if r.get(key)), key=lambda r: -r[key])[:size]


def _prefix(values) -> list[float]:
    out, total = [0.0], 0.0
    for v in values:
        total += v
        out.append(total)
    return out


class Series:
    """一只股票（或 ETF）的日线。预先算好前缀和，回看任意一段的统计都是 O(1)。"""

    def __init__(self, bars: list[Bar], code: str = "", market: str = "SH", name: str = "", limit: float | None = None):
        n = len(bars)
        self.code, self.market, self.name, self.n = code, market, name, n
        self.dates = [b.date for b in bars]
        self.o = [b.open for b in bars]
        self.h = [b.high for b in bars]
        self.l = [b.low for b in bars]
        self.c = [b.close for b in bars]
        self.v = [b.volume or 0.0 for b in bars]
        self.limit = limit if limit is not None else limit_pct(code, market)
        edge = self.limit - 0.004
        r, lin, lon = [0.0] * n, [0.0] * n, [0.0] * n
        up, down = [0] * n, [0] * n
        for i in range(1, n):
            pc, o, c = self.c[i - 1], self.o[i], self.c[i]
            if pc > 0 and o > 0 and c > 0:
                r[i] = c / pc - 1
                lon[i] = math.log(o / pc)            # 隔夜：昨收 → 今开
                lin[i] = math.log(c / o)             # 盘中：今开 → 今收
                up[i] = 1 if r[i] >= edge else 0
                down[i] = 1 if r[i] <= -edge else 0
        self.r, self.lin, self.lon = r, lin, lon
        self.p_r, self.p_r2 = _prefix(r), _prefix(x * x for x in r)
        self.p_lin, self.p_v = _prefix(lin), _prefix(self.v)
        self.p_up, self.p_down = _prefix(up), _prefix(down)
        self.p_pos = _prefix(1 if x > 0 else 0 for x in r)
        y = [math.log(c) if c > 0 else 0.0 for c in self.c]
        self.p_y, self.p_y2 = _prefix(y), _prefix(v * v for v in y)
        self.p_iy = _prefix(i * v for i, v in enumerate(y))

    @staticmethod
    def span(p: list[float], a: int, b: int) -> float:
        """第 a 到第 b 根（含两端）的合计。"""
        return p[b + 1] - p[a]

    def ret(self, t: int, k: int) -> float:
        return self.c[t] / self.c[t - k] - 1

    def sigma(self, t: int, window: int = 120, skip: int = 5) -> float | None:
        """日涨跌幅的标准差：取 t 之前 window 天，跳过最近 skip 天（不让这次下跌本身把波动抬高）。"""
        b = t - skip
        a = b - window + 1
        if a < 1:
            return None
        s1, s2 = self.span(self.p_r, a, b), self.span(self.p_r2, a, b)
        var = (s2 - s1 * s1 / window) / (window - 1)
        return math.sqrt(var) if var > 0 else None

    def intraday_share(self, t: int, k: int) -> float | None:
        """最近 k 天的跌幅里，有多少是盘中跌出来的（其余是隔夜跳空）。只在下跌时有意义。"""
        total = math.log(self.c[t] / self.c[t - k])
        return self.span(self.p_lin, t - k + 1, t) / total if total < 0 else None

    def worst_gap(self, t: int, k: int) -> float:
        return min(math.exp(self.lon[i]) - 1 for i in range(t - k + 1, t + 1))

    def limit_days(self, t: int, k: int) -> tuple[int, int]:
        """最近 k 天里涨停、跌停各几天。"""
        return (int(self.span(self.p_up, t - k + 1, t)), int(self.span(self.p_down, t - k + 1, t)))

    def clv(self, t: int) -> float:
        """收盘在当天最低到最高之间的位置，0 = 收在最低，1 = 收在最高。"""
        span = self.h[t] - self.l[t]
        return (self.c[t] - self.l[t]) / span if span > 0 else 0.5

    def avg_vol(self, t: int, k: int) -> float:
        return self.span(self.p_v, t - k + 1, t) / k

    def up_ratio(self, t: int, k: int) -> float:
        return self.span(self.p_pos, t - k + 1, t) / k

    def max_gain(self, t: int, k: int) -> float:
        return max(self.r[t - k + 1:t + 1])

    def trend(self, t: int, k: int) -> tuple[float, float]:
        """最近 k 天对数价格对时间的直线拟合：(R²，每天的斜率)。R² 越接近 1，走得越像一条直线。"""
        a, b = t - k + 1, t
        sx = (a + b) * k / 2
        sxx = (b * (b + 1) * (2 * b + 1) - (a - 1) * a * (2 * a - 1)) / 6
        sy, syy, sxy = self.span(self.p_y, a, b), self.span(self.p_y2, a, b), self.span(self.p_iy, a, b)
        cov, var_x, var_y = sxy - sx * sy / k, sxx - sx * sx / k, syy - sy * sy / k
        if var_x <= 0 or var_y <= 1e-12:
            return 0.0, 0.0
        return min(1.0, cov * cov / (var_x * var_y)), cov / var_x


def clean(bars: list[Bar]) -> bool:
    """开高低收都是正数。个别数据源偶尔会给出 0，带着它算涨跌幅会出错。"""
    return all(b.open > 0 and b.close > 0 and b.high > 0 and b.low > 0 for b in bars)


def regime_by_date(bench: list[Bar]) -> dict[str, str]:
    """每个交易日的市场环境（只看沪深300 的走势）：三项都好算偏强，三项都差算偏弱，其余算震荡。"""
    closes = [b.adj_close for b in bench]
    ma20, ma60 = ind.sma(closes, 20), ind.sma(closes, 60)
    out = {}
    for i in range(60, len(bench)):
        score = ((1 if closes[i] >= ma20[i] else -1) + (1 if ma20[i] >= ma60[i] else -1)
                 + (1 if closes[i] > closes[i - 20] else -1))
        out[bench[i].date] = "偏强" if score == 3 else "偏弱" if score == -3 else "震荡"
    return out


def load_bars(router, cache, key: str, name: str, kind: str, as_of: str, partial: str | None, days: int) -> list[Bar]:
    """取一只的日线。同一个交易日里取过就不再取（重新生成、自动任务之后手动再点，都不用重新下载）。"""
    ck = f"poolk:{key}:{days}"
    hit = cache.get_stale(ck, 6 * 86400)
    if hit and hit[0].get("as_of") == as_of:
        return rows_to_bars(hit[0]["rows"])
    inst = symbols.from_key(key, kind, name)
    bars, _ = router.series(inst, days)
    if partial and bars and bars[-1].date == partial:
        bars = bars[:-1]                                   # 今天还没走完的那根不用
    if bars and bars[-1].date == as_of:
        cache.set(ck, {"as_of": as_of, "rows": bars_to_rows(bars)})
    return bars


def load_pool(router, cache, rows: list[dict], as_of: str, partial: str | None, progress=None,
              days: int = POOL_DAYS) -> tuple[dict[str, Series], dict]:
    """返回 ({代码: Series}, 统计)。取不到、停牌、上市太短的都不进池子。"""
    def one(r):
        return load_bars(router, cache, f"{r['market']}:{r['code']}", r.get("name", ""), "stock", as_of, partial, days)

    out: dict[str, Series] = {}
    failed = stale = short = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [(r, ex.submit(one, r)) for r in rows]
        for i, (r, fut) in enumerate(futures, 1):
            if progress and (i % 10 == 0 or i == len(futures)):
                progress(i, len(futures))
            try:
                bars = fut.result()
            except Exception:
                failed += 1
                continue
            if not bars or bars[-1].date != as_of:
                stale += 1                                  # 停牌，或者这只的数据没更新到这一天
            elif len(bars) < MIN_BARS or not clean(bars):
                short += 1                                  # 上市太短，或者行情里有 0 这样的坏数据
            else:
                out[r["code"]] = Series(bars, r["code"], r["market"], r.get("name", ""))
    return out, {"wanted": len(rows), "loaded": len(out), "failed": failed, "stale": stale, "short": short}
