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

TOP_N = 10
PLACEHOLDER = "<!--CONSOLE_ENTRY-->"

STYLE = """
:root{--fg:#15181d;--muted:#5c6673;--line:#e3e6ea;--bg:#f7f8fa;--card:#fff;--link:#14538c}
*{box-sizing:border-box}
body{margin:0;font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--fg);background:var(--bg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:28px 20px}
.wrap{max-width:760px;margin:0 auto}
h1{margin:0;font-size:26px;letter-spacing:-.2px}
.sub{margin:6px 0 0;color:var(--muted);font-size:14px}
main{padding:24px 20px 8px}
article{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 12px}
article h2{margin:0;font-size:17px;line-height:1.4}
article h2 a{color:var(--link);text-decoration:none}
article h2 a:hover{text-decoration:underline}
.meta{margin:6px 0 0;color:var(--muted);font-size:12.5px}
.sum{margin:8px 0 0;color:#39414c;font-size:14.5px}
footer{padding:8px 20px 40px;color:var(--muted);font-size:12.5px}
footer .wrap{border-top:1px solid var(--line);padding-top:14px}
.arch{margin:0 0 18px;font-size:13.5px;color:var(--muted)}
.arch a{color:var(--link)}
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
            (dated if row["ts"] else undated).append(row)
    dated.sort(key=lambda r: r["ts"], reverse=True)
    return dated + undated


def as_json(pages, date=None, top_n=TOP_N):
    """同一批条目的机读版（界面侧 fetch 用，与页面数据同源）。"""
    date = date or dt.date.today().isoformat()
    return {
        "date": date,
        "items": [
            {"rank": idx, "title": row["title"], "url": row["url"],
             "summary": row["summary"], "site": row["site"], "time": row["time"]}
            for idx, row in enumerate(_all_items(pages)[:top_n], 1)
        ],
    }


def render(pages, date=None, top_n=TOP_N, site_name="iGaming Daily"):
    """生成页面 HTML（英文）。`<!--CONSOLE_ENTRY-->` 留给托管方按需注入。"""
    date = date or dt.date.today().isoformat()
    try:
        pretty = dt.date.fromisoformat(date).strftime("%d %b %Y")
    except Exception:
        pretty = date
    items = _all_items(pages)[:top_n]
    esc = lambda value: html_mod.escape(_plain(value))          # noqa: E731

    blocks = []
    for idx, row in enumerate(items, 1):
        title = esc(row["title"])
        if row["url"]:
            head = f'<a href="{esc(row["url"])}" target="_blank" rel="noopener nofollow">{title}</a>'
        else:
            head = title
        meta_bits = [esc(row["site"])]
        if row["time"]:
            meta_bits.append(esc(row["time"]))
        summary = f'<p class="sum">{esc(row["summary"])}</p>' if row["summary"] else ""
        # id = 序号：推送里可以直接 `#3` 定位到第 3 条
        blocks.append(
            '<article id="%d"><h2>%s</h2><p class="meta">%s</p>%s</article>'
            % (idx, head, " · ".join(meta_bits), summary)
        )

    body = "\n".join(blocks) or "<p>No headlines for this date.</p>"
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
<header><div class="wrap">
<h1>{esc(site_name)}</h1>
<p class="sub">Industry headlines · {esc(pretty)}</p>
</div></header>
<main><div class="wrap">
<p class="arch">Also available: <a href="/d/{esc(date)}">this day's page</a></p>
{body}
{PLACEHOLDER}
</div></main>
<footer><div class="wrap">
<p>Aggregated from publicly available industry news feeds. Links open the original publishers.</p>
</div></footer>
</body>
</html>
"""
