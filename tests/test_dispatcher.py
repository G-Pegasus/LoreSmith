"""主 Agent 调度器 dispatch_next() 的单元测试。

测试覆盖场景：
1. 初始启动（无 last_completed_tag）
2. 规划完成 → 写作
3. 写作完成 → 提交
4. 提交完成 → 根据 hints 决定
5. 评审完成 → 根据 verdict 决定
6. 重写完成 → 提交
7. 摘要完成 → 规划
8. pending_action 直接映射
9. finish 场景
"""
from __future__ import annotations

from ainovel_py.agents.orchestrator.dispatcher import dispatch_next
from ainovel_py.agents.orchestrator.tags import TaskTag


def _state(**kwargs) -> dict:
    """构建测试用的状态字典。"""
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


# === 初始启动场景 ===

def test_initial_no_pending_action():
    """无 pending_action 且无 last_completed_tag → 默认规划。"""
    state = _state()
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_initial_with_pending_commit():
    """pending_action=commit_chapter → 提交。"""
    state = _state(pending_action="commit_chapter")
    assert dispatch_next(state) == TaskTag.COMMIT_CHAPTER


def test_initial_with_pending_generate_draft():
    """pending_action=generate_draft → 写作。"""
    state = _state(pending_action="generate_draft")
    assert dispatch_next(state) == TaskTag.WRITE_CHAPTER


def test_initial_with_pending_review():
    """pending_action=review → 评审。"""
    state = _state(pending_action="review")
    assert dispatch_next(state) == TaskTag.REVIEW_CHAPTER


def test_initial_with_pending_rewrite():
    """pending_action=rewrite → 重写。"""
    state = _state(pending_action="rewrite")
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_initial_with_pending_polish():
    """pending_action=polish → 重写（polish 映射为 rewrite）。"""
    state = _state(pending_action="polish")
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_initial_with_pending_arc_summary():
    """pending_action=arc_summary → 弧摘要。"""
    state = _state(pending_action="arc_summary")
    assert dispatch_next(state) == TaskTag.ARC_SUMMARY


def test_initial_with_pending_volume_summary():
    """pending_action=volume_summary → 卷摘要。"""
    state = _state(pending_action="volume_summary")
    assert dispatch_next(state) == TaskTag.VOLUME_SUMMARY


def test_initial_with_pending_expand_arc():
    """pending_action=expand_arc → 大纲扩展。"""
    state = _state(pending_action="expand_arc")
    assert dispatch_next(state) == TaskTag.EXPAND_ARC


def test_initial_with_pending_finish():
    """pending_action=finish → 结束。"""
    state = _state(pending_action="finish")
    assert dispatch_next(state) == TaskTag.FINISH


def test_initial_with_pending_novel_context():
    """pending_action=novel_context → 规划（新章节开始）。"""
    state = _state(pending_action="novel_context")
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_initial_with_pending_continue():
    """pending_action=continue → 规划（继续下一章）。"""
    state = _state(pending_action="continue")
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


# === 规划完成场景 ===

def test_after_plan_chapter():
    """规划完成 → 写作。"""
    state = _state(last_completed_tag=TaskTag.PLAN_CHAPTER.value)
    assert dispatch_next(state) == TaskTag.WRITE_CHAPTER


# === 写作完成场景 ===

def test_after_write_chapter():
    """写作完成 → 提交。"""
    state = _state(last_completed_tag=TaskTag.WRITE_CHAPTER.value)
    assert dispatch_next(state) == TaskTag.COMMIT_CHAPTER


# === 提交完成场景 ===

def test_after_commit_no_hints():
    """提交完成无 hints → 规划（下一章）。"""
    state = _state(last_completed_tag=TaskTag.COMMIT_CHAPTER.value)
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_after_commit_with_review_hint():
    """提交完成有 review_required hint → 评审。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["review_required"]},
    )
    assert dispatch_next(state) == TaskTag.REVIEW_CHAPTER


def test_after_commit_with_arc_end_hint():
    """提交完成有 arc_end hint → 弧摘要。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["arc_end"]},
    )
    assert dispatch_next(state) == TaskTag.ARC_SUMMARY


def test_after_commit_with_book_complete_hint():
    """提交完成有 book_complete hint → 卷摘要。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["book_complete"]},
    )
    assert dispatch_next(state) == TaskTag.VOLUME_SUMMARY


def test_after_commit_with_expand_arc_hint():
    """提交完成有 expand_arc_required hint → 大纲扩展。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["expand_arc_required"]},
    )
    assert dispatch_next(state) == TaskTag.EXPAND_ARC


