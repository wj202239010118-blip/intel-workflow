"""X / Twitter：官方 trends 需付费档 → 走第三方公开趋势页（降级源，低置信）。

region 同时接受国家码（US / ID / MX…）与 slug（united-states / indonesia…）。
"""
import html
import re

from ..core.http import HttpError
from ..core.model import Intel, Item
from .base import Adapter, Degraded

TREND_LINK = re.compile(r'<a[^>]*class=["\']?trend-link["\']?[^>]*>([^<]+)</a>')
FALLBACK = re.compile(r'href="?https://twitter\.com/search\?q=[^"]*"?[^>]*>([^<]{2,60})</a>')

# 国家码 → 趋势页 slug（覆盖常见市场；未收录的按原样小写处理）
REGION_SLUGS = {
    "US": "united-states", "GB": "united-kingdom", "UK": "united-kingdom",
    "ID": "indonesia", "MX": "mexico", "NG": "nigeria", "IN": "india",
    "BR": "brazil", "PH": "philippines", "DE": "germany", "FR": "france",
    "ES": "spain", "IT": "italy", "TR": "turkey", "PK": "pakistan",
    "BD": "bangladesh", "VN": "vietnam", "TH": "thailand", "JP": "japan",
    "KR": "south-korea", "CA": "canada", "AU": "australia", "AR": "argentina",
    "CO": "colombia", "PE": "peru", "ZA": "south-africa", "EG": "egypt",
}
REGION_HINT = "地区可用国家码（US / ID / MX / NG…）或 slug（united-states）"


def slug_for(region):
    """国家码（US / ID / MX…）或 slug（united-states）→ 趋势页 slug。"""
    raw = (region or "").strip() or "US"
    return REGION_SLUGS.get(raw.upper(), raw.lower().replace(" ", "-"))


class X(Adapter):
    platform = "x"

    def hot(self, region="US", period="24h"):
        raw = (region or "").strip() or "US"
        slug = slug_for(raw)
        url = f"https://trends24.in/{slug}/"
        try:
            _, text = self.http.get(url, domain="trends24.in")
        except HttpError as exc:
            if exc.status == 404:
                raise Degraded(
                    f"X：地区 '{raw}' 没有对应的趋势页（{REGION_HINT}）"
                ) from exc
            raise

        seen, names = set(), []
        for value in (TREND_LINK.findall(text) or FALLBACK.findall(text)):
            name = html.unescape(value).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        items = [Item(rank=i + 1, title=name) for i, name in enumerate(names[:50])]
        return Intel(
            platform=self.platform, kind="hot", region=slug, method="fallback-1",
            source="第三方公开趋势页（非官方接口）", confidence="medium", items=items,
            caveat=f"非 X 官方榜单，仅供方向参考；{REGION_HINT}",
        )
