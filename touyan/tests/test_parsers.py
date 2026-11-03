"""数据源解析：样例响应按各接口的实际格式构造（格式参照 akshare 1.20.x 的解析代码）。"""

import json
import unittest

import helpers  # noqa: F401
from market import csvfile, eastmoney, fundem, news, tencent
from market.net import NoData


class EastmoneyTest(unittest.TestCase):
    def test_kline_field_order_and_bad_rows(self):
        payload = {"data": {"name": "贵州茅台", "klines": [
            "2026-10-29,1800.00,1750.50,1820.00,1740.10,80000,14000000000.00,4.44,-2.75,-49.50,0.64",
            "2026-10-30,1750.00,-,1760.00,1740.00,1,2,3,4,5,6",          # 缺收盘：跳过
            "2026-10-31,1750.50,1760.00,1770.00,1745.00,50000",          # 字段少：照样能读
        ]}}
        name, bars = eastmoney.parse_kline(payload)
        self.assertEqual(name, "贵州茅台")
        self.assertEqual(len(bars), 2)
        b = bars[0]
        self.assertEqual((b.date, b.open, b.close, b.high, b.low, b.volume, b.amount, b.turnover),
                         ("2026-10-29", 1800.0, 1750.5, 1820.0, 1740.1, 80000.0, 1.4e10, 0.64))
        self.assertIsNone(bars[1].turnover)
        with self.assertRaises(NoData):
            eastmoney.parse_kline({"data": None})

    def test_quote_fields_and_beijing_time(self):
        payload = {"data": {"diff": [{"f2": 1750.5, "f3": -2.75, "f4": -49.5, "f8": 0.64, "f9": 25.3, "f12": "600519",
                                       "f14": "贵州茅台", "f20": 2.2e12, "f21": 2.2e12, "f23": 8.1, "f100": "酿酒行业",
                                       "f124": 1761894000, "f15": "-"}]}}
        name, q = eastmoney.parse_quote(payload)
        self.assertEqual((name, q.price, q.pe, q.pb, q.industry), ("贵州茅台", 1750.5, 25.3, 8.1, "酿酒行业"))
        self.assertIsNone(q.high, "'-' 是缺失，不是 0")
        self.assertEqual(q.time, "2025-10-31 15:00")
        dict_form = {"data": {"diff": {"0": {"f2": 1.0, "f14": "x"}}}}
        self.assertEqual(eastmoney.parse_quote(dict_form)[1].price, 1.0)

    def test_search(self):
        payload = {"QuotationCodeTable": {"Data": [
            {"Code": "600519", "Name": "贵州茅台", "QuoteID": "1.600519", "Classify": "AStock", "SecurityTypeName": "沪A"},
            {"Code": "X1", "Name": "期货", "QuoteID": "8.X1", "Classify": "Futures", "SecurityTypeName": "期货"},
        ]}}
        hits = eastmoney.parse_search(payload)
        self.assertEqual([h.key for h in hits], ["SH:600519"])

    def test_financials_candidate_columns(self):
        a_share = {"result": {"data": [
            {"REPORT_DATE": "2026-06-30 00:00:00", "REPORT_DATE_NAME": "2026中报", "TOTALOPERATEREVE": 8e10, "TOTALOPERATEREVETZ": 18.0,
             "PARENTNETPROFIT": 4e10, "PARENTNETPROFITTZ": 16.0, "ROEJQ": 18.0, "XSMLL": 91.0, "XSJLL": 51.0, "ZCFZL": 20.0, "EPSJB": 32.0},
            {"REPORT_DATE": "2026-09-30 00:00:00", "REPORT_DATE_NAME": "2026三季报", "ROEJQ": 26.1, "TOTALOPERATEREVETZ": "-"},
        ]}}
        periods = eastmoney.parse_financials(a_share)
        self.assertEqual([p.report_date for p in periods], ["2026-09-30", "2026-06-30"], "新的在前")
        self.assertIsNone(periods[0].revenue_yoy)
        self.assertEqual((periods[1].roe, periods[1].gross_margin, periods[1].eps), (18.0, 91.0, 32.0))
        hk = {"result": {"data": [{"STD_REPORT_DATE": "2025-12-31", "OPERATE_INCOME_YOY": 10.0, "HOLDER_PROFIT_YOY": 12.0,
                                   "ROE_AVG": 20.0, "GROSS_PROFIT_RATIO": 50.0, "DEBT_ASSET_RATIO": 40.0, "BASIC_EPS": 2.1}]}}
        p = eastmoney.parse_financials(hk)[0]
        self.assertEqual((p.revenue_yoy, p.net_profit_yoy, p.roe, p.gross_margin, p.debt_ratio), (10.0, 12.0, 20.0, 50.0, 40.0))

    def test_num_never_fakes_zero(self):
        for missing in (None, "-", "", "--", "nan", True):
            self.assertIsNone(eastmoney.num(missing))
        self.assertEqual(eastmoney.num("1,234.5"), 1234.5)
        self.assertEqual(eastmoney.num("12.5%"), 12.5)
        self.assertEqual(eastmoney.num(0), 0.0)


