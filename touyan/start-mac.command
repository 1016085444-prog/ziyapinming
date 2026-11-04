#!/bin/bash
# 投研智能体 —— macOS 双击启动。
# 如果双击后提示「无法打开」：到「系统设置 → 隐私与安全性」底部点「仍要打开」，
# 或者打开「终端」，输入 bash 和一个空格，把 start.sh 拖进窗口，按回车。
cd "$(dirname "$0")" || exit 1
bash start.sh
