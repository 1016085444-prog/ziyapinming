"""全市场数据：A 股快照（三个来源）、行业板块、开放式基金排行的解析，以及降级与缓存。"""

import json
import unittest
from unittest import mock

import helpers  # noqa: F401
from market import universe as U
from market.cache import Cache
from market.net import SourceError


class ParseTest(unittest.TestCase):
    def test_datacenter(self):
        payload = {"success": True, "result": {"count": 3, "data": [
            {"SECUCODE": "600519.SH", "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台", "NEW_PRICE": 1500.5,
             "CHANGE_RATE": 1.2, "VOLUME_RATIO": 0.9, "DEAL_AMOUNT": 5.2e9, "TURNOVERRATE": 0.4, "PE9": 22.1,
             "PBNEWMRQ": 7.5, "TOTAL_MARKET_CAP": 1.88e12, "CIRCULATION_MARKET_CAP": 1.88e12},
            {"SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行", "NEW_PRICE": None},     # 停牌
            {"SECURITY_CODE": "510300", "SECURITY_NAME_ABBR": "沪深300ETF", "NEW_PRICE": 4.0},  # 不是股票
        ]}}
        rows, total = U.parse_datacenter(payload)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["code"], r["market"], r["name"]), ("600519", "SH", "贵州茅台"))
        self.assertEqual((r["pe"], r["pb"], r["amount"], r["volume_ratio"]), (22.1, 7.5, 5.2e9, 0.9))
        with self.assertRaises(SourceError):
            U.parse_datacenter({"success": False, "message": "频繁"})

    def test_clist_and_sina(self):
        payload = {"data": {"total": 2, "diff": [
            {"f12": "300750", "f14": "宁德时代", "f2": 250.0, "f3": -1.5, "f6": 8e9, "f8": 1.1, "f9": 25.0,
             "f10": 1.3, "f20": 1.1e12, "f21": 1e12, "f23": 5.1, "f24": 12.0, "f25": 30.0, "f100": "电池"},
            {"f12": "830799", "f14": "艾融软件", "f2": "-", "f3": "-"},
        ]}}
        rows, total = U.parse_clist_stocks(payload)
        self.assertEqual((total, len(rows)), (2, 1))
        self.assertEqual((rows[0]["market"], rows[0]["industry"], rows[0]["change_60d"]), ("SZ", "电池", 12.0))
        sina = U.parse_sina([{"symbol": "bj430047", "code": "430047", "name": "诺思兰德", "trade": "12.50",
                              "changepercent": "2.1", "amount": "50000000", "turnoverratio": "3.2", "per": "-15",
                              "pb": "4.4", "mktcap": "345000", "nmc": "200000"}])
        self.assertEqual(sina[0]["market"], "BJ")
        self.assertEqual(sina[0]["total_mv"], 345000 * 10000)     # 万元 → 元
        self.assertEqual(sina[0]["pe"], -15)
        self.assertNotIn("volume_ratio", sina[0], "新浪没有量比，打分时不能当成 1")

    def test_boards(self):
        payload = {"data": {"total": 3, "diff": [
            {"f12": "BK0475", "f14": "银行", "f3": -0.5, "f104": 10, "f105": 30, "f128": "招商银行", "f136": 1.2},
            {"f12": "BK1036", "f14": "半导体", "f3": 3.2, "f104": 120, "f105": 8, "f128": "寒武纪", "f136": 10.0},
            {"f12": "BK0000", "f14": "", "f3": 1.0},
        ]}}
        boards = U.parse_boards(payload)
        self.assertEqual([b["name"] for b in boards], ["半导体", "银行"])
        self.assertEqual(boards[0]["leader"], "寒武纪")

    def test_fund_rank(self):
        line = ("110011,易方达优质精选混合(QDII),YFDYZJXHHQDII,2026-11-07,4.7770,6.1530,0.53,1.46,1.91,-1.39,"
                "1.27,9.69,26.21,31.80,2.73,624.35,2008-03-24,1,-9.48,1.50%,0.15%,1,0.15%,1,-0.93")
        bad = "abc,坏数据"
        text = "var rankData = {datas:" + json.dumps([line, bad], ensure_ascii=False) + \
               ",allRecords:2,pageIndex:1,pageNum:20000,allPages:1,allNum:2,gpNum:0};"
        rows = U.parse_fund_rank(text, "qdii")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["code"], r["inception"], r["fee"], r["type"]), ("110011", "2008-03-24", "0.15%", "QDII"))
        self.assertEqual((r["m6"], r["y1"], r["y2"], r["y3"], r["ytd"]), (1.27, 9.69, 26.21, 31.80, 2.73))
        with self.assertRaises(SourceError):
            U.parse_fund_rank("<html>维护中</html>")


class SnapshotFallbackTest(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(None)
        self.addCleanup(self.cache.close)

    def rows(self, n):
        return [{"code": f"{600000 + i}", "market": "SH", "name": f"股票{i}", "price": 10.0} for i in range(n)]

    def test_fallback_order_and_cache(self):
        calls = []

        def fail(label):
            def f():
                calls.append(label)
                raise SourceError("连不上")
            return f

        def short():
            calls.append("short")
            return self.rows(10)

        def good():
            calls.append("good")
            return self.rows(2500)

        with mock.patch.object(U, "STOCK_SOURCES", (("A", fail("A")), ("B", short), ("C", good))):
            rows, source, warnings = U.a_share_snapshot(self.cache)
            self.assertEqual((len(rows), source, warnings), (2500, "C", []))
            self.assertEqual(calls, ["A", "short", "good"])
            U.a_share_snapshot(self.cache)
            self.assertEqual(len(calls), 3, "缓存命中时不再请求")

    def test_stale_cache_when_all_fail(self):
        self.cache.set("universe:a-share", {"rows": self.rows(2100), "source": "旧"})
        with mock.patch.object(self.cache, "get", return_value=None), \
                mock.patch.object(U, "STOCK_SOURCES", (("A", mock.Mock(side_effect=SourceError("x"))),)):
            rows, source, warnings = U.a_share_snapshot(self.cache)
        self.assertEqual((len(rows), source), (2100, "旧"))
        self.assertIn("小时前", warnings[0])
        with mock.patch.object(U, "STOCK_SOURCES", (("A", mock.Mock(side_effect=SourceError("x"))),)):
            empty = Cache(None)
            self.addCleanup(empty.close)
            with self.assertRaises(SourceError):
                U.a_share_snapshot(empty)


if __name__ == "__main__":
    unittest.main()
