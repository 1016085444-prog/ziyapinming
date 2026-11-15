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
    out += [f"- {line}" for line in c.get("more") or []]
    r = c.get("recent") or {}
    if r.get("n"):
        line = (f"**最近的实际表现**：按同样的规则回看，{r['days']} 个日子共 {r['n']} 笔，{r['win_rate'] * 100:.0f}% 赚钱，"
                f"平均每笔 {_pct(r['mean'])}")
        if r.get("baseline") is not None:
            line += f"；同样的日子随便买是 {_pct(r['baseline'])}"
        out += ["", line + "。样本少，只能看个大概。"]
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
    if plan.get("stop_note"):
        out.append(f"**关于止损**：{plan['stop_note']}")
    if p.get("risks"):
        out.append("**风险**：" + "；".join(p["risks"]))
    return out


def gauge_text(g: dict) -> list[str]:
    f = g["facts"]
    on = [p for p in g["parts"] if p["on"]]
    out = ["", f"### 大盘预估分：{g['score']:+d} · {g['label']}", g["basis"], "",
           f"- 今天：全市场平均 {_pct(f['change'])}，{f['limit_up']} 只涨停、{f['limit_down']} 只跌停，"
           + (f"成交额是近 20 日均值的 {f['amount_ratio']:.2f} 倍" if f.get("amount_ratio") else "成交额对比不出来")
           + f"；明天是{f['next_weekday']}"]
    out.append("- 加减分：" + ("、".join(f"{p['label']} {p['points']:+d}（{p['detail']}）" for p in on) if on else "没有一项触发"))
    st = g.get("style")
    if st:
        out.append(f"- 风格：**{st['label']}**——{'；'.join(st['notes'])}。{st['advice']}")
    if g.get("hot_sectors"):
        out.append("- 今天涨停最集中的板块（不碰）：" + "、".join(f"{h['name']}（{h['limit_up']}/{h['total']}）" for h in g["hot_sectors"]))
    out += ["", "| 分数 | 近十年：天数占比 | 之后 5 天平均 | 上涨的日子 | 更早的十年：之后 5 天平均 | 上涨的日子 |", "|---|---:|---:|---:|---:|---:|"]
    for r in g["table"]:
        mark = " ← 今天" if r["current"] else ""
        out.append(f"| {r['bucket']}{mark} | {r['new']['share'] * 100:.0f}% | {_pct(r['new']['after'], 2)} | {r['new']['up'] * 100:.0f}% | "
                   f"{_pct(r['old']['after'], 2)} | {r['old']['up'] * 100:.0f}% |")
    return out


def board_text(b: dict) -> list[str]:
    out = ["", f"## {b['title']} · {b['name']}（{b['horizon']}）", b["idea"]]
    if b.get("gauge"):
        out += gauge_text(b["gauge"])
    if b.get("timing"):
        out += ["", f"**买入时机**：{b['timing']['text']}"]
    out += [""] + checkup_text(b["checkup"])
    f = b.get("funnel") or {}
    if b.get("note"):
        out += ["", b["note"]]
    elif not b["picks"]:
        reasons = "；".join(f"{k} {v} 只" for k, v in list((f.get("reasons") or {}).items())[:4])
        out += ["", "今天没有符合条件的。" + (f"没入选的主要原因：{reasons}。" if reasons else "")]
    for i, p in enumerate(b["picks"], 1):
        out += pick_text(i, p)
    etfs = b.get("etfs")
    if etfs and etfs.get("picks"):
        out += ["", "### 也可以直接买宽基 ETF", etfs["how"]]
        for e in etfs["picks"]:
            out += ["", f"**{e['name']}（{e['code']}）**" + (f" · 最新 {e['price']}" if e.get("price") else ""), e["why"]]
            out += [f"- {r}" for r in e["rules"]]
    avoid = b.get("avoid")
    if avoid and avoid.get("names"):
        out += ["", "### 今天最热的（别追）", avoid["note"], "",
                "、".join(f"{a['name']}（近 20 天 {_pct(a['r20'], 0)}）" for a in avoid["names"])]
    funds = b.get("funds")
    if funds:
        out += ["", "### 长期持有的基金"]
        if not funds["picks"]:
            out.append("今天没有基金通过全部检查。")
        for i, p in enumerate(funds["picks"], 1):
            out += pick_text(i, p)
    if b.get("ranking"):
        out += ["", "| 指数 | 基金 | 温度 | 这个月 | 定投3年赚钱概率 | 中位收益 | 折合年化 | 较差的一成 |", "|---|---|---:|---|---:|---:|---:|---:|"]
        for r in b["ranking"]:
            out.append(f"| {r['index']} | {r['name']} | {r['temp'] if r['temp'] is not None else '—'} | {r['advice']} | "
                       f"{r['win_rate']:.0f}% | {_pct(r['median'], 0, False)} | {_pct(r['irr'], 1, False)} | {_pct(r['p10'], 0, False)} |")
    for q in b.get("faq") or []:
        out += ["", f"**问：{q['q']}**", q["a"]]
    return out


def to_markdown(p: dict) -> str:
    if not p.get("boards"):
        return f"# 每日精选 · {p.get('as_of', '')}\n\n这条记录是旧版本生成的，结构和现在的四个板块不同，不再展示。\n"
    label = f"（{p['as_of_label']}）" if p.get("as_of_label") else ""
    m = p["market"]
    out = [f"# 每日精选 · {p['as_of']}{label}", "", f"> {p['disclaimer']}", ""]
    reg = m["regime"]
    out += ["## 大盘", f"- 走势：**{reg['label']}**（{'；'.join(reg['notes'])}）"]
    g = p.get("gauge")
    if g:
        out.append(f"- 大盘预估分：**{g['score']:+d} · {g['label']}**。{g['basis']}")
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
