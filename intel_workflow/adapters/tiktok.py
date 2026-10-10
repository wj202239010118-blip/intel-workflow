"""TikTok：官方未提供公开趋势接口 → 用 playwright 渲染其**公开展示**的趋势页读取数据。

依赖：node + playwright（可选组件）。缺则明确报安装方式，不静默失败。
抓取仍受本仓库闸门约束（子进程本身不受闸门管，故在调用前后显式 check/record）。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

from ..core.gate import RateLimited
from ..core.model import Intel, Item
from .base import Adapter, Degraded

TOOLS = pathlib.Path(__file__).resolve().parent.parent.parent / "tools" / "tiktok_trends.js"
DOMAIN = "ads.tiktok.com"
INSTALL_HINT = "npm i playwright && npx playwright install chromium（或把已装 playwright 的 node_modules 路径给 INTEL_NODE_PATH）"
REGION_RE = re.compile(r"[A-Za-z0-9_-]{2,8}")


class TikTok(Adapter):
    platform = "tiktok"

    def _node_path(self):
        candidates = [
            os.environ.get("INTEL_NODE_PATH"),
            str(TOOLS.parent.parent / "node_modules"),
        ]
        npm = shutil.which("npm")
        if npm:
            try:
                root = subprocess.run(
                    [npm, "root", "-g"], capture_output=True, text=True, timeout=20
                ).stdout.strip()
                if root:
                    candidates.append(root)
            except Exception:
                pass
        return os.pathsep.join([c for c in candidates if c])

    def hot(self, region="US", period="24h"):
        region = (region or "US").upper()
        if not REGION_RE.fullmatch(region):
            raise Degraded(f"TikTok：region 只允许 2–8 位字母/数字/_/-（收到 {region!r}）")
        if not shutil.which("node"):
            raise Degraded(f"TikTok 需要 node + playwright → {INSTALL_HINT}")

        allowed, why = self.http.gate.check(DOMAIN)
        if not allowed:
            raise RateLimited(f"{DOMAIN}: {why}")

        env = dict(os.environ, NODE_PATH=self._node_path())
        try:
            proc = subprocess.run(
                ["node", str(TOOLS), f"--region={region}"],
                capture_output=True, text=True, timeout=180, env=env,
            )
        except subprocess.TimeoutExpired:
            raise Degraded("TikTok：页面渲染超时（页面可能变更或网络受阻）")
        self.http.gate.record(DOMAIN)

        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            if "Cannot find module" in err or "MODULE_NOT_FOUND" in err:
                raise Degraded(f"TikTok：缺 playwright 依赖 → {INSTALL_HINT}")
            raise Degraded(f"TikTok：渲染失败 → {err[-200:]}")
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            raise Degraded("TikTok：渲染结果解析失败（页面结构可能已变）")

        items = [
            Item(rank=it.get("rank", i + 1), title=it["title"], url=it.get("url", ""), metrics=it.get("metrics", {}))
            for i, it in enumerate(payload.get("items", []))
        ]
        if not items:
            raise Degraded("TikTok：页面渲染成功但未解析到榜单（选择器可能已变）")
        return Intel(
            platform=self.platform, kind="hot", region=region, method="fallback-1",
            source="TikTok Creative Center 公开展示的趋势页（浏览器渲染）",
            confidence="medium", items=items,
            caveat="读取页面公开展示的数据；地区以页面为准（region 参数生效性待验证）",
        )
