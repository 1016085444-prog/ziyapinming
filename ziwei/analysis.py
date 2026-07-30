"""紫微命盘的结构化分析。

和八字那边一个原则：**每条判断都要能指回盘上的字**。所以格局判断全部写成
「命中条件 → 依据文本」的显式规则，权重与门槛写在常量里，便于按流派调参，
也让解读时能引用具体依据而不是凭空发挥。

紫微与子平的分析口径有一处根本差别：子平算五行力量的连续量，紫微数星曜
的离散组合。所以这里不做「旺衰比」那类连续指标，改为三件事——
三方四正里有什么、成不成格、四化打在哪一宫。
"""

from __future__ import annotations

from bazi.ganzhi import BRANCHES, STEMS

from .stars import (
    BRIGHTNESS_RANK, LUCKY_STARS, MAJOR_STARS, MALEFIC_STARS,
    STAR_MEANINGS, palace_label, transformations,
)

__all__ = [
    "palace_view", "patterns", "sihua_landing", "analyze", "year_outlook",
    "AUSPICIOUS_MINOR", "INAUSPICIOUS_MINOR",
]

# 吉性杂曜。单颗不足以定论，成组出现才见力，所以只用来微调而不主导判断。
AUSPICIOUS_MINOR = (
    "禄存", "天马", "三台", "八座", "恩光", "天贵", "龙池", "凤阁",
    "台辅", "封诰", "天官", "天福", "天巫", "解神", "天才", "天寿",
    "红鸾", "天喜", "华盖",
)
# 凶性杂曜
INAUSPICIOUS_MINOR = (
    "天刑", "阴煞", "破碎", "天哭", "天虚", "孤辰", "寡宿", "天月",
    "蜚廉", "咸池", "天姚",
)

# 四化的分量。化忌不是「凶」，是「执着与耗损所在」——但它确实是全盘
# 最需要提醒的一处，所以给的绝对值最大。
SIHUA_WEIGHT = {"化禄": 3.0, "化权": 2.5, "化科": 2.0, "化忌": -3.5}


# --------------------------------------------------------------------------
# 宫位视图
# --------------------------------------------------------------------------

def palace_view(chart, palace_name):
    """一个宫的完整取用视图：本宫 + 三方四正的星曜与力量。

    紫微极少只看本宫。一颗化忌落在对宫，力量照样打进来；命宫空无主星，
    也要借对宫的星来论。不把三方四正一起摊开，判断就没有依据。
    """
    palace = chart.by_name(palace_name)
    trio = chart.triangle(palace.index)
    labels = ("本宫", "三合", "对宫", "三合")

    majors, lucky, malefic, sihua = [], [], [], []
    for label, p in zip(labels, trio):
        for s in p.majors:
            majors.append("{}{}（{}{}）".format(
                s.name, s.brightness or "", label,
                "·" + s.sihua if s.sihua else ""))
        for s in p.stars:
            if s.name in LUCKY_STARS:
                lucky.append("{}（{}）".format(s.name, label))
            elif s.name in MALEFIC_STARS:
                malefic.append("{}（{}）".format(s.name, label))
            if s.sihua:
                sihua.append("{}{}（{}）".format(s.name, s.sihua, label))

    # 空宫借对宫主星：本宫无主星时，对宫的星就是这个宫的实际内容
    borrowed = ["{}{}".format(s.name, s.brightness or "") for s in palace.borrowed]

    return {
        "宫位": palace_name,
        "落宫": palace.branch,
        "宫干支": palace.gz,
        "含义": palace.to_dict()["宫位含义"],
        "空宫": palace.is_empty,
        "借星": borrowed,
        "三方四正主星": majors or ["三方四正无主星，力量偏散"],
        "会吉星": lucky or ["三方四正不见六吉"],
        "会煞星": malefic or ["三方四正不见六煞"],
        "四化": sihua or ["三方四正无四化"],
        "力量": _palace_power(chart, palace.index),
    }


