"""news：站点解析 / 日报整合 / 推送纪律 / plist 渲染 —— 全部离线，不发任何请求。

重点回归：
  · 日报正文必须是英文（能过 push.assert_no_cjk —— 否则推不出去）
  · 默认 dry-run：push() 不碰 http
  · 幂等：当天成功跑过就不再抓
  · plist 的 PATH / RunAtLoad / 时间必须写对（launchd 环境缺 PATH 时 node 起不来）
"""
import contextlib
import io
import json
import pathlib
import plistlib
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from intel_workflow.adapters.base import Degraded  # noqa: E402
from intel_workflow.core.model import Intel, Item  # noqa: E402
from intel_workflow.news import digest as news_digest  # noqa: E402
from intel_workflow.news import feed as news_feed  # noqa: E402
from intel_workflow.news import fetch as news_fetch  # noqa: E402
from intel_workflow.news import push as news_push  # noqa: E402
from intel_workflow.news import schedule as news_sched  # noqa: E402
from intel_workflow.news import sitemap as news_sitemap  # noqa: E402
from intel_workflow.news import sites as news_sites  # noqa: E402


def _cfg(sections=None):
    data = sections or {}
    return types.SimpleNamespace(section=lambda name: data.get(name, {}))


def _intel(key="sbcnews", urls=("https://sbcnews.co.uk/a",), titles=None):
    titles = titles or [f"Headline {i}" for i in range(len(urls))]
    return Intel(
        platform=key, kind="news", method="heur",
        source="sbcnews.co.uk 列表页（有头浏览器渲染，持久 profile 复用会话）",
        confidence="medium",
        items=[Item(rank=i + 1, title=t, url=u, metrics={"time": "3 hours ago", "site": "sbcnews.co.uk"})
               for i, (u, t) in enumerate(zip(urls, titles))],
    )


class SiteTest(unittest.TestCase):
    def test_builtin_sites_and_keys(self):
        got = news_sites.resolve(_cfg())
        self.assertEqual([s.key for s in got], ["igaming", "igamingbusiness", "sbcnews", "yogonet"])
        self.assertEqual(got[0].domain, "igaming.news")

    def test_config_overrides_and_appends(self):
        cfg = _cfg({"news": {"sites": ["https://example.com/news/"], "extra_sites": ["https://extra.org/"]}})
        got = news_sites.resolve(cfg)
        self.assertEqual([s.domain for s in got], ["example.com", "extra.org"])

    def test_selectors_bound_by_domain_and_dedup(self):
        cfg = _cfg({"news": {"extra_sites": ["https://igaming.news/latest", "https://new.site/"],
                             "per_site_limit": 5},
                    "news.selectors": {"new.site": "article h2 a"}})
        got = {s.domain: s for s in news_sites.resolve(cfg)}
        self.assertEqual(got["new.site"].selector, "article h2 a")
        self.assertEqual(got["new.site"].limit, 5)
        self.assertNotIn("igaming.news/latest", [s.url for s in got.values()])  # 同域去重


class DigestTest(unittest.TestCase):
    def test_marks_new_against_history(self):
        intel = _intel(urls=("https://sbcnews.co.uk/1", "https://sbcnews.co.uk/2"))
        markdown, stats = news_digest.build([intel], {"https://sbcnews.co.uk/1"})
        self.assertEqual(stats["items"], 2)
        self.assertEqual(stats["new"], 1)
        self.assertIn("**NEW** [Headline 1]", markdown)
        self.assertIn("1 new_", markdown)

    def test_first_run_is_flagged(self):
        markdown, stats = news_digest.build([_intel()], set())
        self.assertTrue(stats["first_run"])
        self.assertIn("First run", markdown)

    def test_digest_body_is_english(self):
        """日报要能过「外发禁中文」校验，否则推送时会被拒。"""
        markdown, _ = news_digest.build([_intel()], set())
        self.assertEqual(news_push.assert_no_cjk(markdown), markdown)

    def test_failures_section_stays_english(self):
        """失败原因不能把中文异常消息带进日报 —— 否则推送会被 assert_no_cjk 拒发（真实踩过）。"""
        markdown, stats = news_digest.build(
            [_intel()], set(), failures=[("sbcnews", "not fetched — render/extract failed (see local log)")]
        )
        self.assertEqual(stats["failed"], 1)
        self.assertIn("## Sources not fetched", markdown)
        news_push.assert_no_cjk(markdown)

    def test_history_reads_previous_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "2026-10-10-sbcnews-news.jsonl").write_text(
                json.dumps(_intel().to_dict()) + "\n", encoding="utf-8")
            self.assertIn("https://sbcnews.co.uk/a", news_digest.history_urls(tmp))


