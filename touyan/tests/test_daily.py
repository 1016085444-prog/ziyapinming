"""每日精选（四个板块）：共用的量法与模拟买卖、四种选法、整次运行、历史表现、接口。全部离线。"""

import math
import random
import statistics
import unittest
from datetime import date, datetime
from unittest import mock

import helpers
from helpers import fund_md, line_bars, trading_days, walk

import app as A  # noqa: E402
from daily import common, dca, longterm, mid, short, sim, track
from daily import market as M
from daily import pool as P
from daily import runner as R
from daily import text as T
from fastapi.testclient import TestClient
from market.cache import Cache
from market.models import Bar, FinancialPeriod
from store import Store

LOCAL = ("127.0.0.1", 50001)
CLOSE_TIME = datetime(2026, 10, 30, 16, 0, tzinfo=R.BJ)       # 替身行情的最后一天，收盘后


def bars_from(closes, opens=None, highs=None, lows=None, vols=None, end=None):
    """按给定的收盘价（可选开盘、最高、最低、成交量）造日线；没给开盘价就等于前收。"""
    days = trading_days(len(closes), end)
    out, prev = [], closes[0]
    for i, (d, c) in enumerate(zip(days, closes)):
        o = opens[i] if opens else prev
        h = highs[i] if highs else max(o, c)
        low = lows[i] if lows else min(o, c)
        out.append(Bar(d, o, h, low, c, vols[i] if vols else 1000.0))
        prev = c
    return out


def calm(n=200, seed=5, start=20.0, drift=0.0006):
    return [b.close for b in walk(n, start, drift, 0.01, seed=seed)]


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
                              pb=pe * rnd.uniform(0.08, 0.3), total_mv=rnd.uniform(8e9, 3e11), industry=f"行业{i % 9}"))
    rows += [stock_row("600999", "*ST退市"), stock_row("301999", "N新股"), stock_row("600998", "小票", amount=1e6)]
    return rows


def fin_periods(roe=16.0, growth=12.0, eps=2.0, bps=12.0, payout=0.4, ocf_ratio=1.1, debt=40.0, years=(2025, 2024, 2023),
                latest_growth=None):
    """三年年报 + 最新一期季报。每股净资产按「留存利润」逐年递增。"""
    out = [FinancialPeriod("2026-09-30", "2026三季报", 9e10, 10.0, 3e10, growth if latest_growth is None else latest_growth,
                           growth if latest_growth is None else latest_growth, roe * 0.75, 40.0, 20.0, debt, eps * 0.75,
                           bps + eps * 0.5, eps * 0.8, 1.5)]
    for k, y in enumerate(years):
        out.append(FinancialPeriod(f"{y}-12-31", f"{y}年报", 1e11, 10.0, 4e10, growth, growth, roe - k * 0.3, 40.0 + k, 20.0,
                                   debt, eps, bps - k * eps * (1 - payout), eps * ocf_ratio, 1.5))
    return out


# ── 共用的量法 ────────────────────────────────────────────────────

class SeriesTest(unittest.TestCase):
    def test_volatility_and_returns(self):
        closes = calm(200)
        s = P.Series(bars_from(closes))
        t = 199
        rets = [closes[i] / closes[i - 1] - 1 for i in range(t - 124, t - 4)]
        self.assertAlmostEqual(s.sigma(t), statistics.stdev(rets), places=10)
        self.assertAlmostEqual(s.ret(t, 5), closes[t] / closes[t - 5] - 1)
        self.assertIsNone(s.sigma(100), "数据不够长时不给波动率")

    def test_drop_is_split_into_intraday_and_overnight(self):
        base = [20.0] * 10
        intraday = P.Series(bars_from(base + [19.6, 19.2, 18.8]))                 # 开盘 = 前收，盘中跌
        self.assertAlmostEqual(intraday.intraday_share(12, 3), 1.0)
        gaps = [20.0] * 10 + [19.6, 19.2, 18.8]
        overnight = P.Series(bars_from(gaps, opens=gaps))                          # 低开后全天不动
        self.assertAlmostEqual(overnight.intraday_share(12, 3), 0.0)
        self.assertAlmostEqual(overnight.worst_gap(12, 3), 18.8 / 19.2 - 1, msg="三次低开里最大的一次")
        self.assertIsNone(intraday.intraday_share(9, 3), "没跌就谈不上占比")

    def test_limit_days_and_close_position(self):
        closes = [10.0] * 5 + [11.0, 11.0, 9.9, 9.9]
        s = P.Series(bars_from(closes, highs=[c + 0.2 for c in closes], lows=[c - 0.2 for c in closes]), "600001", "SH")
        self.assertEqual(s.limit_days(8, 5), (1, 1))
        self.assertEqual(P.Series(bars_from(closes), "300001", "SZ").limit_days(8, 5), (0, 0), "创业板 20% 才算涨停")
        self.assertAlmostEqual(s.clv(8), 0.5)

    def test_trend_fit(self):
        straight = P.Series(bars_from([10 * math.exp(0.003 * i) for i in range(100)]))
        r2, slope = straight.trend(99, 60)
        self.assertAlmostEqual(r2, 1.0, places=6)
        self.assertAlmostEqual(slope, 0.003, places=6)
        zigzag = P.Series(bars_from([10 + (0.5 if i % 2 else 0) for i in range(100)]))
        self.assertLess(zigzag.trend(99, 60)[0], 0.05)
        self.assertAlmostEqual(straight.up_ratio(99, 60), 1.0)

    def test_pool_and_regime(self):
        rows = [stock_row("600001", total_mv=5e10), stock_row("600002", total_mv=9e10), stock_row("600003", "ST甲"),
                stock_row("600004", amount=1e6, total_mv=2e11), stock_row("600005", price=2.0)]
        self.assertEqual([r["code"] for r in P.build_pool(rows, 5)], ["600002", "600001"])
        derived = [{k: v for k, v in r.items() if k != "amount"} for r in rows]     # 盘中倒推的快照没有成交额
        self.assertEqual([r["code"] for r in P.build_pool(derived, 5)], ["600004", "600002", "600001"])
        self.assertEqual(set(P.regime_by_date(line_bars([100 + i for i in range(80)])).values()), {"偏强"})
        self.assertTrue(P.clean(bars_from([10.0, 10.1])))
        self.assertFalse(P.clean(bars_from([10.0, 0.0])), "带 0 的坏数据不进池子")
        self.assertEqual(set(P.regime_by_date(line_bars([200 - i for i in range(80)])).values()), {"偏弱"})

    def test_buckets(self):
        names = ["招商银行", "工商银行", "中信证券", "贵州茅台", "长江电力"]
        cands = [{"code": str(i), "name": n, "industry": ""} for i, n in enumerate(names)]
        self.assertEqual([c["name"] for c in common.diversify(cands, 3, per_bucket=1)], ["招商银行", "贵州茅台", "长江电力"])
        self.assertEqual([c["name"] for c in common.diversify(cands, 4)], ["招商银行", "工商银行", "贵州茅台", "长江电力"])
        banks = [{"name": n, "industry": "银行"} for n in ("甲", "乙", "丙", "丁")]
        self.assertEqual(len(common.diversify(banks, 4)), 2, "凑不满就少选，不让一个行业占满名单")
        self.assertEqual(common.bucket_of("电网设备"), "新能源")
        self.assertEqual(common.bucket_of("航天航空"), "军工")
        self.assertTrue(common.is_financial("", "平安银行"))
        self.assertEqual(common.pct_rank([1, 2, 3, 4], higher_better=False), [100, 75, 50, 25])


