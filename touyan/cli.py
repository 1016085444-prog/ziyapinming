"""命令行入口。

    python cli.py analyze 600519             快速量化分析（不用大模型，几秒出结果）
    python cli.py analyze 110011 --deep      AI 多智能体深度分析，终端里实时看每个智能体发言
    python cli.py analyze 腾讯 --md 报告.md   结果另存为 Markdown
    python cli.py search 茅台                 搜索代码
    python cli.py doctor                      自检：数据源能不能连上、大模型配置是否就绪
    python cli.py serve                       启动网页版（等同 python app.py）
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import unicodedata

import config
from market.cache import Cache
from market.net import SourceError
from market.router import DataRouter
from quant import report as qr


def _pad(text: str, width: int) -> str:
    """按显示宽度补空格：中文字符占两格，用 str.ljust 对不齐。"""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - shown)


def _router() -> DataRouter:
    return DataRouter(Cache(config.CACHE_PATH))


def cmd_search(args) -> int:
    for inst in _router().search(args.text):
        print(f"{inst.key:14} {_pad(inst.kind_label, 10)} {inst.name}")
    return 0


def cmd_analyze(args) -> int:
    router = _router()
    try:
        inst = router.resolve(args.code, args.kind)
        print(f"正在获取 {inst.display} 的数据……", file=sys.stderr)
        md = router.load(inst)
    except SourceError as exc:
        print(f"取数失败：{exc}", file=sys.stderr)
        return 2
    s = config.load()
    rep = qr.build(md, s.risk_free_rate / 100)
    if not args.deep:
        text = qr.to_markdown(rep)
        print(text)
        if args.md:
            open(args.md, "w", encoding="utf-8").write(text)
            print(f"\n已保存到 {args.md}", file=sys.stderr)
        return 0

    from agents.llm import LLMError, make_llm
    from agents.pipeline import DeepOptions, Pipeline, to_markdown
    from store import Store

    ready, reason = config.llm_ready(s)
    if not ready:
        print(f"{reason}。请先运行网页版到「设置」里配置，或设置环境变量（见 .env.example）。", file=sys.stderr)
        return 2
    quick_cfg, deep_cfg = config.llm_configs(s)
    lock = threading.Lock()
    current = {"id": None}

    def emit(ev: dict) -> None:
        with lock:
            t = ev["type"]
            if t == "stage":
                print(f"\n\n==================== {ev['label']} ====================", flush=True)
            elif t == "agent_start":
                rnd = f" · 第 {ev['round']} 轮" if ev.get("round") else ""
                print(f"\n\n──── {ev['label']}{rnd}（{ev['model']}）────\n", flush=True)
                current["id"] = ev["id"]
            elif t == "delta":
                # 分析师并行发言：只实时打印当前这一位，其余的在完成时整段打印
                if ev["id"] == current["id"]:
                    print(ev["text"], end="", flush=True)
            elif t == "agent_done" and ev["id"] != current["id"]:
                print(f"\n\n──── {ev['id']} ────\n{ev['content']}", flush=True)
            elif t == "agent_error":
                print(f"\n[{ev['id']} 失败] {ev['message']}", flush=True)

    try:
        quick, deep = make_llm(quick_cfg), make_llm(deep_cfg)
        options = DeepOptions(s.analysts, args.rounds or s.debate_rounds, args.risk_rounds or s.risk_rounds)
        store = Store(config.DB_PATH)
        result = Pipeline(quick, deep, emit).run(rep, options)
    except LLMError as exc:
        print(f"\n大模型调用失败：{exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    rid = store.save(result, rep)
    final = result["final"]
    print(f"\n\n==================== 最终结论：{final['label']}（{final['rating']}） ====================")
    if final.get("summary"):
        print(final["summary"])
    print(f"\n已保存到历史记录（{rid}），网页版「历史与复盘」里可以查看。")
    if args.md:
        open(args.md, "w", encoding="utf-8").write(to_markdown(result))
        print(f"报告已保存到 {args.md}")
    return 0


def cmd_doctor(_args) -> int:
    import selftest
    from agents import providers

    print("数据源自检（约 10 秒）……\n")
    res = selftest.run()
    for c in res["checks"]:
        print(f"  {'✓' if c['ok'] else '✗'} {_pad(c['name'], 20)} {c['ms']:>5}ms  {c['detail']}")
    print(f"\n  {res['ok']}/{res['total']} 个数据源可用；可选后备库：" +
          "，".join(f"{k} {'已安装' if v else '未安装'}" for k, v in res["optional"].items()))
    s = config.load()
    ready, reason = config.llm_ready(s)
    quick, deep = config.models(s)
    print(f"\n大模型：{providers.get(s.provider).label}，快模型 {quick or '—'}，深度模型 {deep or '—'}")
    print("  ✓ 配置就绪（在网页「设置」里可以测试连通性）" if ready else f"  ✗ {reason}")
    return 0 if res["ok"] else 1


def cmd_serve(args) -> int:
    os.environ["HOST"] = args.host
    os.environ["PORT"] = str(args.port)
    import runpy
    runpy.run_path(os.path.join(config.BASE_DIR, "app.py"), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touyan", description="投研智能体：股票、基金、ETF 的量化与 AI 多智能体分析")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze", help="分析一个品种")
    p.add_argument("code", help="代码或名称：600519 / 00700 / AAPL / 510300 / 110011 / 茅台")
    p.add_argument("--kind", default="auto", choices=["auto", "stock", "etf", "fund", "index"], help="品种类型（代码有歧义时指定）")
    p.add_argument("--deep", action="store_true", help="运行 AI 多智能体深度分析")
    p.add_argument("--rounds", type=int, choices=[1, 2, 3], help="多空辩论轮数")
    p.add_argument("--risk-rounds", type=int, choices=[1, 2, 3], help="风控辩论轮数")
    p.add_argument("--md", help="把报告另存为 Markdown 文件")
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("search", help="搜索代码")
    p.add_argument("text")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("doctor", help="自检数据源与大模型配置")
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("serve", help="启动网页版")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8600)
    p.set_defaults(func=cmd_serve)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
