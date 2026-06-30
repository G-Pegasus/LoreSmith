from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable


class IO:
    def __init__(self, directory: str) -> None:
        self.dir = Path(directory)
        self._mu = threading.RLock()

    def path(self, rel: str) -> Path:
        return self.dir / rel

    def read_file(self, rel: str) -> bytes:
        with self._mu:
            return self.read_file_unlocked(rel)

    def read_file_unlocked(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()

    def write_file_unlocked(self, rel: str, data: bytes) -> None:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.parent / f"{p.name}.tmp-{os.getpid()}"
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def read_json(self, rel: str) -> Any:
        with self._mu:
            return self.read_json_unlocked(rel)

    def read_json_unlocked(self, rel: str) -> Any:
        return json.loads(self.read_file_unlocked(rel).decode("utf-8"))

    def write_json(self, rel: str, value: Any) -> None:
        with self._mu:
            self.write_json_unlocked(rel, value)

    def write_json_unlocked(self, rel: str, value: Any) -> None:
        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_file_unlocked(rel, data)

    def write_markdown(self, rel: str, content: str) -> None:
        with self._mu:
            self.write_file_unlocked(rel, content.encode("utf-8"))

    def append_line(self, rel: str, data: bytes) -> None:
        with self._mu:
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

    def remove_file(self, rel: str) -> None:
        with self._mu:
            p = self.path(rel)
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def with_write_lock(self, fn: Callable[[], Any]) -> Any:
        with self._mu:
            return fn()

    def ensure_dirs(self, dirs: list[str]) -> None:
        for d in dirs:
            (self.dir / d).mkdir(parents=True, exist_ok=True)
