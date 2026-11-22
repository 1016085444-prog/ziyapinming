"""每日精选的整次运行（替身行情）、收盘口径、历史表现和接口。不联网。"""

import contextlib
import random
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import helpers
from helpers import day_bars, fund_md, line_bars, price_path, trading_days, walk

import app as A  # noqa: E402
from daily import market as M
from daily import mid, short, track
from daily import runner as R
from daily import text as T
from fastapi.testclient import TestClient
from market.cache import Cache
from market.models import Bar
from store import Store

LOCAL = ("127.0.0.1", 50001)
END = date(2026, 10, 30)
CLOSE_TIME = datetime(2026, 10, 30, 16, 0, tzinfo=R.BJ)       # 替身行情的最后一天，收盘后


def stock_row(code="600001", name="样本股", **kw):
    row = {"code": code, "market": "SH", "name": name, "price": 20.0, "change_pct": 1.0, "amount": 5e8,
           "turnover": 3.0, "volume_ratio": 1.2, "pe": 18.0, "pb": 2.7, "total_mv": 3e10, "float_mv": 2e10}
    row.update(kw)
    return row


def universe_rows(n=120, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        code = f"{600000 + i:06d}" if i % 2 else f"{1 + i:06d}"
        pe = rnd.uniform(6, 45)
        rows.append(stock_row(code, f"股票{i}", market="SH" if i % 2 else "SZ", price=rnd.uniform(4, 90),
                              change_pct=rnd.uniform(-3, 6), amount=rnd.uniform(1.2e8, 4e9), pe=pe,
                              pb=pe * rnd.uniform(0.08, 0.3), total_mv=rnd.uniform(8e9, 3e11)))
    rows += [stock_row("600999", "*ST退市"), stock_row("301999", "N新股"), stock_row("600998", "小票", amount=1e6)]
    return rows


ROWS = universe_rows()
INDUSTRY = {r["code"]: f"行业{k % 12}" for k, r in enumerate(ROWS[:120])}


def fake_reports(cache, today):
    return {c: {"period": "2026-09-30", "label": "2026年三季报", "notice": "2026-10-28", "yoy": 0.05 + (int(c) % 7) * 0.05,
                "profit": 1e9, "eps": 1.0, "industry": ind} for c, ind in INDUSTRY.items()}


def fake_roes(cache, today):
    return {c: ([12.0 + int(c) % 5, 11.0, 10.0] if int(c) % 4 else [6.0, 9.0, 10.0]) for c in INDUSTRY}


def fake_kline(symbol, days=640):
    """股票池的日线（腾讯等比复权的替身）：固定种子，带成交额、换手率和分红。"""
    seed = int(symbol[2:]) % 97 + 1
    rnd = random.Random(seed)
    closes = price_path(days, seed, start=8 + seed % 30, drift=0.0006 if seed % 3 else -0.0004, vol=0.018)
    bars = day_bars(closes, amount=rnd.uniform(1.5e8, 6e8), turnover=rnd.uniform(0.8, 4.0), end=END)
    return bars, {"div12": round(closes[-1] * 0.03, 3) if seed % 2 else 0.0, "div_prev": 0.2}


class FakeRouter:
    """替身数据源：指数、ETF 是固定种子的随机行情，基金是长长的净值序列。"""

    def series(self, inst, days=800):
        if inst.market == "OF":
            return self.fund(inst)[1], "测试"
        if inst.key == "SH:000300":
            return walk(800, 3800, 0.0004, 0.01, seed=99), "测试"
        seed = int(inst.code) % 97 + 1
        return walk(min(days, 800), 20, 0.0012 if seed % 2 else 0.0, 0.013, seed=seed), "测试"

    def fund(self, inst):
        closes = [b.adj_close for b in walk(3200, 1.0, 0.0003, 0.012, seed=int(inst.code) % 50 + 1, nav=True)]
        days = trading_days(len(closes))
        return fund_md().fund, [Bar(d, c, c, c, c, adj=c) for d, c in zip(days, closes)], []


INDEX_FUNDS = {"zs": ["易方达沪深300ETF联接A", "南方中证500ETF联接A", "易方达创业板ETF联接A", "大成中证红利指数A",
                      "华夏恒生ETF联接A", "富国沪深300指数增强A"],
               "qdii": ["广发纳斯达克100ETF联接人民币(QDII)A", "博时标普500ETF联接A"]}


def fake_fund_rank(cache, ft):
    rnd = random.Random(len(ft))
    names = INDEX_FUNDS.get(ft) or [f"{ft}基金{i}" for i in range(12)]
    return [{"code": f"{100000 + i + 1000 * len(ft):06d}", "name": name, "type": "", "ft": ft, "nav": 1.5,
             "nav_date": date.today().isoformat(), "inception": "2012-01-01", "fee": "0.12%", "m6": rnd.uniform(-5, 10),
             "y1": rnd.uniform(-10, 30), "y2": rnd.uniform(-10, 40), "y3": rnd.uniform(-10, 60), "ytd": 1.0}
            for i, name in enumerate(names)]


def fake_quarters(cache, today, latest):
    """单季利润：一半的股票最新一季比去年同季多赚，另一半少赚。"""
    return {c: {"period": r.get("period") or "2026-09-30", "label": r.get("label") or "2026年三季报", "notice": r.get("notice") or "2026-10-28",
                "sq": 1.5e8 if int(c) % 2 else 0.8e8, "sq_ly": 1.0e8} for c, r in latest.items()}


@contextlib.contextmanager
def offline(now=CLOSE_TIME, kline=fake_kline):
    """整次运行要用到的外部数据，全部换成替身。"""
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(R.universe, "a_share_snapshot", return_value=([dict(r) for r in ROWS], "测试快照", [])))
        stack.enter_context(mock.patch.object(R.universe, "latest_reports", side_effect=fake_reports))
        stack.enter_context(mock.patch.object(R.universe, "annual_roes", side_effect=fake_roes))
        stack.enter_context(mock.patch.object(R.universe, "quarter_profits", side_effect=fake_quarters))
        stack.enter_context(mock.patch.object(R.universe, "report_period", side_effect=AssertionError("测试里不该联网取财报")))
        stack.enter_context(mock.patch.object(R.universe, "fund_rank", side_effect=fake_fund_rank))
        stack.enter_context(mock.patch.object(R.tencent, "kline_true_ex", side_effect=kline))
        stack.enter_context(mock.patch.object(R.temperature, "MIN_STOCKS", 50))
        stack.enter_context(mock.patch.object(R.config, "llm_ready", return_value=(False, "尚未设置 API Key")))
        stack.enter_context(mock.patch.object(R, "beijing_now", return_value=now))
        yield


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.store, self.cache, self.router = Store(None), Cache(None), FakeRouter()
        self.addCleanup(self.store.close)
        self.addCleanup(self.cache.close)

    def run_once(self, now=CLOSE_TIME, kline=fake_kline, **kw):
        events = []
        kw.setdefault("pool_path", None)
        with offline(now, kline):
            payload = R.run(self.router, self.cache, self.store, on_progress=lambda **e: events.append(e), **kw)
        return payload, events

    def test_full_run(self):
        payload, events = self.run_once(stock_count=5)
        self.assertEqual(events[-1]["stage"], "保存")
        self.assertEqual([e["percent"] for e in events], sorted(e["percent"] for e in events), "进度只增不减")
        self.assertEqual((payload["version"], payload["as_of"], payload["basis"]), (3, "2026-10-30", "live"))
        self.assertEqual(list(payload["boards"]), ["short", "mid", "long", "dca"])
        self.assertEqual((payload["pool"]["wanted"], payload["pool"]["loaded"]), (120, 120))
        t = payload["temperature"]
        self.assertIsNone(t["stale"])
        self.assertTrue(0 <= t["value"] <= 100)
        self.assertEqual(payload["gauge"]["temp"]["value"], t["value"], "大盘预估分用市场温度把关")
        self.assertFalse(any("生成失败" in w or "没有算出来" in w for w in payload["warnings"]), payload["warnings"])
        for key, board in payload["boards"].items():
            for field in ("title", "name", "horizon", "idea", "how", "checkup", "picks", "funnel"):
                self.assertIn(field, board, key)
            self.assertNotIn("warnings", board)
            for p in board["picks"]:
                for field in ("key", "code", "name", "kind", "score", "headline", "evidence", "plan", "risks"):
                    self.assertIn(field, p, key)
                for field in ("horizon", "entry", "rules", "expected", "position"):
                    self.assertIn(field, p["plan"], key)
                self.assertTrue(p["plan"]["expected"]["text"])
        boards = payload["boards"]
        self.assertEqual(boards["short"]["name"], short.NAME)
        self.assertIn("gauge", boards["short"])
        self.assertIn(boards["short"]["stance"]["key"], ("go", "light", "wait", "avoid"))
        self.assertIn("timing", boards["mid"])
        mid_board = boards["mid"]
        self.assertTrue(mid_board["picks"], mid_board["funnel"])
        self.assertTrue(all(p.get("badge") for p in mid_board["picks"]), "中期卡片显示入选理由，不显示排序分")
        self.assertFalse([w for w in payload["warnings"] if "单季利润" in w or "去年同期" in w])
        self.assertIn("tier", boards["short"]["gauge"])
        self.assertTrue(boards["short"]["gauge"]["tier_table"])
        long_board = boards["long"]
        self.assertTrue(long_board["picks"], long_board["funnel"])
        self.assertIn(long_board["stance"]["key"], ("buy", "hold", "pause", "sell"))
        self.assertTrue(long_board["industry"]["count"] >= 10)
        self.assertTrue(long_board["funds"]["picks"], "不想选股的：指数基金")
        self.assertGreater(len(boards["dca"]["ranking"]), 4)
        self.assertNotIn("增强", "".join(r["name"] for r in boards["dca"]["ranking"]))
        self.assertIsNone(payload["commentary"], "没配大模型时不点评，也不报错")

        self.assertEqual(self.store.latest_daily()["id"], payload["id"])
        with offline():
            self.assertIsNone(R.run(self.router, self.cache, self.store, skip_if_exists=True, pool_path=None), "自动任务：同一交易日不重复生成")
        again, _ = self.run_once()
        self.assertEqual(len(self.store.list_daily()), 1, "同一交易日只留最新")
        self.assertEqual(self.store.list_daily()[0]["id"], again["id"])
        self.assertEqual(self.store.list_daily()[0]["methods"]["mid"], mid.NAME)

        md = T.to_markdown(payload)
        for part in ("# 每日精选", "## 大盘", "## 市场温度", "## 短期 · 看天出手", "## 中期 · 冷门蓄势", "## 长期 · 低温买入",
                     "## 定投 · 看温度定投", "方法体检", "预期收益", "什么时候卖", "### 行业风向", "| 指数 | 基金 | 方法"):
            self.assertIn(part, md)
        lb = boards["long"]
        self.assertGreater(len(lb["picks"]), 1)
        self.assertIsNotNone(T.shared_expected(lb["picks"]), "长期的预期是整个名单的统计，每只都一样")
        self.assertEqual(md.count(lb["picks"][0]["plan"]["expected"]["text"]), 1, "一样的预期收益只写一次")

        perf = track.performance(self.store, self.router)
        self.assertEqual(len(perf["runs"]), 1)
        self.assertEqual(perf["boards"]["mid"]["horizons"], [20, 120])

    def test_following_previous_picks(self):
        first, _ = self.run_once()
        earlier = dict(first, as_of="2026-10-20", created_at="2026-10-20 16:00:00")
        some = [p for p in first["boards"]["long"]["picks"][:3]]       # 拿几只池子里的股票当作「以前入选的」
        earlier["boards"] = {k: dict(b) for k, b in first["boards"].items()}
        outside = {"key": "SH:600998", "code": "600998", "name": "小票"}       # 成交太少、不在今天的股票池里
        earlier["boards"]["mid"]["picks"] = some + [outside]
        earlier["boards"]["short"]["picks"] = some[:1]
        self.store.save_daily(earlier)
        payload, _ = self.run_once()
        got = payload["boards"]["mid"]["following"]
        self.assertEqual({x["code"] for x in got["items"]}, {p["code"] for p in some} | {"600998"})
        self.assertNotEqual({x["code"]: x for x in got["items"]}["600998"]["status"], "unknown", "掉出池子的单独取了日线接着跟踪")
        self.assertTrue(all(x["picked"] == "2026-10-20" for x in got["items"]))
        self.assertTrue(all(x["status"] in ("hold", "sell", "done") for x in got["items"]))
        self.assertIn("following", payload["boards"]["short"])
        self.assertIn("之前入选的，现在该怎么办", T.to_markdown(payload))

    def test_reuses_downloaded_pool_on_rerun(self):
        path = Path(tempfile.mkdtemp()) / "pool.bin"
        self.run_once(pool_path=path)

        def boom(symbol, days=640):
            raise AssertionError("不该再下载")
        payload, _ = self.run_once(pool_path=path, kline=boom)
        self.assertTrue(payload["pool"]["cached"], "同一个交易日重新生成，不再重新下载几千只股票的日线")
        self.assertEqual(payload["pool"]["failed"], 0)

    def test_before_close_uses_previous_close(self):
        def kline(symbol, days=640):
            bars, div = fake_kline(symbol, days)
            return bars[1:] + day_bars([bars[-1].close], end=date(2026, 11, 2)), div
        bench = walk(800, 3800, 0.0004, 0.01, seed=99) + line_bars([3900.0], end=date(2026, 11, 2))
        with mock.patch.object(self.router, "series", side_effect=lambda inst, days=800: (bench, "测试") if inst.key == "SH:000300"
                               else FakeRouter.series(self.router, inst, days)):
            payload, _ = self.run_once(now=datetime(2026, 11, 2, 10, 0, tzinfo=R.BJ), kline=kline)
            self.assertTrue(payload["intraday"])
            self.assertEqual((payload["basis"], payload["as_of"]), ("derived", "2026-10-30"))
            self.assertIn("上一个交易日", payload["as_of_label"])
            self.assertIsNone(payload["market"]["breadth"], "倒推的数据不算涨跌家数")
            self.assertTrue(any("还没收盘" in w for w in payload["warnings"]))
            again, _ = self.run_once(now=datetime(2026, 11, 2, 10, 30, tzinfo=R.BJ), kline=kline)
            self.assertEqual(again["id"], payload["id"], "盘中再点生成：上一交易日已有结果就直接用")
            self.assertTrue(again["reused"])

    def test_commentary_with_llm(self):
        llm = helpers.FakeLLM("q")
        seen = {}

        def complete(system, user, **kw):
            seen["user"] = user
            return "<think>草稿</think>大盘震荡，仅供研究参考，不构成投资建议。"

        llm.complete = complete
        with offline(), mock.patch.object(R.config, "llm_ready", return_value=(True, "")), mock.patch.object(R, "make_llm", return_value=llm):
            payload = R.run(self.router, self.cache, self.store, pool_path=None)
        self.assertEqual(payload["commentary"], "大盘震荡，仅供研究参考，不构成投资建议。")
        for title in ("短期", "中期", "长期", "定投", "历史检验", "市场温度"):
            self.assertIn(title, seen["user"])

    def test_pool_failures_are_reported_not_fatal(self):
        def flaky(symbol, days=640):
            if symbol.startswith("sh"):
                raise R.SourceError("限流")
            return fake_kline(symbol, days)
        with mock.patch.object(self.router, "series", side_effect=lambda inst, days=800: (
                (walk(800, 3800, 0.0004, 0.01, seed=99), "测试") if inst.key == "SH:000300" else
                (_ for _ in ()).throw(R.SourceError("限流")) if inst.kind == "stock" else FakeRouter.series(self.router, inst, days))):
            payload, _ = self.run_once(kline=flaky)
        self.assertEqual(payload["pool"]["failed"], 60)
        self.assertTrue(any("日线没取到" in w for w in payload["warnings"]))

    def test_one_board_failing_does_not_kill_the_run(self):
        with mock.patch.object(R.short, "select", side_effect=ZeroDivisionError("坏数据")), \
                mock.patch.object(R.longterm, "index_funds", side_effect=R.SourceError("基金接口挂了")), \
                self.assertLogs("touyan.daily", level="ERROR"):
            payload, _ = self.run_once()
        short_board = payload["boards"]["short"]
        self.assertEqual((short_board["picks"], short_board["title"]), ([], "短期"))
        self.assertIn("没有生成出来", short_board["checkup"]["verdict"])
        self.assertTrue(any("短期板块生成失败" in w and "ZeroDivisionError" in w for w in payload["warnings"]))
        self.assertTrue(any("指数基金部分生成失败" in w for w in payload["warnings"]))
        self.assertGreater(len(payload["boards"]["dca"]["ranking"]), 0, "其他板块不受影响")
        self.assertIn("## 短期", T.to_markdown(payload))

    def test_quarter_failure_is_a_warning(self):
        payload, _ = self.run_once_with(quarter_error=True)
        self.assertTrue(any("去年同期的财报摘要取不到" in w for w in payload["warnings"]))
        mid_board = payload["boards"]["mid"]
        self.assertTrue(mid_board["picks"], "取不到单季利润也照样选")
        self.assertTrue(any("单季利润没取到" in w for w in payload["warnings"]), "板块自己的提示也汇总到页面底部")

    def run_once_with(self, quarter_error=False):
        events = []
        with offline(CLOSE_TIME, fake_kline):
            if quarter_error:
                with mock.patch.object(R.universe, "quarter_profits", side_effect=R.SourceError("限流")):
                    payload = R.run(self.router, self.cache, self.store, on_progress=lambda **e: events.append(e), pool_path=None)
            else:
                payload = R.run(self.router, self.cache, self.store, on_progress=lambda **e: events.append(e), pool_path=None)
        return payload, events

    def test_temperature_failure_is_a_warning(self):
        with mock.patch.object(R.temperature, "compute", side_effect=ValueError("历史文件坏了")), \
                self.assertLogs("touyan.daily", level="ERROR"):
            payload, _ = self.run_once()
        self.assertIsNone(payload["temperature"])
        self.assertTrue(any("市场温度没有算出来" in w for w in payload["warnings"]))
        self.assertEqual(payload["boards"]["long"]["stance"]["key"], "unknown")
        self.assertIn("## 长期", T.to_markdown(payload))


