"""短期（5 个交易日）· 看天出手

顺序是：先判断大盘 → 再看大盘股还是小盘股 → 避开当天最热的板块 → 最后才选股。大盘这一关过不了，就空仓。

为什么这么排：在二十二年的真实行情上检验下来，短线的输赢主要取决于「哪天出手」，而不是「买哪只」。
- 同一套选股规则，只在大盘预估分 ≥3 的日子用，每笔平均 +2.9%，六成赚钱；每天都用，平均只有 +0.25%，一半亏钱；
  专挑分数低的日子用，是亏的。差别全在第一步。
- 分数够的日子里，买什么：近期跌得多、离高点远、没人追捧的。恐慌或者放量之后，被错杀的股票反弹最多；
  当天涨停的、领涨的、放巨量的、收在最高位的，之后最差。
- 涨停股「第二天指数一直涨」是真的，但涨幅几乎全在第二天开盘那一下，买不到；第二天开盘追进去的平均是亏的（见 evidence.py）。
- 板块没有「追强」的规律：当天涨停最集中的板块，之后反而跑输，所以只做回避。

计划很简单：第二天开盘买，拿 5 个交易日，收盘跌破买入价 8% 止损。不设止盈——赚的那些平均赚 8%，
设了止盈会把最赚钱的几笔截掉，平均收益反而更低。
"""

from __future__ import annotations

from . import evidence as ev
from . import gauge as gg
from . import sim
from .common import bucket_of, diversify, pct_rank, price
from .features import Cross, oversold_score
from .pool import Stock, day_int, day_text

KEY, TITLE, NAME = "short", "短期", "看天出手"
HORIZON = "5 个交易日"
HOLD, STOP, MAX_GAP = 5, 0.08, 0.02
ETF_STOP = 0.06
MIN_COLD = 50              # 冷热分在后一半（偏热）的不选

IDEA = ("先看大盘，再决定出不出手。短线的输赢主要取决于哪天出手：同一套选股规则，只在「大盘预估分」高的日子用才赚钱，"
        "每天都用等于没用。分数不够就空仓——这是这个板块最常见、也最重要的结论。")
HOW = [
    "第一步 大盘：给今天收盘后的市场打分（放量、大涨大跌、涨停跌停多、月末月初加分；平淡、缩量扣分）。≥3 分出手，2 分轻仓，其余不出手",
    "第二步 风格：小盘股近期领涨、市场活跃时偏向中小盘；市场冷清时偏向大盘",
    "第三步 板块：今天涨停最集中的板块不碰（这类板块之后平均跑输）",
    "第四步 选股：近 5 天、近 20 天跌得多，离一年高点远，冷热分偏冷（没人追）的；今天涨停、跌停或涨了 5% 以上的不选；公司要在赚钱",
    "第二天开盘买（高开 2% 以上放弃），拿 5 个交易日；收盘跌破买入价 8% 止损；不设止盈",
]
ETFS = {
    "小盘占优": [("SH:512100", "512100", "中证1000ETF", "中证1000"), ("SH:510500", "510500", "中证500ETF", "中证500")],
    "不明显": [("SH:512100", "512100", "中证1000ETF", "中证1000"), ("SH:510300", "510300", "沪深300ETF", "沪深300")],
    "大盘更稳": [("SH:510300", "510300", "沪深300ETF", "沪深300"), ("SH:510500", "510500", "中证500ETF", "中证500")],
}
FAQ = [
    {"q": "为什么不直接买涨停股？听说涨停股第二天的指数一直在涨", "a": ev.FACTS["limit_up"]},
    {"q": "为什么不追最强的板块？", "a": ev.FACTS["hot_sector"]},
    {"q": "为什么大多数日子都让我空仓？",
     "a": "因为平常日子做短线，扣掉手续费后平均是亏的。近十年里，大盘预估分 ≤−1 的日子（占三成）之后 5 天全市场平均 −0.5%；"
          "0–1 分的日子（占一半）在 0 附近。机会集中在一成左右的日子里，其余时间不动才是对的。"},
    {"q": "为什么不设止盈？", "a": "检验过：设 6% 或 8% 的止盈，胜率能高几个点，但平均每笔少赚 0.6–1 个点——"
                              "赚钱的那些平均赚 8%，其中最赚的几笔正是被止盈截掉的。拿满 5 天再卖更划算。"},
]


