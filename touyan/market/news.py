"""资讯：个股新闻（东方财富搜索）与市场快讯（东方财富 7x24，新浪 7x24 兜底）。

资讯只是辅助信号：取不到不影响量化分析，智能体会被明确告知「本次没有新闻数据」，
而不是拿到一个空白当作「没有利空」。
"""

from __future__ import annotations

import json
import random
import re
import time
from urllib.parse import quote as urlquote

from market import net
from market.models import NewsItem
from market.net import NoData

COMPANY_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
FAST_NEWS_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
SINA_FEED_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"

_TAG = re.compile(r"<[^>]+>")


def _clean(text) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", str(text or ""))).strip()


def company_news(keyword: str, limit: int = 15) -> list[NewsItem]:
    inner = {
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default", "pageIndex": 1,
            "pageSize": limit, "preTag": "", "postTag": "",
        }},
    }
    cb = f"jQuery3510{random.randint(10**15, 10**16 - 1)}_{int(time.time() * 1000)}"
    params = {"cb": cb, "param": json.dumps(inner, ensure_ascii=False), "_": str(int(time.time() * 1000))}
    headers = {"Referer": f"https://so.eastmoney.com/news/s?keyword={urlquote(keyword)}"}
    resp = net.get(COMPANY_NEWS_URL, params=params, headers=headers)
    return parse_company_news(resp.text)


def parse_company_news(text: str) -> list[NewsItem]:
    """JSONP：callback({...})。去掉外壳再解析。"""
    start, end = text.find("("), text.rfind(")")
    body = text[start + 1:end] if 0 <= start < end else text
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise NoData("东方财富新闻接口返回格式无法识别") from exc
    items = ((payload or {}).get("result") or {}).get("cmsArticleWebOld") or []
    out = []
    for it in items:
        title = _clean(it.get("title"))
        if not title:
            continue
        code = str(it.get("code") or "")
        url = str(it.get("url") or (f"https://finance.eastmoney.com/a/{code}.html" if code else ""))
        out.append(NewsItem(
            title=title, time=str(it.get("date") or "")[:16], source=_clean(it.get("mediaName")),
            url=url, summary=_clean(it.get("content"))[:220],
        ))
    return out


def market_news(limit: int = 30) -> list[NewsItem]:
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "",
        "pageSize": str(limit), "req_trace": str(int(time.time() * 1000)),
    }
    return parse_fast_news(net.get_json(FAST_NEWS_URL, params=params))


def parse_fast_news(payload: dict) -> list[NewsItem]:
    items = ((payload or {}).get("data") or {}).get("fastNewsList") or []
    out = []
    for it in items:
        title = _clean(it.get("title"))
        if not title:
            continue
        code = str(it.get("code") or "")
        out.append(NewsItem(
            title=title, time=str(it.get("showTime") or "")[:16], source="东方财富7x24",
            url=f"https://finance.eastmoney.com/a/{code}.html" if code else "",
            summary=_clean(it.get("summary"))[:220],
        ))
    return out


def sina_market_news(limit: int = 30) -> list[NewsItem]:
    params = {
        "page": "1", "page_size": str(limit), "zhibo_id": "152", "tag_id": "0",
        "dire": "f", "dpc": "1", "pagesize": str(limit), "type": "1",
    }
    return parse_sina_feed(net.get_json(SINA_FEED_URL, params=params))


def parse_sina_feed(payload: dict) -> list[NewsItem]:
    items = ((((payload or {}).get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    out = []
    for it in items:
        text = _clean(it.get("rich_text"))
        if not text:
            continue
        title = text[:60] + ("…" if len(text) > 60 else "")
        out.append(NewsItem(title=title, time=str(it.get("create_time") or "")[:16],
                            source="新浪财经7x24", summary=text[:220]))
    return out