# ── 模拟买卖 ──────────────────────────────────────────────────────

class SimTest(unittest.TestCase):
    def series(self, closes, **kw):
        return P.Series(bars_from(closes, **kw), "600001", "SH")

    def test_buys_next_open_and_cannot_sell_same_day(self):
        #        t=2 信号   t=3 买入（当天冲到 11 也不能卖）  t=4 才能卖
        closes = [10, 10, 10, 10.2, 10.6, 10.6]
        highs = [10, 10, 10, 11.0, 10.7, 10.6]
        s = self.series(closes, highs=highs)
        ret, days, why = sim.run_trade(s, 2, max_days=5, target=0.05)
        self.assertEqual((days, why), (1, "target"))
        self.assertAlmostEqual(ret, 0.05 - sim.COST)
        self.assertIsNone(sim.run_trade(s, 2, max_days=5, target=0.5, stop=0.5), "没走完的交易不算")

    def test_skips_gap_up_and_limit_down_open(self):
        up = self.series([10, 10, 10, 10.5, 10.5], opens=[10, 10, 10, 10.4, 10.5])
        self.assertIsNone(sim.run_trade(up, 2, max_days=1), "高开 4%，不追")
        down = self.series([10, 10, 10, 9.0, 9.0], opens=[10, 10, 10, 9.0, 9.0])
        self.assertIsNone(sim.run_trade(down, 2, max_days=1), "开盘就跌停，不接")

    def test_target_gap_stop_and_time_exits(self):
        gap = self.series([10, 10, 10, 10, 10.8, 10.8], opens=[10, 10, 10, 10, 10.8, 10.8])
        self.assertAlmostEqual(sim.run_trade(gap, 2, max_days=5, target=0.05)[0], 0.08 - sim.COST, msg="跳空越过目标价，按开盘价成交")
        stop = self.series([10, 10, 10, 10, 9.9, 9.5, 9.4], lows=[10, 10, 10, 10, 9.3, 9.5, 9.4])
        ret, days, why = sim.run_trade(stop, 2, max_days=5, stop=0.04)
        self.assertEqual((days, why), (2, "stop"), "盘中跌破不算，收盘跌破才卖")
        self.assertAlmostEqual(ret, -0.05 - sim.COST)
        flat = self.series([10, 10, 10, 10, 10.1, 10.2, 10.3])
        self.assertEqual(sim.run_trade(flat, 2, max_days=3, target=0.2, stop=0.2)[1:], (3, "time"))

    def test_trailing_stop_and_hot_exit(self):
        closes = [10, 10, 10, 10, 11, 12, 11.2, 11.0, 11.0]
        ret, days, why = sim.run_trade(self.series(closes), 2, max_days=5, stop=0.06, trail=0.06)
        self.assertEqual((days, why), (3, "stop"), "从最高收盘价 12 回落 6% 以上卖出")
        self.assertAlmostEqual(ret, 0.12 - sim.COST)
        base = [10.0] * 25
        hot = self.series(base + [10.0, 10.5, 11.55, 11.6, 11.6], vols=[1000.0] * 30)   # 第 27 根涨停
        ret, days, why = sim.run_trade(hot, 24, max_days=10, hot_exit=True)
        self.assertEqual(why, "hot")
        self.assertAlmostEqual(ret, 11.55 / 10.0 - 1 - sim.COST, msg="涨停后第二天开盘卖")

    def cycle(self, k):
        """每 30 天一个循环：信号日之后第二天大涨 5%，然后慢慢跌回去。"""
        closes = []
        for i in range(380):
            phase = (i + k) % 30
            closes.append(10.0 if phase in (0, 1) else 10.5 - 0.5 * (phase - 2) / 27)
        return P.Series(bars_from(closes), f"60000{k}", "SH")

    def test_checkup_separates_real_edge_from_noise(self):
        seriess = [self.cycle(k) for k in range(8)]
        plan = lambda f: {"max_days": 3, "target": 0.04}                                   # noqa: E731
        good = sim.checkup(seriess, lambda s, t: {} if (t + int(s.code[-1])) % 30 == 0 else None, plan, 40, {}, "")
        self.assertEqual(good["level"], "ok")
        self.assertEqual(good["reasons"]["target"], good["n"])
        self.assertAlmostEqual(good["mean"], 0.04 - sim.COST)
        self.assertGreater(good["edge"], 0.03, "比同一批股票随便买多赚的部分")
        noise = sim.checkup(seriess, lambda s, t: {} if t % 7 == 0 else None, lambda f: {"max_days": 3}, 40, {}, "")
        self.assertEqual(noise["level"], "weak", "随便挑日子买，不该被说成有效")
        self.assertIn("没有比随便买更好", noise["verdict"])
        thin = sim.checkup(seriess[:1], lambda s, t: {} if t == 100 else None, plan, 40, {}, "")
        self.assertEqual(thin["level"], "thin")
        none = sim.checkup(seriess, lambda s, t: None, plan, 40, {}, "")
        self.assertEqual((none["n"], none["level"]), (0, "thin"))
        self.assertFalse(sim.expected(none)["available"])

    def test_expected_prefers_current_regime(self):
        seriess = [self.cycle(k) for k in range(8)]
        regimes = {d: "偏弱" for d in seriess[0].dates}
        rep = sim.checkup(seriess, lambda s, t: {} if (t + int(s.code[-1])) % 30 == 0 else None,
                          lambda f: {"max_days": 3, "target": 0.04}, 40, regimes, "偏弱")
        self.assertEqual(rep["now"]["n"], rep["n"])
        exp = sim.expected(rep)
        self.assertTrue(exp["available"] and exp["reliable"])
        self.assertIn("偏弱", exp["text"])


