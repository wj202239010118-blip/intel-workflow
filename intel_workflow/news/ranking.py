# -*- coding: utf-8 -*-
"""各家官网自己的「热门/排行榜」→ 当热度信号（用户 2026-10-14：按这些官方网站给新闻做排行）。

实测（2026-10-14）：
  · **igaming.news** `/top-reads`：有一块 `Ranking / Most read stories`，是 `<ol>`，
    每条 `<li>` 里带名次数字 + `/news/...` 链接 → 能拿到名次。
  · **yogonet** 首页：一块 `TOP STORIES`，条目是 `Nº N` + 文章链接 → 能拿到名次。
  · **igamingbusiness** 首页只有 `Featured`（编辑精选，不是阅读量）；**sbcnews** 首页
    连区块标题都只有 By Region / By Vertical。这两家**不参与排行**
    —— 宁缺毋滥，不拿"最新"冒充"最热"。

用法：`fetch_ranks(http)` → {文章路径: {"rank": N, "site": key}}；再用 `rank_of(url, ranks)`
把名次匹配回具体条目（容忍绝对/相对 URL 与结尾斜杠差异）。
"""
import re

IGAMING_TOP_READS = "https://igaming.news/top-reads"
YOGONET_HOME = "https://www.yogonet.com/international/"
RANK_SITES = ("igaming", "yogonet")


def _get(http, url, domain):
    """榜单是**增强项**：抓不到就返回空串，绝不抛、绝不拖垮抓取主线。"""
    try:
        _status, text = http.get(url, domain=domain)
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


def parse_igaming(html):
    """igaming.news 的 Most read stories → {path: rank}"""
    i = (html or "").lower().find("most read stories")
    if i < 0:
        return {}
    out = {}
    # 注意 `<li[^>]*>`：头几条 li 带 class，写成 `<li>` 会漏掉它们（2026-10-14 踩过，名次从 4 开始）
    for m in re.finditer(r"<li[^>]*>(.*?)</li>", html[i:i + 30000], re.S):
        block = m.group(1)
        rank = re.search(r">\s*(\d{1,2})\s*</span>", block)
        link = re.search(r'href="(/news/[^"]+)"', block)
        if rank and link:
            out[link.group(1)] = int(rank.group(1))
    return out


def parse_yogonet(html):
    """yogonet 的 TOP STORIES → {path: rank}（`Nº N` 之后最近的第一个 /news/ 链接就是那一条）"""
    out = {}
    for m in re.finditer(r"Nº\s*(\d+)(.{0,1500}?)"
                         r"(https://www\.yogonet\.com/international/news/[^\"\s]+)", html or "", re.S):
        path = m.group(3).replace("https://www.yogonet.com", "")
        out.setdefault(path, int(m.group(1)))
    return out


def fetch_ranks(http):
    """抓各家的榜单 → {路径: {"rank": N, "site": key}}。任何一家抓不到都只是少一份信号。"""
    out = {}
    for key, parser, url, domain in (
        ("igaming", parse_igaming, IGAMING_TOP_READS, "igaming.news"),
        ("yogonet", parse_yogonet, YOGONET_HOME, "www.yogonet.com"),
    ):
        for path, rank in (parser(_get(http, url, domain)) or {}).items():
            out[path] = {"rank": rank, "site": key}
    return out


def rank_of(url, ranks):
    """条目 URL → 名次整数（0 = 不在任何榜单上）。"""
    if not url or not ranks:
        return 0
    path = re.sub(r"^https?://[^/]+", "", url).rstrip("/")
    hit = ranks.get(path) or ranks.get(path + "/")
    if hit:
        return int(hit.get("rank") or 0)
    tail = path.split("/")[-1]                      # 兜底：按 slug 尾巴匹配
    for key, value in ranks.items():
        if key.rstrip("/").split("/")[-1] == tail:
            return int((value or {}).get("rank") or 0)
    return 0
