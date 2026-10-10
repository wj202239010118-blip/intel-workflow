"""闸门：最小间隔 / 每日上限 / 熔断冷却 / 持久化 / 域名隔离。"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.core.gate import Gate  # noqa: E402


class GateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self._tmp.name) / "gate.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_domain_allowed(self):
        ok, why = Gate(self.state).check("example.com")
        self.assertTrue(ok, why)

    def test_min_interval_blocks(self):
        gate = Gate(self.state, min_interval=15)
        gate.record("example.com")
        ok, why = gate.check("example.com")
        self.assertFalse(ok)
        self.assertIn("最小间隔", why)

    def test_daily_cap_blocks(self):
        gate = Gate(self.state, min_interval=0, daily_cap=2)
        gate.record("d.com")
        gate.record("d.com")
        ok, why = gate.check("d.com")
        self.assertFalse(ok)
        self.assertIn("每日上限", why)

    def test_trip_sets_cooldown(self):
        gate = Gate(self.state)
        gate.trip("d.com", seconds=60)
        ok, why = gate.check("d.com")
        self.assertFalse(ok)
        self.assertIn("冷却", why)

    def test_cooldown_persists_across_instances(self):
        Gate(self.state).trip("d.com", seconds=60)
        ok, why = Gate(self.state).check("d.com")
        self.assertFalse(ok)
        self.assertIn("冷却", why)

    def test_domains_are_independent(self):
        gate = Gate(self.state, min_interval=15)
        gate.record("a.com")
        ok, _ = gate.check("b.com")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
