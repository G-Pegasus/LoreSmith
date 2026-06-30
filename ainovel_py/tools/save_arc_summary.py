from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ainovel_py.domain.checkpoint import arc_scope
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import (
    parse_arc_summary,
    parse_character_snapshot,
    parse_writing_style_rules,
)


class SaveArcSummaryTool:
    """
    篇章摘要保存工具
    
    负责保存篇章摘要信息，包括：
    - 篇章摘要本身
    - 人物快照（记录人物在篇章结束时的状态）
    - 写作风格规则
    
    用于支持长篇小说的分层叙事和人物发展追踪。
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "save_arc_summary"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行篇章摘要保存
        
        Args:
            args: 参数字典，包含：
                - volume: 卷号
                - arc: 篇章号
                - summary: 篇章摘要
                - character_snapshots: 人物快照列表
                - style_rules: 写作风格规则
        
        Returns:
            保存结果字典
        """
        summary = parse_arc_summary(args)
        if summary.volume <= 0 or summary.arc <= 0:
            raise ValueError("volume and arc must be > 0")

        # 保存篇章摘要
        self.store.summaries.save_arc_summary(summary)

        # 保存人物快照
        snapshots = [
            parse_character_snapshot(x, volume=summary.volume, arc=summary.arc)
            for x in (args.get("character_snapshots") or [])
            if isinstance(x, dict)
        ]
        if snapshots:
            self.store.world.save_character_snapshots(summary.volume, summary.arc, snapshots)

        # 保存写作风格规则
        style_rules_saved = False
        style_rules_raw = args.get("style_rules")
        if isinstance(style_rules_raw, dict) and style_rules_raw.get("prose"):
            rules = parse_writing_style_rules(style_rules_raw, volume=summary.volume, arc=summary.arc)
            if not rules.updated_at:
                rules.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.world.save_style_rules(rules)
            style_rules_saved = True

        # 记录检查点
        self.store.checkpoints.append(arc_scope(summary.volume, summary.arc), "arc_summary")

        return {
            "saved": True,
            "type": "arc_summary",
            "volume": summary.volume,
            "arc": summary.arc,
            "snapshots": len(snapshots),
            "style_rules_saved": style_rules_saved,
        }
