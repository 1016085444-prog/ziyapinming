"""紫微命盘多维评分。

与八字那套评分同一条原则，理由也一样：**刻意不做「命格总分」**。把一生
压成一个数字既是虚假的精确，也真的会伤人——低分用户往往直接关页面。
分维度看，每张盘都有强项，弱项才好谈怎么补。

紫微评分比子平天然顺一层：十二宫本来就是分领域的，官禄宫管事业、财帛宫
管钱、夫妻宫管感情，不需要像子平那样从五行力量里反推领域。所以这里每一维
都锚在一个主宫上，再取两个相关宫作辅。

多出的一维是**心性福分**（福德宫）。子平没有对应的东西，而这恰是紫微
最见长处的一块：一个人过得舒不舒服，和他事业财富的高低是两件事。
"""

from __future__ import annotations

from .analysis import AUSPICIOUS_MINOR, INAUSPICIOUS_MINOR, patterns
from .stars import BRIGHTNESS_RANK, LUCKY_STARS, MALEFIC_STARS, palace_label

__all__ = ["score_chart", "DIMENSIONS"]

BASE = 58.0
FLOOR, CEIL = 38, 96

DIMENSIONS = ("事业格局", "财富机遇", "情感缘分", "人际助力", "健康根基", "心性福分")

# 每一维锚定的宫位：(主宫, 辅宫, 辅宫)。主宫权重最高。
# 组合不是随手配的——譬如财富取「财帛 + 田宅 + 福德」，因为财帛是进项、
# 田宅是留存、福德是花钱的态度，三者缺一都说不清一个人的财务面貌。
DIMENSION_PALACES = {
    "事业格局": ("官禄", "命宫", "迁移"),
    "财富机遇": ("财帛", "田宅", "福德"),
    "情感缘分": ("夫妻", "子女", "福德"),
    "人际助力": ("交友", "兄弟", "父母"),
    "健康根基": ("疾厄", "命宫", "父母"),
    "心性福分": ("福德", "命宫", "田宅"),
}
PALACE_WEIGHTS = (1.0, 0.45, 0.35)

# ── 维度间的尺度归一 ──────────────────────────────────────────
#
# 各维的规则条数与锚定宫位不同，原始分的散布天然不一致。不归一的后果很
# 实际：情感拿 78 分比事业拿 78 分稀有得多，同一个数字并排放在雷达图上
# 含义却不一样，用户无从比较。所以统一到同一中位数与同一散布，
# 即 IQ / 信用分那套做法——仿射变换只改尺度不改形状。
#
# 常量由 6000 张随机盘的原始分实测得出（绕开截断），改动任何规则权重后
# 都需重新测定，TestZiweiScoringCalibration 会在跑偏时报警。
TARGET_MEDIAN = 68.0
TARGET_SPREAD = 12.0

RAW_CALIBRATION = {
    "事业格局": (79.6, 10.3),
    "财富机遇": (77.2, 7.2),
    "情感缘分": (75.1, 5.8),
    "人际助力": (77.7, 8.0),
    "健康根基": (74.6, 6.1),
    "心性福分": (74.4, 6.9),
}

# 每一维的减分总额上限。不封顶时同一维能叠掉近三十分，直接把人按到底部——
# 而那些减分项在紫微上往往同源（宫内见煞、对宫见煞、三合见煞，说的都是
# 「这一宫煞重」这一件事），逐条累加等于同一件事罚三次。封顶后依据仍逐条
# 列出，不掩盖任何一条，只是不让它们在分数上重复计。
PENALTY_CAP = 20

# 分数偏低时补一句方向。只列问题不给出路，用户只会沮丧地关掉页面——
# 而「该怎么补」恰恰是值得当面问的东西。
ADVICE = {
    "事业格局": "这类结构宜借势而非硬闯：靠平台、靠专业资质、靠一位明确的"
                "领路人，比自立门户稳得多。",
    "财富机遇": "财路宜专不宜广，先把一门手艺做深做出口碑，钱跟着专业度来，"
                "少碰快进快出的机会。",
    "情感缘分": "感情上宜慢不宜快，给彼此留出观察期；越是心动越要看长期，"
                "对方是否稳定可靠比一时投契重要。",
    "人际助力": "不必勉强扩圈，把两三个真正对路的人处深，比认识一百个人"
                "有用。合作前把权责写清楚。",
    "健康根基": "这类底子怕的是熬和耗，不是缺补品。作息规律、别硬撑，"
                "比任何调理都管用。",
    "心性福分": "心里的余裕是可以经营的：固定的作息、一件不为钱做的事、"
                "两三个说得上话的人，比想通什么道理都实在。",
}


