"""财富指数报告：一个生辰，八字与紫微两张盘合看，只回答「钱」这一件事。

这个模块只做组合与取材，不重新发明排盘——四柱、十神、喜用、十二宫、四化
全部来自 bazi/ 与 ziwei/ 两个引擎。两个站点共用同一套排盘内核，修一处
两边同时生效，不会出现「同一个生辰，主站和财富站排出两张盘」的事故。

输出由六块组成，每块都能落到盘上的具体字：

    财富指数   八字「财富机遇」+ 紫微「财富机遇」+ 财富五力，合成后归一
    财富五力   正财 / 偏财 / 守财 / 创富 / 贵人，各自带依据
    财富品阶   按随机命盘的实测分布定位次（「胜过 X% 的命盘」）
    一生财运   逐步大运的财运起伏，标出高峰期与当下
    近三年     流年财运星级，八字流年十神 + 紫微流年四化
    招财指南   喜用五行对应的方位、颜色、数字、行业，天乙贵人对应的生肖

口径上沿用主站的几条硬约束：

* 分数夹在 38–96，没有 0 分也没有满分；
* 每一项都给「依据」，说清是盘上哪几个字造成的；
* 低于 52 分必须附带方向（ADVICE），只列问题不给出路是产品事故；
* 措辞避开「破财」「穷命」这类判词，只描述结构特征。
"""

from __future__ import annotations

from bazi.analysis import (
    YEAR_THEME, day_master_strength, element_scores, favorable_elements,
    pattern, ten_god_census,
)
from bazi.ganzhi import (
    BRANCH_ELEMENT, BRANCHES, HIDDEN_STEMS, STEM_ELEMENT, ZODIAC, _NOBLE,
    ten_god,
)
from bazi.scoring import _bell, score_chart as bazi_scores
from ziwei.analysis import _palace_power, palace_view, patterns
from ziwei.scoring import score_chart as ziwei_scores
from ziwei.stars import LUCKY_STARS, palace_label, transformations

from .calibration import CDF, COMPOSITE, FORCES

FLOOR, CEIL = 38, 96
TARGET_MEDIAN, TARGET_SPREAD = 68.0, 12.0

FORCE_NAMES = ("正财力", "偏财力", "守财力", "创富力", "贵人财")

FORCE_HINTS = {
    "正财力": "主业与固定进项",
    "偏财力": "投资副业与机遇",
    "守财力": "存得住攒得下",
    "创富力": "以手艺创意变现",
    "贵人财": "平台与人脉之财",
}

# 分数偏低时附一句方向。和主站同一条规矩：不给出路的低分是产品事故。
ADVICE = {
    "正财力": "固定薪资不是你最顺的那条路，与其死守一份工资，不如尽早给自己"
              "攒一门能单独计价的本事。",
    "偏财力": "偏财不是你的强项，快进快出的机会看着诱人，于你多半是成本。"
              "钱放在看得懂、拿得住的地方。",
    "守财力": "进账不难，难在留住。先定好每月固定转出的比例，再谈消费与投资，"
              "顺序一反，钱就容易过手即空。",
    "创富力": "单靠自己的手艺变现偏吃力，宜借平台、借团队把产出放大，"
              "而不是一个人硬扛全部环节。",
    "贵人财": "贵人运偏淡，财路更多要靠自己闯。合作之前把权责写清楚，"
              "比指望有人拉一把可靠。",
}

# 财库：财星五行的墓库之支。原局见之，传统上称「带财库」。
# 土的墓库历来有辰、戌两说，这里取「水土同宫」一派的辰。
TREASURY = {"木": "未", "火": "戌", "土": "辰", "金": "丑", "水": "辰"}

