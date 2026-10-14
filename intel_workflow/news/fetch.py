"""资讯站取数：三条通道，按站点配置自动选。

  1. **feed（首选）** —— 站点给了 RSS/Atom 地址就走 core.http 一次普通 GET：
     无浏览器、无 consent 墙、无反爬判定，最稳也最轻（闸门由 core.http 内部 check/record）。
  2. **sitemap** —— 没有 feed 但给了 XML sitemap 地址：同样纯 HTTP。指向的是 sitemapindex
     时自动跟一层到子 sitemap（优先名字含 news 的，如 /news-sitemap.xml）；跟随时按闸门的
     最小间隔等待，不绕过限速。**有了 feed 或 sitemap，就完全不需要 node + playwright。**
  3. **浏览器** —— 两者都没有才渲染列表页：有头（默认）或 `--headless`，持久 profile
     复用 cookie / consent 选择 / 登录态。浏览器子进程本身绕过 core.http，所以调用前后
     显式 gate.check / gate.record（每个域名每天一次导航）。

条目的 metrics 里除 `time`（给人看）与 `site` 外，还带 `ts`（可比较的 ISO 时间戳，跨站排序用）
与 `summary`（摘要，推送卡片用）—— 后者只有 feed 通道拿得到，sitemap 本身不带摘要。

另外提供 profile_lock()：定时任务与手动跑同时用同一个 profile 会让两边都起不来
（Chromium 的 ProcessSingleton），所以整轮抓取先拿这把文件锁。
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import time

from ..adapters.base import Degraded
from ..core import node
from ..core.gate import RateLimited
from ..core.model import Intel, Item
from . import feed as feed_parser
from . import sitemap as sitemap_parser

TOOLS = pathlib.Path(__file__).resolve().parent.parent.parent / "tools" / "news_fetch.js"
DEFAULT_PROFILE = pathlib.Path.home() / ".cache" / "intel-workflow" / "browser-profile"


def profile_dir(cfg=None):
    if cfg is not None:
        value = cfg.section("news").get("profile_dir")
        if value:
            return str(pathlib.Path(str(value)).expanduser())
    return str(DEFAULT_PROFILE)


def wants_headless(cfg=None):
    """默认**有头**；config 里显式 headless = true 才无头。"""
    if cfg is not None:
        return cfg.section("news").get("headless") is True
    return False


def channel_of(site):
    """这个站点会走哪条通道（打印/测试用）。"""
    if site.feed:
        return "feed"
    if site.sitemap:
        return "sitemap"
    return "browser"


def _items_from(parsed, site):
    """解析结果 → Item 列表（统一带上 time / site / ts / summary）。"""
    return [
        Item(
            rank=it["rank"], title=it["title"], url=it["url"],
            metrics={
                "time": it.get("time", ""),
                "site": site.domain,
                "ts": it.get("ts", ""),
                "summary": it.get("summary", ""),
                "image": it.get("image", ""),
                "category": it.get("category", ""),
            },
        )
        for it in parsed
    ]


# --- 通道 1：feed（无浏览器） ---

def fetch_feed(site, http, limit=None):
    """RSS/Atom → Intel。取不到就抛 Degraded，绝不返回空榜糊弄。"""
    try:
        _wait_min_interval(http)   # 榜单腿可能刚请求过同域 → 先等够间隔再发（云端实测踩到过）
        _status, text = http.get(site.feed, domain=site.domain)
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001 — 网络/HTTP 错误都算「这个站这轮拿不到」
        raise Degraded(f"{site.key}：feed 取不到 → {type(exc).__name__}: {exc}")

    items = _items_from(feed_parser.parse(text, limit=limit or site.limit), site)
    if not items:
        raise Degraded(f"{site.key}：feed 有响应但解析不出条目（地址还是 RSS 吗？）")
    # RSS 常常不带配图（sbcnews 尤其：整站对 HTTP 403，图在独立子域）→ 按站点策略补图。
    # 只补缺图的、限量、走闸门；补不到也不影响这条通道（图是增强项）。
    fill_article_images(site, http, items)
    return Intel(
        platform=site.key, kind="news", method="feed",
        source=f"{site.domain} RSS/Atom feed（HTTP，无浏览器）",
        confidence="high", items=items,
    )


# --- 通道 2：sitemap（无浏览器） ---

def _wait_min_interval(http):
    """同域连发第二次请求前，等够闸门的最小间隔（尊重闸门，不绕过）。"""
    gate = getattr(http, "gate", None)
    gap = int(getattr(gate, "min_interval", 0) or 0)
    if gap > 0:
        time.sleep(gap + 1)


def og_from(html):
    """文章页 HTML → 首图（og:image / twitter:image）+ 分类（articleSection / category 链接）。

    与 Worker 实时腿里的 `_ogFrom` 同规则 —— 两边都靠这一对字段给 sitemap 源补图文卡。
    """
    text = html or ""
    m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', text, re.I)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', text, re.I)
         or re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', text, re.I))
    category = ""
    jl = re.search(r'"articleSection"\s*:\s*"([^"]+)"', text, re.I)
    if jl:
        category = feed_parser._clean(jl.group(1))
    if not category:
        a = re.search(r'<a[^>]+href=["\'][^"\']*?/category/([^"\'/]+)["\']', text, re.I)
        if a:
            category = feed_parser._clean(a.group(1)).replace("-", " ")
    return {"image": feed_parser._clean(m.group(1)) if m else "", "category": category[:40]}


def fill_article_images(site, http, items, cap=15):
    """sitemap 通道天生不给图 → 逐篇抓文章页抽 og:image / 分类。

    三条约束（与 Worker 侧一致，理由是同一个）：**只补缺图的**、**最多 cap 篇**、
    抓取走 `http` 的限流闸门（篇间自动留间隔）。这是"逐篇抓"，比"一次 GET 拿全量"重得多，
    所以只能在这个量级上做（一天一次 × 15 篇），绝不放宽。

    图是**增强项**：单篇抓失败就跳过，绝不让它拖垮整条通道。
    """
    todo = [it for it in items if not (it.metrics or {}).get("image")][:cap]
    if getattr(site, "browser_og", False):
        # 整站对 HTTP 一律 403 的站（sbcnews.co.uk）：HTTP 抓文章页只会拿到 403 的挑战页，
        # 图 URL 只能由真实浏览器读 og:image 得到 → 换一条腿（每轮上限更小，只读不下载）。
        return _fill_images_via_browser(site, items, cap=4)
    for it in todo:
        # 闸门要求同域两次请求之间留够间隔（默认 15s），而 http.get **不会自己等**：间隔不够
        # 直接抛 RateLimited。原先的 `except Exception: continue` 会把限流一起吞掉 → 15 篇全被
        # 静默跳过、图一张都没补上（2026-10-14 实测踩到）。
        _wait_min_interval(http)
        try:
            _status, html = http.get(it.url, domain=site.domain)
        except RateLimited:
            break                              # 撞到闸门别硬来：剩下的留到下一天
        except Exception:  # noqa: BLE001
            continue
        got = og_from(html)
        metrics = it.metrics or {}
        if got["image"]:
            metrics["image"] = got["image"]
        if got["category"] and not metrics.get("category"):
            metrics["category"] = got["category"]
        it.metrics = metrics
    return items


def _fill_images_via_browser(site, items, cap=4, headless=True, profile=None):
    """整站对普通 HTTP 一律 403 的站（sbcnews.co.uk）：用浏览器**只读一次**文章页拿 og:image。

    为什么值得单开一条腿（2026-10-14 实测）：它的图不在主域，而在 resources.sbcnews.co.uk ——
    Cloudflare 只放行图片扩展名（单张图 200 image/jpeg），目录 / S3 列表 API 一律 403；文件名又不是
    文章 slug（按 slug 拼是 404）。文章页 HTML 里的 og:image 是唯一出口，而它必须由真实浏览器读
    （浏览器能跑 JS 过那个挑战）。顺带把 article:section 当分类补上。

    两条硬约束：
    - **每轮最多 cap 篇（默认 4）**：一次调用 = 一次页面加载 + 可能要等挑战（数秒），比 HTTP 逐篇重得多。
      所以只喂"最需要图的位置"（调用方已排序）。
    - **只读 URL、不下载图片**：把图 URL 记下来即可，图片由访客浏览器直接从那个子域加载。

    图是增强项：任何一步失败都只跳过这一篇，绝不拖垮主线。
    """
    todo = [it for it in items if not (it.metrics or {}).get("image")][:cap]
    if not todo or not node.node_available():
        return items
    for it in todo:
        # 先等够闸门要求的同域间隔再问闸门 —— 调用这条腿之前刚抓过同一个域的 feed，
        # 直接 check 会因为还在冷却里被拒，结果一张图都补不到（2026-10-14 云端实测踩到）。
        _wait_min_interval(http)
        allowed, _why = http.gate.check(site.domain)
        if not allowed:
            break                                  # 撞到闸门别硬来：剩下的留到下一天
        args = [
            "--og=1", f"--url={it.url}", f"--domain={site.domain}",
            f"--headless={1 if headless else 0}", "--wait=6000", "--timeout=45000",
        ]
        if profile:
            args.append(f"--profile={profile}")
        try:
            _rc, out, err = node.run_node(TOOLS, args, timeout=180)
        except Exception:  # noqa: BLE001 — 超时/启动失败都算这篇没拿到
            http.gate.record(site.domain)
            continue
        http.gate.record(site.domain)
        if node.missing_playwright((err or "").strip()):
            break                                  # 环境没有浏览器：这条腿本轮作废，别逐篇重试
        line = ""
        for cand in reversed((out or "").strip().splitlines()):
            if cand.strip().startswith("{"):
                line = cand.strip()
                break
        try:
            og = (json.loads(line) or {}).get("og") or {}
        except Exception:  # noqa: BLE001 — 拿不到就跳过这篇
            continue
        metrics = it.metrics or {}
        if og.get("image"):
            metrics["image"] = og["image"]
        if og.get("category") and not metrics.get("category"):
            metrics["category"] = og["category"]
        it.metrics = metrics
    return items


def fetch_sitemap(site, http, limit=None):
    """XML sitemap → Intel；是 sitemapindex 就自动跟一层到含 "news" 的子 sitemap。"""
    url = site.sitemap
    try:
        _wait_min_interval(http)   # 同上：榜单腿可能刚请求过同域
        _status, text = http.get(url, domain=site.domain)
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001
        raise Degraded(f"{site.key}：sitemap 取不到 → {type(exc).__name__}: {exc}")

    if sitemap_parser.is_index(text):
        children = sitemap_parser.child_sitemaps(text)
        if children:
            url = children[0]
            _wait_min_interval(http)
            try:
                _status, text = http.get(url, domain=site.domain)
            except RateLimited:
                raise
            except Exception as exc:  # noqa: BLE001
                raise Degraded(f"{site.key}：子 sitemap 取不到（{url}）→ {type(exc).__name__}: {exc}")

    items = _items_from(sitemap_parser.parse(text, limit=limit or site.limit), site)
    if not items:
        raise Degraded(
            f"{site.key}：sitemap 有响应但解析不出条目"
            "（把 [news.sitemaps] 直接指向子 sitemap，例如 .../news-sitemap.xml）"
        )
    fill_article_images(site, http, items)     # sitemap 没图 → 逐篇补（受限流闸门保护）
    return Intel(
        platform=site.key, kind="news", method="sitemap",
        source=f"{site.domain} sitemap（HTTP，无浏览器）",
        confidence="high", items=items,
    )


# --- 通道 3：浏览器渲染列表页 ---

def fetch_site(site, http, profile=None, headless=False, wait=2500, timeout=45):
    if not node.node_available():
        raise Degraded(f"{site.key}：需要 node + playwright → {node.INSTALL_HINT}")

    allowed, why = http.gate.check(site.domain)
    if not allowed:
        raise RateLimited(f"{site.domain}: {why}")

    args = [
        f"--url={site.url}", f"--domain={site.domain}", f"--limit={site.limit}",
        f"--headless={1 if headless else 0}", f"--wait={wait}", f"--timeout={timeout * 1000}",
    ]
    if site.selector:
        args.append(f"--selector={site.selector}")
    if profile:
        args.append(f"--profile={profile}")

    try:
        rc, out, err = node.run_node(TOOLS, args, timeout=timeout + 60)
    except Exception as exc:  # noqa: BLE001 — 超时/启动失败都算取不到
        http.gate.record(site.domain)
        raise Degraded(f"{site.key}：浏览器渲染失败 → {type(exc).__name__}: {exc}")
    http.gate.record(site.domain)

    stderr = (err or "").strip()
    if node.missing_playwright(stderr):
        raise Degraded(f"{site.key}：缺 playwright 依赖 → {node.INSTALL_HINT}")
    if rc != 0:
        raise Degraded(f"{site.key}：渲染失败（exit {rc}）→ {stderr[-200:] or '无错误输出'}")

    try:
        payload = json.loads((out or "").strip().splitlines()[-1])
    except Exception:
        raise Degraded(f"{site.key}：渲染结果解析失败（页面结构可能已变）")

    items = [
        Item(
            rank=it.get("rank", i + 1),
            title=it.get("title", ""),
            url=it.get("url", ""),
            metrics={"time": it.get("time", ""), "site": site.domain,
                     "ts": it.get("ts", ""), "summary": it.get("summary", ""),
                     "image": it.get("image", ""), "category": it.get("category", "")},
        )
        for i, it in enumerate(payload.get("items", []))
    ]
    if not items:
        raise Degraded(f"{site.key}：页面打开成功但未抽到条目（配 [news.selectors] 或改用 [news.feeds]）")

    return Intel(
        platform=site.key,
        kind="news",
        method="primary" if site.selector else "heur",
        source=f"{site.domain} 列表页（有头浏览器渲染，持久 profile 复用会话）",
        confidence="medium",
        items=items,
        caveat="" if site.selector else "条目由通用启发式抽取（版面标题 + 同域链接）；结果偏少时配 [news.selectors] 或 [news.feeds]",
    )


def fetch(site, http, profile=None, headless=False, wait=2500, timeout=45):
    """按站点配置选通道：feed / sitemap（纯 HTTP，稳）优先，都没有才渲染列表页。"""
    channel = channel_of(site)
    if channel == "feed":
        return fetch_feed(site, http)
    if channel == "sitemap":
        return fetch_sitemap(site, http)
    return fetch_site(site, http, profile=profile, headless=headless, wait=wait, timeout=timeout)


# --- 并发保护 ---

@contextlib.contextmanager
def profile_lock(profile):
    """浏览器 profile 互斥（非阻塞）。yield True=拿到锁，False=别人正在用。

    定时任务与手动跑撞上同一个 profile 时，Chromium 的 ProcessSingleton 会让**两边都失败**；
    宁可这一轮跳过（幂等，下次补上），也不要两边一起挂。
    """
    path = pathlib.Path(profile)
    path.mkdir(parents=True, exist_ok=True)
    handle = (path / ".lock").open("w")
    acquired = False
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            handle.write(f"{os.getpid()} {dt.datetime.now().astimezone().isoformat(timespec='seconds')}\n")
            handle.flush()
        except OSError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001
                pass
        handle.close()
