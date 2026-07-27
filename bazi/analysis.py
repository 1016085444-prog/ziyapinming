"""命理分析层：把命盘转成结构化判断，供报告与 AI 对话取用。

子平法在旺衰、取用上本就有多家说法，这里选定一套**透明可复现**的量化口径：
每一步的权重都写在常量里，输出同时给出结论和依据，便于日后按流派调参，
也让 AI 在解读时能引用具体依据而不是凭空发挥。
"""

from __future__ import annotations

from .ganzhi import (
    BRANCHES, BRANCH_ELEMENT, ELEMENTS, HIDDEN_STEMS, HIDDEN_WEIGHTS,
    STEM_ELEMENT, STEM_YANG, STEMS, controls, generates, ten_god,
    twelve_stage,
)

__all__ = [
    "element_scores", "day_master_strength", "pattern",
    "favorable_elements", "ten_god_census", "analyze", "year_outlook",
]

# 各柱位权重。月令最重，日支次之——月令司权是子平法的核心前提。
POSITION_WEIGHT = {
    "年干": 0.8, "月干": 1.0, "日干": 1.0, "时干": 0.8,
    "年支": 0.8, "月支": 2.0, "日支": 1.2, "时支": 0.8,
}

# 旺相休囚死：以月令五行为基准的季节调整系数
SEASON_FACTOR = {"旺": 1.30, "相": 1.10, "休": 0.90, "囚": 0.80, "死": 0.70}

# 通根：日主坐于这些十二运位视为有根
ROOTED_STAGES = ("长生", "冠带", "临官", "帝旺", "墓")

STRONG_THRESHOLD = 0.575      # 扶抑比高于此判身强
WEAK_THRESHOLD = 0.425        # 低于此判身弱

# 羊刃：阳干的帝旺之支
BLADE_BRANCH = {"甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子"}


def _season_state(element, month_element):
    """该五行相对月令处于旺/相/休/囚/死。"""
    if element == month_element:
        return "旺"
    if generates(month_element) == element:
        return "相"
    if generates(element) == month_element:
        return "休"
    if controls(element) == month_element:
        return "囚"
    return "死"


# --------------------------------------------------------------------------
# 五行力量
# --------------------------------------------------------------------------

def element_scores(chart):
    """五行力量得分。返回 (得分表, 明细列表)。

    天干按柱位计权；地支拆藏干，按本气/中气/余气分配权重；
    最后整体乘以该五行相对月令的旺相休囚死系数。
    """
    month_element = BRANCH_ELEMENT[chart.month.branch]
    raw = {e: 0.0 for e in ELEMENTS}
    detail = []

    labels = ("年", "月", "日", "时")
    for label, p in zip(labels, chart.pillars):
        w = POSITION_WEIGHT[label + "干"]
        raw[STEM_ELEMENT[p.stem]] += w
        detail.append({
            "来源": "{}干 {}".format(label, p.stem),
            "五行": STEM_ELEMENT[p.stem], "权重": round(w, 3),
        })

        bw = POSITION_WEIGHT[label + "支"]
        hidden = HIDDEN_STEMS[p.branch]
        for h, share in zip(hidden, HIDDEN_WEIGHTS[len(hidden)]):
            w = bw * share
            raw[STEM_ELEMENT[h]] += w
            detail.append({
                "来源": "{}支 {} 藏 {}".format(label, p.branch, h),
                "五行": STEM_ELEMENT[h], "权重": round(w, 3),
            })

    scores = {}
    for e in ELEMENTS:
        state = _season_state(e, month_element)
        scores[e] = round(raw[e] * SEASON_FACTOR[state], 3)

    return scores, detail


# --------------------------------------------------------------------------
# 日主强弱
# --------------------------------------------------------------------------

