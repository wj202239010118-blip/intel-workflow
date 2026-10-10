"""digest：对比历史抓取（离线，不发请求）。"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.cli import _digest  # noqa: E402


def _record(fetched_at, titles, region="US"):
    return {
        "platform": "twitch", "kind": "hot", "region": region,
        "fetched_at": fetched_at, "source": "test", "method": "primary",
        "confidence": "high", "caveat": "",
        "items": [
            {"rank": i + 1, "title": t, "url": "", "metrics": {}}
            for i, t in enumerate(titles)
        ],
    }


class DigestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self):
        args = types.SimpleNamespace(out=str(self.out), no_save=True)
        cfg = types.SimpleNamespace(output_dir=str(self.out))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _digest(args, cfg)
        return rc, buf.getvalue()

    def test_no_history(self):
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("还没有历史记录", out)

    def test_single_snapshot_is_not_enough(self):
        (self.out / "2026-10-10-twitch-hot-US.jsonl").write_text(
            json.dumps(_record("2026-10-10T10:00:00+00:00", ["A", "B"])) + "\n", encoding="utf-8"
        )
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("还不够两次记录", out)

    def test_added_dropped_and_moved(self):
        path = self.out / "2026-10-10-twitch-hot-US.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_record("2026-10-10T10:00:00+00:00", ["A", "B", "C"])) + "\n")
            fh.write(json.dumps(_record("2026-10-10T11:00:00+00:00", ["B", "A", "D"])) + "\n")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("新进榜（1）：D", out)
        self.assertIn("掉榜（1）：C", out)
        self.assertIn("A（1 → 2）", out)

    def test_platforms_are_grouped_separately(self):
        path = self.out / "2026-10-10-mixed.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            a = _record("2026-10-10T10:00:00+00:00", ["A"])
            b = dict(a, fetched_at="2026-10-10T11:00:00+00:00", items=[
                {"rank": 1, "title": "B", "url": "", "metrics": {}}])
            fh.write(json.dumps(a) + "\n")
            fh.write(json.dumps(b) + "\n")
        _, out = self._run()
        self.assertIn("## twitch · hot · US", out)


if __name__ == "__main__":
    unittest.main()
