from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.runner import AgentRunner, LLMCoordinatorBackend
from ainovel_py.assets import load_bundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.runtime import FlowState
from ainovel_py.domain.runtime_events import RuntimeQueueItem, RuntimeQueueKind, RuntimeQueuePriority
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event
from ainovel_py.store.store import Store

from .nodes import (
    arc_summary_node,
    checkpoint_node,
    commit_chapter_node,
    expand_arc_node,
    finish_node,
    generate_draft_node,
    load_runtime_context,
    novel_context_node,
    plan_chapter_node,
    review_node,
    rewrite_node,
    route_after_checkpoint,
    route_after_commit,
    route_after_load,
    route_after_plan,
    volume_summary_node,
)
from .state import GraphState


@dataclass
class LangGraphRuntime(LLMCoordinatorBackend):
    cfg: Config
    runner: AgentRunner
    store: Store
    emit_event: Callable[[Event], None]
    emit_stream: Callable[[str, str], None]

    def __post_init__(self) -> None:
        self._aborted = False
        self.context_manager = ContextManager(context_window=self.cfg.context_window)
        self.assets = load_bundle(self.cfg.style)
        self.graph = self._build_graph()

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

    def emit_checkpoint_pending(self, pending: PendingRunCheckpoint) -> None:
        handler = getattr(self.runner.backend, 'emit_checkpoint_pending', None)
        if callable(handler):
            handler(pending)

    def _invoke(self, seed_text: str, resume_mode: bool) -> None:
        state: GraphState = {
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

    def _dict_to_chapter_plan(self, data: dict[str, Any]):
        return self.runner.backend._dict_to_chapter_plan(data) if hasattr(self.runner, "backend") else LLMCoordinatorBackend._dict_to_chapter_plan(data)

    def _build_graph(self):
        graph = StateGraph(GraphState)
        graph.add_node("load_runtime_context", load_runtime_context(self))
        graph.add_node("novel_context", novel_context_node(self))
        graph.add_node("plan_chapter", plan_chapter_node(self))
        graph.add_node("generate_draft", generate_draft_node(self))
        graph.add_node("commit_chapter", commit_chapter_node(self))
        graph.add_node("review", review_node(self))
        graph.add_node("rewrite", rewrite_node(self))
        graph.add_node("arc_summary", arc_summary_node(self))
        graph.add_node("volume_summary", volume_summary_node(self))
        graph.add_node("expand_arc", expand_arc_node(self))
        graph.add_node("checkpoint", checkpoint_node(self))
        graph.add_node("finish", finish_node(self))
        graph.add_edge(START, "load_runtime_context")
        graph.add_conditional_edges(
            "load_runtime_context",
            route_after_load,
            {
                "novel_context": "novel_context",
                "generate_draft": "generate_draft",
                "commit_chapter": "commit_chapter",
                "rewrite": "rewrite",
                "polish": "rewrite",
                "finish": "finish",
            },
        )
        graph.add_edge("novel_context", "plan_chapter")
        graph.add_conditional_edges(
            "plan_chapter",
            route_after_plan,
            {
                "generate_draft": "generate_draft",
                "finish": "finish",
            },
        )
        graph.add_edge("generate_draft", "commit_chapter")
        graph.add_conditional_edges(
            "commit_chapter",
            route_after_commit,
            {
                "review": "review",
                "rewrite": "rewrite",
                "polish": "rewrite",
                "arc_summary": "arc_summary",
                "volume_summary": "volume_summary",
                "expand_arc": "expand_arc",
                "checkpoint": "checkpoint",
                "finish": "finish",
            },
        )
        graph.add_conditional_edges(
            "review",
            route_after_commit,
            {
                "rewrite": "rewrite",
                "polish": "rewrite",
                "arc_summary": "arc_summary",
                "volume_summary": "volume_summary",
                "expand_arc": "expand_arc",
                "checkpoint": "checkpoint",
                "finish": "finish",
            },
        )
        graph.add_conditional_edges(
            "arc_summary",
            route_after_commit,
            {
                "volume_summary": "volume_summary",
                "expand_arc": "expand_arc",
                "checkpoint": "checkpoint",
                "finish": "finish",
            },
        )
        graph.add_conditional_edges(
            "volume_summary",
            route_after_commit,
            {
                "expand_arc": "expand_arc",
                "checkpoint": "checkpoint",
                "finish": "finish",
            },
        )
        graph.add_edge("rewrite", "checkpoint")
        graph.add_edge("expand_arc", "checkpoint")
        graph.add_conditional_edges(
            "checkpoint",
            route_after_checkpoint,
            {
                "novel_context": "novel_context",
                "finish": "finish",
            },
        )
        graph.add_edge("finish", END)
        return graph.compile()
