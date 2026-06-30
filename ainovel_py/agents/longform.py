from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ainovel_py.agents.hints import HintAction
from ainovel_py.assets import select_architect_prompt
from ainovel_py.host.events import Event


def generate_longform_outline_payload(
    client: Any,
    assets: Any,
    planning_tier: str,
    chapter: int,
    mode: str,
) -> dict[str, Any]:
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
    if HintAction.ARC_END in actions:
        emit_event(Event(time=datetime.now(), category="TOOL", summary=f"执行 arc_end 后续动作 (ch{chapter})", level="info"))
        runner.call_tool(
            "save_arc_summary",
            {
                "volume": 1,
                "arc": max(1, chapter // 3),
                "title": f"第{max(1, chapter // 3)}弧",
                "summary": f"到第{chapter}章的弧总结",
                "key_events": [f"第{chapter-2}~{chapter}章关键推进"],
                "character_snapshots": [{"name": "主角", "status": "仍在追查", "power": "稳步提升", "motivation": "查清真相", "relations": "与同伴建立基础信任"}],
                "style_rules": {"prose": ["保持紧凑节奏", "场景切换时保留因果衔接", "每章保留明确钩子"], "dialogue": [{"name": "主角", "rules": ["短句为主", "关键处直陈目标"]}], "taboos": ["避免重复解释已知设定"]},
            },
        )
        out_lines.append("[hint-actions] arc_end -> save_arc_summary")
    if HintAction.BOOK_COMPLETE in actions:
        out_lines.append("[hint-actions] book_complete -> 已到达收尾阶段")
        if chapter % 6 == 0:
            runner.call_tool(
                "save_volume_summary",
                {
                    "volume": 1,
                    "title": "第一卷",
                    "summary": f"到第{chapter}章的卷总结",
                    "key_events": ["主线建立", "冲突升级", "阶段性转折"],
                },
            )
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