# ── 短期：错杀反弹 ────────────────────────────────────────────────

class ShortTest(unittest.TestCase):
    def dropped(self, tail_closes, tail_opens=None, base=None):
        base = base or calm(200)
        k = base[-1] / 20.0
        closes = base + [c * k for c in tail_closes]
        opens = None
        if tail_opens:
            opens = [base[0]] + base[:-1] + [o * k for o in tail_opens]
        return P.Series(bars_from(closes, opens=opens), "600001", "SH", "样本股")

    def test_sold_down_intraday_qualifies(self):
        s = self.dropped([19.6, 19.2, 18.8, 18.45, 18.1])                 # 每天开在前收、盘中跌 2%
        f, why = short.evaluate(s, s.n - 1)
        self.assertEqual(why, "")
        self.assertAlmostEqual(f["drop"], 18.1 / 20 - 1, places=6)
        self.assertGreater(f["share"], 0.99)
        self.assertLess(f["z"], -3)
        p = short.plan(f)
        self.assertAlmostEqual(p["target"], 0.5 * 0.095 / 0.905, places=6, msg="止盈 = 收复一半跌幅")
        self.assertAlmostEqual(p["stop"], 0.75 * 0.095, places=6)
        self.assertEqual((p["max_days"], p["max_gap"]), (8, 0.02))

    def test_rejections_name_the_reason(self):
        tail = [19.6, 19.2, 18.8, 18.45, 18.1]
        gap_down = self.dropped(tail, tail_opens=tail)                     # 同样的跌幅，全是低开
        self.assertEqual(short.evaluate(gap_down, gap_down.n - 1), (None, "跌幅主要来自隔夜低开，不是盘中卖出来的"))
        big_gap = self.dropped([19.9, 19.0, 18.9, 18.8, 18.7], tail_opens=[20.0, 19.1, 19.0, 18.9, 18.8])
        self.assertEqual(short.evaluate(big_gap, big_gap.n - 1)[1], "有 3% 以上的低开，可能是出了坏消息")
        limit_down = self.dropped([19.8, 17.8, 17.7, 17.6, 17.5])
        self.assertEqual(short.evaluate(limit_down, limit_down.n - 1)[1], "近 10 天有跌停，卖盘可能还没完")
        falling = [b.close for b in walk(200, 30, -0.003, 0.01, seed=9)]
        bear = self.dropped(tail, base=falling)
        self.assertEqual(short.evaluate(bear, bear.n - 1)[1], "近半年一直在跌，大方向不好")
        mild = self.dropped([19.95, 19.9, 19.85, 19.8, 19.75])
        self.assertEqual(short.evaluate(mild, mild.n - 1), (None, ""), "跌得不深的不算候选，也不计入原因")

    def test_select_builds_plans_and_diversifies(self):
        tail = [19.6, 19.2, 18.8, 18.45, 18.1]
        pool = {code: P.Series(bars_from(calm(200, seed) + [c * calm(200, seed)[-1] / 20 for c in tail]), code, "SH", name)
                for code, name, seed in (("600001", "甲银行", 5), ("600002", "乙银行", 6), ("600005", "丁银行", 9),
                                         ("600003", "丙科技", 7), ("600004", "亏损股", 8))}
        rows = {c: stock_row(c, s.name) for c, s in pool.items()}
        rows["600004"]["pe"] = -5.0
        board = short.select(pool, rows, {"n": 0, "level": "thin", "verdict": "", "regime": "震荡"}, "偏弱", 4)
        names = [p["name"] for p in board["picks"]]
        self.assertEqual(len(names), 3)
        self.assertIn("丙科技", names)
        self.assertEqual(sum("银行" in n for n in names), 2, "同一大类最多两只")
        self.assertEqual(board["funnel"]["reasons"], {"公司在亏损": 1})
        pick = board["picks"][0]
        plan = pick["plan"]
        self.assertEqual(plan["hold_max"], 8)
        self.assertLess(plan["stop_price"], pick["price"])
        self.assertGreater(plan["target_price"], pick["price"])
        self.assertEqual(len(plan["rules"]), 4)
        self.assertFalse(plan["expected"]["available"])
        self.assertTrue(any("仓位减半" in r for r in pick["risks"]), "市场偏弱要提醒")


# ── 中期：悄悄走强 ────────────────────────────────────────────────

def steady(n=200, slope=0.0025, wobble=0.004):
    """稳步上行：每天涨一点，偶尔小幅回落。"""
    return [10 * math.exp(slope * i + wobble * math.sin(i * 1.7)) for i in range(n)]


