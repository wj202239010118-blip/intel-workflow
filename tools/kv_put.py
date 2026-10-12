#!/usr/bin/env python3
"""把一份文件写进 Cloudflare Workers KV（云端 workflow 用）。

凭据全部走环境变量 —— 不落盘、不进仓库、不打进日志：
    CF_API_TOKEN       权限 `Workers KV Storage:Edit` 的 token
    CF_ACCOUNT_ID      账号 id
    CF_KV_NAMESPACE    KV 命名空间 id

用法：
    python3 tools/kv_put.py out/2026-10-12-daily.html daily:index
    python3 tools/kv_put.py out/2026-10-12-daily.html daily:2026-10-12
    python3 tools/kv_put.py <file> <key> --dry-run     # 只打印，不发

凭据不齐时自动退化为 dry-run（本地开发不会被误触发）。
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.request

API = "https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s/values/%s"


def main():
    ap = argparse.ArgumentParser(description="文件 → Cloudflare Workers KV")
    ap.add_argument("file")
    ap.add_argument("key")
    ap.add_argument("--content-type", default="text/html; charset=utf-8")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    account = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    namespace = (os.environ.get("CF_KV_NAMESPACE") or "").strip()

    body = pathlib.Path(args.file).read_bytes()
    ready = bool(token and account and namespace)
    if args.dry_run or not ready:
        print(f"[dry-run] PUT {len(body)} bytes → KV[{args.key}]"
              f"（凭据齐全={ready}；缺就设置 CF_API_TOKEN / CF_ACCOUNT_ID / CF_KV_NAMESPACE）")
        return 0

    req = urllib.request.Request(
        API % (account, namespace, args.key),
        data=body, method="PUT",
        headers={"Authorization": "Bearer " + token, "Content-Type": args.content_type},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        ok = bool(json.loads(resp.read().decode() or "{}").get("success"))
    print(("✅ wrote " if ok else "❌ failed ") + f"{args.key} ({len(body)} bytes)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
