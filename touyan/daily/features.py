"""从日线里量出来的几样东西，以及「冷热分」。

冷热分量的是一只股票被追捧的程度。四样，全部来自日线，都是越高越「热」：
- 盘中拉升：近 60 个交易日「开盘到收盘」的累计涨幅。散户多在盘中追涨，盘中一路被买上去的股票，之后明显跑输；
- 放量：近 20 日成交股数 ÷ 近 250 日成交股数。突然热闹起来的股票，之后跑输；
- 量价同向：近 20 日里收盘价和成交股数的相关系数。越涨越放量是有人在追，之后跑输；
- 收在高位：近 20 日平均每天收在当天最低到最高之间的什么位置。天天尾盘被买上去的，之后跑输。
四样各自在全池里排名次，取平均，再排一次名次：100 = 最冷（最没人追），0 = 最热。

依据见 research/：最热的一成在 2005–2026 这 22 年里每一年都跑输同期随便买（60 天平均少赚 2%–3%）；
最冷的一成在两个十年里都跑赢。成交股数用「成交额 ÷ 复权价」来算，不受送转股和限售股解禁的影响。
"""

from __future__ import annotations

from array import array
from collections import deque
from math import log, sqrt

from .common import pct_rank
from .pool import Stock

MIN_T = 250                # 至少要有这么多根之前的日线
FIELDS = ("id60", "vabn", "pvv", "clv", "r1", "r5", "r20", "hi")
COLD_FIELDS = ("id60", "vabn", "pvv", "clv")


class Prep:
    """一只股票的前缀和：回看任意一天的指标都是 O(1)。只在算指标的时候建，用完就丢。"""

    __slots__ = ("s", "lin", "v1", "v2", "c1", "c2", "cv", "clv", "hi")

    def __init__(self, s: Stock, hi_window: int = 250):
        self.s = s
        n, c, o, h, l, a = s.n, s.c, s.o, s.h, s.l, s.a
        total = sum(a[i] / c[i] for i in range(n) if c[i] > 0)
        scale = total / n if total > 0 else 1.0           # 成交股数除以均值，免得平方后数字太大
        lin, v1, v2, c1, c2, cv, clv = [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0]
        for i in range(n):
            ci = c[i]
            v = a[i] / ci / scale if ci > 0 else 0.0
            lin.append(lin[-1] + (log(ci / o[i]) if ci > 0 and o[i] > 0 else 0.0))
            v1.append(v1[-1] + v)
            v2.append(v2[-1] + v * v)
            c1.append(c1[-1] + ci)
            c2.append(c2[-1] + ci * ci)
            cv.append(cv[-1] + ci * v)
            span = h[i] - l[i]
            clv.append(clv[-1] + ((ci - l[i]) / span if span > 0 else 0.5))
        self.lin, self.v1, self.v2, self.c1, self.c2, self.cv, self.clv = lin, v1, v2, c1, c2, cv, clv
        hi, window = [0.0] * n, deque()                    # 近 hi_window 根的最高价
        for i in range(n):
            while window and h[window[-1]] <= h[i]:
                window.pop()
            window.append(i)
            if window[0] <= i - hi_window:
                window.popleft()
            hi[i] = h[window[0]]
        self.hi = hi

    def id60(self, t: int, k: int = 60) -> float:
        return self.lin[t + 1] - self.lin[t + 1 - k]

    def vabn(self, t: int, short: int = 20, long: int = 250) -> float:
        base = (self.v1[t + 1] - self.v1[t + 1 - long]) / long
        return (self.v1[t + 1] - self.v1[t + 1 - short]) / short / base if base > 0 else 1.0

    def pvv(self, t: int, k: int = 20) -> float:
        a = t + 1 - k
        sx, sy = self.c1[t + 1] - self.c1[a], self.v1[t + 1] - self.v1[a]
        vx = self.c2[t + 1] - self.c2[a] - sx * sx / k
        vy = self.v2[t + 1] - self.v2[a] - sy * sy / k
        if vx <= 1e-12 or vy <= 1e-12:
            return 0.0
        return max(-1.0, min(1.0, (self.cv[t + 1] - self.cv[a] - sx * sy / k) / sqrt(vx * vy)))

    def clv20(self, t: int, k: int = 20) -> float:
        return (self.clv[t + 1] - self.clv[t + 1 - k]) / k

    def values(self, t: int) -> tuple[float, ...]:
        """按 FIELDS 的顺序。"""
        c = self.s.c
        return (self.id60(t), self.vabn(t), self.pvv(t), self.clv20(t), c[t] / c[t - 1] - 1, c[t] / c[t - 5] - 1,
                c[t] / c[t - 20] - 1, c[t] / self.hi[t] - 1 if self.hi[t] > 0 else 0.0)


