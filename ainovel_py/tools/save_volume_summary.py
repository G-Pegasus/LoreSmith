from __future__ import annotations

from typing import Any

from ainovel_py.domain.checkpoint import volume_scope
from ainovel_py.store.store import Store
from ainovel_py.tools.parsers import parse_volume_summary


class SaveVolumeSummaryTool:
    """
    卷摘要保存工具
    
    负责保存卷级别的摘要信息，用于支持长篇小说的分层叙事结构。
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "save_volume_summary"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行卷摘要保存
        
        Args:
            args: 参数字典，包含 volume 和 summary 字段
        
        Returns:
            保存结果字典
        """
        summary = parse_volume_summary(args)
        if summary.volume <= 0:
            raise ValueError("volume must be > 0")
        self.store.summaries.save_volume_summary(summary)
        self.store.checkpoints.append(volume_scope(summary.volume), "volume_summary")
        return {"saved": True, "type": "volume_summary", "volume": summary.volume}
