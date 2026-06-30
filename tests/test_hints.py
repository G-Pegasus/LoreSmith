"""HintAction / ActionPlan / parse_hint_actions 单元测试。"""
from __future__ import annotations

from ainovel_py.agents.orchestrator.langgraph.hints import (
    ActionPlan,
    HintAction,
    has_placeholder_action,
    needs_review_from_actions,
    parse_hint_actions,
    plan_actions,
)


# === parse_hint_actions ===

def test_parse_review_required():
    assert parse_hint_actions(["review_required"]) == [HintAction.REVIEW_REQUIRED]


def test_parse_rewrite_required():
    assert parse_hint_actions(["rewrite_required"]) == [HintAction.REWRITE_REQUIRED]


def test_parse_polish_required():
    assert parse_hint_actions(["polish_required"]) == [HintAction.POLISH_REQUIRED]


def test_parse_arc_end():
    assert parse_hint_actions(["arc_end"]) == [HintAction.ARC_END]


def test_parse_book_complete():
    assert parse_hint_actions(["book_complete"]) == [HintAction.BOOK_COMPLETE]


def test_parse_expand_arc_required():
    assert parse_hint_actions(["expand_arc_required"]) == [HintAction.EXPAND_ARC_REQUIRED]


def test_parse_new_volume_required():
    assert parse_hint_actions(["new_volume_required"]) == [HintAction.NEW_VOLUME_REQUIRED]


def test_parse_continue():
    assert parse_hint_actions(["continue"]) == [HintAction.CONTINUE]


def test_parse_writer_feedback():
    assert parse_hint_actions(["writer_feedback"]) == [HintAction.WRITER_FEEDBACK]


def test_parse_review_accepted():
    assert parse_hint_actions(["review_accepted"]) == [HintAction.REVIEW_ACCEPTED]


def test_parse_unknown_hint():
    assert parse_hint_actions(["something_random"]) == [HintAction.UNKNOWN]


def test_parse_multiple_hints():
    result = parse_hint_actions(["review_required", "arc_end", "book_complete"])
    assert result == [HintAction.REVIEW_REQUIRED, HintAction.ARC_END, HintAction.BOOK_COMPLETE]


def test_parse_empty_list():
    assert parse_hint_actions([]) == []


def test_parse_chinese_rewrite_hint():
    """中文"重写_required"关键词也应识别。"""
    assert parse_hint_actions(["重写_required"]) == [HintAction.REWRITE_REQUIRED]


def test_parse_chinese_polish_hint():
    """中文"打磨_required"关键词也应识别。"""
    assert parse_hint_actions(["打磨_required"]) == [HintAction.POLISH_REQUIRED]


def test_parse_chinese_rewrite_done():
    """中文"完成重写"应识别为 REWRITE_DONE。"""
    assert parse_hint_actions(["完成重写"]) == [HintAction.REWRITE_DONE]


def test_parse_case_insensitive():
    """大小写不敏感。"""
    assert parse_hint_actions(["REVIEW_REQUIRED"]) == [HintAction.REVIEW_REQUIRED]


# === plan_actions ===

def test_plan_review_only():
    plan = plan_actions([HintAction.REVIEW_REQUIRED])
    assert plan.requires_review is True
    assert plan.rewrite_mode == ""
    assert plan.queue == []
    assert plan.next_action == "review"


def test_plan_rewrite_only():
    plan = plan_actions([HintAction.REWRITE_REQUIRED])
    assert plan.requires_review is False
    assert plan.rewrite_mode == "rewrite"
    assert plan.next_action == "rewrite"


def test_plan_polish_only():
    plan = plan_actions([HintAction.POLISH_REQUIRED])
    assert plan.rewrite_mode == "polish"
    assert plan.next_action == "polish"


def test_plan_arc_end():
    plan = plan_actions([HintAction.ARC_END])
    assert plan.queue == ["arc_summary"]
    assert plan.next_action == "arc_summary"


def test_plan_book_complete():
    plan = plan_actions([HintAction.BOOK_COMPLETE])
    assert plan.queue == ["volume_summary"]
    assert plan.next_action == "volume_summary"


