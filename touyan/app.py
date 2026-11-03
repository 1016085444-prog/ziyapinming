"""投研智能体 —— Web 服务。

    python app.py                 本机启动，浏览器打开 http://127.0.0.1:8600
    uvicorn app:app --host 0.0.0.0 --port 8600     服务器部署（务必设置 APP_PASSWORD）

接口一览：
    GET  /api/search?q=            搜索证券 / 基金
    GET  /api/analyze?key=|q=      快速量化分析（免费、秒出、不用大模型）
    POST /api/compare              多品种对比
    POST /api/import               导入 CSV 分析任意产品
    POST /api/deep                 发起 AI 深度分析（多智能体，后台运行）
    GET  /api/deep/{id}/events     深度分析实时事件（SSE）
    GET  /api/history…             历史记录与复盘
    GET/POST /api/settings…        大模型设置、连通性测试
    GET  /api/selftest             数据源自检

安全：大模型按调用计费。没有设置访问密码时，「深度分析」和「修改设置」只允许本机访问，
防止服务暴露到公网后被别人刷光额度（原站 README 里提过的那个真实漏洞）。
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from urllib.parse import quote as urlquote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

import config
import selftest
import store as store_mod
from agents.llm import LLMError, make_llm
from agents.pipeline import DeepOptions, Pipeline
from agents.pipeline import to_markdown as deep_markdown
from jobs import JobManager, coalesce
from market import csvfile, symbols
from market.cache import Cache
from market.models import Instrument
from market.net import NoData, SourceError
from market.router import DataRouter
from quant import compare as compare_mod
from quant import report as qr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for _noisy in ("httpx", "httpx2", "openai", "anthropic"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)   # 每个请求一行 INFO，太吵
log = logging.getLogger("touyan")

@asynccontextmanager
async def lifespan(_app):
    yield
    cache.close()
    store.close()


app = FastAPI(title="投研智能体", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)

cache = Cache(config.CACHE_PATH)
router = DataRouter(cache)
store = store_mod.Store(config.DB_PATH)
jobs = JobManager(config.MAX_JOBS)
imports: dict[str, dict] = {}       # CSV 导入的数据，供深度分析复用（只在内存里）
IMPORT_TTL = 2 * 3600


# ── 访问控制 ───────────────────────────────────────────────────

def _authorized(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        _, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(password.encode(), config.APP_PASSWORD.encode())


@app.middleware("http")
async def password_gate(request: Request, call_next):
    if config.APP_PASSWORD and request.url.path != "/api/health" and not _authorized(request):
        return Response("需要访问密码", status_code=401, headers={"WWW-Authenticate": 'Basic realm="touyan", charset="UTF-8"'})
    return await call_next(request)


def is_local(request: Request) -> bool:
    # 经过反向代理的请求一律视为远程：本机浏览器不会带这些头
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        return False
    host = request.client.host if request.client else ""
    return host in ("::1", "localhost") or host.startswith("127.")


def trusted(request: Request) -> bool:
    return bool(config.APP_PASSWORD) or config.ALLOW_REMOTE or is_local(request)


def require_trusted(request: Request) -> None:
    if not trusted(request):
        raise HTTPException(403, "为防止他人消耗你的大模型额度，远程访问时需要先设置访问密码"
                                 "（环境变量 APP_PASSWORD）才能使用深度分析和修改设置。")


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, NoData):
        return HTTPException(404, str(exc))
    if isinstance(exc, (SourceError, LLMError)):
        return HTTPException(502, str(exc))
    if isinstance(exc, csvfile.CSVError):
        return HTTPException(400, str(exc))
    log.exception("未预期的错误")
    return HTTPException(500, f"内部错误：{type(exc).__name__}: {exc}")


def _rf() -> float:
    return config.load().risk_free_rate / 100


def _instrument(key: str | None, q: str | None, kind: str = "auto", name: str = "", secid: str = "") -> Instrument:
    if key:
        inst = symbols.from_key(key, kind if kind != "auto" else "", name, secid)
        if inst is None:
            raise HTTPException(400, f"无法识别的代码：{key}")
        return inst
    if not q or not q.strip():
        raise HTTPException(400, "请输入代码或名称")
    try:
        return router.resolve(q.strip(), kind)
    except SourceError as exc:
        raise _error(exc) from exc


# ── 基础 ───────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True, "version": config.VERSION}


@app.get("/api/config")
def api_config(request: Request):
    s = config.load()
    ready, reason = config.llm_ready(s)
    quick, deep = config.models(s)
    from agents import providers
    from market import optional
    return {
        "version": config.VERSION,
        "disclaimer": qr.DISCLAIMER,
        "llm_ready": ready,
        "llm_reason": reason,
        "provider": s.provider,
        "provider_label": providers.get(s.provider).label,
        "models": {"quick": quick, "deep": deep},
        "trusted": trusted(request),
        "password_protected": bool(config.APP_PASSWORD),
        "optional": optional.available(),
        "defaults": {"analysts": s.analysts, "debate_rounds": s.debate_rounds, "risk_rounds": s.risk_rounds},
        "running_jobs": [j.info() for j in jobs.running()],
    }


# ── 搜索与快速分析 ─────────────────────────────────────────────

@app.get("/api/search")
def api_search(q: str = ""):
    try:
        return {"items": [i.to_dict() for i in router.search(q)]}
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@app.get("/api/analyze")
def api_analyze(key: str | None = None, q: str | None = None, kind: str = "auto", name: str = "", secid: str = ""):
    inst = _instrument(key, q, kind, name, secid)
    try:
        md = router.load(inst)
        return qr.build(md, _rf())
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@app.get("/api/analyze/markdown")
def api_analyze_markdown(key: str | None = None, q: str | None = None, kind: str = "auto"):
    inst = _instrument(key, q, kind)
    try:
        rep = qr.build(router.load(inst), _rf())
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc
    return _download(qr.to_markdown(rep), f"{inst.name or inst.code}_量化分析_{rep['as_of']}.md")


class CompareRequest(BaseModel):
    keys: list[str] = Field(..., min_length=2, max_length=6)
    period: str = "1y"


@app.post("/api/compare")
def api_compare(req: CompareRequest):
    insts = []
    for key in req.keys:
        inst = symbols.from_key(key)
        if inst is None:
            raise HTTPException(400, f"无法识别的代码：{key}")
        insts.append(inst)
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(inst, pool.submit(router.series, inst)) for inst in insts]
        for inst, fut in futures:
            try:
                bars, _ = fut.result()
                if len(bars) > 20:
                    items.append((inst, bars))
                else:
                    errors.append(f"{inst.display}：数据不足")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{inst.display}：{exc}")
    if len(items) < 2:
        raise HTTPException(502, "可对比的品种不足两个：" + "；".join(errors))
    result = compare_mod.compare(items, req.period, _rf())
    result["errors"] = errors
    return result


@app.post("/api/import")
async def api_import(file: UploadFile = File(...), name: str = Form("导入数据"), currency: str = Form("CNY")):
    raw = await file.read()
    try:
        bars = csvfile.parse_csv(raw)
        currency = currency if currency in ("CNY", "HKD", "USD") else "CNY"
        md = await asyncio.to_thread(router.load_csv, name.strip()[:40] or "导入数据", bars, currency)
        rep = qr.build(md, _rf())
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc
    now = time.time()
    for k in [k for k, v in imports.items() if now - v["created"] > IMPORT_TTL]:
        imports.pop(k, None)
    csv_id = uuid.uuid4().hex[:12]
    imports[csv_id] = {"name": md.instrument.name, "currency": currency, "bars": bars, "created": now}
    rep["csv_id"] = csv_id
    return rep


# ── AI 深度分析 ────────────────────────────────────────────────

class Position(BaseModel):
    shares: float | None = Field(None, ge=0)
    cost: float | None = Field(None, gt=0)
    cash: float | None = Field(None, ge=0)


class DeepRequest(BaseModel):
    key: str | None = None
    q: str | None = None
    kind: str = "auto"
    name: str = ""
    secid: str = ""
    csv_id: str | None = None
    analysts: list[str] | None = None
    debate_rounds: int | None = Field(None, ge=1, le=3)
    risk_rounds: int | None = Field(None, ge=1, le=3)
    position: Position | None = None


def _past(inst_key: str, md) -> list[dict]:
    out = []
    for row in store.list(limit=5, inst_key=inst_key):
        out.append({"date": row["created_at"][:10], "rating": row["rating"], "rating_label": row["rating_label"],
                    "price": row["price"], "outcome": store_mod.outcome(row["as_of"], md.bars, md.benchmark_bars)})
    return out


@app.post("/api/deep")
def api_deep(req: DeepRequest, request: Request):
    require_trusted(request)
    s = config.load()
    ready, reason = config.llm_ready(s)
    if not ready:
        raise HTTPException(400, f"{reason}。请先到「设置」里配置大模型。")
    try:
        quick_cfg, deep_cfg = config.llm_configs(s)
        quick, deep = make_llm(quick_cfg), make_llm(deep_cfg)
    except LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    csv = None
    if req.csv_id:
        csv = imports.get(req.csv_id)
        if csv is None:
            raise HTTPException(404, "导入的数据已过期，请重新上传 CSV")
        inst_key, title = "CSV:CSV", csv["name"]
    else:
        inst = _instrument(req.key, req.q, req.kind, req.name, req.secid)
        inst_key, title = inst.key, inst.display
    position = req.position.model_dump() if req.position and any(v is not None for v in req.position.model_dump().values()) else None
    options = DeepOptions(req.analysts or s.analysts, req.debate_rounds or s.debate_rounds,
                          req.risk_rounds or s.risk_rounds, position)
    rf = s.risk_free_rate / 100

    def work(job):
        job.emit({"type": "stage", "stage": "data", "label": "获取行情、基本面与资讯数据"})
        if csv is not None:
            md = router.load_csv(csv["name"], csv["bars"], csv["currency"])
        else:
            md = router.load(inst)
        rep = qr.build(md, rf)
        job.title = md.instrument.display
        job.emit({"type": "report", "instrument": rep["instrument"], "as_of": rep["as_of"], "summary": rep["summary"],
                  "warnings": rep["warnings"], "scores": rep["scores"]})
        past = _past(md.instrument.key, md) if csv is None else []
        result = Pipeline(quick, deep, job.emit, job.cancel).run(rep, options, past)
        return store.save(result, rep)

    try:
        job = jobs.start(title, inst_key, work)
    except RuntimeError as exc:
        raise HTTPException(429, str(exc)) from exc
    return {"job_id": job.id}


@app.get("/api/deep/jobs")
def api_jobs():
    return {"jobs": jobs.recent()}


@app.get("/api/deep/{job_id}/events")
async def api_deep_events(job_id: str, request: Request, after: int = 0):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已过期")
    last_id = request.headers.get("last-event-id")
    start = int(last_id) + 1 if last_id and last_id.isdigit() else max(0, after)

    async def stream():
        idx = start
        yield "retry: 3000\n\n"
        while True:
            events, finished = await asyncio.to_thread(job.wait, idx, 15.0)
            if events:
                idx = events[-1]["seq"] + 1
                for ev in coalesce(events):
                    yield f"id: {ev['seq']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            elif not finished:
                yield ": ping\n\n"
            if finished and idx >= len(job.events):
                break

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/deep/{job_id}/cancel")
def api_deep_cancel(job_id: str, request: Request):
    require_trusted(request)
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已过期")
    job.cancel.set()
    return {"ok": True}


# ── 历史与复盘 ─────────────────────────────────────────────────

@app.get("/api/history")
def api_history(limit: int = 100, key: str | None = None):
    return {"items": store.list(min(max(limit, 1), 500), key)}


@app.get("/api/history/{rid}")
def api_history_item(rid: str):
    item = store.get(rid)
    if item is None:
        raise HTTPException(404, "记录不存在")
    return item


@app.delete("/api/history/{rid}")
def api_history_delete(rid: str, request: Request):
    require_trusted(request)
    if not store.delete(rid):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@app.get("/api/history/{rid}/markdown")
def api_history_markdown(rid: str):
    item = store.get(rid)
    if item is None:
        raise HTTPException(404, "记录不存在")
    inst = item["result"]["instrument"]
    return _download(deep_markdown(item["result"]), f"{inst.get('name') or inst['code']}_AI深度分析_{item['created_at'][:10]}.md")


class OutcomeRequest(BaseModel):
    ids: list[str] = Field(..., max_length=60)


@app.post("/api/history/outcomes")
def api_outcomes(req: OutcomeRequest):
    rows = [r for r in (store.get(i) for i in req.ids) if r is not None]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["inst_key"], []).append(r)

    def evaluate(key: str, items: list[dict]) -> dict[str, dict]:
        if key.startswith("CSV:"):
            return {r["id"]: {"return": None, "note": "导入数据无法自动复盘"} for r in items}
        inst = symbols.from_key(key, items[0]["kind"], items[0]["name"] or "")
        if inst is None:
            return {}
        try:
            bars, _ = router.series(inst)
            bench_inst = symbols.benchmark_for(inst)
            try:
                bench, _ = router.series(bench_inst) if bench_inst.key != inst.key else (bars, "")
            except SourceError:
                bench = []
        except Exception as exc:  # noqa: BLE001
            return {r["id"]: {"return": None, "note": f"行情获取失败：{exc}"} for r in items}
        out = {}
        for r in items:
            o = store_mod.outcome(r["as_of"], bars, bench)
            o["hit"] = store_mod.direction_hit(r["rating"], o.get("excess", o.get("return")))
            out[r["id"]] = o
        return out

    result: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for part in pool.map(lambda kv: evaluate(*kv), groups.items()):
            result.update(part)
    return {"outcomes": result}


# ── 设置与自检 ─────────────────────────────────────────────────

@app.get("/api/settings")
def api_settings():
    return config.public(config.load())


@app.post("/api/settings")
def api_settings_save(patch: dict, request: Request):
    require_trusted(request)
    try:
        return config.public(config.save(patch))
    except ValueError as exc:
        raise HTTPException(400, f"设置无效：{exc}") from exc


@app.post("/api/settings/test")
def api_settings_test(request: Request, patch: dict | None = None):
    """用当前（或尚未保存的）设置调用一次快模型，确认 Key、模型名、网络都没问题。"""
    require_trusted(request)
    s = config.load()
    patch = patch or {}
    provider = patch.get("provider") or s.provider
    s.provider = provider
    if patch.get("api_key") and patch["api_key"] != "__clear__":
        s.api_keys[provider] = patch["api_key"].strip()
    for field, store_dict in (("base_url", s.base_urls), ("quick_model", s.quick_models), ("deep_model", s.deep_models)):
        if patch.get(field):
            store_dict[provider] = patch[field].strip()
    quick_cfg, _ = config.llm_configs(s)
    quick_cfg.timeout = 90
    started = time.time()
    try:
        llm = make_llm(quick_cfg)
        reply = llm.complete("你是连通性测试助手。", "请只回复两个字：正常")
    except LLMError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 — 测试接口要把任何失败都讲清楚，而不是返回 500
        log.exception("连通性测试失败")
        return {"ok": False, "message": f"调用失败：{type(exc).__name__}: {exc}"}
    return {"ok": True, "model": llm.label, "reply": reply[:80], "ms": int((time.time() - started) * 1000)}


@app.get("/api/selftest")
def api_selftest():
    return selftest.run()


# ── 页面 ───────────────────────────────────────────────────────

def _download(text: str, filename: str) -> PlainTextResponse:
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urlquote(filename)}"})


_ASSETS = ("style.css", "app.js", "chart.js", "md.js")


def _asset_version() -> str:
    """静态资源版本号 = 最新修改时间，改了文件浏览器立即拿到新版（沿用原站的做法）。"""
    return str(int(max((config.STATIC_DIR / n).stat().st_mtime for n in _ASSETS if (config.STATIC_DIR / n).exists())))


@app.get("/", response_class=HTMLResponse)
def index():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()))


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    headers = getattr(exc, "headers", None)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=headers)


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8600"))
    if host not in ("127.0.0.1", "localhost") and not config.APP_PASSWORD:
        log.warning("服务监听在 %s 且没有设置 APP_PASSWORD：深度分析与设置只允许本机使用。", host)
    print(f"\n  投研智能体已启动：http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