class TencentTest(unittest.TestCase):
    def test_kline_text(self):
        text = ('kline_dayqfq2026={"code":0,"msg":"","data":{"sh600519":{"qfqday":['
                '["2026-10-29","1800.000","1750.500","1820.000","1740.100","80000.000",{"nd":"2026"},"0.64","1400000.00"],'
                '["2026-10-30","1750","1760","1770","1740","50000"]],"qt":{}}}}')
        bars = tencent.parse_kline_text(text, "sh600519")
        self.assertEqual((bars[0].close, bars[0].volume, bars[0].turnover, bars[0].amount), (1750.5, 80000.0, 0.64, 1.4e10))
        self.assertIsNone(bars[1].amount)

    def test_star_market_volume_normalized_to_lots(self):
        text = 'x={"data":{"sh688981":{"qfqday":[["2026-10-29","10","11","12","9","500000"]]}}}'
        self.assertEqual(tencent.parse_kline_text(text, "sh688981")[0].volume, 5000.0)

    def test_index_uses_day_key(self):
        text = 'x={"data":{"sh000300":{"day":[["2026-10-29","3800","3810","3820","3790","1000000"]]}}}'
        self.assertEqual(tencent.parse_kline_text(text, "sh000300")[0].close, 3810.0)

    def test_quote_text(self):
        fields = ["1", "贵州茅台", "600519", "1750.50", "1800.00", "1800.00", "80000"] + ["0"] * 23
        fields += ["20261030150003", "-49.50", "-2.75", "1820.00", "1740.10", "x", "80000", "140000", "0.64", "25.30",
                   "", "1820", "1740", "4.44", "21990.00", "21990.00", "8.10"]
        text = 'v_sh600519="' + "~".join(fields) + '";'
        name, q = tencent.parse_quote_text(text, "sh600519")
        self.assertEqual((name, q.price, q.change_pct, q.high, q.low, q.pe, q.pb), ("贵州茅台", 1750.5, -2.75, 1820.0, 1740.1, 25.3, 8.1))
        self.assertEqual(q.total_cap, 21990.0 * 1e8)
        self.assertEqual(q.time, "2026-10-30 15:00")
        with self.assertRaises(NoData):
            tencent.parse_quote_text('v_sh600519="";', "sh600519")

    def test_segments_cover_window(self):
        segs = tencent._segments(800)
        self.assertGreaterEqual(len(segs), 2)
        for a, b in zip(segs, segs[1:]):
            self.assertLess(a[1], b[0])


