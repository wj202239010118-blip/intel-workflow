# intel-workflow

> ⚠️ **Disclaimer** — for lawful personal / educational use only. You are responsible for
> complying with each platform's Terms of Service; the built-in rate limiter is part of the
> design (don't remove it); no credentials are shipped. See [DISCLAIMER.md](DISCLAIMER.md).
>
> **Acceptable use / 用途约束** — **允许**：个人研究、热点发现、由人或其 agent 对**公开可见**数据做单次查询，
> 且保持很低的请求频率。**禁止**：规模化批量采集；对个人建库 / 画像 / 侧写；追踪敏感群体；
> 重识别或关联账号；移除、关闭或绕过限速器；任何骚扰、监控或侵权用途。

给 agent（Claude Code / Codex）装上「社交平台站内一手情报 + 热点监控 + 行业资讯日报」能力：
直接向平台要数据，而不是依赖搜索引擎/模型训练数据里的二手信息。

## 让 AI 直接集成（推荐）

把本仓库链接丢给你的 AI（Claude Code / Codex）：

> 读这个仓库的 AGENTS.md，按它完成安装和集成，最后跑一条腿验证。

仓库根有 `AGENTS.md`（给 AI 的集成与使用说明）和 `CLAUDE.md`（指向 AGENTS.md）；
`agent/` 下是装载件（Claude Code skill、Codex 的 AGENTS 片段）。AI 读完就能自己装。

**装载其实是「两步 + 一次验证」**（详见 [`docs/INSTALL.md`](docs/INSTALL.md) 第三节）：

1. **装工具** —— 让 agent 有「取数的手」：`bash install.sh` 会自动把 skill 装进 `~/.claude/skills/`
2. **装规矩** —— 把它该遵守的行为规范**落成文件**（`~/.claude/skills/<name>/SKILL.md`，或写进项目 `CLAUDE.md` / `AGENTS.md`）。
   只"发到对话里读一次"不算 —— 换个会话就忘了
3. **验证** —— 问它「查今天 X 的热点」：返回**带来源和抓取时间**的真实榜才算成

> 装工具的 AI 会让你批准执行命令，点允许即可；若它回 `blocked on permission`，回一句「允许执行」。

## 手动安装

```bash
git clone <repo> && cd intel-workflow
bash install.sh               # 幂等，可重复跑；结束会把 skill 装到 ~/.claude/skills/
bash install.sh --uninstall   # 卸载已装载的 skill
bash install.sh --install-scheduler   # 额外装「每天自动查行业资讯」的 launchd 任务
```

`install.sh` 依次做：环境探测 → 依赖 → 生成/升级 `config.toml`（含凭据向导，可全部跳过）→ 探测 claude/codex → 冒烟自检 → 装载到 agent。

> 不熟悉命令行？看 [`docs/INSTALL.md`](docs/INSTALL.md) —— 面向非技术同事的逐步教程（含常见报错表）。

## 能做什么

| 命令 | 用途 |
|---|---|
| `./intel hot --platform all --region US` | 各平台热点 / 热榜 |
| `./intel hot --platform x --region indonesia` | 指定地区的 X 趋势 |
| `./intel search --platform youtube --q "<kw>"` | 关键词下钻（YouTube） |
| `./intel verify --platform instagram --handle <@handle>` | 账号核实（Instagram，需自带 cookie） |
| `./intel analyze --platform all --region US` | 取事实 + 双模型交叉复核（结论 / 存疑 / 一致 / 分歧） |
| `./intel news run` | 一组 iGaming 行业站每日检索 → 整合日报（feed/sitemap 纯 HTTP，无需浏览器） |
| `./intel schedule install` | 装 launchd 定时：开机 / 登录跑一次 + 每天固定时刻一次（当天已跑过会跳过） |

## 每日资讯检索（news）

面向「每天把行业新闻汇总推给同事」的场景：默认**纯 HTTP 取数**（feed / sitemap），
一次跑完一组 iGaming 行业站（默认 `igaming.news` / `igamingbusiness.com` / `sbcnews.co.uk` / `yogonet.com`），
合成一份**英文**日报，可选推到 Lark 群 / 邮件。**四个内置站都不需要 node + playwright。**

```bash
./intel news run                        # 抓取 + 整合日报 → out/<日期>-news-digest.md（同时打印）
./intel news push                       # 把最近一份日报推出去（默认 dry-run，只打印不发）
./intel news run --send                 # 真发（配置齐备才生效；发前建议先 dry-run 看过内容）
./intel news run --headless             # 只有浏览器通道的站点才用得到（内置四站都用不到）
./intel schedule install --hour 9 --minute 30   # 开机/登录一次 + 每天 9:30 一次
./intel schedule status                 # 装没装 / 今天跑过没 / 上次成功时间
```

- **取数三条通道，自动选**（前两条完全不碰浏览器）：
  1. `[news.feeds]`（或内置）的 **RSS/Atom** —— 最稳也最轻：一次 GET、几十 KB、无 JS、无 consent 墙、
     不会被当 bot。`sbcnews.co.uk`、`igamingbusiness.com`、`yogonet.com` 走这条。
  2. `[news.sitemaps]`（或内置）的 **XML sitemap** —— 站点没给 feed 时通常还有它，同为纯 HTTP。
     内置的 `igaming.news` 走这条：它没有 RSS（`/feed/`、`/rss.xml` 都 404），但 `/news-sitemap.xml`
     一次 GET 就给全部文章（`loc` + `news:publication_date` + `news:title`）。配 `/sitemap.xml`
     （index）也行 —— 会自动跟到含 `news` 的子 sitemap，跟进时按闸门的最小间隔等待。
  3. 两者都没有才**渲染列表页**（有头 Chromium + 持久 profile，需要 `node + playwright`）；
     抽不准时用 `[news.selectors]` 按域名配「文章链接」的 CSS 选择器校准。
- **登录态复用**：走浏览器通道时用持久 profile（默认 `~/.cache/intel-workflow/browser-profile`）——
  cookie、同意弹窗、（将来某站要登录时的）登录态都留在这份 profile 里，不必每次重建会话。
- **幂等**：当天已经成功跑过就跳过（`--force` 强制重跑）。所以「开机跑一次 + 每天一次」不会变成反复抓。
- **默认不发**：推送默认 dry-run，只把将要发送的内容打印出来；确认后再加 `--send`。
  Lark 自定义机器人发出去的消息**撤不回**，务必先看清楚。
- **外发禁中文**：日报正文是英文，含中文字符会被直接拒发。
- 抓取仍走同一套闸门：同域名两次请求之间有最小间隔（sitemap index 自动跟进时同样等待），
  命中风控即熔断、不重试。
- **不会互相撞**：整轮抓取先拿 profile 文件锁；定时任务与手动跑撞上时，后到的这轮直接跳过
  （幂等，下次跑会补上）—— 而不是两边一起挂。
- **改版会被点名**：某站条目数跌破上次的 40%（且少于 3 条）时，日报顶部出现英文告警行
  （`layout may have changed or access is limited`），不至于悄悄发一份空日报。

## 云腿：让日报在云端每天自己跑（可选）

设备关机也要出日报时，把这条腿放到 **GitHub Actions** —— 仓库自带 `.github/workflows/news-daily.yml`。

- **触发**：每天 `16:00 UTC`（= 中国次日 00:00）由 Cloudflare Worker（kol-ext-gateway 的 Durable Object alarm）调 `workflow_dispatch` 触发；也能在 Actions 页面手动 `Run workflow`（补跑）。**不用** GitHub 自带的 schedule —— 它会延迟/跳过，且与 Worker 入口并存会双发。⚠️ 时刻定在 16:00 是因为四站都是欧美媒体：UTC 01:30（中国 09:30）时伦敦才凌晨 2:30、阿根廷还在前一日，当天稿一条都没发。
- **要装什么**：什么都不用。四站全是纯 HTTP（RSS / sitemap），runner 上**不需要 node、不需要 playwright**。
- **产出**：日报正文直接贴在 **Run 摘要页**（打开 Actions 就能读，不必下载），同时
  `<日期>-news-digest.md` 与 `*.jsonl` 作为 artifact 归档 90 天。
- **默认不推送**：workflow 里的推送步骤是注释掉的。要推到 Lark 群：仓库 Settings → Secrets 加
  `LARK_WEBHOOK`（机器人开了签名再加 `LARK_SECRET`），再把那一步的 `if` 改成 `true` —— 发出去撤不回，先看过内容。
- **可靠性**：GitHub 的 `schedule` 在高峰期可能延迟甚至跳过，仓库连续 60 天无提交活动也会被暂停；
  要准时可以用外部 cron（Cloudflare Worker 之类）调 `workflow_dispatch` 触发。
- **同事怎么用**：fork 本仓库 → 在他自己的 Actions 里跑一次即可（不依赖任何 secret，fork 后开箱可用）。
- **把日报用起来**：`docs/CAMPAIGN-IDEAS.md` 给了「日报 → 蹭热度活动建议」的五步法与可直接复制的 prompt。

## 凭据（全部可选，由使用者自带；仓库不含任何凭据）

| 平台 | 需要什么 | 去哪拿 |
|---|---|---|
| Twitch | 无（公开 GQL 免登录） | — |
| X | 无（第三方公开趋势页，降级源、低置信） | — |
| YouTube | Data API key（免费） | Google Cloud Console → 启用 YouTube Data API v3 |
| Kick | app token（免费） | https://dev.kick.com 建 app |
| TikTok | 无凭据（需 node + playwright 渲染页面） | `npm i playwright && npx playwright install chromium` |
| Instagram | sessionid cookie + 对标账号 ⚠️ **法律风险高于其它平台**（读取的是非公开端点，需自行评估） | 浏览器登录 IG 取 sessionid；`seed_accounts` 配几个对标账号 |
| news（每日资讯） | 无凭据（内置四站走 RSS / sitemap，纯 HTTP） | **不需要** node + playwright（只有自己新加的、既无 feed 也无 sitemap 的站点才需要）；推送另需 `[push.lark]` / `[push.email]` |

缺凭据不会静默失败：命令会直接告诉你缺什么、去哪申请。

## 抓取纪律（写进代码，不建议关）

- 同域名最小请求间隔 + 每日上限 + 命中风控后**持久化冷却**（冷却期内零请求）
- 命中风控立即熔断，**不自动重试**（反复请求只会延长封禁）
- 禁并发、禁批量翻页

## 测试

```bash
python3 -m unittest discover -s tests -v
```

**全部离线**（不发任何网络请求）。覆盖：闸门熔断 / 冷却持久化 / 域名隔离、`404` 不误熔断（回归用例）、
TOML 零依赖解析器与 stdlib 结果一致、X 的 region 归一化、TikTok 的 region 白名单、`digest` 的新进/掉榜/排位对比、
`news` 的站点解析 / 日报整合与英文校验 / 推送默认 dry-run / launchd plist 渲染 / 当天幂等。
CI 在 push 与 PR 时跑（Python 3.9 与 3.12 双版本 + gitleaks 密钥扫描）。

## 文档

- `AGENTS.md` — 给 AI 的集成与使用说明（含纪律）
- `docs/DESIGN.md` — 技术方案（腿矩阵、热点降级链、架构、每日资讯检索、里程碑、探针实测结论）
- `docs/INSTALL.md` — 装载教程（非技术同事向：环境、拿仓库、安装、凭据、每日定时、常见报错）

## 状态

M1–M3：`hot` 已通 YouTube / X / Twitch / TikTok；`analyze` 双模型交叉复核可用（本机实测 claude 引擎）；Kick 待使用者 token；Instagram 待使用者 cookie + 对标账号。
M6（2026-10-11）：`news` 每日资讯检索 + `schedule` launchd 定时落地（有头持久 profile / 英文日报 / 默认 dry-run 推送）；
真实站点的一次校准跑由使用者确认后执行（会弹出有头窗口）。
M7（2026-10-12）：`news` 改为**零浏览器** —— 新增 XML sitemap 通道（`news/sitemap.py`），
内置四站全部走纯 HTTP（`igaming.news` 用 `/news-sitemap.xml`，其余三站用 RSS）；
本机未装 playwright 实测 `4 sources · 55 items`，单测 68 项通过。
M8（2026-10-12 云端）：加 `.github/workflows/news-daily.yml` —— 日报在 GitHub Actions 每天自动跑
（纯 HTTP，runner 上无需 node / playwright）；首轮手动触发即成功（17s，`4 sources · 55 items`），
产出贴 Run 摘要 + artifact 归档 90 天，推送默认关闭。
