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

from .analysis import day_master_strength, element_scores, ten_god_census
from .ganzhi import (
    BRANCHES, PUNISH_GROUPS, PUNISH_PAIR, SELF_PUNISH,
    SIX_CLASH, SIX_HARM, SIX_HARMONY, THREE_HARMONY, THREE_MEETING,
)

__all__ = ["score_chart", "DIMENSIONS"]

BASE = 58.0
FLOOR, CEIL = 38, 96

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


def _bell(x, center, width):
    """离 center 越近越接近 1，超出 width 归零。用来表达「适中最好」。

    命理里很多东西不是越多越好——官杀太旺压身、财太旺身弱担不住，
    所以用钟形而不是线性。
    """
    if width <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(x - center) / width)


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

    result = {}

    # ── 事业格局 ────────────────────────────────────────────
    v, why = BASE, []
    gain = 18 * _bell(r["官杀"], 0.22, 0.16)
    v += gain
    if gain > 11:
        why.append("官杀力量适中，事业上有明确的方向感与约束力")
    elif r["官杀"] < 0.07:
        why.append("官杀偏轻，需要自己给自己立规矩，不宜久处无人管束的环境")

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
        v -= 8
        why.append("正官七杀并见，路径容易分岔，宜早定一门深入")

    if r["官杀"] > 0.34 and balance < 0.44:
        v -= 10
        why.append("官杀旺而日主偏弱，压力大于助力，忌硬扛")

    result["事业格局"] = (v, why)

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

    if r["食伤"] > 0.08 and r["财"] > 0.08:
        v += 9
        why.append("食伤生财，靠本事与创意换钱，比坐等机会有力")

    if r["财"] > 0.28 and balance < 0.42:
        v -= 12
        why.append("财旺而身弱，机会看得见抓不住，宜先固本再图大")

    if r["比劫"] > 0.30 and r["财"] < 0.12:
        v -= 8
        why.append("比劫重而财轻，合伙与借贷需格外谨慎")

    result["财富机遇"] = (v, why)

    # ── 人际助力 ────────────────────────────────────────────
    v, why = BASE - 2, []
    v += 12 * _bell(r["印"], 0.18, 0.17)
    if r["印"] > 0.12:
        why.append("印星有力，长辈与师长一路都有照应")

    v += 8 * _bell(r["比劫"], 0.22, 0.19)
    if r["比劫"] > 0.34:
        why.append("比劫偏重，平辈助力与竞争同时存在，界限要谈清楚")
    elif r["比劫"] < 0.10 and r["印"] < 0.12:
        why.append("印比俱轻，凡事多靠自己张罗，早年少现成的依靠")

    lucky = 0
    for name, w in AUSPICIOUS.items():
        if name in shensha:
            lucky += w
    if lucky:
        v += min(14, lucky)
        hit = [n for n in AUSPICIOUS if n in shensha]
        why.append("命带" + "、".join(hit) + "，关键处常有人拉一把")

    h = _harmony_count(chart)
    if h:
        v += min(9, h * 3)
        why.append("原局有{}处合会，与人相处偏和顺".format(h))

    c = _clash_count(chart)
    if c:
        v -= min(12, c * 3)
        why.append("原局有{}处刑冲害，关系上易起波折，忌意气用事".format(c))

    result["人际助力"] = (v, why)

    # ── 健康根基 ────────────────────────────────────────────
    v, why = BASE + 2, []
    # 五行占比的离散度：越均衡越稳。完全平均为 0，极端偏枯约 0.32
    props = [scores[e] / total for e in scores]
    mean = sum(props) / len(props)
    spread = (sum((p - mean) ** 2 for p in props) / len(props)) ** 0.5
    v += 18 * max(0.0, 1 - spread / 0.17)
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
        v -= min(14, 7 * len(missing))
        why.append("五行缺" + "、".join(missing) + "，对应脏腑与情志需多留意")

    if day_rel["冲"]:
        v -= 8
        why.append("日支逢冲（" + "、".join(day_rel["冲"]) + "），作息与情绪易被打断")

    if chart.month.branch in "亥子丑" and scores["火"] / total < 0.08:
        v -= 6
        why.append("生于冬月而火气不足，畏寒、循环偏弱")
    elif chart.month.branch in "巳午未" and scores["水"] / total < 0.08:
        v -= 6
        why.append("生于夏月而水气不足，易燥易耗，注意补水与睡眠")

    result["健康根基"] = (v, why)

    # ── 情感缘分 ────────────────────────────────────────────
    v, why = BASE, []
    male = chart.gender == "male"
    # 男以财为配偶星，女以官杀为配偶星
    spouse_star = r["财"] if male else r["官杀"]
    gain = 14 * _bell(spouse_star, 0.18, 0.16)
    v += gain
    if gain > 9:
        why.append("配偶星力量适中，感情节奏不急不缓")
    elif spouse_star < 0.07:
        why.append("配偶星偏轻，缘分来得晚一些，宜主动而非等待")

    if not (day_rel["冲"] or day_rel["刑"] or day_rel["害"]):
        v += 10
        why.append("配偶宫（日支）安稳未受刑冲，家宅少是非")
    if day_rel["合"]:
        v += 6
        why.append("日支逢合（" + "、".join(day_rel["合"]) + "），亲密关系有黏合力")
    if day_rel["冲"]:
        v -= 12
        why.append("日支逢冲（" + "、".join(day_rel["冲"]) + "），聚少离多或聚散反复")
    if day_rel["刑"] or day_rel["害"]:
        v -= 7
        why.append("日支带刑害，相处中细节摩擦偏多")

    if male and god("正财") > 0.5 and god("偏财") > 0.5:
        v -= 8
        why.append("正偏财并见，感情选择多，专一需要刻意为之")
    if (not male) and god("正官") > 0.5 and god("七杀") > 0.5:
        v -= 8
        why.append("官杀混杂，容易遇到反差很大的两类人，宜看长期不看一时")

    if (not male) and r["食伤"] > 0.30 and r["官杀"] < 0.10:
        v -= 6
        why.append("食伤旺而官星弱，主见强不易将就，宜找欣赏你锋芒的人")

    if "桃花" in shensha:
        v += 4
        why.append("命带桃花，异性缘不缺，选择反而更需要标准")

    from .ganzhi import empty_branches
    if chart.day.branch in empty_branches(chart.day.stem, chart.day.branch):
        v -= 5

    result["情感缘分"] = (v, why)

    # ── 汇总 ────────────────────────────────────────────────
    final = {}
    for name in DIMENSIONS:
        raw, why = result[name]
        s = _clamp(raw)
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
