import threading
import unittest

from helpers import DECISION_REPLIES, FakeLLM, stock_md
from agents import rating
from agents.llm import Cancelled, LLMError
from agents.pipeline import DeepOptions, Pipeline, available_analysts, plan, to_markdown
from market import symbols
from market.models import MarketData
from quant import report


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.rep = report.build(stock_md())

    def run_pipeline(self, options=None, quick=None, deep=None, past=None, cancel=None):
        quick = quick or FakeLLM("quick", DECISION_REPLIES)
        deep = deep or FakeLLM("deep", DECISION_REPLIES)
        events = []
        res = Pipeline(quick, deep, events.append, cancel).run(self.rep, options or DeepOptions(), past)
        return res, events, quick, deep

    def test_order_rounds_and_model_tiers(self):
        res, events, quick, deep = self.run_pipeline(DeepOptions(debate_rounds=2, risk_rounds=2))
        ids = [s["id"] for s in res["steps"]]
        self.assertEqual(ids, ["market", "fundamentals", "news", "bull-1", "bear-1", "bull-2", "bear-2", "research_manager",
                               "trader", "aggressive-1", "conservative-1", "neutral-1", "aggressive-2", "conservative-2",
                               "neutral-2", "portfolio_manager"])
        self.assertEqual([c[0] for c in deep.calls], ["研究主管", "投资经理"], "主管与投资经理用深度模型")
        self.assertEqual(len(quick.calls), 14)
        done = [e["id"] for e in events if e["type"] == "agent_done"]
        self.assertEqual(sorted(done), sorted(ids))
        self.assertEqual(done[3:], ids[3:], "辩论之后严格按顺序发言")
        self.assertEqual(res["research"]["rating"], "Overweight")
        self.assertEqual((res["trader"]["action"], res["trader"]["entry"]), ("Buy", 100.0))
        self.assertEqual((res["final"]["rating"], res["final"]["price_target"]), ("Buy", 118.5))
        self.assertEqual(events[-1]["type"], "decision")

    def test_first_speaker_is_told_to_open(self):
        """对手还没发言时要明说，否则模型会编一个对手论点来反驳（TradingAgents #1176）。"""
        _, _, quick, _ = self.run_pipeline()
        bull_prompt = [c for c in quick.calls if c[0] == "多头研究员"][0][2]
        self.assertIn("还没有发言", bull_prompt)
        bear_prompt = [c for c in quick.calls if c[0] == "空头研究员"][0][2]
        self.assertIn("多头研究员的报告", bear_prompt)

    def test_prompts_carry_verified_data_and_identity(self):
        _, _, quick, _ = self.run_pipeline()
        system, market_prompt = quick.calls[0][1], [c for c in quick.calls if c[0] == "技术分析师"][0][2]
        self.assertIn("600519", system)
        self.assertIn("不要替换成其他公司", system)
        self.assertIn("已核验的行情数据快照", market_prompt)
        self.assertIn(f"{self.rep['indicators']['ma20']:,.2f}", market_prompt)

    def test_trader_gets_levels_and_position(self):
        _, _, quick, _ = self.run_pipeline(DeepOptions(position={"shares": 1000, "cost": 90.0, "cash": 50000}))
        trader_prompt = [c for c in quick.calls if c[0] == "交易员"][0][2]
        self.assertIn("关键价位", trader_prompt)
        self.assertIn("持有 1,000 股", trader_prompt)

    def test_no_position_is_not_flat_book(self):
        _, _, quick, _ = self.run_pipeline()
        trader_prompt = [c for c in quick.calls if c[0] == "交易员"][0][2]
        self.assertIn("不要假设空仓", trader_prompt)

    def test_past_decisions_reach_portfolio_manager(self):
        past = [{"date": "2026-09-01", "rating": "Buy", "rating_label": "买入", "price": 90.0,
                 "outcome": {"return": 0.05, "excess": 0.02, "price": 94.5, "days": 40}}]
        _, _, _, deep = self.run_pipeline(past=past)
        pm_prompt = deep.calls[-1][2]
        self.assertIn("历史决策复盘", pm_prompt)
        self.assertIn("2026-09-01", pm_prompt)

    def test_one_analyst_failing_is_tolerated(self):
        quick = FakeLLM("quick", DECISION_REPLIES, fail_roles=("资讯分析师",))
        res, events, _, _ = self.run_pipeline(quick=quick)
        self.assertEqual(res["analysts"]["news"], "")
        self.assertIn("news", res["analyst_errors"])
        self.assertTrue(any(e["type"] == "agent_error" and e["id"] == "news" for e in events))
        bull_prompt = [c for c in quick.calls if c[0] == "多头研究员"][0][2]
        self.assertIn("本次没有资讯报告", bull_prompt)

    def test_all_analysts_failing_aborts(self):
        quick = FakeLLM("quick", fail_roles=("技术分析师", "基本面分析师", "资讯分析师"))
        with self.assertRaises(LLMError):
            self.run_pipeline(quick=quick)

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(Cancelled):
            self.run_pipeline(cancel=ev)

    def test_unreadable_final_is_review(self):
        deep = FakeLLM("deep", {"研究主管": "说不清", "投资经理": "也说不清"})
        res, _, _, _ = self.run_pipeline(deep=deep)
        self.assertEqual(res["final"]["rating"], rating.REVIEW)
        self.assertEqual(res["final"]["label"], "待复核")

    def test_analysts_skipped_without_data(self):
        md = MarketData(symbols.parse("沪深300"), stock_md().bars, symbols.CSI300, [], fetched_at="x")
        rep = report.build(md)
        self.assertEqual(available_analysts(rep, ["market", "fundamentals", "news"]), ["market"])
        self.assertEqual(len(plan(rep, DeepOptions().normalized())), 1 + 2 + 1 + 1 + 3 + 1)

    def test_options_are_clamped(self):
        o = DeepOptions(analysts=["evil", "news"], debate_rounds=99, risk_rounds=0).normalized()
        self.assertEqual((o.analysts, o.debate_rounds, o.risk_rounds), (["news"], 3, 1))

    def test_markdown_export(self):
        res, _, _, _ = self.run_pipeline()
        text = to_markdown(res)
        self.assertIn("最终结论：买入（Buy）", text)
        self.assertNotIn("```json", text)
        self.assertIn("不构成任何投资建议", text)


if __name__ == "__main__":
    unittest.main()
