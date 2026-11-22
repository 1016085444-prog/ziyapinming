"""把一次每日精选写成 Markdown：可以下载，也可以直接复制到微信、飞书里发。"""

from __future__ import annotations

ICONS = {"pass": "✅", "warn": "⚠️", "fail": "❌", "info": "・"}
STATUS = {"sell": "该卖了", "hold": "继续拿", "wait": "等买入", "done": "已卖出", "unknown": "查不到"}


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


def _expected_line(ex: dict) -> str:
    return ("（这个方法没通过历史检验，下面的数字仅供参考）" if ex.get("reliable") is False else "") + ex.get("text", "")


def shared_expected(picks: list[dict]) -> dict | None:
    """同一个板块里每只的「预期收益」是同一段话时（整批的统计），只说一次。"""
    if len(picks) < 2:
        return None
    t = picks[0]["plan"]["expected"].get("text")
    return picks[0]["plan"]["expected"] if t and all(p["plan"]["expected"].get("text") == t for p in picks) else None


def pick_text(i: int, p: dict, shared: bool = False) -> list[str]:
    plan = p["plan"]
    if p.get("badge"):
        score = p["badge"]
    elif p.get("score_unit"):
        score = f"{p['score']:.1f}{p['score_unit']}"
    else:
        score = f"{p['score']:.0f} 分"
    head = f"### {i}. {p['name']}（{p['code']}）" + (f" · {p['industry']}" if p.get("industry") else "") + f" · {score}"
    out = ["", head, p["headline"]]
    out += [f"- {ICONS.get(e['status'], '・')} {e['label']}：{e['detail']}" for e in p["evidence"]]
    out += ["", f"**持有时间**：{plan['horizon']}　**仓位**：{plan.get('position', '')}", f"**怎么买**：{plan['entry']}"]
    if not shared:
        out.append("**预期收益**：" + _expected_line(plan["expected"]))
    out.append("**什么时候卖**：")
    out += [f"- {r}" for r in plan["rules"]]
    if plan.get("stop_note"):
        out.append(f"**关于止损**：{plan['stop_note']}")
    if p.get("risks"):
        out.append("**风险**：" + "；".join(p["risks"]))
    return out


