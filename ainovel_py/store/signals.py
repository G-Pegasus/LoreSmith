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
    def __init__(self, io: IO) -> None:
        self.io = io

    def save_last_commit(self, result: dict) -> None:
        self.io.write_json("meta/last_commit.json", result)

    def load_last_commit(self) -> dict | None:
        try:
            return self.io.read_json("meta/last_commit.json")
        except FileNotFoundError:
            return None

    def load_and_clear_last_commit(self) -> dict | None:
        data = self.load_last_commit()
        if data is not None:
            self.clear_last_commit()
        return data

    def clear_last_commit(self) -> None:
        self.io.remove_file("meta/last_commit.json")

    def save_pending_commit(self, pending: PendingCommit) -> None:
        self.io.write_json("meta/pending_commit.json", asdict(pending))

    def load_pending_commit(self) -> PendingCommit | None:
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
        self.io.remove_file("meta/pending_commit.json")

    def save_pending_checkpoint(self, pending: PendingRunCheckpoint) -> None:
        self.io.write_json("meta/pending_checkpoint.json", asdict(pending))

    def load_pending_checkpoint(self) -> PendingRunCheckpoint | None:
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
        self.io.remove_file("meta/pending_checkpoint.json")

    def save_last_review(self, review: dict) -> None:
        self.io.write_json("meta/last_review.json", review)

    def load_last_review_signal(self):
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
        self.io.remove_file("meta/last_review.json")

    def load_and_clear_last_review(self):
        item = self.load_last_review_signal()
        if item is not None:
            self.clear_last_review()
        return item

    def clear_stale_signals(self) -> None:
        self.clear_last_commit()
        self.clear_last_review()
        self.clear_pending_checkpoint()
