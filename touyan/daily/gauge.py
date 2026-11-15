"""大盘预估：收盘后先回答一个问题——接下来几天，适不适合出手。短期、中期两个板块都先看它。

做法是打分。下面每一条都是在 2005–2026 两个十年里分别检验过、方向一致的（数字见 evidence.py）：
- 市场刚有过大动作之后偏强：全市场放量、当天大涨或大跌、涨停或跌停很多、5 天跌了不少。
  大面积跌停（恐慌盘出尽）之后最强，记 2 分；
- 不温不火之后偏弱：涨跌不到 0.5% 的平淡日、缩量日，各扣 1 分；
- 日历：明天是月末最后一个或月初第一个交易日、明天是周一，加分；明天是周四，扣分。
分数 ≥3 的日子约占一成，之后 5 天全市场平均 +1.6%；分数 ≤−1 的日子占三成，之后 5 天平均 −0.5%。
同一套选股规则，只在分数高的日子用才有效，每天都用等于没用——所以「不出手」是这个板块最常见、也最重要的结论。

统计用的是股票池（全市场成交活跃的几千只）的等权平均，不是上证指数：上证指数被几只大盘股左右，
量不出「大多数股票」的状态。
"""

from __future__ import annotations

from datetime import date
from math import log

from . import evidence as ev
from . import tradingday as td
from .pool import Stock, day_text
from .sim import COST

