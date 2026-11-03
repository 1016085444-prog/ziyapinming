import unittest

import helpers  # noqa: F401  — 隔离数据目录
from market import symbols


class ParseTest(unittest.TestCase):
    def check(self, text, key, kind, secid="", kind_hint="auto"):
        inst = symbols.parse(text, kind_hint)
        self.assertIsNotNone(inst, text)
        self.assertEqual((inst.key, inst.kind, inst.secid), (key, kind, secid), text)

    def test_a_share_forms(self):
        for text in ("600519", "sh600519", "SH.600519", "600519.SH", "600519.SS", " 600519 "):
            self.check(text, "SH:600519", "stock", "1.600519")
        self.check("000001", "SZ:000001", "stock", "0.000001")
        self.check("300750", "SZ:300750", "stock", "0.300750")
        self.check("688981", "SH:688981", "stock", "1.688981")
        self.check("830799", "BJ:830799", "stock", "0.830799")
        self.check("920019", "BJ:920019", "stock", "0.920019")

    def test_fullwidth_input(self):
        self.check("６００５１９", "SH:600519", "stock", "1.600519")
        self.check("００７００", "HK:00700", "stock", "116.00700")

    def test_exchange_funds_and_indices(self):
        self.check("510300", "SH:510300", "etf", "1.510300")
        self.check("159915", "SZ:159915", "etf", "0.159915")
        self.check("508000", "SH:508000", "etf", "1.508000")
        self.check("sh000001", "SH:000001", "index", "1.000001")
        self.check("399006", "SZ:399006", "index", "0.399006")
        self.check("沪深300", "SH:000300", "index", "1.000300")
        self.check("恒生指数", "GI:HSI", "index", "100.HSI")
        self.check("SPX", "GI:SPX", "index", "100.SPX")

    def test_otc_funds(self):
        self.check("110011", "OF:110011", "fund")
        self.check("005827", "OF:005827", "fund")
        self.check("of000001", "OF:000001", "fund")
        self.check("000001.OF", "OF:000001", "fund")
        self.check("510300", "OF:510300", "fund", kind_hint="fund")

    def test_hk_and_us(self):
        for text in ("00700", "700.HK", "hk700", "HK.00700", "0700.hk"):
            self.check(text, "HK:00700", "stock", "116.00700")
        self.check("AAPL", "US:AAPL", "stock")
        self.check("brk.b", "US:BRK.B", "stock")
        self.check("us.TSLA", "US:TSLA", "stock")
        self.check("SPY", "US:SPY", "etf", kind_hint="etf")
        self.assertEqual(symbols.parse("AAPL").currency, "USD")

    def test_kind_hint_overrides(self):
        self.check("000300", "SH:000300", "index", "1.000300", kind_hint="index")
        self.check("000001", "SZ:000001", "stock", "0.000001", kind_hint="stock")

    def test_names_are_left_to_search(self):
        self.assertIsNone(symbols.parse("茅台"))
        self.assertIsNone(symbols.parse(""))
        self.assertIsNone(symbols.parse("../../etc/passwd"))

    def test_alternatives_for_ambiguous_code(self):
        keys = [i.key for i in symbols.alternatives("000001")]
        self.assertEqual(keys, ["SZ:000001", "SH:000001", "OF:000001"])

    def test_from_key_roundtrip_and_safety(self):
        for key in ("SH:600519", "SZ:000001", "HK:00700", "US:AAPL", "OF:110011", "GI:HSI", "SH:510300"):
            self.assertEqual(symbols.from_key(key).key, key)
        self.assertEqual(symbols.from_key("SH:000300").kind, "index")
        for bad in ("SH:../../x", "XX:600519", "SH:60051", "US:<script>", "OF:abc", ":"):
            self.assertIsNone(symbols.from_key(bad), bad)
        self.assertEqual(symbols.from_key("US:AAPL", secid="105.AAPL").secid, "105.AAPL")
        self.assertEqual(symbols.from_key("US:AAPL", secid="1.0;DROP").secid, "")


class MappingTest(unittest.TestCase):
    def test_us_candidates_use_hints(self):
        self.assertEqual(symbols.us_secid_candidates("AAPL")[0], "105.AAPL")
        self.assertEqual(symbols.us_secid_candidates("BRK.B")[0], "106.BRK_B")
        self.assertEqual(symbols.us_secid_candidates("SPY")[0], "107.SPY")
        self.assertEqual(len(set(symbols.us_secid_candidates("XYZ"))), 3)

    def test_tencent_symbols(self):
        self.assertEqual(symbols.tencent_symbol(symbols.parse("600519")), "sh600519")
        self.assertEqual(symbols.tencent_symbol(symbols.parse("700.HK")), "hk00700")
        self.assertEqual(symbols.tencent_symbol(symbols.parse("BRK.B")), "usBRK_B")
        self.assertEqual(symbols.tencent_symbol(symbols.parse("110011")), "")

    def test_benchmarks(self):
        self.assertEqual(symbols.benchmark_for(symbols.parse("600519")).name, "沪深300")
        self.assertEqual(symbols.benchmark_for(symbols.parse("110011")).name, "沪深300")
        self.assertEqual(symbols.benchmark_for(symbols.parse("00700")).name, "恒生指数")
        self.assertEqual(symbols.benchmark_for(symbols.parse("AAPL")).name, "标普500")

    def test_search_item_mapping(self):
        f = symbols.from_search_item
        a = f({"Code": "600519", "Name": "贵州茅台", "QuoteID": "1.600519", "Classify": "AStock", "SecurityTypeName": "沪A"})
        self.assertEqual((a.key, a.name, a.secid), ("SH:600519", "贵州茅台", "1.600519"))
        b = f({"Code": "830799", "Name": "艾融软件", "QuoteID": "0.830799", "Classify": "AStock", "SecurityTypeName": "京A"})
        self.assertEqual(b.key, "BJ:830799")
        hk = f({"Code": "00700", "Name": "腾讯控股", "QuoteID": "116.00700", "Classify": "HK", "SecurityTypeName": "港股"})
        self.assertEqual((hk.key, hk.currency), ("HK:00700", "HKD"))
        us = f({"Code": "AAPL", "Name": "苹果", "QuoteID": "105.AAPL", "Classify": "UsStock", "SecurityTypeName": "美股"})
        self.assertEqual((us.key, us.secid), ("US:AAPL", "105.AAPL"))
        etf = f({"Code": "510300", "Name": "沪深300ETF", "QuoteID": "1.510300", "Classify": "Fund", "SecurityTypeName": "基金"})
        self.assertEqual((etf.key, etf.kind), ("SH:510300", "etf"))
        of = f({"Code": "110011", "Name": "易方达", "QuoteID": "150.110011", "Classify": "Fund", "SecurityTypeName": "基金"})
        self.assertEqual(of.key, "OF:110011")
        self.assertIsNone(f({"Code": "IF2512", "Name": "期货", "QuoteID": "8.IF2512", "Classify": "Futures"}))


if __name__ == "__main__":
    unittest.main()
