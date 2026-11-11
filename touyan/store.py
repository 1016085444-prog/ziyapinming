"""历史记录：每次 AI 深度分析的完整结果，以及之后的实际表现（复盘）。

学自 TradingAgents 的 memory log：一次分析给出一个判断，但单次判断说明不了系统好不好。
把判断存下来、事后对照实际走势，才知道它在哪些情况下靠谱——这也是投资经理下次
分析同一标的时会读到的「历史决策复盘」。

复盘口径：入场价取分析当天（数据日期）的收盘，出场取最新收盘，都在同一条复权价序列里取，
这样中间发生的分红、拆股不会让收益算错。同期基准收益相减得到超额收益。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date
from pathlib import Path

from market.models import Bar
from quant.metrics import bar_on_or_before

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    inst_key TEXT NOT NULL,
    code TEXT NOT NULL,
    market TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT,
    as_of TEXT NOT NULL,
    price REAL,
    rating TEXT,
    rating_label TEXT,
    quant_score REAL,
    quant_rating TEXT,
    models TEXT,
    result_json TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_inst ON analyses(inst_key, created_at);
CREATE TABLE IF NOT EXISTS daily_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    as_of TEXT NOT NULL,
    strategy TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_asof ON daily_runs(as_of, strategy);
"""

_LIST_COLS = ("id", "created_at", "inst_key", "code", "market", "kind", "name", "as_of", "price",
              "rating", "rating_label", "quant_score", "quant_rating", "models")


class Store:
    def __init__(self, path: str | Path | None):
        self._lock = threading.Lock()
        target = ":memory:" if path is None else str(path)
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def save(self, result: dict, report: dict) -> str:
        inst = result["instrument"]
        rid = uuid.uuid4().hex[:12]
        slim = {k: v for k, v in report.items() if k != "chart"}   # 图表序列很大，复盘用不到
        with self._lock:
            self._db.execute(
                "INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, result["finished_at"], inst["key"], inst["code"], inst["market"], inst["kind"], inst.get("name", ""),
                 result["as_of"], result.get("price"), result["final"]["rating"], result["final"]["label"],
                 report["scores"]["composite"], report["scores"]["rating"]["label"],
                 f"{result['models']['quick']} / {result['models']['deep']}",
                 json.dumps(result, ensure_ascii=False), json.dumps(slim, ensure_ascii=False)),
            )
            self._db.commit()
        return rid

    def list(self, limit: int = 100, inst_key: str | None = None) -> list[dict]:
        cols = ", ".join(_LIST_COLS)
        with self._lock:
            if inst_key:
                rows = self._db.execute(f"SELECT {cols} FROM analyses WHERE inst_key = ? ORDER BY created_at DESC LIMIT ?",
                                        (inst_key, limit)).fetchall()
            else:
                rows = self._db.execute(f"SELECT {cols} FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, rid: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM analyses WHERE id = ?", (rid,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        d["report"] = json.loads(d.pop("report_json"))
        return d

    def delete(self, rid: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM analyses WHERE id = ?", (rid,))
            self._db.commit()
        return cur.rowcount > 0

    # ── 每日精选 ──────────────────────────────────────────────────

    def save_daily(self, payload: dict) -> str:
        """同一交易日、同一选股风格只留最新一次。"""
        rid = uuid.uuid4().hex[:12]
        payload = {**payload, "id": rid}
        strategy = payload["strategy"]["key"]
        summary = {
            "strategy_label": payload["strategy"]["label"],
            "regime": payload["market"]["regime"]["label"],
            "stocks": [{"key": p["key"], "name": p["name"], "score": p["score"], "signal": p["dashboard"]["signal"]}
                       for p in payload["stocks"]["picks"]],
            "etfs": [{"key": p["key"], "name": p["name"]} for p in payload["etfs"]["picks"]],
            "funds": [{"key": p["key"], "name": p["name"]} for g in payload["funds"]["groups"] for p in g["picks"]],
        }
        with self._lock:
            self._db.execute("DELETE FROM daily_runs WHERE as_of = ? AND strategy = ?", (payload["as_of"], strategy))
            self._db.execute("INSERT INTO daily_runs VALUES (?,?,?,?,?,?)",
                             (rid, payload["created_at"], payload["as_of"], strategy,
                              json.dumps(summary, ensure_ascii=False), json.dumps(payload, ensure_ascii=False)))
            self._db.commit()
        return rid

    def list_daily(self, limit: int = 60) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, created_at, as_of, strategy, summary_json FROM daily_runs "
                                    "ORDER BY as_of DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.update(json.loads(d.pop("summary_json")))
            out.append(d)
        return out

    def get_daily(self, rid: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT payload_json FROM daily_runs WHERE id = ?", (rid,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_daily(self, strategy: str | None = None) -> dict | None:
        sql = "SELECT payload_json FROM daily_runs"
        args: tuple = ()
        if strategy:
            sql += " WHERE strategy = ?"
            args = (strategy,)
        with self._lock:
            row = self._db.execute(sql + " ORDER BY as_of DESC, created_at DESC LIMIT 1", args).fetchone()
        return json.loads(row[0]) if row else None

    def daily_exists(self, as_of: str, strategy: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM daily_runs WHERE as_of = ? AND strategy = ?",
                                   (as_of, strategy)).fetchone()
        return row is not None

    def delete_daily(self, rid: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM daily_runs WHERE id = ?", (rid,))
            self._db.commit()
        return cur.rowcount > 0


def outcome(as_of: str, bars: list[Bar], bench: list[Bar] | None = None) -> dict:
    """从 as_of 当天收盘持有到最新收盘的收益、同期基准收益与超额收益。"""
    if not bars:
        return {"return": None}
    entry = bar_on_or_before(bars, date.fromisoformat(as_of[:10]))
    last = bars[-1]
    if entry is None or last.date <= entry.date:
        return {"return": None, "note": "分析之后还没有新的行情"}
    days = sum(1 for b in bars if entry.date < b.date <= last.date)
    ret = last.adj_close / entry.adj_close - 1
    out = {"return": ret, "price": last.close, "date": last.date, "days": days, "entry_date": entry.date}
    if bench:
        b0 = bar_on_or_before(bench, date.fromisoformat(entry.date))
        b1 = bar_on_or_before(bench, date.fromisoformat(last.date))
        if b0 is not None and b1 is not None and b1.date > b0.date:
            out["benchmark_return"] = b1.adj_close / b0.adj_close - 1
            out["excess"] = ret - out["benchmark_return"]
    return out


def direction_hit(rating: str, ret: float | None) -> bool | None:
    """评级方向与实际涨跌是否一致。持有/待复核不计。"""
    if ret is None:
        return None
    if rating in ("Buy", "Overweight"):
        return ret > 0
    if rating in ("Sell", "Underweight"):
        return ret < 0
    return None
