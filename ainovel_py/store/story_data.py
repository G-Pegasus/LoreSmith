from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from ainovel_py.domain.review import (
    ForeshadowEntry,
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
    flatten_outline,
)
from ainovel_py.domain.writing import (
    ArcSummary,
    ChapterPlan,
    ChapterSummary,
    CharacterSnapshot,
    CharacterVoice,
    VolumeSummary,
    WritingStyleRules,
)
from ainovel_py.store.io import IO


def _pair_key(a: str, b: str) -> str:
    """生成人物关系对的排序键（确保 a|b 和 b|a 相同）"""
    return "|".join(sorted([a, b]))


class OutlineStore:
    """
    大纲存储管理器
    
    负责管理小说大纲相关的数据：
    - premise: 故事前提
    - outline: 扁平章节大纲
    - layered_outline: 分层大纲（卷/篇章/章节）
    - compass: 故事罗盘
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_premise(self, content: str) -> None:
        """保存故事前提"""
        self.io.write_markdown("premise.md", content)

    def load_premise(self) -> str:
        """加载故事前提"""
        try:
            return self.io.read_file("premise.md").decode("utf-8")
        except FileNotFoundError:
            return ""

    def save_outline(self, entries: list[OutlineEntry]) -> None:
        """保存扁平章节大纲"""
        payload = [asdict(x) for x in entries]
        self.io.write_json("outline.json", payload)

    def load_outline(self) -> list[OutlineEntry]:
        """加载扁平章节大纲"""
        try:
            data = self.io.read_json("outline.json")
        except FileNotFoundError:
            return []
        return [
            OutlineEntry(
                chapter=int(x.get("chapter", 0) or 0),
                title=str(x.get("title", "") or ""),
                core_event=str(x.get("core_event", "") or ""),
                hook=str(x.get("hook", "") or ""),
                scenes=[str(s) for s in (x.get("scenes") or [])],
            )
            for x in data
        ]

    def get_chapter_outline(self, chapter: int) -> OutlineEntry | None:
        """获取指定章节的大纲"""
        for item in self.load_outline():
            if item.chapter == chapter:
                return item
        return None

    def save_layered_outline(self, volumes: list[VolumeOutline]) -> None:
        """保存分层大纲（同时更新扁平大纲）"""
        self.io.write_json("layered_outline.json", [asdict(v) for v in volumes])
        self.save_outline(flatten_outline(volumes))

    def load_layered_outline(self) -> list[VolumeOutline]:
        """加载分层大纲"""
        try:
            data = self.io.read_json("layered_outline.json")
        except FileNotFoundError:
            return []
        out: list[VolumeOutline] = []
        for v in data:
            arcs: list[ArcOutline] = []
            for a in v.get("arcs", []) or []:
                chapters = [
                    OutlineEntry(
                        chapter=int(ch.get("chapter", 0) or 0),
                        title=str(ch.get("title", "") or ""),
                        core_event=str(ch.get("core_event", "") or ""),
                        hook=str(ch.get("hook", "") or ""),
                        scenes=[str(s) for s in (ch.get("scenes") or [])],
                    )
                    for ch in (a.get("chapters") or [])
                ]
                arcs.append(
                    ArcOutline(
                        index=int(a.get("index", 0) or 0),
                        title=str(a.get("title", "") or ""),
                        goal=str(a.get("goal", "") or ""),
                        estimated_chapters=int(a.get("estimated_chapters", 0) or 0),
                        chapters=chapters,
                    )
                )
            out.append(
                VolumeOutline(
                    index=int(v.get("index", 0) or 0),
                    title=str(v.get("title", "") or ""),
                    theme=str(v.get("theme", "") or ""),
                    final=bool(v.get("final", False)),
                    arcs=arcs,
                )
            )
        return out

    def save_compass(self, compass: StoryCompass) -> None:
        """保存故事罗盘"""
        self.io.write_json("meta/compass.json", asdict(compass))

    def load_compass(self) -> StoryCompass | None:
        """加载故事罗盘"""
        try:
            data = self.io.read_json("meta/compass.json")
        except FileNotFoundError:
            return None
        return StoryCompass(
            ending_direction=str(data.get("ending_direction", "") or ""),
            open_threads=[str(x) for x in (data.get("open_threads") or [])],
            estimated_scale=str(data.get("estimated_scale", "") or ""),
            last_updated=int(data.get("last_updated", 0) or 0),
        )


class CharacterStore:
    """
    人物存储管理器
    
    负责管理小说中的人物定义数据。
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save(self, chars: list[Character]) -> None:
        """保存人物列表"""
        self.io.write_json("characters.json", [asdict(c) for c in chars])

    def load(self) -> list[Character]:
        """加载人物列表"""
        try:
            data = self.io.read_json("characters.json")
        except FileNotFoundError:
            return []
        return [
            Character(
                name=str(x.get("name", "") or ""),
                aliases=[str(a) for a in (x.get("aliases") or [])],
                role=str(x.get("role", "") or ""),
                description=str(x.get("description", "") or ""),
                arc=str(x.get("arc", "") or ""),
                traits=[str(t) for t in (x.get("traits") or [])],
                tier=str(x.get("tier", "important") or "important"),
            )
            for x in data
        ]


