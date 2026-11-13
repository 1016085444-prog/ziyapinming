"""设置存在哪、怎么搬、读不出来时怎么办。

API Key 丢过两次：数据原先放在程序文件夹的 data/ 里，换一个新版本的文件夹、或者整个替换掉文件夹，
Key 就没了。现在默认放在个人文件夹下的 .touyan，老位置的数据第一次启动时自动搬过去。
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  必须先导入：隔离数据目录

import config


def write_settings(path: Path, keys: dict | None = None, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": "deepseek", "api_keys": keys or {}, **extra}), encoding="utf-8")


def make_db(path: Path, rows: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT)")
    con.executemany("INSERT INTO analyses VALUES (?)", [(str(i),) for i in range(rows)])
    con.commit()
    con.close()


def db_rows(path: Path) -> int:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    finally:
        con.close()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="touyan-cfg-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.legacy, self.target = self.tmp / "app" / "data", self.tmp / "home" / ".touyan"


class LocationTest(TempDirTest):
    def test_default_is_in_home_not_in_app_folder(self):
        d = config.default_data_dir()
        self.assertEqual(d, Path.home() / ".touyan")
        self.assertNotIn(config.BASE_DIR, d.parents)

    def test_env_wins_and_never_migrates(self):
        self.assertEqual(config.DATA_DIR, Path(os.environ["TOUYAN_DATA_DIR"]))
        self.assertEqual(config.MIGRATED, [])
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        with mock.patch.object(config, "LEGACY_DATA_DIR", self.legacy), \
                mock.patch.dict(os.environ, {"TOUYAN_DATA_DIR": str(self.tmp / "custom")}):
            self.assertEqual(config._resolve_data_dir(), (self.tmp / "custom", []))
        self.assertTrue((self.legacy / "settings.json").exists(), "指定了数据目录就不碰老位置")

    def resolve(self):
        env = {k: v for k, v in os.environ.items() if k != "TOUYAN_DATA_DIR"}
        with mock.patch.object(config, "LEGACY_DATA_DIR", self.legacy), \
                mock.patch.object(config, "default_data_dir", return_value=self.target), \
                mock.patch.dict(os.environ, env, clear=True):
            return config._resolve_data_dir()

    def test_first_start_moves_old_data_to_home(self):
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        make_db(self.legacy / "touyan.db", rows=3)
        make_db(self.legacy / "cache.db")
        self.assertEqual(self.resolve(), (self.target, ["settings.json", "touyan.db", "cache.db"]))
        self.assertTrue(config._has_keys(self.target / "settings.json"))
        self.assertEqual(db_rows(self.target / "touyan.db"), 3)
        self.assertFalse(self.legacy.exists(), "搬空以后程序文件夹里不再留着 Key")
        self.assertEqual(self.resolve(), (self.target, []), "第二次启动没有东西可搬")

    def test_fresh_install_and_unwritable_home(self):
        self.assertEqual(self.resolve(), (self.target, []))
        self.assertTrue(self.target.is_dir())
        with mock.patch.object(config.os, "access", return_value=False):
            self.assertEqual(self.resolve(), (self.legacy, []), "个人文件夹写不了就退回老位置")


class MigrateTest(TempDirTest):
    def test_never_overwrites_real_data(self):
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        make_db(self.legacy / "touyan.db", rows=2)
        make_db(self.legacy / "cache.db")
        write_settings(self.target / "settings.json", {"deepseek": "sk-new"})
        make_db(self.target / "touyan.db", rows=5)
        make_db(self.target / "cache.db")
        self.assertEqual(config.migrate_legacy(self.legacy, self.target), [])
        self.assertEqual(json.loads((self.target / "settings.json").read_text())["api_keys"], {"deepseek": "sk-new"})
        self.assertEqual(db_rows(self.target / "touyan.db"), 5)
        self.assertTrue((self.legacy / "settings.json").exists(), "没搬的文件原样留着")
        self.assertFalse((self.legacy / "cache.db").exists(), "缓存不留两份")

    def test_empty_target_is_replaced(self):
        # 先在一个新文件夹里跑过新版本（新位置有了空的库和没有 Key 的设置），再回到老文件夹启动
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        make_db(self.legacy / "touyan.db", rows=2)
        write_settings(self.target / "settings.json", daily_auto=False)
        make_db(self.target / "touyan.db")
        self.assertEqual(config.migrate_legacy(self.legacy, self.target), ["settings.json", "touyan.db"])
        self.assertTrue(config._has_keys(self.target / "settings.json"))
        self.assertEqual(db_rows(self.target / "touyan.db"), 2)

    def test_noop_cases(self):
        self.assertEqual(config.migrate_legacy(self.legacy, self.target), [], "没有老数据")
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        self.assertEqual(config.migrate_legacy(self.legacy, self.legacy), [], "新老位置相同")
        self.assertTrue((self.legacy / "settings.json").exists())

    def test_file_in_use_is_retried_next_start(self):
        write_settings(self.legacy / "settings.json", {"deepseek": "sk-old"})
        make_db(self.legacy / "touyan.db", rows=1)
        self.target.mkdir(parents=True)
        real = os.replace

        def busy(src, dst):
            if str(src).endswith("touyan.db"):
                raise PermissionError(13, "另一个程序正在使用此文件")
            return real(src, dst)

        with mock.patch.object(config.os, "replace", side_effect=busy):
            self.assertEqual(config.migrate_legacy(self.legacy, self.target), ["settings.json"])
        self.assertEqual(db_rows(self.legacy / "touyan.db"), 1, "占用中的文件不复制，免得拷出半截")
        self.assertEqual(config.migrate_legacy(self.legacy, self.target), ["touyan.db"])
        self.assertFalse(self.legacy.exists())


class SettingsFileTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "data" / "settings.json"
        for name, value in (("DATA_DIR", self.path.parent), ("SETTINGS_PATH", self.path)):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_bad_field_does_not_drop_the_key(self):
        write_settings(self.path, {"deepseek": "sk-keep"}, debate_rounds=99, daily_stock_count="很多", unknown=1)
        s = config.load()
        self.assertEqual((config.api_key(s, "deepseek"), s.debate_rounds, s.daily_stock_count), ("sk-keep", 1, 5))
        config.save({"daily_auto": False})
        self.assertEqual(json.loads(self.path.read_text())["api_keys"], {"deepseek": "sk-keep"})

    def test_unreadable_file_is_not_overwritten(self):
        write_settings(self.path, {"deepseek": "sk-keep"})
        before = self.path.read_bytes()
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError(13, "denied")):
            self.assertEqual(config.api_key(config.load(), "deepseek"), "", "读不出来时按默认设置显示")
            self.assertIn("读不出来", config.settings_problem())
            with self.assertRaises(ValueError):
                config.save({"api_key": "sk-other"})
        self.assertEqual(self.path.read_bytes(), before, "读不出来不等于没有：不能用默认值盖掉")
        self.assertEqual(config.settings_problem(), "")

    def test_corrupt_file_is_kept_aside(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"api_keys": {"deepseek": "sk-half', encoding="utf-8")
        self.assertIn("损坏", config.settings_problem())
        config.save({"provider": "deepseek", "api_key": "sk-new"})
        self.assertIn("sk-half", self.path.with_name("settings.json.broken").read_text(encoding="utf-8"))
        self.assertEqual(config.api_key(config.load(), "deepseek"), "sk-new")
        self.assertEqual(config.settings_problem(), "")


class InstanceTest(TempDirTest):
    def test_code_stamp_changes_after_in_place_update(self):
        base = self.tmp / "app"
        for rel in ("app.py", "agents/llm.py", ".venv/lib/site.py", "tests/test_x.py"):
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text("x = 1\n")
            os.utime(base / rel, (1_700_000_000, 1_700_000_000))
        stamp = config.code_stamp(base)
        os.utime(base / ".venv/lib/site.py", (1_800_000_000, 1_800_000_000))
        os.utime(base / "tests/test_x.py", (1_800_000_000, 1_800_000_000))
        self.assertEqual(config.code_stamp(base), stamp, "依赖和测试不算程序本身")
        os.utime(base / "agents/llm.py", (1_800_000_000, 1_800_000_000))
        self.assertNotEqual(config.code_stamp(base), stamp, "覆盖更新后要能认出还开着的是旧程序")
        self.assertRegex(config.INSTANCE_ID, r"^[0-9a-f]{10}$")

    def test_data_dir_shown_only_to_trusted_clients(self):
        import app as A
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(A.app, client=("127.0.0.1", 50002)).get("/api/config").json()["data_dir"],
                         str(config.DATA_DIR))
        self.assertIsNone(TestClient(A.app).get("/api/config").json()["data_dir"], "不把本机路径给远程访问者")


if __name__ == "__main__":
    unittest.main()
