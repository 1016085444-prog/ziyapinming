"""证券代码解析：把用户随手输入的代码变成规范的 Instrument。纯函数，不联网。

支持的写法（大小写、全角半角都可以）：

    A 股        600519  sh600519  600519.SH  600519.SS
    北交所      830799  bj830799
    港股        00700   700.HK    hk00700
    美股        AAPL    BRK.B     us.AAPL
    场内基金    510300  159915（ETF、LOF、REITs）
    场外基金    of110011  110011.OF（或在界面上选「场外基金」）
    指数        sh000001  sz399006  沪深300  恒生指数  标普500

6 位纯数字代码有歧义：000001 既是平安银行、也是上证指数的代码、还是一只场外基金。
这里按号段给出最可能的一种，同时由 alternatives() 列出其余可能，交给用户选——
猜错品种比让用户多点一下的代价大得多。
"""

from __future__ import annotations

import re
import unicodedata

from market.models import Instrument

# ── 常用指数（名称 → 规范身份）────────────────────────────────────
# secid 取自东方财富行情系统：沪市 1.、深市 0.、全球指数 100.
_INDICES: dict[str, tuple[str, str, str, str, str]] = {
    # 名称: (code, market, secid, currency, 规范名称)
    "上证指数": ("000001", "SH", "1.000001", "CNY", "上证指数"),
    "上证综指": ("000001", "SH", "1.000001", "CNY", "上证指数"),
    "深证成指": ("399001", "SZ", "0.399001", "CNY", "深证成指"),
    "创业板指": ("399006", "SZ", "0.399006", "CNY", "创业板指"),
    "沪深300": ("000300", "SH", "1.000300", "CNY", "沪深300"),
    "中证500": ("000905", "SH", "1.000905", "CNY", "中证500"),
    "中证1000": ("000852", "SH", "1.000852", "CNY", "中证1000"),
    "上证50": ("000016", "SH", "1.000016", "CNY", "上证50"),
    "科创50": ("000688", "SH", "1.000688", "CNY", "科创50"),
    "恒生指数": ("HSI", "GI", "100.HSI", "HKD", "恒生指数"),
    "国企指数": ("HSCEI", "GI", "100.HSCEI", "HKD", "恒生中国企业指数"),
    "标普500": ("SPX", "GI", "100.SPX", "USD", "标普500"),
    "纳斯达克100": ("NDX", "GI", "100.NDX", "USD", "纳斯达克100"),
    "纳斯达克": ("NDX", "GI", "100.NDX", "USD", "纳斯达克100"),
    "道琼斯": ("DJIA", "GI", "100.DJIA", "USD", "道琼斯工业指数"),
    "日经225": ("N225", "GI", "100.N225", "JPY", "日经225"),
}
# 指数的英文代码也认（HSI、SPX……），但要排在美股代码规则之前，否则 SPX 会被当成美股
_INDEX_CODES = {v[0]: k for k, v in _INDICES.items() if v[1] == "GI"}

# 美股交易所：东方财富 105=纳斯达克 106=纽交所 107=美交所/NYSE Arca。
# 不知道交易所时按这里的提示决定尝试顺序，三个都会试，提示错了只是多一次请求。
_US_NYSE_HINT = {
    "BRK.A", "BRK.B", "JPM", "V", "MA", "KO", "WMT", "BABA", "JNJ", "PG", "XOM",
    "DIS", "NKE", "TSM", "ORCL", "UNH", "HD", "BA", "GE", "IBM", "NIO", "LI",
    "XPEV", "TME", "BAC", "C", "GS", "MS", "CVX", "PFE", "MRK", "T", "VZ",
}
_US_ARCA_HINT = {"SPY", "IWM", "DIA", "VOO", "GLD", "SLV", "VTI", "XLF", "XLK", "EEM", "KWEB"}

_SAFE_CODE = re.compile(r"^[A-Z0-9._\-]{1,16}$")
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z])?$")

