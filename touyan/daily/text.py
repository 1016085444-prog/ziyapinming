"""把一次每日精选写成 Markdown：可以下载，也可以直接复制到微信、飞书里发。"""

from __future__ import annotations

ICONS = {"pass": "✅", "warn": "⚠️", "fail": "❌"}


def _pct(x, digits: int = 2, frac: bool = False) -> str:
    if x is None:
        return "—"
    v = x * 100 if frac else x
    return f"{v:+.{digits}f}%"


def _yi(x) -> str:
    return "—" if x is None else (f"{x / 1e8:.0f} 亿" if x < 1e12 else f"{x / 1e12:.2f} 万亿")


def plan_history_text(h: dict | None, hold_max: int) -> str:
    if not h or not h.get("trades"):
        return "历史参照：过去几年没有出现过足够的类似买点，没法参照。"
    text = (f"历史参照：过去 {h['years']} 年出现类似买点 {h['trades']} 次，照这个计划操作：平均每次 {_pct(h['avg'], 1, True)}，"
            f"赚钱的占 {h['win_rate'] * 100:.0f}%；到目标 {h['target_hits']} 次、止损 {h['stop_hits']} 次、"
            f"到期卖出 {h['time_exits']} 次，平均拿 {h['avg_days']:.0f} 个交易日。")
    if h["trades"] < 5:
        text += "样本太少，只能看个大概。"
    return text


def fund_history_text(h: dict | None, horizon: int) -> str:
    if not h:
        return ""
    span = "一年" if horizon >= 240 else "半年"
    return (f"历史参照：过去 {h['years']} 年里任意一天买入、持有满{span}，赚钱的概率 {h['win_rate'] * 100:.0f}%，"
            f"收益中位数 {_pct(h['median'], 1, True)}（运气差的 10% 情况 {_pct(h['p10'], 1, True)}，"
            f"运气好的 10% 情况 {_pct(h['p90'], 1, True)}）。")


def rotation_text(h: dict | None) -> str:
    if not h:
        return ""
    cagr = f"年化 {_pct(h['cagr'], 1, True)}，" if h.get("cagr") is not None else ""
    bench = f"同期沪深300 {_pct(h['bench_total'], 1, True)}、最大回撤 {_pct(h['bench_max_drawdown'], 1, True)}"
    weeks = f"；每只平均拿 {h['avg_hold_weeks']:.1f} 周" if h.get("avg_hold_weeks") else ""
    return (f"历史参照：按这套规则从 {h['start']} 走到 {h['end']}（约 {h['years']} 年），累计 {_pct(h['total'], 1, True)}，"
            f"{cagr}最大回撤 {_pct(h['max_drawdown'], 1, True)}；{bench}{weeks}。未计滑点，过去的表现不代表以后。")


