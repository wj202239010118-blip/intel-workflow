"""适配器纯逻辑：region 归一化 / 白名单校验（不发请求）。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.adapters.base import Degraded  # noqa: E402
from intel_workflow.adapters.tiktok import validate_region  # noqa: E402
from intel_workflow.adapters.x import slug_for  # noqa: E402


class XRegionTest(unittest.TestCase):
    def test_country_codes_map_to_slugs(self):
        self.assertEqual(slug_for("US"), "united-states")
        self.assertEqual(slug_for("id"), "indonesia")
        self.assertEqual(slug_for("MX"), "mexico")
        self.assertEqual(slug_for("NG"), "nigeria")

    def test_slug_passthrough_and_normalisation(self):
        self.assertEqual(slug_for("united-states"), "united-states")
        self.assertEqual(slug_for("south korea"), "south-korea")

    def test_default_is_united_states(self):
        self.assertEqual(slug_for(None), "united-states")
        self.assertEqual(slug_for("  "), "united-states")


class TikTokRegionTest(unittest.TestCase):
    def test_valid_values(self):
        self.assertEqual(validate_region("us"), "US")
        self.assertEqual(validate_region(None), "US")
        self.assertEqual(validate_region("ID"), "ID")

    def test_rejects_injection_attempts(self):
        for bad in ("US; rm -rf /", "united states", "toolongregion", "US/../etc"):
            with self.assertRaises(Degraded):
                validate_region(bad)


if __name__ == "__main__":
    unittest.main()
