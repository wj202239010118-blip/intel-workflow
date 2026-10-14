#!/usr/bin/env node
// 资讯站列表页抓取：有头 Chromium（默认）+ **持久 profile**（cookie / consent 选择 / 登录态次次复用）。
// 一次调用 = 一次页面导航；不翻页、不并发 —— 闸门由调用方（intel_workflow/news/fetch.py）负责。
//
// 抽取两级：
//   1) 给了 --selector → 按它取（站点校准用）
//   2) 否则「标题驱动」通用启发式：版面里的 h1–h4（排除 header/nav/footer/aside）→ 就近同域文章链接，
//      标题直接取 h 元素文本 —— 不把分类标签、摘要、日期粘进标题
// 链接过滤：同域 + 非导航词 + 末段有 slug 特征（够长 / 多连字符 / 含长数字）
//
// 用法: node news_fetch.js --url=<列表页> --domain=<域名> [--selector="article h3 a"]
//                          [--limit=15] [--profile=<dir>] [--headless=0|1] [--wait=2500]
// 输出: 末行 JSON -> {"url","status","pageTitle","items":[{"rank","title","url","time"}]}
/* playwright 优先；本机若只装了全局 @playwright/mcp（它带 playwright-core，且系统已有
   ~/Library/Caches/ms-playwright 的 chromium）就退到 core —— 两者 API 相同，core 只是不含浏览器下载。
   CI 里会装完整 playwright。 */
let chromium;
try {
  chromium = require("playwright").chromium;
} catch (e) {
  chromium = require("playwright-core").chromium;
}

const argv = Object.fromEntries(
  process.argv.slice(2).filter((a) => a.startsWith("--")).map((a) => {
    const i = a.indexOf("=");
    return i < 0 ? [a.slice(2), "1"] : [a.slice(2, i), a.slice(i + 1)];
  })
);

const URL_ = argv.url || "";
const DOMAIN = (argv.domain || "").toLowerCase();
const SELECTOR = argv.selector || "";
const LIMIT = Number(argv.limit || 15);
const PROFILE = argv.profile || "";
/* --exec=<path>：本机调试用 —— 机器上已有别的 playwright 版本下载的 chromium 时直接指定，
   省掉再下一份。CI 不需要（那里由 playwright 装匹配版本）。 */
const EXEC = argv.exec || "";
const HEADLESS = argv.headless !== undefined ? argv.headless !== "0" : false;
const WAIT = Number(argv.wait || 2500);
const TIMEOUT = Number(argv.timeout || 45000);
/* --og=1：**只取 og:image**（不抽列表）。用途：像 sbcnews 这种整站对 HTTP 返回 403、
   但图片放在独立子域且放行图片扩展名的站 —— 用浏览器读一次文章页拿到图 URL 就够了，
   图片本身由访客浏览器直接从那个子域加载，我们不必下载。 */
const OG_ONLY = !!argv.og;
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

// consent 墙上常见按钮文案（点了才看得到内容；持久 profile 会记住这个选择）
const CONSENT_LABELS = [
  "accept all", "accept all cookies", "accept cookies", "accept", "i agree", "agree",
  "got it", "allow all", "ok", "yes, i agree", "consent", "agree and continue",
];

// 页面内提取
function extract({ selector, limit, domain }) {
  const strip = (s) => (s || "").replace(/\s+/g, " ").trim();
  const bare = (h) => (h || "").replace(/^www\./, "").toLowerCase();
  const bd = bare(domain);
  const norm = (href) => {
    try {
      const u = new URL(href, location.href);
      if (!/^https?:$/.test(u.protocol)) return "";
      u.hash = "";
      ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "fbclid", "gclid"].forEach(
        (k) => u.searchParams.delete(k)
      );
      return u.toString();
    } catch (e) {
      return "";
    }
  };
  const NAV =
    /(^|\/)(about|contact|contact-us|login|sign-?in|sign-?up|register|subscribe|newsletters?|privacy|terms|cookies?|advertis\w*|careers?|jobs?|authors?|tags?|categor\w*|topics?|events?|podcasts?|videos?|webinars?|search|feed|rss|sitemap|amp|wp-login|wp-admin|shop|store|account|partners?|content-type|contentos?-\w*|topic)(\/|$)/i;
  const DATE_RE =
    /\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+('?\d{2}|\d{4})|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:min|minute|hour|day|week|month)s?\s+ago|\d{1,2}[hdw]\s+ago|\d{1,2}:\d{2}\s*(?:am|pm)?)\b/i;

  const sameDomain = (u) => {
    try {
      const h = bare(new URL(u).hostname);
      return !bd || h === bd || h.endsWith("." + bd);
    } catch (e) {
      return false;
    }
  };
  // 末段像文章 slug 吗：够长 / 有 ≥2 个连字符 / 含 4 位年份或长数字（挡住 /partners/xxx/ 这类栏目页）
  const slugOk = (path) => {
    const seg = (path || "").replace(/\/+$/, "").split("/").pop() || "";
    return seg.length >= 20 || (seg.match(/-/g) || []).length >= 2 || /(^|-)\d{4}(-|$)|\d{6,}/.test(seg);
  };
  const timeOf = (anchor) => {
    const scope = anchor.closest("article, li, div, section") || anchor.parentElement || anchor;
    const t = scope.querySelector("time[datetime], time");
    if (t) return strip(t.getAttribute("datetime") || t.textContent);
    const m = strip(scope.textContent).slice(0, 600).match(DATE_RE);
    return m ? m[1] : "";
  };
  // 从一个元素就近找文章链接：自己 → 子孙 → 最多往上 3 层找
  const pickAnchor = (el) => {
    if (!el) return null;
    if (el.matches && el.matches("a[href]")) return el;
    let a = el.querySelector && el.querySelector("a[href]");
    let p = el.parentElement;
    for (let i = 0; i < 3 && !a && p; i++, p = p.parentElement) a = p.querySelector("a[href]");
    return a;
  };

  const out = [];
  const seen = new Set();
  const consider = (title, anchor) => {
    if (!anchor || out.length >= limit) return;
    const url = norm(anchor.getAttribute("href"));
    if (!url || !sameDomain(url) || seen.has(url)) return;
    let path;
    try {
      path = new URL(url).pathname;
    } catch (e) {
      return;
    }
    if (NAV.test(path) || path === "/" || !slugOk(path)) return;
    const text = strip(title);
    if (text.length < 20 || text.length > 200) return;
    seen.add(url);
    out.push({ rank: out.length + 1, title: text, url, time: timeOf(anchor) });
  };

  if (selector) {
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(selector));
    } catch (e) {
      nodes = [];
    }
    for (const n of nodes) {
      const head = n.matches("h1,h2,h3,h4") ? n : n.querySelector("h1,h2,h3,h4");
      const a = pickAnchor(n);
      consider(head ? head.textContent : a && (a.getAttribute("title") || a.textContent), a);
    }
    if (out.length) return out;
  }

  // 标题驱动：版面标题 → 就近文章链接
  const heads = Array.from(document.querySelectorAll("h1,h2,h3,h4")).filter(
    (h) => !h.closest("header, nav, footer, aside")
  );
  for (const h of heads) {
    consider(h.textContent, pickAnchor(h));
    if (out.length >= limit) break;
  }
  return out;
}