class PushTest(unittest.TestCase):
    def test_rejects_cjk(self):
        for bad in ("今天热点", "English 中文", "。", "，abc"):
            with self.assertRaises(news_push.PushRefused):
                news_push.assert_no_cjk(bad)

    def test_allows_english_and_spanish(self):
        text = "iGaming News Digest — 12 items · Reporte diario en español"
        self.assertEqual(news_push.assert_no_cjk(text), text)

    def test_lark_payload_shape(self):
        payload = news_push.lark_payload("Title", "# Heading\n- item")
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(payload["card"]["header"]["title"]["content"], "Title")
        self.assertIn("lark_md", json.dumps(payload))

    def test_channels_disabled_by_default(self):
        self.assertEqual(news_push.channels(_cfg()), (None, None))

    def test_channels_enabled(self):
        cfg = _cfg({"push.lark": {"enabled": True, "webhook": "https://open.larksuite.com/open-apis/bot/v2/hook/x"},
                    "push.email": {"enabled": True, "host": "smtp.example.com", "to": ["a@b.c"]}})
        lark, email = news_push.channels(cfg)
        self.assertTrue(lark["webhook"].startswith("https://"))
        self.assertEqual(email["to"], ["a@b.c"])

    def test_dry_run_touches_nothing(self):
        class Boom:
            def post_json(self, *a, **k):
                raise AssertionError("dry-run 不应该发请求")

        cfg = _cfg({"push.lark": {"enabled": True, "webhook": "https://open.larksuite.com/open-apis/bot/v2/hook/x"}})
        actions = news_push.push(cfg, "Title", "- body", Boom(), dry_run=True, log=lambda *_: None)
        self.assertTrue(any("dry-run" in a for a in actions))

    def test_push_refuses_cjk_even_in_dry_run(self):
        cfg = _cfg({"push.lark": {"enabled": True, "webhook": "https://open.larksuite.com/open-apis/bot/v2/hook/x"}})
        with self.assertRaises(news_push.PushRefused):
            news_push.push(cfg, "标题", "body", object(), dry_run=True, log=lambda *_: None)

    def test_markdown_to_html(self):
        html = news_push.markdown_to_html("# T\n- [A](https://x) **B**")
        self.assertIn('<a href="https://x">A</a>', html)
        self.assertIn("<strong>B</strong>", html)

    def test_email_message_headers(self):
        msg = news_push.email_message("from@x.com", ["to@y.com"], "Digest", "# T\n- a")
        self.assertEqual(msg["To"], "to@y.com")
        self.assertEqual(len(msg.get_payload()), 2)  # text + html


class PlistTest(unittest.TestCase):
    def _data(self, **kw):
        return plistlib.loads(news_sched.render_plist("/usr/bin/python3", "/repo", **kw))

    def test_arguments_and_schedule(self):
        data = self._data(hour=7, minute=5, send=True)
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/python3", "/repo/intel", "news", "run", "--send"])
        self.assertEqual(data["StartCalendarInterval"], {"Hour": 7, "Minute": 5})
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["WorkingDirectory"], "/repo")

    def test_no_send_by_default(self):
        self.assertNotIn("--send", self._data()["ProgramArguments"])

    def test_path_is_explicit(self):
        env = self._data()["EnvironmentVariables"]
        self.assertIn("/opt/homebrew/bin", env["PATH"])  # launchd 的 PATH 极简，必须自带

    def test_node_path_passthrough(self):
        self.assertEqual(self._data(node_path="/x/node_modules")["EnvironmentVariables"]["INTEL_NODE_PATH"],
                         "/x/node_modules")


class ScheduleStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = news_sched.STATE
        news_sched.STATE = pathlib.Path(self._tmp.name) / "news_state.json"

    def tearDown(self):
        news_sched.STATE = self._old
        self._tmp.cleanup()

    def test_idempotent_by_date(self):
        self.assertFalse(news_sched.already_ran())
        news_sched.mark_run(success=True)
        self.assertTrue(news_sched.already_ran())

    def test_failure_does_not_mark_success(self):
        news_sched.mark_run(success=True)
        news_sched.mark_run(success=False, note="boom")
        self.assertTrue(news_sched.already_ran())
        self.assertEqual(news_sched.read_state()["last_status"], "failed")


class NewsRunTest(unittest.TestCase):
    """_news_run 的编排：幂等跳过 / 全站失败不编日报。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = types.SimpleNamespace(
            section=lambda name: {"output": {"dir": self.dir}} if name == "output" else {},
            output_dir=self.dir,
            gate_options={"min_interval": 15, "daily_cap": 200, "cooldown": 21600},
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _args(self, **kw):
        base = dict(action="run", force=False, out=None, no_save=True, sites="https://example.com/news/",
                    profile=None, headless=True, send=False, debug=False, config=None)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_skips_when_already_ran_today(self):
        from intel_workflow import cli
        with mock.patch.object(news_sched, "already_ran", return_value=True):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli._news_run(self._args(), self.cfg)
        self.assertEqual(rc, 0)
        self.assertIn("跳过", buf.getvalue())

    def test_all_sources_failing_writes_no_digest(self):
        from intel_workflow import cli
        with mock.patch.object(news_sched, "already_ran", return_value=False), \
             mock.patch.object(news_sched, "mark_run") as marked, \
             mock.patch("intel_workflow.news.fetch.fetch_site", side_effect=Degraded("boom")), \
             mock.patch("intel_workflow.cli.Http"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli._news_run(self._args(force=True), self.cfg)
        self.assertEqual(rc, 1)
        self.assertIn("一个站点都没抓到", buf.getvalue())
        self.assertFalse(marked.call_args.kwargs.get("success", True))
        self.assertEqual(list(pathlib.Path(self.dir).glob("*-news-digest.md")), [])


class FeedTest(unittest.TestCase):
    """feed 解析（离线）。真实样本取自 sbcnews.co.uk/feed/（RSS 2.0）。"""

    RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>SBC &amp; partners launch <![CDATA[<b>report</b>]]></title>
    <link>https://sbcnews.co.uk/a-post/</link>
    <pubDate>Fri, 09 Oct 2026 09:56:06 +0000</pubDate></item>
  <item><title>Second story</title><link>https://sbcnews.co.uk/second/</link></item>
</channel></rss>"""

    ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom story</title><link rel="alternate" href="https://x.example/atom-post"/>
    <updated>2026-10-10T12:00:00Z</updated></entry>
</feed>"""

    def test_rss_items(self):
        items = news_feed.parse(self.RSS, limit=5)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "SBC & partners launch report")  # CDATA + 实体都清掉
        self.assertEqual(items[0]["url"], "https://sbcnews.co.uk/a-post/")
        self.assertIn("Oct 2026", items[0]["time"])

    def test_atom_items(self):
        items = news_feed.parse(self.ATOM)
        self.assertEqual(items[0]["title"], "Atom story")
        self.assertEqual(items[0]["url"], "https://x.example/atom-post")
        self.assertIn("2026", items[0]["time"])

    def test_limit_and_garbage(self):
        self.assertEqual(len(news_feed.parse(self.RSS, limit=1)), 1)
        self.assertEqual(news_feed.parse("<html>not a feed</html>"), [])
        self.assertEqual(news_feed.parse(""), [])


class FeedSiteTest(unittest.TestCase):
    def test_builtin_sbcnews_uses_feed(self):
        got = {s.domain: s for s in news_sites.resolve(_cfg())}
        self.assertEqual(got["sbcnews.co.uk"].feed, "https://sbcnews.co.uk/feed/")
        self.assertEqual(got["igaming.news"].feed, "")

    def test_feed_from_config_by_domain(self):
        cfg = _cfg({"news": {"extra_sites": ["https://extra.org/"], "feeds": {"extra.org": "https://extra.org/rss"}}})
        got = {s.domain: s for s in news_sites.resolve(cfg)}
        self.assertEqual(got["extra.org"].feed, "https://extra.org/rss")


class SitemapTest(unittest.TestCase):
    """sitemap 解析（离线）。样本取自 igaming.news/news-sitemap.xml（Google News 扩展）。"""

    NEWS_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://igaming.news/news/2026-10-09/wazdan-bolsters-danish-market-position</loc>
    <news:news>
      <news:publication><news:name>iGaming News</news:name><news:language>en</news:language></news:publication>
      <news:publication_date>2026-10-09T00:00:00.000Z</news:publication_date>
      <news:title>Wazdan Bolsters Danish Market Position</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://igaming.news/news/2026-10-08/maine-regulator-targets-q1-2027</loc>
    <news:news>
      <news:publication_date>2026-10-08T00:00:00.000Z</news:publication_date>
      <news:title>Maine Regulator Targets Q1 2027</news:title>
    </news:news>
  </url>
</urlset>"""

    INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://x.example/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://x.example/news-sitemap.xml</loc></sitemap>
