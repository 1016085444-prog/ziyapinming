"""分享包：只收运行需要的文件，绝不能带上 data/（里面有 API Key）、.venv/ 和本机杂物。"""

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  先隔离数据目录，子进程导入 app 时也用临时目录
import make_package


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="touyan-pkg-"))
        root = cls.tmp / "src"
        shutil.copytree(make_package.ROOT, root,
                        ignore=shutil.ignore_patterns(".venv", "venv", "data", "dist", "tests", "__pycache__"))
        # 模拟一台用过的电脑：填过 Key、装过依赖、Finder 留下 .DS_Store、跑出过 .pyc
        (root / "data").mkdir()
        (root / "data" / "settings.json").write_text('{"api_key": "sk-secret-key"}', encoding="utf-8")
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").write_text("")
        (root / "static" / ".DS_Store").write_bytes(b"\0")
        (root / "agents" / "__pycache__").mkdir()
        (root / "agents" / "__pycache__" / "llm.cpython-312.pyc").write_bytes(b"\0")
        with mock.patch.object(make_package, "ROOT", root):
            path = make_package.build(cls.tmp / "out")
        cls.root = root
        cls.zf = zipfile.ZipFile(path)
        cls.names = cls.zf.namelist()

    @classmethod
    def tearDownClass(cls):
        cls.zf.close()
        shutil.rmtree(cls.tmp)

    def test_secrets_and_local_junk_stay_out(self):
        for bad in ("data/", ".venv/", "__pycache__", ".DS_Store", ".pyc", "tests/", "dist/"):
            self.assertEqual([n for n in self.names if bad in n], [], bad)
        for info in self.zf.infolist():
            self.assertNotIn(b"sk-secret-key", self.zf.read(info), info.filename)

    def test_launchers_survive_unzip(self):
        self.assertTrue(all(n.startswith("touyan/") for n in self.names))
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in self.zf.infolist()}
        self.assertEqual(modes["touyan/start.sh"], 0o755)
        self.assertEqual(modes["touyan/start-mac.command"], 0o755, "Mac 双击要求可执行")
        self.assertEqual(modes["touyan/app.py"], 0o644)
        bat = self.zf.read("touyan/start.bat")
        self.assertEqual(bat, (self.root / "start.bat").read_bytes())
        self.assertEqual(bat.count(b"\r\n"), bat.count(b"\n"), "start.bat 必须是 CRLF")
        for name in ("touyan/start.sh", "touyan/start-mac.command"):
            self.assertNotIn(b"\r", self.zf.read(name), name)

    def test_usage_note_last_and_readable_in_notepad(self):
        self.assertEqual(self.names[-1], "touyan/使用说明.txt")
        self.assertTrue(self.zf.read(self.names[-1]).startswith("﻿".encode("utf-8")))

    def test_unpacked_copy_has_every_module(self):
        out = self.tmp / "unpacked"
        self.zf.extractall(out)
        r = subprocess.run([sys.executable, "-c", "import app, cli, selftest; print(app.__file__)"],
                           cwd=out / "touyan", capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(Path(r.stdout.strip()).is_relative_to(out), r.stdout)


if __name__ == "__main__":
    unittest.main()
