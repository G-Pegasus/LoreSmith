from __future__ import annotations

from typing import Any

from ainovel_py.store.store import Store


class ReadChapterTool:
    """
    章节读取工具
    
    负责读取章节内容，支持从草稿或最终版本读取，
    也支持读取连续的章节范围。
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "read_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行章节读取
        
        Args:
            args: 参数字典，包含：
                - chapter: 章节号（单个章节读取）
                - from/to: 章节范围（批量读取）
                - source: 来源（draft/final）
                - max_runes: 最大字符数限制
        
        Returns:
            包含章节内容的字典
        """
        chapter = int(args.get("chapter", 0) or 0)
        start = int(args.get("from", 0) or 0)
        end = int(args.get("to", 0) or 0)
        source = str(args.get("source", "final") or "final")
        max_runes = int(args.get("max_runes", 2000) or 2000)

        # 批量读取模式
        if start > 0 and end > 0:
            chapters = self.store.drafts.load_chapter_range(start, end, max_runes=max_runes)
            return {"chapters": chapters, "from": start, "to": end}

        # 单章节读取模式
        if chapter <= 0:
            raise ValueError("chapter is required")

        # 根据来源读取内容
        if source == "draft":
            content = self.store.drafts.load_draft(chapter)
        else:
            content = self.store.drafts.load_chapter_text(chapter)
            if not content:
                content = self.store.drafts.load_draft(chapter)

        if not content:
            return {
                "chapter": chapter,
                "exists": False,
                "hint": "该章节尚未写入，如需写作请先调用 draft_chapter",
            }

        return {"chapter": chapter, "content": content, "word_count": len(content)}
