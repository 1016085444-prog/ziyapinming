"""站点配置 —— 上线前你需要改的东西基本都在这个文件里。

私域引流模式：排盘完全免费且无成本（纯本地计算），命盘只给「骨架」，
真正值钱的解读引导到微信上由真人完成。所以微信号填错 = 整个漏斗断掉，
这是全站最要紧的一个常量。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ── 微信引流（必改）──────────────────────────────────────────
#
# 1. WECHAT_ID 填你的微信号（不是昵称——昵称搜不到人）。
# 2. 把你的二维码图片存成 static/wechat-qr.png，尺寸建议 ≥ 430×430。
#    没放图也能跑，页面会自动只显示微信号和复制按钮。

WECHAT_ID = os.environ.get("WECHAT_ID", "JHan20001230")

# 加微信后你承诺给什么。要具体——「了解更多」这类空话没人加。
WECHAT_OFFER = os.environ.get(
    "WECHAT_OFFER",
    "加我微信，发送本页命盘截图，我会回一份针对你这张盘的精批要点。",
)

WECHAT_QR_FILE = "wechat-qr.png"


def wechat_qr_url():
    """二维码存在才返回地址，否则返回 None（前端据此隐藏图片位）。"""
    if (STATIC_DIR / WECHAT_QR_FILE).exists():
        return "/static/{}".format(WECHAT_QR_FILE)
    return None


def public_config():
    """暴露给前端的配置。注意：这里的东西都会出现在页面源码里，
    不要往里塞任何密钥。"""
    return {
        "wechat_id": WECHAT_ID,
        "wechat_offer": WECHAT_OFFER,
        "wechat_qr": wechat_qr_url(),
    }