def test_after_commit_with_rewrite_hint():
    """提交完成有 rewrite_required hint → 重写。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["rewrite_required"]},
    )
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_after_commit_with_multiple_hints_review_first():
    """提交完成有 review_required + arc_end → 评审优先。"""
    state = _state(
        last_completed_tag=TaskTag.COMMIT_CHAPTER.value,
        latest_commit_result={"system_hints": ["review_required", "arc_end"]},
    )
    assert dispatch_next(state) == TaskTag.REVIEW_CHAPTER


# === 评审完成场景 ===

def test_after_review_accept():
    """评审通过 → 规划（下一章）。"""
    state = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"final_verdict": "accept"},
    )
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_after_review_polish():
    """评审需要打磨 → 重写。"""
    state = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"final_verdict": "polish"},
    )
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_after_review_rewrite():
    """评审需要重写 → 重写。"""
    state = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"final_verdict": "rewrite"},
    )
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_after_review_no_verdict_with_rewrite_hint():
    """评审无标准 verdict 但有 rewrite hint → 重写。"""
    state = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={"system_hints": ["rewrite_required"]},
    )
    assert dispatch_next(state) == TaskTag.REWRITE_CHAPTER


def test_after_review_no_verdict_no_hints():
    """评审无 verdict 无 hints → 默认规划。"""
    state = _state(
        last_completed_tag=TaskTag.REVIEW_CHAPTER.value,
        latest_review_result={},
    )
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


# === 重写完成场景 ===

def test_after_rewrite_chapter():
    """重写完成 → 提交。"""
    state = _state(last_completed_tag=TaskTag.REWRITE_CHAPTER.value)
    assert dispatch_next(state) == TaskTag.COMMIT_CHAPTER


# === 摘要完成场景 ===

def test_after_arc_summary():
    """弧摘要完成 → 规划。"""
    state = _state(last_completed_tag=TaskTag.ARC_SUMMARY.value)
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_after_volume_summary():
    """卷摘要完成 → 规划。"""
    state = _state(last_completed_tag=TaskTag.VOLUME_SUMMARY.value)
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


def test_after_expand_arc():
    """大纲扩展完成 → 规划。"""
    state = _state(last_completed_tag=TaskTag.EXPAND_ARC.value)
    assert dispatch_next(state) == TaskTag.PLAN_CHAPTER


# === pending_action 优先级 ===

def test_pending_action_overrides_last_tag():
    """pending_action 优先于 last_completed_tag。"""
    state = _state(
        last_completed_tag=TaskTag.PLAN_CHAPTER.value,  # 规划完成 → 应该写作
        pending_action="review",  # 但 pending_action 指定评审
    )
    assert dispatch_next(state) == TaskTag.REVIEW_CHAPTER


# === 完整链路模拟 ===

def test_full_chapter_flow():
    """模拟完整的单章流程：规划 → 写作 → 提交 → 下一章。"""
    # 1. 初始 → 规划
    state = _state()
    tag = dispatch_next(state)
    assert tag == TaskTag.PLAN_CHAPTER

    # 2. 规划完成 → 写作
    state["last_completed_tag"] = tag.value
    tag = dispatch_next(state)
    assert tag == TaskTag.WRITE_CHAPTER

    # 3. 写作完成 → 提交
    state["last_completed_tag"] = tag.value
    tag = dispatch_next(state)
    assert tag == TaskTag.COMMIT_CHAPTER

    # 4. 提交完成（无 hints）→ 下一章规划
    state["last_completed_tag"] = tag.value
    tag = dispatch_next(state)
    assert tag == TaskTag.PLAN_CHAPTER


def test_chapter_with_review_flow():
    """模拟带评审的章节流程：规划 → 写作 → 提交 → 评审 → 通过 → 下一章。"""
    state = _state()

    # 规划 → 写作 → 提交
    for _ in range(3):
        tag = dispatch_next(state)
        state["last_completed_tag"] = tag.value

    assert tag == TaskTag.COMMIT_CHAPTER

    # 提交后有 review_required hint
    state["latest_commit_result"] = {"system_hints": ["review_required"]}
    tag = dispatch_next(state)
    assert tag == TaskTag.REVIEW_CHAPTER

    # 评审通过
    state["last_completed_tag"] = tag.value
    state["latest_review_result"] = {"final_verdict": "accept"}
    tag = dispatch_next(state)
    assert tag == TaskTag.PLAN_CHAPTER


def test_chapter_with_rewrite_flow():
    """模拟重写流程：评审完成 → 重写 → 提交。"""
    state = _state(last_completed_tag=TaskTag.REVIEW_CHAPTER.value)

    # 评审需要重写
    state["latest_review_result"] = {"final_verdict": "rewrite"}
    tag = dispatch_next(state)
    assert tag == TaskTag.REWRITE_CHAPTER

    # 重写完成 → 提交
    state["last_completed_tag"] = tag.value
    tag = dispatch_next(state)
    assert tag == TaskTag.COMMIT_CHAPTER


if __name__ == "__main__":
    import sys
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_dispatcher: ok ({len(tests)} tests passed)")
