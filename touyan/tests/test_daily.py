"""每日精选的各个零件：取数解析、交易日历、股票池、冷热分、模拟成交、市场温度、大盘预估分、四个板块、卖出提醒。

全部不联网：行情是固定种子的合成数据，财报、腾讯日线都用替身。整次运行和接口在 test_daily_run.py。
"""

import random
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  （先设好隔离的数据目录）
from helpers import day_bars, price_path, trading_days, walk

from daily import dca, evidence, features, follow, gauge, longterm, mid, short, sim
from daily import pool as P
from daily import temperature as TP
from daily import tradingday as TD
from market import tencent, universe
from market.cache import Cache
from market.models import Bar
from store import Store

END = date(2026, 10, 30)          # 合成行情的最后一天（周五）
LAST = P.day_int(END.isoformat())


def stock(closes, code="600001", market="SH", name="样本股", extra=None, **kw):
    return P.Stock.from_bars(day_bars(closes, end=END, **kw), code, market, name, extra)


def temp_of(v: float) -> dict:
    """一个最小的「市场温度」结果（板块只用到这几样）。"""
    key, label = TP.zone_of(v)
    return {"value": v, "zone": key, "label": label, "table": TP.zone_table(key)}


def cold_stock(code, n=300, seed=1):
    """没人追的样子：每天开盘高、收盘低（盘中被卖），收在当天最低，最近 20 天成交缩到三成。"""
    closes = price_path(n, seed, start=15.0, drift=-0.0004, vol=0.008)
    opens = {i: closes[i] * 1.008 for i in range(n)}
    lows = {i: closes[i] for i in range(n)}
    highs = {i: closes[i] * 1.012 for i in range(n)}
    amount = {i: 2e8 * (0.3 if i >= n - 20 else 1.0) for i in range(n)}
    return stock(closes, code=code, opens=opens, lows=lows, highs=highs, amount=amount, turnover=2.0)


def hot_stock(code, n=300, seed=2):
    """被追捧的样子：每天低开高走、收在最高，最近 20 天成交放大五倍。"""
    closes = price_path(n, seed, start=12.0, drift=0.004, vol=0.008)
    opens = {i: closes[i] / 1.01 for i in range(n)}
    highs = {i: closes[i] for i in range(n)}
    amount = {i: 2e8 * (5.0 if i >= n - 20 else 1.0) for i in range(n)}
    return stock(closes, code=code, opens=opens, highs=highs, amount=amount, turnover=6.0)


def plain_pool(n=40, length=300, seed=10):
    return {f"{600100 + i}": stock(price_path(length, seed + i, start=10 + i % 7, vol=0.015), code=f"{600100 + i}",
                                   turnover=1.0 + i % 5) for i in range(n)}


# ── 取数：腾讯日线的复权和分红、东方财富的财报摘要 ─────────────────────────

class TencentTest(unittest.TestCase):
    def test_parse_dividend(self):
        self.assertEqual(tencent.parse_dividend("10转8股, 10派25.2元"), (2.52, 0.8))
        self.assertEqual(tencent.parse_dividend("10送3股"), (0.0, 0.3))
        cash, bonus = tencent.parse_dividend("10派4.39元")
        self.assertAlmostEqual(cash, 0.439)
        self.assertEqual(bonus, 0.0)
        self.assertIsNone(tencent.parse_dividend(""), "配股没有文字内容")
        self.assertIsNone(tencent.parse_dividend(None))

    def test_cash_dividend_and_bonus_shares(self):
        f, unresolved = tencent.adjust_factors([10.0, 10.0, 9.5, 9.6], {2: "10派5元"})
        self.assertEqual(unresolved, [])
        self.assertAlmostEqual(f[0], 0.95)
        self.assertEqual(f[2:], [1.0, 1.0])
        self.assertAlmostEqual(9.5 / (10.0 * f[1]) - 1, 0.0, msg="除息日当天按复权价算是平的")
        f, _ = tencent.adjust_factors([20.0, 20.0, 10.1], {2: "10转10股"})
        self.assertAlmostEqual(f[0], 0.5)
        self.assertAlmostEqual(10.1 / (20.0 * f[1]) - 1, 0.01, msg="送转之后真实涨了 1%")

    def test_unknown_events_fall_back(self):
        f, unresolved = tencent.adjust_factors([10.0, 10.0, 8.0, 8.1], {2: ""})
        self.assertEqual(unresolved, [2], "没有文字、也没有前复权价可对照：这一天的涨跌按 0 算")
        self.assertAlmostEqual(8.0 / (10.0 * f[1]) - 1, 0.0)
        closes = [20.0, 20.0, 10.0, 10.2, 10.4, 10.3]
        qfq = [10.0, 10.0, 10.0, 10.2, 10.4, 10.3]          # 前复权：除权前的价格减半
        f, unresolved = tencent.adjust_factors(closes, {2: ""}, qfq)
        self.assertEqual(unresolved, [])
        self.assertAlmostEqual(f[0], 0.5, places=6, msg="配股这类没有文字的，用前复权价反推")

    def test_dividend_info(self):
        closes = [10.0] * 600
        info = tencent.dividend_info(closes, {590: "10派5元", 300: "10派3元", 50: "10派9元"}, [1.0] * 600)
        self.assertEqual((info["div12"], info["div_prev"]), (0.5, 0.3), "近一年、再往前一年；更早的不算")
        self.assertAlmostEqual(info["yield"], 0.05)
        half = tencent.dividend_info(closes, {590: "10派5元"}, [0.5] * 590 + [1.0] * 10)
        self.assertEqual(half["div12"], 0.25, "按除权前一天的系数折成今天的股数口径")