class MidTest(unittest.TestCase):
    def setUp(self):
        self.bench60 = {}

    def series(self, closes, vols=None, code="600001"):
        return P.Series(bars_from(closes, vols=vols), code, "SH", "样本股")

    def test_quiet_climber_qualifies(self):
        s = self.series(steady())
        f, why = mid.evaluate(s, s.n - 1, self.bench60)
        self.assertEqual(why, "")
        self.assertGreater(f["r2"], 0.9)
        self.assertGreater(f["up"], 0.53)
        self.assertAlmostEqual(f["abn"], 1.0)
        p = mid.plan(f)
        self.assertEqual((p["max_days"], p["hot_exit"]), (60, True))
        self.assertEqual(p["stop"], p["trail"])
        self.assertTrue(0.06 <= p["trail"] <= 0.12)

    def test_rejections_name_the_reason(self):
        closes = steady()
        strong_bench = {d: 0.5 for d in trading_days(200)}
        s = self.series(closes)
        self.assertEqual(mid.evaluate(s, s.n - 1, strong_bench)[1], "没有比大盘强多少")
        spike = closes[:170] + [c * 1.10 for c in closes[170:]]                    # 第 170 天一个涨停
        s = self.series(spike)
        self.assertEqual(mid.evaluate(s, s.n - 1, {})[1], "这段时间有过涨停或跌停，已经被注意到了")
        s = self.series(closes, vols=[1000.0] * 180 + [2500.0] * 20)
        self.assertEqual(mid.evaluate(s, s.n - 1, {})[1], "成交量明显放大，已经热起来了")
        jump = closes[:197] + [closes[197] * 1.03, closes[197] * 1.06, closes[197] * 1.09]
        s = self.series(jump)
        self.assertEqual(mid.evaluate(s, s.n - 1, {})[1], "最近 5 天急拉或急跌")
        choppy = [10 * math.exp(0.0025 * i) * (1.03 if i % 2 else 0.99) for i in range(200)]
        s = self.series(choppy)
        self.assertIn(mid.evaluate(s, s.n - 1, {})[1], ("上涨的天数不够多，是靠少数几天拉上来的", "走势起伏大，不够稳"))
        flat = self.series([10.0] * 200)
        self.assertEqual(mid.evaluate(flat, 199, {}), (None, ""))

    def test_financial_confirmation(self):
        ok, evidence, bonus = mid.confirm(fin_periods(growth=20.0))
        self.assertIs(ok, True)
        self.assertEqual(bonus, 15.0)
        self.assertEqual([e["label"] for e in evidence], ["业绩", "增速变化", "现金流"])
        bad, evidence, _ = mid.confirm(fin_periods(latest_growth=-8.0))
        self.assertIs(bad, False)
        self.assertIn("没有业绩支撑", evidence[0]["detail"])
        self.assertIsNone(mid.confirm(None)[0])
        self.assertIsNone(mid.confirm([])[0])

    def test_select_drops_unsupported_rallies(self):
        pool = {c: self.series(steady(slope=0.0025 + i * 0.0002), code=c) for i, c in enumerate(("600001", "600002", "600003"))}
        rows = {c: stock_row(c, f"公司{c[-1]}", industry=f"行业{c[-1]}") for c in pool}
        fin = {"600001": fin_periods(growth=15.0), "600002": fin_periods(latest_growth=-20.0)}
        report = {"n": 0, "level": "thin", "verdict": "", "regime": "震荡"}
        board = mid.select(pool, rows, {}, report, 5, financials=lambda rs: fin)
        self.assertEqual({p["code"] for p in board["picks"]}, {"600001", "600003"})
        self.assertEqual(board["funnel"]["reasons"], {"利润在下滑，上涨没有业绩支撑": 1})
        by_code = {p["code"]: p for p in board["picks"]}
        self.assertGreater(by_code["600001"]["score"], by_code["600003"]["score"], "有财报确认的排在前面")
        self.assertEqual(by_code["600003"]["evidence"][-1]["status"], "warn")
        plan = by_code["600001"]["plan"]
        self.assertIsNone(plan["target_price"])
        self.assertLess(plan["stop_price"], by_code["600001"]["price"])
        self.assertTrue(any("热了就走" in r for r in plan["rules"]))

    def test_etf_section(self):
        series = {"510300": P.Series(bars_from(steady(slope=0.0015)), "510300", "SH", "沪深300ETF"),
                  "512480": P.Series(bars_from([10.0] * 200), "512480", "SH", "半导体ETF")}
        meta = {"510300": ("SH:510300", "沪深300ETF", "宽基"), "512480": ("SH:512480", "半导体ETF", "行业")}
        out = mid.select_etfs(series, meta, {}, {"n": 0, "level": "thin", "verdict": "", "regime": "震荡"})
        self.assertEqual([p["name"] for p in out["picks"]], ["沪深300ETF"])
        self.assertEqual(out["picks"][0]["kind"], "etf")
        self.assertEqual([r["name"] for r in out["ranking"]], ["沪深300ETF", "半导体ETF"])
        self.assertEqual(out["ranking"][1]["why_not"], "涨幅不够")
        self.assertEqual(out["safe"]["code"], "511010")
        empty = mid.select_etfs({"512480": series["512480"]}, meta, {}, {"n": 0, "level": "thin", "verdict": "", "regime": ""})
        self.assertIn("不硬选", empty["note"])


# ── 长期：耐心溢价 ────────────────────────────────────────────────

