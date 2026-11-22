"""中期（1–6 个月）· 冷门蓄势

对手盘：追热点的人。A 股里被追捧的股票——换手突然放大、盘中一路被买上去、越涨越放量、天天收在最高位——
之后是跑输的：在 2005–2026 的二十二年里，「最热的一成」没有一年跑赢过同期随便买，60 天平均少赚 2%–3%。
反过来，没人理的股票是偏便宜的。这个板块就买「最冷的一成」，并且要求：
- 不是大盘股（这个规律在市值最大的三成里基本不成立，机构定价更充分）；
- 公司在赚钱，而且最新一期财报的净利润同比增长超过 10%（冷是因为没人看，不是因为业绩在变坏）。

怎么量「冷热」见 features.py。卖出规则是按两个十年的行情比出来的（research/exp50–52）：
- 变热了再卖：冷热分掉到 30 以下（开始有人追了）就卖，没变热就一直拿，最多拿 120 个交易日（约半年）。
  比「拿满 60 天就卖」每笔多赚一截，胜率从五成出头提到六成——冷门股被重新注意到需要时间，过早卖掉等于白等。
- 收盘涨停的，第二天开盘卖（涨停股次日平均高开 2%，之后往回走）。
- 不设价格止损：加 12% 止损，平均收益掉一大半——冷门股常常先再跌一段才涨，止损正好卖在低点。风险靠分散控制。

买入时机看市场温度（temperature.py）：温度 40 以下时买入的，两个十年里平均都在 +7% 以上；80 以上买入的是亏的。
老实话也要说清楚：入选的股票大多在阴跌、缩量，看上去并不讨喜；单只仍有四成会亏，必须分散，至少 5 只。
"""

from __future__ import annotations

from math import exp

from . import evidence as ev
from . import gauge as gg
from .common import bucket_of, diversify, pct_rank, price
from .features import Cross
from .pool import Stock, day_int, day_text
from .sim import COST

KEY, TITLE, NAME = "mid", "中期", "冷门蓄势"
HORIZON = "1–6 个月"
HOLD, MAX_GAP = 120, 0.03
COLD_MIN = 90              # 冷热分：最冷的一成
EXIT_COLD = 30             # 冷热分掉到这以下算「变热了」，卖
SIZE_MAX = 70              # 流通市值不在最大的三成里
MIN_GROWTH = 0.10
STEP = 10                  # 回看时每隔 10 个交易日取一天
CHECK_EVERY = 5            # 回看时每 5 个交易日检查一次冷热分（每天都算太慢，和「每周看一次」也更接近）

IDEA = ("买没人追的股票，等它被重新注意到。被追捧的股票（放量、盘中拉升、越涨越放量、天天收在高位）之后是跑输的——"
        "二十二年里最热的一成没有一年跑赢过随便买；最冷的一成、公司又在赚钱并且利润在增长的，之后几个月平均跑赢。"
        "买了就拿着，直到它变热（有人开始追了）再卖。")
HOW = [
    "冷热分在最冷的一成：近 60 天盘中没被拉升、近 20 天成交没放大、不是越涨越放量、不是天天收在高位（四项在全市场里排名次）",
    "流通市值不在全市场最大的三成里（这个规律在大盘股里基本不成立）",
    "公司在赚钱，最新一期财报的净利润同比增长超过 10%",
    "今天没有涨停或跌停；同一个行业大类最多选两只",
    "第二天开盘买（高开 3% 以上放弃）；冷热分掉到 30 以下（变热了）就卖，收盘涨停的第二天开盘卖，最多拿 120 个交易日；不设价格止损",
    "买入时机看市场温度：40 以下最好，80 以上不买",
]
_s12 = ev.MID["stop12"]
STOP_NOTE = (f"不设价格止损。检验过：加 12% 的止损，平均每笔从 {ev.pct(ev.MID['all']['new']['mean'])} 掉到 {ev.pct(_s12['new']['mean'])}（{ev.NEW['short']}）、"
             f"从 {ev.pct(ev.MID['all']['old']['mean'])} 掉到 {ev.pct(_s12['old']['mean'])}（{ev.OLD['short']}）——冷门股常常先再跌一段才涨，止损正好卖在低点。"
             "风险靠分散来控制：单只不超过一成仓位，至少买 5 只。")


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