class ReportsTest(unittest.TestCase):
    PERIODS = {
        "2025-12-31": {"600001": {"notice": "2026-03-30", "roe": 12.0, "yoy": 15.0, "industry": "白酒Ⅱ"},
                       "600002": {"notice": "2026-12-01", "roe": 30.0}},
        "2024-12-31": {"600001": {"notice": "2025-03-30", "roe": 13.0}},
        "2023-12-31": {"600001": {"notice": "2024-03-30", "roe": 11.0}},
        "2022-12-31": {"600001": {"notice": "2023-03-30", "roe": 9.0}},
        "2026-09-30": {"600001": {"notice": "2026-10-28", "yoy": 20.0, "profit": 1e9, "eps": 1.2, "industry": "白酒Ⅱ"}},
        "2026-06-30": {"600003": {"notice": "2026-08-20", "yoy": -5.0, "industry": "银行Ⅱ"}},
        "2026-03-31": {},
    }

    def test_periods(self):
        self.assertEqual(universe.recent_periods(date(2026, 11, 13)), ["2026-09-30", "2026-06-30", "2026-03-31"])
        self.assertEqual(universe.recent_periods(date(2026, 1, 5)), ["2025-12-31", "2025-09-30", "2025-06-30"])
        self.assertEqual(universe.annual_periods(date(2026, 11, 13), 2), ["2025-12-31", "2024-12-31"])

    def test_parse_reports(self):
        rows, pages = universe.parse_reports({"result": {"pages": 3, "data": [
            {"SECURITY_CODE": "600519", "NOTICE_DATE": "2026-10-31 00:00:00", "PARENT_NETPROFIT": 6.4e10, "SJLTZ": -0.25,
             "BASIC_EPS": 51.5, "WEIGHTAVG_ROE": 26.1, "PUBLISHNAME": "白酒Ⅱ"},
            {"SECURITY_CODE": "bad"}]}})
        self.assertEqual(pages, 3)
        self.assertEqual(list(rows), ["600519"])
        self.assertEqual((rows["600519"]["notice"], rows["600519"]["roe"], rows["600519"]["industry"]), ("2026-10-31", 26.1, "白酒Ⅱ"))
        self.assertEqual(universe.parse_reports({"result": None}), ({}, 0), "还没有公司披露的报告期")

    def test_annual_roes_and_latest_reports(self):
        cache = Cache(None)
        self.addCleanup(cache.close)
        with mock.patch.object(universe, "report_period", side_effect=lambda p: self.PERIODS.get(p, {})) as call:
            roes = universe.annual_roes(cache, date(2026, 11, 13))
            self.assertEqual(roes, {"600001": [12.0, 13.0, 11.0]}, "最多三年，新的在前；还没公告的（600002）不算")
            n = call.call_count
            universe.annual_roes(cache, date(2026, 11, 13))
            self.assertEqual(call.call_count, n, "已经过了披露期的年报存起来，不重复去取")
            rep = universe.latest_reports(cache, date(2026, 11, 13))
        self.assertEqual(rep["600001"]["label"], "2026年三季报")
        self.assertAlmostEqual(rep["600001"]["yoy"], 0.20, msg="同比换成小数")
        self.assertEqual(rep["600003"]["period"], "2026-06-30", "三季报还没出的，用最近一期")
        self.assertEqual(rep["600001"]["industry"], "白酒Ⅱ")


# ── 交易日历 ──────────────────────────────────────────────────────

class TradingDayTest(unittest.TestCase):
    def test_holidays_and_next_day(self):
        self.assertFalse(TD.is_trading_day(date(2026, 10, 1)), "国庆")
        self.assertFalse(TD.is_trading_day(date(2026, 10, 31)), "周六")
        self.assertTrue(TD.is_trading_day(date(2026, 10, 9)))
        self.assertEqual(TD.next_trading_day(date(2026, 9, 30)), date(2026, 10, 8))
        self.assertFalse(TD.is_trading_day(date(2027, 2, 8)), "官方还没公布的年份，按春节估")

    def test_month_window(self):
        self.assertEqual(TD.month_window(date(2026, 10, 29)), "last", "明天（10-30）是十月最后一个交易日")
        self.assertEqual(TD.month_window(date(2026, 10, 30)), "first", "明天（11-02）是十一月第一个交易日")
        self.assertEqual(TD.month_window(date(2026, 10, 28)), "")
        self.assertEqual(TD.trading_days_until_month_window(date(2026, 10, 27)), 2)
        self.assertEqual(TD.trading_days_until_month_window(date(2026, 10, 29)), 0)


# ── 股票池 ────────────────────────────────────────────────────────

