"""长期（2–3 年）· 低温买入

长期能不能赚钱，主要看买的时候整个市场贵不贵，其次才是买了什么。这是把二十二年的行情翻下来最清楚的一条：
- 市场温度（temperature.py）低于 40 时买入、拿两年：两个十年里 95% 以上的时候是赚的；80 以上买入的，之后两年没有赚过。
  「温度低于 40 买、高于 80 卖」十八年半只换了 9 次仓，中证全指的年化从 +1.5% 变成 +10.1%，最大回撤从 60% 降到 35%。
- 选股上，「挑好公司」的经典办法在 A 股并不灵：高 ROE、低市盈率各自分组看，都没有稳定的超额（高 ROE 那组近十年还是跑输的）。
  站得住的是「回避」：一年波动最大的两成、换手最高的两成、被追捧的、两年半涨得最多的——这「四种热」之后一两年明显跑输；
  每月剔一次，剩下的比全市场平均每年多 5–6 个点。
- 行业是强者恒强：连续几年跑输的行业，之后一到三年继续落后（不是「跌多了就会补涨」）。所以长期走弱的行业不选。

于是这里的做法是：先看温度决定买不买；买的话，从「稳健名单」里挑——公司在赚钱、近一年有现金分红、
近三年年报 ROE 没有低于 8% 的、不属于四种热、所在行业不在长期走弱里——按股息率从高到低排，同一行业大类最多两只。
单只股票的运气成分很大（同样的规则挑 10 只，不同挑法十年下来年化能差出 10 个点），所以至少分散 8 只，
或者干脆买指数基金；主动基金不推荐——过去三年业绩最好的那五分之一，之后三年反而比同类少赚 7 个点。
"""

from __future__ import annotations

from . import evidence as ev
from . import temperature as tp
from .common import bucket_of, diversify, price
from .features import Cross
from .pool import Stock, day_int

KEY, TITLE, NAME = "long", "长期", "低温买入"
HORIZON = "2–3 年"
ROE_MIN = 8.0
MIN_PICKS = 8
BUY_BELOW, SELL_ABOVE = 40, 80

IDEA = ("先看市场贵不贵，再决定买不买。市场温度低于 40 时买入、拿两三年，历史上几乎都是赚的；80 以上买入，之后两年没有赚过。"
        "买什么反而是其次：从赚钱、分红、不热门、行业没在走下坡路的公司里分散着买，或者直接买指数基金。")
HOW = [
    "第一步 看温度：市场温度低于 40 才买；40–60 少买、慢买；60 以上不新买；80 以上分批卖出",
    "第二步 稳健名单：公司在赚钱；近一年有现金分红；近三年年报 ROE 没有低于 8% 的",
    "第三步 去掉四种热：一年波动最大的两成、换手最高的两成、被追捧的（冷热分最低的两成）、两年半涨得最多的两成",
    "第四步 去掉长期走弱的行业：行业两年半的表现排在后三成、最近半年也在后一半（行业是强者恒强，不是跌多了就补涨）",
    "按股息率从高到低排，同一行业大类最多两只；至少买 8 只，或者直接买下面的指数基金",
    "卖出：温度到 80 以上分批卖；每个季度复查一次，不在名单里了（亏损、不分红、变热）就换；不设价格止损",
]
FAQ = [
    {"q": "冷了很久、不景气了很久的行业，是不是更适合长期买？", "a": ev.FACTS["industry"] + ev.FACTS["industry_cheap"]},
    {"q": "为什么不挑 ROE 高的白马股？",
     "a": "分组检验过：近三年 ROE 都在 15% 以上的公司，近十年里拿一年平均比全市场少赚 2.6%，9 年里只有 4 年跑赢；更早的十年也少赚 2%。"
          "好公司人人都知道，价格里早就算进去了。ROE 在这里只用来排除差的（低于 8% 的不要），不用来挑好的。"},
    {"q": "为什么不推荐主动基金？", "a": ev.FACTS["fund"]},
    {"q": "为什么不设止损？",
     "a": "长期持有的股票，价格下跌本身不是卖出的理由——中期板块上检验过，加止损反而把收益砍掉一大半。"
          "真正要卖的是三种情况：市场温度到 80 以上、公司不在稳健名单里了、股票变热了。风险靠「买得便宜」和「分散」来控制。"},
]


