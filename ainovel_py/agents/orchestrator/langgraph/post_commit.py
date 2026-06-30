from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hints import HintAction, parse_hint_actions, plan_actions


@dataclass
class PostCommitPlan:
    """章节提交后的执行计划，决定 commit_chapter_node 完成后的下一步动作。

    由 plan_post_commit() 函数构建，被 commit_chapter_node 用于设置
    pending_action（直接跳转目标）和 pending_actions（待处理队列）。

    Attributes:
        hints: 原始系统提示字符串列表（来自 commit_res.system_hints）
        actions: 解析后的 HintAction 枚举列表
        next_action: 下一步应跳转的目标节点名
        pending_review_for: 待评审的章节数（commit 后通常为 None，由 supervisor 统一调度）
        queue: 待执行的后续动作队列（arc_summary / volume_summary / expand_arc）
    """

    hints: list[str] = field(default_factory=list)
    actions: list[HintAction] = field(default_factory=list)
    next_action: str = "checkpoint"
    pending_review_for: int | None = None
    queue: list[str] = field(default_factory=list)


@dataclass
class ReviewFollowupPlan:
    """评审完成后的执行计划，决定 review_node 完成后的下一步动作。

    由 plan_review_followup() 函数构建，与 PostCommitPlan 的区别在于：
    - 不抑制 review 直达（评审后允许直接触发 rewrite/polish）
    - 没有 pending_review_for 字段（评审本身就是对某章节的）

    Attributes:
        hints: 原始系统提示字符串列表（来自 review_res.system_hints）
        actions: 解析后的 HintAction 枚举列表
        next_action: 下一步应跳转的目标节点名
        queue: 待执行的后续动作队列
    """

    hints: list[str] = field(default_factory=list)
    actions: list[HintAction] = field(default_factory=list)
    next_action: str = "checkpoint"
    queue: list[str] = field(default_factory=list)


def plan_post_commit(commit_res: dict[str, Any], chapter: int) -> PostCommitPlan:
    """根据章节提交结果规划后续动作。

    从 commit_chapter 工具返回的 system_hints 中提取提示信号，
    经解析和调度后生成后续执行计划。

    特殊行为：
    - 当 ActionPlan.next_action 为 "review" 时强制改为 "checkpoint"，
      因为评审流程由 supervisor 统一调度，不在此处直达
    - queue 中会过滤掉 "review" 动作（如有）

    Args:
        commit_res: commit_chapter 工具返回的完整结果字典，需包含 system_hints 字段
        chapter: 当前已提交的章节号

    Returns:
        PostCommitPlan 对象，包含 next_action、queue、hints 等字段
    """
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
    """根据评审结果规划后续动作。

    从 save_review 工具返回的 system_hints 中提取提示信号，
    经解析和调度后生成评审后的执行计划。

    与 plan_post_commit 的区别：
    - 不抑制任何动作（包括 review），直接透传给 supervisor 做最终决策
    - 评审后可能触发 rewrite/polish/expand_arc 等多种路径

    Args:
        review_res: save_review 工具返回的完整结果字典，需包含 system_hints 和 final_verdict 字段

    Returns:
        ReviewFollowupPlan 对象，包含 next_action、queue、hints 等字段
    """
    hints = list(review_res.get("system_hints") or [])
    actions = parse_hint_actions(hints)
    action_plan = plan_actions(actions)
    return ReviewFollowupPlan(
        hints=hints,
        actions=actions,
        next_action=action_plan.next_action,
        queue=list(action_plan.queue),
    )
