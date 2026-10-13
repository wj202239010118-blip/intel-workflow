"""给当天的新闻做「分类 + 倾向 + 主题走向」——轻量版的群体智能推演。

为什么不直接跑 MiroFish 本体：它是前后端一体的仿真应用（Vue + Flask + Zep Cloud 长期记忆，
官方镜像 8GB+），本机没有 docker、Python 版本也不匹配（它要 ≤3.12）；而且它的产出是**它自己的**
交互沙盘 UI，塞不进我们的日报页面。这里只借它的**思路**：
同一批事实，交给立场不同的角色各自读一遍 → 汇总成倾向（正/负）与主题走向。

引擎：复用 `collab.engines`（优先本机 `claude -p` CLI —— 不碰任何云端 API key）。

三条纪律（同 page.py）：
  · **输出一律英文**（这一页可能被公开访问，只允许 EN / ES）。
  · **只基于给定事实**，不让模型拿记忆补事实。
  · 引擎不可用时**如实失败**，绝不编造分类结果。
"""
import json
import re

SENTIMENTS = ("positive", "negative", "mixed")
KINDS = ("hot", "routine")

PROMPT = """You are an iGaming industry analyst. Below are today's numbered headlines.

For EACH headline decide three things:
- "sentiment": "positive" | "negative" | "mixed"
  Judged for an iGaming operator / affiliate / KOL-agency business:
  a market opening, a favourable ruling, growth = positive;
  a ban, crackdown, fine, licence loss, market shutdown = negative.
- "kind": "hot" | "routine"
  "hot" = regulation & bans, court rulings, M&A, market entry/exit, big fines, major launches.
  "routine" = product/tech, supplier deals, people moves, awards, minor partnerships.
- "why": ONE short English sentence (max 140 characters) justifying those two labels, plain English.

Then summarise by theme: 2-3 English sentences for each theme that actually appears below, saying what
that cluster of news means for the industry right now. Candidate themes (use only the ones present):
regulation, market-entry, M&A, product-tech, people.

Write in English only. Base every judgement on the headlines given; do not add outside facts.

Output STRICT JSON, nothing else (no markdown, no code fences, no commentary):
{"items":[{"i":1,"sentiment":"positive","kind":"hot","why":"..."}],
 "themes":[{"name":"regulation","summary":"..."}]}

Headlines:
"""


def _render(rows):
    lines = []
    for idx, row in enumerate(rows, 1):
        bits = [f'{idx}. {row.get("title", "")}', f'[{row.get("site", "")}]']
        summary = (row.get("summary") or "")[:300]
        if summary:
            bits.append(summary)
        lines.append(" ".join(bits))
    return "\n".join(lines)


def _parse(raw):
    """引擎可能包 ```json 围栏或加闲话 —— 只取最外层 JSON 对象。"""
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"引擎没返回 JSON：{(raw or '')[:160]}")
    return json.loads(text[start:end + 1])


def analyze(rows, engine):
    """rows（[{title,site,time,summary}]）→ {"items":[{sentiment,kind,why}×N], "themes":[...]}。

    `engine` 是 `collab.engines.available(cfg)` 里的某个可调用；由调用方决定用哪个引擎。
    """
    if not rows:
        return {"items": [], "themes": []}

    data = _parse(engine(PROMPT + _render(rows)))

    by_index = {}
    for item in data.get("items") or []:
        try:
            by_index[int(item.get("i"))] = item
        except (TypeError, ValueError):
            continue

    items = []
    for idx in range(1, len(rows) + 1):
        got = by_index.get(idx) or {}
        sentiment = got.get("sentiment") if got.get("sentiment") in SENTIMENTS else "mixed"
        kind = got.get("kind") if got.get("kind") in KINDS else "routine"
        items.append({"sentiment": sentiment, "kind": kind,
                      "why": str(got.get("why") or "")[:200]})

    themes = [{"name": str(t.get("name") or "").strip(),
               "summary": str(t.get("summary") or "").strip()}
              for t in (data.get("themes") or [])
              if str(t.get("summary") or "").strip()]

    return {"items": items, "themes": themes}
