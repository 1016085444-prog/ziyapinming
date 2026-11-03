"""OpenAI 兼容接口：DeepSeek、通义千问、智谱、Kimi、MiniMax、硅基流动、OpenAI、Gemini、
OpenRouter、Ollama、vLLM、各类中转站……用官方 openai SDK，只改 base_url。

几处兼容性处理：
- DeepSeek 等推理模型把思考过程放在 delta.reasoning_content，这里只取正文 content；
- Qwen3 / GLM / MiniMax / 本地模型可能把思考写成正文里的 <think>…</think>，流式过滤掉；
- temperature、max_tokens 默认不传：新一代推理模型多半忽略或拒绝 temperature，
  各家 max_tokens 上限也不同，留给服务端默认值最稳。设置里可以手动指定。
"""

from __future__ import annotations

import threading

import openai

from agents import providers
from agents.llm import Cancelled, DeltaFn, LLMConfig, LLMError, ThinkFilter, strip_think


class OpenAICompatLLM:
    def __init__(self, cfg: LLMConfig, base_url: str):
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")
        self.provider = providers.get(cfg.provider)
        self.label = f"{self.provider.label} · {cfg.model}"
        self.client = openai.OpenAI(
            api_key=cfg.api_key or "not-needed",
            base_url=self.base_url,
            timeout=cfg.timeout,
            max_retries=2,
        )

    def complete(self, system: str, user: str, on_delta: DeltaFn | None = None,
                 cancel: threading.Event | None = None) -> str:
        kwargs = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": True,
        }
        if self.cfg.temperature is not None:
            kwargs["temperature"] = self.cfg.temperature
        if self.cfg.max_tokens:
            kwargs["max_tokens"] = self.cfg.max_tokens
        parts: list[str] = []
        finish = None
        filt = ThinkFilter()
        try:
            stream = self.client.chat.completions.create(**kwargs)
            try:
                for chunk in stream:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    text = getattr(choice.delta, "content", None) if choice.delta else None
                    if text:
                        parts.append(text)
                        visible = filt.feed(text)
                        if visible and on_delta:
                            on_delta(visible)
                    if choice.finish_reason:
                        finish = choice.finish_reason
            finally:
                stream.close()
            tail = filt.flush()
            if tail and on_delta:
                on_delta(tail)
        except Cancelled:
            raise
        except openai.AuthenticationError as exc:
            raise LLMError(f"{self.provider.label} 的 API Key 无效或已过期，请到「设置」检查") from exc
        except openai.PermissionDeniedError as exc:
            raise LLMError(f"{self.provider.label} 拒绝访问：账号没有该模型的权限，或余额不足") from exc
        except openai.NotFoundError as exc:
            raise LLMError(f"模型「{self.cfg.model}」不存在或当前账号不可用，请到「设置」核对模型名") from exc
        except openai.RateLimitError as exc:
            raise LLMError(f"{self.provider.label} 返回 429：请求太频繁或账户余额不足，请稍后再试或检查余额") from exc
        except openai.BadRequestError as exc:
            raise LLMError(f"{self.provider.label} 拒绝了请求：{_message(exc)}") from exc
        except openai.APITimeoutError as exc:
            raise LLMError(f"{self.provider.label} 响应超时，请稍后重试") from exc
        except openai.APIConnectionError as exc:
            hint = "（该服务在国内通常需要代理）" if self.provider.region == "intl" else ""
            raise LLMError(f"无法连接 {self.base_url}{hint}，请检查网络") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"{self.provider.label} 服务出错（HTTP {exc.status_code}）：{_message(exc)}") from exc
        except openai.APIError as exc:
            raise LLMError(f"{self.provider.label} 调用失败：{_message(exc)}") from exc
        text = strip_think("".join(parts))
        if not text:
            raise LLMError(f"{self.provider.label} 返回了空内容（模型「{self.cfg.model}」可能不适合长文本生成）")
        if finish == "length":
            text += "\n\n（输出达到长度上限，以上内容可能不完整。可在「设置」里调大最大输出长度）"
        return text


def _message(exc: Exception) -> str:
    msg = getattr(exc, "message", None) or str(exc)
    return str(msg)[:300]
