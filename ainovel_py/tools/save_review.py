from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.domain.checkpoint import arc_scope, chapter_scope
from ainovel_py.domain.review import ReviewEntry
from ainovel_py.domain.runtime import FlowState
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import parse_review_entry

_EXPECTED_DIMENSIONS = {
    "consistency",
    "continuity",
    "voice",
    "emotional_impact",
    "rhythm_variety",
    "surprise",
    "restraint",
}

_CRITICAL_DIMENSIONS = {"consistency", "continuity"}
_AESTHETIC_DIMENSIONS = {"voice", "emotional_impact", "rhythm_variety", "surprise", "restraint"}


class SaveReviewTool:
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "save_review"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        review = parse_review_entry(args)
        normalization_hints: list[str] = []
        if review.verdict in {"rewrite", "polish"} and not review.affected_chapters and review.chapter > 0:
            review.affected_chapters = [review.chapter]
        normalization_hints.extend(self._normalize_dimensions(review))
        self._validate_review_entry(review)

        self.store.world.save_review(review)
        self.store.signals.save_last_review(asdict(review))

        final_verdict = review.verdict
        escalation_reason = ""
        if review.verdict == "accept":
            gate = self._evaluate_scorecard_gate(review)
            if gate:
                final_verdict = "rewrite" if gate.startswith("rewrite:") else "polish"
                escalation_reason = gate

        hints: list[str] = []
        hints.extend(normalization_hints)
        progress = self.store.progress.load()
        if final_verdict in {"rewrite", "polish"}:
            completed = set(progress.completed_chapters) if progress else set()
            affected = [ch for ch in review.affected_chapters if ch in completed]
            dropped = [ch for ch in review.affected_chapters if ch not in completed]
            if dropped:
                hints.append(f"[系统] review_filtered: 未完成章节不会进入重写队列 {dropped}。")
            if not affected and review.chapter > 0 and review.chapter in completed:
                affected = [review.chapter]
            flow = FlowState.REWRITING
            verb = "重写"
            if final_verdict == "polish":
                flow = FlowState.POLISHING
                verb = "打磨"
            self.store.progress.set_pending_rewrites(affected, review.summary)
            self.store.progress.set_flow(flow)
            hint = f"[系统] {verb}_required: 审阅结论为 {final_verdict}，受影响章节 {affected}。"
            if escalation_reason:
                hint += f" （升级原因：{escalation_reason}）"
            hint += f" 请逐章调用 writer 执行{verb}，全部完成后再继续写新章节。"
            hints.append(hint)
        else:
            self.store.progress.set_flow(FlowState.WRITING)
            next_ch = progress.next_chapter() if progress else review.chapter + 1
            hints.append(f"[系统] review_accepted: 审阅通过，继续写第 {next_ch} 章。")

        if review.scope == "arc":
            progress = self.store.progress.load()
            vol = progress.current_volume if progress else 0
            arc = progress.current_arc if progress else 0
            self.store.checkpoints.append(arc_scope(vol, arc), "review")
        else:
            self.store.checkpoints.append(chapter_scope(review.chapter), "review")

        return {
            "saved": True,
            "chapter": review.chapter,
            "scope": review.scope,
            "verdict": review.verdict,
            "final_verdict": final_verdict,
            "escalation": escalation_reason,
            "issues": len(review.issues),
            "system_hints": hints,
        }

    def _validate_review_entry(self, review: ReviewEntry) -> None:
        if review.chapter <= 0:
            raise ValueError("chapter must be > 0")
        if not review.scope.strip():
            raise ValueError("scope is required")
        if not review.summary.strip():
            raise ValueError("summary is required")
        if (review.verdict in {"rewrite", "polish"}) and not review.affected_chapters:
            raise ValueError(f"affected_chapters is required when verdict={review.verdict}")

        for issue in review.issues:
            if not issue.description.strip():
                raise ValueError("issue description is required")
            if not issue.evidence.strip():
                raise ValueError("issue evidence is required")

        self._validate_dimensions(review)

    def _normalize_dimensions(self, review: ReviewEntry) -> list[str]:
        hints: list[str] = []
        for dim in review.dimensions:
            expected = self._expected_dimension_verdict(dim.score)
            if dim.verdict != expected:
                hints.append(
                    f"[系统] review_normalized: 维度 {dim.dimension} 的 verdict 已从 {dim.verdict} 修正为 {expected}（score={dim.score}）。"
                )
                dim.verdict = expected
        return hints

    def _validate_dimensions(self, review: ReviewEntry) -> None:
        if len(review.dimensions) != len(_EXPECTED_DIMENSIONS):
            raise ValueError(f"dimensions must contain exactly {len(_EXPECTED_DIMENSIONS)} entries")
        seen: set[str] = set()
        for dim in review.dimensions:
            if dim.dimension not in _EXPECTED_DIMENSIONS:
                raise ValueError(f"unknown dimension: {dim.dimension}")
            if dim.dimension in seen:
                raise ValueError(f"duplicate dimension: {dim.dimension}")
            seen.add(dim.dimension)
            if dim.score < 0 or dim.score > 100:
                raise ValueError(f"invalid score for {dim.dimension}: {dim.score}")
            expected = self._expected_dimension_verdict(dim.score)
            if dim.verdict != expected:
                raise ValueError(
                    f"dimension {dim.dimension} has inconsistent score/verdict: score={dim.score} verdict={dim.verdict}"
                )
            if dim.dimension in _AESTHETIC_DIMENSIONS and not dim.comment.strip():
                raise ValueError(f"{dim.dimension} comment is required")

    @staticmethod
    def _expected_dimension_verdict(score: int) -> str:
        if score >= 80:
            return "pass"
        if score >= 60:
            return "warning"
        return "fail"

    def _evaluate_scorecard_gate(self, review: ReviewEntry) -> str:
        critical_fails: list[str] = []
        polish_issues: list[str] = []
        for dim in review.dimensions:
            is_critical = dim.dimension in _CRITICAL_DIMENSIONS
            if is_critical and (dim.verdict == "fail" or dim.score < 60):
                critical_fails.append(f"{dim.dimension}({dim.score})")
            elif dim.dimension in _AESTHETIC_DIMENSIONS and dim.verdict == "fail":
                critical_fails.append(f"{dim.dimension}({dim.score})")
            elif dim.dimension in _AESTHETIC_DIMENSIONS and dim.verdict in {"warning", "fail"}:
                polish_issues.append(f"{dim.dimension}({dim.score})")
        if critical_fails:
            return f"rewrite: 关键维度不合格 {critical_fails}"
        if polish_issues:
            return f"polish: 审美维度需打磨 {polish_issues}"
        return ""
