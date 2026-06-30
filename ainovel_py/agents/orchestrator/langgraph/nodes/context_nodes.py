from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.domain.runtime import FlowState

from .helpers import (
    DEFAULT_ACTION,
    RUN_CONTINUE_SENTINEL,
    _append_line,
    _is_rewrite_mode,
    _resume_from_checkpoint,
    _resume_from_in_progress,
    _resume_from_pending_commit,
    _resume_from_rewrite_queue,
)
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def load_runtime_context(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建运行时上下文加载节点工厂函数。

    这是整个 LangGraph 工作流的**入口节点**，负责：
    1. 从 store 加载进度、待提交、待确认检查点等持久化状态
    2. 根据不同恢复场景（4 种）决定初始路由目标
    3. 初始化 GraphState 的所有关键字段

    恢复场景优先级（从高到低）：
    - 待确认检查点（pending_checkpoint）→ 需用户确认
    - resume_mode 开启 + 待提交章节（pending）→ 直接提交
    - resume_mode 开启 + 进行中章节（in_progress_chapter）→ 恢复生成
    - resume_mode 开启 + 重写队列（pending_rewrites）→ 进入重写
    - 正常模式 → 从下一章开始

    Args:
        runtime: LangGraphRuntime 实例，提供 store/runner/agent 访问

    Returns:
        LangGraph 可调用的节点函数，接收 GraphState 并返回更新后的 GraphState
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        pending = runtime.store.signals.load_pending_commit()
        pending_checkpoint = runtime.store.signals.load_pending_checkpoint()
        latest = runtime.store.checkpoints.latest_global()
        current_chapter = progress.next_chapter() if progress else 1
        next_action = "novel_context"
        rewrite_mode = ""
        seed_text = str(state.get("seed_text") or "").strip()

        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            current_chapter = progress.pending_rewrites[0]
            rewrite_mode = "polish" if progress.flow == FlowState.POLISHING else "rewrite"

        if pending_checkpoint is not None:
            current_chapter = pending_checkpoint.next_chapter
            next_action = _resume_from_checkpoint(runtime, state, pending_checkpoint, seed_text)
        elif state.get("resume_mode"):
            if pending is not None:
                current_chapter, next_action = _resume_from_pending_commit(state, pending)
            elif progress and progress.in_progress_chapter > 0:
                current_chapter, next_action = _resume_from_in_progress(runtime, state, progress, latest, current_chapter)
            elif progress and progress.pending_rewrites:
                current_chapter, next_action = _resume_from_rewrite_queue(state, progress, rewrite_mode)

        state["current_chapter"] = current_chapter
        state["progress_snapshot"] = {
            "phase": progress.phase if progress else "",
            "flow": progress.flow if progress else "",
            "total_chapters": progress.total_chapters if progress else 0,
            "completed_chapters": list(progress.completed_chapters) if progress else [],
            "pending_rewrites": list(progress.pending_rewrites) if progress else [],
            "rewrite_reason": progress.rewrite_reason if progress else "",
            "in_progress_chapter": progress.in_progress_chapter if progress else 0,
        }
        state["pending_review_for"] = None
        state["rewrite_mode"] = rewrite_mode
        state["pending_actions"] = []
        state["pending_action"] = next_action
        return state

    return _node


def novel_context_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建小说上下文加载节点工厂函数。

    调用 novel_context 工具加载指定章节的全部上下文信息
    （角色、世界观、近期摘要、伏笔等），写入 state["context"]。
    重写模式下还会通过 RewriteAgent 注入评审意见到上下文中。

    这是正常写作流程和重写流程的分叉点——上下文质量直接影响后续规划。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["context"]
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        context = runtime.runner.call_tool("novel_context", {"chapter": chapter})
        if _is_rewrite_mode(progress):
            rewrite_agent = runtime.get_agent("rewrite")
            context = rewrite_agent.build_rewrite_context(progress, context)
        context = context or {}
        state["context"] = context
        return state

    return _node
