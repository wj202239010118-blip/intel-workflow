# 社交平台情报工作流 · 技术方案（v0.1 草案）

> 面向：实现者 + 评审者
> 定位：给 agent（Claude Code / Codex）装上「站内一手情报 + 热点监控」能力，开源分发、同事零门槛安装。
> 本文件为**开源就绪版**：不含任何内部系统名、内部路径、账号或凭据。

---

## 0. 一句话定位

让 agent 不再依赖「搜索引擎 / 模型训练数据里那些二手信息」，而是**直接向社交平台要数据**：查热点、按词下钻、核实账号与内容；结果落盘并写入 agent 记忆，供后续复用与对比。

---

## 1. 目标与边界

### 要做
1. **热点监控**（主入口）：问「今天 X / YouTube / TikTok / Instagram 的热点是什么」→ 返回带来源与时间的榜。
2. **关键词下钻**：按关键词 / 地区查站内正在讨论什么（不是搜账号，是搜"正在发生的事"）。
3. **账号与内容核实**：给定 handle / URL，回一手事实（简介、近期内容、链接、互动量级）。
4. **双模型协同**：本机同时有 claude 与 codex 时，交叉复核后合并输出。
5. **记忆沉淀**：结果结构化落盘 + 可写入 agent 记忆，支持「认知 × 热点」结合。

### 不做（明确划出去，避免范围蔓延）
- 不做内容抓取归档（不囤原始帖库）、不做登录态批量爬取、不做任何绕过平台风控的手段。
- 不随包分发任何账号 / cookie / API key。
- 不承诺数据完整性（第三方公开源随时会变），只承诺**标注来源与置信度**。

---

## 2. 能力面

### 2.1 腿矩阵（每平台 = 一个 adapter）

| 平台 | 取什么 | 鉴权 | 依赖 | 可行性 |
|---|---|---|---|---|
| X / Twitter | 趋势、关键词搜索 | 免费链：免登录（第三方趋势页）；完整链：自带 API token | python3 | 中（趋势靠降级源） |
| YouTube | 趋势（mostPopular）、频道近期内容 | **自带 API key**（免费额度足够）；无 key 时 yt-dlp 拿频道内容 | python3 + yt-dlp | 高 |
| TikTok | 热门 hashtag / 热门视频 | 官方无开放趋势接口 → 用第三方公开趋势页；站内搜索需自带 cookie | python3（可选 curl_cffi） | 中 |
| Instagram | 趋势（代理指标）、账号近期内容 | 无公开趋势 API → 登录态或公开账号近期帖代理；需自带 cookie | python3 | 低-中（最弱一环） |
| Twitch | 分类榜、在播 Top | 公开 GQL（免登录）或自带 app token | python3 | 高 |
| Kick | 分类榜、在播 Top | **官方 Public API 需 app token（免费；实测无 token 返 401）** | python3（可选 curl_cffi） | 中 |

> 原则：**优先免登录能拿到的量；需要登录态的，留「配置自己的 cookie」入口，由使用者自备。**

### 2.2 热点路线与降级链（第一版一次做齐四平台）

| 平台 | 主路线 | 降级链 | 输出字段 |
|---|---|---|---|
| YouTube | Data API v3 `videos?chart=mostPopular&regionCode=<XX>` | （无）→ 缺 key 时明确报「需配置 key」 | 标题 / 频道 / 观看量 / 发布时间 / 分类 |
| X | 免登录趋势页（按国家/城市） | ① 第三方趋势聚合页 ② 自带 API token 走官方 trends ③ 登录态 Explore | 趋势词 / 排名 / 地区 / 抓取时间 |
| TikTok | ✅ 读取平台公开展示的趋势页（playwright 渲染，免登录；2026-10-10 实测拿到真实榜） | ① 站内公开页（使用者自带登录态）② 第三方趋势页 | hashtag / 榜位 / posts / views / 类目 |
| Instagram | 公开账号近期帖按互动排序（**代理指标**，非官方趋势） | ① 第三方趋势报告页 ② 登录态 Explore | 账号 / 帖 / 互动量 / 口径声明 |
| Twitch / Kick | 分类榜 + 在播 Top（在播量排序） | （无） | 分类 / 在播频道数 / Top 频道与观众数 |

