from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.host.events import Event

from .helpers import _append_line, _is_rewrite_mode
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def plan_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建章节规划节点工厂函数。

    调用 ArchitectAgent 生成当前章节的结构化规划（标题、目标、冲突、钩子、契约等），
    通过 plan_chapter 工具持久化，结果写入 state["latest_plan"]。

    规划完成后自动将 pending_action 设为 "generate_draft"，驱动边跳转到草稿生成节点。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["latest_plan"]
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = state.get("context") or {}
        seed_text = str(state.get("seed_text") or "")
        progress = runtime.store.progress.load()
        if _is_rewrite_mode(progress):
            summary = f"调用 plan_chapter (rewrite ch{chapter})"
        else:
            summary = f"调用 plan_chapter (ch{chapter})"
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=summary, level="info"))
        architect = runtime.get_agent("architect")
        plan_payload = architect.build_dynamic_plan(seed_text, chapter, context)
        plan_res = runtime.runner.call_tool("plan_chapter", plan_payload)
        latest_plan = plan_res.get("plan") or plan_payload
        state["latest_plan"] = latest_plan
        state["pending_action"] = "generate_draft"
        return state

    return _node


def generate_draft_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建草稿生成节点工厂函数。

    调用 WriterAgent 基于上下文和规划生成完整的章节正文草稿。
    这是 LLM Token 消耗最密集的环节，支持流式输出和字数自动调整
    （不足时补写，超限时压缩）。

    生成的草稿写入 state["latest_draft"]，字数写入 state["latest_word_count"]。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["latest_draft"] 和 state["latest_word_count"]
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = state.get("context") or {}
        plan = state.get("latest_plan") or {}
        contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
        writer = runtime.get_agent("writer")
        client = writer.build_client()
        draft, word_count = writer.generate_chapter_with_context(
            client=client,
            seed_text=str(state.get("seed_text") or ""),
            chapter=chapter,
            context=context,
            plan=plan,
            contract=contract,
        )
        state["latest_draft"] = draft
        state["latest_word_count"] = word_count
        _append_line(state, f"[tool] draft_generation -> word_count={word_count}")
        return state

    return _node
