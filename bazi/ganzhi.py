"""干支体系的静态数据与基础推导。

纯查表 + 简单函数，不含时间计算。上层 chart.py 负责把公历时刻映射到干支，
本模块负责回答「这组干支意味着什么」。
"""

from __future__ import annotations

__all__ = [
    "STEMS", "BRANCHES", "STEM_ELEMENT", "BRANCH_ELEMENT",
    "STEM_YANG", "BRANCH_YANG", "ZODIAC", "HIDDEN_STEMS",
    "ten_god", "nayin", "twelve_stage", "branch_relations",
    "shensha", "ELEMENTS", "generates", "controls", "empty_branches",
]

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"

ELEMENTS = ("木", "火", "土", "金", "水")

STEM_ELEMENT = dict(zip(STEMS, "木木火火土土金金水水"))
BRANCH_ELEMENT = dict(zip(BRANCHES, "水土木木土火火土金金土水"))

# 阳干/阳支为 True
STEM_YANG = {s: (i % 2 == 0) for i, s in enumerate(STEMS)}
BRANCH_YANG = {b: (i % 2 == 0) for i, b in enumerate(BRANCHES)}

# 地支藏干，按 本气 → 中气 → 余气 排列
HIDDEN_STEMS = {
    "子": ("癸",),
    "丑": ("己", "癸", "辛"),
    "寅": ("甲", "丙", "戊"),
    "卯": ("乙",),
    "辰": ("戊", "乙", "癸"),
    "巳": ("丙", "庚", "戊"),
    "午": ("丁", "己"),
    "未": ("己", "丁", "乙"),
    "申": ("庚", "壬", "戊"),
    "酉": ("辛",),
    "戌": ("戊", "辛", "丁"),
    "亥": ("壬", "甲"),
}

# 藏干权重：本气 0.6、中气 0.3、余气 0.1（单藏则独占）。用于五行强弱量化。
HIDDEN_WEIGHTS = {1: (1.0,), 2: (0.7, 0.3), 3: (0.6, 0.3, 0.1)}


def generates(e):
    """五行相生：木→火→土→金→水→木。"""
    return ELEMENTS[(ELEMENTS.index(e) + 1) % 5]


def controls(e):
    """五行相克：木→土→金→木、火→金、水→火。"""
    return ELEMENTS[(ELEMENTS.index(e) + 2) % 5]


# --------------------------------------------------------------------------
# 十神
# --------------------------------------------------------------------------

_TEN_GOD_TABLE = {
    ("same", True): "比肩", ("same", False): "劫财",
    ("child", True): "食神", ("child", False): "伤官",
    ("wealth", True): "偏财", ("wealth", False): "正财",
    ("officer", True): "七杀", ("officer", False): "正官",
    ("seal", True): "偏印", ("seal", False): "正印",
}


def ten_god(day_stem, other_stem):
    """以日干为「我」，判断另一天干的十神。

    同性相见为偏（比肩/食神/偏财/七杀/偏印），异性相见为正。
    """
    me, other = STEM_ELEMENT[day_stem], STEM_ELEMENT[other_stem]
    same_polarity = STEM_YANG[day_stem] == STEM_YANG[other_stem]

    if me == other:
        kind = "same"
    elif generates(me) == other:
        kind = "child"          # 我生者为食伤
    elif controls(me) == other:
        kind = "wealth"         # 我克者为财
    elif controls(other) == me:
        kind = "officer"        # 克我者为官杀
    else:
        kind = "seal"           # 生我者为印
    return _TEN_GOD_TABLE[(kind, same_polarity)]


# --------------------------------------------------------------------------
# 纳音（六十甲子）
# --------------------------------------------------------------------------

_NAYIN = [
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火",
    "涧下水", "城头土", "白蜡金", "杨柳木", "泉中水", "屋上土",
    "霹雳火", "松柏木", "长流水", "砂中金", "山下火", "平地木",
    "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
]


