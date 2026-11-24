"""子牙品命 —— 八字与紫微双盘排盘 Web 服务（一密一人核销版）。

商业模型：
    小红书/发卡渠道自动发货（一次性密码）
      ──► 网站凭密码排盘（一密绑一人，八字＋紫微双盘通用，随时回看）
      ──► 底部微信号 ziyapinming 承接真人深度精批

排盘纯本地计算，零大模型 API 费用；密码核销使用标准库 SQLite 落盘，
腾讯云单机部署即天然持久化，重启不丢数据。
"""

from __future__ import annotations

import hmac
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import codes
import config
from bazi.analysis import analyze, year_outlook
from bazi.chart import build_chart
from bazi.inquiry import open_questions
from bazi.scoring import score_chart

from ziwei.analysis import analyze as zw_analyze, year_outlook as zw_year_outlook
from ziwei.chart import build_chart as zw_build_chart
from ziwei.inquiry import open_questions as zw_open_questions
from ziwei.scoring import score_chart as zw_score_chart

app = FastAPI(title="子牙品命", docs_url=None, redoc_url=None)


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
    code: str = Field("", max_length=64)


class ZiweiInput(BirthInput):
    """紫微斗数的入参：同一个生辰，多两处流派选项。"""
    year_boundary: str = Field("lunar", pattern="^(lunar|lichun)$")
    leap_month_rule: str = Field("current", pattern="^(current|split)$")


class GenerateCodesInput(BaseModel):
    count: int = Field(50, ge=1, le=2000)
    prefix: str = Field("ZY", max_length=8)
    note: str = Field("", max_length=80)


class ToggleCodeInput(BaseModel):
    disabled: bool


def _require_valid_code(payload: BirthInput) -> Optional[dict]:
    """核验并绑定兑换密码（一密绑一人，八字与紫微通用）。"""
    if not config.REQUIRE_CODE:
        return None
    key, summary = codes.birth_fingerprint(
        payload.year, payload.month, payload.day,
        payload.hour, payload.minute,
        payload.gender, payload.longitude, payload.tz_offset,
        payload.use_true_solar_time, payload.late_zi_shifts_day,
        payload.adjust_china_dst,
    )
    ok, state_tag, msg = codes.get_store().verify_and_bind(payload.code, key, summary)
    if not ok:
        raise HTTPException(403, msg)
    return {
        "code": codes.normalize_code(payload.code),
        "state": state_tag,
        "message": msg,
    }


def _require_admin(x_admin_token: Optional[str]) -> None:
    expected = config.ADMIN_TOKEN
    if not expected:
        raise HTTPException(
            503,
            "管理后台未启用：请先在服务器环境变量中设置 ADMIN_TOKEN 后重启服务",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token.strip(), expected):
        raise HTTPException(401, "管理口令不正确")


