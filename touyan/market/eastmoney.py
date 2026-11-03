"""东方财富：K 线、行情快照、证券搜索、主要财务指标。

这些都是网页版在用的非公开接口，没有官方文档。接口地址、参数与字段含义取自
akshare 1.20.x（2026-11）的实现——akshare 社区持续跟进这些接口的变化，是目前
最可靠的参照。字段含义没有经过 akshare 印证的一律不用，宁缺毋滥。

每个接口拆成「取数」和「解析」两步：解析是纯函数，可以用样例响应单测；
接口变了只需要改解析。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from market import net
from market.models import Bar, FinancialPeriod, Instrument, Quote
from market.net import NoData
from market.symbols import from_search_item

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
KLINE_UT = "7eea3edcaed734bea9cbfc24409ed989"
ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
ULIST_UT = "f057cbcbce2a86e2866ab8877db1d059"
SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
FIN_A_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
FIN_V1_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

REFERER = {"Referer": "https://quote.eastmoney.com/"}

# 行情快照字段（列表接口口径，含义均经 akshare 印证）：
# f2 最新价 f3 涨跌幅 f4 涨跌额 f5 成交量 f6 成交额 f8 换手率 f9 市盈率(动态)
# f12 代码 f14 名称 f15 最高 f16 最低 f17 今开 f18 昨收 f20 总市值 f21 流通市值
# f23 市净率 f24 60日涨跌幅 f25 年初至今涨跌幅 f100 所属板块 f124 更新时间
QUOTE_FIELDS = "f2,f3,f4,f5,f6,f8,f9,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f100,f124"


def num(value) -> float | None:
    """东方财富用 "-"、空串表示缺失。转成 float，失败返回 None（绝不返回 0 冒充）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").rstrip("%")
    if text in ("", "-", "--", "None", "null", "NaN", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ts(value) -> str:
    """Unix 时间戳 → 北京时间。不依赖服务器时区（云主机常是 UTC）。"""
    v = num(value)
    if not v or v < 1e8:
        return ""
    if v > 1e12:  # 毫秒
        v /= 1000
    return (datetime(1970, 1, 1) + timedelta(seconds=v, hours=8)).strftime("%Y-%m-%d %H:%M")


# ── K 线 ───────────────────────────────────────────────────────

def kline(secid: str, limit: int = 800, adjust: str = "qfq") -> tuple[str, list[Bar]]:
    """日 K 线，默认前复权（最新价是真实成交价，历史价按除权调整，指标才连续）。"""
    params = {
        "secid": secid,
        "ut": KLINE_UT,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": {"qfq": "1", "hfq": "2", "": "0"}[adjust],
        "end": "20500101",
        "lmt": str(limit),
    }
    return parse_kline(net.get_json(KLINE_URL, params=params, headers=REFERER))


def parse_kline(payload: dict) -> tuple[str, list[Bar]]:
    """klines 每行：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率。"""
    data = (payload or {}).get("data") or {}
    rows = data.get("klines") or []
    if not rows:
        raise NoData("东方财富没有该品种的 K 线数据（代码可能不存在、已退市，或品种不支持）")
    bars: list[Bar] = []
    for line in rows:
        p = str(line).split(",")
        if len(p) < 6:
            continue
        o, c, h, lo, v = num(p[1]), num(p[2]), num(p[3]), num(p[4]), num(p[5])
        if None in (o, c, h, lo) or c <= 0:
            continue
        bars.append(Bar(
            date=p[0][:10], open=o, high=h, low=lo, close=c, volume=v or 0.0,
            amount=num(p[6]) if len(p) > 6 else None,
            turnover=num(p[10]) if len(p) > 10 else None,
        ))
    if not bars:
        raise NoData("东方财富返回的 K 线无法解析，接口可能已变更")
    return str(data.get("name") or ""), bars


# ── 行情快照 ───────────────────────────────────────────────────

def quote(secid: str) -> tuple[str, Quote]:
    params = {"fltt": "2", "invt": "2", "fields": QUOTE_FIELDS, "secids": secid, "ut": ULIST_UT}
    return parse_quote(net.get_json(ULIST_URL, params=params, headers=REFERER))


def parse_quote(payload: dict) -> tuple[str, Quote]:
    diff = ((payload or {}).get("data") or {}).get("diff") or []
    if isinstance(diff, dict):  # 部分接口把列表编成 {"0": {...}}
        diff = list(diff.values())
    if not diff:
        raise NoData("东方财富没有该品种的行情快照")
    d = diff[0]
    industry = d.get("f100")
    q = Quote(
        price=num(d.get("f2")), change_pct=num(d.get("f3")), change=num(d.get("f4")),
        volume=num(d.get("f5")), amount=num(d.get("f6")), turnover=num(d.get("f8")),
        pe=num(d.get("f9")), high=num(d.get("f15")), low=num(d.get("f16")),
        open=num(d.get("f17")), prev_close=num(d.get("f18")),
        total_cap=num(d.get("f20")), float_cap=num(d.get("f21")), pb=num(d.get("f23")),
        change_60d=num(d.get("f24")), change_ytd=num(d.get("f25")),
        industry=str(industry) if industry not in (None, "-", "") else "",
        time=_ts(d.get("f124")), source="东方财富",
    )
    return str(d.get("f14") or ""), q


def names(secids: list[str]) -> dict[str, tuple[str, float | None]]:
    """一次查多只证券的名称和涨跌幅（基金重仓股用）。返回 {代码: (名称, 涨跌幅)}。"""
    if not secids:
        return {}
    params = {"fltt": "2", "invt": "2", "fields": "f3,f12,f14", "secids": ",".join(secids), "ut": ULIST_UT}
    payload = net.get_json(ULIST_URL, params=params, headers=REFERER)
    diff = ((payload or {}).get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    return {str(d.get("f12")): (str(d.get("f14") or ""), num(d.get("f3"))) for d in diff if d.get("f12")}


# ── 搜索 ───────────────────────────────────────────────────────

def search(text: str, count: int = 10) -> list[Instrument]:
    params = {"input": text, "type": "14", "token": SEARCH_TOKEN, "count": str(count)}
    return parse_search(net.get_json(SEARCH_URL, params=params, headers=REFERER))


def parse_search(payload: dict) -> list[Instrument]:
    table = (payload or {}).get("QuotationCodeTable") or {}
    out: list[Instrument] = []
    for item in table.get("Data") or []:
        inst = from_search_item(item)
        if inst is not None:
            out.append(inst)
    return out


# ── 主要财务指标 ───────────────────────────────────────────────
#
# A 股、港股、美股三张报表的列名各不相同。按「候选列名」逐个尝试，取到哪个算哪个；
# 一个都没有就留 None，界面上显示「—」而不是编一个数。
_FIN_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("TOTALOPERATEREVE", "OPERATE_INCOME", "TOTAL_OPERATE_INCOME", "TOTAL_INCOME"),
    "revenue_yoy": ("TOTALOPERATEREVETZ", "OPERATE_INCOME_YOY", "TOTAL_OPERATE_INCOME_YOY", "TOTAL_INCOME_YOY"),
    "net_profit": ("PARENTNETPROFIT", "HOLDER_PROFIT", "PARENT_HOLDER_NETPROFIT", "PARENT_NETPROFIT"),
    "net_profit_yoy": ("PARENTNETPROFITTZ", "HOLDER_PROFIT_YOY", "PARENT_HOLDER_NETPROFIT_YOY", "PARENT_NETPROFIT_YOY"),
    "deduct_profit_yoy": ("KCFJCXSYJLRTZ",),
    "roe": ("ROEJQ", "ROE_AVG", "ROE_YEARLY", "ROE"),
    "gross_margin": ("XSMLL", "GROSS_PROFIT_RATIO"),
    "net_margin": ("XSJLL", "NET_PROFIT_RATIO"),
    "debt_ratio": ("ZCFZL", "DEBT_ASSET_RATIO", "DEBT_RATIO"),
    "eps": ("EPSJB", "BASIC_EPS", "BASIC_EPS_CS"),
    "bps": ("BPS",),
    "ocf_per_share": ("MGJYXJJE", "PER_NETCASH_OPERATE"),
    "current_ratio": ("LD", "CURRENT_RATIO"),
}


def _pick(row: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = num(row.get(key))
        if value is not None:
            return value
    return None


def parse_financials(payload: dict) -> list[FinancialPeriod]:
    result = (payload or {}).get("result") or {}
    rows = result.get("data") or []
    periods: list[FinancialPeriod] = []
    for row in rows:
        date = str(row.get("REPORT_DATE") or row.get("STD_REPORT_DATE") or "")[:10]
        if not date:
            continue
        name = str(row.get("REPORT_DATE_NAME") or row.get("REPORT_TYPE") or row.get("DATE_TYPE") or "")
        fp = FinancialPeriod(report_date=date, report_name=name)
        for attr, keys in _FIN_FIELDS.items():
            setattr(fp, attr, _pick(row, keys))
        periods.append(fp)
    periods.sort(key=lambda p: p.report_date, reverse=True)
    return periods


def financials(inst: Instrument, us_secucode: str = "") -> list[FinancialPeriod]:
    """最近若干期主要财务指标，新的在前。"""
    if inst.market in ("SH", "SZ", "BJ"):
        params = {
            "type": "RPT_F10_FINANCE_MAINFINADATA", "sty": "APP_F10_MAINFINADATA",
            "quoteColumns": "", "filter": f'(SECUCODE="{inst.code}.{inst.market}")',
            "p": "1", "ps": "12", "sr": "-1", "st": "REPORT_DATE", "source": "HSF10", "client": "PC",
        }
        payload = net.get_json(FIN_A_URL, params=params)
    elif inst.market == "HK":
        params = {
            "reportName": "RPT_HKF10_FN_MAININDICATOR", "columns": "HKF10_FN_MAININDICATOR",
            "quoteColumns": "", "filter": f'(SECUCODE="{inst.code}.HK")',
            "pageNumber": "1", "pageSize": "9", "sortTypes": "-1", "sortColumns": "STD_REPORT_DATE",
            "source": "F10", "client": "PC",
        }
        payload = net.get_json(FIN_V1_URL, params=params)
    elif inst.market == "US" and us_secucode:
        params = {
            "reportName": "RPT_USF10_FN_GMAININDICATOR", "columns": "USF10_FN_GMAININDICATOR",
            "quoteColumns": "", "filter": f'(SECUCODE="{us_secucode}")(DATE_TYPE_CODE="001")',
            "pageNumber": "1", "pageSize": "8", "sortTypes": "-1", "sortColumns": "REPORT_DATE",
            "source": "SECURITIES", "client": "PC",
        }
        payload = net.get_json(FIN_V1_URL, params=params)
    else:
        raise NoData("该品种没有可用的财务数据源")
    periods = parse_financials(payload)
    if not periods:
        raise NoData("东方财富没有返回财务数据")
    return periods


def us_profile(ticker: str) -> dict[str, str]:
    """美股公司档案：SECUCODE（查财务要用）、所属行业、公司简介。"""
    params = {
        "reportName": "RPT_USF10_INFO_ORGPROFILE",
        "columns": "SECUCODE,SECURITY_CODE,ORG_NAME,ORG_EN_ABBR,BELONG_INDUSTRY,FOUND_DATE,ORG_PROFILE",
        "quoteColumns": "", "filter": f'(SECURITY_CODE="{ticker.replace(".", "_")}")',
        "pageNumber": "1", "pageSize": "5", "sortTypes": "", "sortColumns": "",
        "source": "SECURITIES", "client": "PC",
    }
    payload = net.get_json(FIN_V1_URL, params=params)
    rows = ((payload or {}).get("result") or {}).get("data") or []
    if not rows:
        raise NoData("东方财富没有该美股的公司档案")
    row = rows[0]
    return {
        "secucode": str(row.get("SECUCODE") or ""),
        "name": str(row.get("ORG_NAME") or ""),
        "industry": str(row.get("BELONG_INDUSTRY") or ""),
        "profile": str(row.get("ORG_PROFILE") or "")[:600],
    }
