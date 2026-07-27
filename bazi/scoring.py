"""命盘多维评分。

刻意不做「命格总分」。把一个人的一生压成一个数字既是虚假的精确，
也真的会伤人——而且低分用户往往直接关页面。五个维度各自评分，
每张盘都有强项，低分项自然引出「这方面该怎么借力」的追问。

分数是**结构相对强弱**，不是人生价值判断，所以：

* 起点 58 分，加减项各自封顶，最终夹在 38–96 之间。没有 0 分，也没有满分。
* 每项都带「依据」，说清是盘上哪几个字造成的——用户能验证，才可能信。
* 措辞避开「克夫」「破财」这类判词，只描述结构特征。

评分口径写死在常量里，便于日后按流派调整。
"""

from __future__ import annotations

from .analysis import (
    day_master_strength, element_scores, favorable_elements, pattern,
    ten_god_census,
)
from .ganzhi import (
    BRANCHES, PUNISH_GROUPS, PUNISH_PAIR, SELF_PUNISH,
    SIX_CLASH, SIX_HARM, SIX_HARMONY, THREE_HARMONY, THREE_MEETING,
)

__all__ = ["score_chart", "DIMENSIONS"]

BASE = 58.0
FLOOR, CEIL = 38, 96

# ── 维度间的尺度归一 ──────────────────────────────────────────
#
# 各维的规则条数与权重天然不同，原始分的散布相差很大（实测标准差从 9.3 到
# 14.2）。不归一的后果很实际：人际拿 78 分比事业拿 78 分稀有得多——前者离
# 中位数 1.0 个标准差，后者只有 0.6 个。同一个数字并排显示在雷达图上，
# 含义却不一样，用户无从比较。
#
# 所以把五维统一映射到同一中位数与同一标准差，即 IQ / SAT / 信用分那套
# 做法。归一是仿射变换，只改尺度不改形状——各维的偏度（实测 -0.07~+0.04，
# 已相当对称）与相对排序都原样保留。
#
# 注意这里**不追求正态**。实测峰度全为负（比正态平坦），这对本产品是好事：
# 正态会把多数人堆在中间、削弱区分度，平坦一些分数才摊得开。对称才是要
# 守住的性质——明显偏斜通常意味着规则有 bug（例如同一信号被罚两次），
# 那时正态检验是好用的诊断工具，但不该拿它当目标去硬凑。
#
# 常量由 4000 张随机盘的原始分（绕开截断）实测得出；改动任何规则权重后
# 都需重新测定，TestScoringCalibration 会在跑偏时报警。
TARGET_MEDIAN = 68.0
TARGET_SPREAD = 12.0

RAW_CALIBRATION = {
    "事业格局": (68.6, 14.2),
    "财富机遇": (69.3, 13.6),
    "人际助力": (68.8, 9.5),
    "健康根基": (68.0, 9.3),
    "情感缘分": (66.2, 11.4),
}

# 每一维的减分总额上限。
#
# 不封顶时同一维能叠掉近 30 分，直接把人按到底部——而那些减分项在命理上
# 往往同源（日支冲、带刑害、配偶宫空亡，说的都是「配偶宫不稳」这一件事），
# 逐条累加等于同一件事罚三次。封顶后依据仍逐条列出，不掩盖任何一条，
# 只是不让它们在分数上重复计。
PENALTY_CAP = 20

DIMENSIONS = ("事业格局", "财富机遇", "人际助力", "健康根基", "情感缘分")

# 吉神加分权重（封顶见各维度）
AUSPICIOUS = {"天乙贵人": 7, "文昌贵人": 4, "将星": 3, "华盖": 2}

# 分数偏低时补一句方向。只列问题不给出路，用户只会沮丧地关掉页面——
# 而「该怎么补」恰恰是值得当面问的东西。
ADVICE = {
    "事业格局": "这类结构宜借势而非硬闯：靠平台、靠专业资质、靠一位明确的领路人，"
                "比自立门户稳得多。",
    "财富机遇": "财路宜专不宜广，先把一门手艺做深做出口碑，钱跟着专业度来，"
                "少碰快进快出的机会。",
    "人际助力": "不必勉强扩圈，把两三个真正对路的人处深，比认识一百个人有用。"
                "合作前把权责写清楚。",
    "健康根基": "这类底子怕的是熬和耗，不是缺补品。作息规律、别硬撑，"
                "比任何调理都管用。",
    "情感缘分": "感情上宜慢不宜快，给彼此留出观察期；越是心动越要看长期，"
                "对方是否稳定可靠比一时投契重要。",
}


