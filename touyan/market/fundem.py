"""基金数据：天天基金（东方财富）+ 蛋卷基金。场外基金与 ETF 共用。

主数据来自 pingzhongdata/{代码}.js——一个由若干 `var 名称 = 值;` 组成的 JS 文件，
净值走势、规模、经理、资产配置、同类排名都在里面。akshare 用 JS 引擎执行它；
这里的值都是 JSON 字面量，用 json.raw_decode 逐个解析即可，省掉一个重依赖。

收益一律按「复权净值」算：单位净值遇到分红会跳水，直接拿来算收益会把分红算成亏损。
复权净值由每日「净值回报」（已含分红）连乘得到。货币基金净值恒为 1，改用每日万份收益
连乘出收益指数。
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timedelta

from market import net
from market.eastmoney import num
from market.models import Bar, FundManager, FundProfile, Holding, Instrument
from market.net import NoData

PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
DANJUAN_URL = "https://danjuanfunds.com/djapi/fund/{code}"
ARCHIVES_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
FUND_SEARCH_URL = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"

_VAR = re.compile(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*")


def parse_js_vars(text: str) -> dict:
    """把 `var a = 1; var b = [...];` 解析成 dict。不是 JSON 的值（如单引号数组）跳过。"""
    decoder = json.JSONDecoder()
    out: dict = {}
    pos = 0
    while True:
        m = _VAR.search(text, pos)
        if not m:
            break
        try:
            value, end = decoder.raw_decode(text, m.end())
        except ValueError:
            pos = m.end()
            continue
        out[m.group(1)] = value
        pos = end
    return out


def _date_from_ms(ms) -> str:
    """毫秒时间戳 → 北京时间日期。不依赖系统时区。"""
    return (datetime(1970, 1, 1) + timedelta(milliseconds=float(ms), hours=8)).strftime("%Y-%m-%d")


def _tenure_years(text: str) -> float | None:
    """「6年又200天」→ 6.55；「200天」→ 0.55。"""
    if not text:
        return None
    years = re.search(r"(\d+)\s*年", text)
    days = re.search(r"(\d+)\s*天", text)
    if not years and not days:
        return None
    return round((int(years.group(1)) if years else 0) + (int(days.group(1)) if days else 0) / 365, 2)


def nav_bars(js: dict) -> list[Bar]:
    """净值走势 → Bar 序列（o=h=l=c=单位净值，adj=复权净值）。"""
    trend = js.get("Data_netWorthTrend") or []
    bars: list[Bar] = []
    adj = None
    prev_nav = None
    for point in trend:
        if not isinstance(point, dict):
            continue
        nav = num(point.get("y"))
        if nav is None or nav <= 0 or point.get("x") is None:
            continue
        daily = num(point.get("equityReturn"))
        if adj is None:
            adj = nav
        elif daily is not None:
            adj *= 1 + daily / 100
        elif prev_nav:
            adj *= nav / prev_nav
        prev_nav = nav
        bars.append(Bar(date=_date_from_ms(point["x"]), open=nav, high=nav, low=nav, close=nav, adj=round(adj, 6)))
    if bars:
        return bars
    # 货币基金：没有净值走势，用每日万份收益连乘出收益指数（起点 1.0）
    income = js.get("Data_millionCopiesIncome") or []
    level = 1.0
    for point in income:
        if not isinstance(point, list) or len(point) < 2:
            continue
        per10k = num(point[1])
        if per10k is None:
            continue
        level *= 1 + per10k / 10000
        value = round(level, 6)
        bars.append(Bar(date=_date_from_ms(point[0]), open=value, high=value, low=value, close=value))
    return bars


def profile_from_js(js: dict) -> FundProfile:
    p = FundProfile(source="天天基金")
    p.name = str(js.get("fS_name") or "")
    p.fee_rate = num(js.get("fund_Rate"))
    p.fee_rate_original = num(js.get("fund_sourceRate"))
    for key, label in (("syl_1y", "1m"), ("syl_3y", "3m"), ("syl_6y", "6m"), ("syl_1n", "1y")):
        value = num(js.get(key))
        if value is not None:
            p.returns[label] = value

    scale = js.get("Data_fluctuationScale") or {}
    series = scale.get("series") or []
    cats = scale.get("categories") or []
    if series and isinstance(series[-1], dict):
        p.scale = num(series[-1].get("y"))
        p.scale_date = str(cats[-1]) if cats else ""

    for m in js.get("Data_currentFundManager") or []:
        if isinstance(m, dict) and m.get("name"):
            tenure = str(m.get("workTime") or "")
            p.managers.append(FundManager(
                name=str(m["name"]), tenure=tenure, tenure_years=_tenure_years(tenure),
                managed_size=str(m.get("fundSize") or ""),
            ))

    alloc = js.get("Data_assetAllocation") or {}
    a_cats = alloc.get("categories") or []
    for s in alloc.get("series") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "")
        data = s.get("data") or []
        if "占净比" in name and data:
            value = num(data[-1])
            if value is not None:
                p.allocation[name.replace("占净比", "")] = value
    p.allocation_date = str(a_cats[-1]) if a_cats else ""
    p.stock_ratio = p.allocation.get("股票")
    if p.stock_ratio is None:
        positions = js.get("Data_fundSharesPositions") or []
        if positions and isinstance(positions[-1], list) and len(positions[-1]) > 1:
            p.stock_ratio = num(positions[-1][1])

    ranks = js.get("Data_rateInSimilarType") or []
    if ranks and isinstance(ranks[-1], dict):
        rank, total = num(ranks[-1].get("y")), num(ranks[-1].get("sc"))
        if rank and total:
            p.rank, p.rank_total = int(rank), int(total)

    evaluation = js.get("Data_performanceEvaluation") or {}
    for cat, value in zip(evaluation.get("categories") or [], evaluation.get("data") or []):
        v = num(value)
        if v is not None:
            p.evaluation[str(cat)] = v
    return p


def pingzhong(code: str) -> tuple[FundProfile, list[Bar], list[str]]:
    """返回 (档案, 净值序列, 重仓股 secid 列表)。"""
    url = PINGZHONG_URL.format(code=code)
    resp = net.get(url, params={"v": time.strftime("%Y%m%d%H%M")}, headers={"Referer": "https://fund.eastmoney.com/"})
    js = parse_js_vars(resp.text)
    if not js.get("fS_name") and not js.get("Data_netWorthTrend"):
        raise NoData(f"天天基金没有代码为 {code} 的基金（请确认代码，或换成「场内基金/股票」再试）")
    holdings = [str(s) for s in (js.get("stockCodesNew") or []) if isinstance(s, str) and "." in s]
    return profile_from_js(js), nav_bars(js), holdings[:10]


def danjuan(code: str) -> dict[str, str]:
    """蛋卷基金的档案：类型、基金公司、托管行、业绩比较基准、投资策略、成立日期。"""
    payload = net.get_json(DANJUAN_URL.format(code=code))
    data = (payload or {}).get("data") or {}
    if not data:
        raise NoData("蛋卷基金没有该基金的档案")
    return {
        "full_name": str(data.get("fd_full_name") or ""),
        "fund_type": str(data.get("type_desc") or ""),
        "establish_date": str(data.get("found_date") or ""),
        "company": str(data.get("keeper_name") or ""),
        "custodian": str(data.get("trup_name") or ""),
        "benchmark": str(data.get("performance_bench_mark") or ""),
        "strategy": str(data.get("invest_orientation") or "")[:300],
        "manager": str(data.get("manager_name") or ""),
    }


def merge_danjuan(profile: FundProfile, info: dict[str, str]) -> None:
    profile.fund_type = profile.fund_type or info.get("fund_type", "")
    profile.establish_date = profile.establish_date or info.get("establish_date", "")
    profile.company = profile.company or info.get("company", "")
    profile.custodian = profile.custodian or info.get("custodian", "")
    profile.benchmark = profile.benchmark or info.get("benchmark", "")
    profile.strategy = profile.strategy or info.get("strategy", "")
    if not profile.managers and info.get("manager"):
        profile.managers = [FundManager(name=n) for n in re.split(r"[,，、\s]+", info["manager"]) if n]


_TAG = re.compile(r"<[^>]+>")


def parse_holdings(text: str) -> tuple[str, list[Holding]]:
    """FundArchivesDatas 返回 `var apidata={ content:"<html>", ...}`，取最新一季的表格。"""
    m = re.search(r'content\s*:\s*"(.*?)"\s*,\s*arryear', text, re.S)
    html = m.group(1) if m else text
    period = re.search(r"(\d{4}年\d季度)", html)
    first_table = re.search(r"<table.*?</table>", html, re.S)
    if not first_table:
        return "", []
    holdings: list[Holding] = []
    for row in re.findall(r"<tr.*?</tr>", first_table.group(0), re.S):
        cells = [_TAG.sub("", c).strip() for c in re.findall(r"<td.*?>(.*?)</td>", row, re.S)]
        if len(cells) < 3 or not cells[1]:
            continue
        weight = next((num(c) for c in cells[3:] if re.fullmatch(r"-?\d+(\.\d+)?%", c)), None)
        holdings.append(Holding(code=cells[1], name=cells[2], weight=weight))
    return (period.group(1) if period else ""), holdings[:10]


def holdings(code: str) -> tuple[str, list[Holding]]:
    params = {"type": "jjcc", "code": code, "topline": "10", "year": "", "month": "", "rt": f"{random.random():.16f}"}
    headers = {"Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html", "X-Requested-With": "XMLHttpRequest"}
    resp = net.get(ARCHIVES_URL, params=params, headers=headers)
    return parse_holdings(resp.text)


def search(text: str) -> list[Instrument]:
    """场外基金按名称/拼音/代码搜索。"""
    payload = net.get_json(FUND_SEARCH_URL, params={"m": "1", "key": text})
    return parse_fund_search(payload)


def parse_fund_search(payload: dict) -> list[Instrument]:
    out: list[Instrument] = []
    for item in (payload or {}).get("Datas") or []:
        code = str(item.get("CODE") or "")
        name = str(item.get("NAME") or "")
        category = str(item.get("CATEGORYDESC") or "")
        if re.fullmatch(r"\d{6}", code) and name and (not category or "基金" in category):
            out.append(Instrument(code, "OF", "fund", name))
    return out