class Cross:
    """某一天全池的横截面：每只股票的指标，以及排出来的冷热分。"""

    def __init__(self, day: int):
        self.day = day
        self.codes: list[str] = []
        self.t = array("i")                     # 这一天是各自的第几根
        self.col = {f: array("f") for f in FIELDS}
        self.cold: list[float] = []             # 0–100，越大越冷
        self.pos: dict[str, int] = {}

    def add(self, code: str, t: int, values: tuple[float, ...]) -> None:
        self.pos[code] = len(self.codes)
        self.codes.append(code)
        self.t.append(t)
        for f, v in zip(FIELDS, values):
            self.col[f].append(v)

    def rank(self) -> "Cross":
        if not self.codes:
            return self
        n = len(self.codes)
        ranks = [pct_rank(list(self.col[f]), higher_better=False) for f in COLD_FIELDS]
        self.cold = pct_rank([sum(r[i] for r in ranks) / len(ranks) for i in range(n)])
        return self

    def get(self, code: str) -> dict | None:
        i = self.pos.get(code)
        if i is None:
            return None
        out = {f: self.col[f][i] for f in FIELDS}
        out["t"] = self.t[i]
        out["cold"] = self.cold[i] if self.cold else None
        return out

    def __len__(self) -> int:
        return len(self.codes)


def crosses(stocks: dict[str, Stock], days: list[int]) -> dict[int, Cross]:
    """这些天各自的横截面。每只股票只建一次前缀和。当天没交易、之前的日线不够的不算在内。"""
    out = {d: Cross(d) for d in days}
    for code, s in stocks.items():
        hits = [(d, s.index(d)) for d in days]
        hits = [(d, t) for d, t in hits if t >= MIN_T]
        if not hits:
            continue
        prep = Prep(s)
        for d, t in hits:
            out[d].add(code, t, prep.values(t))
    for cross in out.values():
        cross.rank()
    return out


def oversold_score(cross: Cross) -> list[float]:
    """短期板块的排序分（0–100）：近 5 日跌得多、近 20 日跌得多、离一年高点远、没人追捧，四项名次的平均。"""
    r5 = pct_rank(list(cross.col["r5"]), higher_better=False)
    r20 = pct_rank(list(cross.col["r20"]), higher_better=False)
    hi = pct_rank(list(cross.col["hi"]), higher_better=False)
    return [(r5[i] + r20[i] + hi[i] + cross.cold[i]) / 4 for i in range(len(cross))]


# ── 长期板块用的几样慢指标 ──────────────────────────────────────────

def volatility(s: Stock, k: int = 250) -> float | None:
    """近 k 个交易日日涨跌幅的标准差（不够 150 根的不算）。"""
    a = max(1, s.n - k)
    rets = [s.c[i] / s.c[i - 1] - 1 for i in range(a, s.n) if s.c[i - 1] > 0]
    if len(rets) < 150:
        return None
    m = sum(rets) / len(rets)
    return sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))


def turnover(s: Stock, k: int = 250) -> float | None:
    """近 k 个交易日平均每天换手多少（成交股数 ÷ 流通股数）。流通市值没取到的不算。"""
    if not s.float_mv or s.n < 150 or s.c[-1] <= 0:
        return None
    a = max(0, s.n - k)
    shares = sum(s.a[i] / s.c[i] for i in range(a, s.n) if s.c[i] > 0) / (s.n - a)
    return shares * s.c[-1] / s.float_mv


