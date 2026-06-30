from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.domain.runtime import Phase, extract_novel_name_from_premise, normalize_planning_tier
from ainovel_py.domain.story import flatten_outline, total_chapters
from ainovel_py.store.store import Store
from ainovel_py.tools.helpers import parse_json_content
from ainovel_py.tools.parsers import (
    parse_character,
    parse_outline_entry,
    parse_story_compass,
    parse_volume_outline,
    parse_world_rule,
)


class SaveFoundationTool:
    """
    基础设定保存工具
    
    负责保存小说的各种基础设定，包括：
    - premise: 故事前提
    - outline: 章节大纲
    - layered_outline: 分层大纲（卷-篇章-章节）
    - characters: 人物设定
    - world_rules: 世界规则
    - expand_arc: 扩展篇章
    - append_volume: 追加卷
    - mark_final: 标记卷为最终状态
    - update_compass: 更新故事罗盘
    """
    def __init__(self, store: Store) -> None:
        self.store = store

    def name(self) -> str:
        """返回工具名称"""
        return "save_foundation"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        执行基础设定保存
        
        Args:
            args: 参数字典，包含：
                - type: 设定类型（premise/outline/layered_outline/characters/world_rules等）
                - content: 设定内容
                - scale: 规划层级
                - volume: 卷号（用于expand_arc/append_volume/mark_final）
                - arc: 篇章号（用于expand_arc）
        
        Returns:
            保存结果字典，包含剩余未完成的设定项
        """
        foundation_type = str(args.get("type", "") or "").strip()
        if not foundation_type:
            raise ValueError("type is required")

        content = parse_json_content(args.get("content"))
        raw_scale = str(args.get("scale", "") or "")
        scale = normalize_planning_tier(raw_scale)
        if raw_scale.strip() and not scale:
            raise ValueError(f"invalid scale: {raw_scale}")
        if scale:
            self.store.run_meta.set_planning_tier(scale)
        volume = int(args.get("volume", 0) or 0)
        arc = int(args.get("arc", 0) or 0)

        result: dict[str, Any] = {"saved": True, "type": foundation_type, "scale": scale}

        if foundation_type == "premise":
            if not isinstance(content, str):
                raise ValueError("premise content must be markdown string")
            self.store.outline.save_premise(content)
            name = extract_novel_name_from_premise(content)
            if name:
                self.store.progress.set_novel_name(name)
                result["novel_name"] = name
            self.store.progress.update_phase(Phase.PREMISE)

        elif foundation_type == "outline":
            if not isinstance(content, list):
                raise ValueError("outline content must be array")
            entries = [parse_outline_entry(x) for x in content]
            self.store.outline.save_outline(entries)
            self.store.progress.update_phase(Phase.OUTLINE)
            self.store.progress.set_total_chapters(len(entries))
            self.store.progress.set_layered(False)
            self.store.progress.update_volume_arc(0, 0)
            result["chapters"] = len(entries)

        elif foundation_type == "layered_outline":
            if not isinstance(content, list):
                raise ValueError("layered_outline content must be array")
            volumes = [parse_volume_outline(x) for x in content]
            self.store.outline.save_layered_outline(volumes)
            flat = flatten_outline(volumes)
            self.store.outline.save_outline(flat)
            self.store.progress.update_phase(Phase.OUTLINE)
            self.store.progress.set_total_chapters(total_chapters(volumes))
            self.store.progress.set_layered(True)
            if volumes and volumes[0].arcs:
                self.store.progress.update_volume_arc(volumes[0].index, volumes[0].arcs[0].index)
            result["volumes"] = len(volumes)
            result["chapters"] = len(flat)

        elif foundation_type == "characters":
            if not isinstance(content, list):
                raise ValueError("characters content must be array")
            chars = [parse_character(x) for x in content]
            self.store.characters.save(chars)
            result["count"] = len(chars)

        elif foundation_type == "world_rules":
            if not isinstance(content, list):
                raise ValueError("world_rules content must be array")
            rules = [parse_world_rule(x) for x in content]
            self.store.world.save_world_rules(rules)
            result["count"] = len(rules)

        elif foundation_type == "expand_arc":
            if volume <= 0 or arc <= 0:
                raise ValueError("expand_arc requires volume and arc")
            if not isinstance(content, list):
                raise ValueError("expand_arc content must be array")
            volumes = self.store.outline.load_layered_outline()
            found = False
            for i, vol in enumerate(volumes):
                if vol.index != volume:
                    continue
                for j, a in enumerate(vol.arcs):
                    if a.index != arc:
                        continue
                    vol.arcs[j].chapters = [parse_outline_entry(x) for x in content]
                    vol.arcs[j].estimated_chapters = 0
                    found = True
            if not found:
                raise ValueError(f"arc not found: volume={volume} arc={arc}")
            self.store.outline.save_layered_outline(volumes)
            flat = flatten_outline(volumes)
            self.store.outline.save_outline(flat)
            self.store.progress.set_total_chapters(len(flat))
            result.update({"volume": volume, "arc": arc, "chapters": len(content)})

        elif foundation_type == "append_volume":
            vol = parse_volume_outline(content if isinstance(content, dict) else {})
            volumes = self.store.outline.load_layered_outline()
            if volumes and vol.index <= volumes[-1].index:
                raise ValueError("volume index must be increasing")
            volumes.append(vol)
            self.store.outline.save_layered_outline(volumes)
            flat = flatten_outline(volumes)
            self.store.outline.save_outline(flat)
            self.store.progress.set_total_chapters(len(flat))
            result.update({"volume": vol.index, "arcs": len(vol.arcs)})

        elif foundation_type == "mark_final":
            if volume <= 0:
                raise ValueError("mark_final requires volume")
            volumes = self.store.outline.load_layered_outline()
            found = False
            for i, vol in enumerate(volumes):
                if vol.index == volume:
                    volumes[i].final = True
                    found = True
            if not found:
                raise ValueError(f"volume {volume} not found")
            self.store.outline.save_layered_outline(volumes)
            result.update({"volume": volume, "final": True})

        elif foundation_type == "update_compass":
            if not isinstance(content, dict):
                raise ValueError("update_compass content must be object")
            compass = parse_story_compass(content)
            if not compass.ending_direction:
                raise ValueError("ending_direction is required")
            self.store.outline.save_compass(compass)
            result["ending_direction"] = compass.ending_direction

        else:
            raise ValueError(
                f"unknown type {foundation_type}, expected premise/outline/layered_outline/characters/world_rules/expand_arc/append_volume/update_compass/mark_final"
            )

        result["remaining"] = self._remaining()
        if not result["remaining"]:
            result["system_hints"] = {"next_step": "所有基础设定已完成，直接返回结果给 Coordinator"}
        return result

    def _remaining(self) -> list[str]:
        """
        检查尚未完成的基础设定项
        
        Returns:
            缺失的设定项列表
        """
        missing: list[str] = []
        if not self.store.outline.load_premise():
            missing.append("premise")
        if not self.store.outline.load_outline():
            missing.append("outline")
        layered = self.store.outline.load_layered_outline()
        if layered and self.store.outline.load_compass() is None:
            missing.append("compass")
        if not self.store.characters.load():
            missing.append("characters")
        if not self.store.world.load_world_rules():
            missing.append("world_rules")
        return missing