def temp_tier(temp: dict | None) -> str | None:
    if not temp:
        return None
    v = temp["value"]
    return "lt20" if v < 20 else "20to40" if v < 40 else "40to60" if v < 60 else "60to80" if v < 80 else "ge80"


def expected(temp: dict | None) -> dict:
    new, old = ev.MID["all"]["new"], ev.MID["all"]["old"]
    text = (f"历史上按这个规则买卖（{ev.NEW['short']} {new['n']} 笔，平均拿 {new['days']:.0f} 个交易日）：{new['win'] * 100:.0f}% 赚钱，"
            f"平均每笔 {ev.pct(new['mean'])}，中位 {ev.pct(new['median'])}；赚的平均 {ev.pct(new['avg_win'], 0)}，亏的平均 {ev.pct(new['avg_loss'], 0)}；"
            f"同期随便买是 {ev.pct(new['base'])}。{ev.OLD['short']}：{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}。")
    use = new
    tier = temp_tier(temp)
    if tier:
        tn, to = ev.MID["by_temp"][tier]["new"], ev.MID["by_temp"][tier]["old"]
        label = dict(ev.MID_TEMP_ROWS)[tier]
        text += (f"今天的市场温度是 {temp['value']:.0f}：历史上在温度 {label} 的时候买入，"
                 + "；".join(f"{w['short']}平均 {ev.pct(x['mean'])}、{x['win'] * 100:.0f}% 赚钱" for w, x in ((ev.NEW, tn), (ev.OLD, to)) if x) + "。")
        use = tn or to or new
    text += f"亏钱的年份：{ev.years(new['bad_years'])}——大盘不好的年份它也会亏，只是亏得比随便买少。"
    return {"available": True, "kind": "trade", "reliable": True, "n": use["n"], "win_rate": use["win"], "median": use["median"],
            "mean": use["mean"], "avg_days": use["days"], "text": text}


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


