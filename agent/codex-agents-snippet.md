<!-- intel-workflow:start -->

## 社交平台情报（intel-workflow）

查平台热点与站内一手情报统一走 CLI，**不要**用模型记忆或搜索摘要冒充实时数据：

```bash
<INTEL_DIR>/intel hot    --platform all --region US         # 各平台热点/热榜
<INTEL_DIR>/intel hot    --platform x --region indonesia    # 指定地区趋势
<INTEL_DIR>/intel search --platform youtube --q "<keyword>" # 关键词下钻
<INTEL_DIR>/intel verify --platform x --handle <@handle>     # 账号核实
<INTEL_DIR>/intel analyze --platform all --region US         # 取事实 + 双模型交叉复核
```

把 `<INTEL_DIR>` 替换为 intel-workflow 仓库的绝对路径。

纪律：结论必须带来源与抓取时间；缺凭据 / 取不到就如实说；不绕过限速闸门；不并发抓取；对外内容只 EN/ES。
平台：`youtube`（需自带 key）、`x`（免凭据）、`twitch`（免凭据）、`kick`（需 token）、`tiktok`（免凭据，需 node+playwright）、`instagram`（需 cookie + 对标账号）。

<!-- intel-workflow:end -->
