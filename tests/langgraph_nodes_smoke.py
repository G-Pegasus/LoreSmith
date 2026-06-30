from __future__ import annotations

from ainovel_py.agents.hints import HintAction
from ainovel_py.agents.orchestrator.langgraph.actions import plan_actions
from ainovel_py.agents.orchestrator.langgraph.nodes.core import (
    route_after_checkpoint,
    route_after_commit,
    route_after_load,
)


def main() -> int:
    plan = plan_actions([HintAction.REVIEW_REQUIRED, HintAction.ARC_END, HintAction.BOOK_COMPLETE])
    if not plan.requires_review:
        raise RuntimeError("structured action plan lost review flag")
    if plan.queue != ["arc_summary", "volume_summary"]:
        raise RuntimeError(f"unexpected action queue: {plan.queue}")
    rewrite_plan = plan_actions([HintAction.REWRITE_REQUIRED])
    if rewrite_plan.rewrite_mode != "rewrite":
        raise RuntimeError("rewrite action plan missing rewrite mode")
    polish_plan = plan_actions([HintAction.POLISH_REQUIRED])
    if polish_plan.rewrite_mode != "polish":
        raise RuntimeError("rewrite action plan missing polish mode")
    if route_after_load({"pending_action": "generate_draft"}) != "generate_draft":
        raise RuntimeError("load generate_draft route broken")
    if route_after_load({"pending_action": "commit_chapter"}) != "commit_chapter":
        raise RuntimeError("load commit route broken")
    if route_after_load({"pending_action": "rewrite"}) != "rewrite":
        raise RuntimeError("load rewrite route broken")
    if route_after_load({"pending_action": "polish"}) != "rewrite":
        raise RuntimeError("load polish route broken")
    if route_after_commit({"pending_action": "review"}) != "review":
        raise RuntimeError("review route broken")
    if route_after_commit({"pending_action": "rewrite"}) != "rewrite":
        raise RuntimeError("rewrite route broken")
    if route_after_commit({"pending_action": "polish"}) != "rewrite":
        raise RuntimeError("polish route broken")
    if route_after_commit({"pending_action": "arc_summary"}) != "arc_summary":
        raise RuntimeError("arc_summary route broken")
    if route_after_commit({"pending_action": "volume_summary"}) != "volume_summary":
        raise RuntimeError("volume_summary route broken")
    if route_after_commit({"pending_action": "expand_arc"}) != "expand_arc":
        raise RuntimeError("expand_arc route broken")
    if route_after_checkpoint({"pending_action": "continue"}) != "novel_context":
        raise RuntimeError("continue route broken")
    if route_after_checkpoint({"pending_action": "arc_summary"}) != "arc_summary":
        raise RuntimeError("checkpoint arc_summary route broken")
    if route_after_checkpoint({"pending_action": "volume_summary"}) != "volume_summary":
        raise RuntimeError("checkpoint volume_summary route broken")
    if route_after_checkpoint({"pending_action": "expand_arc"}) != "expand_arc":
        raise RuntimeError("checkpoint expand_arc route broken")
    print("langgraph_nodes_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
