"""盘上「需结合处境才能定论」的点。

这是转化引擎，但沿用八字那边自己划死的那条线：**每一条都必须是真的两可**。

紫微在这件事上比子平更容易讲清楚，因为十二宫本身就带着处境的坐标：
化忌落在官禄宫还是夫妻宫，是两件完全不同的事；身宫落在财帛宫的人，
和身宫落在福德宫的人，同一步大限的用法相反。

不做的事：把已知结论藏起来假装神秘，或者「你命里有一处凶险，加微信详谈」
这种制造恐惧的话术。除了不体面，它招来的是最焦虑、最难伺候、最容易事后
翻脸的客户，对靠复购和转介绍的生意是负资产。

每条给三段：盘上的事实 → 为什么两可 → 一个只有当事人能答的问题。
"""

from __future__ import annotations

import time

from .analysis import patterns
from .stars import LUCKY_STARS, MALEFIC_STARS, STAR_MEANINGS, palace_label

__all__ = ["open_questions", "MAX_QUESTIONS"]

# 超过三条会稀释注意力，反而没有一条被认真对待
MAX_QUESTIONS = 3


def _malefics_in(chart, palace_name):
    """某宫三方四正里的煞星名单（去重，保持出现顺序）。"""
    palace = chart.by_name(palace_name)
    got = []
    for p in chart.triangle(palace.index):
        for s in p.stars:
            if s.name in MALEFIC_STARS and s.name not in got:
                got.append(s.name)
    return got


def _luckies_in(chart, palace_name):
    palace = chart.by_name(palace_name)
    got = []
    for p in chart.triangle(palace.index):
        for s in p.stars:
            if s.name in LUCKY_STARS and s.name not in got:
                got.append(s.name)
    return got


def _sihua_palace(chart, kind):
    """某种四化落在哪个宫，返回 (宫名, 星名)；没有则 (None, None)。"""
    for star, k in chart.sihua.items():
        if k == kind:
            p = chart.star_palace(star)
            if p is not None:
                return p.name, star
    return None, None


def _limit_turning(chart, this_year):
    """是否临近大限交接（前后两年内）。换限前后该进该守，最看当下手上的事。"""
    age = chart.age_in(this_year)
    for p in chart.palaces:
        lo, _ = p.limit_ages
        if abs(lo - age) <= 2:
            return p
    return None


