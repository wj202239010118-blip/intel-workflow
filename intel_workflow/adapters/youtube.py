"""YouTube：官方 Data API v3（需使用者自带免费 API key）。"""
import urllib.parse

from ..core.model import Intel, Item
from .base import Adapter, Degraded, NeedCredential

API = "https://youtube.googleapis.com/youtube/v3"
HINT = (
    "YouTube 需要 Data API key（免费，额度足够）：Google Cloud Console → 启用 "
    "YouTube Data API v3 → 创建 API key → 填 config.toml 的 [youtube].api_key"
)


class YouTube(Adapter):
    platform = "youtube"

    def _key(self):
        key = self.cfg.youtube_api_key
        if not key:
            raise NeedCredential(HINT)
        return key

    def hot(self, region="US", period="24h"):
        url = (
            f"{API}/videos?part=snippet,statistics&chart=mostPopular"
            f"&regionCode={urllib.parse.quote(region or 'US')}&maxResults=25&key={self._key()}"
        )
        _, data = self.http.get_json(url, domain="youtube.googleapis.com")
        items = [
            Item(
                rank=i + 1,
                title=v["snippet"]["title"],
                url=f"https://www.youtube.com/watch?v={v['id']}",
                metrics={
                    "views": int(v["statistics"].get("viewCount", 0)),
                    "channel": v["snippet"].get("channelTitle", ""),
                },
            )
            for i, v in enumerate(data.get("items", []))
        ]
        return Intel(
            platform=self.platform, kind="hot", region=region or "US", method="primary",
            source="YouTube Data API v3 · chart=mostPopular（官方接口）",
            confidence="high", items=items,
        )

    def search(self, query, region=None):
        if not query:
            raise Degraded("YouTube 搜索需 --q 关键词")
        url = (
            f"{API}/search?part=snippet&type=video&maxResults=25"
            f"&q={urllib.parse.quote(query)}&key={self._key()}"
        )
        _, data = self.http.get_json(url, domain="youtube.googleapis.com")
        items = [
            Item(
                rank=i + 1,
                title=v["snippet"]["title"],
                url=f"https://www.youtube.com/watch?v={(v.get('id') or {}).get('videoId', '')}",
                metrics={"channel": v["snippet"].get("channelTitle", "")},
            )
            for i, v in enumerate(data.get("items", []))
        ]
        return Intel(
            platform=self.platform, kind="search", query=query, region=region, method="primary",
            source="YouTube Data API v3 · search（官方接口）", confidence="high", items=items,
        )