def _palace_power(chart, index):
    """宫位力量：主星亮度打底，吉煞与四化增减。

    这是个**相对**指标，只用于同一张盘内各宫的比较与评分归一，
    不宜跨盘直接比大小。
    """
    trio = chart.triangle(index)
    # 本宫权重最高，对宫次之，三合再次——同一颗星落在不同位置分量不同
    weights = (1.0, 0.55, 0.75, 0.55)

    total = 0.0
    for w, p in zip(weights, trio):
        for s in p.majors:
            total += w * BRIGHTNESS_RANK[s.brightness]
        for s in p.stars:
            if s.name in LUCKY_STARS:
                total += w * 1.6
            elif s.name in MALEFIC_STARS:
                total -= w * 1.6
            elif s.name in AUSPICIOUS_MINOR:
                total += w * 0.4
            elif s.name in INAUSPICIOUS_MINOR:
                total -= w * 0.4
            if s.sihua:
                total += w * SIHUA_WEIGHT[s.sihua]

    # 本宫无主星、且对宫也无可借：这个宫确实缺主心骨
    if chart.palace(index).is_empty and not chart.palace(index).borrowed:
        total -= 2.0
    return round(total, 2)


# --------------------------------------------------------------------------
# 格局
#
# 紫微的格局是「星曜组合命中特定形状」，判断本身是机械的。难的是措辞：
# 传统格局名自带吉凶（「马头带箭」「泛水桃花」），直接抛给用户既看不懂
# 又容易吓人。所以每条格局都给三段：格名、盘上依据、白话的性质说明。
# --------------------------------------------------------------------------

def _in_triangle(chart, index, *names):
    """三方四正里是否见到这些星（任一）。"""
    return any(p.has(*names) for p in chart.triangle(index))


def _all_in_triangle(chart, index, *names):
    """三方四正里是否见齐这些星（全部）。"""
    present = {s.name for p in chart.triangle(index) for s in p.stars}
    return all(n in present for n in names)


def _sihua_in_triangle(chart, index, kind):
    """三方四正里是否有某种四化，返回命中的「星+化」描述。"""
    hits = []
    for p in chart.triangle(index):
        for s in p.stars:
            if s.sihua == kind:
                hits.append(s.name + kind)
    return hits


