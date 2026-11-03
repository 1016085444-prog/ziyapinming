"""SQLite 缓存：减少重复请求，也让数据源临时不可用时还有「最近一次」的数据可看。

两种读法：
  get(key, max_age)   新鲜度内才返回，正常路径用这个
  get_stale(key, ...) 过期也返回（附带年龄），所有数据源都失败时兜底，并明确告诉用户是旧数据

只缓存 JSON 可序列化的数据。行情数据量很小（三年日线约 60KB），不做淘汰之外的花样。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: str | Path | None):
        self._lock = threading.Lock()
        # path 为 None 时用内存库（测试用）
        target = ":memory:" if path is None else str(path)
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts REAL NOT NULL, value TEXT NOT NULL)"
        )
        self._db.commit()

    def get(self, key: str, max_age: float) -> Any | None:
        hit = self._read(key)
        if hit is None:
            return None
        ts, value = hit
        return value if time.time() - ts <= max_age else None

    def get_stale(self, key: str, max_age: float = 7 * 86400) -> tuple[Any, float] | None:
        """返回 (value, 已过去的秒数)，超过 max_age 的太旧数据不返回。"""
        hit = self._read(key)
        if hit is None:
            return None
        ts, value = hit
        age = time.time() - ts
        return (value, age) if age <= max_age else None

    def set(self, key: str, value: Any) -> None:
        blob = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache (key, ts, value) VALUES (?, ?, ?)", (key, time.time(), blob)
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM cache")
            self._db.commit()

    def prune(self, older_than: float = 30 * 86400) -> None:
        with self._lock:
            self._db.execute("DELETE FROM cache WHERE ts < ?", (time.time() - older_than,))
            self._db.commit()

    def _read(self, key: str) -> tuple[float, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT ts, value FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return row[0], json.loads(row[1])
        except ValueError:
            return None


def humanize_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} 分钟"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时"
    return f"{int(seconds // 86400)} 天"