**硬要求**：每个热点结果必须带 `source`、`fetched_at`、`method`（主路线/降级几档）、`confidence`。IG 的结果必须显式标注「代理指标」。

---

## 3. 架构

```
agent (Claude Code / Codex)
        │  一个统一入口：intel <command>
        ▼
┌─────────────────────────────────────────┐
│ core                                    │
│  · 命令路由 / 参数校验                   │
│  · 限速闸门（按域名最小间隔 + 每日上限 + 冷却持久化）│
│  · 归一化情报对象                        │
│  · 输出层（Markdown + JSONL）            │
│  · 记忆写入（按宿主 agent 适配）          │
└─────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────┐
│ adapters（每平台一个，统一接口）          │
│  hot(region, period) / search(q) / verify(handle) │
│  x · youtube · tiktok · instagram · twitch · kick │
└─────────────────────────────────────────┘
```

### 3.1 统一入口

```
intel hot    --platform <x|yt|tt|ig|twitch|kick|all> [--region US] [--period 24h]
intel search --platform <x|tt|yt|ig> --q "<keyword>" [--region US]
intel verify --platform <x|tt|yt|ig> --handle @foo | --url <u>
intel digest --since 24h [--region US]        # 汇总成一份日报
```

### 3.2 归一化情报对象（所有 adapter 必须产出这个形状）

```json
{
  "platform": "x",
  "kind": "trend | search | profile",
  "region": "US",
  "query": null,
  "method": "primary | fallback-1 | fallback-2",
  "source": "人类可读的来源说明 + URL",
  "fetched_at": "2026-10-10T12:00:00+05:30",
  "confidence": "high | medium | low",
  "caveat": "IG 趋势为代理指标，非官方榜单",
  "items": [
    {"rank": 1, "title": "...", "url": "...", "metrics": {"views": 0}, "extra": {}}
  ]
}
```

### 3.3 输出与记忆

- **落盘**：`out/<date>-<platform>-<kind>[-<region>].md`（人读）+ 同名 `.jsonl`（机读，供对比）。
- **记忆**：按宿主适配写入 —— Claude Code 侧写 repo 内 `MEMORY.md`（或 CLAUDE.md 的标记区块）；Codex 侧写 `AGENTS.md` 标记区块。**只追加结构化摘要，不写原始数据**，便于「认知 × 热点」时被模型读取。
- **对比**：同平台同日多次抓取时，`intel digest` 自动标注「新进榜 / 掉榜 / 排位变化」。

---

## 4. 双模型协同（默认开启，可关）

> **实现状态（2026-10-10）**：已落地 `intel analyze`。本机实测 `claude` 引擎可用（`claude -p`，22s 产出结论/存疑/待确认）；
> `codex exec` 路径**未在本机验证**（本机无 codex）；缺 codex 时用 OpenAI 兼容端替代（`[collab]` 三项必须配齐，否则不启用）。
> 产出的报告做**结构化对齐**（一致 / 单侧），不做语义取舍。

### 4.1 探测

安装器与每次运行时检测：`claude` 与 `codex` 是否在 PATH 且可用。

### 4.2 两端都有 → 交叉复核

1. 主模型（当前会话那个）先跑 adapter，产出情报对象。
2. 拉**无头对端**做同步分析：对端只吃归一化对象（不吃原始 HTML），产出「结论 + 存疑点 + 补充」。
3. `merge`：一致 → 合并为一；冲突 → 两条都留，标 `DISAGREE` 并列出分歧点；单侧独有 → 标 `ONLY-<平台>`。
4. 输出结构：`结论 / 一致项 / 分歧项 / 待人工确认`。

### 4.3 缺 codex

- 用 **OpenAI 兼容 API**（使用者填自己的 token）替代 codex 端：同一份提示词模板、同一份输入输出契约，行为等价。
- 因此 codex 不是硬依赖，**第二意见能力不依赖本地 codex CLI**。

### 4.4 缺 claude

- 提示「下载 Claude Code 并登录后使用」（Claude 端无 API 等价替代，需本地 CLI）。
- 只有一端时：仍可单模型运行，输出标注 `single-model`。

### 4.5 开关

