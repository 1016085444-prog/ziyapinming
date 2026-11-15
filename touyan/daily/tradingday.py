"""交易日历：下一个交易日是哪天、是不是月末月初。

大盘预估要用到两件「明天」的事：明天是周几、明天是不是月末最后一个或月初第一个交易日。
2024–2026 年的休市日是从真实行情里核对出来的；之后的年份官方还没公布，
按周末 + 元旦 + 春节（除夕到初六）+ 五一 + 国庆来估，清明、端午、中秋这些单日假期估不到，
偶尔会差一天。交易所每年年底公布下一年的安排，届时把 HOLIDAYS 补上即可。
"""

from __future__ import annotations

from datetime import date, timedelta

# 周一到周五里休市的日子（MMDD）
HOLIDAYS = {
    2024: "0101 0209 0212 0213 0214 0215 0216 0404 0405 0501 0502 0503 0610 0916 0917 1001 1002 1003 1004 1007",
    2025: "0101 0128 0129 0130 0131 0203 0204 0404 0501 0502 0505 0602 1001 1002 1003 1006 1007 1008",
    2026: "0101 0102 0216 0217 0218 0219 0220 0223 0406 0501 0504 0505 0619 0925 1001 1002 1005 1006 1007",
}
SPRING_FESTIVAL = {2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23)}   # 正月初一
_closed: dict[int, set[date]] = {}


def closed_days(year: int) -> set[date]:
    if year not in _closed:
        if year in HOLIDAYS:
            days = {date(year, int(x[:2]), int(x[2:])) for x in HOLIDAYS[year].split()}
        else:
            days = {date(year, 1, 1)} | {date(year, 5, d) for d in (1, 2, 3)} | {date(year, 10, d) for d in range(1, 8)}
            if year in SPRING_FESTIVAL:
                first = date(year, *SPRING_FESTIVAL[year])
                days |= {first + timedelta(days=k) for k in range(-1, 7)}
        _closed[year] = days
    return _closed[year]


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in closed_days(d.year)


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def month_window(d: date, nxt: date | None = None, after: date | None = None) -> str:
    """d 之后的那个交易日（nxt）是月末最后一个交易日返回 "last"，是月初第一个返回 "first"，都不是返回 ""。
    nxt、after（再下一个交易日）已知时直接用（回看历史），不知道就按日历推。"""
    nxt = nxt or next_trading_day(d)
    if nxt.month != d.month:
        return "first"
    after = after or next_trading_day(nxt)
    return "last" if after.month != nxt.month else ""


def trading_days_until_month_window(d: date, limit: int = 30) -> int:
    """还要过几个交易日，收盘后看到的「明天」才是月末最后一个交易日（0 = 今天收盘后就是）。"""
    for k in range(limit):
        if month_window(d) == "last":
            return k
        d = next_trading_day(d)
    return limit
