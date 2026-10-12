#!/usr/bin/env python3
"""把当天前 N 条推成一条 Lark 卡片：序号标题（指向我们的页面）+ 一句摘要。

链接指向**我们自己的页面**（固定域名），不是原站 —— 每条带 `#n` 锚点，点进去直接定位；
页面上再点标题才去原站。这样群里的入口始终是我们那个域名。

用法：
    PUBLIC_BASE_URL=https://example.com python3 tools/push_top.py --top 10            # 只打印（dry-run）
    PUBLIC_BASE_URL=https://example.com python3 tools/push_top.py --top 10 --send     # 真发
    python3 tools/push_top.py --top 10 --date 2026-10-12 --outdir out

凭据（真发才需要）：
    LARK_WEBHOOK   自定义机器人 webhook
    LARK_SECRET    机器人开了签名校验时才有
没有凭据 / 不带 --send → 只打印将要发送的内容（绝不静默发送）。
"""
import argparse
import datetime as dt
import html
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.news import page as news_page      # noqa: E402
from intel_workflow.news import push as news_push      # noqa: E402


def _text(value):
    """清掉残留的 HTML 实体（有些源是双重编码）—— 推送里不该出现 `&#39;` 这种东西。"""
    text = str(value or "")
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


def build_message(items, base, date):
    """前 N 条 → Lark markdown（英文）：`1. [标题](base#1)` + 摘要。"""
    lines = [f"**iGaming Daily — {date}**", ""]
    for idx, row in enumerate(items, 1):
        title = _text(row["title"]).replace("[", "(").replace("]", ")")
        if base:
            lines.append(f"**{idx}.** [{title}]({base.rstrip('/')}/#{idx})")
        else:
            lines.append(f"**{idx}.** {title}")
        summary = _text(row["summary"])
        if summary:
            lines.append(f"> {summary}")
        meta = " · ".join(_text(x) for x in (row["site"], row["time"]) if x)
        if meta:
            lines.append(f"> _({meta})_")
        lines.append("")
    if base:
        lines.append(f"[Open today's page]({base.rstrip('/')}/)")
    return "\n".join(lines).strip()


def main():
    ap = argparse.ArgumentParser(description="当天前 N 条 → Lark 卡片（链接指向我们的页面）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--date", default=None)
    ap.add_argument("--top", type=int, default=news_page.TOP_N)
    ap.add_argument("--base", default=os.environ.get("PUBLIC_BASE_URL", "").strip(),
                    help="我们页面的基址（留空则只列标题，不加链接）")
    ap.add_argument("--send", action="store_true", help="真发（默认只打印）")
    args = ap.parse_args()

    date = args.date or dt.date.today().isoformat()
    pages = news_page.load_latest(args.outdir, date)
    if not pages:
        print(f"⚠️  {args.outdir}/ 里没有 {date} 的抓取结果（先跑 intel news run）")
        return 1

    items = news_page._all_items(pages)[:args.top]
    title = f"iGaming Daily — {date}"
    body = build_message(items, args.base, date)
    news_push.assert_no_cjk(title + "\n" + body)          # 外发禁中文（硬校验）

    webhook = os.environ.get("LARK_WEBHOOK", "").strip()
    secret = os.environ.get("LARK_SECRET", "").strip()

    print(f"=== 预览（{len(items)} 条{'' if args.base else '，未设 PUBLIC_BASE_URL 故无链接'}）===")
    print(body)
    print()

    if not args.send or not webhook:
        print(f"[dry-run] 未发送（--send={args.send} / webhook={'有' if webhook else '无'}）")
        return 0

    from intel_workflow.core.http import Http
    payload = news_push.lark_payload(title, body)
    news_push.send_lark(webhook, payload, Http(), secret=secret)
    print("✅ 已发送到 Lark（自定义机器人无法撤回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
