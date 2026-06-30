from __future__ import annotations

from enum import Enum


class TaskTag(str, Enum):
    """任务标签枚举，定义主 Agent 可以分派给角色的任务类型。

    每个标签对应一个角色的特定技能：
    - PLAN_CHAPTER → Architect 的规划技能
    - WRITE_CHAPTER → Writer 的写作技能
    - COMMIT_CHAPTER → Editor 的提交技能
    - REVIEW_CHAPTER → Editor 的评审技能
    - REWRITE_CHAPTER → Writer 的重写技能（注入评审意见）
    - ARC_SUMMARY → Architect 的弧摘要技能
    - VOLUME_SUMMARY → Architect 的卷摘要技能
    - EXPAND_ARC → Architect 的大纲扩展技能
    - FINISH → 结束
    """
    PLAN_CHAPTER = "plan_chapter"
    WRITE_CHAPTER = "write_chapter"
    COMMIT_CHAPTER = "commit_chapter"
    REVIEW_CHAPTER = "review_chapter"
    REWRITE_CHAPTER = "rewrite_chapter"
    ARC_SUMMARY = "arc_summary"
    VOLUME_SUMMARY = "volume_summary"
    EXPAND_ARC = "expand_arc"
    FINISH = "finish"
