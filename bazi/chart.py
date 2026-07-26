"""排盘核心：把一个公历出生时刻映射为完整命盘。

三条容易被廉价程序做错的规则，这里都显式处理：

1. **年柱以立春换年**，不是元旦，也不是农历正月初一。
2. **月柱以「节」换月**（立春/惊蛰/清明…），不是「气」，也不是农历月。
3. **时辰按真太阳时**：标准时 + 经度时差 + 均时差。北京时间的 120°E
   基准让乌鲁木齐出生者最多偏差近两小时，足以整体错一到两个时辰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from .astro import (
    equation_of_time,
    julian_day,
    jd_to_datetime,
    solar_term_jd,
)
from .ganzhi import (
    BRANCHES, BRANCH_ELEMENT, HIDDEN_STEMS, STEMS, STEM_ELEMENT, STEM_YANG,
    ZODIAC, branch_relations, empty_branches, nayin, shensha, ten_god,
    twelve_stage,
)

__all__ = ["Pillar", "LuckPillar", "Chart", "build_chart", "SOLAR_TERM_NAMES"]

SOLAR_TERM_NAMES = (
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
)

# 十二「节」（偶数序）依次对应寅月起的十二月建
MONTH_NODE_NAMES = tuple(SOLAR_TERM_NAMES[i] for i in range(0, 24, 2))

DEFAULT_TZ = 8.0
DEFAULT_LONGITUDE = 116.4074   # 北京
DEFAULT_LATITUDE = 39.9042


@lru_cache(maxsize=4096)
def _term_jd(year, index):
    return solar_term_jd(year, index)


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------

@dataclass
class Pillar:
    """一柱：天干 + 地支及其派生信息。"""
    stem: str
    branch: str
    label: str = ""

    @property
    def gz(self):
        return self.stem + self.branch

    @property
    def stem_element(self):
        return STEM_ELEMENT[self.stem]

    @property
    def branch_element(self):
        return BRANCH_ELEMENT[self.branch]

    @property
    def hidden(self):
        return HIDDEN_STEMS[self.branch]

    @property
    def nayin(self):
        return nayin(self.stem, self.branch)

    def to_dict(self, day_stem):
        return {
            "label": self.label,
            "干支": self.gz,
            "天干": self.stem,
            "地支": self.branch,
            "天干五行": self.stem_element,
            "地支五行": self.branch_element,
            "天干十神": "日主" if self.label == "日" else ten_god(day_stem, self.stem),
            "藏干": [
                {"干": h, "十神": ten_god(day_stem, h)} for h in self.hidden
            ],
            "纳音": self.nayin,
            "十二运": twelve_stage(day_stem, self.branch),
        }


@dataclass
class LuckPillar:
    """一步大运。"""
    stem: str
    branch: str
    start_age: float          # 起运虚岁（含小数）
    start_year: int           # 公历起始年
    end_year: int

    @property
    def gz(self):
        return self.stem + self.branch

    def to_dict(self, day_stem):
        return {
            "干支": self.gz,
            "起始虚岁": round(self.start_age, 1),
            "年份区间": "{}–{}".format(self.start_year, self.end_year),
            "天干十神": ten_god(day_stem, self.stem),
            "地支藏干十神": [
                {"干": h, "十神": ten_god(day_stem, h)}
                for h in HIDDEN_STEMS[self.branch]
            ],
            "十二运": twelve_stage(day_stem, self.branch),
        }


@dataclass
class Chart:
    solar_time: datetime          # 出生地标准时（带时区）
    true_solar_time: datetime     # 真太阳时
    gender: str                   # "male" / "female"
    longitude: float
    latitude: float

    year: Pillar = None
    month: Pillar = None
    day: Pillar = None
    hour: Pillar = None

    luck_forward: bool = True
    luck_start_desc: str = ""
    luck_start_age: float = 0.0
    luck_pillars: List[LuckPillar] = field(default_factory=list)

    prev_node: Tuple[str, datetime] = None   # 上一个节
    next_node: Tuple[str, datetime] = None   # 下一个节
    fetal_origin: str = ""                   # 胎元

    @property
    def pillars(self):
        return [self.year, self.month, self.day, self.hour]

    @property
    def day_stem(self):
        return self.day.stem

    @property
    def branches(self):
        return [p.branch for p in self.pillars]

    @property
    def stems(self):
        return [p.stem for p in self.pillars]

    @property
    def zodiac(self):
        return ZODIAC[BRANCHES.index(self.year.branch)]

    def luck_at(self, year):
        """给定公历年份，返回当时所处的大运（未起运则为 None）。"""
        for lp in self.luck_pillars:
            if lp.start_year <= year <= lp.end_year:
                return lp
        return None

    def fleeting_year(self, year):
        """流年干支。"""
        return Pillar(
            STEMS[(year - 4) % 10], BRANCHES[(year - 4) % 12], label="流年"
        )

    def to_dict(self):
        ds = self.day_stem
        void = empty_branches(self.day.stem, self.day.branch)
        return {
            "出生": {
                "标准时": self.solar_time.strftime("%Y-%m-%d %H:%M"),
                "真太阳时": self.true_solar_time.strftime("%Y-%m-%d %H:%M"),
                "性别": "男" if self.gender == "male" else "女",
                "经度": self.longitude,
                "纬度": self.latitude,
                "生肖": self.zodiac,
            },
            "四柱": [p.to_dict(ds) for p in self.pillars],
            "日主": {"天干": ds, "五行": STEM_ELEMENT[ds],
                     "阴阳": "阳" if STEM_YANG[ds] else "阴"},
            "节气": {
                "上一节": "{} {}".format(
                    self.prev_node[0], self.prev_node[1].strftime("%Y-%m-%d %H:%M")
                ),
                "下一节": "{} {}".format(
                    self.next_node[0], self.next_node[1].strftime("%Y-%m-%d %H:%M")
                ),
            },
            "胎元": self.fetal_origin,
            "空亡": "".join(void),
            "神煞": shensha(
                self.year.branch, self.day.stem, self.day.branch, self.branches
            ),
            "刑冲合害": branch_relations(self.branches),
            "大运": {
                "排法": "顺行" if self.luck_forward else "逆行",
                "起运": self.luck_start_desc,
                "各步": [lp.to_dict(ds) for lp in self.luck_pillars],
            },
        }


# --------------------------------------------------------------------------
# 时间与节气定位
# --------------------------------------------------------------------------

def _apply_true_solar(local_dt, longitude, tz_offset):
    """标准时 → 真太阳时。

    修正两项：经度时差（每偏离标准经线 1° 差 4 分钟）与均时差
    （地球轨道偏心率 + 黄赤交角造成的视太阳与平太阳之差，全年 ±16 分钟）。
    """
    standard_meridian = tz_offset * 15.0
    longitude_minutes = (longitude - standard_meridian) * 4.0

    utc_dt = local_dt.astimezone(timezone.utc)
    eot_minutes = equation_of_time(julian_day(utc_dt.replace(tzinfo=None)))

    return local_dt + timedelta(minutes=longitude_minutes + eot_minutes)


def _find_month_node(jd_ut, civil_year):
    """定位出生时刻所在的月建。

    返回 (立春所属年, 节序号 k)，k=0 为寅月。同时给出该节与下一节的时刻。
    """
    candidates = []
    for y in (civil_year - 1, civil_year, civil_year + 1):
        for k in range(12):
            candidates.append((_term_jd(y, k * 2), y, k))
    candidates.sort()

    for i, item in enumerate(candidates):
        if item[0] > jd_ut:
            if i == 0:
                break          # 早于窗口内第一个节，无法定位月建
            return candidates[i - 1], item
    raise ValueError("出生时刻超出节气计算范围")


# --------------------------------------------------------------------------
# 排盘
# --------------------------------------------------------------------------

def build_chart(
    year, month, day, hour, minute=0,
    gender="male",
    longitude=DEFAULT_LONGITUDE,
    latitude=DEFAULT_LATITUDE,
    tz_offset=DEFAULT_TZ,
    use_true_solar_time=True,
    late_zi_shifts_day=True,
    luck_count=10,
):
    """排出完整命盘。

    参数
    ----
    year..minute      出生地当地**标准时**（如中国大陆用北京时间）。
    gender            "male" / "female"，决定大运顺逆。
    longitude         出生地经度，东经为正。真太阳时校正用。
    tz_offset         出生地时区偏移小时数（中国为 8）。
    use_true_solar_time  是否启用真太阳时。关闭则日柱时柱直接用标准时。
    late_zi_shifts_day   晚子时（23:00–23:59）是否算次日。
                         True = 子正换日（主流子平法）；False = 夜半换日。
    luck_count        排几步大运。
    """
    if gender not in ("male", "female"):
        raise ValueError("gender 必须是 'male' 或 'female'")

    tz = timezone(timedelta(hours=tz_offset))
    local_dt = datetime(year, month, day, hour, minute, tzinfo=tz)

    if use_true_solar_time:
        reckon_dt = _apply_true_solar(local_dt, longitude, tz_offset)
    else:
        reckon_dt = local_dt

    # --- 年柱、月柱：按绝对时刻与节气比较，与时区无关 -------------------
    jd_ut = julian_day(local_dt.astimezone(timezone.utc).replace(tzinfo=None))
    (prev_jd, node_year, k), (next_jd, _, next_k) = _find_month_node(jd_ut, year)

    year_stem_idx = (node_year - 4) % 10
    year_branch_idx = (node_year - 4) % 12
    year_pillar = Pillar(STEMS[year_stem_idx], BRANCHES[year_branch_idx], "年")

    # 五虎遁：甲己之年丙作首
    month_stem_idx = ((year_stem_idx % 5) * 2 + 2 + k) % 10
    month_branch_idx = (2 + k) % 12
    month_pillar = Pillar(STEMS[month_stem_idx], BRANCHES[month_branch_idx], "月")

    # --- 日柱：六十甲子连续循环，锚点经 2000-01-01 = 戊午 校准 ----------
    d = reckon_dt
    if late_zi_shifts_day and d.hour == 23:
        d = d + timedelta(hours=1)      # 晚子时归次日

    jdn = int(julian_day(datetime(d.year, d.month, d.day, 12)))
    day_index = (jdn + 49) % 60
    day_pillar = Pillar(STEMS[day_index % 10], BRANCHES[day_index % 12], "日")

    # --- 时柱：五鼠遁 -------------------------------------------------
    hour_branch_idx = ((reckon_dt.hour + 1) // 2) % 12
    hour_stem_idx = ((day_index % 10 % 5) * 2 + hour_branch_idx) % 10
    hour_pillar = Pillar(STEMS[hour_stem_idx], BRANCHES[hour_branch_idx], "时")

    chart = Chart(
        solar_time=local_dt,
        true_solar_time=reckon_dt,
        gender=gender,
        longitude=longitude,
        latitude=latitude,
        year=year_pillar, month=month_pillar,
        day=day_pillar, hour=hour_pillar,
    )

    chart.prev_node = (
        MONTH_NODE_NAMES[k], jd_to_datetime(prev_jd).astimezone(tz)
    )
    chart.next_node = (
        MONTH_NODE_NAMES[next_k], jd_to_datetime(next_jd).astimezone(tz)
    )

    # 胎元：月干进一位、月支进三位
    chart.fetal_origin = (
        STEMS[(month_stem_idx + 1) % 10] + BRANCHES[(month_branch_idx + 3) % 12]
    )

    _build_luck(chart, jd_ut, prev_jd, next_jd, year_stem_idx,
                month_stem_idx, month_branch_idx, luck_count, tz)
    return chart


def _build_luck(chart, jd_ut, prev_jd, next_jd, year_stem_idx,
                month_stem_idx, month_branch_idx, count, tz):
    """大运：阳男阴女顺排、阴男阳女逆排；三日折一年起运。"""
    year_is_yang = STEM_YANG[STEMS[year_stem_idx]]
    forward = (year_is_yang == (chart.gender == "male"))
    chart.luck_forward = forward

    # 顺行数到下一节，逆行数回上一节
    span_days = (next_jd - jd_ut) if forward else (jd_ut - prev_jd)

    # 三日折一年、一日折四月、一时辰折十日
    start_age = span_days / 3.0
    whole_years = int(start_age)
    rem_days = span_days - whole_years * 3
    months = int(rem_days * 4)
    days = int(round((rem_days * 4 - months) * 30))
    if days >= 30:
        months += 1
        days -= 30

    chart.luck_start_age = start_age
    chart.luck_start_desc = "{}岁{}个月{}天后起运（虚岁 {} 岁交运）".format(
        whole_years, months, days, whole_years + 1
    )

    # 起运的实际时刻：按回归年长度把「折算年数」还原成日期
    luck_start_dt = chart.solar_time + timedelta(days=start_age * 365.2425)

    step = 1 if forward else -1
    for i in range(1, count + 1):
        s = (month_stem_idx + step * i) % 10
        b = (month_branch_idx + step * i) % 12
        y0 = luck_start_dt.year + (i - 1) * 10
        chart.luck_pillars.append(
            LuckPillar(
                stem=STEMS[s], branch=BRANCHES[b],
                start_age=start_age + (i - 1) * 10 + 1,   # 虚岁
                start_year=y0, end_year=y0 + 9,
            )
        )
