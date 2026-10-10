"""Instagram：无官方趋势接口 → 用「对标账号近期帖互动」做代理指标（需使用者自带 cookie）。

实测：无 cookie 请求 web_profile_info 返 401 require_login。
因此本适配器在缺凭据时直接报 NeedCredential，不做无意义的降级。
"""
import urllib.parse

from ..core.model import Intel, Item
from .base import Adapter, Degraded, NeedCredential

PROFILE_API = "https://www.instagram.com/api/v1/users/web_profile_info/?username="
IG_APP_ID = "936619743392459"  # IG 网页端公开 app id（非私密凭据）
HINT = (
    "Instagram 需要使用者自带的 sessionid cookie：浏览器登录 IG → 开发者工具 → 取 sessionid → "
    "填 config.toml 的 [instagram].session_id"
)


class Instagram(Adapter):
    platform = "instagram"

    def _cookie(self):
        sid = self.cfg.instagram_session_id
        if not sid:
            raise NeedCredential(HINT)
        return f"sessionid={sid}"

    def verify(self, handle):
        if not handle:
            raise Degraded("IG verify 需 --handle")
        user = self._profile(handle)
        if not user:
            raise Degraded(f"Instagram：取不到 @{handle.lstrip('@')}（账号不存在或需重新登录）")
        return Intel(
            platform=self.platform, kind="profile", method="primary",
            source="Instagram web_profile_info（需登录态 cookie）", confidence="medium",
            items=[Item(rank=1, title=user.get("full_name") or handle,
                        url=f"https://www.instagram.com/{user.get('username', '')}/",
                        metrics={"followers": (user.get("edge_followed_by") or {}).get("count"),
                                 "posts": (user.get("edge_owner_to_timeline_media") or {}).get("count"),
                                 "bio": (user.get("biography") or "")[:120]})],
            caveat="依赖登录态，数据为公开资料快照",
        )

    def _profile(self, handle):
        url = PROFILE_API + urllib.parse.quote(handle.lstrip("@"))
        _, data = self.http.get_json(
            url, domain="www.instagram.com",
            headers={"x-ig-app-id": IG_APP_ID, "Cookie": self._cookie(),
                     "Referer": f"https://www.instagram.com/{handle.lstrip('@')}/"},
        )
        return (data.get("data") or {}).get("user") or {}

    def hot(self, region=None, period="24h"):
        seeds = self.cfg.instagram_seed_accounts
        if not seeds:
            raise Degraded(
                "IG 无官方趋势接口；请在 config.toml 的 [instagram].seed_accounts 配几个对标账号，"
                "用它们的近期帖互动做代理指标（非官方榜单）"
            )
        rows = []
        for handle in seeds[:10]:
            try:
                user = self._profile(handle)
            except Exception:
                continue
            edges = ((user.get("edge_owner_to_timeline_media") or {}).get("edges")) or []
            for edge in edges[:6]:
                node = edge.get("node") or {}
                likes = (node.get("edge_liked_by") or node.get("edge_media_preview_like") or {}).get("count", 0)
                caption = ((node.get("edge_media_to_caption") or {}).get("edges") or [{}])[0].get("node", {}).get("text", "")
                rows.append(Item(
                    rank=0, title=(caption[:80] or f"@{handle} 的帖子"),
                    url=f"https://www.instagram.com/p/{node.get('shortcode', '')}/",
                    metrics={"likes": likes, "comments": (node.get("edge_media_to_comment") or {}).get("count", 0),
                             "account": handle.lstrip("@")},
                ))
        rows.sort(key=lambda it: it.metrics.get("likes", 0), reverse=True)
        for i, item in enumerate(rows[:25]):
            item.rank = i + 1
        if not rows:
            raise Degraded("Instagram：没有取到任何帖子（cookie 可能失效，或账号近期无内容）")
        return Intel(
            platform=self.platform, kind="hot", method="fallback-2",
            source="对标账号近期帖互动排序（代理指标，非官方趋势）", confidence="low",
            items=rows[:25],
            caveat="这不是 IG 官方热榜：仅按指定对标账号的公开帖互动量排序，用于感知方向",
        )