- 默认开；`--single` 关闭；配置项 `collab.mode = cross | single | auto`。

---

## 5. 安装器（面向非技术同事）

### 5.1 一键流程

```
git clone <repo> && cd <repo> && ./install.sh     # macOS/Linux
（Windows: install.ps1）
```

`install.sh` 依次做：
1. **环境探测**：python3 / node / git 版本，缺则给出**逐条安装指令**（含 Homebrew / 官网链接），不擅自装系统级东西。
2. **依赖安装**：`pip install -r requirements.txt`（或 uv），可选组件（curl_cffi、yt-dlp）失败不阻断主流程。
3. **凭据向导**（可选步骤，全可跳过）：交互式问「你有 YouTube API key 吗 / 要配 IG cookie 吗」，写入 `config.toml`（`chmod 600`），不打印明文。
4. **模型端探测**：报「detected: claude ✅ / codex ❌」，缺 codex 时提示填 OpenAI 兼容 token。
5. **冒烟自检**：跑 1 个免登录 leg（如 Twitch/Kick 榜）+ 打印一份样例输出，**装完立刻看到结果**。
6. **装载到 agent**：把 skill 文件复制到 Claude Code 的 skills 目录 / 写 Codex 的 `AGENTS.md` 标记区块（可 `--uninstall` 回滚）。

### 5.2 依赖清单

| 依赖 | 必需 | 说明 |
|---|---|---|
| python3 ≥ 3.10 | ✔ | 全部 adapter |
| git | ✔ | 安装/更新 |
| node ≥ 18 | 可选 | 部分浏览器腿 |
| yt-dlp | 可选 | YouTube 无 key 降级 |
| curl_cffi | 可选 | 有 TLS 指纹要求的站点 |
| playwright | 可选 | TikTok 趋势（需浏览器渲染 DOM） |
| claude / codex | 至少一 | 协同分析 |

### 5.3 仓库结构

```
intel-workflow/
├─ README.md              # 装载教程（非技术同事向，含常见报错）
├─ install.sh / install.ps1
├─ config.example.toml
├─ core/                  # 闸门、归一化、输出、记忆
├─ adapters/              # x.py youtube.py tiktok.py instagram.py twitch.py kick.py
├─ collab/                # 双模型交叉复核 + merge
├─ agent/                 # claude 侧 skill 文件 / codex 侧 AGENTS 片段
└─ docs/DESIGN.md         # 本方案
```

---

## 6. 安全与合规（硬约束，不砍）

1. **仓库零凭据**：全仓禁止出现 token / cookie / client_secret / 私有域名。上 CI：`gitleaks` 或 `detect-secrets` + 自定义规则（标识词黑名单）。
2. **凭据由使用者自带**：`config.example.toml` 只放字段名与占位符；`.gitignore` 覆盖 `config.toml`、`*.cookie`、`.secrets/`。
3. **抓取纪律打包进代码**（不是写在文档里让人自觉）：
   - 按域名最小间隔 + 每日上限 + 命中风控后的**持久化冷却**；
   - 连续 2 次风控响应 → **熔断退出，不自动重试**；
   - 禁并发、禁批量翻页抓取；
   - 冷却期内**零请求**退出。
4. **不做登录态批量**：登录态只用于单次、低频核实类查询。
5. **来源可追溯**：每条结果带 `source` + `fetched_at`，输出禁止伪装成官方数据。

---

## 7. 交付物与里程碑

| # | 交付物 | 通道 | 说明 |
|---|---|---|---|
| 1 | 本方案 `docs/DESIGN.md` | GitHub（公开） | 技术逻辑 |
| 2 | 代码 + `install.sh` + skill 适配 | GitHub（公开） | 零内部信息 |
| 3 | `README.md` 装载教程 | GitHub（公开） | 非技术同事向 |

