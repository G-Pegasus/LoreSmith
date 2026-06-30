from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from ainovel_py.internal_api.tasks import RunTask
from ainovel_py.store.io import IO


def _iso_or_empty(value: Optional[datetime]) -> str:
    return value.isoformat() if value is not None else ""


class RunRegistryStore:
    def __init__(self, path: str) -> None:
        self.io = IO(".")
        self.path = path

    def load(self) -> List[Dict[str, Any]]:
        try:
            data = self.io.read_json(self.path)
        except FileNotFoundError:
            return []
        return data if isinstance(data, list) else []

    def save(self, rows: List[Dict[str, Any]]) -> None:
        self.io.write_json(self.path, rows)

    def upsert(self, row: Dict[str, Any]) -> None:
        rows = self.load()
        replaced = False
        for idx, existing in enumerate(rows):
            if str(existing.get("run_id", "")) == str(row.get("run_id", "")):
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        self.save(rows)

    @staticmethod
    def build_row(session) -> Dict[str, Any]:
        return {
            "run_id": session.run_id,
            "story_id": session.story_id,
            "output_dir": session.output_dir,
            "created_at": _iso_or_empty(session.created_at),
            "started_at": _iso_or_empty(session.started_at),
            "finished_at": _iso_or_empty(session.finished_at),
            "last_error_code": session.last_error_code,
            "last_error_message": session.last_error_message,
            "state_override": session.state_override,
            "last_operation": session.last_operation,
            "cfg": {
                "output_dir": session.cfg.output_dir,
                "provider": session.cfg.provider,
                "model": session.cfg.model,
                "providers": {
                    name: asdict(pc) for name, pc in session.cfg.providers.items()
                },
                "roles": {
                    name: asdict(rc) for name, rc in session.cfg.roles.items()
                },
                "style": session.cfg.style,
                "context_window": session.cfg.context_window,
            },
        }


class RunTaskStore:
    def __init__(self, path: str) -> None:
        self.io = IO(".")
        self.path = path

    def load(self) -> List[Dict[str, Any]]:
        try:
            data = self.io.read_json(self.path)
        except FileNotFoundError:
            return []
        return data if isinstance(data, list) else []

    def save(self, rows: List[Dict[str, Any]]) -> None:
        self.io.write_json(self.path, rows)

    def upsert(self, row: Dict[str, Any]) -> None:
        rows = self.load()
        replaced = False
        for idx, existing in enumerate(rows):
            if str(existing.get("task_id", "")) == str(row.get("task_id", "")):
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        self.save(rows)

    @staticmethod
    def build_row(task: RunTask) -> Dict[str, Any]:
        return {
            "task_id": task.task_id,
            "run_id": task.run_id,
            "op": task.op,
            "payload": task.payload,
            "status": task.status,
            "created_at": _iso_or_empty(task.created_at),
            "started_at": _iso_or_empty(task.started_at),
            "finished_at": _iso_or_empty(task.finished_at),
            "error": task.error,
        }