</sitemapindex>"""

    def test_news_sitemap_items(self):
        items = news_sitemap.parse(self.NEWS_SITEMAP, limit=5)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Wazdan Bolsters Danish Market Position")
        self.assertEqual(
            items[0]["url"],
            "https://igaming.news/news/2026-10-09/wazdan-bolsters-danish-market-position",
        )
        self.assertIn("Oct 2026", items[0]["time"])

    def test_plain_sitemap_falls_back_to_slug_title(self):
        plain = ('<?xml version="1.0"?><urlset><url>'
                 '<loc>https://x.example/news/wazdan-bolsters-danish-position</loc>'
                 '<lastmod>2026-10-07</lastmod></url></urlset>')
        items = news_sitemap.parse(plain)
        self.assertEqual(items[0]["title"], "Wazdan bolsters danish position")  # 无 <title> 时由 slug 兜底
        self.assertIn("2026", items[0]["time"])

    def test_index_detection_and_news_first(self):
        self.assertTrue(news_sitemap.is_index(self.INDEX))
        self.assertFalse(news_sitemap.is_index(self.NEWS_SITEMAP))
        self.assertEqual(news_sitemap.child_sitemaps(self.INDEX)[0], "https://x.example/news-sitemap.xml")

    def test_limit_and_garbage(self):
        self.assertEqual(len(news_sitemap.parse(self.NEWS_SITEMAP, limit=1)), 1)
        self.assertEqual(news_sitemap.parse("<html>nope</html>"), [])
        self.assertEqual(news_sitemap.parse(""), [])


class ChannelCoverageTest(unittest.TestCase):
    """默认清单必须**全部**走纯 HTTP —— 否则同事又得装 node + playwright（2026-10-12 改）。"""

    def test_all_builtin_sites_are_browser_free(self):
        got = news_sites.resolve(_cfg())
        self.assertEqual({s.domain: news_fetch.channel_of(s) for s in got}, {
            "igaming.news": "sitemap",
            "igamingbusiness.com": "feed",
            "sbcnews.co.uk": "feed",
            "www.yogonet.com": "feed",
        })

    def test_sitemap_from_config_by_domain(self):
        cfg = _cfg({"news": {"extra_sites": ["https://extra.org/"],
                             "sitemaps": {"extra.org": "https://extra.org/sitemap.xml"}}})
        got = {s.domain: s for s in news_sites.resolve(cfg)}
        self.assertEqual(got["extra.org"].sitemap, "https://extra.org/sitemap.xml")
        self.assertEqual(news_fetch.channel_of(got["extra.org"]), "sitemap")


class FetchChannelTest(unittest.TestCase):
    class _StubHttp:
        def __init__(self, body=""):
            self.body = body
            self.calls = []

        def get(self, url, domain=None):
            self.calls.append(url)
            return 200, self.body

    def _site(self, feed="", sitemap=""):
        return news_sites.Site(key="sbcnews", url="https://sbcnews.co.uk/", domain="sbcnews.co.uk",
                               feed=feed, sitemap=sitemap)

    def test_sitemap_site_never_touches_browser(self):
        http = self._StubHttp(SitemapTest.NEWS_SITEMAP)
        intel = news_fetch.fetch(self._site(sitemap="https://igaming.news/news-sitemap.xml"), http,
                                 profile="/nonexistent-profile")
        self.assertEqual(intel.method, "sitemap")
        self.assertEqual(len(intel.items), 2)
        # 先拿 sitemap；之后通道会**逐篇抓文章页补 og:image**（sitemap 天生不给图）——
        # 全程仍是纯 HTTP、不起浏览器（2026-10-14 加补图后断言相应放宽）。
        self.assertEqual(http.calls[0], "https://igaming.news/news-sitemap.xml")
        self.assertTrue(all(c.startswith("http") for c in http.calls))
        self.assertEqual(intel.items[0].title, "Wazdan Bolsters Danish Market Position")
        self.assertIn("Oct 2026", intel.items[0].metrics["time"])
        for item in intel.items:
            news_push.assert_no_cjk(item.title)

    def test_feed_wins_over_sitemap(self):
        site = self._site(feed="https://sbcnews.co.uk/feed/", sitemap="https://sbcnews.co.uk/news-sitemap.xml")
        self.assertEqual(news_fetch.channel_of(site), "feed")

    def test_sitemap_index_follows_news_child(self):
        """配的是 sitemapindex 时自动跟到含 news 的子 sitemap（第二次请求按闸门间隔等待）。"""
        http = self._StubHttp(SitemapTest.NEWS_SITEMAP)
        http.body = SitemapTest.INDEX           # 第一次给 index，之后给真 sitemap
        calls = []

        def _get(url, domain=None):
            calls.append(url)
            http.body = SitemapTest.NEWS_SITEMAP
            return 200, SitemapTest.INDEX if len(calls) == 1 else SitemapTest.NEWS_SITEMAP

        http.get = _get
        http.gate = types.SimpleNamespace(min_interval=0)   # 测试里不等 15 秒
        intel = news_fetch.fetch(self._site(sitemap="https://x.example/sitemap.xml"), http)
        self.assertEqual(intel.method, "sitemap")
        # 头两次是 sitemapindex → 子 sitemap；其余是逐篇补图的文章页
        self.assertEqual(calls[:2], ["https://x.example/sitemap.xml", "https://x.example/news-sitemap.xml"])
        self.assertTrue(all(c.startswith("http") for c in calls))


    def test_feed_site_never_touches_browser(self):
        http = self._StubHttp(FeedTest.RSS)
        intel = news_fetch.fetch(self._site("https://sbcnews.co.uk/feed/"), http, profile="/nonexistent-profile")
        self.assertEqual(intel.method, "feed")
        self.assertEqual(len(intel.items), 2)
        self.assertEqual(http.calls, ["https://sbcnews.co.uk/feed/"])  # 只发了一次 HTTP，没起浏览器
        for item in intel.items:
            news_push.assert_no_cjk(item.title)

    def test_feed_without_items_raises(self):
        with self.assertRaises(Degraded):
            news_fetch.fetch(self._site("https://sbcnews.co.uk/feed/"), self._StubHttp("<html>nope</html>"))

    def test_profile_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            with news_fetch.profile_lock(tmp) as first:
                self.assertTrue(first)
                with news_fetch.profile_lock(tmp) as second:
                    self.assertFalse(second)   # 并发的那一方被挡下，而不是两边一起挂
            with news_fetch.profile_lock(tmp) as again:
                self.assertTrue(again)          # 上一轮结束后锁必须释放


class HealthTest(unittest.TestCase):
    def _many(self, n):
        return _intel(urls=tuple(f"https://sbcnews.co.uk/{i}" for i in range(n)))

    def test_drop_is_flagged_in_english(self):
        notices = news_digest.health_notices({"sbcnews": 15}, [self._many(1)])
        self.assertEqual(len(notices), 1)
        self.assertIn("only 1 items vs 15", notices[0])
        news_push.assert_no_cjk(notices[0])

    def test_stable_and_first_run_are_not_flagged(self):
        self.assertEqual(news_digest.health_notices({"sbcnews": 15}, [self._many(14)]), [])
        self.assertEqual(news_digest.health_notices({}, [self._many(2)]), [])

    def test_scan_reports_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = _intel(urls=("https://sbcnews.co.uk/1", "https://sbcnews.co.uk/2"))
            (pathlib.Path(tmp) / "2026-10-10-sbcnews-news.jsonl").write_text(
                json.dumps(rec.to_dict()) + "\n", encoding="utf-8")
            urls, counts = news_digest.scan(tmp)
            self.assertEqual(counts["sbcnews"], 2)
            self.assertIn("https://sbcnews.co.uk/1", urls)


if __name__ == "__main__":
    unittest.main()
