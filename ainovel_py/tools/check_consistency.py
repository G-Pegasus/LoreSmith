from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.store.store import Store


class CheckConsistencyTool:
    """
    一致性检查工具
    
    用于检查章节内容与世界设定、人物关系、伏笔等的一致性。
    加载相关上下文信息供后续处理使用。
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "check_consistency"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行一致性检查
        
        Args:
            args: 参数字典，包含 chapter 字段
        
        Returns:
            包含章节内容和相关上下文的字典
        """
        chapter = int(args.get("chapter", 0) or 0)
        if chapter <= 0:
            raise ValueError("chapter must be > 0")

        content, word_count = self.store.drafts.load_chapter_content(chapter)
        if not content:
            raise ValueError(f"no content found for chapter {chapter}")

        result: dict[str, Any] = {
            "chapter": chapter,
            "content": content,
            "word_count": word_count,
        }

        rules = self.store.world.load_world_rules()
        if rules:
            result["world_rules"] = [asdict(x) for x in rules]
        foreshadow = self.store.world.load_active_foreshadow()
        if foreshadow:
            result["foreshadow_ledger"] = [asdict(x) for x in foreshadow]
        relationships = self.store.world.load_relationships()
        if relationships:
            result["relationships"] = [asdict(x) for x in relationships]
        chars = self.store.characters.load()
        if chars:
            alias_map: dict[str, str] = {}
            for c in chars:
                for alias in c.aliases:
                    alias_map[alias] = c.name
            if alias_map:
                result["alias_map"] = alias_map
        summaries = self.store.summaries.load_recent_summaries(chapter, 2)
        if summaries:
            result["recent_summaries"] = [asdict(x) for x in summaries]

        self.store.checkpoints.append(chapter_scope(chapter), "consistency_check")
        return result
