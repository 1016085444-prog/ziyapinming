"""数据源自检：逐个探测各数据源能不能连上、返回的数据能不能解析。

网络环境千差万别（公司网络、海外服务器、代理……），哪个源通、哪个不通，跑一次就知道。
东方财富 push2 对密集请求会封 IP，所以这里只探测 3 次 push2，并且间隔开。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from market import eastmoney, fundem, news, optional, tencent
from market.models import Instrument
from market.net import SourceError


def _check(name: str, desc: str, fn: Callable[[], str]) -> dict:
    started = time.time()
    try:
        detail = fn()
        ok = True
    except SourceError as exc:
        detail, ok = str(exc), False
    except Exception as exc:  # noqa: BLE001 — 自检要把任何异常都报告出来
        detail, ok = f"{type(exc).__name__}: {exc}", False
    return {"name": name, "desc": desc, "ok": ok, "detail": detail, "ms": int((time.time() - started) * 1000)}


def _em_kline() -> str:
    name, bars = eastmoney.kline("1.000300", 5)
    return f"{name or '沪深300'} 最新 {bars[-1].date} 收盘 {bars[-1].close}"


def _em_quote() -> str:
    name, q = eastmoney.quote("1.600519")
    return f"{name} 最新价 {q.price}，市盈率 {q.pe}，市净率 {q.pb}，行业 {q.industry or '—'}"


def _em_us() -> str:
    name, bars = eastmoney.kline("105.AAPL", 5)
    return f"{name or 'AAPL'} 最新 {bars[-1].date} 收盘 {bars[-1].close}"


def _em_search() -> str:
    hits = eastmoney.search("茅台", 5)
    return "、".join(f"{h.name}({h.code})" for h in hits[:3]) or "无结果"


def _em_fin() -> str:
    periods = eastmoney.financials(Instrument("600519", "SH", "stock"))
    p = periods[0]
    filled = sum(1 for k, v in p.__dict__.items() if k not in ("report_date", "report_name") and v is not None)
    return f"{p.report_name or p.report_date}：{filled}/13 个字段有值（ROE {p.roe}，营收同比 {p.revenue_yoy}）"


def _tx_kline() -> str:
    bars = tencent.kline("sh000300", 30)
    return f"沪深300 最新 {bars[-1].date} 收盘 {bars[-1].close}"


def _tx_hk() -> str:
    bars = tencent.kline("hk00700", 30)
    return f"腾讯控股 最新 {bars[-1].date} 收盘 {bars[-1].close}"


def _fund() -> str:
    profile, bars, _ = fundem.pingzhong("110011")
    return f"{profile.name} 净值 {bars[-1].close}（{bars[-1].date}），规模 {profile.scale} 亿"


def _danjuan() -> str:
    info = fundem.danjuan("110011")
    return f"{info.get('fund_type') or '—'}｜{info.get('company') or '—'}"


def _company_news() -> str:
    items = news.company_news("600519", 5)
    return f"{len(items)} 条，最新：{items[0].title[:30] if items else '—'}"


def _market_news() -> str:
    items = news.market_news(5)
    return f"{len(items)} 条，最新：{items[0].title[:30] if items else '—'}"


def _sina_news() -> str:
    items = news.sina_market_news(5)
    return f"{len(items)} 条"


CHECKS = [
    ("东方财富·K线", "A 股 / ETF / 指数日线（push2his）", _em_kline, True),
    ("东方财富·行情快照", "最新价、市盈率、市净率（push2）", _em_quote, True),
    ("东方财富·美股", "美股日线（push2his）", _em_us, True),
    ("东方财富·搜索", "按名称 / 拼音搜索证券", _em_search, False),
    ("东方财富·财务", "主要财务指标（datacenter）", _em_fin, False),
    ("腾讯证券·K线", "A 股备用行情源", _tx_kline, False),
    ("腾讯证券·港股", "港股备用行情源", _tx_hk, False),
    ("天天基金", "基金净值、规模、经理", _fund, False),
    ("蛋卷基金", "基金类型、基金公司", _danjuan, False),
    ("东方财富·个股新闻", "个股新闻搜索", _company_news, False),
    ("东方财富·7x24", "市场快讯", _market_news, False),
    ("新浪财经·7x24", "市场快讯（备用）", _sina_news, False),
]


def run() -> dict:
    results: dict[str, dict] = {}
    push2 = [c for c in CHECKS if c[3]]
    others = [c for c in CHECKS if not c[3]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {name: pool.submit(_check, name, desc, fn) for name, desc, fn, _ in others}
        for i, (name, desc, fn, _) in enumerate(push2):   # push2 串行、间隔开
            if i:
                time.sleep(0.8)
            results[name] = _check(name, desc, fn)
        for name, fut in futures.items():
            results[name] = fut.result()
    ordered = [results[name] for name, *_ in CHECKS]
    return {
        "checks": ordered,
        "ok": sum(1 for r in ordered if r["ok"]),
        "total": len(ordered),
        "optional": optional.available(),
    }
