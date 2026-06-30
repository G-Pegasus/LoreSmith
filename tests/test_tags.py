"""TaskTag 枚举的单元测试。"""
from __future__ import annotations

from ainovel_py.agents.orchestrator.tags import TaskTag


def test_task_tag_values():
    """验证 TaskTag 枚举值正确。"""
    assert TaskTag.PLAN_CHAPTER.value == "plan_chapter"
    assert TaskTag.WRITE_CHAPTER.value == "write_chapter"
    assert TaskTag.COMMIT_CHAPTER.value == "commit_chapter"
    assert TaskTag.REVIEW_CHAPTER.value == "review_chapter"
    assert TaskTag.REWRITE_CHAPTER.value == "rewrite_chapter"
    assert TaskTag.ARC_SUMMARY.value == "arc_summary"
    assert TaskTag.VOLUME_SUMMARY.value == "volume_summary"
    assert TaskTag.EXPAND_ARC.value == "expand_arc"
    assert TaskTag.FINISH.value == "finish"


def test_task_tag_count():
    """验证 TaskTag 共 9 个枚举值。"""
    assert len(TaskTag) == 9


def test_task_tag_is_string():
    """验证 TaskTag 是 str 的子类，可用于字典键。"""
    tag = TaskTag.PLAN_CHAPTER
    assert isinstance(tag, str)
    d = {tag: "test"}
    assert d["plan_chapter"] == "test"


if __name__ == "__main__":
    test_task_tag_values()
    test_task_tag_count()
    test_task_tag_is_string()
    print("test_tags: ok")
