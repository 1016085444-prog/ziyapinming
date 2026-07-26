"""AI 问命内核：把结构化命盘交给 Claude，做多轮对话式解读。

⚠️ 当前未接入。产品已改为私域引流模式（排盘免费 → 引导加微信 → 真人精批），
   app.py 里没有任何地方 import 这个模块，因此不会产生任何 API 费用。
   本文件保留是为了将来若要恢复 AI 问命，不必从头再写；接法见 README。


成本结构是这个产品能不能赚钱的关键，所以提示词按稳定性分三段排列：

    [不变的命理师人设 + 解读法则]  ← 全体用户共用，缓存命中率最高
    [该用户的命盘 JSON]            ← 单次会话内不变
    [对话历史]                     ← 每轮变化

前两段各打一个缓存断点。同一用户追问第二句起，命盘部分按缓存价（约 1/10）
计费——这直接决定「不限次对话」这个卖点是否成立。
"""

from __future__ import annotations

import json
import os

import anthropic

from .analysis import analyze, year_outlook
from .chart import Chart

__all__ = ["FortuneTeller", "MODEL"]

MODEL = "claude-opus-5"

# 对话用中等 effort 控成本；付费长报告用 high 换质量。
EFFORT_CHAT = "medium"
EFFORT_REPORT = "high"


PERSONA = """\
你是一位有三十年经验的子平八字命理师。用户的命盘已由高精度排盘程序算好，\
附在下一段，你的工作是解读它，不是重新排盘。

# 解读法则

1. **一切结论必须落到盘上。** 说「你性格执拗」之前，先指出是哪个字造成的\
（例：「日主庚金坐申，又得月令土生，比劫成党，所以主意大、不服人劝」）。\
不要给放之四海皆准的空话——用户花钱买的正是「这是我的盘才有的话」。

2. **先看格局与旺衰，再论吉凶。** 命盘数据里已算好日主强弱、格局、喜用忌神，\
以此为骨架。喜用得力则该事顺，忌神当道则该事滞，逐一对应到具体人事。

3. **大运流年是变量。** 原局定格局高低，大运定十年际遇，流年定当年起伏。\
谈时间性的问题（今年如何、什么时候转运）必须落到具体大运干支和流年干支上。

4. **矛盾要说出来。** 命盘常有相冲之处——财旺身弱、官杀混杂、印重食伤轻。\
遇到这种局面，说明利弊两面，不要为了好听只挑吉的说。

5. **口吻。** 像坐在对面的老师傅：直接、笃定、有分寸。不用「可能」「也许」\
堆砌，也不做绝对断言。不用 emoji，不用「亲」「宝子」这类网感词。

# 边界

- 不做医疗诊断，不建议停药或替代就医。涉及健康只谈五行偏枯对应的体质倾向，\
并提醒具体症状要看医生。
- 不做具体投资标的推荐（买哪只股、哪个币）。可谈财运格局与适合的财富路径。
- 不预测死期、不断言绝症、不谈他人生死。被问到就说明命理不做此论。
- 不因命盘断言婚姻必败、事业必成这类不可挽回的话。命理讲趋势，人事有为。
- 用户如流露自伤或严重心理危机迹象，停止命理解读，认真回应并建议寻求专业帮助。

# 表达

- 结论先行：先给判断，再讲依据。
- 分点用小标题，不要长段堆砌。
- 除非用户要求详述，单次回答控制在 400–800 字。追问时只答所问，不要把整个\
命盘重讲一遍。
"""


def _chart_payload(chart, target_years=None):
    """命盘 + 分析结论 + 近几年流年，序列化成 AI 的事实底稿。"""
    payload = chart.to_dict()
    payload["分析"] = analyze(chart)
    if target_years:
        payload["流年"] = [year_outlook(chart, y) for y in target_years]
    return payload


