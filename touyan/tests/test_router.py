"""数据路由：降级链、熔断、旧缓存兜底、汇总时的缺项提示。各数据源用替身函数，不联网。"""

import unittest
from unittest import mock

import helpers
from market import net, symbols
from market.cache import Cache
from market.models import FundProfile, Instrument, NewsItem, Quote
from market.net import NoData, RateLimited, SourceError
from market.router import DataRouter


_OPEN: list[Cache] = []


def router(**vendors):
    cache = Cache(None)
    _OPEN.append(cache)
    return DataRouter(cache, kline_vendors=vendors.get("order", ["eastmoney", "tencent"]))


def tearDownModule():
    for cache in _OPEN:
        cache.close()


class KlineChainTest(unittest.TestCase):
    def setUp(self):
        net.reset_bans()
        self.bars = helpers.walk(120, seed=1)

    def test_falls_back_to_tencent_on_rate_limit(self):
        r = router()
        with mock.patch("market.eastmoney.kline", side_effect=RateLimited("限流")), \
                mock.patch("market.tencent.kline", return_value=self.bars) as tx:
            bars, source, _ = r.bars(symbols.parse("600519"), 120)
        self.assertEqual(source, "腾讯证券")
        self.assertEqual(len(bars), 120)
        tx.assert_called_once_with("sh600519", 120)

    def test_cache_hit_avoids_network(self):
        r = router()
        with mock.patch("market.eastmoney.kline", return_value=("贵州茅台", self.bars)) as em:
            r.bars(symbols.parse("600519"), 120)
            r.bars(symbols.parse("600519"), 120)
        self.assertEqual(em.call_count, 1)

    def test_stale_cache_when_everything_fails(self):
        r = router()
        with mock.patch("market.eastmoney.kline", return_value=("贵州茅台", self.bars)):
            r.bars(symbols.parse("600519"), 120)
        with mock.patch("market.router.TTL", {"kline": -1}), \
                mock.patch("market.eastmoney.kline", side_effect=SourceError("断网")), \
                mock.patch("market.tencent.kline", side_effect=SourceError("断网")):
            bars, source, _ = r.bars(symbols.parse("600519"), 120)
        self.assertEqual(len(bars), 120)
        self.assertIn("缓存", source)

    def test_all_fail_message_names_each_source(self):
        r = router()
        with mock.patch("market.eastmoney.kline", side_effect=SourceError("A失败")), \
                mock.patch("market.tencent.kline", side_effect=SourceError("B失败")):
            with self.assertRaises(SourceError) as ctx:
                r.bars(symbols.parse("600519"), 120)
        self.assertIn("东方财富：A失败", str(ctx.exception))
        self.assertIn("腾讯证券：B失败", str(ctx.exception))

    def test_us_secid_tries_exchanges(self):
        r = router()
        calls = []

        def kline(secid, days):
            calls.append(secid)
            if not secid.startswith("106."):
                raise NoData("无")
            return "伯克希尔", self.bars

        with mock.patch("market.eastmoney.search", side_effect=SourceError("搜索不可用")), \
                mock.patch("market.eastmoney.kline", side_effect=kline):
            inst = symbols.parse("BRK.B")
            r.bars(inst, 120)
        self.assertEqual(calls, ["106.BRK_B"], "提示表把纽交所排在第一位")
        self.assertEqual(inst.secid, "106.BRK_B")

    def test_optional_vendors_skipped_when_not_installed(self):
        r = DataRouter(Cache(None), kline_vendors=["akshare", "yfinance", "tencent"])
        self.addCleanup(r.cache.close)
        r._optional = {"akshare": False, "yfinance": False}
        with mock.patch("market.tencent.kline", return_value=self.bars):
            _, source, _ = r.bars(symbols.parse("600519"), 120)
        self.assertEqual(source, "腾讯证券")


class CircuitBreakerTest(unittest.TestCase):
    def setUp(self):
        net.reset_bans()

    def tearDown(self):
        net.reset_bans()

    def test_push2_disconnect_bans_the_group(self):
        import httpx
        with mock.patch.object(net.client(), "get", side_effect=httpx.RemoteProtocolError("Server disconnected")) as get:
            with self.assertRaises(RateLimited):
                net.get("https://push2his.eastmoney.com/api/qt/stock/kline/get")
            self.assertEqual(get.call_count, 1, "限流时不重试")
            with self.assertRaises(RateLimited):
                net.get("https://82.push2.eastmoney.com/api/qt/ulist.np/get")
            self.assertEqual(get.call_count, 1, "熔断期内不再发请求，所有 push2 子域共用")
        self.assertGreater(net.is_banned("eastmoney-push2"), 0)
        self.assertEqual(net.is_banned("qt.gtimg.cn"), 0)

    def test_other_hosts_retry_then_explain(self):
        import httpx
        with mock.patch.object(net.client(), "get", side_effect=httpx.ConnectError("refused")) as get, \
                mock.patch("time.sleep"):
            with self.assertRaises(SourceError) as ctx:
                net.get("https://qt.gtimg.cn/q=sh600519", retries=1)
        self.assertEqual(get.call_count, 2)
        self.assertIn("qt.gtimg.cn", str(ctx.exception))


