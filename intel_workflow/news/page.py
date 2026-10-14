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
import collections
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
:root{--fg:#14171c;--muted:#5f6a77;--dim:#8b94a1;--line:#e4e8ed;--hair:#eef1f4;
--soft:#fafafa;--bar:#f4f5f6;--card:#fff;--link:#0b62c4;--or:#e8842c;--or-soft:#fdf1e3;
--pos:#2f9e5e;--neg:#d1495b}
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--fg);background:#fff}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}

/* ① utility bar */
.ubar{background:var(--bar);border-bottom:1px solid #e6e9e7}
.ubar .wrap{display:flex;align-items:center;gap:14px;padding:9px 20px;min-height:38px}
.srcs{display:flex;gap:15px;flex:1;overflow-x:auto;scrollbar-width:none}
.srcs::-webkit-scrollbar{display:none}
.srcs a{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
text-decoration:none;white-space:nowrap;font-weight:600;cursor:pointer}
.srcs a:hover{color:var(--fg)}
.srcs a.on{color:var(--or)}
.ubar .arch{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
text-decoration:none;white-space:nowrap}
.ubar .arch:hover{color:var(--fg)}
.pill{border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 12px;
font-size:11.5px;font-weight:700;letter-spacing:.04em;white-space:nowrap}

/* ② masthead */
.mast .wrap{display:flex;align-items:center;gap:26px;padding:16px 20px}
.wordmark{font-size:23px;font-weight:800;letter-spacing:-.4px;color:var(--fg);
text-decoration:none;white-space:nowrap}
.wordmark span{color:var(--or)}
.mainnav{display:flex;gap:20px;flex:1;overflow-x:auto;scrollbar-width:none}
.mainnav::-webkit-scrollbar{display:none}
.mainnav a{font-size:12.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
color:var(--fg);text-decoration:none;white-space:nowrap}
.mainnav a:hover{color:var(--or)}
.cta{background:var(--or);color:#fff;border-radius:999px;padding:9px 16px;font-size:12.5px;
font-weight:700;letter-spacing:.04em;text-transform:uppercase;text-decoration:none;white-space:nowrap}

/* ③ sector bar */
.sectors{border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.sectors .wrap{display:flex;gap:22px;padding:13px 20px;overflow-x:auto;scrollbar-width:none}
.sectors::-webkit-scrollbar{display:none}
.sectors a{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
color:var(--muted);text-decoration:none;white-space:nowrap;cursor:pointer}
.sectors a:hover{color:var(--fg)}
.sectors a.more{color:var(--or)}

/* ④ main：左 2/3 主列 + 右 1/3 侧栏 */
main{padding:24px 20px 60px}
.cols{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:26px}
.live-pill{display:inline-flex;align-items:center;gap:7px;background:var(--or-soft);color:var(--or);
border-radius:999px;padding:6px 13px;font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase}
.live-pill i{width:7px;height:7px;border-radius:50%;background:var(--or);display:inline-block;
animation:blip 2s ease-in-out infinite}
@keyframes blip{0%,100%{opacity:1}50%{opacity:.2}}
.lead{display:block;margin:14px 0 26px;text-decoration:none;color:inherit}
.lead img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;display:block;background:var(--hair)}
.kicker{display:block;margin:12px 0 6px;font-size:11px;font-weight:700;letter-spacing:.07em;
text-transform:uppercase;color:var(--or)}
.lead h2{margin:0;font-size:32px;line-height:1.15;font-weight:800;letter-spacing:-.6px}
.lead p{margin:10px 0 0;font-size:15px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}
article{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--line);
border-radius:10px;padding:0 16px 15px;overflow:hidden}
article.plain{padding-top:14px}
article.hot{border-left-color:var(--or)}
article.positive{border-left-color:var(--pos)}
article.negative{border-left-color:var(--neg)}
article .thumb{display:block;margin:0 -16px 12px;width:calc(100% + 32px);aspect-ratio:16/9;
object-fit:cover;background:var(--hair)}
article h3{margin:0;font-size:17px;line-height:1.35;font-weight:700;letter-spacing:-.2px}
article h3 a{color:var(--fg);text-decoration:none}
article h3 a:hover{color:var(--link)}
.tag{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--or)}
.meta{margin:9px 0 0;color:var(--dim);font-size:12px}
.why{margin:9px 0 0;color:#1d3f6e;font-size:13.5px}
.sum{margin:9px 0 0;color:#3c4653;font-size:13.5px;display:-webkit-box;
-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

/* 侧栏 */
.side{display:flex;flex-direction:column;gap:16px}
.topic{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:16px}
.topic-h{display:flex;align-items:center;gap:10px;margin:0 0 10px}
.topic-h b{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.topic-h .more{margin-left:auto;font-size:12px;color:var(--link);text-decoration:none;font-weight:600}
.topic ul{list-style:none;margin:0;padding:0}
.topic li{padding:11px 0;border-top:1px solid var(--hair);display:flex;gap:11px;align-items:flex-start}
.topic li:first-child{border-top:0;padding-top:2px}
.topic img{width:56px;height:42px;border-radius:6px;object-fit:cover;flex:none;background:var(--hair)}
.topic .t{font-size:15px;line-height:1.3;font-weight:700;color:var(--fg);text-decoration:none;display:block}
.topic .t:hover{color:var(--link)}
.topic .d{display:block;margin-top:3px;font-size:12px;color:var(--dim)}
.topic .withimg{min-width:0}
.th{margin:0 0 10px}
.th b{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.th p{margin:5px 0 0;font-size:13.5px;color:#2c333c}

/* ⑤ 分区段 */
.bysec{margin:34px 0 0;padding-top:24px;border-top:1px solid var(--line)}
.sec-h{display:flex;align-items:baseline;gap:12px;margin:0 0 14px}
.sec-h em{font-style:normal;font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--or)}
.sec-h h2{margin:0;font-size:20px;font-weight:800;letter-spacing:-.3px}
.sec-h .more{margin-left:auto;font-size:12.5px;color:var(--or);text-decoration:none;font-weight:700}
.srow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px}
.slist{list-style:none;margin:0;padding:0}
.slist li{padding:10px 0;border-top:1px solid var(--hair);display:flex;gap:10px;align-items:baseline}
.slist li:first-child{border-top:0;padding-top:0}
.slist a{font-size:15px;line-height:1.35;font-weight:600;color:var(--fg);text-decoration:none}
.slist a:hover{color:var(--link)}
.slist .d{font-size:12px;color:var(--dim);white-space:nowrap;margin-left:auto}

footer{color:var(--dim);font-size:12.5px;padding:0 20px 40px}
footer .wrap{border-top:1px solid var(--line);padding-top:14px}
@media (max-width:820px){.cols,.srow{grid-template-columns:1fr}.mast .wrap{gap:14px}
.lead h2{font-size:26px}}

/* ══ 2026-10-14 评审优化 ══════════════════════════════════════════
   来源：claude 的建议（① sticky 右列 ② 头条→3 精选→长尾列表 的层级
   ③ 头条文字叠到图上省首屏 ④ 无图做成一种样式 ⑤ 色条改小胶囊）。 */

/* ① 右列贴着滚动：左列再长，右下也不会留大片空白（零新增内容） */
.side{position:sticky;top:84px}

/* ② 层级：头条 → 3 张精选（图+why+摘要都留）→ 长尾紧凑列表（只留 why） */
.featured-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin:26px 0 30px}
.feed-label{margin:0 0 2px;padding-top:22px;border-top:1px solid var(--line);font-size:11px;font-weight:700;
letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.feed-list{list-style:none;margin:0;padding:0}
.feed-row{display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:14px;align-items:center;
padding:14px 0;border-bottom:1px solid var(--hair)}
.feed-row img{width:96px;height:64px;border-radius:8px;object-fit:cover;object-position:50% 35%;background:var(--bar)}
.feed-row .noimg{width:96px;height:64px;border-radius:8px;display:flex;align-items:center;justify-content:center;
padding:4px;overflow:hidden;text-align:center;font-size:9.5px;font-weight:800;letter-spacing:.5px;
text-transform:uppercase;color:var(--or);background:linear-gradient(135deg,#fdece0,#f4f5f6)}
.feed-row h4{margin:3px 0;font-size:15px;font-weight:700;line-height:1.3}
.feed-row h4 a{color:var(--fg);text-decoration:none}
.feed-row h4 a:hover{color:var(--link)}
.feed-row .why2{margin:0;font-size:13px;color:var(--link);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.feed-row .d{font-size:12px;color:var(--dim);white-space:nowrap}

/* ③ 头条：文字叠在图内（省掉「图高 + 文字高」的叠加），比例放宽到 2:1 */
.hero{display:block;margin:14px 0 0;text-decoration:none;color:inherit}
.hero-media{position:relative;display:flex;align-items:flex-end;aspect-ratio:2/1;border-radius:14px;
overflow:hidden;background:var(--hair)}
.hero-media img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 35%}
.hero-scrim{position:absolute;inset:0;
background:linear-gradient(to top,rgba(0,0,0,.8) 0%,rgba(0,0,0,.18) 55%,rgba(0,0,0,0) 100%)}
.hero-text{position:relative;padding:0 24px 20px}
.hero-cat{font-size:12px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:#ffb877}
.hero-title{display:block;margin:6px 0 0;font-size:30px;line-height:1.15;font-weight:800;letter-spacing:-.5px;color:#fff}
.hero-sum{margin:8px 0 0;font-size:14px;color:rgba(255,255,255,.84);display:-webkit-box;
-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hero-why{margin:12px 0 0;font-size:15px;color:var(--link)}

/* ④ 无图不是 bug，是一种卡片样式：统一渐变 + 分类字样占位 */
.nophoto{display:flex;align-items:center;justify-content:center;aspect-ratio:16/9;border-radius:10px;
margin:0 0 12px;padding:8px;text-align:center;font-size:13px;font-weight:800;letter-spacing:.6px;
text-transform:uppercase;color:var(--or);background:linear-gradient(135deg,#fdece0,#f4f5f6)}

/* ⑤ sentiment：左侧 3px 色条改成小胶囊（有图无图都一致，不再和图片边缘打架） */
article,article.hot,article.positive,article.negative{border-left:1px solid var(--line)}
.chip{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;
font-size:10px;font-weight:700;letter-spacing:.3px;text-transform:uppercase;vertical-align:middle}
.chip-hot{color:var(--or);background:#fdecd9}
.chip-positive{color:var(--pos);background:#eaf7f0}
.chip-negative{color:var(--neg);background:#fdecef}
.chip-row{margin:0 0 8px;display:flex;align-items:center;gap:8px}

@media (max-width:820px){.featured-row{grid-template-columns:1fr}.hero-title{font-size:22px}
.hero-text{padding:0 16px 14px}}
@media (max-width:560px){.feed-row{grid-template-columns:72px minmax(0,1fr)}
.feed-row img,.feed-row .noimg{width:72px;height:48px}}
"""

# tab 切换：纯前端，无依赖。支持 `#hot` 这种深链接，刷新后仍停在同一个 tab。
SCRIPT = """
(function(){
  /* 源过滤：点 utility bar / sector bar 里的站名 → 只看那一家的条目（再点一次取消）。 */
  var links=[].slice.call(document.querySelectorAll('a[data-filter]')), cur='';
  function applyFilter(){
    [].slice.call(document.querySelectorAll('[data-site]')).forEach(function(el){
      el.style.display=(!cur||el.getAttribute('data-site')===cur)?'':'none';
    });
    links.forEach(function(a){a.classList.toggle('on',a.getAttribute('data-filter')===cur);});
  }
  links.forEach(function(a){
    a.onclick=function(){var f=a.getAttribute('data-filter');cur=(cur===f)?'':f;applyFilter();return false;};
  });

  /* 实时区：拉 /live.json（Worker 每 5 分钟抓一轮），把 LIVE 大头条 + 卡片流 + TOP READS
     换成最新条目。拉不到 / 没数据 / 还在加载就保持服务端渲染的内容 —— 绝不留空白。 */
  var LABEL=window.__SITE_LABEL||{}, last='';
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function label(it){return LABEL[it.site_key]||it.site||'';}
  function chip(it){
    var k=it.kind==='hot'?'hot':(it.sentiment||'');
    if(k!=='hot'&&k!=='positive'&&k!=='negative') return '';
    return '<span class="chip chip-'+k+'">'+k.charAt(0).toUpperCase()+k.slice(1)+'</span>';
  }
  function heroHtml(it){
    var img=it.image?'<img src="'+esc(it.image)+'" alt="" referrerpolicy="no-referrer">':'';
    var cat=it.category?'<span class="hero-cat">'+esc(it.category)+'</span>':'';
    var sum=it.summary?'<span class="hero-sum">'+esc(it.summary)+'</span>':'';
    return '<a class="hero" href="'+esc(it.url)+'" target="_blank" rel="noopener nofollow">'
      +'<span class="hero-media">'+img+'<span class="hero-scrim"></span>'
      +'<span class="hero-text">'+cat+'<span class="hero-title">'+esc(it.title)+'</span>'+sum+'</span></span></a>';
  }
  function card(it,i){
    var media=it.image
      ? '<img class="thumb" src="'+esc(it.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
      : '<span class="nophoto">'+esc(it.category||'Headline')+'</span>';
    var tag=(it.image&&it.category)?'<span class="tag">'+esc(it.category)+'</span>':'';   // 无图时分类已在占位块里
    var sum=it.summary?'<p class="sum">'+esc(it.summary)+'</p>':'';
    return '<article id="'+(i+1)+'" data-site="'+esc(it.site_key||'')+'">'+media
      +'<span class="chip-row">'+chip(it)+tag+'</span>'
      +'<h3><a href="'+esc(it.url)+'" target="_blank" rel="noopener nofollow">'+esc(it.title)+'</a></h3>'
      +'<p class="meta">'+esc(it.date_cn||'')+'</p>'+sum+'</article>';
  }
  function feedRow(it){
    var thumb=it.image
      ? '<img src="'+esc(it.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
      : '<span class="noimg">'+esc(it.category||'News')+'</span>';
    var cat=(it.image&&it.category)?'<span class="tag">'+esc(it.category)+'</span>':'';   // 无图时分类已在占位块里
    return '<li class="feed-row" data-site="'+esc(it.site_key||'')+'">'+thumb+'<div>'+cat
      +'<h4><a href="'+esc(it.url)+'" target="_blank" rel="noopener nofollow">'+esc(it.title)+'</a></h4>'
      +'</div><time class="d">'+esc(it.date_cn||'')+'</time></li>';
  }
  function topic(it){
    var img=it.image?'<img src="'+esc(it.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">':'';
    var tag=it.category?'<span class="tag">'+esc(it.category)+'</span>':'';
    return '<li data-site="'+esc(it.site_key||'')+'">'+img+'<div class="withimg">'+tag
      +'<a class="t" href="'+esc(it.url)+'" target="_blank" rel="noopener nofollow">'+esc(it.title)+'</a>'
      +'<span class="d">'+esc(it.date_cn||'')+'</span></div></li>';
  }
  function paint(items){
    var box=document.getElementById('live');
    if(!box) return;
    var head=null, idx=0, i;
    for(i=0;i<items.length;i++){ if(items[i].image){head=items[i];idx=i;break;} }
    if(!head){ head=items[0]; idx=0; }
    var rest=items.slice(0,idx).concat(items.slice(idx+1));
    box.innerHTML='<span class="live-pill"><i></i>Live iGaming News</span>'
      +(head?heroHtml(head):'')
      +'<div class="featured-row">'+rest.slice(0,3).map(card).join('')+'</div>'
      +'<h3 class="feed-label">More headlines</h3>'
      +'<ul class="feed-list">'+rest.slice(3).map(feedRow).join('')+'</ul>';
    var top=document.querySelector('#top ul');
    if(top) top.innerHTML=items.slice(0,4).map(topic).join('');
    applyFilter();
  }
  function pull(){
    fetch('/live.json?t='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.json();})
      .then(function(j){
        if(!j||!j.ok||!j.items||!j.items.length) return;
        if(j.updated_at===last) return;      /* 没变就不重绘 */
        last=j.updated_at;
        paint(j.items);
      })
      .catch(function(){});                  /* 拉不到 → 保持 SSR 内容 */
  }
  pull();
  setInterval(pull, 300000);                 /* 5 分钟一次，与 Worker 的抓取周期对齐 */
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
                "image": metrics.get("image") or item.get("image") or "",
                "category": metrics.get("category") or item.get("category") or "",
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


# 站点短名 → 展示名（utility bar / sector bar / 分区段抬头用）
SITE_LABEL = {
    "igaming": "iGaming.News",
    "igamingbusiness": "iGamingBusiness",
    "sbcnews": "SBC News",
    "yogonet": "Yogonet",
}


def _site_label(row):
    key = row.get("site_key") or ""
    return SITE_LABEL.get(key) or row.get("site") or key


def _hero(row, esc):
    """LIVE 大头条：文字叠在图内（省掉「图高＋文字高」的叠加，首屏不再被图吃掉）。"""
    if not row:
        return ""
    image = row.get("image") or ""
    img = ('<img src="%s" alt="" referrerpolicy="no-referrer">' % esc(image)) if image else ""
    cat = ('<span class="hero-cat">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    summary = ('<span class="hero-sum">%s</span>' % esc(row.get("summary"))) if row.get("summary") else ""
    why = ('<p class="hero-why">%s</p>' % esc(row["why"])) if row.get("why") else ""
    return ('<a class="hero" href="%s" target="_blank" rel="noopener nofollow">'
            '<span class="hero-media">%s<span class="hero-scrim"></span>'
            '<span class="hero-text">%s<span class="hero-title">%s</span>%s</span></span></a>%s'
            % (esc(row["url"]), img, cat, esc(row["title"]), summary, why))


def _topic_item(row, esc):
    """侧栏 TOP READS 的一条：小缩略图 + 分类 + 标题 + 中国日期。"""
    image = row.get("image") or ""
    img = ('<img src="%s" alt="" loading="lazy" referrerpolicy="no-referrer" '
           'onerror="this.remove()">' % esc(image)) if image else ""
    tag = ('<span class="tag">%s</span>' % esc(row.get("category") or _site_label(row))
           if row.get("category") else "")
    return ('<li data-site="%s">%s<div class="withimg">%s'
            '<a class="t" href="%s" target="_blank" rel="noopener nofollow">%s</a>'
            '<span class="d">%s</span></div></li>'
            % (esc(row.get("site_key") or ""), img, tag, esc(row["url"]),
               esc(row["title"]), esc(row.get("date_cn") or row.get("time") or "")))


def _themes_card(themes, esc):
    """侧栏第二张卡：把 GPT 跑出来的主题解读放进新版面（原来占着第一个 tab 位）。"""
    if not themes:
        return ""
    blocks = "".join('<div class="th"><b>%s</b><p>%s</p></div>'
                     % (esc(t.get("name")), esc(t.get("summary"))) for t in themes)
    return ('<section class="topic" id="themes"><div class="topic-h"><b>Today\'s themes</b></div>'
            '%s</section>' % blocks)


def _chip(row):
    """sentiment 小胶囊（替代原来的左侧 3px 色条：有图无图表现一致，不再和图片边缘打架）。"""
    kind = "hot" if row.get("kind") == "hot" else (row.get("sentiment") or "")
    if kind not in ("hot", "positive", "negative"):
        return ""
    label = {"hot": "Hot", "positive": "Positive", "negative": "Negative"}[kind]
    return '<span class="chip chip-%s">%s</span>' % (kind, label)


def _feed_row(row, esc):
    """长尾条目：紧凑一行（缩略图/占位 + 分类 + 标题 + why + 日期），只留 why 不留摘要。"""
    image = row.get("image") or ""
    if image:
        thumb = ('<img src="%s" alt="" loading="lazy" referrerpolicy="no-referrer" '
                 'onerror="this.remove()">' % esc(image))
        cat = ('<span class="tag">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    else:
        # 占位块里已经写了分类名 → 不再重复一个同样的角标
        thumb = '<span class="noimg">%s</span>' % esc(row.get("category") or "News")
        cat = ""
    why = ('<p class="why2">%s</p>' % esc(row["why"])) if row.get("why") else ""
    return ('<li class="feed-row" data-site="%s">%s<div>%s<h4><a href="%s" target="_blank" '
            'rel="noopener nofollow">%s</a></h4>%s</div><time class="d">%s</time></li>'
            % (esc(row.get("site_key") or ""), thumb, cat, esc(row["url"]),
               esc(row["title"]), why, esc(row.get("date_cn") or row.get("time") or "")))


def _card(row, idx, esc):
    """精选卡（头条下面那 3 张）：图或无图占位 → 分类 + sentiment 胶囊 → 标题 → 日期 → why → 摘要。"""
    title = esc(row["title"])
    if row["url"]:
        head = f'<a href="{esc(row["url"])}" target="_blank" rel="noopener nofollow">{title}</a>'
    else:
        head = title
    image = row.get("image") or ""
    if image:
        media = ('<img class="thumb" src="%s" alt="" loading="lazy" referrerpolicy="no-referrer" '
                 'onerror="this.remove()">' % esc(image))
        tag = ('<span class="tag">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    else:
        # 无图不是 bug，是一种卡片样式（统一渐变 + 分类字样），别留空白也别用假图。
        # 分类字样已经在占位里 → 不再另外输出角标，免得分同一个类出现两遍。
        media = '<span class="nophoto">%s</span>' % esc(row.get("category") or "Headline")
        tag = ""
    meta = esc(row.get("date_cn") or row["time"])      # 不标来源：几家平台彻底汇总成一个流
    why = f'<p class="why">{esc(row["why"])}</p>' if row.get("why") else ""
    summary = f'<p class="sum">{esc(row["summary"])}</p>' if row["summary"] else ""
    # id = 全局序号：推送里可以直接 `#3` 定位到第 3 条
    return ('<article id="%d" data-site="%s">%s<span class="chip-row">%s%s</span><h3>%s</h3>'
            '<p class="meta">%s</p>%s%s</article>'
            % (idx, esc(row.get("site_key") or ""), media, _chip(row), tag, head, meta, why, summary))


def render(pages, date=None, per_site=PER_SITE_N, site_name="iGaming Daily", analysis=None):
    """生成页面 HTML（英文）。版面按 igaming.news 首页的语言（规格见 docs/a-face-layout.md）：
    utility bar → masthead → 左 2/3 主列（LIVE 大头条 + 卡片网格）
    / 右 1/3 侧栏（TOP READS + Today's themes）。

    2026-10-14(用户): **几家平台彻底汇总成一个流** —— 不按来源分区、卡片上也不标来源
    （原话「我只看结果」）。因此没有 sector bar，也没有 `LATEST FROM <源>` 段落。

    `analysis` = `analyze.analyze()` 的结果（每条 sentiment/kind/why + themes）：新版面没有 tab，
    它落在卡片左侧色条（hot/positive/negative）、卡片里那行 why、以及侧栏的 themes 卡上。
    缺失、或条目数对不上 → 退化成不带分析的版式（**宁可没有分析，也不允许错位**）。
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

    themes = (analysis or {}).get("themes") or []
    sources = ", ".join(sorted({r["site"] for r in rows if r["site"]}))

    # 排序：先按**中国日期**（同一天的聚在一起），再按精确时间 —— igaming.news 的 sitemap
    # 只给到日期（当天 00:00），若只用 ts 排，它会整批沉到最底下，"彻底汇总"就看不出来了。
    ordered = sorted(rows, key=lambda r: (r.get("date_cn") or "", r.get("ts") or ""), reverse=True)
    lead = next((r for r in ordered if r.get("image")), ordered[0] if ordered else None)
    rest = [r for r in ordered if r is not lead]

    ubar = ('<div class="ubar"><div class="wrap">'
            '<a class="arch" href="/d/%s">This day\'s page</a>'
            '<span class="pill">%s</span></div></div>' % (esc(date), esc(pretty)))

    mast = ('<header class="mast"><div class="wrap">'
            '<a class="wordmark" href="/?news">iGaming<span>Daily</span></a>'
            '<nav class="mainnav"><a href="#live">Latest</a><a href="#top">Top reads</a>'
            '<a href="#themes">Themes</a></nav>'
            '<a class="cta" href="#live">Live feed</a></div></header>')

    # 彻底汇总 + 分层（2026-10-14 评审优化）：头条 → 3 张精选（图/why/摘要都留）
    # → 长尾紧凑列表（只留 why）。页面长度砍掉一大截，右列靠 sticky 跟滚、不再留空白。
    featured = rest[:3]
    featured_html = "".join(_card(r, i + 1, esc) for i, r in enumerate(featured))
    tail_html = "".join(_feed_row(r, esc) for r in rest[3:])
    main_col = ('<div id="live"><span class="live-pill"><i></i>Live iGaming News</span>'
                '%s'
                '<div class="featured-row">%s</div>'
                '<h3 class="feed-label">More headlines</h3>'
                '<ul class="feed-list">%s</ul></div>'
                % (_hero(lead, esc) if lead else "", featured_html, tail_html))

    top = "".join(_topic_item(r, esc) for r in ordered[:4])
    side = ('<aside class="side">'
            '<section class="topic" id="top"><div class="topic-h"><b>Top reads</b>'
            '<a class="more" href="#live">Explore more \u2192</a></div><ul>%s</ul></section>'
            '%s</aside>' % (top, _themes_card(themes, esc)))

    if not rows:
        main_col = ('<div id="live"><span class="live-pill"><i></i>Live iGaming News</span>'
                    '<p class="sec">No headlines for this date.</p></div>')

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
{ubar}
{mast}
<main class="wrap">
<div class="cols">{main_col}{side}</div>
{PLACEHOLDER}
</main>
<footer><div class="wrap">
<p>Aggregated from publicly available industry feeds ({esc(sources)}). Links open the original publishers.</p>
</div></footer>
<script>window.__SITE_LABEL={json.dumps(SITE_LABEL, ensure_ascii=False)};</script>
<script>{SCRIPT}</script>
</body>
</html>
"""
