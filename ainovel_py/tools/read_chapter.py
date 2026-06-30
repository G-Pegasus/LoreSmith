from __future__ import annotations

from typing import Any

from ainovel_py.store.store import Store


class ReadChapterTool:
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "read_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = int(args.get("chapter", 0) or 0)
        start = int(args.get("from", 0) or 0)
        end = int(args.get("to", 0) or 0)
        source = str(args.get("source", "final") or "final")
        max_runes = int(args.get("max_runes", 2000) or 2000)

        if start > 0 and end > 0:
            chapters = self.store.drafts.load_chapter_range(start, end, max_runes=max_runes)
            return {"chapters": chapters, "from": start, "to": end}

        if chapter <= 0:
            raise ValueError("chapter is required")

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
