"""农历（夏历）转换。

紫微斗数的地基不是节气，而是**农历月与农历日**——命宫由生月生时定位，
紫微星由五行局与生日定位。八字那套「以节换月」的口径在这里完全用不上，
必须真的把公历换算成农历。

农历是定朔定气历，两条规则决定一切：

1. **月首为朔**：日月合朔（视黄经相等）那一天为初一，与月相观测一致。
2. **冬至必在十一月**；相邻两个十一月之间若含十三个朔望月，则其中第一个
   不含中气的月为闰月。

市面上多数程序用 1900–2100 年的压缩查表（那串 `lunarInfo` 魔法数组），
表外年份直接失效，且 2033 年闰十一月这类罕见排法在不少表里就是错的。
这里直接算：太阳视黄经复用 bazi.astro，月亮视黄经用 ELP2000-82 截断级数，
精度约 10 角秒，折合朔时误差约 20 秒——离「跨过午夜差一天」还有四个数量级。

参考：Jean Meeus, *Astronomical Algorithms*, 2nd ed., ch. 47/49。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

# 天文层本就与命理流派无关，八字那边已经把太阳黄经、儒略日、ΔT 都算好了，
# 没有理由为紫微再写一份。
from bazi.astro import (
    SECONDS_PER_DAY,
    apparent_solar_longitude,
    delta_t,
    julian_day,
)
from bazi.ganzhi import BRANCHES, STEMS

__all__ = [
    "LunarDate", "lunar_date", "moon_apparent_longitude", "new_moon_jd",
    "spring_festival_jdn", "MONTH_NAMES", "DAY_NAMES", "SHICHEN_NAMES",
    "hour_branch_index", "format_lunar",
]

J2000 = 2451545.0

MONTH_NAMES = ("正", "二", "三", "四", "五", "六",
               "七", "八", "九", "十", "十一", "十二")

DAY_NAMES = (
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
)

SHICHEN_NAMES = tuple(b + "时" for b in BRANCHES)


# --------------------------------------------------------------------------
# 月亮视黄经：ELP2000-82 截断级数（Meeus 表 47.A 的 Σl 列）
#
# 每项为 (D, M, M', F, 系数)，贡献 系数 * E^|M| * sin(D·D + M·M + M'·M' + F·F)，
# 单位 1e-6 度。E 是地球轨道偏心率的世纪修正，只作用于含太阳平近点角的项。
# --------------------------------------------------------------------------

_MOON_TERMS = (
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314),
    (0, 0, 2, 0, 213618), (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332),
    (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066), (2, 0, 1, 0, 53322),
    (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528),
    (0, 0, 1, -2, 10980), (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034),
    (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888), (2, 1, 0, 0, -6766),
    (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036),
    (2, 0, 2, 0, 3994), (4, 0, 0, 0, 3861), (2, 0, -3, 0, 3665),
    (0, 1, -2, 0, -2689), (2, 0, -1, 2, -2602), (2, -1, -2, 0, 2390),
    (1, 0, 1, 0, -2348), (2, -2, 0, 0, 2236), (0, 1, 2, 0, -2120),
    (0, 2, 0, 0, -2069), (2, -2, -1, 0, 2048), (2, 0, 1, -2, -1773),
    (2, 0, 0, 2, -1595), (4, -1, -1, 0, 1215), (0, 0, 2, 2, -1110),
    (3, 0, -1, 0, -892), (2, 1, 1, 0, -810), (4, -1, -2, 0, 759),
    (0, 2, -1, 0, -713), (2, 2, -1, 0, -700), (2, 1, -2, 0, 691),
    (2, -1, 0, -2, 596), (4, 0, 1, 0, 549), (0, 0, 4, 0, 537),
    (4, -1, 0, 0, 520), (1, 0, -2, 0, -487), (2, 1, 0, -2, -399),
    (0, 0, 2, -2, -381), (1, 1, 1, 0, 351), (3, 0, -2, 0, -340),
    (4, 0, -3, 0, 330), (2, -1, 2, 0, 327), (0, 2, 1, 0, -323),
    (1, 1, -1, 0, 299), (2, 0, 3, 0, 294),
)


def moon_apparent_longitude(jde):
    """给定力学时儒略日，返回月亮视黄经（度，0–360）。

    截断到振幅 ≥ 294e-6 度的项，实测精度约 10 角秒。定朔只需要月日
    黄经之差过零的时刻，而两者相对角速度约 12.19°/日，10″ 折合 20 秒——
    离影响「朔落在哪一天」还差得远。
    """
    t = (jde - J2000) / 36525.0

    # 月亮平黄经
    lp = (218.3164477 + 481267.88123421 * t - 0.0015786 * t ** 2
          + t ** 3 / 538841.0 - t ** 4 / 65194000.0)
    # 日月平距角
    d = (297.8501921 + 445267.1114034 * t - 0.0018819 * t ** 2
         + t ** 3 / 545868.0 - t ** 4 / 113065000.0)
    # 太阳平近点角
    m = (357.5291092 + 35999.0502909 * t - 0.0001536 * t ** 2
         + t ** 3 / 24490000.0)
    # 月亮平近点角
    mp = (134.9633964 + 477198.8675055 * t + 0.0087414 * t ** 2
          + t ** 3 / 69699.0 - t ** 4 / 14712000.0)
    # 月亮升交点平角距
    f = (93.2720950 + 483202.0175233 * t - 0.0036539 * t ** 2
         - t ** 3 / 3526000.0 + t ** 4 / 863310000.0)

    # 金星（A1）、木星（A2）与地球扁率（A3）的摄动辐角
    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    a3 = 313.45 + 481266.484 * t

    # 地球轨道偏心率随时间减小，含太阳平近点角的项须按其幂次缩放
    e = 1.0 - 0.002516 * t - 0.0000074 * t ** 2

    total = 0.0
    for cd, cm, cmp_, cf, coeff in _MOON_TERMS:
        arg = math.radians(cd * d + cm * m + cmp_ * mp + cf * f)
        total += coeff * (e ** abs(cm)) * math.sin(arg)

    total += 3958.0 * math.sin(math.radians(a1))
    total += 1962.0 * math.sin(math.radians(lp - f))
    total += 318.0 * math.sin(math.radians(a2))
    # a3 只进入黄纬与视差项，对黄经无贡献；留着变量是为对照 Meeus 原文
    del a3

    # 章动黄经：日月黄经之差里它本会抵消，但单独取月黄经时仍需补上
    omega = math.radians(125.04452 - 1934.136261 * t)
    l_sun = math.radians(280.4665 + 36000.7698 * t)
    l_moon = math.radians(218.3165 + 481267.8813 * t)
    nutation = (
        -17.20 * math.sin(omega) - 1.32 * math.sin(2 * l_sun)
        - 0.23 * math.sin(2 * l_moon) + 0.21 * math.sin(2 * omega)
    ) / 3600.0

    return (lp + total / 1e6 + nutation) % 360.0


# --------------------------------------------------------------------------
# 定朔
# --------------------------------------------------------------------------

# 朔望月平均长度（Meeus 49.1）
SYNODIC_MONTH = 29.530588861


@lru_cache(maxsize=8192)
def new_moon_jd(k):
    """第 k 个朔的时刻，返回 UT 儒略日。k=0 对应 2000-01-06 的朔。

    先用 Meeus 49.1 的平朔作初值，再对「月黄经 − 日黄经」牛顿法求零点。
    平朔与定朔最多差约 0.6 日，而每次迭代把误差压掉一个数量级，
    五轮之内必然收敛到远优于秒级。
    """
    t = k / 1236.85
    jde = (2451550.09766 + SYNODIC_MONTH * k + 0.00015437 * t ** 2
           - 0.000000150 * t ** 3 + 0.00000000073 * t ** 4)

    for _ in range(12):
        # 月亮相对太阳的黄经差，归一到 (-180, 180]
        diff = (moon_apparent_longitude(jde) - apparent_solar_longitude(jde)
                + 180.0) % 360.0 - 180.0
        if abs(diff) < 1e-7:
            break
        # 月亮相对太阳日行约 13.176 − 0.985 = 12.19°
        jde -= diff / 12.190749
    return jde - delta_t(_rough_year(jde)) / SECONDS_PER_DAY


def _rough_year(jd):
    """儒略日 → 大致公历年。只用于取 ΔT，不必精确到日。"""
    return int(2000 + (jd - J2000) / 365.2425)


# --------------------------------------------------------------------------
# 日序：一切「哪一天」的判断都在本地民用日上做
#
# 农历的日界是当地子夜。中国自 1929 年起统一用东八区（东经 120°）定历，
# 所以默认 tz_offset=8。传别的时区即按该地子夜分日。
# --------------------------------------------------------------------------

def civil_jdn(jd_ut, tz_offset=8.0):
    """UT 儒略日 → 该时刻所在**本地民用日**的儒略日序（整数）。"""
    return int(math.floor(jd_ut + tz_offset / 24.0 + 0.5))


def date_jdn(year, month, day):
    """公历年月日 → 儒略日序。与 civil_jdn 同一尺度，可直接相减得天数。"""
    return int(julian_day(datetime(year, month, day, 12)))


def jdn_to_date(jdn):
    """儒略日序 → (年, 月, 日)。"""
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year, month, day


# --------------------------------------------------------------------------
# 中气与冬至
# --------------------------------------------------------------------------

# bazi.astro.solar_term_jd 以立春（视黄经 315°）为 0 号，此后每 15° 一个。
# 「气」落在奇数号上：1 雨水、3 春分 …… 21 冬至、23 大寒。置闰只看这十二个。
_MAJOR_TERM_INDICES = tuple(range(1, 24, 2))
_WINTER_SOLSTICE_INDEX = 21


@lru_cache(maxsize=4096)
def _term_jd(year, index):
    from bazi.astro import solar_term_jd
    return solar_term_jd(year, index)


@lru_cache(maxsize=1024)
def _winter_solstice_jdn(year, tz_offset):
    """该公历年冬至所在的本地民用日。"""
    return civil_jdn(_term_jd(year, _WINTER_SOLSTICE_INDEX), tz_offset)


@lru_cache(maxsize=1024)
def _major_term_jdns(year, tz_offset):
    """该公历年十二个中气所在的本地民用日，升序。"""
    return tuple(sorted(
        civil_jdn(_term_jd(year, i), tz_offset) for i in _MAJOR_TERM_INDICES
    ))


def _has_major_term(start_jdn, end_jdn, tz_offset):
    """[start, end) 这个朔望月里是否含中气。

    一个朔望月约 29.53 日，中气间隔约 30.44 日，所以偶尔会有整月无中气——
    那正是置闰的依据。
    """
    y0 = jdn_to_date(start_jdn)[0]
    for y in (y0 - 1, y0, y0 + 1):
        for jdn in _major_term_jdns(y, tz_offset):
            if start_jdn <= jdn < end_jdn:
                return True
    return False


# --------------------------------------------------------------------------
# 朔序号定位
# --------------------------------------------------------------------------

def _nm_jdn(k, tz_offset):
    return civil_jdn(new_moon_jd(k), tz_offset)


def _k_at_or_before(jdn, tz_offset):
    """含 jdn 这一天的朔望月，其朔的序号 k。"""
    k = int(math.floor((jdn - 2451550.1) / SYNODIC_MONTH))
    # 平朔与定朔的差最多约 0.6 日，最多挪一格就到位；循环是为绝对稳妥
    while _nm_jdn(k, tz_offset) > jdn:
        k -= 1
    while _nm_jdn(k + 1, tz_offset) <= jdn:
        k += 1
    return k


# --------------------------------------------------------------------------
# 公历 → 农历
# --------------------------------------------------------------------------

@dataclass
class LunarDate:
    """一个农历日期。

    year 是农历年（正月初一换年，与公历年可差一岁），不是「立春年」——
    紫微斗数主流以正月初一论年，这一点与八字的立春换年是两套口径。
    """
    year: int
    month: int            # 1–12
    day: int              # 1–30
    is_leap: bool         # 该月是否为闰月
    month_days: int       # 该月天数（29 或 30）
    jdn: int              # 对应公历日的儒略日序

    @property
    def month_name(self):
        return ("闰" if self.is_leap else "") + MONTH_NAMES[self.month - 1] + "月"

    @property
    def day_name(self):
        return DAY_NAMES[self.day - 1]

    @property
    def year_ganzhi(self):
        return STEMS[(self.year - 4) % 10] + BRANCHES[(self.year - 4) % 12]

    def __str__(self):
        return "{}年{}{}".format(self.year_ganzhi, self.month_name, self.day_name)


def lunar_date(year, month, day, tz_offset=8.0):
    """公历 → 农历。year/month/day 为**本地民用日期**。

    做法：先找出目标日之前最近的冬至，其所在朔望月即十一月；由该月起顺数
    到目标日所在的月，即得月序。若这个十一月到下个十一月之间有十三个朔望月，
    则第一个不含中气的月为闰月，其后各月月序整体退一位。
    """
    target = date_jdn(year, month, day)

    # 定基准冬至：目标日之前（含当日）最近的那一个
    ws_year = year
    ws = _winter_solstice_jdn(ws_year, tz_offset)
    if target < ws:
        ws_year -= 1
        ws = _winter_solstice_jdn(ws_year, tz_offset)

    k11 = _k_at_or_before(ws, tz_offset)                 # 十一月之朔
    k11_next = _k_at_or_before(
        _winter_solstice_jdn(ws_year + 1, tz_offset), tz_offset)

    # 闰月位置：自 k11 起算的偏移量。十一月本身必含冬至，故从偏移 1 起找
    leap_offset = None
    if k11_next - k11 == 13:
        for i in range(1, 13):
            lo = _nm_jdn(k11 + i, tz_offset)
            hi = _nm_jdn(k11 + i + 1, tz_offset)
            if not _has_major_term(lo, hi, tz_offset):
                leap_offset = i
                break

    k = _k_at_or_before(target, tz_offset)
    i = k - k11

    is_leap = leap_offset is not None and i == leap_offset
    # 闰月与其前一个月共用月序，故闰月及其后各月都退一位
    seq = 11 + i - (1 if leap_offset is not None and i >= leap_offset else 0)

    month_no = (seq - 1) % 12 + 1
    lunar_year = ws_year if seq <= 12 else ws_year + 1

    start = _nm_jdn(k, tz_offset)
    return LunarDate(
        year=lunar_year,
        month=month_no,
        day=target - start + 1,
        is_leap=is_leap,
        month_days=_nm_jdn(k + 1, tz_offset) - start,
        jdn=target,
    )


def spring_festival_jdn(lunar_year, tz_offset=8.0):
    """某农历年正月初一的儒略日序。主要供测试与年首校验使用。"""
    ws_year = lunar_year - 1
    k11 = _k_at_or_before(_winter_solstice_jdn(ws_year, tz_offset), tz_offset)
    k11_next = _k_at_or_before(
        _winter_solstice_jdn(ws_year + 1, tz_offset), tz_offset)

    leap_offset = None
    if k11_next - k11 == 13:
        for i in range(1, 13):
            lo = _nm_jdn(k11 + i, tz_offset)
            hi = _nm_jdn(k11 + i + 1, tz_offset)
            if not _has_major_term(lo, hi, tz_offset):
                leap_offset = i
                break

    # 正月即 seq == 13 的那个月
    for i in range(0, 14):
        seq = 11 + i - (1 if leap_offset is not None and i >= leap_offset else 0)
        leap_here = leap_offset is not None and i == leap_offset
        if seq == 13 and not leap_here:
            return _nm_jdn(k11 + i, tz_offset)
    raise ValueError("未能定位 {} 年正月初一".format(lunar_year))


# --------------------------------------------------------------------------
# 时辰
# --------------------------------------------------------------------------

def hour_branch_index(hour, minute=0):
    """时刻 → 时辰地支序号（0 = 子时）。

    子时跨午夜：23:00–00:59 同属子时。这与八字时柱同一口径。
    """
    return ((hour + 1) // 2) % 12


def format_lunar(ld):
    """农历日期的常用写法，如「甲辰年闰二月初三」。"""
    return str(ld)
