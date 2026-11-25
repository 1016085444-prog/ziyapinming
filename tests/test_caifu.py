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


class TestCodes(unittest.TestCase):
    SECRET = "test-secret"

    def setUp(self):
        import tempfile
        from caifu import codes
        self.codes = codes
        self.tmp = tempfile.TemporaryDirectory()
        self.store = codes.SQLiteStore(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sign_and_verify(self):
        c = self.codes
        code = c.make_code(self.SECRET)
        self.assertTrue(c.is_valid(self.SECRET, code))
        self.assertTrue(c.is_valid(self.SECRET, code.lower().replace("-", " ")))
        self.assertFalse(c.is_valid("another-secret", code))
        forged = code[:-1] + ("2" if code[-1] != "2" else "3")
        self.assertFalse(c.is_valid(self.SECRET, forged))

    def test_one_code_one_birthday(self):
        c, s = self.codes, self.store
        code = c.make_code(self.SECRET)
        self.assertEqual(c.redeem(s, self.SECRET, code, 1990, 6, 15), "bound")
        # 同一生日可以反复测（改时辰、出生地都不影响，那些不参与绑定）
        self.assertEqual(c.redeem(s, self.SECRET, code, 1990, 6, 15), "again")
        with self.assertRaises(c.CodeError):
            c.redeem(s, self.SECRET, code, 1991, 6, 15)
        # 店主重置后可重新绑定
        s.reset(c.normalize(code))
        self.assertEqual(c.redeem(s, self.SECRET, code, 1991, 6, 15), "bound")

    def test_bad_codes(self):
        c = self.codes
        for bad in ("", "1234", "AAAA-BBBB-CCCC"):
            with self.assertRaises(c.CodeError):
                c.redeem(self.store, self.SECRET, bad, 1990, 1, 1)

    def test_no_birthday_stored(self):
        """库里只有摘要，查不到生日原文——「生辰不留存」的承诺。"""
        import sqlite3
        c = self.codes
        code = c.make_code(self.SECRET)
        c.redeem(self.store, self.SECRET, code, 1990, 6, 15)
        dump = repr(sqlite3.connect(self.store.path).execute(
            "SELECT * FROM caifu_binding").fetchall())
        self.assertNotIn("1990", dump)

    def test_concurrent_bind_is_atomic(self):
        """两个人同时用同一个码、填不同生日，只能有一个成功。"""
        import threading
        c = self.codes
        code = c.make_code(self.SECRET)
        results = []

        def go(y):
            try:
                results.append(c.redeem(self.store, self.SECRET, code, y, 1, 1))
            except c.CodeError:
                results.append("rejected")

        ts = [threading.Thread(target=go, args=(1980 + i,)) for i in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(results.count("bound"), 1)
        self.assertEqual(results.count("rejected"), 7)


class TestApi(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            import caifu.app as appmod
        except (ImportError, RuntimeError) as exc:   # httpx 未装时跳过
            self.skipTest(str(exc))
        import tempfile
        from caifu import codes, config
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (config.CODE_SECRET, config.ADMIN_KEY, config.OPEN_ACCESS,
                      config.MYSQL_URL, appmod._store)
        config.CODE_SECRET, config.ADMIN_KEY = "s", "admin"
        config.OPEN_ACCESS, config.MYSQL_URL = False, ""
        appmod._store = codes.SQLiteStore(Path(self.tmp.name) / "t.db")
        self.config, self.appmod, self.codes = config, appmod, codes
        self.c = TestClient(appmod.app)

    def tearDown(self):
        (self.config.CODE_SECRET, self.config.ADMIN_KEY, self.config.OPEN_ACCESS,
         self.config.MYSQL_URL, self.appmod._store) = self.saved
        self.tmp.cleanup()

    BIRTH = {"year": 1990, "month": 6, "day": 15, "hour": 10, "minute": 30}

    def test_pages(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/admin").status_code, 200)
        self.assertEqual(self.c.get("/shared/places.js").status_code, 200)
        self.assertEqual(self.c.get("/shared/app.js").status_code, 404)

    def test_wealth_needs_code(self):
        self.assertEqual(self.c.post("/api/wealth", json=self.BIRTH).status_code, 403)
        code = self.codes.make_code("s")
        r = self.c.post("/api/wealth", json=dict(self.BIRTH, code=code))
        self.assertEqual(r.status_code, 200)
        self.assertIn("财富指数", r.json()["report"])
        r = self.c.post("/api/wealth", json=dict(self.BIRTH, year=1991, code=code))
        self.assertEqual(r.status_code, 403)

    def test_invalid_date_does_not_burn_code(self):
        code = self.codes.make_code("s")
        r = self.c.post("/api/wealth", json=dict(self.BIRTH, month=2, day=30, code=code))
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/wealth", json=dict(self.BIRTH, code=code))
        self.assertEqual(r.status_code, 200)

    def test_missing_secret_fails_closed(self):
        """忘了配密钥时整站拒绝测算，而不是变成人人免费。"""
        self.config.CODE_SECRET = ""
        r = self.c.post("/api/wealth", json=dict(self.BIRTH, code="X"))
        self.assertEqual(r.status_code, 503)

    def test_admin(self):
        self.assertEqual(self.c.post("/api/admin/codes", json={"key": "no"}).status_code, 401)
        r = self.c.post("/api/admin/codes", json={"key": "admin", "count": 3})
        made = r.json()["codes"]
        self.assertEqual(len(made), 3)
        self.c.post("/api/wealth", json=dict(self.BIRTH, code=made[0]))
        look = self.c.post("/api/admin/lookup", json={"key": "admin", "code": made[0]}).json()
        self.assertTrue(look["bound"])
        self.c.post("/api/admin/reset", json={"key": "admin", "code": made[0]})
        look = self.c.post("/api/admin/lookup", json={"key": "admin", "code": made[0]}).json()
        self.assertFalse(look["bound"])


if __name__ == "__main__":
    unittest.main()