# 吉格（月令成格且格神得用时，路径比杂格清晰）
BENIGN_PATTERNS = ("正官格", "正印格", "正财格", "食神格", "建禄格")
# 需制化的格，无制则主波折
HARSH_PATTERNS = ("七杀格", "伤官格", "偏印格", "羊刃格")


def _bell(x, center, width):
    """离 center 越近越接近 1，超出 width 归零。用来表达「适中最好」。

    命理里很多东西不是越多越好——官杀太旺压身、财太旺身弱担不住，
    所以用钟形而不是线性。

    中心值对着 600 张随机盘的真实分布校过：官杀/财/印/食伤的力量占比
    中位数约 0.145，比劫因含日主自身而偏高（约 0.238）。中心取在中位数
    之上，表示「略多于常见水平为佳」，而不是「跟大多数人一样就好」。
    """
    if width <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(x - center) / width)


def _favor_shift(element, fav, span):
    """该五行是喜用还是忌神，折算成分数增减。

    这是子平法的核心，也是只看「力量大小」必然判错的地方：同一个十神
    是吉是凶，取决于它是喜神还是忌神。财旺，对身强是能担财，对身弱是
    破财；官杀旺，对身强是有担当，对身弱是压力压垮人。只数力量不辨喜忌，
    这两种截然相反的局会被判成同一个分数。
    """
    if element in fav["喜用"]:
        return span
    if element in fav["忌神"]:
        return -span
    return 0.0


def _normalize(name, raw):
    """把某一维的原始分映射到全站统一的中位数与散布。

    仿射变换，保形不保值：各维的偏度与盘间相对排序不变，变的只是尺度，
    使「事业 78 分」与「人际 78 分」代表同等的稀有程度。
    """
    med, spread = RAW_CALIBRATION[name]
    if spread <= 0:
        return raw
    return TARGET_MEDIAN + (raw - med) * TARGET_SPREAD / spread


def _clamp(v):
    return int(round(max(FLOOR, min(CEIL, v))))


def _band(score):
    if score >= 82:
        return "强"
    if score >= 70:
        return "较强"
    if score >= 58:
        return "中和"
    if score >= 48:
        return "偏弱"
    return "需借力"


def _day_branch_relations(chart):
    """日支（配偶宫）与其余三支的关系。感情维度最看重这里。"""
    day = chart.day.branch
    others = [p.branch for p in chart.pillars if p is not chart.day]

    out = {"冲": [], "刑": [], "害": [], "合": []}
    for b in others:
        pair = frozenset((day, b))
        if len(pair) == 1:
            if day in SELF_PUNISH:
                out["刑"].append(day + b + "自刑")
            continue
        if pair in SIX_CLASH:
            out["冲"].append(SIX_CLASH[pair] + "相冲")
        if pair in SIX_HARM:
            out["害"].append(SIX_HARM[pair] + "相害")
        if pair in SIX_HARMONY:
            out["合"].append(SIX_HARMONY[pair][0] + "相合")
        if pair == PUNISH_PAIR:
            out["刑"].append("子卯相刑")

    present = set([day] + others)
    for group in PUNISH_GROUPS:
        hit = [x for x in group if x in present]
        if day in group and len(hit) >= 2:
            out["刑"].append("".join(hit) + "相刑")
    return out


def _harmony_count(chart):
    """原局的合会数量，粗略代表人缘顺逆。"""
    present = set(chart.branches)
    n = 0
    for combo, _ in THREE_MEETING:
        if set(combo) <= present:
            n += 1
    for combo, _ in THREE_HARMONY:
        if set(combo) <= present:
            n += 1
    bs = chart.branches
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            if frozenset((bs[i], bs[j])) in SIX_HARMONY:
                n += 1
    return n


def _clash_count(chart):
    bs = chart.branches
    n = 0
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            pair = frozenset((bs[i], bs[j]))
            if len(pair) == 1:
                continue
            if pair in SIX_CLASH or pair in SIX_HARM or pair == PUNISH_PAIR:
                n += 1
    return n