class MarketTest(unittest.TestCase):
    def test_breadth_and_regime(self):
        rows = [stock_row("600001", change_pct=10.0), stock_row("300001", change_pct=19.9),
                stock_row("600002", "ST甲", change_pct=-5.0), stock_row("600003", change_pct=0.0)]
        b = M.breadth(rows)
        self.assertEqual((b["up"], b["down"], b["flat"], b["limit_up"], b["limit_down"]), (2, 1, 1, 2, 1))
        strong = M.regime(line_bars([100 + i for i in range(80)]), {"up_ratio": 0.7})
        weak = M.regime(line_bars([200 - i for i in range(80)]), {"up_ratio": 0.2})
        self.assertEqual((strong["label"], weak["label"]), ("偏强", "偏弱"))


class CloseBasisTest(unittest.TestCase):
    """每日精选一律按完整交易日的收盘算：收盘前生成，就用上一个交易日的收盘。"""

    def test_session_intraday(self):
        bars = line_bars([10.0] * 30, end=date(2026, 11, 12))          # 最后一根是 11-12（周四）

        def thu(hh, mm):
            return datetime(2026, 11, 12, hh, mm, tzinfo=R.BJ)

        self.assertTrue(R.session_intraday(thu(10, 0), bars))
        self.assertFalse(R.session_intraday(thu(15, 30), bars))
        before = bars[:-1]
        self.assertTrue(R.session_intraday(thu(9, 20), before), "集合竞价时 K 线可能还没有今天这根")
        self.assertFalse(R.session_intraday(thu(8, 50), before), "开盘前，快照还是昨天的完整数据")
        self.assertFalse(R.session_intraday(thu(10, 30), before), "10:30 还没有今天的 K 线，多半是休市")
        self.assertFalse(R.session_intraday(datetime(2026, 11, 14, 10, 0, tzinfo=R.BJ), bars), "周末")
        self.assertEqual(R.drop_partial(bars, "2026-11-12")[-1].date, before[-1].date)
        self.assertEqual(len(R.drop_partial(bars, None)), 30)

    def test_to_prev_close(self):
        y = R.to_prev_close(stock_row(price=11.0, change_pct=10.0, pe=22.0, pb=2.2, total_mv=1.1e10))
        self.assertAlmostEqual(y["price"], 10.0)
        self.assertAlmostEqual(y["pe"], 20.0)
        self.assertAlmostEqual(y["total_mv"], 1e10)
        for k in ("amount", "turnover", "volume_ratio", "change_pct"):
            self.assertNotIn(k, y)

    def test_as_of_label(self):
        now = datetime(2026, 11, 11, 22, 0, tzinfo=R.BJ)
        self.assertEqual(R.as_of_label("2026-11-11", now, False), "今天收盘")
        self.assertIn("上一个交易日收盘", R.as_of_label("2026-11-10", now, True))
        self.assertIn("不是今天的数据", R.as_of_label("2026-11-10", now, False))
        self.assertEqual(R.as_of_label("2026-11-13", datetime(2026, 11, 14, 10, 0, tzinfo=R.BJ), False), "最近一个交易日收盘")

    def test_auto_due(self):
        R._attempts.clear()
        tue_after = datetime(2026, 11, 10, 16, 0, tzinfo=R.BJ)
        self.assertTrue(R.auto_due(tue_after, None))
        self.assertFalse(R.auto_due(datetime(2026, 11, 10, 14, 0, tzinfo=R.BJ), None), "收盘前不跑")
        self.assertFalse(R.auto_due(datetime(2026, 11, 8, 16, 0, tzinfo=R.BJ), None), "周末不跑")
        self.assertFalse(R.auto_due(tue_after, {"created_at": "2026-11-10 15:50:00"}), "今天已经生成过")
        R._attempts["2026-11-10"] = [0.0, 0.0, 0.0]
        self.assertFalse(R.auto_due(tue_after, None), "一天最多尝试 3 次")
        R._attempts.clear()


