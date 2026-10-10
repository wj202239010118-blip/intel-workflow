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

## 三、把它交给你的 AI（集成）

打开 **Claude Code**（或 **Codex**），发这一句：

> 读 ~/intel-workflow/AGENTS.md，按它完成集成，然后跑一条腿验证

**它会让你批准执行命令**（通常就一条 `bash install.sh`）—— 点「允许 / Yes」。
如果它回复说 `blocked on permission`，回它一句「允许执行」就行。

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