def day_master_strength(chart):
    """判定日主旺衰，并给出得令/得地/得势三项依据。"""
    scores, _ = element_scores(chart)
    me = STEM_ELEMENT[chart.day_stem]
    month_element = BRANCH_ELEMENT[chart.month.branch]

    seal = next(e for e in ELEMENTS if generates(e) == me)   # 生我者为印
    child = generates(me)                                    # 我生者为食伤
    wealth = controls(me)                                    # 我克者为财
    officer = next(e for e in ELEMENTS if controls(e) == me)  # 克我者为官杀

    support = scores[me] + scores[seal]
    drain = scores[child] + scores[wealth] + scores[officer]
    ratio = support / (support + drain) if (support + drain) else 0.5

    if ratio >= STRONG_THRESHOLD + 0.075:
        verdict = "身旺"
    elif ratio >= STRONG_THRESHOLD:
        verdict = "偏强"
    elif ratio > WEAK_THRESHOLD:
        verdict = "中和"
    elif ratio > WEAK_THRESHOLD - 0.075:
        verdict = "偏弱"
    else:
        verdict = "身弱"

    # 得令：月令为我或生我
    state = _season_state(me, month_element)
    has_season = state in ("旺", "相")

    # 得地：日主在四支中是否通根
    roots = [
        "{}支{}（{}）".format(lbl, p.branch, twelve_stage(chart.day_stem, p.branch))
        for lbl, p in zip("年月日时", chart.pillars)
        if twelve_stage(chart.day_stem, p.branch) in ROOTED_STAGES
    ]

    # 得势：印比在天干的呼应
    allies = [
        "{}干{}（{}）".format(lbl, p.stem, ten_god(chart.day_stem, p.stem))
        for lbl, p in zip("年月日时", chart.pillars)
        if lbl != "日" and STEM_ELEMENT[p.stem] in (me, seal)
    ]

    return {
        "结论": verdict,
        "扶抑比": round(ratio, 3),
        "扶（比劫+印）": round(support, 3),
        "抑（食伤+财+官杀）": round(drain, 3),
        "日主五行": me,
        "月令": "{}月，日主处「{}」地".format(chart.month.branch, state),
        "得令": has_season,
        "得地": roots or ["四支无根"],
        "得势": allies or ["天干无印比相助"],
        "五行角色": {
            "比劫": me, "印": seal, "食伤": child, "财": wealth, "官杀": officer,
        },
    }


# --------------------------------------------------------------------------
# 格局
# --------------------------------------------------------------------------

def pattern(chart):
    """月令取格：先看建禄/羊刃，再看月支藏干透出者。"""
    day_stem = chart.day_stem
    month_branch = chart.month.branch
    stage = twelve_stage(day_stem, month_branch)

    if stage == "临官":
        return {"格局": "建禄格", "依据": "月令{}为日主{}之临官".format(month_branch, day_stem)}
    if BLADE_BRANCH.get(day_stem) == month_branch:
        return {"格局": "羊刃格", "依据": "月令{}为日主{}之羊刃".format(month_branch, day_stem)}

    # 其余天干（不含日干）中出现的字，视为透出
    exposed = {p.stem for lbl, p in zip("年月日时", chart.pillars) if lbl != "日"}
    hidden = HIDDEN_STEMS[month_branch]

    for rank, h in enumerate(hidden):
        if h in exposed:
            god = ten_god(day_stem, h)
            tier = ("本气", "中气", "余气")[rank]
            return {
                "格局": "{}格".format(god),
                "依据": "月令{}藏{}（{}）透于天干，取{}为格".format(
                    month_branch, h, tier, god),
            }

    god = ten_god(day_stem, hidden[0])
    return {
        "格局": "{}格".format(god),
        "依据": "月令{}藏干未透，以本气{}论{}格".format(month_branch, hidden[0], god),
    }


# --------------------------------------------------------------------------
# 喜用神
# --------------------------------------------------------------------------

def favorable_elements(chart):
    """扶抑为主、调候为辅，给出喜忌。"""
    strength = day_master_strength(chart)
    roles = strength["五行角色"]
    verdict = strength["结论"]

    if verdict in ("身旺", "偏强"):
        like = [roles["食伤"], roles["财"], roles["官杀"]]
        avoid = [roles["比劫"], roles["印"]]
        reason = "日主{}，宜克泄耗以求平衡，忌再生扶。".format(verdict)
    elif verdict in ("身弱", "偏弱"):
        like = [roles["印"], roles["比劫"]]
        avoid = [roles["食伤"], roles["财"], roles["官杀"]]
        reason = "日主{}，宜生扶帮身，忌再耗泄。".format(verdict)
    else:
        # 中和局取五行最弱者补之
        scores, _ = element_scores(chart)
        weakest = min(ELEMENTS, key=lambda e: scores[e])
        like = [weakest]
        avoid = [max(ELEMENTS, key=lambda e: scores[e])]
        reason = "日主中和，以补足最弱之{}、抑制最旺者为宜。".format(weakest)

    # 调候：冬寒宜暖、夏燥宜润
    month_branch = chart.month.branch
    climate = None
    if month_branch in "亥子丑":
        climate = "生于冬月，天寒地冻，火为调候之要。"
        if "火" not in like:
            like = like + ["火"]
    elif month_branch in "巳午未":
        climate = "生于夏月，火炎土燥，水为调候之要。"
        if "水" not in like:
            like = like + ["水"]

    return {
        "喜用": like,
        "忌神": [e for e in avoid if e not in like],
        "取用依据": reason,
        "调候": climate,
    }


# --------------------------------------------------------------------------
# 十神统计
# --------------------------------------------------------------------------

