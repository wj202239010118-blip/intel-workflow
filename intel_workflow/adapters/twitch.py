"""Twitch：公开 GQL（免登录）取类目热度榜。client-id 是网页端公开固定值，非私密凭据。"""
from ..core.model import Intel, Item
from .base import Adapter

GQL = "https://gql.twitch.tv/gql"
PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TOP_GAMES = "query { games(first: 30, options: {sort: VIEWER_COUNT}) { edges { node { id name viewersCount } } } }"


class Twitch(Adapter):
    platform = "twitch"

    def hot(self, region=None, period="24h"):
        _, data = self.http.post_json(
            GQL,
            {"query": TOP_GAMES},
            domain="gql.twitch.tv",
            headers={"Client-ID": PUBLIC_CLIENT_ID, "Origin": "https://www.twitch.tv"},
        )
        edges = ((data.get("data") or {}).get("games") or {}).get("edges") or []
        items = [
            Item(
                rank=i + 1,
                title=e["node"]["name"],
                url=f"https://www.twitch.tv/directory/game/{e['node']['id']}",
                metrics={"viewers": e["node"].get("viewersCount", 0)},
            )
            for i, e in enumerate(edges)
        ]
        return Intel(
            platform=self.platform, kind="hot", method="primary",
            source="Twitch 公开 GQL · games(sort=VIEWER_COUNT)（免登录类目热度榜）",
            confidence="high", items=items,
        )
