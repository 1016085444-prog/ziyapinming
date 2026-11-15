"""腾讯证券：A 股 / 港股日 K 线与行情快照。东方财富被限流时的备用数据源。

接口取自 akshare 1.20.x 的 stock_zh_a_hist_tx / stock_hk_daily 实现：
单次最多返回 640 根 K 线，所以按约一年半一段分段请求。

两种复权：
- kline()：腾讯自己的「前复权」。它是减法复权——除权日之前的价格统一减去每股分红。画图、看最近的走势没问题，
  但分红累计多了以后，早年的价格被减得很低，拿它算涨跌幅会被放大（茅台 2016 年的前复权价只有二十几元）。
- kline_true()：等比复权。用不复权价和行情里自带的除权除息记录，把除权日之前的价格统一乘一个系数，
  每天的涨跌幅和当时实际发生的一样。每日精选要拿历史涨跌幅做统计，用这一种。
"""

from __future__ import annotations

import json
import random
import re
from datetime import date, timedelta

from market import net
from market.eastmoney import num
from market.models import Bar, Quote
from market.net import NoData

A_KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
HK_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
QUOTE_URL = "https://qt.gtimg.cn/q={symbol}"


def _segments(days: int) -> list[tuple[str, str]]:
    """把「最近 days 个交易日」拆成若干 ≤ 1.6 年的日期段（每段远小于 640 根）。"""
    calendar_days = int(days * 365 / 245) + 10
    end = date.today()
    start = end - timedelta(days=calendar_days)
    out = []
    cursor = start
    while cursor < end:
        seg_end = min(end, cursor + timedelta(days=580))
        out.append((cursor.isoformat(), seg_end.isoformat()))
        cursor = seg_end + timedelta(days=1)
    return out


def parse_kline_text(text: str, symbol: str) -> list[Bar]:
    """响应形如 kline_dayqfq={"code":0,"data":{"sh600519":{"qfqday":[[日期,开,收,高,低,量,...]]}}}。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise NoData("腾讯行情返回格式无法识别")
    payload = json.loads(text[start:end + 1])
    node = ((payload.get("data") or {}).get(symbol)) or {}
    rows = node.get("qfqday") or node.get("day") or node.get("hfqday") or []
    # 科创板与指数的成交量单位是「股」，其余 A 股是「手」；统一成手，和东方财富一致
    divisor = 100 if symbol.startswith(("sh688", "sh000", "sz399")) else 1
    bars: list[Bar] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        o, c, h, lo, v = num(row[1]), num(row[2]), num(row[3]), num(row[4]), num(row[5])
        if None in (o, c, h, lo) or c <= 0:
            continue
        amount = num(row[8]) if len(row) > 8 else None
        bars.append(Bar(
            date=str(row[0])[:10], open=o, high=h, low=lo, close=c,
            volume=(v or 0.0) / divisor if symbol[:2] in ("sh", "sz", "bj") else (v or 0.0),
            turnover=num(row[7]) if len(row) > 7 else None,
            amount=amount * 10000 if amount is not None else None,
        ))
    return bars


def kline(symbol: str, days: int = 800) -> list[Bar]:
    """symbol 形如 sh600519 / sz000001 / hk00700。返回按日期升序去重的 K 线。"""
    hk = symbol.startswith("hk")
    url = HK_KLINE_URL if hk else A_KLINE_URL
    merged: dict[str, Bar] = {}
    for seg_start, seg_end in _segments(days):
        params = {
            "_var": f"kline_dayqfq{seg_start[:4]}",
            "param": f"{symbol},day,{seg_start},{seg_end},640,qfq",
            "r": f"{random.random():.16f}",
        }
        resp = net.get(url, params=params, headers={"Referer": "https://gu.qq.com/"})
        for bar in parse_kline_text(resp.text, symbol):
            merged[bar.date] = bar
    if not merged:
        raise NoData("腾讯行情没有该品种的 K 线数据")
    return [merged[d] for d in sorted(merged)][-days:]


# ── 等比复权 ──────────────────────────────────────────────────────

_CASH = re.compile(r"10派([\d.]+)元")
_BONUS = re.compile(r"10(?:送|转增?)([\d.]+)股")
MAX_BARS = 640


def parse_dividend(text: str) -> tuple[float, float] | None:
    """「10转8股, 10派25.2元」→ (每股派息 2.52, 每股送转 0.8)。配股等没有文字内容的返回 None。"""
    cash = sum(float(x) for x in _CASH.findall(text or "")) / 10
    bonus = sum(float(x) for x in _BONUS.findall(text or "")) / 10
    return (cash, bonus) if cash or bonus else None


def parse_raw_kline(text: str, symbol: str) -> list[list]:
    """原样取出 K 线行：[日期, 开, 收, 高, 低, 量, {除权除息}, 换手率%, 成交额(万元), ...]。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise NoData("腾讯行情返回格式无法识别")
    data = json.loads(text[start:end + 1]).get("data")
    node = data.get(symbol) if isinstance(data, dict) else None
    rows = (node or {}).get("day") or (node or {}).get("qfqday") or []
    return [r for r in rows if isinstance(r, list) and len(r) >= 6]


