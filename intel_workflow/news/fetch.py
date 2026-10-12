"""资讯站取数：三条通道，按站点配置自动选。

  1. **feed（首选）** —— 站点给了 RSS/Atom 地址就走 core.http 一次普通 GET：
     无浏览器、无 consent 墙、无反爬判定，最稳也最轻（闸门由 core.http 内部 check/record）。
  2. **sitemap** —— 没有 feed 但给了 XML sitemap 地址：同样纯 HTTP。指向的是 sitemapindex
     时自动跟一层到子 sitemap（优先名字含 news 的，如 /news-sitemap.xml）；跟随时按闸门的
     最小间隔等待，不绕过限速。**有了 feed 或 sitemap，就完全不需要 node + playwright。**
  3. **浏览器** —— 两者都没有才渲染列表页：有头（默认）或 `--headless`，持久 profile
     复用 cookie / consent 选择 / 登录态。浏览器子进程本身绕过 core.http，所以调用前后
     显式 gate.check / gate.record（每个域名每天一次导航）。

另外提供 profile_lock()：定时任务与手动跑同时用同一个 profile 会让两边都起不来
（Chromium 的 ProcessSingleton），所以整轮抓取先拿这把文件锁。
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import pathlib
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


# --- 通道 1：feed（无浏览器） ---

def fetch_feed(site, http, limit=None):
    """RSS/Atom → Intel。取不到就抛 Degraded，绝不返回空榜糊弄。"""
    try:
        _status, text = http.get(site.feed, domain=site.domain)
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001 — 网络/HTTP 错误都算「这个站这轮拿不到」
        raise Degraded(f"{site.key}：feed 取不到 → {type(exc).__name__}: {exc}")

    items = [
        Item(rank=it["rank"], title=it["title"], url=it["url"],
             metrics={"time": it.get("time", ""), "site": site.domain})
        for it in feed_parser.parse(text, limit=limit or site.limit)
    ]
    if not items:
        raise Degraded(f"{site.key}：feed 有响应但解析不出条目（地址还是 RSS 吗？）")
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


def fetch_sitemap(site, http, limit=None):
    """XML sitemap → Intel；是 sitemapindex 就自动跟一层到含 "news" 的子 sitemap。"""
    url = site.sitemap
    try:
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

    items = [
        Item(rank=it["rank"], title=it["title"], url=it["url"],
             metrics={"time": it.get("time", ""), "site": site.domain})
        for it in sitemap_parser.parse(text, limit=limit or site.limit)
    ]
    if not items:
        raise Degraded(
            f"{site.key}：sitemap 有响应但解析不出条目"
            "（把 [news.sitemaps] 直接指向子 sitemap，例如 .../news-sitemap.xml）"
        )
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
            metrics={"time": it.get("time", ""), "site": site.domain},
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
