import unittest

from helpers import fund_md, stock_md, walk
from market import symbols
from market.models import FinancialPeriod, FundManager, FundProfile, Instrument, MarketData, Quote
from quant import fund, fundamental, report, scoring
from quant.technical import Signal


class FundamentalTest(unittest.TestCase):
    def test_a_share_roe_is_annualized_by_period(self):
        inst = symbols.parse("600519")
        q1 = FinancialPeriod("2026-03-31", "一季报", roe=6.0)
        h1 = FinancialPeriod("2026-06-30", "中报", roe=10.0)
        q3 = FinancialPeriod("2026-09-30", "三季报", roe=15.0)
        fy = FinancialPeriod("2025-12-31", "年报", roe=20.0)
        self.assertEqual([fundamental.annualize_roe(p, inst) for p in (q1, h1, q3, fy)], [24.0, 20.0, 20.0, 20.0])
        self.assertEqual(fundamental.annualize_roe(q1, symbols.parse("AAPL")), 6.0, "非 A 股不年化")

    def test_financial_industry_skips_debt_and_margin(self):
        inst = symbols.parse("601398")
        p = FinancialPeriod("2025-12-31", "年报", roe=10.0, debt_ratio=91.0, gross_margin=None)
        out = fundamental.analyze(inst, Quote(pe=5.0, pb=0.6), [p], "银行")
        debt = [s for s in out["signals"] if s.key == "debt"][0]
        self.assertEqual(debt.impact, 0)
        self.assertIn("金融企业", debt.detail)

    def test_loss_and_peg(self):
        inst = symbols.parse("600000")
        loss = fundamental.analyze(inst, Quote(pe=-12.0), [], "")
        self.assertEqual([s.impact for s in loss["signals"] if s.key == "pe"], [-10])
        cheap = fundamental.analyze(inst, Quote(pe=10.0), [FinancialPeriod("2025-12-31", net_profit_yoy=25.0)], "")
        self.assertAlmostEqual(cheap["valuation"]["peg"], 0.4)
        self.assertTrue(all("未做同行业比较" in s.detail for s in cheap["signals"] if s.key == "pe"))


class FundRulesTest(unittest.TestCase):
    def test_small_scale_liquidation_warning_and_new_manager(self):
        inst = Instrument("000001", "OF", "fund")
        profile = FundProfile(scale=0.3, managers=[FundManager("新人", "200天", 0.55)])
        sigs = fund.analyze(inst, profile, {}, {})["signals"]
        scale = [s for s in sigs if s.key == "scale"][0]
        manager = [s for s in sigs if s.key == "manager"][0]
        self.assertEqual(scale.impact, -12)
        self.assertIn("清盘", scale.detail)
        self.assertLess(manager.impact, 0)
        self.assertIn("不是现任经理的业绩", manager.detail)

    def test_benchmark_name_in_excess_signal(self):
        inst = Instrument("000001", "OF", "fund")
        sigs = fund.analyze(inst, None, {"1y": {"excess_return": 0.12}}, {}, bench_name="恒生指数")["signals"]
        self.assertIn("跑赢恒生指数", sigs[0].detail)


class ScoreTest(unittest.TestCase):
    def test_clamp_and_missing_dimensions(self):
        sigs = [Signal("a", "a", "trend", 80, "", "x"), Signal("b", "b", "momentum", -80, "", "y")]
        out = scoring.score("index", sigs, 500)
        dims = {d["key"]: d for d in out["dimensions"]}
        self.assertEqual(dims["trend"]["score"], scoring.SCORE_MAX)
        self.assertEqual(dims["momentum"]["score"], scoring.SCORE_MIN)
        self.assertIsNone(dims["risk"]["score"])
        expected = (95 * 0.4 + 5 * 0.3) / 0.7
        self.assertAlmostEqual(out["composite"], round(expected, 1))
        self.assertEqual(out["confidence"], "中")

    def test_rating_thresholds(self):
        self.assertEqual([scoring.rating_for(x) for x in (80, 60, 50, 35, 20)], ["Buy", "Overweight", "Hold", "Underweight", "Sell"])

    def test_every_scored_dimension_has_evidence(self):
        for md in (stock_md(), fund_md()):
            r = report.build(md)
            for d in r["scores"]["dimensions"]:
                if d["score"] is not None:
                    self.assertTrue(d["evidence"], f"{d['label']} 有分数但没有依据")
                    self.assertAlmostEqual(min(95, max(5, 50 + sum(e["impact"] for e in d["evidence"]))), d["score"])

    def test_low_data_lowers_confidence(self):
        inst = symbols.parse("510300")
        md = MarketData(inst, walk(60, seed=3), symbols.CSI300, walk(60, seed=4), fetched_at="x")
        self.assertEqual(report.build(md)["scores"]["confidence"], "低")


class ReportTest(unittest.TestCase):
    def test_stock_report_shape(self):
        r = report.build(stock_md())
        self.assertEqual(r["kind"], "stock")
        self.assertEqual(len(r["chart"]["dates"]), len(r["chart"]["close"]))
        self.assertEqual(len(r["chart"]["ma20"]), len(r["chart"]["dates"]))
        self.assertIn("1y", r["metrics"])
        self.assertIsNotNone(r["fundamentals"])
        self.assertIn("量化综合评分", r["summary"])
        md_text = report.to_markdown(r)
        self.assertIn("维度评分", md_text)
        self.assertIn("不构成任何投资建议", md_text)

    def test_fund_report_uses_nav(self):
        r = report.build(fund_md())
        self.assertEqual(r["kind"], "fund")
        self.assertTrue(r["is_nav"])
        self.assertEqual({d["key"] for d in r["scores"]["dimensions"]}, {"performance", "risk_control", "efficiency", "stability", "trend"})
        self.assertIsNotNone(r["fund"]["profile"])

    def test_index_unit(self):
        md = MarketData(symbols.parse("沪深300"), walk(300, 3800, seed=2), symbols.CSI300, [], fetched_at="x")
        self.assertEqual(report.build(md)["currency_label"], "点")


if __name__ == "__main__":
    unittest.main()
