"""兑换码：一个码绑定一个生日。

售卖模式：用户在各平台下单 → 你在管理页生成兑换码 → 把专属链接发给买家
→ 买家第一次测算时，码与他填的公历生日（年月日）绑定 → 之后这个码只能
测这个生日。同一生日可以反复打开、改出生时刻与出生地；换一个生日就拒绝。

设计上的几个取舍：

* **码本身不入库。** 码 = 随机部分 + 密钥签名，服务器靠签名验真伪。生成
  多少个码都不需要写数据库，管理页离线也能批量出码；伪造一个有效码要猜
  中 30 位签名（约十亿分之一）。
* **只绑定「年月日」，不绑时刻、性别和出生地。** 买家最常犯的错是时辰
  填错、出生地选错，绑得太死就会把付了钱的人锁在门外。年月日填错的，
  你在管理页把这个码重置一下即可。
* **库里不存生日本身，只存不可逆摘要**（HMAC，需要密钥才能比对）。
  就算库被拖走，也拿不到任何人的生日——本站「生辰不留存」的承诺还在。
* **绑定是原子的。** 码是主键，「插入即绑定」，两台实例同时抢同一个码，
  只有一条能插进去，另一条读回已有绑定再比对。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from pathlib import Path

# 去掉了 0/O、1/I 这些手抄易混的字符，正好 32 个，每字符 5 位。
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
assert len(ALPHABET) == 32 and len(set(ALPHABET)) == 32

RAND_LEN = 6   # 30 位随机
SIG_LEN = 6    # 30 位签名


# --------------------------------------------------------------------------
# 码的生成与校验
# --------------------------------------------------------------------------

def _encode(n, length):
    out = []
    for _ in range(length):
        out.append(ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(out))


def _sig(secret, body):
    digest = hmac.new(secret.encode(), ("code:" + body).encode(), hashlib.sha256).digest()
    return _encode(int.from_bytes(digest[:8], "big"), SIG_LEN)


def normalize(code):
    """去掉分隔符与空格、转大写。买家手抄时常带空格或小写。"""
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def pretty(code):
    c = normalize(code)
    return "-".join(c[i:i + 4] for i in range(0, len(c), 4))


def make_code(secret):
    body = "".join(secrets.choice(ALPHABET) for _ in range(RAND_LEN))
    return pretty(body + _sig(secret, body))


def is_valid(secret, code):
    c = normalize(code)
    if len(c) != RAND_LEN + SIG_LEN or any(ch not in ALPHABET for ch in c):
        return False
    body, sig = c[:RAND_LEN], c[RAND_LEN:]
    return hmac.compare_digest(sig, _sig(secret, body))


def birth_digest(secret, code, year, month, day):
    """生日的不可逆摘要。混入码本身，同一生日在不同码下摘要也不同。"""
    msg = "birth:{}:{:04d}-{:02d}-{:02d}".format(normalize(code), year, month, day)
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------
# 存储
# --------------------------------------------------------------------------

class Store:
    """绑定表的最小接口。两种实现共用同一段 SQL，只有占位符不同。"""

    PH = "?"

    def _conn(self):
        raise NotImplementedError

    def _run(self, sql, args=(), fetch=False):
        raise NotImplementedError

    def init(self):
        self._run(
            "CREATE TABLE IF NOT EXISTS caifu_binding ("
            " code VARCHAR(16) PRIMARY KEY,"
            " birth_hash CHAR(64) NOT NULL,"
            " bound_at BIGINT NOT NULL,"
            " last_at BIGINT NOT NULL,"
            " uses INTEGER NOT NULL DEFAULT 1)")

    def get(self, code):
        rows = self._run(
            "SELECT birth_hash, bound_at, last_at, uses FROM caifu_binding "
            "WHERE code = {}".format(self.PH), (code,), fetch=True)
        if not rows:
            return None
        h, b, l_, u = rows[0]
        return {"birth_hash": h, "bound_at": int(b), "last_at": int(l_), "uses": int(u)}

    def try_bind(self, code, birth_hash):
        """插入绑定。码已被绑定则返回 False（由主键冲突保证原子性）。"""
        now = int(time.time())
        try:
            self._run(
                "INSERT INTO caifu_binding (code, birth_hash, bound_at, last_at, uses) "
                "VALUES ({0}, {0}, {0}, {0}, 1)".format(self.PH),
                (code, birth_hash, now, now))
            return True
        except self.IntegrityError:
            return False

    def touch(self, code):
        self._run(
            "UPDATE caifu_binding SET uses = uses + 1, last_at = {0} "
            "WHERE code = {0}".format(self.PH), (int(time.time()), code))

    def reset(self, code):
        self._run("DELETE FROM caifu_binding WHERE code = {}".format(self.PH), (code,))


class SQLiteStore(Store):
    """单文件数据库。本地开发、或部署在有持久磁盘的服务器上用。"""

    PH = "?"
    IntegrityError = sqlite3.IntegrityError

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.init()

    def _run(self, sql, args=(), fetch=False):
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=10)
            try:
                cur = conn.execute(sql, args)
                rows = cur.fetchall() if fetch else None
                conn.commit()
                return rows
            finally:
                conn.close()


class MySQLStore(Store):
    """MySQL。云托管这类容器会重启、会缩到零的平台用它——容器本地文件不持久。

    连接串形如 mysql://用户:密码@主机:端口/库名 。每次请求新开连接：
    测算是低频操作，省掉连接池换来的是不会出现「连接被服务端掐断」的问题。
    """

    PH = "%s"

    def __init__(self, url):
        import pymysql
        from urllib.parse import unquote, urlparse

        self._pymysql = pymysql
        self.IntegrityError = pymysql.err.IntegrityError
        u = urlparse(url)
        self._args = dict(
            host=u.hostname, port=u.port or 3306,
            user=unquote(u.username or ""), password=unquote(u.password or ""),
            database=(u.path or "/").lstrip("/"), charset="utf8mb4",
            connect_timeout=5, autocommit=True,
        )
        self.init()

    def _run(self, sql, args=(), fetch=False):
        conn = self._pymysql.connect(**self._args)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall() if fetch else None
        finally:
            conn.close()


def open_store(mysql_url, sqlite_path):
    if mysql_url:
        return MySQLStore(mysql_url)
    return SQLiteStore(sqlite_path)


# --------------------------------------------------------------------------
# 业务
# --------------------------------------------------------------------------

class CodeError(Exception):
    """给用户看的错误。message 直接显示在页面上。"""

    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def redeem(store, secret, code, year, month, day):
    """校验兑换码并绑定生日。通过则返回 True，否则抛 CodeError。"""
    c = normalize(code)
    if not c:
        raise CodeError("请输入兑换码。购买后店铺会发给你")
    if not is_valid(secret, c):
        raise CodeError("兑换码无效，请核对后重新输入（不区分大小写）")

    digest = birth_digest(secret, c, year, month, day)
    if store.try_bind(c, digest):
        return "bound"

    row = store.get(c)
    if row is None:          # 极少见：刚被管理员重置。再试一次即可
        if store.try_bind(c, digest):
            return "bound"
        row = store.get(c)
    if row and hmac.compare_digest(row["birth_hash"], digest):
        store.touch(c)
        return "again"
    raise CodeError(
        "这个兑换码已经绑定了另一个生日。一个码只能测一个生日——"
        "为家人朋友测算需另购兑换码；若是自己填错了日期，请联系店铺重置")