PINGZHONG = '''/*基金*/var ishb=false;var fS_name = "样例混合";var fS_code = "110011";var fund_sourceRate="1.50";var fund_Rate="0.15";
var stockCodesNew =["1.600519","0.000858"];/*收益率*/var syl_1n="12.34";var syl_6y="5.6";var syl_3y="-1.2";var syl_1y="";
var Data_fundSharesPositions = [[1727625600000,88.5]];
var Data_netWorthTrend = [{"x":1727625600000,"y":1.5,"equityReturn":0,"unitMoney":""},{"x":1727712000000,"y":1.53,"equityReturn":2.0,"unitMoney":""},{"x":1727798400000,"y":1.43,"equityReturn":0.5,"unitMoney":"分红：每份派现金0.1080元"}];
var Data_fluctuationScale = {"categories":["2026-06-30","2026-09-30"],"series":[{"y":30.5,"mom":"-2%"},{"y":31.2,"mom":"2.3%"}]};
var Data_assetAllocation = {"series":[{"name":"股票占净比","data":[85.1,88.2]},{"name":"现金占净比","data":[10.0,8.1]},{"name":"净资产","data":[30,31]}],"categories":["2026-06-30","2026-09-30"]};
var Data_rateInSimilarType = [{"x":1727798400000,"y":120,"sc":"4000"}];
var Data_performanceEvaluation = {"avr":"60","categories":["选证能力","收益率"],"data":[80,70]};
var Data_currentFundManager =[{"id":"1","name":"张坤","workTime":"12年又35天","fundSize":"500.00亿(4只基金)"},{"name":"李四","workTime":"200天"}] ;
var swithSameType = [['a','b']];'''


class FundTest(unittest.TestCase):
    def test_js_vars_skip_non_json(self):
        v = fundem.parse_js_vars(PINGZHONG)
        self.assertEqual(v["fS_name"], "样例混合")
        self.assertIs(v["ishb"], False)
        self.assertNotIn("swithSameType", v)

    def test_profile(self):
        p = fundem.profile_from_js(fundem.parse_js_vars(PINGZHONG))
        self.assertEqual((p.name, p.fee_rate, p.fee_rate_original, p.scale, p.scale_date), ("样例混合", 0.15, 1.5, 31.2, "2026-09-30"))
        self.assertEqual(p.returns, {"3m": -1.2, "6m": 5.6, "1y": 12.34})
        self.assertEqual(p.allocation, {"股票": 88.2, "现金": 8.1})
        self.assertEqual((p.rank, p.rank_total, p.rank_beat_pct), (120, 4000, 97.0))
        self.assertEqual([(m.name, m.tenure_years) for m in p.managers], [("张坤", 12.1), ("李四", 0.55)])

    def test_nav_adjusted_for_dividend(self):
        bars = fundem.nav_bars(fundem.parse_js_vars(PINGZHONG))
        self.assertEqual([b.date for b in bars], ["2024-09-30", "2024-10-01", "2024-10-02"], "按北京时间取日期")
        self.assertEqual(bars[2].close, 1.43)
        self.assertAlmostEqual(bars[2].adj, 1.5 * 1.02 * 1.005)

    def test_money_fund_income_index(self):
        js = {"Data_netWorthTrend": [], "Data_millionCopiesIncome": [[1727625600000, 0.5], [1727712000000, 0.6]]}
        bars = fundem.nav_bars(js)
        self.assertAlmostEqual(bars[-1].close, (1 + 0.5 / 1e4) * (1 + 0.6 / 1e4))

    def test_holdings_html(self):
        content = ("<div class='box'><h4 class='t'>样例&nbsp;&nbsp;2026年3季度股票投资明细</h4><table><thead><tr><th>序号</th></tr></thead><tbody>"
                   "<tr><td>1</td><td><a href='x'>600519</a></td><td class='tol'><a href='y'>贵州茅台</a></td><td>相关资讯</td>"
                   "<td class='tor'>9.87%</td><td>100</td><td>1,000</td></tr>"
                   "<tr><td>2</td><td>000858</td><td>五粮液</td><td class='tor'>5.01%</td></tr></tbody></table></div>")
        text = 'var apidata={ content:"' + content + '",arryear:[2026,2025],curyear:2026};'
        period, rows = fundem.parse_holdings(text)
        self.assertEqual(period, "2026年3季度")
        self.assertEqual([(h.code, h.name, h.weight) for h in rows], [("600519", "贵州茅台", 9.87), ("000858", "五粮液", 5.01)])

    def test_fund_search(self):
        payload = {"Datas": [{"CODE": "110011", "NAME": "易方达优质精选", "CATEGORYDESC": "基金"},
                             {"CODE": "BK001", "NAME": "板块", "CATEGORYDESC": "板块"}]}
        self.assertEqual([i.key for i in fundem.parse_fund_search(payload)], ["OF:110011"])

    def test_danjuan_merge_keeps_existing(self):
        p = fundem.profile_from_js(fundem.parse_js_vars(PINGZHONG))
        fundem.merge_danjuan(p, {"fund_type": "混合型", "company": "易方达", "manager": "王五"})
        self.assertEqual((p.fund_type, p.company), ("混合型", "易方达"))
        self.assertEqual(p.managers[0].name, "张坤", "已有经理信息不被覆盖")