class LoadTest(unittest.TestCase):
    def setUp(self):
        net.reset_bans()

    def test_stock_load_collects_warnings_not_failures(self):
        r = router()
        bars = helpers.walk(300, seed=2)
        with mock.patch("market.eastmoney.kline", return_value=("贵州茅台", bars)), \
                mock.patch("market.tencent.kline", return_value=helpers.walk(300, 3800, seed=3)), \
                mock.patch("market.eastmoney.quote", return_value=("贵州茅台", Quote(price=1.0, industry="酿酒行业"))), \
                mock.patch("market.eastmoney.financials", side_effect=SourceError("财务接口挂了")), \
                mock.patch("market.news.market_news", side_effect=SourceError("x")), \
                mock.patch("market.news.sina_market_news", return_value=[NewsItem("快讯")]), \
                mock.patch("market.news.company_news", return_value=[NewsItem("新闻")]):
            md = r.load(symbols.parse("600519"))
        self.assertEqual(md.instrument.name, "贵州茅台")
        self.assertEqual(len(md.bars), 300)
        self.assertEqual(len(md.benchmark_bars), 300)
        self.assertEqual(md.company["industry"], "酿酒行业")
        self.assertEqual(md.sources["市场快讯"], "新浪财经7x24")
        self.assertTrue(any("财务数据未取到" in w for w in md.warnings))
        self.assertEqual([n.title for n in md.news], ["新闻"])

    def test_otc_fund_uses_nav_and_fails_loudly(self):
        r = router()
        nav = helpers.walk(400, 1.2, seed=4, nav=True)
        with mock.patch("market.fundem.pingzhong", return_value=(FundProfile(name="样例基金"), nav, [])), \
                mock.patch("market.fundem.danjuan", side_effect=SourceError("蛋卷挂了")), \
                mock.patch("market.fundem.holdings", return_value=("", [])), \
                mock.patch("market.tencent.kline", return_value=helpers.walk(400, 3800, seed=5)), \
                mock.patch("market.news.market_news", return_value=[]), \
                mock.patch("market.news.sina_market_news", return_value=[]):
            md = r.load(Instrument("110011", "OF", "fund"))
        self.assertEqual(md.instrument.name, "样例基金")
        self.assertEqual(md.bars, nav)
        self.assertTrue(any("蛋卷基金" in w for w in md.warnings))
        r2 = router()
        with mock.patch("market.fundem.pingzhong", side_effect=NoData("没有这只基金")), \
                mock.patch("market.tencent.kline", return_value=helpers.walk(400, 3800, seed=5)), \
                mock.patch("market.news.market_news", return_value=[]), \
                mock.patch("market.news.sina_market_news", return_value=[]):
            with self.assertRaises(NoData):
                r2.load(Instrument("999999", "OF", "fund"))

    def test_too_little_history(self):
        r = router()
        with mock.patch("market.eastmoney.kline", return_value=("新股", helpers.walk(10, seed=6))), \
                mock.patch("market.eastmoney.quote", side_effect=SourceError("x")), \
                mock.patch("market.tencent.quote", side_effect=SourceError("x")), \
                mock.patch("market.tencent.kline", return_value=helpers.walk(300, seed=7)), \
                mock.patch("market.eastmoney.financials", return_value=[]):
            with self.assertRaises(NoData):
                r.load(symbols.parse("600519"), with_news=False)

    def test_search_merges_online_and_offline(self):
        r = router()
        online = [Instrument("000001", "SZ", "stock", "平安银行", "0.000001")]
        with mock.patch("market.eastmoney.search", return_value=online), \
                mock.patch("market.fundem.search", side_effect=SourceError("x")):
            hits = r.search("000001")
        self.assertEqual([h.key for h in hits], ["SZ:000001", "SH:000001", "OF:000001"])
        self.assertEqual(hits[0].name, "平安银行")
        with mock.patch("market.eastmoney.search", side_effect=SourceError("x")), \
                mock.patch("market.fundem.search", side_effect=SourceError("x")):
            self.assertEqual(r.search("茅台"), [])
            with self.assertRaises(NoData):
                r.resolve("茅台")


if __name__ == "__main__":
    unittest.main()
