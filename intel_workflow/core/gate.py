"""按域名的抓取闸门：最小间隔 + 每日上限 + 命中风控后的持久化冷却。

纪律写进代码，不靠使用者自觉：
  · 同域名两次请求之间有最小间隔
  · 每域名有每日请求上限
  · 一旦命中风控（429 / 挑战页），立刻进入冷却，冷却期内零请求、不自动重试
"""
import datetime as dt
import json
import os
import pathlib
import threading
import time

DEFAULT_STATE = pathlib.Path.home() / ".cache" / "intel-workflow" / "gate.json"


class RateLimited(Exception):
    """闸门拒绝放行（冷却中 / 间隔不足 / 超每日上限）。"""


class Gate:
    def __init__(self, state_path=DEFAULT_STATE, min_interval=15, daily_cap=200, cooldown=21600):
        self.path = pathlib.Path(state_path)
        self.min_interval = min_interval
        self.daily_cap = daily_cap
        self.cooldown = cooldown
        # 2026-10-18: 站间并行抓取 —— Gate 状态是**按域名**的，但 _save 会整文件重写，
        # 多线程同时写会把 gate.json 写坏/丢更新。所以所有读写都过这把锁，写盘用原子替换。
        self._lock = threading.RLock()
        self._d = self._load()

    # --- 状态 ---
    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"domains": {}}

    def _save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._d, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)      # 原子替换：并发读者永远看不到半截 JSON

    def _entry(self, domain):
        entry = self._d["domains"].setdefault(
            domain, {"last": 0, "day": "", "count": 0, "cooldown_until": 0}
        )
        today = dt.date.today().isoformat()
        if entry["day"] != today:
            entry["day"] = today
            entry["count"] = 0
        return entry

    # --- 判定 ---
    def check(self, domain):
        """返回 (是否放行, 原因)。不发任何请求。"""
        with self._lock:
            return self._check(domain)

    def _check(self, domain):
        now = time.time()
        entry = self._entry(domain)
        if entry["cooldown_until"] > now:
            left = int(entry["cooldown_until"] - now)
            return False, f"冷却中，{left}s 后才解禁（命中风控后不自动重试）"
        if entry["count"] >= self.daily_cap:
            return False, f"已达每日上限 {self.daily_cap} 次"
        if entry["last"] and now - entry["last"] < self.min_interval:
            waited = int(now - entry["last"])
            return False, f"距上次请求仅 {waited}s，低于最小间隔 {self.min_interval}s"
        return True, "ok"

    def record(self, domain):
        with self._lock:
            entry = self._entry(domain)
            entry["last"] = time.time()
            entry["count"] += 1
            self._save()

    def trip(self, domain, seconds=None):
        """命中风控 → 冷却（持久化）。"""
        with self._lock:
            entry = self._entry(domain)
            entry["cooldown_until"] = time.time() + (seconds or self.cooldown)
            self._save()