def _fit_ref(q_seg: list[float], p_seg: list[float], q_prev: float) -> float | None:
    """除权日之后那一段里，不复权价 p 和腾讯前复权价 q 是一条直线 p = a·q + b；
    除权日的参考价就是 a·q(前一天) + b。配股这类没有文字内容的除权只能这样反推。"""
    n = len(q_seg)
    if n < 3 or max(q_seg) - min(q_seg) < 0.02:
        return None
    mq, mp = sum(q_seg) / n, sum(p_seg) / n
    var = sum((q - mq) ** 2 for q in q_seg)
    a = sum((q - mq) * (p - mp) for q, p in zip(q_seg, p_seg)) / var
    b = mp - a * mq
    if max(abs(p - (a * q + b)) / p for q, p in zip(q_seg, p_seg)) > 0.012:
        return None
    return a * q_prev + b


def adjust_factors(closes: list[float], events: dict[int, str], qfq: list[float | None] | None = None,
                   max_move: float = 0.31) -> tuple[list[float], list[int]]:
    """每一天的等比复权系数（最后一天为 1），以及还原不了的除权日下标。

    events: {除权日下标: 分红送转文字}。先按文字算参考价 (前收盘 − 每股派息) / (1 + 每股送转)；
    文字缺失、或者算出来当天涨跌超出涨跌停的（偶尔漏记送转），用 qfq（同一批日期的腾讯前复权收盘）反推；
    两样都不行，就把除权日当天的涨跌按 0 处理——不让一个假的跳空混进统计里。
    """
    n = len(closes)
    factors = [1.0] * n
    unresolved: list[int] = []
    cuts = sorted(k for k in events if 0 < k < n)
    scale = 1.0
    last = n
    for k in reversed(cuts):                      # 从后往前：每过一个除权日，系数乘上 参考价 / 前收盘
        for i in range(k, last):
            factors[i] = scale
        prev, cur = closes[k - 1], closes[k]
        ref = None
        parsed = parse_dividend(events[k])
        if parsed:
            ref = (prev - parsed[0]) / (1 + parsed[1])
        ok = ref is not None and 0.05 * prev < ref <= prev * 1.001 and abs(cur / ref - 1) <= max_move
        if not ok and qfq is not None and qfq[k - 1] is not None:
            nxt = min((c for c in cuts if c > k), default=n)
            seg = [(qfq[i], closes[i]) for i in range(k, nxt) if qfq[i] is not None]
            ref = _fit_ref([q for q, _ in seg], [p for _, p in seg], qfq[k - 1]) if seg else None
            ok = ref is not None and 0.05 * prev < ref <= prev * 1.02 and abs(cur / ref - 1) <= max_move
        if not ok:
            ref = cur
            unresolved.append(k)
        scale *= ref / prev
        last = k
    for i in range(0, last):
        factors[i] = scale
    return factors, unresolved


def _fetch_rows(symbol: str, days: int, fq: str) -> list[list]:
    params = {"param": f"{symbol},day,,{date.today().isoformat()},{min(days, MAX_BARS)},{fq}",
              "r": f"{random.random():.16f}"}
    resp = net.get(A_KLINE_URL, params=params, headers={"Referer": "https://gu.qq.com/"})
    return parse_raw_kline(resp.text, symbol)


def dividend_info(closes: list[float], events: dict[int, str], factors: list[float], window: int = 250) -> dict:
    """最近一年、再往前一年的现金分红（每股，折成今天的股数口径），以及按最新收盘价算的股息率。

    events: {除权日下标: 分红送转文字}。除权日那天的每股派息是按除权前的股数说的，乘上前一天的复权系数就折成了今天的口径。
    """
    n = len(closes)
    recent = earlier = 0.0
    for k, text in events.items():
        parsed = parse_dividend(text) if 0 < k < n else None
        if not parsed or parsed[0] <= 0:
            continue
        cash = parsed[0] * factors[k - 1]
        if k >= n - window:
            recent += cash
        elif k >= n - 2 * window:
            earlier += cash
    return {"div12": round(recent, 4), "div_prev": round(earlier, 4), "yield": recent / closes[-1] if closes and closes[-1] > 0 else None}