def stance_of(temp: dict | None) -> dict:
    """现在该买、该拿、还是该卖。"""
    if not temp:
        return {"key": "unknown", "label": "温度没算出来", "text": "市场温度这次没有算出来，名单只供参考；等能算出温度再决定买不买。"}
    v = temp["value"]
    z = {r["key"]: r for r in temp["table"]}[temp["zone"]]
    after = (f"历史上温度在这一档时买入中证全指，之后两年平均 {ev.pct(z['y2']['mean'], 0)}、{ev.share(z['y2']['win'])} 的日子是赚的；"
             f"三年平均 {ev.pct(z['y3']['mean'], 0)}、{ev.share(z['y3']['win'])}。")
    if v < BUY_BELOW:
        return {"key": "buy", "label": "可以买入", "text": f"市场温度 {v:.0f}（{temp['label']}），低于 {BUY_BELOW}：是长期买入的时候。{after}"}
    if v < 60:
        return {"key": "hold", "label": "少买、慢买", "text": f"市场温度 {v:.0f}（{temp['label']}）：已经持有的继续拿；想新买的，最多先买计划的一半，剩下的等温度回到 {BUY_BELOW} 以下。{after}"}
    if v < SELL_ABOVE:
        return {"key": "pause", "label": "不再新买", "text": f"市场温度 {v:.0f}（{temp['label']}）：不再新买，已经持有的继续拿到 {SELL_ABOVE}。{after}"}
    return {"key": "sell", "label": "分批卖出", "text": f"市场温度 {v:.0f}（{temp['label']}），高于 {SELL_ABOVE}：长期持有的股票和宽基指数基金分批卖出（比如每月卖三分之一）。{after}"}


def tier_key(temp: dict | None) -> str | None:
    if not temp:
        return None
    v = temp["value"]
    return "temp_0_20" if v < 20 else "temp_20_40" if v < 40 else "temp_40_60" if v < 60 else "temp_60_80" if v < 80 else "temp_80_100"


def expected(temp: dict | None) -> dict:
    """按建仓时的市场温度：稳健名单拿两年、三年的历史结果。"""
    k = tier_key(temp) or "temp_0_40"
    rows = {(h, w): ev.LONG[f"steady_{h}"][w].get(k) for h in ("2y", "3y") for w in ("new", "old")}
    label = {"temp_0_20": "20 以下", "temp_20_40": "20–40", "temp_40_60": "40–60", "temp_60_80": "60–80", "temp_80_100": "80 以上", "temp_0_40": "40 以下"}[k]

    def part(h: str, name: str) -> str:
        bits = [f"{w['short']}平均 {ev.pct(x['mean'], 0)}、{ev.share(x['win'])} 的时候赚钱（最差 {ev.pct(x['worst'], 0)}）"
                for w, x in ((ev.NEW, rows[(h, "new")]), (ev.OLD, rows[(h, "old")])) if x]
        return f"拿{name}：" + "；".join(bits) + "。" if bits else ""

    text = (f"历史上在市场温度 {label} 时买入整个稳健名单（几百只，等权）：{part('2y', '两年')}{part('3y', '三年')}"
            "只买其中几只的话，结果会比这个分散得多——这是「名单整体」的统计，不是单只股票的承诺。")
    use = rows[("2y", "new")] or rows[("2y", "old")] or {}
    use3 = rows[("3y", "new")] or rows[("3y", "old")] or {}
    return {"available": bool(use), "kind": "hold", "reliable": True, "mean": use.get("mean"), "win_rate": use.get("win"),
            "mean3": use3.get("mean"), "win3": use3.get("win"), "text": text}


