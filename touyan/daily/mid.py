"""中期（1–3 个月）· 冷门蓄势

对手盘：追热点的人。A 股里被追捧的股票——换手突然放大、盘中一路被买上去、越涨越放量、天天收在最高位——
之后是跑输的：在 2005–2026 的二十二年里，「最热的一成」没有一年跑赢过同期随便买，60 天平均少赚 2%–3%。
反过来，没人理的股票是偏便宜的。这个板块就买「最冷的一成」，并且要求：
- 不是大盘股（这个规律在市值最大的三成里基本不成立，机构定价更充分）；
- 公司在赚钱，而且最新一期财报的净利润同比增长超过 10%（冷是因为没人看，不是因为业绩在变坏）。

怎么量「冷热」见 features.py。老实话也要说清楚：
- 入选的股票大多在阴跌、缩量，看上去并不讨喜；买了之后常常还要再磨一阵。
- 单只的胜率只有五成出头，靠的是赚的时候（平均 +17%）比亏的时候（平均 −12%）多。所以必须分散，至少 5 只。
- 价格止损在这个方法上是有害的：加 12% 止损，平均收益从 +2.4% 掉到 +0.3%——冷门股常常先跌一段再涨，止损正好卖在低点。
  真正有效的卖出规则只有一条：涨停了，第二天开盘卖（涨停股次日平均高开 2%，之后往回走）。
- 这个方法在 2017 年以后才明显有效（更早的十年只是略好于随便买，加上利润增长这一条后才显著）。
"""

from __future__ import annotations

from math import exp

from . import evidence as ev
from . import gauge as gg
from . import sim
from .common import bucket_of, diversify, pct_rank, price
from .features import Cross
from .pool import Stock, day_int, day_text

KEY, TITLE, NAME = "mid", "中期", "冷门蓄势"
HORIZON = "1–3 个月"
HOLD, MAX_GAP = 60, 0.03
COLD_MIN = 90              # 冷热分：最冷的一成
SIZE_MAX = 70              # 流通市值不在最大的三成里
MIN_GROWTH = 0.10
STEP = 10                  # 回看时每隔 10 个交易日取一天

IDEA = ("买没人追的股票，躲开被追捧的。被追捧的股票（放量、盘中拉升、越涨越放量、天天收在高位）之后是跑输的——"
        "二十二年里最热的一成没有一年跑赢过随便买；最冷的一成、公司又在赚钱并且利润在增长的，之后一到三个月平均跑赢。")
HOW = [
    "冷热分在最冷的一成：近 60 天盘中没被拉升、近 20 天成交没放大、不是越涨越放量、不是天天收在高位（四项在全市场里排名次）",
    "流通市值不在全市场最大的三成里（这个规律在大盘股里基本不成立）",
    "公司在赚钱，最新一期财报的净利润同比增长超过 10%",
    "今天没有涨停或跌停；同一个行业大类最多选两只",
    "第二天开盘买（高开 3% 以上放弃），最多拿 60 个交易日；涨停了第二天开盘卖；不设价格止损，靠分散控制风险",
]
STOP_NOTE = ("不设价格止损。检验过：加 12% 的止损，平均收益从 +2.4% 掉到 +0.3%；放宽到 20% 也要少赚一个点——"
             "冷门股常常先再跌一段才涨，止损正好卖在低点。风险靠分散来控制：单只不超过一成仓位，至少买 5 只。")


def size_ranks(stocks: dict[str, Stock], cross: Cross) -> list[float]:
    """流通市值在全池里的名次（0–100，越大市值越大）。"""
    return pct_rank([stocks[c].float_mv for c in cross.codes])


def candidates(stocks: dict[str, Stock], cross: Cross, rows: dict[str, dict], reports: dict[str, dict]) -> tuple[list[dict], dict]:
    """今天符合条件的，从最冷的排起。reports 为空（财报摘要没取到）时不检查利润增长。"""
    size = size_ranks(stocks, cross) if len(cross) else []
    out, reasons = [], {}

    def miss(why):
        reasons[why] = reasons.get(why, 0) + 1

    for i, code in enumerate(cross.codes):
        s, t = stocks[code], cross.t[i]
        if t != s.n - 1 or cross.cold[i] < COLD_MIN:
            continue
        row = rows.get(code) or {}
        rep = reports.get(code) or {}
        growth = rep.get("yoy")
        ind = rep.get("industry") or row.get("industry") or ""
        if size[i] >= SIZE_MAX:
            miss("市值在全市场最大的三成里（这个方法在大盘股里不成立）")
        elif not (row.get("pe") and row["pe"] > 0):
            miss("公司在亏损，或者没有取到市盈率")
        elif reports and growth is None:
            miss("没有取到最新财报的利润同比")
        elif reports and growth <= MIN_GROWTH:
            miss("最新财报的净利润同比没有超过 10%")
        elif s.limit_up(t) or s.limit_down(t):
            miss("今天涨停或跌停")
        else:
            out.append({"code": code, "name": row.get("name") or s.name, "industry": ind, "bucket": bucket_of(ind, s.name),
                        "cold": cross.cold[i], "size": size[i], "growth": growth, "report": rep.get("label", ""),
                        "notice": rep.get("notice", ""), "pe": row.get("pe"), "float_mv": s.float_mv,
                        "id60": cross.col["id60"][i], "vabn": cross.col["vabn"][i], "pvv": cross.col["pvv"][i],
                        "clv": cross.col["clv"][i], "r20": cross.col["r20"][i], "hi": cross.col["hi"][i],
                        "r60": s.c[t] / s.c[t - 60] - 1})
    out.sort(key=lambda c: -c["cold"])
    return out, reasons


