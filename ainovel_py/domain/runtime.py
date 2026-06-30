from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Phase:
    """创作阶段枚举"""
    INIT = "init"          # 初始化阶段
    PREMISE = "premise"    # 前提设定阶段
    OUTLINE = "outline"    # 大纲制定阶段
    WRITING = "writing"    # 写作阶段
    COMPLETE = "complete"  # 完成阶段


class FlowState:
    """写作流程状态枚举"""
    WRITING = "writing"     # 正常写作
    REVIEWING = "reviewing" # 评审中
    REWRITING = "rewriting" # 重写中
    POLISHING = "polishing" # 打磨中
    STEERING = "steering"   # 干预调整中


@dataclass
class Progress:
    """
    创作进度状态
    
    跟踪小说创作的整体进度，包括当前章节、已完成章节、字数统计等信息。
    支持断点续传判断和下一章节计算。
    """
    novel_name: str = ""                   # 小说名称
    phase: str = Phase.INIT                # 当前阶段
    current_chapter: int = 0               # 当前正在处理的章节
    total_chapters: int = 0                # 总章节数
    completed_chapters: list[int] = field(default_factory=list)  # 已完成章节列表
    total_word_count: int = 0              # 总字数
    chapter_word_counts: dict[int, int] = field(default_factory=dict)  # 各章节字数统计
    in_progress_chapter: int = 0           # 进行中的章节
    completed_scenes: list[int] = field(default_factory=list)  # 已完成场景列表
    flow: str = ""                         # 当前流程状态
    pending_rewrites: list[int] = field(default_factory=list)  # 待重写章节列表
    rewrite_reason: str = ""               # 重写原因
    strand_history: list[str] = field(default_factory=list)    # 主线历史记录
    hook_history: list[str] = field(default_factory=list)      # 钩子历史记录
    current_volume: int = 0                # 当前卷
    current_arc: int = 0                   # 当前篇章
    layered: bool = False                  # 是否为分层大纲模式

    def is_resumable(self) -> bool:
        """判断是否可以从断点恢复"""
        return self.phase == Phase.WRITING and self.current_chapter > 0

    def next_chapter(self) -> int:
        """计算下一个要写作的章节号"""
        if not self.completed_chapters:
            return 1
        return max(self.completed_chapters) + 1


@dataclass
class SteerEntry:
    """
    干预记录条目
    
    记录用户对创作过程的干预指令和时间戳。
    """
    input: str       # 干预内容
    timestamp: str   # 时间戳


@dataclass
class RunMeta:
    """
    运行元数据
    
    记录当前创作会话的配置信息，包括模型选择、风格、字数目标等。
    """
    started_at: str = ""                    # 开始时间
    provider: str = ""                      # 服务提供商
    style: str = ""                         # 写作风格
    model: str = ""                         # 模型名称
    story_title: str = ""                   # 故事标题
    genre: str = ""                         # 体裁
    min_words: int = 1200                   # 单章节最小字数
    target_words: int = 1800                # 单章节目标字数
    max_words: int = 2600                   # 单章节最大字数
    planning_tier: str = ""                 # 规划层级（short/mid/long）
    steer_history: list[SteerEntry] = field(default_factory=list)  # 干预历史
    pending_steer: str = ""                 # 待处理的干预指令


def extract_novel_name_from_premise(premise: str) -> str:
    """从前提文本中提取小说名称（寻找以 '# ' 开头的行）"""
    for raw in premise.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("# "):
            return ""
        return line[2:].strip()
    return ""


def normalize_planning_tier(value: Any) -> str:
    """规范化规划层级值"""
    tier = str(value or "").strip().lower()
    return tier if tier in {"short", "mid", "long"} else ""


def infer_planning_tier(progress: Progress | None, has_layered_outline: bool, has_compass: bool) -> str:
    """根据进度和配置推断规划层级"""
    if progress and progress.layered:
        return "long"
    if has_layered_outline or has_compass:
        return "long"
    total = progress.total_chapters if progress else 0
    if 1 <= total <= 25:
        return "short"
    if total >= 80:
        return "long"
    return "mid"
