@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 投研智能体

rem 投研智能体 一键启动（Windows）：双击本文件即可。
rem 第一次运行会创建虚拟环境并安装依赖（约 1-3 分钟），之后秒开。

set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo 没有找到 Python 3.10 或更高版本。
  echo 请从 https://www.python.org/downloads/ 下载安装，安装时勾选 "Add python.exe to PATH"，然后重新双击本文件。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行：创建虚拟环境……
  %PY% -m venv .venv
  if errorlevel 1 (
    echo 创建虚拟环境失败。
    pause
    exit /b 1
  )
)

if not exist ".venv\deps-ok" (
  echo 安装依赖……
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 (
    echo 镜像源安装失败，改用官方 PyPI 重试……
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.org/simple
    if errorlevel 1 (
      echo 依赖安装失败，请检查网络后重新运行。
      pause
      exit /b 1
    )
  )
  echo ok> ".venv\deps-ok"
)

if "%PORT%"=="" set "PORT=8600"
set "TOUYAN_OPEN_BROWSER=1"
".venv\Scripts\python.exe" app.py
pause
