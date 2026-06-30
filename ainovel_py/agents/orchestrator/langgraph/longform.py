from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ainovel_py.assets import select_architect_prompt
from ainovel_py.host.events import Event

from .hints import HintAction
from .review_flow import _build_arc_payload, _build_volume_payload


def generate_longform_outline_payload(
    client: Any,
    assets: Any,
    planning_tier: str,
    chapter: int,
    mode: str,
) -> dict[str, Any]:
    """通过 LLM 生成长篇分层大纲的 payload。

    根据模式（mode）不同，调用 LLM 生成不同粒度的大纲结构：
    - "append_volume"：生成整卷规划 JSON，包含卷索引、标题、主题、弧列表
    - "expand_arc"：生成下一弧的章节详细列表 JSON 数组

    此函数是 expand_arc_node 的核心数据源，生成的 payload 会被传入
    save_foundation 工具持久化到存储层。

    Args:
        client: LLM 客户端实例（OpenAICompatClient），用于调用大模型
        assets: 资源包对象，用于获取 architect 系统提示词
        planning_tier: 规划层级（如 "simple"/"layered"/"compass"），决定提示词复杂度
        chapter: 当前章节号，作为上下文信息传给 LLM
        mode: 生成模式，"append_volume" 或 "expand_arc"

    Returns:
        - append_volume 模式：返回完整卷规划的 JSON 解析字典
        - expand_arc 模式：返回 {"chapters": [...]} 格式的字典
    """
    system_prompt = select_architect_prompt(assets, planning_tier)
    if not system_prompt:
        system_prompt = "你是小说规划助手，只输出 JSON。"
    if mode == "append_volume":
        prompt = f"请为当前故事追加下一卷规划，严格输出 JSON 对象，字段：index,title,theme,final,arcs。arcs 内每项包括 index,title,goal,estimated_chapters,chapters。请至少让第一弧包含详细 chapters。当前章节：{chapter}。"
        raw = client.complete(system_prompt, prompt, temperature=0.4)
        import json
        return json.loads(raw)
    prompt = f"请为当前故事展开下一弧，严格输出 JSON 数组。每个元素字段：chapter,title,core_event,hook,scenes。当前章节：{chapter}。"
    raw = client.complete(system_prompt, prompt, temperature=0.4)
    import json
    return {"chapters": json.loads(raw)}


def run_longform_hint_actions(
    client: Any,
    runner: Any,
    emit_event: Callable[[Event], None],
    assets: Any,
    planning_tier: str,
    chapter: int,
    actions: list[HintAction],
    out_lines: list[str],
) -> None:
    """根据 HintAction 列表依次执行长篇相关的后续动作。

    这是一个批量执行函数，按固定顺序处理 4 类长篇动作：
    1. ARC_END → 调用 save_arc_summary 工具保存弧摘要
    2. BOOK_COMPLETE → 输出收尾日志 + 条件性调用 save_volume_summary（每6章一次）
    3. NEW_VOLUME_REQUIRED → 生成追加卷大纲 + 调用 save_foundation 持久化
    4. EXPAND_ARC_REQUIRED → 生成扩展弧大纲 + 调用 save_foundation 持久化

    注意：此函数与 nodes/core.py 中的独立节点（arc_summary_node、volume_summary_node、
    expand_arc_node）功能有重叠，但此函数用于非图节点的直接调用场景（如外部调度器）。

    Args:
        client: LLM 客户端实例，用于调用大模型生成分层大纲
        runner: AgentRunner 实例，用于调用工具
        emit_event: 事件发射函数，用于记录工具调用日志
        assets: 资源包对象
        planning_tier: 规划层级
        chapter: 当前章节号
        actions: 待执行的 HintAction 列表
        out_lines: 输出行列表（会被就地修改，追加日志行）
    """
    if HintAction.ARC_END in actions:
        emit_event(Event(time=datetime.now(), category="TOOL", summary=f"执行 arc_end 后续动作 (ch{chapter})", level="info"))
        runner.call_tool("save_arc_summary", _build_arc_payload(chapter))
        out_lines.append("[hint-actions] arc_end -> save_arc_summary")
    if HintAction.BOOK_COMPLETE in actions:
        out_lines.append("[hint-actions] book_complete -> 已到达收尾阶段")
        if chapter % 6 == 0:
            runner.call_tool("save_volume_summary", _build_volume_payload(chapter))
            out_lines.append("[hint-actions] book_complete -> save_volume_summary")
    if HintAction.NEW_VOLUME_REQUIRED in actions:
        emit_event(Event(time=datetime.now(), category="TOOL", summary=f"执行 new_volume_required 规划 (ch{chapter})", level="info"))
        payload = generate_longform_outline_payload(client, assets, planning_tier, chapter, "append_volume")
        runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
        out_lines.append("[hint-actions] new_volume_required -> save_foundation append_volume")
    if HintAction.EXPAND_ARC_REQUIRED in actions:
        emit_event(Event(time=datetime.now(), category="TOOL", summary=f"执行 expand_arc_required 规划 (ch{chapter})", level="info"))
        payload = generate_longform_outline_payload(client, assets, planning_tier, chapter, "expand_arc")
        runner.call_tool("save_foundation", {"type": "expand_arc", "volume": 1, "arc": max(1, chapter // 3) + 1, "content": payload.get("chapters", [])})
        out_lines.append("[hint-actions] expand_arc_required -> save_foundation expand_arc")
