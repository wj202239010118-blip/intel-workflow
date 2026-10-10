# intel-workflow

> ⚠️ **Disclaimer** — for lawful personal / educational use only. You are responsible for
> complying with each platform's Terms of Service; the built-in rate limiter is part of the
> design (don't remove it); no credentials are shipped. See [DISCLAIMER.md](DISCLAIMER.md).
>
> **Acceptable use / 用途约束** — **允许**：个人研究、热点发现、由人或其 agent 对**公开可见**数据做单次查询，
> 且保持很低的请求频率。**禁止**：规模化批量采集；对个人建库 / 画像 / 侧写；追踪敏感群体；
> 重识别或关联账号；移除、关闭或绕过限速器；任何骚扰、监控或侵权用途。

给 agent（Claude Code / Codex）装上「社交平台站内一手情报 + 热点监控」能力：
直接向平台要数据，而不是依赖搜索引擎/模型训练数据里的二手信息。

## 让 AI 直接集成（推荐）

把本仓库链接丢给你的 AI（Claude Code / Codex）：

> 读这个仓库的 AGENTS.md，按它完成安装和集成，最后跑一条腿验证。

仓库根有 `AGENTS.md`（给 AI 的集成与使用说明）和 `CLAUDE.md`（指向 AGENTS.md）；
`agent/` 下是装载件（Claude Code skill、Codex 的 AGENTS 片段）。AI 读完就能自己装。

## 手动安装

```bash
git clone <repo> && cd intel-workflow
bash install.sh               # 幂等，可重复跑；结束会把 skill 装到 ~/.claude/skills/
bash install.sh --uninstall   # 卸载已装载的 skill
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

## 凭据（全部可选，由使用者自带；仓库不含任何凭据）

| 平台 | 需要什么 | 去哪拿 |
|---|---|---|
| Twitch | 无（公开 GQL 免登录） | — |
| X | 无（第三方公开趋势页，降级源、低置信） | — |
| YouTube | Data API key（免费） | Google Cloud Console → 启用 YouTube Data API v3 |
| Kick | app token（免费） | https://dev.kick.com 建 app |
| TikTok | 无凭据（需 node + playwright 渲染页面） | `npm i playwright && npx playwright install chromium` |
| Instagram | sessionid cookie + 对标账号 ⚠️ **法律风险高于其它平台**（读取的是非公开端点，需自行评估） | 浏览器登录 IG 取 sessionid；`seed_accounts` 配几个对标账号 |

缺凭据不会静默失败：命令会直接告诉你缺什么、去哪申请。

## 抓取纪律（写进代码，不建议关）

- 同域名最小请求间隔 + 每日上限 + 命中风控后**持久化冷却**（冷却期内零请求）
- 命中风控立即熔断，**不自动重试**（反复请求只会延长封禁）
- 禁并发、禁批量翻页

## 文档

- `AGENTS.md` — 给 AI 的集成与使用说明（含纪律）
- `docs/DESIGN.md` — 技术方案（腿矩阵、热点降级链、架构、里程碑、探针实测结论）
- `docs/INSTALL.md` — 装载教程（非技术同事向：环境、拿仓库、安装、凭据、常见报错）

## 状态

M1–M3：`hot` 已通 YouTube / X / Twitch / TikTok；`analyze` 双模型交叉复核可用（本机实测 claude 引擎）；Kick 待使用者 token；Instagram 待使用者 cookie + 对标账号。