def sexagenary_index(stem, branch):
    """干支组合在六十甲子中的序号 0–59。"""
    si, bi = STEMS.index(stem), BRANCHES.index(branch)
    # 解 n ≡ si (mod 10) 且 n ≡ bi (mod 12)，六个候选里必有其一
    for k in range(6):
        cand = si + 10 * k
        if cand % 12 == bi:
            return cand
    raise ValueError("{}{} 不是有效的干支组合".format(stem, branch))


def nayin(stem, branch):
    return _NAYIN[sexagenary_index(stem, branch) // 2]


# --------------------------------------------------------------------------
# 十二长生
# --------------------------------------------------------------------------

STAGES = (
    "长生", "沐浴", "冠带", "临官", "帝旺",
    "衰", "病", "死", "墓", "绝", "胎", "养",
)

# 各天干的「长生」所在地支
_BIRTH_BRANCH = {
    "甲": "亥", "乙": "午", "丙": "寅", "丁": "酉", "戊": "寅",
    "己": "酉", "庚": "巳", "辛": "子", "壬": "申", "癸": "卯",
}


def twelve_stage(stem, branch):
    """天干在地支上的十二运。阳干顺行、阴干逆行。"""
    start = BRANCHES.index(_BIRTH_BRANCH[stem])
    pos = BRANCHES.index(branch)
    step = (pos - start) if STEM_YANG[stem] else (start - pos)
    return STAGES[step % 12]


# --------------------------------------------------------------------------
# 地支刑冲合害
# --------------------------------------------------------------------------

# 组合一律以惯用写法存储（三合按 长生-帝旺-墓库 排序，而非地支序），
# 需要判定时再转成集合，这样输出的名称和命书一致。
SIX_HARMONY_PAIRS = (
    ("子丑", "土"), ("寅亥", "木"), ("卯戌", "火"),
    ("辰酉", "金"), ("巳申", "水"), ("午未", "土"),
)
SIX_HARMONY = {frozenset(p): (p, e) for p, e in SIX_HARMONY_PAIRS}

THREE_HARMONY = (       # 三合局
    ("申子辰", "水"), ("亥卯未", "木"), ("寅午戌", "火"), ("巳酉丑", "金"),
)
THREE_MEETING = (       # 三会方
    ("寅卯辰", "木"), ("巳午未", "火"), ("申酉戌", "金"), ("亥子丑", "水"),
)
SIX_CLASH = {frozenset(p): p for p in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}
SIX_HARM = {frozenset(p): p for p in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")}
PUNISH_GROUPS = ("寅巳申", "丑戌未")
PUNISH_PAIR = frozenset("子卯")
SELF_PUNISH = set("辰午酉亥")

STEM_HARMONY = {         # 天干五合
    frozenset("甲己"): "土", frozenset("乙庚"): "金", frozenset("丙辛"): "水",
    frozenset("丁壬"): "木", frozenset("戊癸"): "火",
}
STEM_CLASH = [frozenset(p) for p in ("甲庚", "乙辛", "丙壬", "丁癸")]


def branch_relations(branches):
    """扫描一组地支，列出成立的刑冲合害。

    branches: 按 年/月/日/时（可再加大运、流年）顺序的地支列表。
    返回 {类别: [描述, ...]}。
    """
    out = {"六合": [], "三合": [], "三会": [], "六冲": [], "相刑": [], "六害": []}
    present = set(branches)

    for combo, elem in THREE_MEETING:
        if set(combo) <= present:
            out["三会"].append("{}会{}局".format(combo, elem))
    for combo, elem in THREE_HARMONY:
        if set(combo) <= present:
            out["三合"].append("{}合{}局".format(combo, elem))

    n = len(branches)
    for i in range(n):
        for j in range(i + 1, n):
            pair = frozenset((branches[i], branches[j]))
            if len(pair) == 1:
                if branches[i] in SELF_PUNISH:
                    out["相刑"].append("{}{}自刑".format(branches[i], branches[j]))
                continue
            if pair in SIX_HARMONY:
                name, elem = SIX_HARMONY[pair]
                out["六合"].append("{}合{}".format(name, elem))
            if pair in SIX_CLASH:
                out["六冲"].append("{}相冲".format(SIX_CLASH[pair]))
            if pair in SIX_HARM:
                out["六害"].append("{}相害".format(SIX_HARM[pair]))
            if pair == PUNISH_PAIR:
                out["相刑"].append("子卯相刑")

    for group in PUNISH_GROUPS:
        hit = [b for b in group if b in present]   # 保持惯用顺序
        if len(hit) == 3:
            out["相刑"].append("{}三刑".format("".join(hit)))
        elif len(hit) == 2:
            out["相刑"].append("{}相刑".format("".join(hit)))

    # 同一关系可能被多组地支重复命中（如两个午同害一个丑），去重只留一条
    return {
        k: list(dict.fromkeys(v)) for k, v in out.items() if v
    }


# --------------------------------------------------------------------------
# 空亡与神煞
# --------------------------------------------------------------------------

def empty_branches(day_stem, day_branch):
    """日柱所属旬的空亡（旬空）二支。"""
    idx = sexagenary_index(day_stem, day_branch)
    xun_start = idx - idx % 10          # 本旬首柱序号
    # 旬首干为甲，其后第 10、11 位地支落空
    first_branch = BRANCHES.index(day_branch) - (idx - xun_start)
    return (
        BRANCHES[(first_branch + 10) % 12],
        BRANCHES[(first_branch + 11) % 12],
    )


_NOBLE = {  # 天乙贵人：以日干（或年干）查
    "甲": "丑未", "戊": "丑未", "庚": "丑未",
    "乙": "子申", "己": "子申",
    "丙": "亥酉", "丁": "亥酉",
    "壬": "卯巳", "癸": "卯巳",
    "辛": "寅午",
}
_ACADEMIC = {  # 文昌贵人
    "甲": "巳", "乙": "午", "丙": "申", "丁": "酉", "戊": "申",
    "己": "酉", "庚": "亥", "辛": "子", "壬": "寅", "癸": "卯",
}
_BLADE = {  # 羊刃（阳干专有）
    "甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子",
}
# 以年支/日支三合局起：桃花=沐浴位、驿马=冲长生、华盖=墓库
_PEACH = {"申子辰": "酉", "亥卯未": "子", "寅午戌": "卯", "巳酉丑": "午"}
_HORSE = {"申子辰": "寅", "亥卯未": "巳", "寅午戌": "申", "巳酉丑": "亥"}
_CANOPY = {"申子辰": "辰", "亥卯未": "未", "寅午戌": "戌", "巳酉丑": "丑"}
_GENERAL = {"申子辰": "子", "亥卯未": "卯", "寅午戌": "午", "巳酉丑": "酉"}


def _group_of(branch):
    for group in _PEACH:
        if branch in group:
            return group
    return None


def shensha(year_branch, day_stem, day_branch, all_branches):
    """常用神煞。返回 {神煞名: [命中的地支, ...]}。

    桃花/驿马/华盖/将星按年支与日支双查（传统上年支为主、日支为辅）。
    """
    found = {}

    def hit(name, targets):
        got = [b for b in all_branches if b in targets]
        if got:
            found.setdefault(name, [])
            for b in got:
                if b not in found[name]:
                    found[name].append(b)

    hit("天乙贵人", _NOBLE[day_stem])
    hit("文昌贵人", _ACADEMIC[day_stem])
    if day_stem in _BLADE:
        hit("羊刃", _BLADE[day_stem])

    for base in {year_branch, day_branch}:
        group = _group_of(base)
        if not group:
            continue
        hit("桃花", _PEACH[group])
        hit("驿马", _HORSE[group])
        hit("华盖", _CANOPY[group])
        hit("将星", _GENERAL[group])

    void = empty_branches(day_stem, day_branch)
    hit("空亡", "".join(void))
    return found
