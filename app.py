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


@app.get("/api/config")
def api_config():
    """前端启动时拉一次，拿微信号与二维码地址。"""
    return config.public_config()


_ASSETS = ("style.css", "app.js")


def _asset_version():
    """用静态资源的最新修改时间做版本号，注入到 index.html 的引用里。

    静态文件带 ETag 缓存，改完 CSS/JS 后老用户会卡在旧版本。加上随文件变化的
    ?v= 参数，一改即刻生效，既不用手动维护版本串，也不必牺牲缓存。
    """
    return str(int(max(
        (config.STATIC_DIR / name).stat().st_mtime for name in _ASSETS
    )))


@app.get("/", response_class=HTMLResponse)
def index():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()))


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
