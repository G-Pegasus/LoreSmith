from __future__ import annotations

from dataclasses import asdict

from ainovel_py.domain.runtime import FlowState, Phase, Progress
from ainovel_py.domain.transitions import validate_flow_transition, validate_phase_transition
from ainovel_py.store.io import IO


class ProgressStore:
    """
    进度存储管理器
    
    负责持久化和管理小说创作进度信息，包括：
    - 当前阶段（INIT/PREMISE/OUTLINE/WRITING/COMPLETE）
    - 当前流程状态（WRITING/REWRITING/POLISHING）
    - 章节完成情况
    - 字数统计
    - 重写队列
    
    所有写操作都通过写锁保护，确保线程安全。
    """
    def __init__(self, io: IO) -> None:
        self.io = io

    def load(self) -> Progress | None:
        """加载进度信息"""
        try:
            data = self.io.read_json("meta/progress.json")
        except FileNotFoundError:
            return None
        return _progress_from_dict(data)

    def save(self, progress: Progress) -> None:
        """保存进度信息"""
        self.io.write_json("meta/progress.json", asdict(progress))

    def init(self, novel_name: str, total_chapters: int) -> None:
        """初始化进度信息"""
        self.save(Progress(novel_name=novel_name, phase=Phase.INIT, total_chapters=total_chapters))

    def update_phase(self, phase: str) -> None:
        """更新创作阶段（带状态转换验证）"""
        def op() -> None:
            p = self.load() or Progress()
            validate_phase_transition(p.phase, phase)
            p.phase = phase
            self.save(p)

        self.io.with_write_lock(op)

    def start_chapter(self, chapter: int) -> None:
        """开始写作指定章节"""
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
        """设置当前流程状态（带状态转换验证）"""
        def op() -> None:
            p = self.load() or Progress()
            validate_flow_transition(p.flow, flow)
            p.flow = flow
            self.save(p)

        self.io.with_write_lock(op)

    def is_chapter_completed(self, chapter: int) -> bool:
        """检查章节是否已完成"""
        p = self.load()
        if p is None:
            return False
        return chapter in p.completed_chapters

    def set_total_chapters(self, total: int) -> None:
        """设置总章节数"""
        def op() -> None:
            p = self.load() or Progress()
            p.total_chapters = total
            self.save(p)

        self.io.with_write_lock(op)

    def set_novel_name(self, name: str) -> None:
        """设置小说名称"""
        name = name.strip()
        if not name:
            return

        def op() -> None:
            p = self.load() or Progress()
            p.novel_name = name
            self.save(p)

        self.io.with_write_lock(op)

    def set_layered(self, layered: bool) -> None:
        """设置是否使用分层大纲"""
        def op() -> None:
            p = self.load() or Progress()
            p.layered = layered
            self.save(p)

        self.io.with_write_lock(op)

    def update_volume_arc(self, volume: int, arc: int) -> None:
        """更新当前卷和篇章"""
        def op() -> None:
            p = self.load() or Progress()
            p.current_volume = volume
            p.current_arc = arc
            self.save(p)

        self.io.with_write_lock(op)

    def set_pending_rewrites(self, chapters: list[int], reason: str) -> None:
        """设置待重写章节列表"""
        def op() -> None:
            p = self.load() or Progress()
            p.pending_rewrites = list(chapters)
            p.rewrite_reason = reason
            self.save(p)

        self.io.with_write_lock(op)

    def complete_rewrite(self, chapter: int) -> None:
        """标记章节重写完成"""
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
        """清除进行中的章节状态"""
        def op() -> None:
            p = self.load() or Progress()
            p.in_progress_chapter = 0
            p.completed_scenes = []
            self.save(p)

        self.io.with_write_lock(op)

    def mark_chapter_complete(self, chapter: int, word_count: int, hook_type: str = "", dominant_strand: str = "") -> None:
        """
        标记章节完成
        
        Args:
            chapter: 章节号
            word_count: 章节字数
            hook_type: 钩子类型（可选）
            dominant_strand: 主线类型（可选）
        """
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
