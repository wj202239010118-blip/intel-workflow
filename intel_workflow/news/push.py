"""推送：Lark 自定义机器人 webhook + SMTP 邮件。

两条对外纪律写进代码，不靠自觉：
  1. **默认 dry-run** —— 只有显式 --send 才真发；dry-run 只打印将要发送的内容。
  2. **外发正文禁中文** —— 含 CJK 字符直接拒绝（assert_no_cjk），只允许 EN/ES。

配置（config.toml，留空 = 该通道不发，并明确告诉你缺什么）：

    [push.lark]
    enabled = false
    webhook = ""    # https://open.larksuite.com/open-apis/bot/v2/hook/...
    secret  = ""    # 机器人开了「签名校验」才需要

    [push.email]
    enabled = false
    host = ""; port = 465; user = ""; password = ""; sender = ""
    to = ["a@example.com"]; subject_prefix = "[iGaming News]"
"""
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
LARK_CHUNK = 2800


class PushRefused(Exception):
    """内容或配置不满足对外发送的条件（中文 / 缺配置）。"""


def assert_no_cjk(text):
    """外发前的硬校验：出现中文字符就拒绝。返回原文，便于链式调用。"""
    hit = CJK.search(text or "")
    if hit:
        raise PushRefused(f"外发内容含中文字符 {hit.group(0)!r}（对外只允许 EN / ES）")
    return text


def lark_payload(title, markdown_text):
    """飞书 interactive 卡片；正文分片，避免单元素超限。"""
    assert_no_cjk(title + "\n" + markdown_text)
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": chunk}}
                for chunk in _chunks(markdown_text, LARK_CHUNK)]
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": elements or [{"tag": "div", "text": {"tag": "lark_md", "content": "(empty)"}}],
        },
    }


def _chunks(text, size):
    lines, buf, out = text.splitlines(), "", []
    for line in lines:
        if len(buf) + len(line) + 1 > size and buf:
            out.append(buf)
            buf = ""
        buf += line + "\n"
    if buf.strip():
        out.append(buf)
    return out


def lark_signature(secret, timestamp):
    """飞书自定义机器人的签名校验：base64(HMAC-SHA256(secret, timestamp + '\\n' + secret))。"""
    import base64
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}\n{secret}".encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_lark(webhook, payload, http, secret="", timeout=20):
    """POST 到 webhook；返回飞书响应 dict。非 0 code 视为失败。"""
    url = webhook
    if secret:
        ts = str(int(time.time()))
        url = f"{webhook}?timestamp={ts}&sign={lark_signature(secret, ts)}"
    status, body = http.post_json(url, payload, domain=_domain_of(webhook))
    if isinstance(body, dict) and body.get("code") not in (0, None):
        raise PushRefused(f"Lark 拒绝：code={body.get('code')} msg={body.get('msg')}")
    return body


def _domain_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


def markdown_to_html(text):
    """极简 markdown → html（标题 / 列表 / 链接 / 粗体 / 斜体），够邮件正文用。"""
    def inline(s):
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"_([^_]+)_", r"<em>\1</em>", s)
        return s

    html, in_list = [], False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        if line.startswith("## "):
            html.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            html.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip():
            html.append(f"<p>{inline(line)}</p>")
    if in_list:
        html.append("</ul>")
    return "<html><body>" + "\n".join(html) + "</body></html>"


def email_message(sender, to, subject, markdown_text):
    assert_no_cjk(subject + "\n" + markdown_text)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(markdown_text, "plain", "utf-8"))
    msg.attach(MIMEText(markdown_to_html(markdown_text), "html", "utf-8"))
    return msg


def send_email(host, port, user, password, sender, to, message, timeout=30):
    port = int(port or 465)
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
        server.starttls(context=ssl.create_default_context())
    try:
        if user:
            server.login(user, password)
        server.sendmail(sender, list(to), message.as_string())
    finally:
        server.quit()


def channels(cfg):
    """读配置 → (lark dict, email dict)，未启用的为 None。"""
    lark = cfg.section("push.lark") or cfg.section("lark")
    email = cfg.section("push.email") or cfg.section("email")
    # 支持 [push.lark] 与 [push] 下内联两种写法
    if not lark:
        push = cfg.section("push")
        lark = {k: push[k] for k in ("enabled", "webhook", "secret") if k in push}
        email = email or {k: push[k] for k in ("enabled", "host", "port", "user", "password", "sender", "to", "subject_prefix") if k in push}
    lark_on = bool(lark.get("enabled")) and bool(lark.get("webhook"))
    email_to = email.get("to") or []
    if isinstance(email_to, str):
        email_to = [email_to]
    email_on = bool(email.get("enabled")) and bool(email.get("host")) and bool(email_to)
    return (lark if lark_on else None), (dict(email, to=email_to) if email_on else None)


def push(cfg, title, markdown_text, http, dry_run=True, log=print):
    """按配置推送；返回动作列表。dry_run=True 时只打印不发送。"""
    assert_no_cjk(title + "\n" + markdown_text)
    lark, email = channels(cfg)
    actions = []
    if not lark and not email:
        actions.append("未启用任何推送通道（config.toml 的 [push.lark] / [push.email] 都是空或 enabled=false）→ 跳过")
        return actions

    if dry_run:
        if lark:
            actions.append(f"[dry-run] 将发 Lark webhook：{lark['webhook'][:48]}…")
            log(json.dumps(lark_payload(title, markdown_text), ensure_ascii=False, indent=1)[:1200])
        if email:
            actions.append(f"[dry-run] 将发邮件 → {', '.join(email['to'])}：{title}")
        return actions

    if lark:
        send_lark(lark["webhook"], lark_payload(title, markdown_text), http, secret=lark.get("secret", ""))
        actions.append("✅ Lark 已发送（自定义机器人无法撤回；发错了只能请群管理员删）")
    if email:
        msg = email_message(
            email.get("sender") or email.get("user"), email["to"],
            f"{email.get('subject_prefix', '')}{title}".strip(), markdown_text,
        )
        send_email(email["host"], email.get("port", 465), email.get("user", ""),
                   email.get("password", ""), email.get("sender") or email.get("user"), email["to"], msg)
        actions.append(f"✅ 邮件已发送 → {', '.join(email['to'])}")
    return actions
