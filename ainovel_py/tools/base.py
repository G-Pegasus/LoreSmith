from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class Tool(Protocol):
    def name(self) -> str: ...
    def execute(self, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class ToolError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message
