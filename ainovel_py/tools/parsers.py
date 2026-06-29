from __future__ import annotations

from typing import Any

from ainovel_py.domain.review import (
    ConsistencyIssue,
    DimensionScore,
    ForeshadowUpdate,
    RelationshipEntry,
    ReviewEntry,
    StateChange,
    TimelineEvent,
)
from ainovel_py.domain.story import (
    ArcOutline,
    Character,
    OutlineEntry,
    StoryCompass,
    VolumeOutline,
    WorldRule,
)
from ainovel_py.domain.writing import (
    ArcSummary,
    ChapterContract,
    ChapterPlan,
    CharacterSnapshot,
    CharacterVoice,
    VolumeSummary,
    WritingStyleRules,
)


def parse_outline_entry(data: dict[str, Any]) -> OutlineEntry:
    return OutlineEntry(
        chapter=int(data.get("chapter", 0) or 0),
        title=str(data.get("title", "") or ""),
        core_event=str(data.get("core_event", "") or ""),
        hook=str(data.get("hook", "") or ""),
        scenes=[str(x) for x in (data.get("scenes") or [])],
    )


def parse_volume_outline(data: dict[str, Any]) -> VolumeOutline:
    arcs: list[ArcOutline] = []
    for arc in (data.get("arcs") or []):
        chapters = [parse_outline_entry(ch) for ch in (arc.get("chapters") or [])]
        arcs.append(
            ArcOutline(
                index=int(arc.get("index", 0) or 0),
                title=str(arc.get("title", "") or ""),
                goal=str(arc.get("goal", "") or ""),
                estimated_chapters=int(arc.get("estimated_chapters", 0) or 0),
                chapters=chapters,
            )
        )
    return VolumeOutline(
        index=int(data.get("index", 0) or 0),
        title=str(data.get("title", "") or ""),
        theme=str(data.get("theme", "") or ""),
        final=bool(data.get("final", False)),
        arcs=arcs,
    )


def parse_character(data: dict[str, Any]) -> Character:
    return Character(
        name=str(data.get("name", "") or ""),
        aliases=[str(x) for x in (data.get("aliases") or [])],
        role=str(data.get("role", "") or ""),
        description=str(data.get("description", "") or ""),
        arc=str(data.get("arc", "") or ""),
        traits=[str(x) for x in (data.get("traits") or [])],
        tier=str(data.get("tier", "important") or "important"),
    )


def parse_world_rule(data: dict[str, Any]) -> WorldRule:
    return WorldRule(
        category=str(data.get("category", "") or ""),
        rule=str(data.get("rule", "") or ""),
        boundary=str(data.get("boundary", "") or ""),
    )


def parse_chapter_plan(data: dict[str, Any]) -> ChapterPlan:
    contract_data = data.get("contract") or {}
    contract = ChapterContract(
        chapter_direction=str(contract_data.get("chapter_direction", "") or ""),
        required_beats=[str(x) for x in (contract_data.get("required_beats") or [])],
        avoid=[str(x) for x in (contract_data.get("avoid") or [])],
        forbidden_moves=[str(x) for x in (contract_data.get("forbidden_moves") or [])],
        continuity_checks=[str(x) for x in (contract_data.get("continuity_checks") or [])],
        evaluation_focus=[str(x) for x in (contract_data.get("evaluation_focus") or [])],
        emotion_target=str(contract_data.get("emotion_target", "") or ""),
        payoff_points=[str(x) for x in (contract_data.get("payoff_points") or [])],
        hook_goal=str(contract_data.get("hook_goal", "") or ""),
        min_words=int(contract_data.get("min_words", 1200) or 1200),
        target_words=int(contract_data.get("target_words", 1800) or 1800),
        max_words=int(contract_data.get("max_words", 2600) or 2600),
    )
    return ChapterPlan(
        chapter=int(data.get("chapter", 0) or 0),
        title=str(data.get("title", "") or ""),
        goal=str(data.get("goal", "") or ""),
        conflict=str(data.get("conflict", "") or ""),
        hook=str(data.get("hook", "") or ""),
        emotion_arc=str(data.get("emotion_arc", "") or ""),
        notes=str(data.get("notes", "") or ""),
        contract=contract,
    )


