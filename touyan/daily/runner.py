"""每日精选的一次完整运行：大盘 → 核心池 → 短期 / 中期 / 长期 / 定投四个板块 →（可选）大模型点评 → 保存。

四个板块用四种不同的方法（见 short.py、mid.py、longterm.py、dca.py），各自先拿历史数据检验自己，
再给出今天的入选和每一只的持有计划。一次运行要下载几百只股票的日线，约 3–5 分钟；
同一个交易日里重新生成会直接用已经下载的数据。个别标的取不到会跳过并记在 warnings 里，不会让整次运行失败。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import config
from agents.llm import LLMError, make_llm, strip_think
from market import eastmoney, symbols, universe
from market.models import FinancialPeriod, Instrument
from market.net import SourceError
from quant import report as qr

from . import dca, longterm, mid, pool, short
from . import market as mkt
from .common import guess_industry

log = logging.getLogger("touyan.daily")
BJ = timezone(timedelta(hours=8))
BOARDS_KEY = "boards"
ORDER = ("short", "mid", "long", "dca")
DISCLAIMER = ("每日精选由公开数据和固定规则自动生成，用来缩小研究范围，不是买卖指令，也不构成投资建议。"
              "「预期收益」是历史统计或按财报的推算，不是承诺；每个板块都写明了方法在历史上的检验结果，请结合它和自己的判断使用。")


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


# ── 数据装配 ──────────────────────────────────────────────────────

def fill_industries(rows: list[dict]) -> str:
    """给缺行业的股票补上行业（一次批量请求）；取不到时按名字猜（银行、证券、保险）。返回提示或空串。"""
    missing = [r for r in rows if not r.get("industry")]
    if not missing:
        return ""
    note = ""
    try:
        found = eastmoney.industries([f"{1 if r['market'] == 'SH' else 0}.{r['code']}" for r in missing])
    except SourceError as exc:
        found, note = {}, f"股票所属行业取不到（{exc}），行业分散只能按名字粗略判断"
    for r in missing:
        r["industry"] = found.get(r["code"]) or guess_industry(r.get("name", ""))
    return note


def make_financials(router, cache):
    """返回 financials(rows) → {代码: 财报列表}。财报一个季度才变一次，存 3 天。"""
    def one(row):
        key = f"dailyfin:{row['market']}:{row['code']}"
        hit = cache.get(key, 3 * 86400)
        if hit is not None:
            return [FinancialPeriod(**d) for d in hit]
        inst = symbols.from_key(f"{row['market']}:{row['code']}", "stock", row.get("name", ""))
        periods = router.financials(inst)
        cache.set(key, [asdict(p) for p in periods])
        return periods

    def many(rows: list[dict]) -> dict[str, list]:
        out = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [(r["code"], ex.submit(one, r)) for r in rows]
            for code, fut in futures:
                try:
                    out[code] = fut.result()
                except Exception as exc:
                    log.info("财报没取到 %s：%s", code, exc)
        return out

    return many


def load_etfs(router, cache, as_of: str, partial: str | None) -> tuple[dict, dict, list[str]]:
    """ETF 池的日线（三年多，检验要用）。返回 ({代码: Series}, {代码: (key, 名称, 类别)}, 提示)。"""
    def one(item):
        code, name, _ = item
        key = ("SH:" if code[0] in "56" else "SZ:") + code
        return key, pool.load_bars(router, cache, key, name, "etf", as_of, partial, 800)

    series, meta, failed = {}, {}, []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [(item, ex.submit(one, item)) for item in mid.ETF_POOL]
        for (code, name, group), fut in futures:
            try:
                key, bars = fut.result()
            except Exception:
                failed.append(name)
                continue
            if bars and bars[-1].date == as_of and len(bars) >= pool.MIN_BARS and pool.clean(bars):
                series[code] = pool.Series(bars, code, key[:2], name, limit=0.10)
                meta[code] = (key, name, group)
            else:
                failed.append(name)
    warnings = [f"有 {len(failed)} 只 ETF 的行情没取到：{'、'.join(failed[:5])}"] if failed else []
    return series, meta, warnings


def pick_long_funds(router, cache, bench: list, rf: float, n: int = 3) -> tuple[dict, list[str]]:
    rows, warnings = [], []
    for ft in ("gp", "hh"):
        try:
            rows += universe.fund_rank(cache, ft)
        except SourceError as exc:
            warnings.append(f"{universe.FUND_TYPES[ft]}基金排行取不到：{exc}")
    ranked = longterm.fund_perf_scores(longterm.fund_prefilter(rows))[:9]

    def one(r):
        md = router.load(Instrument(r["code"], "OF", "fund", r["name"]), days=1200, with_news=False)
        return qr.build(md, rf, chart_bars=2), md.bars

    picks, rejected = [], []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [(r, ex.submit(one, r)) for r in ranked]
        for r, fut in futures:
            try:
                rep, nav = fut.result()
            except Exception as exc:
                rep, nav = None, []
                log.info("基金 %s 体检失败：%s", r["code"], exc)
            pick, why = longterm.fund_pick(r, rep, nav, bench)
            if pick is None:
                rejected.append({"code": r["code"], "name": r["name"], "reason": why})
            else:
                picks.append(pick)
    picks.sort(key=lambda p: -p["score"])
    return {"picks": picks[:n], "how": longterm.FUND_HOW, "screened": len(ranked), "rejected": rejected[:4]}, warnings


def pick_dca(router, cache, n: int = 5) -> tuple[dict, list[str]]:
    rows, warnings = [], []
    for ft in ("zs", "qdii"):
        try:
            rows += universe.fund_rank(cache, ft)
        except SourceError as exc:
            warnings.append(f"{universe.FUND_TYPES[ft]}基金排行取不到：{exc}")
    cands = dca.find_candidates(rows)
    if rows and not cands:
        warnings.append("基金排行里没有找到符合条件的指数基金（排行数据的格式可能变了），定投板块这次是空的")

    def one(r):
        return router.fund(Instrument(r["code"], "OF", "fund", r["name"]))[1]

    navs = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [(r, ex.submit(one, r)) for r in cands]
        for r, fut in futures:
            try:
                navs[r["code"]] = fut.result()
            except Exception as exc:
                log.info("基金 %s 净值没取到：%s", r["code"], exc)
    return dca.select(cands, lambda r: navs[r["code"]], n), warnings


# ── 大模型点评（可选） ────────────────────────────────────────────

COMMENT_SYSTEM = (
    "你是一名谨慎的投研助理。根据用户给的结构化数据写今日点评，400 字以内：先一句话说大盘环境，"
    "再按短期、中期、长期、定投四个板块各写两三句——这个板块的方法在历史检验里表现如何、今天选了什么、最该注意什么。"
    "只能引用数据里出现的数字和事实，不编造新闻、业绩或价格；方法检验结果不好的板块要直说；"
    "不使用「必涨」「稳赚」「强烈推荐」这类词；最后一句提醒：仅供研究参考，不构成投资建议。"
)


def commentary(payload: dict) -> tuple[str | None, str]:
    s = config.load()
    ready, reason = config.llm_ready(s)
    if not ready:
        return None, reason

    def brief(board: dict) -> dict:
        picks = list(board["picks"]) + (board.get("etfs") or {}).get("picks", []) + (board.get("funds") or {}).get("picks", [])
        return {"方法": board["name"], "持有": board["horizon"], "历史检验": board["checkup"].get("verdict", ""),
                "入选": [{"名称": p["name"], "一句话": p["headline"], "预期": p["plan"]["expected"].get("text", "")[:120]}
                       for p in picks[:6]]}

    data = {
        "日期": payload["as_of"],
        "大盘": {"市场温度": payload["market"]["regime"]["label"], "依据": payload["market"]["regime"]["notes"],
               "指数": [{i["name"]: i["change_pct"]} for i in payload["market"]["indices"]]},
        **{payload["boards"][k]["title"]: brief(payload["boards"][k]) for k in ORDER},
    }
    try:
        quick, _ = config.llm_configs(s)
        text = make_llm(quick).complete(COMMENT_SYSTEM, json.dumps(data, ensure_ascii=False))
    except LLMError as exc:
        return None, str(exc)
    except Exception as exc:                       # 网络等异常：点评可有可无，不能拖垮整次运行
        return None, f"{type(exc).__name__}: {exc}"
    return strip_think(text).strip() or None, ""


# ── 一次完整运行 ──────────────────────────────────────────────────

def empty_board(module, error: str) -> dict:
    return {"key": module.KEY, "title": module.TITLE, "name": module.NAME, "horizon": module.HORIZON,
            "idea": module.IDEA, "how": module.HOW, "picks": [], "funnel": {"pool": 0, "candidates": 0, "picked": 0, "reasons": {}},
            "checkup": {"level": "thin", "verdict": f"这个板块这次没有生成出来：{error}"}, "warnings": []}


def guarded(module, build, warnings: list[str]) -> dict:
    """一个板块出错不拖垮其他板块：记下原因，这个板块留空。"""
    try:
        return build()
    except Exception as exc:
        log.exception("%s板块生成失败", module.TITLE)
        warnings.append(f"{module.TITLE}板块生成失败（{type(exc).__name__}: {exc}），其他板块不受影响。把这句话发给开发者可以帮助定位问题")
        return empty_board(module, f"{type(exc).__name__}: {exc}")


def as_of_label(as_of: str, now: datetime, intraday: bool) -> str:
    """数据日期说人话。工作日里拿到的不是今天的数据，要直接告诉用户。"""
    if intraday:
        return "上一个交易日收盘：今天还没收盘，收盘后会更新"
    if as_of == now.date().isoformat():
        return "今天收盘"
    if now.weekday() >= 5 or (now.hour, now.minute) < (9, 15):
        return "最近一个交易日收盘"
    return "不是今天的数据：今天休市，或者数据源还没更新到今天"


def run(router, cache, store, stock_count: int = 5, use_llm: bool = True, on_progress=None,
        skip_if_exists: bool = False) -> dict | None:
    """返回保存好的结果。skip_if_exists=True 且这个交易日已经有结果时返回 None（自动任务用）。"""
    t0 = time.time()
    n = max(3, min(10, int(stock_count or 5)))
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
    if skip_if_exists and store.daily_exists(as_of, BOARDS_KEY):
        return None
    if intraday:
        existing = store.find_daily(as_of, BOARDS_KEY)
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
    regimes = pool.regime_by_date(bench)
    regime_now = regimes.get(as_of, "震荡")
    bench60 = mid.bench_returns(bench)
    rows_by_code = {r["code"]: r for r in rows}
    financials = make_financials(router, cache)

    pool_rows = pool.build_pool(rows)
    series, pool_info = pool.load_pool(
        router, cache, pool_rows, as_of, partial,
        progress=lambda i, total: progress("核心池", f"下载市值最大的 {total} 只股票的日线（{i}/{total}）", 4 + 41 * i / total))
    if pool_info["wanted"] and pool_info["failed"] > pool_info["wanted"] * 0.2:
        warnings.append(f"核心池里有 {pool_info['failed']} 只股票的日线没取到（数据源可能在限流），"
                        "短期和中期板块是在剩下的股票里选的，过一会儿重新生成可以补全")
    plist = list(series.values())

    progress("短期", "检验方法，找今天被错杀的股票", 47)
    b_short = guarded(short, lambda: short.select(series, rows_by_code, short.checkup(plist, regimes, regime_now),
                                                  regime_now, n, fill_industries), warnings)

    progress("中期", "检验方法，找悄悄走强的股票", 52)
    b_mid = guarded(mid, lambda: mid.select(series, rows_by_code, bench60, mid.checkup(plist, bench60, regimes, regime_now),
                                            n, financials, fill_industries), warnings)
    progress("中期", "下载 ETF 行情", 58)

    def etf_section():
        etf_series, etf_meta, etf_warn = load_etfs(router, cache, as_of, partial)
        warnings.extend(etf_warn)
        report = mid.checkup(list(etf_series.values()), bench60, regimes, regime_now, mid.ETF_RULE, "三年")
        return mid.select_etfs(etf_series, etf_meta, bench60, report)

    try:
        b_mid["etfs"] = etf_section()
    except Exception as exc:
        log.exception("ETF 小节生成失败")
        warnings.append(f"中期板块的 ETF 部分生成失败（{type(exc).__name__}: {exc}）")

    progress("长期", "读财报，估算长期回报", 66)

    def closes_of(row):
        s = series.get(row["code"])
        if s is not None:
            return s.c
        bars = pool.load_bars(router, cache, f"{row['market']}:{row['code']}", row.get("name", ""), "stock",
                              as_of, partial, pool.POOL_DAYS)
        return [b.close for b in bars]

    b_long = guarded(longterm, lambda: longterm.select(rows, n, financials, fill_industries, closes_of), warnings)
    progress("长期", "筛选长期持有的基金", 78)
    try:
        b_long["funds"], fund_warn = pick_long_funds(router, cache, bench, rf)
        warnings += fund_warn
    except Exception as exc:
        log.exception("长期基金小节生成失败")
        warnings.append(f"长期板块的基金部分生成失败（{type(exc).__name__}: {exc}）")

    progress("定投", "模拟指数基金的定投", 88)

    def dca_board():
        board, dca_warn = pick_dca(router, cache)
        warnings.extend(dca_warn)
        return board

    b_dca = guarded(dca, dca_board, warnings)

    result = {"short": b_short, "mid": b_mid, "long": b_long, "dca": b_dca}
    for b in result.values():
        warnings += b.pop("warnings", [])
    payload = {
        "version": 2, "as_of": as_of, "as_of_label": as_of_label(as_of, now, intraday),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"), "intraday": intraday, "basis": basis,
        "strategy": {"key": BOARDS_KEY, "label": "四个板块"},
        "market": market, "regime_bucket": regime_now, "boards": result, "order": list(ORDER),
        "pool": pool_info, "sources": {"全市场快照": snap_source},
        "warnings": list(dict.fromkeys(warnings)), "commentary": None, "disclaimer": DISCLAIMER,
    }
    if use_llm:
        progress("点评", "大模型撰写今日点评……", 95)
        text, err = commentary(payload)
        payload["commentary"] = text
        if err and config.llm_ready(config.load())[0]:
            payload["warnings"].append(f"大模型点评没有生成：{err}")
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
    if not auto_due(now, store.latest_daily()):
        return False
    _attempts.setdefault(now.date().isoformat(), []).append(time.time())
    return start_background(router, cache, store, stock_count=s.daily_stock_count, use_llm=s.daily_llm,
                            skip_if_exists=True)


def auto_loop(router, cache, store, stop: threading.Event, first_delay: float = 60, interval: float = 600) -> None:
    wait = first_delay
    while not stop.wait(wait):
        wait = interval
        try:
            auto_tick(router, cache, store)
        except Exception:
            log.exception("每日精选自动任务出错")
