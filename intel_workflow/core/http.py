"""HTTP 客户端：直连、带闸门、命中风控即熔断。"""
import gzip
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .gate import Gate, RateLimited

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RISK_MARKERS = ("cloudflare", "rate limit", "too many requests", "just a moment", "错误 1015")


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class Http:
    def __init__(self, gate=None, timeout=25, use_proxy=False):
        self.gate = gate or Gate()
        self.timeout = timeout
        handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
        if not use_proxy:
            handlers.insert(0, urllib.request.ProxyHandler({}))  # 默认直连
        self.opener = urllib.request.build_opener(*handlers)

    def _send(self, url, data, headers, domain):
        domain = domain or urllib.parse.urlsplit(url).netloc
        allowed, why = self.gate.check(domain)
        if not allowed:
            raise RateLimited(f"{domain}: {why}")
        req = urllib.request.Request(
            url, data=data,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", **(headers or {})},
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                self.gate.record(domain)
                return resp.status, raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            self.gate.record(domain)
            raw = exc.read()
            if exc.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            text = raw.decode("utf-8", "replace")
            low = text.lower()
            if exc.code in (429, 503) or any(m in low for m in RISK_MARKERS):
                self.gate.trip(domain)
                raise RateLimited(
                    f"{domain}: 命中风控 HTTP {exc.code} → 已熔断，冷却 {self.gate.cooldown}s，不自动重试"
                ) from exc
            raise HttpError(exc.code, text) from exc

    def get(self, url, domain=None, headers=None):
        return self._send(url, None, headers, domain)

    def post_json(self, url, payload, domain=None, headers=None):
        body = json.dumps(payload).encode("utf-8")
        status, text = self._send(url, body, {"Content-Type": "application/json", **(headers or {})}, domain)
        return status, json.loads(text)

    def get_json(self, url, domain=None, headers=None):
        status, text = self.get(url, domain=domain, headers=headers)
        return status, json.loads(text)
