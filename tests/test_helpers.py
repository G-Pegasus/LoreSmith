"""helpers.py 路由函数单元测试。"""
from __future__ import annotations

from ainovel_py.agents.orchestrator.langgraph.nodes.helpers import (
    route_after_load,
    route_after_plan,
    route_after_commit,
    route_after_checkpoint,
    route_from_supervisor,
)


# === route_after_load ===

def test_load_default():
    """无 pending_action → novel_context。"""
    assert route_after_load({}) == "novel_context"


def test_load_generate_draft():
    assert route_after_load({"pending_action": "generate_draft"}) == "generate_draft"


def test_load_commit_chapter():
    assert route_after_load({"pending_action": "commit_chapter"}) == "commit_chapter"


def test_load_rewrite():
    assert route_after_load({"pending_action": "rewrite"}) == "rewrite"


def test_load_polish():
    """polish 映射为 rewrite。"""
    assert route_after_load({"pending_action": "polish"}) == "rewrite"


def test_load_finish():
    assert route_after_load({"pending_action": "finish"}) == "finish"


def test_load_novel_context():
    assert route_after_load({"pending_action": "novel_context"}) == "novel_context"


# === route_after_plan ===

def test_plan_default():
    """无 pending_action → generate_draft。"""
    assert route_after_plan({}) == "generate_draft"


def test_plan_finish():
    assert route_after_plan({"pending_action": "finish"}) == "finish"


def test_plan_generate_draft():
    assert route_after_plan({"pending_action": "generate_draft"}) == "generate_draft"


# === route_after_commit ===

def test_commit_default():
    """无 pending_action → checkpoint。"""
    assert route_after_commit({}) == "checkpoint"


def test_commit_review():
    assert route_after_commit({"pending_action": "review"}) == "review"


def test_commit_rewrite():
    assert route_after_commit({"pending_action": "rewrite"}) == "rewrite"


def test_commit_polish():
    """polish 映射为 rewrite。"""
    assert route_after_commit({"pending_action": "polish"}) == "rewrite"


def test_commit_arc_summary():
    assert route_after_commit({"pending_action": "arc_summary"}) == "arc_summary"


def test_commit_volume_summary():
    assert route_after_commit({"pending_action": "volume_summary"}) == "volume_summary"


def test_commit_expand_arc():
    assert route_after_commit({"pending_action": "expand_arc"}) == "expand_arc"


def test_commit_finish():
    assert route_after_commit({"pending_action": "finish"}) == "finish"


# === route_after_checkpoint ===

def test_checkpoint_continue():
    """continue → novel_context。"""
    assert route_after_checkpoint({"pending_action": "continue"}) == "novel_context"


def test_checkpoint_novel_context():
    assert route_after_checkpoint({"pending_action": "novel_context"}) == "novel_context"


def test_checkpoint_arc_summary():
    assert route_after_checkpoint({"pending_action": "arc_summary"}) == "arc_summary"


def test_checkpoint_volume_summary():
    assert route_after_checkpoint({"pending_action": "volume_summary"}) == "volume_summary"


def test_checkpoint_expand_arc():
    assert route_after_checkpoint({"pending_action": "expand_arc"}) == "expand_arc"


def test_checkpoint_rewrite():
    assert route_after_checkpoint({"pending_action": "rewrite"}) == "rewrite"


def test_checkpoint_finish():
    assert route_after_checkpoint({"pending_action": "finish"}) == "finish"


def test_checkpoint_default():
    """无 pending_action → finish。"""
    assert route_after_checkpoint({}) == "finish"


# === route_from_supervisor ===

def test_supervisor_architect():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "architect"}}) == "novel_context"


def test_supervisor_writer():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "writer"}}) == "generate_draft"


def test_supervisor_editor():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "editor"}}) == "review"


def test_supervisor_rewrite():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "rewrite"}}) == "rewrite"


def test_supervisor_arc_summary():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "arc_summary"}}) == "arc_summary"


def test_supervisor_volume_summary():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "volume_summary"}}) == "volume_summary"


def test_supervisor_expand_arc():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "expand_arc"}}) == "expand_arc"


def test_supervisor_checkpoint():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "checkpoint"}}) == "checkpoint"


def test_supervisor_finish():
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "FINISH"}}) == "finish"


def test_supervisor_invalid_decision_fallback():
    """无效 decision → 回退到 route_after_commit（默认 checkpoint）。"""
    assert route_from_supervisor({"supervisor_decision": {"next_agent": "unknown_agent"}}) == "checkpoint"


def test_supervisor_no_decision_fallback():
    """无 decision → 回退。"""
    assert route_from_supervisor({}) == "checkpoint"


def test_supervisor_none_decision_fallback():
    """decision 为 None → 回退。"""
    assert route_from_supervisor({"supervisor_decision": None}) == "checkpoint"


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_helpers: ok ({len(tests)} tests passed)")
