"""核验数据简报：把量化报告（quant/report.py 的输出）写成给各个智能体看的文字材料。

学自 TradingAgents 的 verified market snapshot：大模型容易编造精确数字（一条从未出现
的布林带、一次「历史验证过的反弹」），所以每个分析师都拿到一份由程序计算的简报，
并被要求「引用具体数字时以此为准」。简报里没有的东西，就明确写「没有」——
空白会被模型当成「没有利空」来填补，明说缺失才不会（TradingAgents #1176）。
"""

from __future__ import annotations

from quant.report import fmt_money, fmt_num, fmt_pct

_DIR = {1: "偏多", 0: "中性", -1: "偏空"}


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _digits(r: dict) -> int:
    return 4 if r["is_nav"] or (r["price"]["last"] or 0) < 5 else 2


def instrument_context(r: dict) -> str:
    inst = r["instrument"]
    name = inst["name"] or inst["code"]
    parts = [f"分析标的：{name}（代码 {inst['code']}，{inst['market_label']} · {inst['kind_label']}）"]
    if r.get("industry"):
        parts.append(f"所属行业：{r['industry']}")
    parts.append(f"计价单位：{r['currency_label']}")
    parts.append(f"最新数据日期：{r['as_of']}" + ("（今日数据可能是盘中实时数据、尚未收盘）" if r.get("intraday") else ""))
    return "；".join(parts) + "。所有输出都使用这个确切的名称与代码，不要替换成其他公司、基金或代码。"


def position_context(position: dict | None, r: dict) -> str:
    if not position:
        return ("持仓情况：用户未提供。你不知道用户是否持有、持有多少，不要假设空仓；"
                "请给出用户能按自身仓位套用的方向与仓位建议。")
    price = r["price"]["last"]
    shares = position.get("shares")
    cost = position.get("cost")
    cash = position.get("cash")
    unit = r["currency_label"]
    lines = ["用户当前持仓："]
    if shares is not None:
        if shares == 0:
            lines.append("- 当前没有持有该标的（空仓）")
        else:
            lines.append(f"- 持有 {shares:,.0f} 股/份")
            if cost:
                pnl = price / cost - 1 if price else None
                lines.append(f"- 持仓成本 {fmt_num(cost, _digits(r))} {unit}，按最新价{'浮盈' if (pnl or 0) >= 0 else '浮亏'} {fmt_pct(pnl)}")
            if price:
                lines.append(f"- 持仓市值约 {fmt_money(shares * price)} {unit}")
    if cash is not None:
        lines.append(f"- 可用资金 {fmt_money(cash)} {unit}")
    lines.append("请结合实际持仓给出可执行的操作（加仓、减仓、持有或建仓的具体比例）。")
    return "\n".join(lines)


def quant_brief(r: dict) -> str:
    s = r["scores"]
    dims = "，".join(f"{d['label']} {d['score']:.0f}" for d in s["dimensions"] if d["score"] is not None)
    lines = [
        f"规则模型综合评分 {s['composite']:.1f}/100（50 为中性）→「{s['rating']['label']}」，置信度{s['confidence']}。",
        f"各维度：{dims}。",
    ]
    if s["pros"]:
        lines.append("主要正面：" + "；".join(x["text"] for x in s["pros"]))
    if s["cons"]:
        lines.append("主要负面：" + "；".join(x["text"] for x in s["cons"]))
    lines.append("（这是按固定规则打的分，不考虑新闻和定性因素，可以不同意，但要说明理由。）")
    return "\n".join(lines)


def _returns_table(r: dict) -> list[str]:
    bench = (r.get("benchmark") or {}).get("name", "基准")
    rets, br = r["returns"], r["benchmark_returns"]
    rows = ["| 区间 | 本标的 | " + bench + " |", "|---|---:|---:|"]
    for key, label in (("1w", "近1周"), ("1m", "近1月"), ("3m", "近3月"), ("6m", "近6月"),
                       ("ytd", "今年以来"), ("1y", "近1年"), ("3y", "近3年")):
        if rets.get(key) is None and br.get(key) is None:
            continue
        rows.append(f"| {label} | {fmt_pct(rets.get(key))} | {fmt_pct(br.get(key))} |")
    return rows


