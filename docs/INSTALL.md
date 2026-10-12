# 装载教程（照做即可）

> 面向不写代码的同事。**最快 3 步，约 5 分钟**。遇到问题先看第五节「卡住了怎么办」。

---

## 一、最快的路（3 步）

**第 1 步**　打开「终端」：
- Mac：按 `Command + 空格` → 输入 `Terminal` → 回车
- 会跳出一个黑/白窗口，把你下面的命令**整行复制粘贴**进去

**第 2 步**　复制下面这行，粘贴进终端，按回车（**URL 用我们发给你的那个**）：

```bash
git clone https://github.com/wj202239010118-blip/intel-workflow.git ~/intel-workflow && bash ~/intel-workflow/install.sh
```

**第 3 步**　等它自己跑完。**看到一份带「Just Chatting / ARC Raiders…」和观众数的榜单，就是成功了。**

然后回到 Claude Code（或 Codex），以后用的时候只需要说这种话：

> 用 ~/intel-workflow 查今天各平台热点

第一次可以让它自己完成集成，直接把这句发给它：

> 读 ~/intel-workflow/AGENTS.md，按它完成集成，然后跑一条腿验证

---

## 二、每一步你会看到什么（对照检查）

| 步骤 | 你看到的 | 意思 |
|---|---|---|
| 第 2 步回车后 | 出现 `Cloning into...` 然后一堆中文/英文输出 | 正常，仓库在下载 + 自动安装 |
| 第 2 步里 | `1/6 环境探测` → `✅ python3` `✅ git` | 依赖正常 |
| 第 2 步里 | `⚠️ 未检测到 codex（可选）` | **不用管**，不影响使用 |
| 第 2 步里 | `⚠️ node 已就位，但没有 playwright` | **不用管**，只是 TikTok 热点暂时用不了（想用见第四节） |
| 第 2 步里 | `凭据向导：每项都可直接回车跳过` | **直接连按回车跳过**，或者这时就填凭据（见第四节） |
| 第 3 步 | `| 1 | [Just Chatting]... | viewers=148407 |` | ✅ 装好了，这是真实的 Twitch 榜单 |
| 结尾 | `完成 → 用法：/Users/你的用户名/intel-workflow/intel hot ...` | ✅ 全部成功 |

---

## 三、装载：两步 + 一次验证

工具和「规矩」是两件事，都要装 —— 只装工具，agent 照样会把训练数据里的旧信息当"今天的热点"。

### 第 1 步 · 装工具（让 agent 有「取数的手」）

下面这条就把仓库拉下来、依赖装好、skill 装好（`install.sh` 里已包含装载）：

```bash
git clone <仓库地址> ~/intel-workflow && bash ~/intel-workflow/install.sh
```

不想碰终端也行：把仓库链接发给 AI，说「读这个仓库的 AGENTS.md，按它完成集成」—— 它会自己跑上面这条。

### 第 2 步 · 装规矩（把行为规范落成 agent 指令）

如果你们有自己的规范 / 认知文档（信源纪律、红线之类），把它**落成文件**：

- **存成 skill**：写到 `~/.claude/skills/<name>/SKILL.md`，文件头带 `name` / `description`（Claude Code 会自动加载它）
- **或写进项目指令**：贴进项目的 `CLAUDE.md` / `AGENTS.md`，用标记区块包起来

> ⚠️ 只是"发到对话里让它读一次"**不算** —— 换个会话它就忘了。必须落成文件。

### 第 3 步 · 验证

问它「查今天 X 的热点」：

- ✅ 返回**带来源 + 抓取时间**的真实榜 → 生效
- ❌ 返回「根据我的了解……」这类没有来源和时间的说法 → 规矩没装上，回第 2 步

**为什么第 2 步不能省**：第 1 步装的是"手"（能取数的 CLI），第 2 步装的是"规矩"（不许编、要标来源、不绕限速）。
只装手不装规矩，agent 就会拿模型记忆糊弄你。

装好之后，直接用大白话问它：

- 「查今天美国 X 上的热点」
- 「TikTok 今天的热门 hashtag 有哪些」
- 「核实一下 @某个账号 的近期内容和互动量」
- 「对比今天和昨天的热点，哪些新进榜」

---

## 四、可选：让更多平台可用

不填也能用（Twitch / X / TikTok 三条腿免凭据）。想用更多就编辑 `~/intel-workflow/config.toml`：

