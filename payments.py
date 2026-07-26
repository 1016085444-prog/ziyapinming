"""支付：Stripe Checkout + Webhook 履约。

⚠️ 当前未接入。私域模式下成交发生在微信里（真人收款），站上不再有付费墙，
   app.py 没有 import 这个模块。保留以备将来上线自助购买时复用。


没配置 STRIPE_SECRET_KEY 时自动降级为开发模式——点「购买」直接解锁，
方便本地跑通整条转化漏斗，不必先注册商户。上线前务必设好环境变量，
否则等于白送。

环境变量
--------
STRIPE_SECRET_KEY       sk_live_... / sk_test_...
STRIPE_WEBHOOK_SECRET   whsec_...（Webhook 签名校验，必配）
PUBLIC_BASE_URL         对外可访问的站点地址，用于支付后跳回
CURRENCY                默认 cny
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

import stripe

__all__ = ["PRODUCTS", "dev_mode", "create_checkout", "verify_webhook", "Product"]


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    amount: int          # 最小货币单位（分）
    grants_report: bool
    grants_unlimited: bool


PRODUCTS = {
    "report": Product(
        key="report",
        name="深度批命报告",
        amount=6800,
        grants_report=True,
        grants_unlimited=False,
    ),
    "unlimited": Product(
        key="unlimited",
        name="不限次问命 · 30 天（含深度报告）",
        amount=9800,
        grants_report=True,
        grants_unlimited=True,
    ),
}  # type: Dict[str, Product]

CURRENCY = os.environ.get("CURRENCY", "cny")


def dev_mode():
    """未配置密钥即为开发模式。"""
    return not os.environ.get("STRIPE_SECRET_KEY")


def _client():
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_checkout(product, session_id):
    """建一个 Stripe Checkout 会话，返回收银台地址。

    session_id 塞进 metadata，Webhook 回来时靠它找到要解锁的会话。
    """
    base = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    sk = _client()

    checkout = sk.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": CURRENCY,
                "product_data": {"name": product.name},
                "unit_amount": product.amount,
            },
            "quantity": 1,
        }],
        # 我们的会话 id 同时作为幂等锚点：同一命盘重复下单不会串号
        client_reference_id=session_id,
        metadata={"session_id": session_id, "product": product.key},
        success_url="{}/?paid={}&sid={}".format(base, product.key, session_id),
        cancel_url="{}/?canceled=1&sid={}".format(base, session_id),
    )
    return checkout.url


def verify_webhook(payload, signature):
    """校验 Stripe 签名并返回事件。签名不对就抛异常——不要跳过这一步，
    否则任何人都能伪造「已付款」把权益白拿走。"""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("未配置 STRIPE_WEBHOOK_SECRET，拒绝处理 Webhook")
    _client()
    return stripe.Webhook.construct_event(payload, signature, secret)
