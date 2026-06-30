from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from ainovel_py.domain.checkpoint import Checkpoint, Scope
from ainovel_py.store.io import IO


CHECKPOINTS_FILE = "meta/checkpoints.jsonl"


class CheckpointStore:
    def __init__(self, io: IO) -> None:
        self.io = io
        self._next_seq = 0
        self._load_seq()

    def _load_seq(self) -> None:
        all_items = self.all()
        self._next_seq = all_items[-1].seq if all_items else 0

    def append(self, scope: Scope, step: str, artifact: str = "", digest: str = "") -> Checkpoint:
        def op() -> Checkpoint:
            if digest:
                for cp in reversed(self._load_all_unlocked()):
                    if cp.scope.matches(scope) and cp.step == step and cp.digest == digest:
                        return cp
            self._next_seq += 1
            cp = Checkpoint(
                seq=self._next_seq,
                scope=scope,
                step=step,
                artifact=artifact,
                digest=digest,
                occurred_at=datetime.utcnow(),
            )
            payload = asdict(cp)
            payload["occurred_at"] = cp.occurred_at.isoformat()
            payload["scope"] = asdict(cp.scope)
            self.io.append_line(CHECKPOINTS_FILE, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            return cp

        return self.io.with_write_lock(op)

    def latest(self, scope: Scope) -> Checkpoint | None:
        for cp in reversed(self.all()):
            if cp.scope.matches(scope):
                return cp
        return None

    def latest_by_step(self, scope: Scope, step: str) -> Checkpoint | None:
        for cp in reversed(self.all()):
            if cp.scope.matches(scope) and cp.step == step:
                return cp
        return None

    def latest_global(self) -> Checkpoint | None:
        items = self.all()
        return items[-1] if items else None

    def all(self) -> list[Checkpoint]:
        return self._load_all_unlocked()

    def reset(self) -> None:
        self.io.remove_file(CHECKPOINTS_FILE)
        self._next_seq = 0

    def _load_all_unlocked(self) -> list[Checkpoint]:
        try:
            raw = self.io.read_file(CHECKPOINTS_FILE).decode("utf-8")
        except FileNotFoundError:
            return []
        items: list[Checkpoint] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                scope_raw = row.get("scope") or {}
                scope = Scope(
                    kind=str(scope_raw.get("kind", "") or ""),
                    chapter=int(scope_raw.get("chapter", 0) or 0),
                    volume=int(scope_raw.get("volume", 0) or 0),
                    arc=int(scope_raw.get("arc", 0) or 0),
                )
                items.append(
                    Checkpoint(
                        seq=int(row.get("seq", 0) or 0),
                        scope=scope,
                        step=str(row.get("step", "") or ""),
                        artifact=str(row.get("artifact", "") or ""),
                        digest=str(row.get("digest", "") or ""),
                        occurred_at=datetime.fromisoformat(row.get("occurred_at")) if row.get("occurred_at") else datetime.utcnow(),
                    )
                )
            except Exception:
                continue
        return items
