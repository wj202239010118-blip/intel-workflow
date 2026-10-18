"""命令行入口：hot / search / verify / analyze（analyze = 取事实 + 双模型交叉复核）
+ news（iGaming 资讯站每日检索 → 整合日报 → 可选推送）+ schedule（launchd 每日定时）。"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from .adapters import ADAPTERS
from .adapters.base import Degraded, NeedCredential
from .collab import crosscheck
from .config import Config
from .core.gate import Gate, RateLimited
from .core.http import Http
from concurrent.futures import ThreadPoolExecutor

from .news import digest as news_digest
from .news import fetch as news_fetch
from .news import push as news_push
from .news import ranking as news_ranking
from .news import schedule as news_sched
from .news import sites as news_sites

PLATFORMS = ["youtube", "x", "twitch", "kick", "tiktok", "instagram"]
_COMMANDS = [
    ("hot", "平台热点 / 热榜"),
    ("search", "关键词下钻（目前仅 YouTube）"),
    ("verify", "账号核实（目前仅 Instagram）"),
    ("analyze", "取事实 + 双模型交叉复核"),
    ("digest", "对比历史抓取的变化（新进榜 / 掉榜 / 排位变化）"),
]


def build_parser():
    parser = argparse.ArgumentParser(prog="intel", description="社交平台情报 · 统一入口")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd, help_text in _COMMANDS:
        sp = sub.add_parser(cmd, help=help_text)
        sp.add_argument("--platform", default="all", help=f"all 或逗号分隔：{','.join(PLATFORMS)}")
        sp.add_argument("--region", default=None, help="地区（YouTube 用 US；X 用 united-states 这类 slug）")
        sp.add_argument("--q", default=None, help="search 的关键词")
        sp.add_argument("--handle", default=None, help="verify 的账号")
        sp.add_argument("--out", default=None)
        sp.add_argument("--no-save", action="store_true", help="只打印不落盘")
        sp.add_argument("--config", default=None)
        if cmd == "analyze":
            sp.add_argument("--single", action="store_true", help="只用一个引擎（关掉交叉复核）")
            sp.add_argument("--main", default=None, help="标记主引擎（claude / codex），仅影响报告标注")
    _add_news_parser(sub)
    _add_schedule_parser(sub)
    return parser


def _add_news_parser(sub):
    sp = sub.add_parser(
        "news",
        help="iGaming 资讯站每日检索（feed/sitemap 优先，纯 HTTP；都没有才用浏览器）→ 整合日报 → 可选推送",
    )
    sp.add_argument("action", nargs="?", default="run", choices=["run", "push"],
                    help="run=抓取+整合日报（默认）／push=把最近一份日报推出去")
    sp.add_argument("--sites", default=None, help="逗号分隔的列表页 URL（不给则用 config / 内置一组）")
    sp.add_argument("--profile", default=None, help="浏览器持久 profile 目录（登录态复用）")
    sp.add_argument("--headless", action="store_true", help="无头跑（默认有头）")
    sp.add_argument("--send", action="store_true", help="真发推送（默认 dry-run，只打印不发）")
    sp.add_argument("--force", action="store_true", help="当天已成功跑过也再跑一次")
    sp.add_argument("--debug", action="store_true", help="打印每个站点的抓取细节")
    sp.add_argument("--out", default=None)
    sp.add_argument("--no-save", action="store_true", help="只打印不落盘")
    sp.add_argument("--no-images", action="store_true",
                    help="不抓文章图（云端用：省掉逐篇 16s 闸门等待；本机跑图时不要加）")
    sp.add_argument("--config", default=None)


def _add_schedule_parser(sub):
    sp = sub.add_parser("schedule", help="每日定时（launchd：开机/登录跑一次 + 每天固定时刻跑一次）")
    sp.add_argument("action", nargs="?", default="status", choices=["status", "install", "uninstall", "show"])
    sp.add_argument("--hour", type=int, default=None, help="每天几点跑（默认 9，或 config [schedule].hour）")
    sp.add_argument("--minute", type=int, default=None, help="每小时第几分跑（默认 30）")
    sp.add_argument("--send", action="store_true", help="定时任务里带上 --send（真推送；默认只抓取落盘）")
    sp.add_argument("--node-path", default=None, help="定时任务的 INTEL_NODE_PATH（playwright 装别处时用）")
    sp.add_argument("--config", default=None)


def _names(value):
    return PLATFORMS if value in ("all", "") else [s.strip() for s in value.split(",")]


def _call(adapter, args):
    if args.cmd == "search":
        return adapter.search(args.q, region=args.region)
    if args.cmd == "verify":
        return adapter.verify(args.handle)
    return adapter.hot(region=args.region)  # hot / analyze


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


# --- news：资讯站每日检索 → 整合日报 → 推送 ---

def _news_sites(args, cfg):
    if args.sites:
        urls = [u.strip() for u in args.sites.split(",") if u.strip()]
        return [
            news_sites.Site(key=news_sites.key_of(news_sites.domain_of(u)), url=u,
                            domain=news_sites.domain_of(u), limit=news_sites.DEFAULT_LIMIT)
            for u in urls
        ]
    return news_sites.resolve(cfg)


def _news_run(args, cfg):
    if getattr(args, "no_images", False):
        import os as _os
        _os.environ["INTEL_NEWS_IMAGES"] = "0"
        print("🖼  本轮不抓图（--no-images）：只取标题/摘要/链接")
    if not args.force and not args.out and news_sched.already_ran():
        print(f"⏭  今天（{news_sched.today()}）已经成功跑过 → 跳过（要重跑加 --force）")
        return 0

    site_list = _news_sites(args, cfg)
    if not site_list:
        print("❌ 没有可用站点（config [news] sites 为空？）")
        return 1
    outdir = args.out or cfg.output_dir
    history, prev_counts = news_digest.scan(outdir)     # 必须在写本次快照之前读
    http = Http(gate=Gate(**cfg.gate_options))
    profile = args.profile or news_fetch.profile_dir(cfg)
    headless = args.headless or news_fetch.wants_headless(cfg)

    counts = {name: sum(1 for s in site_list if news_fetch.channel_of(s) == name)
              for name in ("feed", "sitemap", "browser")}
    summary = " / ".join(f"{label} {counts[name]}" for name, label in
                         (("feed", "feed"), ("sitemap", "sitemap"), ("browser", "浏览器"))
                         if counts[name])
    head = f"站点 {len(site_list)} 个（{summary}）"
    if counts["browser"]:
        head += f" · {'无头' if headless else '有头'} · profile {profile}"
    else:
        head += " · 纯 HTTP（不需要浏览器 / playwright）"
    print(head)

    # 各家的「热门/排行榜」先取一次（当天量级：2 次请求）→ 用来给条目打名次。用户 2026-10-14：
    # 按这些官方网站给新闻做排行。榜单是**增强项**：抓不到就全 0，绝不影响抓取主线。
    try:
        ranks = news_ranking.fetch_ranks(http)
        print("🔥 各家热门榜：%d 条" % len(ranks))
    except Exception as exc:  # noqa: BLE001
        ranks = {}
        print("⚠️  热门榜抓取失败（不影响抓取）：%r" % (exc,))

    # 整轮先拿 profile 锁：定时任务与手动跑撞同一个 profile 会让两边都起不来（幂等，跳过即可）
    with news_fetch.profile_lock(profile) as locked:
        if not locked:
            print("⏭  另一个 news 进程正在用同一浏览器 profile → 本轮跳过（别并发，下次跑会补上）")
            return 0

        def _fetch_one(site):
            """抓一个站（2026-10-18：改成按站并行 —— 不同域名的闸门互不影响）。"""
            channel = news_fetch.channel_of(site)
            print(f"→ {site.key} [{channel}]  {site.feed or site.sitemap or site.url}")
            try:
                intel = news_fetch.fetch(site, http, profile=profile, headless=headless)
            except RateLimited as exc:
                print(f"  ⛔ {exc}（闸门保护，这是预期行为，不要绕开）")
                return None, (site.key, "rate-gated (see local log)")
            except Degraded as exc:
                print(f"  ⚠️  {type(exc).__name__}: {exc}")
                return None, (site.key, "not fetched — render/extract failed (see local log)")
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ {type(exc).__name__}: {exc}")
                return None, (site.key, f"error: {type(exc).__name__}")
            print(f"  ✅ {len(intel.items)} 条（{intel.method}）")
            # 命中各家热门榜的记下名次（0 = 不在榜上）。榜单抓不到时 ranks 为空 → 全 0
            for item in intel.items:
                metrics = item.metrics or {}
                metrics["hot_rank"] = news_ranking.rank_of(item.url, ranks)
                item.metrics = metrics
            on_board = sum(1 for i in intel.items if (i.metrics or {}).get("hot_rank"))
            if on_board:
                print(f"     🔥 其中 {on_board} 条在自家热门榜上")
            if not args.no_save:
                md_path, _ = intel.save(outdir)
                if args.debug:
                    print(f"  💾 {md_path}")
            return intel, None

        # 站间并行：4 个域名各自的闸门（min_interval / 每日上限 / 冷却）互不相干，
        # 站内仍是串行 + 等间隔（fetch() 内部 _wait_min_interval）。原来串行跑 ≈ 4×单站时长。
        intels, failures = [], []
        _workers = max(1, min(4, len(site_list)))
        with ThreadPoolExecutor(max_workers=_workers) as _ex:
            for intel, fail in _ex.map(_fetch_one, site_list):
                if intel is not None:
                    intels.append(intel)
                if fail is not None:
                    failures.append(fail)

    if not intels:
        news_sched.mark_run(success=False, note="所有站点都没抓到")
        print("❌ 一个站点都没抓到 → 不生成日报（先解决上面的问题；不要靠编造补上）")
        return 1

    notices = news_digest.health_notices(prev_counts, intels)
    for notice in notices:
        print(f"⚠️  健康告警：{notice}")
    markdown, stats = news_digest.build(intels, history, failures=failures, notices=notices)
    print(markdown)
    if not args.no_save:
        path = news_digest.save(markdown, outdir)
        print(f"💾 {path}")

    title = markdown.splitlines()[0].lstrip("# ").strip()
    try:
        for line in news_push.push(cfg, title, markdown, http, dry_run=not args.send):
            print(f"📤 {line}")
    except news_push.PushRefused as exc:
        news_sched.mark_run(success=True, note=f"推送被拒：{exc}")
        print(f"⛔ 推送被拒：{exc}")
        return 1

    news_sched.mark_run(success=True, note=f"{stats['sites']} 站 / {stats['items']} 条 / 新进 {stats['new']}")
    if not args.send:
        print("（当前是 dry-run：没有真的发出去。确认内容无误后加 --send 真发）")
    return 0


def _news_push(args, cfg):
    outdir = pathlib.Path(args.out or cfg.output_dir)
    files = sorted(outdir.glob("*-news-digest.md"))
    if not files:
        print("⚠️  还没有日报（先跑 intel news run），或者 --out 指错了目录")
        return 1
    path = files[-1]
    markdown = path.read_text(encoding="utf-8")
    title = markdown.splitlines()[0].lstrip("# ").strip()
    http = Http(gate=Gate(**cfg.gate_options))
    print(f"用最近一份日报：{path}")
    try:
        for line in news_push.push(cfg, title, markdown, http, dry_run=not args.send):
            print(f"📤 {line}")
    except news_push.PushRefused as exc:
        print(f"⛔ {exc}")
        return 1
    if not args.send:
        print("（dry-run：没有真的发出去；加 --send 真发）")
    return 0


def _news(args, cfg):
    return _news_push(args, cfg) if args.action == "push" else _news_run(args, cfg)


# --- schedule：launchd 定时 ---

def _schedule(args, cfg):
    section = cfg.section("schedule")
    hour = args.hour if args.hour is not None else int(section.get("hour", news_sched.DEFAULT_HOUR))
    minute = args.minute if args.minute is not None else int(section.get("minute", news_sched.DEFAULT_MINUTE))
    send = args.send or section.get("send") is True

    if args.action == "show":
        print(news_sched.render_plist(sys.executable, news_sched.ROOT, hour, minute, send,
                                     args.node_path or "").decode("utf-8"))
        return 0
    if args.action == "install":
        path, notes = news_sched.install(sys.executable, news_sched.ROOT, hour, minute, send,
                                        args.node_path or "")
        print(f"✅ 已安装定时任务 {news_sched.LABEL}")
        for line in notes:
            print(f"   {line}")
        print("   （定时任务只抓取落盘；--send 才会推送。手动验证：launchctl kickstart -k "
              f"gui/$UID/{news_sched.LABEL}）")
        return 0
    if args.action == "uninstall":
        for line in news_sched.uninstall():
            print(f"   {line}")
        return 0
    for line in news_sched.status():
        print(line)
    return 0


def _digest(args, cfg):
    """对比同一平台/地区最近两次抓取：新进榜 / 掉榜 / 排位变化。不需要联网。"""
    outdir = pathlib.Path(args.out or cfg.output_dir)
    groups = {}
    if outdir.exists():
        for path in sorted(outdir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                key = (rec.get("platform", "?"), rec.get("kind", "?"), rec.get("region"))
                groups.setdefault(key, []).append(rec)
    if not groups:
        print("⚠️  还没有历史记录：先跑几次 hot（结果会落进 out/），再运行 digest 才有对比")
        return 1

    lines, compared = ["# 情报 · 变化对比", ""], 0
    for (platform, kind, region), recs in sorted(groups.items()):
        recs.sort(key=lambda r: r.get("fetched_at", ""))
        if len(recs) < 2:
            continue
        prev, cur = recs[-2], recs[-1]
        prev_titles = [i.get("title") for i in prev.get("items", [])]
        cur_titles = [i.get("title") for i in cur.get("items", [])]
        added = [t for t in cur_titles if t not in prev_titles]
        dropped = [t for t in prev_titles if t not in cur_titles]
        moved = []
        for idx, title in enumerate(cur_titles):
            if title in prev_titles and prev_titles.index(title) + 1 != idx + 1:
                moved.append(f"{title}（{prev_titles.index(title) + 1} → {idx + 1}）")
        label = f"{platform} · {kind}" + (f" · {region}" if region else "")
        lines += [
            f"## {label}", "",
            f"- 对比：{prev.get('fetched_at', '?')} → {cur.get('fetched_at', '?')}",
            f"- 新进榜（{len(added)}）：" + ("、".join(added[:10]) or "—"),
            f"- 掉榜（{len(dropped)}）：" + ("、".join(dropped[:10]) or "—"),
            f"- 排位变化（{len(moved)}）：" + ("；".join(moved[:10]) or "—"), "",
        ]
        compared += 1

    if not compared:
        lines.append("（每个平台都还不够两次记录，先多跑几次 hot）")
    text = "\n".join(lines) + "\n"
    print(text)
    if not args.no_save and outdir.exists():
        path = outdir / f"{dt.date.today().isoformat()}-digest.md"
        path.write_text(text, encoding="utf-8")
        print(f"💾 {path}")
    return 0


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
    if args.cmd == "digest":
        return _digest(args, cfg)
    if args.cmd == "news":
        return _news(args, cfg)
    if args.cmd == "schedule":
        return _schedule(args, cfg)
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
