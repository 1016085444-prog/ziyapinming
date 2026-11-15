"""全市场数据：每日精选用的 A 股快照、行业板块、开放式基金排行。

一次拿全市场做初筛，入围的少数标的再走常规分析链路（K 线、财务、基金档案）。
接口和字段含义参考 daily_stock_analysis（MIT）与 akshare 的实现；分页请求之间留间隔，
东方财富对突发的密集请求很敏感。
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, timedelta

from . import net
from .eastmoney import num
from .net import NoData, SourceError
from .symbols import classify_six

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_PAGES = 80                      # 防御：接口异常时不无限翻页

_pace_lock = threading.Lock()
_last_request: dict[str, float] = {}


def _paced(group: str, interval: float) -> None:
    """同一来源的分页请求之间至少间隔 interval 秒。"""
    with _pace_lock:
        wait = _last_request.get(group, 0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[group] = time.monotonic()


def _stock_row(code: str, name: str, **fields) -> dict | None:
    code = str(code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return None
    market, kind = classify_six(code)
    if kind != "stock":
        return None
    price = fields.get("price")
    if not price or price <= 0:          # 停牌、未上市
        return None
    row = {"code": code, "market": market, "name": str(name or "").strip()}
    row.update(fields)
    return row


# ── A 股快照：东方财富数据中心 → 东方财富行情 → 新浪 ─────────────────

DATACENTER_URL = "https://data.eastmoney.com/dataapi/xuangu/list"
DATACENTER_FIELDS = ("SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_PRICE,CHANGE_RATE,VOLUME_RATIO,DEAL_AMOUNT,"
                     "TURNOVERRATE,PE9,PBNEWMRQ,TOTAL_MARKET_CAP,CIRCULATION_MARKET_CAP")


def parse_datacenter(payload: dict) -> tuple[list[dict], int]:
    if not isinstance(payload, dict) or not payload.get("success"):
        msg = payload.get("message") if isinstance(payload, dict) else ""
        raise SourceError(f"东方财富选股接口返回错误：{msg or '未知'}")
    result = payload.get("result") or {}
    rows = []
    for d in result.get("data") or []:
        row = _stock_row(
            d.get("SECURITY_CODE"), d.get("SECURITY_NAME_ABBR"),
            price=num(d.get("NEW_PRICE")), change_pct=num(d.get("CHANGE_RATE")),
            amount=num(d.get("DEAL_AMOUNT")), turnover=num(d.get("TURNOVERRATE")),
            volume_ratio=num(d.get("VOLUME_RATIO")), pe=num(d.get("PE9")), pb=num(d.get("PBNEWMRQ")),
            total_mv=num(d.get("TOTAL_MARKET_CAP")), float_mv=num(d.get("CIRCULATION_MARKET_CAP")),
        )
        if row:
            rows.append(row)
    return rows, int(result.get("count") or 0)


def stocks_datacenter() -> list[dict]:
    rows: list[dict] = []
    size = 500
    for page in range(1, MAX_PAGES + 1):
        _paced("em-datacenter", 0.8)
        payload = net.get_json(DATACENTER_URL, params={
            "st": "SECURITY_CODE", "sr": "1", "ps": str(size), "p": str(page), "sty": DATACENTER_FIELDS,
            "filter": '(MARKET+in+("上交所主板","深交所主板","深交所创业板","上交所科创板","北交所"))',
            "source": "SELECT_SECURITIES", "client": "WEB",
        }, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/xuangu/"}, timeout=30)
        batch, total = parse_datacenter(payload)
        rows += batch
        if not batch or page * size >= total:
            break
    return rows


CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
A_SHARE_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"


def _clist_params(fs: str, fields: str, page: int, fid: str = "f12", po: str = "0") -> dict:
    return {"pn": str(page), "pz": "100", "po": po, "np": "1", "fltt": "2", "invt": "2",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fid": fid, "fs": fs, "fields": fields}


def _clist_page(payload: dict) -> tuple[list[dict], int]:
    data = (payload or {}).get("data") or {}
    diff = data.get("diff") or []
    if isinstance(diff, dict):            # np=0 时是 {"0": {...}}
        diff = list(diff.values())
    return diff, int(data.get("total") or 0)


def parse_clist_stocks(payload: dict) -> tuple[list[dict], int]:
    diff, total = _clist_page(payload)
    rows = []
    for d in diff:
        industry = d.get("f100")
        row = _stock_row(
            d.get("f12"), d.get("f14"),
            price=num(d.get("f2")), change_pct=num(d.get("f3")), amount=num(d.get("f6")),
            turnover=num(d.get("f8")), volume_ratio=num(d.get("f10")), pe=num(d.get("f9")),
            pb=num(d.get("f23")), total_mv=num(d.get("f20")), float_mv=num(d.get("f21")),
            change_60d=num(d.get("f24")), ytd=num(d.get("f25")),
        )
        if row:
            if industry not in (None, "-", ""):
                row["industry"] = str(industry)
            rows.append(row)
    return rows, total


def stocks_clist() -> list[dict]:
    rows: list[dict] = []
    fields = "f2,f3,f6,f8,f9,f10,f12,f13,f14,f20,f21,f23,f24,f25,f100"
    for page in range(1, MAX_PAGES + 1):
        _paced("eastmoney-push2", 0.6)
        payload = net.get_json(CLIST_URL, params=_clist_params(A_SHARE_FS, fields, page),
                               headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=20)
        batch, total = parse_clist_stocks(payload)
        diff, _ = _clist_page(payload)
        rows += batch
        if not diff or page * 100 >= total:
            break
    return rows


SINA_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"


def parse_sina(items: list) -> list[dict]:
    if not isinstance(items, list):
        raise SourceError("新浪行情中心返回的数据格式不对")
    rows = []
    for d in items:
        mv, fmv = num(d.get("mktcap")), num(d.get("nmc"))
        row = _stock_row(
            d.get("code"), d.get("name"),
            price=num(d.get("trade")), change_pct=num(d.get("changepercent")), amount=num(d.get("amount")),
            turnover=num(d.get("turnoverratio")), pe=num(d.get("per")), pb=num(d.get("pb")),
            total_mv=mv * 10000 if mv else None, float_mv=fmv * 10000 if fmv else None,   # 新浪单位是万元
        )
        if row:
            rows.append(row)
    return rows


def stocks_sina() -> list[dict]:
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        _paced("sina-hq", 0.5)
        resp = net.get(SINA_URL, params={"page": page, "num": 100, "sort": "symbol", "asc": 1, "node": "hs_a",
                                         "symbol": "", "_s_r_a": "page"},
                       headers={"User-Agent": UA, "Referer": "https://vip.stock.finance.sina.com.cn/mkt/"}, timeout=20)
        try:
            items = resp.json()
        except ValueError as exc:
            raise SourceError("新浪行情中心返回的不是有效 JSON") from exc
        rows += parse_sina(items)
        if not items or len(items) < 100:
            break
    return rows


STOCK_SOURCES = (("东方财富数据中心", stocks_datacenter), ("东方财富行情", stocks_clist), ("新浪财经", stocks_sina))


def a_share_snapshot(cache, max_age: float = 1800) -> tuple[list[dict], str, list[str]]:
    """全部 A 股的最新快照。返回 (行, 来源, 提示)。至少要有 2000 只才算取全。"""
    key = "universe:a-share"
    hit = cache.get(key, max_age)
    if hit:
        return hit["rows"], hit["source"], []
    errors = []
    for label, fetch in STOCK_SOURCES:
        try:
            rows = fetch()
        except SourceError as exc:
            errors.append(f"{label}：{exc}")
            continue
        if len(rows) >= 2000:
            cache.set(key, {"rows": rows, "source": label})
            return rows, label, []
        errors.append(f"{label}：只取到 {len(rows)} 只股票，数据不全")
    stale = cache.get_stale(key, 3 * 86400)
    if stale:
        value, age = stale
        return value["rows"], value["source"], [f"实时快照取不到，用了 {int(age // 3600)} 小时前的数据"] + errors
    raise SourceError("全市场行情都取不到：" + "；".join(errors))


# ── 行业板块 ──────────────────────────────────────────────────────

def parse_boards(payload: dict) -> list[dict]:
    diff, _ = _clist_page(payload)
    out = []
    for d in diff:
        name = str(d.get("f14") or "").strip()
        change = num(d.get("f3"))
        if not name or change is None:
            continue
        out.append({"code": str(d.get("f12") or ""), "name": name, "change_pct": change,
                    "up": num(d.get("f104")), "down": num(d.get("f105")),
                    "leader": str(d.get("f128") or "").strip(), "leader_change": num(d.get("f136"))})
    out.sort(key=lambda x: -x["change_pct"])
    return out


def industry_boards(cache, max_age: float = 1800) -> list[dict]:
    key = "universe:boards"
    hit = cache.get(key, max_age)
    if hit is not None:
        return hit
    payload = net.get_json(CLIST_URL, params=_clist_params("m:90 t:2 f:!50", "f3,f12,f14,f104,f105,f128,f136", 1,
                                                           fid="f3", po="1"),
                           headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=15)
    boards = parse_boards(payload)
    if not boards:
        raise NoData("行业板块数据为空")
    cache.set(key, boards)
    return boards


# ── 全市场财报摘要：每只股票最新一期的净利润同比和所属行业 ──────────────
# 东方财富数据中心的「业绩报表」，一个报告期一张全市场的表。每日精选的中期板块要给几千只股票
# 确认「利润是不是在增长」，逐只去读财报太慢，用这张表十几次请求就够。

REPORT_URLS = ("https://datacenter.eastmoney.com/api/data/v1/get", "https://datacenter-web.eastmoney.com/api/data/v1/get")
REPORT_COLUMNS = "SECURITY_CODE,NOTICE_DATE,PARENT_NETPROFIT,SJLTZ,BASIC_EPS,PUBLISHNAME"
REPORT_LABELS = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}


def recent_periods(today: date, n: int = 3) -> list[str]:
    """today 之前最近的 n 个报告期（季度末），新的在前。年报、一季报披露期里有的公司最新一期还是上一期，所以取三个。"""
    out, y = [], today.year
    while len(out) < n:
        for md in ("12-31", "09-30", "06-30", "03-31"):
            p = f"{y}-{md}"
            if p < today.isoformat() and len(out) < n:
                out.append(p)
        y -= 1
    return out


def parse_reports(payload: dict) -> tuple[dict[str, dict], int]:
    result = (payload or {}).get("result") if isinstance(payload, dict) else None
    if not result:
        return {}, 0                                 # 这个报告期还没有公司披露
    rows = {}
    for d in result.get("data") or []:
        code = str(d.get("SECURITY_CODE") or "")
        if not re.fullmatch(r"\d{6}", code):
            continue
        rows[code] = {"notice": str(d.get("NOTICE_DATE") or "")[:10], "profit": num(d.get("PARENT_NETPROFIT")),
                      "yoy": num(d.get("SJLTZ")), "eps": num(d.get("BASIC_EPS")),
                      "industry": str(d.get("PUBLISHNAME") or "").strip()}
    return rows, int(result.get("pages") or 1)


def report_period(period: str) -> dict[str, dict]:
    """一个报告期的全市场业绩报表：{代码: {公告日, 归母净利润, 净利润同比(%), 每股收益, 行业}}。"""
    last: Exception | None = None
    for url in REPORT_URLS:
        rows: dict[str, dict] = {}
        try:
            for page in range(1, MAX_PAGES + 1):
                _paced("em-datacenter", 0.35)
                payload = net.get_json(url, params={
                    "reportName": "RPT_LICO_FN_CPD", "columns": REPORT_COLUMNS, "sortColumns": "SECURITY_CODE", "sortTypes": "1",
                    "pageSize": "500", "pageNumber": str(page),
                    "filter": f"(REPORTDATE='{period}')(SECURITY_TYPE_CODE in (\"058001001\"))",
                }, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}, timeout=30)
                batch, pages = parse_reports(payload)
                rows.update(batch)
                if not batch or page >= pages:
                    break
            return rows
        except SourceError as exc:
            last = exc
    raise SourceError(f"全市场财报摘要取不到：{last}")


def latest_reports(cache, today: date) -> dict[str, dict]:
    """每只股票已经披露的最新一期：{代码: {period, label, yoy(小数), profit, eps, industry, notice}}。
    行业取自任意一期（它不随报告期变）。已经过完披露期的报告期存 7 天，最新的一期每 20 小时更新。"""
    out: dict[str, dict] = {}
    industry: dict[str, str] = {}
    cutoff = today.isoformat()
    for i, period in enumerate(recent_periods(today)):
        key = f"reports:{period}"
        rows = cache.get(key, 20 * 3600 if i == 0 else 7 * 86400)
        if rows is None:
            rows = report_period(period)
            if rows:
                cache.set(key, rows)
        for code, r in rows.items():
            if r.get("industry"):
                industry.setdefault(code, r["industry"])
            if code in out or not r.get("notice") or r["notice"] > cutoff:
                continue
            out[code] = {"period": period, "label": f"{period[:4]}年{REPORT_LABELS[period[5:]]}", "notice": r["notice"],
                         "yoy": r["yoy"] / 100 if r.get("yoy") is not None else None, "profit": r.get("profit"), "eps": r.get("eps")}
    for code, r in out.items():
        r["industry"] = industry.get(code, "")
    for code, name in industry.items():              # 还没披露过任何一期的（刚上市），至少有行业
        out.setdefault(code, {"period": "", "label": "", "notice": "", "yoy": None, "profit": None, "eps": None, "industry": name})
    return out


# ── 开放式基金排行（天天基金） ────────────────────────────────────

FUND_RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
FUND_TYPES = {"gp": "股票型", "hh": "混合型", "zq": "债券型", "zs": "指数型", "qdii": "QDII"}
_RANK_FIELDS = {7: "w1", 8: "m1", 9: "m3", 10: "m6", 11: "y1", 12: "y2", 13: "y3", 14: "ytd", 15: "since"}


def parse_fund_rank(text: str, ft: str = "") -> list[dict]:
    """rankhandler 返回 JS：var rankData = {datas:["代码,简称,拼音,日期,单位净值,累计净值,日增长率,近1周,...",...],...}"""
    m = re.search(r"datas\s*:\s*(\[.*?\])\s*,\s*allRecords", text or "", re.S)
    if not m:
        raise SourceError("天天基金排行返回的数据格式不对，接口可能已变更")
    try:
        items = json.loads(m.group(1))
    except ValueError as exc:
        raise SourceError("天天基金排行数据解析失败") from exc
    out = []
    for line in items:
        f = str(line).split(",")
        if len(f) < 21 or not re.fullmatch(r"\d{6}", f[0]):
            continue
        row = {"code": f[0], "name": f[1], "type": FUND_TYPES.get(ft, ""), "ft": ft, "nav_date": f[3],
               "nav": num(f[4]), "inception": f[16] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f[16]) else "",
               "fee": f[20] if f[20].endswith("%") else ""}
        for i, k in _RANK_FIELDS.items():
            row[k] = num(f[i])
        out.append(row)
    return out


def fund_rank(cache, ft: str, max_age: float = 12 * 3600) -> list[dict]:
    if ft not in FUND_TYPES:
        raise ValueError(f"未知的基金类型：{ft}")
    key = f"universe:fundrank:{ft}"
    hit = cache.get(key, max_age)
    if hit is not None:
        return hit
    today = date.today()
    _paced("fund-rank", 0.8)
    resp = net.get(FUND_RANK_URL, params={
        "op": "ph", "dt": "kf", "ft": ft, "rs": "", "gs": "0", "sc": "3nzf", "st": "desc",
        "sd": (today - timedelta(days=365)).isoformat(), "ed": today.isoformat(), "qdii": "",
        "tabSubtype": ",,,,,", "pi": "1", "pn": "20000", "dx": "1", "v": "0.5",
    }, headers={"User-Agent": UA, "Referer": "https://fund.eastmoney.com/fundguzhi.html"}, timeout=30)
    rows = parse_fund_rank(resp.text, ft)
    if not rows:
        raise NoData(f"{FUND_TYPES[ft]}基金排行为空")
    cache.set(key, rows)
    return rows
