"""一次性兑换密码（卡密）核销系统 —— 一密绑一人，八字与紫微互通。

设计原则：
1. 纯 Python 标准库（sqlite3 + secrets），零外部依赖，腾讯云单机落盘即持久化。
2. 语义是「一密绑一生辰」而非「一次 HTTP 请求即烧毁」：
   - 首次使用时原子锁定并绑定该生辰指纹；
   - 同一密码 + 同一生辰，可无缝切换八字页与紫微页，也可刷新或日后回来重看；
   - 同一密码 + 不同生辰，一律拒绝（403），防止一人买码全家/转卖滥用。
3. 输入宽容：自动忽略大小写、空格与横杠差异，避免买家手打出错引发客诉。
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config

# 剔除易混淆字符 0/O/1/I/L
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_CLEAN_RE = re.compile(r"[^A-Z0-9]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def normalize_code(raw: str) -> str:
    """把用户输入规整为标准格式（如 ZY-XXXX-XXXX）。

    兼容大小写、首尾空格、少打横杠等情况。
    """
    cleaned = _CODE_CLEAN_RE.sub("", (raw or "").upper())
    if not cleaned:
        return ""
    if len(cleaned) == 10 and cleaned.startswith("ZY"):
        return f"{cleaned[:2]}-{cleaned[2:6]}-{cleaned[6:10]}"
    if len(cleaned) == 8:
        return f"ZY-{cleaned[:4]}-{cleaned[4:8]}"
    # 自定义前缀格式（如 2位前缀 + 8位主体）
    if len(cleaned) == 10:
        return f"{cleaned[:2]}-{cleaned[2:6]}-{cleaned[6:10]}"
    return cleaned


def birth_fingerprint(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    gender: str,
    longitude: float,
    tz_offset: float,
    use_true_solar_time: bool,
    late_zi_shifts_day: bool,
    adjust_china_dst: bool,
) -> Tuple[str, str]:
    """生成同一生辰的稳定指纹（八字与紫微共用，确保双盘互通）。

    经度保留 2 位小数、时区保留 2 位小数，避免浮点微差误判为不同人。
    """
    key = (
        f"{year:04d}-{month:02d}-{day:02d}|{hour:02d}:{minute:02d}|{gender}|"
        f"{round(float(longitude), 2):.2f}|{round(float(tz_offset), 2):.2f}|"
        f"{int(bool(use_true_solar_time))}|{int(bool(late_zi_shifts_day))}|"
        f"{int(bool(adjust_china_dst))}"
    )
    g_cn = "女" if gender == "female" else "男"
    summary = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d} {g_cn}"
    return key, summary


class CodeStore:
    """SQLite 卡密仓储。每次操作独立连接 + WAL 模式，适配 uvicorn 并发。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or config.CODES_DB_PATH)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS codes (
                    code          TEXT PRIMARY KEY,
                    status        TEXT NOT NULL DEFAULT 'unused',
                    birth_key     TEXT,
                    birth_summary TEXT,
                    note          TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL,
                    bound_at      TEXT,
                    last_used_at  TEXT,
                    use_count     INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_codes_status ON codes(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_codes_created ON codes(created_at DESC)"
            )

    def generate(self, count: int = 10, prefix: str = "ZY", note: str = "") -> List[str]:
        """批量生成不重复的防输错卡密。"""
        if count < 1 or count > 2000:
            raise ValueError("单次生成数量须在 1 到 2000 之间")
        pfx = _CODE_CLEAN_RE.sub("", (prefix or "ZY").upper())[:4] or "ZY"
        now = _now_iso()
        created: List[str] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                while len(created) < count:
                    part1 = "".join(secrets.choice(_ALPHABET) for _ in range(4))
                    part2 = "".join(secrets.choice(_ALPHABET) for _ in range(4))
                    code = f"{pfx}-{part1}-{part2}"
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO codes (code, status, note, created_at) "
                        "VALUES (?, 'unused', ?, ?)",
                        (code, (note or "").strip()[:80], now),
                    )
                    if cur.rowcount == 1:
                        created.append(code)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return created

    def verify_and_bind(
        self, raw_code: str, birth_key: str, birth_summary: str
    ) -> Tuple[bool, str, str]:
        """校验并原子绑定密码。

        返回 (ok, state_tag, message)。
        state_tag: 'bound_new' | 'bound_same' | 'missing' | 'invalid' | 'disabled' | 'mismatch'
        """
        code = normalize_code(raw_code)
        if not code:
            return False, "missing", "请输入兑换密码后再排盘"

        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT code, status, birth_key, birth_summary, use_count "
                    "FROM codes WHERE code = ?",
                    (code,),
                ).fetchone()

                if row is None:
                    conn.execute("ROLLBACK")
                    return False, "invalid", "兑换密码无效，请核对是否输错字符"

                status = row["status"]
                if status == "disabled":
                    conn.execute("ROLLBACK")
                    return False, "disabled", "该兑换密码已停用，请联系客服核实"

                if status == "unused":
                    conn.execute(
                        "UPDATE codes SET status='bound', birth_key=?, birth_summary=?, "
                        "bound_at=?, last_used_at=?, use_count=1 "
                        "WHERE code=? AND status='unused'",
                        (birth_key, birth_summary, now, now, code),
                    )
                    conn.execute("COMMIT")
                    return True, "bound_new", "密码已激活并绑定当前生辰"

                # status == 'bound'
                if row["birth_key"] == birth_key:
                    conn.execute(
                        "UPDATE codes SET last_used_at=?, use_count=use_count+1 "
                        "WHERE code=?",
                        (now, code),
                    )
                    conn.execute("COMMIT")
                    return True, "bound_same", "已验证，正在载入你的专属命盘"

                conn.execute("ROLLBACK")
                return (
                    False,
                    "mismatch",
                    "此密码已绑定其他生辰，一个密码仅限排测一人（八字与紫微两套盘通用）",
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM codes GROUP BY status"
            ).fetchall()
        counts = {"unused": 0, "bound": 0, "disabled": 0}
        for r in rows:
            counts[r["status"]] = r["n"]
        counts["total"] = sum(counts.values())
        return counts

    def list_codes(
        self, status: Optional[str] = None, q: Optional[str] = None, limit: int = 200
    ) -> List[Dict]:
        limit = max(1, min(int(limit), 1000))
        clauses = []
        params: List = []
        if status in ("unused", "bound", "disabled"):
            clauses.append("status = ?")
            params.append(status)
        if q:
            like = f"%{q.strip().upper()}%"
            clauses.append("(UPPER(code) LIKE ? OR UPPER(note) LIKE ? OR birth_summary LIKE ?)")
            params.extend([like, like, f"%{q.strip()}%"])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT code, status, birth_summary, note, created_at, bound_at, last_used_at, use_count "
            f"FROM codes {where} ORDER BY created_at DESC, code ASC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_disabled(self, raw_code: str, disabled: bool) -> bool:
        code = normalize_code(raw_code)
        with self._connect() as conn:
            row = conn.execute("SELECT status, birth_key FROM codes WHERE code=?", (code,)).fetchone()
            if row is None:
                return False
            new_status = "disabled" if disabled else ("bound" if row["birth_key"] else "unused")
            conn.execute("UPDATE codes SET status=? WHERE code=?", (new_status, code))
            return True

    def reset_code(self, raw_code: str) -> bool:
        """客服救急：解除误填生辰的绑定，恢复为未使用。"""
        code = normalize_code(raw_code)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE codes SET status='unused', birth_key=NULL, birth_summary=NULL, "
                "bound_at=NULL, last_used_at=NULL, use_count=0 WHERE code=?",
                (code,),
            )
            return cur.rowcount == 1

    def storage_info(self) -> Dict[str, str]:
        return {
            "backend": "sqlite",
            "persistent_hint": "local",
            "label": f"本地 SQLite（{self.db_path}）",
            "warning": "若部署在腾讯云云托管且未挂载持久盘，容器缩容重启会清空本地文件；建议在云托管关联 MySQL 并配置 MYSQL_ADDRESS / MYSQL_USERNAME / MYSQL_PASSWORD。",
        }