# ── 招财指南：五行对应 ─────────────────────────────────────
# 河图数：天一生水、地二生火、天三生木、地四生金、天五生土，各配成数。
LUCKY = {
    "木": {"方位": "东方", "颜色": ["青", "翠绿"], "数字": [3, 8],
           "行业": ["教育培训", "文化出版", "医药健康", "设计", "园艺农林"]},
    "火": {"方位": "南方", "颜色": ["朱红", "紫"], "数字": [2, 7],
           "行业": ["互联网", "传媒直播", "能源电力", "餐饮", "美业"]},
    "土": {"方位": "东北 · 西南", "颜色": ["明黄", "驼色"], "数字": [5, 0],
           "行业": ["地产建筑", "仓储物流", "农业", "咨询中介", "政务服务"]},
    "金": {"方位": "西方", "颜色": ["白", "香槟金"], "数字": [4, 9],
           "行业": ["金融财务", "法律", "机械制造", "汽车", "科技硬件"]},
    "水": {"方位": "北方", "颜色": ["玄黑", "深蓝"], "数字": [1, 6],
           "行业": ["贸易", "航运物流", "旅游", "水产饮品", "咨询传播"]},
}

# 紫微财帛宫主星：这颗星说的是「钱从哪条路来、怎么花」。
WEALTH_STAR_NOTES = {
    "紫微": "帝星坐财，财随地位来。做主导者、掌一摊事，收入才放得开。",
    "天机": "智星坐财，以脑生财。策划、技术、理财算计都在行，收入随变化起伏。",
    "太阳": "先名后利。财来自声望与付出，越公开、越服务大众，钱越顺。",
    "武曲": "正财星归位。靠实干与专业换钱，金融、实业皆宜，理财果断。",
    "天同": "福星坐财，钱来得不费劲。难处不在赚，而在肯不肯主动经营。",
    "廉贞": "财在交际与规划里。有章法、有制度的行业最稳，正路求财最旺。",
    "天府": "财库之星。善守善积，宜稳健理财与置产，是攒钱的命。",
    "太阴": "富星坐财，细水长流。宜不动产与长期储蓄，越久越见厚度。",
    "贪狼": "偏财之星。财来自多方机缘与人脉，善抓机会者得之，守株者失之。",
    "巨门": "以口生财。靠口才、专业知识与竞争得财，越是讲究专业的场子越有利。",
    "天相": "财在信用与协作。替人打理、做服务性的事最顺，名声就是本钱。",
    "天梁": "荫星坐财，财来自资历与庇护。专业服务、医疗保险类相宜，忌投机。",
    "七杀": "将星坐财，财来自开拓。大进大出，宜有计划地拼，忌孤注一掷。",
    "破军": "先破后成。财在破旧立新里，收支起伏大，手上务必留一份储备。",
}

STABLE_STARS = ("武曲", "天府", "太阴", "天相")
VENTURE_STARS = ("贪狼", "破军", "七杀")
KEEPER_STARS = ("天府", "禄存", "太阴")

# ── 品阶与类型 ─────────────────────────────────────────────

# 按「胜过多少命盘」分五品。最低一档叫「蓄势」而不是「下品」——
# 结构偏弱说的是路径不同，不是一辈子没钱。
TIERS = (
    (95, "一品", "鼎食", "钟鸣鼎食之格。财星有根、守得住、又有机缘，百中难得几张。"),
    (80, "二品", "金玉", "金玉满堂之格。财路清楚、底子厚，顺势而为即可放大。"),
    (55, "三品", "丰盈", "丰盈有余之格。财源不缺，关键在选对主路、守住节奏。"),
    (25, "四品", "殷实", "殷实安稳之格。财来得稳而不急，靠积累一步步走厚。"),
    (0, "五品", "蓄势", "蓄势待发之格。财运起步偏晚，走的是先养本事、后见收成的路。"),
)

ARCHETYPES = {
    "正财力": ("主业聚财型", "钱跟着本职走。把一份事业做深做久，收入会像复利一样往上走。"),
    "偏财力": ("机遇捕手型", "对机会的嗅觉比别人灵。财在出手的时机里，难在克制与止盈。"),
    "守财力": ("聚宝守成型", "天生会攒钱。别人赚得快，你留得多——时间站在你这边。"),
    "创富力": ("才华变现型", "本事就是印钞机。手艺、作品、内容，都能变成钱。"),
    "贵人财": ("贵人提携型", "财路上总有人搭手。选对平台、跟对人，比单打独斗快得多。"),
}