def parse_review_entry(data: dict[str, Any]) -> ReviewEntry:
    issues = [
        ConsistencyIssue(
            type=str(x.get("type", "") or ""),
            severity=str(x.get("severity", "") or ""),
            description=str(x.get("description", "") or ""),
            evidence=str(x.get("evidence", "") or ""),
            suggestion=str(x.get("suggestion", "") or ""),
        )
        for x in (data.get("issues") or [])
    ]
    dimensions = [
        DimensionScore(
            dimension=str(x.get("dimension", "") or ""),
            score=int(x.get("score", 0) or 0),
            verdict=str(x.get("verdict", "") or ""),
            comment=str(x.get("comment", "") or ""),
        )
        for x in (data.get("dimensions") or [])
    ]
    return ReviewEntry(
        chapter=int(data.get("chapter", 0) or 0),
        scope=str(data.get("scope", "") or ""),
        issues=issues,
        dimensions=dimensions,
        contract_status=str(data.get("contract_status", "") or ""),
        contract_misses=[str(x) for x in (data.get("contract_misses") or [])],
        contract_notes=str(data.get("contract_notes", "") or ""),
        verdict=str(data.get("verdict", "") or ""),
        summary=str(data.get("summary", "") or ""),
        affected_chapters=[int(x) for x in (data.get("affected_chapters") or [])],
    )


def parse_timeline_event(data: dict[str, Any], chapter_fallback: int = 0) -> TimelineEvent:
    return TimelineEvent(
        chapter=int(data.get("chapter", chapter_fallback) or chapter_fallback),
        time=str(data.get("time", "") or ""),
        event=str(data.get("event", "") or ""),
        characters=[str(x) for x in (data.get("characters") or [])],
    )


def parse_foreshadow_update(data: dict[str, Any]) -> ForeshadowUpdate:
    return ForeshadowUpdate(
        id=str(data.get("id", "") or "").strip(),
        action=str(data.get("action", "") or "").strip().lower(),
        description=str(data.get("description", "") or "").strip(),
    )


def parse_relationship_entry(data: dict[str, Any], chapter_fallback: int = 0) -> RelationshipEntry:
    return RelationshipEntry(
        character_a=str(data.get("character_a", "") or "").strip(),
        character_b=str(data.get("character_b", "") or "").strip(),
        relation=str(data.get("relation", "") or "").strip(),
        chapter=int(data.get("chapter", chapter_fallback) or chapter_fallback),
    )


def parse_state_change(data: dict[str, Any], chapter_fallback: int = 0) -> StateChange:
    return StateChange(
        entity=str(data.get("entity", "") or ""),
        field=str(data.get("field", "") or ""),
        old_value=str(data.get("old_value", "") or ""),
        new_value=str(data.get("new_value", "") or ""),
        reason=str(data.get("reason", "") or ""),
        chapter=int(data.get("chapter", chapter_fallback) or chapter_fallback),
    )


def parse_arc_summary(data: dict[str, Any]) -> ArcSummary:
    return ArcSummary(
        volume=int(data.get("volume", 0) or 0),
        arc=int(data.get("arc", 0) or 0),
        title=str(data.get("title", "") or ""),
        summary=str(data.get("summary", "") or ""),
        key_events=[str(x) for x in (data.get("key_events") or [])],
    )


def parse_volume_summary(data: dict[str, Any]) -> VolumeSummary:
    return VolumeSummary(
        volume=int(data.get("volume", 0) or 0),
        title=str(data.get("title", "") or ""),
        summary=str(data.get("summary", "") or ""),
        key_events=[str(x) for x in (data.get("key_events") or [])],
    )


def parse_character_snapshot(data: dict[str, Any], volume: int = 0, arc: int = 0) -> CharacterSnapshot:
    return CharacterSnapshot(
        volume=int(data.get("volume", volume) or volume),
        arc=int(data.get("arc", arc) or arc),
        name=str(data.get("name", "") or ""),
        status=str(data.get("status", "") or ""),
        power=str(data.get("power", "") or ""),
        motivation=str(data.get("motivation", "") or ""),
        relations=str(data.get("relations", "") or ""),
    )


def parse_writing_style_rules(data: dict[str, Any], volume: int = 0, arc: int = 0) -> WritingStyleRules:
    dialogue = [
        CharacterVoice(name=str(x.get("name", "") or ""), rules=[str(r) for r in (x.get("rules") or [])])
        for x in (data.get("dialogue") or [])
    ]
    return WritingStyleRules(
        volume=int(data.get("volume", volume) or volume),
        arc=int(data.get("arc", arc) or arc),
        prose=[str(x) for x in (data.get("prose") or [])],
        dialogue=dialogue,
        taboos=[str(x) for x in (data.get("taboos") or [])],
        updated_at=str(data.get("updated_at", "") or ""),
    )


def parse_story_compass(data: dict[str, Any]) -> StoryCompass:
    return StoryCompass(
        ending_direction=str(data.get("ending_direction", "") or ""),
        open_threads=[str(x) for x in (data.get("open_threads") or [])],
        estimated_scale=str(data.get("estimated_scale", "") or ""),
        last_updated=int(data.get("last_updated", 0) or 0),
    )