def build_pick(s: Stock, c: dict, temp: dict | None, as_of: str) -> dict:
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
             "单只仍有四成会亏——一定要分散买，不要只买一只",
             "被 ST、财报由盈转亏、公告立案调查这类事发生时，不用等，直接卖"]
    if temp and temp["value"] >= 80:
        risks.insert(0, f"市场温度 {temp['value']:.0f}（很热）：历史上这种时候买入中期股票平均是亏的，名单只供观察，不建议现在买")
    return {
        "key": s.key, "code": s.code, "name": c["name"], "kind": "stock", "industry": c["industry"],
        "price": price(close), "as_of": as_of, "score": round(c["cold"], 1),
        "headline": "全市场最没人追的一成，公司在赚钱" + (f"、利润同比 {growth * 100:+.0f}%" if growth is not None else "") + "；拿到它变热为止",
        "evidence": evidence, "risks": risks,
        "spark": {"closes": [round(x, 2) for x in s.c[-120:]], "refs": []},
        "meters": [{"label": "冷热分", "value": c["cold"], "text": f"{c['cold']:.0f}（掉到 {EXIT_COLD} 以下就卖）"},
                   {"label": "成交（比一年平均）", "value": min(100.0, c["vabn"] * 50), "text": f"{c['vabn']:.2f} 倍"}],
        "plan": {
            "horizon": HORIZON, "hold_max": HOLD,
            "entry": f"明天开盘买入；开盘价高于 {price(close * (1 + MAX_GAP))}（比今天收盘高 3%）就放弃。也可以分两三次、隔几天买",
            "ref_price": price(close), "target_price": None, "target_pct": None, "stop_price": None, "stop_pct": None,
            "stop_note": STOP_NOTE,
            "position": "单只不超过总资金的一成，至少分散 5 只",
            "rules": [
                f"变热了就卖：冷热分掉到 {EXIT_COLD} 以下（说明开始有人追它了），第二天开盘卖。每周回来看一次就够——下面「之前入选的」会提醒",
                "涨停：哪天收盘封在涨停，第二天开盘卖（涨停股次日平均高开 2%，之后往回走）",
                f"到期：一直没变热的，买入后第 {HOLD} 个交易日（约半年）收盘卖出",
                "不设价格止损（原因见下面「关于止损」）",
            ],
            "expected": expected(temp),
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
    hot = ev.MID["cold"]["hot10_h60"]
    return {"names": names,
            "note": (f"冷热分最低（最热）的一成，之后 60 个交易日平均比同期随便买少赚 {-hot['new']['ex'] * 100:.1f}%（{ev.NEW['short']}）/ "
                     f"{-hot['old']['ex'] * 100:.1f}%（{ev.OLD['short']}），22 年里没有一年跑赢过。手里有这类股票不必马上卖，但不要追着买。")}


def simulate(s: Stock, t: int, cold_at, hold: int = HOLD, max_gap: float = MAX_GAP) -> tuple[float, int, str] | None:
    """按中期的买卖规则走一遍。cold_at(下标) → 那天的冷热分，没有算过的日子返回 None（不检查）。
    返回 (扣费后收益, 拿了几个交易日, 卖出原因 hot/limit_up/time)；买不进或没走完返回 None。"""
    e = t + 1
    last = e + hold
    if last >= s.n:
        return None
    entry, prev = s.o[e], s.c[t]
    if entry <= 0 or prev <= 0 or entry > prev * (1 + max_gap) or s.opens_at_limit(e):
        return None
    pending = ""
    for j in range(e + 1, last + 1):
        if pending:
            return s.o[j] / entry * (1 - COST) - 1, j - e, pending
        cold = cold_at(j)
        if s.limit_up(j):
            pending = "limit_up"
        elif cold is not None and cold < EXIT_COLD:
            pending = "hot"
        elif j == last:
            if not s.limit_down(j):
                return s.c[j] / entry * (1 - COST) - 1, j - e, "time"
            pending = "time"
    if last + 1 < s.n:
        return s.o[last + 1] / entry * (1 - COST) - 1, last + 1 - e, pending
    return s.c[last] / entry * (1 - COST) - 1, hold, pending


def cold_lookup(s: Stock, crosses: dict[int, Cross]):
    """给 simulate 用：这只股票在算过横截面的那些天的冷热分。"""
    known = {}
    for day, cross in crosses.items():
        i = cross.pos.get(s.code)
        if i is not None and cross.cold:
            known[cross.t[i]] = cross.cold[i]
    return known.get


def recent_check(stocks: dict[str, Stock], crosses: dict[int, Cross], calendar: list[int], n: int) -> dict:
    """最近一年：每隔 10 个交易日按冷热分选一次（只看冷热分和市值——当时的财报这里没有），按同样的规则买卖的结果。
    冷热分每 5 个交易日检查一次。"""
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
            s = stocks[code]
            res = simulate(s, t, cold_lookup(s, crosses))
            if res:
                got.append(res)
            if len(got) == n:
                break
        if not got:
            continue
        span = round(sum(r[1] for r in got) / len(got))          # 这一批平均拿了多久，对照就拿同样久
        market = []
        for c, t in zip(cross.codes, cross.t):
            s = stocks[c]
            e = t + 1
            if e + span < s.n and s.o[e] > 0:
                market.append(s.c[e + span] / s.o[e] * (1 - COST) - 1)
        if market:
            trades += [r[0] for r in got]
            m = sum(market) / len(market)
            base.append(m)
            rows.append({"date": day_text(day), "picks": sum(r[0] for r in got) / len(got), "market": m, "days": span})
    from .sim import stats
    out = stats(trades)
    out.update({"days": len(rows), "baseline": sum(base) / len(base) if base else None, "rows": rows[::-1]})
    return out


def sample_days(calendar: list[int]) -> list[int]:
    """回看用的建仓日：往前 120 天之外（要等结果走完）、370 天之内，每隔 10 个交易日一天。"""
    last = len(calendar) - 1
    return [calendar[j] for j in range(last - HOLD - 2, max(0, last - 370), -STEP)][::-1]


def check_days(calendar: list[int]) -> list[int]:
    """回看时检查冷热分的日子：最近 370 天里每 5 个交易日一天。"""
    last = len(calendar) - 1
    return [calendar[j] for j in range(last, max(0, last - 370), -CHECK_EVERY)][::-1]


def checkup(recent: dict) -> dict:
    new, old = ev.MID["all"]["new"], ev.MID["all"]["old"]
    op = ev.MID["old_plan"]
    cn, co = ev.MID["cold"]["cand_h60"]["new"], ev.MID["cold"]["cand_h60"]["old"]
    hn, ho = ev.MID["cold"]["hot10_h60"]["new"], ev.MID["cold"]["hot10_h60"]["old"]
    bt = ev.MID["by_temp"]
    bs = ev.MID["by_score"]
    return {
        "level": "ok", "n": new["n"], "win_rate": new["win"], "mean": new["mean"], "median": new["median"],
        "baseline": new["base"], "avg_days": new["days"], "span": "十年", "stocks": ev.NEW["pool"],
        "verdict": (f"通过了两个十年的检验。{ev.NEW['label']}：每天按规则选 5 只，共 {new['n']} 笔，{new['win'] * 100:.0f}% 赚钱，平均每笔 {ev.pct(new['mean'])}"
                    f"（平均拿 {new['days']:.0f} 个交易日），同期随便买是 {ev.pct(new['base'])}；"
                    f"{ev.OLD['label']}：{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}，随便买是 {ev.pct(old['base'])}。优势是「比随便买好」，不是「稳赚」。"),
        "more": [
            f"卖出规则比过：原来「拿满 60 天就卖」是 {op['new']['win'] * 100:.0f}% 赚钱、平均 {ev.pct(op['new']['mean'])}（{ev.NEW['short']}）/ "
            f"{op['old']['win'] * 100:.0f}%、{ev.pct(op['old']['mean'])}（{ev.OLD['short']}）；改成「变热了才卖、最多拿半年」后是 "
            f"{new['win'] * 100:.0f}%、{ev.pct(new['mean'])} / {old['win'] * 100:.0f}%、{ev.pct(old['mean'])}。",
            f"买入时机（市场温度）：温度 40 以下买入，平均 {ev.pct(bt['lt40']['new']['mean'])}、{bt['lt40']['new']['win'] * 100:.0f}% 赚钱（{ev.NEW['short']}）/ "
            f"{ev.pct(bt['lt40']['old']['mean'])}、{bt['lt40']['old']['win'] * 100:.0f}%（{ev.OLD['short']}）；40–80 之间 {ev.pct(bt['40to80']['new']['mean'])} / {ev.pct(bt['40to80']['old']['mean'])}；"
            f"80 以上 {ev.pct(bt['ge80']['new']['mean'])} / {ev.pct(bt['ge80']['old']['mean'])}——很热的时候不买。",
            f"买入时机（大盘预估分）：分数 ≥2 的日子买入，平均 {ev.pct(bs['ge2']['new']['mean'])} / {ev.pct(bs['ge2']['old']['mean'])}；"
            f"分数 ≤−1 的日子买入，{ev.pct(bs['le-1']['new']['mean'])} / {ev.pct(bs['le-1']['old']['mean'])}。",
            f"全部符合条件的股票（不只是选出来的 5 只）：之后 60 天比随便买多赚 {ev.pct(cn['ex'])}（{ev.NEW['short']}，{cn['pos_years']}/{cn['years']} 年跑赢）/ "
            f"{ev.pct(co['ex'])}（{ev.OLD['short']}，{co['pos_years']}/{co['years']} 年跑赢）。",
            f"反面：最热的一成之后 60 天比随便买少赚 {-hn['ex'] * 100:.1f}% / {-ho['ex'] * 100:.1f}%，22 年里 {hn['pos_years'] + ho['pos_years']} 年跑赢。",
            f"单只仍有四成会亏：赚的平均 {ev.pct(new['avg_win'], 0)}，亏的平均 {ev.pct(new['avg_loss'], 0)}，最差的 5% 亏 {-new['p5'] * 100:.0f}% 以上。",
            f"亏钱的年份：{ev.years(new['bad_years'])}（{ev.NEW['short']}）、{ev.years(old['bad_years'])}（{ev.OLD['short']}）——都是大盘不好的年份。",
            STOP_NOTE,
            "口径：信号收盘后才知道，第二天开盘买；开盘就涨停的买不进；封死跌停卖不掉顺延；每笔扣 0.2%。",
        ],
        "by_year": {"new": ev.MID["by_year"]["new"], "old": ev.MID["by_year"]["old"]},
        "by_year_base": {"new": ev.MID["by_year_base"]["new"], "old": ev.MID["by_year_base"]["old"]},
        "hist": ev.MID["hist"],
        "recent": recent,
    }


def temp_table(temp: dict | None) -> list[dict]:
    """建仓时的市场温度和之后的结果。"""
    tier = temp_tier(temp)
    return [{"label": label, "current": k == tier,
             **{w: ({"n": x["n"], "mean": x["mean"], "win": x["win"]} if x else None)
                for w, x in (("new", ev.MID["by_temp"][k]["new"]), ("old", ev.MID["by_temp"][k]["old"]))}}
            for k, label in ev.MID_TEMP_ROWS]


def timing(g: dict, temp: dict | None) -> dict:
    """现在是不是建仓的时候：先看市场温度（大方向），再看大盘预估分（这几天）。"""
    score = g["score"]
    bs, bt = ev.MID["by_score"], ev.MID["by_temp"]
    score_text = (f"大盘预估分 {score}：" + (f"这几天也是好时候（分数 ≥2 的日子买入，平均 {ev.pct(bs['ge2']['new']['mean'])} / {ev.pct(bs['ge2']['old']['mean'])}）。" if score >= gg.LIGHT
                                         else "这几天不好不坏，可以先买一部分，剩下的等分数到 2 以上的日子再买。" if score >= 0
                                         else "这几天偏弱，不用急，可以等分数回到 2 以上的日子再动手。"))
    if not temp:
        level = "go" if score >= gg.LIGHT else "wait" if score >= 0 else "avoid"
        return {"level": level, "score": score, "temp": None, "text": score_text, "table": temp_table(None)}
    v = temp["value"]
    if v >= 80:
        level = "avoid"
        text = (f"市场温度 {v:.0f}（很热）：现在不建仓。历史上温度 80 以上买入，平均 {ev.pct(bt['ge80']['new']['mean'])}（{ev.NEW['short']}）/ "
                f"{ev.pct(bt['ge80']['old']['mean'])}（{ev.OLD['short']}），是亏的。名单只供观察。")
    elif v < 40:
        level = "go" if score >= 0 else "wait"
        x = bt["lt20" if v < 20 else "20to40"]
        text = (f"市场温度 {v:.0f}（{temp['label']}）：是建仓的好时候。历史上这个温度买入，平均 {ev.pct(x['new']['mean'])}、{x['new']['win'] * 100:.0f}% 赚钱（{ev.NEW['short']}）/ "
                f"{ev.pct(x['old']['mean'])}、{x['old']['win'] * 100:.0f}%（{ev.OLD['short']}）。{score_text}")
    else:
        level = "wait"
        x = bt["40to60" if v < 60 else "60to80"]
        text = (f"市场温度 {v:.0f}（{temp['label']}）：可以买，但优势比市场冷的时候小——历史上这个温度买入，平均 {ev.pct(x['new']['mean'])}（{ev.NEW['short']}）/ "
                f"{ev.pct(x['old']['mean'])}（{ev.OLD['short']}）。仓位小一点。{score_text}")
    return {"level": level, "score": score, "temp": v, "text": text, "table": temp_table(temp)}


def select(stocks: dict[str, Stock], crosses: dict[int, Cross], g: dict, rows: dict[str, dict], reports: dict[str, dict],
           calendar: list[int], as_of: str, n: int, temp: dict | None = None) -> dict:
    cross = crosses.get(day_int(as_of)) or Cross(day_int(as_of))
    cands, reasons = candidates(stocks, cross, rows, reports)
    picked = diversify(cands, n)
    industry = {c: r.get("industry", "") for c, r in reports.items()}
    board = {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "timing": timing(g, temp),
        "picks": [build_pick(stocks[c["code"]], c, temp, as_of) for c in picked],
        "avoid": avoid_list(stocks, cross, rows, industry),
        "funnel": {"pool": len(stocks), "candidates": len(cands), "picked": len(picked), "reasons": reasons,
                   "cold": sum(1 for x in cross.cold if x >= COLD_MIN)},
        "checkup": checkup(recent_check(stocks, crosses, calendar, n)), "warnings": [],
    }
    if not reports:
        board["warnings"].append("全市场财报摘要没取到，中期板块这次没有检查「利润同比增长超过 10%」这一条，入选的股票请自己核对最新财报")
    return board
