"""CSV 导入：数据源覆盖不到的产品（银行理财、私募、信托、自己记录的净值……）也能分析。

只要求两列：日期 + 价格/净值。表头不区分中英文、大小写：

    日期 / date / 净值日期 / trade_date
    收盘 / close / 单位净值 / 净值 / nav / price / 累计净值
    开盘 open、最高 high、最低 low、成交量 volume  （可选）

分隔符自动识别（逗号、制表符、分号），编码先试 UTF-8 再试 GBK（Excel 另存的中文 CSV 常是 GBK）。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from market.eastmoney import num
from market.models import Bar

_DATE_KEYS = ("日期", "date", "净值日期", "trade_date", "交易日期", "time", "时间")
_CLOSE_KEYS = ("复权净值", "adj_close", "累计净值", "收盘", "收盘价", "close", "单位净值", "净值", "nav", "price", "价格")
_OPEN_KEYS = ("开盘", "开盘价", "open")
_HIGH_KEYS = ("最高", "最高价", "high")
_LOW_KEYS = ("最低", "最低价", "low")
_VOL_KEYS = ("成交量", "volume", "vol")

MAX_BYTES = 5 * 1024 * 1024


class CSVError(ValueError):
    pass


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CSVError("无法识别文件编码，请另存为 UTF-8 或 GBK 编码的 CSV")


def _parse_date(text: str) -> str | None:
    s = text.strip().replace("/", "-").replace(".", "-")
    s = re.sub(r"[年月]", "-", s).replace("日", "")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19] if " " in s else s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _find(headers: list[str], keys: tuple[str, ...]) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for key in keys:
        if key.lower() in lowered:
            return lowered.index(key.lower())
    return None


def parse_csv(raw: bytes) -> list[Bar]:
    if len(raw) > MAX_BYTES:
        raise CSVError("文件太大（上限 5MB）")
    text = _decode(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise CSVError("文件里没有数据行")
    header = rows[0]
    i_date = _find(header, _DATE_KEYS)
    i_close = _find(header, _CLOSE_KEYS)
    if i_date is None or i_close is None:
        raise CSVError("找不到「日期」和「收盘价/净值」两列。请确认表头，例如：日期,收盘")
    i_open, i_high, i_low, i_vol = (_find(header, k) for k in (_OPEN_KEYS, _HIGH_KEYS, _LOW_KEYS, _VOL_KEYS))

    def cell(row, idx):
        return num(row[idx]) if idx is not None and idx < len(row) else None

    by_date: dict[str, Bar] = {}
    for row in rows[1:]:
        if i_date >= len(row):
            continue
        day = _parse_date(row[i_date])
        close = cell(row, i_close)
        if not day or close is None or close <= 0:
            continue
        o = cell(row, i_open) or close
        h = cell(row, i_high) or max(o, close)
        lo = cell(row, i_low) or min(o, close)
        by_date[day] = Bar(date=day, open=o, high=max(h, o, close), low=min(lo, o, close),
                           close=close, volume=cell(row, i_vol) or 0.0)
    bars = [by_date[d] for d in sorted(by_date)]
    if len(bars) < 20:
        raise CSVError(f"有效数据只有 {len(bars)} 行，至少需要 20 个交易日才能分析")
    return bars
