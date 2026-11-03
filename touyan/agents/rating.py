"""五档评级的解析。决策类智能体（研究主管、交易员、投资经理）在正文末尾输出一个 JSON 块，
这里优先读 JSON；读不到再从「评级：X」这类标注行里找。

沿用 TradingAgents 的原则（#1170）：**读不出评级就是 REVIEW（待复核），绝不默认成「持有」。**
一个没人能读懂的决策不是「持有」；把它记成持有，下次复盘时会被当成一个真实做过的判断。
同样，正文里出现的评级词可能是在反驳（「不是卖出」），所以只认带标注的行。
"""

from __future__ import annotations

import json
import re
import unicodedata

from quant.scoring import RATING_LABELS

REVIEW = "REVIEW"

_ALIASES = {
    "buy": "Buy", "strong buy": "Buy", "买入": "Buy", "强烈推荐": "Buy", "强推": "Buy",
    "overweight": "Overweight", "增持": "Overweight", "推荐": "Overweight", "谨慎增持": "Overweight",
    "hold": "Hold", "持有": "Hold", "中性": "Hold", "观望": "Hold",
    "underweight": "Underweight", "减持": "Underweight", "谨慎减持": "Underweight",
    "sell": "Sell", "卖出": "Sell", "回避": "Sell",
}
_TRADER = {"buy": "Buy", "买入": "Buy", "hold": "Hold", "持有": "Hold", "观望": "Hold", "sell": "Sell", "卖出": "Sell"}
TRADER_LABELS = {"Buy": "买入", "Hold": "持有/观望", "Sell": "卖出"}

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_WORDS = "|".join(sorted((re.escape(k) for k in _ALIASES), key=len, reverse=True))
_LABEL_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?[#*_\s]*(?:最终|综合|我的|本次)?(?:投资)?(?:评级|建议|结论|rating|recommendation)[*_\s]*[:：\-—]\s*[*_\s]*(" + _WORDS + r")",
    re.I | re.M,
)


def normalize(value) -> str | None:
    if not isinstance(value, str):
        return None
    key = unicodedata.normalize("NFKC", value).strip().strip("*").strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    for alias, code in _ALIASES.items():   # 「增持（Overweight）」这类混写
        if key.startswith(alias):
            return code
    return None


def normalize_action(value) -> str | None:
    if not isinstance(value, str):
        return None
    key = unicodedata.normalize("NFKC", value).strip().lower()
    for alias, code in _TRADER.items():
        if key.startswith(alias):
            return code
    return None


def json_block(text: str) -> dict:
    """正文里最后一个 ```json {...}``` 块。没有或解析失败返回 {}。"""
    blocks = _JSON_BLOCK.findall(text or "")
    for raw in reversed(blocks):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def strip_json_block(text: str) -> str:
    """展示用：去掉末尾的 JSON 块（界面上单独用卡片呈现）。"""
    return _JSON_BLOCK.sub("", text or "").rstrip()


def extract_rating(text: str) -> str | None:
    data = json_block(text)
    code = normalize(data.get("rating")) if data else None
    if code:
        return code
    norm = unicodedata.normalize("NFKC", text or "")
    found = {normalize(m) for m in _LABEL_LINE.findall(norm)}
    found.discard(None)
    # 多个标注行给出不同评级 → 无法判断哪个是结论
    return found.pop() if len(found) == 1 else None


def parse_rating(text: str) -> str:
    return extract_rating(text) or REVIEW


def label(code: str) -> str:
    return RATING_LABELS.get(code, "待复核")


def to_float(value) -> float | None:
    """模型写进 JSON 的价格：去掉货币符号和千分位；百分比、区间、"N/A" 一律丢弃（学自 TradingAgents #1058/#1288）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and value > 0 else None
    text = str(value).strip()
    if not text or text.endswith("%") or text.lower() in ("none", "null", "n/a", "na", "-", "无", "未提供"):
        return None
    text = text.replace(",", "").lstrip("¥$€£HK").replace("元", "").strip()
    try:
        v = float(text)
    except ValueError:
        return None
    return v if v > 0 else None