@app.post("/api/chart")
def api_chart(payload: BirthInput):
    """排盘 + 命理分析。先验历法合法性，再核销绑定密码，避免误填非法日期浪费密码。"""
    try:
        chart = build_chart(
            payload.year, payload.month, payload.day,
            payload.hour, payload.minute,
            gender=payload.gender,
            longitude=payload.longitude,
            tz_offset=payload.tz_offset,
            use_true_solar_time=payload.use_true_solar_time,
            late_zi_shifts_day=payload.late_zi_shifts_day,
            adjust_china_dst=payload.adjust_china_dst,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    code_info = _require_valid_code(payload)
    this_year = time.localtime().tm_year
    return {
        "chart": chart.to_dict(),
        "analysis": analyze(chart),
        "scores": score_chart(chart),
        "inquiry": open_questions(chart, this_year),
        "years": [
            year_outlook(chart, y)
            for y in (this_year, this_year + 1, this_year + 2)
        ],
        "code_info": code_info,
    }


@app.post("/api/ziwei")
def api_ziwei(payload: ZiweiInput):
    """紫微斗数排盘 + 分析。同一密码与八字页共用绑定生辰。"""
    try:
        chart = zw_build_chart(
            payload.year, payload.month, payload.day,
            payload.hour, payload.minute,
            gender=payload.gender,
            longitude=payload.longitude,
            tz_offset=payload.tz_offset,
            use_true_solar_time=payload.use_true_solar_time,
            late_zi_shifts_day=payload.late_zi_shifts_day,
            adjust_china_dst=payload.adjust_china_dst,
            year_boundary=payload.year_boundary,
            leap_month_rule=payload.leap_month_rule,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    code_info = _require_valid_code(payload)
    this_year = time.localtime().tm_year
    return {
        "chart": chart.to_dict(),
        "analysis": zw_analyze(chart),
        "scores": zw_score_chart(chart),
        "inquiry": zw_open_questions(chart, this_year),
        "years": [
            zw_year_outlook(chart, y)
            for y in (this_year, this_year + 1, this_year + 2)
        ],
        "code_info": code_info,
    }


@app.get("/api/config")
def api_config():
    """前端启动时拉一次，拿微信号、二维码与是否启用兑换码。"""
    return config.public_config()


# ── 卡密管理后台接口（需 X-Admin-Token） ─────────────────────

@app.get("/api/admin/stats")
def admin_stats(x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    store = codes.get_store()
    return {
        "stats": store.stats(),
        "storage": store.storage_info(),
        "require_code": config.REQUIRE_CODE,
    }


@app.get("/api/admin/codes")
def admin_list_codes(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    x_admin_token: Optional[str] = Header(None),
):
    _require_admin(x_admin_token)
    store = codes.get_store()
    return {
        "stats": store.stats(),
        "items": store.list_codes(status=status, q=q, limit=limit),
    }


@app.post("/api/admin/codes")
def admin_generate_codes(
    payload: GenerateCodesInput,
    x_admin_token: Optional[str] = Header(None),
):
    _require_admin(x_admin_token)
    store = codes.get_store()
    created = store.generate(
        count=payload.count, prefix=payload.prefix, note=payload.note
    )
    return {
        "created": created,
        "count": len(created),
        "stats": store.stats(),
    }


@app.get("/api/admin/codes/export", response_class=PlainTextResponse)
def admin_export_unused(
    note: Optional[str] = Query(None),
    x_admin_token: Optional[str] = Header(None),
):
    """导出未使用卡密纯文本（一行一个），可直接粘贴进自动发货卡密库。"""
    _require_admin(x_admin_token)
    items = codes.get_store().list_codes(status="unused", q=note, limit=1000)
    lines = [it["code"] for it in items]
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": 'attachment; filename="ziyapinming-codes.txt"'},
    )


@app.post("/api/admin/codes/{code}/toggle")
def admin_toggle_code(
    code: str,
    payload: ToggleCodeInput,
    x_admin_token: Optional[str] = Header(None),
):
    _require_admin(x_admin_token)
    ok = codes.get_store().set_disabled(code, payload.disabled)
    if not ok:
        raise HTTPException(404, "未找到该密码")
    return {"ok": True, "stats": codes.get_store().stats()}


@app.post("/api/admin/codes/{code}/reset")
def admin_reset_code(
    code: str,
    x_admin_token: Optional[str] = Header(None),
):
    """解除绑定（买家填错出生日期时客服救急用）。"""
    _require_admin(x_admin_token)
    ok = codes.get_store().reset_code(code)
    if not ok:
        raise HTTPException(404, "未找到该密码")
    return {"ok": True, "stats": codes.get_store().stats()}


# ── 页面与静态资源 ────────────────────────────────────────────

_ASSETS = ("style.css", "common.js", "app.js", "places.js", "ziwei.css", "ziwei.js")


def _asset_version():
    return str(int(max(
        (config.STATIC_DIR / name).stat().st_mtime for name in _ASSETS
    )))


def _page(name):
    html = (config.STATIC_DIR / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()))


@app.get("/", response_class=HTMLResponse)
def index():
    return _page("index.html")


@app.get("/ziwei", response_class=HTMLResponse)
def ziwei():
    return _page("ziwei.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return _page("admin.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
