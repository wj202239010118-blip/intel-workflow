#!/usr/bin/env bash
# 一键安装（macOS 优先适配）：环境探测 → 依赖 → 配置(凭据向导) → 模型端 → 冒烟自检 → 装载到 agent
#   bash install.sh              正常安装（含装载 skill）
#   bash install.sh --uninstall  卸载装载到 agent 的 skill
# 兼容 macOS 自带的 bash 3.2；非交互环境自动跳过凭据向导（设 INTEL_WIZARD=1 可强制进入）
set -uo pipefail
cd "$(dirname "$0")"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

REPO_DIR="$PWD"
SKILL_DEST="$HOME/.claude/skills/intel-workflow"

# ── 选 Python：macOS 自带的 /usr/bin/python3 是 3.9，够用；有更新的版本优先用 ──
pick_python() {
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$cand" && "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)' 2>/dev/null; then
      echo "$cand"; return 0
    fi
  done
  return 1
}
PY="$(pick_python)" || PY=""

# 改 config.toml 里某个 [section] 下的 key（避免 sed 的 macOS/GNU 差异）
set_toml() {
  "$PY" - "$1" "$2" "$3" <<'PYEOF'
import pathlib, re, sys
section, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
path = pathlib.Path("config.toml")
lines = path.read_text(encoding="utf-8").splitlines()
out, in_sec, done = [], False, False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        in_sec = stripped == f"[{section}]"
    elif in_sec and not done and re.match(rf"^{re.escape(key)}\s*=", stripped):
        line = f'{key} = "{value}"'
        done = True
    out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PYEOF
}

if [ "${1:-}" = "--uninstall" ]; then
  say "卸载"
  rm -rf "$SKILL_DEST" && echo "  ✅ 已移除 $SKILL_DEST"
  echo "  （config.toml 与 ~/.cache/intel-workflow 的闸门状态未动，需清理请手动删）"
  echo "  （定时任务另卸：python3 intel schedule uninstall）"
  exit 0
fi

# 可选：装「每天自动查行业资讯」的 launchd 任务（开机/登录一次 + 每天一次）
if [ "${1:-}" = "--install-scheduler" ]; then
  say "装定时任务（launchd）"
  "$PY" intel schedule install "${@:2}"
  exit $?
fi

say "1/6 环境探测（macOS）"
MISSING=0
if [ -n "$PY" ]; then
  echo "  ✅ python: ${PY}（$("$PY" -V 2>&1)）"
else
  echo "  ❌ 缺 Python ≥3.9 —— macOS 自带的是 3.9（/usr/bin/python3）"
  echo "     若你的 python3 太旧：brew install python@3.12"
  MISSING=1
fi
if have git; then echo "  ✅ git  $(command -v git)"; else
  echo "  ❌ 缺 git —— 运行 xcode-select --install（或 brew install git）"; MISSING=1; fi
for t in node claude codex; do
  have "$t" && echo "  ✅ ${t}（可选）" || echo "  ⚠️  未检测到 ${t}（可选）"
done
if [ "$MISSING" = 1 ]; then echo "缺必需依赖，装好后重跑。"; exit 1; fi

say "2/6 依赖"
"$PY" -m pip install -q -r requirements.txt 2>/dev/null \
  && echo "  依赖已就绪" || echo "  ⚠️  pip 安装失败（核心仅用标准库，Python 3.9 也不影响继续）"
if ! have node; then
  echo "  ⚠️  未检测到 node → TikTok 热点不可用（装 node 后再 npm i playwright）"
elif node -e "require('playwright')" >/dev/null 2>&1; then
  echo "  ✅ node + playwright 可用（TikTok 热点）"
else
  echo "  ⚠️  node 已就位，但没有 playwright → TikTok 热点不可用"
  echo "      装它：npm i playwright && npx playwright install chromium"
fi

say "3/6 配置"
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml && chmod 600 config.toml
  echo "  已生成 config.toml（凭据可留空：留空只是对应平台不可用，其余照常）"
else
  cp config.toml config.toml.bak
  "$PY" - <<'PYEOF'
import pathlib, re

cfg, exp = pathlib.Path("config.toml"), pathlib.Path("config.example.toml")


def parse(text):
    data, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            cur = m.group(1)
            data.setdefault(cur, {})
        elif cur and s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            data[cur][k.strip()] = v.strip()
    return data


