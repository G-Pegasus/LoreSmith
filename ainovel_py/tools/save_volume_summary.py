from __future__ import annotations

from typing import Any

from ainovel_py.domain.checkpoint import volume_scope
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import parse_volume_summary


class SaveVolumeSummaryTool:
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "save_volume_summary"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = parse_volume_summary(args)
        if summary.volume <= 0:
            raise ValueError("volume must be > 0")
        self.store.summaries.save_volume_summary(summary)
        self.store.checkpoints.append(volume_scope(summary.volume), "volume_summary")
        return {"saved": True, "type": "volume_summary", "volume": summary.volume}
