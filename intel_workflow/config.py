"""配置读取：config.toml + 环境变量兜底。

零第三方依赖 —— macOS 自带的 Python 3.9（无 tomllib）也能开箱运行：
优先 tomllib(Py3.11+) → tomli(可选) → 内置极简解析器。
"""
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config.toml"


def _simple_toml(text):
    """极简 TOML 子集：`[section]` / `[a.b]` + `key = value`（字符串 / 整数 / 布尔 / 字符串数组）。

    仅在 tomllib 与 tomli 都不可用时启用（macOS 自带 Python 3.9）；语义与 tomllib 对齐
    —— `[a.b]` 解成嵌套 dict，这样 config.section("a.b") 两种解析器下行为一致。
    """
    data, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = re.fullmatch(r"\[([^\]]+)\]", line)
        if head:
            node = data
            for part in [p.strip() for p in head.group(1).split(".")]:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
            current = node
            continue
        if "=" not in line or current is None:
            continue
        key, value = line.split("=", 1)
        if " #" in value:  # 去掉行尾注释
            value = value.split(" #", 1)[0]
        key, value = key.strip().strip('"'), value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            parsed = value[1:-1]
        elif value.startswith("[") and value.endswith("]"):
            parsed = [v.strip().strip('"') for v in value[1:-1].split(",") if v.strip()]
        elif value in ("true", "false"):
            parsed = value == "true"
        elif value.isdigit():
            parsed = int(value)
        else:
            parsed = value
        current[key] = parsed
    return data


def _loader():
    try:
        import tomllib  # Python >= 3.11
        return tomllib.loads
    except ModuleNotFoundError:
        pass
    try:
        import tomli  # 可选依赖
        return tomli.loads
    except ModuleNotFoundError:
        return _simple_toml


class Config:
    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else DEFAULT_PATH
        self.data = {}
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8")
            try:
                self.data = _loader()(text)
            except Exception as exc:
                raise SystemExit(f"config.toml 解析失败：{exc}")

    def section(self, name):
        """按名字取一段。兼容两种解析器：tomllib 把 [a.b] 解成嵌套 dict，
        内置解析器解成扁平的 "a.b" 键 —— 这里两种都认。"""
        if name in self.data:
            value = self.data.get(name)
        else:
            value = self.data
            for part in name.split("."):
                value = value.get(part) if isinstance(value, dict) else None
        return value if isinstance(value, dict) else {}

    # --- 凭据（缺则返回空串，由适配器给出「去哪申请」的提示） ---
    @property
    def youtube_api_key(self):
        return (self.section("youtube").get("api_key") or os.environ.get("YOUTUBE_API_KEY") or "").strip()

    @property
    def kick_access_token(self):
        return (self.section("kick").get("access_token") or os.environ.get("KICK_ACCESS_TOKEN") or "").strip()

    @property
    def instagram_session_id(self):
        return (self.section("instagram").get("session_id") or os.environ.get("IG_SESSIONID") or "").strip()

    @property
    def instagram_seed_accounts(self):
        value = self.section("instagram").get("seed_accounts") or []
        return [str(a).strip() for a in value if str(a).strip()]

    @property
    def output_dir(self):
        return self.section("output").get("dir") or "out"

    @property
    def gate_options(self):
        gate = self.section("gate")
        return {
            "min_interval": int(gate.get("min_interval_seconds", 15)),
            "daily_cap": int(gate.get("daily_cap_per_domain", 200)),
            "cooldown": int(gate.get("cooldown_seconds", 21600)),
        }

    # --- 双模型协同 ---
    @property
    def collab_mode(self):
        return (self.section("collab").get("mode") or "auto").strip()

    @property
    def openai_base_url(self):
        return (self.section("collab").get("openai_base_url") or os.environ.get("OPENAI_BASE_URL") or "").strip()

    @property
    def openai_api_key(self):
        return (self.section("collab").get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()

    @property
    def openai_model(self):
        return (self.section("collab").get("openai_model") or os.environ.get("OPENAI_MODEL") or "").strip()
