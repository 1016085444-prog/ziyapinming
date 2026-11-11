"""配置：环境变量 > data/settings.json（网页「设置」里保存的）> 默认值。

- 本机使用：直接在网页「设置」里填 API Key，存到 data/settings.json（不进 git）。
- 服务器部署：用环境变量（或 touyan/.env 文件）注入，网页上显示为「由环境变量提供」、不可修改。

每个服务商的 Key、模型、接口地址分开保存，切换服务商不会丢掉之前填的东西。
API Key 不会完整地发给浏览器：前端只拿到 sk-****abcd 这样的掩码。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, Field

from agents import providers
from agents.llm import LLMConfig

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取：KEY=VALUE，# 开头为注释；已存在的环境变量不覆盖。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("TOUYAN_DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = DATA_DIR / "touyan.db"
CACHE_PATH = DATA_DIR / "cache.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
ALLOW_REMOTE = os.environ.get("TOUYAN_ALLOW_REMOTE", "").lower() in ("1", "true", "yes", "on")
MAX_JOBS = int(os.environ.get("TOUYAN_MAX_JOBS", "2"))
VERSION = "1.1.0"
# 区分「同一份程序」和「另一份（旧版本、另一个文件夹）」：启动时端口被占用要靠它判断。
# 只给路径的摘要，不把本机路径暴露给别人。
INSTANCE_ID = hashlib.sha1(str(BASE_DIR).encode("utf-8")).hexdigest()[:10]

EFFORTS = ("low", "medium", "high", "xhigh", "max")


class Settings(BaseModel):
    provider: str = providers.DEFAULT_PROVIDER
    api_keys: dict[str, str] = Field(default_factory=dict)
    base_urls: dict[str, str] = Field(default_factory=dict)
    quick_models: dict[str, str] = Field(default_factory=dict)
    deep_models: dict[str, str] = Field(default_factory=dict)
    analysts: list[str] = Field(default_factory=lambda: ["market", "fundamentals", "news"])
    debate_rounds: int = Field(1, ge=1, le=3)
    risk_rounds: int = Field(1, ge=1, le=3)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=256, le=128000)
    claude_effort: str = "high"
    risk_free_rate: float = Field(2.0, ge=0, le=20)   # %
    timeout: int = Field(300, ge=30, le=1800)
    daily_auto: bool = True             # 交易日收盘后自动生成每日精选（软件开着时）
    daily_strategy: str = "balanced"
    daily_stock_count: int = Field(5, ge=3, le=10)
    daily_llm: bool = True              # 配置了大模型时，附一段大模型点评


_lock = threading.Lock()


def _read_file() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def env_locks(provider: str) -> dict[str, bool]:
    """哪些设置由环境变量提供（网页上只读）。"""
    p = providers.get(provider)
    return {
        "provider": bool(os.environ.get("TOUYAN_LLM_PROVIDER")),
        "api_key": bool(p.key_env and os.environ.get(p.key_env)),
        "base_url": bool(os.environ.get("TOUYAN_BASE_URL")),
        "quick_model": bool(os.environ.get("TOUYAN_QUICK_MODEL")),
        "deep_model": bool(os.environ.get("TOUYAN_DEEP_MODEL")),
    }


def load() -> Settings:
    with _lock:
        data = _read_file()
    try:
        s = Settings.model_validate(data)
    except ValueError:
        s = Settings()
    env = os.environ
    if env.get("TOUYAN_LLM_PROVIDER") in providers.PROVIDERS:
        s.provider = env["TOUYAN_LLM_PROVIDER"]
    p = s.provider
    if env.get("TOUYAN_QUICK_MODEL"):
        s.quick_models[p] = env["TOUYAN_QUICK_MODEL"]
    if env.get("TOUYAN_DEEP_MODEL"):
        s.deep_models[p] = env["TOUYAN_DEEP_MODEL"]
    if env.get("TOUYAN_BASE_URL"):
        s.base_urls[p] = env["TOUYAN_BASE_URL"]
    for key, attr, cast in (("TOUYAN_DEBATE_ROUNDS", "debate_rounds", int), ("TOUYAN_RISK_ROUNDS", "risk_rounds", int),
                            ("TOUYAN_RISK_FREE_RATE", "risk_free_rate", float), ("TOUYAN_MAX_TOKENS", "max_tokens", int),
                            ("TOUYAN_TEMPERATURE", "temperature", float), ("TOUYAN_CLAUDE_EFFORT", "claude_effort", str)):
        if env.get(key):
            try:
                setattr(s, attr, cast(env[key]))
            except ValueError:
                pass
    return s


def api_key(s: Settings, provider: str | None = None) -> str:
    p = providers.get(provider or s.provider)
    return (os.environ.get(p.key_env, "") if p.key_env else "") or s.api_keys.get(p.key, "")


def models(s: Settings, provider: str | None = None) -> tuple[str, str]:
    p = providers.get(provider or s.provider)
    return (s.quick_models.get(p.key) or p.quick), (s.deep_models.get(p.key) or p.deep)


def llm_configs(s: Settings) -> tuple[LLMConfig, LLMConfig]:
    p = providers.get(s.provider)
    quick, deep = models(s)
    common = dict(provider=p.key, api_key=api_key(s), base_url=s.base_urls.get(p.key, ""),
                  temperature=s.temperature, max_tokens=s.max_tokens, timeout=float(s.timeout))
    effort = s.claude_effort if s.claude_effort in EFFORTS else "high"
    return LLMConfig(model=quick, effort=effort, **common), LLMConfig(model=deep, effort=effort, **common)


def llm_ready(s: Settings) -> tuple[bool, str]:
    p = providers.get(s.provider)
    quick, deep = models(s)
    if p.needs_key and not api_key(s):
        return False, f"尚未设置 {p.label} 的 API Key"
    if not quick or not deep:
        return False, f"尚未设置 {p.label} 的模型名称"
    if p.key == "custom" and not s.base_urls.get("custom"):
        return False, "自定义接口尚未填写接口地址"
    return True, ""


def mask(key: str) -> str:
    if not key:
        return ""
    return key[:3] + "****" + key[-4:] if len(key) > 10 else "****"


def public(s: Settings) -> dict:
    """给前端的设置：Key 只给掩码。"""
    ready, reason = llm_ready(s)
    per_provider = {}
    for key, p in providers.PROVIDERS.items():
        quick, deep = models(s, key)
        per_provider[key] = {
            "api_key_masked": mask(api_key(s, key)),
            "has_key": bool(api_key(s, key)),
            "key_from_env": bool(p.key_env and os.environ.get(p.key_env)),
            "base_url": s.base_urls.get(key, ""),
            "quick_model": quick,
            "deep_model": deep,
        }
    return {
        "provider": s.provider,
        "per_provider": per_provider,
        "analysts": s.analysts,
        "debate_rounds": s.debate_rounds,
        "risk_rounds": s.risk_rounds,
        "temperature": s.temperature,
        "max_tokens": s.max_tokens,
        "claude_effort": s.claude_effort,
        "risk_free_rate": s.risk_free_rate,
        "timeout": s.timeout,
        "daily_auto": s.daily_auto,
        "daily_strategy": s.daily_strategy,
        "daily_stock_count": s.daily_stock_count,
        "daily_llm": s.daily_llm,
        "locks": env_locks(s.provider),
        "llm_ready": ready,
        "llm_reason": reason,
        "providers": [p.to_dict() for p in providers.PROVIDERS.values()],
    }


def save(patch: dict) -> Settings:
    """合并保存。api_key 传空串表示不修改，传 "__clear__" 表示清除。"""
    with _lock:
        data = _read_file()
        current = Settings.model_validate(data) if data else Settings()
        provider = patch.get("provider") or current.provider
        if provider not in providers.PROVIDERS:
            raise ValueError("未知的服务商")
        current.provider = provider
        if "api_key" in patch:
            value = (patch.get("api_key") or "").strip()
            if value == "__clear__":
                current.api_keys.pop(provider, None)
            elif value:
                current.api_keys[provider] = value
        for field, store in (("base_url", current.base_urls), ("quick_model", current.quick_models),
                             ("deep_model", current.deep_models)):
            if field in patch:
                value = (patch.get(field) or "").strip()
                if value:
                    store[provider] = value
                else:
                    store.pop(provider, None)
        for field in ("analysts", "debate_rounds", "risk_rounds", "temperature", "max_tokens",
                      "claude_effort", "risk_free_rate", "timeout",
                      "daily_auto", "daily_strategy", "daily_stock_count", "daily_llm"):
            if field in patch:
                setattr(current, field, patch[field])
        current = Settings.model_validate(current.model_dump())  # 重新校验取值范围
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(current.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(SETTINGS_PATH)
    return load()
