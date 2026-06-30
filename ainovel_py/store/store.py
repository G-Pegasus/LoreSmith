from __future__ import annotations

from ainovel_py.store.io import IO
from ainovel_py.store.progress import ProgressStore
from ainovel_py.store.run_meta import RunMetaStore
from ainovel_py.store.runtime import RuntimeStore
from ainovel_py.store.checkpoints import CheckpointStore
from ainovel_py.store.signals import SignalStore
from ainovel_py.store.story_data import (
    CharacterStore,
    DraftStore,
    OutlineStore,
    SummaryStore,
    WorldStore,
)


class Store:
    def __init__(self, directory: str) -> None:
        self._dir = directory
        self.progress = ProgressStore(IO(directory))
        self.run_meta = RunMetaStore(IO(directory))
        self.runtime = RuntimeStore(IO(directory))
        self.outline = OutlineStore(IO(directory))
        self.characters = CharacterStore(IO(directory))
        self.drafts = DraftStore(IO(directory))
        self.summaries = SummaryStore(IO(directory))
        self.world = WorldStore(IO(directory))
        self.signals = SignalStore(IO(directory))
        self.checkpoints = CheckpointStore(IO(directory))

    def dir(self) -> str:
        return self._dir

    def init(self) -> None:
        self.progress.io.ensure_dirs(
            [
                "chapters",
                "summaries",
                "drafts",
                "reviews",
                "meta",
                "meta/runtime",
                "meta/runtime/tasks",
                "meta/sessions",
                "meta/sessions/agents",
            ]
        )
