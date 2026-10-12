"""跨站整合日报：把本次各站抓取合并成一份简报，并标注「NEW / seen」。

**正文一律英文** —— 这份简报会直接进推送通道（Lark / 邮件），对外的内容不允许中文
（见 push.assert_no_cjk）。终端摘要可以中文，日报正文不行。

不联网：历史来自 out/ 目录里的 *-news.jsonl（每次运行追加），因此
  · 「新进」= 本次条目中此前任何一次快照都没出现过的 URL
  · 「健康」= 与各站上一次快照的条目数对比，骤降就在日报里点名（改版/被封的第一信号）
"""
import datetime as dt
import json
import pathlib

NEW_MARK = "**NEW**"


def scan(outdir):
    """扫历史快照 → (出现过的 URL 集合, {站点: 最近一次条目数})。"""
    urls, counts, latest = set(), {}, {}
    directory = pathlib.Path(outdir)
    if not directory.exists():
        return urls, counts
    for path in sorted(directory.glob("*-news.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            platform = rec.get("platform", "?")
            for item in rec.get("items", []):
                if item.get("url"):
                    urls.add(item["url"])
            stamp = rec.get("fetched_at", "")
            if platform not in latest or stamp >= latest[platform]:
                latest[platform] = stamp
                counts[platform] = len(rec.get("items", []))
    return urls, counts


def history_urls(outdir):
    """出现过的 URL 集合（不含本次）。"""
    return scan(outdir)[0]


def health_notices(prev_counts, intels, min_ratio=0.4, floor=3):
    """条目数骤降 → 英文告警行（进日报）。少于上次的 40% 且低于 3 条才算异常。"""
    notices = []
    for intel in intels:
        prev = prev_counts.get(intel.platform)
        current = len(intel.items)
        if prev and current < max(floor, prev * min_ratio):
            notices.append(
                f"{intel.platform}: only {current} items vs {prev} last run — layout may have changed or access is limited"
            )
    return notices


def build(intels, history, per_site=10, failures=None, notices=None, fetched_at=None):
    """intels + 历史 URL 集合 → (英文 markdown, stats dict)。"""
    fetched_at = fetched_at or dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    date = fetched_at[:10]
    total = sum(len(i.items) for i in intels)
    new_items = [it for i in intels for it in i.items if it.url not in history]
    first_run = not history
    stats = {
        "sites": len(intels),
        "failed": len(failures or []),
        "items": total,
        "new": len(new_items),
        "first_run": first_run,
    }

    lines = [
        f"# iGaming News Digest — {date}",
        "",
        f"_Fetched {fetched_at} · {stats['sites']} sources"
        + (f" · {stats['failed']} failed" if stats["failed"] else "")
        + f" · {total} items · {len(new_items)} new_",
        "",
    ]
    if first_run:
        lines += ["_First run for this machine: no history yet, so every item is listed._", ""]
    for notice in notices or []:
        lines.append(f"> ⚠️ {notice}")
    if notices:
        lines.append("")

    for intel in intels:
        fresh = sum(1 for it in intel.items if it.url not in history)
        lines.append(f"## {intel.platform} ({intel.source.split(' ')[0]}) — {len(intel.items)} items · {fresh} new")
        for item in intel.items[:per_site]:
            stamp = (item.metrics or {}).get("time") or ""
            mark = f"{NEW_MARK} " if item.url not in history else ""
            tail = f" — {stamp}" if stamp else ""
            title = item.title.replace("[", "(").replace("]", ")")
            lines.append(f"- {mark}[{title}]({item.url}){tail}" if item.url else f"- {mark}{title}{tail}")
        if len(intel.items) > per_site:
            lines.append(f"- _… {len(intel.items) - per_site} more from this source_")
        lines.append("")

    if failures:
        lines.append("## Sources not fetched")
        for key, reason in failures:
            lines.append(f"- {key}: {reason}")
        lines.append("")

    return "\n".join(lines) + "\n", stats


def save(markdown, outdir="out", date=None):
    directory = pathlib.Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    date = date or dt.date.today().isoformat()
    path = directory / f"{date}-news-digest.md"
    path.write_text(markdown, encoding="utf-8")
    return path