KEYWORDS = {
    "正财力": "细水长流", "偏财力": "机遇之财", "守财力": "积厚成丰",
    "创富力": "以才生财", "贵人财": "贵人提携",
}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _clamp(v):
    return int(round(max(FLOOR, min(CEIL, v))))


def _normalize(raw, calib):
    mean, spread = calib
    if spread <= 0:
        return raw
    return TARGET_MEDIAN + (raw - mean) * TARGET_SPREAD / spread


def _band(score):
    if score >= 82:
        return "极强"
    if score >= 70:
        return "强"
    if score >= 58:
        return "中上"
    if score >= 48:
        return "平稳"
    return "待发力"


def percentile(score):
    """财富指数在随机命盘里「胜过」的百分比（1–99），查实测分布表。"""
    i = int(round(score)) - FLOOR
    return CDF[max(0, min(len(CDF) - 1, i))]


def _tier(pct):
    for floor, rank, name, desc in TIERS:
        if pct >= floor:
            return {"品阶": rank, "名号": name, "释义": desc}
    return {"品阶": TIERS[-1][1], "名号": TIERS[-1][2], "释义": TIERS[-1][3]}


# --------------------------------------------------------------------------
# 取材
# --------------------------------------------------------------------------

class _Bazi:
    """八字一侧评财需要的材料，一次取全。"""

    def __init__(self, chart):
        self.chart = chart
        self.strength = day_master_strength(chart)
        self.roles = self.strength["五行角色"]
        scores, _ = element_scores(chart)
        total = sum(scores.values()) or 1.0
        self.r = {k: scores[v] / total for k, v in self.roles.items()}
        self.balance = self.strength["扶抑比"]
        self.fav = favorable_elements(chart)
        census = ten_god_census(chart)
        ctotal = sum(census.values()) or 1.0
        self.god = lambda n: census.get(n, 0.0) / ctotal   # noqa: E731
        self.shensha = chart.to_dict()["神煞"]
        self.cai = self.roles["财"]
        self.cai_fav = self.cai in self.fav["喜用"]
        self.cai_ji = self.cai in self.fav["忌神"]
        self.ss_fav = self.roles["食伤"] in self.fav["喜用"]
        self.ss_ji = self.roles["食伤"] in self.fav["忌神"]
        ds = chart.day_stem
        self.stem_gods = [ten_god(ds, p.stem) for p in chart.pillars
                          if p is not chart.day]
        self.treasury = TREASURY[self.cai]
        self.has_treasury = self.treasury in chart.branches


class _Ziwei:
    """紫微一侧评财需要的材料。"""

    def __init__(self, chart):
        self.chart = chart
        self.power = {p.name: _palace_power(chart, p.index) for p in chart.palaces}
        self.cai = chart.by_name("财帛")
        self.tian = chart.by_name("田宅")
        self.pats = {p["格名"] for p in patterns(chart)}

    def own(self, palace):
        """本宫主星；空宫则取借来的对宫主星。"""
        stars = palace.majors or palace.borrowed
        return [s.name for s in stars]

    def tri_has(self, palace_name, *names):
        p = self.chart.by_name(palace_name)
        return [n for n in names
                if any(q.has(n) for q in self.chart.triangle(p.index))]

    def tri_sihua(self, palace_name, kind):
        p = self.chart.by_name(palace_name)
        return [s.name for q in self.chart.triangle(p.index)
                for s in q.stars if s.sihua == kind]

    def own_sihua(self, palace, kind):
        return [s.name for s in palace.stars if s.sihua == kind]


# --------------------------------------------------------------------------
# 财富五力
# --------------------------------------------------------------------------

