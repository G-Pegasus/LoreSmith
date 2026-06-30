from __future__ import annotations

from dataclasses import asdict

from ainovel_py.domain.commit import PendingCommit
from ainovel_py.domain.review import (
    ConsistencyIssue,
    DimensionScore,
    ReviewEntry,
)
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.store.io import IO


class SignalStore:
    """
    信号存储管理器
    
    负责管理临时信号和状态标志，用于进程间通信和断点恢复：
    - last_commit: 最后一次提交结果
    - pending_commit: 待完成的提交（用于中断恢复）
    - pending_checkpoint: 待确认的检查点（用于用户确认）
    - last_review: 最后一次评审结果
    
    这些信号通常是一次性的，使用后会被清除。
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_last_commit(self, result: dict) -> None:
        """保存最后一次提交结果"""
        self.io.write_json("meta/last_commit.json", result)

    def load_last_commit(self) -> dict | None:
        """加载最后一次提交结果"""
        try:
            return self.io.read_json("meta/last_commit.json")
        except FileNotFoundError:
            return None

    def load_and_clear_last_commit(self) -> dict | None:
        """加载并清除最后一次提交结果（原子操作）"""
        data = self.load_last_commit()
        if data is not None:
            self.clear_last_commit()
        return data

    def clear_last_commit(self) -> None:
        """清除最后一次提交结果"""
        self.io.remove_file("meta/last_commit.json")

    def save_pending_commit(self, pending: PendingCommit) -> None:
        """保存待完成的提交（用于中断恢复）"""
        self.io.write_json("meta/pending_commit.json", asdict(pending))

    def load_pending_commit(self) -> PendingCommit | None:
        """加载待完成的提交"""
        try:
            data = self.io.read_json("meta/pending_commit.json")
        except FileNotFoundError:
            return None
        return PendingCommit(
            chapter=int(data.get("chapter", 0) or 0),
            stage=str(data.get("stage", "") or ""),
            summary=str(data.get("summary", "") or ""),
            hook_type=str(data.get("hook_type", "") or ""),
            dominant_strand=str(data.get("dominant_strand", "") or ""),
            result=data.get("result"),
            started_at=str(data.get("started_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
        )

    def clear_pending_commit(self) -> None:
        """清除待完成的提交"""
        self.io.remove_file("meta/pending_commit.json")

    def save_pending_checkpoint(self, pending: PendingRunCheckpoint) -> None:
        """保存待确认的检查点"""
        self.io.write_json("meta/pending_checkpoint.json", asdict(pending))

    def load_pending_checkpoint(self) -> PendingRunCheckpoint | None:
        """加载待确认的检查点"""
        try:
            data = self.io.read_json("meta/pending_checkpoint.json")
        except FileNotFoundError:
            return None
        return PendingRunCheckpoint(
            pause_after_chapter=int(data.get("pause_after_chapter", 0) or 0),
            next_chapter=int(data.get("next_chapter", 0) or 0),
            completed_count=int(data.get("completed_count", 0) or 0),
            status=str(data.get("status", "awaiting_confirmation") or "awaiting_confirmation"),
        )

    def clear_pending_checkpoint(self) -> None:
        """清除待确认的检查点"""
        self.io.remove_file("meta/pending_checkpoint.json")

    def save_last_review(self, review: dict) -> None:
        """保存最后一次评审结果"""
        self.io.write_json("meta/last_review.json", review)

    def load_last_review_signal(self):
        """加载最后一次评审结果"""
        try:
            data = self.io.read_json("meta/last_review.json")
        except FileNotFoundError:
            return None
        issues = [
            ConsistencyIssue(
                type=str(x.get("type", "") or ""),
                severity=str(x.get("severity", "") or ""),
                description=str(x.get("description", "") or ""),
                evidence=str(x.get("evidence", "") or ""),
                suggestion=str(x.get("suggestion", "") or ""),
            )
            for x in (data.get("issues") or [])
        ]
        dimensions = [
            DimensionScore(
                dimension=str(x.get("dimension", "") or ""),
                score=int(x.get("score", 0) or 0),
                verdict=str(x.get("verdict", "") or ""),
                comment=str(x.get("comment", "") or ""),
            )
            for x in (data.get("dimensions") or [])
        ]
        return ReviewEntry(
            chapter=int(data.get("chapter", 0) or 0),
            scope=str(data.get("scope", "") or ""),
            issues=issues,
            dimensions=dimensions,
            contract_status=str(data.get("contract_status", "") or ""),
            contract_misses=[str(x) for x in (data.get("contract_misses") or [])],
            contract_notes=str(data.get("contract_notes", "") or ""),
            verdict=str(data.get("verdict", "") or ""),
            summary=str(data.get("summary", "") or ""),
            affected_chapters=[int(x) for x in (data.get("affected_chapters") or [])],
        )

    def clear_last_review(self) -> None:
        """清除最后一次评审结果"""
        self.io.remove_file("meta/last_review.json")

    def load_and_clear_last_review(self):
        """加载并清除最后一次评审结果（原子操作）"""
        item = self.load_last_review_signal()
        if item is not None:
            self.clear_last_review()
        return item

    def clear_stale_signals(self) -> None:
        """清除所有过期信号"""
        self.clear_last_commit()
        self.clear_last_review()
        self.clear_pending_checkpoint()