class LongTest(unittest.TestCase):
    def test_prefilter(self):
        rows = [stock_row("600001", pe=10, pb=1.5, total_mv=5e10), stock_row("600002", pe=50, pb=8, total_mv=5e10),
                stock_row("600003", pe=10, pb=0.5, total_mv=5e10), stock_row("600004", pe=10, pb=1.5, total_mv=5e9),
                stock_row("600005", pe=-3, pb=1.0, total_mv=5e10), stock_row("600006", "ST甲", pe=10, pb=1.5, total_mv=5e10),
                stock_row("600007", pe=8, pb=2.0, total_mv=5e10)]
        out = longterm.prefilter(rows)
        self.assertEqual([r["code"] for r in out], ["600007", "600001"], "更便宜、ROE 更高的排前面")
        self.assertAlmostEqual(out[1]["roe_proxy"], 0.15)

    def test_payout_from_book_value_growth(self):
        years = longterm.annuals(fin_periods(eps=2.0, bps=12.0, payout=0.4))
        self.assertEqual([y.report_date[:4] for y in years], ["2025", "2024", "2023"])
        self.assertAlmostEqual(longterm.infer_payout(years), 0.4)
        split = fin_periods(eps=2.0, bps=12.0, payout=0.4)
        split[3].bps = 30.0                                                        # 2023 年每股净资产大很多：2024 年送转过
        self.assertAlmostEqual(longterm.infer_payout(longterm.annuals(split)), 0.4, msg="送转的年份不用")
        issued = fin_periods(eps=2.0, bps=12.0, payout=0.4)
        issued[3].bps = 2.0                                                        # 2024 年每股净资产猛增：增发过
        self.assertAlmostEqual(longterm.infer_payout(longterm.annuals(issued)), 0.4, msg="增发的年份不用")
        self.assertIsNone(longterm.infer_payout(longterm.annuals(fin_periods(eps=-1.0))))

    def test_expected_return_breakdown(self):
        e = longterm.expected_return(pe=10, roe=0.15, payout=0.4)
        self.assertAlmostEqual(e["dividend"], 0.04)
        self.assertAlmostEqual(e["growth"], 0.09 * 0.7)
        self.assertAlmostEqual(e["base"], 0.103)
        self.assertLess(e["low"], e["base"])
        self.assertGreater(e["high"], e["base"])
        capped = longterm.expected_return(pe=30, roe=0.40, payout=0.1)
        self.assertAlmostEqual(capped["growth"], 0.12 * 0.7, msg="增长封顶 12% 再打七折")

    def test_rolling_pe_from_reports(self):
        periods = fin_periods(eps=2.0)                       # 三季报累计 1.5，上年年报 2.0
        periods.insert(1, FinancialPeriod("2025-09-30", "2025三季报", eps=1.3))
        self.assertAlmostEqual(longterm.ttm_pe(stock_row(price=22.0, pe=11.0), periods), 22.0 / (1.5 + 2.0 - 1.3))
        self.assertEqual(longterm.ttm_pe(stock_row(price=22.0, pe=11.0), fin_periods(eps=2.0)), 11.0, "缺上年同期就用行情给的")
        self.assertEqual(longterm.ttm_pe(stock_row(price=220.0, pe=11.0), periods), 11.0, "差得离谱（多半送转过）也用行情给的")
        annual_first = fin_periods(eps=2.0)[1:]
        self.assertAlmostEqual(longterm.ttm_pe(stock_row(price=24.0, pe=11.0), annual_first), 12.0)

    def test_assess(self):
        row = stock_row(pe=12.0)
        a, why = longterm.assess(row, fin_periods(), False)
        self.assertEqual(why, "")
        self.assertAlmostEqual(a["payout"], 0.4)
        self.assertFalse(a["payout_assumed"])
        self.assertAlmostEqual(a["roe_min"], 15.4)
        for periods, reason in ((fin_periods(roe=7.0), "ROE 不够高或者不够稳"),
                                (fin_periods(latest_growth=-30.0), "最新一期利润下滑超过 10%"),
                                (fin_periods(ocf_ratio=0.3), "经营现金流跟不上利润"),
                                (fin_periods(debt=82.0), "负债率超过 70%"),
                                (fin_periods(years=(2025,)), "年报不足两年"), (None, "财报没有取到")):
            self.assertEqual(longterm.assess(row, periods, False), (None, reason))
        bank, why = longterm.assess(row, fin_periods(roe=10.0, ocf_ratio=-2.0, debt=92.0), True)
        self.assertEqual(why, "", "银行不看现金流和负债率，ROE 门槛也低一些")
        self.assertIsNone(bank["cash"])

    def test_select(self):
        rows = [stock_row(f"60000{i}", f"公司{i}", pe=10 + i, pb=2.0 + i * 0.1, total_mv=5e10, industry=ind)
                for i, ind in enumerate(["银行", "银行", "银行", "白酒", "电力行业"])]
        fin = {r["code"]: fin_periods(roe=14.0 + i) for i, r in enumerate(rows)}
        fin["600003"] = fin_periods(roe=6.0)
        board = longterm.select(rows, 4, financials=lambda rs: fin, closes_of=lambda r: [10 + math.sin(i / 9) for i in range(300)])
        codes = [p["code"] for p in board["picks"]]
        self.assertEqual(len(codes), 3)
        self.assertEqual(sum(c in ("600000", "600001", "600002") for c in codes), 2, "同一大类最多两只，凑不满就少选")
        self.assertNotIn("600003", codes)
        self.assertEqual(board["funnel"]["reasons"], {"ROE 不够高或者不够稳": 1})
        pick = board["picks"][0]
        exp = pick["plan"]["expected"]
        self.assertEqual(exp["kind"], "model")
        self.assertAlmostEqual(exp["annual"], exp["dividend"] + exp["growth"])
        self.assertIsNone(pick["plan"]["stop_price"])
        self.assertTrue(any("不设价格止损" in r for r in pick["plan"]["rules"]))
        self.assertTrue(any(e["label"] == "回撤" for e in pick["evidence"]))
        self.assertEqual(board["checkup"]["level"], "model")

    def test_fund_filters_and_capture(self):
        base = {"nav_date": "2026-11-07", "m6": 5.0, "y2": 10.0, "type": "混合型", "ft": "hh"}
        rows = [{**base, "code": "000001", "name": "甲成长混合A", "inception": "2015-01-01", "y1": 20.0, "y3": 40.0},
                {**base, "code": "000002", "name": "甲成长混合C", "inception": "2015-01-01", "y1": 19.5, "y3": 39.0},
                {**base, "code": "000003", "name": "乙一年持有期混合", "inception": "2015-01-01", "y1": 30.0, "y3": 50.0},
                {**base, "code": "000004", "name": "丙新基金", "inception": "2025-06-01", "y1": 50.0, "y3": None},
                {**base, "code": "000005", "name": "丁价值混合", "inception": "2012-01-01", "y1": 5.0, "y3": 15.0}]
        ranked = longterm.fund_perf_scores(longterm.fund_prefilter(rows, date(2026, 11, 10)))
        self.assertEqual([r["code"] for r in ranked], ["000001", "000005"], "锁定期、新基金不要，A/C 只留一个")

        days = trading_days(900)
        bench, nav, b, f = [], [], 100.0, 1.0
        for d in days:
            r = 0.004 if int(d[5:7]) % 2 else -0.004                               # 单月涨、双月跌
            b *= 1 + r
            f *= 1 + (r if r > 0 else r * 0.5)                                     # 涨全跟、跌只跌一半
            bench.append(Bar(d, b, b, b, b))
            nav.append(Bar(d, f, f, f, f, adj=f))
        cap = longterm.capture(nav, bench)
        self.assertAlmostEqual(cap["up"], 1.0, delta=0.08)
        self.assertAlmostEqual(cap["down"], 0.5, delta=0.08)
        self.assertIsNone(longterm.capture(nav[:200], bench[:200]), "不到两年的不算")

        report = {"scores": {"composite": 60.0, "rating": {"code": "Overweight", "label": "增持"}},
                  "metrics": {"3y": {"max_drawdown": -0.18}},
                  "fund": {"profile": {"scale": 30.0, "managers": [{"name": "张三", "tenure_years": 6.0}]}}}
        row = {**rows[0], "perf_score": 80.0, "y3_rank_pct": 10}
        pick, why = longterm.fund_pick(row, report, nav, bench)
        self.assertEqual(why, "")
        self.assertIn("涨的时候跟得上", pick["headline"])
        self.assertEqual(pick["plan"]["expected"]["kind"], "history")
        small = {**report, "fund": {"profile": {"scale": 0.8, "managers": []}}}
        self.assertIn("清盘", longterm.fund_pick(row, small, nav, bench)[1])
        rookie = {**report, "fund": {"profile": {"scale": 30, "managers": [{"name": "李四", "tenure_years": 0.5}]}}}
        self.assertIn("只管了", longterm.fund_pick(row, rookie, nav, bench)[1])
        self.assertEqual(longterm.fund_pick(row, None, nav, bench), (None, "取不到基金档案"))


