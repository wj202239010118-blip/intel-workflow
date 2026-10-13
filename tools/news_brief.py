#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""news_brief.py — 每日 iGaming 行业快讯（**全中文、只推当日新闻**）→ Lark 内部通知群。

    同一次 run：`intel news run` → out/<日期>-*.jsonl（每站最新一轮，全量）
            ↓ 本脚本（按**发布日期**只留当天的条目；AI 把英文标题译成中文）
    Lark 内部通知群一条快讯卡片：当日条目（中文标题 · 日期，可点）+ 底部「查看完整资讯」

## 为什么取 jsonl 而不是日报 md（2026-10-12 修正）

日报 md 每源只列 15 条，而站点列表页的顺序**不保证最新在前**（实测 igaming.news 前 10 条
全是 3 天前的稿）—— 当日稿会被截断在外。看板页走的是同一份 jsonl（`page.load_latest`），
所以这里也从 jsonl 取数：**快讯与看板同源同批**。

## 三条硬纪律（写进代码，不靠自觉）

1. **只推当日**：按发布日期筛（`--lookback N` 可放宽到最近 N 天，默认 0=严格当日）。
   当天各源都没有新稿 → **什么都不发**（打印说明后正常退出；绝不发空卡片、绝不拿旧闻充当日）。
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
    python3 tools/news_brief.py --date 2026-10-12 --lookback 3 --limit 3
"""
import argparse
import html
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # noqa: E402

from intel_workflow.core.http import Http            # noqa: E402
from intel_workflow.news import page as news_page    # noqa: E402
from intel_workflow.news import push as news_push    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
# A 面资讯页：对外链接一律用 `?news`（Worker 源码注释：URL 里不该出现内部分区的叫法）。
NEWS_URL = "https://kol-ext-gateway.wj202239010118.workers.dev/?news"
PER_SOURCE = 6          # 当日每源最多列几条（当日稿通常很少，这里只防爆量）

CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

TRANSLATE_PROMPT = """你是 iGaming 行业媒体的中文编辑。把下面每条英文新闻标题翻译成**简体中文**：
- 说人话、行业口吻，不要逐字硬译，不要加原文没有的信息，不要评论、不要加书名号或引号
- 公司名 / 产品名 / 赛事名 / 机构名保留通用写法（如 YouTube、NFL、DATA.BET、Kick、Twitch）
- 只输出一个 JSON 数组，元素是中文标题字符串，**条数和顺序严格与输入一致**，不要任何解释

标题列表：
"""


# ── 取数：jsonl（全量）→ 只留当日的条目 ─────────────────────────────────────

def iso_of(time_text):
    """`09 Oct 2026` → `2026-10-09`；解析不了返回 ""。"""
    try:
        t = time.strptime(str(time_text).strip(), "%d %b %Y")
        return "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
    except Exception:
        return ""


def _plain(value):
    """源站标题里常带 HTML 实体（有些还是双重编码）→ 清干净。"""
    text = str(value or "")
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text.strip()


def pick(pages, date, lookback_days=0, per_source=PER_SOURCE):
    """每个来源里**只留发布日期在窗口内**的条目（默认只有 date 当天）。

    返回 [(来源名, [row…])]，只含有内容的来源；row = {title, url, time, day}。
    窗口 = [date - lookback_days, date]（按字符串比即可，ISO 日期天然可比）。
    """
    lo = date
    if lookback_days > 0:
        lo = time.strftime("%Y-%m-%d", time.localtime(
            time.mktime(time.strptime(date, "%Y-%m-%d")) - lookback_days * 86400))
    out = []
    for page in pages:
        site = site_of(page)
        rows = []
        for item in page.get("items", []):
            metrics = item.get("metrics") or {}
            day = iso_of(metrics.get("time"))
            if not day or day < lo or day > date:
                continue
            rows.append({"title": _plain(item.get("title")), "url": item.get("url") or "",
                         "time": str(metrics.get("time") or ""), "day": day})
        if rows:
            rows.sort(key=lambda r: r["day"], reverse=True)      # 新的在前
            out.append((site, rows[:per_source]))
    return out


def site_of(page):
    """来源名：拿第一条 item 的 site（更口语），没有就退回 platform。"""
    for item in page.get("items", []):
        site = (item.get("metrics") or {}).get("site")
        if site:
            return str(site)
    return str(page.get("platform") or "?")


def flat_items(picked):
    return [row for _, rows in picked for row in rows]


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


def card(title, picked, zh, date_str):
    """卡片：抬头 + 每个来源一块（中文条目 · 日期）+ 底部按钮。只含当日条目。"""
    n = sum(len(rows) for _, rows in picked)
    blocks = [_div("**今日 iGaming 行业动态**\n%s · 共 %d 条 / %d 个来源 · 仅当日新稿"
                   % (cn_day(date_str), n, len(picked)))]
    idx = 0
    for site, rows in picked:
        lines = ["**%s**" % site]
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
    for site, rows in picked:
        parts.append(site)
        for _ in rows:
            parts.append(zh[idx] if zh else "")
            idx += 1
    return "\n".join(parts)


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="日报 → Lark 内部群快讯卡片（全中文、只推当日）")
    ap.add_argument("--date", default="", help="日期 YYYY-MM-DD（默认今天）；读 out/<date>-*.jsonl")
    ap.add_argument("--lookback", type=int, default=0,
                    help="放宽到最近 N 天（默认 0 = 严格只当日）")
    ap.add_argument("--limit", type=int, default=PER_SOURCE, help="每源最多几条（默认 6）")
    ap.add_argument("--no-translate", action="store_true", help="不译中文，直接用英文原标题")
    ap.add_argument("--allow-cjk", action="store_true",
                    help="显式允许外发中文（本脚本只给**内部通知群**用；默认拒绝）")
    ap.add_argument("--send", action="store_true", help="真发（默认 dry-run 只打印）")
    ap.add_argument("--json", action="store_true", help="打印将要发送的 payload")
    a = ap.parse_args()

    date = a.date or time.strftime("%Y-%m-%d")
    pages = news_page.load_latest(OUT, date)
    if not pages:
        print("❌ 找不到 %s 的抓取结果（%s/<date>-*.jsonl）——先跑 `./intel news run`" % (date, OUT))
        return 1

    total = sum(len(p.get("items") or []) for p in pages)
    picked = pick(pages, date, a.lookback, a.limit)
    if not picked:
        # 当日各源都没有新稿：不发空卡片、不拿旧闻充当日（用户口径：只推当日）
        print("ℹ️  %s 各来源**没有当日新稿** → 不发。" % date)
        print("    （抓取共 %d 条 / %d 个来源，但发布日期都不是 %s）" % (total, len(pages), date))
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

    title = "iGaming 行业快讯 · %s" % cn_day(date)
    payload = card(title, picked, zh, date)

    print("▶ 抓取: %d 条 / %d 个来源（%s）" % (total, len(pages), date))
    print("▶ 当日快讯: %d 条 / %d 个来源 · 窗口=%s · 标题=%s"
          % (len(items), len(picked),
             ("当日" if not a.lookback else "最近 %d 天" % a.lookback),
             ("中文（%s）" % engine_name) if zh else "英文原文"))
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
