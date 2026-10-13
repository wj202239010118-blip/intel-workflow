#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""news_brief.py — 每日 iGaming 行业快讯（**全中文、只推各站"本地当日"的稿**）→ Lark 内部通知群。

    同一次 run：`intel news run` → out/<日期>-*.jsonl（每站最新一轮，全量）
            ↓ 本脚本（按**该站所在时区的今天**筛条目；AI 把英文标题译成中文）
    Lark 内部通知群一条快讯卡片：当日条目（中文标题 · 日期，可点）+ 底部「查看完整资讯」

## 「当日」的判定基准 = 平台自己的时区（2026-10-13 用户口径）

不拿 UTC / 中国的日历日去卡：那四家是欧美行业媒体，中国早上 09:30（UTC 01:30）时
英国才 02:30、阿根廷还在前一天 22:30 —— 用 UTC 日期判定会把 yogonet 当地的**当天稿**
误判成"昨天"而丢掉。所以每个站用它**自己时区的今天**来判，条目日期取发布方标注的日期。
（实测：sbcnews / igamingbusiness → Europe/London；yogonet → America/Argentina/Buenos_Aires。）
不在这里的站按 UTC 处理，宁可保守也不误判成"当天"。

## 三条硬纪律（写进代码，不靠自觉）

1. **只推当日**：按上面的基准筛（`--lookback N` 可放宽到最近 N 天，默认 0）。
   各站都没有当日新稿 → **什么都不发**（打印说明后正常退出；绝不发空卡片、绝不拿旧闻充当日）。
2. **默认 dry-run**：不带 `--send` 只打印；没配 `LARK_WEBHOOK` 时即使带 `--send` 也只打印。
3. **默认拒绝中文**：卡片是中文，属于**内部通知群**口吻（与云腿 daily-report 一致），
   必须显式 `--allow-cjk`。仓库对外的通道仍走 `push.py` 的 `assert_no_cjk`（纯英文）。

## 翻译

标题走 `collab.engines`：本机优先 `claude -p` CLI，云端走 `[collab] openai_*`（CI 用 env 传的
`OPENAI_*` secrets）—— 与 `tools/daily_page.py --analyze` 同一个引擎选择逻辑。
**拿不到引擎 / 翻译失败 → 原样用英文标题并打印警告**（绝不编造、绝不静默降级）。

用法：
    python3 tools/news_brief.py                                   # dry-run：只打印（推荐先跑）
    LARK_WEBHOOK=... python3 tools/news_brief.py --allow-cjk --send   # 真发（内部群）
    python3 tools/news_brief.py --now 2026-10-13T01:30 --lookback 1    # 模拟某个时刻（调试）
"""
import argparse
import html
import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # noqa: E402

from intel_workflow.core.http import Http            # noqa: E402
from intel_workflow.news import page as news_page    # noqa: E402
from intel_workflow.news import push as news_push    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
# A 面资讯页：对外链接一律用 `?news`（Worker 源码注释：URL 里不该出现内部分区的叫法）。
NEWS_URL = "https://kol-ext-gateway.wj202239010118.workers.dev/?news"
PER_SOURCE = 6          # 当日每源最多列几条（当日稿通常很少，这里只防爆量）
HEADLINE_TZ = "Asia/Shanghai"   # 卡片抬头上的日期用中国时间（看的人是中国人）

# 站点所在时区：判定「平台认为的今天」用。不在这里的站按 UTC。
SITE_TZ = {
    "sbcnews.co.uk": "Europe/London",
    "igamingbusiness.com": "Europe/London",
    "www.yogonet.com": "America/Argentina/Buenos_Aires",
    "yogonet.com": "America/Argentina/Buenos_Aires",
    "igaming.news": "UTC",
}

CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

TRANSLATE_PROMPT = """你是 iGaming 行业媒体的中文编辑。把下面每条英文新闻标题翻译成**简体中文**：
- 说人话、行业口吻，不要逐字硬译，不要加原文没有的信息，不要评论、不要加书名号或引号
- 公司名 / 产品名 / 赛事名 / 机构名保留通用写法（如 YouTube、NFL、DATA.BET、Kick、Twitch）
- 只输出一个 JSON 数组，元素是中文标题字符串，**条数和顺序严格与输入一致**，不要任何解释