def _risk_table(r: dict) -> list[str]:
    windows = r["metrics"]
    if not windows:
        return ["（数据不足，未计算风险指标）"]
    names = {"1y": "近1年", "3y": "近3年", "all": "全部数据"}
    rows = ["| 指标 | " + " | ".join(names[k] for k in windows) + " |", "|---|" + "---:|" * len(windows)]
    spec = (("区间收益", "total_return", "pct"), ("年化收益", "cagr", "pct"), ("年化波动率", "volatility", "pct0"),
            ("最大回撤", "max_drawdown", "pct"), ("夏普比率", "sharpe", "num"), ("索提诺比率", "sortino", "num"),
            ("卡玛比率", "calmar", "num"), ("贝塔", "beta", "num"), ("相关系数", "correlation", "num"),
            ("超额收益", "excess_return", "pct"), ("单日VaR(95%)", "var95", "pct0"))
    for label, key, kind in spec:
        cells = []
        for m in windows.values():
            v = m.get(key)
            cells.append(fmt_pct(v) if kind == "pct" else fmt_pct(v, 2, False) if kind == "pct0" else fmt_num(v, 2))
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    one = windows.get("1y") or windows.get("all") or {}
    if one.get("drawdown_peak"):
        rec = one.get("drawdown_recover") or "尚未修复"
        rows.append(f"\n最大回撤区间：{one['drawdown_peak']} → {one['drawdown_trough']}，修复日期：{rec}。")
    return rows


def _signals(r: dict, dims: tuple[str, ...]) -> list[str]:
    out = []
    for s in r["signals"]:
        if s["dimension"] in dims:
            out.append(f"- [{_DIR[_sign(s['impact'])]}] {s['name']}（{s['value']}）：{s['detail']}")
    return out or ["（无）"]


def _dim_scores(r: dict, keys: tuple[str, ...]) -> str:
    items = [f"{d['label']} {d['score']:.0f}" for d in r["scores"]["dimensions"] if d["key"] in keys and d["score"] is not None]
    return "，".join(items) if items else "（无）"


