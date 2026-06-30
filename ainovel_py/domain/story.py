from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OutlineEntry:
    """
    章节大纲条目
    
    表示小说大纲中的一个章节定义，包含章节号、标题、核心事件、钩子和场景列表。
    """
    chapter: int           # 章节编号
    title: str             # 章节标题
    core_event: str        # 核心事件描述
    hook: str = ""         # 章末钩子（悬念设置）
    scenes: list[str] = field(default_factory=list)  # 场景列表


@dataclass
class Character:
    """
    人物角色定义
    
    包含人物的基本信息，如姓名、别名、角色定位、描述、人物弧光和性格特征。
    """
    name: str              # 人物姓名
    aliases: list[str] = field(default_factory=list)  # 别名列表
    role: str = ""         # 角色定位（主角/配角/反派等）
    description: str = ""  # 人物描述
    arc: str = ""          # 人物弧光（成长轨迹）
    traits: list[str] = field(default_factory=list)  # 性格特征列表
    tier: str = "important"  # 重要性层级（important/minor/background）


@dataclass
class ArcOutline:
    """
    篇章大纲
    
    表示小说中的一个篇章（Arc），包含篇章索引、标题、目标和预计章节数。
    """
    index: int                    # 篇章索引
    title: str                    # 篇章标题
    goal: str                     # 篇章目标
    estimated_chapters: int = 0   # 预计章节数
    chapters: list[OutlineEntry] = field(default_factory=list)  # 包含的章节列表

    def is_expanded(self) -> bool:
        """判断篇章是否已展开（包含具体章节）"""
        return len(self.chapters) > 0


@dataclass
class VolumeOutline:
    """
    卷大纲
    
    表示小说的一个卷（Volume），包含卷索引、标题、主题和所属篇章列表。
    """
    index: int               # 卷索引
    title: str               # 卷标题
    theme: str               # 卷主题
    final: bool = False      # 是否为最终卷
    arcs: list[ArcOutline] = field(default_factory=list)  # 包含的篇章列表


@dataclass
class StoryCompass:
    """
    故事罗盘
    
    用于指导长篇小说创作方向，包含结局方向、开放线索和预计规模。
    """
    ending_direction: str     # 结局方向（如：悲剧/喜剧/开放式）
    open_threads: list[str] = field(default_factory=list)  # 当前开放的线索
    estimated_scale: str = ""  # 预计规模（short/mid/long）
    last_updated: int = 0      # 最后更新时间戳


@dataclass
class WorldRule:
    """
    世界规则
    
    定义小说世界中的设定规则，包含类别、规则内容和边界条件。
    """
    category: str    # 规则类别（魔法/科技/社会等）
    rule: str        # 规则内容
    boundary: str = ""  # 规则边界（适用范围/限制条件）


def flatten_outline(volumes: list[VolumeOutline]) -> list[OutlineEntry]:
    """将层级大纲展平为线性章节列表"""
    out: list[OutlineEntry] = []
    chapter = 1
    for vol in volumes:
        for arc in vol.arcs:
            for item in arc.chapters:
                out.append(
                    OutlineEntry(
                        chapter=chapter,
                        title=item.title,
                        core_event=item.core_event,
                        hook=item.hook,
                        scenes=list(item.scenes),
                    )
                )
                chapter += 1
    return out


def total_chapters(volumes: list[VolumeOutline]) -> int:
    """计算总章节数"""
    return len(flatten_outline(volumes))
