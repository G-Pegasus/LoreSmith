from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChapterContract:
    chapter_direction: str = ""
    required_beats: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    forbidden_moves: list[str] = field(default_factory=list)
    continuity_checks: list[str] = field(default_factory=list)
    evaluation_focus: list[str] = field(default_factory=list)
    emotion_target: str = ""
    payoff_points: list[str] = field(default_factory=list)
    hook_goal: str = ""
    min_words: int = 1200
    target_words: int = 1800
    max_words: int = 2600


@dataclass
class ChapterPlan:
    chapter: int
    title: str
    goal: str
    conflict: str
    hook: str
    emotion_arc: str = ""
    notes: str = ""
    contract: ChapterContract = field(default_factory=ChapterContract)


@dataclass
class PendingRunCheckpoint:
    pause_after_chapter: int
    next_chapter: int
    completed_count: int
    status: str = "awaiting_confirmation"


@dataclass
class ChapterSummary:
    chapter: int
    summary: str
    characters: list[str] = field(default_factory=list)
    key_events: list[str] = field(default_factory=list)
    emotional_landing: str = ""
    narrative_tone: str = ""
    sensory_anchor: str = ""


@dataclass
class ArcSummary:
    volume: int
    arc: int
    title: str
    summary: str
    key_events: list[str] = field(default_factory=list)


@dataclass
class VolumeSummary:
    volume: int
    title: str
    summary: str
    key_events: list[str] = field(default_factory=list)


@dataclass
class CharacterVoice:
    name: str
    rules: list[str] = field(default_factory=list)


@dataclass
class CharacterSnapshot:
    volume: int
    arc: int
    name: str
    status: str
    power: str = ""
    motivation: str = ""
    relations: str = ""


@dataclass
class WritingStyleRules:
    volume: int
    arc: int
    prose: list[str] = field(default_factory=list)
    dialogue: list[CharacterVoice] = field(default_factory=list)
    taboos: list[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class OutlineFeedback:
    deviation: str
    suggestion: str


@dataclass
class CommitResult:
    chapter: int
    committed: bool
    word_count: int
    next_chapter: int
    review_required: bool = False
    review_reason: str = ""
    hook_type: str = ""
    dominant_strand: str = ""
    system_hints: list[str] = field(default_factory=list)
