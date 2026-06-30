from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HintAction(str, Enum):
    """工作流指令动作枚举，定义 Agent 之间传递意图的词汇表。

    这些枚举值由 LLM 返回的系统提示（system_hints）经 parse_hint_actions 解析后生成，
    作为图状态流转的信号，决定下一步跳转到哪个节点。
    """

    CONTINUE = "continue"
    REVIEW_REQUIRED = "review_required"
    REWRITE_REQUIRED = "rewrite_required"
    POLISH_REQUIRED = "polish_required"
    REWRITE_DONE = "rewrite_done"
    WRITER_FEEDBACK = "writer_feedback"
    ARC_END = "arc_end"
    BOOK_COMPLETE = "book_complete"
    NEW_VOLUME_REQUIRED = "new_volume_required"
    EXPAND_ARC_REQUIRED = "expand_arc_required"
    REVIEW_ACCEPTED = "review_accepted"
    UNKNOWN = "unknown"


@dataclass
class ActionPlan:
    """可执行的动作计划，将 HintAction 列表转化为图跳转目标。

    由 plan_actions() 函数根据 HintAction 列表构建，被节点函数用于
    设置 pending_action 和 pending_actions，驱动条件边路由。

    Attributes:
        requires_review: 是否需要触发 review 节点进行评审
        rewrite_mode: 重写模式，"rewrite" 表示完全重写，"polish" 表示轻度打磨
        queue: 待执行的动作队列，按顺序包含 arc_summary / volume_summary / expand_arc 等目标节点名
    """

    requires_review: bool = False
    rewrite_mode: str = ""
    queue: list[str] = field(default_factory=list)

    @property
    def next_action(self) -> str:
        """根据优先级返回下一个应跳转的目标节点名。

        优先级从高到低：
        1. requires_review 为 True → 返回 "review"（触发评审）
        2. rewrite_mode 非空 → 返回重写模式（"rewrite" 或 "polish"）
        3. queue 非空 → 返回队列首个动作（如 "arc_summary"）
        4. 以上均不满足 → 返回 "checkpoint"（回到检查点，继续下一章）
        """
        if self.requires_review:
            return "review"
        if self.rewrite_mode:
            return self.rewrite_mode
        if self.queue:
            return self.queue[0]
        return "checkpoint"


def parse_hint_actions(hints: list[str]) -> list[HintAction]:
    """将原始字符串 hint 列表解析为 HintAction 枚举列表。

    从 commit 或 review 工具返回的 system_hints 字段中提取字符串列表，
    通过关键词匹配将每条 hint 映射为对应的 HintAction 枚举值。
    支持中英文关键词匹配（如 "rewrite_required" 和 "重写_required" 均可识别）。

    Args:
        hints: 原始提示字符串列表，如 ["arc_end", "需要重写", "review_required"]

    Returns:
        解析后的 HintAction 枚举列表，无法识别的 hint 映射为 UNKNOWN
    """
    actions: list[HintAction] = []
    for hint in hints:
        lower = hint.lower()
        if "review_required" in lower:
            actions.append(HintAction.REVIEW_REQUIRED)
        elif "review_accepted" in lower:
            actions.append(HintAction.REVIEW_ACCEPTED)
        elif "rewrite_required" in lower or "重写_required" in lower:
            actions.append(HintAction.REWRITE_REQUIRED)
        elif "polish_required" in lower or "打磨_required" in lower:
            actions.append(HintAction.POLISH_REQUIRED)
        elif "writer_feedback" in lower:
            actions.append(HintAction.WRITER_FEEDBACK)
        elif "continue:" in lower or "continue" in lower:
            actions.append(HintAction.CONTINUE)
        elif "arc_end" in lower:
            actions.append(HintAction.ARC_END)
        elif "book_complete" in lower:
            actions.append(HintAction.BOOK_COMPLETE)
        elif "new_volume_required" in lower:
            actions.append(HintAction.NEW_VOLUME_REQUIRED)
        elif "expand_arc_required" in lower:
            actions.append(HintAction.EXPAND_ARC_REQUIRED)
        elif "全部完成" in hint or "完成重写" in hint or "完成打磨" in hint:
            actions.append(HintAction.REWRITE_DONE)
        else:
            actions.append(HintAction.UNKNOWN)
    return actions


def needs_review_from_actions(commit_res: dict[str, Any], actions: list[HintAction]) -> bool:
    """判断是否需要触发评审流程。

    双重检查机制：优先查看 commit 结果中的 review_required 标记，
    其次检查解析后的动作列表中是否包含 REVIEW_REQUIRED。

    Args:
        commit_res: commit_chapter 工具返回的结果字典
        actions: 已解析的 HintAction 列表

    Returns:
        True 表示需要触发 review 节点
    """
    if commit_res.get("review_required"):
        return True
    return HintAction.REVIEW_REQUIRED in actions


def has_placeholder_action(actions: list[HintAction]) -> bool:
    """检测动作列表中是否包含标记性/占位动作。

    占位动作是指那些表示流程阶段性终点的信号，
    如弧结束(ARC_END)、全书完成(BOOK_COMPLETE)、需要新卷(NEW_VOLUME_REQUIRED)、
    需要扩展弧(EXPAND_ARC_REQUIRED)。这些动作通常不会直接触发节点跳转，
    而是通过 plan_actions 转化为 queue 中的具体目标。

    Args:
        actions: 已解析的 HintAction 列表

    Returns:
        列表中存在任一占位动作时返回 True
    """
    return any(
        a in {
            HintAction.ARC_END,
            HintAction.BOOK_COMPLETE,
            HintAction.NEW_VOLUME_REQUIRED,
            HintAction.EXPAND_ARC_REQUIRED,
        }
        for a in actions
    )


def plan_actions(actions: list[HintAction]) -> ActionPlan:
    """根据 HintAction 列表构建可执行的 ActionPlan。

    这是指令系统的核心调度函数，将语义化的动作信号转化为图的跳转目标：

    调度规则：
    - rewrite_mode 优先级：REWRITE_REQUIRED > POLISH_REQUIRED（两者互斥，取先出现的）
    - queue 构建顺序：ARC_END → arc_summary, BOOK_COMPLETE → volume_summary,
      NEW_VOLUME_REQUIRED/EXPAND_ARC_REQUIRED → expand_arc
    - requires_review：当列表中存在 REVIEW_REQUIRED 时为 True

    注意：REVIEW_REQUIRED 不会进入 queue，而是通过 requires_review 标志
    在 next_action 属性中以最高优先级返回 "review"。

    Args:
        actions: 已解析的 HintAction 列表

    Returns:
        包含 requires_review、rewrite_mode、queue 的 ActionPlan 对象
    """
    queue: list[str] = []
    rewrite_mode = ""

    if HintAction.REWRITE_REQUIRED in actions:
        rewrite_mode = "rewrite"
    elif HintAction.POLISH_REQUIRED in actions:
        rewrite_mode = "polish"

    if HintAction.ARC_END in actions:
        queue.append("arc_summary")
    if HintAction.BOOK_COMPLETE in actions:
        queue.append("volume_summary")
    if HintAction.NEW_VOLUME_REQUIRED in actions or HintAction.EXPAND_ARC_REQUIRED in actions:
        queue.append("expand_arc")

    return ActionPlan(
        requires_review=HintAction.REVIEW_REQUIRED in actions,
        rewrite_mode=rewrite_mode,
        queue=queue,
    )
