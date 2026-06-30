from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.host.events import Event

from ..nodes.helpers import _append_line, _enqueue_hint_actions, ensure_novel_context
from ..post_commit import plan_review_followup
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_editor_review_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Editor 的"评审章节"技能子图。

    子图流程：
    START → generate_review → save_review → END

    generate_review 节点：
    - 调用 EditorAgent.generate_review_payload() 生成评审报告

    save_review 节点：
    - 调用 save_review 工具持久化评审结果
    - 解析后续动作

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图
    """
    graph = StateGraph(GraphState)
    graph.add_node("generate_review", _generate_review_node(runtime))
    graph.add_node("save_review", _save_review_node(runtime))
    graph.add_edge(START, "generate_review")
    graph.add_edge("generate_review", "save_review")
    graph.add_edge("save_review", END)
    return graph.compile()


def _generate_review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 评审技能的生成评审节点。

    通过 ensure_novel_context() 懒加载上下文，首次加载后缓存到 state["context"]。
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or state.get("current_chapter") or 0)
        if chapter <= 0:
            _append_line(state, f"[review] skipped -> chapter={chapter} not pending")
            state["latest_review_payload"] = None
            return state

        context = ensure_novel_context(runtime, state)
        editor = runtime.get_agent("editor")
        client = editor.build_client()
        review_payload = editor.generate_review_payload(client, chapter, context)
        state["latest_review_payload"] = review_payload
        _append_line(state, f"[editor] generate_review -> ch{chapter}")
        return state

    return _node


def _save_review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 评审技能的保存评审节点。"""
    def _node(state: GraphState) -> GraphState:
        review_payload = state.get("latest_review_payload")
        if not review_payload:
            state["pending_action"] = "checkpoint"
            return state

        chapter = int(review_payload.get("chapter") or state.get("current_chapter") or 0)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)
        state["latest_review_result"] = review_res
        _append_line(state, f"[tool] save_review -> final_verdict={review_res.get('final_verdict', '')}")

        plan = plan_review_followup(review_res)
        if plan.actions:
            next_action = _enqueue_hint_actions(state, plan.actions)
            state["pending_action"] = next_action
        else:
            state["pending_action"] = plan.next_action

        state["pending_review_for"] = None
        return state

    return _node
