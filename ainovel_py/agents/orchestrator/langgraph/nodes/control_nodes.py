from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.domain.writing import PendingRunCheckpoint

from .helpers import (
    MAX_STEPS,
    PAUSE_INTERVAL,
    REASONING_TRUNCATE_LENGTH,
    _append_line,
)
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def checkpoint_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建检查点/流程控制节点工厂函数。

    这是工作流的**控制中枢**，负责：
    1. 消费 pending_actions 队列（有排队动作时优先执行）
    2. 判断是否全部完成（章节总数已达且最后一章已完成）
    3. 判断是否超步数上限或被中止
    4. 每 PAUSE_INTERVAL 章生成一个暂停检查点（需用户确认后继续）
    5. 正常情况下推进到下一章

    暂停机制：每完成 PAUSE_INTERVAL（默认 5）章后生成 PendingRunCheckpoint，
    通过 emit_checkpoint_pending 通知前端，等待用户确认后才能继续。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["current_chapter"] 和 state["pending_action"]
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        completed = list(progress.completed_chapters) if progress else []
        total = progress.total_chapters if progress else 0
        steps = len(completed)
        pending_actions = list(state.get("pending_actions") or [])

        if pending_actions:
            state["pending_action"] = pending_actions[0]
            return state

        if progress and total > 0 and chapter >= total and chapter in completed:
            state["pending_action"] = "finish"
            return state

        if steps >= MAX_STEPS or runtime.is_aborted:
            state["pending_action"] = "finish"
            return state

        next_chapter = progress.next_chapter() if progress else chapter + 1
        if steps > 0 and steps % PAUSE_INTERVAL == 0:
            pending = PendingRunCheckpoint(
                pause_after_chapter=max(completed) if completed else chapter,
                next_chapter=next_chapter,
                completed_count=steps,
            )
            runtime.store.signals.save_pending_checkpoint(pending)
            runtime.emit_checkpoint_pending(pending)
            state["current_chapter"] = next_chapter
            state["pending_action"] = "finish"
            return state

        state["current_chapter"] = next_chapter
        state["pending_action"] = "continue"
        return state

    return _node


def finish_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建终止节点工厂函数。

    工作流终点节点，仅将 pending_action 设为 "finish"，
    触发图的 END 边结束执行。

    注意：当前实现较简单，未来可在此处添加终止前清理逻辑
    （如保存最终状态、发射完成事件等）。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，设置 state["pending_action"] = "finish"
    """
    def _node(state: GraphState) -> GraphState:
        state["pending_action"] = "finish"
        return state

    return _node


def supervisor_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建 Supervisor 动态路由节点工厂函数。

    多 Agent 架构的**调度核心**，调用 SupervisorAgent 通过 LLM 结构化输出生成决策：
    - next_agent: 下一步应调度的目标 Agent 名称
    - reasoning: 决策理由
    - task_instruction: 给目标 Agent 的具体指令

    决策成功时通过 SUPERVISOR_ACTION_MAP 映射为图节点名；
    失败时回退到 route_after_commit（硬编码路由安全网）。

    此节点是 commit_chapter、review、arc_summary、volume_summary 四个节点的统一汇聚点，
    所有这些节点执行完毕后都会先经过 supervisor 再分发到下一个目标。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 state["supervisor_decision"] 和 state["pending_action"]
    """
    def _node(state: GraphState) -> GraphState:
        from ainovel_py.agents.roles.supervisor import SupervisorAgent

        supervisor = runtime.get_agent("supervisor")
        if not isinstance(supervisor, SupervisorAgent):
            state["supervisor_decision"] = None
            return state

        result = supervisor.execute(state=state)
        decision = result.get("supervisor_decision")
        pending_action = result.get("pending_action", "checkpoint")

        state["supervisor_decision"] = decision
        state["pending_action"] = pending_action

        if decision:
            _append_line(state, f"[supervisor] next={decision.get('next_agent')} reason={decision.get('reasoning', '')[:REASONING_TRUNCATE_LENGTH]}")
        else:
            _append_line(state, "[supervisor] fallback to hardcoded routing")

        return state

    return _node