class NewsTest(unittest.TestCase):
    def test_company_news_jsonp(self):
        body = {"result": {"cmsArticleWebOld": [
            {"title": "<em>贵州茅台</em>发布公告", "content": "内容<em>摘要</em>", "date": "2026-10-30 18:00:00", "mediaName": "证券时报", "code": "202610301"},
            {"title": "", "content": "x"}]}}
        items = news.parse_company_news("jQuery351_1(" + json.dumps(body, ensure_ascii=False) + ")")
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].title, items[0].summary, items[0].time), ("贵州茅台发布公告", "内容摘要", "2026-10-30 18:00"))
        self.assertTrue(items[0].url.startswith("https://finance.eastmoney.com/a/"))

    def test_fast_news_and_sina(self):
        fast = {"data": {"fastNewsList": [{"title": "快讯", "summary": "摘要", "showTime": "2026-10-30 09:30:00", "code": "1"}]}}
        self.assertEqual(news.parse_fast_news(fast)[0].title, "快讯")
        sina = {"result": {"data": {"feed": {"list": [{"rich_text": "新浪快讯内容" * 20, "create_time": "2026-10-30 09:31:00"}]}}}}
        item = news.parse_sina_feed(sina)[0]
        self.assertTrue(item.title.endswith("…"))


class CSVTest(unittest.TestCase):
    def rows(self, n=30):
        return [f"2026-{9 + (i // 28):02d}-{(i % 28) + 1:02d},{1 + i * 0.01:.4f}" for i in range(n)]

    def test_chinese_headers_gbk(self):
        raw = ("日期,单位净值\n" + "\n".join(self.rows())).encode("gbk")
        bars = csvfile.parse_csv(raw)
        self.assertEqual(len(bars), 30)
        self.assertTrue(all(b.open == b.close for b in bars))

    def test_ohlc_and_tab_separated(self):
        lines = ["date\topen\thigh\tlow\tclose\tvolume"] + [f"2026/10/{i + 1:02d}\t10\t11\t9\t10.5\t100" for i in range(25)]
        bars = csvfile.parse_csv("\n".join(lines).encode())
        self.assertEqual((bars[0].date, bars[0].high, bars[0].volume), ("2026-10-01", 11.0, 100.0))

    def test_errors(self):
        with self.assertRaises(csvfile.CSVError):
            csvfile.parse_csv("名称,数值\na,1\n".encode())
        with self.assertRaises(csvfile.CSVError):
            csvfile.parse_csv(("日期,收盘\n" + "\n".join(self.rows(5))).encode())
        with self.assertRaises(csvfile.CSVError):
            csvfile.parse_csv(b"x" * (csvfile.MAX_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
