from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .helpers import _append_line, _enqueue_hint_actions
from ..post_commit import plan_post_commit
from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


def commit_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """创建章节提交节点工厂函数。

    这是状态变更最复杂的节点，负责：
    1. 提取草稿元数据（人物、事件、伏笔、关系变化等）
    2. 生成章节摘要
    3. 执行 write-commit 循环（draft_chapter → check_consistency → commit_chapter）
    4. 解析提交结果的 system_hints，规划后续动作（评审/重写/摘要）

    输出包括：state["latest_commit_result"]、state["latest_commit_hints"]、
    以及通过 plan_post_commit 设置的 pending_action/pending_actions。

    Args:
        runtime: LangGraphRuntime 实例

    Returns:
        节点函数，输出 commit 结果和后续动作规划
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")
        if not draft:
            draft = runtime.store.drafts.load_draft(chapter)
            state["latest_draft"] = draft
        if not draft:
            raise RuntimeError(f"chapter {chapter} draft is empty")
        editor = runtime.get_agent("editor")
        client = editor.build_client()
        metadata = editor.extract_metadata(chapter=chapter, draft=draft)
        writer = runtime.get_agent("writer")
        summary = str(metadata.get("summary", "") or writer.summarize_chapter(client, chapter, draft))
        draft_res, commit_res = editor.run_write_commit_cycle(chapter, draft, summary, metadata)
        state["latest_commit_result"] = commit_res
        _append_line(state, f"[tool] commit_chapter -> chapter={chapter}")
        _append_line(state, f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
        _append_line(state, f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
        plan = plan_post_commit(commit_res, chapter)
        if plan.hints:
            _append_line(state, "[hints] " + " | ".join(plan.hints))
            state["latest_commit_hints"] = list(plan.hints)
        next_action = _enqueue_hint_actions(state, plan.actions)
        state["pending_review_for"] = plan.pending_review_for
        state["pending_action"] = next_action if plan.next_action == next_action or next_action != "checkpoint" else plan.next_action
        return state

    return _node