def ten_god_census(chart):
    """统计十神分布（天干计满分、藏干按气分权），性格与六亲解读的直接依据。"""
    counts = {}
    day_stem = chart.day_stem

    for lbl, p in zip("年月日时", chart.pillars):
        if lbl != "日":
            g = ten_god(day_stem, p.stem)
            counts[g] = counts.get(g, 0) + POSITION_WEIGHT[lbl + "干"]
        bw = POSITION_WEIGHT[lbl + "支"]
        hidden = HIDDEN_STEMS[p.branch]
        for h, share in zip(hidden, HIDDEN_WEIGHTS[len(hidden)]):
            g = ten_god(day_stem, h)
            counts[g] = counts.get(g, 0) + bw * share

    return {k: round(v, 2) for k, v in
            sorted(counts.items(), key=lambda kv: -kv[1])}


# --------------------------------------------------------------------------
# 流年
# --------------------------------------------------------------------------

# 流年天干十神的白话主题。原始十神名对普通用户等于天书，
# 但直接给结论又太满——这里只描述「这一年的气质」，具体落到什么事上留给人谈。
YEAR_THEME = {
    "比肩": "同辈往来密集，合作与竞争一起来。助力和分账都容易出在身边人身上。",
    "劫财": "开销偏大、财易被分。合伙、借贷、替人担保这三件事今年格外要慎。",
    "食神": "心气顺、产出稳。适合埋头做积累型的事，不适合急着要回报。",
    "伤官": "表达欲和锋芒都在高点。出成绩容易，顶撞人也容易，话出口前多想一秒。",
    "偏财": "机会和意外进项都多，但来得快去得也快。适合抓机会，不适合压重注。",
    "正财": "进项偏稳，适合稳扎稳打把手上的事做扎实。男命感情上也主动。",
    "七杀": "压力和挑战集中。扛过去是上一个台阶，硬扛不过去就是消耗，要挑着扛。",
    "正官": "责任与名分加身。升迁、考试、成家这类「被认可」的事今年概率高。",
    "偏印": "心思重、想得多，容易钻牛角尖。适合进修、研究、闭关做深的事。",
    "正印": "有人护着，长辈与贵人给力。学习、置产、靠资历上位都顺。",
}


def year_outlook(chart, year):
    """某一流年与命局、大运的互动。给 AI 写运势的原料，不下吉凶结论。"""
    fy = chart.fleeting_year(year)
    luck = chart.luck_at(year)
    fav = favorable_elements(chart)
    day_stem = chart.day_stem

    from .ganzhi import branch_relations

    def _added(before, after):
        """after 相对 before 新增的关系。"""
        out = {}
        for k, v in after.items():
            extra = [x for x in v if x not in before.get(k, [])]
            if extra:
                out[k] = extra
        return out

    # 大运是十年格局、流年是当年变量，两者分开归因，否则十年一遇的合局
    # 会被误报成「今年新增」。
    natal = branch_relations(chart.branches)
    luck_branches = chart.branches + ([luck.branch] if luck else [])
    with_luck = branch_relations(luck_branches)
    with_year = branch_relations(luck_branches + [fy.branch])

    year_elements = [STEM_ELEMENT[fy.stem], BRANCH_ELEMENT[fy.branch]]
    return {
        "年份": year,
        "流年干支": fy.gz,
        "虚岁": year - chart.solar_time.year + 1,
        "所行大运": luck.gz if luck else "尚未起运",
        "流年天干十神": ten_god(day_stem, fy.stem),
        "流年主题": YEAR_THEME.get(ten_god(day_stem, fy.stem), ""),
        "流年地支藏干十神": [
            {"干": h, "十神": ten_god(day_stem, h)}
            for h in HIDDEN_STEMS[fy.branch]
        ],
        "流年十二运": twelve_stage(day_stem, fy.branch),
        "五行取向": (
            "契合喜用" if any(e in fav["喜用"] for e in year_elements)
            else "触及忌神" if any(e in fav["忌神"] for e in year_elements)
            else "与喜忌无直接关涉"
        ),
        "大运引动": _added(natal, with_luck) or {"说明": ["大运与原局无新增刑冲合会"]},
        "流年引动": _added(with_luck, with_year) or {"说明": ["流年无新增刑冲合会"]},
    }


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def analyze(chart):
    """完整分析结果，与 chart.to_dict() 合并即为 AI 的全部输入。"""
    scores, detail = element_scores(chart)
    total = sum(scores.values()) or 1.0
    return {
        "五行力量": scores,
        "五行占比": {k: "{:.1%}".format(v / total) for k, v in scores.items()},
        "五行缺": [e for e in ELEMENTS if scores[e] < total * 0.05],
        "日主旺衰": day_master_strength(chart),
        "格局": pattern(chart),
        "喜忌": favorable_elements(chart),
        "十神分布": ten_god_census(chart),
        "计分明细": detail,
    }
