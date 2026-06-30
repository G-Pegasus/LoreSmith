from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ainovel_py.agents.hints import HintAction, parse_hint_actions, plan_actions


@dataclass
class PostCommitPlan:
    hints: list[str] = field(default_factory=list)
    actions: list[HintAction] = field(default_factory=list)
    next_action: str = "checkpoint"
    pending_review_for: int | None = None
    queue: list[str] = field(default_factory=list)


@dataclass
class ReviewFollowupPlan:
    hints: list[str] = field(default_factory=list)
    actions: list[HintAction] = field(default_factory=list)
    next_action: str = "checkpoint"
    queue: list[str] = field(default_factory=list)


def plan_post_commit(commit_res: dict[str, Any], chapter: int) -> PostCommitPlan:
    hints = list(commit_res.get("system_hints") or [])
    actions = parse_hint_actions(hints)
    action_plan = plan_actions(actions)
    next_action = action_plan.next_action
    pending_review_for = None
    if next_action == "review":
        next_action = "checkpoint"
    return PostCommitPlan(
        hints=hints,
        actions=actions,
        next_action=next_action,
        pending_review_for=pending_review_for,
        queue=[item for item in action_plan.queue if item != "review"],
    )


def plan_review_followup(review_res: dict[str, Any]) -> ReviewFollowupPlan:
    hints = list(review_res.get("system_hints") or [])
    actions = parse_hint_actions(hints)
    action_plan = plan_actions(actions)
    return ReviewFollowupPlan(
        hints=hints,
        actions=actions,
        next_action=action_plan.next_action,
        queue=list(action_plan.queue),
    )