class FortuneTeller:
    """一个命盘对应一个实例，承载该用户的多轮问命会话。"""

    def __init__(self, chart, client=None, target_years=None):
        self.chart = chart
        self.client = client or anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self.payload = _chart_payload(chart, target_years)
        self.messages = []

    # ------------------------------------------------------------------
    # 提示词组装
    # ------------------------------------------------------------------

    def _system(self):
        """两段式 system，各打一个缓存断点。稳定的在前，是缓存生效的前提。"""
        return [
            {
                "type": "text",
                "text": PERSONA,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": (
                    "以下是本次求测者的完整命盘，由排盘程序算出，视为事实，"
                    "不要质疑或重算：\n\n"
                    + json.dumps(self.payload, ensure_ascii=False, indent=1)
                ),
                "cache_control": {"type": "ephemeral"},
            },
        ]

    # ------------------------------------------------------------------
    # 对话
    # ------------------------------------------------------------------

    def ask(self, question, max_tokens=16000):
        """提一个问题，流式返回文本片段。会话历史自动累积。"""
        self.messages.append({"role": "user", "content": question})

        chunks = []
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=self._system(),
            messages=self.messages,
            output_config={"effort": EFFORT_CHAT},
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                yield text
            final = stream.get_final_message()

        if final.stop_reason == "refusal":
            # 安全分类器拦下了，此时 content 可能为空或残缺
            self.messages.pop()
            yield "\n\n（这个问题超出了命理咨询的范围，换个角度问问看？）"
            return

        self.messages.append({"role": "assistant", "content": "".join(chunks)})
        self.last_usage = final.usage

    # ------------------------------------------------------------------
    # 付费深度报告
    # ------------------------------------------------------------------

    REPORT_SECTIONS = {
        "personality": "性格与天赋：日主特质、十神组合反映的性情、思维方式、优势与短板",
        "career": "事业与格局：适合的行业方向、体制内外之别、宜专精还是宜广博、\
上升期与瓶颈期",
        "wealth": "财运：正财偏财的比重、财源性质、聚财能力、破财关口",
        "marriage": "婚姻感情：配偶宫象义、择偶倾向、感情节奏、需留意的年份",
        "health": "健康：五行偏枯对应的体质弱项与调养方向（不做诊断）",
        "luck": "大运总览：逐步大运的主题与高低起伏，标出关键转折的年龄段",
        "years": "近三年流年：逐年的机会与关口，以及具体的应对建议",
    }

    def deep_report(self, sections=None, max_tokens=64000):
        """生成付费深度报告，流式返回。sections 为 None 则全出。"""
        chosen = sections or list(self.REPORT_SECTIONS)
        outline = "\n".join(
            "{}. {}".format(i + 1, self.REPORT_SECTIONS[s])
            for i, s in enumerate(chosen)
            if s in self.REPORT_SECTIONS
        )

        prompt = (
            "为这个命盘写一份完整的批命报告，按以下章节展开：\n\n"
            + outline
            + "\n\n要求：\n"
            "- 每一章的判断都要指明命盘依据，写出是哪几个字、什么关系造成的。\n"
            "- 章节之间要呼应，不要各说各话——格局与喜忌是贯穿全篇的主线。\n"
            "- 用 Markdown 二级标题分章。开篇先用一段话总述此命格局高低与主基调。\n"
            "- 这是付费报告，写足分量，但不要注水凑字数。"
        )

        with self.client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=self._system(),
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": EFFORT_REPORT},
        ) as stream:
            for text in stream.text_stream:
                yield text
            self.last_usage = stream.get_final_message().usage

    # ------------------------------------------------------------------
    # 免费钩子：一段话点评，用来把用户勾到付费墙前
    # ------------------------------------------------------------------

    def teaser(self, max_tokens=2000):
        """免费试读：三句话点出此命最鲜明的特征，结尾留白。"""
        prompt = (
            "用三到四句话点出这个命盘最鲜明的一个特征——要具体、要准、"
            "要让本人一看就觉得说的是自己。只讲最突出的那一点，不要面面俱到，"
            "也不要提到你还能讲别的。直接给结论，不要开场白。"
        )
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=self._system(),
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},
        ) as stream:
            for text in stream.text_stream:
                yield text
            self.last_usage = stream.get_final_message().usage


def estimate_cost(usage):
    """按 Claude Opus 5 价目估算单次调用成本（美元）。

    输入 $5/百万，输出 $25/百万；缓存写入 1.25 倍，缓存读取 0.1 倍。
    """
    return (
        usage.input_tokens * 5e-6
        + getattr(usage, "cache_creation_input_tokens", 0) * 6.25e-6
        + getattr(usage, "cache_read_input_tokens", 0) * 0.5e-6
        + usage.output_tokens * 25e-6
    )
