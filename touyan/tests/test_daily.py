"""每日精选：筛选规则、技术特征、决策仪表盘、基金与 ETF 精选、整次运行、历史表现、接口。全部离线。"""

import math
import random
import unittest
from datetime import date, datetime
from unittest import mock

import helpers
from helpers import fund_md, line_bars, stock_md, walk

import app as A  # noqa: E402
from daily import funds as F
from daily import market as M
from daily import runner as R
from daily import screen as S
from daily import strategies
from daily import text as T
from daily import track
from fastapi.testclient import TestClient
from market.cache import Cache
from market.models import Quote
from store import Store

LOCAL = ("127.0.0.1", 50001)


def stock_row(code="600001", name="样本股", **kw):
    row = {"code": code, "market": "SH", "name": name, "price": 20.0, "change_pct": 1.0, "amount": 5e8,
           "turnover": 3.0, "volume_ratio": 1.2, "pe": 18.0, "pb": 2.0, "total_mv": 3e10, "float_mv": 2e10}
    row.update(kw)
    return row


def universe_rows(n=300, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        code = f"{600000 + i:06d}" if i % 2 else f"{1 + i:06d}"
        rows.append(stock_row(code, f"股票{i}", market="SH" if i % 2 else "SZ", price=rnd.uniform(4, 90),
                              change_pct=rnd.uniform(-3, 6), amount=rnd.uniform(1.2e8, 4e9),
                              turnover=rnd.uniform(0.5, 8), volume_ratio=rnd.uniform(0.6, 3),
                              pe=rnd.uniform(5, 70), pb=rnd.uniform(0.6, 7), total_mv=rnd.uniform(6e9, 3e11),
                              industry=f"行业{i % 7}"))
    rows += [stock_row("600999", "*ST退市"), stock_row("301999", "N新股"), stock_row("600998", "小票", amount=1e6)]
    return rows


class ScreenTest(unittest.TestCase):
    def test_hard_filter_reasons(self):
        rows = [stock_row(), stock_row("600002", "ST某某"), stock_row("600003", amount=1e6),
                stock_row("600004", pe=-3), stock_row("600005", change_pct=9.9), stock_row("600006", total_mv=1e9)]
        kept, dropped = S.hard_filter(rows, strategies.STRATEGIES["balanced"]["hard"])
        self.assertEqual([r["code"] for r in kept], ["600001"])
        for reason in ("ST / 退市风险", "成交额太小", "市盈率不在范围内（含亏损）", "当天涨得太多（不追高）", "市值偏小"):
            self.assertIn(reason, dropped)

    def test_pct_rank(self):
        self.assertEqual(S.pct_rank([1, 2, 3, 4]), [25, 50, 75, 100])
        self.assertEqual(S.pct_rank([1, 2, 3, 4], higher_better=False), [100, 75, 50, 25])
        self.assertEqual(S.pct_rank([5, 5, None]), [75, 75, 50])

    def test_value_strategy_prefers_cheap_liquid(self):
        cheap = stock_row("600010", "便宜", pe=8, pb=0.9, amount=3e9)
        dear = stock_row("600011", "贵", pe=60, pb=6, amount=1.5e8)
        ranked = S.prescreen([dear, cheap] + [stock_row(f"6001{i:02d}", pe=20 + i, pb=2) for i in range(10)],
                             strategies.STRATEGIES["value"])
        self.assertEqual(ranked[0]["code"], "600010")
        self.assertGreater(cheap["factors"]["value"], dear["factors"]["value"])
        self.assertLess(ranked.index(dear), len(ranked))

    def test_chasing_is_penalized(self):
        # 动量分在「追高起点」附近最高，再往上涨反而扣分；稳定性分随涨幅单调下降
        p = strategies.profile(strategies.STRATEGIES["balanced"])
        calm, strong, limit = stock_row(change_pct=1.0), stock_row(change_pct=5.5), stock_row(change_pct=9.5)
        S.rank_factors([calm, strong, limit])
        mom = [S.factor_scores(r, None, p)["momentum"] for r in (calm, strong, limit)]
        stab = [S.factor_scores(r, None, p)["stability"] for r in (calm, strong, limit)]
        self.assertGreater(mom[1], mom[2])
        self.assertGreater(mom[1], mom[0])
        self.assertEqual(stab, sorted(stab, reverse=True))

    def test_daily_features_uptrend(self):
        bars = line_bars([10 + i * 0.05 for i in range(200)])
        f = S.daily_features(bars)
        self.assertTrue(f["ma_aligned"] and f["ma_bullish"] and f["above_ma20"])
        self.assertAlmostEqual(f["bias_ma5"], (bars[-1].close / (sum(b.close for b in bars[-5:]) / 5) - 1) * 100)
        self.assertEqual(f["macd_status"], "bullish")
        self.assertGreaterEqual(f["signal_score"], 80)
        self.assertIsNone(S.daily_features(bars[:30]))
        down = S.daily_features(line_bars([30 - i * 0.05 for i in range(200)]))
        self.assertEqual(S.daily_reject(down, strategies.STRATEGIES["trend"]["daily"]), "均线不是多头排列")

    def test_risk_and_dashboard(self):
        bars = line_bars([10 + i * 0.02 for i in range(150)] + [13.0] * 4 + [14.17, 15.45])   # 连拉两天
        f = S.daily_features(bars)
        self.assertGreater(f["bias_ma5"], 5)
        row = stock_row(change_pct=7.0, price=bars[-1].close)
        pen, notes = S.risk_penalty(row, f, strategies.STRATEGIES["balanced"]["risk"])
        self.assertTrue(any("不追高" in n for n in notes))
        d = S.dashboard(row, f, None, 75, notes)
        self.assertEqual(d["signal"], "watch")
        self.assertIn("不追高", d["one_sentence"])
        bias_check = next(c for c in d["checklist"] if c["label"] == "乖离率")
        self.assertIn(bias_check["status"], ("warn", "fail"))

        # 带回调的上涨：有涨有跌，RSI 不会顶到 100
        calm = line_bars([10 + i * 0.03 + 0.25 * math.sin(i / 2.5) for i in range(200)])
        f2 = S.daily_features(calm)
        self.assertLess(f2["rsi14"], 70)
        close = calm[-1].close

        def rep(resist):
            return {"scores": {"composite": 65.0, "rating": {"label": "增持"}, "pros": [], "cons": []},
                    "levels": {"resistances": [{"price": x, "label": "波段高点（2026-09-01）"} for x in resist]
                               + [{"price": close * 1.012, "label": "布林上轨"}]}}

        d2 = S.dashboard(stock_row(price=close), f2, rep([close * 1.011, close * 1.15]), 72, [])
        self.assertEqual(d2["signal"], "buy", d2["checklist"])
        lv = d2["levels"]
        self.assertLess(lv["stop_loss"], lv["ideal_buy"])
        self.assertGreaterEqual(lv["reward_risk"], 1.5, "取第一个盈亏比够 1.5 的压力位作目标")
        # 买点就在收盘价、波动大（止损远），而压力位近在眼前：盈亏比不够，降级为等待
        wide = dict(f2, bias_ma5=0.0, ma5=close, atr=close * 0.03)
        cramped = S.dashboard(stock_row(price=close), wide, rep([close * 1.015]), 72, [])
        self.assertEqual(cramped["signal"], "watch")
        self.assertIn("盈亏比", cramped["one_sentence"])

    def test_diversify_one_per_industry(self):
        cands = [{"code": str(i), "industry": ind, "score": 90 - i} for i, ind in enumerate(["银行", "银行", "白酒", "", "银行"])]
        self.assertEqual([c["code"] for c in S.diversify(cands, 3)], ["0", "2", "3"])
        self.assertEqual(len(S.diversify(cands, 5)), 5, "凑不够时放宽行业限制")


class FundEtfTest(unittest.TestCase):
    def fund_rows(self):
        base = {"nav_date": "2026-11-07", "m6": 5.0, "y2": 10.0, "type": "混合型", "ft": "hh"}
        return [
            {**base, "code": "000001", "name": "甲成长混合A", "inception": "2015-01-01", "y1": 20.0, "y3": 40.0},
            {**base, "code": "000002", "name": "甲成长混合C", "inception": "2015-01-01", "y1": 19.5, "y3": 39.0},
            {**base, "code": "000003", "name": "乙一年持有期混合", "inception": "2015-01-01", "y1": 30.0, "y3": 50.0},
            {**base, "code": "000004", "name": "丙新基金", "inception": "2025-06-01", "y1": 50.0, "y3": None},
            {**base, "code": "000005", "name": "丁价值混合", "inception": "2012-01-01", "y1": 5.0, "y3": 15.0},
            {**base, "code": "000006", "name": "戊停更", "inception": "2012-01-01", "y1": 9.0, "y3": 9.0,
             "nav_date": "2026-01-01"},
        ]

    def test_prefilter_and_dedupe(self):
        kept = F.fund_prefilter(self.fund_rows(), date(2026, 11, 10))
        self.assertEqual({r["code"] for r in kept}, {"000001", "000002", "000005"})
        ranked = F.fund_perf_scores(kept)
        self.assertEqual([r["code"] for r in ranked], ["000001", "000005"], "A/C 份额只留一个")
        self.assertEqual(F.share_class_key("易方达蓝筹精选混合"), F.share_class_key("易方达蓝筹精选混合C"))

    def test_verdict(self):
        row = {"perf_score": 80.0, "y3": 40.0, "y3_rank_pct": 10, "ft": "hh"}
        rep = {"scores": {"composite": 60.0, "rating": {"code": "Overweight", "label": "增持"}},
               "metrics": {"3y": {"max_drawdown": -0.18, "sharpe": 1.1}},
               "fund": {"profile": {"scale": 30.0, "managers": [{"name": "张三", "tenure_years": 6.0}]}}}
        score, pros, cons = F.fund_verdict(row, rep)
        self.assertEqual(score, round(0.55 * 80 + 0.45 * 60, 1))
        self.assertTrue(any("张三" in p for p in pros))
        small = {**rep, "fund": {"profile": {"scale": 0.8, "managers": []}}}
        self.assertIsNone(F.fund_verdict(row, small)[0])
        rookie = {**rep, "fund": {"profile": {"scale": 30, "managers": [{"name": "李四", "tenure_years": 0.5}]}}}
        self.assertIsNone(F.fund_verdict(row, rookie)[0])
        self.assertIsNone(F.fund_verdict(row, None)[0])

    def test_etf_momentum(self):
        up = F.etf_momentum(line_bars([1 + i * 0.004 for i in range(200)]))
        down = F.etf_momentum(line_bars([2 - i * 0.004 for i in range(200)]))
        self.assertTrue(up["eligible"])
        self.assertFalse(down["eligible"])
        rows = [{"name": "涨", "momentum": up}, {"name": "跌", "momentum": down}]
        picks, note = F.etf_picks(rows, 3)
        self.assertEqual([p["name"] for p in picks], ["涨"])
        self.assertIn("国债", note)


class MarketTest(unittest.TestCase):
    def test_breadth_and_regime(self):
        rows = [stock_row("600001", change_pct=10.0), stock_row("300001", change_pct=19.9),
                stock_row("600002", "ST甲", change_pct=-5.0), stock_row("600003", change_pct=0.0)]
        b = M.breadth(rows)
        self.assertEqual((b["up"], b["down"], b["flat"], b["limit_up"], b["limit_down"]), (2, 1, 1, 2, 1))
        strong = M.regime(line_bars([100 + i for i in range(80)]), {"up_ratio": 0.7})
        weak = M.regime(line_bars([200 - i for i in range(80)]), {"up_ratio": 0.2})
        self.assertEqual((strong["label"], weak["label"]), ("偏强", "偏弱"))


class FakeRouter:
    def __init__(self):
        self.series_calls = 0

    def series(self, inst, days=800):
        self.series_calls += 1
        if inst.key == "SH:000300":
            return walk(600, 3800, 0.0004, 0.01, seed=99), "测试"
        seed = int(inst.code) % 97 + 1
        drift = 0.002 if seed % 2 else 0.0
        return walk(420, 20, drift, 0.012, seed=seed), "测试"

    def financials(self, inst):
        return stock_md().financials

    def quote(self, inst):
        return Quote(price=3000.0, change_pct=0.6), "测试"

    def load(self, inst, days=800, with_news=True):
        md = fund_md()
        md.instrument = inst
        return md


def fake_fund_rank(cache, ft):
    rnd = random.Random(len(ft))
    return [{"code": f"{100000 + i + 1000 * len(ft):06d}", "name": f"{ft}基金{i}", "type": "", "ft": ft,
             "nav_date": date.today().isoformat(), "inception": "2016-01-01", "m6": rnd.uniform(-5, 10),
             "y1": rnd.uniform(-10, 30), "y2": rnd.uniform(-10, 40), "y3": rnd.uniform(-10, 60), "ytd": 1.0}
            for i in range(20)]


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(None)
        self.cache = Cache(None)
        self.addCleanup(self.store.close)
        self.addCleanup(self.cache.close)
        self.router = FakeRouter()
        self.patches = [
            mock.patch.object(R.universe, "a_share_snapshot", return_value=(universe_rows(), "测试快照", [])),
            mock.patch.object(R.universe, "industry_boards", return_value=[
                {"name": f"板块{i}", "change_pct": 3 - i * 0.5, "code": f"BK{i}"} for i in range(12)]),
            mock.patch.object(R.universe, "fund_rank", side_effect=fake_fund_rank),
            mock.patch.object(R.eastmoney, "industries", return_value={}),             # 测试不联网
            # 固定在替身数据最后一天的收盘后，结果不随真实时钟变化（盘中逻辑另有测试）
            mock.patch.object(R, "beijing_now", return_value=datetime(2026, 10, 30, 16, 0, tzinfo=R.BJ)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_once(self, **kw):
        events = []
        payload = R.run(self.router, self.cache, self.store, on_progress=lambda **e: events.append(e), **kw)
        return payload, events

    def test_full_run(self):
        with mock.patch.object(R.config, "llm_ready", return_value=(False, "尚未设置 API Key")):
            payload, events = self.run_once(strategy="balanced", stock_count=4, use_llm=True)
        self.assertEqual(events[-1]["stage"], "保存")
        self.assertTrue(payload["id"])
        st = payload["stocks"]
        self.assertLessEqual(len(st["picks"]), 4)
        self.assertGreater(len(st["picks"]), 0)
        self.assertEqual(st["funnel"]["universe"], 303)
        self.assertIn("ST / 退市风险", st["funnel"]["dropped"])
        scores = [p["score"] for p in st["picks"]]
        industries = [p["industry"] for p in st["picks"] if p["industry"]]
        self.assertEqual(len(industries), len(set(industries)), "同一行业只留一只")
        for p in st["picks"]:
            self.assertIn(p["dashboard"]["signal"], ("buy", "watch"))
            self.assertTrue(p["dashboard"]["checklist"])
            self.assertNotIn("_rep", p)
            self.assertAlmostEqual(p["price"], p["features"]["ma5"] * (1 + p["features"]["bias_ma5"] / 100), delta=0.02,
                                   msg="显示的价格与仪表盘用的收盘价一致")
        self.assertLessEqual(scores, sorted(scores, reverse=True) or scores)
        self.assertEqual(len(payload["etfs"]["ranking"]), len(F.ETF_POOL))
        self.assertEqual([g["key"] for g in payload["funds"]["groups"]], [g[0] for g in F.FUND_PLAN])
        self.assertIsNone(payload["commentary"], "没配大模型时不点评，也不报错")
        self.assertFalse(any("点评" in w for w in payload["warnings"]))
        self.assertEqual(payload["market"]["regime"]["label"] in ("偏强", "震荡", "偏弱"), True)

        latest = self.store.latest_daily()
        self.assertEqual(latest["id"], payload["id"])
        self.assertTrue(self.store.daily_exists(payload["as_of"], "balanced"))
        self.assertIsNone(self.run_once(skip_if_exists=True)[0], "自动任务：同一交易日不重复生成")
        again, _ = self.run_once(strategy="balanced")
        self.assertEqual(len(self.store.list_daily()), 1, "同一交易日同一风格只留最新")
        self.assertEqual(self.store.latest_daily()["id"], again["id"])

        md = T.to_markdown(payload)
        for part in ("# 每日精选", "## 大盘", "## 精选股票", "## ETF 动量轮动", "## 场外基金", "参考价位"):
            self.assertIn(part, md)

        perf = track.performance(self.store, self.router)
        self.assertEqual(len(perf["runs"]), 1)
        self.assertIn("stocks", perf["groups"])

    def test_commentary_with_llm(self):
        llm = helpers.FakeLLM("q")
        llm.complete = lambda system, user, **kw: "<think>草稿</think>大盘震荡，仅供研究参考，不构成投资建议。"
        with mock.patch.object(R.config, "llm_ready", return_value=(True, "")), \
                mock.patch.object(R, "make_llm", return_value=llm):
            payload, _ = self.run_once(strategy="value", use_llm=True)
        self.assertEqual(payload["commentary"], "大盘震荡，仅供研究参考，不构成投资建议。")

    def test_trend_strategy_runs(self):
        payload, _ = self.run_once(strategy="trend")
        self.assertEqual(payload["strategy"]["key"], "trend")
        self.assertIn("daily_dropped", payload["stocks"]["funnel"])


class TrackTest(unittest.TestCase):
    def test_outcome_horizons(self):
        bars = line_bars([10.0] * 5 + [11.0] + [12.0] * 30)
        bench = line_bars([100.0] * 36)
        res = track.outcome(bars, bars[4].date, bench)
        self.assertAlmostEqual(res["t1"], 0.1)
        self.assertAlmostEqual(res["t5"], 0.2)
        self.assertAlmostEqual(res["t20_excess"], 0.2)
        self.assertNotIn("t20", track.outcome(bars, bars[-3].date, bench))
        s = track.summarize([0.1, -0.05, 0.02], [0.05, -0.1, 0.0])
        self.assertEqual((s["n"], round(s["win_rate"], 3), round(s["beat_rate"], 3)), (3, 0.667, 0.333))


class AutoTest(unittest.TestCase):
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
        r = self.local.get("/api/daily")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([s["key"] for s in body["strategies"]], list(strategies.STRATEGIES))
        self.assertTrue(body["can_run"])
        self.assertFalse(self.remote.get("/api/daily").json()["can_run"])
        self.assertEqual(self.remote.post("/api/daily/run", json={}).status_code, 403)
        self.assertEqual(self.local.post("/api/daily/run", json={"strategy": "nope"}).status_code, 400)
        with mock.patch.object(A.daily_runner, "start_background", return_value=False):
            self.assertEqual(self.local.post("/api/daily/run", json={}).status_code, 409)
        with mock.patch.object(A.daily_runner, "start_background", return_value=True) as start:
            self.assertEqual(self.local.post("/api/daily/run", json={"strategy": "trend", "stock_count": 6}).status_code, 200)
            self.assertEqual((start.call_args.kwargs["strategy"], start.call_args.kwargs["stock_count"]), ("trend", 6))
        self.assertEqual(self.local.get("/api/daily/runs/nope").status_code, 404)
        self.assertEqual(self.local.post("/api/settings", json={"daily_strategy": "nope"}).status_code, 400)
        r = self.local.post("/api/settings", json={"daily_strategy": "value", "daily_auto": False})
        self.assertEqual((r.json()["daily_strategy"], r.json()["daily_auto"]), ("value", False))
        self.local.post("/api/settings", json={"daily_strategy": "balanced", "daily_auto": True})

    def test_saved_run_roundtrip(self):
        store = Store(None)
        self.addCleanup(store.close)
        cache = Cache(None)
        self.addCleanup(cache.close)
        with mock.patch.object(R.universe, "a_share_snapshot", return_value=(universe_rows(80), "测试", [])), \
                mock.patch.object(R.universe, "industry_boards", return_value=[]), \
                mock.patch.object(R.universe, "fund_rank", side_effect=fake_fund_rank), \
                mock.patch.object(R.eastmoney, "industries", return_value={}), \
                mock.patch.object(R, "beijing_now", return_value=datetime(2026, 10, 30, 16, 0, tzinfo=R.BJ)):
            payload = R.run(FakeRouter(), cache, store, use_llm=False)
        rid = A.store.save_daily(payload)
        self.addCleanup(A.store.delete_daily, rid)
        self.assertEqual(self.local.get(f"/api/daily/runs/{rid}").json()["as_of"], payload["as_of"])
        md = self.local.get(f"/api/daily/runs/{rid}/markdown")
        self.assertEqual(md.status_code, 200)
        self.assertIn("每日精选", md.text)
        self.assertEqual(self.local.get("/api/daily").json()["latest"]["id"], rid)
        self.assertEqual(self.remote.delete(f"/api/daily/runs/{rid}").status_code, 403)


if __name__ == "__main__":
    unittest.main()


class DiversifyBucketTest(unittest.TestCase):
    def test_banks_without_industry_only_one(self):
        names = ["招商银行", "工商银行", "成都银行", "中信证券", "贵州茅台", "宁波银行", "长江电力"]
        cands = [{"code": str(i), "name": n, "industry": "", "score": 90 - i} for i, n in enumerate(names)]
        picked = [c["name"] for c in S.diversify(cands, 4)]
        self.assertEqual(picked, ["招商银行", "贵州茅台", "长江电力", "工商银行"],
                         "银行、券商同属金融：先各大类一只，凑不够才放宽")
        self.assertEqual(S.bucket_of("", "平安银行"), "金融")
        self.assertEqual(S.bucket_of("电网设备"), "新能源")
        self.assertEqual(S.bucket_of("电力行业"), "公用事业")
        self.assertEqual(S.bucket_of("航天航空"), "军工")
        self.assertEqual(S.bucket_of("航空机场"), "交通运输")
        self.assertEqual(S.bucket_of("化学制药"), "医药")
        self.assertEqual(S.bucket_of("工程机械"), "机械设备")
        self.assertEqual(S.bucket_of("旅游酒店"), "大消费")
        self.assertEqual(S.bucket_of("包装材料"), "包装材料", "认不出的大类就按行业本身")

    def test_fill_industries(self):
        from market import eastmoney
        payload = {"data": {"diff": [{"f12": "600036", "f14": "招商银行", "f100": "银行"},
                                     {"f12": "600519", "f14": "贵州茅台", "f100": "-"}]}}
        self.assertEqual(eastmoney.parse_industries(payload), {"600036": "银行"})
        rows = [stock_row("600036", "招商银行", industry=""), stock_row("000001", "平安银行", market="SZ", industry=""),
                stock_row("600519", "贵州茅台", industry="酿酒行业")]
        with mock.patch.object(R.eastmoney, "industries", return_value={"600036": "银行"}) as call:
            self.assertEqual(R.fill_industries(rows), "")
        self.assertEqual(call.call_args.args[0], ["1.600036", "0.000001"], "只查缺的，沪市 1. 深市 0.")
        self.assertEqual([r["industry"] for r in rows], ["银行", "银行", "酿酒行业"])
        rows = [stock_row("601998", "中信银行", industry="")]
        with mock.patch.object(R.eastmoney, "industries", side_effect=R.SourceError("断网")):
            self.assertIn("行业", R.fill_industries(rows))
        self.assertEqual(rows[0]["industry"], "银行")


class PlanTest(unittest.TestCase):
    def test_all_targets_on_steady_rise(self):
        bars = line_bars([10 * 1.005 ** k for k in range(200)])
        h = __import__("daily.backtest").backtest.plan_history(bars, 2.0, 3.0, 10)
        self.assertGreater(h["trades"], 10)
        self.assertEqual((h["target_hits"], h["win_rate"], h["avg_days"]), (h["trades"], 1.0, 4.0))
        self.assertAlmostEqual(h["avg"], 0.02)

    def test_time_exit(self):
        from daily.backtest import plan_history
        h = plan_history(line_bars([10 * 1.001 ** k for k in range(200)]), 5.0, 3.0, 10)
        self.assertEqual(h["time_exits"], h["trades"])
        self.assertAlmostEqual(h["avg"], 1.001 ** 10 - 1, places=6)

    def test_breakeven_limits_loss(self):
        from daily.backtest import plan_history
        prices = [30 - k * 0.05 for k in range(60)]                       # 先跌：均线空头，没有买点
        prices += [prices[-1] * 1.003 ** k for k in range(1, 23)]          # 慢涨：出现买点，涨过 +2% 但没到 +5%
        prices += [prices[-1] * 0.98 ** k for k in range(1, 14)]           # 再连跌
        bars = line_bars(prices)
        plain = plan_history(bars, 5.0, 3.0, 30)
        guarded = plan_history(bars, 5.0, 3.0, 30, breakeven_pct=2.0)
        self.assertEqual((plain["trades"], plain["stop_hits"]), (1, 1))
        self.assertLess(plain["worst"], -0.03)
        self.assertEqual(guarded["stop_hits"], 1)
        self.assertGreater(guarded["worst"], -0.03, "涨过保本线后止损提到买入价，亏得比原止损少")
        self.assertEqual(plan_history(line_bars([30 - k * 0.05 for k in range(200)]), 5, 3, 10)["trades"], 0)

    def test_dashboard_plan(self):
        calm = line_bars([10 + i * 0.03 + 0.25 * math.sin(i / 2.5) for i in range(200)])
        f = S.daily_features(calm)
        close = calm[-1].close
        rep = {"scores": {"composite": 65.0, "rating": {"label": "增持"}, "pros": [], "cons": []},
               "levels": {"resistances": [{"price": close * 1.6, "label": "波段高点（2025-01-02）"}]}}
        d = S.dashboard(stock_row(price=close), f, rep, 72, [], {"min": 5, "max": 15, "label": "1–3 周"})
        plan = d["plan"]
        self.assertEqual(len(plan["rules"]), 4)
        self.assertLess(plan["target_pct"], 60, "15 天内够不着的前高要按波动幅度封顶")
        self.assertGreater(plan["target_pct"], 0)
        self.assertGreater(plan["stop_pct"], 0)
        self.assertAlmostEqual(plan["breakeven_pct"], round(plan["target_pct"] / 2, 1))


class HoldingStatsTest(unittest.TestCase):
    def test_rolling_stats(self):
        from daily.backtest import rolling_stats
        s = rolling_stats(walk(800, 1.0, 0.0008, 0.005, seed=2, nav=True), 250)
        self.assertEqual(s["windows"], 550)
        self.assertLessEqual(s["p10"], s["median"])
        self.assertLessEqual(s["median"], s["p90"])
        self.assertIsNone(rolling_stats(walk(200, 1.0, seed=2, nav=True), 250))

    def test_rotation_backtest(self):
        from daily.backtest import rotation_backtest
        n = 420
        series = {"A": line_bars([1 * 1.003 ** k for k in range(n)]), "B": line_bars([1 * 1.0015 ** k for k in range(n)]),
                  "C": line_bars([1.0] * n), "D": line_bars([2 * 0.998 ** k for k in range(n)])}
        bench = line_bars([3000 * 1.0005 ** k for k in range(n)])
        res = rotation_backtest(series, bench, top_n=2)
        self.assertGreater(res["total"], res["bench_total"])
        self.assertEqual(res["switches"], 0, "一直是 A、B 两只，不用换")
        self.assertGreater(res["max_drawdown"], -0.002, "一路上涨，几乎没有回撤")
        falling = {k: line_bars([2 * 0.998 ** i for i in range(n)]) for k in "ABC"}
        flat = rotation_backtest(falling, bench, top_n=2)
        self.assertAlmostEqual(flat["total"], 0.0, places=6, msg="一只都不合格、又没有防守品种时空仓")


class RunnerPlanTest(RunnerTest):
    def test_plans_and_labels(self):
        with mock.patch.object(R.config, "llm_ready", return_value=(False, "")):
            payload, _ = self.run_once(strategy="trend")
        self.assertTrue(payload["as_of_label"])
        for p in payload["stocks"]["picks"]:
            plan = p["dashboard"]["plan"]
            self.assertEqual((plan["hold_min"], plan["hold_max"]), (5, 15))
            self.assertIn("trades", plan["history"])
        self.assertIn("rules", payload["etfs"]["plan"])
        self.assertIsNotNone(payload["etfs"]["plan"]["history"])
        fund = next(f for g in payload["funds"]["groups"] for f in g["picks"])
        self.assertEqual(fund["plan"]["horizon_days"] in (125, 250), True)
        self.assertIsNotNone(fund["plan"]["history"])
        md = T.to_markdown(payload)
        for part in ("持有计划", "历史参照", "怎么拿"):
            self.assertIn(part, md)

    def test_as_of_label(self):
        now = datetime(2026, 11, 11, 22, 0, tzinfo=R.BJ)
        self.assertEqual(R.as_of_label("2026-11-11", now, False), "今天收盘")
        self.assertIn("上一个交易日收盘", R.as_of_label("2026-11-10", now, True), "盘中生成一律按上一个交易日收盘")
        self.assertIn("不是今天的数据", R.as_of_label("2026-11-10", now, False), "工作日晚上还拿到昨天的数据要明说")
        self.assertEqual(R.as_of_label("2026-11-13", datetime(2026, 11, 14, 10, 0, tzinfo=R.BJ), False), "最近一个交易日收盘")
        self.assertEqual(R.as_of_label("2026-11-10", datetime(2026, 11, 11, 8, 0, tzinfo=R.BJ), False), "最近一个交易日收盘")


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

    def test_missing_columns_and_recheck(self):
        hard = strategies.STRATEGIES["balanced"]["hard"]
        rows = [stock_row(f"6000{i:02d}", pe=None, amount=0.0) for i in range(20)]
        h, skipped = S.usable_hard(rows, hard)
        self.assertEqual(set(skipped), {"成交额", "市盈率"})
        self.assertEqual(len(S.hard_filter(rows, h)[0]), 20, "某列全空时跳过这条，不把全市场都刷掉")
        derived = [R.to_prev_close(stock_row())]
        h2, skipped2 = S.usable_hard(derived, hard)
        self.assertEqual(skipped2, [])
        self.assertEqual(len(S.hard_filter(derived, h2)[0]), 1, "倒推的行没有成交额和涨跌幅，初筛不查这两项")
        bars = line_bars([10.0] * 10 + [10.5])
        bars[-1].volume = 50000.0                                   # 5 万手 × 100 × 10.5 元 = 5250 万元
        r2, reason = S.recheck_with_bars(derived[0], bars, hard)
        self.assertAlmostEqual(r2["change_pct"], 5.0)
        self.assertEqual(reason, "成交额太小")


class IntradayRunTest(RunnerTest):
    def run_at(self, when, **kw):
        with mock.patch.object(R, "beijing_now", return_value=when), \
                mock.patch.object(R.config, "llm_ready", return_value=(False, "")):
            return self.run_once(**kw)[0]

    def test_before_close_uses_previous_close(self):
        payload = self.run_at(datetime(2026, 10, 30, 10, 0, tzinfo=R.BJ))   # 替身 K 线最后一根是 10-30
        self.assertTrue(payload["intraday"])
        self.assertEqual((payload["basis"], payload["as_of"]), ("derived", "2026-10-29"))
        self.assertIn("上一个交易日", payload["as_of_label"])
        self.assertIsNone(payload["market"]["breadth"], "倒推的数据不算涨跌家数")
        self.assertEqual(payload["market"]["sectors_up"], [])
        self.assertTrue(all(i["date"] == "2026-10-29" for i in payload["market"]["indices"]))
        self.assertGreater(len(payload["stocks"]["picks"]), 0)
        self.assertTrue(all(p["as_of"] == "2026-10-29" for p in payload["stocks"]["picks"]))
        self.assertTrue(all(e["as_of"] == "2026-10-29" for e in payload["etfs"]["ranking"]))
        self.assertTrue(any("还没收盘" in w for w in payload["warnings"]))
        again = self.run_at(datetime(2026, 10, 30, 14, 0, tzinfo=R.BJ))
        self.assertEqual(again["id"], payload["id"], "盘中再点生成：上一交易日已有结果就直接用，不重复计算")

    def test_close_snapshot_reused_next_morning(self):
        payload = self.run_at(datetime(2026, 10, 30, 16, 0, tzinfo=R.BJ))
        self.assertEqual((payload["basis"], payload["as_of"], payload["intraday"]), ("live", "2026-10-30", False))
        self.assertEqual(self.cache.get_stale(R.EOD_KEY)[0]["date"], "2026-10-30", "收盘后的完整数据存下来")
        self.cache.set(R.EOD_KEY, {"date": "2026-10-29", "rows": universe_rows(), "source": "测试"})
        payload = self.run_at(datetime(2026, 10, 30, 10, 0, tzinfo=R.BJ))
        self.assertEqual(payload["basis"], "eod", "盘中优先用上次收盘后存下的数据，不用倒推")
        self.assertIsNotNone(payload["market"]["breadth"])
        self.assertIn("收盘后存下", payload["stocks"]["funnel"]["source"])
