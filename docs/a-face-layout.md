# A 面版式规格（对照 igaming.news）

> 2026-10-14 定。依据：igaming.news 首页实测（结构 snapshot + 截图）+ 四个源的真实 XML 字段统计。
> 目标：A 面（`/?news`）的**展示方式**复刻 igaming.news 的首页语言；数据仍是四家聚合。
> 纪律不变：正文一律英文、无敏感语境、私有入口不写死。

## 0. 数据字段现状（决定降级规则）

| 源 | 图片 | 分类 |
|---|---|---|
| igamingbusiness.com | `media:content` 100/102 | `category` 100/102 |
| www.yogonet.com | `media:content` 20/21 | `category` 20/21 |
| sbcnews.co.uk | 几乎没有（1/11） | `category` 10/11 |
| igaming.news（sitemap） | 无 | 无 |

→ **每张卡都必须支持「无图」「无分类」两种降级**，不能因为缺字段就整条不显示。

## 1. 区块与顺序

```
① utility bar   浅灰细条：大写小字工具链接（左） + 日期胶囊（右）
② masthead      白底：wordmark（左） + 主导航（中/右） + 橙色圆角主按钮（右）
③ sector bar    白底细分隔条：大写分类项平铺
④ main          左 2/3 主列 + 右 1/3 侧栏
   左：LIVE 胶囊 → 大头条 → 卡片网格
   右：TOP READS 卡（列表）
⑤ 分区段        「Latest from <源>」：1 大 + N 小（标题列表 + 日期）
⑥ footer        聚合声明
```

## 2. 各区块规格

### ① utility bar
- 底 `#f4f5f6`，下边线 `1px #e6e9e7`，内边距上下 10px
- 链接：11.5px、**大写**、`letter-spacing .06em`、色 `#5f6a77`；当前项 `#e8842c` 粗体
- 我们放：四个源站名（点击过滤）+ `This day's page`
- 右端：日期胶囊（**中国日期**，如 `15 Oct 2026`），`#fff` 底 + 1px 边 + 圆角 999

### ② masthead
- 白底；wordmark 24px、字重 800、字距 -0.4px：`iGaming` 黑 + `Daily` 橙
- 导航：12.5px、大写、字重 700、`letter-spacing .04em`、色 `#14171c`、hover 变橙
- 右侧主按钮：橙底 `#e8842c`、白字、圆角 999、内边距 9px 16px

### ③ sector bar
- 白底，上下各 1px 线 `#e4e8ed`，内边距上下 13px
- 项：12px 大写 700，`letter-spacing .04em`，色 `#5f6a77`，hover 橙
- 末项 `More →` 用橙色

### ④ main（栅格 `minmax(0,2fr) minmax(0,1fr)`，间隔 26px）

**左列**
- LIVE 胶囊：浅橙底 `#fdf1e3`、橙字 `#e8842c`、11px 大写 700、圆角 999、前缀一个呼吸圆点
- 大头条：图 16:9 圆角 10px + 全宽；分类角标 11px 大写橙；标题 32px/1.15 字重 800 字距 -0.6px；摘要 15px/1.6 `#5f6a77`；`Read article →` 蓝色链接
- 卡片网格：`auto-fill minmax(300px,1fr)`，间隔 20px；每卡 = 图（16:9，圆角 10px）→ 分类角标 → 标题 17px/1.35 字重 700 → 摘要 13.5px `#5f6a77`（2 行截断）→ 底行 12px 灰（来源 · 中国日期）

**右列**
- TOP READS 卡：底 `#fafafa`、1px 边 `#e4e8ed`、圆角 12px、内边距 16px；标题栏 11px 大写 700 `#5f6a77` + 右侧 `Explore more →` 蓝
- 列表项：56×42 圆角 6px 缩略图 + 橙色分类 10.5px 大写 + 标题 15px/1.3 字重 700 + 日期 12px `#8b94a1`；项间 `1px #eef1f4` 分隔

### ⑤ 分区段
- 段头：小字大写橙（`CATEGORISED NEWS` 的位置）+ 20px 粗黑标题 + 右侧 `More →` 橙
- 段体：左 1 张大卡 + 右侧若干「标题 + 日期」细条

### ⑥ footer
- 12.5px `#8b94a1`，聚合声明，勿含内部信息

## 3. 配色 / 字型

```
页面底      #ffffff
浅底/卡底   #fafafa / #f4f5f6
正文        #14171c
次要        #5f6a77
更次要      #8b94a1
分隔线      #e4e8ed / #eef1f4
品牌橙      #e8842c
链接蓝      #0b62c4
正向绿      #2f9e5e      负向红 #d1495b   （现有分析沿用）
字体   -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
标题字重 700-800，字距 -0.2 ~ -0.6px；导航/分类/角标一律大写 + letter-spacing
```

## 4. 现有分析（GPT 跑出来的）如何融进去

igaming.news 首页没有情感分析，但用户要保留。落位：

- **Hot / Positive / Negative**：变成 ③ sector bar 之后的两个「tab 位」之外的**过滤 chip**，
  或主列卡片上的左侧色条（沿用现有 `article.hot/.positive/.negative` 的 3px 左边线）
- **每条一句 `why`**：卡片摘要上方一行（13.5px，色 `#1d3f6e`，沿用现有 `.why`）
- **themes（主题解读）**：放在 ① utility bar 之下、② masthead 之前的 **Overview 条**；
  或作为侧栏 TOP READS 下面第二张卡（`Today's themes`）

→ 实现时选后者（侧栏第二卡 + 卡片色条），对 igaming.news 的版面侵入最小。

## 5. 实时性（与 `/live.json` 的关系）

- 页面 HTML 仍是**每天一版**（KV `daily:index`），保证无 JS 也有内容；
- 顶部左列的 **LIVE 大头条 + TOP READS** 由前端拉 `/live.json` 覆盖/填充，并每 5 分钟自动刷新；
- 拉不到（或没有数据）时保持 SSR 内容，不显示空白。

## 6. 不做的事

- 不复制对方的 logo 图片、`igamingnews` wordmark、`FEATURED ADVERTORIAL` / 订阅表单 / 广告位；
- 不放任何内部入口、内网地址、账号线索（沿用现有的 `<!--CONSOLE_ENTRY-->` 占位机制）。
