"""财富站测试：报告口径的硬约束 + 校准是否跑偏 + 接口冒烟。"""

import random
import statistics as st
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bazi.chart import build_chart as bazi_chart      # noqa: E402
from ziwei.chart import build_chart as ziwei_chart    # noqa: E402
from caifu import report                              # noqa: E402
from caifu.calibration import CDF                     # noqa: E402


def sample_reports(n, seed=11):
    rnd = random.Random(seed)
    for _ in range(n):
        y, m, d = rnd.randint(1955, 2008), rnd.randint(1, 12), rnd.randint(1, 28)
        h, mi = rnd.randint(0, 23), rnd.randint(0, 59)
        g = rnd.choice(("male", "female"))
        yield report.wealth_report(
            bazi_chart(y, m, d, h, mi, gender=g),
            ziwei_chart(y, m, d, h, mi, gender=g), 2026)


class TestReportRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = list(sample_reports(300))

    def test_scores_in_range(self):
        for r in self.reports:
            self.assertTrue(38 <= r["财富指数"] <= 96)
            self.assertTrue(1 <= r["胜过"] <= 99)
            for f in r["五力"].values():
                self.assertTrue(38 <= f["分数"] <= 96)

    def test_every_force_has_basis(self):
        for r in self.reports:
            for name, f in r["五力"].items():
                self.assertTrue(f["依据"], name)

    def test_low_score_gets_advice(self):
        """低于 52 分必须附带方向——只列问题不给出路是产品事故。"""
        for r in self.reports:
            for name, f in r["五力"].items():
                if f["分数"] < 52:
                    self.assertEqual(f["依据"][-1], report.ADVICE[name])

    def test_no_harsh_words(self):
        harsh = ("破财", "穷命", "败家", "克夫", "克妻")
        for r in self.reports[:60]:
            text = repr(r)
            for w in harsh:
                self.assertNotIn(w, text)

    def test_curve_has_one_peak_and_now(self):
        for r in self.reports:
            curve = r["一生财运"]
            self.assertEqual(sum(1 for s in curve if s.get("高峰")), 1)
            self.assertLessEqual(sum(1 for s in curve if s["当下"]), 1)
            for s in curve:
                self.assertTrue(40 <= s["指数"] <= 96)

    def test_year_stars(self):
        for r in self.reports:
            self.assertEqual(len(r["近年"]), 3)
            for y in r["近年"]:
                self.assertIn(y["星级"], (2, 3, 4, 5))


class TestCalibration(unittest.TestCase):
    """改了 report.py 的权重却没重跑 tools/calibrate_caifu.py，这里会报警。"""

    def test_cdf_monotonic(self):
        self.assertEqual(len(CDF), 96 - 38 + 1)
        self.assertEqual(CDF, sorted(CDF))

    def test_index_distribution(self):
        idx = [r["财富指数"] for r in sample_reports(400, seed=99)]
        self.assertAlmostEqual(st.median(idx), 68, delta=3)
        self.assertAlmostEqual(st.pstdev(idx), 12, delta=2.5)

    def test_tier_shares(self):
        """五品的实际占比应接近设计值 5/15/25/30/25。"""
        tiers = [r["品阶"]["品阶"] for r in sample_reports(400, seed=5)]
        share = lambda k: tiers.count(k) / len(tiers)   # noqa: E731
        self.assertLess(share("一品"), 0.10)
        self.assertGreater(share("四品"), 0.18)
        self.assertGreater(share("五品"), 0.15)


class TestApi(unittest.TestCase):
    def test_wealth_endpoint(self):
        try:
            from fastapi.testclient import TestClient
            from caifu.app import app
        except (ImportError, RuntimeError) as exc:   # httpx 未装时跳过
            self.skipTest(str(exc))
        c = TestClient(app)
        r = c.post("/api/wealth", json={"year": 1990, "month": 6, "day": 15,
                                        "hour": 10, "minute": 30})
        self.assertEqual(r.status_code, 200)
        self.assertIn("财富指数", r.json()["report"])
        self.assertEqual(c.get("/").status_code, 200)
        self.assertEqual(c.get("/shared/places.js").status_code, 200)
        self.assertEqual(c.get("/shared/app.js").status_code, 404)


if __name__ == "__main__":
    unittest.main()