def patterns(chart):
    """格局判断。返回列表，每项 {格名, 性质, 依据, 说明}。

    性质分「助力」「考验」「中性」三类，而不是吉凶——同一个结构在不同
    处境下走法相反，这是 inquiry.py 那些「待定论」的来源。
    """
    out = []
    life = chart.life_index
    lp = chart.life_palace()

    def add(name, kind, basis, note):
        out.append({"格名": name, "性质": kind, "依据": basis, "说明": note})

    # ── 命宫的主星结构：整张盘的主轴 ────────────────────────
    star_names = {s.name for s in lp.majors} or {s.name for s in lp.borrowed}

    if star_names & {"七杀", "破军", "贪狼"}:
        add("杀破狼", "中性",
            "命宫坐" + "、".join(sorted(star_names & {"七杀", "破军", "贪狼"})),
            "主变动的结构。一生的转折多由自己发动，起伏比常人大——"
            "顺境里是开创力，逆境里是折腾，差别全在有没有沉淀期。")
    if star_names & {"天机", "太阴", "天同", "天梁"}:
        add("机月同梁", "中性",
            "命宫坐" + "、".join(sorted(star_names & {"天机", "太阴", "天同", "天梁"})),
            "主稳定的结构。适合有体系、有章法的场子，靠专业与耐性积累，"
            "不适合频繁换轨。")
    if not lp.majors:
        add("命无正曜", "中性",
            "命宫（{}）无主星，借对宫{}论".format(
                lp.branch, "、".join(s.name for s in lp.borrowed) or "无"),
            "空宫坐命并非不好，是性格的可塑性大、受环境影响深。"
            "同一个人在不同环境里差别会比别人明显。")

    # ── 主星得位：位置对了，同一颗星判若两人 ────────────────
    def sits(star, branch, name, note):
        p = chart.star_palace(star)
        if p and p.branch == branch and p.index == life:
            add(name, "助力", "{}坐命于{}宫，为{}".format(star, branch, name), note)

    sits("紫微", "午", "极向离明", "紫微居午为最得位之地，气度与决断都在高点。")
    sits("太阳", "午", "日丽中天", "太阳居午为全盘最亮，主外向、担当与声名。")
    sits("太阴", "亥", "月朗天门", "太阴居亥为最得位之地，主内敏、财禄与人缘。")

    zw, tf = chart.star_palace("紫微"), chart.star_palace("天府")
    if zw is tf:
        add("紫府同宫", "助力", "紫微天府同居{}宫".format(zw.branch),
            "尊星与库星同宫，格局与守成兼备，是较清晰的上升结构。")
    if _all_in_triangle(chart, life, "天府", "天相"):
        add("府相朝垣", "助力", "三方四正会天府、天相",
            "库星与印星夹辅，主稳当、有余裕，路走得比多数人平。")

    sun, moon = chart.star_palace("太阳"), chart.star_palace("太阴")
    if sun and moon:
        s_power = BRIGHTNESS_RANK[brightness_of(sun, "太阳")]
        m_power = BRIGHTNESS_RANK[brightness_of(moon, "太阴")]
        if s_power >= 4 and m_power >= 4:
            add("日月并明", "助力",
                "太阳在{}（{}）、太阴在{}（{}）俱得位".format(
                    sun.branch, brightness_of(sun, "太阳"),
                    moon.branch, brightness_of(moon, "太阴")),
                "内外两面都亮：既能对外担事，也守得住里头，是难得的均衡。")
        # 反背要求两星俱「陷」。放宽到含「平」会让三成的盘都命中——
        # 一个三成人都有的「考验」标签，除了让人不安之外没有信息量。
        elif s_power == 0 and m_power == 0:
            add("日月反背", "考验",
                "太阳在{}（{}）、太阴在{}（{}）俱失位".format(
                    sun.branch, brightness_of(sun, "太阳"),
                    moon.branch, brightness_of(moon, "太阴")),
                "两面都不占位，早年多半要靠自己摸索。这类盘走的是晚成，"
                "忌与人比进度。")

    # ── 禄与马：财路的形状 ──────────────────────────────────
    lucun = chart.star_palace("禄存")
    tianma = chart.star_palace("天马")
    if lucun is tianma:
        add("禄马交驰", "助力", "禄存与天马同居{}宫".format(lucun.branch),
            "财与动同宫，财路多在走动与外向发展里，守着不动反而滞。")
    lu_hits = _sihua_in_triangle(chart, life, "化禄")
    if lu_hits and _in_triangle(chart, life, "禄存"):
        add("双禄交流", "助力",
            "三方四正同见禄存与" + "、".join(lu_hits),
            "两重财禄呼应，进项的来路比一般人宽，也守得住。")

    three = [k for k in ("化禄", "化权", "化科")
             if _sihua_in_triangle(chart, life, k)]
    if len(three) == 3:
        add("三奇加会", "助力",
            "三方四正会齐" + "、".join(
                h for k in three for h in _sihua_in_triangle(chart, life, k)),
            "禄权科三化俱会，是紫微里分量最重的助力格——机会、话事权与"
            "名分三样齐备。")

    # ── 火贪铃贪：爆发型结构 ────────────────────────────────
    tanlang = chart.star_palace("贪狼")
    if tanlang:
        if tanlang.has("火星"):
            add("火贪格", "中性", "贪狼与火星同居{}宫".format(tanlang.branch),
                "主突发的机遇与暴起暴落。来得猛，也去得快，宜在势起时落袋。")
        if tanlang.has("铃星"):
            add("铃贪格", "中性", "贪狼与铃星同居{}宫".format(tanlang.branch),
                "与火贪同类而更闷，力量走内里。适合长线蓄势，忌情绪积压。")
        if tanlang.index == life and chart.star_palace("紫微") is tanlang:
            add("桃花犯主", "考验", "紫微与贪狼同宫坐命",
                "尊星与欲望之星同宫，主见与情欲都强，容易在关系上分心。")

    # ── 文星与贵人 ──────────────────────────────────────────
    if _all_in_triangle(chart, life, "文昌", "文曲"):
        add("文星拱命", "助力", "三方四正会文昌、文曲",
            "文书、口才与才艺俱佳，靠专业表达立身的路子最顺。")
    if _all_in_triangle(chart, life, "天魁", "天钺"):
        add("魁钺拱命", "助力", "三方四正会天魁、天钺",
            "明处暗处都有人提携，关键节点上常有人拉一把。")
    if _all_in_triangle(chart, life, "左辅", "右弼"):
        add("辅弼拱命", "助力", "三方四正会左辅、右弼",
            "平辈里实际的帮手不缺，适合带团队而非单打独斗。")
    if _all_in_triangle(chart, life, "太阳", "天梁", "文昌") and \
            _in_triangle(chart, life, "禄存"):
        add("阳梁昌禄", "助力", "三方四正会太阳、天梁、文昌、禄存",
            "传统里主科名的格。走考试、资历、专业认证这条路特别顺。")

    # ── 煞星结构：这些是「用法要换」，不是「命不好」 ────────
    if lp.has("擎羊") and lp.branch == "午":
        add("马头带箭", "考验", "擎羊坐命于午宫",
            "锋锐至极的结构。冲劲极强，适合在竞争与压力里用，"
            "放在讲和气的场子里就成了伤己。")
    left, right = chart.palace(life - 1), chart.palace(life + 1)
    if left.has("擎羊", "陀罗") and right.has("擎羊", "陀罗"):
        add("羊陀夹命", "考验", "命宫前后为擎羊、陀罗所夹",
            "两侧都是消磨的力量，事情容易前后受阻。宜早断不宜久拖，"
            "把节奏放慢反而顺。")
    if left.has("火星", "铃星") and right.has("火星", "铃星"):
        add("火铃夹命", "考验", "命宫前后为火星、铃星所夹",
            "两侧都是急火，性子容易被环境点着。给自己留冷静期最要紧。")
    if lp.has("地空", "地劫") or (left.has("地空") and right.has("地劫")) \
            or (left.has("地劫") and right.has("地空")):
        add("空劫扰命", "考验", "命宫见（或前后夹）地空、地劫",
            "想法容易脱离实际，也主一场空的落差。凡事先落地小试，"
            "别一次压满。")
    ji = _sihua_in_triangle(chart, life, "化忌")
    if ji:
        add("忌星入命垣", "考验", "三方四正见" + "、".join(ji),
            "化忌所在就是这一生最执着、也最容易耗在里头的那件事。"
            "认清它是什么，比躲开它有用。")

    if lp.has("廉贞") and _in_triangle(chart, life, "天相") and \
            _in_triangle(chart, life, "擎羊"):
        add("刑囚夹印", "考验", "廉贞坐命，三方会天相、擎羊",
            "是非与锋锐同时在场，容易卷进纠纷。凡事留书面凭据最实在。")

    ju_men = chart.star_palace("巨门")
    if ju_men and ju_men.index == life and ju_men.branch in ("子", "午"):
        kind = "助力" if any(s.name == "巨门" and s.sihua in ("化禄", "化权")
                             for s in ju_men.stars) else "中性"
        add("石中隐玉", kind, "巨门坐命于{}宫".format(ju_men.branch),
            "才干藏在里头，需要时间与场合才显出来。前期容易被低估，"
            "熬过去便是一门深功夫。")

    return out


