#!/usr/bin/env python3
"""tools/kv_get.py — 从 Cloudflare Workers KV 读一个 key。

用途：发送类步骤的**幂等闸门**（例：`news:brief:<中国日期>` 存在就跳过，防重复骚扰）。
读不到（404）或凭据缺失 → 输出空、exit 0（由调用方决定"没标记就当没发过"）。
"""
import os
import sys
import urllib.request

API = "https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s/values/%s"


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    account = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    namespace = (os.environ.get("CF_KV_NAMESPACE") or "").strip()
    if not (key and token and account and namespace):
        return 0
    try:
        req = urllib.request.Request(
            API % (account, namespace, key),
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            sys.stdout.write(resp.read().decode("utf-8", "replace"))
    except Exception:
        pass                      # 404 / 网络问题 → 当作"无标记"
    return 0


if __name__ == "__main__":
    sys.exit(main())
