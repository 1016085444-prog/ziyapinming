"""子牙财鉴 —— 财富指数测算站。独立于主站部署。

    uvicorn caifu.app:app --port 8100

排盘仍是纯本地计算、无外部调用。和主站不同的是这个站本身是付费商品：
一个兑换码绑定一个生日（见 codes.py），所以多了一张很小的绑定表，以及
一个给店主用的管理页 /admin（生成码、查码、重置码）。
"""

from __future__ import annotations

import hmac
import logging
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bazi.chart import build_chart as bazi_chart
from ziwei.chart import build_chart as ziwei_chart

from . import codes, config
from .report import wealth_report

log = logging.getLogger("caifu")
app = FastAPI(title="子牙财鉴", docs_url=None, redoc_url=None)


class BirthInput(BaseModel):
    year: int = Field(..., ge=1900, le=2100)
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    gender: str = Field("male", pattern="^(male|female)$")
    longitude: float = Field(116.4074, ge=-180, le=180)
    tz_offset: float = Field(8.0, ge=-12, le=14)
    use_true_solar_time: bool = True
    late_zi_shifts_day: bool = True
    adjust_china_dst: bool = True
    code: str = Field("", max_length=40)


# ── 绑定表：首次用到时才连，连不上不影响页面本身打开 ──────────────

_store = None
_store_lock = threading.Lock()


def store():
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = codes.open_store(config.MYSQL_URL, config.DB_PATH)
    return _store


def _gate(p: BirthInput):
    """兑换码校验 + 绑定生日。开放模式直接放行。"""
    if config.OPEN_ACCESS:
        return
    if not config.CODE_SECRET:
        # 宁可整站不可用，也不要在忘配密钥时变成人人免费
        log.error("CAIFU_CODE_SECRET 未设置，测算接口已关闭")
        raise HTTPException(503, "站点正在维护，请稍后再试")
    try:
        codes.redeem(store(), config.CODE_SECRET, p.code, p.year, p.month, p.day)
    except codes.CodeError as exc:
        raise HTTPException(exc.status, str(exc))
    except Exception:
        log.exception("绑定表读写失败")
        raise HTTPException(503, "服务繁忙，请稍后再试")


@app.post("/api/wealth")
def api_wealth(p: BirthInput):
    """同一个生辰排两张盘（八字 + 紫微），合成一份财富报告。"""
    common = dict(
        gender=p.gender, longitude=p.longitude, tz_offset=p.tz_offset,
        use_true_solar_time=p.use_true_solar_time,
        late_zi_shifts_day=p.late_zi_shifts_day,
        adjust_china_dst=p.adjust_china_dst,
    )
    # 先排盘再验码：填了 2 月 30 日这类非法日期，不该白白占掉一个码
    try:
        bz = bazi_chart(p.year, p.month, p.day, p.hour, p.minute, **common)
        zw = ziwei_chart(p.year, p.month, p.day, p.hour, p.minute, **common)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    _gate(p)

    this_year = time.localtime().tm_year
    bd = bz.to_dict()
    return {
        "birth": {
            "公历": bd["出生"]["登记时刻"],
            "真太阳时": bd["出生"]["真太阳时"],
            "农历": zw.to_dict()["出生"]["农历"],
            "性别": bd["出生"]["性别"],
            "生肖": bd["出生"]["生肖"],
            "四柱": [x["干支"] for x in bd["四柱"]],
            "距时辰交界": bd["出生"]["距时辰交界"],
            "已回退夏令时": bd["出生"]["已回退夏令时"],
        },
        "report": wealth_report(bz, zw, this_year),
    }


@app.get("/api/config")
def api_config():
    return config.public_config()


# ── 店主管理 ──────────────────────────────────────────────

class AdminAuth(BaseModel):
    key: str = Field(..., max_length=200)


class AdminMake(AdminAuth):
    count: int = Field(1, ge=1, le=100)


class AdminCode(AdminAuth):
    code: str = Field(..., max_length=40)


_fails = {"n": 0, "until": 0.0}


def _admin(key):
    """管理口令校验。连错 10 次锁 10 分钟，挡住在线暴力猜口令。"""
    now = time.time()
    if now < _fails["until"]:
        raise HTTPException(429, "尝试次数过多，请 10 分钟后再试")
    if not config.ADMIN_KEY or not config.CODE_SECRET:
        raise HTTPException(503, "管理功能未启用：请先在环境变量里设置 "
                                 "CAIFU_ADMIN_KEY 与 CAIFU_CODE_SECRET")
    if not hmac.compare_digest(key.encode(), config.ADMIN_KEY.encode()):
        _fails["n"] += 1
        if _fails["n"] >= 10:
            _fails.update(n=0, until=now + 600)
        raise HTTPException(401, "管理口令不对")
    _fails["n"] = 0


@app.post("/api/admin/login")
def admin_login(p: AdminAuth):
    _admin(p.key)
    return {"ok": True, "storage": "MySQL" if config.MYSQL_URL else "本地 SQLite"}


@app.post("/api/admin/codes")
def admin_codes(p: AdminMake):
    _admin(p.key)
    return {"codes": [codes.make_code(config.CODE_SECRET) for _ in range(p.count)]}


@app.post("/api/admin/lookup")
def admin_lookup(p: AdminCode):
    _admin(p.key)
    c = codes.normalize(p.code)
    if not codes.is_valid(config.CODE_SECRET, c):
        return {"code": codes.pretty(c), "valid": False}
    row = store().get(c)
    return {
        "code": codes.pretty(c), "valid": True, "bound": row is not None,
        "bound_at": row and time.strftime("%Y-%m-%d %H:%M", time.localtime(row["bound_at"])),
        "last_at": row and time.strftime("%Y-%m-%d %H:%M", time.localtime(row["last_at"])),
        "uses": row and row["uses"],
    }


@app.post("/api/admin/reset")
def admin_reset(p: AdminCode):
    _admin(p.key)
    c = codes.normalize(p.code)
    if not codes.is_valid(config.CODE_SECRET, c):
        raise HTTPException(400, "这不是一个有效的兑换码")
    store().reset(c)
    return {"ok": True, "code": codes.pretty(c)}


# ── 静态资源 ──────────────────────────────────────────────

_OWN = ("caifu.css", "caifu.js", "admin.js")
_SHARED = ("common.js", "places.js")


def _asset_version():
    """取所有引用资源的最新修改时间做版本号，改完即刻生效、不牺牲缓存。"""
    paths = [config.STATIC_DIR / n for n in _OWN] + \
            [config.SHARED_STATIC_DIR / n for n in _SHARED]
    return str(int(max(p.stat().st_mtime for p in paths)))


def _page(name):
    html = (config.STATIC_DIR / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()))


@app.get("/", response_class=HTMLResponse)
def index():
    return _page("index.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return _page("admin.html")


# 与主站共用的两份脚本：直接读主站那一份，不复制——城市表只能有一处定义
@app.get("/shared/{name}")
def shared(name: str):
    if name not in _SHARED:
        raise HTTPException(404)
    return FileResponse(config.SHARED_STATIC_DIR / name,
                        media_type="application/javascript")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
