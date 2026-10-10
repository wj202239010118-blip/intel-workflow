"""Kick：官方 Public API 需 app token（免费申请）→ 缺凭据时明确提示，不静默失败。"""
from ..core.model import Intel, Item
from .base import Adapter, NeedCredential

API = "https://api.kick.com/public/v2/livestreams?limit=30&sort=desc"
HINT = (
    "Kick 需要官方 Public API 的 app token（免费）：https://dev.kick.com 建 app → "
    "把 client_id / client_secret 填进 config.toml 的 [kick]，或直接填 [kick].access_token"
)


class Kick(Adapter):
    platform = "kick"

    def hot(self, region=None, period="24h"):
        token = self.cfg.kick_access_token
        if not token:
            raise NeedCredential(HINT)
        _, data = self.http.get_json(
            API, domain="api.kick.com", headers={"Authorization": f"Bearer {token}"}
        )
        rows = (data.get("data") or []) if isinstance(data, dict) else []
        items = []
        for i, row in enumerate(rows):
            category = row.get("category") or {}
            slug = row.get("slug") or row.get("channel", {}).get("slug", "")
            items.append(
                Item(
                    rank=i + 1,
                    title=row.get("session_title") or slug or f"#{i + 1}",
                    url=f"https://kick.com/{slug}" if slug else "",
                    metrics={
                        "viewers": row.get("viewer_count", row.get("viewers", 0)),
                        "category": category.get("name", ""),
                    },
                )
            )
        return Intel(
            platform=self.platform, kind="hot", method="primary",
            source="Kick 官方 Public API · /public/v2/livestreams", confidence="high", items=items,
        )
