"""资讯站清单：默认一组 iGaming 行业站；config.toml 的 [news] 可覆盖或追加。

每站的取数通道按优先级选：
  1. **feed**（RSS/Atom）有 → 走 core/http 一次 GET（无浏览器、无 consent 墙、无反爬，最稳）
  2. 否则 → 有头/无头 Chromium 渲染列表页，按 [news.selectors] 或通用启发式抽条目

站点结构特殊时用 [news.selectors] 按域名指定「文章链接」的 CSS 选择器；
有 feed 就用 [news.feeds] 按域名指定（这才是首选）。

    [news.feeds]
    "www.example.com" = "https://www.example.com/feed/"

不联网、不读凭据，纯清单解析（可离线测试）。
"""
import re
from dataclasses import dataclass

# 内置站点：iGaming 行业新闻站（列表页 URL, 选择器, feed URL）
#
# sbcnews.co.uk 走 feed 的原因（2026-10-11 实测）：它的首页在无头下只渲染广告与菜单
# （consent=accept all、滚动 6 次后仍 articles=0、bodyLen 5392；换 chromium 新 headless 模式
# 逐字节相同 → 不是自动化被识别，是服务端就不给内容），而 /feed/ 一次 GET 就给 10 条。
DEFAULT_SITES = [
    ("https://igaming.news/", "", ""),
    ("https://igamingbusiness.com/news/", "", ""),
    ("https://sbcnews.co.uk/", "", "https://sbcnews.co.uk/feed/"),
    ("https://www.yogonet.com/international/", "", ""),
]

DEFAULT_LIMIT = 15


@dataclass
class Site:
    key: str            # 短名，用于文件名与日报分组：igaming / sbcnews / yogonet
    url: str            # 列表页（feed 站只是兜底入口）
    domain: str         # 闸门与选择器按它归组
    selector: str = ""  # 可选：文章链接的 CSS 选择器（空 → 通用启发式）
    feed: str = ""      # 可选：RSS/Atom 地址（有则走 HTTP 通道，不用浏览器）
    limit: int = DEFAULT_LIMIT


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) if m else "").lower()


def key_of(domain):
    """igaming.news → igaming；www.yogonet.com → yogonet；sbcnews.co.uk → sbcnews。"""
    host = re.sub(r"^www\.", "", domain or "")
    parts = host.split(".")
    main = parts[-2] if len(parts) >= 2 else host
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        main = parts[-3]  # co.uk / com.au 这类二级后缀
    return re.sub(r"[^a-z0-9]+", "-", main).strip("-") or "site"


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if str(v).strip()]


def resolve(cfg):
    """内置站点 + config 覆盖/追加 → Site 列表（按域名去重，保持顺序）。"""
    section = cfg.section("news")
    # [news.selectors] / [news.feeds] 两种解析器下都要取到（tomllib 嵌套 vs 内置解析器扁平）
    selectors = {str(k).lower(): str(v) for k, v in (section.get("selectors") or {}).items()}
    selectors.update({str(k).lower(): str(v) for k, v in cfg.section("news.selectors").items()})
    feeds = {str(k).lower(): str(v) for k, v in (section.get("feeds") or {}).items()}
    feeds.update({str(k).lower(): str(v) for k, v in cfg.section("news.feeds").items()})
    limit = int(section.get("per_site_limit") or DEFAULT_LIMIT)

    specs = []
    if section.get("sites"):
        specs += [(str(u), "", "") for u in _as_list(section.get("sites"))]     # 覆盖
    else:
        specs += list(DEFAULT_SITES)
    specs += [(str(u), "", "") for u in _as_list(section.get("extra_sites"))]   # 追加

    sites, seen = [], set()
    for url, selector, feed in specs:
        domain = domain_of(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        sites.append(Site(
            key=key_of(domain), url=url, domain=domain,
            selector=selector or selectors.get(domain, ""),
            feed=feed or feeds.get(domain, ""), limit=limit,
        ))
    return sites
