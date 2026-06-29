from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.domain.commit import CommitStage, PendingCommit
from ainovel_py.domain.review import (
    ForeshadowUpdate,
    RelationshipEntry,
    StateChange,
    TimelineEvent,
)
from ainovel_py.domain.writing import ChapterSummary, CommitResult, OutlineFeedback
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import (
    parse_foreshadow_update,
    parse_relationship_entry,
    parse_state_change,
    parse_timeline_event,
)


class CommitChapterTool:
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "commit_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = int(args.get("chapter", 0) or 0)
        if chapter <= 0:
            raise ValueError("chapter must be > 0")

        if self.store.progress.is_chapter_completed(chapter):
            pending = self.store.signals.load_pending_commit()
            if pending is not None and pending.chapter == chapter:
                self.store.signals.clear_pending_commit()

            progress = self.store.progress.load()
            if progress and progress.flow in {"rewriting", "polishing"} and chapter in progress.pending_rewrites:
                self.store.progress.complete_rewrite(chapter)
                return {
                    "chapter": chapter,
                    "skipped": True,
                    "reason": f"第 {chapter} 章已完成，标记为重写/打磨完成",
                    "next_step": "已退出该章节重写队列，请继续下一章",
                }

            return {
                "chapter": chapter,
                "skipped": True,
                "reason": f"第 {chapter} 章已提交完成，无需重复提交",
                "next_step": "该章节已完成，请继续写下一章",
            }

        existing_pending = self.store.signals.load_pending_commit()
        if existing_pending is not None and existing_pending.chapter != chapter:
            raise ValueError(
                f"存在未恢复的章节提交：第 {existing_pending.chapter} 章（阶段 {existing_pending.stage}），请先恢复或重新提交该章"
            )

        content, word_count = self.store.drafts.load_chapter_content(chapter)
        if not content:
            raise ValueError(f"no content found for chapter {chapter}")

        summary_text = str(args.get("summary", "") or "").strip()
        if not summary_text:
            raise ValueError("summary is required")

        now = datetime.now(timezone.utc).isoformat()
        pending = PendingCommit(
            chapter=chapter,
            stage=CommitStage.STARTED,
            summary=summary_text,
            hook_type=str(args.get("hook_type", "") or ""),
            dominant_strand=str(args.get("dominant_strand", "") or ""),
            started_at=now,
            updated_at=now,
        )
        self.store.signals.save_pending_commit(pending)

        self.store.drafts.save_final_chapter(chapter, content)

        summary = ChapterSummary(
            chapter=chapter,
            summary=summary_text,
            characters=[str(x) for x in (args.get("characters") or [])],
            key_events=[str(x) for x in (args.get("key_events") or [])],
            emotional_landing=str(args.get("emotional_landing", "") or ""),
            narrative_tone=str(args.get("narrative_tone", "") or ""),
            sensory_anchor=str(args.get("sensory_anchor", "") or ""),
        )
        self.store.summaries.save_summary(summary)

        timeline_events = [
            parse_timeline_event(x, chapter_fallback=chapter)
            for x in (args.get("timeline_events") or [])
            if isinstance(x, dict)
        ]
        if timeline_events:
            for e in timeline_events:
                e.chapter = chapter
            self.store.world.append_timeline_events(timeline_events)

        foreshadow_updates = [
            parse_foreshadow_update(x)
            for x in (args.get("foreshadow_updates") or [])
            if isinstance(x, dict)
        ]
        foreshadow_updates = [
            x
            for x in foreshadow_updates
            if x.id and x.action in {"plant", "advance", "resolve"} and (x.action != "plant" or bool(x.description))
        ]
        if foreshadow_updates:
            self.store.world.update_foreshadow(chapter, foreshadow_updates)

        relationship_changes = [
            parse_relationship_entry(x, chapter_fallback=chapter)
            for x in (args.get("relationship_changes") or [])
            if isinstance(x, dict)
        ]
        relationship_changes = [x for x in relationship_changes if x.character_a and x.character_b and x.relation]
        if relationship_changes:
            for e in relationship_changes:
                e.chapter = chapter
            self.store.world.update_relationships(relationship_changes)

        state_changes = [
            parse_state_change(x, chapter_fallback=chapter)
            for x in (args.get("state_changes") or [])
            if isinstance(x, dict)
        ]
        if state_changes:
            for s in state_changes:
                s.chapter = chapter
            self.store.world.append_state_changes(state_changes)

        pending.stage = CommitStage.STATE_APPLIED
        pending.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.signals.save_pending_commit(pending)

        hook_type = str(args.get("hook_type", "") or "")
        dominant_strand = str(args.get("dominant_strand", "") or "")
        self.store.progress.mark_chapter_complete(
            chapter=chapter,
            word_count=word_count,
            hook_type=hook_type,
            dominant_strand=dominant_strand,
        )

        pending.stage = CommitStage.PROGRESS_MARKED
        pending.updated_at = datetime.now(timezone.utc).isoformat()

        progress = self.store.progress.load()
        review_required = False
        review_reason = ""

        feedback_raw = args.get("feedback")
        feedback = None
        if isinstance(feedback_raw, dict):
            dev = str(feedback_raw.get("deviation", "") or "")
            sug = str(feedback_raw.get("suggestion", "") or "")
            if dev or sug:
                feedback = OutlineFeedback(deviation=dev, suggestion=sug)

        result = CommitResult(
            chapter=chapter,
            committed=True,
            word_count=word_count,
            next_chapter=chapter + 1,
            review_required=review_required,
            review_reason=review_reason,
            hook_type=hook_type,
            dominant_strand=dominant_strand,
        )

        hints: list[str] = []
        if feedback and feedback.deviation:
            hints.append(
                f"[系统] writer_feedback: Writer 在第 {chapter} 章发现大纲偏离。偏离：{feedback.deviation}。建议：{feedback.suggestion}。"
            )

        if progress and progress.flow in {"rewriting", "polishing"}:
            verb = "打磨" if progress.flow == "polishing" else "重写"
            remaining = [x for x in progress.pending_rewrites if x != chapter]
            self.store.progress.complete_rewrite(chapter)
            if remaining:
                hints.append(f"[系统] {verb}完成: 第 {chapter} 章已完成{verb}。剩余待处理章节: {remaining}。")
            else:
                hints.append(f"[系统] {verb}全部完成: 第 {chapter} 章已完成{verb}，继续写第 {chapter + 1} 章。")
        else:
            if progress and progress.total_chapters > 0:
                hints.append(
                    f"[系统] continue: 第 {chapter} 章提交成功（{word_count} 字）。请继续写第 {chapter + 1} 章（共 {progress.total_chapters} 章）。"
                )
            else:
                hints.append(
                    f"[系统] continue: 第 {chapter} 章提交成功（{word_count} 字）。请继续写第 {chapter + 1} 章。"
                )

        result.system_hints = hints

        payload = asdict(result)
        if feedback:
            payload["feedback"] = asdict(feedback)

        pending.result = payload
        pending.stage = CommitStage.SIGNAL_SAVED
        pending.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.signals.save_pending_commit(pending)
        self.store.signals.save_last_commit(payload)

        self.store.progress.clear_in_progress()
        self.store.signals.clear_pending_commit()

        self.store.checkpoints.append(
            chapter_scope(chapter),
            "commit",
            artifact=f"chapters/ch{chapter:02d}.md",
        )
        return payload
