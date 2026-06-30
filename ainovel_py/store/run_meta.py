from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from ainovel_py.domain.runtime import RunMeta, SteerEntry, normalize_planning_tier
from ainovel_py.store.io import IO


class RunMetaStore:
    """
    运行元数据存储管理器
    
    负责持久化和管理小说创作的运行时元数据，包括：
    - 启动时间
    - 服务提供商和模型配置
    - 写作风格
    - 故事标题和类型
    - 字数限制（最小/目标/最大）
    - 规划层级
    - 用户干预历史和待处理干预
    
    所有写操作都通过写锁保护，确保线程安全。
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def load(self) -> RunMeta | None:
        """加载运行元数据"""
        try:
            data = self.io.read_json("meta/run.json")
        except FileNotFoundError:
            return None
        history = [
            SteerEntry(input=str(x.get("input", "") or ""), timestamp=str(x.get("timestamp", "") or ""))
            for x in (data.get("steer_history") or [])
            if isinstance(x, dict)
        ]
        return RunMeta(
            started_at=str(data.get("started_at", "") or ""),
            provider=str(data.get("provider", "") or ""),
            style=str(data.get("style", "") or ""),
            model=str(data.get("model", "") or ""),
            story_title=str(data.get("story_title", "") or ""),
            genre=str(data.get("genre", "") or ""),
            min_words=int(data.get("min_words", 1200) or 1200),
            target_words=int(data.get("target_words", 1800) or 1800),
            max_words=int(data.get("max_words", 2600) or 2600),
            planning_tier=str(data.get("planning_tier", "") or ""),
            steer_history=history,
            pending_steer=str(data.get("pending_steer", "") or ""),
        )

    def save(self, meta: RunMeta) -> None:
        """保存运行元数据"""
        self.io.write_json("meta/run.json", asdict(meta))

    def init(self, style: str, provider: str, model: str) -> None:
        """
        初始化运行元数据
        
        保留已有的故事相关配置（标题、类型、字数限制等），仅更新启动时间、提供商和模型。
        """
        existing = self.load()
        meta = RunMeta(
            started_at=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            style=style,
            model=model,
        )
        if existing:
            meta.story_title = existing.story_title
            meta.genre = existing.genre
            meta.min_words = existing.min_words
            meta.target_words = existing.target_words
            meta.max_words = existing.max_words
            meta.steer_history = existing.steer_history
            meta.pending_steer = existing.pending_steer
            meta.planning_tier = existing.planning_tier
        self.save(meta)

    def set_pending_steer(self, text: str) -> None:
        """设置待处理的用户干预指令"""
        meta = self.load() or RunMeta()
        meta.pending_steer = text
        self.save(meta)

    def set_planning_tier(self, tier: str) -> None:
        """设置规划层级（带验证）"""
        normalized = normalize_planning_tier(tier)
        if str(tier or "").strip() and not normalized:
            raise ValueError(f"invalid planning_tier: {tier}")

        def _write() -> None:
            meta = self.load() or RunMeta()
            meta.planning_tier = normalized
            self.save(meta)

        self.io.with_write_lock(_write)

    def set_story_defaults(self, title: str, genre: str, min_words: int, target_words: int, max_words: int) -> None:
        """设置故事默认配置（字数限制带约束校验）"""
        def _write() -> None:
            meta = self.load() or RunMeta()
            meta.story_title = title
            meta.genre = genre
            meta.min_words = max(200, min_words)
            meta.target_words = max(meta.min_words, target_words)
            meta.max_words = max(meta.target_words, max_words)
            self.save(meta)

        self.io.with_write_lock(_write)
