"""适配器基类与两类「如实上报」的异常。

设计原则：取不到数就明确报「缺什么、去哪拿」，绝不静默降级、绝不返回空榜糊弄。
"""


class NeedCredential(Exception):
    """缺使用者自带的凭据（API key / token / cookie）。"""


class Degraded(Exception):
    """当前条件下该平台取不到数（需浏览器渲染 / 需登录态 / 端点变更）。"""


class Adapter:
    platform = "?"

    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http

    def hot(self, region=None, period="24h"):
        raise Degraded(f"{self.platform}: 热点能力未实现")

    def search(self, query, region=None):
        raise Degraded(f"{self.platform}: 关键词下钻未实现")

    def verify(self, handle):
        raise Degraded(f"{self.platform}: 账号核实未实现")
