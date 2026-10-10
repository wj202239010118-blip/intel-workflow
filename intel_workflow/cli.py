"""命令行入口：hot / search / verify / analyze（analyze = 取事实 + 双模型交叉复核）。"""
import argparse
import datetime as dt
import pathlib
import sys

from .adapters import ADAPTERS
from .adapters.base import Degraded, NeedCredential
from .collab import crosscheck
from .config import Config
from .core.gate import Gate, RateLimited
from .core.http import Http

PLATFORMS = ["youtube", "x", "twitch", "kick", "tiktok", "instagram"]
_COMMANDS = [
    ("hot", "平台热点 / 热榜"),
    ("search", "关键词下钻"),
    ("verify", "账号核实"),
    ("analyze", "取事实 + 双模型交叉复核"),
]


def build_parser():
    parser = argparse.ArgumentParser(prog="intel", description="社交平台情报 · 统一入口")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd, help_text in _COMMANDS:
        sp = sub.add_parser(cmd, help=help_text)
        sp.add_argument("--platform", default="all", help=f"all 或逗号分隔：{','.join(PLATFORMS)}")
        sp.add_argument("--region", default=None, help="地区（YouTube 用 US；X 用 united-states 这类 slug）")
        sp.add_argument("--period", default="24h")
        sp.add_argument("--q", default=None, help="search 的关键词")
        sp.add_argument("--handle", default=None, help="verify 的账号")
        sp.add_argument("--out", default=None)
        sp.add_argument("--no-save", action="store_true", help="只打印不落盘")
        sp.add_argument("--config", default=None)
        if cmd == "analyze":
            sp.add_argument("--single", action="store_true", help="只用一个引擎（关掉交叉复核）")
            sp.add_argument("--main", default=None, help="标记主引擎（claude / codex），仅影响报告标注")
    return parser


def _names(value):
    return PLATFORMS if value in ("all", "") else [s.strip() for s in value.split(",")]


def _call(adapter, args):
    if args.cmd == "search":
        return adapter.search(args.q, region=args.region)
    if args.cmd == "verify":
        return adapter.verify(args.handle)
    return adapter.hot(region=args.region, period=args.period)  # hot / analyze


def collect(args, cfg, http):
    """按命令取事实；单平台失败不影响其它平台。返回 (facts, rc)。"""
    facts, rc = [], 0
    for name in _names(args.platform):
        cls = ADAPTERS.get(name)
        if not cls:
            print(f"❌ 未知平台：{name}（可选：{', '.join(PLATFORMS)}）")
            rc = 2
            continue
        try:
            facts.append(_call(cls(cfg, http), args))
        except NeedCredential as exc:
            print(f"⚠️  {name}：缺凭据 → {exc}")
            rc = 1
        except Degraded as exc:
            print(f"⚠️  {name}：暂不可用 → {exc}")
            rc = 1
        except RateLimited as exc:
            print(f"⛔ {name}：{exc}")
            print("   （闸门保护生效，这是预期行为；稍后再试，不要绕开）")
            rc = 1
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {name}：{type(exc).__name__}: {exc}")
            rc = 1
    return facts, rc


def _run_analyze(args, cfg, http):
    facts, rc = collect(args, cfg, http)
    if not facts:
        print("没有可分析的事实（先解决上面的凭据 / 组件问题）")
        return rc or 1
    report, reason = crosscheck.analyze(facts, cfg, main=args.main, single=args.single)
    if report is None:
        print(f"⚠️  交叉复核未进行 → {reason}")
        for intel in facts:
            print(intel.to_markdown())
        return 1
    text = crosscheck.to_markdown(report, facts)
    print(text)
    if not args.no_save:
        directory = pathlib.Path(args.out or cfg.output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{dt.date.today().isoformat()}-crosscheck.md"
        path.write_text(text, encoding="utf-8")
        print(f"💾 {path}")
    return rc


def run(args):
    cfg = Config(args.config)
    http = Http(gate=Gate(**cfg.gate_options))
    if args.cmd == "analyze":
        return _run_analyze(args, cfg, http)

    facts, rc = collect(args, cfg, http)
    outdir = args.out or cfg.output_dir
    for intel in facts:
        print(intel.to_markdown())
        if not args.no_save:
            md_path, jsonl_path = intel.save(outdir)
            print(f"💾 {md_path} ｜ {jsonl_path}\n")
    return rc


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