def set_in_text(text, sec, key, value):
    out, in_sec, done = [], False, False
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"\[[^\]]+\]", s):
            in_sec = s == f"[{sec}]"
        elif in_sec and not done and re.match(rf"^{re.escape(key)}\s*=", s):
            line = f"{key} = {value}"
            done = True
        out.append(line)
    return "\n".join(out) + "\n"


old = parse(cfg.read_text(encoding="utf-8"))
text = exp.read_text(encoding="utf-8")
carried = 0
for sec, kv in old.items():
    for key, value in kv.items():
        if value in ('""', "[]", ""):
            continue
        text = set_in_text(text, sec, key, value)
        carried += 1
cfg.write_text(text, encoding="utf-8")
print(f"  已升级 config.toml 到最新结构（旧文件备份为 config.toml.bak，保留你原有的 {carried} 项非空配置）")
PYEOF
  chmod 600 config.toml
fi

if [ -t 0 ] || [ "${INTEL_WIZARD:-}" = "1" ]; then
  echo
  echo "  凭据向导：每项都可直接回车跳过（跳过=该平台暂不可用，其余照常）"
  read -r -p "  YouTube Data API key            : " v_yt
  read -r -p "  Kick client_id                  : " v_kid
  read -r -p "  Kick client_secret              : " v_ksec
  read -r -p "  Kick access_token（有则可跳）    : " v_ktok
  read -r -p "  Instagram sessionid             : " v_ig
  read -r -p "  OpenAI 兼容 base_url（缺 codex）  : " v_ob
  read -r -p "  OpenAI 兼容 api_key             : " v_ok
  read -r -p "  OpenAI 兼容 model               : " v_om
  [ -n "$v_yt" ]   && { set_toml youtube api_key "$v_yt"; echo "  ✅ YouTube key 已写入"; }
  [ -n "$v_kid" ]  && { set_toml kick client_id "$v_kid"; echo "  ✅ Kick client_id 已写入"; }
  [ -n "$v_ksec" ] && { set_toml kick client_secret "$v_ksec"; echo "  ✅ Kick client_secret 已写入"; }
  [ -n "$v_ktok" ] && { set_toml kick access_token "$v_ktok"; echo "  ✅ Kick access_token 已写入"; }
  [ -n "$v_ig" ]   && { set_toml instagram session_id "$v_ig"; echo "  ✅ Instagram sessionid 已写入"; }
  [ -n "$v_ob" ]   && set_toml collab openai_base_url "$v_ob"
  [ -n "$v_ok" ]   && set_toml collab openai_api_key "$v_ok"
  [ -n "$v_om" ]   && set_toml collab openai_model "$v_om"
  [ -n "$v_ob$v_ok$v_om" ] && echo "  ✅ OpenAI 兼容端字段已写入（三项齐了才生效）"
  echo "  （凭据只写在本机 config.toml，不会被提交到 git）"
else
  echo "  非交互环境 → 跳过凭据向导（可稍后编辑 config.toml）"
fi

say "4/6 模型端"
have claude && echo "  ✅ claude 已就位" || echo "  ⚠️  无 claude：需下载 Claude Code 并登录后使用"
have codex  && echo "  ✅ codex 已就位"  || echo "  ⚠️  无 codex：可在 config.toml 的 [collab] 填 OpenAI 兼容端替代"

say "5/6 冒烟自检（跑一条免凭据的腿）"
"$PY" intel hot --platform twitch --no-save 2>&1 | head -20

say "6/6 装载到 agent"
if [ -d "$HOME/.claude" ]; then
  "$PY" - "$REPO_DIR" <<'PYEOF'
import pathlib, sys
repo = pathlib.Path(sys.argv[1])
src = repo / "agent" / "claude-skill" / "SKILL.md"
dest = pathlib.Path.home() / ".claude" / "skills" / "intel-workflow" / "SKILL.md"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(src.read_text(encoding="utf-8").replace("{{INTEL_DIR}}", str(repo)), encoding="utf-8")
print(f"  ✅ Claude Code skill → {dest}")
PYEOF
else
  echo "  ⚠️  未检测到 ~/.claude（Claude Code 未安装）→ 跳过 skill 装载"
fi
echo "  Codex：把 agent/codex-agents-snippet.md 贴进你项目的 AGENTS.md（<INTEL_DIR> 换成 ${REPO_DIR}）"

say "完成 → 用法：${REPO_DIR}/intel hot --platform all --region US"
echo "  详细教程见 docs/INSTALL.md；遇到问题先看它的「卡住了怎么办」一节。"