def candidates(stocks: dict[str, Stock], cross: Cross, rows: dict[str, dict], industry: dict[str, str],
               hot: set[str]) -> tuple[list[dict], dict]:
    """今天符合选股条件的，按排序分从高到低。返回 (候选, 各种没入选的原因计数)。"""
    score = oversold_score(cross) if len(cross) else []
    r5_rank = pct_rank(list(cross.col["r5"]), higher_better=False) if len(cross) else []
    out, reasons = [], {}

    def miss(why):
        reasons[why] = reasons.get(why, 0) + 1

    for i, code in enumerate(cross.codes):
        s, t = stocks[code], cross.t[i]
        if t != s.n - 1:
            continue
        row = rows.get(code) or {}
        ind = industry.get(code) or row.get("industry") or ""
        if s.limit_up(t) or s.limit_down(t):
            miss("今天涨停或跌停")
        elif cross.col["r1"][i] >= 0.05:
            miss("今天涨了 5% 以上")
        elif cross.cold[i] < MIN_COLD:
            miss("冷热分偏热（有人在追）")
        elif not (row.get("pe") and row["pe"] > 0):
            miss("公司在亏损，或者没有取到市盈率")
        elif ind in hot:
            miss("属于今天涨停最集中的板块")
        else:
            out.append({"code": code, "name": row.get("name") or s.name, "industry": ind, "bucket": bucket_of(ind, s.name),
                        "score": score[i], "r5": cross.col["r5"][i], "r20": cross.col["r20"][i], "hi": cross.col["hi"][i],
                        "r1": cross.col["r1"][i], "cold": cross.cold[i], "r5_rank": r5_rank[i], "pe": row.get("pe")})
    out.sort(key=lambda c: -c["score"])
    return out, reasons


def expected(stance: str) -> dict:
    tier = "go" if stance == "go" else "light"
    new, old = ev.SHORT[tier]["new"], ev.SHORT[tier]["old"]
    label = "分数 ≥3 的日子" if tier == "go" else "分数 ≥2 的日子"
    text = (f"历史上{label}按这个规则买入（{ev.NEW['short']} {new['n']} 笔）：{new['win'] * 100:.0f}% 赚钱，平均每笔 {ev.pct(new['mean'])}，"
            f"中位 {ev.pct(new['median'])}；赚的平均 {ev.pct(new['avg_win'])}，亏的平均 {ev.pct(new['avg_loss'])}。"
            f"{ev.OLD['short']}（{old['n']} 笔）：{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}。"
            f"单只有四成会亏，所以要把今天的几只都买上，不要只挑一只。")
    return {"available": True, "kind": "trade", "reliable": True, "n": new["n"], "win_rate": new["win"], "median": new["median"],
            "mean": new["mean"], "avg_days": new["days"], "text": text}


def build_pick(s: Stock, c: dict, stance: str, as_of: str) -> dict:
    close = s.c[-1]
    stop_ref = price(close * (1 - STOP))
    evidence = [
        {"label": "近 5 天", "status": "pass", "detail": f"{c['r5'] * 100:+.1f}%，在全市场里属于跌得最多的 {max(1, 100 - c['r5_rank']):.0f}%"},
        {"label": "近 20 天", "status": "pass" if c["r20"] < 0 else "info", "detail": f"{c['r20'] * 100:+.1f}%"},
        {"label": "离一年高点", "status": "pass", "detail": f"低 {-c['hi'] * 100:.0f}%"},
        {"label": "冷热分", "status": "pass" if c["cold"] >= 70 else "info",
         "detail": f"{c['cold']:.0f}（100 最冷）：" + ("没什么人追" if c["cold"] >= 70 else "不算热")},
        {"label": "公司盈利", "status": "pass", "detail": f"市盈率 {c['pe']:.0f} 倍，在赚钱"},
    ]
    risks = ["如果买入后出了利空公告（业绩暴雷、被立案等），不等止损价，直接卖",
             "历史上最差的情况：2015 年那种连环暴跌里，一篮子 5 只在 5 天里亏过 20% 以上——所以单只不超过一成仓位"]
    if stance == "light":
        risks.insert(0, f"今天是轻仓档：历史上这一档每笔平均只有 {ev.pct(ev.SHORT['light']['new']['mean'])}，仓位减半")
    return {
        "key": s.key, "code": s.code, "name": c["name"], "kind": "stock", "industry": c["industry"],
        "price": price(close), "as_of": as_of, "score": round(c["score"], 1),
        "headline": f"5 天跌了 {-c['r5'] * 100:.1f}%、离一年高点 {-c['hi'] * 100:.0f}%，没人追捧；大盘预估分够了，博 5 天的反弹",
        "evidence": evidence, "risks": risks,
        "spark": {"closes": [round(x, 2) for x in s.c[-120:]], "refs": [{"y": stop_ref, "label": "止损"}]},
        "meters": [{"label": "近 5 天跌幅", "value": c["r5_rank"], "text": f"比 {c['r5_rank']:.0f}% 的股票跌得多"},
                   {"label": "冷热分", "value": c["cold"], "text": f"{c['cold']:.0f}（越高越没人追）"}],
        "plan": {
            "horizon": HORIZON, "hold_max": HOLD,
            "entry": f"明天开盘买入；开盘价高于 {price(close * (1 + MAX_GAP))}（比今天收盘高 2%）就放弃，不追",
            "ref_price": price(close), "target_price": None, "target_pct": None,
            "stop_price": stop_ref, "stop_pct": round(STOP * 100, 1),
            "stop_note": "止损价按买入价算；这里的价格是按今天收盘价估的",
            "position": "单只不超过总资金的一成" + ("（今天是轻仓档，再减半）" if stance == "light" else ""),
            "rules": [
                f"到期：买入后第 {HOLD} 个交易日收盘卖出，不管赚亏",
                f"止损：哪天收盘价比你的买入价低 {STOP * 100:.0f}% 以上（按今天收盘价估约 {stop_ref}），当天收盘卖",
                "不设止盈：检验下来拿满 5 天比提前止盈赚得多",
                "买入当天不能卖（T+1），所以高开太多宁可放弃",
            ],
            "expected": expected(stance),
        },
    }


