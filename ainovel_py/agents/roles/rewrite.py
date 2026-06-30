from __future__ import annotations

from datetime import datetime
from typing import Any

from ainovel_py.host.events import Event

from .base import BaseAgent


class RewriteAgent(BaseAgent):
    name = "rewrite"

    def system_prompt(self) -> str:
        return self.assets.prompts.get("editor") or "你是小说编辑助手，负责根据评审意见制定重写方案。"

    def build_rewrite_context(self, progress: Any, context: dict[str, Any]) -> dict[str, Any]:
        """构建重写上下文，将评审意见注入到 context 中。

        Args:
            progress: 进度对象，包含 pending_rewrites、rewrite_reason 等
            context: 原始上下文（来自 novel_context 工具）

        Returns:
            注入了重写信息的上下文
        """
        from dataclasses import asdict

        context = dict(context or {})
        chapter = progress.pending_rewrites[0] if progress and progress.pending_rewrites else 0
        if chapter > 0:
            review = self.store.world.load_last_review(chapter)
            if review:
                context["latest_review"] = asdict(review)
                context["rewrite_issues"] = [asdict(it) for it in (review.issues or [])]
        if progress and progress.rewrite_reason:
            context["rewrite_reason"] = progress.rewrite_reason
        return context

    def execute(self, *, chapter: int, context: dict[str, Any], review_result: dict[str, Any], rewrite_mode: str = "rewrite") -> dict[str, Any]:
        issues = review_result.get("issues") or []
        verdict = review_result.get("final_verdict") or review_result.get("verdict") or "rewrite"
        summary = review_result.get("summary") or ""

        issue_text = "\n".join(
            f"- [{it.get('severity', 'info')}] {it.get('description', '')} (建议: {it.get('suggestion', '')})"
            for it in issues
        ) if issues else "无具体问题列表"

        rewrite_notes = (
            f"评审结论: {verdict}\n"
            f"评审摘要: {summary}\n"
            f"需修正的问题:\n{issue_text}\n"
            f"重写模式: {rewrite_mode}"
        )

        self.emit_event(Event(
            time=datetime.now(),
            category="AGENT",
            summary=f"RewriteAgent: 第{chapter}章重写方案已制定 (mode={rewrite_mode}, verdict={verdict})",
            level="info",
        ))

        return {
            "chapter": chapter,
            "rewrite_mode": rewrite_mode,
            "rewrite_reason": summary,
            "rewrite_issues": issues,
            "rewrite_notes": rewrite_notes,
        }