class DraftStore:
    """
    草稿存储管理器
    
    负责管理章节草稿和最终内容：
    - 章节计划（plan）
    - 草稿内容（draft）
    - 最终章节（chapter）
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_chapter_plan(self, plan: ChapterPlan) -> None:
        """保存章节计划"""
        self.io.write_json(f"drafts/{plan.chapter:02d}.plan.json", asdict(plan))

    def load_chapter_plan(self, chapter: int) -> ChapterPlan | None:
        """加载章节计划"""
        try:
            data = self.io.read_json(f"drafts/{chapter:02d}.plan.json")
        except FileNotFoundError:
            return None
        contract = data.get("contract") or {}
        from ainovel_py.domain.writing import ChapterContract

        return ChapterPlan(
            chapter=int(data.get("chapter", 0) or 0),
            title=str(data.get("title", "") or ""),
            goal=str(data.get("goal", "") or ""),
            conflict=str(data.get("conflict", "") or ""),
            hook=str(data.get("hook", "") or ""),
            emotion_arc=str(data.get("emotion_arc", "") or ""),
            notes=str(data.get("notes", "") or ""),
            contract=ChapterContract(
                chapter_direction=str(contract.get("chapter_direction", "") or ""),
                required_beats=[str(x) for x in (contract.get("required_beats") or [])],
                avoid=[str(x) for x in (contract.get("avoid") or [])],
                forbidden_moves=[str(x) for x in (contract.get("forbidden_moves") or [])],
                continuity_checks=[str(x) for x in (contract.get("continuity_checks") or [])],
                evaluation_focus=[str(x) for x in (contract.get("evaluation_focus") or [])],
                emotion_target=str(contract.get("emotion_target", "") or ""),
                payoff_points=[str(x) for x in (contract.get("payoff_points") or [])],
                hook_goal=str(contract.get("hook_goal", "") or ""),
                min_words=int(contract.get("min_words", 1200) or 1200),
                target_words=int(contract.get("target_words", 1800) or 1800),
                max_words=int(contract.get("max_words", 2600) or 2600),
            ),
        )

    def save_draft(self, chapter: int, content: str) -> None:
        """保存章节草稿"""
        self.io.write_markdown(f"drafts/{chapter:02d}.draft.md", content)

    def append_draft(self, chapter: int, content: str) -> None:
        """追加内容到章节草稿"""
        rel = f"drafts/{chapter:02d}.draft.md"
        try:
            existing = self.io.read_file(rel).decode("utf-8")
        except FileNotFoundError:
            existing = ""
        merged = f"{existing}\n\n{content}".strip() if existing else content
        self.io.write_markdown(rel, merged)

    def load_draft(self, chapter: int) -> str:
        """加载章节草稿"""
        try:
            return self.io.read_file(f"drafts/{chapter:02d}.draft.md").decode("utf-8")
        except FileNotFoundError:
            return ""

    def load_chapter_content(self, chapter: int) -> tuple[str, int]:
        """加载章节内容并返回内容和长度"""
        content = self.load_draft(chapter)
        return content, len(content)

    def save_final_chapter(self, chapter: int, content: str) -> None:
        """保存最终章节内容"""
        self.io.write_markdown(f"chapters/{chapter:02d}.md", content)

    def load_chapter_text(self, chapter: int) -> str:
        """加载最终章节内容"""
        try:
            return self.io.read_file(f"chapters/{chapter:02d}.md").decode("utf-8")
        except FileNotFoundError:
            return ""

    def load_chapter_range(self, start: int, end: int, max_runes: int = 2000) -> dict[int, str]:
        """加载指定范围的章节内容（带长度限制）"""
        out: dict[int, str] = {}
        for ch in range(start, end + 1):
            text = self.load_chapter_text(ch)
            if not text:
                continue
            if max_runes > 0 and len(text) > max_runes:
                text = text[:max_runes] + "..."
            out[ch] = text
        return out


class SummaryStore:
    """
    摘要存储管理器
    
    负责管理各级摘要数据：
    - 章节摘要（ChapterSummary）
    - 篇章摘要（ArcSummary）
    - 卷摘要（VolumeSummary）
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_summary(self, summary: ChapterSummary) -> None:
        """保存章节摘要"""
        self.io.write_json(f"summaries/{summary.chapter:02d}.json", asdict(summary))

    def load_summary(self, chapter: int) -> ChapterSummary | None:
        """加载章节摘要"""
        try:
            data = self.io.read_json(f"summaries/{chapter:02d}.json")
        except FileNotFoundError:
            return None
        return ChapterSummary(
            chapter=int(data.get("chapter", 0) or 0),
            summary=str(data.get("summary", "") or ""),
            characters=[str(x) for x in (data.get("characters") or [])],
            key_events=[str(x) for x in (data.get("key_events") or [])],
            emotional_landing=str(data.get("emotional_landing", "") or ""),
            narrative_tone=str(data.get("narrative_tone", "") or ""),
            sensory_anchor=str(data.get("sensory_anchor", "") or ""),
        )

    def load_recent_summaries(self, current: int, count: int) -> list[ChapterSummary]:
        """加载最近的章节摘要"""
        out: list[ChapterSummary] = []
        for ch in range(max(current - count, 1), current):
            item = self.load_summary(ch)
            if item:
                out.append(item)
        return out

    def save_arc_summary(self, summary: ArcSummary) -> None:
        """保存篇章摘要"""
        self.io.write_json(f"summaries/arc-v{summary.volume:02d}a{summary.arc:02d}.json", asdict(summary))

    def save_volume_summary(self, summary: VolumeSummary) -> None:
        """保存卷摘要"""
        self.io.write_json(f"summaries/vol-v{summary.volume:02d}.json", asdict(summary))

    def load_arc_summary(self, volume: int, arc: int) -> ArcSummary | None:
        """加载篇章摘要"""
        try:
            data = self.io.read_json(f"summaries/arc-v{volume:02d}a{arc:02d}.json")
        except FileNotFoundError:
            return None
        return ArcSummary(
            volume=int(data.get("volume", 0) or 0),
            arc=int(data.get("arc", 0) or 0),
            title=str(data.get("title", "") or ""),
            summary=str(data.get("summary", "") or ""),
            key_events=[str(x) for x in (data.get("key_events") or [])],
        )

    def load_arc_summaries(self, volume: int) -> list[ArcSummary]:
        """加载指定卷的所有篇章摘要"""
        out: list[ArcSummary] = []
        for arc in range(1, 21):
            item = self.load_arc_summary(volume, arc)
            if item is not None:
                out.append(item)
        return out

    def load_volume_summary(self, volume: int) -> VolumeSummary | None:
        """加载卷摘要"""
        try:
            data = self.io.read_json(f"summaries/vol-v{volume:02d}.json")
        except FileNotFoundError:
            return None
        return VolumeSummary(
            volume=int(data.get("volume", 0) or 0),
            title=str(data.get("title", "") or ""),
            summary=str(data.get("summary", "") or ""),
            key_events=[str(x) for x in (data.get("key_events") or [])],
        )

    def load_all_volume_summaries(self) -> list[VolumeSummary]:
        """加载所有卷摘要"""
        out: list[VolumeSummary] = []
        for vol in range(1, 21):
            item = self.load_volume_summary(vol)
            if item is not None:
                out.append(item)
        return out