def _raw_forces(bz, zw):
    """五力原始分与依据。原始分不截断，归一在外面做。"""
    out = {}
    pl = palace_label

    # ── 正财力：主业与固定进项 ─────────────────────────────
    v, why = 0.0, []
    zc = bz.god("正财")
    g = 12 * _bell(zc, 0.12, 0.12)
    v += g
    if zc >= 0.08:
        why.append("八字正财有根，收入以稳定进项为主，越做越厚")
    elif zc < 0.02:
        why.append("八字正财不显，固定薪资不是你最主要的财源")
    if "正财" in bz.stem_gods:
        v += 4
        why.append("正财透干，赚钱的路子摆在明处，一份事业能吃很久")
    if bz.god("正官") > 0.06 and zc > 0.05:
        v += 3
        why.append("财官相生，主业越稳，收入越稳")
    if bz.cai_fav:
        v += 5
        why.append("财星为喜用，正路得来的钱守得住")
    elif bz.cai_ji:
        v -= 4
        why.append("财星属忌神，收入宜求稳不求猛")
    pg = zw.power["官禄"]
    v += 0.6 * (pg - 12)
    if pg >= 16:
        why.append("紫微官禄宫力量足，事业是你最可靠的提款机")
    elif pg <= 7:
        why.append("紫微官禄宫偏弱，主业上宜借平台之力")
    stable = [s for s in zw.own(zw.cai) if s in STABLE_STARS]
    if stable:
        v += 4
        why.append("财帛宫见{}，正路求财最顺".format("、".join(stable)))
    out["正财力"] = (v, why)

    # ── 偏财力：投资、副业与机遇 ───────────────────────────
    v, why = 0.0, []
    pc = bz.god("偏财")
    g = 12 * _bell(pc, 0.12, 0.12)
    v += g
    if pc >= 0.08:
        why.append("八字偏财有力，机会之财、副业之财都比常人多")
    elif pc < 0.02:
        why.append("八字偏财不显，意外之财少，财更多来自本业")
    if "偏财" in bz.stem_gods:
        v += 4
        why.append("偏财透干，看得见机会，也敢出手")
    if bz.r["食伤"] > 0.08 and bz.r["财"] > 0.08:
        v += 3
        why.append("食伤生财，点子能变成钱")
    if "驿马" in bz.shensha:
        v += 2
        why.append("命带驿马，财在走动与外向发展中")
    if bz.r["比劫"] > 0.30 and bz.r["财"] < 0.12:
        v -= 4
        why.append("比劫重而财轻，合伙投资宜格外谨慎")
    venture = zw.tri_has("财帛", *VENTURE_STARS)
    if venture:
        v += 3
        why.append("财帛宫三方会{}，敢闯敢拼，财有爆发力".format("、".join(venture)))
    if "禄马交驰" in zw.pats:
        v += 5
        why.append("紫微「禄马交驰」，财与动同宫，越走动越有财")
    burst = {"火贪格", "铃贪格"} & zw.pats
    if burst:
        v += 4
        why.append("紫微成「{}」，偏财有突发之象，宜见好就收".format("、".join(sorted(burst))))
    lu = zw.tri_sihua("财帛", "化禄")
    if lu:
        v += 3
        why.append("{}化禄会入财帛宫，财路上有实际的顺势".format("、".join(lu)))
    void = [s.name for s in zw.cai.stars if s.name in ("地空", "地劫")]
    if void:
        v -= 4
        why.append("{}入财帛宫，偏财来去如风，不宜重仓".format("、".join(void)))
    out["偏财力"] = (v, why)

    # ── 守财力：存得住 ─────────────────────────────────────
    v, why = 0.0, []
    g = 10 * _bell(bz.balance, 0.5, 0.3)
    v += g
    if g > 6:
        why.append("日主与财星力量相当，赚得到也担得起")
    if bz.balance < 0.35 and bz.r["财"] > 0.25:
        v -= 6
        why.append("财多身弱，钱过手容易留不住，宜先固本")
    if bz.has_treasury:
        v += 6
        why.append("命带财库（{}），天生有攒钱的底子".format(bz.treasury))
    if bz.r["比劫"] > 0.32:
        v -= 5
        why.append("比劫偏重，钱容易被身边人分走，借贷担保要慎")
    pt = zw.power["田宅"]
    v += 0.6 * (pt - 12)
    if pt >= 16:
        why.append("紫微田宅宫力量足，积蓄与置产都有利")
    elif pt <= 7:
        why.append("紫微田宅宫偏弱，资产宜分散存放、少动大额")
    keep = sorted({s.name for p in (zw.cai, zw.tian) for s in p.stars
                   if s.name in KEEPER_STARS})
    if keep:
        v += 4
        why.append("{}坐守财帛或田宅，主积蓄".format("、".join(keep)))
    ji = zw.own_sihua(zw.cai, "化忌") + zw.own_sihua(zw.tian, "化忌")
    if ji:
        v -= 5
        why.append("{}化忌坐财帛或田宅，对钱容易执着，收支务必留余地".format(
            "、".join(ji)))
    if any(zw.tian.has(n) for n in ("地空", "地劫")):
        v -= 3
        why.append("空劫入田宅，大额资产忌频繁腾挪")
    out["守财力"] = (v, why)

    # ── 创富力：以才生财 ───────────────────────────────────
    v, why = 0.0, []
    g = 12 * _bell(bz.r["食伤"], 0.18, 0.15)
    v += g
    if g > 7:
        why.append("食伤有力，手艺与创意本身就能卖钱")
    elif bz.r["食伤"] < 0.05:
        why.append("食伤偏弱，单凭个人产出变现较吃力")
    if bz.ss_fav:
        v += 5
        why.append("食伤为喜用，越输出越有回报")
    elif bz.ss_ji:
        v -= 3
        why.append("食伤属忌神，表达宜收着用，重质不重量")
    if bz.god("食神") > 0.08 and bz.r["财"] > 0.08:
        v += 3
        why.append("食神生财，靠口碑与作品慢慢做大")
    pm = zw.power["命宫"]
    v += 0.5 * (pm - 12)
    if pm >= 16:
        why.append("紫微命宫力量足，个人能力是最大的本钱")
    quan = zw.tri_sihua("财帛", "化权") + zw.tri_sihua("官禄", "化权")
    if quan:
        v += 3
        why.append("{}化权会财官，有话事权就有收入".format("、".join(sorted(set(quan)))))
    out["创富力"] = (v, why)

    # ── 贵人财：平台与人脉 ─────────────────────────────────
    v, why = 0.0, []
    if "天乙贵人" in bz.shensha:
        v += 6
        why.append("命带天乙贵人（{}），关键时刻有人拉一把".format(
            "".join(bz.shensha["天乙贵人"])))
    g = 6 * _bell(bz.r["印"], 0.18, 0.14)
    v += g
    if g > 4:
        why.append("印星有力，有长辈与平台托底")
    if bz.god("正官") > 0.06:
        v += 2
        why.append("正官有气，体制与规则于你是助力")
    helpers = sorted(set(
        zw.tri_has("财帛", *LUCKY_STARS) + zw.tri_has("命宫", *LUCKY_STARS)))
    if helpers:
        v += min(8, 2.0 * len(helpers))
        why.append("紫微财帛、命宫三方会{}，财路上有人搭手".format("、".join(helpers)))
    else:
        why.append("紫微财帛、命宫三方不见六吉，财路更多靠自己")
    pf = zw.power["交友"]
    v += 0.4 * (pf - 12)
    if pf >= 16:
        why.append("紫微交友宫力量足，朋友圈本身就是资源")
    out["贵人财"] = (v, why)

    return out


