from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.host.events import Event

from .helpers import _append_line, _enqueue_hint_actions, _is_rewrite_mode
from ..post_commit import plan_review_followup
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建评审节点工厂函数。

    对指定章节进行多维度评审（一致性、角色、节奏、连续性、伏笔、钩子、美学），
    生成结构化的评审报告并通过 save_review 工具持久化。

    评审结果是触发重写流程的唯一来源——final_verdict 为 "rewrite" 或 "polish"
    时会在后续规划中生成对应动作。

    无待评审章节（chapter <= 0）时跳过并记录日志。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["latest_review_result"] 和 state["latest_final_verdict"]
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or 0)
        if chapter <= 0:
            _append_line(state, f"[review] skipped -> chapter={chapter} not pending")
            state["pending_action"] = "checkpoint"
            return state
        editor = runtime.get_agent("editor")
        client = editor.build_client()
        review_payload = editor.generate_review_payload(client, chapter)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)
        state["latest_review_result"] = review_res
        _append_line(state, f"[tool] save_review -> final_verdict={review_res.get('final_verdict', '')}")
        state["latest_final_verdict"] = review_res.get("final_verdict', ''")
        plan = plan_review_followup(review_res)
        next_action = _enqueue_hint_actions(state, plan.actions) if plan.actions else plan.next_action
        state["pending_review_for"] = None
        state["pending_action"] = next_action
        return state

    return _node


def rewrite_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建重写入口节点工厂函数。

    此节点仅负责设置重写状态（章节号、重写模式），不调用任何 Agent 或工具。
    实际的重写工作由后续的 novel_context → plan_chapter → generate_draft 完成。

    重写模式优先级：pending_action > state 中已有的 rewrite_mode > 默认 "rewrite"。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["current_chapter"]、state["rewrite_mode"]，
        并将 pending_action 指向 "novel_context" 以重新开始该章的生成流程
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        rewrite_mode = str(state.get("pending_action") or state.get("rewrite_mode") or "rewrite")
        if progress and progress.pending_rewrites:
            chapter = progress.pending_rewrites[0]
        state["current_chapter"] = chapter
        state["rewrite_mode"] = rewrite_mode
        _append_line(state, f"[rewrite] mode={rewrite_mode} chapter={chapter}")
        state["pending_action"] = "novel_context"
        return state

    return _node