def expected(score: int) -> dict:
    new, old = ev.MID["all"]["new"], ev.MID["all"]["old"]
    tier = "ge2" if score >= gg.LIGHT else "0to1" if score >= 0 else "le-1"
    by = ev.MID["by_score"][tier]
    tier_text = {"ge2": "≥2", "0to1": "0–1", "le-1": "≤−1"}[tier]
    text = (f"历史上按这个规则买入（{ev.NEW['short']} {new['n']} 笔，平均拿 {new['days']:.0f} 个交易日）：{new['win'] * 100:.0f}% 赚钱，"
            f"平均每笔 {ev.pct(new['mean'])}，中位 {ev.pct(new['median'])}；赚的平均 {ev.pct(new['avg_win'], 0)}，亏的平均 {ev.pct(new['avg_loss'], 0)}；"
            f"同期随便买是 {ev.pct(new['base'])}。{ev.OLD['short']}：{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}。"
            f"今天的大盘预估分是 {score}，历史上在分数 {tier_text} 的日子买入，平均 {ev.pct(by['new'][0])}（{ev.NEW['short']}）/ "
            f"{ev.pct(by['old'][0])}（{ev.OLD['short']}）。亏钱的年份：{new['bad_years']}——大盘不好的年份它也会亏，只是亏得比随便买少。")
    return {"available": True, "kind": "trade", "reliable": True, "n": new["n"], "win_rate": new["win"], "median": new["median"],
            "mean": new["mean"], "avg_days": new["days"], "text": text}


def cold_story(c: dict) -> list[dict]:
    """冷热分的四项，说成人话。"""
    return [
        {"label": "盘中", "status": "pass",
         "detail": f"近 60 天「开盘到收盘」累计 {(exp(c['id60']) - 1) * 100:+.0f}%：" + ("盘中没人往上买" if c["id60"] < 0 else "盘中涨得不多")},
        {"label": "成交", "status": "pass",
         "detail": f"近 20 天的成交是一年平均的 {c['vabn']:.2f} 倍：" + ("明显缩量" if c["vabn"] < 0.7 else "没有放量")},
        {"label": "量价", "status": "pass" if c["pvv"] < 0.2 else "info",
         "detail": ("价格低的时候成交反而多（有人在低位接）" if c["pvv"] < -0.2 else "没有越涨越放量") + f"，相关系数 {c['pvv']:+.2f}"},
        {"label": "收盘位置", "status": "pass" if c["clv"] < 0.5 else "info",
         "detail": f"近 20 天平均收在当天最低到最高之间 {c['clv'] * 100:.0f}% 的位置：" + ("没有人尾盘抢筹" if c["clv"] < 0.5 else "不算高")},
    ]