async function dismissConsent(page) {
  const hit = await page
    .evaluate((labels) => {
      const nodes = Array.from(
        document.querySelectorAll("button, a, input[type=button], input[type=submit], [role=button]")
      );
      for (const n of nodes.slice(0, 80)) {
        const t = ((n.innerText || n.value || n.textContent || "").trim()).toLowerCase();
        if (!t || t.length > 28) continue;
        if (labels.indexOf(t) >= 0) {
          n.click();
          return t;
        }
      }
      return "";
    }, CONSENT_LABELS)
    .catch(() => "");
  if (hit) await page.waitForTimeout(1500);
  return hit;
}

(async () => {
  const launchOpts = {
    headless: HEADLESS,
    ...(EXEC ? { executablePath: EXEC } : {}),
    userAgent: UA,
    locale: "en-US",
    viewport: { width: 1440, height: 900 },
    args: ["--disable-blink-features=AutomationControlled"],
  };
  const ctx = PROFILE
    ? await chromium.launchPersistentContext(PROFILE, launchOpts) // 持久 profile：cookie/consent/登录态次次复用
    : await (await chromium.launch({ headless: HEADLESS })).newContext(launchOpts);
  try {
    const page = ctx.pages()[0] || (await ctx.newPage());
    const resp = await page.goto(URL_, { waitUntil: "domcontentloaded", timeout: TIMEOUT });
    await page.waitForTimeout(WAIT);
    const consent = await dismissConsent(page);
    for (let i = 0; i < 2; i++) {
      await page.mouse.wheel(0, 2500).catch(() => {}); // 触发懒加载
      await page.waitForTimeout(600);
    }
    await page.waitForTimeout(600);
    const pageTitle0 = await page.title().catch(() => "");
    if (OG_ONLY) {
      /* Cloudflare 的 JS 挑战页标题是 "Just a moment..." / "Attention required"。
         它通常自己就能过（不需要人），所以给它几秒钟；过不去就如实报空。 */
      for (let i = 0; i < 12; i++) {
        const t = await page.title().catch(() => "");
        if (t && !/just a moment|attention required|checking your browser/i.test(t)) break;
        await page.waitForTimeout(1000);
      }
      const og = await page.evaluate(() => {
        const meta = (sel, attr) => {
          const el = document.querySelector(sel);
          return el ? (el.getAttribute(attr || "content") || "").trim() : "";
        };
        const img =
          meta('meta[property="og:image"]') ||
          meta('meta[property="og:image:url"]') ||
          meta('meta[name="twitter:image"]') ||
          meta('link[rel="image_src"]', "href") ||
          "";
        const cat =
          meta('meta[property="article:section"]') ||
          meta('meta[name="section"]') ||
          "";
        return { image: img, category: cat };
      });
      console.log(JSON.stringify({
        url: URL_, status: resp ? resp.status() : 0,
        pageTitle: await page.title().catch(() => ""),
        consent: consent || "", og,
      }));
      return;                                   // 只要 og，不抽列表
    }
    const items = await page.evaluate(extract, { selector: SELECTOR, limit: LIMIT, domain: DOMAIN });
    const pageTitle = await page.title().catch(() => "");
    const status = resp ? resp.status() : 0;
    console.log(JSON.stringify({ url: URL_, status, pageTitle, consent: consent || "", items }));
    if (!items.length) {
      console.error(
        `no items extracted (status=${status}, title=${pageTitle}, consent=${consent || "none"}) — 需校准选择器或页面结构变了`
      );
      process.exit(3);
    }
  } finally {
    await ctx.close();
  }
})().catch((e) => {
  console.error(String((e && e.message) || e));
  process.exit(1);
});
