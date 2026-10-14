"""每日热点页 —— 一张可托到边缘（静态托管）的 HTML 简报。

为什么要有它：每天把前 N 条推给使用者，链接必须**随时打得开**；而自建服务往往跑在
本机或内网后面（不开机就不通）。所以把每日简报渲染成静态 HTML、写进边缘 KV，
由边缘直接返回 —— 不依赖任何自有服务在线。

同时提供 `as_json()`：同一批条目的机读版，供界面侧（看板 / 面板）fetch 使用
（HTML 给人看，JSON 给界面用，两边数据同源）。

三条纪律写在这里：
  · **正文一律英文** —— 这一页可能被公开访问，只允许 EN / ES。
  · **无敏感语境** —— 只有公开新闻的标题 / 摘要 / 链接。
  · **私有入口不写死** —— 本文件只留 `<!--CONSOLE_ENTRY-->` 占位，由托管方按需注入
    （默认留空，不影响页面渲染）。

不联网：只读 out/ 里已抓好的 jsonl。
"""
import datetime as dt
import html as html_mod
import json
import pathlib
from zoneinfo import ZoneInfo

TOP_N = 10               # 「前 N 条」场合用（Lark 卡片）
PER_SITE_N = 0           # 页面 / JSON：每个来源列几条；**0 = 不限**（各平台穷举）
PLACEHOLDER = "<!--CONSOLE_ENTRY-->"

# 页面分区（按分析结果归类）：key → 标题 / 一句话说明
SECTIONS = (
    ("hot", "Hot topics", "Regulation, rulings, M&A, market moves — the ones worth acting on."),
    ("positive", "Positive", "Reads as favourable for operators / affiliates."),
    ("negative", "Negative", "Reads as a headwind."),
    ("mixed", "Other", "Product, people and everything else."),
)

STYLE = """
:root{--fg:#14171c;--muted:#5f6a77;--line:#e4e8ed;--soft:#f4f6f8;--card:#fff;--link:#0b62c4;
--brand:#0f1b2d;--hot:#e8842c;--pos:#2f9e5e;--neg:#d1495b}
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--fg);background:var(--soft)}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
.topbar{background:var(--brand);color:#fff}
.topbar .wrap{display:flex;align-items:baseline;gap:12px;padding:15px 20px}
.brand{font-size:20px;font-weight:700;letter-spacing:-.2px}
.date{color:#9fb0c6;font-size:13px}
.arch{margin-left:auto;font-size:13px}
.arch a{color:#cdd9e8;text-decoration:none}
.arch a:hover{text-decoration:underline}
.tabs{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:9}
.tabs .wrap{display:flex;gap:2px;overflow-x:auto;padding:0 20px}
.tab{border:0;background:none;font:inherit;font-weight:600;color:var(--muted);padding:13px 15px;cursor:pointer;
border-bottom:2px solid transparent;white-space:nowrap}
.tab:hover{color:var(--fg)}
.tab.is-on{color:var(--brand);border-bottom-color:var(--brand)}
.tab .n{color:#98a2b3;font-weight:500;margin-left:5px}
main{padding:22px 20px 64px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
article{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--line);
border-radius:10px;padding:14px 16px}
article.hot{border-left-color:var(--hot)}
article.positive{border-left-color:var(--pos)}
article.negative{border-left-color:var(--neg)}
article h3{margin:0;font-size:16px;line-height:1.35}
article h3 a{color:var(--link);text-decoration:none}
article h3 a:hover{text-decoration:underline}
.meta{margin:6px 0 0;color:var(--muted);font-size:12px}
.why{margin:9px 0 0;color:#1d3f6e;font-size:13.5px}
.sum{margin:9px 0 0;color:#3c4653;font-size:13.5px}
.sec{margin:0 0 14px;color:var(--muted);font-size:13px}
.sec b{color:var(--fg)}
.th{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 12px}
.th b{font-size:12.5px;letter-spacing:.5px;text-transform:uppercase;color:var(--muted)}
.th p{margin:6px 0 0;font-size:14.5px;color:#2c333c}
footer{color:var(--muted);font-size:12.5px;padding:0 20px 40px}
footer .wrap{border-top:1px solid var(--line);padding-top:14px}
@media (max-width:560px){.brand{font-size:18px}.tab{padding:12px 11px;font-size:14px}}
"""

# tab 切换：纯前端，无依赖。支持 `#hot` 这种深链接，刷新后仍停在同一个 tab。
SCRIPT = """
(function(){
  var tabs=[].slice.call(document.querySelectorAll('.tab')),
      panels=[].slice.call(document.querySelectorAll('.panel'));
  function pick(id,push){
    tabs.forEach(function(t){t.classList.toggle('is-on',t.dataset.t===id);});
    panels.forEach(function(p){p.hidden=(p.id!=='p-'+id);});
    if(push&&location.hash!=='#'+id){try{history.replaceState(null,'','#'+id);}catch(e){}}
  }
  tabs.forEach(function(t){t.onclick=function(){pick(t.dataset.t,true);window.scrollTo(0,0);};});
  var want=(location.hash||'').replace('#','');
  if(want&&document.getElementById('p-'+want)) pick(want,false);
})();
"""


