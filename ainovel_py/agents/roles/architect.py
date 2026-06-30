from __future__ import annotations

import json
from typing import Any

from ainovel_py.agents.runner import dict_to_chapter_plan, chapter_plan_to_dict
from ainovel_py.domain.runtime import infer_planning_tier, normalize_planning_tier

from .base import BaseAgent


class ArchitectAgent(BaseAgent):
    name = "architect"

    def system_prompt(self) -> str:
        return self.assets.prompts.get("architect") or "你是小说章节规划助手，只输出 JSON。"

    def execute(self, *, seed_text: str, chapter: int, context: dict[str, Any], feedback: str = "") -> dict[str, Any]:
        plan = self._build_dynamic_plan(seed_text, chapter, context, feedback)
        if feedback:
            revised = self._revise_plan_with_feedback(seed_text, chapter, context, plan, feedback)
            if revised:
                plan = revised
        self.runner.call_tool("plan_chapter", plan)
        return {"plan": plan, "chapter": chapter}

    def _build_dynamic_plan(self, seed_text: str, chapter: int, context: dict[str, Any], feedback: str = "") -> dict[str, Any]:
        outline = context.get("current_chapter_outline") or {}
        latest_review = context.get("latest_review") or {}
        recent_summaries = context.get("recent_summaries") or []
        review_focus: list[str] = []
        if isinstance(latest_review, dict):
            for issue in latest_review.get("issues") or []:
                desc = str(issue.get("description", "") or "").strip()
                if desc:
                    review_focus.append(desc)
        character_names = [
            str(item.get("name", "") or "").strip()
            for item in (context.get("characters") or [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ]
        summary_focus = [str(item.get("summary", "") or "") for item in recent_summaries if isinstance(item, dict)]
        rewrite_reason = str(context.get("rewrite_reason", "") or "")
        rewrite_issues = [
            str(item.get("description", "") or "")
            for item in (context.get("rewrite_issues") or [])
            if isinstance(item, dict)
        ]
        meta = self.store.run_meta.load()
        min_words_default = meta.min_words if meta else 1200
        target_words_default = meta.target_words if meta else 1800
        max_words_default = meta.max_words if meta else 2600
        contract = {
            "required_beats": [
                str(outline.get("core_event", "") or "推进主线"),
                "角色决策造成后续影响",
                str(outline.get("hook", "") or "章末制造明确悬念"),
            ],
            "forbidden_moves": ["提前完结主线", "无铺垫引入重大设定变更"],
            "continuity_checks": (review_focus or ["延续前文章节因果", "角色称谓与状态一致"])
            + (["严格使用用户提供的人物名称，不要擅自替换主角或创造同位角色"] if character_names else []),
            "evaluation_focus": ["节奏递进", "冲突兑现", "章末钩子有效"] + review_focus[:2] + rewrite_issues[:2],
            "emotion_target": "紧张推进并在章末提升期待",
            "payoff_points": summary_focus[:2],
            "hook_goal": str(outline.get("hook", "") or "形成强追读欲望"),
            "min_words": min_words_default,
            "target_words": target_words_default,
            "max_words": max_words_default,
        }
        base_plan = {
            "chapter": chapter,
            "title": str(outline.get("title", "") or f"第{chapter}章"),
            "goal": str(outline.get("core_event", "") or "推进主线冲突并制造新的局面"),
            "conflict": str(outline.get("core_event", "") or "角色在压力中做出高代价选择"),
            "hook": str(outline.get("hook", "") or "章末引出更大问题"),
            "emotion_arc": "承压 -> 升级 -> 反转/悬念",
            "notes": f"seed={seed_text[:80]} | rewrite_reason={rewrite_reason[:120]}",
            "contract": contract,
        }
        if feedback:
            revised = self._revise_plan_with_feedback(seed_text, chapter, context, base_plan, feedback)
            if revised:
                return revised
            base_plan["notes"] = (str(base_plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
        return base_plan

    def build_dynamic_plan(self, seed_text: str, chapter: int, context: dict[str, Any], feedback: str = "") -> dict[str, Any]:
        return self._build_dynamic_plan(seed_text, chapter, context, feedback)

    def _revise_plan_with_feedback(
        self,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],
        base_plan: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any] | None:
        try:
            client = self.build_client()
            pack = self.context_manager.build_writer_pack(context)
            system_prompt = "你是小说章节规划助手，只输出 JSON。请基于既有章节上下文和用户反馈，返回修订后的本章计划。"
            prompt = (
                f"请修订第{chapter}章计划，严格输出 JSON 对象，字段必须包含：chapter,title,goal,conflict,hook,emotion_arc,notes,contract。"
                f"contract 内字段：required_beats,forbidden_moves,continuity_checks,evaluation_focus,emotion_target,payoff_points,hook_goal,min_words,target_words,max_words。\n\n"
                f"[用户方向]\n{seed_text}\n\n"
                f"[用户反馈]\n{feedback}\n\n"
                f"[当前计划]\n{json.dumps(base_plan, ensure_ascii=False)}\n\n"
                f"{pack.summary_block or ''}"
            )
            raw = client.complete(system_prompt, prompt, temperature=0.4)
            data = json.loads(raw)
            plan = chapter_plan_to_dict(dict_to_chapter_plan(data))
            plan["notes"] = (str(plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
            return plan
        except Exception:
            return None

    def effective_planning_tier(self) -> str:
        meta = self.store.run_meta.load()
        explicit_tier = normalize_planning_tier(meta.planning_tier if meta else "")
        if explicit_tier:
            return explicit_tier
        progress = self.store.progress.load()
        layered = self.store.outline.load_layered_outline()
        compass = self.store.outline.load_compass()
        return infer_planning_tier(progress, has_layered_outline=bool(layered), has_compass=compass is not None)
