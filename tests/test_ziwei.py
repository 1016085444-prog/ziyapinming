"""紫微斗数排盘正确性测试。

重点覆盖三类最容易出错的地方：

1. **农历换算**。紫微以农历月定命宫、以农历日安紫微，所以农历错一天，
   满盘皆错。这是全系统最脆弱的一环，测得最重。
2. **安星表**。紫微星表拿传世的五局三十日全表逐格对；十四主星的两系
   位移与紫府对称性用结构不变量锁住。
3. **流派选项**。换年点、闰月归属、晚子时这三处各有两派，必须确认切换
   真的改变结果，而不是写了个开关但没接上。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bazi.chart import build_chart as bazi_chart                  # noqa: E402
from bazi.ganzhi import BRANCHES, nayin                           # noqa: E402
from ziwei.chart import build_chart                               # noqa: E402
from ziwei.lunar import (                                          # noqa: E402
    date_jdn, jdn_to_date, lunar_date, spring_festival_jdn,
)
from ziwei.stars import (                                          # noqa: E402
    BRIGHTNESS_RANK, MAJOR_STARS, PALACES, five_phase_ju,
    palace_label, palace_stem, tianfu_index, transformations,
    ziwei_index,
)


class TestLunarCalendar(unittest.TestCase):
    """农历换算。全系统的地基，错一天则满盘皆错。"""

    # 春节（正月初一）的公历日期。跨度取满 1900–2100，
    # 因为查表法的实现恰恰在表的两端失效。
    SPRING = {
        1900: (1900, 1, 31), 1912: (1912, 2, 18), 1949: (1949, 1, 29),
        1950: (1950, 2, 17), 1960: (1960, 1, 28), 1970: (1970, 2, 6),
        1976: (1976, 1, 31), 1980: (1980, 2, 16), 1984: (1984, 2, 2),
        1990: (1990, 1, 27), 2000: (2000, 2, 5), 2008: (2008, 2, 7),
        2010: (2010, 2, 14), 2020: (2020, 1, 25), 2023: (2023, 1, 22),
        2024: (2024, 2, 10), 2025: (2025, 1, 29), 2026: (2026, 2, 17),
        2030: (2030, 2, 3), 2033: (2033, 1, 31), 2050: (2050, 1, 23),
        2100: (2100, 2, 9),
    }

    def test_spring_festival(self):
        for year, expected in sorted(self.SPRING.items()):
            got = jdn_to_date(spring_festival_jdn(year))
            self.assertEqual(got, expected, "{} 年正月初一".format(year))

    # 闰月年份与闰的是哪个月。2033 年闰十一月是著名的坑：
    # 不少压缩查表把它排成闰十月或闰十二月。
    LEAP = {
        1982: 4, 1984: 10, 1987: 6, 1990: 5, 1993: 3, 1995: 8, 1998: 5,
        2001: 4, 2004: 2, 2006: 7, 2009: 5, 2012: 4, 2014: 9, 2017: 6,
        2020: 4, 2023: 2, 2025: 6, 2028: 5, 2031: 3, 2033: 11, 2036: 6,
        2039: 5,
    }

    def test_leap_months(self):
        """扫过 1980–2040 的每一个农历月，闰月必须与史历一致。"""
        found = {}
        jdn = date_jdn(1980, 1, 1)
        end = date_jdn(2040, 12, 31)
        while jdn <= end:
            ld = lunar_date(*jdn_to_date(jdn))
            if ld.is_leap:
                found.setdefault(ld.year, ld.month)
            jdn += 15          # 闰月至少 29 天，半月一步不会漏
        self.assertEqual(found, self.LEAP)

    def test_no_gaps_across_two_centuries(self):
        """逐日推进，日序只能 +1 或归 1；归 1 时上月天数须为 29 或 30。

        这一条比逐个对照更有力：它不依赖任何外部历表，靠农历自身的
        内部一致性把「某一天算错」这类错误全部逼出来。
        """
        jdn = date_jdn(1901, 1, 1)
        end = date_jdn(2099, 12, 31)
        prev = None
        while jdn <= end:
            ld = lunar_date(*jdn_to_date(jdn))
            if prev is not None:
                if ld.day == 1:
                    self.assertIn(prev.day, (29, 30),
                                  "{} 之后跳到 {}".format(prev, ld))
                    self.assertEqual(prev.month_days, prev.day,
                                     "{} 的月长与末日不符".format(prev))
                else:
                    self.assertEqual(ld.day, prev.day + 1,
                                     "{} 之后跳到 {}".format(prev, ld))
            prev = ld
            jdn += 1

    def test_known_dates(self):
        for (y, m, d), expected in {
            (1949, 10, 1): "己丑年八月初十",
            (2024, 2, 10): "甲辰年正月初一",
            (2023, 3, 22): "癸卯年闰二月初一",
            (2033, 12, 22): "癸丑年闰十一月初一",
            (1990, 5, 20): "庚午年四月廿六",
        }.items():
            self.assertEqual(str(lunar_date(y, m, d)), expected)


class TestZiweiStarTable(unittest.TestCase):
    """安紫微星：与传世的「紫微星诀表」五局三十日逐格对照。

    表共 150 格，是整套安星规则里唯一没法用结构不变量自证的部分，
    所以只能硬对。对上了，十四主星的位置就全定了。
    """

    TABLE = {
        2: "丑寅寅卯卯辰辰巳巳午午未未申申酉酉戌戌亥亥子子丑丑寅寅卯卯辰",
        3: "辰丑寅巳寅卯午卯辰未辰巳申巳午酉午未戌未申亥申酉子酉戌丑戌亥",
        4: "亥辰丑寅子巳寅卯丑午卯辰寅未辰巳卯申巳午辰酉午未巳戌未申午亥",
        5: "午亥辰丑寅未子巳寅卯申丑午卯辰酉寅未辰巳戌卯申巳午亥辰酉午未",
        6: "酉午亥辰丑寅戌未子巳寅卯亥申丑午卯辰子酉寅未辰巳丑戌卯申巳午",
    }

    def test_full_table(self):
        for ju, row in self.TABLE.items():
            got = "".join(BRANCHES[ziwei_index(d, ju)] for d in range(1, 31))
            self.assertEqual(got, row, "{} 局".format(ju))

    def test_tianfu_symmetry(self):
        """紫微与天府以寅申为轴对称，故仅在寅、申二宫同度。"""
        same = [BRANCHES[i] for i in range(12) if tianfu_index(i) == i]
        self.assertEqual(same, ["寅", "申"])
        for i in range(12):
            self.assertEqual((i + tianfu_index(i)) % 12, 4)


class TestStarTables(unittest.TestCase):
    """静态表的完整性。表写残了不会报错，只会静静排错盘。"""

    def test_brightness_table_complete(self):
        from ziwei.stars import _BRIGHTNESS
        self.assertEqual(set(_BRIGHTNESS), set(MAJOR_STARS))
        for star, row in _BRIGHTNESS.items():
            self.assertEqual(len(row), 12, star)
            self.assertLessEqual(set(row), set(BRIGHTNESS_RANK), star)

    def test_sihua_table(self):
        """每个天干必有四化，且四颗星互不相同。"""
        from bazi.ganzhi import STEMS
        for stem in STEMS:
            t = transformations(stem)
            self.assertEqual(len(t), 4, stem)
            self.assertEqual(sorted(t.values()),
                             sorted(["化禄", "化权", "化科", "化忌"]), stem)

    def test_palace_stem_uses_wuhu_dun(self):
        """五虎遁自寅宫起排，绕回子丑两宫会与寅卯重复——传统排法如此。"""
        # 甲年：寅丙、卯丁 …… 戌甲、亥乙，子丙、丑丁
        self.assertEqual(
            "".join(palace_stem("甲", BRANCHES.index(b)) for b in
                    "寅卯辰巳午未申酉戌亥子丑"),
            "丙丁戊己庚辛壬癸甲乙丙丁")

    def test_palace_label_never_doubles(self):
        """只有「命宫」自带宫字，直接拼会得到「命宫宫」。"""
        self.assertEqual(palace_label("命宫"), "命宫")
        self.assertEqual(palace_label("夫妻"), "夫妻宫")

    def test_five_phase_ju_follows_nayin(self):
        for stem in "甲乙丙丁戊己庚辛壬癸":
            for idx in range(12):
                ju, name = five_phase_ju(stem, idx)
                element = nayin(palace_stem(stem, idx), BRANCHES[idx])[-1]
                self.assertEqual(name[0], element)
                self.assertEqual(ju, {"水": 2, "木": 3, "金": 4,
                                      "土": 5, "火": 6}[element])


class TestPalaceLayout(unittest.TestCase):
    """定命宫身宫。命宫错一位，整盘全错。"""

    def test_first_month_zi_hour(self):
        """正月子时命身同宫在寅——最经典的对照点。"""
        c = build_chart(2024, 2, 10, 0, gender="male",
                        use_true_solar_time=False, late_zi_shifts_day=False)
        self.assertEqual(str(c.lunar_text), "甲辰年正月初一")
        self.assertEqual(BRANCHES[c.life_index], "寅")
        self.assertEqual(BRANCHES[c.body_index], "寅")

    def test_life_and_body_are_mirrored(self):
        """命宫逆数、身宫顺数，故两者对生月之宫左右对称。"""
        for h in range(0, 24, 2):
            c = build_chart(2024, 3, 15, h, gender="female",
                            use_true_solar_time=False)
            month_palace = (2 + c.used_month - 1) % 12
            self.assertEqual((c.life_index + c.body_index) % 12,
                             (2 * month_palace) % 12)

    def test_palace_names_run_counterclockwise(self):
        """十二宫自命宫起逆行：命宫在寅则兄弟在丑、夫妻在子。"""
        c = build_chart(2024, 2, 10, 0, gender="male",
                        use_true_solar_time=False, late_zi_shifts_day=False)
        for i, name in enumerate(PALACES):
            idx = (c.life_index - i) % 12
            self.assertEqual(c.palaces[idx].name, name)


class TestChartInvariants(unittest.TestCase):
    """结构不变量。随机盘上必须恒成立——比逐盘对照更能扫出安星逻辑的错。"""

    SAMPLE = 300

    @classmethod
    def setUpClass(cls):
        import random
        rng = random.Random(20260730)
        cls.charts = [
            build_chart(
                rng.randint(1920, 2060), rng.randint(1, 12), rng.randint(1, 28),
                rng.randint(0, 23), rng.choice([0, 15, 30, 45]),
                gender=rng.choice(["male", "female"]),
                longitude=rng.choice([116.41, 121.47, 113.26, 104.07, 87.62]),
            )
            for _ in range(cls.SAMPLE)
        ]

    def test_each_major_star_appears_exactly_once(self):
        for c in self.charts:
            names = [s.name for p in c.palaces for s in p.stars]
            for star in MAJOR_STARS:
                self.assertEqual(names.count(star), 1,
                                 "{} 在 {} 出现 {} 次".format(
                                     star, c.lunar_text, names.count(star)))

    def test_twelve_palaces_all_present(self):
        for c in self.charts:
            self.assertEqual(sorted(p.name for p in c.palaces),
                             sorted(PALACES))

    def test_major_limits_tile_without_gaps(self):
        """十二步大限须自局数起、每宫十年、不重不漏。"""
        for c in self.charts:
            starts = sorted(p.limit_ages[0] for p in c.palaces)
            self.assertEqual(starts, [c.ju + 10 * i for i in range(12)])

    def test_minor_limits_cover_one_to_twelve(self):
        for c in self.charts:
            self.assertEqual(sorted(p.minor_age for p in c.palaces),
                             list(range(1, 13)))

    def test_empty_palaces_borrow_from_opposite(self):
        for c in self.charts:
            for p in c.palaces:
                if p.is_empty:
                    opposite = c.palace(p.index + 6)
                    self.assertEqual([s.name for s in p.borrowed],
                                     [s.name for s in opposite.majors])
                else:
                    self.assertEqual(p.borrowed, [])

    def test_yang_blade_flanks_lucun(self):
        """擎羊、陀罗永夹禄存左右——「羊陀夹」是禄存位置的必然结果。"""
        for c in self.charts:
            lu = c.star_palace("禄存").index
            self.assertEqual(c.star_palace("擎羊").index, (lu + 1) % 12)
            self.assertEqual(c.star_palace("陀罗").index, (lu - 1) % 12)

    def test_serialization_is_complete(self):
        """to_dict 不能漏字段：前端整张盘都靠它。"""
        for c in self.charts[:20]:
            d = c.to_dict()
            self.assertEqual(len(d["十二宫"]), 12)
            for p in d["十二宫"]:
                for key in ("宫名", "地支", "宫干支", "星曜", "借星",
                            "大限", "小限起", "长生十二神"):
                    self.assertIn(key, p)
            # 盘上出现的每颗有释义的星，释义表里都得有
            for p in d["十二宫"]:
                for s in p["星曜"]:
                    from ziwei.stars import STAR_MEANINGS
                    if s["名"] in STAR_MEANINGS:
                        self.assertIn(s["名"], d["星曜释义"])


class TestSchoolOptions(unittest.TestCase):
    """流派开关必须真的改变结果，否则等于写了个摆设。"""

    def test_year_boundary_matters_between_lichun_and_new_year(self):
        """2024 年立春 2/4、春节 2/10，其间出生者两派差一整年。"""
        kw = dict(gender="male", use_true_solar_time=False)
        lunar = build_chart(2024, 2, 6, 12, year_boundary="lunar", **kw)
        lichun = build_chart(2024, 2, 6, 12, year_boundary="lichun", **kw)
        self.assertEqual(lunar.year_gz, "癸卯")
        self.assertEqual(lichun.year_gz, "甲辰")

    def test_year_boundary_agrees_outside_the_gap(self):
        """立春与春节之外的日子，两派必须给同一个生年。"""
        kw = dict(gender="male", use_true_solar_time=False)
        for (y, m, d) in [(2024, 6, 1), (2023, 11, 20), (2000, 8, 8)]:
            a = build_chart(y, m, d, 12, year_boundary="lunar", **kw)
            b = build_chart(y, m, d, 12, year_boundary="lichun", **kw)
            self.assertEqual(a.year_gz, b.year_gz, "{}-{}-{}".format(y, m, d))

    def test_leap_month_rule_only_bites_in_leap_months(self):
        """非闰月生人，两个闰月选项必须给出完全相同的盘。"""
        kw = dict(gender="female", use_true_solar_time=False)
        a = build_chart(2024, 6, 1, 10, leap_month_rule="current", **kw)
        b = build_chart(2024, 6, 1, 10, leap_month_rule="split", **kw)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_leap_month_split_shifts_the_month(self):
        """2023 闰二月十六之后，split 派按三月定宫。"""
        kw = dict(gender="female", use_true_solar_time=False)
        # 2023-04-08 是闰二月十八
        ld = lunar_date(2023, 4, 8)
        self.assertTrue(ld.is_leap)
        self.assertEqual((ld.month, ld.day), (2, 18))

        cur = build_chart(2023, 4, 8, 10, leap_month_rule="current", **kw)
        spl = build_chart(2023, 4, 8, 10, leap_month_rule="split", **kw)
        self.assertEqual(cur.used_month, 2)
        self.assertEqual(spl.used_month, 3)
        self.assertNotEqual(cur.life_index, spl.life_index)

    def test_late_zi_shifts_the_lunar_day(self):
        """晚子时归次日会改农历日，而农历日决定紫微落哪一宫。

        紫微对这一项比八字敏感得多：八字只换日柱，紫微是整盘重排。
        """
        kw = dict(gender="male", use_true_solar_time=False)
        on = build_chart(1984, 2, 4, 23, 30, late_zi_shifts_day=True, **kw)
        off = build_chart(1984, 2, 4, 23, 30, late_zi_shifts_day=False, **kw)
        self.assertEqual(on.lunar_day, 4)
        self.assertEqual(off.lunar_day, 3)
        self.assertNotEqual(on.star_palace("紫微").index,
                            off.star_palace("紫微").index)
        # 时辰不受影响：23:30 两派都是子时
        self.assertEqual(on.hour_index, 0)
        self.assertEqual(off.hour_index, 0)


class TestSharedReckoning(unittest.TestCase):
    """两套系统必须把同一个生辰归正到同一个时刻。

    八字与紫微取用的历法完全不同，但「用户填的那个时间对应哪一刻」是同一个
    问题。若两边答案不同，同一个人的两张盘会落在不同的时辰上——这种不一致
    比单张盘算错更难排查，也更伤信任。
    """

    CASES = [
        (1990, 5, 20, 10, 30, 121.47),    # 夏令时期间
        (1984, 2, 4, 23, 30, 120.58),     # 立春 + 晚子时
        (2001, 7, 15, 6, 5, 87.62),       # 乌鲁木齐，真太阳时偏差近两小时
        (1966, 12, 31, 23, 59, 116.41),   # 跨年 + 晚子时
    ]

    def test_hour_branch_agrees(self):
        for y, m, d, h, mi, lon in self.CASES:
            bz = bazi_chart(y, m, d, h, mi, gender="male", longitude=lon)
            zw = build_chart(y, m, d, h, mi, gender="male", longitude=lon)
            self.assertEqual(
                bz.hour.branch, BRANCHES[zw.hour_index],
                "{}-{}-{} {}:{:02d} 两套系统时辰不一致".format(y, m, d, h, mi))

    def test_true_solar_time_agrees(self):
        for y, m, d, h, mi, lon in self.CASES:
            bz = bazi_chart(y, m, d, h, mi, gender="male", longitude=lon)
            zw = build_chart(y, m, d, h, mi, gender="male", longitude=lon)
            self.assertEqual(bz.true_solar_time, zw.true_solar_time)
            self.assertEqual(bz.input_time, zw.input_time)
            self.assertEqual(bz.dst_adjusted, zw.dst_adjusted)


class TestPatterns(unittest.TestCase):
    """格局判断。既不能人人都中，也不能永不命中。"""

    SAMPLE = 300

    @classmethod
    def setUpClass(cls):
        import collections
        import random
        from ziwei.analysis import patterns
        rng = random.Random(4242)
        cls.hits = collections.Counter()
        cls.per_chart = []
        for _ in range(cls.SAMPLE):
            c = build_chart(
                rng.randint(1930, 2040), rng.randint(1, 12), rng.randint(1, 28),
                rng.randint(0, 23), gender=rng.choice(["male", "female"]))
            got = patterns(c)
            cls.per_chart.append(len(got))
            for p in got:
                cls.hits[p["格名"]] += 1

    def test_pattern_density_is_readable(self):
        """平均每盘两到六个格：太少无话可说，太多等于没重点。"""
        avg = sum(self.per_chart) / len(self.per_chart)
        self.assertGreater(avg, 2.0, "格局太少（平均 {:.1f}）".format(avg))
        self.assertLess(avg, 6.0, "格局太多（平均 {:.1f}）".format(avg))

    def test_no_pattern_is_universal(self):
        """命中率逼近 100% 的格没有信息量，通常意味着条件写松了。"""
        for name, n in self.hits.items():
            rate = 100.0 * n / self.SAMPLE
            self.assertLess(rate, 75.0,
                            "{} 命中率 {:.0f}%，条件过松".format(name, rate))

    def test_kinds_are_not_dominated_by_warnings(self):
        """「考验」类不该压过「助力」类——本站不做恐惧营销。"""
        import collections
        from ziwei.analysis import patterns
        import random
        rng = random.Random(99)
        kinds = collections.Counter()
        for _ in range(200):
            c = build_chart(rng.randint(1930, 2040), rng.randint(1, 12),
                            rng.randint(1, 28), rng.randint(0, 23),
                            gender=rng.choice(["male", "female"]))
            for p in patterns(c):
                kinds[p["性质"]] += 1
        self.assertLess(kinds["考验"], kinds["助力"],
                        "考验类格局多于助力类：{}".format(dict(kinds)))


class TestZiweiScoring(unittest.TestCase):
    """六维评分的形状与尺度。"""

    SAMPLE = 240

    @classmethod
    def setUpClass(cls):
        import random
        from ziwei.scoring import DIMENSIONS, score_chart
        rng = random.Random(20260730)
        cls.dims = DIMENSIONS
        cls.cols = {d: [] for d in DIMENSIONS}
        for _ in range(cls.SAMPLE):
            c = build_chart(
                rng.randint(1955, 2010), rng.randint(1, 12), rng.randint(1, 28),
                rng.randint(0, 23), rng.choice([0, 15, 30, 45]),
                gender=rng.choice(["male", "female"]),
                longitude=rng.choice([116.41, 121.47, 113.26, 104.07, 87.62]),
            )
            r = score_chart(c)
            for d in DIMENSIONS:
                cls.cols[d].append(r["维度"][d]["分数"])

    def test_scores_stay_in_band(self):
        from ziwei.scoring import CEIL, FLOOR
        for d, col in self.cols.items():
            self.assertGreaterEqual(min(col), FLOOR, d)
            self.assertLessEqual(max(col), CEIL, d)

    def test_every_dimension_discriminates(self):
        """标准差过小说明这一维在给所有人打同样的分，等于没有这一维。"""
        import statistics as st
        for d, col in self.cols.items():
            self.assertGreater(st.pstdev(col), 7.0,
                               "{} 区分度不足（标准差 {:.1f}）".format(
                                   d, st.pstdev(col)))

    def test_dimensions_share_one_scale(self):
        """六维必须同尺度，否则雷达图会骗人：并排的两个 78 分含义不同。

        RAW_CALIBRATION 就是为消除各维原始散布的差异而存在的。动了任何
        规则权重都要重新测定那组常量，这条断言会在跑偏时报警。
        """
        import statistics as st
        meds = {d: st.median(col) for d, col in self.cols.items()}
        sds = {d: st.pstdev(col) for d, col in self.cols.items()}
        self.assertLess(max(meds.values()) - min(meds.values()), 6.0,
                        "各维中位数离散过大：{}".format(
                            {k: round(v, 1) for k, v in meds.items()}))
        self.assertLess(max(sds.values()) - min(sds.values()), 4.0,
                        "各维标准差离散过大：{}".format(
                            {k: round(v, 1) for k, v in sds.items()}))

    def test_low_score_rate_is_balanced(self):
        """没有哪一维该系统性地当「坏消息担当」。"""
        rates = {d: 100.0 * sum(1 for x in col if x < 52) / len(col)
                 for d, col in self.cols.items()}
        for d, rate in rates.items():
            self.assertLess(rate, 20.0, "{} 低分率过高（{:.1f}%）".format(d, rate))
        self.assertLess(max(rates.values()) - min(rates.values()), 12.0,
                        "各维低分率离散过大：{}".format(
                            {k: round(v, 1) for k, v in rates.items()}))

    def test_every_dimension_has_reasons(self):
        """分数必须带依据。没有依据的分数用户无从验证，也就无从相信。"""
        from ziwei.scoring import score_chart
        c = build_chart(1990, 5, 20, 10, 30, gender="female", longitude=121.47)
        r = score_chart(c)
        for d in self.dims:
            self.assertTrue(r["维度"][d]["依据"], d)
            for line in r["维度"][d]["依据"]:
                self.assertNotIn("宫宫", line, "宫名重复拼接：" + line)


class TestZiweiInquiry(unittest.TestCase):
    """待定论。转化引擎，但每条必须是真的两可。"""

    def test_always_offers_something(self):
        import random
        from ziwei.inquiry import MAX_QUESTIONS, open_questions
        rng = random.Random(11)
        for _ in range(200):
            c = build_chart(rng.randint(1930, 2030), rng.randint(1, 12),
                            rng.randint(1, 28), rng.randint(0, 23),
                            gender=rng.choice(["male", "female"]))
            qs = open_questions(c, 2026)
            self.assertGreaterEqual(len(qs), 2)
            self.assertLessEqual(len(qs), MAX_QUESTIONS)

    def test_each_item_is_three_parts(self):
        from ziwei.inquiry import open_questions
        c = build_chart(1990, 5, 20, 10, 30, gender="female", longitude=121.47)
        for q in open_questions(c, 2026):
            for key in ("标题", "问法", "事实", "两可", "问题"):
                self.assertTrue(q.get(key), key)
            self.assertTrue(q["问题"].endswith("？"), q["问题"])
            self.assertNotIn("宫宫", q["事实"] + q["问法"] + q["标题"])

    def test_no_fear_mongering(self):
        """不用恐惧话术。招来的是最焦虑最难伺候的客户，对靠转介绍的生意是负资产。"""
        import random
        from ziwei.inquiry import open_questions
        banned = ("凶险", "大凶", "血光", "灾祸", "破财", "克夫", "克妻", "短命")
        rng = random.Random(7)
        for _ in range(120):
            c = build_chart(rng.randint(1930, 2030), rng.randint(1, 12),
                            rng.randint(1, 28), rng.randint(0, 23),
                            gender=rng.choice(["male", "female"]))
            for q in open_questions(c, 2026):
                blob = "".join(q.values())
                for word in banned:
                    self.assertNotIn(word, blob, q["标题"])


class TestYearOutlook(unittest.TestCase):
    """流年。"""

    def test_current_year_lands_in_a_palace(self):
        from ziwei.analysis import year_outlook
        c = build_chart(1990, 5, 20, 10, 30, gender="female", longitude=121.47)
        r = year_outlook(c, 2026)
        self.assertEqual(r["流年干支"], "丙午")
        self.assertEqual(r["虚岁"], 2026 - 1990 + 1)
        self.assertIn(r["流年宫"], PALACES)
        self.assertIn(r["小限宫"], PALACES)
        self.assertEqual(len(r["流年四化"]), 4)
        self.assertNotIn("宫宫", r["所行大限"])

    def test_future_birth_has_no_limit_yet(self):
        """出生日期填在未来时不能炸——表单允许填到 2100 年。"""
        from ziwei.analysis import year_outlook
        c = build_chart(2090, 5, 20, 10, gender="male")
        r = year_outlook(c, 2026)
        self.assertEqual(r["所行大限"], "尚未入限")
        self.assertEqual(r["小限宫"], "—")
        self.assertEqual(r["大限主星"], [])


class TestRejectsBadInput(unittest.TestCase):
    def test_gender(self):
        with self.assertRaises(ValueError):
            build_chart(1990, 5, 20, 10, gender="x")

    def test_school_options(self):
        with self.assertRaises(ValueError):
            build_chart(1990, 5, 20, 10, year_boundary="x")
        with self.assertRaises(ValueError):
            build_chart(1990, 5, 20, 10, leap_month_rule="x")


if __name__ == "__main__":
    unittest.main()
