from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock, Thread
from typing import Dict, Optional

from ainovel_py.bootstrap.config import Config, provider_config_from_dict, role_config_from_dict
from ainovel_py.host.host import Host
from ainovel_py.internal_api.persistence import RunRegistryStore, RunTaskStore
from ainovel_py.internal_api.tasks import RunTask


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunSession:
    run_id: str
    story_id: str
    output_dir: str
    cfg: Config
    host: Host
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    last_error_code: str = ""
    last_error_message: str = ""
    state_override: str = ""
    last_operation: str = ""
    worker: Optional[Thread] = None
    lock: RLock = field(default_factory=RLock)
    has_queued_task: bool = False
    has_running_task: bool = False

    def is_busy(self) -> bool:
        return self.has_queued_task or self.has_running_task


class RunRegistry:
    def __init__(self, store: RunRegistryStore | None = None, task_store: RunTaskStore | None = None) -> None:
        self._lock = RLock()
        self._items: Dict[str, RunSession] = {}
        self._tasks: Dict[str, RunTask] = {}
        self._store = store
        self._task_store = task_store

    def get(self, run_id: str) -> Optional[RunSession]:
        with self._lock:
            return self._items.get(run_id)

    def put(self, session: RunSession) -> RunSession:
        with self._lock:
            self._items[session.run_id] = session
            self._sync_session_flags_locked(session.run_id)
            self._persist_locked(session)
            return session

    def require(self, run_id: str) -> RunSession:
        with self._lock:
            session = self._items.get(run_id)
            if session is None:
                raise KeyError(run_id)
            return session

    def persist(self, session: RunSession) -> None:
        with self._lock:
            self._sync_session_flags_locked(session.run_id)
            self._persist_locked(session)

    def list(self) -> list[RunSession]:
        with self._lock:
            for run_id in self._items:
                self._sync_session_flags_locked(run_id)
            return list(self._items.values())

    def list_tasks(self, run_id: str = "") -> list[RunTask]:
        with self._lock:
            items = list(self._tasks.values())
            if run_id:
                return [task for task in items if task.run_id == run_id]
            return items

    def put_task(self, task: RunTask) -> RunTask:
        with self._lock:
            self._tasks[task.task_id] = task
            self._sync_session_flags_locked(task.run_id)
            self._persist_task_locked(task)
            return task

    def persist_task(self, task: RunTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            self._sync_session_flags_locked(task.run_id)
            self._persist_task_locked(task)

    def claim_next_task(self) -> Optional[RunTask]:
        with self._lock:
            for task in sorted(self._tasks.values(), key=lambda item: item.created_at):
                if task.status == "queued":
                    session = self._items.get(task.run_id)
                    if session is None:
                        continue
                    task.status = "running"
                    task.started_at = utcnow()
                    self._sync_session_flags_locked(task.run_id)
                    self._persist_task_locked(task)
                    return task
            return None

    def restore(self) -> None:
        if self._store is not None:
            rows = self._store.load()
            for row in rows:
                cfg_raw = row.get("cfg") or {}
                providers_raw = cfg_raw.get("providers") or {}
                roles_raw = cfg_raw.get("roles") or {}
                cfg = Config(
                    output_dir=str(cfg_raw.get("output_dir", row.get("output_dir", "")) or row.get("output_dir", "")),
                    provider=str(cfg_raw.get("provider", "") or ""),
                    model=str(cfg_raw.get("model", "") or ""),
                    providers={name: provider_config_from_dict(data) for name, data in providers_raw.items()},
                    roles={name: role_config_from_dict(data) for name, data in roles_raw.items()},
                    style=str(cfg_raw.get("style", "default") or "default"),
                    context_window=int(cfg_raw.get("context_window", 128000) or 128000),
                )
                cfg.fill_defaults()
                if cfg.provider and cfg.provider not in cfg.providers:
                    from ainovel_py.bootstrap.config import ProviderConfig

                    cfg.providers[cfg.provider] = ProviderConfig(api_key="dummy-key")
                host = Host(cfg)
                session = RunSession(
                    run_id=str(row.get("run_id", "") or ""),
                    story_id=str(row.get("story_id", "") or ""),
                    output_dir=str(row.get("output_dir", cfg.output_dir) or cfg.output_dir),
                    cfg=cfg,
                    host=host,
                    last_error_code=str(row.get("last_error_code", "") or ""),
                    last_error_message=str(row.get("last_error_message", "") or ""),
                    state_override=str(row.get("state_override", "") or ""),
                    last_operation=str(row.get("last_operation", "") or ""),
                )
                self._items[session.run_id] = session
        if self._task_store is not None:
            for row in self._task_store.load():
                task = RunTask(
                    task_id=str(row.get("task_id", "") or ""),
                    run_id=str(row.get("run_id", "") or ""),
                    op=str(row.get("op", "") or ""),
                    payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
                    status=str(row.get("status", "queued") or "queued"),
                    error=str(row.get("error", "") or ""),
                )
                if task.status == "running":
                    task.status = "queued"
                self._tasks[task.task_id] = task
        for run_id in self._items:
            self._sync_session_flags_locked(run_id)

    def _persist_locked(self, session: RunSession) -> None:
        if self._store is None:
            return
        self._store.upsert(self._store.build_row(session))

    def _persist_task_locked(self, task: RunTask) -> None:
        if self._task_store is None:
            return
        self._task_store.upsert(self._task_store.build_row(task))

    def _sync_session_flags_locked(self, run_id: str) -> None:
        session = self._items.get(run_id)
        if session is None:
            return
        session.has_queued_task = any(task.run_id == run_id and task.status == "queued" for task in self._tasks.values())
        session.has_running_task = any(task.run_id == run_id and task.status == "running" for task in self._tasks.values())
