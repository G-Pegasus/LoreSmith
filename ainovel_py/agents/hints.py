from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HintAction(str, Enum):
    CONTINUE = "continue"
    REVIEW_REQUIRED = "review_required"
    REWRITE_REQUIRED = "rewrite_required"
    POLISH_REQUIRED = "polish_required"
    REWRITE_DONE = "rewrite_done"
    WRITER_FEEDBACK = "writer_feedback"
    ARC_END = "arc_end"
    BOOK_COMPLETE = "book_complete"
    NEW_VOLUME_REQUIRED = "new_volume_required"
    EXPAND_ARC_REQUIRED = "expand_arc_required"
    REVIEW_ACCEPTED = "review_accepted"
    UNKNOWN = "unknown"


@dataclass
class ActionPlan:
    requires_review: bool = False
    rewrite_mode: str = ""
    queue: list[str] = field(default_factory=list)

    @property
    def next_action(self) -> str:
        if self.requires_review:
            return "review"
        if self.rewrite_mode:
            return self.rewrite_mode
        if self.queue:
            return self.queue[0]
        return "checkpoint"


def parse_hint_actions(hints: list[str]) -> list[HintAction]:
    actions: list[HintAction] = []
    for hint in hints:
        lower = hint.lower()
        if "review_required" in lower:
            actions.append(HintAction.REVIEW_REQUIRED)
        elif "review_accepted" in lower:
            actions.append(HintAction.REVIEW_ACCEPTED)
        elif "rewrite_required" in lower or "重写_required" in lower:
            actions.append(HintAction.REWRITE_REQUIRED)
        elif "polish_required" in lower or "打磨_required" in lower:
            actions.append(HintAction.POLISH_REQUIRED)
        elif "writer_feedback" in lower:
            actions.append(HintAction.WRITER_FEEDBACK)
        elif "continue:" in lower or "continue" in lower:
            actions.append(HintAction.CONTINUE)
        elif "arc_end" in lower:
            actions.append(HintAction.ARC_END)
        elif "book_complete" in lower:
            actions.append(HintAction.BOOK_COMPLETE)
        elif "new_volume_required" in lower:
            actions.append(HintAction.NEW_VOLUME_REQUIRED)
        elif "expand_arc_required" in lower:
            actions.append(HintAction.EXPAND_ARC_REQUIRED)
        elif "全部完成" in hint or "完成重写" in hint or "完成打磨" in hint:
            actions.append(HintAction.REWRITE_DONE)
        else:
            actions.append(HintAction.UNKNOWN)
    return actions


def needs_review_from_actions(commit_res: dict[str, Any], actions: list[HintAction]) -> bool:
    if commit_res.get("review_required"):
        return True
    return HintAction.REVIEW_REQUIRED in actions


def has_placeholder_action(actions: list[HintAction]) -> bool:
    return any(
        a in {
            HintAction.ARC_END,
            HintAction.BOOK_COMPLETE,
            HintAction.NEW_VOLUME_REQUIRED,
            HintAction.EXPAND_ARC_REQUIRED,
        }
        for a in actions
    )


def plan_actions(actions: list[HintAction]) -> ActionPlan:
    queue: list[str] = []
    rewrite_mode = ""
    if HintAction.REWRITE_REQUIRED in actions:
        rewrite_mode = "rewrite"
    elif HintAction.POLISH_REQUIRED in actions:
        rewrite_mode = "polish"
    if HintAction.ARC_END in actions:
        queue.append("arc_summary")
    if HintAction.BOOK_COMPLETE in actions:
        queue.append("volume_summary")
    if HintAction.NEW_VOLUME_REQUIRED in actions or HintAction.EXPAND_ARC_REQUIRED in actions:
        queue.append("expand_arc")
    return ActionPlan(
        requires_review=HintAction.REVIEW_REQUIRED in actions,
        rewrite_mode=rewrite_mode,
        queue=queue,
    )
