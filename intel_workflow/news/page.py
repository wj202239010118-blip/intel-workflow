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
import re
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
/* 2026-10-19(用户)：整页固定在视口内，**左列自己上下滑** ——
   新闻再长也不会把侧栏 Today's themes 下面拖出一长串（那样很丑）。
   移动端(<820px)退回普通整页滚动。 */
.cols{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:26px;
height:calc(100vh - 180px);min-height:520px;align-items:start}
/* 2026-10-19(用户)：头条 + 分类导航**固定**不滚；滚动条只在分类导航下方（#cats）开始 */
.main-col{min-width:0;height:100%;overflow:hidden;display:flex;flex-direction:column}
#live{flex:0 0 auto}
#cats{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;
padding-right:10px;scrollbar-width:thin;scrollbar-color:#cfd6de transparent}
#cats::-webkit-scrollbar{width:8px}
#cats::-webkit-scrollbar-thumb{background:#cfd6de;border-radius:8px}
#cats::-webkit-scrollbar-track{background:transparent}
@keyframes blip{0%,100%{opacity:1}50%{opacity:.2}}
.lead{display:block;margin:14px 0 26px;text-decoration:none;color:inherit}
.lead img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;display:block;background:var(--hair)}
.kicker{display:block;margin:12px 0 6px;font-size:11px;font-weight:700;letter-spacing:.07em;
text-transform:uppercase;color:var(--or)}
.lead h2{margin:0;font-size:32px;line-height:1.15;font-weight:800;letter-spacing:-.6px}
.lead p{margin:10px 0 0;font-size:15px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
/* 2026-10-19(用户选 igaming.news 风): 去卡片容器 —— 无边框/无圆角，只用底部细线分条 */
article{background:transparent;border:0;border-bottom:1px solid var(--line);
border-radius:0;padding:0 0 14px;overflow:visible}
article.plain{padding-top:0}
article.hot{border-left-color:var(--or)}
article.positive{border-left-color:var(--pos)}
article.negative{border-left-color:var(--neg)}
article .thumb{display:block;margin:0 0 12px;width:100%;aspect-ratio:16/9;border-radius:8px;
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
/* 2026-10-19: 侧栏长标题 3 行截断（实测 Austria's… 那种会撑爆卡片） */
.topic .withimg .t{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.topic{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:16px}
.topic-h{display:flex;align-items:center;gap:10px;margin:0 0 10px}
.topic-h b{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.topic-h .more{margin-left:auto;font-size:12px;color:var(--link);text-decoration:none;font-weight:600}
.topic ul{list-style:none;margin:0;padding:0}
.topic li{padding:11px 0;border-top:1px solid var(--hair);display:flex;gap:11px;align-items:flex-start}
.topic li:first-child{border-top:0;padding-top:2px}
.topic img{width:72px;height:54px;border-radius:6px;object-fit:cover;flex:none;background:var(--hair)}
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
/* 2026-10-19(用户)：右侧 Top reads / Today's themes **不要滚动条** —— 内容自然高度，超出就随页面走 */
.side{height:auto;max-height:100%;overflow:visible;position:static}

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
text-transform:uppercase;color:var(--or);background:#f6f7f9}
.feed-row h4{margin:3px 0;font-size:15px;font-weight:700;line-height:1.3}
.feed-row h4 a{color:var(--fg);text-decoration:none}
.feed-row h4 a:hover{color:var(--link)}
.feed-row .why2{margin:0;font-size:13px;color:var(--link);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.feed-row .d{font-size:12px;color:var(--dim);white-space:nowrap}

/* ③ 头条：文字叠在图内（省掉「图高 + 文字高」的叠加），比例放宽到 2:1 */
.hero{display:block;margin:14px 0 0;text-decoration:none;color:inherit}
.hero-media{position:relative;display:flex;align-items:flex-end;aspect-ratio:2/1;border-radius:10px;
overflow:hidden;background:var(--hair)}
.hero-media img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 35%}
.hero-scrim{position:absolute;inset:0;
background:linear-gradient(to top,rgba(0,0,0,.8) 0%,rgba(0,0,0,.18) 55%,rgba(0,0,0,0) 100%)}
.hero-text{position:relative;padding:0 24px 20px}
.hero-cat{font-size:12px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:#ffb877}
.hero-title{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
margin:6px 0 0;font-size:24px;line-height:1.2;font-weight:800;letter-spacing:-.2px;color:#fff}
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

@media (max-width:820px){.cols{display:block;height:auto;min-height:0}
.main-col,.side{height:auto;overflow:visible;padding-right:0}
#cats{overflow:visible;padding-right:0}
.featured-row{grid-template-columns:1fr}.hero-title{font-size:22px}
.hero-text{padding:0 16px 14px}}
@media (max-width:560px){.feed-row{grid-template-columns:72px minmax(0,1fr)}
.feed-row img,.feed-row .noimg{width:72px;height:48px}}

/* ⑥ 轮播（2026-10-14 用户）：把「各家的首页头条」汇总成一块可切换的大图。
   基础用 CSS scroll-snap —— 没有 JS 也能横向滑动；圆点/自动播放由 JS 增强。 */
.hero-carousel{position:relative;margin:14px 0 0}
.hero-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scroll-behavior:smooth;
border-radius:14px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.hero-track::-webkit-scrollbar{display:none}
.hero-slide{flex:0 0 100%;scroll-snap-align:start;display:block;text-decoration:none;color:inherit}
.hero-dots{display:none;gap:7px;justify-content:center;margin:11px 0 0}
.hero-dots button{width:8px;height:8px;padding:0;border:0;border-radius:50%;background:#d7dbe0;
cursor:pointer;transition:width .2s ease,background .2s ease}
.hero-dots button.on{width:22px;border-radius:4px;background:var(--or)}
.hero-dots button:hover{background:#b9bfc7}

/* ⑦ 类别块（聚合平台的核心：同一类消息聚在一起）。段头最左侧的小字改成条数，
   块与块之间用一条细线分隔；块内是「首条图文卡 + 其余紧凑行」。 */
.cats{display:flex;flex-direction:column;gap:32px}
.cat-block{padding-top:22px;border-top:1px solid var(--line)}
.cat-block:first-child{padding-top:0;border-top:0}
.cat-block .sec-h{margin-bottom:12px}
.cat-lead{display:block;margin:0 0 10px;max-width:420px}

/* ⑧ 官方热度榜块：条目带 №N 名次徽标；块本身顶格（它排在最前） */
.rank{display:inline-block;min-width:26px;margin-right:6px;padding:1px 6px;border-radius:6px;
font-size:10.5px;font-weight:800;letter-spacing:.2px;vertical-align:middle;color:#fff;background:var(--or)}

/* ⑨ 分类索引（用户 2026-10-14）：头条下方一排分类按钮，点了跳到对应分类块。
   原生锚点，不依赖 JS；`scroll-margin-top` 让跳过去时不被吸顶的 masthead 盖住。 */
/* 2026-10-19(用户)：分类导航美化 —— 单行横滑 + 竖线分隔 + 数量小胶囊（不换行，省一行高度） */
.catnav{display:flex;flex-wrap:nowrap;gap:0;margin:10px 0 12px;padding:8px 0;
border-top:1px solid var(--line);border-bottom:1px solid var(--line);
overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.catnav::-webkit-scrollbar{display:none}
.catnav a{display:inline-flex;align-items:center;gap:6px;padding:2px 13px;border:0;
border-right:1px solid var(--line);border-radius:0;background:transparent;
font-size:11.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
color:var(--muted);text-decoration:none;white-space:nowrap;transition:color .15s ease}
.catnav a:first-child{padding-left:0}
.catnav a:last-child{border-right:0}
.catnav a:hover{color:var(--fg)}
.catnav a .n{font-size:10px;font-weight:700;color:var(--dim);background:#f1f3f6;
border-radius:20px;padding:1px 7px;margin:0;line-height:1.5;transition:background .15s ease,color .15s ease}
.catnav a:hover .n{background:var(--or);color:#fff}
.catnav a:hover .n{color:var(--or)}
.cat-block{scroll-margin-top:84px}

/* ⑩ 收录页（/?top）：照 igaming.news 的 /top-reads —— 大标题 + 名次卡片列表 */
.page-h{margin:0 0 6px;font-size:34px;line-height:1.15;letter-spacing:-.5px}
.page-sub{margin:0 0 26px;color:var(--dim);font-size:14px}
.toplist{margin:0 0 34px}
.tl{list-style:none;margin:0;padding:0}
.tl-row{display:flex;align-items:flex-start;gap:16px;padding:16px;margin:0 0 10px;
background:#fff;border:1px solid var(--line);border-radius:12px}
.tl-n{flex:0 0 auto;display:flex;align-items:center;justify-content:center;width:44px;height:44px;
border-radius:10px;background:var(--hair);color:var(--fg);font-size:18px;font-weight:800}
.tl-row.hot .tl-n{background:var(--or);color:#fff}
.tl-thumb{flex:0 0 auto;width:112px;height:74px;object-fit:cover;border-radius:8px;background:var(--hair)}
.tl-nophoto{flex:0 0 auto;display:flex;align-items:center;justify-content:center;width:112px;height:74px;
border-radius:8px;background:linear-gradient(135deg,#eef1f4,#e2e7ec);color:#8a94a0;
font-size:10.5px;font-weight:700;letter-spacing:.5px;text-align:center;padding:0 6px}
.tl-body{flex:1 1 auto;min-width:0}
.tl-body h3{margin:4px 0 6px;font-size:17px;line-height:1.35}
.tl-body h3 a{color:var(--fg);text-decoration:none}
.tl-body h3 a:hover{color:var(--or)}
.tl-body time{color:var(--dim);font-size:12.5px}
.mainnav a.on{color:var(--fg);font-weight:700}
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
  function esc(s){
    /* 2026-10-19: 源站 RSS 里带数字实体（M&#038;A / Dafabet&#8217;s），前端重建时原样显示成字面量。
       先把数字实体还原成字符，再统一转义 —— 顺序不能反（先还原再转义才不会二次编码）。 */
    var t=String(s==null?'':s).replace(/&#(\\d+);/g,function(_,n){
      try{return String.fromCodePoint(parseInt(n,10));}catch(e){return _;}
    });
    return t.replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function label(it){return LABEL[it.site_key]||it.site||'';}
  function chip(it){
    var k=it.kind==='hot'?'hot':(it.sentiment||'');
    if(k!=='hot'&&k!=='positive'&&k!=='negative') return '';
    return '<span class="chip chip-'+k+'">'+k.charAt(0).toUpperCase()+k.slice(1)+'</span>';
  }
  /* 类别归一化：与 Python 侧 CATEGORY_RULES 同一套规则、同一顺序（具体 → 宽泛）。
     先用站方给的 category 匹配，没命中再用标题兜底 —— 反过来会让标题里的词盖掉站方分类。 */
  var GROUP_RULES=[
    ['Events',['event','conference','summit','expo','awards','g2e','sigma','ice barcelona','show']],
    ['People',['people','appoint','hire','leadership','women in','interview','chief']],
    ['Regulation & Law',['regulat','law','legal','compliance','legislat','court','policy','ruling','tax']],
    ['Markets & Entry',['market','entry','expansion','licen','oceania','brazil','brasil','africa','asia','latam','mexico','spain','poland','belgium','netherlands','alberta','zealand']],
    ['Affiliate & Marketing',['affiliate','marketing','promo','advert','media','sponsor']],
    ['M&A & Finance',['m&a','merger','acquisition','finance','results','revenue','banking','deal','companies','turnover','ebitda']],
    ['Product & Tech',['product','tech','platform','innovation','payment','software','digital',' ai ','artificial intelligence']],
    ['Betting',['betting','sportsbook','odds','sports']],
    ['Casino & Slots',['casino','slot','poker','land based','bingo','lottery','free-to-play','online gaming']]
  ];
  function _matchGroup(text){
    for(var i=0;i<GROUP_RULES.length;i++){
      var keys=GROUP_RULES[i][1];
      for(var j=0;j<keys.length;j++){ if(text.indexOf(keys[j])>=0) return GROUP_RULES[i][0]; }
    }
    return '';
  }
  function groupOf(it){
    var byCat=_matchGroup((it.category||'').toLowerCase());
    if(byCat) return byCat;
    return _matchGroup((it.title||'').toLowerCase())||'Industry';
  }
  function heroSlide(it){
    var img=it.image?'<img src="'+esc(it.image)+'" alt="" referrerpolicy="no-referrer">':'';
    var cat=it.category?'<span class="hero-cat">'+esc(it.category)+'</span>':'';
    var sum=it.summary?'<span class="hero-sum">'+esc(it.summary)+'</span>':'';
    return '<a class="hero-slide" href="'+esc(it.url)+'" target="_blank" rel="noopener nofollow">'
      +'<span class="hero-media">'+img+'<span class="hero-scrim"></span>'
      +'<span class="hero-text">'+cat+'<span class="hero-title">'+esc(it.title)+'</span>'+sum+'</span></span></a>';
  }
  /* 轮播内容 = 各平台各取最新一条（≈ 各家首页头条） */
  function carouselPick(items){
    var seen={}, picks=[], i;
    for(i=0;i<items.length;i++){ var k=items[i].site_key||''; if(k&&!seen[k]){ seen[k]=1; picks.push(items[i]); } }
    if(picks.length<3){ for(i=0;i<items.length&&picks.length<3;i++){ if(picks.indexOf(items[i])<0) picks.push(items[i]); } }
    return picks.slice(0,4);
  }
  /* 类别名 → 锚点 id；与 Python 侧 _slug 同一套规则（分类索引要跳对 id） */
  function slug(name){ return 'cat-'+String(name||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''); }
  function catSection(name,items){
    return '<section class="cat-block" id="'+slug(name)+'" data-cat="'+esc(name)+'">'
      +'<div class="sec-h"><em>'+items.length+' items</em><h2>'+esc(name)+'</h2></div>'
      +'<ul class="feed-list">'+items.map(feedRow).join('')+'</ul></section>';
  }
  /* 分类索引：头条（轮播）下面一排按钮，点一个跳到对应分类块（原生锚点） */
  function catNav(order,groups){
    if(!order||order.length<2) return '';
    return '<nav class="catnav" aria-label="Sections">'+order.map(function(g){
      return '<a href="#'+slug(g)+'">'+esc(g)+'<span class="n">'+groups[g].length+'</span></a>';
    }).join('')+'</nav>';
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
  /* 轮播交互：**单向循环**（一直向左滑）+ 圆点 + 6 秒自动播放。
     单向的做法：末尾克隆第 1 张，滑到克隆后再无动画跳回真第 1 张 —— 视觉上永远朝同一方向，
     不会出现"到尾巴又倒着滑回去"。n<2 时不显示控件。 */
  function initCarousel(){
    var track=document.querySelector('.hero-track'), dots=document.querySelector('.hero-dots');
    if(!track||!dots) return;
    var old=track.querySelector('[data-loop-clone]');
    if(old) old.remove();                       /* 重建后重复调用时别叠克隆 */
    var n=track.children.length;
    if(n<2) return;
    var clone=track.children[0].cloneNode(true);
    clone.setAttribute('data-loop-clone','1');
    clone.setAttribute('aria-hidden','true');
    track.appendChild(clone);                   /* 末尾多一张 = 第 1 张的替身 */

    dots.style.display='flex';
    dots.innerHTML='';
    var i=0, timer=null, busy=false;
    function cur(){ return Math.round(track.scrollLeft/Math.max(1,track.clientWidth)); }
    function mark(){ var k=i%n; [].forEach.call(dots.children,function(b,j){ b.className=(j===k)?'on':''; }); }
    function restart(){ if(timer) clearInterval(timer); timer=setInterval(step,6000); }
    /* 单向循环的"跳回"必须是瞬时的。坑：CSS 里 .hero-track 是 scroll-behavior:smooth，
       而 scrollTo({behavior:'auto'}) 的 auto 意思是「沿用 CSS 的值」→ 会变成右滑回去。
       所以跳回时把 CSS 也临时置为 auto，下一帧再恢复。 */
    function goto(k,smooth){
      if(smooth){ track.scrollTo({left:track.clientWidth*k,behavior:'smooth'}); return; }
      track.style.scrollBehavior='auto';
      track.scrollTo({left:track.clientWidth*k,behavior:'auto'});
      requestAnimationFrame(function(){ track.style.scrollBehavior=''; });
    }
    function step(){                            /* 永远 +1：只朝左走 */
      if(busy) return;
      busy=true;
      var next=i+1;
      goto(next,true);
      setTimeout(function(){                    /* 等滑动动画走完再决定要不要跳回开头 */
        busy=false;
        if(next>=n){ goto(0,false); i=0; }      /* 滑到克隆了 → 无声跳回真第 1 张 */
        else { i=next; }
        mark();
      },620);
    }
    for(var j=0;j<n;j++){ (function(j){
      var b=document.createElement('button');
      b.type='button';
      b.onclick=function(){ busy=false; i=j; goto(j,true); mark(); restart(); };
      dots.appendChild(b);
    })(j); }
    mark();
    track.addEventListener('scroll',function(){
      var k=cur();
      if(k>=n){ i=0; mark(); return; }          /* 手动滑到克隆：按第 1 张高亮 */
      if(k!==i && !busy){ i=k; mark(); }
    });
    restart();
  }
  function paint(items){
    var box=document.getElementById('live');
    if(!box) return;
    var picks=carouselPick(items);
    var car=picks.length
      ? '<div class="hero-carousel"><div class="hero-track">'+picks.map(heroSlide).join('')
        +'</div><span class="hero-dots"></span></div>'
      : '';
    var rest=items.filter(function(x){ return picks.indexOf(x)<0; });
    var groups={}, order=[];
    rest.forEach(function(it){
      var g=groupOf(it);
      if(!groups[g]){ groups[g]=[]; order.push(g); }
      groups[g].push(it);
    });
    /* 类别之间按条数多少排（内容多的类别说明当下更热），与 SSR 一致 */
    order.sort(function(a,b){ return groups[b].length-groups[a].length || a.localeCompare(b); });
    var cats=order.map(function(g){ return catSection(g,groups[g]); }).join('');
    box.innerHTML=car+catNav(order,groups);
    var catsBox=document.getElementById('cats');
    if(catsBox) catsBox.innerHTML=cats;
    var top=document.querySelector('#top ul');
    if(top) top.innerHTML=items.slice(0,4).map(topic).join('');
    applyFilter();
    initCarousel();
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
  /* 服务端已经渲染好轮播 → 先装上圆点/自动播放（这样即使 /live.json 拉不到也能用） */
  initCarousel();
  pull();
  setInterval(pull, 300000);                 /* 5 分钟一次，与 Worker 的抓取周期对齐 */
})();
"""


def _plain(value):
    """多轮解实体：有些源双重/三重编码（`&amp;#39;`、`&amp;amp;#8217;`）。

    2026-10-19 实测：Top reads 里出现 `Austria&#8217;s` 字面量 —— 只解 3 轮不够，
    且解完再 `html.escape` 会把它变成 `&amp;#8217;`（浏览器显示成 `&#8217;`）。
    这里解到稳定为止（上限 6 轮），后面的 escape 才是唯一一次编码。
    """
    text = str(value or "")
    for _ in range(6):
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
                "hot_rank": int(metrics.get("hot_rank") or 0),   # 自家官网热门榜名次（0=不在榜上）
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


# 聚合平台的核心：**同一类消息要聚在一起**（用户 2026-10-14）。可各家的分类词完全不一样
# （BETTING / Sportsbook / Legal & compliance / GAMBLING LAW / OCEANIA…），所以先把它们
# 归一到一组统一类别，再按类别成块展示。
CATEGORY_RULES = (
    ("Events", ("event", "conference", "summit", "expo", "awards", "g2e", "sigma",
                "ice barcelona", "show")),
    ("People", ("people", "appoint", "hire", "leadership", "women in", "interview", "chief")),
    ("Regulation & Law", ("regulat", "law", "legal", "compliance", "legislat", "court",
                          "policy", "ruling", "tax")),
    ("Markets & Entry", ("market", "entry", "expansion", "licen", "oceania", "brazil", "brasil",
                         "africa", "asia", "latam", "mexico", "spain", "poland", "belgium",
                         "netherlands", "alberta", "zealand")),
    ("Affiliate & Marketing", ("affiliate", "marketing", "promo", "advert", "media", "sponsor")),
    ("M&A & Finance", ("m&a", "merger", "acquisition", "finance", "results", "revenue",
                       "banking", "deal", "companies", "turnover", "ebitda")),
    ("Product & Tech", ("product", "tech", "platform", "innovation", "payment", "software",
                        "digital", " ai ", "artificial intelligence")),
    ("Betting", ("betting", "sportsbook", "odds", "sports")),
    ("Casino & Slots", ("casino", "slot", "poker", "land based", "bingo", "lottery",
                        "free-to-play", "online gaming")),
)
FALLBACK_CATEGORY = "Industry"


def _group_of(row):
    """类别归一：**先用来源站自己给的分类**（站方标注最权威），没命中才用标题兜底。

    2026-10-14 修：原先把 category 和 title 拼在一起匹配 → 标题里的词会盖掉站方分类
    （`OCEANIA` 的稿子因为标题有 "licensing" 被塞进 Regulation & Law，`IGAMING EVENTS`
    因为含 "gaming" 被塞进 Casino）。所以拆成两轮匹配，且规则顺序按「具体 → 宽泛」排。
    """
    cat = (row.get("category") or "").lower()
    if cat:
        for name, keys in CATEGORY_RULES:
            for kw in keys:
                if kw in cat:
                    return name
    low = (row.get("title") or "").lower()
    for name, keys in CATEGORY_RULES:
        for kw in keys:
            if kw in low:
                return name
    return FALLBACK_CATEGORY


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


def _hero_slide(row, esc):
    """轮播里的一张（= 原来那张大头条）：文字叠在图内（省首屏高度）。"""
    if not row:
        return ""
    image = row.get("image") or ""
    img = ('<img src="%s" alt="" referrerpolicy="no-referrer">' % esc(image)) if image else ""
    cat = ('<span class="hero-cat">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    summary = ('<span class="hero-sum">%s</span>' % esc(row.get("summary"))) if row.get("summary") else ""
    return ('<a class="hero-slide" href="%s" target="_blank" rel="noopener nofollow">'
            '<span class="hero-media">%s<span class="hero-scrim"></span>'
            '<span class="hero-text">%s<span class="hero-title">%s</span>%s</span></span></a>'
            % (esc(row["url"]), img, cat, esc(row["title"]), summary))


def _carousel_rows(ordered, want=4):
    """轮播内容 = **各平台各取最新一条**（≈ 各家首页的 hero 头条），汇总到同一块轮播里。

    这正是用户要的「同一个级别的新闻聚集到一起」：头条级进轮播，其余进下面的精选/列表。
    平台不够时用最新的补足到 want 张。
    """
    best = {}
    for row in ordered:
        key = row.get("site_key") or ""
        if key and key not in best:
            best[key] = row        # ordered 已按时间倒序 → 每个平台的第一条就是它最新的
    picks = list(best.values())
    if len(picks) < want:
        for row in ordered:
            if row not in picks:
                picks.append(row)
            if len(picks) >= want:
                break
    return picks[:want]


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


def _feed_row(row, esc, badge=""):
    """长尾条目：紧凑一行（缩略图/占位 + [名次徽标] + 分类 + 标题 + why + 日期），只留 why。"""
    image = row.get("image") or ""
    if image:
        thumb = ('<img src="%s" alt="" loading="lazy" referrerpolicy="no-referrer" '
                 'onerror="this.remove()">' % esc(image))
        cat = ('<span class="tag">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    else:
        # 占位块里已经写了分类名 → 不再重复一个同样的角标
        thumb = '<span class="noimg">%s</span>' % esc(row.get("category") or "News")
        cat = ""
    mark = ('<span class="rank">%s</span>' % esc(badge)) if badge else ""
    why = ('<p class="why2">%s</p>' % esc(row["why"])) if row.get("why") else ""
    return ('<li class="feed-row" data-site="%s">%s<div>%s%s<h4><a href="%s" target="_blank" '
            'rel="noopener nofollow">%s</a></h4>%s</div><time class="d">%s</time></li>'
            % (esc(row.get("site_key") or ""), thumb, mark, cat, esc(row["url"]),
               esc(row["title"]), why, esc(row.get("date_cn") or row.get("time") or "")))


def _slug(name):
    """类别名 → 锚点 id（`Casino & Slots` → `cat-casino-slots`）。

    前端 JS 里有一份**同样规则**的实现（分类索引导航要跳到同样的 id 才对得上）。
    """
    return "cat-" + re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _cat_section(name, items, esc):
    """一个类别块：段头（类别名 + 条数）+ 该类的**全部条目（统一紧凑行）**。

    「同一个级别的新闻聚在一起」—— 头条级已经进了上面的轮播，这里就都是同一档，
    所以不再区分大卡/小卡（同一类里混着大小卡，反而像有层级差）。类别内按时间倒序，
    类别之间按条数多少排。块本身带锚点 id，供头条下方的分类索引跳转。
    """
    head = ('<div class="sec-h"><em>%d items</em><h2>%s</h2></div>' % (len(items), esc(name)))
    rows = "".join(_feed_row(r, esc) for r in items)
    return ('<section class="cat-block" id="%s" data-cat="%s">%s'
            '<ul class="feed-list">%s</ul></section>'
            % (_slug(name), esc(name), head, rows))


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

    # 轮播：各平台各取最新一条（≈ 各家首页的 hero 头条）汇总到同一块大图轮播里，
    # 剩下的才进精选卡 / 紧凑列表 —— 就是用户要的「同级别的新闻聚到一起」。
    carousel_rows = _carousel_rows(ordered)
    slides = "".join(_hero_slide(r, esc) for r in carousel_rows)
    carousel = ('<div class="hero-carousel"><div class="hero-track">%s</div>'
                '<span class="hero-dots"></span></div>' % slides) if slides else ""

    used = {id(r) for r in carousel_rows}
    rest_all = [r for r in ordered if id(r) not in used]

    # 按类别成块（聚合平台的核心：同一类消息聚在一起）。类别内保持时间倒序，
    # 类别之间按条数多少排 —— 内容多的类别（说明当下更热）自然靠前。
    # 2026-10-19(用户)：主页**只做最新新闻** —— 移除「Top ranked」榜单块（榜单在 /?top），
    # 所以这里不再按 hot_rank 抽走条目，全部新闻都留在类别流里。
    rest_cats = rest_all

    by_cat = collections.OrderedDict()
    for row in rest_cats:
        by_cat.setdefault(_group_of(row), []).append(row)
    ordered_cats = sorted(by_cat.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    cats_html = "".join(_cat_section(name, items, esc) for name, items in ordered_cats)

    # 分类索引（用户 2026-10-14）：头条（轮播）下面一排按钮，点一个跳到对应分类块。
    # 用原生锚点（href="#cat-xxx"）→ 不依赖 JS；id 走 _slug，和类别块的 id 一致。
    catnav = ""
    if len(ordered_cats) > 1:
        catnav = ('<nav class="catnav" aria-label="Sections">%s</nav>'
                  % "".join('<a href="#%s">%s<span class="n">%d</span></a>'
                            % (_slug(name), esc(name), len(items))
                            for name, items in ordered_cats))

    # 顺序（2026-10-19 用户）：**轮播头条在最上** → 分类索引 → 按类别的最新新闻流。
    # 主页只做新闻（榜单挪去 /?top）；`#live` 与 `#cats` 是实时刷新会重建的两块。
    main_col = ('<div class="main-col">'
                '<div id="live">'
                '%s%s</div>'
                '<div id="cats" class="cats">%s</div></div>'
                % (carousel, catnav, cats_html))

    top = "".join(_topic_item(r, esc) for r in ordered[:4])
    side = ('<aside class="side">'
            '<section class="topic" id="top"><div class="topic-h"><b>Top reads</b>'
            '<a class="more" href="/?top">Explore more \u2192</a></div><ul>%s</ul></section>'
            '%s</aside>' % (top, _themes_card(themes, esc)))

    if not rows:
        main_col = ('<div id="live">'
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


def _top_card(row, idx, esc):
    """收录页的一张名次卡：方块数字徽标 + 缩略图 + 分类 + 标题 + 日期。

    方块数字徽标与「前两名换强调色」是照 igaming.news 的 /top-reads 做的。
    """
    image = row.get("image") or ""
    if image:
        thumb = ('<img class="tl-thumb" src="%s" alt="" loading="lazy" '
                 'referrerpolicy="no-referrer" onerror="this.remove()">' % esc(image))
        cat = ('<span class="tag">%s</span>' % esc(row.get("category"))) if row.get("category") else ""
    else:
        # 无图不是错，是另一种样式（渐变底 + 分类字样）；字样已在占位里，不再重复角标
        thumb = '<span class="tl-nophoto">%s</span>' % esc(row.get("category") or "News")
        cat = ""
    return ('<li class="tl-row%s"><span class="tl-n">%d</span>%s'
            '<div class="tl-body">%s<h3><a href="%s">%s</a></h3><time>%s</time></div></li>'
            % (" hot" if idx <= 2 else "", idx, thumb, cat,
               esc(row.get("url")), esc(row.get("title")), esc(row.get("date_cn") or "")))


def render_top(pages, date=None, per_site=60, site_name="iGaming Daily"):
    """收录页（`/?top`）：把各家官网热门榜上的条目**完整收在一页**。

    骨架照 igaming.news 的 /top-reads：大标题 + 「Most read stories」名次卡片列表
    + 「Latest headlines」列表。与首页的区别：首页侧栏只放榜单前 4 条，这里全收。

    同样**不标来源平台**（用户 2026-10-14「我只看结果」）；`<!--CONSOLE_ENTRY-->`
    占位符照留，由托管方按权限决定要不要注入控制台入口。
    """
    date = date or dt.date.today().isoformat()
    try:
        pretty = dt.date.fromisoformat(date).strftime("%d %b %Y")
    except Exception:
        pretty = date
    esc = lambda value: html_mod.escape(_plain(value))          # noqa: E731

    rows = collect(pages, per_site)
    ordered = sorted(rows, key=lambda r: (r.get("date_cn") or "", r.get("ts") or ""), reverse=True)
    ranked = sorted([r for r in ordered if r.get("hot_rank")], key=lambda r: r["hot_rank"])

    cards = "".join(_top_card(r, i, esc) for i, r in enumerate(ranked, 1))
    most = ('<section class="toplist" id="most-read">'
            '<div class="sec-h"><em>%d from publishers\' boards</em>'
            '<h2>Most read stories</h2></div><ol class="tl">%s</ol></section>'
            % (len(ranked), cards)) if ranked else ""

    latest_rows = ordered[:24]
    latest = ('<section class="toplist" id="latest">'
              '<div class="sec-h"><em>%d items</em><h2>Latest headlines</h2></div>'
              '<ul class="feed-list">%s</ul></section>'
              % (len(latest_rows), "".join(_feed_row(r, esc) for r in latest_rows)))

    ubar = ('<div class="ubar"><div class="wrap">'
            '<a class="arch" href="/?news">\u2190 Today\'s edition</a>'
            '<span class="pill">%s</span></div></div>' % esc(pretty))
    mast = ('<header class="mast"><div class="wrap">'
            '<a class="wordmark" href="/?news">iGaming<span>Daily</span></a>'
            '<nav class="mainnav"><a href="/?news">Latest</a>'
            '<a class="on" href="/?top">Top reads</a>'
            '<a href="/?news#themes">Themes</a></nav>'
            '<a class="cta" href="/?news">Live feed</a></div></header>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top reads — {esc(site_name)}</title>
<meta name="description" content="Most-read iGaming stories of the day, collected from each publisher's own most-read board.">
<meta name="robots" content="index,follow">
<style>{STYLE}</style>
</head>
<body>
{ubar}
{mast}
<main class="wrap">
<h1 class="page-h">Top reads</h1>
<p class="page-sub">Collected from the publishers' own most-read boards — the whole industry on one page.</p>
{most}
{latest}
{PLACEHOLDER}
</main>
<footer><div class="wrap">
<p>Rankings come from each publisher's own most-read board. Links open the original publishers.</p>
</div></footer>
</body>
</html>
"""
