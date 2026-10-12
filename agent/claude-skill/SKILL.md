---
name: intel-workflow
description: 查社交平台站内的一手情报与热点（X/YouTube/Twitch/Kick 等）—— 热点榜、关键词下钻、账号核实；以及每日 iGaming 行业资讯检索与整合日报。当使用者问「今天各平台热点」「某国/某词在讨论什么」「核实某账号」「今天的行业新闻」时使用；不要用模型记忆或搜索摘要冒充实时数据。
---

# intel-workflow

一手情报入口。所有查询都走 CLI：`{{INTEL_DIR}}/intel`。

## 用法

```bash
{{INTEL_DIR}}/intel hot    --platform all --region US         # 各平台热点/热榜
{{INTEL_DIR}}/intel hot    --platform x --region indonesia    # 指定地区趋势
{{INTEL_DIR}}/intel search --platform youtube --q "<keyword>" # 关键词下钻（目前仅 YouTube）
{{INTEL_DIR}}/intel verify --platform instagram --handle <@h>  # 账号核实（目前仅 IG，需自带 cookie）
{{INTEL_DIR}}/intel analyze --platform all --region US         # 取事实 + 双模型交叉复核
{{INTEL_DIR}}/intel news run                                   # 每日行业资讯：一组 iGaming 站 → 整合英文日报
{{INTEL_DIR}}/intel news push                                  # 把最近一份日报推出去（默认 dry-run，只打印不发）
{{INTEL_DIR}}/intel schedule status                            # 定时任务状态（install / uninstall / show）
```

平台：`youtube`（需使用者自带 API key）、`x`（免凭据，降级源，置信度 medium）、
`twitch`（免凭据）、`kick`（需自带 token）、`tiktok`（免凭据，需 node + playwright）、`instagram`（需自带 cookie + 对标账号）。
`--region`：YouTube 用 `US` 这类国家码；X 用 `united-states` 这类 slug。
结果落 `{{INTEL_DIR}}/out/`（`.md` 人读 + `.jsonl` 机读，便于次日对比）。

**news**（每日行业资讯）：有头 Chromium + 持久 profile 跑 `[news]` 的站点列表页，合并成
`out/<日期>-news-digest.md`（英文）。日报正文禁中文；推送默认 dry-run。

## 纪律（必须遵守）

1. 查热点一律走本 CLI 取实时数据，**不得**用记忆/搜索摘要冒充「今天的榜」。
2. 结论必须带来源与抓取时间；`method` 为 `fallback-*` 或带 `caveat` 时要说明是降级源 / 代理指标。
3. 缺凭据、取不到、被闸门拦截 → **如实上报**，不要编、不要静默降级。
4. 不修改限速参数、不在冷却期重试、不并发抓取。
5. 对外内容只 EN / ES，不发中文。
6. **推送默认不发**：`news` 默认 dry-run；要 `--send` 真发，先让使用者看过内容并明确同意（Lark 群消息撤不回）。
   定时任务默认只抓取落盘。

## 排障

- `⛔ ...冷却中 / 间隔不足`：闸门保护，等最小间隔（默认 15s）重试，不要绕开。
- `⚠️ 缺凭据`：让使用者本人申请并填 `{{INTEL_DIR}}/config.toml`；不要代填第三方凭据。
- `news`：`缺 playwright 依赖` → `npm i playwright && npx playwright install chromium`（或给 `INTEL_NODE_PATH`）；
  `未抽到条目` → 先试该域名的 RSS（`[news.feeds]`，无浏览器最稳），再考虑 `[news.selectors]`；
  `今天已跑过 → 跳过` 是幂等，正常现象（要重跑加 `--force`）；`另一个 news 进程正在用同一 profile` 是并发保护，别并发跑。