def candidates(stocks: dict[str, Stock], cross: Cross, rows: dict[str, dict], reports: dict[str, dict], roes: dict[str, list[float]],
               heat: dict[str, dict], trends: dict[str, dict]) -> tuple[list[dict], dict, dict]:
    """稳健名单，按股息率从高到低。返回 (名单, 没入选的原因计数, 每一步剩多少只)。"""
    out, reasons = [], {}
    steps = {"profit": 0, "dividend": 0, "roe": 0, "calm": 0, "industry": 0}

    def miss(why):
        reasons[why] = reasons.get(why, 0) + 1

    for code, h in heat.items():
        s = stocks[code]
        row = rows.get(code) or {}
        rep = reports.get(code) or {}
        ind = rep.get("industry") or row.get("industry") or ""
        roe = roes.get(code) or []
        dy = s.dividend_yield
        if not (row.get("pe") and row["pe"] > 0):
            miss("公司在亏损，或者没有取到市盈率")
            continue
        steps["profit"] += 1
        if dy is None:
            miss("没有取到分红记录")
            continue
        if dy <= 0:
            miss("近一年没有现金分红")
            continue
        steps["dividend"] += 1
        if len(roe) < 2:
            miss("年报不足两年，看不出 ROE 稳不稳")
            continue
        if min(roe) < ROE_MIN:
            miss(f"近三年年报的 ROE 有低于 {ROE_MIN:.0f}% 的")
            continue
        steps["roe"] += 1
        if h["kinds"]:
            miss("属于「四种热」：" + h["kinds"][0])
            continue
        steps["calm"] += 1
        trend = trends.get(ind)
        if trend and trend["state"] == "weak":
            miss("所在行业长期走弱")
            continue
        steps["industry"] += 1
        out.append({"code": code, "name": row.get("name") or s.name, "industry": ind, "bucket": bucket_of(ind, s.name),
                    "dy": dy, "div12": s.div12, "div_prev": s.div_prev, "roe": roe, "pe": row["pe"], "pb": row.get("pb"),
                    "heat": h, "trend": trend, "growth": rep.get("yoy"), "report": rep.get("label", ""), "total_mv": row.get("total_mv")})
    out.sort(key=lambda c: -c["dy"])
    return out, dict(sorted(reasons.items(), key=lambda kv: -kv[1])), steps


