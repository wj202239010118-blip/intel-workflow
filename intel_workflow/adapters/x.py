"""X / Twitter：官方 trends 需付费档 → 走第三方公开趋势页（降级源，低置信）。"""
import html
import re

from ..core.model import Intel, Item
from .base import Adapter

# 该站属性引号可能被压缩工具省略（class=trend-link），故引号设为可选
TREND_LINK = re.compile(r'<a[^>]*class=["\']?trend-link["\']?[^>]*>([^<]+)</a>')
FALLBACK = re.compile(r'href="?https://twitter\.com/search\?q=[^"]*"?[^>]*>([^<]{2,60})</a>')
REGION_HINT = "地区用 slug（如 united-states / indonesia / mexico / nigeria）"


class X(Adapter):
    platform = "x"

    def hot(self, region="united-states", period="24h"):
        slug = (region or "united-states").strip().lower().replace(" ", "-")
        url = f"https://trends24.in/{slug}/"
        _, text = self.http.get(url, domain="trends24.in")
        seen, names = set(), []
        for raw in (TREND_LINK.findall(text) or FALLBACK.findall(text)):
            name = html.unescape(raw).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        items = [Item(rank=i + 1, title=n) for i, n in enumerate(names[:50])]
        return Intel(
            platform=self.platform, kind="hot", region=slug, method="fallback-1",
            source="第三方公开趋势页（非官方接口）", confidence="medium", items=items,
            caveat=f"非 X 官方榜单，仅供方向参考；{REGION_HINT}",
        )
