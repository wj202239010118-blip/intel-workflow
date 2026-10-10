"""交叉复核：事实 → 各引擎独立分析 → 结构化对齐（一致 / 分歧 / 单侧）→ 报告。

注意：本模块不做语义判断，只做「结构化对齐」——一致 = 两边 key_findings 归一化后相同；
其余归入分歧/单侧。真正的取舍交给读报告的人（或调用方 agent）。
"""
import datetime as dt
import json
import re

from . import engines


def build_prompt(facts, max_chars=8000):
    payload = [
        {
            "platform": f.platform, "kind": f.kind, "region": f.region,
            "source": f.source, "method": f.method, "confidence": f.confidence,
            "caveat": f.caveat,
            "items": [{"rank": i.rank, "title": i.title, "metrics": i.metrics} for i in f.items[:15]],
        }
        for f in facts
    ]
    text = json.dumps(payload, ensure_ascii=False)
    return engines.CONTRACT + "\n\n情报事实（JSON）：\n" + text[:max_chars]


def _extract_json(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    for candidate in (match.group(0), match.group(0).replace("\n", " ")):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _norm(text):
    return re.sub(r"[\s，。,.、:：\-—–]+", "", str(text)).lower()


def analyze(facts, cfg, main=None, single=False):
    picked = engines.available(cfg)
    if not picked:
        return None, (
            "两端都不可用：装 Claude Code（需登录）或 codex，"
            "或在 config.toml 的 [collab] 填 OpenAI 兼容端（缺 codex 时的等价替代）"
        )
    if single:
        picked = dict(list(picked.items())[:1])

    prompt = build_prompt(facts)
    results = {}
    for name, call in picked.items():
        try:
            raw = call(prompt)
            results[name] = {"parsed": _extract_json(raw), "raw": raw[:1500]}
        except Exception as exc:  # noqa: BLE001 - 单端失败不影响另一端
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return _merge(results, main=main), None


def _merge(results, main=None):
    findings = {}
    for name, payload in results.items():
        parsed = payload.get("parsed") or {}
        for item in parsed.get("key_findings", []) or []:
            findings.setdefault(_norm(item), []).append((name, item))

    agree, disagree = [], []
    for _, pairs in findings.items():
        if len(pairs) > 1:
            agree.append(pairs)
        else:
            disagree.append(pairs)

    return {
        "fetched_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "engines": list(results),
        "successful": [name for name, payload in results.items() if payload.get("parsed")],
        "main": main,
        "mode": "cross" if sum(1 for p in results.values() if p.get("parsed")) > 1 else "single-model",
        "results": results,
        "agree": agree,
        "disagree": disagree,
    }


def to_markdown(report, facts):
    lines = [
        "# 情报 · 双模型交叉复核",
        "",
        f"- 时间：{report['fetched_at']}",
        f"- 引擎：{', '.join(report['engines'])}　模式：{report['mode']}"
        + (f"（主：{report['main']}）" if report.get("main") else ""),
        "",
        "## 一、事实（来自平台实测）",
        "",
        "| 平台 | 条数 | 来源 | 置信度 | 说明 |",
        "|---|---|---|---|---|",
    ]
    if report["mode"] == "single-model" and len(report["engines"]) > 1:
        lines += ["", "> ⚠️ 另一个引擎没有产出（见第二节错误行）—— 本次不是真正的交叉复核。", ""]
    for fact in facts:
        lines.append(
            f"| {fact.platform} | {len(fact.items)} | {fact.source} | {fact.confidence} | {fact.caveat or '—'} |"
        )

    lines += ["", "## 二、各引擎结论", ""]
    for name, payload in report["results"].items():
        lines.append(f"### {name}")
        if payload.get("error"):
            lines += [f"- ❌ {payload['error']}", ""]
            continue
        parsed = payload.get("parsed")
        if not parsed:
            lines += ["- ⚠️ 未能解析出结构化结论，原始输出：", "", "```", payload.get("raw", "")[:600], "```", ""]
            continue
        for item in parsed.get("key_findings", []):
            lines.append(f"- 结论：{item}")
        for item in parsed.get("caveats", []):
            lines.append(f"- 存疑：{item}")
        for item in parsed.get("questions", []):
            lines.append(f"- 待确认：{item}")
        lines.append("")

    lines += ["## 三、一致 / 分歧", "", f"**一致项（{len(report['agree'])}）**", ""]
    lines += [f"- {pairs[0][1]}　" + "（" + " / ".join(n for n, _ in pairs) + "）" for pairs in report["agree"]] or ["- （无）"]
    lines += ["", f"**单侧项（{len(report['disagree'])}）** —— 只有一个引擎提到，需人工判断", ""]
    lines += [f"- [{n}] {t}" for pairs in report["disagree"] for n, t in pairs] or ["- （无）"]
    lines += ["", "> 本报告只做结构化对齐，不做语义取舍；结论请结合第四节的来源与置信度判断。"]
    return "\n".join(lines) + "\n"
