from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.host.events import Event

from ..nodes.helpers import _append_line, _pop_pending_action
from ..longform import generate_longform_outline_payload
from ..review_flow import save_arc_summary_followup, save_volume_summary_followup
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_summary_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Architect 的"弧/卷摘要与大纲扩展"技能子图。

    子图流程：
    START → execute_summary → END

    execute_summary 节点根据 state["current_tag"] 决定执行哪种摘要操作：
    - arc_summary: 保存弧摘要
    - volume_summary: 保存卷摘要
    - expand_arc: 大纲扩展（expand_arc 或 append_volume）

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图
    """
    graph = StateGraph(GraphState)
    graph.add_node("execute_summary", _execute_summary_node(runtime))
    graph.add_edge(START, "execute_summary")
    graph.add_edge("execute_summary", END)
    return graph.compile()


def _execute_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Architect 摘要技能的核心节点。

    根据 current_tag 分发到不同的摘要操作。
    """
    def _node(state: GraphState) -> GraphState:
        tag = str(state.get("current_tag") or state.get("pending_action") or "")
        chapter = int(state.get("current_chapter") or 1)
        out_lines = list(state.get("out_lines") or [])

        if tag == "arc_summary":
            result = save_arc_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines)
            if result is None:
                _append_line(state, "[warn] arc_summary_followup returned None")
        elif tag == "volume_summary":
            progress = runtime.store.progress.load()
            volume = max(1, progress.current_volume) if progress else 1
            result = save_volume_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines, volume=volume, always=True)
            if result is None:
                _append_line(state, "[warn] volume_summary_followup returned None")
        elif tag == "expand_arc":
            _execute_expand_arc(runtime, state, chapter, out_lines)
        else:
            _append_line(state, f"[warn] unknown summary tag: {tag}")

        state["out_lines"] = out_lines
        _pop_pending_action(state)
        return state

    return _node


def _execute_expand_arc(runtime: "LangGraphRuntime", state: GraphState, chapter: int, out_lines: list[str]) -> None:
    """执行大纲扩展操作（expand_arc 或 append_volume）。"""
    client = runtime.build_client()
    progress = runtime.store.progress.load()
    architect = runtime.get_agent("architect")
    planning_tier = architect.effective_planning_tier()
    foundation_type = "append_volume"
    payload = None

    if progress and progress.layered:
        volumes = runtime.store.outline.load_layered_outline()
        current_volume = max(1, progress.current_volume or 1)
        current_arc = max(1, progress.current_arc or 1)
        target_arc = current_arc + 1
        has_target_arc = False
        for vol in volumes:
            if vol.index == current_volume:
                has_target_arc = any(arc.index == target_arc for arc in vol.arcs)
                break
        if has_target_arc:
            foundation_type = "expand_arc"
            payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "expand_arc")

    if payload is None:
        payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")

    runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation {foundation_type} (ch{chapter})", level="info"))
    if foundation_type == "expand_arc":
        runtime.runner.call_tool(
            "save_foundation",
            {"type": "expand_arc", "volume": progress.current_volume if progress else 1, "arc": (progress.current_arc or 1) + 1 if progress else 2, "content": payload.get("chapters", [])},
        )
    else:
        runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})

    out_lines.append(f"[tool] save_foundation -> {foundation_type}")
