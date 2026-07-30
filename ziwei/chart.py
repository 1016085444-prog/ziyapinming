"""紫微斗数排盘：把一个公历出生时刻映射为完整的十二宫命盘。

排盘链条只有五步，但每一步都有廉价程序做错的地方：

1. **农历换算**：紫微以农历月定命宫、以农历日安紫微。查表法在表外年份
   直接失效，闰十一月这类罕见排法常出错。见 lunar.py。
2. **定命宫身宫**：寅宫起正月顺数至生月，再自该宫起子时逆数至生时。
   闰月的归属有流派分歧，此处可选。
3. **定五行局**：命宫干支取纳音，局数既定紫微落点，也定大限起运岁数。
   命宫错一位，整盘全错。
4. **安星**：十四主星由紫微天府两个锚点串出，其余按生年干、生年支、
   农历月、农历日、生时五组口诀分别落宫。
5. **大限小限**：阳男阴女顺行、阴男阳女逆行。

与八字共用的部分（夏令时回退、真太阳时校正）直接调 bazi.chart.reckon_time，
保证同一个人的两张盘落在同一个时辰上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from bazi.astro import julian_day, solar_term_jd
from bazi.chart import DEFAULT_LONGITUDE, DEFAULT_TZ, reckon_time
from bazi.ganzhi import BRANCHES, STEMS, STEM_YANG, ZODIAC

from .lunar import (
    MONTH_NAMES, SHICHEN_NAMES, hour_branch_index, lunar_date,
)
from .stars import (
    LUCKY_STARS, MAJOR_STARS, MALEFIC_STARS, PALACES, PALACE_MEANINGS,
    STAR_MEANINGS, TRIANGLE_OFFSETS,
    body_lord, boshi_cycle, brightness, changsheng_cycle, day_stars,
    five_phase_ju, hour_stars, jiangqian_cycle, life_lord,
    major_star_positions, month_stars, palace_stem, suiqian_cycle,
    transformations, year_branch_stars, year_stem_stars,
)

__all__ = ["Star", "Palace", "ZiweiChart", "build_chart", "MINOR_LIMIT_START"]

# 小限起宫：「寅午戌人从辰起，申子辰人从戌起，
#            巳酉丑人从未起，亥卯未人从丑起」
MINOR_LIMIT_START = {
    "寅午戌": "辰", "申子辰": "戌", "巳酉丑": "未", "亥卯未": "丑",
}

# 主星只有十四颗，一宫最多容三四颗，故十二宫里必有空宫。
# 空宫不是「什么都没有」，传统作法是借对宫主星来论——所以这里要标出来。
_CATEGORY = {}
for _s in MAJOR_STARS:
    _CATEGORY[_s] = "主星"
for _s in LUCKY_STARS:
    _CATEGORY[_s] = "吉星"
for _s in MALEFIC_STARS:
    _CATEGORY[_s] = "煞星"


def _category(name):
    return _CATEGORY.get(name, "杂曜")


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------

@dataclass
class Star:
    """落在某一宫的一颗星。"""
    name: str
    category: str                  # 主星 / 吉星 / 煞星 / 杂曜
    brightness: Optional[str] = None   # 仅主星有庙旺利陷
    sihua: Optional[str] = None        # 本命四化

    @property
    def power(self):
        """亮度量化值，非主星返回 None。格局判断与评分取用。"""
        from .stars import BRIGHTNESS_RANK
        return BRIGHTNESS_RANK.get(self.brightness) if self.brightness else None

    def to_dict(self):
        out = {"名": self.name, "类": self.category}
        if self.brightness:
            out["亮度"] = self.brightness
        if self.sihua:
            out["四化"] = self.sihua
        return out


@dataclass
class Palace:
    """十二宫之一。"""
    index: int                     # 地支序号 0–11
    name: str                      # 宫名
    stem: str
    is_body: bool = False          # 是否身宫
    stars: List[Star] = field(default_factory=list)

    changsheng: str = ""           # 长生十二神
    boshi: str = ""                # 博士十二神
    suiqian: str = ""              # 岁前十二星
    jiangqian: str = ""            # 将前十二星

    limit_ages: Tuple[int, int] = (0, 0)     # 大限虚岁区间
    limit_years: Tuple[int, int] = (0, 0)    # 大限公历年区间
    minor_age: int = 0                       # 小限基础虚岁（此后每 12 年一轮）

    borrowed: List[Star] = field(default_factory=list)   # 空宫所借对宫主星

    @property
    def branch(self):
        return BRANCHES[self.index]

    @property
    def gz(self):
        return self.stem + self.branch

    @property
    def majors(self):
        return [s for s in self.stars if s.category == "主星"]

    @property
    def is_empty(self):
        """无主星即空宫。约七分之三的宫会是空宫，属常态。"""
        return not self.majors

    def has(self, *names):
        return any(s.name in names for s in self.stars)

    def to_dict(self):
        return {
            "宫名": self.name,
            "地支": self.branch,
            "宫干支": self.gz,
            "宫位含义": PALACE_MEANINGS.get(self.name, ""),
            "身宫": self.is_body,
            "空宫": self.is_empty,
            "星曜": [s.to_dict() for s in self.stars],
            "借星": [s.to_dict() for s in self.borrowed],
            "长生十二神": self.changsheng,
            "博士十二神": self.boshi,
            "岁前": self.suiqian,
            "将前": self.jiangqian,
            "大限": "{}–{} 虚岁（{}–{}）".format(
                self.limit_ages[0], self.limit_ages[1],
                self.limit_years[0], self.limit_years[1]),
            "小限起": self.minor_age,
        }


@dataclass
class ZiweiChart:
    """一张完整的紫微命盘。"""
    input_time: datetime
    standard_time: datetime
    true_solar_time: datetime
    # 换农历用的时刻：晚子时归次日时会比 true_solar_time 晚一小时。
    # 刻意不叫 reckon_time——那是 bazi.chart 里那个函数的名字，同名会读混。
    shifted_time: datetime
    gender: str
    longitude: float
    dst_adjusted: bool

    lunar_year: int = 0
    lunar_month: int = 0
    lunar_day: int = 0
    lunar_is_leap: bool = False
    lunar_text: str = ""
    used_month: int = 0             # 定盘实际采用的月（闰月规则可能改它）
    leap_note: str = ""

    year_stem: str = ""
    year_branch: str = ""
    hour_index: int = 0

    life_index: int = 0             # 命宫地支序号
    body_index: int = 0             # 身宫地支序号
    ju: int = 0
    ju_name: str = ""

    forward: bool = True            # 大限顺行
    palaces: List[Palace] = field(default_factory=list)   # 按地支序号 0–11

    life_lord: str = ""
    body_lord: str = ""
    sihua: Dict[str, str] = field(default_factory=dict)

    # ── 取用 ──────────────────────────────────────────────

    @property
    def year_gz(self):
        return self.year_stem + self.year_branch

    @property
    def zodiac(self):
        return ZODIAC[BRANCHES.index(self.year_branch)]

    @property
    def yin_yang(self):
        return "阳" if STEM_YANG[self.year_stem] else "阴"

    def palace(self, index):
        return self.palaces[index % 12]

    def by_name(self, name):
        """按宫名取宫，如 by_name('官禄')。"""
        for p in self.palaces:
            if p.name == name:
                return p
        raise KeyError(name)

    def life_palace(self):
        return self.palace(self.life_index)

    def body_palace(self):
        return self.palace(self.body_index)

    def triangle(self, index):
        """某宫的三方四正：本宫、对宫、三合两宫。

        紫微论断极少只看本宫——一颗星落在对宫，力量照样打进来。
        """
        return [self.palace(index + off) for off in TRIANGLE_OFFSETS]

    def star_palace(self, star_name):
        """某颗星所在的宫（找不到返回 None）。"""
        for p in self.palaces:
            if p.has(star_name):
                return p
        return None

    def limit_at(self, age):
        """给定虚岁，返回所在大限之宫（未入限则为 None）。"""
        for p in self.palaces:
            lo, hi = p.limit_ages
            if lo <= age <= hi:
                return p
        return None

    def minor_limit_at(self, age):
        """给定虚岁，返回小限所在之宫。小限一年一宫，十二年一轮。"""
        step = 1 if self.gender == "male" else -1
        start = BRANCHES.index(
            _group_lookup(MINOR_LIMIT_START, self.year_branch))
        return self.palace(start + step * (age - 1))

    def age_in(self, year):
        """某公历年的虚岁。紫微以农历年论年岁。"""
        return year - self.lunar_year + 1

    def to_dict(self):
        return {
            "出生": {
                "登记时刻": self.input_time.strftime("%Y-%m-%d %H:%M"),
                "标准时": self.standard_time.strftime("%Y-%m-%d %H:%M"),
                "真太阳时": self.true_solar_time.strftime("%Y-%m-%d %H:%M"),
                "农历": self.lunar_text,
                "时辰": SHICHEN_NAMES[self.hour_index],
                "性别": "男" if self.gender == "male" else "女",
                "生肖": self.zodiac,
                "年干支": self.year_gz,
                "阴阳": self.yin_yang + ("男" if self.gender == "male" else "女"),
                "经度": self.longitude,
                "已回退夏令时": self.dst_adjusted,
                "闰月处理": self.leap_note,
            },
            "命盘": {
                "命宫": BRANCHES[self.life_index],
                "身宫": BRANCHES[self.body_index],
                "五行局": self.ju_name,
                "命主": self.life_lord,
                "身主": self.body_lord,
                "大限排法": "顺行" if self.forward else "逆行",
                "生年四化": self.sihua,
            },
            # 按地支序号排列（子=0），前端据此摆十二宫的方位
            "十二宫": [p.to_dict() for p in self.palaces],
            # 星曜释义随盘一起下发，而不是在前端再存一份表：一份数据两处维护，
            # 迟早对不上。做成查找表而非挂在每颗星上，是因为同名星只出现一次，
            # 挂在星上会把同一段话重复几十遍。
            "星曜释义": {
                s.name: STAR_MEANINGS[s.name]
                for p in self.palaces for s in p.stars
                if s.name in STAR_MEANINGS
            },
        }


def _group_lookup(table, branch):
    for key, value in table.items():
        if branch in key:
            return value
    raise ValueError("表中无 {}".format(branch))


# --------------------------------------------------------------------------
# 排盘
# --------------------------------------------------------------------------

def build_chart(
    year, month, day, hour, minute=0,
    gender="male",
    longitude=DEFAULT_LONGITUDE,
    tz_offset=DEFAULT_TZ,
    use_true_solar_time=True,
    late_zi_shifts_day=True,
    adjust_china_dst=True,
    year_boundary="lunar",
    leap_month_rule="current",
):
    """排出完整紫微命盘。

    参数
    ----
    year..minute        出生地当地**标准时**（中国大陆即北京时间）。
    gender              "male" / "female"，决定大限与小限的顺逆。
    longitude/tz_offset 出生地经度与时区，真太阳时校正用。
    late_zi_shifts_day  晚子时（23:00–23:59）是否算次日。
                        对紫微影响比对八字更大——它直接改农历日，
                        而农历日决定紫微星落哪一宫，一改则满盘皆变。
    year_boundary       生年干支的换年点。
                        "lunar"  = 正月初一换年（紫微斗数主流）
                        "lichun" = 立春换年（与八字同口径，少数派）
    leap_month_rule     闰月生人按哪个月定命宫。
                        "current" = 一律作本月（通行做法）
                        "split"   = 初一至十五作本月，十六起作下月
    """
    if gender not in ("male", "female"):
        raise ValueError("gender 必须是 'male' 或 'female'")
    if year_boundary not in ("lunar", "lichun"):
        raise ValueError("year_boundary 必须是 'lunar' 或 'lichun'")
    if leap_month_rule not in ("current", "split"):
        raise ValueError("leap_month_rule 必须是 'current' 或 'split'")

    rt = reckon_time(
        year, month, day, hour, minute,
        longitude=longitude, tz_offset=tz_offset,
        use_true_solar_time=use_true_solar_time,
        adjust_china_dst=adjust_china_dst,
    )

    # 晚子时归次日：必须在换算农历之前做，否则日期错一天，紫微星就错一宫
    d = rt.reckon_dt
    if late_zi_shifts_day and d.hour == 23:
        d = d + timedelta(hours=1)

    ld = lunar_date(d.year, d.month, d.day, tz_offset=tz_offset)
    hour_index = hour_branch_index(rt.reckon_dt.hour, rt.reckon_dt.minute)

    # ── 闰月归属 ────────────────────────────────────────────
    used_month = ld.month
    leap_note = ""
    if ld.is_leap:
        # 月份一律用汉字数字，与农历日期的写法保持一致（「闰二月」而非「闰2月」）
        this_name = MONTH_NAMES[ld.month - 1]
        if leap_month_rule == "split" and ld.day > 15:
            used_month = ld.month % 12 + 1
            leap_note = "闰{}月十六日之后，按下一月（{}月）定宫".format(
                this_name, MONTH_NAMES[used_month - 1])
        else:
            leap_note = "闰{}月按本月定宫".format(this_name)

    # ── 生年干支 ────────────────────────────────────────────
    if year_boundary == "lunar":
        gz_year = ld.year
    else:
        gz_year = _lichun_year(rt.standard_dt)
    year_stem = STEMS[(gz_year - 4) % 10]
    year_branch = BRANCHES[(gz_year - 4) % 12]

    # ── 命宫与身宫 ──────────────────────────────────────────
    # 寅宫起正月顺数至生月，再自该宫起子时逆数至生时得命宫；顺数则得身宫。
    month_palace = (2 + used_month - 1) % 12
    life_index = (month_palace - hour_index) % 12
    body_index = (month_palace + hour_index) % 12

    ju, ju_name = five_phase_ju(year_stem, life_index)

    chart = ZiweiChart(
        input_time=rt.input_dt,
        standard_time=rt.standard_dt,
        true_solar_time=rt.reckon_dt,
        shifted_time=d,
        gender=gender,
        longitude=longitude,
        dst_adjusted=rt.dst_adjusted,
        lunar_year=ld.year, lunar_month=ld.month, lunar_day=ld.day,
        lunar_is_leap=ld.is_leap, lunar_text=str(ld),
        used_month=used_month, leap_note=leap_note,
        year_stem=year_stem, year_branch=year_branch,
        hour_index=hour_index,
        life_index=life_index, body_index=body_index,
        ju=ju, ju_name=ju_name,
        life_lord=life_lord(life_index), body_lord=body_lord(year_branch),
        sihua=transformations(year_stem),
    )

    _build_palaces(chart)
    _place_stars(chart, ld)
    _build_limits(chart)
    _borrow_stars(chart)
    return chart


def _lichun_year(dt):
    """立春换年下的生年。仅在 year_boundary='lichun' 时用到。

    立春时刻与出生时刻都是绝对时刻，比较时化到 UTC，与时区无关。
    """
    jd = julian_day(dt.astimezone(timezone.utc).replace(tzinfo=None))
    return dt.year if jd >= solar_term_jd(dt.year, 0) else dt.year - 1


def _build_palaces(chart):
    """摆十二宫：自命宫起**逆行**安宫名，宫干按五虎遁。"""
    chart.palaces = [None] * 12
    for i, name in enumerate(PALACES):
        idx = (chart.life_index - i) % 12
        chart.palaces[idx] = Palace(
            index=idx,
            name=name,
            stem=palace_stem(chart.year_stem, idx),
            is_body=(idx == chart.body_index),
        )


def _place_stars(chart, ld):
    """安星：把五组口诀的结果汇总到各宫。"""
    positions = {}   # {星名: 宫序号}

    positions.update(major_star_positions(ld.day, chart.ju))
    positions.update(year_stem_stars(chart.year_stem))
    positions.update(year_branch_stars(chart.year_branch, chart.hour_index))
    positions.update(month_stars(chart.used_month))
    hs = hour_stars(chart.hour_index)
    positions.update(hs)
    # 三台八座依辅弼、恩光天贵依昌曲，故须等前几组落定
    positions.update(day_stars(
        ld.day,
        positions["左辅"], positions["右弼"],
        hs["文昌"], hs["文曲"],
    ))

    for name, idx in positions.items():
        cat = _category(name)
        chart.palaces[idx].stars.append(Star(
            name=name,
            category=cat,
            brightness=brightness(name, idx),
            sihua=chart.sihua.get(name),
        ))

    # 每宫内按 主星 → 吉星 → 煞星 → 杂曜 排序，读盘时视线才有落点
    order = {"主星": 0, "吉星": 1, "煞星": 2, "杂曜": 3}
    for p in chart.palaces:
        p.stars.sort(key=lambda s: (order[s.category], s.name))

    # ── 四组十二神 ──────────────────────────────────────────
    forward = STEM_YANG[chart.year_stem] == (chart.gender == "male")
    chart.forward = forward

    cs = changsheng_cycle(chart.ju, forward)
    bs = boshi_cycle(positions["禄存"], forward)
    sq = suiqian_cycle(chart.year_branch)
    jq = jiangqian_cycle(chart.year_branch)
    for idx, p in enumerate(chart.palaces):
        p.changsheng = cs[idx]
        p.boshi = bs[idx]
        p.suiqian = sq[idx]
        p.jiangqian = jq[idx]


def _build_limits(chart):
    """大限与小限。

    大限自命宫起，阳男阴女顺行、阴男阳女逆行，一宫十年；第一大限的起始
    虚岁即五行局数——水二局自二岁起，火六局自六岁起。

    小限另起一路：依生年支三合定起宫，男顺女逆，一年一宫十二年一轮。
    """
    step = 1 if chart.forward else -1
    for i in range(12):
        idx = (chart.life_index + step * i) % 12
        lo = chart.ju + 10 * i
        hi = lo + 9
        p = chart.palaces[idx]
        p.limit_ages = (lo, hi)
        # 虚岁 n 对应农历年 lunar_year + n - 1
        p.limit_years = (chart.lunar_year + lo - 1, chart.lunar_year + hi - 1)

    m_step = 1 if chart.gender == "male" else -1
    start = BRANCHES.index(_group_lookup(MINOR_LIMIT_START, chart.year_branch))
    for age in range(1, 13):
        chart.palaces[(start + m_step * (age - 1)) % 12].minor_age = age


def _borrow_stars(chart):
    """空宫借对宫主星。

    十四颗主星摆进十二宫，必有空宫。传统作法是借对宫的主星来论——
    对宫的力量本就通过三方四正打进来，借星只是把这件事写明白。
    """
    for p in chart.palaces:
        if not p.is_empty:
            continue
        opposite = chart.palace(p.index + 6)
        p.borrowed = [
            Star(name=s.name, category=s.category,
                 # 借来的星论其在**原宫**的亮度，不按本宫重算
                 brightness=s.brightness, sihua=s.sihua)
            for s in opposite.majors
        ]
