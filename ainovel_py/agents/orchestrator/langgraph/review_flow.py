from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ainovel_py.host.events import Event

from .hints import HintAction

DEFAULT_ARC_SUMMARY_PAYLOAD = {
    "volume": 1,
    "arc": 1,
    "title": "第1弧",
    "summary": "弧总结",
    "key_events": ["关键推进"],
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
}

DEFAULT_VOLUME_SUMMARY_PAYLOAD = {
    "volume": 1,
    "title": "第一卷",
    "summary": "卷总结",
    "key_events": ["主线建立", "冲突升级", "阶段性转折"],
}


def _build_arc_payload(chapter: int) -> dict[str, Any]:
    payload = dict(DEFAULT_ARC_SUMMARY_PAYLOAD)
    arc = max(1, chapter // 3)
    payload["arc"] = arc
    payload["title"] = f"第{arc}弧"
    payload["summary"] = f"到第{chapter}章的弧总结"
    payload["key_events"] = [f"第{chapter-2}~{chapter}章关键推进"]
    return payload


def _build_volume_payload(chapter: int, volume: int = 1, always: bool = False) -> dict[str, Any]:
    payload = dict(DEFAULT_VOLUME_SUMMARY_PAYLOAD)
    payload["volume"] = volume
    payload["title"] = f"第{volume}卷" if always else "第一卷"
    payload["summary"] = f"到第{chapter}章的卷总结"
    return payload


def save_arc_summary_followup(
    runner: Any,
    emit_event: Callable[[Event], None],
    chapter: int,
    out_lines: list[str],
) -> None:
    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_arc_summary (ch{chapter})", level="info"))
    runner.call_tool("save_arc_summary", _build_arc_payload(chapter))
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
    runner.call_tool("save_volume_summary", _build_volume_payload(chapter, volume, always))
    out_lines.append("[tool] save_volume_summary -> saved=True")
    return True
