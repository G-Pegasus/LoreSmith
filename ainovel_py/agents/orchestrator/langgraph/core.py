from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.roles import ArchitectAgent, BaseAgent, EditorAgent, RewriteAgent, SupervisorAgent, WriterAgent
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.agents.orchestrator.interface import OrchestratorBackend
from ainovel_py.agents.orchestrator.dispatcher import dispatch_next
from ainovel_py.agents.orchestrator.tags import TaskTag
from ainovel_py.assets import load_bundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event
from ainovel_py.store.store import Store

from .nodes import (
    checkpoint_node,
    finish_node,
    load_runtime_context,
    route_after_checkpoint,
    route_after_load,
)
from .nodes.helpers import _append_line
from .state import GraphState, OrchestratorState
from .subgraphs import (
    build_architect_plan_subgraph,
    build_editor_commit_subgraph,
    build_editor_review_subgraph,
    build_summary_subgraph,
    build_writer_subgraph,
)

# TaskTag 到子图节点名的映射
TAG_TO_NODE: dict[str, str] = {
    TaskTag.PLAN_CHAPTER.value: "architect_plan",
    TaskTag.WRITE_CHAPTER.value: "writer_write",
    TaskTag.COMMIT_CHAPTER.value: "editor_commit",
    TaskTag.REVIEW_CHAPTER.value: "editor_review",
    TaskTag.REWRITE_CHAPTER.value: "writer_write",
    TaskTag.ARC_SUMMARY.value: "architect_summary",
    TaskTag.VOLUME_SUMMARY.value: "architect_summary",
    TaskTag.EXPAND_ARC.value: "architect_summary",
    TaskTag.FINISH.value: "finish",
}


@dataclass
class LangGraphRuntime(OrchestratorBackend):
    cfg: Config
    runner: AgentRunner
    store: Store
    emit_event: Callable[[Event], None]
    emit_stream: Callable[[str, str], None]

    def __post_init__(self) -> None:
        self._aborted = False
        self.context_manager = ContextManager(context_window=self.cfg.context_window)
        self.assets = load_bundle(self.cfg.style)
        self._agents: dict[str, BaseAgent] = {}
        self._init_agents()
        self.graph = self._build_graph()

    def _init_agents(self) -> None:
        common = dict(cfg=self.cfg, runner=self.runner, store=self.store, assets=self.assets, emit_event=self.emit_event, emit_stream=self.emit_stream)
        self._agents["architect"] = ArchitectAgent(**common)
        self._agents["writer"] = WriterAgent(**common)
        self._agents["editor"] = EditorAgent(**common)
        self._agents["rewrite"] = RewriteAgent(**common)
        self._agents["supervisor"] = SupervisorAgent(**common)

    def get_agent(self, name: str) -> BaseAgent:
        return self._agents[name]

    def start(self, prompt: str) -> None:
        self._aborted = False
        self._invoke(prompt, resume_mode=False)

    def resume(self, prompt: str) -> None:
        self._aborted = False
        self._invoke(prompt, resume_mode=True)

    def follow_up(self, text: str) -> None:
        self._aborted = False
        self._invoke(text, resume_mode=False)

    def abort(self) -> None:
        self._aborted = True

    def wait_idle(self) -> None:
        return

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    def emit_checkpoint_pending(self, pending: PendingRunCheckpoint) -> None:
        pass

    def _invoke(self, seed_text: str, resume_mode: bool) -> None:
        state: OrchestratorState = {
            "seed_text": seed_text,
            "resume_mode": resume_mode,
            "pending_action": "load",
            "pending_actions": [],
            "stop_requested": self._aborted,
            "out_lines": [f"[LangGraph] 协调器开始执行：{seed_text}"],
        }
        result = self.graph.invoke(state)
        out_lines = result.get("out_lines") or []
        if out_lines:
            self.emit_stream("thinking", "\n".join(out_lines) + "\n")

    def build_client(self) -> OpenAICompatClient:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 为占位值")
        return OpenAICompatClient(
            api_key=pc.api_key,
            model=self.cfg.model,
            base_url=pc.base_url,
            timeout=120.0,
        )

    def _build_graph(self):
        """构建主图 + 子图的二级架构。

        主图结构（角色编排层）：
        START → load_context → dispatch → [角色子图] → collect → dispatch (循环)
                        ↓                           → checkpoint → finish → END
                      finish

        子图结构（技能实现层）：
        - architect_plan: Architect 的规划章节技能
        - writer_write: Writer 的写章节技能
        - editor_commit: Editor 的提交章节技能
        - editor_review: Editor 的评审章节技能
        - architect_summary: Architect 的弧/卷摘要技能

        上下文加载策略：懒加载。子图按需调用 ensure_novel_context() 加载上下文，
        首次加载后缓存到 state["context"]，后续子图直接复用。
        """
        graph = StateGraph(OrchestratorState)

        # === 主图节点（角色编排层） ===
        graph.add_node("load_context", load_runtime_context(self))
        graph.add_node("dispatch", _dispatch_node(self))
        graph.add_node("collect", _collect_node(self))
        graph.add_node("checkpoint", checkpoint_node(self))
        graph.add_node("finish", finish_node(self))

        # === 角色技能子图节点 ===
        graph.add_node("architect_plan", build_architect_plan_subgraph(self))
        graph.add_node("writer_write", build_writer_subgraph(self))
        graph.add_node("editor_commit", build_editor_commit_subgraph(self))
        graph.add_node("editor_review", build_editor_review_subgraph(self))
        graph.add_node("architect_summary", build_summary_subgraph(self))

        # === 边 ===
        graph.add_edge(START, "load_context")

        # load_context → 根据恢复状态决定：dispatch 或 finish
        graph.add_conditional_edges(
            "load_context",
            _route_after_load_to_dispatch,
            {
                "dispatch": "dispatch",
                "finish": "finish",
            },
        )

        # dispatch → 根据 TaskTag 路由到角色子图
        graph.add_conditional_edges(
            "dispatch",
            _route_by_tag,
            {
                "architect_plan": "architect_plan",
                "writer_write": "writer_write",
                "editor_commit": "editor_commit",
                "editor_review": "editor_review",
                "architect_summary": "architect_summary",
                "finish": "finish",
            },
        )

        # 所有角色子图完成后都回到 collect
        graph.add_edge("architect_plan", "collect")
        graph.add_edge("writer_write", "collect")
        graph.add_edge("editor_commit", "collect")
        graph.add_edge("editor_review", "collect")
        graph.add_edge("architect_summary", "collect")

        # collect → 再次 dispatch（循环）或 checkpoint
        graph.add_conditional_edges(
            "collect",
            _route_after_collect,
            {
                "dispatch": "dispatch",
                "checkpoint": "checkpoint",
            },
        )

        graph.add_conditional_edges(
            "checkpoint",
            _route_after_checkpoint_to_dispatch,
            {
                "dispatch": "dispatch",
                "finish": "finish",
            },
        )

        graph.add_edge("finish", END)

        return graph.compile()


