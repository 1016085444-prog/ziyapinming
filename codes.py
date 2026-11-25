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
import threading
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


def _ejson(v):
    """把接口返回的 EJSON（{"$numberInt": "3"} 这类）还原成普通值。"""
    if isinstance(v, dict):
        if len(v) == 1:
            k, x = next(iter(v.items()))
            if k in ("$numberInt", "$numberLong"):
                return int(x)
            if k == "$numberDouble":
                return float(x)
            if k == "$oid":
                return x
        return {k: _ejson(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ejson(x) for x in v]
    return v


class TcbDocCodeStore:
    """云开发文档型数据库卡密仓储，走云开发 HTTP API。

    环境变量：
      TCB_ENV_ID      云开发环境 ID
      TCB_API_KEY     服务端 API Key（管理员权限，只放服务端）；
                      也可在云托管里打开「API Key 设置」，平台会注入为 CLOUDBASE_APIKEY
      TCB_COLLECTION  集合名（默认 ziya_codes）

    每张卡密一条记录，_id 就是卡密本身，天然不重复。
    """

    _FIELDS = ("code", "status", "birth_summary", "note", "created_at",
               "bound_at", "last_used_at", "use_count")

    def __init__(self, env_id: str, api_key: str, collection: str = "ziya_codes"):
        self.env_id = env_id
        self.api_key = api_key
        self.collection = re.sub(r"[^A-Za-z0-9_]", "", collection) or "ziya_codes"
        self.base = (
            f"https://{env_id}.api.tcloudbasegateway.com/v1/database/instances/"
            f"(default)/databases/(default)"
        )
        self.init_db()

    def _call(self, method: str, path: str, body=None, params=None, ok404=False):
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if ok404 and e.code == 404:
                return None
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"云开发数据库接口出错 {e.code}：{detail}") from None
        return _ejson(json.loads(raw)) if raw else {}

    def _docs(self) -> str:
        return f"/collections/{self.collection}/documents"

    def _get(self, code: str) -> Optional[Dict]:
        from urllib.parse import quote
        return self._call("GET", f"{self._docs()}/{quote(code, safe='')}", ok404=True)

    def _update(self, query: Dict, fields: Dict, inc: Optional[Dict] = None) -> int:
        data = {"$set": fields}
        if inc:
            data["$inc"] = inc
        res = self._call("PATCH", self._docs(), {"query": query, "data": data})
        return int(res.get("updated", 0) or res.get("matched", 0))

    def init_db(self) -> None:
        try:
            self._call("POST", "/collections", {"collectionName": self.collection})
        except RuntimeError as e:
            # 409 = 集合已存在，正常
            if " 409" not in str(e) and "ALREADY_EXIST" not in str(e):
                raise

    def generate(self, count: int = 10, prefix: str = "ZY", note: str = "") -> List[str]:
        if count < 1 or count > 2000:
            raise ValueError("单次生成数量须在 1 到 2000 之间")
        pfx = _CODE_CLEAN_RE.sub("", (prefix or "ZY").upper())[:4] or "ZY"
        now = _now_iso()
        clean_note = (note or "").strip()[:80]
        created: List[str] = []
        while len(created) < count:
            batch = []
            for _ in range(min(100, count - len(created))):
                c = f"{pfx}-" + "".join(secrets.choice(_ALPHABET) for _ in range(4)) \
                    + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))
                batch.append({
                    "_id": c, "code": c, "status": "unused", "birth_key": None,
                    "birth_summary": None, "note": clean_note, "created_at": now,
                    "bound_at": None, "last_used_at": None, "use_count": 0,
                })
            try:
                self._call("POST", self._docs(), {"data": batch})
            except RuntimeError as e:
                # 31^8 种组合撞号几乎不可能；真撞了整批换新码重来
                if "duplicate" in str(e).lower() or "E11000" in str(e):
                    continue
                raise
            created.extend(d["code"] for d in batch)
        return created

    def verify_and_bind(
        self, raw_code: str, birth_key: str, birth_summary: str
    ) -> Tuple[bool, str, str]:
        code = normalize_code(raw_code)
        if not code:
            return False, "missing", "请输入兑换密码后再排盘"
        now = _now_iso()

        row = self._get(code)
        if row is None:
            return False, "invalid", "兑换密码无效，请核对是否输错字符"
        if row.get("status") == "disabled":
            return False, "disabled", "该兑换密码已停用，请联系客服核实"

        if row.get("status") == "unused":
            # 带条件更新：只有仍是 unused 才绑定，两人同时抢一个码只会成一个
            n = self._update(
                {"_id": code, "status": "unused"},
                {"status": "bound", "birth_key": birth_key, "birth_summary": birth_summary,
                 "bound_at": now, "last_used_at": now, "use_count": 1},
            )
            if n == 1:
                return True, "bound_new", "密码已激活并绑定当前生辰"
            row = self._get(code) or {}  # 被别人抢先绑了，按已绑定处理

        if row.get("status") == "bound" and row.get("birth_key") == birth_key:
            self._update({"_id": code}, {"last_used_at": now}, inc={"use_count": 1})
            return True, "bound_same", "已验证，正在载入你的专属命盘"
        if row.get("status") == "disabled":
            return False, "disabled", "该兑换密码已停用，请联系客服核实"
        return (
            False,
            "mismatch",
            "此密码已绑定其他生辰，一个密码仅限排测一人（八字与紫微两套盘通用）",
        )

    def stats(self) -> Dict[str, int]:
        import json

        counts = {}
        for s in ("unused", "bound", "disabled"):
            res = self._call("GET", self._docs(), params={
                "query": json.dumps({"status": s}), "count": "true"})
            counts[s] = int(res.get("total", 0))
        counts["total"] = sum(counts.values())
        return counts

    def list_codes(
        self, status: Optional[str] = None, q: Optional[str] = None, limit: int = 200
    ) -> List[Dict]:
        import json

        limit = max(1, min(int(limit), 1000))
        query: Dict = {}
        if status in ("unused", "bound", "disabled"):
            query["status"] = status
        if q and q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            query["$or"] = [{"code": rx}, {"note": rx}, {"birth_summary": rx}]
        out: List[Dict] = []
        while len(out) < limit:
            page = min(100, limit - len(out))  # 接口单页有上限，分页取
            res = self._call("GET", self._docs(), params={
                "query": json.dumps(query, ensure_ascii=False),
                "order": json.dumps([{"field": "created_at", "direction": "desc"},
                                     {"field": "code", "direction": "asc"}]),
                "offset": len(out), "limit": page,
            })
            items = res.get("list") or []
            out.extend({k: d.get(k) for k in self._FIELDS} for d in items)
            if len(items) < page:
                break
        return out

    def set_disabled(self, raw_code: str, disabled: bool) -> bool:
        code = normalize_code(raw_code)
        row = self._get(code)
        if row is None:
            return False
        new_status = "disabled" if disabled else ("bound" if row.get("birth_key") else "unused")
        self._update({"_id": code}, {"status": new_status})
        return True

    def reset_code(self, raw_code: str) -> bool:
        code = normalize_code(raw_code)
        if self._get(code) is None:
            return False
        self._update({"_id": code}, {
            "status": "unused", "birth_key": None, "birth_summary": None,
            "bound_at": None, "last_used_at": None, "use_count": 0})
        return True

    def storage_info(self) -> Dict[str, str]:
        return {
            "backend": "tcb-doc",
            "persistent_hint": "cloud",
            "label": f"云开发文档型数据库（{self.env_id} / {self.collection}）",
            "warning": "",
        }


