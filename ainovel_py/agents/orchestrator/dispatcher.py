from __future__ import annotations

from typing import Any

from .tags import TaskTag


def dispatch_next(state: dict[str, Any]) -> TaskTag:
    """主 Agent 的核心调度函数：规则优先 + LLM 兜底。

    分析当前状态，决定下一步将任务分配给哪个角色的哪个技能。

    规则层覆盖的确定性链路：
    1. 刚加载上下文 → 根据恢复状态决定
    2. 规划完成 → 写作
    3. 写作完成 → 提交
    4. 提交完成 → 根据 system_hints 决定（review/checkpoint/summary）
    5. 评审完成 → 根据 verdict 决定（accept→下一章, polish/rewrite→重写）
    6. 摘要完成 → checkpoint 或下一章

    规则无法匹配时，回退到 LLM 决策。

    Args:
        state: 当前图状态字典

    Returns:
        TaskTag 枚举值，指示下一步应执行的任务
    """
    last_tag = str(state.get("last_completed_tag") or "")
    current_tag = str(state.get("current_tag") or "")
    pending_action = str(state.get("pending_action") or "")

    # 规则 1：pending_action 中有直接指令
    if pending_action:
        tag = _map_pending_action_to_tag(pending_action)
        if tag:
            return tag

    # 规则 2：根据上一个完成的任务决定
    if last_tag:
        return _decide_after_completion(state, last_tag)

    # 规则 3：首次启动（无 last_completed_tag），从 load_context 后的状态推断
    return _decide_initial(state)


def _map_pending_action_to_tag(action: str) -> TaskTag | None:
    """将旧的 pending_action 值映射为 TaskTag。"""
    mapping = {
        "generate_draft": TaskTag.WRITE_CHAPTER,
        "commit_chapter": TaskTag.COMMIT_CHAPTER,
        "review": TaskTag.REVIEW_CHAPTER,
        "rewrite": TaskTag.REWRITE_CHAPTER,
        "polish": TaskTag.REWRITE_CHAPTER,
        "arc_summary": TaskTag.ARC_SUMMARY,
        "volume_summary": TaskTag.VOLUME_SUMMARY,
        "expand_arc": TaskTag.EXPAND_ARC,
        "finish": TaskTag.FINISH,
        "novel_context": TaskTag.PLAN_CHAPTER,
        "continue": TaskTag.PLAN_CHAPTER,
    }
    return mapping.get(action)


def _decide_after_completion(state: dict[str, Any], last_tag: str) -> TaskTag:
    """根据上一个完成的任务，用规则决定下一个任务。"""

    # 规划完成 → 写作
    if last_tag == TaskTag.PLAN_CHAPTER.value:
        return TaskTag.WRITE_CHAPTER

    # 写作完成 → 提交
    if last_tag == TaskTag.WRITE_CHAPTER.value:
        return TaskTag.COMMIT_CHAPTER

    # 提交完成 → 根据 hints 决定
    if last_tag == TaskTag.COMMIT_CHAPTER.value:
        return _decide_after_commit(state)

    # 评审完成 → 根据 verdict 决定
    if last_tag == TaskTag.REVIEW_CHAPTER.value:
        return _decide_after_review(state)

    # 重写完成 → 提交
    if last_tag == TaskTag.REWRITE_CHAPTER.value:
        return TaskTag.COMMIT_CHAPTER

    # 摘要完成 → checkpoint（由 checkpoint_node 决定下一章或结束）
    if last_tag in (TaskTag.ARC_SUMMARY.value, TaskTag.VOLUME_SUMMARY.value, TaskTag.EXPAND_ARC.value):
        return _decide_after_summary(state)

    # 默认：回到规划
    return TaskTag.PLAN_CHAPTER


def _decide_after_commit(state: dict[str, Any]) -> TaskTag:
    """提交完成后的规则调度。"""
    commit_result = state.get("latest_commit_result") or {}
    hints = commit_result.get("system_hints") or []

    from .langgraph.hints import parse_hint_actions, plan_actions
    actions = parse_hint_actions(hints)
    action_plan = plan_actions(actions)

    # 需要评审 → Editor 评审技能
    if action_plan.requires_review:
        return TaskTag.REVIEW_CHAPTER

    # 需要重写/打磨 → Writer 重写技能
    if action_plan.rewrite_mode:
        return TaskTag.REWRITE_CHAPTER

    # 有排队的摘要/扩展任务
    if action_plan.queue:
        return _map_pending_action_to_tag(action_plan.queue[0]) or TaskTag.PLAN_CHAPTER

    # 无特殊 hints → 下一章
    return TaskTag.PLAN_CHAPTER


def _decide_after_review(state: dict[str, Any]) -> TaskTag:
    """评审完成后的规则调度。"""
    review_result = state.get("latest_review_result") or {}
    verdict = str(review_result.get("final_verdict") or review_result.get("verdict") or "")

    # 评审通过 → 下一章
    if verdict == "accept":
        return TaskTag.PLAN_CHAPTER

    # 评审需要打磨/重写 → Writer 重写技能
    if verdict in ("polish", "rewrite"):
        return TaskTag.REWRITE_CHAPTER

    # 评审结果模糊（如 LLM 输出非标准 verdict）→ LLM 兜底
    # 也检查 hints
    hints = review_result.get("system_hints") or []
    if hints:
        from .langgraph.hints import parse_hint_actions, plan_actions
        actions = parse_hint_actions(hints)
        action_plan = plan_actions(actions)
        if action_plan.rewrite_mode:
            return TaskTag.REWRITE_CHAPTER
        if action_plan.queue:
            tag = _map_pending_action_to_tag(action_plan.queue[0])
            if tag:
                return tag

    # 默认：下一章
    return TaskTag.PLAN_CHAPTER


def _decide_after_summary(state: dict[str, Any]) -> TaskTag:
    """摘要完成后的规则调度。"""
    # 摘要完成后回到规划（下一章）
    return TaskTag.PLAN_CHAPTER


def _decide_initial(state: dict[str, Any]) -> TaskTag:
    """首次启动时的规则调度。"""
    pending_action = str(state.get("pending_action") or "")

    # load_context 已设置 pending_action
    if pending_action:
        tag = _map_pending_action_to_tag(pending_action)
        if tag:
            return tag

    # 默认：从规划开始
    return TaskTag.PLAN_CHAPTER
