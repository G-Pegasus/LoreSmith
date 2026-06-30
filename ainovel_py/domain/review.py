from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimelineEvent:
    chapter: int
    time: str
    event: str
    characters: list[str] = field(default_factory=list)


@dataclass
class ForeshadowEntry:
    id: str
    description: str
    planted_at: int
    status: str
    resolved_at: int = 0


@dataclass
class ForeshadowUpdate:
    id: str
    action: str
    description: str = ""


@dataclass
class RelationshipEntry:
    character_a: str
    character_b: str
    relation: str
    chapter: int


@dataclass
class StateChange:
    entity: str
    field: str
    new_value: str
    chapter: int
    old_value: str = ""
    reason: str = ""


@dataclass
class ConsistencyIssue:
    type: str
    severity: str
    description: str
    evidence: str = ""
    suggestion: str = ""


@dataclass
class DimensionScore:
    dimension: str
    score: int
    verdict: str
    comment: str = ""


@dataclass
class ReviewEntry:
    chapter: int
    scope: str
    issues: list[ConsistencyIssue]
    verdict: str
    summary: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    contract_status: str = ""
    contract_misses: list[str] = field(default_factory=list)
    contract_notes: str = ""
    affected_chapters: list[int] = field(default_factory=list)
