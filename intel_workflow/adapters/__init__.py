"""适配器注册表。"""
from .instagram import Instagram
from .kick import Kick
from .tiktok import TikTok
from .twitch import Twitch
from .x import X
from .youtube import YouTube

ADAPTERS = {cls.platform: cls for cls in (YouTube, X, Twitch, Kick, TikTok, Instagram)}
