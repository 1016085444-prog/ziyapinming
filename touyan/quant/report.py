"""快速分析报告：把行情数据算成一份结构化结果（给界面）和一份 Markdown（给导出、命令行）。

这份结果也是 AI 深度分析的「事实底稿」：智能体只拿这里的数字说话。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from market.models import CURRENCY_LABELS, MarketData
from quant import fund, fundamental, metrics, scoring, technical

DISCLAIMER = (
    "本报告由程序根据公开行情数据自动生成，仅供研究与学习参考，不构成任何投资建议。"
    "历史表现不代表未来，市场有风险，投资需谨慎。"
)


def _r(x, n: int = 4):
    if x is None:
        return None
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def _rl(xs, n: int = 4) -> list:
    return [_r(x, n) for x in xs]


def scoring_kind(md: MarketData) -> str:
    inst = md.instrument
    if inst.kind == "stock" and inst.market != "CSV":
        return "stock"
    if inst.market == "OF":
        return "fund"
    if inst.kind == "etf" and md.fund is not None:
        return "etf"
    return "index"


def beijing_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def build(md: MarketData, rf: float = 0.02, chart_bars: int = 800) -> dict:
    inst = md.instrument
    bars = md.bars
    tech = technical.compute(bars)
    lv = technical.levels(bars, tech)
    windows = metrics.all_windows(bars, md.benchmark_bars, rf)
    rets = metrics.period_returns(bars)
    bench_rets = metrics.period_returns(md.benchmark_bars) if md.benchmark_bars else {}
    main_window = windows.get("1y") or windows.get("all") or {}

    sigs = technical.signals(bars, tech) + technical.risk_signals(main_window)
    kind = scoring_kind(md)
    missing: list[str] = []
    industry = md.company.get("industry") or (md.quote.industry if md.quote else "")

    fundamentals = None
    if kind == "stock":
        fundamentals = fundamental.analyze(inst, md.quote, md.financials, industry)
        sigs += fundamentals["signals"]
        if not md.financials:
            missing.append("财务数据未取到")
    fundinfo = None
    if md.fund is not None or inst.market == "OF":
        bench_name = md.benchmark.name if md.benchmark else "基准"
        fundinfo = fund.analyze(inst, md.fund, windows, rets, bench_name)
        sigs += fundinfo["signals"]
    if not md.benchmark_bars:
        missing.append("基准指数数据未取到")
    scores = scoring.score(kind, sigs, len(bars), missing)

    last, prev = bars[-1], bars[-2] if len(bars) > 1 else bars[-1]
    q = md.quote
    price = q.price if q and q.price else last.close
    change_pct = q.change_pct if q and q.change_pct is not None else (last.close / prev.close - 1) * 100
    change = q.change if q and q.change is not None else last.close - prev.close
    is_nav = inst.market == "OF" or not tech["has_ohlc"]

    # 基准按日期对齐、归一化到首日 = 实例首日价格，便于在同一张图上比较
    tail = bars[-chart_bars:]
    bench_map = {b.date: b.adj_close for b in md.benchmark_bars}
    bench_series = []
    base_inst = base_bench = None
    for b in tail:
        m = bench_map.get(b.date)
        if m is not None and base_bench is None:
            base_inst, base_bench = b.adj_close, m
        bench_series.append(_r(m / base_bench * base_inst) if (m is not None and base_bench) else None)
    adj_ratio = [b.adj_close / b.close if b.close else 1 for b in tail]
    series = tech["series"]
    n = len(tail)
    chart = {
        "dates": [b.date for b in tail],
        "open": _rl(b.open for b in tail), "high": _rl(b.high for b in tail),
        "low": _rl(b.low for b in tail), "close": _rl(b.close for b in tail),
        "volume": [b.volume for b in tail],
        "adj": _rl(b.adj_close for b in tail) if any(abs(r - 1) > 1e-9 for r in adj_ratio) else None,
        "benchmark": bench_series if any(v is not None for v in bench_series) else None,
        "drawdown": _rl(metrics.drawdown_series(tail), 4),
        **{k: _rl(v[-n:]) for k, v in series.items()},
    }

    latest = {k: _r(v) for k, v in tech["latest"].items()}
    report = {
        "instrument": inst.to_dict(),
        "kind": kind,
        "as_of": last.date,
        "intraday": last.date == beijing_today() and inst.market in ("SH", "SZ", "BJ", "HK"),
        "fetched_at": md.fetched_at,
        "sources": md.sources,
        "warnings": md.warnings,
        "currency": inst.currency,
        "currency_label": "点" if inst.kind == "index" else CURRENCY_LABELS.get(inst.currency, inst.currency),
        "volume_unit": md.volume_unit,
        "is_nav": is_nav,
        "price": {"last": _r(price), "change": _r(change), "change_pct": _r(change_pct, 2), "date": last.date},
        "quote": asdict(q) if q else None,
        "company": md.company,
        "industry": industry,
        "benchmark": md.benchmark.to_dict() if md.benchmark else None,
        "indicators": latest,
        "levels": {k: (_r(v) if not isinstance(v, list) else v) for k, v in lv.items()},
        "signals": [s.to_dict() for s in sigs],
        "returns": {k: _r(v) for k, v in rets.items()},
        "benchmark_returns": {k: _r(v) for k, v in bench_rets.items()},
        "metrics": {k: {kk: (_r(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in windows.items()},
        "monthly": [{"month": m["month"], "return": _r(m["return"])} for m in metrics.monthly_returns(bars)],
        "fundamentals": _strip_signals(fundamentals),
        "fund": _strip_signals(fundinfo),
        "scores": scores,
        "news": [asdict(n) for n in md.news[:15]],
        "market_news": [asdict(n) for n in md.market_news[:20]],
        "chart": chart,
        "risk_free_rate": rf,
        "disclaimer": DISCLAIMER,
    }
    report["summary"] = summary_text(report)
    return report


def _strip_signals(section: dict | None) -> dict | None:
    if section is None:
        return None
    return {k: v for k, v in section.items() if k != "signals"}


def fmt_pct(x, digits: int = 2, signed: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def fmt_num(x, digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:,.{digits}f}"


def fmt_money(x) -> str:
    if x is None:
        return "—"
    if abs(x) >= 1e12:
        return f"{x / 1e12:.2f} 万亿"
    if abs(x) >= 1e8:
        return f"{x / 1e8:.2f} 亿"
    if abs(x) >= 1e4:
        return f"{x / 1e4:.2f} 万"
    return f"{x:.2f}"


def summary_text(r: dict) -> str:
    inst = r["instrument"]
    p = r["price"]
    s = r["scores"]
    unit = "净值" if r["is_nav"] else "最新价"
    name = f"{inst['name']}（{inst['code']}）" if inst["name"] else inst["code"]
    dims = "、".join(f"{d['label']} {d['score']:.0f}" for d in s["dimensions"] if d["score"] is not None)
    text = (f"{name}{unit} {fmt_num(p['last'], 4 if r['is_nav'] else 2)} {r['currency_label']}"
            f"（{p['change_pct']:+.2f}%，{p['date']}）。量化综合评分 {s['composite']:.1f}（中性为 50），"
            f"对应「{s['rating']['label']}」，置信度{s['confidence']}。各维度：{dims}。")
    if s["pros"]:
        text += "主要正面因素：" + "；".join(x["text"] for x in s["pros"][:3]) + "。"
    if s["cons"]:
        text += "主要负面因素：" + "；".join(x["text"] for x in s["cons"][:3]) + "。"
    return text


def to_markdown(r: dict) -> str:
    """快速分析的 Markdown 版本（导出 / 命令行）。"""
    inst = r["instrument"]
    s = r["scores"]
    lines = [
        f"# {inst['name'] or inst['code']}（{inst['code']}）量化分析",
        "",
        f"- 品种：{inst['market_label']} · {inst['kind_label']}　数据日期：{r['as_of']}　生成时间：{r['fetched_at']}",
        f"- 数据来源：" + "，".join(f"{k}：{v}" for k, v in r["sources"].items()),
        "",
        f"**量化综合评分 {s['composite']:.1f} → {s['rating']['label']}（{s['rating']['code']}）**，置信度{s['confidence']}。",
        "",
        r["summary"],
        "",
        "## 维度评分",
        "",
        "| 维度 | 得分 | 主要依据 |",
        "|---|---:|---|",
    ]
    for d in s["dimensions"]:
        ev = "；".join(e["text"] for e in d["evidence"][:3]) or "数据不足"
        score_text = "—" if d["score"] is None else f"{d['score']:.0f}"
        lines.append(f"| {d['label']} | {score_text} | {ev} |")
    rets = r["returns"]
    br = r["benchmark_returns"]
    bname = (r.get("benchmark") or {}).get("name", "基准")
    lines += ["", "## 区间收益", "", f"| 区间 | 本品种 | {bname} |", "|---|---:|---:|"]
    for key, label in (("1m", "近1月"), ("3m", "近3月"), ("6m", "近6月"), ("ytd", "今年以来"), ("1y", "近1年"), ("3y", "近3年")):
        lines.append(f"| {label} | {fmt_pct(rets.get(key))} | {fmt_pct(br.get(key))} |")
    lines += ["", "## 风险指标", "", "| 指标 | " + " | ".join(metrics.WINDOW_LABELS[k] for k in r["metrics"]) + " |",
              "|---|" + "---:|" * len(r["metrics"])]
    rows = (("年化收益", "cagr", True), ("年化波动", "volatility", False), ("最大回撤", "max_drawdown", True),
            ("夏普比率", "sharpe", None), ("索提诺比率", "sortino", None), ("卡玛比率", "calmar", None),
            ("贝塔", "beta", None), ("超额收益", "excess_return", True))
    for label, key, pct in rows:
        cells = []
        for m in r["metrics"].values():
            v = m.get(key)
            cells.append(fmt_pct(v, 2, bool(pct)) if pct is not None else fmt_num(v, 2))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lv = r["levels"]
    lines += ["", "## 关键价位", ""]
    for item in lv.get("resistances", []):
        lines.append(f"- 压力 {fmt_num(item['price'])}：{item['label']}")
    for item in lv.get("supports", []):
        lines.append(f"- 支撑 {fmt_num(item['price'])}：{item['label']}")
    if lv.get("atr"):
        lines.append(f"- ATR(14) {fmt_num(lv['atr'])}（约 {lv['atr_pct'] * 100:.1f}% 的日均波幅）")
    if r["warnings"]:
        lines += ["", "## 数据提示", ""] + [f"- {w}" for w in r["warnings"]]
    lines += ["", "---", "", f"*{r['disclaimer']}*", ""]
    return "\n".join(lines)