GO, LIGHT = 3, 2
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
HOLD = 5
BUCKETS = (("≤ −1", -99, -1), ("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("≥ 3", 3, 99))


def to_date(d: int) -> date:
    return date(d // 10000, d // 100 % 100, d % 100)


class DayTable:
    """每个交易日全池的统计：几只在交易、平均涨跌、涨停跌停数、成交额，以及这一天收盘后随便买、拿 5 天的平均收益。"""

    def __init__(self, calendar: list[int]):
        n = len(calendar)
        self.calendar = calendar
        self.n, self.up, self.down = [0] * n, [0] * n, [0] * n
        self.sum_r, self.amount = [0.0] * n, [0.0] * n
        self.f5, self.f5n = [0.0] * n, [0] * n
        self.small_r, self.small_n, self.big_r, self.big_n = [0.0] * n, [0] * n, [0.0] * n, [0] * n

    def mean(self, j: int) -> float:
        return self.sum_r[j] / self.n[j] if self.n[j] else 0.0

    def after(self, j: int) -> float | None:
        """这一天收盘后在池子里随便买、拿 5 天的平均收益；还没走完的返回 None。"""
        return self.f5[j] / self.f5n[j] if self.n[j] and self.f5n[j] >= self.n[j] * 0.5 else None


def size_groups(stocks: dict[str, Stock]) -> tuple[set[str], set[str]]:
    """按流通市值：最小的四成算小盘，最大的两成算大盘。"""
    ranked = sorted((s for s in stocks.values() if s.float_mv), key=lambda s: s.float_mv)
    n = len(ranked)
    return {s.code for s in ranked[:int(n * 0.4)]}, {s.code for s in ranked[int(n * 0.8):]}


def build_table(stocks: dict[str, Stock], calendar: list[int]) -> DayTable:
    tb = DayTable(calendar)
    pos = {d: i for i, d in enumerate(calendar)}
    small, big = size_groups(stocks)
    for s in stocks.values():
        c, o, a, dates, n = s.c, s.o, s.a, s.dates, s.n
        edge = s.limit - 0.004
        group = 1 if s.code in small else 2 if s.code in big else 0
        for i in range(1, n):
            j = pos.get(dates[i])
            if j is None or c[i - 1] <= 0:
                continue
            r = c[i] / c[i - 1] - 1
            tb.n[j] += 1
            tb.sum_r[j] += r
            tb.amount[j] += a[i]
            if r >= edge and c[i] >= s.h[i] * 0.9995:
                tb.up[j] += 1
            elif r <= -edge and c[i] <= s.l[i] * 1.0005:
                tb.down[j] += 1
            if group == 1:
                tb.small_r[j] += r
                tb.small_n[j] += 1
            elif group == 2:
                tb.big_r[j] += r
                tb.big_n[j] += 1
            e = i + 1
            if e + HOLD < n and o[e] > 0 and o[e] / c[i] - 1 < edge:      # 第二天开盘买得进，并且已经走完 5 天
                tb.f5[j] += c[e + HOLD] / o[e] * (1 - COST) - 1
                tb.f5n[j] += 1
    return tb


def measure(tb: DayTable, j: int) -> dict:
    """第 j 个交易日收盘时量到的东西。"""
    n = tb.n[j] or 1
    base = [tb.amount[k] for k in range(max(0, j - 20), j) if tb.amount[k] > 0]
    change5 = 1.0
    for k in range(max(0, j - 4), j + 1):
        change5 *= 1 + tb.mean(k)
    return {"change": tb.mean(j), "amount_ratio": tb.amount[j] / (sum(base) / len(base)) if len(base) >= 10 else None,
            "limit_up": tb.up[j], "limit_down": tb.down[j], "up_share": tb.up[j] / n, "down_share": tb.down[j] / n,
            "change5": change5 - 1, "pool": tb.n[j]}


def score_parts(m: dict, nxt: date, window: str) -> list[dict]:
    """每一项：成立没有、几分、今天的读数。"""
    ratio = m["amount_ratio"]
    pc = lambda x: f"{x * 100:+.1f}%"
    rows = [
        ("vol_up", "放量", 1, ratio is not None and ratio >= 1.15,
         f"全市场成交额是近 20 日均值的 {ratio:.2f} 倍" if ratio is not None else "成交额对比不出来", "≥1.15 倍算放量"),
        ("big_up", "大涨日", 1, m["change"] >= 0.015, f"全市场平均 {pc(m['change'])}", "平均涨 1.5% 以上"),
        ("big_dn", "大跌日", 1, m["change"] <= -0.015, f"全市场平均 {pc(m['change'])}", "平均跌 1.5% 以上"),
        ("dn_many", "大面积跌停", 2, m["down_share"] >= 0.02,
         f"{m['limit_down']} 只跌停，占 {m['down_share'] * 100:.1f}%", "跌停占 2% 以上：恐慌盘集中卖出，之后几天反弹最强"),
        ("up_many", "涨停多", 1, m["up_share"] >= 0.02, f"{m['limit_up']} 只涨停，占 {m['up_share'] * 100:.1f}%", "涨停占 2% 以上"),
        ("drop5", "5 天跌得多", 1, m["change5"] <= -0.04, f"近 5 天全市场平均 {pc(m['change5'])}", "5 天平均跌 4% 以上"),
        ("month", "月末月初", 1, bool(window),
         "明天是" + ("月末最后一个交易日" if window == "last" else "月初第一个交易日") if window else "明天不在月末月初",
         "月末最后一天到下月第一天，22 年里指数平均 +0.5% 以上"),
        ("mon", "明天周一", 1, nxt.weekday() == 0, f"明天是{WEEKDAYS[nxt.weekday()]}", "周一历来偏强"),
        ("flat", "平淡日", -1, abs(m["change"]) < 0.005, f"全市场平均 {pc(m['change'])}", "涨跌不到 0.5%：没人关注的日子，之后偏弱"),
        ("vol_dn", "缩量", -1, ratio is not None and ratio <= 0.85,
         f"全市场成交额是近 20 日均值的 {ratio:.2f} 倍" if ratio is not None else "成交额对比不出来", "≤0.85 倍算缩量"),
        ("thu", "明天周四", -1, nxt.weekday() == 3, f"明天是{WEEKDAYS[nxt.weekday()]}", "周四历来偏弱"),
    ]
    return [{"key": k, "label": label, "points": pts, "on": bool(on), "detail": detail, "rule": rule}
            for k, label, pts, on, detail, rule in rows]


def total(parts: list[dict]) -> int:
    return sum(p["points"] for p in parts if p["on"])


def stance_of(score: int) -> tuple[str, str, str]:
    """(档位, 一句话结论, 依据)。"""
    if score >= GO:
        return "go", "可以出手", ("分数 ≥3 的日子约占一成。之后 5 个交易日，全市场平均 +1.7%（近十年）/ +1.6%（更早的十年），"
                              "六成半的日子是涨的。")
    if score == LIGHT:
        return "light", "可以轻仓", ("分数 2 的日子，之后 5 个交易日全市场平均 +0.4%（近十年）/ +0.8%（更早的十年），"
                                 "有一点优势但不大。用小仓位，或者等分数到 3。")
    if score >= 0:
        return "wait", "不出手", ("分数 0–1 的日子，之后 5 个交易日全市场平均在 0 附近，扣掉手续费没有优势。"
                               "短线不出手，等分数到 2 以上。")
    return "avoid", "不出手", ("分数 ≤−1 的日子占三成。之后 5 个交易日全市场平均 −0.5%，"
                            "近十年里这样的日子做短线，十年有九年是亏的。空仓。")


def evidence_table(score: int) -> list[dict]:
    rows = []
    for (label, lo, hi), new, old in zip(BUCKETS, ev.SCORE_TABLE["new"], ev.SCORE_TABLE["old"]):
        rows.append({"bucket": label, "current": lo <= score <= hi,
                     "new": {"days": new[1], "share": new[2], "after": new[3], "up": new[4]},
                     "old": {"days": old[1], "share": old[2], "after": old[3], "up": old[4]}})
    return rows


def history(tb: DayTable, start: int = 25) -> list[dict]:
    """过去每一天的分数，以及那天收盘后随便买、拿 5 天的结果（用实际的日历，不用推算）。"""
    cal = tb.calendar
    out = []
    for j in range(start, len(cal) - 2):
        after = tb.after(j)
        if after is None or tb.n[j] < 50:
            continue
        d, nxt, nxt2 = to_date(cal[j]), to_date(cal[j + 1]), to_date(cal[j + 2])
        out.append({"date": day_text(cal[j]), "score": total(score_parts(measure(tb, j), nxt, td.month_window(d, nxt, nxt2))), "after": after})
    return out


def recent_check(hist: list[dict]) -> dict:
    """用池子自己最近两年多的行情再核对一遍：各分数档之后 5 天的实际结果。"""
    rows = []
    for label, lo, hi in BUCKETS:
        sub = [h["after"] for h in hist if lo <= h["score"] <= hi]
        rows.append({"bucket": label, "days": len(sub), "after": sum(sub) / len(sub) if sub else None,
                     "up": sum(1 for x in sub if x > 0) / len(sub) if sub else None})
    signals = [h for h in hist if h["score"] >= LIGHT][-12:]
    return {"days": len(hist), "from": hist[0]["date"] if hist else "", "to": hist[-1]["date"] if hist else "",
            "rows": rows, "signals": signals[::-1]}


def style(tb: DayTable, j: int, m: dict, nxt: date) -> dict:
    """大盘股还是小盘股。"""
    lead = 0.0
    for k in range(max(0, j - 4), j + 1):
        if tb.small_n[k] and tb.big_n[k]:
            lead += log(1 + tb.small_r[k] / tb.small_n[k]) - log(1 + tb.big_r[k] / tb.big_n[k])
    notes, score = [], 0
    if lead >= 0.013:
        score += 1
        notes.append(f"近 5 天小盘股比大盘股多涨 {lead * 100:.1f} 个点（小盘在领涨，这种领先通常会延续）")
    if m["change"] >= 0.01 or m["up_share"] >= 0.018:
        score += 1
        notes.append("今天大涨或涨停多（市场活跃时小盘股弹性更大）")
    if m["up_share"] < 0.007:
        score -= 1
        notes.append(f"今天只有 {m['limit_up']} 只涨停（市场冷清时大盘股更稳）")
    if nxt.month == 2:
        score += 1
        notes.append("2 月历来是小盘股最强的月份")
    elif nxt.month in (4, 6, 12):
        score -= 1
        notes.append(f"{nxt.month} 月历来小盘股偏弱（财报披露、年中年末资金紧）")
    label = "小盘占优" if score >= 1 else "大盘更稳" if score <= -1 else "不明显"
    advice = {"小盘占优": "选股和 ETF 都可以偏向中小盘（如中证1000）",
              "大盘更稳": "偏向大盘股、宽基（如沪深300），小盘股少碰",
              "不明显": "大小盘没有明显偏向"}[label]
    return {"label": label, "score": score, "lead5": lead, "notes": notes or ["没有明显的信号"], "advice": advice,
            "evidence": ev.FACTS["style"]}


def hot_sectors(stocks: dict[str, Stock], industry: dict[str, str], top: int = 3) -> list[dict]:
    """今天涨停最集中的板块（板块里至少 8 只、涨停至少 3 只且占 5% 以上）。这些板块今天不选。"""
    count, hits = {}, {}
    for code, s in stocks.items():
        name = industry.get(code)
        if not name:
            continue
        count[name] = count.get(name, 0) + 1
        if s.limit_up(s.n - 1):
            hits[name] = hits.get(name, 0) + 1
    rows = [{"name": k, "limit_up": v, "total": count[k], "share": v / count[k]} for k, v in hits.items()
            if count[k] >= 8 and v >= 3 and v / count[k] >= 0.05]
    return sorted(rows, key=lambda r: -r["share"])[:top]


def sector_moves(stocks: dict[str, Stock], industry: dict[str, str], min_count: int = 8) -> list[dict]:
    """各行业今天的平均涨跌（%，从高到低）。用池子里的股票自己算，不依赖行情网站的板块接口。"""
    total, count = {}, {}
    for code, s in stocks.items():
        name = industry.get(code)
        if name and s.n >= 2:
            total[name] = total.get(name, 0.0) + s.ret(s.n - 1)
            count[name] = count.get(name, 0) + 1
    rows = [{"name": k, "change_pct": round(total[k] / count[k] * 100, 2), "count": count[k]} for k in total if count[k] >= min_count]
    return sorted(rows, key=lambda r: -r["change_pct"])


def compute(stocks: dict[str, Stock], calendar: list[int], industry: dict[str, str] | None = None) -> dict:
    """今天的大盘预估。calendar：到今天为止的交易日（20261113 这样的整数，升序）。"""
    tb = build_table(stocks, calendar)
    j = len(calendar) - 1
    today = to_date(calendar[j])
    nxt = td.next_trading_day(today)
    window = td.month_window(today, nxt)
    m = measure(tb, j)
    parts = score_parts(m, nxt, window)
    score = total(parts)
    key, label, basis = stance_of(score)
    hist = history(tb)
    wait = td.trading_days_until_month_window(today)
    return {
        "score": score, "stance": key, "label": label, "basis": basis, "parts": parts,
        "facts": {**m, "next_day": nxt.isoformat(), "next_weekday": WEEKDAYS[nxt.weekday()], "window": window},
        "table": evidence_table(score),
        "recent": recent_check(hist),
        "style": style(tb, j, m, nxt),
        "hot_sectors": hot_sectors(stocks, industry or {}),
        "next_window": {"days": wait, "text": "今天收盘后就是月末月初的窗口" if wait == 0 else f"离下一个月末月初窗口还有 {wait} 个交易日"},
        "history": hist,
    }
