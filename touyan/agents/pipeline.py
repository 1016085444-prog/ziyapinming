"""深度分析编排：分析师（并行）→ 多空辩论 → 研究主管 → 交易员 → 风控辩论 → 投资经理。

对应 TradingAgents 的 graph/setup.py + conditional_logic.py：辩论轮数、发言顺序、
「辩论满 N 轮交给主管」的路由规则都与原项目一致，只是写成了顺序代码。

整个流程通过 emit(event) 推送事件（开始、逐字输出、完成、出错），网页据此实时显示
每个智能体的发言。事件格式见 Pipeline.run 的文档。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from agents import dossier, prompts, rating
from agents.llm import LLM, Cancelled, LLMError

AGENTS = {
    "market": ("技术分析师", "analysts"),
    "fundamentals": ("基本面分析师", "analysts"),
    "news": ("资讯分析师", "analysts"),
    "bull": ("多头研究员", "research"),
    "bear": ("空头研究员", "research"),
    "research_manager": ("研究主管", "research"),
    "trader": ("交易员", "trading"),
    "aggressive": ("激进型风控", "risk"),
    "conservative": ("保守型风控", "risk"),
    "neutral": ("中性风控", "risk"),
    "portfolio_manager": ("投资经理", "decision"),
}
STAGES = {
    "analysts": "分析师团队",
    "research": "研究团队：多空辩论",
    "trading": "交易员：制定方案",
    "risk": "风控团队：风险辩论",
    "decision": "投资经理：最终决策",
}
ANALYSTS = ("market", "fundamentals", "news")

Emit = Callable[[dict], None]


@dataclass
class DeepOptions:
    analysts: list[str] = field(default_factory=lambda: list(ANALYSTS))
    debate_rounds: int = 1
    risk_rounds: int = 1
    position: dict | None = None

    def normalized(self) -> "DeepOptions":
        picked = [a for a in ANALYSTS if a in (self.analysts or [])] or ["market"]
        return DeepOptions(picked, max(1, min(3, int(self.debate_rounds))), max(1, min(3, int(self.risk_rounds))), self.position)


def available_analysts(report: dict, wanted: list[str]) -> list[str]:
    """按数据情况决定哪些分析师有材料可写：指数、导入数据没有基本面；完全没有新闻时不派资讯分析师。"""
    out = []
    for key in wanted:
        if key == "fundamentals" and not (report.get("fund") or (report.get("fundamentals") or {}).get("available")):
            continue
        if key == "news" and not (report.get("news") or report.get("market_news")):
            continue
        out.append(key)
    return out or ["market"]


def plan(report: dict, options: DeepOptions) -> list[dict]:
    """整个流程里每一次发言，事先排好，界面可以一开始就画出完整时间线。"""
    steps = []

    def add(agent: str, rnd: int = 0):
        label, stage = AGENTS[agent]
        steps.append({"id": f"{agent}-{rnd}" if rnd else agent, "agent": agent, "label": label, "stage": stage, "round": rnd})

    for key in available_analysts(report, options.analysts):
        add(key)
    for rnd in range(1, options.debate_rounds + 1):
        add("bull", rnd)
        add("bear", rnd)
    add("research_manager")
    add("trader")
    for rnd in range(1, options.risk_rounds + 1):
        add("aggressive", rnd)
        add("conservative", rnd)
        add("neutral", rnd)
    add("portfolio_manager")
    return steps


def beijing_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=8)


class Pipeline:
    def __init__(self, quick: LLM, deep: LLM, emit: Emit, cancel: threading.Event | None = None):
        self.quick = quick
        self.deep = deep
        self.emit = emit
        self.cancel = cancel or threading.Event()

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _speak(self, step: dict, llm: LLM, system: str, user: str) -> str:
        self._check()
        sid = step["id"]
        self.emit({"type": "agent_start", **step, "model": llm.label})
        started = time.time()
        try:
            text = llm.complete(system, user, on_delta=lambda t: self.emit({"type": "delta", "id": sid, "text": t}),
                                cancel=self.cancel)
        except LLMError as exc:
            self.emit({"type": "agent_error", "id": sid, "message": str(exc)})
            raise
        self.emit({"type": "agent_done", "id": sid, "content": text, "elapsed": round(time.time() - started, 1)})
        return text

    def run(self, report: dict, options: DeepOptions, past: list[dict] | None = None) -> dict:
        """事件：
        start         {steps: [...], models}
        stage         {stage, label}
        agent_start   {id, agent, label, stage, round, model}
        delta         {id, text}            逐字输出
        agent_done    {id, content, elapsed}
        agent_error   {id, message}
        decision      {data}                最终结论（结构化）
        """
        options = options.normalized()
        steps = plan(report, options)
        by_id = {s["id"]: s for s in steps}
        today = beijing_now().strftime("%Y-%m-%d")
        ctx = dossier.instrument_context(report)
        quant = dossier.quant_brief(report)
        position = dossier.position_context(options.position, report)
        unit = report["currency_label"]
        sys_for = lambda agent: prompts.system(AGENTS[agent][0], today, ctx)  # noqa: E731
        started = time.time()
        self.emit({"type": "start", "steps": steps, "models": {"quick": self.quick.label, "deep": self.deep.label}})

        # ── 1. 分析师团队（并行）──
        self.emit({"type": "stage", "stage": "analysts", "label": STAGES["analysts"]})
        is_fund = bool(report.get("fund"))
        briefs = {
            "market": prompts.MARKET_ANALYST.format(dossier=dossier.market_dossier(report)),
            "fundamentals": (prompts.FUND_ANALYST if is_fund else prompts.FUNDAMENTALS_ANALYST).format(
                dossier=dossier.fundamentals_dossier(report)),
            "news": prompts.NEWS_ANALYST.format(dossier=dossier.news_dossier(report)),
        }
        analyst_steps = [s for s in steps if s["stage"] == "analysts"]
        reports: dict[str, str] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(analyst_steps)) as pool:
            futures = {s["agent"]: pool.submit(self._speak, s, self.quick, sys_for(s["agent"]), briefs[s["agent"]])
                       for s in analyst_steps}
            for key, fut in futures.items():
                try:
                    reports[key] = fut.result()
                except LLMError as exc:
                    errors[key] = str(exc)
                    reports[key] = ""
        self._check()
        if not any(reports.values()):
            raise LLMError(next(iter(errors.values()), "所有分析师都未能完成报告"))

        # ── 2. 多空辩论 → 研究主管 ──
        self.emit({"type": "stage", "stage": "research", "label": STAGES["research"]})
        debate: list[dict] = []
        history = ""
        last_bull = last_bear = ""
        for rnd in range(1, options.debate_rounds + 1):
            step = by_id[f"bull-{rnd}"]
            last_bull = self._speak(step, self.quick, sys_for("bull"), prompts.bull(reports, quant, history, last_bear))
            debate.append({"id": step["id"], "agent": "bull", "round": rnd, "text": last_bull})
            history += f"\n\n【多头研究员 · 第 {rnd} 轮】\n{last_bull}"
            step = by_id[f"bear-{rnd}"]
            last_bear = self._speak(step, self.quick, sys_for("bear"), prompts.bear(reports, quant, history, last_bull))
            debate.append({"id": step["id"], "agent": "bear", "round": rnd, "text": last_bear})
            history += f"\n\n【空头研究员 · 第 {rnd} 轮】\n{last_bear}"
        plan_text = self._speak(by_id["research_manager"], self.deep, sys_for("research_manager"),
                                prompts.research_manager(history.strip(), quant))
        research_rating = rating.parse_rating(plan_text)

        # ── 3. 交易员 ──
        self.emit({"type": "stage", "stage": "trading", "label": STAGES["trading"]})
        trader_text = self._speak(by_id["trader"], self.quick, sys_for("trader"),
                                  prompts.trader(plan_text, reports.get("market", ""), dossier.levels_brief(report), position, unit))
        trade = parse_trader(trader_text, report["price"]["last"])

        # ── 4. 风控辩论 ──
        self.emit({"type": "stage", "stage": "risk", "label": STAGES["risk"]})
        risk: list[dict] = []
        risk_history = ""
        last = {"aggressive": "", "conservative": "", "neutral": ""}
        speakers = (("aggressive", prompts.aggressive, ("conservative", "neutral")),
                    ("conservative", prompts.conservative, ("aggressive", "neutral")),
                    ("neutral", prompts.neutral, ("aggressive", "conservative")))
        for rnd in range(1, options.risk_rounds + 1):
            for agent, build, others in speakers:
                step = by_id[f"{agent}-{rnd}"]
                user = build(trader_text, reports, position, risk_history.strip(), last[others[0]], last[others[1]])
                text = self._speak(step, self.quick, sys_for(agent), user)
                last[agent] = text
                risk.append({"id": step["id"], "agent": agent, "round": rnd, "text": text})
                risk_history += f"\n\n【{AGENTS[agent][0]} · 第 {rnd} 轮】\n{text}"

        # ── 5. 投资经理 ──
        self.emit({"type": "stage", "stage": "decision", "label": STAGES["decision"]})
        lessons = dossier.past_decisions_brief(past or [], report)
        final_text = self._speak(by_id["portfolio_manager"], self.deep, sys_for("portfolio_manager"),
                                 prompts.portfolio_manager(plan_text, trader_text, risk_history.strip(), quant, position, lessons))
        final = parse_final(final_text)
        self.emit({"type": "decision", "data": final})

        return {
            "instrument": report["instrument"],
            "as_of": report["as_of"],
            "price": report["price"]["last"],
            "currency_label": unit,
            "models": {"quick": self.quick.label, "deep": self.deep.label},
            "options": {"analysts": [s["agent"] for s in analyst_steps], "debate_rounds": options.debate_rounds,
                        "risk_rounds": options.risk_rounds, "position": options.position},
            "steps": steps,
            "analysts": reports,
            "analyst_errors": errors,
            "debate": debate,
            "research": {"text": plan_text, "rating": research_rating, "label": rating.label(research_rating)},
            "trader": trade,
            "risk": risk,
            "final": final,
            "quant": {"composite": report["scores"]["composite"], "rating": report["scores"]["rating"]},
            "used_past": len(past or []),
            "elapsed": round(time.time() - started, 1),
            "finished_at": beijing_now().strftime("%Y-%m-%d %H:%M"),
        }


def parse_trader(text: str, price: float | None) -> dict:
    data = rating.json_block(text)
    action = rating.normalize_action(data.get("action")) if data else None
    if action is None:
        import re
        m = re.search(r"操作[*\s]*[:：][*\s]*(买入|持有|观望|卖出)", text)
        action = rating.normalize_action(m.group(1)) if m else None
    entry, stop, take = (rating.to_float(data.get(k)) for k in ("entry_price", "stop_loss", "take_profit"))
    warnings = []
    # 价格落地校验（学自 TradingAgents 的 Trader price grounding）：方向错了或离现价太远的价位要提示
    if price:
        if action == "Buy" and stop is not None and stop >= price:
            warnings.append("止损价不低于现价，与买入方向矛盾，请谨慎参考")
        if action == "Buy" and take is not None and take <= price:
            warnings.append("目标价不高于现价，与买入方向矛盾，请谨慎参考")
        for name, v in (("入场价", entry), ("止损价", stop), ("目标价", take)):
            if v is not None and abs(v / price - 1) > 0.5:
                warnings.append(f"{name} {v} 与现价 {price} 相差超过 50%，可能有误")
    return {
        "text": text, "action": action or rating.REVIEW,
        "label": rating.TRADER_LABELS.get(action or "", "待复核"),
        "entry": entry, "stop": stop, "take": take,
        "position": str(data.get("position") or "") if data else "",
        "warnings": warnings,
    }


def parse_final(text: str) -> dict:
    data = rating.json_block(text)
    code = (rating.normalize(data.get("rating")) if data else None) or rating.parse_rating(text)
    confidence = str(data.get("confidence") or "") if data else ""
    return {
        "text": text, "rating": code, "label": rating.label(code),
        "price_target": rating.to_float(data.get("price_target")) if data else None,
        "time_horizon": str(data.get("time_horizon") or "") if data else "",
        "confidence": confidence if confidence in ("高", "中", "低") else "",
        "summary": str(data.get("summary") or "") if data else "",
    }


def to_markdown(result: dict) -> str:
    """深度分析报告全文（导出用）。"""
    inst = result["instrument"]
    name = f"{inst['name']}（{inst['code']}）" if inst.get("name") else inst["code"]
    final, trade, research = result["final"], result["trader"], result["research"]
    strip = rating.strip_json_block
    lines = [
        f"# {name} AI 深度分析报告",
        "",
        f"- 生成时间：{result['finished_at']}　数据日期：{result['as_of']}",
        f"- 模型：{result['models']['quick']}（分析与辩论），{result['models']['deep']}（研究主管与投资经理）",
        f"- 流程：{len(result['options']['analysts'])} 位分析师 → 多空辩论 {result['options']['debate_rounds']} 轮 → 研究主管 → 交易员 → 风控辩论 {result['options']['risk_rounds']} 轮 → 投资经理",
        "",
        f"## 最终结论：{final['label']}（{final['rating']}）",
        "",
    ]
    if final.get("summary"):
        lines += [f"> {final['summary']}", ""]
    facts = []
    if final.get("price_target"):
        facts.append(f"目标价 {final['price_target']} {result['currency_label']}")
    if final.get("time_horizon"):
        facts.append(f"持有期 {final['time_horizon']}")
    if final.get("confidence"):
        facts.append(f"信心 {final['confidence']}")
    if facts:
        lines += ["　".join(facts), ""]
    lines += [strip(final["text"]), ""]
    lines += ["## 交易方案", "", f"操作：{trade['label']}　入场 {trade['entry'] or '—'}　止损 {trade['stop'] or '—'}　目标 {trade['take'] or '—'}　仓位 {trade['position'] or '—'}", ""]
    for w in trade.get("warnings", []):
        lines.append(f"> ⚠️ {w}")
    lines += [strip(trade["text"]), ""]
    lines += [f"## 研究主管：{research['label']}", "", strip(research["text"]), ""]
    titles = {"market": "技术面分析", "fundamentals": "基本面分析", "news": "资讯与情绪分析"}
    for key, text in result["analysts"].items():
        lines += [f"## {titles.get(key, key)}", "", text or f"（未完成：{result['analyst_errors'].get(key, '无')}）", ""]
    lines += ["## 多空辩论", ""]
    for d in result["debate"]:
        lines += [f"### {AGENTS[d['agent']][0]} · 第 {d['round']} 轮", "", d["text"], ""]
    lines += ["## 风控讨论", ""]
    for d in result["risk"]:
        lines += [f"### {AGENTS[d['agent']][0]} · 第 {d['round']} 轮", "", d["text"], ""]
    lines += ["---", "", "*本报告由大模型多智能体自动生成，仅供研究与学习参考，不构成任何投资建议。模型可能出错，请独立判断。*", ""]
    return "\n".join(lines)
