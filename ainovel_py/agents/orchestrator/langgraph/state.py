from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    seed_text: str
    resume_mode: bool
    current_chapter: int
    progress_snapshot: dict[str, Any]
    context: dict[str, Any]
    latest_plan: dict[str, Any]
    latest_draft: str
    latest_commit_result: dict[str, Any]
    latest_review_result: dict[str, Any]
    pending_review_for: int | None
    rewrite_mode: str
    pending_actions: list[str]
    pending_action: str
    plan_feedback: str
    plan_decision: str
    stop_requested: bool
    error: str
    out_lines: list[str]
