"""Claude：走 Anthropic 官方 SDK（anthropic），不经 OpenAI 兼容层。

按当前 API 的要求处理：
- 不传 temperature / top_p（API 版本 2026-10-21 起一律 400）；
- 不传 thinking：Opus 5.5 / Sonnet 5.5 / Haiku 5.5 / Fable 5.1 默认自适应思考，
  深度由 output_config.effort 控制（默认 high，可在设置里调整）；
- 流式输出，max_tokens 给足 64000，避免长报告被截断；
- 安全策略拒答（stop_reason == "refusal"）时报清楚原因；直连官方 API 时默认开启
  服务端回退（fallbacks="default"），被拒的请求由 Anthropic 自动交给推荐的备用模型重跑。
  走自定义中转地址时不开启——中转站未必支持这个 beta。
"""

from __future__ import annotations

import threading

import anthropic

from agents.llm import Cancelled, DeltaFn, LLMConfig, LLMError

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 支持服务端回退 fallbacks="default" 的模型
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
DEFAULT_MAX_TOKENS = 64000


def supports_effort(model: str) -> bool:
    """output_config.effort：4.5 以后的 Opus、5 代以后的全系支持；Haiku 4.5 及更早不支持。"""
    m = model.lower()
    return not (m.startswith("claude-3") or m.startswith("claude-haiku-4") or m.startswith("claude-sonnet-4-5"))


class ClaudeLLM:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.label = f"Claude · {cfg.model}"
        kwargs = {"api_key": cfg.api_key, "max_retries": 2, "timeout": cfg.timeout}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url.rstrip("/")
        self.client = anthropic.Anthropic(**kwargs)
        self.use_fallbacks = not cfg.base_url and cfg.model in FALLBACK_MODELS

    def complete(self, system: str, user: str, on_delta: DeltaFn | None = None,
                 cancel: threading.Event | None = None) -> str:
        params = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens or DEFAULT_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self.cfg.effort and supports_effort(self.cfg.model):
            params["output_config"] = {"effort": self.cfg.effort}
        parts: list[str] = []
        try:
            if self.use_fallbacks:
                manager = self.client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                manager = self.client.messages.stream(**params)
            with manager as stream:
                for text in stream.text_stream:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    parts.append(text)
                    if on_delta:
                        on_delta(text)
                final = stream.get_final_message()
        except Cancelled:
            raise
        except anthropic.AuthenticationError as exc:
            raise LLMError("Claude 的 API Key 无效，请到「设置」检查") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("Claude 拒绝访问：账号没有该模型的权限，或所在地区不受支持") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Claude 模型「{self.cfg.model}」不存在，请到「设置」核对模型名") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude 返回 429：请求太频繁或额度用尽，请稍后再试") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Claude 拒绝了请求：{exc.message}") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("Claude 响应超时，请稍后重试") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("无法连接 Claude API。国内网络通常无法直连，需要代理，或在「设置」里填写中转地址") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude 服务出错（HTTP {exc.status_code}），请稍后重试") from exc
        if final.stop_reason == "refusal":
            raise LLMError("Claude 按安全策略拒绝了这次请求，可在「设置」中换一个模型后重试")
        text = "".join(parts).strip()
        if not text:
            raise LLMError("Claude 返回了空内容")
        if final.stop_reason == "max_tokens":
            text += "\n\n（输出达到长度上限，以上内容可能不完整）"
        return text
