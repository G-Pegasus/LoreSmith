from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ..nodes.helpers import _append_line, _enqueue_hint_actions
from ..post_commit import plan_post_commit
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_editor_commit_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Editor 的"提交章节"技能子图。

    子图流程：
    START → extract_metadata → write_commit_cycle → END

    extract_metadata 节点：
    - 调用 EditorAgent.extract_metadata() 从正文提取结构化元数据
    - 如 metadata 无 summary，用 WriterAgent.summarize_chapter() 做 fallback

    write_commit_cycle 节点：
    - 调用 EditorAgent.run_write_commit_cycle() 执行 draft → check_consistency → commit
    - 解析 system_hints 设置后续动作

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图
    """
    graph = StateGraph(GraphState)
    graph.add_node("extract_metadata", _extract_metadata_node(runtime))
    graph.add_node("write_commit_cycle", _write_commit_cycle_node(runtime))
    graph.add_edge(START, "extract_metadata")
    graph.add_edge("extract_metadata", "write_commit_cycle")
    graph.add_edge("write_commit_cycle", END)
    return graph.compile()


def _extract_metadata_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 提交技能的元数据提取节点。"""
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")

        editor = runtime.get_agent("editor")
        metadata = editor.extract_metadata(chapter=chapter, draft=draft)

        summary = str(metadata.get("summary") or "")
        if not summary:
            writer = runtime.get_agent("writer")
            client = writer.build_client()
            summary = writer.summarize_chapter(client, chapter, draft)
            metadata["summary"] = summary

        state["latest_metadata"] = metadata
        state["latest_summary"] = summary
        _append_line(state, f"[editor] extract_metadata -> ch{chapter}")
        return state

    return _node


def _write_commit_cycle_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Editor 提交技能的写入-提交节点。"""
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")
        summary = str(state.get("latest_summary") or "")
        metadata = state.get("latest_metadata") or {}

        editor = runtime.get_agent("editor")
        draft_res, commit_res = editor.run_write_commit_cycle(chapter, draft, summary, metadata)
        state["latest_commit_result"] = commit_res

        _append_line(state, f"[editor] commit_chapter -> ch{chapter}")

        plan = plan_post_commit(commit_res, chapter)
        if plan.actions:
            next_action = _enqueue_hint_actions(state, plan.actions)
            state["pending_action"] = next_action
        else:
            state["pending_action"] = plan.next_action

        if plan.pending_review_for:
            state["pending_review_for"] = plan.pending_review_for

        return state

    return _node
