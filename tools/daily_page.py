#!/usr/bin/env python3
"""生成每日热点页 HTML。

读 out/<date>-*news.jsonl（每站取最新一轮）→ **按来源分区**，每站列自己的前 N 条（标题 / 链接 / 摘要）
→ 一份静态 HTML；可写进边缘 KV，由边缘在固定域名下直接返回（不依赖自有服务在线）。

用法：
    python3 tools/daily_page.py                          # → out/<今天>-daily.html
    python3 tools/daily_page.py --per-site 10 --date 2026-10-12
    python3 tools/daily_page.py --out /tmp/daily.html
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.news import page as news_page  # noqa: E402


def _analyze(pages, per_site):
    """按需跑分类分析：热点 / 正向 / 负向 + 主题解读。

    引擎 = 本机 `claude` CLI（首选）或 config.toml 的 `[collab] openai_*`。
    不可用 → 返回 None：页面照常生成，只是**没有**分类与解读 —— 绝不编造。
    """
    from intel_workflow.collab import engines
    from intel_workflow.config import Config
    from intel_workflow.news import analyze as news_analyze

    avail = engines.available(Config())
    if not avail:
        print("⚠️  跳过分析：需要本机 `claude` CLI，或在 config.toml 配 [collab] openai_*")
        return None
    name = "claude" if "claude" in avail else sorted(avail)[0]
    rows = news_page.collect(pages, per_site)          # 与 render 内部取的是同一批、同一顺序
    try:
        result = news_analyze.analyze(rows, engine=avail[name])
    except Exception as exc:  # noqa: BLE001
        # 分析是**可选**步骤：端点被拦截 / 超时 / 返回非 JSON，都不能拖垮日报生成。
        # （2026-10-12 INC-20261012-02：云端要走 GPT 端点，而它可能被 CF 拦 → 必须降级而不是崩）
        print(f"⚠️  分析失败（{type(exc).__name__}: {str(exc)[:120]}）→ 不带分析继续")
        return None
    print(f"🧠 {name} 分析 {len(result['items'])} 条 → {len(result['themes'])} 个主题")
    return result


def main():
    ap = argparse.ArgumentParser(description="生成每日热点页（英文，可托到边缘）")
    ap.add_argument("--outdir", default="out", help="抓取结果目录（读 <date>-*news.jsonl）")
    ap.add_argument("--out", default=None, help="输出文件（默认 <outdir>/<date>-daily.html）")
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认：读本机本地日、页面显示中国日）")
    ap.add_argument("--now", default="",
                    help="把这个时刻当成'现在'（ISO，调试用；只影响页面上的中国日期）")
    ap.add_argument("--per-site", type=int, default=news_page.PER_SITE_N,
                    help="每个来源列几条；0 = 不限（默认：各平台穷举）")
    ap.add_argument("--analyze", action="store_true",
                    help="跑分类分析（热点 / 正向 / 负向 + 主题解读）：本机 claude CLI 或 [collab] openai_*")
    args = ap.parse_args()

    # 读文件的日期：产物 out/<date>-*news.jsonl 的 <date> 跟 intel save 一样取**本机本地日**
    # （CI runner 即 UTC）——同机同口径。**别换成 ZoneInfo**，否则会像 news_brief 那样在
    # 16:00 UTC 触发时错位一天（找次日的文件、目录里只有当日的）。
    date = args.date or dt.date.today().isoformat()
    pages = news_page.load_latest(args.outdir, date)
    if not pages:
        print(f"⚠️  {args.outdir}/ 里没有 {date} 的抓取结果（先跑 intel news run）")
        return 1

    # 页面/JSON 上「这一期是哪天」按**中国时间**（读的人在中国，与 Lark 卡片抬头同口径）：
    # 欧美站的稿子换算过来常常已跨日 → 页面显示的就是换算后的中国日期。
    if args.date:
        show_date = args.date
    else:
        _now = dt.datetime.now(dt.timezone.utc)
        if args.now:
            _p = dt.datetime.fromisoformat(args.now)
            _now = _p.replace(tzinfo=dt.timezone.utc) if _p.tzinfo is None else _p
        show_date = _now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()

    analysis = _analyze(pages, args.per_site) if args.analyze else None

    doc = news_page.render(pages, show_date, per_site=args.per_site, analysis=analysis)
    path = pathlib.Path(args.out) if args.out else pathlib.Path(args.outdir) / f"{date}-daily.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")

    # 收录页（同一站点的第二个页面 `/?top`）：同一批条目，但把各家热门榜**完整收全**
    # ——首页侧栏只放前 4 条，这里全收（照 igaming.news 的 /top-reads）。
    # 写在 daily.html 同目录，便于一起推上边缘 KV。
    top_path = path.parent / "top.html"
    top_path.write_text(news_page.render_top(pages, show_date), encoding="utf-8")
    print(f"💾 {top_path}（收录页 /?top）")

    # 同一批条目的 JSON：界面侧也要显示资讯，直接 fetch 这份
    data = news_page.as_json(pages, show_date, per_site=args.per_site, analysis=analysis)
    json_path = path.parent / "daily.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(len(p.get("items", [])) for p in pages)
    print(f"💾 {path}")
    print(f"💾 {json_path}（{len(data['items'])} 条，供界面 fetch）")
    scope = f"每站前 {args.per_site} 条" if args.per_site and args.per_site > 0 else "各来源全列"
    print(f"   {len(pages)} 站 / {total} 条 → {scope}（英文，零业务语境）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
