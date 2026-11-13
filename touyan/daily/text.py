"""把一次每日精选写成 Markdown：可以下载，也可以直接复制到微信、飞书里发。"""

from __future__ import annotations

ICONS = {"pass": "✅", "warn": "⚠️", "fail": "❌", "info": "・"}


def _pct(x, digits: int = 1, frac: bool = True) -> str:
    if x is None:
        return "—"
    v = round(x * 100 if frac else x, digits)
    return f"{v + 0.0:+.{digits}f}%" if v else f"{0:.{digits}f}%"


def checkup_text(c: dict) -> list[str]:
    out = [f"**方法体检**：{c.get('verdict', '')}"]
    if c.get("n"):
        line = (f"过去{c.get('span', '')}在 {c.get('stocks', 0)} 只里出现 {c['n']} 次：赚钱的占 {c['win_rate'] * 100:.0f}%，"
                f"平均 {_pct(c['mean'])}，中位 {_pct(c['median'])}，平均拿 {c['avg_days']:.0f} 个交易日")
        if c.get("baseline") is not None:
            line += f"；同一批随便买、拿同样久，平均 {_pct(c['baseline'])}"
        out.append(line + "。")
        now = c.get("now")
        if now:
            out.append(f"目前「{c['regime']}」的市场环境下 {now['n']} 次：赚钱的占 {now['win_rate'] * 100:.0f}%，中位 {_pct(now['median'])}。")
    return out


def pick_text(i: int, p: dict) -> list[str]:
    plan = p["plan"]
    head = f"### {i}. {p['name']}（{p['code']}）" + (f" · {p['industry']}" if p.get("industry") else "") + f" · {p['score']:.0f} 分"
    out = ["", head, p["headline"]]
    out += [f"- {ICONS.get(e['status'], '・')} {e['label']}：{e['detail']}" for e in p["evidence"]]
    out += ["", f"**持有时间**：{plan['horizon']}　**仓位**：{plan.get('position', '')}", f"**怎么买**：{plan['entry']}",
            "**预期收益**：" + ("（这个方法没通过历史检验，下面的数字仅供参考）" if plan["expected"].get("reliable") is False else "")
            + plan["expected"].get("text", ""), "**什么时候卖**："]
    out += [f"- {r}" for r in plan["rules"]]
    if p.get("risks"):
        out.append("**风险**：" + "；".join(p["risks"]))
    return out


def board_text(b: dict) -> list[str]:
    out = ["", f"## {b['title']} · {b['name']}（{b['horizon']}）", b["idea"], ""] + checkup_text(b["checkup"])
    f = b.get("funnel") or {}
    if not b["picks"]:
        reasons = "；".join(f"{k} {v} 只" for k, v in list((f.get("reasons") or {}).items())[:4])
        out += ["", "今天没有符合条件的。" + (f"没入选的主要原因：{reasons}。" if reasons else "")]
    for i, p in enumerate(b["picks"], 1):
        out += pick_text(i, p)
    etfs = b.get("etfs")
    if etfs:
        out += ["", "### ETF（同样的量法）", etfs["note"] + "。"] + checkup_text(etfs["checkup"])
        for i, p in enumerate(etfs["picks"], 1):
            out += pick_text(i, p)
        if etfs["ranking"]:
            out += ["", "| ETF | 类别 | 近60日 | 比沪深300 | 拟合度 | 结论 |", "|---|---|---:|---:|---:|---|"]
            for r in etfs["ranking"][:10]:
                out.append(f"| {r['name']} | {r['group']} | {_pct(r['r60'], 1, False)} | {_pct(r['excess'], 1, False)} | "
                           f"{r['r2'] if r['r2'] is not None else '—'} | {'入选' if r['score'] else r['why_not']} |")
    funds = b.get("funds")
    if funds:
        out += ["", "### 长期持有的基金"]
        if not funds["picks"]:
            out.append("今天没有基金通过全部检查。")
        for i, p in enumerate(funds["picks"], 1):
            out += pick_text(i, p)
    if b.get("ranking"):
        if b.get("note"):
            out += ["", b["note"]]
        out += ["", "| 指数 | 基金 | 温度 | 这个月 | 定投3年赚钱概率 | 中位收益 | 折合年化 | 较差的一成 |", "|---|---|---:|---|---:|---:|---:|---:|"]
        for r in b["ranking"]:
            out.append(f"| {r['index']} | {r['name']} | {r['temp'] if r['temp'] is not None else '—'} | {r['advice']} | "
                       f"{r['win_rate']:.0f}% | {_pct(r['median'], 0, False)} | {_pct(r['irr'], 1, False)} | {_pct(r['p10'], 0, False)} |")
    return out


def to_markdown(p: dict) -> str:
    if not p.get("boards"):
        return f"# 每日精选 · {p.get('as_of', '')}\n\n这条记录是旧版本生成的，结构和现在的四个板块不同，不再展示。\n"
    label = f"（{p['as_of_label']}）" if p.get("as_of_label") else ""
    m = p["market"]
    out = [f"# 每日精选 · {p['as_of']}{label}", "", f"> {p['disclaimer']}", ""]
    reg = m["regime"]
    out += ["## 大盘", f"- 市场温度：**{reg['label']}**（{'；'.join(reg['notes'])}）。{reg['advice']}"]
    if m["indices"]:
        out.append("- " + " | ".join(f"{i['name']} {i['price']:.2f}（{_pct(i['change_pct'], 2, False)}）"
                                     for i in m["indices"] if i.get("price") is not None))
    br = m.get("breadth")
    if br:
        out.append(f"- 上涨 {br['up']} / 下跌 {br['down']}，涨停 {br['limit_up']}、跌停 {br['limit_down']}，成交 {br['amount_yi']:.0f} 亿")
    if m["sectors_up"]:
        out.append("- 领涨行业：" + "、".join(f"{b['name']} {_pct(b['change_pct'], 2, False)}" for b in m["sectors_up"]))
    if p.get("commentary"):
        out += ["", "## 今日点评", p["commentary"]]
    for key in p.get("order") or p["boards"]:
        out += board_text(p["boards"][key])
    if p.get("warnings"):
        out += ["", "## 数据提示"] + [f"- {w}" for w in p["warnings"]]
    out += ["", "---", f"生成时间 {p['created_at']}（北京时间），用时 {p.get('elapsed', 0):.0f} 秒"]
    return "\n".join(out) + "\n"
