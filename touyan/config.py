"""配置：环境变量 > settings.json（网页「设置」里保存的）> 默认值。

- 本机使用：直接在网页「设置」里填 API Key，存到数据目录里的 settings.json。
- 服务器部署：用环境变量（或 touyan/.env 文件）注入，网页上显示为「由环境变量提供」、不可修改。

数据目录（设置、历史记录、行情缓存）默认是个人文件夹下的 .touyan，不在程序文件夹里。
以前放在程序文件夹的 data/ 里，换一个新版本的文件夹、或者把文件夹整个替换掉，API Key 就跟着丢；
放进 iCloud / OneDrive 同步的目录还可能读不出来。现在程序放哪、怎么换版本，设置都在同一个地方。
老版本留在 data/ 里的数据，第一次启动时自动搬过去。环境变量 TOUYAN_DATA_DIR 可以另指位置（Docker 用 /data）。

每个服务商的 Key、模型、接口地址分开保存，切换服务商不会丢掉之前填的东西。
API Key 不会完整地发给浏览器：前端只拿到 sk-****abcd 这样的掩码。
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sqlite3
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

# ── 数据目录 ──────────────────────────────────────────────────────

LEGACY_DATA_DIR = BASE_DIR / "data"          # 1.1 及以前：数据放在程序文件夹里


def default_data_dir() -> Path:
    try:
        return Path.home() / ".touyan"
    except RuntimeError:                      # 极少数环境确定不了个人文件夹
        return LEGACY_DATA_DIR


def _has_keys(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and any((data.get("api_keys") or {}).values())


def _db_has_rows(path: Path) -> bool:
    """历史库里有没有记录。打不开的当作「有」，宁可不动它。"""
    if not path.is_file():
        return False
    try:
        con = sqlite3.connect(str(path))
        try:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return any(con.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone() for t in tables)
        finally:
            con.close()
    except sqlite3.Error:
        return True


def _move(src: Path, dst: Path) -> None:
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:          # 只有跨磁盘才改用复制；文件被占用等情况留到下次启动再搬
            raise
        shutil.copy2(src, dst)
        src.unlink()


def migrate_legacy(legacy: Path, target: Path) -> list[str]:
    """把老版本放在程序文件夹里的数据搬到新位置，返回搬过去的文件名。

    新位置已有内容的文件绝不覆盖；只有它是空的（设置里没有 Key、历史库里没有记录）而旧的有内容时才替换。
    单个文件搬不动（比如 Windows 上旧程序还开着）就跳过，下次启动再试。
    """
    moved: list[str] = []
    if not legacy.is_dir() or legacy.resolve() == target.resolve():
        return moved
    rules = (
        ("settings.json", lambda dst, src: not dst.exists() or (not _has_keys(dst) and _has_keys(src))),
        ("touyan.db", lambda dst, src: not dst.exists() or (not _db_has_rows(dst) and _db_has_rows(src))),
        ("cache.db", lambda dst, src: not dst.exists()),
    )
    for name, wanted in rules:
        src, dst = legacy / name, target / name
        if not src.is_file():
            continue
        try:
            if wanted(dst, src):
                _move(src, dst)
                for suffix in ("-journal", "-wal", "-shm"):     # SQLite 的伴随文件跟着走
                    side = legacy / (name + suffix)
                    if side.is_file():
                        _move(side, target / (name + suffix))
                moved.append(name)
            elif name == "cache.db":
                src.unlink()                                     # 行情缓存随时可以重建，不留两份
        except OSError:
            continue
    try:
        legacy.rmdir()                                           # 搬空了才删得掉
    except OSError:
        pass
    return moved


def _resolve_data_dir() -> tuple[Path, list[str]]:
    if os.environ.get("TOUYAN_DATA_DIR"):
        return Path(os.environ["TOUYAN_DATA_DIR"]), []
    target = default_data_dir()
    if target == LEGACY_DATA_DIR:
        return target, []
    try:
        created = not target.exists()
        target.mkdir(parents=True, exist_ok=True)
        if created:
            os.chmod(target, 0o700)
        if not os.access(target, os.W_OK):
            raise OSError("not writable")
    except OSError:
        return LEGACY_DATA_DIR, []                               # 个人文件夹写不了：退回老位置，至少能用
    return target, migrate_legacy(LEGACY_DATA_DIR, target)


DATA_DIR, MIGRATED = _resolve_data_dir()                         # MIGRATED：这次启动从老位置搬过来的文件
DB_PATH = DATA_DIR / "touyan.db"
CACHE_PATH = DATA_DIR / "cache.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
ALLOW_REMOTE = os.environ.get("TOUYAN_ALLOW_REMOTE", "").lower() in ("1", "true", "yes", "on")
MAX_JOBS = int(os.environ.get("TOUYAN_MAX_JOBS", "2"))
VERSION = "1.2.0"
CODE_DIRS = ("agents", "daily", "market", "quant")


def code_stamp(base: Path = BASE_DIR) -> str:
    """程序文件最新的修改时间。在原文件夹里覆盖更新后它会变。"""
    files = list(base.glob("*.py")) + [f for d in CODE_DIRS for f in (base / d).rglob("*.py")]
    try:
        return str(max((f.stat().st_mtime_ns for f in files), default=0))
    except OSError:
        return "0"


# 区分「同一份程序」和「另一份」：启动时端口被占用要靠它判断。另一个文件夹里的、旧版本的、
# 以及同一个文件夹里覆盖更新之前就启动、现在还开着的旧程序，都算另一份。
# 只给摘要，不把本机路径暴露给别人。
INSTANCE_ID = hashlib.sha1(f"{BASE_DIR}|{VERSION}|{code_stamp()}".encode("utf-8")).hexdigest()[:10]

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


def _read_file() -> tuple[dict, str]:
    """返回 (内容, 问题)。问题为空表示正常（或文件还不存在）；"io" 暂时读不出来；"corrupt" 内容坏了。"""
    try:
        raw = SETTINGS_PATH.read_bytes()
    except FileNotFoundError:
        return {}, ""
    except OSError:
        return {}, "io"
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}, "corrupt"
    return (data, "") if isinstance(data, dict) else ({}, "corrupt")


def _parse(data: dict) -> Settings:
    """个别字段不合法（手改过文件、或是别的版本写的）时只丢掉那几项，不连 API Key 一起丢。"""
    try:
        return Settings.model_validate(data)
    except ValueError:
        good = {}
        for key, value in data.items():
            if key not in Settings.model_fields:
                continue
            try:
                Settings.model_validate({key: value})
            except ValueError:
                continue
            good[key] = value
        return Settings.model_validate(good)


PROBLEMS = {
    "io": "设置文件暂时读不出来，现在显示的是默认设置。文件没有被改动，稍后刷新再看；这期间不要重新保存。",
    "corrupt": "设置文件的内容损坏了，现在显示的是默认设置。重新保存时会把损坏的文件另存为 settings.json.broken。",
}


def settings_problem() -> str:
    with _lock:
        return PROBLEMS.get(_read_file()[1], "")


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
        data, _ = _read_file()
    s = _parse(data)
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
        "problem": settings_problem(),
        "llm_ready": ready,
        "llm_reason": reason,
        "providers": [p.to_dict() for p in providers.PROVIDERS.values()],
    }


def save(patch: dict) -> Settings:
    """合并保存。api_key 传空串表示不修改，传 "__clear__" 表示清除。"""
    with _lock:
        data, problem = _read_file()
        if problem == "io":
            # 读不出来不等于没有：照常保存会用默认值盖掉已有的 Key
            raise ValueError("设置文件暂时读不出来。为了不覆盖已有的设置，这次没有保存，请稍后再试")
        if problem == "corrupt":
            try:
                SETTINGS_PATH.replace(SETTINGS_PATH.with_name("settings.json.broken"))   # 留原件备查
            except OSError:
                pass
        current = _parse(data)
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
