from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.domain.writing import ChapterPlan
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import parse_chapter_plan


class PlanChapterTool:
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "plan_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        plan = parse_chapter_plan(args)
        if plan.chapter <= 0:
            raise ValueError("chapter must be > 0")
        progress = self.store.progress.load()
        allow_rewrite = bool(
            progress
            and progress.flow in {"rewriting", "polishing"}
            and plan.chapter in progress.pending_rewrites
        )
        if self.store.progress.is_chapter_completed(plan.chapter) and not allow_rewrite:
            return {
                "chapter": plan.chapter,
                "skipped": True,
                "reason": f"第 {plan.chapter} 章已提交完成，不能重新规划",
                "next_step": "该章节已完成，请继续规划下一章",
            }
        if plan.contract.target_words <= 0:
            plan.contract.target_words = 1800
        if plan.contract.min_words <= 0:
            plan.contract.min_words = 1200
        if plan.contract.max_words < plan.contract.target_words:
            plan.contract.max_words = max(plan.contract.target_words + 400, 2200)

        self.store.drafts.save_chapter_plan(plan)
        self.store.progress.start_chapter(plan.chapter)
        self.store.checkpoints.append(
            chapter_scope(plan.chapter),
            "plan",
            artifact=f"drafts/ch{plan.chapter:02d}.plan.json",
        )
        return {
            "planned": True,
            "chapter": plan.chapter,
            "next_step": "立即调用 draft_chapter 写入正文，不要重复规划同一章",
            "plan": asdict(plan),
        }
