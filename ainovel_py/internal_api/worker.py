from __future__ import annotations

import threading
import time
from datetime import datetime

from ainovel_py.internal_api.registry import RunRegistry
from ainovel_py.internal_api.tasks import RunTask, utcnow


class WorkerManager:
    def __init__(self, registry: RunRegistry) -> None:
        self.registry = registry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="internal-api-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            task = self.registry.claim_next_task()
            if task is None:
                time.sleep(0.1)
                continue
            self._execute(task)

    def _execute(self, task: RunTask) -> None:
        session = self.registry.get(task.run_id)
        if session is None:
            task.status = "failed"
            task.error = f"run not found: {task.run_id}"
            task.finished_at = utcnow()
            self.registry.persist_task(task)
            return

        task.status = "running"
        task.started_at = utcnow()
        self.registry.persist_task(task)
        session.last_operation = task.op
        self.registry.persist(session)

        try:
            if task.op == "start":
                prompt = str(task.payload.get("prompt", "") or "")
                session.host.start_prepared(prompt)
            elif task.op == "resume":
                prompt = str(task.payload.get("prompt", "") or "")
                if prompt:
                    session.host.continue_run(prompt)
                else:
                    session.host.resume()
            elif task.op == "continue":
                text = str(task.payload.get("text", "") or "")
                session.host.continue_run(text)
            else:
                raise ValueError(f"unknown task op: {task.op}")
            if session.state_override != "canceled":
                session.last_error_code = ""
                session.last_error_message = ""
                session.state_override = ""
            task.status = "completed"
        except Exception as exc:
            if session.state_override != "canceled":
                session.last_error_code = "INTERNAL_ERROR"
                session.last_error_message = str(exc)
                session.state_override = "failed"
            task.status = "failed"
            task.error = str(exc)
        finally:
            task.finished_at = utcnow()
            if session.host.lifecycle == "completed":
                session.finished_at = utcnow()
            self.registry.persist(session)
            self.registry.persist_task(task)