def to_markdown(p: dict) -> str:
    m, st = p["market"], p["stocks"]
    label = f"（{p['as_of_label']}）" if p.get("as_of_label") else ""
    out = [f"# 每日精选 · {p['as_of']}{label} · {p['strategy']['label']}", "",
           f"> {p['disclaimer']}", ""]
    if p.get("intraday"):
        out += ["> 生成时今天还没收盘，用的是上一个交易日的收盘数据。", ""]
    reg = m["regime"]
    out += ["## 大盘", f"- 市场温度：**{reg['label']}**（{'；'.join(reg['notes'])}）。{reg['advice']}"]
    if m["indices"]:
        out.append("- " + " | ".join(f"{i['name']} {i['price']:.2f}（{_pct(i['change_pct'])}）"
                                     for i in m["indices"] if i.get("price") is not None))
    br = m.get("breadth")
    if br:
        out.append(f"- 上涨 {br['up']} / 下跌 {br['down']}，涨停 {br['limit_up']}、跌停 {br['limit_down']}，"
                   f"成交 {_yi(br['amount_yi'] * 1e8)}")
    if m["sectors_up"]:
        out.append("- 领涨行业：" + "、".join(f"{b['name']} {_pct(b['change_pct'])}" for b in m["sectors_up"]))
    if m["sectors_down"]:
        out.append("- 领跌行业：" + "、".join(f"{b['name']} {_pct(b['change_pct'])}" for b in m["sectors_down"]))
    if p.get("commentary"):
        out += ["", "## 今日点评", p["commentary"]]

    f = st["funnel"]
    out += ["", f"## 精选股票（全市场 {f['universe']} → 条件过滤 {f['passed_hard']} → 初选 {f['pool']} → 入选 {f['picked']}）"]
    if f.get("source"):
        out.append(f"全市场数据：{f['source']}")
    if not st["picks"]:
        reasons = {**f.get("dropped", {}), **f.get("daily_dropped", {})}
        out.append("这次没有股票同时满足全部条件。主要原因：" + "；".join(f"{k} {v} 只" for k, v in list(reasons.items())[:5]))
    for i, s in enumerate(st["picks"], 1):
        d = s["dashboard"]
        icon = "🟢" if d["signal"] == "buy" else "🟡"
        lv = d["levels"]
        out += ["", f"### {i}. {s['name']}（{s['code']}）· {s['industry'] or '行业未知'} · {icon} {d['signal_label']} · {s['score']:.0f} 分",
                f"**结论**：{d['one_sentence']}"]
        out += [f"- {ICONS[c['status']]} {c['label']}：{c['detail']}" for c in d["checklist"]]
        rr = f"（盈亏比 {lv['reward_risk']}）" if lv.get("reward_risk") else ""
        out.append(f"\n**参考价位**：理想买点 {lv['ideal_buy']} / 次优 {lv['secondary_buy']} / 止损 {lv['stop_loss']} / "
                   f"目标 {lv['target']}{rr}")
        out.append(f"**空仓者**：{d['advice']['no_position']}　**持仓者**：{d['advice']['has_position']}")
        plan = d.get("plan")
        if plan:
            out.append(f"\n**持有计划**：买入价 {plan['entry']}，目标 +{plan['target_pct']}%，最多亏 −{plan['stop_pct']}%，"
                       f"一般持有 {plan['hold_label']}（最多 {plan['hold_max']} 个交易日）")
            out += [f"- {rule}" for rule in plan["rules"]]
            out.append(plan_history_text(plan.get("history"), plan["hold_max"]))
        if d["risks"]:
            out.append("**风险**：" + "；".join(d["risks"]))

    e = p["etfs"]
    out += ["", "## ETF 动量轮动", e["note"] + "。"]
    if e["picks"]:
        out.append("入选：" + "、".join(f"{x['name']}（{x['code']}）" for x in e["picks"]))
    if e.get("safe"):
        out.append(f"防守：{e['safe']['name']}（{e['safe']['code']}）")
    if e.get("plan"):
        out += ["", "**怎么拿**："] + [f"- {r}" for r in e["plan"]["rules"]]
        if e["plan"].get("history"):
            out.append(rotation_text(e["plan"]["history"]))
    if e["ranking"]:
        out += ["", "| ETF | 近20日 | 近60日 | 近120日 | 站上20日线 |", "|---|---:|---:|---:|:---:|"]
        for x in e["ranking"][:10]:
            mo = x["momentum"]
            out.append(f"| {x['name']} | {_pct(mo['r20'], 1)} | {_pct(mo['r60'], 1)} | {_pct(mo['r120'], 1)} | "
                       f"{'是' if mo['above_ma20'] else '否'} |")

    out += ["", "## 场外基金"]
    for g in p["funds"]["groups"]:
        out += ["", f"### {g['label']}"]
        if not g["picks"]:
            out.append("今天没有基金通过全部检查。")
        for x in g["picks"]:
            r = x["returns"]
            out.append(f"- **{x['name']}（{x['code']}）**：近1年 {_pct(r.get('y1'), 1)}，近3年 {_pct(r.get('y3'), 1)}，"
                       f"近3年最大回撤 {_pct(x.get('max_drawdown_3y'), 1, frac=True)}，综合 {x['score']:.0f} 分"
                       + (f"。注意：{'；'.join(x['cons'])}" if x["cons"] else ""))
            plan = x.get("plan")
            if plan:
                out.append(f"  - 持有：{plan['hold_label']}。" + fund_history_text(plan.get("history"), plan["horizon_days"]))
        if g["picks"] and g["picks"][0].get("plan"):
            out.append("\n怎么拿：" + "；".join(g["picks"][0]["plan"]["rules"]) + "。")
    if p.get("warnings"):
        out += ["", "## 数据提示"] + [f"- {w}" for w in p["warnings"]]
    out += ["", "---", f"生成时间 {p['created_at']}（北京时间），用时 {p.get('elapsed', 0):.0f} 秒"]
    return "\n".join(out) + "\n"
