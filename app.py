"""子牙品命 —— 八字排盘 Web 服务。

商业模型（私域引流）：

    免费排盘 ──► 命盘只给骨架 ──► 引导加微信 ──► 真人精批成交

排盘是纯本地计算，没有任何外部调用，所以：**没有可变成本，就不需要
会话、额度、防刷、Redis。** 有人拿脚本狂刷排盘，只花你的 CPU。

这也是这版比 AI 对话版简单一大截的原因——服务端不持有任何用户状态，
命盘算完即返回，进程重启不丢东西。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from bazi.analysis import analyze, year_outlook
from bazi.inquiry import open_questions
from bazi.scoring import score_chart
from bazi.chart import build_chart

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
    # 纬度不参与任何推算（真太阳时只用经度），故不作为入参
    longitude: float = Field(116.4074, ge=-180, le=180)
    tz_offset: float = Field(8.0, ge=-12, le=14)
    use_true_solar_time: bool = True
    late_zi_shifts_day: bool = True
    adjust_china_dst: bool = True


class ZiweiInput(BirthInput):
    """紫微斗数的入参：同一个生辰，多两处流派选项。

    这两处在八字里不存在——八字以立春换年、以节换月，根本用不到农历，
    也就没有闰月归属的问题。
    """
    # 紫微主流以正月初一换年；少数流派用立春，与八字同口径
    year_boundary: str = Field("lunar", pattern="^(lunar|lichun)$")
    # 闰月生人按本月还是按下月定宫
    leap_month_rule: str = Field("current", pattern="^(current|split)$")


@app.post("/api/chart")
def api_chart(payload: BirthInput):
    """排盘 + 命理分析。纯函数：同样的输入永远得到同样的输出，不留状态。"""
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
    }


@app.post("/api/ziwei")
def api_ziwei(payload: ZiweiInput):
    """紫微斗数排盘 + 分析。同样是纯函数，不留状态。

    与 /api/chart 是两条独立的路径而不是一个带 system 参数的接口：两套体系
    的输出结构差得远（四柱 vs 十二宫），塞进一个响应里只会让前端两头都别扭。
    """
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
    }


@app.get("/api/config")
def api_config():
    """前端启动时拉一次，拿微信号与二维码地址。"""
    return config.public_config()


_ASSETS = ("style.css", "app.js", "places.js", "ziwei.css", "ziwei.js")


def _asset_version():
    """用静态资源的最新修改时间做版本号，注入到页面的引用里。

    静态文件带 ETag 缓存，改完 CSS/JS 后老用户会卡在旧版本。加上随文件变化的
    ?v= 参数，一改即刻生效，既不用手动维护版本串，也不必牺牲缓存。

    刻意取**所有**资源的最新时间而不是各自的时间：两个页面共用 places.js，
    分开算版本号会让「改了共用文件但没改本页 JS」的情况漏掉刷新。
    """
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
def ziwei_page():
    return _page("ziwei.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