def score_chart(chart):
    """五维评分。返回 {维度: {分数, 评级, 依据[]}} 加一段总述。"""
    strength = day_master_strength(chart)
    scores, _ = element_scores(chart)
    census = ten_god_census(chart)
    roles = strength["五行角色"]
    total = sum(scores.values()) or 1.0

    # 五行力量按十神角色归并，得到 0–1 的占比
    r = {k: scores[v] / total for k, v in roles.items()}
    balance = strength["扶抑比"]
    rooted = "四支无根" not in strength["得地"]

    god = lambda name: census.get(name, 0.0)      # noqa: E731
    shensha = chart.to_dict()["神煞"]
    day_rel = _day_branch_relations(chart)
    fav = favorable_elements(chart)
    pat = pattern(chart)["格局"]

    result = {}

    # ── 事业格局 ────────────────────────────────────────────
    v, why = BASE, []
    gain = 18 * _bell(r["官杀"], 0.22, 0.16)
    v += gain
    if gain > 11:
        why.append("官杀力量适中，事业上有明确的方向感与约束力")
    elif r["官杀"] < 0.07:
        why.append("官杀偏轻，需要自己给自己立规矩，不宜久处无人管束的环境")

    penalty = 0

    # 官杀是喜是忌，决定这份约束是助力还是压力——同样的官杀力量，
    # 身强者得之为担当，身弱者得之为重压
    shift = _favor_shift(roles["官杀"], fav, 7)
    if shift > 0:
        v += shift
        why.append("官杀正为喜用，责任与权力落到你身上是加分项")
    elif shift < 0:
        penalty += -shift
        why.append("官杀属忌神，头衔与责任若来得太快反成负担，宜量力承接")

    # 月令成格则路径清晰，杂格则方向易散。
    # 但正官格逢七杀即「官杀混杂」，格已不清——此时再给「路径清晰」的加分，
    # 会和下面「正官七杀并见，路径容易分岔」那条自相矛盾。
    if pat in BENIGN_PATTERNS:
        if pat == "正官格" and god("七杀") > 0.5:
            why.append("月令虽属正官格，然七杀并透、格局不清，方向要靠自己厘定")
        else:
            v += 6
            why.append("月令成{}，本业路径比多数人清晰".format(pat))
    elif pat in HARSH_PATTERNS:
        penalty += 4
        why.append("{}需有制化才见其力，顺境靠积累，逆境忌冒进".format(pat))

    # 同样做成互斥全覆盖，避免中间区间一句话都说不出来
    carry = 12 * _bell(balance, 0.52, 0.16)
    v += carry
    if carry > 8:
        why.append("日主强弱与官杀相称，担得起责任")
    elif balance >= 0.52:
        why.append("日主偏旺，能扛事但不受管，适合有自主权的位置")
    else:
        why.append("日主偏弱，宜先借平台与团队之力，不宜过早独当一面")

    if r["印"] > 0.10 and r["官杀"] > 0.10:
        v += 8
        why.append("官印相生，有名分也有支撑，是较清晰的上升结构")

    if god("正官") > 0.5 and god("七杀") > 0.5:
        penalty += 8
        why.append("正官七杀并见，路径容易分岔，宜早定一门深入")

    if r["官杀"] > 0.34 and balance < 0.44:
        penalty += 10
        why.append("官杀旺而日主偏弱，压力大于助力，忌硬扛")

    result["事业格局"] = (v - min(PENALTY_CAP, penalty), why)

    # ── 财富机遇 ────────────────────────────────────────────
    v, why = BASE, []
    gain = 16 * _bell(r["财"], 0.20, 0.16)
    v += gain
    if gain > 10:
        why.append("财星力量适中，取财路径清楚")
    elif r["财"] < 0.11:
        why.append("财星偏轻，财富更多来自专业与口碑的累积，不宜投机")
    elif r["财"] > 0.30:
        why.append("财星偏重，机会不缺，难在取舍与守成")

    # 三个分支互斥且覆盖全区间，任何盘都至少落一条，
    # 否则会出现「此项无突出特征」这种等于没说的输出
    fit = 12 * (1 - min(1.0, abs(balance - 0.5) / 0.26))
    v += fit
    if fit > 8:
        why.append("身与财相当，赚多少守得住多少")
    elif balance >= 0.5:
        why.append("日主偏旺而财偏轻，须主动出击去赚，坐等分红不适合你")
    else:
        why.append("日主偏弱而财不轻，宜先把自己这一头养厚，再谈放大")

    penalty = 0

    # 财是喜是忌，决定同样的财星力量是能担还是被压
    shift = _favor_shift(roles["财"], fav, 7)
    if shift > 0:
        v += shift
        why.append("财星正为喜用，赚到的守得住，宜早立主业")
    elif shift < 0:
        penalty += -shift
        why.append("财星属忌神，进项越猛越要留出余地，忌加杠杆放大")

    if r["食伤"] > 0.08 and r["财"] > 0.08:
        v += 9
        why.append("食伤生财，靠本事与创意换钱，比坐等机会有力")

    if r["财"] > 0.28 and balance < 0.42:
        penalty += 12
        why.append("财旺而身弱，机会看得见抓不住，宜先固本再图大")

    if r["比劫"] > 0.30 and r["财"] < 0.12:
        penalty += 8
        why.append("比劫重而财轻，合伙与借贷需格外谨慎")

    result["财富机遇"] = (v - min(PENALTY_CAP, penalty), why)

    # ── 人际助力 ────────────────────────────────────────────
    # 这一维曾经形同虚设：600 张样本里最低 52 分、标准差仅 7.2，人人中上。
    # 原因有二——比劫钟形中心恰好压在中位数上（几乎人人拿满），
    # 且加分上限远高于减分上限。下面把中心移开、把上下限拉平。
    v, why = BASE - 4, []
    v += 12 * _bell(r["印"], 0.18, 0.17)
    if r["印"] > 0.12:
        why.append("印星有力，长辈与师长一路都有照应")

    v += 9 * _bell(r["比劫"], 0.26, 0.16)
    if r["比劫"] > 0.38:
        why.append("比劫偏重，平辈助力与竞争同时存在，界限要谈清楚")
    elif r["比劫"] < 0.12 and r["印"] < 0.12:
        why.append("印比俱轻，凡事多靠自己张罗，早年少现成的依靠")

    penalty = 0

    # 印为喜用则长辈之力真能落到实处，为忌则易受人情牵绊
    shift = _favor_shift(roles["印"], fav, 5)
    if shift > 0:
        v += shift
    elif shift < 0:
        penalty += -shift
        why.append("印星属忌神，他人的好意有时反成牵绊，边界要自己守")

    lucky = 0
    for name, w in AUSPICIOUS.items():
        if name in shensha:
            lucky += w
    if lucky:
        v += min(10, lucky)
        hit = [n for n in AUSPICIOUS if n in shensha]
        why.append("命带" + "、".join(hit) + "，关键处常有人拉一把")

    h = _harmony_count(chart)
    if h:
        v += min(9, h * 3)
        why.append("原局有{}处合会，与人相处偏和顺".format(h))

    c = _clash_count(chart)
    if c:
        penalty += min(16, c * 4)
        why.append("原局有{}处刑冲害，关系上易起波折，忌意气用事".format(c))

    result["人际助力"] = (v - min(PENALTY_CAP, penalty), why)

    # ── 健康根基 ────────────────────────────────────────────
    v, why = BASE + 2, []
    # 五行占比的离散度：越均衡越稳。完全平均为 0，极端偏枯约 0.32
    props = [scores[e] / total for e in scores]
    mean = sum(props) / len(props)
    spread = (sum((p - mean) ** 2 for p in props) / len(props)) ** 0.5
    penalty = 0
    # 权重从 18 提到 22：这一维原先标准差只有 8.9，是五维里最窄的，
    # 而五行是否偏枯恰恰是健康维度最有分辨力的信号，值得给足权重
    v += 22 * max(0.0, 1 - spread / 0.17)
    if spread < 0.07:
        why.append("五行分布均衡，身体底子偏稳")
    elif spread > 0.14:
        why.append("五行明显偏枯，精力起伏大，作息比进补更要紧")

    if rooted:
        v += 10
        why.append("日主通根，恢复力不差")
    else:
        why.append("日主四支无根，耐受力有限，忌长期硬撑")

    if strength["得令"]:
        v += 5

    missing = [e for e in scores if scores[e] / total < 0.05]
    if missing:
        penalty += min(14, 7 * len(missing))
        why.append("五行缺" + "、".join(missing) + "，对应脏腑与情志需多留意")

    if day_rel["冲"]:
        penalty += 8
        why.append("日支逢冲（" + "、".join(day_rel["冲"]) + "），作息与情绪易被打断")

    if chart.month.branch in "亥子丑" and scores["火"] / total < 0.08:
        penalty += 6
        why.append("生于冬月而火气不足，畏寒、循环偏弱")
    elif chart.month.branch in "巳午未" and scores["水"] / total < 0.08:
        penalty += 6
        why.append("生于夏月而水气不足，易燥易耗，注意补水与睡眠")

    result["健康根基"] = (v - min(PENALTY_CAP, penalty), why)

    # ── 情感缘分 ────────────────────────────────────────────
    # 起点比其他维度高 6 分，是为了抵掉一处重复计分：样本里 54.5% 的盘
    # 日支带刑冲害，这些盘原先既拿不到「宫位安稳」的加分、又要再吃一次
    # 减分，同一个信号计了两次，导致这一维低分率是其他维度的三四倍。
    # 现在把安稳视作常态（加分调小），刑冲只从减分一侧生效。
    v, why = BASE + 6, []
    male = chart.gender == "male"
    # 男以财为配偶星，女以官杀为配偶星
    spouse_star = r["财"] if male else r["官杀"]
    gain = 14 * _bell(spouse_star, 0.18, 0.16)
    v += gain
    if gain > 9:
        why.append("配偶星力量适中，感情节奏不急不缓")
    elif spouse_star < 0.07:
        why.append("配偶星偏轻，缘分来得晚一些，宜主动而非等待")

    penalty = 0

    # 配偶星是喜是忌，比它力量多少更能说明关系带来的是滋养还是消耗
    shift = _favor_shift(roles["财"] if male else roles["官杀"], fav, 6)
    if shift > 0:
        v += shift
        why.append("配偶星正为喜用，伴侣多能带来实际的助益")
    elif shift < 0:
        penalty += -shift
        why.append("配偶星属忌神，亲密关系里容易过度付出，需留出自己的空间")

    if day_rel["合"]:
        v += 6
        why.append("日支逢合（" + "、".join(day_rel["合"]) + "），亲密关系有黏合力")

    if not (day_rel["冲"] or day_rel["刑"] or day_rel["害"]):
        v += 4
        why.append("配偶宫（日支）安稳未受刑冲，家宅少是非")
    if day_rel["冲"]:
        penalty += 12
        why.append("日支逢冲（" + "、".join(day_rel["冲"]) + "），聚少离多或聚散反复")
    if day_rel["刑"] or day_rel["害"]:
        penalty += 7
        why.append("日支带刑害，相处中细节摩擦偏多")

    if male and god("正财") > 0.5 and god("偏财") > 0.5:
        penalty += 8
        why.append("正偏财并见，感情选择多，专一需要刻意为之")
    if (not male) and god("正官") > 0.5 and god("七杀") > 0.5:
        penalty += 8
        why.append("官杀混杂，容易遇到反差很大的两类人，宜看长期不看一时")

    if (not male) and r["食伤"] > 0.30 and r["官杀"] < 0.10:
        penalty += 6
        why.append("食伤旺而官星弱，主见强不易将就，宜找欣赏你锋芒的人")

    from .ganzhi import empty_branches
    if chart.day.branch in empty_branches(chart.day.stem, chart.day.branch):
        penalty += 5
        why.append("配偶宫落空亡，感情上易有「差一点」的遗憾，宜晚婚")

    if "桃花" in shensha:
        v += 4
        why.append("命带桃花，异性缘不缺，选择反而更需要标准")

    result["情感缘分"] = (v - min(PENALTY_CAP, penalty), why)

    # ── 汇总 ────────────────────────────────────────────────
    final = {}
    for name in DIMENSIONS:
        raw, why = result[name]
        s = _clamp(_normalize(name, raw))
        why = list(why) or ["此项无突出特征，五行力量分布平均，属中和之局"]
        if s < 52:
            why.append(ADVICE[name])
        final[name] = {"分数": s, "评级": _band(s), "依据": why}

    ranked = sorted(DIMENSIONS, key=lambda k: -final[k]["分数"])
    best, worst = ranked[0], ranked[-1]
    gap = final[best]["分数"] - final[worst]["分数"]

    if gap < 10:
        summary = ("五项分布均衡，没有特别突出的短板，也没有一骑绝尘的长处——"
                   "这类盘走的是稳，忌大起大落的选择。")
    else:
        summary = ("最见力的是**{}**（{} 分），最需要借力的是**{}**（{} 分）。"
                   "命理讲的是倾向：强项顺势用，弱项知道了就能提前补。").format(
            best, final[best]["分数"], worst, final[worst]["分数"])

    return {
        "维度": final,
        "最强": best,
        "最弱": worst,
        "总述": summary,
        "说明": "分数表示命盘在该方面的结构相对强弱，不是人生价值判断。",
    }
