import unittest

import helpers  # noqa: F401
from agents import rating
from agents.pipeline import parse_final, parse_trader


class RatingTest(unittest.TestCase):
    def test_json_block_wins(self):
        text = "评级：持有\n……\n```json\n{\"rating\": \"Overweight\", \"summary\": \"x\"}\n```"
        self.assertEqual(rating.extract_rating(text), "Overweight")

    def test_labelled_lines_in_chinese_and_english(self):
        self.assertEqual(rating.extract_rating("**评级**：买入\n理由……"), "Buy")
        self.assertEqual(rating.extract_rating("- **最终评级**：增持（Overweight）"), "Overweight")
        self.assertEqual(rating.extract_rating("Rating: Sell"), "Sell")
        self.assertEqual(rating.extract_rating("## 评级 — 减持"), "Underweight")

    def test_unlabelled_prose_is_not_a_call(self):
        """正文里的评级词可能是反驳（「不是卖出」），读出来就是没人做过的判断（TradingAgents #1170）。"""
        self.assertIsNone(rating.extract_rating("我们认为现在不是卖出的时机，也谈不上买入。"))
        self.assertEqual(rating.parse_rating("没有结论"), rating.REVIEW)

    def test_conflicting_labels_are_review(self):
        self.assertIsNone(rating.extract_rating("评级：买入\n……\n评级：卖出"))

    def test_trader_action(self):
        self.assertEqual(rating.normalize_action("Buy"), "Buy")
        self.assertEqual(rating.normalize_action("持有/观望"), "Hold")
        self.assertIsNone(rating.normalize_action("加仓吧"))

    def test_price_coercion(self):
        f = rating.to_float
        self.assertEqual(f("¥1,234.5"), 1234.5)
        self.assertEqual(f("$189.50"), 189.5)
        self.assertEqual(f(160), 160.0)
        for bad in ("15%", "N/A", "150-160", "约150", "", None, "未提供", -3, True, float("nan")):
            self.assertIsNone(f(bad), repr(bad))

    def test_strip_json_block(self):
        self.assertEqual(rating.strip_json_block("正文\n```json\n{\"a\": 1}\n```"), "正文")


class ParseDecisionTest(unittest.TestCase):
    def test_trader_grounding_warnings(self):
        t = parse_trader("```json\n{\"action\": \"Buy\", \"entry_price\": 100, \"stop_loss\": 105, \"take_profit\": 95}\n```", 100)
        self.assertEqual(t["action"], "Buy")
        joined = "；".join(t["warnings"])
        self.assertIn("止损价不低于现价", joined)
        self.assertIn("目标价不高于现价", joined)
        far = parse_trader("```json\n{\"action\": \"Buy\", \"entry_price\": 300}\n```", 100)
        self.assertTrue(any("相差超过 50%" in w for w in far["warnings"]))

    def test_trader_fallback_to_label(self):
        t = parse_trader("**操作**：卖出\n理由……", 100)
        self.assertEqual((t["action"], t["label"]), ("Sell", "卖出"))
        self.assertEqual(parse_trader("说不清", 100)["action"], rating.REVIEW)

    def test_final_decision(self):
        text = "**评级**：买入\n```json\n{\"rating\": \"Buy\", \"price_target\": \"118.5\", \"confidence\": \"很高\", \"time_horizon\": \"6个月\"}\n```"
        f = parse_final(text)
        self.assertEqual((f["rating"], f["label"], f["price_target"], f["time_horizon"]), ("Buy", "买入", 118.5, "6个月"))
        self.assertEqual(f["confidence"], "", "不在 高/中/低 里的信心值丢弃")
        self.assertEqual(parse_final("看情况")["rating"], rating.REVIEW)


if __name__ == "__main__":
    unittest.main()