class MySQLCodeStore:
    """腾讯云云托管 MySQL 卡密仓储（容器缩容/重建不丢密码）。

    环境变量兼容微信/腾讯云云托管标准命名：
      MYSQL_ADDRESS   例 10.x.x.x:3306（也可分别填 MYSQL_HOST + MYSQL_PORT）
      MYSQL_USERNAME  用户名
      MYSQL_PASSWORD  密码
      MYSQL_DATABASE  库名（默认 ziyapinming）
    """

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.init_db()

    def _connect(self, use_db: bool = True):
        import pymysql
        import pymysql.cursors

        kwargs = dict(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=8,
            read_timeout=15,
            write_timeout=15,
            cursorclass=pymysql.cursors.DictCursor,
        )
        if use_db:
            kwargs["database"] = self.database
        return pymysql.connect(**kwargs)

    def init_db(self) -> None:
        safe_db = re.sub(r"[^A-Za-z0-9_]", "", self.database) or "ziyapinming"
        self.database = safe_db
        conn0 = self._connect(use_db=False)
        try:
            with conn0.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{safe_db}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn0.commit()
        finally:
            conn0.close()

        conn = self._connect(use_db=True)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS codes (
                        code          VARCHAR(32) PRIMARY KEY,
                        status        VARCHAR(16) NOT NULL DEFAULT 'unused',
                        birth_key     VARCHAR(160) NULL,
                        birth_summary VARCHAR(120) NULL,
                        note          VARCHAR(120) NOT NULL DEFAULT '',
                        created_at    VARCHAR(32) NOT NULL,
                        bound_at      VARCHAR(32) NULL,
                        last_used_at  VARCHAR(32) NULL,
                        use_count     INT NOT NULL DEFAULT 0,
                        INDEX idx_codes_status (status),
                        INDEX idx_codes_created (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def generate(self, count: int = 10, prefix: str = "ZY", note: str = "") -> List[str]:
        if count < 1 or count > 2000:
            raise ValueError("单次生成数量须在 1 到 2000 之间")
        pfx = _CODE_CLEAN_RE.sub("", (prefix or "ZY").upper())[:4] or "ZY"
        now = _now_iso()
        clean_note = (note or "").strip()[:80]
        created: List[str] = []
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                while len(created) < count:
                    part1 = "".join(secrets.choice(_ALPHABET) for _ in range(4))
                    part2 = "".join(secrets.choice(_ALPHABET) for _ in range(4))
                    code = f"{pfx}-{part1}-{part2}"
                    n = cur.execute(
                        "INSERT IGNORE INTO codes (code, status, note, created_at) "
                        "VALUES (%s, 'unused', %s, %s)",
                        (code, clean_note, now),
                    )
                    if n == 1:
                        created.append(code)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return created

    def verify_and_bind(
        self, raw_code: str, birth_key: str, birth_summary: str
    ) -> Tuple[bool, str, str]:
        code = normalize_code(raw_code)
        if not code:
            return False, "missing", "请输入兑换密码后再排盘"

        now = _now_iso()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, status, birth_key, birth_summary, use_count "
                    "FROM codes WHERE code = %s FOR UPDATE",
                    (code,),
                )
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return False, "invalid", "兑换密码无效，请核对是否输错字符"

                status = row["status"]
                if status == "disabled":
                    conn.rollback()
                    return False, "disabled", "该兑换密码已停用，请联系客服核实"

                if status == "unused":
                    cur.execute(
                        "UPDATE codes SET status='bound', birth_key=%s, birth_summary=%s, "
                        "bound_at=%s, last_used_at=%s, use_count=1 "
                        "WHERE code=%s AND status='unused'",
                        (birth_key, birth_summary, now, now, code),
                    )
                    conn.commit()
                    return True, "bound_new", "密码已激活并绑定当前生辰"

                if row["birth_key"] == birth_key:
                    cur.execute(
                        "UPDATE codes SET last_used_at=%s, use_count=use_count+1 "
                        "WHERE code=%s",
                        (now, code),
                    )
                    conn.commit()
                    return True, "bound_same", "已验证，正在载入你的专属命盘"

                conn.rollback()
                return (
                    False,
                    "mismatch",
                    "此密码已绑定其他生辰，一个密码仅限排测一人（八字与紫微两套盘通用）",
                )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def stats(self) -> Dict[str, int]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, COUNT(*) AS n FROM codes GROUP BY status")
                rows = cur.fetchall()
        finally:
            conn.close()
        counts = {"unused": 0, "bound": 0, "disabled": 0}
        for r in rows:
            counts[r["status"]] = int(r["n"])
        counts["total"] = sum(counts.values())
        return counts

    def list_codes(
        self, status: Optional[str] = None, q: Optional[str] = None, limit: int = 200
    ) -> List[Dict]:
        limit = max(1, min(int(limit), 1000))
        clauses = []
        params: List = []
        if status in ("unused", "bound", "disabled"):
            clauses.append("status = %s")
            params.append(status)
        if q:
            like = f"%{q.strip().upper()}%"
            clauses.append("(UPPER(code) LIKE %s OR UPPER(note) LIKE %s OR birth_summary LIKE %s)")
            params.extend([like, like, f"%{q.strip()}%"])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT code, status, birth_summary, note, created_at, bound_at, last_used_at, use_count "
            f"FROM codes {where} ORDER BY created_at DESC, code ASC LIMIT %s"
        )
        params.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        finally:
            conn.close()

    def set_disabled(self, raw_code: str, disabled: bool) -> bool:
        code = normalize_code(raw_code)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, birth_key FROM codes WHERE code=%s FOR UPDATE", (code,))
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return False
                new_status = "disabled" if disabled else ("bound" if row["birth_key"] else "unused")
                cur.execute("UPDATE codes SET status=%s WHERE code=%s", (new_status, code))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reset_code(self, raw_code: str) -> bool:
        code = normalize_code(raw_code)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                n = cur.execute(
                    "UPDATE codes SET status='unused', birth_key=NULL, birth_summary=NULL, "
                    "bound_at=NULL, last_used_at=NULL, use_count=0 WHERE code=%s",
                    (code,),
                )
            conn.commit()
            return n == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def storage_info(self) -> Dict[str, str]:
        return {
            "backend": "mysql",
            "persistent_hint": "cloud",
            "label": f"云端 MySQL（{self.host}:{self.port} / {self.database}）",
            "warning": "",
        }


