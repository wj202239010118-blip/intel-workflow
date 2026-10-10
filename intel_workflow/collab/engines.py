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


def call_openai_compatible(prompt, base_url, api_key, model):
    """缺 codex 时的等价替代：任意 OpenAI 兼容 /chat/completions。"""
    if not (base_url and api_key and model):
        raise RuntimeError("OpenAI 兼容引擎未配置（[collab] openai_base_url / openai_api_key / openai_model）")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI 兼容端 HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}")
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")


def available(cfg):
    """返回可用的引擎 {name: callable}。claude 优先，codex 缺失时用 OpenAI 兼容端顶上。"""
    found = detect()
    engines = {}
    if found["claude"]:
        engines["claude"] = call_claude
    if found["codex"]:
        engines["codex"] = call_codex
    elif cfg.openai_api_key and cfg.openai_base_url and cfg.openai_model:
        engines["openai-compatible"] = lambda p: call_openai_compatible(
            p, cfg.openai_base_url, cfg.openai_api_key, cfg.openai_model
        )
    return engines
