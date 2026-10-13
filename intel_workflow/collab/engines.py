"""引擎探测与调用：claude CLI / codex CLI / OpenAI 兼容 API。

设计原则：
  · 谁可用用谁，不可用就如实说（缺 codex → 提示填 OpenAI 兼容 token；缺 claude → 提示下载登录）
  · 只把「归一化情报对象」喂给模型，不喂原始 HTML
  · 引擎失败不影响其它引擎，错误记进报告
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

TIMEOUT = 240

CONTRACT = (
    "你是情报复核员。下面给你一组从社交平台取到的结构化情报事实（JSON）。"
    "请只基于这些事实（不要使用你自己的记忆或训练数据补充事实），输出严格 JSON：\n"
    '{"key_findings": ["最重要的结论，3-5 条"], "caveats": ["数据可信度/口径上的问题"], '
    '"questions": ["需要人工确认的点"]}\n'
    "只输出 JSON，不要任何解释、不要 Markdown 代码块。"
)


def detect():
    """返回两端 CLI 是否可用。"""
    return {"claude": bool(shutil.which("claude")), "codex": bool(shutil.which("codex"))}


def _run(cmd, prompt):
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT,
        env=dict(os.environ, NO_COLOR="1"),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 退出码 {proc.returncode}: {(proc.stderr or '').strip()[-200:]}")
    return (proc.stdout or "").strip()


def call_claude(prompt):
    """Claude Code 非交互模式。"""
    return _run(["claude", "-p"], prompt)


def call_codex(prompt):
    """Codex CLI 非交互模式（本机未验证，见 docs/DESIGN.md）。"""
    return _run(["codex", "exec"], prompt)


def call_openai_compatible(prompt, base_url, api_key, model, proxy=""):
    """任意 OpenAI 兼容端 —— 走**本机已验证的姿势**：`curl` → `/v1/responses`（+ 可选 socks5 代理）。

    2026-10-12（INC-20261012-02）：原先用 urllib 打 `/chat/completions`，既没设 UA 也没走代理 →
    第一条请求就被 Cloudflare 按签名拦（`403 / error code 1010`）。本机既有脚本
    （`~/scripts/gpt-think.py`）的注释写明了原因：**urllib 在本机直连该端点会被拦，curl 走代理才通**。
    所以这里对齐那条已验证的路，而不是继续猜。

    代理放 `OPENAI_PROXY`（例：`socks5h://127.0.0.1:7897`）；**云端（GitHub Actions）没有代理就别设**。
    """
    if not (base_url and api_key and model):
        raise RuntimeError("OpenAI 兼容引擎未配置（[collab] openai_base_url / openai_api_key / openai_model）")
    root = base_url.rstrip("/")
    if root.endswith("/v1"):                      # 容错：填不填 `/v1` 都指向同一处
        root = root[:-3]
    body = json.dumps({"model": model, "input": prompt})
    cmd = ["curl", "-s", "--max-time", str(TIMEOUT)]
    if proxy:
        cmd += ["-x", proxy]
    cmd += ["-A", "intel-workflow/1.0",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: Bearer {api_key}",
            "-d", body, root + "/v1/responses"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 15)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"curl 超时（{TIMEOUT}s）") from exc

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError(f"curl 无输出（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"响应不是 JSON：{raw[:200]}") from exc
    if data.get("error"):
        raise RuntimeError(f"API 错误：{json.dumps(data['error'], ensure_ascii=False)[:300]}")

    texts = []
    for item in data.get("output") or []:                       # Responses API 形状
        for chunk in item.get("content") or []:
            if chunk.get("type") == "output_text":
                texts.append(chunk.get("text") or "")
    if not texts:                                               # 兼容 chat/completions 形状
        try:
            texts = [data["choices"][0]["message"]["content"]]
        except Exception:  # noqa: BLE001
            texts = []
    return "\n".join(texts).strip()


def available(cfg):
    """返回可用的引擎 {name: callable}。claude 优先，codex 缺失时用 OpenAI 兼容端顶上。"""
    found = detect()
    engines = {}
    if found["claude"]:
        engines["claude"] = call_claude
    if found["codex"]:
        engines["codex"] = call_codex
    elif cfg.openai_api_key and cfg.openai_base_url and cfg.openai_model:
        proxy = os.environ.get("OPENAI_PROXY", "").strip()
        engines["openai-compatible"] = lambda p: call_openai_compatible(
            p, cfg.openai_base_url, cfg.openai_api_key, cfg.openai_model, proxy=proxy
        )
    return engines
