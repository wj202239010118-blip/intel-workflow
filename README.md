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
| `./intel news run` | 一组 iGaming 行业站每日检索 → 整合日报（有头浏览器，持久 profile 复用登录态） |
| `./intel schedule install` | 装 launchd 定时：开机 / 登录跑一次 + 每天固定时刻一次（当天已跑过会跳过） |

## 每日资讯检索（news）

面向「每天把行业新闻汇总推给同事」的场景：有头 Chromium + **持久 profile**，
一次跑完一组 iGaming 行业站（默认 `igaming.news` / `igamingbusiness.com` / `sbcnews.co.uk` / `yogonet.com`），
合成一份**英文**日报，可选推到 Lark 群 / 邮件。

```bash
./intel news run                        # 抓取 + 整合日报 → out/<日期>-news-digest.md（同时打印）
./intel news run --headless             # 无头（默认有头；有头更容易拿到渲染后内容）
./intel news push                       # 把最近一份日报推出去（默认 dry-run，只打印不发）
./intel news run --send                 # 真发（配置齐备才生效；发前建议先 dry-run 看过内容）
./intel schedule install --hour 9 --minute 30   # 开机/登录一次 + 每天 9:30 一次
./intel schedule status                 # 装没装 / 今天跑过没 / 上次成功时间
```

- **登录态复用**：浏览器用持久 profile（默认 `~/.cache/intel-workflow/browser-profile`）——
  cookie、同意弹窗、（将来某站要登录时的）登录态都留在这份 profile 里，不必每次重建会话。
- **幂等**：当天已经成功跑过就跳过（`--force` 强制重跑）。所以「开机跑一次 + 每天一次」不会变成反复抓。
- **默认不发**：推送默认 dry-run，只把将要发送的内容打印出来；确认后再加 `--send`。
  Lark 自定义机器人发出去的消息**撤不回**，务必先看清楚。
- **外发禁中文**：日报正文是英文，含中文字符会被直接拒发。
- **抽不准就校准**：给该域名在 `[news.selectors]` 里配一条文章链接的 CSS 选择器（见 `config.example.toml`）。
- 抓取仍走同一套闸门：每站每域名一次导航请求，命中风控即熔断、不重试。
- **feed 优先**（最稳的一条）：站点有 RSS/Atom 就配 `[news.feeds]` —— 走普通 HTTP，
  没有 JS、没有 consent 墙、不会被当 bot 判定，几十 KB 一次拿全。内置清单里 `sbcnews.co.uk`
  已默认走 feed：它的首页在无头下只吐 5392 字节空壳（换 chromium 新 headless 模式逐字节相同，
  说明是服务端不给内容，不是自动化被识别），而 `/feed/` 一次 GET 就给 10 条。
- **不会互相撞**：整轮抓取先拿 profile 文件锁；定时任务与手动跑撞上时，后到的这轮直接跳过
  （幂等，下次跑会补上）—— 而不是两边一起挂。
- **改版会被点名**：某站条目数跌破上次的 40%（且少于 3 条）时，日报顶部出现英文告警行
  （`layout may have changed or access is limited`），不至于悄悄发一份空日报。

## 凭据（全部可选，由使用者自带；仓库不含任何凭据）

| 平台 | 需要什么 | 去哪拿 |
|---|---|---|
| Twitch | 无（公开 GQL 免登录） | — |
| X | 无（第三方公开趋势页，降级源、低置信） | — |
| YouTube | Data API key（免费） | Google Cloud Console → 启用 YouTube Data API v3 |
| Kick | app token（免费） | https://dev.kick.com 建 app |
| TikTok | 无凭据（需 node + playwright 渲染页面） | `npm i playwright && npx playwright install chromium` |
| Instagram | sessionid cookie + 对标账号 ⚠️ **法律风险高于其它平台**（读取的是非公开端点，需自行评估） | 浏览器登录 IG 取 sessionid；`seed_accounts` 配几个对标账号 |
| news（每日资讯） | 无凭据（有头浏览器渲染公开列表页） | 需 node + playwright；推送另需 `[push.lark]` / `[push.email]` |

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
