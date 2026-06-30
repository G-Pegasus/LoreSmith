from __future__ import annotations

from ainovel_py.agents.runner import AgentRunner, CoordinatorLoop
from ainovel_py.bootstrap.config import Config
from ainovel_py.store.store import Store
from ainovel_py.tools import (
    CheckConsistencyTool,
    CommitChapterTool,
    DraftChapterTool,
    NovelContextTool,
    PlanChapterTool,
    ReadChapterTool,
    SaveArcSummaryTool,
    SaveFoundationTool,
    SaveReviewTool,
    SaveVolumeSummaryTool,
)


def build_tool_registry(store: Store) -> dict[str, object]:
    tools = [
        NovelContextTool(store, style=store.run_meta.load().style if store.run_meta.load() else "default"),
        SaveFoundationTool(store),
        ReadChapterTool(store),
        PlanChapterTool(store),
        DraftChapterTool(store),
        CheckConsistencyTool(store),
        CommitChapterTool(store),
        SaveReviewTool(store),
        SaveArcSummaryTool(store),
        SaveVolumeSummaryTool(store),
    ]
    return {tool.name(): tool for tool in tools}


def _build_langgraph_runtime(
    cfg: Config,
    runner: AgentRunner,
    store: Store,
    emit_event,
    emit_stream,
    on_checkpoint_pending=None,
):
    from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime

    return LangGraphRuntime(cfg, runner, store, emit_event, emit_stream, on_checkpoint_pending=on_checkpoint_pending)


def build_coordinator_loop(
    cfg: Config,
    store: Store,
    emit_event,
    emit_stream,
    on_checkpoint_pending=None,
) -> CoordinatorLoop:
    runner = AgentRunner(build_tool_registry(store))
    impl = _build_langgraph_runtime(cfg, runner, store, emit_event, emit_stream, on_checkpoint_pending=on_checkpoint_pending)
    return CoordinatorLoop(impl)