def build_pick(s: Stock, c: dict, score: int, as_of: str) -> dict:
    close = s.c[-1]
    mv = f"流通市值约 {c['float_mv'] / 1e8:.0f} 亿" if c.get("float_mv") else "流通市值没取到"
    growth = c.get("growth")
    evidence = [{"label": "冷热分", "status": "pass", "detail": f"{c['cold']:.0f}（100 最冷）：全市场最没人追的一成"}] + cold_story(c) + [
        {"label": "市值", "status": "pass", "detail": f"{mv}，比全市场 {c['size']:.0f}% 的股票大（不在最大的三成里）"},
        {"label": "业绩", "status": "pass" if growth is not None else "warn",
         "detail": (f"{c['report']}净利润同比 {growth * 100:+.0f}%" + (f"（{c['notice']} 公告）" if c.get("notice") else "") + f"，市盈率 {c['pe']:.0f} 倍")
         if growth is not None else f"财报摘要没取到，没法确认利润在增长；市盈率 {c['pe']:.0f} 倍"},
        {"label": "近 60 天", "status": "info", "detail": f"{c['r60'] * 100:+.1f}%，离一年高点 {c['hi'] * 100:+.0f}%"},
    ]
    risks = ["入选的股票多半在阴跌、缩量，买了之后可能还要再磨一阵，甚至先再跌一段",
             "单只的胜率只有五成出头——一定要分散买，不要只买一只",
             "被 ST、财报由盈转亏、公告立案调查这类事发生时，不用等，直接卖"]
    if score < 0:
        risks.insert(0, f"今天大盘预估分是 {score}（偏弱）：不用急着买，可以等分数回到 2 以上的日子再建仓")
    return {
        "key": s.key, "code": s.code, "name": c["name"], "kind": "stock", "industry": c["industry"],
        "price": price(close), "as_of": as_of, "score": round(c["cold"], 1),
        "headline": "全市场最没人追的一成，公司在赚钱" + (f"、利润同比 {growth * 100:+.0f}%" if growth is not None else "") + "；等它被重新注意到",
        "evidence": evidence, "risks": risks,
        "plan": {
            "horizon": HORIZON, "hold_max": HOLD,
            "entry": f"明天开盘买入；开盘价高于 {price(close * (1 + MAX_GAP))}（比今天收盘高 3%）就放弃。也可以分两三次、隔几天买",
            "ref_price": price(close), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "stop_note": STOP_NOTE,
            "position": "单只不超过总资金的一成，至少分散 5 只",
            "rules": [
                "涨停：哪天收盘封在涨停，第二天开盘卖（涨停股次日平均高开 2%，之后往回走——这是唯一检验有效的提前卖出规则）",
                f"到期：买入后第 {HOLD} 个交易日（约三个月）收盘卖出；想少操心也可以在第 20 个交易日看一次",
                "业绩：新一期财报的净利润同比转为下降，卖出",
                "不设价格止损（原因见下面「关于止损」）",
            ],
            "expected": expected(score),
        },
    }


def avoid_list(stocks: dict[str, Stock], cross: Cross, rows: dict[str, dict], industry: dict[str, str], n: int = 12) -> dict:
    """今天最热的：别追。"""
    order = sorted((i for i in range(len(cross)) if cross.t[i] == stocks[cross.codes[i]].n - 1), key=lambda i: cross.cold[i])[:n]
    names = []
    for i in order:
        code = cross.codes[i]
        s = stocks[code]
        names.append({"key": s.key, "code": code, "name": (rows.get(code) or {}).get("name") or s.name,
                      "industry": industry.get(code, ""), "cold": round(cross.cold[i], 1), "r20": cross.col["r20"][i],
                      "vabn": cross.col["vabn"][i], "id60": exp(cross.col["id60"][i]) - 1})
    new, old = ev.MID["hot10_60"]["new"], ev.MID["hot10_60"]["old"]
    return {"names": names,
            "note": (f"冷热分最低（最热）的一成，之后 60 个交易日平均比同期随便买少赚 {-new[0] * 100:.1f}%（{ev.NEW['short']}）/ "
                     f"{-old[0] * 100:.1f}%（{ev.OLD['short']}），22 年里没有一年跑赢过。手里有这类股票不必马上卖，但不要追着买。")}


def recent_check(stocks: dict[str, Stock], crosses: dict[int, Cross], calendar: list[int], n: int) -> dict:
    """最近一年多：每隔 10 个交易日按冷热分选一次（只看冷热分和市值——当时的财报这里没有），拿满 60 天的结果。"""
    trades, base, rows = [], [], []
    for day in sample_days(calendar):
        cross = crosses.get(day)
        if not cross or not len(cross):
            continue
        size = size_ranks(stocks, cross)
        cands = sorted(((cross.cold[i], cross.codes[i], cross.t[i]) for i in range(len(cross))
                        if cross.cold[i] >= COLD_MIN and size[i] < SIZE_MAX), reverse=True)
        got = []
        for _, code, t in cands[:n * 3]:
            res = sim.trade(stocks[code], t, HOLD, MAX_GAP, sell_on_limit_up=True)
            if res:
                got.append(res[0])
            if len(got) == n:
                break
        market = [r for r in (sim.hold_return(stocks[c], t, HOLD) for c, t in zip(cross.codes, cross.t)) if r is not None]
        if got and market:
            trades += got
            m = sum(market) / len(market)
            base.append(m)
            rows.append({"date": day_text(day), "picks": sum(got) / len(got), "market": m})
    out = sim.stats(trades)
    out.update({"days": len(rows), "baseline": sum(base) / len(base) if base else None, "rows": rows[::-1]})
    return out


def sample_days(calendar: list[int]) -> list[int]:
    """回看用的日子：往前 60 天之外（要等结果走完）、310 天之内，每隔 10 个交易日一天。"""
    last = len(calendar) - 1
    return [calendar[j] for j in range(last - HOLD - 2, max(0, last - 310), -STEP)][::-1]


