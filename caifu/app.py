"""子牙财鉴 —— 财富指数测算站。独立于主站部署。

    uvicorn caifu.app:app --port 8100

和主站一样是纯本地计算、无外部调用、不留任何用户状态：没有可变成本，
所以也不需要会话、额度与防刷。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bazi.chart import build_chart as bazi_chart
from ziwei.chart import build_chart as ziwei_chart

from . import config
from .report import wealth_report

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


@app.post("/api/wealth")
def api_wealth(p: BirthInput):
    """同一个生辰排两张盘（八字 + 紫微），合成一份财富报告。"""
    common = dict(
        gender=p.gender, longitude=p.longitude, tz_offset=p.tz_offset,
        use_true_solar_time=p.use_true_solar_time,
        late_zi_shifts_day=p.late_zi_shifts_day,
        adjust_china_dst=p.adjust_china_dst,
    )
    try:
        bz = bazi_chart(p.year, p.month, p.day, p.hour, p.minute, **common)
        zw = ziwei_chart(p.year, p.month, p.day, p.hour, p.minute, **common)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

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


# ── 静态资源 ──────────────────────────────────────────────

_OWN = ("caifu.css", "caifu.js")
_SHARED = ("common.js", "places.js")


def _asset_version():
    """取所有引用资源的最新修改时间做版本号，改完即刻生效、不牺牲缓存。"""
    paths = [config.STATIC_DIR / n for n in _OWN] + \
            [config.SHARED_STATIC_DIR / n for n in _SHARED]
    return str(int(max(p.stat().st_mtime for p in paths)))


@app.get("/", response_class=HTMLResponse)
def index():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()))


# 与主站共用的两份脚本：直接读主站那一份，不复制——城市表只能有一处定义
@app.get("/shared/{name}")
def shared(name: str):
    if name not in _SHARED:
        raise HTTPException(404)
    return FileResponse(config.SHARED_STATIC_DIR / name,
                        media_type="application/javascript")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