# ── 定投 ──────────────────────────────────────────────────────────

class DcaTest(unittest.TestCase):
    def test_only_plain_index_funds_match(self):
        for name, words in (("易方达沪深300ETF联接A", ("沪深300",)), ("博时沪深300指数A", ("沪深300",)),
                            ("嘉实沪深300ETF联接(LOF)A", ("沪深300",)), ("华夏恒生ETF联接A", ("恒生指数", "恒生")),
                            ("广发纳斯达克100ETF联接人民币(QDII)A", ("纳斯达克100",)), ("国泰纳斯达克100指数(QDII)", ("纳斯达克100",)),
                            ("易方达上证科创板50ETF联接A", ("科创板50", "科创50")), ("大成中证红利指数A", ("中证红利",))):
            self.assertTrue(dca.match_index(name, words), name)
        for name, words in (("易方达沪深300ETF联接C", ("沪深300",)), ("富国沪深300指数增强A", ("沪深300",)),
                            ("华夏沪深300价值ETF联接A", ("沪深300",)), ("华夏恒生科技ETF联接(QDII)A", ("恒生指数", "恒生")),
                            ("华安创业板50ETF联接A", ("创业板",)), ("沪深300ETF联接A", ("沪深300",)),
                            ("广发纳斯达克100ETF联接美元现汇(QDII)A", ("纳斯达克100",))):
            self.assertFalse(dca.match_index(name, words), name)

    def test_candidates_take_the_longest_history(self):
        rows = [{"code": "000001", "name": "嘉实沪深300ETF联接A", "inception": "2015-03-01"},
                {"code": "000002", "name": "易方达沪深300ETF联接A", "inception": "2009-08-26"},
                {"code": "000003", "name": "南方中证1000ETF联接A", "inception": "2024-01-01"},
                {"code": "000004", "name": "广发纳斯达克100ETF联接(QDII)A", "inception": "2012-08-15"}]
        out = dca.find_candidates(rows, date(2026, 11, 13))
        self.assertEqual([(c["code"], c["index"], c["group"]) for c in out],
                         [("000002", "沪深300", "A股宽基"), ("000004", "纳斯达克100", "美股")])

    def test_cost_temperature_and_multiplier(self):
        closes = [1.0] * 800 + [2.0] * 800
        self.assertAlmostEqual(dca.dca_cost(closes, 799), 1.0)
        self.assertAlmostEqual(dca.dca_cost([1.0 if (i // 21) % 2 else 2.0 for i in range(800)], 799), 4 / 3, places=6,
                               msg="每次投一样的钱，平均成本是调和平均")
        nav = [b.adj_close for b in walk(2500, 1.0, 0.0003, 0.012, seed=3, nav=True)]
        ratios, temps = dca.temperatures(nav)
        _, earlier = dca.temperatures(nav[:2000])
        self.assertEqual(temps[:2000], earlier, "某一天的温度只用到那天为止的数据")
        self.assertIsNone(temps[700])
        self.assertTrue(0 <= temps[-1] <= 100)
        self.assertEqual([dca.multiplier(t) for t in (5, 30, 50, 70, 90, None)], [2.0, 1.5, 1.0, 0.5, 0.0, 1.0])

    def test_simulation(self):
        flat = dca.simulate([1.0] * 1500)
        self.assertTrue(all(abs(t) < 1e-9 and abs(i) < 1e-6 for t, i in flat))
        rising = dca.summarize(dca.simulate([1.0 * 1.0004 ** i for i in range(2000)]))
        self.assertEqual(rising["win_rate"], 1.0)
        self.assertAlmostEqual(rising["irr"], 1.0004 ** 245 - 1, delta=0.01, msg="一路匀速上涨时，定投年化 ≈ 指数年化")
        self.assertAlmostEqual(dca._irr([1.0] * 12, 12 * 1.01 ** 6.5), 1.01 ** 12 - 1, delta=0.003)
        self.assertIsNone(dca.summarize(dca.simulate([1.0] * 800)), "起点太少不出结论")

    def nav(self, seed, drift=0.0003, tail=None):
        closes = [b.adj_close for b in walk(3000, 1.0, drift, 0.012, seed=seed, nav=True)]
        if tail:
            closes = closes[:-250] + [closes[-250] * tail ** i for i in range(250)]
        days = trading_days(len(closes))
        return [Bar(d, c, c, c, c, adj=c) for d, c in zip(days, closes)]

    def test_select(self):
        cands = [{"code": "000001", "name": "甲沪深300ETF联接A", "index": "沪深300", "group": "A股宽基"},
                 {"code": "000002", "name": "乙中证500ETF联接A", "index": "中证500", "group": "A股宽基"},
                 {"code": "000003", "name": "丙创业板ETF联接A", "index": "创业板", "group": "A股宽基"},
                 {"code": "000004", "name": "丁纳斯达克100ETF联接(QDII)A", "index": "纳斯达克100", "group": "美股", "ft": "qdii"},
                 {"code": "000005", "name": "戊标普500ETF联接A", "index": "标普500", "group": "美股"},
                 {"code": "000006", "name": "己恒生ETF联接A", "index": "恒生指数", "group": "港股"}]
        navs = {"000001": self.nav(1, tail=0.998), "000002": self.nav(2, tail=0.998), "000003": self.nav(3, tail=0.998),
                "000004": self.nav(4, tail=1.004), "000005": self.nav(5, tail=0.998), "000006": self.nav(6)[:800]}
        board = dca.select(cands, lambda r: navs[r["code"]])
        groups = [p["industry"].split(" · ")[0] for p in board["picks"]]
        self.assertEqual(groups.count("A股宽基"), 2, "A 股宽基最多两只")
        self.assertEqual(groups.count("美股"), 1)
        self.assertNotIn("000004", [p["code"] for p in board["picks"]], "涨了一年、温度很高的不入选")
        hot = next(r for r in board["ranking"] if r["code"] == "000004")
        self.assertGreaterEqual(hot["temp"], 80)
        self.assertEqual(hot["multiplier"], 0.0)
        self.assertEqual(board["funnel"]["reasons"], {"净值历史不足 5 年": 1})
        pick = board["picks"][0]
        self.assertLess(pick["temp"], 40)
        self.assertGreaterEqual(pick["multiplier"], 1.5)
        exp = pick["plan"]["expected"]
        self.assertEqual(exp["kind"], "dca")
        self.assertIn("定投满 3 年", exp["text"])
        self.assertTrue(any("不设止损" in r for r in pick["plan"]["rules"]))
        self.assertTrue(any(e["label"] == "按温度投" for e in pick["evidence"]))
        missing = dca.select(cands[:1], lambda r: navs["nope"])
        self.assertEqual(missing["funnel"]["reasons"], {"净值没有取到": 1})


# ── 大盘 ──────────────────────────────────────────────────────────

class MarketTest(unittest.TestCase):
    def test_breadth_and_regime(self):
        rows = [stock_row("600001", change_pct=10.0), stock_row("300001", change_pct=19.9),
                stock_row("600002", "ST甲", change_pct=-5.0), stock_row("600003", change_pct=0.0)]
        b = M.breadth(rows)
        self.assertEqual((b["up"], b["down"], b["flat"], b["limit_up"], b["limit_down"]), (2, 1, 1, 2, 1))
        strong = M.regime(line_bars([100 + i for i in range(80)]), {"up_ratio": 0.7})
        weak = M.regime(line_bars([200 - i for i in range(80)]), {"up_ratio": 0.2})
        self.assertEqual((strong["label"], weak["label"]), ("偏强", "偏弱"))


# ── 整次运行 ──────────────────────────────────────────────────────

class FakeRouter:
    """替身数据源：指数、股票、ETF 是固定种子的随机行情，基金是长长的净值序列。"""

    def series(self, inst, days=800):
        if inst.market == "OF":
            return self.fund(inst)[1], "测试"
        if inst.key == "SH:000300":
            return walk(800, 3800, 0.0004, 0.01, seed=99), "测试"
        seed = int(inst.code) % 97 + 1
        return walk(min(days, 800), 20, 0.0012 if seed % 2 else 0.0, 0.013, seed=seed), "测试"

    def financials(self, inst):
        return fin_periods(roe=12.0 + int(inst.code) % 9)

    def load(self, inst, days=800, with_news=True):
        md = fund_md()
        md.instrument = inst
        return md

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


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.store, self.cache, self.router = Store(None), Cache(None), FakeRouter()
        self.addCleanup(self.store.close)
        self.addCleanup(self.cache.close)
        self.patches = [
            mock.patch.object(R.universe, "a_share_snapshot", return_value=(universe_rows(), "测试快照", [])),
            mock.patch.object(R.universe, "industry_boards", return_value=[
                {"name": f"板块{i}", "change_pct": 3 - i * 0.5, "code": f"BK{i}"} for i in range(12)]),
            mock.patch.object(R.universe, "fund_rank", side_effect=fake_fund_rank),
            mock.patch.object(R.eastmoney, "industries", return_value={}),             # 测试不联网
            mock.patch.object(R.config, "llm_ready", return_value=(False, "尚未设置 API Key")),
            mock.patch.object(R, "beijing_now", return_value=CLOSE_TIME),              # 结果不随真实时钟变化
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_once(self, **kw):
        events = []
        payload = R.run(self.router, self.cache, self.store, on_progress=lambda **e: events.append(e), **kw)
        return payload, events

    def test_full_run(self):
        payload, events = self.run_once(stock_count=4)
        self.assertEqual(events[-1]["stage"], "保存")
        self.assertEqual([e["percent"] for e in events], sorted(e["percent"] for e in events), "进度只增不减")
        self.assertEqual((payload["version"], payload["as_of"], payload["basis"]), (2, "2026-10-30", "live"))
        self.assertEqual(list(payload["boards"]), ["short", "mid", "long", "dca"])
        self.assertEqual(payload["pool"]["wanted"], 120)
        self.assertEqual(payload["pool"]["loaded"], 120)
        for key, board in payload["boards"].items():
            for field in ("title", "name", "horizon", "idea", "how", "checkup", "picks", "funnel"):
                self.assertIn(field, board, key)
            self.assertNotIn("warnings", board)
            self.assertLessEqual(len(board["picks"]), 5)
            for p in board["picks"]:
                for field in ("key", "code", "name", "kind", "score", "headline", "evidence", "plan", "risks"):
                    self.assertIn(field, p, key)
                for field in ("horizon", "entry", "rules", "expected", "position"):
                    self.assertIn(field, p["plan"], key)
                self.assertTrue(p["plan"]["expected"]["text"])
        boards = payload["boards"]
        self.assertGreater(boards["short"]["checkup"]["n"], 0)
        self.assertEqual(boards["short"]["checkup"]["stocks"], 120)
        self.assertIn("etfs", boards["mid"])
        self.assertEqual(len(boards["mid"]["etfs"]["ranking"]), len(mid.ETF_POOL))
        self.assertGreater(len(boards["long"]["picks"]), 0)
        self.assertIn("funds", boards["long"])
        self.assertGreater(len(boards["dca"]["ranking"]), 4)
        self.assertNotIn("增强", "".join(r["name"] for r in boards["dca"]["ranking"]))
        self.assertIsNone(payload["commentary"], "没配大模型时不点评，也不报错")
        self.assertFalse(any("点评" in w or "生成失败" in w for w in payload["warnings"]), payload["warnings"])

        self.assertEqual(self.store.latest_daily()["id"], payload["id"])
        self.assertIsNone(self.run_once(skip_if_exists=True)[0], "自动任务：同一交易日不重复生成")
        again, _ = self.run_once()
        self.assertEqual(len(self.store.list_daily()), 1, "同一交易日只留最新")
        self.assertEqual(self.store.list_daily()[0]["id"], again["id"])
        self.assertEqual(set(self.store.list_daily()[0]["boards"]), {"short", "mid", "long", "dca"})

        md = T.to_markdown(payload)
        for part in ("# 每日精选", "## 大盘", "## 短期 · 错杀反弹", "## 中期 · 悄悄走强", "## 长期 · 耐心溢价",
                     "## 定投 · 模拟出来的定投", "方法体检", "预期收益", "什么时候卖", "ETF（同样的量法）", "| 指数 | 基金 | 温度"):
            self.assertIn(part, md)

        perf = track.performance(self.store, self.router)
        self.assertEqual(len(perf["runs"]), 1)
        self.assertEqual(set(perf["boards"]), {"short", "mid", "long", "dca"})
        self.assertEqual(perf["boards"]["short"]["horizons"], [3, 8])

    def test_reuses_downloaded_bars_on_rerun(self):
        self.run_once()
        with mock.patch.object(self.router, "series", wraps=self.router.series) as series:
            self.run_once()
        stock_calls = [c for c in series.call_args_list if c.args[0].market in ("SH", "SZ") and c.args[0].kind == "stock"]
        self.assertEqual(stock_calls, [], "同一个交易日重新生成，不再重新下载几百只股票的日线")

    def test_before_close_uses_previous_close(self):
        with mock.patch.object(R, "beijing_now", return_value=datetime(2026, 10, 30, 10, 0, tzinfo=R.BJ)):
            payload, _ = self.run_once()
            self.assertTrue(payload["intraday"])
            self.assertEqual((payload["basis"], payload["as_of"]), ("derived", "2026-10-29"))
            self.assertIn("上一个交易日", payload["as_of_label"])
            self.assertIsNone(payload["market"]["breadth"], "倒推的数据不算涨跌家数")
            self.assertTrue(all(i["date"] == "2026-10-29" for i in payload["market"]["indices"]))
            self.assertTrue(all(p["as_of"] == "2026-10-29" for p in payload["boards"]["short"]["picks"]))
            self.assertTrue(any("还没收盘" in w for w in payload["warnings"]))
            again, _ = self.run_once()
            self.assertEqual(again["id"], payload["id"], "盘中再点生成：上一交易日已有结果就直接用")
            self.assertTrue(again["reused"])

    def test_commentary_with_llm(self):
        llm = helpers.FakeLLM("q")
        seen = {}

        def complete(system, user, **kw):
            seen["user"] = user
            return "<think>草稿</think>大盘震荡，仅供研究参考，不构成投资建议。"

        llm.complete = complete
        with mock.patch.object(R.config, "llm_ready", return_value=(True, "")), mock.patch.object(R, "make_llm", return_value=llm):
            payload, _ = self.run_once()
        self.assertEqual(payload["commentary"], "大盘震荡，仅供研究参考，不构成投资建议。")
        for title in ("短期", "中期", "长期", "定投", "历史检验"):
            self.assertIn(title, seen["user"])

    def test_pool_failures_are_reported_not_fatal(self):
        real = self.router.series

        def flaky(inst, days=800):
            if inst.kind == "stock" and inst.market == "SH":
                raise R.SourceError("限流")
            return real(inst, days)

        with mock.patch.object(self.router, "series", side_effect=flaky):
            payload, _ = self.run_once()
        self.assertEqual(payload["pool"]["failed"], 60)
        self.assertTrue(any("日线没取到" in w for w in payload["warnings"]))
        self.assertEqual(payload["boards"]["short"]["checkup"]["stocks"], 60)

    def test_one_board_failing_does_not_kill_the_run(self):
        with mock.patch.object(R.short, "select", side_effect=ZeroDivisionError("坏数据")), \
                mock.patch.object(R, "pick_long_funds", side_effect=R.SourceError("基金接口挂了")):
            payload, _ = self.run_once()
        short_board = payload["boards"]["short"]
        self.assertEqual((short_board["picks"], short_board["title"]), ([], "短期"))
        self.assertIn("没有生成出来", short_board["checkup"]["verdict"])
        self.assertTrue(any("短期板块生成失败" in w and "ZeroDivisionError" in w for w in payload["warnings"]))
        self.assertTrue(any("基金部分生成失败" in w for w in payload["warnings"]))
        self.assertNotIn("funds", payload["boards"]["long"])
        self.assertGreater(len(payload["boards"]["dca"]["ranking"]), 0, "其他板块不受影响")
        self.assertIn("## 短期", T.to_markdown(payload))

    def test_fill_industries(self):
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


# ── 历史表现 ──────────────────────────────────────────────────────

class TrackTest(unittest.TestCase):
    def test_entry_is_next_day(self):
        closes = [10.0] * 5 + [11.0, 11.5, 12.0, 12.0, 12.0, 12.0]
        opens = [10.0] * 5 + [10.5, 11.0, 11.5, 12.0, 12.0, 12.0]                  # 入选次日开盘 10.5
        bars = bars_from(closes, opens=opens)
        bench = bars_from([100.0] * 11)
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


# ── 接口 ──────────────────────────────────────────────────────────

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
            self.assertNotIn("strategy", start.call_args.kwargs)
        self.assertEqual(self.local.get("/api/daily/runs/nope").status_code, 404)
        r = self.local.post("/api/settings", json={"daily_auto": False})
        self.assertEqual(r.json()["daily_auto"], False)
        self.local.post("/api/settings", json={"daily_auto": True})

    def test_saved_run_roundtrip(self):
        store, cache = Store(None), Cache(None)
        self.addCleanup(store.close)
        self.addCleanup(cache.close)
        with mock.patch.object(R.universe, "a_share_snapshot", return_value=(universe_rows(60), "测试", [])), \
                mock.patch.object(R.universe, "industry_boards", return_value=[]), \
                mock.patch.object(R.universe, "fund_rank", side_effect=fake_fund_rank), \
                mock.patch.object(R.eastmoney, "industries", return_value={}), \
                mock.patch.object(R, "beijing_now", return_value=CLOSE_TIME):
            payload = R.run(FakeRouter(), cache, store, use_llm=False)
        rid = A.store.save_daily(payload)
        self.addCleanup(A.store.delete_daily, rid)
        self.assertEqual(self.local.get(f"/api/daily/runs/{rid}").json()["as_of"], payload["as_of"])
        md = self.local.get(f"/api/daily/runs/{rid}/markdown")
        self.assertEqual(md.status_code, 200)
        self.assertIn("## 定投", md.text)
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


if __name__ == "__main__":
    unittest.main()
