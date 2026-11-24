#!/usr/bin/env python3
"""命令行批量生成兑换密码并导出为纯文本（供自动发货直接导入）。

用法：
    python3 tools/make_codes.py 100 --note 小红书首发 --out codes.txt
    CODES_DB_PATH=/var/lib/ziyapinming/codes.db python3 tools/make_codes.py 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import codes  # noqa: E402
import config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="批量生成子牙品命一次性兑换密码")
    parser.add_argument("count", type=int, help="生成数量（1–2000）")
    parser.add_argument("--prefix", default="ZY", help="前缀，默认 ZY")
    parser.add_argument("--note", default="", help="批次备注，例如：小红书第一批")
    parser.add_argument("--out", default="", help="可选：把生成的密码逐行写入指定 txt 文件")
    args = parser.parse_args()

    store = codes.get_store()
    created = store.generate(count=args.count, prefix=args.prefix, note=args.note)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text("\n".join(created) + "\n", encoding="utf-8")
        print(f"已生成 {len(created)} 个密码并写入 {out_path}（数据库：{config.CODES_DB_PATH}）")
    else:
        for c in created:
            print(c)
        print(f"\n# 共生成 {len(created)} 个（数据库：{config.CODES_DB_PATH}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
