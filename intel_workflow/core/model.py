"""归一化情报对象 —— 所有适配器必须产出这个形状，便于对比与交给模型。"""
import datetime as dt
import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Item:
    rank: int
    title: str
    url: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class Intel:
    platform: str
    kind: str                      # hot | search | profile
    method: str                    # primary | fallback-1 | fallback-2
    source: str                    # 人类可读来源说明（口径可追溯）
    confidence: str                # high | medium | low
    items: list
    region: Optional[str] = None
    query: Optional[str] = None
    caveat: str = ""
    fetched_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    )

    def to_dict(self):
        return asdict(self)

    def to_markdown(self):
        head = [
            f"# {self.platform} · {self.kind}" + (f" · {self.region}" if self.region else ""),
            "",
            f"- 来源：{self.source}",
            f"- 方式：{self.method}　置信度：{self.confidence}",
            f"- 抓取时间：{self.fetched_at}",
        ]
        if self.query:
            head.append(f"- 关键词：{self.query}")
        if self.caveat:
            head.append(f"- ⚠️ 说明：{self.caveat}")
        head += ["", "| # | 条目 | 数据 |", "|---|---|---|"]
        for item in self.items:
            metrics = ", ".join(f"{k}={v}" for k, v in (item.metrics or {}).items()) or "—"
            title = f"[{item.title}]({item.url})" if item.url else item.title
            head.append(f"| {item.rank} | {title} | {metrics} |")
        return "\n".join(head) + "\n"

    def save(self, outdir="out"):
        directory = pathlib.Path(outdir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.date.today().isoformat()
        base = f"{stamp}-{self.platform}-{self.kind}" + (f"-{self.region}" if self.region else "")
        md_path = directory / f"{base}.md"
        jsonl_path = directory / f"{base}.jsonl"
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
        return md_path, jsonl_path
