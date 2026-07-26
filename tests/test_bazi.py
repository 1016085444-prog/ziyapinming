"""排盘正确性测试。

重点覆盖三类最容易出错的边界：立春换年、节换月、子时换日，
外加真太阳时对时柱/日柱的实际影响。
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bazi.astro import jd_to_datetime, solar_term_jd          # noqa: E402
from bazi.chart import build_chart                            # noqa: E402
from bazi.ganzhi import (                                     # noqa: E402
    branch_relations, empty_branches, nayin, ten_god, twelve_stage,
)

CST = timezone(timedelta(hours=8))


def gz(chart):
    return " ".join(p.gz for p in chart.pillars)


class TestSolarTerms(unittest.TestCase):
    """节气时刻对照紫金山天文台/香港天文台公布值，容差 60 秒。"""

    CASES = {
        (2024, 0): "2024-02-04 16:26:53",    # 立春
        (2024, 3): "2024-03-20 11:06:12",    # 春分
        (2024, 9): "2024-06-21 04:50:46",    # 夏至
        (2023, 21): "2023-12-22 11:27:09",   # 冬至
        (2000, 0): "2000-02-04 20:40:34",    # 立春
        (1984, 0): "1984-02-04 23:19:22",    # 立春
    }

    def test_accuracy(self):
        for (year, idx), expected in self.CASES.items():
            got = jd_to_datetime(solar_term_jd(year, idx)).astimezone(CST)
            exp = datetime.strptime(expected, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
            err = abs((got - exp).total_seconds())
            self.assertLess(err, 60, "{}年第{}个节气误差 {:.0f} 秒".format(year, idx, err))


class TestKnownCharts(unittest.TestCase):
    """公开命例。均以当时当地视时论，故关闭时区推算之外的额外校正。"""

    def test_mao(self):
        c = build_chart(1893, 12, 26, 8, 0, gender="male",
                        longitude=112.9, use_true_solar_time=False)
        self.assertEqual(gz(c), "癸巳 甲子 丁酉 甲辰")

    def test_chiang(self):
        c = build_chart(1887, 10, 31, 12, 0, gender="male",
                        longitude=121.4, use_true_solar_time=False)
        self.assertEqual(gz(c), "丁亥 庚戌 己巳 庚午")

    def test_day_pillar_anchor(self):
        # 六十甲子日柱是连续循环，任一锚点错则全盘皆错
        c = build_chart(2000, 1, 1, 12, 0, use_true_solar_time=False)
        self.assertEqual(c.day.gz, "戊午")
        c = build_chart(1949, 10, 1, 12, 0, use_true_solar_time=False)
        self.assertEqual(c.day.gz, "甲子")


class TestBoundaries(unittest.TestCase):

    def test_lichun_switches_year(self):
        """2024 立春 = 02-04 16:26:53 北京时间，前后年柱必须不同。"""
        before = build_chart(2024, 2, 4, 16, 0, use_true_solar_time=False)
        after = build_chart(2024, 2, 4, 17, 0, use_true_solar_time=False)
        self.assertEqual(before.year.gz, "癸卯")   # 仍属 2023 年柱
        self.assertEqual(after.year.gz, "甲辰")
        # 月柱同步换：丑月 → 寅月
        self.assertEqual(before.month.branch, "丑")
        self.assertEqual(after.month.branch, "寅")

    def test_jie_switches_month(self):
        """惊蛰换卯月：2024 惊蛰 = 03-05 10:22 北京时间。"""
        before = build_chart(2024, 3, 5, 9, 0, use_true_solar_time=False)
        after = build_chart(2024, 3, 5, 11, 0, use_true_solar_time=False)
        self.assertEqual(before.month.branch, "寅")
        self.assertEqual(after.month.branch, "卯")
        self.assertEqual(before.year.gz, after.year.gz)  # 年柱不受影响

    def test_late_zi_day_switch(self):
        """23:00 后：子正换日则进次日，夜半换日则仍属当日。"""
        shifted = build_chart(2024, 3, 15, 23, 30, use_true_solar_time=False,
                              late_zi_shifts_day=True)
        kept = build_chart(2024, 3, 15, 23, 30, use_true_solar_time=False,
                           late_zi_shifts_day=False)
        next_day = build_chart(2024, 3, 16, 12, 0, use_true_solar_time=False)
        same_day = build_chart(2024, 3, 15, 12, 0, use_true_solar_time=False)

        self.assertEqual(shifted.day.gz, next_day.day.gz)
        self.assertEqual(kept.day.gz, same_day.day.gz)
        # 两种流派时支都是子
        self.assertEqual(shifted.hour.branch, "子")
        self.assertEqual(kept.hour.branch, "子")

    def test_true_solar_time_shifts_hour(self):
        """乌鲁木齐用北京时间，经度时差约 -2 小时10分，足以改时柱。"""
        raw = build_chart(2024, 6, 1, 1, 0, longitude=87.62,
                          use_true_solar_time=False)
        adj = build_chart(2024, 6, 1, 1, 0, longitude=87.62,
                          use_true_solar_time=True)
        self.assertEqual(raw.hour.branch, "丑")
        self.assertEqual(adj.hour.branch, "亥")          # 退回前一日亥时
        self.assertNotEqual(raw.day.gz, adj.day.gz)      # 日柱也退一天

    def test_true_solar_time_noop_at_meridian(self):
        """正好在 120°E 且均时差极小的日子，校正量应小于一分钟量级。"""
        c = build_chart(2024, 4, 15, 12, 0, longitude=120.0)
        delta = abs((c.true_solar_time - c.solar_time).total_seconds())
        self.assertLess(delta, 120)


class TestLuckPillars(unittest.TestCase):

    def test_direction_yin_male_reverse(self):
        """癸年（阴）男 → 逆排，月柱甲子之后为癸亥、壬戌…"""
        c = build_chart(1893, 12, 26, 8, 0, gender="male",
                        longitude=112.9, use_true_solar_time=False)
        self.assertFalse(c.luck_forward)
        self.assertEqual([lp.gz for lp in c.luck_pillars[:4]],
                         ["癸亥", "壬戌", "辛酉", "庚申"])

    def test_direction_flips_with_gender(self):
        c_m = build_chart(1990, 5, 20, 10, 0, gender="male",
                          use_true_solar_time=False)
        c_f = build_chart(1990, 5, 20, 10, 0, gender="female",
                          use_true_solar_time=False)
        self.assertNotEqual(c_m.luck_forward, c_f.luck_forward)
        self.assertEqual(c_m.pillars[1].gz, c_f.pillars[1].gz)  # 命盘相同

    def test_start_age_within_range(self):
        """起运在 0–10 虚岁之间：节气间隔最多约 31 天，31/3 ≈ 10.3。"""
        for month in range(1, 13):
            c = build_chart(1995, month, 15, 9, 0, use_true_solar_time=False)
            self.assertGreaterEqual(c.luck_start_age, 0)
            self.assertLess(c.luck_start_age, 11)

    def test_luck_years_are_contiguous(self):
        c = build_chart(1990, 5, 20, 10, 0, gender="male",
                        use_true_solar_time=False)
        for a, b in zip(c.luck_pillars, c.luck_pillars[1:]):
            self.assertEqual(b.start_year, a.end_year + 1)


class TestGanzhiPrimitives(unittest.TestCase):

    def test_ten_god(self):
        self.assertEqual(ten_god("甲", "甲"), "比肩")
        self.assertEqual(ten_god("甲", "乙"), "劫财")
        self.assertEqual(ten_god("甲", "丙"), "食神")   # 木生火，同为阳
        self.assertEqual(ten_god("甲", "丁"), "伤官")
        self.assertEqual(ten_god("甲", "戊"), "偏财")   # 木克土，同为阳
        self.assertEqual(ten_god("甲", "己"), "正财")
        self.assertEqual(ten_god("甲", "庚"), "七杀")   # 金克木，同为阳
        self.assertEqual(ten_god("甲", "辛"), "正官")
        self.assertEqual(ten_god("甲", "壬"), "偏印")   # 水生木，同为阳
        self.assertEqual(ten_god("甲", "癸"), "正印")

    def test_nayin(self):
        self.assertEqual(nayin("甲", "子"), "海中金")
        self.assertEqual(nayin("乙", "丑"), "海中金")
        self.assertEqual(nayin("丙", "寅"), "炉中火")
        self.assertEqual(nayin("癸", "亥"), "大海水")

    def test_twelve_stage(self):
        self.assertEqual(twelve_stage("甲", "亥"), "长生")   # 阳干顺行
        self.assertEqual(twelve_stage("甲", "子"), "沐浴")
        self.assertEqual(twelve_stage("甲", "午"), "死")
        self.assertEqual(twelve_stage("乙", "午"), "长生")   # 阴干逆行
        self.assertEqual(twelve_stage("乙", "巳"), "沐浴")

    def test_empty_branches(self):
        # 甲子旬（甲子起）空戌亥
        self.assertEqual(empty_branches("甲", "子"), ("戌", "亥"))
        self.assertEqual(empty_branches("癸", "酉"), ("戌", "亥"))
        # 甲戌旬空申酉
        self.assertEqual(empty_branches("甲", "戌"), ("申", "酉"))

    def test_branch_relations(self):
        rel = branch_relations(["申", "子", "辰", "午"])
        self.assertIn("申子辰合水局", rel.get("三合", []))
        self.assertIn("子午相冲", rel.get("六冲", []))

        rel2 = branch_relations(["寅", "巳", "申", "亥"])
        self.assertIn("寅巳申三刑", rel2.get("相刑", []))
        self.assertIn("寅亥合木", rel2.get("六合", []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
