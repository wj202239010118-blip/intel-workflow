"""RSS / Atom 解析 —— 无浏览器、无风控的取数通道。

为什么优先用它：feed 是站点**主动提供**的机器接口 —— 一次普通 GET、几十 KB、
没有 JS、没有 consent 墙、没有反爬判定。比渲染列表页稳定得多，也轻得多
（实测 sbcnews.co.uk：首页渲染无头下只吐 5392 字节空壳，而 /feed/ 一次 GET 就给 10 条）。

只依赖标准库；解析失败时用正则兜底（有些 feed 不是严格 XML）。
"""
import datetime as dt
import email.utils
import html
import re
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
ITEM_BLOCK = re.compile(r"<(item|entry)\b.*?</\1>", re.S | re.I)


def _clean(text):
    """剥 CDATA、剥标签、解实体、归一空白 —— 标题里常有 &amp; 与内嵌 <img>。"""
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _fmt_time(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(raw)  # RFC822：RSS pubDate
    except Exception:
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom updated/published
        except Exception:
            return raw[:19]
    try:
        parsed = parsed.astimezone()
    except Exception:
        pass
    return parsed.strftime("%d %b %Y")


def _from_xml(text, limit):
    try:
        root = ET.fromstring((text or "").strip())
    except Exception:
        return []
    out, seen = [], set()
    for entry in root.iter():
        if entry.tag not in ("item", ATOM + "entry"):
            continue
        title, link, stamp = "", "", ""
        for child in entry:
            tag = child.tag
            if tag in ("title", ATOM + "title"):
                title = _clean(child.text)
            elif tag == ATOM + "link":
                href = child.get("href") or ""
                rel = child.get("rel") or "alternate"
                if href and (rel == "alternate" or not link):
                    link = href
            elif tag == "link":
                link = link or _clean(child.text)
            elif tag in ("pubDate", "published", "date", ATOM + "published", ATOM + "updated"):
                stamp = stamp or _clean(child.text)
        if not (title and link) or link in seen:
            continue
        seen.add(link)
        out.append({"rank": len(out) + 1, "title": title, "url": link, "time": _fmt_time(stamp)})
        if len(out) >= limit:
            break
    return out


def _first(block, tag):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S | re.I)
    return _clean(m.group(1)) if m else ""


def _from_regex(text, limit):
    out, seen = [], set()
    for m in ITEM_BLOCK.finditer(text or ""):
        block = m.group(0)
        title = _first(block, "title")
        link = _first(block, "link")
        if not link:
            lm = re.search(r'<link[^>]*href="([^"]+)"', block, re.I)
            link = lm.group(1) if lm else ""
        stamp = _first(block, "pubDate") or _first(block, "published") or _first(block, "updated")
        if not (title and link) or link in seen:
            continue
        seen.add(link)
        out.append({"rank": len(out) + 1, "title": title, "url": link, "time": _fmt_time(stamp)})
        if len(out) >= limit:
            break
    return out


def parse(text, limit=15):
    """RSS 2.0 / Atom → [{rank,title,url,time}]；严格解析不行就走正则兜底。"""
    return _from_xml(text, limit) or _from_regex(text, limit)
