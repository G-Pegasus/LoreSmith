from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ainovel_py.domain.runtime_events import RuntimeQueueItem
from ainovel_py.store.io import IO


RUNTIME_QUEUE_PATH = "meta/runtime/queue.jsonl"
RUNTIME_CONTROL_PATH = "meta/runtime/control.json"


class RuntimeStore:
    def __init__(self, io: IO) -> None:
        self.io = io
        self._seq_loaded = False
        self._next_seq = 0

    def append_queue(self, item: RuntimeQueueItem) -> RuntimeQueueItem:
        def op() -> RuntimeQueueItem:
            self._ensure_seq_loaded_locked()
            self._next_seq += 1
            item.seq = self._next_seq
            if not item.time:
                item.time = datetime.utcnow()
            payload = asdict(item)
            payload["time"] = item.time.isoformat()
            self.io.append_line(RUNTIME_QUEUE_PATH, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            return item

        return self.io.with_write_lock(op)

    def load_queue(self) -> list[RuntimeQueueItem]:
        try:
            data = self.io.read_file(RUNTIME_QUEUE_PATH).decode("utf-8")
        except FileNotFoundError:
            return []
        out: list[RuntimeQueueItem] = []
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append(
                RuntimeQueueItem(
                    seq=int(row.get("seq", 0) or 0),
                    time=datetime.fromisoformat(row.get("time")) if row.get("time") else datetime.utcnow(),
                    kind=str(row.get("kind", "") or ""),
                    priority=str(row.get("priority", "") or ""),
                    task_id=str(row.get("task_id", "") or ""),
                    agent=str(row.get("agent", "") or ""),
                    category=str(row.get("category", "") or ""),
                    summary=str(row.get("summary", "") or ""),
                    payload=row.get("payload"),
                )
            )
        return out

    def load_queue_after(self, after_seq: int) -> list[RuntimeQueueItem]:
        items = self.load_queue()
        if after_seq <= 0:
            return items
        return [x for x in items if x.seq > after_seq]

    def reset(self) -> None:
        queue_file = self.io.path(RUNTIME_QUEUE_PATH)
        control_file = self.io.path(RUNTIME_CONTROL_PATH)
        tasks_dir = self.io.path("meta/runtime/tasks")
        if queue_file.exists():
            queue_file.unlink()
        if control_file.exists():
            control_file.unlink()
        if tasks_dir.exists():
            for p in tasks_dir.glob("**/*"):
                if p.is_file():
                    p.unlink()
        tasks_dir.mkdir(parents=True, exist_ok=True)
        self._seq_loaded = False
        self._next_seq = 0

    def _ensure_seq_loaded_locked(self) -> None:
        if self._seq_loaded:
            return
        items = self.load_queue()
        self._next_seq = items[-1].seq if items else 0
        self._seq_loaded = True