def etf_picks(g: dict, quotes: dict[str, dict] | None = None) -> dict:
    """同样的日子直接买宽基 ETF：省心，也不会碰上个股的雷。"""
    label = g["style"]["label"]
    tier = "go" if g["stance"] == "go" else "light"
    days = "分数 ≥3 的日子" if tier == "go" else "分数 ≥2 的日子"
    picks = []
    for key, code, name, index in ETFS[label]:
        new, old = ev.SHORT["etf"][tier][index]["new"], ev.SHORT["etf"][tier][index]["old"]
        q = (quotes or {}).get(code) or {}
        close = q.get("close")
        picks.append({
            "key": key, "code": code, "name": name, "kind": "etf", "price": price(close) if close else None, "index": index,
            "why": f"跟踪{index}指数。历史上{days}第二天开盘买入{index}、拿 5 天："
                   f"{ev.NEW['short']}平均 {ev.pct(new[0])}、{new[1] * 100:.0f}% 的时候赚；{ev.OLD['short']}平均 {ev.pct(old[0])}、{old[1] * 100:.0f}%。",
            "stop_price": price(close * (1 - ETF_STOP)) if close else None,
            "rules": [f"明天开盘买，买入后第 {HOLD} 个交易日收盘卖", f"收盘价比买入价低 {ETF_STOP * 100:.0f}% 以上就卖"],
        })
    how = "不想选股、或者想少担个股风险，可以直接买宽基 ETF：收益比精选个股低（约一半），但省心，手续费也低。"
    if tier == "light":
        how += "今天只有 2 分，是轻仓档，ETF 的优势也相应小一些。"
    return {"style": label, "note": g["style"]["advice"], "picks": picks, "how": how}


def recent_check(stocks: dict[str, Stock], crosses: dict[int, Cross], history: list[dict], rows: dict[str, dict],
                 n: int, min_score: int = gg.GO) -> dict:
    """最近两年多里每个出手日，按今天同样的规则选出来的股票后来怎么样（没有用到当时拿不到的信息，
    只是盈利与否用的是现在的市盈率）。"""
    after = {h["date"]: h for h in history}
    trades, days, base = [], [], []
    for day, cross in sorted(crosses.items()):
        h = after.get(day_text(day))
        if h is None or h["score"] < min_score or not len(cross):
            continue
        score = oversold_score(cross)
        cands = []
        for i, code in enumerate(cross.codes):
            s, t = stocks[code], cross.t[i]
            pe = (rows.get(code) or {}).get("pe")
            if s.limit_up(t) or s.limit_down(t) or cross.col["r1"][i] >= 0.05 or cross.cold[i] < MIN_COLD or not (pe and pe > 0):
                continue
            cands.append((score[i], code, t))
        got = []
        for _, code, t in sorted(cands, reverse=True)[:n * 2]:
            res = sim.trade(stocks[code], t, HOLD, MAX_GAP, STOP)
            if res:
                got.append(res[0])
            if len(got) == n:
                break
        if got:
            trades += got
            days.append({"date": h["date"], "score": h["score"], "picks": sum(got) / len(got), "market": h["after"]})
            base.append(h["after"])
    out = sim.stats(trades)
    out.update({"days": len(days), "baseline": sum(base) / len(base) if base else None, "rows": days[::-1][:12]})
    return out