# ============================================================
# 主图节点实现
# ============================================================

def _dispatch_node(runtime: "LangGraphRuntime") -> Callable[[OrchestratorState], OrchestratorState]:
    """主 Agent 的 dispatch 节点：分析状态，决定任务分配给哪个角色。"""
    def _node(state: OrchestratorState) -> OrchestratorState:
        tag = dispatch_next(state)
        state["current_tag"] = tag.value
        reason = f"last={state.get('last_completed_tag', 'none')} pending={state.get('pending_action', 'none')}"
        state["dispatch_reason"] = reason
        _append_line(state, f"[dispatch] tag={tag.value} reason={reason}")
        return state
    return _node


def _collect_node(runtime: "LangGraphRuntime") -> Callable[[OrchestratorState], OrchestratorState]:
    """主 Agent 的 collect 节点：收集角色子图产出，更新状态。"""
    def _node(state: OrchestratorState) -> OrchestratorState:
        completed_tag = str(state.get("current_tag") or "")
        state["last_completed_tag"] = completed_tag
        _append_line(state, f"[collect] completed={completed_tag}")

        # 检查是否需要 checkpoint
        pending_action = str(state.get("pending_action") or "")
        if pending_action == "finish":
            state["pending_action"] = "finish"
        elif pending_action in ("checkpoint", "continue", "novel_context"):
            state["pending_action"] = "checkpoint"
        else:
            # 子图可能已设置了 pending_action（如 review 后的 rewrite）
            # 保留该值，让 dispatch 在下一轮处理
            pass

        return state
    return _node


# ============================================================
# 路由函数
# ============================================================

def _route_after_load_to_dispatch(state: OrchestratorState) -> str:
    """load_context 后的路由：决定进入 dispatch 还是 finish。"""
    action = str(state.get("pending_action") or "dispatch")
    if action == "finish":
        return "finish"
    return "dispatch"


def _route_by_tag(state: OrchestratorState) -> str:
    """根据 current_tag 路由到对应的角色子图节点。"""
    tag = str(state.get("current_tag") or "")
    node = TAG_TO_NODE.get(tag)
    if node:
        return node
    # 未知 tag → 回到 dispatch 重新决策
    return "dispatch"


def _route_after_collect(state: OrchestratorState) -> str:
    """collect 后的路由：决定继续 dispatch 还是进入 checkpoint。"""
    pending_action = str(state.get("pending_action") or "")
    if pending_action == "finish":
        return "checkpoint"
    if pending_action == "checkpoint":
        return "checkpoint"
    # 默认继续 dispatch（循环）
    return "dispatch"


def _route_after_checkpoint_to_dispatch(state: OrchestratorState) -> str:
    """checkpoint 后的路由：决定进入 dispatch 还是 finish。"""
    action = str(state.get("pending_action") or "finish")
    if action in ("novel_context", "continue"):
        # checkpoint 决定继续下一章 → 重新 dispatch
        state["last_completed_tag"] = ""
        return "dispatch"
    if action == "finish":
        return "finish"
    # 其他情况也回到 dispatch
    return "dispatch"
