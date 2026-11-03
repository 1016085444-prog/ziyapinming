"""大模型调用的统一接口。

每个智能体只需要一件事：给系统提示词和用户提示词，流式拿回文本。
OpenAI 兼容接口（DeepSeek、通义、智谱、Kimi、Ollama……）与 Claude 各自一个实现，
分别在 llm_openai.py 与 llm_claude.py——Claude 走 Anthropic 官方 SDK，不经 OpenAI 兼容层。

错误统一成 LLMError，message 用中文直接给用户看，并尽量说清怎么解决。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable, Protocol

from agents import providers

DeltaFn = Callable[[str], None]


class LLMError(Exception):
    """模型调用失败。message 用中文。"""


class Cancelled(Exception):
    """用户取消了任务。"""


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    effort: str | None = None      # 仅 Claude：low / medium / high / xhigh / max
    timeout: float = 300.0


class LLM(Protocol):
    label: str

    def complete(self, system: str, user: str, on_delta: DeltaFn | None = None,
                 cancel: threading.Event | None = None) -> str:
        ...


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str) -> str:
    """去掉推理模型混在正文里的 <think>…</think>（含未闭合的开头块）。"""
    text = _THINK_BLOCK.sub("", text)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


class ThinkFilter:
    """流式过滤 <think> 块。标签可能被拆在两个分片里，所以要留一小段尾巴再判断。"""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while True:
            if self.inside:
                idx = self.buf.find(self.CLOSE)
                if idx < 0:
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[idx + len(self.CLOSE):]
                self.inside = False
            else:
                idx = self.buf.find(self.OPEN)
                if idx < 0:
                    keep = len(self.OPEN) - 1
                    safe = self.buf[:-keep] if len(self.buf) > keep else ""
                    # 尾巴里没有 '<' 就不可能是标签开头，可以全部放行
                    if "<" not in self.buf[-keep:]:
                        safe, self.buf = self.buf, ""
                    else:
                        self.buf = self.buf[len(safe):]
                    out.append(safe)
                    break
                out.append(self.buf[:idx])
                self.buf = self.buf[idx + len(self.OPEN):]
                self.inside = True
        return "".join(out)

    def flush(self) -> str:
        tail, self.buf = ("" if self.inside else self.buf), ""
        return tail


def make_llm(cfg: LLMConfig) -> LLM:
    p = providers.get(cfg.provider)
    if not cfg.model:
        raise LLMError(f"没有设置 {p.label} 的模型名称，请到「设置」里填写")
    if p.needs_key and not cfg.api_key:
        raise LLMError(f"没有设置 {p.label} 的 API Key，请到「设置」里填写，或设置环境变量 {p.key_env}")
    if p.kind == "anthropic":
        from agents.llm_claude import ClaudeLLM
        return ClaudeLLM(cfg)
    from agents.llm_openai import OpenAICompatLLM
    base = cfg.base_url or p.base_url
    if not base:
        raise LLMError("自定义接口需要填写接口地址（Base URL），例如 http://localhost:8000/v1")
    return OpenAICompatLLM(cfg, base)