**里程碑（四平台热点一次做齐）**
- M1 骨架：core（闸门/归一化/输出）+ Twitch/Kick/YouTube（最稳三板斧）跑通
- M2 热点齐活：+ X / TikTok / Instagram 热点（降级链至少 2 档）
- M3 协同：✅ 已落地 `intel analyze`（各引擎独立分析 → 结构化对齐：一致 / 单侧）；`codex exec` 路径未本机验证
- M4 装载：install.sh 端到端（从零机器 → 出第一份热点）+ 教程
- M5 开源就绪：✅ README + `docs/INSTALL.md`（非技术同事向）+ 凭据向导
- **端到端实测（2026-10-10）**：让真实 AI（`claude -p`）在隔离克隆里、只读仓库独立完成集成 —— 受限权限模式下卡在「blocked on permission」；给权限后全流程跑通（生成 config.toml / 冒烟出真实榜 / 装载 skill / 仓库零改动），且**它自己撞上闸门时没有绕过、等 15s 重试**。已把权限前提写进 AGENTS.md 与 INSTALL.md

---

## 8. 风险与待验证项（写清楚，别假装没有）

| 风险 | 影响 | 处置 |
|---|---|---|
| X 趋势无官方免费接口 | 热点最弱档之一 | 第三方公开趋势页 + 自带 token 双轨；标注 confidence |
| TikTok 公开趋势端点非官方、可能变更 | 随时失效 | adapter 层隔离 + 降级链 + 明确报错文案 |
| IG 无趋势 API | 只能给代理指标 | 输出强制标注；roadmap 里明确 |
| 平台风控（429/挑战页） | 中断、封禁 | 第 6 节闸门 + 熔断；文档教使用者「命中就停」 |
| 开源后接口被滥用 | 上游站点压力 | 限速/熔断写进代码 + README 显式声明 |
| 工期：四平台一次做齐 | 下周交付有压力 | M1-M2 优先，X/IG 若卡住先给降级档并标 roadmap |

**探针实测结论（2026-10-10，每平台 1–4 次请求，串行低频）**

| 平台 | 结论 | 证据 |
|---|---|---|
| YouTube | ✅ 可直接用 | `videos?chart=mostPopular&regionCode=US` → HTTP 200，返回真实榜（需自带 key，免费额度足够；缺 key 时明确报错） |
| X | ✅ 走降级源 | 免登录趋势页 → HTTP 200，趋势词可结构化解析（置信度 medium） |
| TikTok | ✅ 可行（页面渲染） | 官方未开放趋势接口、直接请求无数据；改用 playwright 读取其**公开展示**的趋势页 → 渲染出真实榜（`#shopwithconfidence` 92.1K posts / 68M views），免登录 |
| Instagram | ⚠️ 必须登录态 | `web_profile_info` 无 cookie → HTTP 401 `require_login`；只能靠使用者自带 cookie，且输出为代理指标 |
| Twitch | ✅ 免登录可用 | 公开 GQL · games(sort=VIEWER_COUNT) → HTTP 200，含观众数 |
| Kick | ⚠️ 需自带 token | 官方 Public API 无 token → HTTP 401 Unauthorized（app 免费申请） |

**结论**：四平台热点**全部打通** —— YouTube（官方 API）、X（第三方页降级）、TikTok（playwright 浏览器渲染，免 cookie）、IG（自带 cookie + 对标账号，代理指标）。TikTok 的 playwright 由安装器作为**可选组件**安装，缺组件时明确提示而非静默失败。

---

## 9. 版本记录

- v0.1（2026-10-10）初稿：范围、腿矩阵、热点降级链、架构、双模型协同、安装器、安全约束、里程碑。
- v0.2（2026-10-10）回填四平台探针实测：YouTube/X 可用，TikTok 需浏览器渲染，IG 需登录态；依赖表加 playwright。
- v0.3（2026-10-10）M1 骨架落地（core + 6 个 adapter + CLI + install.sh）；新增 AGENTS.md / CLAUDE.md / `agent/` 装载件，AI 可直接读仓库完成集成；Twitch/Kick 结论回填。
- v0.4（2026-10-10）四平台热点齐活：TikTok 走 playwright 渲染（实测通，免 cookie）、IG 走自带 cookie + 对标账号代理指标；两平台均如实报缺凭据/缺组件，不静默降级。
- v0.5（2026-10-10）M3 双模型协同落地：`intel analyze`（引擎探测 / 独立分析 / 结构化对齐报告）；修 OpenAI 兼容端误启用（三项需配齐）；`mode` 按成功引擎数判定。
