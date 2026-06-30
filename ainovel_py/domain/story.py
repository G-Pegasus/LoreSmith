from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OutlineEntry:
    chapter: int
    title: str
    core_event: str
    hook: str = ""
    scenes: list[str] = field(default_factory=list)


@dataclass
class Character:
    name: str
    aliases: list[str] = field(default_factory=list)
    role: str = ""
    description: str = ""
    arc: str = ""
    traits: list[str] = field(default_factory=list)
    tier: str = "important"


@dataclass
class ArcOutline:
    index: int
    title: str
    goal: str
    estimated_chapters: int = 0
    chapters: list[OutlineEntry] = field(default_factory=list)

    def is_expanded(self) -> bool:
        return len(self.chapters) > 0


@dataclass
class VolumeOutline:
    index: int
    title: str
    theme: str
    final: bool = False
    arcs: list[ArcOutline] = field(default_factory=list)


@dataclass
class StoryCompass:
    ending_direction: str
    open_threads: list[str] = field(default_factory=list)
    estimated_scale: str = ""
    last_updated: int = 0


@dataclass
class WorldRule:
    category: str
    rule: str
    boundary: str = ""


def flatten_outline(volumes: list[VolumeOutline]) -> list[OutlineEntry]:
    out: list[OutlineEntry] = []
    chapter = 1
    for vol in volumes:
        for arc in vol.arcs:
            for item in arc.chapters:
                out.append(
                    OutlineEntry(
                        chapter=chapter,
                        title=item.title,
                        core_event=item.core_event,
                        hook=item.hook,
                        scenes=list(item.scenes),
                    )
                )
                chapter += 1
    return out


def total_chapters(volumes: list[VolumeOutline]) -> int:
    return len(flatten_outline(volumes))