def market_dossier(r: dict) -> str:
    ind = r["indicators"]
    lv = r["levels"]
    ch = r["chart"]
    dg = _digits(r)
    unit = r["currency_label"]
    p = r["price"]
    lines = [
        f"## 已核验的行情数据快照（截至 {r['as_of']}）",
        "以下数字均由程序根据原始行情计算，是引用价格与指标时的唯一依据。",
        f"数据来源：{r['sources'].get('行情') or r['sources'].get('净值', '—')}；价格为前复权（基金为单位净值，收益按复权净值计算）。",
        "",
        "### 最新行情",
        "| 项目 | 数值 |", "|---|---:|",
        f"| {'单位净值' if r['is_nav'] else '最新价'} | {fmt_num(p['last'], dg)} {unit} |",
        f"| 涨跌幅 | {p['change_pct']:+.2f}% |",
    ]
    if not r["is_nav"]:
        lines.append(f"| 今开 / 最高 / 最低 | {fmt_num(ch['open'][-1], dg)} / {fmt_num(ch['high'][-1], dg)} / {fmt_num(ch['low'][-1], dg)} |")
    if ch["volume"] and ch["volume"][-1]:
        lines.append(f"| 成交量 | {ch['volume'][-1]:,.0f} {r['volume_unit']} |")
    if ind.get("volume_ratio") is not None:
        lines.append(f"| 量比（对比前5日均量） | {ind['volume_ratio']:.2f} |")
    q = r.get("quote") or {}
    if q.get("turnover") is not None:
        lines.append(f"| 换手率 | {q['turnover']:.2f}% |")

    lines += ["", "### 最近 20 个交易日", "| 日期 | 收盘 | 涨跌幅 |", "|---|---:|---:|"]
    closes, dates = ch["close"], ch["dates"]
    for i in range(max(1, len(closes) - 20), len(closes)):
        chg = closes[i] / closes[i - 1] - 1 if closes[i - 1] else None
        lines.append(f"| {dates[i]} | {fmt_num(closes[i], dg)} | {fmt_pct(chg)} |")

    lines += ["", "### 技术指标（最新值，口径同通达信 / 东方财富）", "| 指标 | 数值 |", "|---|---:|"]
    for key, label in (("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"), ("ma60", "MA60"), ("ma120", "MA120"),
                       ("ma250", "MA250（年线）"), ("dif", "MACD DIF"), ("dea", "MACD DEA"), ("macd", "MACD 柱（2×(DIF−DEA)）"),
                       ("rsi6", "RSI(6)"), ("rsi14", "RSI(14)"), ("k", "KDJ K"), ("d", "KDJ D"), ("j", "KDJ J"),
                       ("boll_up", "布林上轨"), ("boll_mid", "布林中轨"), ("boll_low", "布林下轨"), ("atr14", "ATR(14)")):
        v = ind.get(key)
        if v is not None:
            lines.append(f"| {label} | {fmt_num(v, 3 if key in ('dif', 'dea', 'macd') else dg if key.startswith(('ma', 'boll', 'atr')) else 1)} |")

    lines += ["", "### 关键价位（程序识别）"]
    for item in lv.get("resistances", []):
        lines.append(f"- 压力 {fmt_num(item['price'], dg)}：{item['label']}")
    for item in lv.get("supports", []):
        lines.append(f"- 支撑 {fmt_num(item['price'], dg)}：{item['label']}")
    if lv.get("high_52w"):
        pos = lv.get("pos_52w")
        lines.append(f"- 52 周最高 {fmt_num(lv['high_52w'], dg)}，最低 {fmt_num(lv['low_52w'], dg)}"
                     + (f"，当前处于区间 {pos * 100:.0f}% 位置" if pos is not None else ""))
    if lv.get("atr"):
        lines.append(f"- ATR(14) = {fmt_num(lv['atr'], dg)}，约为价格的 {lv['atr_pct'] * 100:.1f}%")

    lines += ["", "### 区间收益（复权）"] + _returns_table(r)
    lines += ["", "### 风险指标"] + _risk_table(r)
    lines += ["", "### 程序识别的技术信号"] + _signals(r, ("trend", "momentum", "risk"))
    lines += ["", f"### 量化评分（规则模型）：{_dim_scores(r, ('trend', 'momentum', 'risk'))}"]
    return "\n".join(lines)


def fundamentals_dossier(r: dict) -> str:
    if r.get("fund"):
        return _fund_dossier(r)
    f = r.get("fundamentals")
    lines = ["## 基本面数据"]
    if not f or not f.get("available"):
        lines.append("（本次没有取到该标的的财务与估值数据。不要凭记忆补充财务数字，请明确说明基本面信息缺失。）")
        return "\n".join(lines)
    v = f["valuation"]
    unit = r["currency_label"]
    lines += [
        f"数据来源：{r['sources'].get('财务', '东方财富')}；估值来自行情快照（{(r.get('quote') or {}).get('source', '—')}）。",
        "",
        "### 估值",
        f"- 市盈率（动态）：{fmt_num(v['pe'], 2)} 倍" + ("（为负表示亏损）" if (v['pe'] or 0) < 0 else ""),
        f"- 市净率：{fmt_num(v['pb'], 2)} 倍",
        f"- PEG：{fmt_num(v['peg'], 2)}" if v.get("peg") else "- PEG：无法计算（利润增速非正或缺失）",
        f"- 总市值：{fmt_money(v['total_cap'])} {unit}；流通市值：{fmt_money(v['float_cap'])} {unit}",
        "（数据中没有同行业公司的估值对比。）",
    ]
    if f.get("is_financial"):
        lines.append("（该公司属于金融行业：高负债率是经营特征，没有传统意义上的毛利率。）")
    lt = f.get("latest")
    if lt:
        roe_note = "（按报告期年化）" if lt.get("roe_annualized") != lt.get("roe") else ""
        lines += [
            "", f"### 最新报告期：{lt.get('report_name') or lt['report_date']}",
            f"- 营业收入：{fmt_money(lt.get('revenue'))} {unit}，同比 {fmt_num(lt.get('revenue_yoy'), 2)}%",
            f"- 归母净利润：{fmt_money(lt.get('net_profit'))} {unit}，同比 {fmt_num(lt.get('net_profit_yoy'), 2)}%",
            f"- 扣非净利润同比：{fmt_num(lt.get('deduct_profit_yoy'), 2)}%",
            f"- ROE：{fmt_num(lt.get('roe_annualized'), 2)}%{roe_note}",
            f"- 毛利率：{fmt_num(lt.get('gross_margin'), 2)}%；净利率：{fmt_num(lt.get('net_margin'), 2)}%",
            f"- 资产负债率：{fmt_num(lt.get('debt_ratio'), 2)}%；流动比率：{fmt_num(lt.get('current_ratio'), 2)}",
            f"- 每股收益：{fmt_num(lt.get('eps'), 3)}；每股净资产：{fmt_num(lt.get('bps'), 3)}；每股经营现金流：{fmt_num(lt.get('ocf_per_share'), 3)}",
        ]
    hist = f.get("history") or []
    if len(hist) > 1:
        lines += ["", "### 近几期趋势", "| 报告期 | 营收同比 | 净利润同比 | ROE(年化) | 毛利率 | 负债率 |", "|---|---:|---:|---:|---:|---:|"]
        for h in hist:
            lines.append(f"| {h['report_name'] or h['report_date']} | {fmt_num(h['revenue_yoy'], 1)}% | {fmt_num(h['net_profit_yoy'], 1)}% | "
                         f"{fmt_num(h['roe'], 1)}% | {fmt_num(h['gross_margin'], 1)}% | {fmt_num(h['debt_ratio'], 1)}% |")
    company = r.get("company") or {}
    if company.get("profile"):
        lines += ["", "### 公司简介", company["profile"]]
    lines += ["", "### 程序识别的基本面信号"] + _signals(r, ("valuation", "quality", "growth"))
    lines += ["", f"### 量化评分（规则模型）：{_dim_scores(r, ('valuation', 'quality', 'growth'))}"]
    return "\n".join(lines)


