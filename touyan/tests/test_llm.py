"""大模型客户端：用假的 SDK 客户端核对请求参数、流式输出、错误映射。不联网。"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
import httpx2

from agents.llm import Cancelled, LLMConfig, LLMError, ThinkFilter, make_llm, strip_think


class ThinkFilterTest(unittest.TestCase):
    def run_chunks(self, text, size):
        f = ThinkFilter()
        out = "".join(f.feed(text[i:i + size]) for i in range(0, len(text), size))
        return out + f.flush()

    def test_tags_split_across_chunks(self):
        text = "前言<think>内部推理很长很长</think>正文 a < b 结束"
        for size in range(1, 12):
            self.assertEqual(self.run_chunks(text, size), "前言正文 a < b 结束", size)

    def test_unclosed_think_is_dropped(self):
        self.assertEqual(self.run_chunks("<think>还没想完", 3), "")
        self.assertEqual(strip_think("答案<think>尾巴"), "答案")
        self.assertEqual(strip_think("<think>x</think>\n\n结论"), "结论")


def chunk(text=None, finish=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)])


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeOpenAI:
    last = None

    def __init__(self, **kwargs):
        FakeOpenAI.last = self
        self.init = kwargs
        self.kwargs = None
        self.result = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        self.stream = FakeStream(self.result)
        return self.stream


class OpenAICompatTest(unittest.TestCase):
    def make(self, **cfg):
        base = dict(provider="deepseek", model="deepseek-flash", api_key="sk-x")
        base.update(cfg)
        with mock.patch("openai.OpenAI", FakeOpenAI):
            return make_llm(LLMConfig(**base))

    def test_stream_filters_think_and_defaults(self):
        llm = self.make()
        FakeOpenAI.last.result = [chunk("<thi"), chunk("nk>推理</think>报告"), chunk("正文"), chunk(None, "stop")]
        got = []
        text = llm.complete("系统", "用户", on_delta=got.append)
        self.assertEqual(text, "报告正文")
        self.assertEqual("".join(got), "报告正文")
        kw = FakeOpenAI.last.kwargs
        self.assertTrue(kw["stream"])
        self.assertNotIn("temperature", kw)
        self.assertNotIn("max_tokens", kw)
        self.assertEqual(FakeOpenAI.last.init["base_url"], "https://api.deepseek.com")
        self.assertTrue(FakeOpenAI.last.stream.closed)

    def test_overrides_and_truncation_note(self):
        llm = self.make(temperature=0.2, max_tokens=4096, base_url="https://relay.example.com/v1/")
        FakeOpenAI.last.result = [chunk("部分"), chunk(None, "length")]
        text = llm.complete("s", "u")
        self.assertIn("长度上限", text)
        self.assertEqual((FakeOpenAI.last.kwargs["temperature"], FakeOpenAI.last.kwargs["max_tokens"]), (0.2, 4096))
        self.assertEqual(FakeOpenAI.last.init["base_url"], "https://relay.example.com/v1")

    def test_error_mapping(self):
        req = httpx2.Request("POST", "https://api.deepseek.com/chat/completions")
        import openai
        cases = [
            (openai.AuthenticationError("bad", response=httpx2.Response(401, request=req), body=None), "API Key 无效"),
            (openai.NotFoundError("nf", response=httpx2.Response(404, request=req), body=None), "不存在"),
            (openai.RateLimitError("rl", response=httpx2.Response(429, request=req), body=None), "429"),
            (openai.APIConnectionError(request=req), "无法连接"),
        ]
        for exc, words in cases:
            llm = self.make()
            FakeOpenAI.last.result = exc
            with self.assertRaises(LLMError) as ctx:
                llm.complete("s", "u")
            self.assertIn(words, str(ctx.exception))

    def test_empty_reply_and_cancel(self):
        llm = self.make()
        FakeOpenAI.last.result = [chunk("<think>只有推理</think>"), chunk(None, "stop")]
        with self.assertRaises(LLMError):
            llm.complete("s", "u")
        llm = self.make()
        FakeOpenAI.last.result = [chunk("a"), chunk("b")]
        ev = threading.Event()
        ev.set()
        with self.assertRaises(Cancelled):
            llm.complete("s", "u", cancel=ev)

    def test_config_validation(self):
        with self.assertRaises(LLMError):
            make_llm(LLMConfig(provider="deepseek", model="deepseek-flash", api_key=""))
        with self.assertRaises(LLMError):
            make_llm(LLMConfig(provider="custom", model="m"))
        with self.assertRaises(LLMError):
            make_llm(LLMConfig(provider="qwen", model="", api_key="k"))
        with mock.patch("openai.OpenAI", FakeOpenAI):
            make_llm(LLMConfig(provider="ollama", model="qwen3:latest"))   # 本机模型不需要 Key


class FakeMessageStream:
    def __init__(self, texts, stop):
        self.text_stream = iter(texts)
        self.stop = stop

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop)


class FakeAnthropic:
    last = None

    def __init__(self, **kwargs):
        FakeAnthropic.last = self
        self.init = kwargs
        self.calls = []
        self.texts, self.stop = ["结论", "正文"], "end_turn"
        self.messages = SimpleNamespace(stream=lambda **p: self._stream("messages", p))
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **p: self._stream("beta", p)))

    def _stream(self, kind, params):
        self.calls.append((kind, params))
        return FakeMessageStream(self.texts, self.stop)


class ClaudeTest(unittest.TestCase):
    def make(self, **cfg):
        base = dict(provider="anthropic", model="claude-opus-5-5", api_key="sk-ant-x", effort="high")
        base.update(cfg)
        with mock.patch("anthropic.Anthropic", FakeAnthropic):
            return make_llm(LLMConfig(**base))

    def test_request_shape_on_first_party_api(self):
        llm = self.make(temperature=0.7)
        got = []
        self.assertEqual(llm.complete("系统", "用户", on_delta=got.append), "结论正文")
        kind, params = FakeAnthropic.last.calls[0]
        self.assertEqual(kind, "beta")
        self.assertEqual(params["fallbacks"], "default")
        self.assertEqual(params["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(params["output_config"], {"effort": "high"})
        self.assertEqual(params["max_tokens"], 64000)
        self.assertEqual(params["system"], "系统")
        self.assertNotIn("temperature", params, "Claude 不接受 temperature")
        self.assertNotIn("thinking", params)
        self.assertEqual(got, ["结论", "正文"])

    def test_relay_and_models_without_fallback(self):
        self.make(base_url="https://relay.example.com").complete("s", "u")
        self.assertEqual(FakeAnthropic.last.calls[0][0], "messages")
        self.make(model="claude-haiku-5-5").complete("s", "u")
        self.assertEqual(FakeAnthropic.last.calls[0][0], "messages", "Haiku 5.5 没有服务端回退")
        self.make(model="claude-haiku-4-5").complete("s", "u")
        self.assertNotIn("output_config", FakeAnthropic.last.calls[0][1], "Haiku 4.5 不支持 effort")

    def test_refusal_and_truncation(self):
        llm = self.make()
        FakeAnthropic.last.stop = "refusal"
        with self.assertRaises(LLMError) as ctx:
            llm.complete("s", "u")
        self.assertIn("安全策略", str(ctx.exception))
        llm = self.make()
        FakeAnthropic.last.stop = "max_tokens"
        self.assertIn("长度上限", llm.complete("s", "u"))


if __name__ == "__main__":
    unittest.main()
