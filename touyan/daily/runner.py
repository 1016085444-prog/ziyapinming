"""每日精选的一次完整运行：大盘 → 选股 → ETF → 场外基金 →（可选）大模型点评 → 保存。

全市场快照和基金排行各取一次；入围的几十只股票、十几只基金再逐只体检。整个过程约 1–3 分钟，
数据源用的都是已有的降级链路，个别标的取不到会跳过并记在 warnings 里，不会让整次运行失败。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import config
from agents.llm import LLMError, make_llm, strip_think
from market import eastmoney, symbols, universe
from market.models import Instrument, MarketData, Quote
from market.net import SourceError
from quant import report as qr

from . import backtest
from . import funds as fundpick
from . import market as mkt
from . import screen, strategies

log = logging.getLogger("touyan.daily")
BJ = timezone(timedelta(hours=8))
DISCLAIMER = ("每日精选由公开数据和固定规则自动生成，用来缩小研究范围，不是买卖指令，也不构成投资建议。"
              "规则没有经过长期回测验证，请结合「历史表现」和自己的判断使用。")


def beijing_now() -> datetime:
    return datetime.now(BJ)


# ── 按收盘算 ──────────────────────────────────────────────────────
# 每日精选一律用完整交易日的收盘数据。交易日收盘前（9:15 集合竞价起到 15:00）生成时，
# 用上一个交易日的收盘：K 线去掉今天还没走完的那根；全市场快照优先用上次收盘后存下的，
# 没有的话用实时行情倒推到昨天收盘（估值按昨收折算，成交额、涨跌幅改用 K 线上昨天的数据复核）。

EOD_KEY = "universe:a-share:eod"
DERIVED_NOTE = ("今天还没收盘：全市场数据按实时行情倒推到上一交易日收盘，估值按昨天的收盘价折算；"
                "成交额、涨跌幅等今天还没走完的数据不参与初筛，改用 K 线上昨天的数据复核。"
                "软件在收盘后开着的话会自动存下当天的完整数据，下次盘中生成就不用倒推了。")


def session_intraday(now: datetime, bench: list) -> bool:
    """今天的交易是不是还没走完（数据里有今天的半根 K 线，或者在集合竞价到刚开盘之间）。"""
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    if bench and bench[-1].date == now.date().isoformat():
        return t < (15, 0)
    return (9, 15) <= t < (9, 35)          # 之后还没有今天的 K 线，多半是节假日休市


def drop_partial(bars: list, partial: str | None) -> list:
    return bars[:-1] if partial and bars and bars[-1].date == partial else bars


def to_prev_close(r: dict) -> dict:
    """实时快照倒推到昨天收盘：价格、市值、市盈率、市净率都按昨收折算；今天的成交和涨跌去掉。"""
    out = {k: v for k, v in r.items() if k not in ("amount", "turnover", "volume_ratio", "change_pct")}
    chg = r.get("change_pct")
    if chg is not None and r.get("price") and chg > -100:
        f = 1 / (1 + chg / 100)
        out["price"] = r["price"] * f
        for k in ("total_mv", "float_mv", "pe", "pb"):
            if out.get(k) is not None:
                out[k] = out[k] * f
    return out


def close_snapshot(cache, as_of: str, intraday: bool, now: datetime) -> tuple[list[dict], str, list[str], str]:
    """返回 (行, 来源说明, 提示, 口径)。口径：live 收盘后的实时快照 / eod 上次收盘后存下的 / derived 盘中倒推。"""
    if intraday:
        hit = cache.get_stale(EOD_KEY, 10 * 86400)
        if hit and hit[0].get("date") == as_of:
            v = hit[0]
            return v["rows"], f"{v['source']}（{as_of} 收盘后存下的全市场数据）", [], "eod"
        since_open = (now - now.replace(hour=9, minute=15, second=0, microsecond=0)).total_seconds()
        rows, source, warnings = universe.a_share_snapshot(cache, max_age=max(60.0, min(1800.0, since_open)))
        return [to_prev_close(r) for r in rows], f"{source}（实时行情倒推到 {as_of} 收盘）", warnings + [DERIVED_NOTE], "derived"
    max_age = 1800.0
    if now.weekday() < 5 and as_of == now.date().isoformat():     # 今天收盘后：只认 15:00 以后取的快照
        since_close = (now - now.replace(hour=15, minute=0, second=0, microsecond=0)).total_seconds()
        max_age = max(60.0, min(1800.0, since_close))
    rows, source, warnings = universe.a_share_snapshot(cache, max_age=max_age)
    if not warnings:                                               # 用了旧缓存兜底的不能当作收盘数据存
        cache.set(EOD_KEY, {"date": as_of, "rows": rows, "source": source})
    return rows, source, warnings, "live"


def _r(x, n: int = 2):
    return round(x, n) if isinstance(x, (int, float)) else x


# ── 运行状态（给网页轮询） ────────────────────────────────────────

class RunStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {"running": False, "stage": "", "message": "", "percent": 0, "error": "",
                      "started_at": "", "finished_at": "", "run_id": ""}

    def update(self, **kw) -> None:
        with self._lock:
            self._data.update(kw)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


STATUS = RunStatus()
_run_lock = threading.Lock()


def is_running() -> bool:
    return _run_lock.locked()


# ── 选股 ──────────────────────────────────────────────────────────

def _quote_from_row(r: dict) -> Quote:
    return Quote(price=r.get("price"), change_pct=r.get("change_pct"), amount=r.get("amount"),
                 turnover=r.get("turnover"), pe=r.get("pe"), pb=r.get("pb"), total_cap=r.get("total_mv"),
                 float_cap=r.get("float_mv"), change_60d=r.get("change_60d"), change_ytd=r.get("ytd"),
                 industry=r.get("industry", ""), source="全市场快照")


def _stock_report(router, r: dict, bench: list, rf: float, partial: str | None = None
                  ) -> tuple[Instrument, MarketData, dict]:
    inst = symbols.from_key(f"{r['market']}:{r['code']}", "stock", r["name"])
    bars, source = router.series(inst, 800)          # 3 年多：历史参照要用；也和分析页共用缓存
    bars = drop_partial(bars, partial)
    md = MarketData(instrument=inst, bars=bars, benchmark=symbols.CSI300, benchmark_bars=bench,
                    quote=_quote_from_row(r), sources={"行情": source, "估值": "全市场快照"},
                    fetched_at=beijing_now().strftime("%Y-%m-%d %H:%M"))
    try:
        md.financials = router.financials(inst)
    except SourceError as exc:
        md.warnings.append(f"财务数据取不到：{exc}")
    return inst, md, qr.build(md, rf, chart_bars=2)


def _feature_view(f: dict) -> dict:
    keys = ("ma5", "ma10", "ma20", "ma60", "bias_ma5", "bias_ma20", "change_20d", "change_60d", "rsi14",
            "volatility_20d", "drawdown_20d", "atr_pct", "vol_ratio_5_20", "signal_score")
    out = {k: _r(f.get(k), 3 if k.startswith("ma") else 2) for k in keys}
    out.update({k: f[k] for k in ("ma_aligned", "ma_bullish", "above_ma20", "macd_status", "rsi_status")})
    return out


def _round_all(d: dict | None, n: int = 4) -> dict | None:
    return {k: _r(v, n) for k, v in d.items()} if d else d


def fill_industries(rows: list[dict]) -> str:
    """给缺行业的候选补上行业（一次批量请求）；取不到时按名字猜（银行、证券、保险）。返回提示或空串。"""
    missing = [r for r in rows if not r.get("industry")]
    if not missing:
        return ""
    note = ""
    try:
        found = eastmoney.industries([f"{1 if r['market'] == 'SH' else 0}.{r['code']}" for r in missing])
    except SourceError as exc:
        found, note = {}, f"股票所属行业取不到（{exc}），行业分散只能按名字粗略判断"
    for r in missing:
        r["industry"] = found.get(r["code"]) or screen.guess_industry(r.get("name", ""))
    return note


def pick_stocks(router, rows: list[dict], strat: dict, n: int, bench: list, rf: float, progress,
                derived: bool = False, partial: str | None = None, source: str = "") -> dict:
    hard, skipped = screen.usable_hard(rows, strat["hard"])
    kept, dropped = screen.hard_filter(rows, hard)
    ranked = screen.prescreen(kept, strat)
    pool = ranked[: int(strat.get("pool", 30) * (1.5 if derived else 1))]   # 倒推的数据要靠 K 线复核，多留一些
    warnings = [w for w in [fill_industries(pool)] if w]
    if skipped:
        warnings.append("全市场数据里「" + "、".join(skipped) + "」几乎都是空的（接口变了，或者还没开盘），这几条条件这次没有用")
    p = strategies.profile(strat)
    cands, daily_dropped, failed, stale = [], Counter(), 0, 0

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [(r, ex.submit(_stock_report, router, r, bench, rf, partial)) for r in pool]
        for i, (r, fut) in enumerate(futures, 1):
            progress("选股", f"逐只体检初选股票（{i}/{len(pool)}）", 10 + 50 * i / max(len(pool), 1))
            try:
                inst, md, rep = fut.result()
            except Exception as exc:          # 单只失败不影响整体
                failed += 1
                log.info("跳过 %s：%s", r["code"], exc)
                continue
            if len(md.bars) < 120:
                daily_dropped["上市不满半年"] += 1
                continue
            feats = screen.daily_features(md.bars)
            if r.get("price") and abs(r["price"] / feats["close"] - 1) > 0.01:
                stale += 1                     # 快照价和 K 线收盘价对不上：两边有一边不是最新的
            if derived:
                r, reason = screen.recheck_with_bars(r, md.bars, hard)
                if reason:
                    daily_dropped[reason + "（按昨天收盘）"] += 1
                    continue
            reason = screen.daily_reject(feats, strat["daily"])
            if reason:
                daily_dropped[reason] += 1
                continue
            factors = screen.factor_scores(r, feats, p)
            s_score = screen.weighted(factors, strat["weights"])
            pen, notes = screen.risk_penalty(r, feats, strat["risk"])
            composite = rep["scores"]["composite"]
            final = screen.final_score(s_score, feats["signal_score"], composite, pen)
            industry = rep.get("industry") or r.get("industry") or ""
            cands.append({
                "key": inst.key, "code": inst.code, "name": inst.name or r["name"], "market": inst.market,
                "industry": industry, "bucket": screen.bucket_of(industry, inst.name or r["name"]),
                # 价格取 K 线收盘：仪表盘里的买点、止损都由它算出，两处必须一致
                "price": round(feats["close"], 3 if feats["close"] < 1 else 2), "change_pct": r.get("change_pct"),
                "as_of": rep["as_of"],
                "pe": _r(r.get("pe")), "pb": _r(r.get("pb")), "total_mv": r.get("total_mv"),
                "amount": r.get("amount"), "turnover": _r(r.get("turnover")),
                "score": final, "screen_score": s_score, "signal_score": round(feats["signal_score"], 1),
                "quant_score": composite, "quant_rating": rep["scores"]["rating"]["label"], "penalty": pen,
                "factors": factors, "features": _feature_view(feats),
                "_feats": feats, "_rep": rep, "_row": r, "_notes": notes, "_bars": md.bars,
            })

    cands.sort(key=lambda c: -c["score"])
    picks = screen.diversify(cands, n)
    for c in picks:
        c["dashboard"] = screen.dashboard(c["_row"], c["_feats"], c["_rep"], c["score"], c["_notes"], strat["hold"])
        plan = c["dashboard"]["plan"]
        plan["history"] = _round_all(backtest.plan_history(
            c["_bars"], plan["target_pct"], plan["stop_pct"], plan["hold_max"], plan["breakeven_pct"]))
    runners = [{"key": c["key"], "name": c["name"], "code": c["code"], "industry": c["industry"], "score": c["score"]}
               for c in cands if c not in picks][:8]
    for c in cands:
        for k in ("_feats", "_rep", "_row", "_notes", "_bars"):
            c.pop(k, None)
    checked = len(pool) - failed
    if checked >= 5 and stale > checked / 2:
        warnings.append(f"有 {stale}/{checked} 只股票的全市场快照价格和 K 线收盘价对不上，"
                        "其中一边可能不是最新数据（比如快照还没更新到今天收盘）")
    return {
        "picks": picks, "runners_up": runners, "warnings": warnings,
        "funnel": {"universe": len(rows), "passed_hard": len(kept), "pool": len(pool), "source": source,
                   "skipped": skipped,
                   "checked": len(pool) - failed, "passed_daily": len(cands), "picked": len(picks),
                   "dropped": dict(list(dropped.items())[:6]), "daily_dropped": dict(daily_dropped.most_common(6)),
                   "failed": failed},
    }


# ── ETF ──────────────────────────────────────────────────────────

def _etf_inst(code: str, name: str) -> Instrument:
    return symbols.from_key(("SH:" if code[0] in "56" else "SZ:") + code, "etf", name)


def pick_etfs(router, progress, bench: list | None = None, n: int = 3, partial: str | None = None) -> dict:
    series: dict[str, list] = {}

    def one(item):
        code, name, group = item
        inst = _etf_inst(code, name)
        bars, _ = router.series(inst, 800)
        bars = drop_partial(bars, partial)
        series[code] = bars
        return {"key": inst.key, "code": code, "name": name, "group": group,
                "price": _r(bars[-1].close, 3), "as_of": bars[-1].date, "momentum": fundpick.etf_momentum(bars)}

    rows, warnings = [], []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [(item, ex.submit(one, item)) for item in fundpick.ETF_POOL]
        for i, (item, fut) in enumerate(futures, 1):
            progress("ETF", f"计算 ETF 动量（{i}/{len(futures)}）", 60 + 10 * i / len(futures))
            try:
                rows.append(fut.result())
            except Exception as exc:
                warnings.append(f"{item[1]}：{exc}")
    for r in rows:
        if r["momentum"]:
            r["momentum"] = {k: _r(v) for k, v in r["momentum"].items()}
    picks, note = fundpick.etf_picks(rows, n)
    ranked = sorted((r for r in rows if r["momentum"]), key=lambda r: -r["momentum"]["score"])
    safe = None
    if len(picks) < n:
        code, name, group = fundpick.SAFE_ETF
        inst = _etf_inst(code, name)
        safe = {"key": inst.key, "code": code, "name": name, "group": group}
    history = None
    if bench and len(series) >= n:
        try:
            safe_bars, _ = router.series(_etf_inst(*fundpick.SAFE_ETF[:2]), 800)
            safe_bars = drop_partial(safe_bars, partial)
        except Exception:
            safe_bars = None
        history = _round_all(backtest.rotation_backtest(series, bench, safe_bars, top_n=n))
    plan = {"rules": fundpick.ETF_RULES, "history": history}
    return {"picks": picks, "ranking": ranked, "note": note, "safe": safe, "plan": plan,
            "warnings": warnings[:5] + ([f"另有 {len(warnings) - 5} 只取不到"] if len(warnings) > 5 else [])}


# ── 场外基金 ──────────────────────────────────────────────────────

def _fund_report(router, row: dict, rf: float) -> tuple[dict, list]:
    inst = Instrument(row["code"], "OF", "fund", row["name"])
    md = router.load(inst, days=1200, with_news=False)
    return qr.build(md, rf, chart_bars=2), md.bars


def pick_funds(router, cache, rf: float, progress) -> dict:
    groups, warnings = [], []
    used: set[str] = set()          # 同一只基金可能同时出现在两个类别的排行里，只选一次
    for gi, (key, label, fts, n) in enumerate(fundpick.FUND_PLAN):
        progress("基金", f"筛选{label}", 70 + 20 * gi / len(fundpick.FUND_PLAN))
        rows = []
        for ft in fts:
            try:
                rows += universe.fund_rank(cache, ft)
            except SourceError as exc:
                warnings.append(f"{universe.FUND_TYPES[ft]}基金排行取不到：{exc}")
        ranked = [r for r in fundpick.fund_perf_scores(fundpick.fund_prefilter(rows))
                  if r["code"] not in used and fundpick.share_class_key(r["name"]) not in used][: max(6, n * 3)]
        picks, rejected = [], []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [(r, ex.submit(_fund_report, router, r, rf)) for r in ranked]
            for r, fut in futures:
                try:
                    rep, nav = fut.result()
                except Exception as exc:
                    rep, nav = None, []
                    log.info("基金 %s 体检失败：%s", r["code"], exc)
                score, pros, cons = fundpick.fund_verdict(r, rep)
                if score is None:
                    rejected.append({"code": r["code"], "name": r["name"], "reason": (cons or ["未通过"])[0]})
                    continue
                m3 = ((rep or {}).get("metrics") or {}).get("3y") or {}
                profile = ((rep or {}).get("fund") or {}).get("profile") or {}
                picks.append({
                    "key": f"OF:{r['code']}", "code": r["code"], "name": r["name"], "category": label,
                    "type": r["type"], "nav": r.get("nav"), "nav_date": r.get("nav_date"), "fee": r.get("fee"),
                    "returns": {k: r.get(k) for k in ("m6", "y1", "y2", "y3", "ytd")},
                    "perf_score": r["perf_score"], "quant_score": rep["scores"]["composite"],
                    "quant_rating": rep["scores"]["rating"]["label"], "score": score,
                    "max_drawdown_3y": _r(m3.get("max_drawdown"), 4), "sharpe_3y": _r(m3.get("sharpe")),
                    "scale": profile.get("scale"), "pros": pros, "cons": cons,
                    "plan": fundpick.fund_plan(key, r.get("ft", ""), m3.get("max_drawdown"), _round_all(
                        backtest.rolling_stats(nav, fundpick.FUND_HOLD.get(key, ("", 250))[1]))),
                })
        picks.sort(key=lambda x: -x["score"])
        for x in picks[:n]:
            used.update((x["code"], fundpick.share_class_key(x["name"])))
        groups.append({"key": key, "label": label, "picks": picks[:n], "screened": len(ranked),
                       "rejected": rejected[:4]})
    return {"groups": groups, "warnings": warnings}


# ── 大模型点评（可选） ────────────────────────────────────────────

COMMENT_SYSTEM = (
    "你是一名谨慎的投研助理。根据用户给的结构化数据写今日点评，350 字以内，分三段：大盘环境；"
    "精选股票为什么入选、要注意什么；ETF 和基金怎么看。只能引用数据里出现的数字和事实，不编造新闻、业绩或价格；"
    "不使用「必涨」「稳赚」「强烈推荐」这类词；最后一句提醒：仅供研究参考，不构成投资建议。"
)


def commentary(payload: dict) -> tuple[str | None, str]:
    s = config.load()
    ready, reason = config.llm_ready(s)
    if not ready:
        return None, reason
    brief = {
        "日期": payload["as_of"], "选股风格": payload["strategy"]["label"],
        "大盘": {"市场温度": payload["market"]["regime"]["label"], "依据": payload["market"]["regime"]["notes"],
               "指数": [{i["name"]: i["change_pct"]} for i in payload["market"]["indices"]],
               "涨跌家数": payload["market"].get("breadth"),
               "领涨行业": [b["name"] for b in payload["market"]["sectors_up"]]},
        "精选股票": [{"名称": p["name"], "行业": p["industry"], "最终分": p["score"], "结论": p["dashboard"]["one_sentence"],
                  "持有计划": {"目标涨幅%": p["dashboard"]["plan"]["target_pct"], "止损%": p["dashboard"]["plan"]["stop_pct"],
                           "持有": p["dashboard"]["plan"]["hold_label"]},
                  "检查清单": {c["label"]: c["status"] for c in p["dashboard"]["checklist"]},
                  "风险": p["dashboard"]["risks"][:3]} for p in payload["stocks"]["picks"]],
        "ETF": {"入选": [e["name"] for e in payload["etfs"]["picks"]], "说明": payload["etfs"]["note"]},
        "基金": [{g["label"]: [f["name"] for f in g["picks"]]} for g in payload["funds"]["groups"]],
    }
    try:
        quick, _ = config.llm_configs(s)
        text = make_llm(quick).complete(COMMENT_SYSTEM, json.dumps(brief, ensure_ascii=False))
    except LLMError as exc:
        return None, str(exc)
    except Exception as exc:                       # 网络等异常：点评可有可无，不能拖垮整次运行
        return None, f"{type(exc).__name__}: {exc}"
    return strip_think(text).strip() or None, ""


# ── 一次完整运行 ──────────────────────────────────────────────────

def as_of_label(as_of: str, now: datetime, intraday: bool) -> str:
    """数据日期说人话。工作日里拿到的不是今天的数据，要直接告诉用户。"""
    if intraday:
        return "上一个交易日收盘（今天还没收盘，收盘后会更新）"
    if as_of == now.date().isoformat():
        return "今天收盘"
    if now.weekday() >= 5 or (now.hour, now.minute) < (9, 15):
        return "最近一个交易日收盘"
    return "不是今天的数据：今天休市，或者数据源还没更新到今天"


def run(router, cache, store, strategy: str | None = None, stock_count: int = 5, use_llm: bool = True,
        on_progress=None, skip_if_exists: bool = False) -> dict | None:
    """返回保存好的结果。skip_if_exists=True 且这个交易日已有同风格结果时返回 None（自动任务用）。"""
    t0 = time.time()
    key, strat = strategies.get(strategy)
    stock_count = max(3, min(10, int(stock_count or 5)))
    rf = config.load().risk_free_rate / 100

    def progress(stage: str, message: str, percent: float):
        if on_progress:
            on_progress(stage=stage, message=message, percent=round(percent))

    progress("大盘", "读取全市场行情……", 2)
    now = beijing_now()
    bench_all, _ = router.series(symbols.CSI300, 800)
    intraday = session_intraday(now, bench_all)
    partial = now.date().isoformat() if intraday else None     # 今天还没走完的那根 K 线，一律不用
    bench = drop_partial(bench_all, partial)
    as_of = bench[-1].date
    if skip_if_exists and store.daily_exists(as_of, key):
        return None
    if intraday:
        existing = store.find_daily(as_of, key)
        if existing:
            # 上一个交易日的结果已经有了（收盘后那份用的是完整数据，更准），盘中再算只会更粗糙
            progress("完成", f"{as_of} 收盘后的精选已经有了，今天的会在收盘后生成", 100)
            existing["reused"] = True
            return existing
    rows, snap_source, warnings, basis = close_snapshot(cache, as_of, intraday, now)
    boards = []
    if not intraday:                                           # 盘中的行业涨跌是今天的半场数据，不展示
        try:
            boards = universe.industry_boards(cache)
        except SourceError as exc:
            warnings.append(f"行业板块取不到：{exc}")
    market = mkt.overview(router, rows if basis != "derived" else [], boards, bench, partial)
    warnings += market.pop("warnings")

    progress("选股", "按条件过滤全市场……", 8)
    stocks = pick_stocks(router, rows, strat, stock_count, bench, rf, progress,
                         derived=basis == "derived", partial=partial, source=snap_source)
    warnings += stocks.pop("warnings")
    etfs = pick_etfs(router, progress, bench, partial=partial)
    warnings += etfs.pop("warnings")
    funds = pick_funds(router, cache, rf, progress)
    warnings += funds.pop("warnings")

    payload = {
        "as_of": as_of, "as_of_label": as_of_label(as_of, now, intraday),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"), "intraday": intraday, "basis": basis,
        "strategy": {"key": key, "label": strat["label"], "desc": strat["desc"]},
        "market": market, "stocks": stocks, "etfs": etfs, "funds": funds,
        "sources": {"全市场快照": snap_source}, "warnings": warnings, "commentary": None, "disclaimer": DISCLAIMER,
    }
    if use_llm:
        progress("点评", "大模型撰写今日点评……", 92)
        text, err = commentary(payload)
        payload["commentary"] = text
        if err and config.llm_ready(config.load())[0]:
            warnings.append(f"大模型点评没有生成：{err}")
    payload["elapsed"] = round(time.time() - t0, 1)
    progress("保存", "保存结果", 99)
    payload["id"] = store.save_daily(payload)
    return payload


def start_background(router, cache, store, **kw) -> bool:
    """后台跑一次。已经在跑时返回 False。"""
    if not _run_lock.acquire(blocking=False):
        return False
    STATUS.update(running=True, stage="准备", message="开始生成每日精选", percent=0, error="",
                  started_at=beijing_now().strftime("%Y-%m-%d %H:%M:%S"), finished_at="", run_id="")

    def target():
        try:
            result = run(router, cache, store, on_progress=STATUS.update, **kw)
            if result is None:
                msg = "这个交易日已经生成过了"
            elif result.get("reused"):
                msg = f"今天还没收盘，{result['as_of']} 收盘后的精选已经有了；今天的会在收盘后生成"
            else:
                msg = "已完成"
            STATUS.update(stage="完成", message=msg, percent=100, run_id=(result or {}).get("id", ""))
        except Exception as exc:
            log.exception("每日精选生成失败")
            STATUS.update(stage="失败", error=str(exc) or type(exc).__name__)
        finally:
            STATUS.update(running=False, finished_at=beijing_now().strftime("%Y-%m-%d %H:%M:%S"))
            _run_lock.release()

    threading.Thread(target=target, daemon=True, name="daily-run").start()
    return True


# ── 收盘后自动生成 ────────────────────────────────────────────────

AUTO_AFTER = (15, 45)        # 北京时间，收盘后数据基本更新完
_attempts: dict[str, list[float]] = {}


def auto_due(now: datetime, latest: dict | None) -> bool:
    if now.weekday() >= 5 or (now.hour, now.minute) < AUTO_AFTER:
        return False
    if latest and latest.get("created_at", "")[:10] == now.date().isoformat():
        return False
    tries = _attempts.get(now.date().isoformat(), [])
    return len(tries) < 3 and (not tries or time.time() - tries[-1] > 1800)


def auto_tick(router, cache, store) -> bool:
    s = config.load()
    if not s.daily_auto or is_running():
        return False
    now = beijing_now()
    if not auto_due(now, store.latest_daily(s.daily_strategy)):
        return False
    _attempts.setdefault(now.date().isoformat(), []).append(time.time())
    return start_background(router, cache, store, strategy=s.daily_strategy, stock_count=s.daily_stock_count,
                            use_llm=s.daily_llm, skip_if_exists=True)


def auto_loop(router, cache, store, stop: threading.Event, first_delay: float = 60, interval: float = 600) -> None:
    wait = first_delay
    while not stop.wait(wait):
        wait = interval
        try:
            auto_tick(router, cache, store)
        except Exception:
            log.exception("每日精选自动任务出错")
