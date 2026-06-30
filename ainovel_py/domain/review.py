from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimelineEvent:
    """
    时间线事件
    
    记录故事时间线上的关键事件点。
    """
    chapter: int                        # 发生章节
    time: str                           # 时间描述
    event: str                          # 事件描述
    characters: list[str] = field(default_factory=list)  # 涉及人物


@dataclass
class ForeshadowEntry:
    """
    伏笔条目
    
    记录故事中的伏笔线索，包括埋设位置、状态和解决章节。
    """
    id: str          # 伏笔ID
    description: str # 伏笔描述
    planted_at: int  # 埋设章节
    status: str      # 状态（planted/advanced/resolved）
    resolved_at: int = 0  # 解决章节


@dataclass
class ForeshadowUpdate:
    """
    伏笔更新
    
    用于更新伏笔状态的操作记录。
    """
    id: str          # 伏笔ID
    action: str      # 操作类型（plant/advance/resolve）
    description: str = ""  # 更新描述


@dataclass
class RelationshipEntry:
    """
    人物关系条目
    
    记录两个人物之间的关系状态。
    """
    character_a: str  # 人物A
    character_b: str  # 人物B
    relation: str     # 关系类型
    chapter: int      # 记录章节


@dataclass
class StateChange:
    """
    状态变更记录
    
    记录实体属性的变更历史。
    """
    entity: str       # 实体名称
    field: str        # 字段名
    new_value: str    # 新值
    chapter: int      # 变更章节
    old_value: str = ""  # 旧值
    reason: str = ""     # 变更原因


@dataclass
class ConsistencyIssue:
    """
    一致性问题
    
    记录评审过程中发现的一致性问题。
    """
    type: str              # 问题类型
    severity: str          # 严重程度
    description: str       # 问题描述
    evidence: str = ""     # 证据
    suggestion: str = ""   # 建议


@dataclass
class DimensionScore:
    """
    维度评分
    
    记录单个评审维度的评分结果。
    """
    dimension: str    # 维度名称
    score: int        # 分数（0-100）
    verdict: str      # 判定（pass/warning/fail）
    comment: str = "" # 评语


@dataclass
class ReviewEntry:
    """
    评审记录
    
    完整的章节评审结果，包含多个维度的评分和问题列表。
    """
    chapter: int                        # 章节号
    scope: str                          # 评审范围
    issues: list[ConsistencyIssue]      # 问题列表
    verdict: str                        # 最终判定（accept/polish/rewrite）
    summary: str                        # 评审摘要
    dimensions: list[DimensionScore] = field(default_factory=list)  # 维度评分
    contract_status: str = ""           # 契约状态
    contract_misses: list[str] = field(default_factory=list)        # 未满足的契约项
    contract_notes: str = ""            # 契约备注
    affected_chapters: list[int] = field(default_factory=list)      # 受影响章节
