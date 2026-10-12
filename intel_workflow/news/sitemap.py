"""XML sitemap 解析 —— 第三条取数通道（同样是纯 HTTP，不起浏览器）。

站点没给 RSS/Atom 时，sitemap 往往还在：
  `/sitemap.xml`（sitemapindex，套娃）→ `/news-sitemap.xml`（Google News 扩展：
  `<loc>` + `<news:publication_date>` + `<news:title>`）。

实测 igaming.news（2026-10-12）：`/feed/`、`/rss.xml` 都是 404，但 `/news-sitemap.xml`
一次 GET 就给全部文章（标题 + 发布时间 + URL），与 feed 等价 —— 于是**不需要 node + playwright**。

只依赖标准库；解析失败时用正则兜底（同 feed.py 的思路）。
"""
import re
import xml.etree.ElementTree as ET

from .feed import _clean, _fmt_time

SITEMAP_BLOCK = re.compile(r"<url\b.*?</url>", re.S | re.I)
LOC_RE = re.compile(r"<loc[^>]*>(.*?)</loc>", re.S | re.I)


def _local(tag):
    """{ns}url → url（命名空间前缀不固定，只认本地名）。"""
    return str(tag).rsplit("}", 1)[-1].lower()


def is_index(text):
    """sitemapindex：里面装的是**子 sitemap 的地址**，不是文章。"""
    return "<sitemapindex" in (text or "")[:4000]


def child_sitemaps(text, limit=20):
    """从 sitemapindex 抽子 sitemap 地址，**名字含 news 的排前面**（文章通常在那里）。"""
    urls, seen = [], set()
    for raw in LOC_RE.findall(text or ""):
        url = _clean(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    news_first = [u for u in urls if "news" in u.lower()]
    return (news_first + [u for u in urls if u not in news_first])[:limit]


def title_from_url(url):
    """普通 sitemap 没有 <title> 时，用 URL 末段拼一个可读标题（slug → words）。"""
    tail = re.sub(r"[?#].*$", "", url or "").rstrip("/").rsplit("/", 1)[-1]
    words = [w for w in re.split(r"[-_]+", tail) if w]
    if not words:
        return ""
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _from_xml(text, limit):
    try:
        root = ET.fromstring((text or "").strip())
    except Exception:
        return []
    out, seen = [], set()
    for node in root.iter():
        if _local(node.tag) != "url":
            continue
        loc, title, pub, mod = "", "", "", ""
        for child in node.iter():
            name = _local(child.tag)
            if name == "loc" and not loc:
                loc = _clean(child.text)
            elif name == "title" and not title:
                title = _clean(child.text)
            elif name == "publication_date" and not pub:
                pub = _clean(child.text)
            elif name == "lastmod" and not mod:
                mod = _clean(child.text)
        if not loc or loc in seen:
            continue
        seen.add(loc)
        out.append({
            "rank": len(out) + 1,
            "title": title or title_from_url(loc),
            "url": loc,
            "time": _fmt_time(pub or mod),
        })
        if len(out) >= limit:
            break
    return out


def _from_regex(text, limit):
    out, seen = [], set()
    for m in SITEMAP_BLOCK.finditer(text or ""):
        lm = LOC_RE.search(m.group(0))
        loc = _clean(lm.group(1)) if lm else ""
        if not loc or loc in seen:
            continue
        seen.add(loc)
        out.append({"rank": len(out) + 1, "title": title_from_url(loc), "url": loc, "time": ""})
        if len(out) >= limit:
            break
    return out


def parse(text, limit=15):
    """sitemap（urlset）→ [{rank,title,url,time}]；严格解析不行就走正则兜底。

    保持**文档顺序**（sitemap 一般最新在前；Google News sitemap 更是只放最近两天的文章）。
    """
    return _from_xml(text, limit) or _from_regex(text, limit)
