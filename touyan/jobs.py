"""深度分析任务：在后台线程里跑，事件存在内存里。

任务与浏览器连接解耦：刷新页面、网络断开都不会中断分析，重新连上后从头回放事件
（逐字输出会被合并，回放很快）。任务结束后结果存入历史记录，内存里的事件保留一段时间后清理。
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from typing import Callable

logger = logging.getLogger("touyan.jobs")

KEEP_SECONDS = 2 * 3600


class Job:
    def __init__(self, title: str, inst_key: str):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.inst_key = inst_key
        self.created = time.time()
        self.finished: float | None = None
        self.status = "running"         # running / done / error / cancelled
        self.result_id: str | None = None
        self.error = ""
        self.events: list[dict] = []
        self.cancel = threading.Event()
        self._cond = threading.Condition()

    def emit(self, event: dict) -> None:
        with self._cond:
            event["seq"] = len(self.events)
            self.events.append(event)
            self._cond.notify_all()

    def finish(self, status: str) -> None:
        with self._cond:
            self.status = status
            self.finished = time.time()
            self._cond.notify_all()

    def wait(self, after: int, timeout: float = 15.0) -> tuple[list[dict], bool]:
        """返回 seq ≥ after 的事件，以及任务是否已结束。没有新事件时最多等 timeout 秒。"""
        with self._cond:
            if len(self.events) <= after and self.status == "running":
                self._cond.wait(timeout)
            return self.events[after:], self.status != "running"

    def info(self) -> dict:
        return {"id": self.id, "title": self.title, "inst_key": self.inst_key, "status": self.status,
                "created": self.created, "result_id": self.result_id, "error": self.error}


def coalesce(events: list[dict]) -> list[dict]:
    """把同一智能体连续的逐字片段合并成一条，回放时大幅减少消息数。"""
    out: list[dict] = []
    for ev in events:
        if ev.get("type") == "delta" and out and out[-1].get("type") == "delta" and out[-1]["id"] == ev["id"]:
            merged = dict(out[-1])
            merged["text"] += ev["text"]
            merged["seq"] = ev["seq"]
            out[-1] = merged
        else:
            out.append(ev)
    return out


class JobManager:
    def __init__(self, max_running: int = 2):
        self.max_running = max_running
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def running(self) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.status == "running"]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[dict]:
        self._prune()
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.created)
        return [j.info() for j in jobs]

    def start(self, title: str, inst_key: str, work: Callable[[Job], str | None]) -> Job:
        """work(job) 在后台线程运行，返回历史记录 id；抛出的异常记为失败。"""
        self._prune()
        with self._lock:
            if sum(1 for j in self._jobs.values() if j.status == "running") >= self.max_running:
                raise RuntimeError(f"已有 {self.max_running} 个深度分析正在进行，请等它们完成后再试")
            job = Job(title, inst_key)
            self._jobs[job.id] = job

        def runner():
            from agents.llm import Cancelled
            try:
                job.result_id = work(job)
                job.emit({"type": "done", "result_id": job.result_id})
                job.finish("done")
            except Cancelled:
                job.emit({"type": "cancelled", "message": "分析已取消"})
                job.finish("cancelled")
            except Exception as exc:  # noqa: BLE001 — 任何失败都要告诉前端
                known = type(exc).__name__ in ("LLMError", "SourceError", "NoData", "RateLimited", "CSVError")
                job.error = str(exc) if known else f"内部错误：{type(exc).__name__}: {exc}"
                if not known:
                    logger.error("深度分析任务失败\n%s", traceback.format_exc())
                job.emit({"type": "error", "message": job.error})
                job.finish("error")

        threading.Thread(target=runner, name=f"deep-{job.id}", daemon=True).start()
        return job

    def _prune(self) -> None:
        now = time.time()
        with self._lock:
            for jid in [j.id for j in self._jobs.values() if j.finished and now - j.finished > KEEP_SECONDS]:
                del self._jobs[jid]
