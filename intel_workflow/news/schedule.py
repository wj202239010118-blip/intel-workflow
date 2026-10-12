"""launchd 定时：开机/登录跑一次 + 每天固定时刻跑一次；幂等（当天已成功跑过就跳过）。

为什么用 launchd：同事的要求是「设备开机时才定时跑」——
  · RunAtLoad            → 登录 / 开机后立刻触发一次（关机期间错过的时刻由此补上）
  · StartCalendarInterval → 每天固定时刻再来一次
两者配合，等于「开机跑 + 每天一次」；重复触发不会重复抓，因为 run() 按日期幂等。

写进 ~/Library/LaunchAgents/com.intel-workflow.news.plist；日志落 ~/Library/Logs/。
"""
import datetime as dt
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys

LABEL = "com.intel-workflow.news"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CACHE = pathlib.Path.home() / ".cache" / "intel-workflow"
STATE = CACHE / "news_state.json"
PLIST = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = pathlib.Path.home() / "Library" / "Logs" / "intel-workflow-news.log"
DEFAULT_HOUR, DEFAULT_MINUTE = 9, 30

# launchd 的 PATH 极简（连 /opt/homebrew/bin 都没有）→ 必须显式给，否则 node / 浏览器起不来
PLIST_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def today():
    return dt.date.today().isoformat()


def read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(**fields):
    CACHE.mkdir(parents=True, exist_ok=True)
    state = read_state()
    state.update(fields)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def already_ran(date=None):
    """当天是否已经成功跑过（幂等的依据）。"""
    return read_state().get("last_success_date") == (date or today())


def mark_run(success=True, note=""):
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if success:
        return write_state(last_success_date=today(), last_run_at=stamp, last_note=note, last_status="ok")
    return write_state(last_run_at=stamp, last_note=note, last_status="failed")


def render_plist(python, repo, hour=DEFAULT_HOUR, minute=DEFAULT_MINUTE, send=False, node_path=""):
    args = [str(python), str(pathlib.Path(repo) / "intel"), "news", "run"]
    if send:
        args.append("--send")
    env = {"PATH": PLIST_PATH, "HOME": str(pathlib.Path.home())}
    if node_path:
        env["INTEL_NODE_PATH"] = str(node_path)
    data = {
        "Label": LABEL,
        "ProgramArguments": args,
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,                                  # 开机 / 登录即跑一次
        "StartCalendarInterval": {"Hour": int(hour), "Minute": int(minute)},
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
        "EnvironmentVariables": env,
        "ProcessType": "Interactive",                        # 有头浏览器需要图形会话
    }
    return plistlib.dumps(data)


def _launchctl(sub, args):
    if not shutil.which("launchctl"):
        return 1, "", "launchctl 不存在（非 macOS？）"
    proc = subprocess.run(["launchctl", sub] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


def install(python=None, repo=None, hour=DEFAULT_HOUR, minute=DEFAULT_MINUTE, send=False, node_path=""):
    """写 plist 并加载（可重复执行，幂等）。返回 (plist 路径, 提示行列表)。"""
    python = python or sys.executable
    repo = pathlib.Path(repo or ROOT)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(render_plist(python, repo, hour, minute, send, node_path))

    notes = []
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", [f"{domain}/{LABEL}"])            # 已加载则先卸（失败无妨）
    rc, _, err = _launchctl("bootstrap", [domain, str(PLIST)])
    if rc != 0:
        rc2, _, err2 = _launchctl("load", ["-w", str(PLIST)])  # 老系统回退
        if rc2 != 0:
            notes.append(f"⚠️  加载失败：{(err or err2).strip()[:200]}（plist 已写好，可手动 launchctl load -w {PLIST}）")
    notes.append(f"plist → {PLIST}")
    notes.append(f"触发：开机/登录一次 + 每天 {int(hour):02d}:{int(minute):02d}")
    notes.append(f"推送：{'开（--send）' if send else '关（只抓取落盘，不发）'}")
    notes.append(f"日志：{LOG}")
    return PLIST, notes


def uninstall():
    notes = []
    rc, _, _ = _launchctl("bootout", [f"gui/{os.getuid()}/{LABEL}"])
    notes.append("已从 launchd 卸载" if rc == 0 else "launchd 里没有加载它（或已停止）")
    if PLIST.exists():
        PLIST.unlink()
        notes.append(f"已删除 {PLIST}")
    return notes


def status():
    state = read_state()
    lines = [
        f"plist：{'存在 ' + str(PLIST) if PLIST.exists() else '不存在（未安装）'}",
        f"加载：{'是' if _loaded() else '否'}",
        f"上次成功：{state.get('last_success_date') or '（无记录）'}　上次运行：{state.get('last_run_at') or '—'}"
        + (f"　状态：{state.get('last_status')}" if state.get("last_status") else ""),
        f"今天已跑过：{'是（会跳过）' if already_ran() else '否'}",
        f"状态文件：{STATE}",
        f"日志：{LOG}",
    ]
    return lines


def _loaded():
    rc, out, _ = _launchctl("list", [LABEL])
    return rc == 0 or LABEL in (out or "")