def raw_scores(bz_chart, zw_chart):
    """未经归一的原始分。仅供校准脚本与测试使用。"""
    bz, zw = _Bazi(bz_chart), _Ziwei(zw_chart)
    forces = {k: v for k, (v, _) in _raw_forces(bz, zw).items()}
    norm = [_normalize(forces[k], FORCES[k]) for k in FORCE_NAMES]
    composite = (0.35 * bazi_scores(bz_chart)["维度"]["财富机遇"]["分数"]
                 + 0.35 * ziwei_scores(zw_chart)["维度"]["财富机遇"]["分数"]
                 + 0.30 * sum(norm) / len(norm))
    return forces, composite


# --------------------------------------------------------------------------
# 一生财运曲线
# --------------------------------------------------------------------------

def _luck_curve(bz, zw, this_year):
    chart = bz.chart
    ds = chart.day_stem
    strong = bz.balance >= 0.45
    steps = []
    for lp in chart.luck_pillars[:8]:
        v, notes = 0.0, []
        elems = ((STEM_ELEMENT[lp.stem], 1.0), (BRANCH_ELEMENT[lp.branch], 1.2))
        fav_hit = [e for e, _ in elems if e in bz.fav["喜用"]]
        ji_hit = [e for e, _ in elems if e in bz.fav["忌神"]]
        for e, w in elems:
            if e in bz.fav["喜用"]:
                v += 2 * w
            elif e in bz.fav["忌神"]:
                v -= 2 * w
        gods = ((ten_god(ds, lp.stem), 1.0),
                (ten_god(ds, HIDDEN_STEMS[lp.branch][0]), 1.2))
        for tg, w in gods:
            if tg in ("正财", "偏财"):
                v += w * (2.5 if (bz.cai_fav or strong) else 0.8)
            elif tg in ("食神", "伤官"):
                v += w * (1.5 if bz.r["财"] > 0.05 else 0.5)
            elif tg in ("比肩", "劫财"):
                v += w * (1.0 if (not strong and bz.r["财"] > 0.22) else -1.5)
        names = {tg for tg, _ in gods}
        if names & {"正财", "偏财"}:
            notes.append("财星当运")
        if names & {"食神", "伤官"}:
            notes.append("食伤生财")
        if "劫财" in names and strong:
            notes.append("比劫分财")
        if fav_hit and not ji_hit:
            notes.append("喜用到位")
        elif ji_hit and not fav_hit:
            notes.append("运逢忌神")

        # 同期紫微大限：限宫之干的禄、忌落在哪里
        mid = lp.start_year + 5
        limit = zw.chart.limit_at(zw.chart.age_in(mid))
        if limit is not None:
            for star, kind in transformations(limit.stem).items():
                p = zw.chart.star_palace(star)
                if p is None:
                    continue
                if kind == "化禄" and p.name in ("财帛", "田宅", "官禄", "命宫"):
                    v += 2
                    notes.append("紫微大限化禄入{}".format(palace_label(p.name)))
                elif kind == "化忌" and p.name in ("财帛", "田宅"):
                    v -= 2
                    notes.append("紫微大限化忌入{}".format(palace_label(p.name)))

        steps.append({
            "大运": lp.gz,
            "起始虚岁": int(lp.start_age),
            "年份": [lp.start_year, lp.end_year],
            "指数": max(40, min(96, int(round(66 + v * 3.2)))),
            "要点": notes or ["平稳过渡"],
            "当下": lp.start_year <= this_year <= lp.end_year,
        })

    if steps:
        peak = max(steps, key=lambda s: s["指数"])
        peak["高峰"] = True
    return steps


