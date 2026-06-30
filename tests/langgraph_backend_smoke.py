from __future__ import annotations

from ainovel_py.agents.build import build_coordinator_loop, build_tool_registry
from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.store.store import Store


def _cfg() -> Config:
    return Config(
        output_dir="output/novel",
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="dummy-key")},
        style="default",
        context_window=128000,
    )


def main() -> int:
    store = Store("output/novel")
    store.init()

    cfg_default = Config(
        output_dir="output/novel",
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="dummy-key")},
        style="default",
        context_window=128000,
    )
    cfg_default.fill_defaults()

    tools = build_tool_registry(store)
    if "novel_context" not in tools:
        raise RuntimeError("tool registry missing novel_context")

    try:
        from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime
    except ModuleNotFoundError as exc:
        if exc.name == "langgraph":
            print("langgraph_backend_smoke: skipped (langgraph not installed)")
            return 0
        raise

    loop = build_coordinator_loop(cfg_default, store, lambda event: None, lambda channel, delta: None)
    if not isinstance(loop.backend, LangGraphRuntime):
        raise RuntimeError("default backend should be langgraph")

    cfg_langgraph = _cfg()
    loop = build_coordinator_loop(cfg_langgraph, store, lambda event: None, lambda channel, delta: None)
    if not isinstance(loop.backend, LangGraphRuntime):
        raise RuntimeError("langgraph backend not selected")

    runtime = LangGraphRuntime(cfg_langgraph, loop.backend.runner, store, lambda event: None, lambda channel, delta: None)
    compiled = runtime._build_graph()
    if compiled is None:
        raise RuntimeError("langgraph graph did not compile")
    graph_view = runtime.graph.get_graph()
    node_ids = set(graph_view.nodes)
    required_nodes = {
        "plan_chapter",
        "commit_chapter",
        "review",
        "arc_summary",
        "volume_summary",
        "expand_arc",
        "checkpoint",
    }
    missing = sorted(required_nodes - node_ids)
    if missing:
        raise RuntimeError(f"missing graph nodes: {missing}")

    print("langgraph_backend_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