class PoolTest(unittest.TestCase):
    def test_limits_and_amount(self):
        s = stock([10.0, 11.0, 9.9, 9.9], highs={1: 11.0}, lows={2: 9.9}, opens={3: 8.91})
        self.assertTrue(s.limit_up(1))
        self.assertTrue(s.limit_down(2))
        self.assertEqual(s.opens_at_limit(3), -1, "开盘就在跌停价上")
        self.assertFalse(stock([10.0, 11.0], code="300001", market="SZ", highs={1: 11.0}).limit_up(1), "创业板涨停是 20%")
        self.assertAlmostEqual(s.avg_amount(3), 2e8)
        self.assertAlmostEqual(s.float_mv, 2e8 / 0.015, msg="流通市值 = 成交额 ÷ 换手率")
        self.assertIsNone(s.dividend_yield, "没有分红记录")
        self.assertAlmostEqual(stock([10.0] * 3, extra={"div12": 0.5}).dividend_yield, 0.05)

    def test_save_and_load(self):
        stocks = {"600001": stock(price_path(300, 1), extra={"div12": 0.3, "div_prev": 0.2}), "000002": stock(price_path(280, 2), code="000002", market="SZ")}
        path = Path(tempfile.mkdtemp()) / "pool.bin"
        P.save_pool(path, "2026-10-30", stocks)
        back = P.load_saved(path, "2026-10-30")
        self.assertEqual(set(back), set(stocks))
        self.assertEqual(list(back["600001"].c), list(stocks["600001"].c))
        self.assertEqual((back["600001"].div12, back["600001"].div_prev, back["000002"].div12), (0.3, 0.2, None))
        self.assertEqual(back["000002"].market, "SZ")
        self.assertIsNone(P.load_saved(path, "2026-10-29"), "不是这一天的不用")
        path.write_bytes(b"garbage")
        self.assertIsNone(P.load_saved(path, "2026-10-30"))

    def test_build_and_load_pool(self):
        rows = [{"code": f"6000{i:02d}", "market": "SH", "name": f"股{i}", "price": 10.0, "amount": 1e8} for i in range(8)]
        rows += [{"code": "600900", "market": "SH", "name": "*ST甲", "price": 10.0, "amount": 1e9},
                 {"code": "600901", "market": "SH", "name": "N新股", "price": 10.0, "amount": 1e9},
                 {"code": "600902", "market": "SH", "name": "冷清", "price": 10.0, "amount": 1e6}]
        wanted = P.build_pool(rows)
        self.assertEqual([r["code"] for r in wanted], [f"6000{i:02d}" for i in range(8)], "ST、新股、成交太少的不下载")

        def fetch(row, days):
            k = int(row["code"][-2:])
            if k == 0:
                raise RuntimeError("断网")
            if k == 1:
                return day_bars(price_path(300, k), end=date(2026, 10, 29))            # 停牌：没有今天
            if k == 2:
                return day_bars(price_path(100, k), end=END)                           # 上市不满一年
            if k == 3:
                return day_bars(price_path(300, k), amount=1e6, end=END)               # 成交太冷清
            bars = day_bars(price_path(300, k), end=END)
            return (bars, {"div12": 0.1, "div_prev": 0.0}) if k % 2 else bars
        path = Path(tempfile.mkdtemp()) / "pool.bin"
        stocks, info = P.load_pool(fetch, wanted, "2026-10-30", path=path, workers=2)
        self.assertEqual(sorted(stocks), ["600004", "600005", "600006", "600007"])
        self.assertEqual((info["failed"], info["stale"], info["short"], info["thin"], info["cached"]), (1, 1, 1, 1, False))
        self.assertEqual((stocks["600005"].div12, stocks["600004"].div12), (0.1, None), "带分红信息的取数也认")
        again, info = P.load_pool(lambda r, d: 1 / 0, wanted, "2026-10-30", path=path)
        self.assertTrue(info["cached"], "同一个交易日重新生成，直接用存下的整池")
        self.assertEqual(sorted(again), sorted(stocks))


# ── 冷热分和慢指标 ────────────────────────────────────────────────

class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.stocks = plain_pool()
        self.stocks["600001"] = cold_stock("600001")
        self.stocks["600002"] = hot_stock("600002")
        self.stocks["600003"] = stock(price_path(300, 3), code="600003", turnover=20.0)
        self.cross = features.crosses(self.stocks, [LAST])[LAST]

    def test_cold_score(self):
        self.assertEqual(len(self.cross), len(self.stocks))
        cold = dict(zip(self.cross.codes, self.cross.cold))
        self.assertGreater(cold["600001"], 90, "盘中被卖、缩量、收在低位：最冷")
        self.assertLess(cold["600002"], 10, "盘中拉升、放量、收在高位：最热")
        got = self.cross.get("600002")
        self.assertGreater(got["vabn"], 2.0, "近 20 天成交是一年平均的几倍")
        self.assertGreater(got["clv"], 0.95, "天天收在最高")
        self.assertIsNone(self.cross.get("999999"))
        too_short = {"600003": stock(price_path(200, 3), code="600003")}
        self.assertEqual(len(features.crosses(too_short, [LAST])[LAST]), 0, "日线不到 250 根的不算")

    def test_cold_for_outsiders(self):
        prep = features.Prep(self.stocks["600001"])
        t = self.stocks["600001"].n - 1
        own = self.cross.cold[self.cross.pos["600001"]]
        self.assertAlmostEqual(self.cross.cold_for(prep.values(t)), own, delta=5, msg="放回池子里排，和它本来的分数差不多")
        hot = features.Prep(self.stocks["600002"]).values(t)
        self.assertLess(self.cross.cold_for(hot), 10)
        outsider = cold_stock("600009", seed=9)
        series = features.cold_series(outsider, {LAST: self.cross})
        self.assertGreater(series[outsider.n - 1], 80, "掉出池子的冷门股，照样估得出冷热分")

    def test_oversold_score(self):
        score = dict(zip(self.cross.codes, features.oversold_score(self.cross)))
        self.assertGreater(score["600001"], score["600002"], "跌得多、没人追的排在前面")

    def test_slow_measures_and_heat(self):
        flat = stock([10.0] * 600, turnover=2.0)
        self.assertLess(features.volatility(flat), 1e-9)
        self.assertAlmostEqual(features.turnover(flat), 0.02, places=6, msg="每天换手 2%")
        self.assertEqual(features.long_return(flat), 0.0)
        rising = stock([10.0 * 1.001 ** i for i in range(600)])
        self.assertAlmostEqual(features.long_return(rising), 1.001 ** 599 - 1, places=3)
        self.assertIsNone(features.long_return(stock(price_path(300, 4))), "不到两年的不算两年半涨幅")
        heat = features.heat(self.stocks, self.cross)
        self.assertIn("被追捧", heat["600002"]["kinds"])
        self.assertIn("换手高", heat["600003"]["kinds"])
        self.assertNotIn("被追捧", heat["600001"]["kinds"])

    def test_industry_trends(self):
        stocks, industry = {}, {}
        for g in range(12):
            for k in range(8):
                code = f"6{g:02d}{k:03d}"
                drift = 0.002 if g == 0 else -0.002 if g == 1 else 0.0
                stocks[code] = stock(price_path(640, g * 100 + k, drift=drift, vol=0.01), code=code)
                industry[code] = f"行业{g}"
        calendar = [P.day_int(d) for d in trading_days(640, END)]
        trends = features.industry_trends(stocks, industry, calendar)
        self.assertEqual(len(trends), 12)
        self.assertEqual(trends["行业0"]["state"], "strong")
        self.assertEqual(trends["行业1"]["state"], "weak")
        self.assertGreater(trends["行业0"]["long"], 0.5)
        self.assertEqual(features.industry_trends(stocks, {}, calendar), {}, "没有行业分类就不算")


# ── 模拟成交 ──────────────────────────────────────────────────────