# --------------------------------------------------------------------------
# 近三年流年
# --------------------------------------------------------------------------

YEAR_WEALTH = {
    "正财": "正财之年：进项稳、加薪与签约的机会多，宜把主业做扎实。",
    "偏财": "偏财之年：机会与额外进项增多，宜抓机会、忌压重注。",
    "食神": "食神之年：作品与口碑在积累，钱跟在后面来，不必急。",
    "伤官": "伤官之年：才华外放、敢想敢做，变现机会多，签字前多看一眼。",
    "比肩": "比肩之年：同行与合作者多，财宜合作共赢，分账规则先讲清。",
    "劫财": "劫财之年：开销与人情往来偏多，借贷担保这三件事今年要慎。",
    "正官": "正官之年：名分与职位先行，升职加薪往往随认可而来。",
    "七杀": "七杀之年：压力伴随机会，拼得下来是一个台阶，忌冒进。",
    "正印": "正印之年：贵人与长辈给力，宜进修、置产，靠资历换收益。",
    "偏印": "偏印之年：思虑偏多，宜深耕专业、少碰陌生领域的投资。",
}


def _year_luck(bz, zw, year):
    chart = bz.chart
    ds = chart.day_stem
    fy = chart.fleeting_year(year)
    tg = ten_god(ds, fy.stem)
    strong = bz.balance >= 0.45
    b, notes = 0.0, []

    if tg in ("正财", "偏财"):
        b += 1.5 if (bz.cai_fav or strong) else 0.6
    elif tg in ("食神", "伤官"):
        b += 0.9 if bz.r["财"] > 0.05 else 0.3
    elif tg == "劫财":
        b -= 1.0
    elif tg == "比肩":
        b += 0.4 if not strong else -0.5

    elems = (STEM_ELEMENT[fy.stem], BRANCH_ELEMENT[fy.branch])
    if any(e in bz.fav["喜用"] for e in elems):
        b += 0.7
    elif any(e in bz.fav["忌神"] for e in elems):
        b -= 0.7

    for star, kind in transformations(fy.stem).items():
        p = zw.chart.star_palace(star)
        if p is None:
            continue
        if kind == "化禄" and p.name in ("财帛", "田宅", "官禄"):
            b += 1.2
            notes.append("紫微流年{}化禄入{}，进项有实际的顺势".format(
                star, palace_label(p.name)))
        elif kind == "化权" and p.name == "财帛":
            b += 0.5
            notes.append("流年{}化权入财帛宫，理财上有主导权".format(star))
        elif kind == "化忌" and p.name in ("财帛", "田宅"):
            b -= 1.2
            notes.append("紫微流年{}化忌入{}，收支宜留余地".format(
                star, palace_label(p.name)))

    stars = max(2, min(5, int(round(3 + b))))
    verdict = {5: "大旺", 4: "旺", 3: "平稳", 2: "宜守"}[stars]

    # 星级低时说清为什么低：流年十神的主题可能本身是好事（如正官主升迁），
    # 不交代原因，用户会觉得「好事怎么才两颗星」而不信整张表。
    if any(e in bz.fav["忌神"] for e in elems) and not any(
            e in bz.fav["喜用"] for e in elems):
        notes.insert(0, "流年五行触及忌神，钱上宜稳不宜冒进")
    if stars == 2:
        notes.append("今年财务宜守：大额投资与借贷往后放，先把现金流留足")
    return {
        "年份": year,
        "干支": fy.gz,
        "生肖": ZODIAC[BRANCHES.index(fy.branch)],
        "星级": stars,
        "定调": verdict,
        "主题": YEAR_WEALTH.get(tg, YEAR_THEME.get(tg, "")),
        "紫微": notes,
    }


