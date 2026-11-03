"""腾讯证券：A 股 / 港股日 K 线与行情快照。东方财富被限流时的备用数据源。

接口取自 akshare 1.20.x 的 stock_zh_a_hist_tx / stock_hk_daily 实现：
单次最多返回 640 根 K 线，所以按约一年半一段分段请求。
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