标题列表：
"""


# ── 取数：jsonl（全量）→ 只留各站「本地当日」的条目 ─────────────────────────

def iso_of(time_text):
    """`09 Oct 2026` → `2026-10-09`；解析不了返回 ""。"""
    try:
        t = time.strptime(str(time_text).strip(), "%d %b %Y")
        return "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
    except Exception:
        return ""


def site_today(site, now):
    """该站所在时区此刻的日期 `YYYY-MM-DD` —— 「平台认为的今天」。"""
    try:
        tz = ZoneInfo(SITE_TZ.get(site, "UTC"))
    except Exception:  # noqa: BLE001  (缺 tzdata 时退回 UTC)
        tz = timezone.utc
    return now.astimezone(tz).strftime("%Y-%m-%d")


def _plain(value):
    """源站标题里常带 HTML 实体（有些还是双重编码）→ 清干净。"""
    text = str(value or "")
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text.strip()


def pick(pages, now, lookback_days=0, per_source=PER_SOURCE):
    """每个来源里**只留发布日期 = 该站当地今天**（或回退窗口内）的条目。

    返回 [(来源名, 当地日期, [row…])]；row = {title, url, time, day}。
    窗口按各站自己的"今天"往前推 lookback_days 天算。
    """
    out = []
    for page in pages:
        site = site_of(page)
        today = site_today(site, now)
        if lookback_days > 0:
            base = datetime.strptime(today, "%Y-%m-%d")
            lo = (base - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        else:
            lo = today
        rows = []
        for item in page.get("items", []):
            metrics = item.get("metrics") or {}
            day = iso_of(metrics.get("time"))
            if not day or day < lo or day > today:
                continue
            rows.append({"title": _plain(item.get("title")), "url": item.get("url") or "",
                         "time": str(metrics.get("time") or ""), "day": day})
        if rows:
            rows.sort(key=lambda r: r["day"], reverse=True)      # 新的在前
            out.append((site, today, rows[:per_source]))
    return out


def site_of(page):
    """来源名：拿第一条 item 的 site（更口语），没有就退回 platform。"""
    for item in page.get("items", []):
        site = (item.get("metrics") or {}).get("site")
        if site:
            return str(site)
    return str(page.get("platform") or "?")


def flat_items(picked):
    return [row for _, _, rows in picked for row in rows]


def cn_day(date_str):
    """`2026-10-12` → `10月12日`。"""
    try:
        t = time.strptime(date_str, "%Y-%m-%d")
        return "%d月%d日" % (t.tm_mon, t.tm_mday)
    except Exception:
        return date_str


# ── 中文标题（AI 翻译；失败就退回英文） ─────────────────────────────────────

def make_engine():
    """可用的翻译引擎：本机 claude CLI 优先，其次 [collab] openai_*（云端走 env）。"""
    from intel_workflow.collab import engines
    from intel_workflow.config import Config

    avail = engines.available(Config())
    if not avail:
        return None, ""
    name = "claude" if "claude" in avail else sorted(avail)[0]
    return avail[name], name


def _parse_titles(raw, n):
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        raise ValueError("引擎没返回 JSON 数组：%s" % (raw or "")[:160])
    arr = json.loads(text[start:end + 1])
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError("条数对不上：要 %d 条，拿到 %d 条" % (n, len(arr) if isinstance(arr, list) else -1))
    out = [str(x).strip() for x in arr]
    if any(not x for x in out):
        raise ValueError("有空白标题")
    return out


def translate_titles(items, engine):
    """[条目] → [中文标题]。抛异常交给调用方决定降级。"""
    listing = "\n".join("%d. %s" % (i, it["title"]) for i, it in enumerate(items, 1))
    return _parse_titles(engine(TRANSLATE_PROMPT + listing), len(items))


# ── 卡片 ────────────────────────────────────────────────────────────────────

def _md_title(text):
    """标题里的 markdown 元字符会破坏链接语法。"""
    return str(text).replace("**", "").replace("[", "（").replace("]", "）")


def _div(markdown):
    return {"tag": "div", "text": {"tag": "lark_md", "content": markdown}}


def card(title, picked, zh, note=""):
    """卡片：抬头 + 每个来源一块（中文条目 · 该站日期）+ 底部按钮。只含各站当地当日的条目。"""
    n = sum(len(rows) for _, _, rows in picked)
    head = "**今日 iGaming 行业动态**\n%d 条 / %d 个来源 · 各站按**自身时区的当天**取稿" % (n, len(picked))
    if note:
        head += "\n" + note
    blocks = [_div(head)]
    idx = 0
    for site, today, rows in picked:
        lines = ["**%s**（%s）" % (site, cn_day(today))]
        for row in rows:
            label = zh[idx] if zh else row["title"]
            lines.append("[%s](%s) · %s" % (_md_title(label), row["url"], cn_day(row["day"])))
            idx += 1
        blocks.append(_div("\n".join(lines)))
    blocks.append({"tag": "action", "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看完整资讯"},
         "url": NEWS_URL, "type": "primary"}]})
    return {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": str(title)[:120]}},
        "elements": blocks}}


def flat_text(title, picked, zh):
    """给中文闸看的纯文本。"""
    parts = [title]
    idx = 0
    for site, _today, rows in picked:
        parts.append(site)
        for _ in rows:
            parts.append(zh[idx] if zh else "")
            idx += 1
    return "\n".join(parts)


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="日报 → Lark 内部群快讯卡片（全中文、只推各站当地当日）")
    ap.add_argument("--outdir", default=OUT, help="抓取结果目录（读 <date>-*.jsonl）")
    ap.add_argument("--date", default="", help="读哪天的 jsonl（默认按 HEADLINE_TZ 的今天）")
    ap.add_argument("--now", default="", help="把这个时刻当成'现在'（ISO，调试用；如 2026-10-13T01:30）")
    ap.add_argument("--lookback", type=int, default=0,
                    help="放宽到最近 N 天（默认 0 = 严格各站当地当天）")
    ap.add_argument("--limit", type=int, default=PER_SOURCE, help="每源最多几条（默认 6）")
    ap.add_argument("--no-translate", action="store_true", help="不译中文，直接用英文原标题")
    ap.add_argument("--allow-cjk", action="store_true",
                    help="显式允许外发中文（本脚本只给**内部通知群**用；默认拒绝）")
    ap.add_argument("--send", action="store_true", help="真发（默认 dry-run 只打印）")
    ap.add_argument("--json", action="store_true", help="打印将要发送的 payload")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    if a.now:
        parsed = datetime.fromisoformat(a.now)
        now = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    today_cn = now.astimezone(ZoneInfo(HEADLINE_TZ)).strftime("%Y-%m-%d")
    date = a.date or today_cn
    pages = news_page.load_latest(a.outdir, date)
    if not pages:
        print("❌ 找不到 %s 的抓取结果（%s/<date>-*.jsonl）——先跑 `./intel news run`" % (date, a.outdir))
        return 1

    total = sum(len(p.get("items") or []) for p in pages)
    picked = pick(pages, now, a.lookback, a.limit)
    if not picked:
        # 各站都没有"当地当天"的稿：不发空卡片、不拿旧闻充当日
        print("ℹ️  %s 各来源**没有当地当天的新稿** → 不发。" % today_cn)
        print("    （抓取共 %d 条 / %d 个来源）" % (total, len(pages)))
        for page in pages:
            site = site_of(page)
            print("      · %-22s 它那边的今天是 %s" % (site, site_today(site, now)))
        return 0

    items = flat_items(picked)
    zh, engine_name = None, ""
    if not a.no_translate:
        engine, engine_name = make_engine()
        if not engine:
            print("⚠️  没有可用翻译引擎（需要本机 `claude` CLI，或 [collab] openai_* / OPENAI_* 环境变量）"
                  " → 保留英文原标题")
        else:
            try:
                zh = translate_titles(items, engine)
            except Exception as exc:  # noqa: BLE001
                # 翻译是可选步骤：端点被拦 / 超时 / 返回非 JSON 都不能拖垮发送，退回英文并说清楚
                print("⚠️  翻译失败（%s: %s）→ 保留英文原标题"
                      % (type(exc).__name__, str(exc)[:140]))
                zh = None

    title = "iGaming 行业快讯 · %s" % cn_day(today_cn)
    payload = card(title, picked, zh)

    print("▶ 抓取: %d 条 / %d 个来源（jsonl 日期 %s）" % (total, len(pages), date))
    print("▶ 当日快讯: %d 条 / %d 个来源 · 窗口=%s · 抬头日期=%s（中国）"
          % (len(items), len(picked),
             ("各站当地当天" if not a.lookback else "各站当地近 %d 天" % a.lookback),
             today_cn))
    print("\n===== 卡片预览 =====")
    print("[标题] " + title)
    for el in payload["card"]["elements"]:
        if el.get("tag") == "div":
            for ln in el["text"]["content"].split("\n"):
                print("  " + ln)
        elif el.get("tag") == "action":
            print("[底部按钮] %s → %s" % (el["actions"][0]["text"]["content"], el["actions"][0]["url"]))
    print("===== 预览结束 =====\n")

    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    # ⚠️ 中文闸：与仓库对外通道同一口径（对外只允许 EN/ES）——
    #    内部群场景需显式 --allow-cjk，别把它变成默认行为。
    hit = CJK.search(flat_text(title, picked, zh))
    if hit and not a.allow_cjk:
        print("⛔ 外发内容含中文字符 %r —— 默认不允许（对外只允许 EN/ES）。" % hit.group(0))
        print("   确认是**内部通知群**再加 --allow-cjk。")
        return 2

    webhook = os.environ.get("LARK_WEBHOOK", "").strip()
    secret = os.environ.get("LARK_SECRET", "").strip()
    if not a.send or not webhook:
        print("[dry-run] 未发送（--send=%s / webhook=%s）" % (a.send, "有" if webhook else "无"))
        return 0

    resp = news_push.send_lark(webhook, payload, Http(), secret=secret)
    print("飞书返回：%s" % str(resp)[:300])
    print("✅ 已发送到 Lark 内部通知群（自定义机器人无法撤回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
