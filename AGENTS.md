# AGENTS.md — 给 AI agent 的集成与使用说明

> 你（AI agent）读到的是「社交平台情报工作流」仓库。使用者要的是：**把本仓库装到本机，并让你以后能直接调用它查平台热点、一手情报、以及每天自动汇总行业资讯**。
> 按下面的步骤执行即可，尽量全程自动完成；只有「申请凭据」这一步必须交给使用者本人。

---

## 一、集成 = 装工具 + 装规矩（两步）

> ⚠️ **权限前提**：本集成需要执行 shell 命令。**若你的权限模式不自动批准命令**（非交互 / 受限模式），
> 不要自行跳过安装，也不要想办法绕过权限 —— 把需要批准的命令压成一句话交给使用者批准
> （通常只有 `bash install.sh` 一条，验证已包含在它里面）。
> 实测：受限模式下会被 "blocked on permission" 挡住；给权限后全流程顺畅完成。

### 第 1 步 · 装工具（让使用者有「取数的手」）

1. **确认依赖**：`python3 --version`（**≥3.9** —— macOS 自带的 3.9 就够）、`git --version`。缺则先给使用者逐条安装命令，不要擅自装系统级软件。
2. **进入仓库根目录**（克隆或已存在的位置）。
3. **运行安装**：`bash install.sh`（幂等，可重复执行）。它会依次做：
   - 依赖安装（核心只有标准库，几乎无第三方依赖）
   - 生成 `config.toml`（凭据留空也能跑 Twitch / X / TikTok）
   - 探测 `claude` / `codex`
   - 冒烟自检：跑一条免凭据的腿，立刻看到真实结果
   - 装载 skill 到 `~/.claude/skills/intel-workflow/SKILL.md`（若 `~/.claude` 存在）
   - 可选：`bash install.sh --install-scheduler` 额外装「每天自动查行业资讯」的 launchd 任务
4. **验证工具**：`./intel hot --platform twitch --no-save` 应返回真实榜单。
   - 输出 `⛔`（闸门拦截）→ 说明请求过密，等最小间隔（默认 15s）再试，**不要绕开闸门**。
   - 输出 `⚠️ 缺凭据` → 按提示让**使用者本人**去申请，你不要代填任何第三方凭据。

### 第 2 步 · 装规矩（把规范落成文件，别只在对话里读一次）

工具只给了「取数的手」；**使用者还需要你知道「不许编、要标来源、不绕限速、对外不擅自发」**。

- 若使用者另外给了**规范 / 认知文档**（例如他们团队内部那份），把它**落成文件**：
  - Claude Code：写到 `~/.claude/skills/<name>/SKILL.md`（文件头带 `name` / `description`），或贴进使用者项目的 `CLAUDE.md` 标记区块
  - Codex：贴进使用者项目的 `AGENTS.md` 标记区块
- 若使用者没给：把本文件「二、命令速查」「三、纪律」两节接进使用者的项目指令
  （Claude Code → `CLAUDE.md`；Codex → `agent/codex-agents-snippet.md`，把 `<INTEL_DIR>` 换成本仓库绝对路径）。
- ⚠️ **只是"在对话里读一次"不算** —— 换个会话就没了，必须落成文件。

### 第 3 步 · 验证规矩是否生效

让使用者问一句「查今天 X 的热点」：

- ✅ 返回**带来源 + 抓取时间**的真实榜 → 生效
- ❌ 只给「根据我的了解…」这类没有来源和时间的说法 → 规矩没装上，**回到第 2 步**

## 二、命令速查

```bash
./intel hot    --platform all --region US              # 各平台热点/热榜
./intel hot    --platform x --region indonesia         # 指定地区趋势
./intel search --platform youtube --q "<keyword>"      # 关键词下钻（目前仅 YouTube）
./intel verify --platform instagram --handle <@handle> # 账号核实（目前仅 Instagram，需自带 cookie）
./intel analyze --platform all --region US             # 取事实 + 双模型交叉复核
./intel news run                                       # 每日行业资讯：抓取一组 iGaming 站 → 整合英文日报
./intel news push                                      # 把最近一份日报推出去（默认 dry-run，只打印）
./intel schedule status|install|uninstall              # 定时任务（launchd：开机/登录一次 + 每天一次）
```

平台：`youtube`（需自带 key）、`x`（免凭据，降级源）、`twitch`（免凭据）、`kick`（需自带 token）、`tiktok`（免凭据，需 node + playwright）、`instagram`（需自带 sessionid cookie + 对标账号）。
`--region`：YouTube 用 `US` 这类国家码；X 用 `united-states` 这类 slug。
输出落 `out/`（`.md` 人读 + `.jsonl` 机读，便于次日对比）。

**news**：有头 Chromium + 持久 profile（默认 `~/.cache/intel-workflow/browser-profile`）跑 `[news]` 里的站点列表页
（不配就用内置的 igaming.news / igamingbusiness.com / sbcnews.co.uk / yogonet.com），
合并成 `out/<日期>-news-digest.md`；`--force` 强制重跑，`--headless` 无头，`--send` 真推送，`--sites` 临时换站点。
取数通道按优先级自动选：站点有 RSS/Atom 就用 `[news.feeds]` 配的 feed（**普通 HTTP，不起浏览器，最稳**），
否则渲染列表页、抽不准时按域名配 `[news.selectors]`。
整轮抓取持 profile 文件锁（并发时后到的那轮跳过，不两边一起挂）；某站条目数骤降会在日报顶部点名。

## 三、你必须遵守的纪律

1. **一手优先**：查热点/情报必须走本仓库的 `./intel` 取实时数据，**不得**用模型记忆或搜索摘要冒充「今天的榜」。
2. **可追溯**：每条结论带来源与抓取时间；`method` 为 `fallback-*` 或带 `caveat` 时，引用必须说明是降级源 / 代理指标。
3. **拿不到就说拿不到**：缺凭据、端点变更、被闸门拦截 —— 如实上报，**不要编、不要静默降级**。
4. **不碰闸门**：不要修改 `intel_workflow/core/gate.py` 的限速参数，不要在冷却期内重试，不要并发/批量翻页抓取。
5. **凭据不外流**：不把 `config.toml`、任何 token/cookie 写进仓库、日志或对外内容。
6. **对外内容禁中文**：发到生产通道（群、私聊、通知、话术、caption）的内容只允许 EN / ES；`news` 的日报正文也必须是英文（`assert_no_cjk` 会拦）。
7. **推送默认不发**：`intel news run/push` 默认 dry-run。**要真发（`--send`）必须先让使用者看过将要发送的内容并明确同意** ——
   Lark 自定义机器人发出去的消息撤不回。定时任务默认只抓取落盘，`[schedule].send = true` 才推送。
8. **定时任务只装一次**：`intel schedule install` 幂等；不要为了「让它立刻跑」反复 `launchctl kickstart` 轰炸目标站点 ——
   当天已成功跑过会跳过，重跑用 `--force` 且只在你确知为什么需要时用。

## 四、仓库结构

```
intel            CLI 入口
install.sh       一键安装（含装载 skill；--uninstall 回滚；--install-scheduler 装定时）
intel_workflow/  core（闸门/HTTP/归一化/输出/node 定位）+ adapters（各平台）+ news（行业资讯检索）
tools/           浏览器渲染脚本（tiktok_trends.js / news_fetch.js）
agent/           宿主 agent 的装载件（claude skill / codex AGENTS 片段）
docs/DESIGN.md   技术方案（腿矩阵、热点降级链、架构、每日资讯检索、里程碑、探针实测）
```
