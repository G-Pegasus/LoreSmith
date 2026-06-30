from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StreamChunk:
    channel: str = "content"
    delta: str = ""


@dataclass
class Event:
    time: datetime = field(default_factory=datetime.now)
    category: str = "SYSTEM"
    summary: str = ""
    level: str = "info"


def build_start_prompt(prompt: str) -> str:
    text = prompt.strip()
    return (
        "请根据以下创作要求开始创作一部小说。进入规划后，Premise 第一行必须输出 `# 书名`。"
        "章节数量由你根据故事需要自行决定。\n\n[创作要求]\n"
        + text
        + "\n\n若某些细节未明确，请在不违背用户方向的前提下自行补全。"
    )


@dataclass
class UISnapshot:
    provider: str = ""
    model_name: str = ""
    style: str = ""
    runtime_state: str = ""
    status_label: str = ""
    phase: str = ""
    flow: str = ""
    current_chapter: int = 0
    total_chapters: int = 0
    completed_count: int = 0
    total_word_count: int = 0
    pending_rewrites: list[int] = field(default_factory=list)
    rewrite_reason: str = ""
    pending_steer: str = ""
    premise: str = ""
    outline: list[dict[str, Any]] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    recent_summaries: list[str] = field(default_factory=list)
    last_review_summary: str = ""
    backend: str = ""
    context_window: int = 0
    context_tokens: int = 0
    context_percent: float = 0.0
    agent_status: list[str] = field(default_factory=list)


def replay_stream_chunk(payload: object) -> StreamChunk | None:
    if not isinstance(payload, dict):
        return None
    delta = payload.get("delta")
    if not isinstance(delta, str) or not delta:
        return None
    channel = str(payload.get("channel", "content") or "content").strip().lower()
    if channel not in {"content", "thinking"}:
        channel = "content"
    return StreamChunk(channel=channel, delta=delta)


def replay_delta_text(payload: object) -> str:
    chunk = replay_stream_chunk(payload)
    if chunk is None:
        return ""
    return chunk.delta
