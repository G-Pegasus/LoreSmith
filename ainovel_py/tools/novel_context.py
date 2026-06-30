from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ainovel_py.assets import architect_references, load_bundle, style_text, writer_references
from ainovel_py.domain.runtime import Progress, infer_planning_tier, normalize_planning_tier
from ainovel_py.store.store import Store


class NovelContextTool:
    def __init__(self, store: Store, style: str = "default") -> None:
        self.store = store
        self.style = style

    def name(self) -> str:
        return "novel_context"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = int(args.get("chapter", 0) or 0)
        result: dict[str, Any] = {}

        bundle = load_bundle(self.style)
        progress = self.store.progress.load() or Progress()
        run_meta = self.store.run_meta.load()
        result["progress_status"] = {
            "phase": progress.phase,
            "flow": progress.flow,
            "next_chapter": progress.next_chapter(),
            "pending_rewrites": progress.pending_rewrites,
            "rewrite_reason": progress.rewrite_reason,
        }

        premise = self.store.outline.load_premise()
        if premise:
            result["premise"] = premise

        outline = self.store.outline.load_outline()
        if outline:
            result["outline"] = [asdict(x) for x in outline]

        layered = self.store.outline.load_layered_outline()
        if layered:
            result["layered_outline"] = [asdict(x) for x in layered]

        compass = self.store.outline.load_compass()
        if compass:
            result["compass"] = asdict(compass)

        explicit_tier = normalize_planning_tier(run_meta.planning_tier if run_meta else "")
        result["planning_tier"] = explicit_tier or infer_planning_tier(
            progress,
            has_layered_outline=bool(layered),
            has_compass=compass is not None,
        )

        chars = self.store.characters.load()
        if chars:
            result["characters"] = [asdict(x) for x in chars]

        rules = self.store.world.load_world_rules()
        if rules:
            result["world_rules"] = [asdict(x) for x in rules]

        result["style_reference"] = style_text(self.style)

        if chapter > 0:
            refs = writer_references(bundle, chapter)
            if refs:
                result["references"] = refs
            summaries = self.store.summaries.load_recent_summaries(chapter, 5)
            if summaries:
                result["recent_summaries"] = [asdict(x) for x in summaries]
            timeline = [x for x in self.store.world.load_timeline() if x.chapter < chapter and x.chapter >= max(chapter - 8, 1)]
            if timeline:
                result["timeline"] = [asdict(x) for x in timeline]
            foreshadow = self.store.world.load_active_foreshadow()
            if foreshadow:
                result["foreshadow_ledger"] = [asdict(x) for x in foreshadow]
            relationships = self.store.world.load_relationships()
            if relationships:
                result["relationship_state"] = [asdict(x) for x in relationships]
            state_changes = self.store.world.load_state_changes()
            if state_changes:
                result["recent_state_changes"] = [asdict(x) for x in state_changes[-50:]]
            entry = self.store.outline.get_chapter_outline(chapter)
            if entry:
                result["current_chapter_outline"] = asdict(entry)
            plan = self.store.drafts.load_chapter_plan(chapter)
            if plan:
                result["chapter_plan"] = asdict(plan)

            latest = progress.completed_chapters[-1] if progress.completed_chapters else 0
            if latest:
                review = self.store.world.load_review(latest)
                if review:
                    result["latest_review"] = asdict(review)

            if progress.current_volume > 0:
                arc_summaries = self.store.summaries.load_arc_summaries(progress.current_volume)
                if arc_summaries:
                    result["arc_summaries"] = [asdict(x) for x in arc_summaries]
            volume_summaries = self.store.summaries.load_all_volume_summaries()
            if volume_summaries:
                result["volume_summaries"] = [asdict(x) for x in volume_summaries]

            snapshots = self.store.world.load_latest_character_snapshots()
            if snapshots:
                result["character_snapshots"] = [asdict(x) for x in snapshots]
            style_rules = self.store.world.load_style_rules()
            if style_rules:
                result["style_rules"] = asdict(style_rules)

        if chapter <= 0:
            refs = architect_references(bundle)
            if refs:
                result["reference_pack"] = refs

        result["_loading_summary"] = f"chapter={chapter or 'none'} keys={len(result.keys())}"
        return result
