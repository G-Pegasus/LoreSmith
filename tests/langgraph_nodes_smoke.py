"""新架构 smoke test：验证 TaskTag + dispatcher + 路由函数。

替代旧版 langgraph_nodes_smoke.py（旧版引用已删除的 actions.py 和 route_after_commit）。
"""
from __future__ import annotations

from ainovel_py.agents.orchestrator.dispatcher import dispatch_next
from ainovel_py.agents.orchestrator.tags import TaskTag
from ainovel_py.agents.orchestrator.langgraph.nodes.helpers import (
    route_after_load,
    route_after_checkpoint,
)


def _state(**kwargs) -> dict:
    base = {
        "seed_text": "test",
        "current_chapter": 1,
        "last_completed_tag": "",
        "current_tag": "",
        "pending_action": "",
        "pending_actions": [],
        "latest_commit_result": {},
        "latest_review_result": {},
    }
    base.update(kwargs)
    return base


def main() -> int:
    # 1. TaskTag 枚举完整性
    assert len(TaskTag) == 9, f"expected 9 tags, got {len(TaskTag)}"
    assert TaskTag.PLAN_CHAPTER.value == "plan_chapter"
    assert TaskTag.FINISH.value == "finish"

    # 2. dispatcher 规则链路
    s = _state()
    assert dispatch_next(s) == TaskTag.PLAN_CHAPTER, "initial → plan"

    s = _state(last_completed_tag=TaskTag.PLAN_CHAPTER.value)
    assert dispatch_next(s) == TaskTag.WRITE_CHAPTER, "plan → write"

    s = _state(last_completed_tag=TaskTag.WRITE_CHAPTER.value)
    assert dispatch_next(state=s) == TaskTag.COMMIT_CHAPTER, "write → commit"

    s = _state(last_completed_tag=TaskTag.COMMIT_CHAPTER.value)
    assert dispatch_next(s) == TaskTag.PLAN_CHAPTER, "commit (no hints) → plan"

    s = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["review_required"]},
    )
    assert dispatch_next(s) == TaskTag.REVIEW_CHAPTER, "commit (review hint) → review"

    s = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"final_verdict": "accept"},
    )
    assert dispatch_next(s) == TaskTag.PLAN_CHAPTER, "review (accept) → plan"

    s = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"final_verdict": "rewrite"},
    )
    assert dispatch_next(s) == TaskTag.REWRITE_CHAPTER, "review (rewrite) → rewrite"

    s = _state(last_completed_tag=TaskTag.REWRITE_CHAPTER.value)
    assert dispatch_next(s) == TaskTag.COMMIT_CHAPTER, "rewrite → commit"

    # 3. pending_action 覆盖
    s = _state(pending_action="finish")
    assert dispatch_next(s) == TaskTag.FINISH, "pending finish → finish"

    # 4. route_after_load 仍可用
    assert route_after_load({"pending_action": "commit_chapter"}) == "commit_chapter"
    assert route_after_load({"pending_action": "generate_draft"}) == "generate_draft"
    assert route_after_load({"pending_action": "finish"}) == "finish"

    # 5. route_after_checkpoint 仍可用
    assert route_after_checkpoint({"pending_action": "continue"}) == "novel_context"
    assert route_after_checkpoint({"pending_action": "arc_summary"}) == "arc_summary"

    print("langgraph_nodes_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