def brightness_of(palace, star_name):
    """取某宫内指定主星的亮度。"""
    for s in palace.stars:
        if s.name == star_name:
            return s.brightness
    return "平"


# --------------------------------------------------------------------------
# 四化落宫
# --------------------------------------------------------------------------

def sihua_landing(chart):
    """生年四化各落哪一宫。

    这是全盘信息密度最高的四行：化禄落哪宫是那件事顺，化忌落哪宫是那件事
    最耗心力。很多人看盘只看这四行也能说出个大概。
    """
    out = []
    for star, kind in chart.sihua.items():
        p = chart.star_palace(star)
        if p is None:
            continue
        out.append({
            "星": star,
            "化": kind,
            "落宫": p.name,
            "地支": p.branch,
            "亮度": brightness_of(p, star) if star in MAJOR_STARS else None,
            "释义": STAR_MEANINGS.get(star, ""),
        })
    order = {"化禄": 0, "化权": 1, "化科": 2, "化忌": 3}
    out.sort(key=lambda x: order[x["化"]])
    return out


# --------------------------------------------------------------------------
# 流年
# --------------------------------------------------------------------------

# 流年四化落宫的白话主题。只描述「这一年的气质」，具体落到什么事上留给人谈。
SIHUA_THEME = {
    "化禄": "顺与得。这一宫今年的事推得动，进项与机会都偏向这里。",
    "化权": "掌与争。这一宫今年有话事权，也容易起争执，强势要用在对的地方。",
    "化科": "名与誉。这一宫今年容易被看见、被认可，适合出成绩、考试、露面。",
    "化忌": "执与耗。这一宫今年最费心力，也最容易钻牛角尖。宜守不宜攻。",
}


