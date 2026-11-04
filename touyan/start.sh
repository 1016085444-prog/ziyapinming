#!/usr/bin/env bash
# 投研智能体 一键启动（macOS / Linux）：./start.sh
# 第一次运行会创建虚拟环境并安装依赖（约 1–3 分钟），之后秒开。
set -e
cd "$(dirname "$0")"

# 找一个 3.10 以上的 Python。macOS 自带的 python3 是 3.9，太旧；
# 从 python.org 或 Homebrew 装的新版本常常不叫 python3，所以按版本号逐个找。
find_python() {
  for c in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
           python3; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

if ! PY="$(find_python)"; then
  echo "没有找到 Python 3.10 或更高版本（macOS 自带的 python3 是 3.9，版本太旧）。"
  echo "请到 https://www.python.org/downloads/ 下载最新的 Python 3 安装包，双击安装；"
  echo "装好后关掉这个终端窗口、重新打开一个，再运行一次：bash start.sh"
  exit 1
fi
echo "使用 $("$PY" -V 2>&1)"

if [ ! -x .venv/bin/python ]; then
  echo "首次运行：创建虚拟环境……"
  "$PY" -m venv --clear .venv
fi

if [ ! -f .venv/.deps-ok ] || [ requirements.txt -nt .venv/.deps-ok ]; then
  echo "安装依赖……"
  MIRROR="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
  .venv/bin/python -m pip install -q --upgrade pip -i "$MIRROR" || true
  if ! .venv/bin/python -m pip install -r requirements.txt -i "$MIRROR"; then
    echo "镜像源安装失败，改用官方 PyPI 重试……"
    .venv/bin/python -m pip install -r requirements.txt -i https://pypi.org/simple
  fi
  touch .venv/.deps-ok
fi

PORT="${PORT:-8600}"
exec env PORT="$PORT" TOUYAN_OPEN_BROWSER=1 .venv/bin/python app.py