def test_plan_expand_arc():
    plan = plan_actions([HintAction.EXPAND_ARC_REQUIRED])
    assert plan.queue == ["expand_arc"]
    assert plan.next_action == "expand_arc"


def test_plan_new_volume():
    plan = plan_actions([HintAction.NEW_VOLUME_REQUIRED])
    assert plan.queue == ["expand_arc"]


def test_plan_review_plus_arc_end():
    """review_required + arc_end → review 优先。"""
    plan = plan_actions([HintAction.REVIEW_REQUIRED, HintAction.ARC_END])
    assert plan.requires_review is True
    assert plan.queue == ["arc_summary"]
    assert plan.next_action == "review"


def test_plan_review_plus_rewrite():
    """review_required + rewrite_required → review 优先。"""
    plan = plan_actions([HintAction.REVIEW_REQUIRED, HintAction.REWRITE_REQUIRED])
    assert plan.requires_review is True
    assert plan.rewrite_mode == "rewrite"
    assert plan.next_action == "review"


def test_plan_multiple_milestones():
    """arc_end + book_complete → queue 保持顺序。"""
    plan = plan_actions([HintAction.ARC_END, HintAction.BOOK_COMPLETE])
    assert plan.queue == ["arc_summary", "volume_summary"]


def test_plan_all_milestones():
    """全部里程碑 → 完整队列。"""
    plan = plan_actions([HintAction.ARC_END, HintAction.BOOK_COMPLETE, HintAction.EXPAND_ARC_REQUIRED])
    assert plan.queue == ["arc_summary", "volume_summary", "expand_arc"]


def test_plan_empty():
    """空列表 → 默认 checkpoint。"""
    plan = plan_actions([])
    assert plan.requires_review is False
    assert plan.rewrite_mode == ""
    assert plan.queue == []
    assert plan.next_action == "checkpoint"


def test_plan_rewrite_overwrite_polish():
    """rewrite_required 优先于 polish_required（先出现的生效）。"""
    plan = plan_actions([HintAction.POLISH_REQUIRED, HintAction.REWRITE_REQUIRED])
    assert plan.rewrite_mode == "rewrite"


# === ActionPlan.next_action 优先级 ===

def test_next_action_priority_review_over_rewrite():
    plan = ActionPlan(requires_review=True, rewrite_mode="rewrite")
    assert plan.next_action == "review"


def test_next_action_priority_rewrite_over_queue():
    plan = ActionPlan(rewrite_mode="rewrite", queue=["arc_summary"])
    assert plan.next_action == "rewrite"


def test_next_action_priority_queue_over_checkpoint():
    plan = ActionPlan(queue=["arc_summary"])
    assert plan.next_action == "arc_summary"


def test_next_action_default_checkpoint():
    plan = ActionPlan()
    assert plan.next_action == "checkpoint"


# === needs_review_from_actions ===

def test_needs_review_from_commit_flag():
    assert needs_review_from_actions({"review_required": True}, []) is True


def test_needs_review_from_actions_list():
    assert needs_review_from_actions({}, [HintAction.REVIEW_REQUIRED]) is True


def test_needs_review_false():
    assert needs_review_from_actions({}, [HintAction.ARC_END]) is False


def test_needs_review_empty():
    assert needs_review_from_actions({}, []) is False


# === has_placeholder_action ===

def test_has_placeholder_arc_end():
    assert has_placeholder_action([HintAction.ARC_END]) is True


def test_has_placeholder_book_complete():
    assert has_placeholder_action([HintAction.BOOK_COMPLETE]) is True


def test_has_placeholder_expand_arc():
    assert has_placeholder_action([HintAction.EXPAND_ARC_REQUIRED]) is True


def test_has_placeholder_new_volume():
    assert has_placeholder_action([HintAction.NEW_VOLUME_REQUIRED]) is True


def test_has_placeholder_false():
    assert has_placeholder_action([HintAction.REVIEW_REQUIRED]) is False


def test_has_placeholder_empty():
    assert has_placeholder_action([]) is False


if __name__ == "__main__":
    import sys
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_hints: ok ({len(tests)} tests passed)")
