#!/usr/bin/env bash
# 投研智能体 一键启动（macOS / Linux）：./start.sh
# 第一次运行会创建虚拟环境并安装依赖（约 1–3 分钟），之后秒开。
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "没有找到 Python 3。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/"
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "需要 Python 3.10 或更高版本，当前是 $("$PY" -V 2>&1)"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "首次运行：创建虚拟环境……"
  "$PY" -m venv .venv
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
URL="http://127.0.0.1:${PORT}"
( sleep 2
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi ) >/dev/null 2>&1 &

echo "启动中：${URL}（按 Ctrl+C 退出）"
exec env PORT="$PORT" .venv/bin/python app.py