# --------------------------------------------------------------------------
# 解读块
# --------------------------------------------------------------------------

def _bazi_reading(bz):
    chart = bz.chart
    ds = chart.day_stem
    dm = STEM_ELEMENT[ds]
    zheng, pian = bz.god("正财"), bz.god("偏财")
    lines = ["日主{}属{}，{}克{}为财——你的财星是「{}」。".format(
        ds, dm, dm, bz.cai, bz.cai)]
    if zheng + pian < 0.04:
        lines.append("原局财星偏轻，财不在明处，靠的是本事与时运把它引出来。")
    elif zheng >= pian * 1.5:
        lines.append("正财多于偏财：钱以稳定进项为主，适合长期主义。")
    elif pian >= zheng * 1.5:
        lines.append("偏财多于正财：机会之财、经营之财是你的主场。")
    else:
        lines.append("正偏财并见：既有稳定进项，也有额外的机会之财。")
    lines.append("日主{}（扶抑比 {:.2f}）。{}".format(
        bz.strength["结论"], bz.balance,
        "身能担财，财多反而是好事。" if bz.balance >= 0.45
        else "身弱者先养身后求财，本事厚一分，能担的财就多一分。"))
    if bz.has_treasury:
        lines.append("地支见{}，为财星之库，传统上称「命带财库」。".format(bz.treasury))
    return {
        "财星": bz.cai,
        "日主": "{}{}".format(ds, dm),
        "格局": pattern(chart)["格局"],
        "喜用": bz.fav["喜用"],
        "忌神": bz.fav["忌神"],
        "要点": lines,
    }


def _ziwei_reading(zw):
    view = palace_view(zw.chart, "财帛")
    stars = zw.own(zw.cai)
    notes = [{"星": s, "解": WEALTH_STAR_NOTES[s]}
             for s in stars if s in WEALTH_STAR_NOTES]
    return {
        "落宫": "{}宫".format(view["落宫"]),
        "空宫": view["空宫"],
        "主星": stars,
        "主星解": notes,
        "会吉星": view["会吉星"],
        "会煞星": view["会煞星"],
        "四化": view["四化"],
        "格局": sorted(zw.pats & {"禄马交驰", "双禄交流", "火贪格", "铃贪格",
                                   "府相朝垣", "紫府同宫", "三奇加会", "月朗天门"}),
    }


