"""HTTP 层风控判定：只有 429/503、或 403+挑战页特征才熔断；普通 404 不熔断。

回归点：曾经因为只看响应里有没有 "cloudflare" 字样，导致 404 页面把整个域名冷却 6 小时。
"""
import io
import pathlib
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.core.gate import Gate, RateLimited  # noqa: E402
from intel_workflow.core.http import Http, HttpError  # noqa: E402


class _FakeOpener:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def open(self, req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, self.status, "err", {}, io.BytesIO(self.body.encode("utf-8"))
        )


class HttpRiskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self._tmp.name) / "gate.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _http(self, status, body):
        http = Http(gate=Gate(self.state))
        http.opener = _FakeOpener(status, body)
        return http

    def test_429_trips_gate(self):
        http = self._http(429, "Too Many Requests")
        with self.assertRaises(RateLimited):
            http.get("https://x.test/a", domain="x.test")
        ok, why = http.gate.check("x.test")
        self.assertFalse(ok)
        self.assertIn("冷却", why)

    def test_404_mentioning_cloudflare_does_not_trip(self):
        http = self._http(404, "<html>cloudflare: not found</html>")
        with self.assertRaises(HttpError):
            http.get("https://x.test/a", domain="x.test")
        _, why = http.gate.check("x.test")
        self.assertNotIn("冷却", why, "普通 404 不该触发熔断")

    def test_403_without_challenge_does_not_trip(self):
        http = self._http(403, "Forbidden")
        with self.assertRaises(HttpError):
            http.get("https://x.test/a", domain="x.test")
        _, why = http.gate.check("x.test")
        self.assertNotIn("冷却", why)

    def test_403_with_challenge_trips(self):
        http = self._http(403, "<title>Just a moment...</title>")
        with self.assertRaises(RateLimited):
            http.get("https://x.test/a", domain="x.test")
        _, why = http.gate.check("x.test")
        self.assertIn("冷却", why)


if __name__ == "__main__":
    unittest.main()