CSI300 = Instrument("000300", "SH", "index", "沪深300", "1.000300", "CNY")
HSI = Instrument("HSI", "GI", "index", "恒生指数", "100.HSI", "HKD")
SPX = Instrument("SPX", "GI", "index", "标普500", "100.SPX", "USD")


def _norm(text: str) -> str:
    """全角转半角、去空白、转大写。用户从别处复制来的代码常带全角字符。"""
    s = unicodedata.normalize("NFKC", text or "").strip()
    return re.sub(r"\s+", "", s)


def is_safe_code(code: str) -> bool:
    """代码会被拼进 URL 和文件名，只放行字母、数字和 . _ -。"""
    return bool(code) and bool(_SAFE_CODE.fullmatch(code)) and set(code) != {"."}


def _index(name: str) -> Instrument:
    code, market, secid, currency, canonical = _INDICES[name]
    return Instrument(code, market, "index", canonical, secid, currency)


def classify_six(code: str) -> tuple[str, str]:
    """6 位数字代码按号段归类为 (market, kind)。只看号段，不联网。"""
    p2, p3 = code[:2], code[:3]
    if p3 in ("600", "601", "603", "605", "688", "689", "900"):
        return "SH", "stock"
    if p3 in ("000", "001", "002", "003", "300", "301", "200"):
        return "SZ", "stock"
    if p2 in ("43", "83", "87", "88") or p3 == "920":
        return "BJ", "stock"
    # 沪市基金：51x/52x ETF、56x/58x ETF、50x LOF/封基、508 REITs
    if p2 in ("50", "51", "52", "56", "58"):
        return "SH", "etf"
    # 深市基金：159 ETF、16x LOF、18x REITs
    if p2 in ("15", "16", "18"):
        return "SZ", "etf"
    if p3 == "399":
        return "SZ", "index"
    # 其余 6 位代码最可能是场外基金（110011、005827……）
    return "OF", "fund"


def _from_six(code: str, kind: str) -> Instrument:
    if kind == "fund":
        return Instrument(code, "OF", "fund")
    if kind == "index":
        market = "SZ" if code.startswith("399") else "SH"
        return Instrument(code, market, "index", secid=f"{1 if market == 'SH' else 0}.{code}")
    market, guessed = classify_six(code)
    if kind == "etf" and guessed != "etf":
        market = "SH" if code[0] in "56" else "SZ"
        guessed = "etf"
    if kind == "stock" and guessed in ("fund", "etf", "index"):
        guessed = "stock"
        market = "SH" if code[0] in "69" else ("BJ" if code[0] in "48" else "SZ")
    inst = Instrument(code, market, guessed)
    inst.secid = em_secid(inst)
    return inst