class SimTest(unittest.TestCase):
    BASE = [10.0] * 20

    def test_buys_next_open_and_holds(self):
        s = stock(self.BASE + [10.2, 10.4, 10.6, 10.8, 11.0, 11.2])
        ret, days, why = sim.trade(s, 19, 5)
        self.assertEqual((days, why), (5, "time"))
        self.assertAlmostEqual(ret, 11.2 / 10.0 * (1 - sim.COST) - 1, msg="第二天开盘（=前收 10）买，第 5 天收盘卖")
        self.assertIsNone(sim.trade(s, 22, 5), "还没走完的不算")

    def test_gap_and_limit_open_are_skipped(self):
        self.assertIsNone(sim.trade(stock(self.BASE + [10.5] * 6, opens={20: 10.4}), 19, 5), "高开 4% 放弃")
        self.assertIsNone(sim.trade(stock(self.BASE + [11.0] * 6, opens={20: 11.0}, highs={20: 11.0}), 19, 5, max_gap=0.2),
                          "开盘就涨停买不进")

    def test_stop_and_limit_down(self):
        s = stock(self.BASE + [10.0, 9.5, 9.1, 9.0, 9.0, 9.0])
        ret, days, why = sim.trade(s, 19, 5, stop=0.08)
        self.assertEqual((days, why), (2, "stop"))
        self.assertAlmostEqual(ret, 9.1 / 10.0 * (1 - sim.COST) - 1)
        locked = stock(self.BASE + [10.0, 9.0, 8.8, 8.8, 8.8, 8.8], lows={21: 9.0}, opens={22: 8.7})
        ret, days, why = sim.trade(locked, 19, 5, stop=0.08)
        self.assertEqual((days, why), (2, "stop"), "收盘封跌停卖不掉，第二天开盘卖")
        self.assertAlmostEqual(ret, 8.7 / 10.0 * (1 - sim.COST) - 1)

    def test_limit_up_exit_and_stats(self):
        s = stock(self.BASE + [10.0, 11.0, 11.5, 11.0, 11.0, 11.0], highs={21: 11.0}, opens={22: 11.4})
        ret, days, why = sim.trade(s, 19, 5, sell_on_limit_up=True)
        self.assertEqual((days, why), (2, "limit_up"))
        self.assertAlmostEqual(ret, 11.4 / 10.0 * (1 - sim.COST) - 1)
        self.assertAlmostEqual(sim.hold_return(s, 19, 5), 11.0 / 10.0 * (1 - sim.COST) - 1)
        st = sim.stats([0.1, -0.05, 0.02])
        self.assertEqual((st["n"], round(st["win_rate"], 3), st["median"]), (3, 0.667, 0.02))
        self.assertEqual(sim.stats([]), {"n": 0})


# ── 市场温度 ──────────────────────────────────────────────────────

