import math
import unittest
from datetime import date

from helpers import line_bars, walk
from market.models import Bar
from quant import metrics


class ReturnsTest(unittest.TestCase):
    def test_calendar_lookback_and_insufficient_history(self):
        bars = line_bars([100 + i for i in range(300)])
        r = metrics.period_returns(bars)
        self.assertIsNotNone(r["1y"])
        self.assertIsNone(r["3y"], "历史不足三年时不能给出近三年收益")
        self.assertAlmostEqual(r["all"], bars[-1].close / bars[0].close - 1)
        start = metrics.bar_on_or_before(bars, date.fromisoformat(bars[-1].date).replace(year=date.fromisoformat(bars[-1].date).year - 1))
        self.assertAlmostEqual(r["1y"], bars[-1].close / start.close - 1)

    def test_ytd_uses_previous_year_end(self):
        bars = line_bars([100 + i for i in range(400)])
        r = metrics.period_returns(bars)
        end = date.fromisoformat(bars[-1].date)
        prev = metrics.bar_on_or_before(bars, date(end.year - 1, 12, 31))
        self.assertAlmostEqual(r["ytd"], bars[-1].close / prev.close - 1)

    def test_dividend_adjusted_returns(self):
        # 单位净值在分红日从 1.10 跳到 1.00，复权净值连续：收益不应被算成亏损
        bars = [Bar(d, c, c, c, c, adj=a) for d, c, a in (
            ("2026-10-26", 1.00, 1.00), ("2026-10-27", 1.10, 1.10), ("2026-10-28", 1.00, 1.10), ("2026-10-29", 1.01, 1.111))]
        r = metrics.period_returns(bars)
        self.assertAlmostEqual(r["all"], 0.111)


class RiskTest(unittest.TestCase):
    def test_drawdown_dates_and_recovery(self):
        bars = line_bars([100, 120, 90, 60, 80, 125, 110])
        dd = metrics.drawdown(bars)
        self.assertAlmostEqual(dd["max_drawdown"], 60 / 120 - 1)
        self.assertEqual(dd["peak_date"], bars[1].date)
        self.assertEqual(dd["trough_date"], bars[3].date)
        self.assertEqual(dd["recover_date"], bars[5].date)
        self.assertAlmostEqual(dd["current_drawdown"], 110 / 125 - 1)

    def test_risk_metrics_signs(self):
        up = walk(300, drift=0.002, vol=0.005, seed=2)
        m = metrics.risk_metrics(up, rf=0.02)
        self.assertGreater(m["sharpe"], 1)
        self.assertGreater(m["cagr"], 0)
        self.assertLessEqual(m["max_drawdown"], 0)
        self.assertTrue(0 <= m["win_rate"] <= 1)
        self.assertEqual(metrics.risk_metrics(up[:10]), {})

    def test_no_annualizing_short_windows(self):
        self.assertIsNone(metrics.risk_metrics(walk(40, seed=4))["cagr"])

    def test_beta_of_series_with_itself(self):
        bars = walk(300, seed=8)
        rel = metrics.relative_metrics(bars, bars)
        self.assertAlmostEqual(rel["beta"], 1.0)
        self.assertAlmostEqual(rel["correlation"], 1.0)
        self.assertAlmostEqual(rel["excess_return"], 0.0)

    def test_beta_scales_with_leverage(self):
        bench = walk(300, seed=8)
        lev = [Bar(b.date, 0, 0, 0, 0) for b in bench]
        level = 100.0
        for i, b in enumerate(bench):
            if i:
                level *= 1 + 2 * (b.close / bench[i - 1].close - 1)
            lev[i] = Bar(b.date, level, level, level, level)
        self.assertAlmostEqual(metrics.relative_metrics(lev, bench)["beta"], 2.0, places=6)

    def test_windows_respect_history_length(self):
        bars = walk(400, seed=9)            # 约 1.6 年
        w = metrics.all_windows(bars, [], rf=0.02)
        self.assertIn("1y", w)
        self.assertNotIn("3y", w)
        self.assertIn("all", w)
        start = date.fromisoformat(w["1y"]["start"])
        self.assertLessEqual((date.fromisoformat(w["1y"]["end"]) - start).days, 368)

    def test_periods_per_year_matches_calendar(self):
        self.assertTrue(250 <= metrics.periods_per_year(walk(600, seed=1)) <= 262)

    def test_monthly_returns(self):
        bars = line_bars([100 * math.exp(0.001 * i) for i in range(120)])
        months = metrics.monthly_returns(bars)
        self.assertTrue(all(m["return"] > 0 for m in months))


if __name__ == "__main__":
    unittest.main()