def _fund_dossier(r: dict) -> str:
    fp = (r.get("fund") or {}).get("profile")
    lines = ["## 基金档案与业绩数据"]
    if not fp:
        lines.append("（本次没有取到基金档案，请明确说明信息缺失。）")
        return "\n".join(lines)
    lines += [
        f"数据来源：{r['sources'].get('基金档案', '天天基金')}",
        "",
        "### 基本信息",
        f"- 名称：{fp['name']}；类型：{fp['fund_type'] or '—'}；成立日期：{fp['establish_date'] or '—'}",
        f"- 基金公司：{fp['company'] or '—'}；托管人：{fp['custodian'] or '—'}",
        f"- 业绩比较基准：{fp['benchmark'] or '—'}",
        f"- 规模：{fmt_num(fp['scale'], 2)} 亿元（{fp['scale_date'] or '—'}）",
        f"- 申购费率：{fmt_num(fp['fee_rate'], 2)}%（原费率 {fmt_num(fp['fee_rate_original'], 2)}%）",
    ]
    if fp.get("strategy"):
        lines.append(f"- 投资策略：{fp['strategy']}")
    if fp["managers"]:
        lines.append("- 现任基金经理：" + "；".join(
            f"{m['name']}（任职 {m['tenure'] or '—'}，管理规模 {m['managed_size'] or '—'}）" for m in fp["managers"]))
    if fp.get("rank"):
        lines.append(f"- 近三月同类排名：{fp['rank']}/{fp['rank_total']}（超过 {fp['rank_beat_pct']:.0f}% 的同类）")
    if fp.get("returns"):
        names = {"1m": "近1月", "3m": "近3月", "6m": "近6月", "1y": "近1年"}
        lines.append("- 天天基金公布的区间收益：" + "，".join(f"{names.get(k, k)} {v:+.2f}%" for k, v in fp["returns"].items()))
    if fp.get("allocation"):
        lines.append(f"- 资产配置（{fp['allocation_date'] or '最新'}）：" + "，".join(f"{k} {v:.1f}%" for k, v in fp["allocation"].items()))
    if fp.get("holdings"):
        lines += ["", f"### 前十大持仓（{fp.get('holdings_period') or '最新一期'}）", "| 代码 | 名称 | 占净值 |", "|---|---|---:|"]
        for h in fp["holdings"]:
            lines.append(f"| {h['code']} | {h['name'] or '—'} | {fmt_num(h['weight'], 2) + '%' if h['weight'] is not None else '—'} |")
    if fp.get("evaluation"):
        lines.append("\n天天基金业绩评价（百分制）：" + "，".join(f"{k} {v:.0f}" for k, v in fp["evaluation"].items()))
    lines += ["", "### 区间收益（按复权净值）"] + _returns_table(r)
    lines += ["", "### 风险指标"] + _risk_table(r)
    lines += ["", "### 程序识别的基金信号"] + _signals(r, ("performance", "risk_control", "efficiency", "stability"))
    keys = ("performance", "risk_control", "efficiency", "stability")
    lines += ["", f"### 量化评分（规则模型）：{_dim_scores(r, keys)}"]
    return "\n".join(lines)


