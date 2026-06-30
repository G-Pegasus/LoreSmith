from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ScopeKind:
    """检查点作用域类型枚举"""
    CHAPTER = "chapter"  # 章节级
    ARC = "arc"          # 篇章级
    VOLUME = "volume"    # 卷级
    GLOBAL = "global"    # 全局级


@dataclass
class Scope:
    """
    检查点作用域定义
    
    用于标识检查点适用的层级范围，支持章节、篇章、卷和全局四个层级。
    通过 matches 方法判断两个作用域是否匹配。
    """
    kind: str       # 作用域类型
    chapter: int = 0  # 章节号（仅 CHAPTER 类型有效）
    volume: int = 0   # 卷号（ARC/VOLUME 类型有效）
    arc: int = 0      # 篇章号（ARC 类型有效）

    def matches(self, other: "Scope") -> bool:
        """判断两个作用域是否匹配"""
        if self.kind != other.kind:
            return False
        if self.kind == ScopeKind.CHAPTER:
            return self.chapter == other.chapter
        if self.kind == ScopeKind.ARC:
            return self.volume == other.volume and self.arc == other.arc
        if self.kind == ScopeKind.VOLUME:
            return self.volume == other.volume
        return True


def chapter_scope(chapter: int) -> Scope:
    """创建章节级作用域"""
    return Scope(kind=ScopeKind.CHAPTER, chapter=chapter)


def arc_scope(volume: int, arc: int) -> Scope:
    """创建篇章级作用域"""
    return Scope(kind=ScopeKind.ARC, volume=volume, arc=arc)


def volume_scope(volume: int) -> Scope:
    """创建卷级作用域"""
    return Scope(kind=ScopeKind.VOLUME, volume=volume)


def global_scope() -> Scope:
    """创建全局作用域"""
    return Scope(kind=ScopeKind.GLOBAL)


@dataclass
class Checkpoint:
    """
    检查点数据结构
    
    用于记录创作过程中的关键状态快照，支持断点续传功能。
    每个检查点包含序号、作用域、步骤名称和时间戳等信息。
    """
    seq: int              # 检查点序号
    scope: Scope          # 作用域
    step: str             # 当前步骤名称
    artifact: str = ""    # 关联的产物路径
    digest: str = ""      # 产物摘要（用于完整性校验）
    occurred_at: datetime = datetime.utcnow()  # 创建时间
