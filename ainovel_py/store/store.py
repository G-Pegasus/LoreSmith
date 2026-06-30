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
    """
    存储管理器
    
    统一管理小说创作过程中的所有数据存储，提供分层的数据访问接口。
    
    包含以下存储模块：
    - progress: 进度存储（当前阶段、章节状态等）
    - run_meta: 运行元数据（风格、提供商、模型等）
    - runtime: 运行时数据（任务队列、会话等）
    - outline: 大纲存储（章节大纲、分层大纲、规划罗盘等）
    - characters: 人物存储（人物定义、快照等）
    - drafts: 草稿存储（章节计划、章节内容等）
    - summaries: 摘要存储（章节摘要、篇章摘要等）
    - world: 世界设定存储（规则、时间线、伏笔、关系等）
    - signals: 信号存储（待提交、待检查点等）
    - checkpoints: 检查点存储（断点续传用）
    """
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
        """获取存储目录路径"""
        return self._dir

    def init(self) -> None:
        """初始化存储目录结构"""
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