def build_pick(s: Stock, c: dict, temp: dict | None, stance: dict, as_of: str) -> dict:
    close = s.c[-1]
    h, trend, roe = c["heat"], c["trend"], c["roe"]
    evidence = [
        {"label": "分红", "status": "pass",
         "detail": f"近一年每股现金分红 {c['div12']:.2f} 元，股息率 {c['dy'] * 100:.1f}%" + ("；前一年也分了" if (c.get("div_prev") or 0) > 0 else "；前一年没有分红记录")},
        {"label": "盈利", "status": "pass",
         "detail": f"近 {len(roe)} 年年报 ROE：" + "、".join(f"{x:.1f}%" for x in roe) + f"；市盈率 {c['pe']:.0f} 倍" + (f"，市净率 {c['pb']:.1f} 倍" if c.get("pb") else "")},
        {"label": "不热", "status": "pass",
         "detail": f"冷热分 {h['cold']:.0f}（100 最冷）；一年波动排在全市场 {h['vol_rank']:.0f}%、换手排在 {h['turn_rank']:.0f}%"
                   + (f"；近两年半 {h['long'] * 100:+.0f}%" if h.get("long") is not None else "")},
    ]
    if trend:
        evidence.append({"label": "行业", "status": "pass" if trend["state"] == "strong" else "info",
                         "detail": f"{c['industry']}：近两年半比全部行业平均{'多' if trend['long'] >= 0 else '少'}涨 {abs(trend['long']) * 100:.0f}%，"
                                   f"最近半年{'多' if trend['short'] >= 0 else '少'} {abs(trend['short']) * 100:.0f}%"
                                   + ("——长期走强" if trend["state"] == "strong" else "")})
    else:
        evidence.append({"label": "行业", "status": "info", "detail": f"{c['industry'] or '行业没取到'}：公司太少，行业走势没法单独看"})
    if c.get("growth") is not None:
        evidence.append({"label": "最新财报", "status": "pass" if c["growth"] >= 0 else "warn", "detail": f"{c['report']}净利润同比 {c['growth'] * 100:+.0f}%"})
    entry = {
        "buy": "分两三次买入，每次隔两到四周。短期涨跌没人知道，分批买是为了买在平均价",
        "hold": "现在不贵不便宜：最多先买计划的一半，剩下的等市场温度回到 40 以下再买",
        "pause": "现在偏贵：先不买，放进自选等温度降下来",
        "sell": "现在很贵：不买。已经持有的分批卖出",
        "unknown": "市场温度没算出来：先不急着买",
    }[stance["key"]]
    risks = ["单只股票的运气成分很大：同样的规则挑 10 只，不同挑法十年下来年化能差出 10 个点——一定要分散，至少 8 只，或者直接买指数基金",
             "持有期间出现 20%–30% 的浮亏是正常的（2018 年稳健名单整体跌了 26%），这笔钱要两三年内用不着"]
    if stance["key"] in ("pause", "sell"):
        risks.insert(0, f"现在市场温度 {temp['value']:.0f}，不是长期买入的时候，名单只供已经持有的人对照")
    return {
        "key": s.key, "code": s.code, "name": c["name"], "kind": "stock", "industry": c["industry"],
        "price": price(close), "as_of": as_of, "score": round(c["dy"] * 100, 1), "score_unit": "%",
        "headline": f"股息率 {c['dy'] * 100:.1f}%，近三年 ROE 最低 {min(roe):.0f}%，不在热门里" + ("，行业长期走强" if trend and trend["state"] == "strong" else ""),
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": None, "entry": entry,
            "ref_price": price(close), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "stop_note": "不设价格止损：价格下跌本身不是卖出的理由。跌多了就把下面三条卖出条件重新对一遍，没触发就继续拿。",
            "position": "单只不超过总资金的一成，至少分散 8 只",
            "rules": [
                f"市场温度到 {SELL_ABOVE} 以上：分批卖出（比如每月卖三分之一）——这是最要紧的一条",
                "每个季度财报出来后复查一次（4 月底、8 月底、10 月底）：公司开始亏损、不再分红、或者年报 ROE 跌破 8%，换成名单里别的",
                "变热了：冷热分掉到 20 以下，或者成了全市场波动、换手最高的两成——可以止盈，换成名单里别的（热门股之后一两年是跑输的）",
                "所在行业转成「长期走弱」的，不用马上卖，但不要再加仓",
            ],
            "expected": expected(temp),
        },
    }


def industry_board(trends: dict[str, dict], top: int = 8) -> dict:
    """行业风向：长期走强、长期走弱的各列几个。"""
    rows = [{"name": k, **v} for k, v in trends.items()]
    strong = sorted((r for r in rows if r["state"] == "strong"), key=lambda r: -r["long"])[:top]
    weak = sorted((r for r in rows if r["state"] == "weak"), key=lambda r: r["long"])[:top]
    f = ev.INDUSTRY["filter"]
    note = (ev.FACTS["industry"] +
            f"落到选股上：稳健名单里行业长期走弱的那些，拿两年平均 {ev.pct(f['new']['long|稳健 ∩ 行业长期走弱|两年']['ret'], 0)}（{ev.NEW['short']}）/ "
            f"{ev.pct(f['old']['long|稳健 ∩ 行业长期走弱|两年']['ret'], 0)}（{ev.OLD['short']}）；行业长期走强的是 "
            f"{ev.pct(f['new']['long|稳健 ∩ 行业长期走强|两年']['ret'], 0)} / {ev.pct(f['old']['long|稳健 ∩ 行业长期走强|两年']['ret'], 0)}。"
            "这条只对长期有用——中期、短期按行业分开看没有差别。")
    return {"strong": strong, "weak": weak, "count": len(rows), "weak_count": sum(1 for r in rows if r["state"] == "weak"),
            "strong_count": sum(1 for r in rows if r["state"] == "strong"), "note": note}