def long_return(s: Stock, k: int = 600, min_bars: int = 500) -> float | None:
    """近 k 个交易日（约两年半）的涨幅；日线不够 min_bars 根的不算。"""
    if s.n < min_bars:
        return None
    base = s.c[max(0, s.n - 1 - k)]
    return s.c[-1] / base - 1 if base > 0 else None


def heat(stocks: dict[str, Stock], cross: Cross) -> dict[str, dict]:
    """「四种热」：一年波动最大的两成、换手最高的两成、被追捧（冷热分最低的两成）、两年半涨得最多的两成。
    长期板块不选这些——它们之后一两年是跑输的。返回 {代码: {vol, turn, long, cold, 各自的名次, kinds: [属于哪几种热]}}。"""
    codes = [c for i, c in enumerate(cross.codes) if cross.t[i] == stocks[c].n - 1]
    vol = [volatility(stocks[c]) for c in codes]
    turn = [turnover(stocks[c]) for c in codes]
    lng = [long_return(stocks[c]) for c in codes]
    rv, rt, rl = pct_rank(vol), pct_rank(turn), pct_rank(lng)
    out = {}
    for i, c in enumerate(codes):
        cold = cross.cold[cross.pos[c]]
        kinds = []
        if vol[i] is not None and rv[i] >= 80:
            kinds.append("波动大")
        if turn[i] is not None and rt[i] >= 80:
            kinds.append("换手高")
        if cold < 20:
            kinds.append("被追捧")
        if lng[i] is not None and rl[i] >= 80:
            kinds.append("两年半涨得多")
        out[c] = {"vol": vol[i], "turn": turn[i], "long": lng[i], "cold": cold, "vol_rank": rv[i], "turn_rank": rt[i], "long_rank": rl[i], "kinds": kinds}
    return out


def industry_trends(stocks: dict[str, Stock], industry: dict[str, str], calendar: list[int], long: int = 600, short: int = 125,
                    min_count: int = 8) -> dict[str, dict]:
    """各行业的长期走势：行业里的股票等权，和全部行业的平均比，看近 long 天（约两年半）和近 short 天（半年）谁强谁弱。

    - 长期走弱：两年半排在全部行业的后三成，最近半年也在后一半；
    - 长期走强：两年半排在前三成，最近半年也在前一半。
    检验下来（research/exp54–56）行业是强者恒强：长期走弱的行业之后一到三年继续落后，所以长期板块不从里面选。
    返回 {行业: {state: weak/strong/neutral, long, short（相对全部行业平均的超额）, long_rank, short_rank, count}}。
    """
    days = calendar[-(long + 1):]
    pos = {d: i for i, d in enumerate(days)}
    m = len(days)
    acc: dict[str, tuple[list[float], list[int]]] = {}
    members: dict[str, int] = {}
    for code, s in stocks.items():
        name = industry.get(code)
        if not name:
            continue
        members[name] = members.get(name, 0) + 1
        sums, counts = acc.setdefault(name, ([0.0] * m, [0] * m))
        for i in range(max(1, s.n - long), s.n):
            j = pos.get(s.dates[i])
            if j is not None and s.c[i - 1] > 0:
                sums[j] += s.c[i] / s.c[i - 1] - 1
                counts[j] += 1
    names = [k for k in acc if members[k] >= min_count]
    if len(names) < 10 or m < short + 20:
        return {}
    daily = {k: [acc[k][0][j] / acc[k][1][j] if acc[k][1][j] else 0.0 for j in range(m)] for k in names}
    market = [sum(daily[k][j] for k in names) / len(names) for j in range(m)]

    def excess(k: str, start: int) -> float:
        a = b = 1.0
        for j in range(start, m):
            a *= 1 + daily[k][j]
            b *= 1 + market[j]
        return a / b - 1

    lng = [excess(k, 1) for k in names]
    sht = [excess(k, m - short) for k in names]
    rl, rs = pct_rank(lng), pct_rank(sht)
    out = {}
    for i, k in enumerate(names):
        state = "weak" if rl[i] < 30 and rs[i] < 50 else "strong" if rl[i] >= 70 and rs[i] >= 50 else "neutral"
        out[k] = {"state": state, "long": lng[i], "short": sht[i], "long_rank": rl[i], "short_rank": rs[i], "count": members[k]}
    return out
