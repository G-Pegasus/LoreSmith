from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextSnapshot:
    scope: str = ""
    strategy: str = ""
    active_messages: int = 0
    summary_messages: int = 0
    compacted_count: int = 0
    kept_count: int = 0


@dataclass
class WriterRestorePack:
    recent_summaries: list[str] = field(default_factory=list)
    emotional_landing: str = ""
    narrative_tone: str = ""
    sensory_anchor: str = ""
    style_rules: list[str] = field(default_factory=list)
    foreshadow: list[str] = field(default_factory=list)
    review_lessons: list[str] = field(default_factory=list)

    def refresh(self, context: dict[str, Any]) -> None:
        recent_items = [
            item
            for item in (context.get("recent_summaries") or [])
            if isinstance(item, dict) and str(item.get("summary", "") or "").strip()
        ]
        self.recent_summaries = [str(item.get("summary", "") or "") for item in recent_items][:4]
        latest = recent_items[-1] if recent_items else {}
        self.emotional_landing = str(latest.get("emotional_landing", "") or "").strip()
        self.narrative_tone = str(latest.get("narrative_tone", "") or "").strip()
        self.sensory_anchor = str(latest.get("sensory_anchor", "") or "").strip()
        style = context.get("style_rules") or {}
        self.style_rules = [str(x) for x in (style.get("prose") or []) if str(x).strip()][:5]
        self.foreshadow = [
            f"{item.get('id', '')}:{item.get('description', '')}"
            for item in (context.get("foreshadow_ledger") or [])
            if isinstance(item, dict)
        ][:6]
        latest_review = context.get("latest_review") or {}
        self.review_lessons = [
            str(issue.get("description", "") or "")
            for issue in (latest_review.get("issues") or [])
            if isinstance(issue, dict) and str(issue.get("description", "") or "").strip()
        ][:4]

    def build_text(self) -> str:
        parts: list[str] = []
        resonance: list[str] = []
        if self.emotional_landing:
            resonance.append(f"上一章结束时，读者停留在：{self.emotional_landing}")
        if self.narrative_tone:
            resonance.append(f"上一章主导语调：{self.narrative_tone}")
        if self.sensory_anchor:
            resonance.append(f"可延续或反衬的感官记忆：{self.sensory_anchor}")
        if resonance:
            parts.append("[上一章情感余韵]\n" + "\n".join(f"- {x}" for x in resonance))
        if self.recent_summaries:
            parts.append("[最近章节摘要]\n" + "\n".join(f"- {x}" for x in self.recent_summaries))
        if self.style_rules:
            parts.append("[风格规则]\n" + "\n".join(f"- {x}" for x in self.style_rules))
        if self.foreshadow:
            parts.append("[活跃伏笔]\n" + "\n".join(f"- {x}" for x in self.foreshadow))
        if self.review_lessons:
            parts.append("[最近评审提醒]\n" + "\n".join(f"- {x}" for x in self.review_lessons))
        return "\n\n".join(parts).strip()


@dataclass
class ContextPack:
    summary_block: str = ""
    restore_block: str = ""
    compacted_keys: list[str] = field(default_factory=list)


@dataclass
class ContextManager:
    context_window: int = 128000
    reserve_tokens: int = 32000
    keep_recent_tokens: int = 30000
    snapshots: list[ContextSnapshot] = field(default_factory=list)
    restore: WriterRestorePack = field(default_factory=WriterRestorePack)

    def record(self, snapshot: ContextSnapshot) -> None:
        self.snapshots.append(snapshot)

    def latest(self) -> ContextSnapshot | None:
        if not self.snapshots:
            return None
        return self.snapshots[-1]

    def build_writer_pack(self, context: dict[str, Any]) -> ContextPack:
        self.restore.refresh(context)
        summary_lines: list[str] = []
        compacted: list[str] = []

        premise = str(context.get("premise", "") or "").strip()
        if premise:
            summary_lines.append("[故事前提]\n" + premise[:300])
            compacted.append("premise")

        characters = [
            item for item in (context.get("characters") or [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ][:8]
        if characters:
            summary_lines.append(
                "[主要人物]\n" + "\n".join(
                    f"- {item.get('name', '')} / {item.get('role', '')}: {item.get('description', '')}" for item in characters
                )
            )
            compacted.append("characters")

        world_rules = [
            item for item in (context.get("world_rules") or [])
            if isinstance(item, dict) and str(item.get("rule", "") or "").strip()
        ][:8]
        if world_rules:
            summary_lines.append(
                "[世界规则]\n" + "\n".join(
                    f"- {item.get('category', '')}: {item.get('rule', '')} {item.get('boundary', '')}".strip() for item in world_rules
                )
            )
            compacted.append("world_rules")

        outline = context.get("current_chapter_outline") or {}
        if outline:
            summary_lines.append(
                "[当前章节大纲]\n"
                + f"标题：{outline.get('title', '')}\n"
                + f"核心事件：{outline.get('core_event', '')}\n"
                + f"钩子：{outline.get('hook', '')}"
            )
            compacted.append("current_chapter_outline")

        chapter_plan = context.get("chapter_plan") or {}
        if chapter_plan:
            contract = chapter_plan.get("contract") or {}
            direction = str(contract.get("chapter_direction", "") or chapter_plan.get("goal", "") or "")
            avoid = contract.get("avoid") or contract.get("forbidden_moves") or []
            summary_lines.append(
                "[章节计划]\n"
                + f"方向：{direction}\n"
                + f"情绪：{contract.get('emotion_target', '') or chapter_plan.get('emotion_arc', '')}\n"
                + f"避坑：{', '.join(str(x) for x in avoid[:2])}"
            )
            compacted.append("chapter_plan")

        summary_block = "\n\n".join(summary_lines).strip()
        restore_block = self.restore.build_text()
        return ContextPack(summary_block=summary_block, restore_block=restore_block, compacted_keys=compacted)
