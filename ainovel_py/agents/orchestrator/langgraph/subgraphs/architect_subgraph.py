from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.host.events import Event

from ..nodes.helpers import _append_line, _is_rewrite_mode, ensure_novel_context
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def build_architect_plan_subgraph(runtime: "LangGraphRuntime") -> Any:
    """构建 Architect 的"规划章节"技能子图。

    子图流程：
    START → build_plan → END

    build_plan 节点：
    - 调用 ArchitectAgent.build_dynamic_plan() 生成章节计划
    - 通过 plan_chapter 工具持久化
    - 将计划写入 state["latest_plan"]

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        编译后的子图，可作为主图的节点使用
    """
    graph = StateGraph(GraphState)
    graph.add_node("build_plan", _build_plan_node(runtime))
    graph.add_edge(START, "build_plan")
    graph.add_edge("build_plan", END)
    return graph.compile()


def _build_plan_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """Architect 规划技能的核心节点。

    调用 ArchitectAgent.build_dynamic_plan() 生成章节计划，
    通过 plan_chapter 工具持久化，结果写入 state["latest_plan"]。
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = ensure_novel_context(runtime, state)
        seed_text = str(state.get("seed_text") or "")
        feedback = str(state.get("plan_feedback") or "")
        progress = runtime.store.progress.load()

        if _is_rewrite_mode(progress):
            summary = f"调用 plan_chapter (rewrite ch{chapter})"
        else:
            summary = f"调用 plan_chapter (ch{chapter})"
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=summary, level="info"))

        architect = runtime.get_agent("architect")
        plan_payload = architect.build_dynamic_plan(seed_text, chapter, context, feedback)
        plan_res = runtime.runner.call_tool("plan_chapter", plan_payload)
        latest_plan = plan_res.get("plan") or plan_payload
        state["latest_plan"] = latest_plan

        _append_line(state, f"[architect] plan_chapter -> ch{chapter} title={latest_plan.get('title', '')}")
        return state

    return _node
