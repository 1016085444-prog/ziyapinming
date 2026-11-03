"""HTTP 接口：访问控制、快速分析、对比、导入、深度分析任务（SSE）、历史与设置。

数据源与大模型都用替身；TestClient 默认以「远程客户端」身份访问，
用 client=("127.0.0.1", …) 模拟本机。
"""

import base64
import json
import unittest
from unittest import mock

import helpers
from helpers import DECISION_REPLIES, FakeLLM, fund_md, stock_md

import app as A  # noqa: E402  helpers 必须先导入（隔离数据目录）
from fastapi.testclient import TestClient
from market.net import NoData, SourceError

LOCAL = ("127.0.0.1", 50000)


def fake_load(inst, days=800, with_news=True):
    md = fund_md() if inst.market == "OF" else stock_md()
    md.instrument = inst
    inst.name = inst.name or md.instrument.name or "样例"
    return md


def tearDownModule():
    A.cache.close()
    A.store.close()


class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [
            mock.patch.object(A.router, "load", side_effect=fake_load),
            mock.patch.object(A.router, "series", side_effect=lambda inst, days=800: (fake_load(inst).bars, "测试")),
            mock.patch.object(A.router, "search", return_value=[helpers.symbols.parse("600519")]),
            mock.patch.object(A.router, "load_csv", side_effect=lambda name, bars, cur="CNY", with_benchmark=True:
                              A.DataRouter.load_csv(A.router, name, bars, cur, with_benchmark=False)),
            mock.patch.object(A, "make_llm", side_effect=lambda cfg: FakeLLM(cfg.model, DECISION_REPLIES)),
        ]
        for p in cls.patches:
            p.start()
        cls.local = TestClient(A.app, client=LOCAL)
        cls.remote = TestClient(A.app)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def configure_llm(self):
        r = self.local.post("/api/settings", json={"provider": "deepseek", "api_key": "sk-secret-1234567890"})
        self.assertEqual(r.status_code, 200)

    # ── 基础与快速分析 ──
    def test_health_and_config(self):
        self.assertEqual(self.remote.get("/api/health").json()["ok"], True)
        cfg = self.local.get("/api/config").json()
        self.assertTrue(cfg["trusted"])
        self.assertFalse(self.remote.get("/api/config").json()["trusted"])

    def test_analyze(self):
        r = self.remote.get("/api/analyze", params={"key": "SH:600519"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["instrument"]["key"], "SH:600519")
        self.assertIn("chart", body)
        self.assertIn("scores", body)
        self.assertEqual(self.remote.get("/api/analyze", params={"q": "110011"}).json()["kind"], "fund")
        self.assertEqual(self.remote.get("/api/analyze", params={"key": "SH:../../x"}).status_code, 400)
        self.assertEqual(self.remote.get("/api/analyze").status_code, 400)

    def test_analyze_errors_map_to_status(self):
        with mock.patch.object(A.router, "load", side_effect=NoData("没有这个代码")):
            r = self.remote.get("/api/analyze", params={"key": "SH:600000"})
            self.assertEqual((r.status_code, r.json()["error"]), (404, "没有这个代码"))
        with mock.patch.object(A.router, "load", side_effect=SourceError("东方财富：断网")):
            self.assertEqual(self.remote.get("/api/analyze", params={"key": "SH:600000"}).status_code, 502)

    def test_markdown_export(self):
        r = self.remote.get("/api/analyze/markdown", params={"key": "SH:600519"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("量化分析", r.text)

    def test_search_and_compare(self):
        self.assertEqual(self.remote.get("/api/search", params={"q": "茅台"}).json()["items"][0]["key"], "SH:600519")
        r = self.remote.post("/api/compare", json={"keys": ["SH:600519", "OF:110011"], "period": "1y"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["series"]), 2)
        self.assertEqual(len(body["correlation"]), 2)
        self.assertEqual(self.remote.post("/api/compare", json={"keys": ["SH:600519"]}).status_code, 422)

    def test_csv_import(self):
        rows = "\n".join(f"2026-{9 + i // 28:02d}-{i % 28 + 1:02d},{1 + i * 0.01:.4f}" for i in range(40))
        r = self.remote.post("/api/import", files={"file": ("nav.csv", "日期,单位净值\n" + rows, "text/csv")},
                             data={"name": "理财A", "currency": "CNY"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["instrument"]["name"], body["instrument"]["market"]), ("理财A", "CSV"))
        self.assertTrue(body["csv_id"])
        bad = self.remote.post("/api/import", files={"file": ("x.csv", "a,b\n1,2", "text/csv")})
        self.assertEqual(bad.status_code, 400)

    # ── 访问控制 ──
    def test_remote_without_password_cannot_spend_or_change(self):
        self.assertEqual(self.remote.post("/api/deep", json={"key": "SH:600519"}).status_code, 403)
        self.assertEqual(self.remote.post("/api/settings", json={"api_key": "x"}).status_code, 403)
        self.assertEqual(self.remote.post("/api/settings/test", json={}).status_code, 403)
        proxied = self.local.post("/api/settings", json={"api_key": "x"}, headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(proxied.status_code, 403, "经反向代理的请求不算本机")

    def test_password_gate(self):
        with mock.patch.object(A.config, "APP_PASSWORD", "s3cret"):
            self.assertEqual(self.remote.get("/api/config").status_code, 401)
            self.assertEqual(self.remote.get("/api/health").status_code, 200)
            wrong = {"Authorization": "Basic " + base64.b64encode(b"u:nope").decode()}
            self.assertEqual(self.remote.get("/api/config", headers=wrong).status_code, 401)
            ok = {"Authorization": "Basic " + base64.b64encode(b"anyone:s3cret").decode()}
            cfg = self.remote.get("/api/config", headers=ok)
            self.assertEqual(cfg.status_code, 200)
            self.assertTrue(cfg.json()["trusted"], "设了密码后，通过验证的远程用户可以使用深度分析")

    # ── 设置 ──
    def test_settings_never_leak_key(self):
        self.configure_llm()
        for path in ("/api/settings", "/api/config"):
            text = self.local.get(path).text
            self.assertNotIn("sk-secret-1234567890", text)
        s = self.local.get("/api/settings").json()
        self.assertEqual(s["per_provider"]["deepseek"]["api_key_masked"], "sk-****7890")
        self.assertTrue(s["llm_ready"])
        cleared = self.local.post("/api/settings", json={"provider": "deepseek", "api_key": "__clear__"}).json()
        self.assertFalse(cleared["llm_ready"])
        self.configure_llm()
        self.assertEqual(self.local.post("/api/settings", json={"debate_rounds": 9}).status_code, 400)

    def test_settings_connection_test(self):
        self.configure_llm()
        ok = self.local.post("/api/settings/test", json={}).json()
        self.assertTrue(ok["ok"])
        from agents.llm import LLMError
        with mock.patch.object(A, "make_llm", side_effect=LLMError("Key 无效")):
            bad = self.local.post("/api/settings/test", json={}).json()
        self.assertEqual((bad["ok"], bad["message"]), (False, "Key 无效"))

    # ── 深度分析 ──
    def read_events(self, job_id):
        events = []
        with self.local.stream("GET", f"/api/deep/{job_id}/events") as r:
            self.assertEqual(r.headers["content-type"].split(";")[0], "text/event-stream")
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    def test_deep_job_end_to_end(self):
        self.configure_llm()
        r = self.local.post("/api/deep", json={"key": "SH:600519", "debate_rounds": 1, "risk_rounds": 1,
                                               "position": {"shares": 100, "cost": 90}})
        self.assertEqual(r.status_code, 200, r.text)
        events = self.read_events(r.json()["job_id"])
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "stage")
        self.assertIn("report", types)
        self.assertIn("decision", types)
        self.assertEqual(types[-1], "done")
        rid = events[-1]["result_id"]
        item = self.local.get(f"/api/history/{rid}").json()
        self.assertEqual(item["result"]["final"]["rating"], "Buy")
        self.assertEqual(item["result"]["options"]["position"], {"shares": 100.0, "cost": 90.0, "cash": None})
        md = self.local.get(f"/api/history/{rid}/markdown")
        self.assertIn("AI 深度分析报告", md.text)
        outcomes = self.local.post("/api/history/outcomes", json={"ids": [rid]}).json()["outcomes"]
        self.assertIn(rid, outcomes)
        # 回放：断线重连后从指定位置继续
        replay = self.read_events(r.json()["job_id"])
        self.assertEqual(replay[-1]["type"], "done")
        self.assertEqual(self.remote.delete(f"/api/history/{rid}").status_code, 403)
        self.assertEqual(self.local.delete(f"/api/history/{rid}").status_code, 200)
        self.assertEqual(self.local.get(f"/api/history/{rid}").status_code, 404)

    def test_deep_requires_llm_config(self):
        self.local.post("/api/settings", json={"provider": "deepseek", "api_key": "__clear__"})
        r = self.local.post("/api/deep", json={"key": "SH:600519"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("API Key", r.json()["error"])
        self.configure_llm()

    def test_deep_job_failure_is_reported(self):
        self.configure_llm()
        with mock.patch.object(A.router, "load", side_effect=SourceError("所有数据源都没有取到行情")):
            job_id = self.local.post("/api/deep", json={"key": "SH:600519"}).json()["job_id"]
            events = self.read_events(job_id)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("所有数据源", events[-1]["message"])

    def test_unknown_job(self):
        self.assertEqual(self.local.get("/api/deep/nope/events").status_code, 404)
        self.assertEqual(self.local.post("/api/deep/nope/cancel").status_code, 404)

    def test_index_page_injects_version(self):
        r = self.remote.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("__V__", r.text)
        self.assertEqual(self.remote.get("/static/app.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
