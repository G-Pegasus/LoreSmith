from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ScopeKind:
    CHAPTER = "chapter"
    ARC = "arc"
    VOLUME = "volume"
    GLOBAL = "global"


@dataclass
class Scope:
    kind: str
    chapter: int = 0
    volume: int = 0
    arc: int = 0

    def matches(self, other: "Scope") -> bool:
        if self.kind != other.kind:
            return False
        if self.kind == ScopeKind.CHAPTER:
            return self.chapter == other.chapter
        if self.kind == ScopeKind.ARC:
            return self.volume == other.volume and self.arc == other.arc
        if self.kind == ScopeKind.VOLUME:
            return self.volume == other.volume
        return True


def chapter_scope(chapter: int) -> Scope:
    return Scope(kind=ScopeKind.CHAPTER, chapter=chapter)


def arc_scope(volume: int, arc: int) -> Scope:
    return Scope(kind=ScopeKind.ARC, volume=volume, arc=arc)


def volume_scope(volume: int) -> Scope:
    return Scope(kind=ScopeKind.VOLUME, volume=volume)


def global_scope() -> Scope:
    return Scope(kind=ScopeKind.GLOBAL)


@dataclass
class Checkpoint:
    seq: int
    scope: Scope
    step: str
    artifact: str = ""
    digest: str = ""
    occurred_at: datetime = datetime.utcnow()