def open_questions(chart, this_year=None):
    """返回至多 MAX_QUESTIONS 条待定论的点，按冲击力排序。"""
    if this_year is None:
        this_year = time.localtime().tm_year

    pat_names = {p["格名"] for p in patterns(chart)}
    life = chart.life_palace()
    body = chart.body_palace()
    out = []

    # ── 化忌落宫：全盘最值得谈的一处 ──────────────────────────
    ji_palace, ji_star = _sihua_palace(chart, "化忌")
    if ji_palace:
        out.append((100, {
            "标题": "{}化忌落{}".format(ji_star, palace_label(ji_palace)),
            "问法": "我{}化忌落在{}，这份执着该往哪用？".format(
                ji_star, palace_label(ji_palace)),
            "事实": "你的生年化忌落在{}（{}）。化忌不是灾，是「最放不下」——"
                    "一生里最肯投时间、也最容易钻进去出不来的，就是这一块。".format(
                        palace_label(ji_palace),
                        chart.by_name(ji_palace).to_dict()["宫位含义"].rstrip("。")),
            "两可": "如果这一块正是你吃饭的本事，这份执着就是别人追不上的深度；"
                    "如果它只是你生活的边角，同样的执着就纯粹是漏水的地方。",
            "问题": "{}这一块，现在是你主要在做的事，还是分心的那件事？".format(
                palace_label(ji_palace)),
        }))

    # ── 命宫无主星：可塑性大，但环境说话 ──────────────────────
    if "命无正曜" in pat_names:
        borrowed = "、".join(s.name for s in life.borrowed) or "无"
        out.append((94, {
            "标题": "命宫无主星，借{}论".format(borrowed),
            "问法": "我命宫无正曜借{}，现在的环境算是推我还是拖我？".format(borrowed),
            "事实": "你的命宫（{}宫）没有主星，要借对宫的{}来论。"
                    "这类盘的性格可塑性比一般人大得多。".format(life.branch, borrowed),
            "两可": "可塑性大意味着环境的放大倍数也大：待在对的地方，"
                    "成长速度会明显快过同辈；待在错的地方，也会比别人更快被磨平。"
                    "同一个人换个环境，判若两人。",
            "问题": "你现在待的地方——公司、行业、身边这几个人——是把你往上带，"
                    "还是让你越待越像不想成为的那种人？",
        }))

    # ── 杀破狼：变动结构，看行业是否吃这一套 ──────────────────
    if "杀破狼" in pat_names:
        out.append((85, {
            "标题": "杀破狼坐命",
            "问法": "我杀破狼坐命，现在这行到底适不适合我？",
            "事实": "你的命宫是杀破狼结构，主变动。一生的转折多半由你自己发动，"
                    "起伏也比常人大——这在盘上是明写着的。",
            "两可": "在按年资排队、看谁待得久的地方，这股劲是消耗，你会一直"
                    "觉得憋着；在看谁能开局、允许推倒重来的地方，同样这股劲"
                    "就是核心竞争力。",
            "问题": "你所在的行业，是看资历，还是看谁能把新局面打开？",
        }))

    # ── 身宫与命宫分处：力气花在哪与天性想要什么 ──────────────
    #
    # 只在身宫落这五宫时才问。十二宫里身宫必有十一分之十的机会不在命宫，
    # 若不加限制这条会在八成的盘上挤进前三，把别的话头全顶掉。而身宫落
    # 兄弟、子女、疾厄这类宫，问出来的答案也难落到可行动的建议上。
    if body.name in ("财帛", "官禄", "夫妻", "福德", "迁移"):
        out.append((72, {
            "标题": "身宫落{}".format(palace_label(body.name)),
            "问法": "我身宫落在{}，现在的重心是不是压错了地方？".format(
                palace_label(body.name)),
            "事实": "命宫说的是你的天性，身宫说的是你实际把力气花在哪。"
                    "你的身宫落在{}——{}".format(
                        palace_label(body.name),
                        chart.by_name(body.name).to_dict()["宫位含义"]),
            "两可": "身宫与你现在真正投入的领域一致，那是顺着自己的力气在用，"
                    "事半功倍；若你眼下拼的完全是另一块，就会长期有一种"
                    "「很努力但不对劲」的感觉，而这跟能力无关。",
            "问题": "过去这两三年，你花时间最多的是哪一块？是{}这一头吗？".format(
                body.name),
        }))

    # ── 夫妻宫见煞：婚姻问题还是职业形态 ──────────────────────
    # 门槛取三颗而非两颗：六煞散在十二宫，三方四正占四宫，期望值恰是两颗。
    # 按两颗算会有近七成的盘命中——一个七成人都有的特征不值得单列，
    # 且它会把别的话头挤出前三。
    spouse_malefics = _malefics_in(chart, "夫妻")
    if len(spouse_malefics) >= 3:
        out.append((88, {
            "标题": "夫妻宫三方见{}".format("、".join(spouse_malefics[:3])),
            "问法": "我夫妻宫见{}，感情上具体该注意什么？".format(
                "、".join(spouse_malefics[:3])),
            "事实": "你的夫妻宫三方四正见{}，主关系里聚散反复、"
                    "或者长期分处两地。".format("、".join(spouse_malefics)),
            "两可": "在朝九晚五、天天见面的生活里，这确实是消耗；"
                    "但若你或对方本就是出差、外派、异地这类职业形态，"
                    "这股力量被工作消化掉了，未必落到感情上。",
            "问题": "你和伴侣现在是天天见面，还是本来就聚少离多？",
        }))

    # ── 火贪铃贪：暴发结构，看有没有落袋的渠道 ────────────────
    if pat_names & {"火贪格", "铃贪格"}:
        which = "火贪" if "火贪格" in pat_names else "铃贪"
        out.append((80, {
            "标题": "{}格".format(which),
            "问法": "我{}格，机会来的时候该怎么接才不至于白忙？".format(which),
            "事实": "你盘上贪狼与火铃同宫，属{}格——主突发的机遇，"
                    "来得猛，退得也快。".format(which),
            "两可": "手上有把势头变成资产的渠道（合同、股权、作品、客户名单），"
                    "这类结构就是几次机会改变一生；没有渠道的，"
                    "同样的机会来过几轮，最后什么也没剩下。",
            "问题": "上一次势头最好的时候，你有没有把它变成留得下来的东西？",
        }))

    # ── 化禄与空劫同临财位：进得快也漏得快 ────────────────────
    wealth_malefics = _malefics_in(chart, "财帛")
    if {"地空", "地劫"} & set(wealth_malefics):
        out.append((82, {
            "标题": "财帛宫三方见空劫",
            "问法": "我财帛宫见空劫，钱该怎么放才不漏？",
            "事实": "你的财帛宫三方四正见{}。空劫主的是「想法与实际脱节」"
                    "和「被迫改道」，落在财位上多主进项留不住。".format(
                        "、".join(n for n in wealth_malefics if n in ("地空", "地劫"))),
            "两可": "钱走的是固定渠道、有账可查的人，这条只是提醒别压重注；"
                    "钱主要靠机会和人情流动的人，同一个结构就是实实在在的漏口。",
            "问题": "你现在的钱，主要走固定渠道，还是靠一波一波的机会？",
        }))

    # ── 羊陀夹命：节奏问题 ────────────────────────────────────
    if "羊陀夹命" in pat_names:
        out.append((76, {
            "标题": "羊陀夹命",
            "问法": "我羊陀夹命，手上的事该加快还是该放慢？",
            "事实": "你的命宫前后被擎羊、陀罗夹住。这两颗一主锋锐、一主拖延，"
                    "合起来就是「事情前后都容易受阻」。",
            "两可": "在可以自己定节奏的位置上，放慢反而顺——该断的早断，"
                    "不硬推；在被进度推着走的位置上，这个结构会持续消耗你，"
                    "而问题往往不在你的能力上。",
            "问题": "你现在的工作，节奏是你自己定的，还是被别人的进度推着走？",
        }))

    # ── 大限交接：进还是守 ────────────────────────────────────
    turning = _limit_turning(chart, this_year)
    if turning is not None:
        out.append((70, {
            "标题": "正处大限交接前后",
            "问法": "我虚岁 {} 前后交入{}大限，手上的事该收口还是该转向？".format(
                turning.limit_ages[0], palace_label(turning.name)),
            "事实": "你在虚岁 {} 前后交入{}大限（{}–{} 年）。"
                    "这是十年一换的节点。".format(
                        turning.limit_ages[0], palace_label(turning.name),
                        *turning.limit_years),
            "两可": "手上有正在推进、只差临门一脚的事，换限前后宜稳住收口；"
                    "手上是长期不见起色的局面，这个节点恰恰是掀桌重来的时机。",
            "问题": "你手上现在的事，是快成了，还是拖了很久没动静？",
        }))

    # ── 吉星会命而无煞：顺局也有顺局的问题 ────────────────────
    life_lucky = _luckies_in(chart, "命宫")
    if len(life_lucky) >= 3 and not _malefics_in(chart, "命宫"):
        out.append((60, {
            "标题": "命宫三方会{}".format("、".join(life_lucky[:3])),
            "问法": "我命宫吉星多而不见煞，这种顺局该怎么用才不浪费？",
            "事实": "你的命宫三方四正会{}，不见六煞。盘面上是顺局——"
                    "关键处不缺人搭手。".format("、".join(life_lucky)),
            "两可": "顺局的人若早早找到一件值得做很久的事，助力会一路累加；"
                    "若一直在换方向，同样的助力会分散成很多「差一点就成」的"
                    "半成品——顺反而让人不容易下决心。",
            "问题": "你现在有没有一件已经做了三年以上、还想继续做的事？",
        }))

    # ── 命宫主星的亮度：得位与失位各有各的两可 ────────────────
    own = [s for s in life.majors if s.brightness]
    if own:
        best = max(own, key=lambda s: s.power)
        if best.power >= 4:
            out.append((56, {
                "标题": "命宫{}{}".format(best.name, best.brightness),
                "问法": "我命宫{}{}，这份先天的顺该怎么用才不浪费？".format(
                    best.name, best.brightness),
                "事实": "你的命宫坐{}，在{}宫为「{}」，是得位的。{}".format(
                    best.name, life.branch, best.brightness,
                    STAR_MEANINGS.get(best.name, "")),
                "两可": "先天得位的人，若早早认定一件事，优势会一路复利；"
                        "但顺也容易让人不急着下决心——同样一副好牌，"
                        "打到四十岁才起手和二十五岁起手，是两个人生。",
                "问题": "你现在手上，有没有一件你愿意再做十年的事？",
            }))
        elif best.power <= 1:
            out.append((56, {
                "标题": "命宫{}{}".format(best.name, best.brightness),
                "问法": "我命宫{}{}，先天不占位该往哪补？".format(
                    best.name, best.brightness),
                "事实": "你的命宫坐{}，在{}宫为「{}」，先天不占位。{}".format(
                    best.name, life.branch, best.brightness,
                    STAR_MEANINGS.get(best.name, "")),
                "两可": "落陷不是差，是「这颗星的原厂设定不适合这个位置」，"
                        "所以走的是后天补的路：换环境、换行业、或者把这颗星"
                        "的性子用在它真能发挥的地方。但补哪一条，取决于你"
                        "现在还能动哪一条。",
                "问题": "换城市、换行业、换身边的人这三件事，你现在最能动的"
                        "是哪一件？",
            }))

    # ── 兜底：上面全不触发的盘，用命主与身主起话头。
    #    任何盘都有命主身主，也都在某一步大限里，所以这条必定成立。 ──
    cur = chart.limit_at(chart.age_in(this_year))
    out.append((40, {
        "标题": "命主{}、身主{}".format(chart.life_lord, chart.body_lord),
        "问法": "我命主{}、身主{}，眼下该先动哪一头？".format(
            chart.life_lord, chart.body_lord),
        "事实": "你的命主是{}——{}身主是{}——{}".format(
            chart.life_lord, STAR_MEANINGS.get(chart.life_lord, ""),
            chart.body_lord, STAR_MEANINGS.get(chart.body_lord, "")),
        "两可": "命主说的是你天生怎么用力，身主说的是后天该往哪落。"
                "两者同向的人顺着走就好；两者不同向的人，先动哪一头"
                "差别很大，而这取决于你现在最缺的是什么。",
        "问题": "眼下你最想解决的，是「方向不清」还是「用不上力」？{}".format(
            "你正走在{}大限上。".format(palace_label(cur.name)) if cur else ""),
    }))

    out.sort(key=lambda x: -x[0])
    return [q for _, q in out[:MAX_QUESTIONS]]
