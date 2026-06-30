from __future__ import annotations

import re
from typing import Any

from ainovel_py.domain.checkpoint import chapter_scope
from ainovel_py.store.store import Store


class DraftChapterTool:
    _CHAPTER_HEADING_PATTERN = re.compile(r"^第\s*\d+\s*章(?:[:：\-—\s].*)?$")

    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        return "draft_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = int(args.get("chapter", 0) or 0)
        content = str(args.get("content", "") or "")
        mode = str(args.get("mode", "write") or "write")

        if chapter <= 0:
            raise ValueError("chapter must be > 0")
        if not content:
            raise ValueError("content must not be empty")
        content = self._sanitize_content(chapter, content)
        progress = self.store.progress.load()
        allow_rewrite = bool(
            progress
            and progress.flow in {"rewriting", "polishing"}
            and chapter in progress.pending_rewrites
        )
        if self.store.progress.is_chapter_completed(chapter) and not allow_rewrite:
            return {
                "chapter": chapter,
                "skipped": True,
                "reason": f"第 {chapter} 章已提交完成，不能覆盖",
                "next_step": "该章节已完成，请继续写下一章",
            }

        self.store.progress.start_chapter(chapter)
        if mode == "append":
            self.store.drafts.append_draft(chapter, content)
            full = self.store.drafts.load_draft(chapter)
            wc = len(full)
        else:
            self.store.drafts.save_draft(chapter, content)
            wc = len(content)

        self.store.checkpoints.append(
            chapter_scope(chapter),
            "draft",
            artifact=f"drafts/ch{chapter:02d}.draft.md",
        )

        return {
            "written": True,
            "chapter": chapter,
            "mode": mode,
            "word_count": wc,
            "next_step": "先 read_chapter(source=draft) 回读草稿，再调用 check_consistency，最后 commit_chapter",
        }

    def _sanitize_content(self, chapter: int, content: str) -> str:
        text = content.lstrip("\ufeff").strip()
        if not text:
            return ""
        lines = text.splitlines()
        if not lines:
            return text
        first = lines[0].strip().strip("#＊* ")
        plan = self.store.drafts.load_chapter_plan(chapter)
        expected_titles = {f"第 {chapter} 章", f"第{chapter}章"}
        detected_title = ""
        if plan and plan.title:
            detected_title = plan.title.strip()
            expected_titles.add(detected_title)
            expected_titles.add(f"第{chapter}章 {detected_title}")
            expected_titles.add(f"第 {chapter} 章 {detected_title}")
        if first in expected_titles or self._CHAPTER_HEADING_PATTERN.match(first):
            if not detected_title:
                heading = re.sub(r"^第\s*\d+\s*章[:：\-—\s]*", "", first).strip()
                detected_title = heading or first
            if plan and detected_title and plan.title != detected_title:
                plan.title = detected_title
                self.store.drafts.save_chapter_plan(plan)
            stripped = "\n".join(lines[1:]).lstrip()
            return stripped or text
        return text
