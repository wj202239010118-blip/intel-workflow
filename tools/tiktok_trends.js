#!/usr/bin/env node
// 读取 TikTok Creative Center **公开展示**的流行趋势页（该页数据由前端渲染，故用浏览器读取）。
// 输出：stdout 一行 JSON -> {"source": ..., "region": ..., "items": [{rank,title,url,metrics}]}
const { chromium } = require("playwright");

const arg = process.argv.find((a) => a.startsWith("--region="));
const REGION = (arg ? arg.split("=")[1] : "US").toUpperCase();
const URL = `https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en?region=${REGION}`;
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

function parseItems(lines) {
  const items = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!/^#[\w.\-]+$/.test(line)) continue;
    // 榜位：紧邻其上的纯数字行
    let rank = null;
    for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
      if (/^\d{1,3}$/.test(lines[j])) { rank = Number(lines[j]); break; }
      if (lines[j].startsWith("#")) break;
    }
    const win = lines.slice(i + 1, i + 14);
    const pi = win.indexOf("Posts");
    const vi = win.indexOf("Views");
    const categories = win
      .filter((w) => /[A-Za-z]/.test(w) && !w.startsWith("#") && !["Posts", "Views", "See analytics", "Trends", "Creator", "Action"].includes(w))
      .slice(0, 2);
    items.push({
      rank: rank || items.length + 1,
      title: line,
      url: `https://www.tiktok.com/tag/${line.slice(1)}`,
      metrics: {
        posts: pi >= 0 ? win[pi - 1] : null,
        views: vi >= 0 ? win[vi - 1] : null,
        category: categories[0] || null,
      },
    });
    if (items.length >= 30) break;
  }
  return items;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const ctx = await browser.newContext({ userAgent: UA, locale: "en-US", viewport: { width: 1366, height: 900 } });
    const page = await ctx.newPage();
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(9000);
    const body = await page.innerText("body").catch(() => "");
    const lines = body.split("\n").map((s) => s.trim()).filter(Boolean);
    const items = parseItems(lines);
    console.log(JSON.stringify({ source: "TikTok Creative Center（浏览器渲染）", region: REGION, items }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(String(e));
  process.exit(1);
});