def _mysql_env() -> Optional[Tuple[str, int, str, str, str]]:
    addr = os.environ.get("MYSQL_ADDRESS", "").strip()
    host = os.environ.get("MYSQL_HOST", "").strip()
    if addr:
        if ":" in addr:
            h, p = addr.rsplit(":", 1)
            host, port = h.strip(), int(p.strip())
        else:
            host, port = addr, int(os.environ.get("MYSQL_PORT", "3306"))
    elif host:
        port = int(os.environ.get("MYSQL_PORT", "3306"))
    else:
        return None
    user = os.environ.get("MYSQL_USERNAME", "").strip() or os.environ.get("MYSQL_USER", "").strip()
    password = os.environ.get("MYSQL_PASSWORD", "")
    database = os.environ.get("MYSQL_DATABASE", "ziyapinming").strip() or "ziyapinming"
    return host, port, user, password, database


_DEFAULT_STORE = None
_DEFAULT_STORE_KEY = None


def get_store():
    global _DEFAULT_STORE, _DEFAULT_STORE_KEY
    my = _mysql_env()
    if my is not None:
        key = ("mysql", my[0], my[1], my[2], my[4])
        if _DEFAULT_STORE is None or _DEFAULT_STORE_KEY != key:
            _DEFAULT_STORE = MySQLCodeStore(*my)
            _DEFAULT_STORE_KEY = key
        return _DEFAULT_STORE

    key = ("sqlite", str(config.CODES_DB_PATH))
    if _DEFAULT_STORE is None or _DEFAULT_STORE_KEY != key:
        _DEFAULT_STORE = CodeStore(config.CODES_DB_PATH)
        _DEFAULT_STORE_KEY = key
    return _DEFAULT_STORE