_CLAIM_LOCK = threading.Lock()


def claim_for_order(store, order_id: str) -> Tuple[str, bool]:
    """凭订单号领码：同一订单号永远拿到同一个码。返回 (码, 是否本次新发)。

    订单号记在码的备注里（「订单 XXX」），后台按备注就能对账。
    先查后发要整体加锁，否则同一订单号并发请求会领出多个码。
    云托管实例上限设为 1，进程内锁就够；以后放开多实例要换成数据库级的唯一约束。
    """
    note = f"订单 {order_id}"
    with _CLAIM_LOCK:
        for row in store.list_codes(q=order_id, limit=50):
            if (row.get("note") or "").strip().upper() == note.upper():
                return row["code"], False
        return store.generate(count=1, note=note)[0], True


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
    env_id = os.environ.get("TCB_ENV_ID", "").strip()
    # 云托管「API Key 设置」开关注入的变量名是 CLOUDBASE_APIKEY
    api_key = (os.environ.get("TCB_API_KEY") or os.environ.get("CLOUDBASE_APIKEY") or "").strip()
    if env_id and api_key:
        coll = os.environ.get("TCB_COLLECTION", "ziya_codes").strip()
        key = ("tcb", env_id, coll)
        if _DEFAULT_STORE is None or _DEFAULT_STORE_KEY != key:
            _DEFAULT_STORE = TcbDocCodeStore(env_id, api_key, coll)
            _DEFAULT_STORE_KEY = key
        return _DEFAULT_STORE

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