def _guide(bz):
    use = bz.fav["喜用"][:2] or [bz.cai]
    primary = LUCKY[use[0]]
    colors, numbers, trades = [], [], []
    for e in use:
        colors += LUCKY[e]["颜色"]
        numbers += LUCKY[e]["数字"]
        trades += LUCKY[e]["行业"][:3]
    noble = _NOBLE[bz.chart.day_stem]
    return {
        "用神": use,
        "旺财方位": primary["方位"],
        "幸运色": colors[:3],
        "幸运数字": sorted(set(numbers)),
        "宜从行业": trades[:5],
        "贵人生肖": [ZODIAC[BRANCHES.index(b)] for b in noble],
        "说明": "取八字喜用五行（{}）配方位、颜色与数字；贵人生肖以日干查天乙贵人。"
                .format("、".join(use)),
    }


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def wealth_report(bz_chart, zw_chart, this_year):
    bz, zw = _Bazi(bz_chart), _Ziwei(zw_chart)
    bz_cai = bazi_scores(bz_chart)["维度"]["财富机遇"]
    zw_cai = ziwei_scores(zw_chart)["维度"]["财富机遇"]

    raw = _raw_forces(bz, zw)
    forces = {}
    for name, (r, why) in raw.items():
        s = _clamp(_normalize(r, FORCES[name]))
        why = list(why) or ["此项结构平稳，无明显偏向"]
        if s < 52:
            why.append(ADVICE[name])
        forces[name] = {"分数": s, "评级": _band(s), "释义": FORCE_HINTS[name],
                        "依据": why}

    # 合成用未截断的归一分，与校准脚本（raw_scores）同一口径
    norm_mean = sum(_normalize(raw[n][0], FORCES[n]) for n in FORCE_NAMES) / len(FORCE_NAMES)
    composite = (0.35 * bz_cai["分数"] + 0.35 * zw_cai["分数"] + 0.30 * norm_mean)
    index = _clamp(_normalize(composite, COMPOSITE))
    pct = percentile(index)
    tier = _tier(pct)

    ranked = sorted(FORCE_NAMES, key=lambda k: -forces[k]["分数"])
    best, second, worst = ranked[0], ranked[1], ranked[-1]
    arch_name, arch_desc = ARCHETYPES[best]

    curve = _luck_curve(bz, zw, this_year)
    peak = next((s for s in curve if s.get("高峰")), None)

    summary = "{}，{}。最见力的是{}（{} 分），{}".format(
        arch_name, tier["释义"].rstrip("。"),
        best, forces[best]["分数"],
        "需要补的是{}（{} 分）——知道短板在哪，就知道钱该往哪条路上放。".format(
            worst, forces[worst]["分数"])
        if forces[best]["分数"] - forces[worst]["分数"] >= 10
        else "五力分布均衡，走的是稳中求进的路。")
    if peak:
        summary += "一生财运高峰在 {}–{} 年（{}大运）。".format(
            peak["年份"][0], peak["年份"][1], peak["大运"])

    return {
        "财富指数": index,
        "胜过": pct,
        "品阶": tier,
        "类型": {"名称": arch_name, "释义": arch_desc},
        "关键词": [KEYWORDS[best], KEYWORDS[second],
                   "财星属" + bz.cai],
        "总评": summary,
        "双盘": {
            "八字": {"分数": bz_cai["分数"], "依据": bz_cai["依据"]},
            "紫微": {"分数": zw_cai["分数"], "依据": zw_cai["依据"]},
        },
        "五力": forces,
        "最强": best,
        "最弱": worst,
        "八字财星": _bazi_reading(bz),
        "紫微财帛": _ziwei_reading(zw),
        "一生财运": curve,
        "近年": [_year_luck(bz, zw, y) for y in (this_year, this_year + 1, this_year + 2)],
        "招财": _guide(bz),
        "说明": "分数表示命盘在财富上的结构相对强弱，是传统命理的一种解读框架，"
                "不构成投资建议。",
    }
