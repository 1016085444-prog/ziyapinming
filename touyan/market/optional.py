"""可选的后备数据源：装了 akshare / yfinance 才启用，没装就跳过。

不把它们列为必装依赖：akshare 依赖多（pandas、lxml、JS 引擎……），yfinance 在国内网络下
经常连不上。内置的东方财富 + 腾讯已覆盖 A 股、港股、美股、基金；这两个库只在内置源
都失败时兜底，或用于内置源不覆盖的品种（如加密货币 BTC-USD，需要 yfinance）。
"""

from __future__ import annotations

from market.models import Bar, Instrument
from market.net import NoData, SourceError


def available() -> dict[str, bool]:
    out = {}
    for mod in ("akshare", "yfinance"):
        try:
            __import__(mod)
            out[mod] = True
        except Exception:  # noqa: BLE001 — 任何导入失败都视为不可用
            out[mod] = False
    return out


def _yahoo_symbol(inst: Instrument) -> str:
    if inst.market == "SH":
        return f"{inst.code}.SS"
    if inst.market == "SZ":
        return f"{inst.code}.SZ"
    if inst.market == "HK":
        return f"{int(inst.code):04d}.HK"
    if inst.market == "US":
        return inst.code.replace(".", "-")
    if inst.market == "GI":
        return {"HSI": "^HSI", "SPX": "^GSPC", "NDX": "^NDX", "DJIA": "^DJI", "N225": "^N225"}.get(inst.code, "")
    return ""


def yfinance_kline(inst: Instrument, days: int = 800) -> list[Bar]:
    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        raise SourceError("未安装 yfinance") from exc
    symbol = _yahoo_symbol(inst)
    if not symbol:
        raise NoData("yfinance 不支持该品种")
    years = max(1, round(days / 245 + 0.5))
    try:
        df = yf.Ticker(symbol).history(period=f"{years}y", interval="1d", auto_adjust=True)
    except Exception as exc:  # noqa: BLE001 — yfinance 的异常类型不稳定
        raise SourceError(f"yfinance 取数失败：{exc}") from exc
    if df is None or df.empty:
        raise NoData("yfinance 没有返回数据")
    bars = []
    for idx, row in df.iterrows():
        try:
            bars.append(Bar(date=idx.strftime("%Y-%m-%d"), open=float(row["Open"]), high=float(row["High"]),
                            low=float(row["Low"]), close=float(row["Close"]), volume=float(row.get("Volume") or 0)))
        except (TypeError, ValueError):
            continue
    return bars[-days:]


def akshare_kline(inst: Instrument, days: int = 800) -> list[Bar]:
    try:
        import akshare as ak
    except Exception as exc:  # noqa: BLE001
        raise SourceError("未安装 akshare") from exc
    try:
        if inst.market in ("SH", "SZ", "BJ") and inst.kind == "stock":
            df = ak.stock_zh_a_hist(symbol=inst.code, period="daily", adjust="qfq")
        elif inst.market in ("SH", "SZ") and inst.kind == "etf":
            df = ak.fund_etf_hist_em(symbol=inst.code, period="daily", adjust="qfq")
        elif inst.market == "HK":
            df = ak.stock_hk_hist(symbol=inst.code, period="daily", adjust="qfq")
        else:
            raise NoData("akshare 后备源不支持该品种")
    except NoData:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"akshare 取数失败：{exc}") from exc
    if df is None or df.empty:
        raise NoData("akshare 没有返回数据")
    bars = []
    for _, row in df.iterrows():
        try:
            bars.append(Bar(date=str(row["日期"])[:10], open=float(row["开盘"]), high=float(row["最高"]),
                            low=float(row["最低"]), close=float(row["收盘"]), volume=float(row["成交量"]),
                            amount=float(row["成交额"]), turnover=float(row["换手率"])))
        except (KeyError, TypeError, ValueError):
            continue
    return bars[-days:]
