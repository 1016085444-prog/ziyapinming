"""一次性密码（一密一人、八字与紫微互通）核销单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import codes


class TestCodeStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "codes.db"
        self.store = codes.CodeStore(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_generate_unique_and_normalized(self):
        batch = self.store.generate(count=30, note="test")
        self.assertEqual(len(batch), 30)
        self.assertEqual(len(set(batch)), 30)
        for c in batch:
            self.assertTrue(c.startswith("ZY-"))
            self.assertEqual(len(c), 12)
            for bad in "0O1IL":
                self.assertNotIn(bad, c[3:])

        # 大小写与无横杠自动规整
        sample = batch[0]
        compact = sample.replace("-", "").lower()
        self.assertEqual(codes.normalize_code(f"  {compact}  "), sample)
        self.assertEqual(codes.normalize_code(sample[3:].lower()), sample)

    def test_one_code_per_person_lifecycle(self):
        code = self.store.generate(count=1)[0]
        k1, s1 = codes.birth_fingerprint(1995, 8, 15, 14, 30, "female", 121.47, 8.0, True, True, True)
        k2, s2 = codes.birth_fingerprint(1992, 3, 10, 9, 0, "male", 116.41, 8.0, True, True, True)

        # 1. 空码 / 错码拦截
        ok, tag, _ = self.store.verify_and_bind("", k1, s1)
        self.assertFalse(ok)
        self.assertEqual(tag, "missing")

        ok, tag, _ = self.store.verify_and_bind("ZY-AAAA-BBBB", k1, s1)
        self.assertFalse(ok)
        self.assertEqual(tag, "invalid")

        # 2. 首次使用自动绑定
        ok, tag, _ = self.store.verify_and_bind(code.lower().replace("-", ""), k1, s1)
        self.assertTrue(ok)
        self.assertEqual(tag, "bound_new")

        # 3. 同一密码 + 同一生辰（例如切紫微页或刷新重看）放行
        ok, tag, _ = self.store.verify_and_bind(code, k1, s1)
        self.assertTrue(ok)
        self.assertEqual(tag, "bound_same")

        # 4. 同一密码 + 换另一个生辰：必须拒绝
        ok, tag, msg = self.store.verify_and_bind(code, k2, s2)
        self.assertFalse(ok)
        self.assertEqual(tag, "mismatch")
        self.assertIn("一人", msg)

        # 5. 停用后拒绝
        self.assertTrue(self.store.set_disabled(code, True))
        ok, tag, _ = self.store.verify_and_bind(code, k1, s1)
        self.assertFalse(ok)
        self.assertEqual(tag, "disabled")

        # 6. 解绑重测（客服救急）后可重新绑定新人
        self.assertTrue(self.store.reset_code(code))
        ok, tag, _ = self.store.verify_and_bind(code, k2, s2)
        self.assertTrue(ok)
        self.assertEqual(tag, "bound_new")


if __name__ == "__main__":
    unittest.main()


class TestClaimForOrder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = codes.CodeStore(Path(self._tmp.name) / "codes.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_same_order_same_code(self):
        c1, new1 = codes.claim_for_order(self.store, "P123456789012345678")
        c2, new2 = codes.claim_for_order(self.store, "P123456789012345678")
        self.assertEqual(c1, c2)
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(self.store.stats()["total"], 1)

    def test_order_id_prefix_does_not_collide(self):
        c1, _ = codes.claim_for_order(self.store, "P1234567890")
        c2, _ = codes.claim_for_order(self.store, "P12345678901")
        self.assertNotEqual(c1, c2)

    def test_concurrent_claims_issue_one_code(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            got = set(ex.map(lambda _: codes.claim_for_order(self.store, "P999999999999")[0], range(16)))
        self.assertEqual(len(got), 1)
        self.assertEqual(self.store.stats()["total"], 1)
