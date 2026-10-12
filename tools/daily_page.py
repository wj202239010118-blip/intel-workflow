#!/usr/bin/env python3
"""生成每日热点页 HTML。

读 out/<date>-*news.jsonl（每站取最新一轮）→ 前 N 条（标题 / 链接 / 摘要）
→ 一份静态 HTML；可写进边缘 KV，由边缘在固定域名下直接返回（不依赖自有服务在线）。

用法：
    python3 tools/daily_page.py                      # → out/<今天>-daily.html
    python3 tools/daily_page.py --top 10 --date 2026-10-12
    python3 tools/daily_page.py --out /tmp/daily.html
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.news import page as news_page  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="生成每日热点页（英文，可托到边缘）")
    ap.add_argument("--outdir", default="out", help="抓取结果目录（读 <date>-*news.jsonl）")
    ap.add_argument("--out", default=None, help="输出文件（默认 <outdir>/<date>-daily.html）")
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--top", type=int, default=news_page.TOP_N, help="取前几条（默认 10）")
    args = ap.parse_args()

    date = args.date or dt.date.today().isoformat()
    pages = news_page.load_latest(args.outdir, date)
    if not pages:
        print(f"⚠️  {args.outdir}/ 里没有 {date} 的抓取结果（先跑 intel news run）")
        return 1

    doc = news_page.render(pages, date, top_n=args.top)
    path = pathlib.Path(args.out) if args.out else pathlib.Path(args.outdir) / f"{date}-daily.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")

    # 同一批条目的 JSON：界面侧也要显示资讯，直接 fetch 这份
    data = news_page.as_json(pages, date, top_n=args.top)
    json_path = path.parent / "daily.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(len(p.get("items", [])) for p in pages)
    print(f"💾 {path}")
    print(f"💾 {json_path}（{len(data['items'])} 条，供界面 fetch）")
    print(f"   {len(pages)} 站 / {total} 条 → 页面上取前 {args.top} 条（英文，零业务语境）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
