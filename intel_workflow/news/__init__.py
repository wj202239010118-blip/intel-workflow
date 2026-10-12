"""news — iGaming 行业资讯站的每日抓取 → 整合日报 → 推送。

有头 Chromium + 持久 profile（登录态次次复用）；抓取仍受 core.gate 的闸门约束。
"""
from .sites import Site, resolve

__all__ = ["Site", "resolve"]
