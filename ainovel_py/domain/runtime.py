from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Phase:
    INIT = "init"
    PREMISE = "premise"
    OUTLINE = "outline"
    WRITING = "writing"
    COMPLETE = "complete"


class FlowState:
    WRITING = "writing"
    REVIEWING = "reviewing"
    REWRITING = "rewriting"
    POLISHING = "polishing"
    STEERING = "steering"


@dataclass
class Progress:
    novel_name: str = ""
    phase: str = Phase.INIT
    current_chapter: int = 0
    total_chapters: int = 0
    completed_chapters: list[int] = field(default_factory=list)
    total_word_count: int = 0
    chapter_word_counts: dict[int, int] = field(default_factory=dict)
    in_progress_chapter: int = 0
    completed_scenes: list[int] = field(default_factory=list)
    flow: str = ""
    pending_rewrites: list[int] = field(default_factory=list)
    rewrite_reason: str = ""
    strand_history: list[str] = field(default_factory=list)
    hook_history: list[str] = field(default_factory=list)
    current_volume: int = 0
    current_arc: int = 0
    layered: bool = False

    def is_resumable(self) -> bool:
        return self.phase == Phase.WRITING and self.current_chapter > 0

    def next_chapter(self) -> int:
        if not self.completed_chapters:
            return 1
        return max(self.completed_chapters) + 1


@dataclass
class SteerEntry:
    input: str
    timestamp: str


@dataclass
class RunMeta:
    started_at: str = ""
    provider: str = ""
    style: str = ""
    model: str = ""
    story_title: str = ""
    genre: str = ""
    min_words: int = 1200
    target_words: int = 1800
    max_words: int = 2600
    planning_tier: str = ""
    steer_history: list[SteerEntry] = field(default_factory=list)
    pending_steer: str = ""


def extract_novel_name_from_premise(premise: str) -> str:
    for raw in premise.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("# "):
            return ""
        return line[2:].strip()
    return ""


def normalize_planning_tier(value: Any) -> str:
    tier = str(value or "").strip().lower()
    return tier if tier in {"short", "mid", "long"} else ""


def infer_planning_tier(progress: Progress | None, has_layered_outline: bool, has_compass: bool) -> str:
    if progress and progress.layered:
        return "long"
    if has_layered_outline or has_compass:
        return "long"
    total = progress.total_chapters if progress else 0
    if 1 <= total <= 25:
        return "short"
    if total >= 80:
        return "long"
    return "mid"
