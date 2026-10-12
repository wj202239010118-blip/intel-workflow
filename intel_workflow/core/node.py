"""node / playwright 的定位与可用性判断（tiktok 与 news 共用，避免两处各写一遍）。

playwright 可能装在三个地方，按优先级找：
  1) 环境变量 INTEL_NODE_PATH 指定的 node_modules
  2) 本仓库根目录的 node_modules（npm i playwright）
  3) npm 全局 root
"""
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
INSTALL_HINT = "npm i playwright && npx playwright install chromium（或把已装 playwright 的 node_modules 路径给 INTEL_NODE_PATH）"


def node_available():
    return bool(shutil.which("node"))


def node_path_env():
    """拼出给子进程用的 NODE_PATH（找不到任何候选时返回空串）。"""
    candidates = [os.environ.get("INTEL_NODE_PATH"), str(ROOT / "node_modules")]
    npm = shutil.which("npm")
    if npm:
        try:
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=20).stdout.strip()
            if root:
                candidates.append(root)
        except Exception:  # noqa: BLE001 — npm 不在/超时都不该让命令失败
            pass
    return os.pathsep.join([c for c in candidates if c])


def run_node(script, args, timeout=180, env_extra=None):
    """跑一个 node 脚本，返回 (returncode, stdout, stderr)。缺少 node 时抛 FileNotFoundError。"""
    env = dict(os.environ, NODE_PATH=node_path_env(), **(env_extra or {}))
    proc = subprocess.run(
        ["node", str(script)] + list(args),
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def missing_playwright(stderr):
    text = stderr or ""
    return "Cannot find module" in text or "MODULE_NOT_FOUND" in text