def kline_true(symbol: str, days: int = MAX_BARS) -> list[Bar]:
    """A 股最近 days（≤640）根日线，等比复权。开高低收是复权价，成交量、成交额、换手率是当天的实际值。"""
    return kline_true_ex(symbol, days)[0]


def kline_true_ex(symbol: str, days: int = MAX_BARS) -> tuple[list[Bar], dict]:
    """同 kline_true，另外返回分红信息（见 dividend_info）——除权记录本来就在这份行情里，不用另外去取。"""
    rows = [r for r in _fetch_rows(symbol, days, "") if num(r[2])]
    if not rows:
        raise NoData("腾讯行情没有该品种的 K 线数据")
    closes = [num(r[2]) for r in rows]
    events = {i: (r[6].get("FHcontent") or "") for i, r in enumerate(rows)
              if len(r) > 6 and isinstance(r[6], dict) and r[6]}
    # 除权日当天的涨跌不可能超出涨跌停太多；超出了说明文字漏记了送转，要用前复权价反推
    limit = 0.30 if symbol.startswith("bj") else 0.20 if symbol.startswith(("sh688", "sh689", "sz30")) else 0.10
    factors, unresolved = adjust_factors(closes, events, max_move=limit + 0.02)
    if unresolved:                                 # 少数情况（配股、漏记送转）：再取一次前复权价来反推
        try:
            by_date = {r[0]: num(r[2]) for r in _fetch_rows(symbol, days, "qfq")}
            factors, _ = adjust_factors(closes, events, [by_date.get(r[0]) for r in rows], max_move=limit + 0.02)
        except net.SourceError:
            pass
    divisor = 100 if symbol.startswith(("sh688", "sh689", "sh000", "sz399")) else 1
    bars: list[Bar] = []
    for r, f in zip(rows, factors):
        o, c, h, lo = num(r[1]), num(r[2]), num(r[3]), num(r[4])
        if None in (o, c, h, lo) or min(o, c, h, lo) <= 0:
            continue
        amount = num(r[8]) if len(r) > 8 else None
        bars.append(Bar(date=str(r[0])[:10], open=o * f, high=h * f, low=lo * f, close=c * f,
                        volume=(num(r[5]) or 0.0) / divisor, turnover=num(r[7]) if len(r) > 7 else None,
                        amount=amount * 10000 if amount is not None else None))
    return bars, dividend_info(closes, events, factors)


def parse_quote_text(text: str, symbol: str) -> tuple[str, Quote]:
    """v_sh600519="1~贵州茅台~600519~最新价~昨收~今开~成交量~...";  以 ~ 分隔。"""
    m = re.search(r'v_%s="(.*?)";' % re.escape(symbol), text, re.S)
    if not m or not m.group(1):
        raise NoData("腾讯行情没有该品种的快照")
    f = m.group(1).split("~")
    if len(f) < 35:
        raise NoData("腾讯行情快照字段不全")
    stamp = f[30]
    when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[8:10]}:{stamp[10:12]}" if re.fullmatch(r"\d{12,14}", stamp) else ""
    q = Quote(
        price=num(f[3]), prev_close=num(f[4]), open=num(f[5]),
        change=num(f[31]), change_pct=num(f[32]), high=num(f[33]), low=num(f[34]),
        time=when, source="腾讯证券",
    )
    # 估值字段的位置只在 A 股上较确定，其余市场不取，免得张冠李戴
    if symbol[:2] in ("sh", "sz", "bj") and len(f) > 46:
        q.pe = num(f[39])
        q.pb = num(f[46])
        q.turnover = num(f[38])
        cap = num(f[45])
        q.total_cap = cap * 1e8 if cap is not None else None
        fcap = num(f[44])
        q.float_cap = fcap * 1e8 if fcap is not None else None
    return f[1], q


def quote(symbol: str) -> tuple[str, Quote]:
    resp = net.get(QUOTE_URL.format(symbol=symbol), headers={"Referer": "https://gu.qq.com/"})
    text = resp.content.decode("gbk", errors="replace")
    return parse_quote_text(text, symbol)
