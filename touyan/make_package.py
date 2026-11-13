"""打一个可以直接发给别人的压缩包：python make_package.py → dist/touyan-日期.zip

为什么要用脚本打包，而不是把自己电脑上的文件夹直接压缩：
- .venv/ 是在你这台电脑上装的依赖，换一台电脑用不了，还有几百 MB。
- 1.1 及更早的版本把 API Key（settings.json）、历史记录和缓存放在文件夹里的 data/。发出去，别人就能用你的
  Key 花你的钱。现在这些都在个人文件夹下的 .touyan，但旧文件夹里可能还留着一份。
这个脚本只打包运行需要的文件，并附上一份给对方看的「使用说明.txt」。
"""

from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOP = "touyan"   # 压缩包里的顶层文件夹名，保持英文：Mac 命令行 unzip 处理不了中文目录名

FILES = [
    "app.py", "cli.py", "config.py", "jobs.py", "selftest.py", "store.py",
    "requirements.txt", "start.sh", "start.bat", "start-mac.command",
    ".env.example", "README.md", "NOTICE", "LICENSE-TradingAgents.txt",
]
DIRS = ["agents", "daily", "market", "quant", "static"]
EXECUTABLE = {"start.sh", "start-mac.command"}

USAGE = """投研智能体 使用说明
=====================

股票、基金、ETF 的量化分析与 AI 多智能体投研工具。在你自己的电脑上运行，数据和 API Key 都只存在本机。

一、准备
  需要 Python 3.10 或更高版本。没有的话到 https://www.python.org/downloads/ 下载安装。
  Windows 安装时务必勾选 "Add python.exe to PATH"。

二、启动
  先解压，再运行：Windows 右键压缩包选「全部解压缩」，Mac 双击压缩包。不要在压缩包里面直接双击。
  把解压出来的文件夹放到不会自动同步到云盘的地方：Mac 放进「个人文件夹」（访达左边栏带小房子图标的那个），
  Windows 放到 C 盘下自己建的文件夹（比如 C:\touyan）。不要放在 iCloud、OneDrive 同步的桌面或文稿里，
  也别放在微信的接收文件夹里：第一次启动会装几百 MB 的依赖，云盘同步会拖慢甚至弄坏它们。

  Windows：双击 start.bat。
          如果弹出「Windows 已保护你的电脑」，点「更多信息」→「仍要运行」；
          弹出「无法验证发布者」就点「运行」。
  Mac：    双击 start-mac.command。
          如果提示「无法打开」或「无法验证」，到「系统设置 → 隐私与安全性」，在页面底部点「仍要打开」；
          或者打开「终端」，输入 bash 和一个空格，把 start.sh 拖进窗口，按回车。
          弹出「终端想要访问……文件夹」时点「允许」。

  第一次启动会自动安装依赖，大约 1–3 分钟，完成后浏览器自动打开 http://127.0.0.1:8600 。
  使用期间不要关闭那个黑色 / 白色的命令行窗口，关掉程序就停了。以后再启动只要几秒。

三、使用
  - 在首页输入代码或名称（600519、腾讯、AAPL、510300、110011……）即可得到量化分析，不需要任何配置。
  - 想用 AI 深度分析：打开「设置」，选一家大模型服务商（推荐 DeepSeek，国内直连、便宜），
    填入你自己的 API Key，点「测试连接」。费用由服务商按用量从你的账户扣。
  - 「每日精选」：收盘后扫一遍全市场，分短期、中期、长期、定投四个板块选股票、ETF 和基金，
    每只都写明持有多久、预期收益、什么时候卖。第一次生成约 3–5 分钟。
    每个板块都有「方法体检」：这个方法放回历史行情里的结果。体检没通过的板块只适合观察，不要照着买。
    勾选「交易日收盘后自动生成」，软件开着时每天 15:45 之后自动更新。
  - 打不开行情时：「设置 → 数据源自检」可以看到每个数据源能不能连上。

四、更新到新版本
  解压新版本，直接从新文件夹启动就行，旧文件夹可以删掉（用新文件夹把旧的整个替换掉也可以）。
  你的设置、API Key、历史记录保存在「个人文件夹」下的 .touyan 里，不在程序文件夹里，换版本不用重新填。
  启动时窗口里会显示这个位置，「设置」页里也有。
  如果旧文件夹里有一个 data 文件夹（早期版本把设置存在那里）：先把它复制到新文件夹里再启动，
  程序会自动把里面的内容搬到新位置。

五、提示
  本工具根据公开数据和大模型自动生成分析，仅供研究与学习参考，不构成任何投资建议。
  API Key 只保存在你自己的电脑上。不要把 .touyan 文件夹（或旧版本的 data 文件夹）发给别人。
"""


def collect() -> list[Path]:
    paths = [ROOT / f for f in FILES]
    for d in DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            rel = p.relative_to(ROOT).parts
            if (p.is_file() and "__pycache__" not in rel and p.suffix not in (".pyc", ".pyo")
                    and not any(part.startswith(".") for part in rel)):   # .DS_Store 之类
                paths.append(p)
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        sys.exit("缺少文件：" + "，".join(missing))
    return paths


def _entry(name: str, mode: int, stamp: tuple) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{TOP}/{name}", date_time=stamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3                        # 按 Unix 记录权限，在 Windows 上打包也保留可执行位
    info.external_attr = (0o100000 | mode) << 16
    return info


def build(out_dir: Path) -> Path:
    now = datetime.now()
    stamp = now.timetuple()[:6]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"touyan-{now:%Y%m%d}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in collect():
            rel = path.relative_to(ROOT).as_posix()
            mode = 0o755 if rel in EXECUTABLE else 0o644
            zf.writestr(_entry(rel, mode, stamp), path.read_bytes())   # 原样写字节：start.bat 的 CRLF 不变
        # 说明放最后：中文文件名万一解压出错（Mac 命令行 unzip），前面的程序文件也已经解压好了
        zf.writestr(_entry("使用说明.txt", 0o644, stamp), ("\ufeff" + USAGE).encode("utf-8"))  # BOM：记事本不乱码
    return target


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    path = build(out)
    print(f"已生成：{path}（{path.stat().st_size // 1024} KB）")