def temperature_text(t: dict) -> list[str]:
    out = ["", f"## 市场温度：{t['value']:.0f} · {t['label']}", t["advice"], "",
           f"- 股票池中位数市净率 {t['all']['pb']:.2f} 倍，在近十年里排 {t['all']['pct']:.0f}%；"
           f"流通市值最大的 300 只中位数 {t['big']['pb']:.2f} 倍，排 {t['big']['pct']:.0f}%。两个取平均就是温度（0 最便宜，100 最贵）",
           f"- 已经在「{t['label']}」这一档待了 {t['stay_days']} 个交易日" + (f"；读数日期 {t['stale']}（今天的没取全）" if t.get("stale") else ""),
           "", f"历史上（{t['span']}）在各档温度买入中证全指，之后的结果：", "",
           "| 温度 | 这样的日子占 | 之后一年 | 赚钱的日子 | 之后两年 | 赚钱的日子 | 之后三年 | 赚钱的日子 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in t["table"]:
        mark = " ← 现在" if r["current"] else ""
        out.append(f"| {r['range']} {r['label']}{mark} | {r['share'] * 100:.0f}% | " + " | ".join(
            f"{_pct(r[k]['mean'], 0)} | {r[k]['win'] * 100:.0f}%" for k in ("y1", "y2", "y3")) + " |")
    return out


def gauge_text(g: dict) -> list[str]:
    f = g["facts"]
    on = [p for p in g["parts"] if p["on"]]
    out = ["", f"### 大盘预估分：{g['score']:+d} · {g['label']}", g["basis"], "",
           f"- 今天：全市场平均 {_pct(f['change'])}，{f['limit_up']} 只涨停、{f['limit_down']} 只跌停，"
           + (f"成交额是近 20 日均值的 {f['amount_ratio']:.2f} 倍" if f.get("amount_ratio") else "成交额对比不出来")
           + f"；明天是{f['next_weekday']}"]
    out.append("- 加减分：" + ("、".join(f"{p['label']} {p['points']:+d}（{p['detail']}）" for p in on) if on else "没有一项触发"))
    if g.get("temp") and g["temp"].get("text"):
        out.append(f"- 市场温度把关：{g['temp']['text']}")
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


def tier_rows_text(rows: list[dict]) -> list[str]:
    cell = lambda x: f"{_pct(x['mean'])} | {x['win'] * 100:.0f}%" if x else "— | —"
    out = ["", "出手分档（按今天的分数和市场温度）：", "",
           "| 档位 | 条件 | 一年约几天 | 近十年：每笔平均 | 赚钱的比例 | 更早的十年：每笔平均 | 赚钱的比例 |", "|---|---|---:|---:|---:|---:|---:|"]
    out += [f"| {r['label']}{' ← 今天' if r['current'] else ''} | {r['rule']} | {round(r['per_year']) if r.get('per_year') is not None else '—'} | {cell(r['new'])} | {cell(r['old'])} |"
            for r in rows]
    return out


def temp_rows_text(title: str, rows: list[dict], head: str = "当时的市场温度") -> list[str]:
    cell = lambda x: f"{_pct(x['mean'])} | {x['win'] * 100:.0f}%" if x else "— | —"
    out = ["", title, "", f"| {head} | 近十年：每笔平均 | 赚钱的比例 | 更早的十年：每笔平均 | 赚钱的比例 |", "|---|---:|---:|---:|---:|"]
    out += [f"| {r['label']}{' ← 现在' if r['current'] else ''} | {cell(r['new'])} | {cell(r['old'])} |" for r in rows]
    return out


def following_text(f: dict) -> list[str]:
    s = f["summary"]
    head = f"还拿着 {s['open']} 只" + (f"，其中 {s['sell']} 只该卖了" if s["sell"] else "")
    if s["done"]:
        head += f"；已经按规则卖出 {s['done']} 只，平均每笔 {_pct(s['done_mean'])}，{s['done_win'] * 100:.0f}% 赚钱"
    out = ["", "### 之前入选的，现在该怎么办", head + "。" + f.get("note", ""), "",
           "| 股票 | 入选日 | 买入价 | 现在 | 赚亏 | 拿了几天 | 状态 | 怎么办 |", "|---|---|---:|---:|---:|---:|---|---|"]
    for x in f["items"]:
        price = x.get("exit") if x["status"] == "done" else x.get("last")
        out.append(f"| {x['name']}（{x['code']}） | {x['picked']} | {x.get('entry', '—')} | {price if price is not None else '—'} | "
                   f"{_pct(x.get('ret'))} | {x.get('days', 0)} | {STATUS.get(x['status'], x['status'])} | {x['action']} |")
    return out


def board_text(b: dict) -> list[str]:
    out = ["", f"## {b['title']} · {b['name']}（{b['horizon']}）", b["idea"]]
    if b.get("stance"):
        out += ["", f"**今天的结论：{b['stance']['label']}**。{b['stance']['text']}"]
    if b.get("gauge"):
        out += gauge_text(b["gauge"])
        if b["gauge"].get("tier_table"):
            out += tier_rows_text(b["gauge"]["tier_table"])
        if b["gauge"].get("temp_table"):
            out += temp_rows_text("分数 ≥3 的日子出手，按当时的市场温度分开看：", b["gauge"]["temp_table"])
    if b.get("timing"):
        out += ["", f"**买入时机**：{b['timing']['text']}"]
        if b["timing"].get("table"):
            out += temp_rows_text("按建仓的时机分开看：", b["timing"]["table"], "建仓的时机")
    if b.get("key") == "dca" and b.get("temp"):
        out += ["", f"**这个月**：{b['temp']['text']}"]
    out += [""] + checkup_text(b["checkup"])
    f = b.get("funnel") or {}
    if b.get("note"):
        out += ["", b["note"]]
    elif not b["picks"]:
        reasons = "；".join(f"{k} {v} 只" for k, v in list((f.get("reasons") or {}).items())[:4])
        out += ["", "今天没有符合条件的。" + (f"没入选的主要原因：{reasons}。" if reasons else "")]
    shared = shared_expected(b["picks"])
    if shared:
        out += ["", "**预期收益（下面这几只都一样）**：" + _expected_line(shared)]
    if b.get("equal"):
        out += ["", "**这几只等额买入**：" + b["equal"]["text"]]
    for i, p in enumerate(b["picks"], 1):
        out += pick_text(i, p, shared=bool(shared))
    if b.get("following"):
        out += following_text(b["following"])
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
    ind = b.get("industry")
    if ind:
        out += ["", "### 行业风向", ind["note"], "",
                "- 长期走强：" + ("、".join(f"{r['name']}（两年半 {_pct(r['long'], 0)}，半年 {_pct(r['short'], 0)}）" for r in ind["strong"]) or "没有"),
                "- 长期走弱（不选）：" + ("、".join(f"{r['name']}（两年半 {_pct(r['long'], 0)}，半年 {_pct(r['short'], 0)}）" for r in ind["weak"]) or "没有"),
                "（括号里是相对全部行业平均的超额）"]
    funds = b.get("funds")
    if funds and funds.get("picks"):
        out += ["", "### 不想选股：直接买指数基金", funds["how"]]
        for e in funds["picks"]:
            out += ["", f"**{e['name']}（{e['code']}）** · {e['index']}", e["why"]]
            out += [f"- {r}" for r in e["rules"]]
    if b.get("ranking"):
        out += ["", "| 指数 | 基金 | 方法 | 这个月 | 投满几年 | 赚钱概率 | 中位收益 | 差的一成 | 一直投到现在的年化 | 只买不卖的年化 |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
        for r in b["ranking"]:
            out.append(f"| {r['index']} | {r['name']} | {r['method']} | {r['advice']} | {r['years']} | {r['win_rate']:.0f}% | {_pct(r['median'], 0, False)} | "
                       f"{_pct(r['p10'], 0, False)} | {_pct(r['irr'], 1, False)} | {_pct(r['irr_plain'], 1, False)} |")
    for q in b.get("faq") or []:
        out += ["", f"**问：{q['q']}**", q["a"]]
    return out


def to_markdown(p: dict) -> str:
    if not p.get("boards") or (p.get("version") or 0) < 3:
        return f"# 每日精选 · {p.get('as_of', '')}\n\n这条记录是旧版本生成的，结构和现在的四个板块不同，不再展示。\n"
    label = f"（{p['as_of_label']}）" if p.get("as_of_label") else ""
    m = p["market"]
    out = [f"# 每日精选 · {p['as_of']}{label}", "", f"> {p['disclaimer']}", ""]
    reg = m["regime"]
    out += ["## 大盘", f"- 走势：**{reg['label']}**（{'；'.join(reg['notes'])}）"]
    t = p.get("temperature")
    if t:
        out.append(f"- 市场温度：**{t['value']:.0f} · {t['label']}**。{t['advice']}")
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
    if t:
        out += temperature_text(t)
    if p.get("commentary"):
        out += ["", "## 今日点评", p["commentary"]]
    for key in p.get("order") or p["boards"]:
        out += board_text(p["boards"][key])
    if p.get("warnings"):
        out += ["", "## 数据提示"] + [f"- {w}" for w in p["warnings"]]
    out += ["", "---", f"生成时间 {p['created_at']}（北京时间），用时 {p.get('elapsed', 0):.0f} 秒"]
    return "\n".join(out) + "\n"