def parse(text: str, kind: str = "auto") -> Instrument | None:
    """解析一个代码。认不出（比如输入的是中文名称）返回 None，交给搜索。

    kind 是用户在界面上明确选的品种：auto / stock / etf / fund / index。
    """
    s = _norm(text)
    if not s:
        return None
    if s in _INDICES:
        return _index(s)
    up = s.upper()
    if up in _INDEX_CODES:
        return _index(_INDEX_CODES[up])

    # 带市场前缀：sh600519、SZ.000001、bj830799、of110011
    m = re.fullmatch(r"(SH|SZ|BJ)[.:]?(\d{6})", up)
    if m:
        market, code = m.groups()
        if (market == "SH" and code.startswith("000")) or (market == "SZ" and code.startswith("399")):
            return Instrument(code, market, "index", secid=f"{1 if market == 'SH' else 0}.{code}")
        guessed_market, guessed_kind = classify_six(code)
        k = guessed_kind if guessed_market == market else "stock"
        if kind in ("stock", "etf"):
            k = kind
        inst = Instrument(code, market, k)
        inst.secid = em_secid(inst)
        return inst
    m = re.fullmatch(r"OF[.:]?(\d{6})", up) or re.fullmatch(r"(\d{6})\.OF", up)
    if m:
        return Instrument(m.group(1), "OF", "fund")
    # 带后缀：600519.SH / 600519.SS / 000001.SZ / 830799.BJ
    m = re.fullmatch(r"(\d{6})\.(SH|SS|SZ|BJ)", up)
    if m:
        code, suffix = m.groups()
        return parse({"SS": "SH"}.get(suffix, suffix) + code, kind)
    # 港股：00700 / 700.HK / hk700 / HK.00700
    m = (re.fullmatch(r"HK[.:]?(\d{1,5})", up) or re.fullmatch(r"(\d{1,5})\.HK", up)
         or (re.fullmatch(r"(\d{1,5})", up) if kind in ("auto", "stock") else None))
    if m:
        code = m.group(1).zfill(5)
        return Instrument(code, "HK", "stock", secid=f"116.{code}", currency="HKD")
    # 纯 6 位数字
    if re.fullmatch(r"\d{6}", up):
        return _from_six(up, kind)
    # 美股：AAPL / BRK.B / us.AAPL / AAPL.US
    m = re.fullmatch(r"US[.:]([A-Z][A-Z0-9.\-]*)", up) or re.fullmatch(r"([A-Z][A-Z0-9.\-]*)\.US", up)
    ticker = m.group(1) if m else up
    if _US_TICKER.fullmatch(ticker):
        return Instrument(ticker, "US", "etf" if kind == "etf" else "stock", currency="USD")
    return None


def alternatives(text: str) -> list[Instrument]:
    """一个代码可能指向的全部品种，最可能的排第一。用于离线时的候选列表。"""
    first = parse(text)
    if first is None:
        return []
    out = [first]
    s = _norm(text).upper()
    if re.fullmatch(r"\d{6}", s):
        if s.startswith("000"):
            out.append(Instrument(s, "SH", "index", secid=f"1.{s}"))
        if first.kind != "fund":
            out.append(Instrument(s, "OF", "fund"))
        elif s[:2] in ("50", "51", "52", "56", "58", "15", "16", "18"):
            out.append(_from_six(s, "etf"))
    seen, unique = set(), []
    for inst in out:
        if inst.key not in seen:
            seen.add(inst.key)
            unique.append(inst)
    return unique


def from_key(key: str, kind: str = "", name: str = "", secid: str = "") -> Instrument | None:
    """由 MARKET:CODE（如 SH:600519、OF:110011、US:AAPL）还原 Instrument。非法输入返回 None。"""
    market, _, code = (key or "").partition(":")
    market, code = market.upper(), _norm(code).upper()
    if not is_safe_code(code):
        return None
    if secid and not re.fullmatch(r"\d{1,3}\.[A-Z0-9_.\-]{1,16}", secid.upper()):
        secid = ""
    if market == "OF" and re.fullmatch(r"\d{6}", code):
        return Instrument(code, "OF", "fund", name)
    if market in ("SH", "SZ", "BJ") and re.fullmatch(r"\d{6}", code):
        inst = parse(market + code, kind if kind in ("stock", "etf") else "auto")
        if inst is None:
            return None
        if kind == "index":
            inst.kind = "index"
        inst.name = name or inst.name
        return inst
    if market == "HK" and code.isdigit():
        code = code.zfill(5)
        return Instrument(code, "HK", "stock", name, secid or f"116.{code}", "HKD")
    if market == "US" and _US_TICKER.fullmatch(code):
        return Instrument(code, "US", kind if kind in ("stock", "etf") else "stock", name, secid.upper(), "USD")
    if market == "GI":
        if code in _INDEX_CODES:
            return _index(_INDEX_CODES[code])
        return Instrument(code, "GI", "index", name, secid or f"100.{code}", "HKD" if code in ("HSI", "HSCEI") else "USD")
    return None