def checkup(recent: dict) -> dict:
    """页面上「方法体检」那一块：长期的检验结果 + 最近的实际表现。"""
    new, old = ev.SHORT["go"]["new"], ev.SHORT["go"]["old"]
    every = ev.SHORT["everyday"]["new"]
    bad = ev.SHORT["bad_days"]["new"]
    cold, warm = ev.SHORT["by_temp"]["lt40"], ev.SHORT["by_temp"]["ge60"]
    return {
        "level": "ok", "n": new["n"], "win_rate": new["win"], "mean": new["mean"], "median": new["median"],
        "baseline": new["base"], "avg_days": new["days"], "span": "十年", "stocks": ev.NEW["pool"],
        "verdict": (f"通过了两个十年的检验。{ev.NEW['label']}：分数 ≥3 的日子按规则买入共 {new['n']} 笔，{new['win'] * 100:.0f}% 赚钱，"
                    f"平均每笔 {ev.pct(new['mean'])}（同样的日子随便买是 {ev.pct(new['base'])}）；"
                    f"{ev.OLD['label']}：{old['n']} 笔，{old['win'] * 100:.0f}% 赚钱，平均 {ev.pct(old['mean'])}，12 年里{('只有 ' + ev.years(old['bad_years']) + '是亏的') if old['bad_years'] else '没有一年是亏的'}。"),
        "more": [
            f"对照一：同样的选股规则每天都用，{every['n']} 笔里只有 {every['win'] * 100:.0f}% 赚钱，平均 {ev.pct(every['mean'], 2)}——等于没用。",
            f"对照二：专挑分数 ≤−1 的日子用，{bad['win'] * 100:.0f}% 赚钱，平均 {ev.pct(bad['mean'], 2)}。所以分数不够的日子不出手。",
            f"市场温度：温度 40 以下时出手，平均 {ev.pct(cold['new']['mean'])} / {ev.pct(cold['old']['mean'])}；60 以上只有 {ev.pct(warm['new']['mean'])} / {ev.pct(warm['old']['mean'])}；"
            f"80 以上是 {ev.pct(ev.SHORT['by_temp']['ge80']['old']['mean'])}。去掉温度 80 以上的日子后，两个十年里没有一年是亏的。",
            f"亏钱的年份：{ev.years(new['bad_years'])}（{ev.NEW['short']}）、{ev.years(old['bad_years'])}（{ev.OLD['short']}）。",
            f"最差的情况：一篮子 5 只在 5 天里亏过 {-new['basket_worst'] * 100:.0f}%（近十年）/ {-old['basket_worst'] * 100:.0f}%（2015 年）。"
            "止损和单只一成仓位就是为这个准备的。",
            ev.FACTS["short_hold"], ev.FACTS["short_entry"],
            "口径：信号收盘后才知道，第二天开盘买；开盘就涨停的买不进；当天买的当天不能卖；每笔扣 0.2%。",
        ],
        "by_year": {"new": ev.SHORT["by_year"]["new"], "old": ev.SHORT["by_year"]["old"]},
        "hist": ev.SHORT["hist"],
        "recent": recent,
    }


def select(stocks: dict[str, Stock], crosses: dict[int, Cross], g: dict, rows: dict[str, dict], industry: dict[str, str],
           as_of: str, n: int, etf_quotes: dict[str, dict] | None = None) -> dict:
    cross = crosses.get(day_int(as_of)) or Cross(day_int(as_of))
    hot = {h["name"] for h in g["hot_sectors"]}
    cands, reasons = candidates(stocks, cross, rows, industry, hot)
    acting = g["stance"] in ("go", "light")
    picked = diversify(cands, n) if acting else []
    recent = recent_check(stocks, crosses, g.get("history") or [], rows, n)
    board = {
        "key": KEY, "title": TITLE, "name": NAME, "horizon": HORIZON, "idea": IDEA, "how": HOW,
        "gauge": {k: v for k, v in g.items() if k != "history"},
        "stance": {"key": g["stance"], "label": g["label"], "text": g["basis"]},
        "picks": [build_pick(stocks[c["code"]], c, g["stance"], as_of) for c in picked],
        "etfs": etf_picks(g, etf_quotes) if acting else None,
        "funnel": {"pool": len(stocks), "candidates": len(cands), "picked": len(picked), "reasons": reasons},
        "checkup": checkup(recent), "faq": FAQ, "warnings": [],
    }
    if not acting:
        board["note"] = ("今天不出手。" + g["basis"] + " " + g["next_window"]["text"] +
                         "；另外，哪天全市场放量、大涨大跌或者跌停很多，分数也会上来。")
    elif not picked:
        board["note"] = "大盘这一关过了，但今天没有符合选股条件的股票。可以考虑下面的宽基 ETF。"
    return board
