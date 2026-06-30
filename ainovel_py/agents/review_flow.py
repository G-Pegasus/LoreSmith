from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ainovel_py.host.events import Event


def save_arc_summary_followup(
    runner: Any,
    emit_event: Callable[[Event], None],
    chapter: int,
    out_lines: list[str],
) -> None:
    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_arc_summary (ch{chapter})", level="info"))
    runner.call_tool(
        "save_arc_summary",
        {
            "volume": 1,
            "arc": max(1, chapter // 3),
            "title": f"第{max(1, chapter // 3)}弧",
            "summary": f"到第{chapter}章的弧总结",
            "key_events": [f"第{chapter-2}~{chapter}章关键推进"],
            "character_snapshots": [
                {
                    "name": "主角",
                    "status": "仍在追查",
                    "power": "稳步提升",
                    "motivation": "查清真相",
                    "relations": "与同伴建立基础信任",
                }
            ],
            "style_rules": {
                "prose": ["保持紧凑节奏", "场景切换时保留因果衔接", "每章保留明确钩子"],
                "dialogue": [{"name": "主角", "rules": ["短句为主", "关键处直陈目标"]}],
                "taboos": ["避免重复解释已知设定"],
            },
        },
    )
    out_lines.append("[tool] save_arc_summary -> saved=True")


def save_volume_summary_followup(
    runner: Any,
    emit_event: Callable[[Event], None],
    chapter: int,
    out_lines: list[str],
    *,
    volume: int = 1,
    always: bool = False,
) -> bool:
    if not always and chapter % 6 != 0:
        return False
    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_volume_summary (ch{chapter})", level="info"))
    runner.call_tool(
        "save_volume_summary",
        {
            "volume": volume,
            "title": f"第{volume}卷" if always else "第一卷",
            "summary": f"到第{chapter}章的卷总结",
            "key_events": ["主线建立", "冲突升级", "阶段性转折"],
        },
    )
    out_lines.append("[tool] save_volume_summary -> saved=True")
    return True