def lump_stats(bars: list, months: tuple[int, ...] = (24, 36)) -> dict | None:
    """这只基金：市场温度低于 40 的日子一次买入，拿满两年、三年的结果；以及任意一天买入的结果（对照）。"""
    closes = [b.adj_close for b in bars if b.adj_close > 0]
    days = [day_int(b.date) for b in bars if b.adj_close > 0]
    if len(closes) < 5 * 245:
        return None
    temps = tp.temps_on(days)
    out = {}
    for m in months:
        h = m * 245 // 12
        cold = sorted(closes[i + h] / closes[i] - 1 for i in range(0, len(closes) - h, 5) if temps[i] is not None and temps[i] < BUY_BELOW)
        any_ = sorted(closes[i + h] / closes[i] - 1 for i in range(0, len(closes) - h, 5) if temps[i] is not None)
        hot = sorted(closes[i + h] / closes[i] - 1 for i in range(0, len(closes) - h, 5) if temps[i] is not None and temps[i] >= 60)
        if len(cold) < 20 or len(any_) < 40:
            return None
        pack = lambda xs: {"n": len(xs), "win": sum(1 for x in xs if x > 0) / len(xs), "median": xs[len(xs) // 2], "worst": xs[0]} if xs else None
        out[f"y{m // 12}"] = {"cold": pack(cold), "any": pack(any_), "hot": pack(hot)}
    return out


INDEX_WANTED = ("沪深300", "中证500", "红利低波", "中证红利", "上证50", "中证1000")


def index_funds(cands: list[dict], nav_of, temp: dict | None, n: int = 3) -> dict:
    """不想选股的：直接买指数基金。挑宽基和红利各一两只，给出「温度低于 40 时买入」在它自己历史上的结果。"""
    picks = []
    for want in INDEX_WANTED:
        row = next((c for c in cands if c.get("index") == want), None)
        if not row or len(picks) >= n or (want == "中证红利" and any(p["index"] == "红利低波" for p in picks)):
            continue
        try:
            st = lump_stats(nav_of(row))
        except Exception:
            st = None
        if not st:
            continue
        y2, y3 = st["y2"], st["y3"]
        picks.append({
            "key": f"OF:{row['code']}", "code": row["code"], "name": row["name"], "index": want, "group": row.get("group", ""),
            "nav": row.get("nav"), "stats": st,
            "why": (f"它自己的历史：市场温度低于 {BUY_BELOW} 的日子买入、拿两年，{y2['cold']['win'] * 100:.0f}% 赚钱，中位 {y2['cold']['median'] * 100:+.0f}%"
                    f"（最差 {y2['cold']['worst'] * 100:+.0f}%）；拿三年，{y3['cold']['win'] * 100:.0f}% 赚钱，中位 {y3['cold']['median'] * 100:+.0f}%。"
                    + (f"温度 60 以上买入、拿两年的只有 {y2['hot']['win'] * 100:.0f}% 赚钱，中位 {y2['hot']['median'] * 100:+.0f}%。" if y2.get("hot") else "")),
            "rules": (["温度低于 40 时分两三次买入", "红利类不用按温度卖，可以一直拿着收分红"] if row.get("group") == "红利"
                      else ["温度低于 40 时分两三次买入", f"温度到 {SELL_ABOVE} 以上分批卖出，等回到 40 以下再买回来"]),
        })
    return {"picks": picks,
            "how": "不想选股、或者钱不够分散买 8 只：直接买指数基金，同样看温度。宽基（沪深300、中证500）跟着温度买卖；红利类波动小，可以一直拿。"
                   "想每月投一点而不是一次买入的，看「定投」板块。",
            "note": ev.FACTS["fund"]}


def checkup() -> dict:
    L = ev.LONG
    z = {r["label"]: r for r in ev.TEMP["zones"]}
    s2n, s2o = L["steady_2y"]["new"], L["steady_2y"]["old"]
    cold_n, cold_o = s2n["temp_0_40"], s2o["temp_0_40"]
    mid_n, mid_o = s2n["temp_40_80"], s2o["temp_40_80"]
    hot_o = s2o.get("temp_80_100")
    return {
        "level": "ok",
        "verdict": (f"长期的结果主要取决于买入时的市场温度。稳健名单在温度 40 以下买入、拿两年：{ev.NEW['short']}平均 {ev.pct(cold_n['mean'], 0)}、{ev.share(cold_n['win'])} 的时候赚钱；"
                    f"{ev.OLD['short']}平均 {ev.pct(cold_o['mean'], 0)}、{ev.share(cold_o['win'])}。温度 40–80 之间买入的只有 {ev.pct(mid_n['mean'], 0)}、{ev.share(mid_n['win'])} / "
                    f"{ev.pct(mid_o['mean'], 0)}、{ev.share(mid_o['win'])}；80 以上买入的（{ev.OLD['short']}）平均 {ev.pct(hot_o['mean'], 0)}，没有一次赚钱。"),
        "more": [
            ev.temp_strategy_text(),
            f"选股这一步的作用小得多，而且只有近十年明显：稳健名单每月更新、连续持有，年化 {ev.pct(L['steady_cagr']['new'])}（{ev.NEW['short']}，全池 {ev.pct(L['all_cagr']['new'])}）/ "
            f"{ev.pct(L['steady_cagr']['old'])}（{ev.OLD['short']}，全池 {ev.pct(L['all_cagr']['old'])}）；被剔掉的「四种热」是 {ev.pct(L['hot_cagr']['new'])} / {ev.pct(L['hot_cagr']['old'])}。"
            "一次买入不动、拿满两年的话，稳健名单近十年比全池多 5.6 个点，更早的十年少 2.4 个点（那十年小盘股疯涨）。",
            "单只股票分散不掉的运气：从名单里挑 10 只，按股息率挑近十年年化 +10.2%、更早的十年 +24.8%（全池 +4.3% / +23.6%）；"
            "换成按低波动、按综合分去挑，结果能差出 5–10 个点。所以这里按股息率排、至少买 8 只。",
            ev.FACTS["industry"],
            f"最坏的情况：温度 40 以下买入稳健名单、拿两年，最差的一次是 {ev.pct(cold_n['worst'], 0)}（{ev.NEW['short']}）/ {ev.pct(cold_o['worst'], 0)}（{ev.OLD['short']}）；"
            f"不看温度的话，拿一年最差 {ev.pct(L['steady_1y']['new']['worst'], 0)} / {ev.pct(L['steady_1y']['old']['worst'], 0)}。",
            "这段历史里完整的冷热循环只有四五轮（低点在 2008、2012–2014、2018–2019、2024 年，高点在 2010、2015、2021、2026 年），"
            "「低温买高温卖」的次数不多，不能当成定律；但每一轮方向一致，背后的道理（便宜的时候买）也说得通。",
            "口径：每 21 个交易日建一次仓，名单里的股票等权，第二天开盘买入，扣 0.2%；财报、分红都只用当时已经公告的；包含后来退市的股票。",
        ],
        "by_year": {"new": {"steady": L["steady_by_year"]["new"], "all": L["all_by_year"]["new"], "hot": L["hot_by_year"]["new"]},
                    "old": {"steady": L["steady_by_year"]["old"], "all": L["all_by_year"]["old"], "hot": L["hot_by_year"]["old"]}},
        "strategy": {"hold": ev.TEMP["strategy"]["index"]["hold"], "rule": ev.TEMP["strategy"]["index"]["rule"]},
    }


def select(stocks: dict[str, Stock], cross: Cross, rows: dict[str, dict], reports: dict[str, dict], roes: dict[str, list[float]],
           heat: dict[str, dict], trends: dict[str, dict], temp: dict | None, as_of: str, n: int) -> dict:
    stance = stance_of(temp)
    cands, reasons, steps = candidates(stocks, cross, rows, reports, roes, heat, trends)
    picked = diversify(cands, max(n, MIN_PICKS))
    board = {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "stance": stance, "temp": temp,
        "picks": [build_pick(stocks[c["code"]], c, temp, stance, as_of) for c in picked],
        "industry": industry_board(trends) if trends else None,
        "funnel": {"pool": len(heat), "candidates": len(cands), "picked": len(picked), "reasons": reasons, "steps": steps},
        "checkup": checkup(), "faq": FAQ, "warnings": [],
    }
    if not roes:
        board["warnings"].append("近几年的年报摘要没取到，长期板块这次没法检查 ROE，名单是空的")
    if not trends:
        board["warnings"].append("行业走势这次没有算出来（行业分类没取到），长期板块没有按行业过滤")
    return board
