"""站点配置 —— 上线前你需要改的东西基本都在这个文件里。

一密一人模式（腾讯云部署）：
  - 兑换密码（卡密）通过 SQLite 落盘存储，一个密码绑定一个生辰，八字与紫微互通；
  - 排盘结果页底部引导添加微信号 ziyapinming，承接高客单真人精批。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ── 站点地址 ────────────────────────────────────────────────
SITE_URL = os.environ.get(
    "SITE_URL",
    "https://ziyapinmingzw-288718-10-1460102831.sh.run.tcloudbase.com",
).rstrip("/")

# ── 微信引流 ────────────────────────────────────────────────
# 微信号（不是昵称——昵称搜不到人）。可通过环境变量 WECHAT_ID 覆盖。
WECHAT_ID = os.environ.get("WECHAT_ID", "ziyapinming")

# 加微信后的具体承接说明
WECHAT_OFFER = os.environ.get(
    "WECHAT_OFFER",
    "添加微信 ziyapinming，发来本页命盘截图与你最想问的事，由命理师一对一深度精批。",
)

WECHAT_QR_FILE = "wechat-qr.png"

# ── 一次性兑换密码（卡密）配置 ───────────────────────────────
# 默认开启卡密核销（设为 0/false 可临时关闭做免密调试）
REQUIRE_CODE = os.environ.get("REQUIRE_CODE", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

# SQLite 卡密数据库路径（腾讯云部署建议指向独立数据目录如 /var/lib/ziyapinming/codes.db）
CODES_DB_PATH = Path(
    os.environ.get("CODES_DB_PATH", str(BASE_DIR / "data" / "codes.db"))
)

# 卡密管理后台口令（只走环境变量，切勿写死进代码或 GitHub）
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()


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
        "require_code": REQUIRE_CODE,
    }