class TrackTest(unittest.TestCase):
    def test_entry_is_next_day(self):
        closes = [10.0] * 5 + [11.0, 11.5, 12.0, 12.0, 12.0, 12.0]
        opens = [10.0] * 5 + [10.5, 11.0, 11.5, 12.0, 12.0, 12.0]                  # 入选次日开盘 10.5
        bars = day_bars(closes, opens=opens)
        bench = day_bars([100.0] * 11)
        res = track.outcome(bars, bars[4].date, bench, (2, 4), False)
        self.assertEqual(res["entry_date"], bars[5].date)
        self.assertAlmostEqual(res["h1"], 12.0 / 10.5 - 1, msg="按次日开盘价买入，不是入选当天的收盘价")
        self.assertAlmostEqual(res["h1_excess"], 12.0 / 10.5 - 1)
        self.assertNotIn("h2", track.outcome(bars, bars[7].date, bench, (2, 4), False), "还没走到的时间点不算")
        self.assertIsNone(track.outcome(bars, bars[-1].date, bench, (2, 4), False), "入选后还没有新行情")
        nav = [Bar(b.date, 1.0, 1.0, 1.0, 1.0, adj=c) for b, c in zip(bars, closes)]
        self.assertAlmostEqual(track.outcome(nav, bars[4].date, bench, (2, 4), True)["h1"], 12.0 / 11.0 - 1,
                               msg="基金按次日净值买入")
        s = track.summarize([0.1, -0.05, 0.02], [0.05, -0.1, 0.0])
        self.assertEqual((s["n"], round(s["win_rate"], 3), round(s["beat_rate"], 3)), (3, 0.667, 0.333))


class DailyAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 用独立的内存库：其他测试模块结束时会关闭 app 自带的连接
        cls.store, cls.cache = Store(None), Cache(None)
        cls.patches = [mock.patch.object(A, "store", cls.store), mock.patch.object(A, "cache", cls.cache)]
        for p in cls.patches:
            p.start()
        cls.local = TestClient(A.app, client=LOCAL)
        cls.remote = TestClient(A.app)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.store.close()
        cls.cache.close()

    def test_endpoints(self):
        body = self.local.get("/api/daily").json()
        self.assertTrue(body["can_run"])
        self.assertEqual(set(body["settings"]), {"auto", "stock_count", "llm"})
        self.assertFalse(self.remote.get("/api/daily").json()["can_run"])
        self.assertEqual(self.remote.post("/api/daily/run", json={}).status_code, 403)
        self.assertEqual(self.local.post("/api/daily/run", json={"stock_count": 99}).status_code, 422)
        with mock.patch.object(A.daily_runner, "start_background", return_value=False):
            self.assertEqual(self.local.post("/api/daily/run", json={}).status_code, 409)
        with mock.patch.object(A.daily_runner, "start_background", return_value=True) as start:
            self.assertEqual(self.local.post("/api/daily/run", json={"stock_count": 6}).status_code, 200)
            self.assertEqual(start.call_args.kwargs["stock_count"], 6)
        self.assertEqual(self.local.get("/api/daily/runs/nope").status_code, 404)
        r = self.local.post("/api/settings", json={"daily_auto": False})
        self.assertEqual(r.json()["daily_auto"], False)
        self.local.post("/api/settings", json={"daily_auto": True})

    def test_saved_run_roundtrip(self):
        store, cache = Store(None), Cache(None)
        self.addCleanup(store.close)
        self.addCleanup(cache.close)
        with offline():
            payload = R.run(FakeRouter(), cache, store, use_llm=False, pool_path=None)
        rid = A.store.save_daily(payload)
        self.addCleanup(A.store.delete_daily, rid)
        self.assertEqual(self.local.get(f"/api/daily/runs/{rid}").json()["as_of"], payload["as_of"])
        md = self.local.get(f"/api/daily/runs/{rid}/markdown")
        self.assertEqual(md.status_code, 200)
        self.assertIn("## 定投", md.text)
        self.assertIn("## 市场温度", md.text)
        self.assertEqual(self.local.get("/api/daily").json()["latest"]["id"], rid)
        self.assertEqual(self.local.get("/api/daily/runs").json()["runs"][0]["id"], rid)
        self.assertEqual(self.remote.delete(f"/api/daily/runs/{rid}").status_code, 403)

    def test_old_format_runs_are_hidden(self):
        with A.store._lock:
            A.store._db.execute("INSERT INTO daily_runs VALUES (?,?,?,?,?,?)",
                                ("old1", "2026-11-11 16:00:00", "2026-11-11", "balanced", "{}", '{"as_of": "2026-11-11"}'))
            A.store._db.commit()
        self.addCleanup(A.store.delete_daily, "old1")
        self.assertNotIn("old1", [r["id"] for r in self.local.get("/api/daily/runs").json()["runs"]])
        self.assertIn("旧版本", self.local.get("/api/daily/runs/old1/markdown").text)
        self.assertIn("旧版本", T.to_markdown({"as_of": "2026-11-12", "version": 2, "boards": {"short": {}}}), "上一版的四个板块也按旧版本处理")


if __name__ == "__main__":
    unittest.main()
