"""启动器：端口被占用时，分清是同一份程序、另一份投研智能体（比如旧版本），还是别的程序。"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import helpers  # noqa: F401

import app as A  # noqa: E402
import config


def serve(body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class LauncherTest(unittest.TestCase):
    def start(self, body: bytes) -> int:
        server = serve(body)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_identifies_running_copies(self):
        same = self.start(json.dumps({"ok": True, "version": config.VERSION, "instance": config.INSTANCE_ID}).encode())
        old = self.start(json.dumps({"ok": True, "version": "1.0.0"}).encode())
        other = self.start(b'{"status": "ok"}')
        html = self.start(b"<html>hello</html>")
        self.assertEqual(A.running_instance("127.0.0.1", same), config.INSTANCE_ID)
        self.assertEqual(A.running_instance("127.0.0.1", old), "", "1.0.0 没有实例标识，算另一份")
        self.assertIsNone(A.running_instance("127.0.0.1", other))
        self.assertIsNone(A.running_instance("127.0.0.1", html))

    def test_free_port_skips_busy(self):
        busy = self.start(b"{}")
        port = A.free_port("127.0.0.1", busy)
        self.assertIsNotNone(port)
        self.assertNotEqual(port, busy)

    def test_health_reports_instance(self):
        from fastapi.testclient import TestClient
        body = TestClient(A.app).get("/api/health").json()
        self.assertEqual((body["version"], body["instance"]), (config.VERSION, config.INSTANCE_ID))
        self.assertNotIn("/", body["instance"], "不暴露本机路径")


if __name__ == "__main__":
    unittest.main()
