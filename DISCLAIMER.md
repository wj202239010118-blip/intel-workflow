# Disclaimer / 免责声明

## English

This project is published **for lawful, personal, and educational use only**.

By using, cloning, forking, or redistributing it, you agree that:

1. **You are solely responsible for compliance** with each platform's Terms of Service,
   automated-access / robots policies, and any applicable local laws. This project is
   **not affiliated with, endorsed by, or sponsored by** any platform it reads from
   (including X/Twitter, YouTube, TikTok, Instagram, Twitch, Kick), nor by any data provider.
2. **No credentials are shipped.** API keys, tokens, cookies, and sessions are supplied by
   the user. Do not commit them; do not share them.
3. **The rate limiter is part of the design.** It enforces a minimum interval per domain, a
   daily cap, and a persistent cool-down after a rate-limit response. Removing or bypassing
   it, or scraping at scale, may get your account or IP blocked and may violate platform
   terms — you do so at your own risk.
4. **Do not use this project** to bypass access controls, to collect personal data without a
   lawful basis, or for any purpose that infringes the rights of others.
5. **No warranty.** The software is provided "as is", without warranty of any kind. The
   authors are not liable for any claim, damage, or other liability arising from its use.
6. **Third-party endpoints change without notice.** Adapters may break at any time; results
   are labeled with their source, method, and confidence so that failures are visible
   rather than silently wrong.
7. **Logged-in access / non-public endpoints.** Some adapters (e.g. Instagram) require a
   user-supplied login cookie and read endpoints that are **not** part of a platform's
   official public API. Such access may conflict with that platform's terms and carries
   higher legal risk than the rest of this project — evaluate before use.
8. **Third-party aggregator pages** (used as fallbacks) may have their own terms of use.

## Acceptable Use / 用途约束

**Permitted** — personal research; trend discovery; one-off lookups of publicly visible data by a
human operator or their agent; deliberately low request rates.

**Not permitted**:

- bulk or automated collection at scale;
- building profiles, databases, or dossiers on individuals;
- tracking sensitive groups; re-identifying or correlating accounts;
- removing, disabling, or bypassing the rate limiter;
- any use that harasses, surveils, or infringes the rights of others.

**允许**：个人研究、热点发现、由人或其 agent 对公开可见数据做单次查询、保持很低的请求频率。

**禁止**：规模化批量采集；对个人建库 / 画像 / 侧写；追踪敏感群体；重识别或关联账号；
移除、关闭或绕过限速器；任何骚扰、监控或侵权用途。

## 中文摘要

本项目**仅供合法的个人与学习用途**。

- **合规责任在你自己**：使用本工具须遵守各平台服务条款、自动化访问政策及当地法律。本项目与所涉平台（X/Twitter、YouTube、TikTok、Instagram、Twitch、Kick）**无任何关联或背书**。
- **仓库不含任何凭据**：API key / token / cookie 均由使用者自行提供，请勿提交、勿外传。
- **限速器是设计的一部分**：按域名最小间隔、每日上限、命中风控后冷却。**移除或绕过它**、或规模化抓取，可能导致账号/IP 被封并违反平台条款，风险自负。
- **不要**用它绕过访问控制、或在没有合法依据的情况下收集个人信息。
- **按「现状」提供，无任何担保**。第三方接口随时可能变更，结果会标注来源 / 方式 / 置信度，使失败可见而不是静默出错。
- **登录态 / 非公开接口**：Instagram 等适配器需使用者自带登录 cookie，读取的不是平台官方公开 API。此类访问可能与该平台条款冲突，**法律风险高于本项目其它部分**，请自行评估后使用。
- 作为降级源的**第三方聚合页**也有自己的使用条款。
