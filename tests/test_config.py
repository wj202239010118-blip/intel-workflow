"""配置解析：零依赖兜底解析器必须与标准库 tomllib 结果一致。

回归点：macOS 自带的 Python 3.9 没有 tomllib，兜底解析器是唯一可用路径。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.config import ROOT, _simple_toml  # noqa: E402


class SimpleTomlTest(unittest.TestCase):
    def test_types_and_trailing_comments(self):
        text = """
[gate]
min_interval_seconds = 15      # 行尾注释
daily_cap_per_domain = 200

[instagram]
session_id = ""
seed_accounts = []
"""
        data = _simple_toml(text)
        self.assertEqual(data["gate"]["min_interval_seconds"], 15)
        self.assertEqual(data["gate"]["daily_cap_per_domain"], 200)
        self.assertEqual(data["instagram"]["session_id"], "")
        self.assertEqual(data["instagram"]["seed_accounts"], [])

    def test_array_of_strings(self):
        data = _simple_toml('[instagram]\nseed_accounts = ["a", "b c"]\n')
        self.assertEqual(data["instagram"]["seed_accounts"], ["a", "b c"])

    def test_booleans_and_full_line_comments(self):
        data = _simple_toml("# 注释\n[x]\nflag = true\nother = false\n")
        self.assertIs(data["x"]["flag"], True)
        self.assertIs(data["x"]["other"], False)

    def test_matches_stdlib_on_example_config(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            self.skipTest("tomllib 不可用（Python < 3.11）")
        text = (ROOT / "config.example.toml").read_text(encoding="utf-8")
        self.assertEqual(_simple_toml(text), tomllib.loads(text))


if __name__ == "__main__":
    unittest.main()