def checkup(recent: dict) -> dict:
    new, old = ev.MID["all"]["new"], ev.MID["all"]["old"]
    cn, co = ev.MID["cand_60"]["new"], ev.MID["cand_60"]["old"]
    hn, ho = ev.MID["hot10_60"]["new"], ev.MID["hot10_60"]["old"]
    by = ev.MID["by_score"]
    return {
        "level": "ok", "n": new["n"], "win_rate": new["win"], "mean": new["mean"], "median": new["median"],
        "baseline": new["base"], "avg_days": new["days"], "span": "十年", "stocks": ev.NEW["pool"],
        "verdict": (f"通过了检验，但优势是「比随便买好」，不是「稳赚」。{ev.NEW['label']}：每天按规则选 5 只、最多拿 60 个交易日，"
                    f"共 {new['n']} 笔，{new['win'] * 100:.0f}% 赚钱，平均每笔 {ev.pct(new['mean'])}，同期随便买是 {ev.pct(new['base'])}；"
                    f"{ev.OLD['label']}：{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}，随便买是 {ev.pct(old['base'])}。"),
        "more": [
            f"全部符合条件的股票（不只是选出来的 5 只）：之后 60 天比随便买多赚 {ev.pct(cn[0])}（近十年，{cn[1]}/{cn[2]} 年跑赢）/ "
            f"{ev.pct(co[0])}（更早的十年，{co[1]}/{co[2]} 年跑赢）。",
            f"反面：最热的一成之后 60 天比随便买少赚 {-hn[0] * 100:.1f}% / {-ho[0] * 100:.1f}%，22 年里 {hn[1] + ho[1]} 年跑赢。",
            f"买入时机：大盘预估分 ≥2 的日子买入，平均 {ev.pct(by['ge2']['new'][0])}（近十年）/ {ev.pct(by['ge2']['old'][0])}（更早的十年）；"
            f"分数 ≤−1 的日子买入，平均 {ev.pct(by['le-1']['new'][0])} / {ev.pct(by['le-1']['old'][0])}。",
            f"单只胜率只有 {new['win'] * 100:.0f}%：赚的平均 {ev.pct(new['avg_win'], 0)}，亏的平均 {ev.pct(new['avg_loss'], 0)}，最差的 5% 亏 {-new['p5'] * 100:.0f}% 以上。",
            f"亏钱的年份：{new['bad_years']}（近十年）、{old['bad_years']}（更早的十年）——都是大盘不好的年份。",
            STOP_NOTE,
            "口径：信号收盘后才知道，第二天开盘买；开盘就涨停的买不进；封死跌停卖不掉顺延；每笔扣 0.2%。",
        ],
        "recent": recent,
    }


def timing(g: dict) -> dict:
    score = g["score"]
    by = ev.MID["by_score"]
    if score >= gg.LIGHT:
        text = (f"今天的大盘预估分是 {score}，是建仓的好日子：历史上分数 ≥2 的日子买入，之后平均 {ev.pct(by['ge2']['new'][0])}（近十年）/ "
                f"{ev.pct(by['ge2']['old'][0])}（更早的十年），明显高于平时。")
        level = "go"
    elif score >= 0:
        text = (f"今天的大盘预估分是 {score}，不好不坏。可以先买一部分，剩下的等分数到 2 以上的日子再买。")
        level = "wait"
    else:
        text = (f"今天的大盘预估分是 {score}（偏弱）。不用急：历史上分数 ≤−1 的日子买入，之后平均 {ev.pct(by['le-1']['new'][0])}（近十年），"
                f"比分数 ≥2 的日子买入少赚近一半。名单可以先看着，等分数回到 2 以上再动手。")
        level = "avoid"
    return {"level": level, "score": score, "text": text}


def select(stocks: dict[str, Stock], crosses: dict[int, Cross], g: dict, rows: dict[str, dict], reports: dict[str, dict],
           calendar: list[int], as_of: str, n: int) -> dict:
    cross = crosses.get(day_int(as_of)) or Cross(day_int(as_of))
    cands, reasons = candidates(stocks, cross, rows, reports)
    picked = diversify(cands, n)
    industry = {c: r.get("industry", "") for c, r in reports.items()}
    board = {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "timing": timing(g),
        "picks": [build_pick(stocks[c["code"]], c, g["score"], as_of) for c in picked],
        "avoid": avoid_list(stocks, cross, rows, industry),
        "funnel": {"pool": len(stocks), "candidates": len(cands), "picked": len(picked), "reasons": reasons,
                   "cold": sum(1 for x in cross.cold if x >= COLD_MIN)},
        "checkup": checkup(recent_check(stocks, crosses, calendar, n)), "warnings": [],
    }
    if not reports:
        board["warnings"].append("全市场财报摘要没取到，中期板块这次没有检查「利润同比增长超过 10%」这一条，入选的股票请自己核对最新财报")
    return board