class WorldStore:
    """
    世界设定存储管理器
    
    负责管理小说世界设定相关的数据：
    - world_rules: 世界规则
    - timeline: 时间线事件
    - foreshadow_ledger: 伏笔账本
    - relationship_state: 人物关系状态
    - character_snapshots: 人物快照
    - style_rules: 写作风格规则
    - state_changes: 状态变更记录
    - reviews: 评审结果
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_world_rules(self, rules: list[WorldRule]) -> None:
        """保存世界规则"""
        self.io.write_json("world_rules.json", [asdict(x) for x in rules])

    def save_timeline(self, events: list[TimelineEvent]) -> None:
        """保存时间线事件"""
        self.io.write_json("timeline.json", [asdict(x) for x in events])

    def save_foreshadow_ledger(self, entries: list[ForeshadowEntry]) -> None:
        """保存伏笔账本"""
        self.io.write_json("foreshadow_ledger.json", [asdict(x) for x in entries])

    def save_relationships(self, entries: list[RelationshipEntry]) -> None:
        """保存人物关系状态"""
        self.io.write_json("relationship_state.json", [asdict(x) for x in entries])

    def save_character_snapshots(self, volume: int, arc: int, snapshots: list[CharacterSnapshot]) -> None:
        """保存人物快照（按卷和篇章存储）"""
        payload = [asdict(x) for x in snapshots]
        self.io.write_json(f"meta/snapshots/v{volume:02d}a{arc:02d}.json", payload)

    def load_latest_character_snapshots(self) -> list[CharacterSnapshot]:
        """加载最新的人物快照"""
        latest: tuple[int, int] | None = None
        for vol in range(1, 50):
            for arc in range(1, 50):
                rel = f"meta/snapshots/v{vol:02d}a{arc:02d}.json"
                try:
                    self.io.read_file(rel)
                    latest = (vol, arc)
                except FileNotFoundError:
                    continue
        if latest is None:
            return []
        vol, arc = latest
        data = self.io.read_json(f"meta/snapshots/v{vol:02d}a{arc:02d}.json")
        return [
            CharacterSnapshot(
                volume=int(x.get("volume", vol) or vol),
                arc=int(x.get("arc", arc) or arc),
                name=str(x.get("name", "") or ""),
                status=str(x.get("status", "") or ""),
                power=str(x.get("power", "") or ""),
                motivation=str(x.get("motivation", "") or ""),
                relations=str(x.get("relations", "") or ""),
            )
            for x in data
        ]

    def save_style_rules(self, rules: WritingStyleRules) -> None:
        """保存写作风格规则"""
        self.io.write_json("meta/style_rules.json", asdict(rules))

    def load_style_rules(self) -> WritingStyleRules | None:
        """加载写作风格规则"""
        try:
            data = self.io.read_json("meta/style_rules.json")
        except FileNotFoundError:
            return None
        dialogue = [
            CharacterVoice(name=str(x.get("name", "") or ""), rules=[str(r) for r in (x.get("rules") or [])])
            for x in (data.get("dialogue") or [])
        ]
        return WritingStyleRules(
            volume=int(data.get("volume", 0) or 0),
            arc=int(data.get("arc", 0) or 0),
            prose=[str(x) for x in (data.get("prose") or [])],
            dialogue=dialogue,
            taboos=[str(x) for x in (data.get("taboos") or [])],
            updated_at=str(data.get("updated_at", "") or ""),
        )

    def load_world_rules(self) -> list[WorldRule]:
        """加载世界规则"""
        try:
            data = self.io.read_json("world_rules.json")
        except FileNotFoundError:
            return []
        return [
            WorldRule(
                category=str(x.get("category", "") or ""),
                rule=str(x.get("rule", "") or ""),
                boundary=str(x.get("boundary", "") or ""),
            )
            for x in data
        ]

    def load_timeline(self) -> list[TimelineEvent]:
        """加载时间线事件"""
        try:
            data = self.io.read_json("timeline.json")
        except FileNotFoundError:
            return []
        return [
            TimelineEvent(
                chapter=int(x.get("chapter", 0) or 0),
                time=str(x.get("time", "") or ""),
                event=str(x.get("event", "") or ""),
                characters=[str(c) for c in (x.get("characters") or [])],
            )
            for x in data
        ]

    def append_timeline_events(self, events: list[TimelineEvent]) -> None:
        """追加时间线事件"""
        current = self.load_timeline()
        current.extend(events)
        self.io.write_json("timeline.json", [asdict(x) for x in current])

    def load_foreshadow_ledger(self) -> list[ForeshadowEntry]:
        """加载伏笔账本"""
        try:
            data = self.io.read_json("foreshadow_ledger.json")
        except FileNotFoundError:
            return []
        return [
            ForeshadowEntry(
                id=str(x.get("id", "") or ""),
                description=str(x.get("description", "") or ""),
                planted_at=int(x.get("planted_at", 0) or 0),
                status=str(x.get("status", "") or ""),
                resolved_at=int(x.get("resolved_at", 0) or 0),
            )
            for x in data
        ]

    def update_foreshadow(self, chapter: int, updates: list[ForeshadowUpdate]) -> None:
        """更新伏笔状态（plant/advance/resolve）"""
        items = self.load_foreshadow_ledger()
        idx = {x.id: i for i, x in enumerate(items)}
        for u in updates:
            if u.action == "plant":
                items.append(ForeshadowEntry(id=u.id, description=u.description, planted_at=chapter, status="planted"))
                idx[u.id] = len(items) - 1
            elif u.action == "advance" and u.id in idx:
                items[idx[u.id]].status = "advanced"
            elif u.action == "resolve" and u.id in idx:
                items[idx[u.id]].status = "resolved"
                items[idx[u.id]].resolved_at = chapter
        self.io.write_json("foreshadow_ledger.json", [asdict(x) for x in items])

    def load_active_foreshadow(self) -> list[ForeshadowEntry]:
        """加载未解决的伏笔"""
        return [x for x in self.load_foreshadow_ledger() if x.status != "resolved"]

    def load_relationships(self) -> list[RelationshipEntry]:
        """加载人物关系状态"""
        try:
            data = self.io.read_json("relationship_state.json")
        except FileNotFoundError:
            return []
        return [
            RelationshipEntry(
                character_a=str(x.get("character_a", "") or ""),
                character_b=str(x.get("character_b", "") or ""),
                relation=str(x.get("relation", "") or ""),
                chapter=int(x.get("chapter", 0) or 0),
            )
            for x in data
        ]

    def update_relationships(self, changes: list[RelationshipEntry]) -> None:
        """更新人物关系（更新或新增）"""
        existing = self.load_relationships()
        idx = {_pair_key(x.character_a, x.character_b): i for i, x in enumerate(existing)}
        for c in changes:
            k = _pair_key(c.character_a, c.character_b)
            if k in idx:
                existing[idx[k]] = c
            else:
                existing.append(c)
                idx[k] = len(existing) - 1
        self.io.write_json("relationship_state.json", [asdict(x) for x in existing])

    def load_state_changes(self) -> list[StateChange]:
        """加载状态变更记录"""
        try:
            data = self.io.read_json("meta/state_changes.json")
        except FileNotFoundError:
            return []
        return [
            StateChange(
                entity=str(x.get("entity", "") or ""),
                field=str(x.get("field", "") or ""),
                new_value=str(x.get("new_value", "") or ""),
                chapter=int(x.get("chapter", 0) or 0),
                old_value=str(x.get("old_value", "") or ""),
                reason=str(x.get("reason", "") or ""),
            )
            for x in data
        ]

    def append_state_changes(self, changes: list[StateChange]) -> None:
        """追加状态变更记录"""
        current = self.load_state_changes()
        current.extend(changes)
        self.io.write_json("meta/state_changes.json", [asdict(x) for x in current])

    def save_review(self, review: ReviewEntry) -> None:
        """保存评审结果"""
        suffix = "-global" if review.scope == "global" else ""
        self.io.write_json(f"reviews/{review.chapter:02d}{suffix}.json", asdict(review))

    def load_review(self, chapter: int) -> ReviewEntry | None:
        """加载章节评审结果"""
        try:
            data = self.io.read_json(f"reviews/{chapter:02d}.json")
        except FileNotFoundError:
            return None
        from ainovel_py.tools.parsers import parse_review_entry

        return parse_review_entry(data)

    def load_last_review(self, from_chapter: int) -> ReviewEntry | None:
        """从指定章节向前查找最新的全局评审"""
        from ainovel_py.tools.parsers import parse_review_entry

        for ch in range(from_chapter, 0, -1):
            try:
                data = self.io.read_json(f"reviews/{ch:02d}-global.json")
                return parse_review_entry(data)
            except FileNotFoundError:
                continue
        return None


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
