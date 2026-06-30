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
    """
    章节提交工具
    
    负责完成章节的最终提交流程，是小说创作流程中的关键工具。
    该工具实现了完整的原子提交机制，确保提交过程的可靠性。
    
    核心职责：
    1. 保存最终章节内容到持久化存储
    2. 保存章节摘要（用于上下文管理和后续章节生成）
    3. 更新时间线事件（记录故事时间线）
    4. 更新伏笔状态（种植/推进/回收伏笔）
    5. 更新人物关系（记录人物间关系变化）
    6. 更新状态变化记录（记录场景/物品等状态变化）
    7. 标记章节完成并更新整体进度
    8. 生成系统提示（指导下一步动作）
    
    原子性保障：
    使用 PendingCommit 机制确保提交过程的原子性。
    如果提交过程中发生崩溃，系统可以从 PendingCommit 恢复。
    """
    def __init__(self, store: Store) -> None:
        """
        初始化工具
        
        Args:
            store: 存储接口，提供数据持久化能力
        """
        self.store = store

    def name(self) -> str:
        """返回工具名称，用于工具注册和调用"""
        return "commit_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行章节提交（核心方法）
        
        提交流程分为四个阶段：
        1. 前置校验阶段：检查章节状态、加载内容
        2. 数据持久化阶段：保存章节内容、摘要、世界状态
        3. 进度更新阶段：标记章节完成、更新进度
        4. 结果处理阶段：生成系统提示、清理状态、记录检查点
        
        Args:
            args: 参数字典，包含以下字段：
                - chapter: int, 章节号（必填）
                - summary: str, 章节摘要（必填）
                - characters: list[str], 涉及人物列表
                - key_events: list[str], 关键事件列表
                - timeline_events: list[dict], 时间线事件
                - foreshadow_updates: list[dict], 伏笔更新（plant/advance/resolve）
                - relationship_changes: list[dict], 人物关系变化
                - state_changes: list[dict], 状态变化记录
                - hook_type: str, 章末钩子类型（mystery/twist/cliffhanger等）
                - dominant_strand: str, 主导情节线（quest/character/theme等）
                - feedback: dict, 大纲反馈（可选）
        
        Returns:
            dict[str, Any]: 提交结果字典，包含：
                - chapter: 章节号
                - committed: 是否提交成功
                - word_count: 章节字数
                - next_chapter: 下一章章节号
                - review_required: 是否需要评审
                - review_reason: 评审原因
                - hook_type: 钩子类型
                - dominant_strand: 主导情节线
                - system_hints: 系统提示列表（指导下一步动作）
        """
        # ========== 阶段1：前置校验 ==========
        
        # 1.1 解析并校验章节号
        chapter = int(args.get("chapter", 0) or 0)
        if chapter <= 0:
            raise ValueError("chapter must be > 0")

        # 1.2 检查章节是否已完成（避免重复提交）
        if self.store.progress.is_chapter_completed(chapter):
            # 清理可能存在的待提交记录
            pending = self.store.signals.load_pending_commit()
            if pending is not None and pending.chapter == chapter:
                self.store.signals.clear_pending_commit()

            # 如果是重写/打磨模式，标记重写完成
            progress = self.store.progress.load()
            if progress and progress.flow in {"rewriting", "polishing"} and chapter in progress.pending_rewrites:
                self.store.progress.complete_rewrite(chapter)
                return {
                    "chapter": chapter,
                    "skipped": True,
                    "reason": f"第 {chapter} 章已完成，标记为重写/打磨完成",
                    "next_step": "已退出该章节重写队列，请继续下一章",
                }

            # 普通完成状态，直接返回跳过
            return {
                "chapter": chapter,
                "skipped": True,
                "reason": f"第 {chapter} 章已提交完成，无需重复提交",
                "next_step": "该章节已完成，请继续写下一章",
            }

        # 1.3 检查是否存在其他未完成的提交（防止状态混乱）
        existing_pending = self.store.signals.load_pending_commit()
        if existing_pending is not None and existing_pending.chapter != chapter:
            raise ValueError(
                f"存在未恢复的章节提交：第 {existing_pending.chapter} 章（阶段 {existing_pending.stage}），请先恢复或重新提交该章"
            )

        # 1.4 加载章节内容（必须存在才能提交）
        content, word_count = self.store.drafts.load_chapter_content(chapter)
        if not content:
            raise ValueError(f"no content found for chapter {chapter}")

        # 1.5 获取并校验章节摘要（必填字段）
        summary_text = str(args.get("summary", "") or "").strip()
        if not summary_text:
            raise ValueError("summary is required")

        # ========== 阶段2：创建待提交记录（原子性保障） ==========
        
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
        # 保存待提交记录，用于崩溃恢复
        self.store.signals.save_pending_commit(pending)

        # ========== 阶段3：数据持久化 ==========
        
        # 3.1 保存最终章节内容
        self.store.drafts.save_final_chapter(chapter, content)

        # 3.2 保存章节摘要（用于后续章节的上下文生成）
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

        # 3.3 更新时间线事件
        timeline_events = [
            parse_timeline_event(x, chapter_fallback=chapter)
            for x in (args.get("timeline_events") or [])
            if isinstance(x, dict)
        ]
        if timeline_events:
            for e in timeline_events:
                e.chapter = chapter  # 确保章节号正确
            self.store.world.append_timeline_events(timeline_events)

        # 3.4 更新伏笔状态（种植/推进/回收）
        foreshadow_updates = [
            parse_foreshadow_update(x)
            for x in (args.get("foreshadow_updates") or [])
            if isinstance(x, dict)
        ]
        # 过滤有效伏笔更新：必须有ID、有效动作、种植时必须有描述
        foreshadow_updates = [
            x
            for x in foreshadow_updates
            if x.id and x.action in {"plant", "advance", "resolve"} and (x.action != "plant" or bool(x.description))
        ]
        if foreshadow_updates:
            self.store.world.update_foreshadow(chapter, foreshadow_updates)

        # 3.5 更新人物关系变化
        relationship_changes = [
            parse_relationship_entry(x, chapter_fallback=chapter)
            for x in (args.get("relationship_changes") or [])
            if isinstance(x, dict)
        ]
        # 过滤有效关系变化：必须有双方人物和关系类型
        relationship_changes = [x for x in relationship_changes if x.character_a and x.character_b and x.relation]
        if relationship_changes:
            for e in relationship_changes:
                e.chapter = chapter  # 确保章节号正确
            self.store.world.update_relationships(relationship_changes)

        # 3.6 更新状态变化记录
        state_changes = [
            parse_state_change(x, chapter_fallback=chapter)
            for x in (args.get("state_changes") or [])
            if isinstance(x, dict)
        ]
        if state_changes:
            for s in state_changes:
                s.chapter = chapter  # 确保章节号正确
            self.store.world.append_state_changes(state_changes)

        # 更新待提交记录状态：世界状态已应用
        pending.stage = CommitStage.STATE_APPLIED
        pending.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.signals.save_pending_commit(pending)

        # ========== 阶段4：进度更新 ==========
        
        # 4.1 获取钩子类型和主导情节线
        hook_type = str(args.get("hook_type", "") or "")
        dominant_strand = str(args.get("dominant_strand", "") or "")
        
        # 4.2 标记章节完成
        self.store.progress.mark_chapter_complete(
            chapter=chapter,
            word_count=word_count,
            hook_type=hook_type,
            dominant_strand=dominant_strand,
        )

        # 更新待提交记录状态：进度已标记
        pending.stage = CommitStage.PROGRESS_MARKED
        pending.updated_at = datetime.now(timezone.utc).isoformat()

        # ========== 阶段5：结果处理 ==========
        
        # 5.1 加载最新进度
        progress = self.store.progress.load()
        review_required = False
        review_reason = ""

        # 5.2 解析大纲反馈（如果有）
        feedback_raw = args.get("feedback")
        feedback = None
        if isinstance(feedback_raw, dict):
            dev = str(feedback_raw.get("deviation", "") or "")
            sug = str(feedback_raw.get("suggestion", "") or "")
            if dev or sug:
                feedback = OutlineFeedback(deviation=dev, suggestion=sug)

        # 5.3 构建提交结果对象
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

        # 5.4 生成系统提示（指导下一步动作）
        hints: list[str] = []
        
        # 如果有大纲偏离反馈，添加提示
        if feedback and feedback.deviation:
            hints.append(
                f"[系统] writer_feedback: Writer 在第 {chapter} 章发现大纲偏离。偏离：{feedback.deviation}。建议：{feedback.suggestion}。"
            )

        # 根据当前流程状态生成提示
        if progress and progress.flow in {"rewriting", "polishing"}:
            verb = "打磨" if progress.flow == "polishing" else "重写"
            remaining = [x for x in progress.pending_rewrites if x != chapter]
            self.store.progress.complete_rewrite(chapter)
            if remaining:
                hints.append(f"[系统] {verb}完成: 第 {chapter} 章已完成{verb}。剩余待处理章节: {remaining}。")
            else:
                hints.append(f"[系统] {verb}全部完成: 第 {chapter} 章已完成{verb}，继续写第 {chapter + 1} 章。")
        else:
            # 正常写作流程
            if progress and progress.total_chapters > 0:
                hints.append(
                    f"[系统] continue: 第 {chapter} 章提交成功（{word_count} 字）。请继续写第 {chapter + 1} 章（共 {progress.total_chapters} 章）。"
                )
            else:
                hints.append(
                    f"[系统] continue: 第 {chapter} 章提交成功（{word_count} 字）。请继续写第 {chapter + 1} 章。"
                )

        # 将提示添加到结果中
        result.system_hints = hints

        # 5.5 构建最终返回 payload
        payload = asdict(result)
        if feedback:
            payload["feedback"] = asdict(feedback)

        # 5.6 保存结果到待提交记录
        pending.result = payload
        pending.stage = CommitStage.SIGNAL_SAVED
        pending.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.signals.save_pending_commit(pending)
        self.store.signals.save_last_commit(payload)

        # 5.7 清理临时状态
        self.store.progress.clear_in_progress()
        self.store.signals.clear_pending_commit()

        # 5.8 记录检查点（用于断点续传）
        self.store.checkpoints.append(
            chapter_scope(chapter),
            "commit",
            artifact=f"chapters/ch{chapter:02d}.md",
        )
        
        # 返回提交结果
        return payload