def news_dossier(r: dict) -> str:
    lines = ["## 个股新闻"]
    news = r.get("news") or []
    if news:
        lines.append(f"来源：{r['sources'].get('个股新闻', '东方财富')}，共 {len(news)} 条，按相关度排序：")
        for i, n in enumerate(news, 1):
            meta = "｜".join(x for x in (n.get("time"), n.get("source")) if x)
            lines.append(f"{i}. [{meta}] {n['title']}" + (f" —— {n['summary']}" if n.get("summary") else ""))
    else:
        lines.append("（本次没有取到与该标的直接相关的新闻。这不代表没有利好或利空，只是数据缺失。）")
    lines += ["", "## 市场快讯（宏观与市场整体）"]
    mnews = r.get("market_news") or []
    if mnews:
        lines.append(f"来源：{r['sources'].get('市场快讯', '—')}，最近 {len(mnews)} 条：")
        for i, n in enumerate(mnews, 1):
            lines.append(f"{i}. [{n.get('time', '')}] {n['title']}" + (f" —— {n['summary'][:120]}" if n.get("summary") and n["summary"] != n["title"] else ""))
    else:
        lines.append("（本次没有取到市场快讯。）")
    return "\n".join(lines)


def levels_brief(r: dict) -> str:
    lv = r["levels"]
    dg = _digits(r)
    parts = [f"当前价 {fmt_num(r['price']['last'], dg)} {r['currency_label']}"]
    parts += [f"压力 {fmt_num(x['price'], dg)}（{x['label']}）" for x in lv.get("resistances", [])]
    parts += [f"支撑 {fmt_num(x['price'], dg)}（{x['label']}）" for x in lv.get("supports", [])]
    if lv.get("atr"):
        parts.append(f"ATR(14) {fmt_num(lv['atr'], dg)}（{lv['atr_pct'] * 100:.1f}%）")
    one = (r["metrics"].get("1y") or r["metrics"].get("all") or {})
    if one.get("volatility") is not None:
        parts.append(f"近一年年化波动率 {one['volatility'] * 100:.1f}%")
    return "；".join(parts)


def past_decisions_brief(past: list[dict], r: dict) -> str:
    """同一标的的历史深度分析与之后的实际表现（学自 TradingAgents 的 memory log）。"""
    if not past:
        return ""
    dg = _digits(r)
    lines = ["【本标的的历史决策复盘】（系统根据之后的实际行情计算）"]
    for p in past[:5]:
        outcome = p.get("outcome") or {}
        if outcome.get("return") is None:
            lines.append(f"- {p['date']}：评级「{p['rating_label']}」，当时价格 {fmt_num(p.get('price'), dg)}，结果尚无足够后续行情")
            continue
        excess = outcome.get("excess")
        lines.append(f"- {p['date']}：评级「{p['rating_label']}」，当时 {fmt_num(p.get('price'), dg)} → 现在 {fmt_num(outcome.get('price'), dg)}"
                     f"，收益 {fmt_pct(outcome['return'])}" + (f"，同期超额 {fmt_pct(excess)}" if excess is not None else "")
                     + f"（{outcome.get('days', '?')} 个交易日）")
    lines.append("请从这些结果中总结经验（判断对在哪、错在哪），但不要让历史结果机械地决定本次结论；持有期很短的结果说明力有限。")
    return "\n".join(lines)
