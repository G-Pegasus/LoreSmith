from __future__ import annotations

from dataclasses import asdict

from ainovel_py.domain.runtime import FlowState, Phase, Progress
from ainovel_py.domain.transitions import validate_flow_transition, validate_phase_transition
from ainovel_py.store.io import IO


class ProgressStore:
    def __init__(self, io: IO) -> None:
        self.io = io

    def load(self) -> Progress | None:
        try:
            data = self.io.read_json("meta/progress.json")
        except FileNotFoundError:
            return None
        return _progress_from_dict(data)

    def save(self, progress: Progress) -> None:
        self.io.write_json("meta/progress.json", asdict(progress))

    def init(self, novel_name: str, total_chapters: int) -> None:
        self.save(Progress(novel_name=novel_name, phase=Phase.INIT, total_chapters=total_chapters))

    def update_phase(self, phase: str) -> None:
        def op() -> None:
            p = self.load() or Progress()
            validate_phase_transition(p.phase, phase)
            p.phase = phase
            self.save(p)

        self.io.with_write_lock(op)

    def start_chapter(self, chapter: int) -> None:
        if chapter <= 0:
            raise ValueError("chapter must be > 0")

        def op() -> None:
            p = self.load() or Progress()
            p.phase = Phase.WRITING
            if p.flow not in {FlowState.REWRITING, FlowState.POLISHING}:
                p.flow = FlowState.WRITING
            p.current_chapter = max(p.current_chapter, chapter)
            p.in_progress_chapter = chapter
            p.completed_scenes = []
            self.save(p)

        self.io.with_write_lock(op)

    def set_flow(self, flow: str) -> None:
        def op() -> None:
            p = self.load() or Progress()
            validate_flow_transition(p.flow, flow)
            p.flow = flow
            self.save(p)

        self.io.with_write_lock(op)

    def is_chapter_completed(self, chapter: int) -> bool:
        p = self.load()
        if p is None:
            return False
        return chapter in p.completed_chapters

    def set_total_chapters(self, total: int) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.total_chapters = total
            self.save(p)

        self.io.with_write_lock(op)

    def set_novel_name(self, name: str) -> None:
        name = name.strip()
        if not name:
            return

        def op() -> None:
            p = self.load() or Progress()
            p.novel_name = name
            self.save(p)

        self.io.with_write_lock(op)

    def set_layered(self, layered: bool) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.layered = layered
            self.save(p)

        self.io.with_write_lock(op)

    def update_volume_arc(self, volume: int, arc: int) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.current_volume = volume
            p.current_arc = arc
            self.save(p)

        self.io.with_write_lock(op)

    def set_pending_rewrites(self, chapters: list[int], reason: str) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.pending_rewrites = list(chapters)
            p.rewrite_reason = reason
            self.save(p)

        self.io.with_write_lock(op)

    def complete_rewrite(self, chapter: int) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.pending_rewrites = [x for x in p.pending_rewrites if x != chapter]
            if not p.pending_rewrites:
                validate_flow_transition(p.flow, FlowState.WRITING)
                p.flow = FlowState.WRITING
                p.rewrite_reason = ""
            self.save(p)

        self.io.with_write_lock(op)

    def clear_in_progress(self) -> None:
        def op() -> None:
            p = self.load() or Progress()
            p.in_progress_chapter = 0
            p.completed_scenes = []
            self.save(p)

        self.io.with_write_lock(op)

    def mark_chapter_complete(self, chapter: int, word_count: int, hook_type: str = "", dominant_strand: str = "") -> None:
        def op() -> None:
            p = self.load() or Progress()
            old_wc = p.chapter_word_counts.get(chapter, 0)
            p.total_word_count -= old_wc
            p.chapter_word_counts[chapter] = word_count
            p.total_word_count += word_count
            if chapter not in p.completed_chapters:
                p.completed_chapters.append(chapter)
            p.current_chapter = max(p.current_chapter, chapter + 1)
            p.in_progress_chapter = 0
            p.completed_scenes = []
            validate_phase_transition(p.phase, Phase.WRITING)
            p.phase = Phase.WRITING

            if dominant_strand:
                while len(p.strand_history) < chapter - 1:
                    p.strand_history.append("")
                if len(p.strand_history) < chapter:
                    p.strand_history.append(dominant_strand)
                else:
                    p.strand_history[chapter - 1] = dominant_strand

            if hook_type:
                while len(p.hook_history) < chapter - 1:
                    p.hook_history.append("")
                if len(p.hook_history) < chapter:
                    p.hook_history.append(hook_type)
                else:
                    p.hook_history[chapter - 1] = hook_type

            self.save(p)

        self.io.with_write_lock(op)


def _progress_from_dict(data: dict) -> Progress:
    chapter_word_counts = {
        int(k): int(v) for k, v in (data.get("chapter_word_counts") or {}).items()
    }
    return Progress(
        novel_name=str(data.get("novel_name", "") or ""),
        phase=str(data.get("phase", Phase.INIT) or Phase.INIT),
        current_chapter=int(data.get("current_chapter", 0) or 0),
        total_chapters=int(data.get("total_chapters", 0) or 0),
        completed_chapters=[int(x) for x in (data.get("completed_chapters") or [])],
        total_word_count=int(data.get("total_word_count", 0) or 0),
        chapter_word_counts=chapter_word_counts,
        in_progress_chapter=int(data.get("in_progress_chapter", 0) or 0),
        completed_scenes=[int(x) for x in (data.get("completed_scenes") or [])],
        flow=str(data.get("flow", "") or ""),
        pending_rewrites=[int(x) for x in (data.get("pending_rewrites") or [])],
        rewrite_reason=str(data.get("rewrite_reason", "") or ""),
        strand_history=[str(x) for x in (data.get("strand_history") or [])],
        hook_history=[str(x) for x in (data.get("hook_history") or [])],
        current_volume=int(data.get("current_volume", 0) or 0),
        current_arc=int(data.get("current_arc", 0) or 0),
        layered=bool(data.get("layered", False)),
    )
