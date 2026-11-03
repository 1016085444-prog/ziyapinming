"""共享 HTTP 客户端与数据源错误类型。

集中处理三件事：

1. **浏览器式请求头**。东方财富、腾讯对不带 UA / Referer 的请求常返回空数据。
2. **识别东方财富 push2 限流**。push2 / push2his 在短时间请求较多时不回包、直接断开
   连接。akshare 实测（2026-10-30）：约 5 次密集请求即被封，首次约 5 分钟恢复，反复
   触发可达 40 分钟以上。此时**重试只会延长封禁**，所以一旦识别出来就熔断该数据源
   一段时间，后续请求直接走备用数据源，而不是继续撞墙。
3. **中文错误信息**。SourceError 的 message 会原样展示给用户，要说清是哪个数据源、
   出了什么事、用户能做什么。
"""

from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlsplit

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 熔断时长（秒）。首次限流约 5 分钟恢复，留一点余量。
BAN_SECONDS = int(os.environ.get("TOUYAN_PUSH2_BAN_SECONDS", "360"))


class SourceError(Exception):
    """数据源取数失败。message 用中文，直接给用户看。"""


class RateLimited(SourceError):
    """数据源限流/封禁。调用方应换数据源，不要重试。"""


class NoData(SourceError):
    """请求成功但没有数据（代码不存在、品种不支持等）。"""


_client: httpx.Client | None = None
_client_lock = threading.Lock()
_banned_until: dict[str, float] = {}
_ban_lock = threading.Lock()


def client() -> httpx.Client:
    """进程内共享一个连接池。trust_env=True：尊重用户设置的 HTTP(S)_PROXY。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(
                    headers=DEFAULT_HEADERS,
                    timeout=httpx.Timeout(12.0, connect=6.0),
                    follow_redirects=True,
                    trust_env=True,
                )
    return _client


def source_group(url: str) -> str:
    """把域名归到「数据源组」，熔断按组生效。push2 的各编号子域共用一个封禁。"""
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("eastmoney.com") and "push2" in host:
        return "eastmoney-push2"
    return host


def is_banned(group: str) -> float:
    """该数据源组还要熔断多少秒；0 表示可用。"""
    with _ban_lock:
        left = _banned_until.get(group, 0) - time.time()
    return max(0.0, left)


def ban(group: str, seconds: float = BAN_SECONDS) -> None:
    with _ban_lock:
        _banned_until[group] = time.time() + seconds


def reset_bans() -> None:
    with _ban_lock:
        _banned_until.clear()


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


def get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float | None = None,
    retries: int = 1,
) -> httpx.Response:
    """GET 请求。连接失败、超时、5xx 会重试；push2 断连视为限流，立即熔断不重试。"""
    group = source_group(url)
    left = is_banned(group)
    if left:
        raise RateLimited(
            f"{_host(url)} 正处于限流冷却期（约 {int(left // 60) + 1} 分钟后恢复），已改用备用数据源"
        )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client().get(url, params=params, headers=headers, timeout=timeout)
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            # 服务器不回包就断开：push2 限流的典型表现
            if group == "eastmoney-push2":
                ban(group)
                raise RateLimited(
                    "东方财富行情服务器断开了连接，通常是短时间内请求过多被临时限流"
                    f"（一般 5 分钟左右恢复）。{BAN_SECONDS // 60} 分钟内将自动改用备用数据源。"
                ) from exc
            last = exc
        except httpx.TimeoutException as exc:
            last = exc
        except httpx.TransportError as exc:
            last = exc
        else:
            if resp.status_code == 429:
                ban(group, 120)
                raise RateLimited(f"{_host(url)} 返回 429（请求过于频繁），稍后再试")
            if resp.status_code >= 500:
                last = SourceError(f"{_host(url)} 服务器错误 HTTP {resp.status_code}")
            elif resp.status_code != 200:
                raise SourceError(f"{_host(url)} 返回 HTTP {resp.status_code}")
            else:
                return resp
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    detail = type(last).__name__ if last else "未知错误"
    if isinstance(last, httpx.TimeoutException):
        raise SourceError(f"连接 {_host(url)} 超时，请检查网络")
    if isinstance(last, SourceError):
        raise last
    raise SourceError(f"无法连接 {_host(url)}（{detail}），请检查网络或代理设置")


def get_json(url: str, params: dict | None = None, headers: dict | None = None, **kw):
    resp = get(url, params=params, headers=headers, **kw)
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(f"{_host(url)} 返回的不是有效 JSON，接口可能已变更") from exc