def _plain(value):
    """多轮解实体：有些源双重编码（`&amp;#39;`），只解一次会把字面量留给读者。"""
    text = str(value or "")
    for _ in range(3):
        unescaped = html_mod.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


def load_latest(outdir, date=None):
    """读 out/<date>-*news.jsonl（每站取最新一轮）→ [{platform, method, items}]。"""
    date = date or dt.date.today().isoformat()
    latest = {}
    for path in sorted(pathlib.Path(outdir).glob(f"{date}-*news.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            platform = rec.get("platform")
            if platform:
                latest[platform] = rec        # jsonl 是追加的 → 后写的是最新一轮
    return list(latest.values())


# 页面/JSON 上的日期一律**中国时间**（读的人在中国）：欧美站的稿子换算过来常常已跨日
# —— 例如 sbcnews 的 12 Oct 15:09 UTC → 中国 12 Oct 23:09（同日），
#    而 yogonet 的 12 Oct 20:00 -03:00 → 中国 13 Oct 07:00（跨日）。
CN_TZ = ZoneInfo("Asia/Shanghai")


def _cn_date(ts, fallback=""):
    """条目的发布时刻（带时区的 ts）→ 中国日期 'dd Mon YYYY'；换算不了就退回原文日期。"""
    if not ts:
        return fallback
    try:
        moment = dt.datetime.fromisoformat(str(ts))
    except Exception:  # noqa: BLE001  —— 抓取端的 ts 格式不可控，解不动就用原文
        return fallback
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(CN_TZ).strftime("%d %b %Y")


def _all_items(pages):
    """跨站摊平：带 ts 的按时间倒序排前面，没 ts 的维持原相对顺序跟在后面。"""
    dated, undated = [], []
    for page in pages:
        for pos, item in enumerate(page.get("items", [])):
            metrics = item.get("metrics") or {}
            row = {
                "title": _plain(item.get("title")),
                "url": item.get("url") or "",
                "time": metrics.get("time") or "",
                "ts": metrics.get("ts") or "",
                "summary": _plain(metrics.get("summary")),
                "site": metrics.get("site") or page.get("platform") or "",
                "site_key": page.get("platform") or "",
                "pos": pos,
            }
            # 显示用的日期：来源站发布时刻 → 中国日期（没有 ts 的站点退回原文日期）
            row["date_cn"] = _cn_date(row["ts"], row["time"])
            (dated if row["ts"] else undated).append(row)
    dated.sort(key=lambda r: r["ts"], reverse=True)
    return dated + undated


def collect(pages, per_site=PER_SITE_N):
    """**按来源汇总**：每个站取站内前 `per_site` 条，站与站顺序拼接（站内新→旧）。

    2026-10-12：页面从「各站摊平后全局取前 10 条」改成「按来源分区列出」——
    原先的取法实测 10 条里 9 条来自同一个站（那个站的 feed 时间戳整体最新，把前 N 名包圆），
    而走 sitemap、没有 ts 的站永远一条也进不来。四个平台的资讯都该露面。
    """
    out = []
    for page in pages:
        rows = _all_items([page])
        out.extend(rows[:per_site] if per_site and per_site > 0 else rows)
    return out


def pick_items(pages, top_n=TOP_N):
    """跨站**轮流取** `top_n` 条（站内仍新→旧）—— 给「必须短」的场合（Lark 卡片）用。

    与 `collect()` 的区别：那个是"每站都列出来"（页面/JSON），这个是"总数固定、尽量多元"。
    """
    groups = [g for g in (_all_items([p]) for p in pages) if g]
    out = []
    round_no = 0
    while len(out) < top_n and any(len(g) > round_no for g in groups):
        for group in groups:
            if len(out) >= top_n:
                break
            if len(group) > round_no:
                out.append(group[round_no])
        round_no += 1
    return out


def as_json(pages, date=None, per_site=PER_SITE_N, analysis=None):
    """同一批条目的机读版（界面侧 fetch 用，与页面**同源同序**）。

    `analysis` 有值时附带 sentiment / kind / why；条目数对不上就忽略（宁缺毋错位）。
    """
    date = date or dt.date.today().isoformat()
    rows = collect(pages, per_site)
    if analysis and len(analysis.get("items") or []) == len(rows):
        for row, item in zip(rows, analysis["items"]):
            row["sentiment"] = item.get("sentiment") or "mixed"
            row["kind"] = item.get("kind") or "routine"
            row["why"] = item.get("why") or ""
    return {
        "date": date,
        "themes": (analysis or {}).get("themes") or [],
        "items": [
            {"rank": idx, "title": row["title"], "url": row["url"],
             "summary": row["summary"], "site": row["site"], "time": row["time"],
             "date_cn": row.get("date_cn", ""),
             "sentiment": row.get("sentiment", ""), "kind": row.get("kind", ""),
             "why": row.get("why", "")}
            for idx, row in enumerate(rows, 1)
        ],
    }


def _card(row, idx, esc):
    """一条新闻 → 一张卡片：标题 / 来源·时间 / 一句分析 / 原始摘要。

    左侧色条按归类上色（hot 橙 / positive 绿 / negative 红）—— 热点区里也能一眼看出正负。
    """
    title = esc(row["title"])
    if row["url"]:
        head = f'<a href="{esc(row["url"])}" target="_blank" rel="noopener nofollow">{title}</a>'
    else:
        head = title
    meta = " · ".join(esc(x) for x in (row["site"], row.get("date_cn") or row["time"]) if x)
    why = f'<p class="why">{esc(row["why"])}</p>' if row.get("why") else ""
    summary = f'<p class="sum">{esc(row["summary"])}</p>' if row["summary"] else ""
    cls = "hot" if row.get("kind") == "hot" else (row.get("sentiment") or "")
    # id = 全局序号：推送里可以直接 `#3` 定位到第 3 条
    return ('<article id="%d" class="%s"><h3>%s</h3><p class="meta">%s</p>%s%s</article>'
            % (idx, cls, head, meta, why, summary))


def render(pages, date=None, per_site=PER_SITE_N, site_name="iGaming Daily", analysis=None):
    """生成页面 HTML（英文）。**横向 tab 切换分类**：Overview / Hot topics / Positive / Negative / Other。

    `analysis` = `analyze.analyze()` 的结果（每条 sentiment/kind/why + themes）。
    缺失、或条目数对不上 → 退化成不带分类的完整列表（**宁可没有分类，也不允许错位**）。
    `<!--CONSOLE_ENTRY-->` 留给托管方按需注入。
    """
    date = date or dt.date.today().isoformat()
    try:
        pretty = dt.date.fromisoformat(date).strftime("%d %b %Y")
    except Exception:
        pretty = date
    esc = lambda value: html_mod.escape(_plain(value))          # noqa: E731

    rows = collect(pages, per_site)
    if analysis and len(analysis.get("items") or []) == len(rows):
        for row, item in zip(rows, analysis["items"]):
            row["sentiment"] = item.get("sentiment") or "mixed"
            row["kind"] = item.get("kind") or "routine"
            row["why"] = item.get("why") or ""

    buckets = {key: [] for key, _, _ in SECTIONS}
    for row in rows:
        key = "hot" if row.get("kind") == "hot" else (row.get("sentiment") or "mixed")
        buckets.setdefault(key, buckets["mixed"]).append(row)

    sources = ", ".join(sorted({r["site"] for r in rows if r["site"]}))

    # Overview（主题解读）作为第一个 tab
    themes = (analysis or {}).get("themes") or []
    if themes:
        overview = "".join('<div class="th"><b>%s</b><p>%s</p></div>'
                           % (esc(t.get("name")), esc(t.get("summary"))) for t in themes)
    else:
        overview = '<div class="th"><b>Sources</b><p>%s</p></div>' % esc(sources)
    tabs = ['<button class="tab is-on" data-t="overview">Overview</button>']
    panels = ['<section id="p-overview" class="panel">\n%s\n</section>' % overview]

    idx = 0
    for key, heading, blurb in SECTIONS:
        group = buckets.get(key) or []
        tabs.append('<button class="tab" data-t="%s">%s<span class="n">%d</span></button>'
                    % (key, esc(heading), len(group)))
        cards = []
        for row in group:
            idx += 1
            cards.append(_card(row, idx, esc))
        grid = "\n".join(cards) if cards else '<p class="sec">Nothing in this bucket today.</p>'
        panels.append(
            '<section id="p-%s" class="panel" hidden>\n'
            '<p class="sec"><b>%s</b> — %s · %d items · %s</p>\n<div class="grid">\n%s\n</div>\n</section>'
            % (key, esc(heading), esc(blurb), len(group), esc(sources), grid)
        )

    if not rows:
        panels.append('<section class="panel"><p>No headlines for this date.</p></section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(site_name)} — {esc(pretty)}</title>
<meta name="description" content="Daily iGaming industry headlines from public trade feeds.">
<meta name="robots" content="index,follow">
<style>{STYLE}</style>
</head>
<body>
<div class="topbar"><div class="wrap">
<span class="brand">{esc(site_name)}</span>
<span class="date">{esc(pretty)}</span>
<span class="arch"><a href="/d/{esc(date)}">this day's page</a></span>
</div></div>
<nav class="tabs"><div class="wrap">{"".join(tabs)}</div></nav>
<main class="wrap">
{chr(10).join(panels)}
{PLACEHOLDER}
</main>
<footer><div class="wrap">
<p>Aggregated from publicly available industry news feeds. Links open the original publishers.</p>
</div></footer>
<script>{SCRIPT}</script>
</body>
</html>
"""
