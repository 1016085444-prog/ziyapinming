"""财富站配置 —— 与主站（子牙品命）完全独立，上线前改这里即可。

财富站是一个**单独部署的站点**：独立入口（caifu/app.py）、独立页面、独立
配置、独立网址。它与主站唯一共享的是排盘内核（bazi/、ziwei/）和两份通用
前端脚本（剪贴板兜底、城市表），这样两个站算出来的盘永远一致。

所有项都可以用同名环境变量覆盖，部署时不改代码也能换。
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
# 与主站共用的两份前端脚本（剪贴板/滚动/生日输入 与 354 城市表）所在目录
SHARED_STATIC_DIR = PACKAGE_DIR.parent / "static"

# ── 站点地址 ────────────────────────────────────────────────
# 财富站自己的网址。和主站分开部署后，这里填财富站的域名。
SITE_URL = os.environ.get("CAIFU_SITE_URL", "").rstrip("/")

SITE_NAME = os.environ.get("CAIFU_SITE_NAME", "子牙财鉴")

# ── 微信引流（必改）──────────────────────────────────────────
# 默认与主站同一个微信号；若财富站要单独接待，填另一个号即可。
WECHAT_ID = os.environ.get("CAIFU_WECHAT_ID", "JHan20001230")

# 加微信能得到什么。要具体——「了解更多」这类空话没人加。
WECHAT_OFFER = os.environ.get(
    "CAIFU_WECHAT_OFFER",
    "加微信发送「财富」，附上本页截图，我会回你一份针对这张盘的财运要点。",
)

# 一对一精批的价格展示（与网站本身的售价无关）。留空则不显示价格，
# 只显示「添加微信咨询」。填写示例："¥99"。注意：只写真实售价，不要写虚构的「原价」做划线对比——
# 那属于虚构原价，违反《价格法》与《明码标价和禁止价格欺诈规定》。
PREMIUM_PRICE = os.environ.get("CAIFU_PREMIUM_PRICE", "")

# 本站本身是付费商品：用户在各平台的同名店铺下单，拿到网址再来测。
# 所以店铺名要印在「会被截图分享出去」的地方——财富金卡上和金卡下方——
# 朋友看到截图想测，才知道去哪里买。留空则不显示。
SHOP_NAME = os.environ.get("CAIFU_SHOP_NAME", "ziyapinming")
SHOP_NOTE = os.environ.get(
    "CAIFU_SHOP_NOTE",
    "朋友也想测？各大平台搜索同名店铺「{}」".format(SHOP_NAME) if SHOP_NAME else "",
)

# ── 兑换码（必配）────────────────────────────────────────────
#
# 网站本身是付费商品：一个兑换码绑定一个生日。下面三项都只走环境变量，
# **不要写进代码**——仓库一旦公开，拿到密钥的人就能自己造码。
#
#   CAIFU_CODE_SECRET  签发兑换码的密钥。随便一长串随机字符，设定后不要再改，
#                      改了之前卖出去的码全部作废。
#   CAIFU_ADMIN_KEY    管理页（/admin）的登录口令，用来生成码、查码、重置码。
#                      和上面那个分开，泄露了换掉也不影响已售的码。
#   CAIFU_MYSQL_URL    绑定记录存哪。形如 mysql://用户:密码@主机:3306/库名 。
#                      云托管容器会重启、会缩到零，本地文件存不住，线上必须配。
#                      不配则存本地 SQLite（CAIFU_DB_PATH），只适合本机开发。
#
# 本机开发不想每次输码：设 CAIFU_OPEN_ACCESS=1 关掉兑换码校验。线上绝不要设。

CODE_SECRET = os.environ.get("CAIFU_CODE_SECRET", "")
ADMIN_KEY = os.environ.get("CAIFU_ADMIN_KEY", "")
MYSQL_URL = os.environ.get("CAIFU_MYSQL_URL", "")
DB_PATH = os.environ.get("CAIFU_DB_PATH", str(PACKAGE_DIR.parent / "data" / "caifu.db"))
OPEN_ACCESS = os.environ.get("CAIFU_OPEN_ACCESS", "") == "1"

# 二维码图片：放在 caifu/static/ 下，存在才显示
WECHAT_QR_FILE = "wechat-qr.png"


def wechat_qr_url():
    if (STATIC_DIR / WECHAT_QR_FILE).exists():
        return "/static/{}".format(WECHAT_QR_FILE)
    return None


def public_config():
    """暴露给前端的配置。会出现在页面源码里，不要放任何密钥。"""
    return {
        "site_name": SITE_NAME,
        "wechat_id": WECHAT_ID,
        "wechat_offer": WECHAT_OFFER,
        "wechat_qr": wechat_qr_url(),
        "premium_price": PREMIUM_PRICE,
        "shop_name": SHOP_NAME,
        "shop_note": SHOP_NOTE,
        "need_code": not OPEN_ACCESS,
    }