def _normalize(name, raw):
    """把某一维的原始分映射到全站统一的中位数与散布。

    仿射变换，保形不保值：各维的偏度与盘间相对排序不变，变的只是尺度，
    使「事业 78 分」与「情感 78 分」代表同等的稀有程度。
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


# --------------------------------------------------------------------------
# 宫位取材
# --------------------------------------------------------------------------

def _scan(chart, palace_name):
    """扫一个宫的三方四正，把评分需要的信号一次取全。

    返回的都是原始计数与名单，不含任何加权——加权留给各维度自己定，
    这样同一份材料能被六个维度按不同侧重取用。
    """
    palace = chart.by_name(palace_name)
    trio = chart.triangle(palace.index)
    weights = (1.0, 0.55, 0.75, 0.55)     # 本宫、三合、对宫、三合

    majors = []          # [(星名, 亮度, 亮度分, 是否本宫)]
    lucky, malefic, sihua = [], [], []
    bright_sum = 0.0
    lucky_w = malefic_w = 0.0
    minor_w = 0.0

    for w, p in zip(weights, trio):
        here = p.index == palace.index
        for s in p.majors:
            rank = BRIGHTNESS_RANK[s.brightness]
            majors.append((s.name, s.brightness, rank, here))
            bright_sum += w * rank
        for s in p.stars:
            if s.name in LUCKY_STARS:
                lucky.append(s.name)
                lucky_w += w
            elif s.name in MALEFIC_STARS:
                malefic.append(s.name)
                malefic_w += w
            elif s.name in AUSPICIOUS_MINOR:
                minor_w += w * 0.25
            elif s.name in INAUSPICIOUS_MINOR:
                minor_w -= w * 0.25
            if s.sihua:
                sihua.append((s.name, s.sihua, here))

    return {
        "宫": palace,
        "主星": majors,
        "亮度加权": bright_sum,
        "吉星": lucky, "吉星加权": lucky_w,
        "煞星": malefic, "煞星加权": malefic_w,
        "杂曜加权": minor_w,
        "四化": sihua,
        "空宫": palace.is_empty,
        "借星": [s.name for s in palace.borrowed],
    }


def _core_score(chart, name):
    """一维的骨架分：主宫为主、两辅宫为辅，各宫按同一口径折算。

    这一段刻意做成纯量化、不产文字——文字依据由各维度自己按侧重去写，
    否则六个维度会输出六段一模一样的话。
    """
    total = 0.0
    scans = []
    for w, pname in zip(PALACE_WEIGHTS, DIMENSION_PALACES[name]):
        sc = _scan(chart, pname)
        scans.append(sc)
        total += w * (
            sc["亮度加权"] * 0.75
            + sc["吉星加权"] * 2.2
            - sc["煞星加权"] * 2.0
            + sc["杂曜加权"]
            + sum(_SIHUA_POINTS[k] for _, k, _ in sc["四化"])
        )
    return total, scans


# 四化在评分里的分量。化忌给负分但不给到失控——化忌是「执着与耗损所在」，
# 是提醒而不是判决，一颗化忌不该把一个维度打穿。
_SIHUA_POINTS = {"化禄": 2.6, "化权": 2.0, "化科": 1.6, "化忌": -2.8}


def _bright_words(sc, subject):
    """主星亮度的白话说法。"""
    if sc["空宫"]:
        borrowed = "、".join(sc["借星"]) or "无"
        return "{}无主星，借对宫{}论——这一块受环境影响比别人明显".format(
            palace_label(sc["宫"].name), borrowed)

    own = [(n, b, r) for n, b, r, here in sc["主星"] if here]
    if not own:
        return None
    best = max(own, key=lambda x: x[2])
    if best[2] >= 4:
        return "{}坐{}{}，{}本身是有力的".format(
            palace_label(sc["宫"].name), best[0], best[1], subject)
    if best[2] <= 1:
        return "{}坐{}{}，{}要靠后天经营，先天不占位".format(
            palace_label(sc["宫"].name), best[0], best[1], subject)
    return "{}坐{}{}，{}属中等格局，用力方向比力量大小更要紧".format(
        palace_label(sc["宫"].name), best[0], best[1], subject)


def _sihua_words(sc, subject):
    """四化落在这一宫的白话说法。"""
    out = []
    here_label = {True: "本宫", False: "三方四正"}
    for star, kind, here in sc["四化"]:
        where = "{}（{}）".format(palace_label(sc["宫"].name), here_label[here])
        if kind == "化忌":
            out.append("{}{}落{}——{}上最费心力的正是这一处，"
                       "认清它比躲开它有用".format(star, kind, where, subject))
        elif kind == "化禄":
            out.append("{}{}落{}，{}上有实际的进项与顺势".format(
                star, kind, where, subject))
        elif kind == "化权":
            out.append("{}{}落{}，{}上有话事权，也容易起争执".format(
                star, kind, where, subject))
        else:
            out.append("{}{}落{}，{}上容易被看见、被认可".format(
                star, kind, where, subject))
    return out


def _star_words(sc):
    """吉煞星的白话说法。"""
    out = []
    if sc["吉星"]:
        out.append("三方四正会{}，关键处有人搭手".format(
            "、".join(dict.fromkeys(sc["吉星"]))))
    if sc["煞星"]:
        out.append("三方四正见{}，过程上的波折比别人多，宜留余地".format(
            "、".join(dict.fromkeys(sc["煞星"]))))
    return out


# --------------------------------------------------------------------------
# 评分
# --------------------------------------------------------------------------

# 各维度的主题词，用于把「依据」写成人话而不是术语堆叠
_SUBJECT = {
    "事业格局": "事业", "财富机遇": "财路", "情感缘分": "感情",
    "人际助力": "人脉", "健康根基": "身体", "心性福分": "心境",
}

# 格局对维度的加减。格局是全盘性的，但影响并不平均——
# 「禄马交驰」主要作用在财路，「羊陀夹命」主要作用在事业与心境。
PATTERN_EFFECTS = {
    "三奇加会": {"事业格局": 6, "财富机遇": 5, "心性福分": 3},
    "府相朝垣": {"事业格局": 4, "财富机遇": 4, "心性福分": 2},
    "紫府同宫": {"事业格局": 5, "财富机遇": 3},
    "极向离明": {"事业格局": 5, "心性福分": 2},
    "日丽中天": {"事业格局": 4, "人际助力": 3},
    "月朗天门": {"财富机遇": 4, "情感缘分": 3},
    "日月并明": {"事业格局": 3, "心性福分": 3},
    "日月反背": {"事业格局": -4, "心性福分": -3},
    # 禄马交驰与双禄交流都以禄存为条件，同一张盘可能两格并中。各给 6 分时
    # 财富维出现明显右偏（偏度 +0.32）——同一颗星实质上被记了两次。
    # 压到 5 与 4 后分布回到对称。
    "禄马交驰": {"财富机遇": 5},
    "双禄交流": {"财富机遇": 4, "事业格局": 2},
    "阳梁昌禄": {"事业格局": 6, "人际助力": 2},
    "文星拱命": {"事业格局": 3, "人际助力": 2},
    "魁钺拱命": {"人际助力": 5, "事业格局": 3},
    "辅弼拱命": {"人际助力": 5, "事业格局": 2},
    "机月同梁": {"健康根基": 2, "心性福分": 2},
    "杀破狼": {"事业格局": 2, "健康根基": -3, "心性福分": -2},
    "火贪格": {"财富机遇": 3, "健康根基": -2},
    "铃贪格": {"财富机遇": 2, "心性福分": -2},
    "羊陀夹命": {"事业格局": -4, "心性福分": -4},
    "火铃夹命": {"健康根基": -4, "心性福分": -3},
    "空劫扰命": {"财富机遇": -5, "心性福分": -2},
    "马头带箭": {"事业格局": 3, "健康根基": -4},
    "刑囚夹印": {"事业格局": -3, "人际助力": -4},
    "桃花犯主": {"情感缘分": -4},
    "命无正曜": {"心性福分": -2},
    "忌星入命垣": {"心性福分": -3},
    "石中隐玉": {"事业格局": 2, "心性福分": -2},
}


def score_chart(chart):
    """六维评分。返回 {维度: {分数, 评级, 依据[]}} 加一段总述。

    与八字的 score_chart 输出同一形状，前端的雷达图与分项列表可直接复用。
    """
    pats = patterns(chart)
    pat_names = [p["格名"] for p in pats]

    raw = {}
    reasons = {}

    for name in DIMENSIONS:
        core, scans = _core_score(chart, name)
        subject = _SUBJECT[name]
        main = scans[0]

        why = []
        line = _bright_words(main, subject)
        if line:
            why.append(line)
        why.extend(_star_words(main))
        why.extend(_sihua_words(main, subject))

        # 辅宫只在有明显特征时才出声，否则六段依据会长得一模一样
        for sc in scans[1:]:
            if sc["煞星加权"] >= 2.0:
                why.append("{}（{}）煞星偏重，会分掉一部分{}上的力".format(
                    palace_label(sc["宫"].name),
                    sc["宫"].to_dict()["宫位含义"].rstrip("。"), subject))
            elif sc["吉星加权"] >= 2.0:
                why.append("{}吉星有力，是{}上一处实在的助力".format(
                    palace_label(sc["宫"].name), subject))

        # 格局修正
        bonus = 0.0
        for pname in pat_names:
            delta = PATTERN_EFFECTS.get(pname, {}).get(name)
            if delta:
                bonus += delta
                why.append("命带「{}」，于{}{}".format(
                    pname, subject, "是加分项" if delta > 0 else "是需留意处"))

        # 减分封顶只作用于扣分部分，加分不受限
        gain = max(0.0, core) + max(0.0, bonus)
        loss = -min(0.0, core) - min(0.0, bonus)
        raw[name] = BASE + gain - min(PENALTY_CAP, loss)
        reasons[name] = why

    # ── 汇总 ────────────────────────────────────────────────
    final = {}
    for name in DIMENSIONS:
        s = _clamp(_normalize(name, raw[name]))
        why = reasons[name] or [
            "此宫星曜平和，无突出的助力也无明显的阻力，属中和之局"]
        if s < 52:
            why = why + [ADVICE[name]]
        final[name] = {"分数": s, "评级": _band(s), "依据": why}

    ranked = sorted(DIMENSIONS, key=lambda k: -final[k]["分数"])
    best, worst = ranked[0], ranked[-1]
    gap = final[best]["分数"] - final[worst]["分数"]

    if gap < 10:
        summary = ("六项分布均衡，没有特别突出的短板，也没有一骑绝尘的长处——"
                   "这类盘走的是稳，忌大起大落的选择。")
    else:
        summary = ("最见力的是**{}**（{} 分），最需要借力的是**{}**（{} 分）。"
                   "紫微讲的是倾向：强项顺势用，弱项知道了就能提前补。").format(
            best, final[best]["分数"], worst, final[worst]["分数"])

    return {
        "维度": final,
        "最强": best,
        "最弱": worst,
        "总述": summary,
        "说明": "分数表示命盘在该方面的结构相对强弱，不是人生价值判断。",
    }


def raw_scores(chart):
    """未经归一与截断的原始分。仅供校准脚本与测试使用。"""
    pats = [p["格名"] for p in patterns(chart)]
    out = {}
    for name in DIMENSIONS:
        core, _ = _core_score(chart, name)
        bonus = sum(PATTERN_EFFECTS.get(p, {}).get(name, 0) for p in pats)
        gain = max(0.0, core) + max(0.0, bonus)
        loss = -min(0.0, core) - min(0.0, bonus)
        out[name] = BASE + gain - min(PENALTY_CAP, loss)
    return out