def year_outlook(chart, year):
    """某一流年与命盘、大限的互动。给解读提供原料，不下吉凶结论。"""
    age = chart.age_in(year)
    stem = STEMS[(year - 4) % 10]
    branch = BRANCHES[(year - 4) % 12]

    # 流年命宫：流年地支所在之宫。这一宫的宫名就是今年的主题所在。
    year_palace = chart.palace(BRANCHES.index(branch))
    limit = chart.limit_at(age)
    minor = chart.minor_limit_at(age) if age >= 1 else None

    # 流年四化：同一张四化表换成流年干。落在哪个宫名上才是重点。
    fly = []
    for star, kind in transformations(stem).items():
        p = chart.star_palace(star)
        if p is None:
            continue
        fly.append({
            "星": star, "化": kind, "落宫": p.name, "地支": p.branch,
            "主题": SIHUA_THEME[kind],
        })
    order = {"化禄": 0, "化权": 1, "化科": 2, "化忌": 3}
    fly.sort(key=lambda x: order[x["化"]])

    return {
        "年份": year,
        "流年干支": stem + branch,
        "虚岁": age,
        "流年宫": year_palace.name,
        "流年宫位": year_palace.branch,
        "流年宫含义": year_palace.to_dict()["宫位含义"],
        "所行大限": (
            "{} {}–{} 虚岁".format(palace_label(limit.name), *limit.limit_ages)
            if limit else "尚未入限"
        ),
        "大限主星": (
            [s.name + (s.brightness or "") for s in limit.majors]
            or ["空宫，借" + "、".join(s.name for s in limit.borrowed)]
        ) if limit else [],
        "大限四化": (
            # 大限四化用限宫之干，这是「这十年的气质」的来源
            [{"星": s, "化": k} for s, k in transformations(limit.stem).items()]
            if limit else []
        ),
        "小限宫": minor.name if minor else "—",
        "流年四化": fly,
    }


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

# 用户最关心的六个宫。十二宫全铺开会稀释注意力，
# 而这六个恰好覆盖「事业、钱、感情、身体、人脉、心境」。
KEY_PALACES = ("命宫", "官禄", "财帛", "夫妻", "疾厄", "福德")


def analyze(chart):
    """完整分析结果。与 chart.to_dict() 合并即为解读的全部输入。"""
    return {
        "命宫格局": palace_view(chart, "命宫"),
        "重点宫位": [palace_view(chart, n) for n in KEY_PALACES],
        "格局": patterns(chart),
        "生年四化落宫": sihua_landing(chart),
        "命身主": {
            "命主": {"星": chart.life_lord,
                     "释义": STAR_MEANINGS.get(chart.life_lord, "")},
            "身主": {"星": chart.body_lord,
                     "释义": STAR_MEANINGS.get(chart.body_lord, "")},
        },
        "宫位力量": {
            p.name: _palace_power(chart, p.index) for p in chart.palaces
        },
    }