class TemperatureTest(unittest.TestCase):
    def test_rolling_percentile(self):
        self.assertEqual(TP.rolling_pct([1, 2, 3, 4, 5], window=3, minp=2), [None, 100.0, 100.0, 100.0, 100.0])
        got = TP.rolling_pct([5, 4, 3, 2, 1], window=3, minp=2)
        self.assertEqual(got[1], 50.0)
        self.assertAlmostEqual(got[4], 100 / 3)
        self.assertEqual(TP.rolling_pct([None, 1, None, 2], window=10, minp=1), [None, 100.0, None, 100.0])

    def test_zones(self):
        self.assertEqual([TP.zone_of(v)[1] for v in (5, 35, 50, 70, 95, 100)], ["很冷", "偏冷", "不冷不热", "偏热", "很热", "很热"])
        table = TP.zone_table("cool")
        self.assertEqual([r["current"] for r in table], [False, True, False, False, False])
        self.assertAlmostEqual(sum(r["share"] for r in table), 1.0, places=2)
        self.assertGreater(table[0]["y2"]["win"], 0.9, "很冷的时候买入，之后两年几乎都赚")
        self.assertEqual(table[4]["y2"]["win"], 0.0, "很热的时候买入，之后两年没有赚过")

    def test_shipped_history(self):
        h = TP.history()
        self.assertEqual(len(h["dates"]), len(h["all"]))
        self.assertEqual(h["dates"], sorted(h["dates"]))
        hot, cold, early = TP.temps_on([20150612, 20181228, 20050104])
        self.assertGreater(hot, 80, "2015 年 6 月：很热")
        self.assertLess(cold, 10, "2018 年底：很冷")
        self.assertIsNone(early, "历史不够三年时没有温度")

    def test_reading_and_compute(self):
        stocks, rows = {}, {}
        for i in range(600):
            code = f"{600000 + i}"
            stocks[code] = P.Stock(code, "SH", "", [LAST], [10.0], [10.0], [10.0], [10.0], [1e8], float_mv=float(i + 1))
            rows[code] = {"pb": 0.5 + i / 100}
        r = TP.reading(stocks, rows)
        self.assertAlmostEqual(r["all"], 3.495, places=3)
        self.assertAlmostEqual(r["big"], 4.995, places=3, msg="流通市值最大的 300 只")
        self.assertAlmostEqual(r["below_book"], 50 / 600, places=3)
        self.assertIsNone(TP.reading(dict(list(stocks.items())[:100]), rows), "股票太少（数据源出了问题）就不算")
        cache = Cache(None)
        self.addCleanup(cache.close)
        t = TP.compute(stocks, rows, "2026-11-20", cache)
        self.assertIsNone(t["stale"])
        self.assertTrue(0 <= t["value"] <= 100)
        self.assertEqual(t["label"], TP.zone_of(t["value"])[1])
        self.assertEqual(TP.load_extra(cache), {20261120: (r["all"], r["big"])}, "今天的读数记下来，以后接着用")
        self.assertGreater(len(t["history"]), 200)
        again = TP.compute({}, {}, "2026-11-23", cache)
        self.assertEqual(again["stale"], "2026-11-20", "今天没取全：用最近一次的读数，并且说明")
        self.assertEqual(again["value"], t["value"])

    def test_monthly(self):
        rows = TP.monthly([20260105, 20260130, 20260202, 20260227], [10.0, 20.0, None, 40.0], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(rows, [[202601, 20.0, 2.0], [202602, 40.0, 4.0]])


# ── 大盘预估分 ────────────────────────────────────────────────────

class GaugeTest(unittest.TestCase):
    def test_parts(self):
        crash = {"change": -0.03, "amount_ratio": 1.3, "down_share": 0.03, "up_share": 0.001, "change5": -0.06,
                 "limit_up": 3, "limit_down": 90, "pool": 3000}
        on = {p["key"] for p in gauge.score_parts(crash, date(2026, 11, 2), "") if p["on"]}
        self.assertEqual(on, {"vol_up", "big_dn", "dn_many", "drop5", "mon"})
        self.assertEqual(gauge.total(gauge.score_parts(crash, date(2026, 11, 2), "")), 6)
        quiet = {"change": 0.001, "amount_ratio": 0.8, "down_share": 0.0, "up_share": 0.003, "change5": 0.0,
                 "limit_up": 9, "limit_down": 0, "pool": 3000}
        self.assertEqual(gauge.total(gauge.score_parts(quiet, date(2026, 10, 29), "")), -3, "平淡、缩量、明天周四")
        self.assertEqual([gauge.stance_of(s)[0] for s in (4, 3, 2, 1, 0, -1)], ["go", "go", "light", "wait", "wait", "avoid"])

    def test_temperature_gate(self):
        base = ("go", "可以出手", "依据")
        self.assertEqual(gauge.apply_temperature(3, *base, {"value": 85, "label": "很热"})[0], "avoid", "很热不做短线")
        key, _, basis, info = gauge.apply_temperature(4, *base, {"value": 65, "label": "偏热"})
        self.assertEqual((key, info["effect"]), ("light", "halve"))
        self.assertIn("轻仓", basis)
        key, _, _, info = gauge.apply_temperature(3, *base, {"value": 30, "label": "偏冷"})
        self.assertEqual((key, info["effect"]), ("go", "boost"))
        self.assertEqual(gauge.apply_temperature(3, *base, None), base + (None,))
        rows = gauge.temp_table({"value": 30})
        self.assertTrue(rows[0]["current"])
        self.assertIsNone(rows[3]["new"], "近十年没有温度 80 以上又分数够的日子")

    def test_compute_on_a_crash_day(self):
        stocks = {}
        for i in range(60):
            closes = price_path(299, i + 1, vol=0.01)
            closes.append(round(closes[-1] * 0.90, 2))
            code = f"{600300 + i}"
            stocks[code] = stock(closes, code=code)
        calendar = [P.day_int(d) for d in trading_days(299 + 1, END)]
        g = gauge.compute(stocks, calendar, {c: f"行业{int(c) % 6}" for c in stocks})
        self.assertEqual(g["facts"]["limit_down"], 60)
        on = {p["key"] for p in g["parts"] if p["on"]}
        self.assertTrue({"big_dn", "dn_many", "drop5", "mon", "month"} <= on, on)
        self.assertEqual((g["score"], g["stance"]), (6, "go"))
        self.assertGreater(len(g["scores"]), 10)
        self.assertEqual(g["scores"][-1]["score"], 6)
        self.assertTrue(g["history"])
        self.assertIsNone(g["temp"])


# ── 四个板块 ──────────────────────────────────────────────────────

def board_pool():
    """60 只普通的 + 5 只「5 天跌了不少、没人追」的 + 冷门股 + 热门股，再加一只今天涨停的。"""
    stocks = plain_pool(55)
    for i in range(5):
        closes = price_path(295, 50 + i, vol=0.01)
        for k in range(5):
            closes.append(round(closes[-1] * 0.982, 3))
        code = f"60070{i}"
        stocks[code] = stock(closes, code=code)
    for i in range(6):
        code = f"60080{i}"
        stocks[code] = cold_stock(code, seed=80 + i)
    stocks["600900"] = hot_stock("600900")
    up = price_path(299, 99)
    up.append(round(up[-1] * 1.1, 2))
    stocks["600901"] = stock(up, code="600901", highs={299: round(up[-2] * 1.1, 2)})
    return stocks


class BoardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stocks = board_pool()
        cls.calendar = [P.day_int(d) for d in trading_days(300, END)]
        cls.crosses = features.crosses(cls.stocks, [LAST])
        cls.cross = cls.crosses[LAST]
        cls.industry = {c: f"行业{int(c) % 7}" for c in cls.stocks}
        cls.rows = {c: {"name": f"股{c}", "pe": 15.0, "pb": 1.5, "industry": cls.industry[c]} for c in cls.stocks}
        cls.rows["600704"]["pe"] = -3.0
        cls.g = gauge.compute(cls.stocks, cls.calendar, cls.industry)

    def gauge_as(self, score, stance):
        return dict(self.g, score=score, stance=stance, label="测试", basis="测试依据")

    def test_short_acts_only_when_the_score_is_enough(self):
        b = short.select(self.stocks, self.crosses, self.gauge_as(3, "go"), self.rows, self.industry, END.isoformat(), 5,
                         {"512100": {"close": 2.5}})
        self.assertTrue(b["picks"])
        self.assertLessEqual(len(b["picks"]), 5)
        codes = [p["code"] for p in b["picks"]]
        self.assertTrue(set(codes) & {f"60070{i}" for i in range(5)}, "5 天跌得多的排在前面")
        self.assertNotIn("600704", codes, "公司亏损的不选")
        self.assertNotIn("600901", codes, "今天涨停的不选")
        p = b["picks"][0]
        self.assertAlmostEqual(p["plan"]["stop_price"], p["price"] * (1 - short.STOP), delta=0.011)
        self.assertEqual(len(p["spark"]["closes"]), 120)
        self.assertTrue(p["meters"])
        self.assertEqual(b["etfs"]["picks"][0]["price"], 2.5)
        self.assertIn("两个十年", b["checkup"]["verdict"])
        self.assertIn("by_year", b["checkup"])
        self.assertIn("今天涨停或跌停", b["funnel"]["reasons"])
        self.assertIn("公司在亏损，或者没有取到市盈率", b["funnel"]["reasons"])
        light = short.select(self.stocks, self.crosses, self.gauge_as(2, "light"), self.rows, self.industry, END.isoformat(), 5)
        self.assertIn("轻仓", light["picks"][0]["plan"]["position"])
        self.assertIn("分数 ≥2", light["etfs"]["picks"][0]["why"])
        wait = short.select(self.stocks, self.crosses, self.gauge_as(0, "wait"), self.rows, self.industry, END.isoformat(), 5)
        self.assertEqual((wait["picks"], wait["etfs"]), ([], None))
        self.assertIn("今天不出手", wait["note"])

    def test_mid_rules(self):
        reports = {c: {"yoy": 0.3, "label": "2026年三季报", "notice": "2026-10-28", "industry": self.industry[c]} for c in self.stocks}
        reports["600801"]["yoy"] = 0.05
        b = mid.select(self.stocks, self.crosses, self.g, self.rows, reports, self.calendar, END.isoformat(), 5, temp_of(30))
        codes = {p["code"] for p in b["picks"]}
        self.assertTrue(codes, b["funnel"])
        self.assertTrue(codes <= {f"60080{i}" for i in range(6)}, "只买最冷的一成")
        self.assertNotIn("600801", codes, "利润同比没超过 10% 的不要")
        self.assertIn("最新财报的净利润同比没有超过 10%", b["funnel"]["reasons"])
        self.assertIn("600900", [x["code"] for x in b["avoid"]["names"]], "最热的列在「别追」里")
        p = b["picks"][0]
        self.assertIsNone(p["plan"]["stop_pct"], "不设价格止损")
        self.assertIn("市场温度", p["plan"]["expected"]["text"])
        self.assertEqual(b["timing"]["level"], "go")
        self.assertTrue(b["timing"]["table"][1]["current"])
        self.assertEqual(mid.timing(self.g, temp_of(85))["level"], "avoid", "很热的时候不建仓")
        self.assertEqual(mid.timing(dict(self.g, score=-2), temp_of(30))["level"], "wait")
        self.assertEqual(mid.timing(dict(self.g, score=0), None)["level"], "wait")
        no_reports = mid.select(self.stocks, self.crosses, self.g, self.rows, {}, self.calendar, END.isoformat(), 5)
        self.assertTrue(no_reports["warnings"])

    def test_mid_simulation(self):
        base = [10.0] * 20
        s = stock(base + [10.0, 10.1, 10.2, 10.3, 10.4, 10.5])
        ret, days, why = mid.simulate(s, 19, lambda j: 25 if j == 23 else 95, hold=5)
        self.assertEqual((days, why), (4, "hot"), "冷热分掉到 30 以下：第二天开盘卖")
        self.assertAlmostEqual(ret, 10.3 / 10.0 * (1 - sim.COST) - 1)
        up = stock(base + [10.0, 11.0, 11.4, 11.0, 11.0, 11.0], highs={21: 11.0}, opens={22: 11.3})
        self.assertEqual(mid.simulate(up, 19, lambda j: 95, hold=5)[2], "limit_up")
        self.assertIsNone(mid.simulate(s, 19, lambda j: 95), "最多拿 120 天，还没走完的不算")
        ret, days, why = mid.simulate(s, 19, lambda j: None, hold=5)
        self.assertEqual((days, why), (5, "time"))

    def test_long_board(self):
        reports = {c: {"yoy": 0.1, "label": "2026年三季报", "industry": self.industry[c]} for c in self.stocks}
        reports["600101"]["yoy"] = -0.5
        roes = {c: [12.0, 13.0, 11.0] for c in self.stocks}
        roes["600102"] = [12.0, 6.0, 11.0]
        stocks = {c: P.Stock(s.code, s.market, s.name, s.dates, s.o, s.h, s.l, s.c, s.a, s.float_mv,
                             div12=(0.0 if c == "600103" else s.c[-1] * (0.02 + int(c) % 5 / 100)), div_prev=0.1)
                  for c, s in self.stocks.items()}
        heat = features.heat(stocks, self.cross)
        trends = {f"行业{k}": {"state": "weak" if k == 6 else "neutral", "long": -0.3 if k == 6 else 0.0, "short": -0.1,
                               "long_rank": 5 if k == 6 else 50, "short_rank": 20, "count": 9} for k in range(7)}
        b = longterm.select(stocks, self.cross, self.rows, reports, roes, heat, trends, temp_of(30), END.isoformat(), 5)
        codes = [p["code"] for p in b["picks"]]
        self.assertEqual(b["stance"]["key"], "buy")
        self.assertGreaterEqual(len(codes), 5)
        self.assertLessEqual(len(codes), longterm.MIN_PICKS, "至少要分散 8 只")
        for code, why in (("600101", "掉了 20% 以上"), ("600102", "ROE 有低于 8%"), ("600103", "近一年没有现金分红"), ("600704", "亏损")):
            self.assertNotIn(code, codes)
            self.assertTrue(any(why in k for k in b["funnel"]["reasons"]), why)
        self.assertNotIn("600900", codes, "四种热的不选")
        self.assertFalse([c for c in codes if self.industry[c] == "行业6"], "长期走弱的行业不选")
        yields = [p["score"] for p in b["picks"]]
        self.assertEqual(yields, sorted(yields, reverse=True), "按股息率从高到低")
        self.assertEqual(b["industry"]["weak_count"], 1)
        self.assertIn("温度", b["picks"][0]["plan"]["expected"]["text"])
        self.assertEqual([longterm.stance_of(temp_of(v))["key"] for v in (10, 50, 70, 90)], ["buy", "hold", "pause", "sell"])
        self.assertEqual(longterm.stance_of(None)["key"], "unknown")
        sell = longterm.select(stocks, self.cross, self.rows, reports, roes, heat, trends, temp_of(90), END.isoformat(), 5)
        self.assertIn("不是长期买入的时候", sell["picks"][0]["risks"][0])


class FundsTest(unittest.TestCase):
    @staticmethod
    def nav(seed, n=3200, drift=0.0003):
        closes = [b.adj_close for b in walk(n, 1.0, drift, 0.012, seed=seed, nav=True)]
        return [Bar(d, c, c, c, c, adj=c) for d, c in zip(trading_days(n, END), closes)]

    def test_matching(self):
        self.assertTrue(dca.match_index("易方达沪深300ETF联接A", ("沪深300",)))
        self.assertFalse(dca.match_index("富国沪深300指数增强A", ("沪深300",)), "增强型不是纯指数")
        self.assertFalse(dca.match_index("易方达沪深300ETF联接C", ("沪深300",)), "C 类份额不要")
        rows = [{"code": "1", "name": "华夏沪深300ETF联接A", "inception": "2012-01-01"},
                {"code": "2", "name": "嘉实沪深300ETF联接A", "inception": "2008-01-01"},
                {"code": "3", "name": "大成中证红利指数A", "inception": "2010-01-01"},
                {"code": "4", "name": "广发纳斯达克100ETF联接(QDII)A", "inception": "2024-01-01"}]
        got = {r["index"]: r for r in dca.find_candidates(rows, date(2026, 11, 1))}
        self.assertEqual(got["沪深300"]["code"], "2", "同一个指数取历史最长的")
        self.assertEqual((got["沪深300"]["method"], got["中证红利"]["method"]), ("temp", "hold"))
        self.assertNotIn("纳斯达克100", got, "不满 5 年的不要")

    def test_run_rules(self):
        c = [1.0 + 0.02 * k for k in range(15)] + [1.3 - 0.02 * k for k in range(10)]
        t = [30.0] * 12 + [85.0] * 3 + [30.0] * 10
        hold = dca.run(c, t, "hold")
        rule = dca.run(c, t, "temp")
        self.assertEqual((hold["sells"], hold["months"]), (0, 25))
        self.assertEqual(rule["sells"], 1, "温度一到 80 以上就全部卖出；之后很热的月份不再买")
        self.assertGreater(rule["multiple"], hold["multiple"], "高处卖掉、低处投回，比一直拿着好")
        self.assertGreater(rule["in_fund"], 0.5, "温度回到 40 以下后，卖出的钱分批投回去了")
        self.assertEqual([dca.multiplier(v) for v in (10, 30, 50, 70, 90, None)], [2.0, 1.5, 1.0, 0.5, 0.0, 1.0])
        w = dca.windows(c, t, "hold", 12)
        self.assertEqual(w["n"], len(c) - 12 + 1)
        self.assertIsNone(dca.windows(c[:15], t[:15], "hold", 12), "起点太少不给结果")

    def test_select(self):
        rows = [{"code": f"{110000 + i}", "name": name, "inception": "2012-01-01", "nav": 1.5, "nav_date": "2026-10-30"}
                for i, name in enumerate(["博时沪深300指数A", "南方中证500ETF联接A", "易方达创业板ETF联接A", "大成中证红利指数A", "华安上证50ETF联接A"])]
        cands = dca.find_candidates(rows, date(2026, 11, 1))
        navs = {r["code"]: self.nav(int(r["code"]) % 50 + 1) for r in rows}
        b = dca.select(cands, lambda r: navs[r["code"]], 5, temp_of(30))
        groups = [p["industry"].split(" · ")[0] for p in b["picks"]]
        self.assertLessEqual(groups.count("A股宽基"), 2, "A 股宽基最多两只")
        self.assertEqual(len(b["ranking"]), 5)
        wide = next(p for p in b["picks"] if p["method"] == "temp")
        self.assertEqual(wide["multiplier"], 1.5)
        self.assertTrue(any("80 以上" in r for r in wide["plan"]["rules"]))
        red = next(p for p in b["picks"] if p["method"] == "hold")
        self.assertTrue(any("不止盈" in r for r in red["plan"]["rules"]))
        self.assertEqual(b["temp"]["multiplier"], 1.5)
        hot = dca.select(cands, lambda r: navs[r["code"]], 5, temp_of(90))
        self.assertTrue(all(p["method"] == "hold" for p in hot["picks"]), "很热的时候境内宽基不买")
        self.assertIn("分批卖出", hot["note"])
        self.assertEqual(dca.select(cands[:1], lambda r: 1 / 0)["funnel"]["reasons"], {"净值没有取到": 1})

    def test_index_funds_for_long_board(self):
        cands = [{"code": "110001", "name": "博时沪深300指数A", "index": "沪深300", "group": "A股宽基", "nav": 1.2},
                 {"code": "110002", "name": "大成中证红利指数A", "index": "中证红利", "group": "红利", "nav": 2.1}]
        got = longterm.index_funds(cands, lambda r: self.nav(int(r["code"]) % 50 + 1), temp_of(30))
        self.assertEqual([p["index"] for p in got["picks"]], ["沪深300", "中证红利"])
        st = got["picks"][0]["stats"]
        self.assertTrue(0 <= st["y2"]["cold"]["win"] <= 1)
        self.assertIn("温度", got["picks"][0]["why"])
        self.assertTrue(any("一直拿着" in r for r in got["picks"][1]["rules"]), "红利类不用按温度卖")


# ── 之前入选的，现在该怎么办 ──────────────────────────────────────

class FollowTest(unittest.TestCase):
    BASE = [10.0] * 30

    def picked(self, s, k=29):
        return P.day_text(s.dates[k])

    def test_short(self):
        s = stock(self.BASE + [10.1, 10.2])
        it = follow.follow_short(s, "SH:600001", "甲", self.picked(s))
        self.assertEqual((it["status"], it["days"], it["entry"]), ("hold", 1, 10.0))
        self.assertIn("还有 4 个交易日", it["action"])
        self.assertEqual(it["stop"], 9.2)
        s = stock(self.BASE + [10.0, 9.5, 9.1, 9.3])
        it = follow.follow_short(s, "SH:600001", "甲", self.picked(s))
        self.assertEqual((it["status"], it["exit"]), ("done", 9.1))
        self.assertIn("止损", it["action"])
        s = stock(self.BASE + [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6])
        it = follow.follow_short(s, "SH:600001", "甲", self.picked(s))
        self.assertEqual((it["status"], it["exit"], it["days"]), ("done", 10.5, 5))
        self.assertEqual(follow.follow_short(s, "SH:600001", "甲", self.picked(s, s.n - 1))["status"], "wait")
        gap = stock(self.BASE + [10.5, 10.6], opens={30: 10.4})
        self.assertEqual(follow.follow_short(gap, "SH:600001", "甲", self.picked(gap))["status"], "skip")

    def test_mid(self):
        s = stock(self.BASE + [10.0, 10.1, 10.2, 10.3, 10.4, 10.5])
        it = follow.follow_mid(s, "SH:600001", "甲", self.picked(s), lambda j: 25 if j == 33 else 95, 95)
        self.assertEqual((it["status"], it["exit"]), ("done", 10.3), "变热的第二天开盘卖（开盘 = 前收 10.3）")
        self.assertIn("变热", it["action"])
        it = follow.follow_mid(s, "SH:600001", "甲", self.picked(s), lambda j: 95, 95)
        self.assertEqual(it["status"], "hold")
        self.assertIn("冷热分 95", it["action"])
        it = follow.follow_mid(s, "SH:600001", "甲", self.picked(s), lambda j: 25 if j == s.n - 1 else 95, 25)
        self.assertEqual(it["status"], "sell", "今天刚变热：提醒明天开盘卖")
        self.assertIn("明天开盘卖出", it["action"])

    def test_build_and_attach(self):
        s = stock(self.BASE + [10.0, 10.1, 10.2])
        stocks = {"600001": s}
        picks = [(self.picked(s, 28), "SH:600001", "甲"), (self.picked(s), "SH:600001", "甲"), ("2026-10-01", "SH:600999", "不在池子里")]
        got = follow.build(picks, stocks, follow.follow_short)
        self.assertEqual([x["code"] for x in got["items"]], ["600001", "600999"], "已经拿着的，再入选不重复算")
        self.assertEqual(got["items"][1]["status"], "unknown")
        self.assertEqual(got["summary"]["open"], 1)
        store = Store(None)
        self.addCleanup(store.close)
        store.save_daily({"version": 3, "as_of": self.picked(s, 28), "created_at": "2026-10-28 16:00:00", "strategy": {"key": "boards"},
                          "market": {"regime": {"label": "震荡"}},
                          "boards": {"short": {"name": short.NAME, "picks": [{"key": "SH:600001", "name": "甲"}],
                                               "etfs": {"picks": [{"key": "SH:512100", "name": "中证1000ETF"}]}},
                                     "mid": {"name": "以前的方法", "picks": [{"key": "SH:600001", "name": "甲"}]}}})
        boards = {"short": {}, "mid": {}}
        follow.attach(store, boards, stocks, {}, P.day_text(s.dates[-1]))
        self.assertEqual([x["code"] for x in boards["short"]["following"]["items"]], ["600001"], "一起推荐的 ETF 不跟踪")
        self.assertNotIn("following", boards["mid"], "以前别的方法选出来的不按现在的规则跟踪")
        self.assertEqual(follow.wanted(store, P.day_text(s.dates[-1]), None), [("SH:600001", "甲")])

    def test_outsiders_are_followed(self):
        pool_ = plain_pool(30)
        out = cold_stock("600009", seed=9)                      # 成交缩了、掉出了股票池
        crosses = features.crosses(pool_, [LAST])
        store = Store(None)
        self.addCleanup(store.close)
        picked = P.day_text(out.dates[-4])
        store.save_daily({"version": 3, "as_of": picked, "created_at": picked + " 16:00:00", "strategy": {"key": "boards"},
                          "market": {"regime": {"label": "震荡"}},
                          "boards": {"mid": {"name": mid.NAME, "picks": [{"key": "SH:600009", "name": "冷门"}, {"key": "SH:600008", "name": "退市了"}]}}})
        boards = {"mid": {}}
        follow.attach(store, boards, pool_, crosses, P.day_text(out.dates[-1]), {"600009": out})
        items = {x["code"]: x for x in boards["mid"]["following"]["items"]}
        self.assertEqual(items["600009"]["status"], "hold")
        self.assertIn("冷热分", items["600009"]["action"], "放回池子里估出了冷热分")
        self.assertEqual(items["600008"]["status"], "unknown")


# ── 检验数字 ──────────────────────────────────────────────────────

class EvidenceTest(unittest.TestCase):
    def test_numbers_hold_together(self):
        for w in ("new", "old"):
            rows = evidence.SCORE_TABLE[w]
            self.assertEqual(len(rows), 5)
            self.assertAlmostEqual(sum(r[2] for r in rows), 1.0, delta=0.03, msg="最后几天没有之后 5 天的结果，不算在内")
            self.assertLess(rows[0][3], rows[-1][3], "分数越高，之后 5 天越好")
            self.assertGreater(evidence.SHORT["go"][w]["mean"], evidence.SHORT["everyday"][w]["mean"], "看天出手比每天都买好")
            self.assertGreater(evidence.MID["all"][w]["win"], evidence.MID["old_plan"][w]["win"], "变热才卖比拿满 60 天就卖好")
            self.assertGreater(evidence.MID["all"][w]["mean"], evidence.MID["stop12"][w]["mean"], "加止损反而少赚")
            self.assertLess(evidence.MID["cold"]["hot10_h60"][w]["ex"], 0, "最热的一成跑输")
        s = evidence.TEMP["strategy"]["index"]
        self.assertGreater(s["rule"]["cagr"], s["hold"]["cagr"])
        self.assertIn(f"{s['rule']['trades']} 次", evidence.temp_strategy_text())
        for k, v in evidence.FACTS.items():
            self.assertTrue(v and "None" not in v, k)
        self.assertEqual(evidence.pct(0.0123), "+1.2%")
        self.assertEqual(evidence.pct(-0.0004), "0.0%")
        self.assertEqual(evidence.years([2018, 2023]), "2018、2023 年")


if __name__ == "__main__":
    unittest.main()