def em_secid(inst: Instrument) -> str:
    """东方财富行情 ID。美股不知道交易所时返回空串，由路由层补全。场外基金没有行情 ID。"""
    if inst.secid:
        return inst.secid
    if inst.market == "SH":
        return f"1.{inst.code}"
    if inst.market in ("SZ", "BJ"):
        return f"0.{inst.code}"
    if inst.market == "HK":
        return f"116.{inst.code}"
    if inst.market == "GI":
        return f"100.{inst.code}"
    return ""


def us_secid_candidates(ticker: str) -> list[str]:
    """美股可能的 secid，按提示排序。东方财富把 BRK.B 写成 BRK_B。"""
    em = ticker.replace(".", "_").replace("-", "_")
    order = ["105", "106", "107"]
    if ticker in _US_NYSE_HINT:
        order = ["106", "105", "107"]
    elif ticker in _US_ARCA_HINT:
        order = ["107", "106", "105"]
    return [f"{market}.{em}" for market in order]


def tencent_symbol(inst: Instrument) -> str:
    """腾讯行情代码。不支持的品种返回空串。"""
    if inst.market in ("SH", "SZ", "BJ"):
        return inst.market.lower() + inst.code
    if inst.market == "HK":
        return "hk" + inst.code.zfill(5)
    if inst.market == "GI" and inst.code in ("HSI", "HSCEI"):
        return "hk" + inst.code
    if inst.market == "US":
        return "us" + inst.code.replace(".", "_")
    return ""


def benchmark_for(inst: Instrument) -> Instrument:
    """对比基准：A 股与人民币基金看沪深300，港股看恒生指数，美股看标普500。"""
    if inst.market == "HK" or (inst.market == "GI" and inst.currency == "HKD"):
        return HSI
    if inst.market == "US" or (inst.market == "GI" and inst.currency != "CNY"):
        return SPX
    return CSI300


def from_search_item(item: dict) -> Instrument | None:
    """东方财富搜索接口的一条结果 → Instrument。债券、期货等不支持的品种返回 None。"""
    code = str(item.get("Code") or "").strip().upper()
    name = str(item.get("Name") or "").strip()
    quote_id = str(item.get("QuoteID") or "").strip()
    classify = str(item.get("Classify") or "")
    type_name = str(item.get("SecurityTypeName") or "")
    if not code or not is_safe_code(code):
        return None
    mkt = quote_id.split(".", 1)[0] if "." in quote_id else ""
    if classify in ("AStock", "NEEQ") or type_name in ("沪A", "深A", "京A", "科创板", "创业板"):
        if mkt == "1":
            return Instrument(code, "SH", "stock", name, quote_id)
        if mkt == "0":
            market = "BJ" if ("京" in type_name or code[:2] in ("43", "83", "87", "88") or code.startswith("920")) else "SZ"
            return Instrument(code, market, "stock", name, quote_id)
        return None
    if classify == "HK" or "港" in type_name:
        if not code.isdigit():
            return None
        return Instrument(code.zfill(5), "HK", "stock", name, quote_id or f"116.{code.zfill(5)}", "HKD")
    if classify == "UsStock" or "美" in type_name:
        return Instrument(code, "US", "stock", name, quote_id, "USD")
    if classify in ("Index", "UniversalIndex") or "指数" in type_name:
        if mkt == "1":
            return Instrument(code, "SH", "index", name, quote_id)
        if mkt == "0":
            return Instrument(code, "SZ", "index", name, quote_id)
        if mkt == "100":
            currency = "HKD" if code in ("HSI", "HSCEI") else "USD"
            return Instrument(code, "GI", "index", name, quote_id, currency)
        return None
    if classify == "Fund" or "基金" in type_name:
        if not re.fullmatch(r"\d{6}", code):
            return None
        if mkt in ("0", "1"):
            return Instrument(code, "SH" if mkt == "1" else "SZ", "etf", name, quote_id)
        return Instrument(code, "OF", "fund", name)
    return None
