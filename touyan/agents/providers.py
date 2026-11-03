"""大模型服务商目录。

模型 ID 参照 TradingAgents v0.7.1（2026-10）的 model_catalog，国内厂商用国内站地址。
模型更新很快：下拉列表只是建议，设置页可以直接填任意模型名。

DeepSeek 的 deepseek-chat / deepseek-reasoner 旧别名已于 2026-07 起指向 V4 Flash，
这里直接用 V4 系列的正式 ID。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    kind: str              # openai（OpenAI 兼容接口）| anthropic（Claude 官方 SDK）
    base_url: str
    key_env: str
    quick: str             # 快模型：分析师、研究员、交易员、风控辩手
    deep: str              # 深度模型：研究主管、投资经理
    models: tuple[str, ...] = field(default_factory=tuple)
    signup: str = ""
    note: str = ""
    needs_key: bool = True
    region: str = "cn"     # cn：国内可直连；intl：国内通常需要代理

    def to_dict(self) -> dict:
        d = asdict(self)
        d["models"] = list(self.models)
        return d


PROVIDERS: dict[str, Provider] = {p.key: p for p in [
    Provider(
        "deepseek", "DeepSeek 深度求索", "openai", "https://api.deepseek.com", "DEEPSEEK_API_KEY",
        "deepseek-flash", "deepseek-v4-pro", ("deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash"),
        "https://platform.deepseek.com", "国内直连，价格低，推荐首选",
    ),
    Provider(
        "qwen", "通义千问（阿里云百炼）", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY", "qwen3.8-flash", "qwen3.8-max",
        ("qwen3.8-flash", "qwen3.8-max", "qwen-plus", "qwen-max", "qwen-flash"),
        "https://bailian.console.aliyun.com", "国内直连",
    ),
    Provider(
        "glm", "智谱 GLM", "openai", "https://open.bigmodel.cn/api/paas/v4/", "ZHIPU_API_KEY",
        "glm-5.3-flash", "glm-5.3", ("glm-5.3-flash", "glm-5-turbo", "glm-5.3", "glm-5.2", "glm-4.7"),
        "https://open.bigmodel.cn", "国内直连",
    ),
    Provider(
        "kimi", "Kimi（月之暗面）", "openai", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY",
        "kimi-k2.6", "kimi-k3", ("kimi-k2.6", "kimi-k3"), "https://platform.moonshot.cn", "国内直连",
    ),
    Provider(
        "minimax", "MiniMax", "openai", "https://api.minimaxi.com/v1", "MINIMAX_API_KEY",
        "MiniMax-M3", "MiniMax-M3", ("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"),
        "https://platform.minimaxi.com", "国内直连",
    ),
    Provider(
        "siliconflow", "硅基流动 SiliconFlow", "openai", "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY",
        "", "", (), "https://cloud.siliconflow.cn", "国内直连，模型名请照抄控制台里的完整名称",
    ),
    Provider(
        "anthropic", "Claude（Anthropic）", "anthropic", "", "ANTHROPIC_API_KEY",
        "claude-opus-5-5", "claude-opus-5-5",
        ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
        "https://console.anthropic.com", "官方 SDK 调用；国内网络通常需要代理", region="intl",
    ),
    Provider(
        "openai", "OpenAI", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
        "gpt-6-luna", "gpt-6-sol", ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "gpt-5.6"),
        "https://platform.openai.com", "国内网络通常需要代理", region="intl",
    ),
    Provider(
        "gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GOOGLE_API_KEY", "gemini-3.8-flash", "gemini-3.8-flash",
        ("gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.5-flash"),
        "https://aistudio.google.com", "国内网络通常需要代理", region="intl",
    ),
    Provider(
        "openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        "", "", (), "https://openrouter.ai", "聚合多家模型，模型名形如 厂商/模型", region="intl",
    ),
    Provider(
        "ollama", "Ollama（本机模型）", "openai", "http://localhost:11434/v1", "",
        "qwen3:latest", "qwen3:latest", ("qwen3:latest", "glm-4.7-flash:latest", "gpt-oss:latest"),
        "https://ollama.com", "完全离线、免费；效果取决于本机显卡能跑多大的模型", needs_key=False, region="local",
    ),
    Provider(
        "custom", "自定义（OpenAI 兼容接口）", "openai", "", "OPENAI_COMPATIBLE_API_KEY",
        "", "", (), "", "vLLM、LM Studio、各类中转站等，填写接口地址与模型名", needs_key=False, region="any",
    ),
]}

DEFAULT_PROVIDER = "deepseek"


def get(key: str) -> Provider:
    return PROVIDERS.get(key) or PROVIDERS[DEFAULT_PROVIDER]
