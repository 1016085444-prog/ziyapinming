"""测试公用：确定性的合成行情、脚本化的假模型、隔离的数据目录。

所有测试都不联网：数据源用样例响应或替身函数，大模型用 FakeLLM。
必须在导入 config / app 之前设置数据目录，所以每个测试文件都先 import helpers。
"""

from __future__ import annotations

import os
import random
import tempfile
from datetime import date, timedelta

os.environ["TOUYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="touyan-test-")
for _key in ("APP_PASSWORD", "TOUYAN_LLM_PROVIDER", "TOUYAN_QUICK_MODEL", "TOUYAN_DEEP_MODEL", "DEEPSEEK_API_KEY"):
    os.environ.pop(_key, None)

from market import symbols  # noqa: E402
from market.models import (Bar, FinancialPeriod, FundManager, FundProfile, Holding, Instrument,  # noqa: E402
                           MarketData, NewsItem, Quote)


def trading_days(n: int, end: date | None = None) -> list[str]:
    """最近 n 个工作日（不含周末），按日期升序。"""
    d = end or date(2026, 10, 30)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def walk(n: int, start: float = 100.0, drift: float = 0.0005, vol: float = 0.015, seed: int = 1,
         nav: bool = False, end: date | None = None) -> list[Bar]:
    rnd = random.Random(seed)
    p = start
    out = []
    for d in trading_days(n, end):
        c = p * (1 + rnd.gauss(drift, vol))
        if nav:
            out.append(Bar(d, c, c, c, c, 0.0, adj=c))
        else:
            o = p
            out.append(Bar(d, o, max(o, c) * 1.004, min(o, c) * 0.996, c, rnd.uniform(1e4, 5e4), turnover=0.8))
        p = c
    return out


def line_bars(prices: list[float], end: date | None = None) -> list[Bar]:
    """按给定收盘价生成 K 线（开盘 = 前收），便于手算。"""
    days = trading_days(len(prices), end)
    out = []
    prev = prices[0]
    for d, c in zip(days, prices):
        out.append(Bar(d, prev, max(prev, c), min(prev, c), c, 1000.0))
        prev = c
    return out


def stock_md(n: int = 600, seed: int = 3) -> MarketData:
    inst = symbols.parse("600519")
    inst.name = "样例股份"
    fin = [
        FinancialPeriod("2026-09-30", "2026三季报", 1.2e11, 15.5, 6e10, 14.2, 13.9, 26.1, 91.5, 52.3, 19.0, 48.2, 190.0, 55.0, 3.2),
        FinancialPeriod("2026-06-30", "2026中报", 8e10, 18.0, 4e10, 16.0, 15.8, 18.0, 91.0, 51.0, 20.0, 32.0, 180.0, 30.0, 3.1),
    ]
    bars = walk(n, seed=seed)
    md = MarketData(inst, bars, symbols.CSI300, walk(n, 3800, 0.0002, 0.01, seed=99),
                    Quote(price=bars[-1].close, pe=24.5, pb=7.9, total_cap=2.1e12, float_cap=2.1e12, industry="酿酒行业", source="测试"),
                    fin, fetched_at="2026-10-30 15:00")
    md.news = [NewsItem("样例新闻", "2026-10-29 10:00", "测试", "https://example.com/a", "摘要")]
    md.market_news = [NewsItem("样例快讯", "2026-10-30 09:00", "测试")]
    md.sources = {"行情": "测试", "财务": "测试"}
    return md


def fund_md(n: int = 800) -> MarketData:
    inst = Instrument("110011", "OF", "fund", "样例基金")
    profile = FundProfile(name="样例基金", fund_type="混合型-偏股", scale=31.2,
                          managers=[FundManager("张三", "6年又10天", 6.03, "100亿")], rank=120, rank_total=4000,
                          holdings=[Holding(f"60000{i}", f"重仓{i}", 8.0) for i in range(10)])
    md = MarketData(inst, walk(n, 1.5, 0.0006, 0.011, seed=5, nav=True), symbols.CSI300,
                    walk(n, 3800, 0.0002, 0.01, seed=99), fund=profile, fetched_at="2026-10-30 15:00")
    md.sources = {"净值": "测试"}
    return md


class FakeLLM:
    """按角色返回固定内容的假模型；记录每次调用的角色与提示词。"""

    def __init__(self, label: str = "fake", replies: dict | None = None, fail_roles: tuple = (), chunk: int = 5):
        self.label = label
        self.replies = replies or {}
        self.fail_roles = fail_roles
        self.chunk = chunk
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, system, user, on_delta=None, cancel=None):
        from agents.llm import Cancelled, LLMError
        role = system.split("团队中的")[1].split("。")[0] if "团队中的" in system else "test"
        self.calls.append((role, system, user))
        if role in self.fail_roles:
            raise LLMError(f"{role} 模拟失败")
        text = self.replies.get(role, f"{role}的报告")
        for i in range(0, len(text), self.chunk):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if on_delta:
                on_delta(text[i:i + self.chunk])
        return text


DECISION_REPLIES = {
    "研究主管": "**评级**：增持\n理由\n```json\n{\"rating\": \"Overweight\", \"summary\": \"偏多\"}\n```",
    "交易员": "**操作**：买入\n```json\n{\"action\": \"Buy\", \"entry_price\": 100, \"stop_loss\": 93, \"take_profit\": 115, \"position\": \"三成\"}\n```",
    "投资经理": "**评级**：买入\n```json\n{\"rating\": \"Buy\", \"price_target\": 118.5, \"time_horizon\": \"3-6个月\", \"confidence\": \"中\", \"summary\": \"看多\"}\n```",
}
