import unittest

from helpers import DECISION_REPLIES, FakeLLM, line_bars, stock_md
from agents.pipeline import DeepOptions, Pipeline
from market.models import Bar
from quant import report
from store import Store, direction_hit, outcome


class StoreTest(unittest.TestCase):
    def test_roundtrip(self):
        rep = report.build(stock_md())
        res = Pipeline(FakeLLM("q", DECISION_REPLIES), FakeLLM("d", DECISION_REPLIES), lambda e: None).run(rep, DeepOptions())
        s = Store(None)
        self.addCleanup(s.close)
        rid = s.save(res, rep)
        rows = s.list()
        self.assertEqual(rows[0]["id"], rid)
        self.assertEqual((rows[0]["rating"], rows[0]["rating_label"], rows[0]["inst_key"]), ("Buy", "买入", "SH:600519"))
        item = s.get(rid)
        self.assertNotIn("chart", item["report"], "图表序列不入库")
        self.assertEqual(item["result"]["final"]["rating"], "Buy")
        self.assertEqual(len(s.list(inst_key="SH:600519")), 1)
        self.assertEqual(s.list(inst_key="SZ:000001"), [])
        self.assertTrue(s.delete(rid))
        self.assertIsNone(s.get(rid))


class OutcomeTest(unittest.TestCase):
    def test_return_from_analysis_close_to_latest(self):
        bars = line_bars([100, 102, 104, 110, 99])
        o = outcome(bars[1].date, bars)
        self.assertAlmostEqual(o["return"], 99 / 102 - 1)
        self.assertEqual((o["days"], o["entry_date"]), (3, bars[1].date))

    def test_excess_against_benchmark(self):
        bars = line_bars([100, 110, 121])
        bench = line_bars([10, 10.5, 11])
        o = outcome(bars[0].date, bars, bench)
        self.assertAlmostEqual(o["benchmark_return"], 0.1)
        self.assertAlmostEqual(o["excess"], 0.21 - 0.1)

    def test_dividend_inside_window(self):
        bars = [Bar("2026-10-26", 1.0, 1.0, 1.0, 1.0, adj=1.0), Bar("2026-10-27", 0.9, 0.9, 0.9, 0.9, adj=1.02)]
        self.assertAlmostEqual(outcome("2026-10-26", bars)["return"], 0.02)

    def test_nothing_after_analysis(self):
        bars = line_bars([1, 2, 3])
        self.assertIsNone(outcome(bars[-1].date, bars)["return"])

    def test_direction_hit(self):
        self.assertTrue(direction_hit("Buy", 0.03))
        self.assertFalse(direction_hit("Overweight", -0.01))
        self.assertTrue(direction_hit("Sell", -0.02))
        self.assertIsNone(direction_hit("Hold", 0.05))
        self.assertIsNone(direction_hit("REVIEW", 0.05))
        self.assertIsNone(direction_hit("Buy", None))


if __name__ == "__main__":
    unittest.main()