| 平台 | 不填会怎样 | 需要什么 | 去哪拿 |
|---|---|---|---|
| Twitch / X / TikTok | ✅ 照常可用 | — | — |
| YouTube | ❌ 报「缺凭据」 | Data API key（免费） | Google Cloud Console → 建项目 → 启用「YouTube Data API v3」→ 凭据 → 创建 API key |
| Kick | ❌ 报「缺凭据」 | app token（免费） | dev.kick.com 建 app → 填 `client_id` / `client_secret` |
| Instagram | ❌ 报「缺凭据」 | 你自己账号的 `sessionid` | 浏览器登录 IG → F12 → Application → Cookies → 复制 `sessionid`；再在 `seed_accounts` 写几个要盯的账号 |
| 双模型交叉复核 | 只有一端时算单模型 | 缺 codex 时可填任意 OpenAI 兼容端 | `[collab]` 的 `openai_base_url` / `openai_api_key` / `openai_model`（**三项都要填**才生效） |

**要用 TikTok 热点**（需一个可选组件），终端里跑一次：

```bash
npm i playwright && npx playwright install chromium
```

**要用每日行业资讯（news）**：**不需要额外组件，也不需要凭据** —— 内置四站全部走纯 HTTP：
站点给 RSS/Atom 就用 `[news.feeds]`（最稳最省），没给就用 `[news.sitemaps]` 的 XML sitemap
（内置的 igaming.news 只有 sitemap、没有 RSS；给 `/sitemap.xml` 也行，会自动跟到含 news 的子 sitemap）。
只有你自己新加的、既没 feed 也没 sitemap 的站点，才需要上面那个 node + playwright（渲染列表页）。

### 让它每天自己跑（可选）

「设备开机时跑一次 + 每天固定时刻一次」，一条命令装好：

```bash
cd ~/intel-workflow
python3 intel news run                      # 先手动跑一次，看看日报长什么样（内置四站不弹浏览器窗口）
python3 intel schedule install --hour 9 --minute 30   # 再装定时任务
python3 intel schedule status               # 查：装没装 / 今天跑过没 / 上次成功时间
```

- 定时任务**默认只抓取落盘，不推送**。要它自动推到 Lark / 邮件：先在 `config.toml` 里把
  `[push.lark]` 或 `[push.email]` 的 `enabled` 打开并填好，再 `python3 intel schedule install --send`。
- 当天已经成功跑过就不会重复抓（`--force` 可强制重跑），所以开机多次也不会反复请求。
- 不想要了：`python3 intel schedule uninstall`。
- 日志：`~/Library/Logs/intel-workflow-news.log`。

**另一种做法：交给云端（设备关机也跑）**。把仓库 fork 到自己账号，打开 Actions 页 → `news-daily` →
`Run workflow` 手动跑一次验证；之后它会每天 `04:00 UTC`（= 09:30 IST）自动跑。四站全是纯 HTTP，
云端**不用装 node / playwright，也不需要任何凭据**；日报会贴在该次运行的 **Summary** 里（打开就能读），
同时归档为 artifact（保留 90 天）。要让它推到 Lark 群，才需要在仓库 Settings → Secrets 加
`LARK_WEBHOOK`，并打开 workflow 里那段可选步骤（发出去撤不回，先看过内容）。
多机 / 多人各自想看日报时，这条路比本机 launchd 省事。

---

## 五、卡住了怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `command not found: git` | 没装 git | Mac 会弹窗让你装「命令行开发者工具」，点安装；或跑 `xcode-select --install` |
| `command not found: python3` | 没装 Python | Mac：先装 Homebrew（brew.sh 复制那行命令），再 `brew install python3` |
| `⛔ ...冷却中，Ns 后才解禁` | 保护机制（防止请求太密被封） | **等一会儿再跑**；不要改配置、不要反复重试 |
| `⚠️ 缺凭据 → ...` | 这个平台没填凭据 | 见第四节；申请不到就换别的平台查 |
| `⚠️ 暂不可用 → TikTok：缺 playwright` | 没装浏览器组件 | 见第四节最后那条命令 |
| AI 说 `blocked on permission` | 它的权限模式在等批准 | 回它「允许执行」 |
| AI 说读不到 AGENTS.md | 路径不对 | 把完整路径 `~/intel-workflow/AGENTS.md` 发给它 |
| 想重装 | — | 再跑一次第 2 步的命令即可（幂等，不会重复安装） |
| 想卸载 AI 里的集成 | — | 终端跑 `bash ~/intel-workflow/install.sh --uninstall` |

---

## 六、几条纪律（AI 会自动遵守，你也知道一下）

1. 查热点**只走这个工具**，不要让 AI 凭记忆编一份「今天的榜」。
2. 结果会带**来源和抓取时间**；标注「降级源 / 代理指标」的，参考即可别当官方数据。
3. **不要**把 `config.toml` 发出去或提交到 git（里面是你的凭据）。
4. 命中断流/风控时它会自己停手，**等一会儿**，别催它反复试。
