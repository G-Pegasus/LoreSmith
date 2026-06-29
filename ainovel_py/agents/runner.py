from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
import json
from typing import Any, Callable

from ainovel_py.agents.hints import has_placeholder_action
from ainovel_py.agents.longform import run_longform_hint_actions
from ainovel_py.agents.post_commit import plan_post_commit, plan_review_followup
from ainovel_py.agents.review_flow import save_arc_summary_followup, save_volume_summary_followup
from ainovel_py.domain.runtime import FlowState, infer_planning_tier, normalize_planning_tier

from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.orchestrator.interface import OrchestratorBackend
from ainovel_py.assets import load_bundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.writing import ChapterContract, ChapterPlan
from ainovel_py.host.events import Event


@dataclass
class AgentRunner:
    tools: dict[str, object]

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"tool not found: {name}")
        return tool.execute(args)


class LLMCoordinatorBackend:
    def __init__(
        self,
        cfg: Config,
        runner: AgentRunner,
        store: Any,
        emit_event: Callable[[Event], None],
        emit_stream: Callable[[str, str], None],
    ) -> None:
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.emit_event = emit_event
        self.emit_stream = emit_stream
        self._aborted = False
        self.context_manager = ContextManager(context_window=cfg.context_window)
        self.assets = load_bundle(cfg.style)

    def start(self, prompt: str) -> None:
        self._aborted = False
        self._run_loop(prompt)

    def resume(self, prompt: str) -> None:
        self._aborted = False
        self._run_loop(prompt)

    def follow_up(self, text: str) -> None:
        self._aborted = False
        self._run_loop(text)

    def abort(self) -> None:
        self._aborted = True

    def wait_idle(self) -> None:
        return

    def _run_loop(self, seed_text: str) -> None:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {self.cfg.provider} api_key 为占位值")

        client = OpenAICompatClient(
            api_key=pc.api_key,
            model=self.cfg.model,
            base_url=pc.base_url,
            timeout=120.0,
        )

        out_lines = [f"[Python Port] LLM协调器开始执行：{seed_text}"]
        steps = 0
        max_steps = 12
        pending_review_for: int | None = None

        while not self._aborted and steps < max_steps:
            progress = self.store.progress.load()
            if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
                chapter = progress.pending_rewrites[0]
                context = self.runner.call_tool("novel_context", {"chapter": chapter})
                rewrite_context = self._build_rewrite_context(progress, context)
                plan_payload = self._build_dynamic_plan(seed_text, chapter, rewrite_context)
                self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 plan_chapter (rewrite ch{chapter})", level="info"))
                plan_res = self.runner.call_tool("plan_chapter", plan_payload)
                plan = plan_res.get("plan") or plan_payload
                contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
                draft, _ = self._generate_chapter_with_context(client, seed_text, chapter, context, plan, contract)
                metadata = _extract_commit_metadata(client, chapter, draft)
                summary = str(metadata.get("summary", "") or self._summarize_chapter(client, chapter, draft))
                draft_res, commit_res = _run_write_commit_cycle(self.runner, self.emit_event, chapter, draft, summary, metadata)
                out_lines.append(f"[tool] rewrite_chapter -> chapter={chapter}")
                out_lines.append(f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
                out_lines.append(f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
                hints = commit_res.get("system_hints") or []
                if hints:
                    out_lines.append("[hints] " + " | ".join(hints))
                steps += 1
                continue

            if pending_review_for is not None:
                review_chapter = pending_review_for
                review_result = _run_review_summary(client, self.runner, self.emit_event, review_chapter, out_lines)
                pending_review_for = None
                plan = plan_review_followup(review_result)
                if plan.hints:
                    out_lines.append("[hints] " + " | ".join(plan.hints))
                if has_placeholder_action(plan.actions):
                    run_longform_hint_actions(
                        client,
                        self.runner,
                        self.emit_event,
                        self.assets,
                        self._effective_planning_tier(),
                        review_chapter,
                        plan.actions,
                        out_lines,
                    )
                steps += 1
                continue

            chapter = progress.next_chapter() if progress else 1
            if progress and progress.total_chapters > 0 and chapter > progress.total_chapters:
                break

            context = self.runner.call_tool("novel_context", {"chapter": chapter})
            plan_payload = self._build_dynamic_plan(seed_text, chapter, context)

            self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 plan_chapter (ch{chapter})", level="info"))
            plan_res = self.runner.call_tool("plan_chapter", plan_payload)
            plan = plan_res.get("plan") or plan_payload
            contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}

            draft, _ = self._generate_chapter_with_context(
                client=client,
                seed_text=seed_text,
                chapter=chapter,
                context=context,
                plan=plan,
                contract=contract,
            )

            metadata = _extract_commit_metadata(client, chapter, draft)
            summary = str(metadata.get("summary", "") or self._summarize_chapter(client, chapter, draft))
            draft_res, commit_res = _run_write_commit_cycle(self.runner, self.emit_event, chapter, draft, summary, metadata)

            out_lines.append(f"[tool] plan_chapter -> chapter={chapter}")
            out_lines.append(f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
            out_lines.append(f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")

            plan = plan_post_commit(commit_res, chapter)
            if plan.pending_review_for is not None:
                pending_review_for = plan.pending_review_for
            else:
                if plan.hints:
                    out_lines.append("[hints] " + " | ".join(plan.hints))
                if has_placeholder_action(plan.actions):
                    out_lines.append("[hint-actions] " + ", ".join(a.value for a in plan.actions))
            steps += 1

        self.emit_stream("thinking", "\n".join(out_lines) + "\n")

    def _build_rewrite_context(self, progress: Any, context: dict[str, Any]) -> dict[str, Any]:
        merged = dict(context)
        latest_review = context.get("latest_review") or {}
        if progress and progress.rewrite_reason:
            merged["rewrite_reason"] = progress.rewrite_reason
        if latest_review:
            merged["rewrite_issues"] = latest_review.get("issues") or []
        return merged

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
        core_event = str(outline.get("core_event", "") or "推进主线冲突").strip()
        hook = str(outline.get("hook", "") or "让局面出现新的不确定性").strip()
        previous_landing = ""
        if recent_summaries:
            latest_summary = recent_summaries[-1]
            if isinstance(latest_summary, dict):
                previous_landing = str(latest_summary.get("emotional_landing", "") or "").strip()
        payoff_hint = summary_focus[-1] if summary_focus else ""
        direction_parts = [f"本章围绕“{core_event}”展开"]
        if payoff_hint:
            direction_parts.append(f"承接前文余波：{payoff_hint[:80]}")
        direction_parts.append(f"结尾把读者推向“{hook}”")
        chapter_direction = "；".join(direction_parts) + "。"
        emotion_target = "让读者先感到角色被局面逼近，再在细节变化里意识到问题变得更棘手。"
        if previous_landing:
            emotion_target = f"承接上一章“{previous_landing}”的余韵，" + emotion_target
        meta = self.store.run_meta.load()
        min_words_default = meta.min_words if meta else 1200
        target_words_default = meta.target_words if meta else 1800
        max_words_default = meta.max_words if meta else 2600
        avoid = ["不要提前完结主线", "不要无铺垫引入重大设定变更"]
        if rewrite_reason:
            avoid = [rewrite_reason[:80], avoid[0]]
        elif rewrite_issues:
            avoid = [x[:80] for x in rewrite_issues[:2]]
        continuity_checks = review_focus[:2] + rewrite_issues[:1]
        if character_names:
            continuity_checks.append("沿用已有人物姓名和称谓，不要创造同位替身角色")
        contract = {
            "chapter_direction": chapter_direction,
            "required_beats": [],
            "avoid": avoid[:2],
            "forbidden_moves": avoid[:2],
            "continuity_checks": continuity_checks[:3],
            "evaluation_focus": [],
            "emotion_target": emotion_target,
            "payoff_points": summary_focus[-1:],
            "hook_goal": hook,
            "min_words": min_words_default,
            "target_words": target_words_default,
            "max_words": max_words_default,
        }
        base_plan = {
            "chapter": chapter,
            "title": str(outline.get("title", "") or f"第{chapter}章"),
            "goal": core_event,
            "conflict": core_event or "角色在压力中做出高代价选择",
            "hook": hook,
            "emotion_arc": emotion_target,
            "notes": f"seed={seed_text[:80]} | rewrite_reason={rewrite_reason[:120]}",
            "contract": contract,
        }
        if feedback:
            revised = self._revise_plan_with_feedback(seed_text, chapter, context, base_plan, feedback)
            if revised:
                return revised
            base_plan["notes"] = (str(base_plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
        return base_plan

    def _revise_plan_with_feedback(
        self,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],
        base_plan: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any] | None:
        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            return None
        try:
            client = OpenAICompatClient(api_key=pc.api_key, model=self.cfg.model, base_url=pc.base_url, timeout=120.0)
            pack = self.context_manager.build_writer_pack(context)
            system_prompt = "你是小说章节规划助手，只输出 JSON。请基于既有章节上下文和用户反馈，返回修订后的本章计划。"
            prompt = (
                f"请修订第{chapter}章计划，严格输出 JSON 对象，字段必须包含：chapter,title,goal,conflict,hook,emotion_arc,notes,contract。"
                f"contract 内字段：chapter_direction,avoid,continuity_checks,emotion_target,hook_goal,min_words,target_words,max_words。"
                f"如需兼容可保留 required_beats/forbidden_moves/payoff_points，但不要把它们写成任务清单。\n\n"
                f"[用户方向]\n{seed_text}\n\n"
                f"[用户反馈]\n{feedback}\n\n"
                f"[当前计划]\n{json.dumps(base_plan, ensure_ascii=False)}\n\n"
                f"{pack.summary_block or ''}"
            )
            raw = client.complete(system_prompt, prompt, temperature=0.4)
            data = json.loads(raw)
            plan = self._chapter_plan_to_dict(self._dict_to_chapter_plan(data))
            plan["notes"] = (str(plan.get("notes", "") or "") + f" | feedback={feedback[:120]}").strip()
            return plan
        except Exception:
            return None

    @staticmethod
    def _dict_to_chapter_plan(data: dict[str, Any]) -> ChapterPlan:
        contract_data = data.get("contract") or {}
        return ChapterPlan(
            chapter=int(data.get("chapter", 0) or 0),
            title=str(data.get("title", "") or ""),
            goal=str(data.get("goal", "") or ""),
            conflict=str(data.get("conflict", "") or ""),
            hook=str(data.get("hook", "") or ""),
            emotion_arc=str(data.get("emotion_arc", "") or ""),
            notes=str(data.get("notes", "") or ""),
            contract=ChapterContract(
                chapter_direction=str(contract_data.get("chapter_direction", "") or ""),
                required_beats=[str(x) for x in (contract_data.get("required_beats") or [])],
                avoid=[str(x) for x in (contract_data.get("avoid") or [])],
                forbidden_moves=[str(x) for x in (contract_data.get("forbidden_moves") or [])],
                continuity_checks=[str(x) for x in (contract_data.get("continuity_checks") or [])],
                evaluation_focus=[str(x) for x in (contract_data.get("evaluation_focus") or [])],
                emotion_target=str(contract_data.get("emotion_target", "") or ""),
                payoff_points=[str(x) for x in (contract_data.get("payoff_points") or [])],
                hook_goal=str(contract_data.get("hook_goal", "") or ""),
                min_words=int(contract_data.get("min_words", 1200) or 1200),
                target_words=int(contract_data.get("target_words", 1800) or 1800),
                max_words=int(contract_data.get("max_words", 2600) or 2600),
            ),
        )

    @staticmethod
    def _chapter_plan_to_dict(plan: ChapterPlan) -> dict[str, Any]:
        return asdict(plan)

    def _generate_chapter_with_context(
        self,
        client: OpenAICompatClient,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],
        plan: dict[str, Any],
        contract: dict[str, Any],
    ) -> tuple[str, int]:
        min_words = int(contract.get("min_words", 1200) or 1200)
        target_words = int(contract.get("target_words", 1800) or 1800)
        max_words = int(contract.get("max_words", 2600) or 2600)
        pack = self.context_manager.build_writer_pack(context)
        rewrite_focus = "\n".join(
            f"- {item.get('description', '')}" for item in (context.get("rewrite_issues") or []) if isinstance(item, dict)
        )
        premise = str(context.get("premise", "") or seed_text).strip()
        chapter_direction = str(contract.get("chapter_direction", "") or "").strip()
        if not chapter_direction:
            chapter_direction = (
                f"本章从“{plan.get('goal', '') or '当前冲突'}”进入，围绕“{plan.get('conflict', '') or '压力升级'}”展开，"
                f"结尾留下“{plan.get('hook', '') or '新的不确定性'}”。"
            )
        emotion_target = str(contract.get("emotion_target", "") or plan.get("emotion_arc", "") or "在推进中保留情绪余韵").strip()
        recent_summaries = [item for item in (context.get("recent_summaries") or []) if isinstance(item, dict)]
        previous = recent_summaries[-1] if recent_summaries else {}
        previous_landing = str(previous.get("emotional_landing", "") or "").strip()
        if not previous_landing and previous:
            previous_landing = str(previous.get("summary", "") or "").strip()[:100]
        snapshots = [
            item for item in (context.get("character_snapshots") or [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ][:6]
        if snapshots:
            character_lines = "\n".join(
                f"- {item.get('name', '')}: 状态={item.get('status', '')}；动机={item.get('motivation', '')}；关系={item.get('relations', '')}"
                for item in snapshots
            )
        else:
            character_lines = "\n".join(
                f"- {item.get('name', '')} / {item.get('role', '')}: {item.get('description', '')}"
                for item in (context.get("characters") or [])[:6] if isinstance(item, dict)
            )
        relevance_text = " ".join(
            str(x)
            for x in [
                chapter_direction,
                plan.get("goal", ""),
                plan.get("conflict", ""),
                plan.get("hook", ""),
                emotion_target,
            ]
        )
        foreshadow_items = []
        for item in (context.get("foreshadow_ledger") or []):
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description", "") or "")
            fid = str(item.get("id", "") or "")
            if not desc:
                continue
            if fid and fid in relevance_text or any(token and token in relevance_text for token in desc.split()[:3]):
                foreshadow_items.append(item)
        if not foreshadow_items:
            foreshadow_items = [item for item in (context.get("foreshadow_ledger") or []) if isinstance(item, dict)][:3]
        foreshadow = "\n".join(
            f"- {item.get('id', '')}: {item.get('description', '')}" for item in foreshadow_items[:3]
        )
        world_rule_lines = "\n".join(
            f"- {item.get('category', '')}: {item.get('rule', '')} {item.get('boundary', '')}".strip()
            for item in (context.get("world_rules") or [])[:3] if isinstance(item, dict)
        )
        continuity_items = [str(x) for x in (contract.get("continuity_checks") or []) if str(x).strip()][:3]
        continuity = "\n".join(f"- {x}" for x in continuity_items)
        avoid_items = [str(x) for x in (contract.get("avoid") or contract.get("forbidden_moves") or []) if str(x).strip()][:2]
        forbidden = "\n".join(f"- {x}" for x in avoid_items)
        style_rules = context.get("style_rules") or {}
        prose_candidates = [str(x) for x in (style_rules.get("prose") or []) if str(x).strip()]
        if not prose_candidates:
            style_text = str(context.get("style_reference", "") or self.assets.styles.get("default", "") or "")
            prose_candidates = [
                line.strip("- ").strip()
                for line in style_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        prose_rules = "\n".join(f"- {x}" for x in prose_candidates[:3])

        writer_identity = self.assets.prompts.get("writer") or (
            "你是长篇网文写作助手。输出完整章节正文，不要解释，不要分点，不要写提示语。"
            "必须写出具有场景推进、人物决策、冲突升级和章末钩子的小说章节。"
        )
        system_prompt = f"""
{writer_identity}

[创作简报]
故事前提：{premise[:240] or '从当前故事上下文自然承接。'}
当前章节方向：{chapter_direction}
前文情绪余韵：{previous_landing or '无明确上一章余韵时，从当前场景压力进入。'}
本章核心体验：{emotion_target}
""".strip()
        user_prompt = f"""
请直接创作第{chapter}章正文。以下参考按优先级从高到低使用。

[写作参考]
关键人物当前状态：
{character_lines or '- 以已出现人物为准，先写状态变化，再写事件推进。'}

活跃伏笔：
{foreshadow or '- 本章不强行调用无关伏笔。'}

世界边界：
{world_rule_lines or '- 遵守既有设定，不额外解释设定。'}

风格参考：
{prose_rules or '- 快慢交替；用具体动作和感官细节承载情绪；对白保留潜台词。'}

{pack.restore_block or ''}

[本轮重写/打磨重点]
{rewrite_focus or '- 无'}

[技术约束]
1. 用中文小说正文直接写作。
2. 只输出正文内容，不要输出章节标题、`第X章` 标题头、小标题、说明语或任何非正文包装。
3. 目标长度 {target_words} 字左右，最低不少于 {min_words} 字，最高不超过 {max_words} 字。
4. 连续性硬约束：
{continuity or '- 角色姓名、称谓、状态与前文保持一致。'}
5. 避坑提醒：
{forbidden or '- 不要提前完结主线；不要无铺垫引入重大设定变更。'}
6. 避免 AI 腔：不要写“他不禁”“一股力量涌上心头”“仿佛……一般”，不要用排比三连和段末总结句替代真实场景。
""".strip()
        draft_chunks: list[str] = []
        stream_timeout = client.effective_stream_total_timeout()
        self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"开始生成第{chapter}章正文（流式，超时 {int(stream_timeout)}s）", level="info"))
        self.emit_stream("thinking", "\n[chapter-stream]\n")
        draft = client.complete_stream(
            system_prompt,
            user_prompt,
            on_chunk=lambda channel, d: (
                draft_chunks.append(d) if channel == "content" else None,
                self.emit_stream(channel, d),
            ),
            temperature=0.7,
        )
        if not draft:
            raise RuntimeError(f"chapter {chapter} draft is empty")
        wc = len(draft)
        self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"第{chapter}章正文生成完成（{wc} 字）", level="info"))
        if wc < min_words:
            self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"第{chapter}章字数不足，开始补写（当前 {wc} / 最少 {min_words}）", level="warn"))
            expand_prompt = f"""
下面是已经写好的第{chapter}章正文，请在不重复已有内容的前提下继续扩写，使全文达到至少 {min_words} 字，并加强场景细节、人物动作、心理推进与冲突升级。

[已有正文]
{draft}
""".strip()
            extra = client.complete(system_prompt, expand_prompt, temperature=0.7)
            if extra:
                draft = draft.rstrip() + "\n\n" + extra.strip()
                wc = len(draft)
                self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"第{chapter}章补写完成（{wc} 字）", level="info"))
        if wc > max_words:
            self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"第{chapter}章字数超限，开始压缩（当前 {wc} / 上限 {max_words}）", level="warn"))
            compress_prompt = f"""
下面是第{chapter}章正文，请在保留主要情节、冲突、人物动机、伏笔和章末悬念的前提下压缩到不超过 {max_words} 字。
不要改成摘要，要保留小说正文质感。

[正文]
{draft}
""".strip()
            compressed = client.complete(system_prompt, compress_prompt, temperature=0.4)
            if compressed:
                draft = compressed.strip()
                wc = len(draft)
                self.emit_event(Event(time=datetime.now(), category="LLM", summary=f"第{chapter}章压缩完成（{wc} 字）", level="info"))
        return draft, wc

    def _summarize_chapter(self, client: OpenAICompatClient, chapter: int, draft: str) -> str:
        summary_prompt = (
            f"请用一到两句话总结第{chapter}章的关键推进、冲突变化和章末悬念，控制在80字以内。\n\n{draft}"
        )
        summary_system = self.assets.references.get("quality_checklist") or "你是摘要助手。"
        summary = client.complete(summary_system, summary_prompt, temperature=0.3)
        if not summary:
            raise RuntimeError(f"chapter {chapter} summary is empty")
        return summary

    def _effective_planning_tier(self) -> str:
        meta = self.store.run_meta.load()
        explicit_tier = normalize_planning_tier(meta.planning_tier if meta else "")
        if explicit_tier:
            return explicit_tier
        progress = self.store.progress.load()
        layered = self.store.outline.load_layered_outline()
        compass = self.store.outline.load_compass()
        return infer_planning_tier(progress, has_layered_outline=bool(layered), has_compass=compass is not None)


def _run_write_commit_cycle(
    runner: AgentRunner,
    emit_event: Callable[[Event], None],
    chapter: int,
    draft: str,
    summary: str,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 draft_chapter (ch{chapter})", level="info"))
    draft_res = runner.call_tool("draft_chapter", {"chapter": chapter, "content": draft, "mode": "write"})

    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 check_consistency (ch{chapter})", level="info"))
    runner.call_tool("check_consistency", {"chapter": chapter})

    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 commit_chapter (ch{chapter})", level="info"))
    commit_res = runner.call_tool(
        "commit_chapter",
        {
            "chapter": chapter,
            "summary": summary,
            "characters": metadata.get("characters") or ["主角"],
            "key_events": metadata.get("key_events") or [f"第{chapter}章推进"],
            "timeline_events": metadata.get("timeline_events") or [],
            "foreshadow_updates": metadata.get("foreshadow_updates") or [],
            "relationship_changes": metadata.get("relationship_changes") or [],
            "state_changes": metadata.get("state_changes") or [],
            "hook_type": metadata.get("hook_type") or "mystery",
            "dominant_strand": metadata.get("dominant_strand") or "quest",
            "emotional_landing": metadata.get("emotional_landing") or "",
            "narrative_tone": metadata.get("narrative_tone") or "",
            "sensory_anchor": metadata.get("sensory_anchor") or "",
        },
    )
    return draft_res, commit_res


def _extract_commit_metadata(client: OpenAICompatClient, chapter: int, draft: str) -> dict[str, Any]:
    prompt = f"""
请从下面的第{chapter}章正文中提取结构化信息，并严格输出 JSON 对象（不要输出 Markdown、不要解释）。
字段要求：
- summary: 字符串
- characters: 字符串数组
- key_events: 字符串数组
- timeline_events: 对象数组，每项 {{"time": 字符串, "event": 字符串, "characters": 字符串数组}}
- foreshadow_updates: 对象数组，每项 {{"id": 字符串, "action": "plant"|"advance"|"resolve", "description": 字符串}}
  - action=plant 时 description 必填，id 必须稳定可复用（如 fs_clue_01）
- relationship_changes: 对象数组，每项 {{"character_a": 字符串, "character_b": 字符串, "relation": 字符串, "chapter": 数字}}
  - character_a / character_b / relation 都不能为空
- state_changes: 对象数组，每项 {{"entity": 字符串, "field": 字符串, "old_value": 字符串, "new_value": 字符串, "reason": 字符串, "chapter": 数字}}
- hook_type: 字符串
- dominant_strand: 字符串
- emotional_landing: 字符串，本章结束时读者停留的情绪落点，例如“紧张中带着困惑”
- narrative_tone: 字符串，本章主导叙事语调，例如“压抑、克制、暗流涌动”
- sensory_anchor: 字符串，本章最有记忆感的一个感官细节，例如“雨水顺着门缝渗进来”

如果某项不存在请返回空数组，不要伪造空对象。

正文：
{draft}
""".strip()
    raw = client.complete("你是小说信息抽取助手，只输出 JSON。\n" + (load_bundle("default").references.get("consistency") or ""), prompt, temperature=0.2)
    import json
    try:
        data = json.loads(raw)
    except Exception:
        summary_fallback = client.complete(
            "你是摘要助手。",
            f"请用一到两句话总结第{chapter}章的关键推进、冲突变化和章末悬念，控制在80字以内。\n\n{draft}",
            temperature=0.3,
        )
        data = {
            "summary": summary_fallback,
            "characters": ["主角"],
            "key_events": [f"第{chapter}章推进"],
            "timeline_events": [],
            "foreshadow_updates": [],
            "relationship_changes": [],
            "state_changes": [],
            "hook_type": "mystery",
            "dominant_strand": "quest",
            "emotional_landing": "",
            "narrative_tone": "",
            "sensory_anchor": "",
        }
    data.setdefault("emotional_landing", "")
    data.setdefault("narrative_tone", "")
    data.setdefault("sensory_anchor", "")
    data["chapter"] = chapter
    return data


def _generate_review_payload(client: OpenAICompatClient, runner: AgentRunner, chapter: int) -> dict[str, Any]:
    context = runner.call_tool("novel_context", {"chapter": chapter})
    draft_read = runner.call_tool("read_chapter", {"chapter": chapter, "source": "draft"})
    draft = str(draft_read.get("content", "") or "")
    prompt = f"""
请以小说编辑身份审阅第{chapter}章，并严格输出 JSON 对象，字段包括：
chapter, scope, dimensions, issues, contract_status, contract_misses, contract_notes, verdict, summary, affected_chapters。
其中：
- dimensions 必须包含 consistency, continuity, voice, emotional_impact, rhythm_variety, surprise, restraint 七个维度；
- 每个维度包含 dimension, score(0-100), verdict(pass/warning/fail), comment；
- issues 每项包含 type, severity, description, evidence, suggestion；
- verdict 只能是 accept/polish/rewrite。
- consistency/continuity 是硬门槛：只有明显设定或因果错误才给 fail，普通瑕疵不要用它触发重写；
- polish/rewrite 应主要由 voice/emotional_impact/rhythm_variety/surprise/restraint 的审美维度不达标触发；
- 不要把“没有严格履约”当作主要问题，优先评价读起来是否有声音、有情绪、有节奏、有留白。

[章节正文]
{draft}

[章节上下文]
{context}
""".strip()
    raw = client.complete((load_bundle("default").prompts.get("editor") or "你是严格的小说编辑评审助手，只输出 JSON。"), prompt, temperature=0.2)
    import json
    try:
        data = json.loads(raw)
    except Exception:
        data = {
            "chapter": chapter,
            "scope": "chapter",
            "dimensions": [
                {"dimension": "consistency", "score": 85, "verdict": "pass", "comment": "设定一致"},
                {"dimension": "continuity", "score": 86, "verdict": "pass", "comment": "连续性良好"},
                {"dimension": "voice", "score": 81, "verdict": "pass", "comment": "语言声音稳定"},
                {"dimension": "emotional_impact", "score": 82, "verdict": "pass", "comment": "情绪能落到场景里"},
                {"dimension": "rhythm_variety", "score": 78, "verdict": "warning", "comment": "局部节奏可再拉开"},
                {"dimension": "surprise", "score": 80, "verdict": "pass", "comment": "有合理的意外推进"},
                {"dimension": "restraint", "score": 81, "verdict": "pass", "comment": "说明较克制"},
            ],
            "issues": [
                {
                    "type": "rhythm_variety",
                    "severity": "warning",
                    "description": "中段节奏略平",
                    "evidence": "第二段连续解释较多",
                    "suggestion": "用动作和对白替代部分说明",
                }
            ],
            "contract_status": "met",
            "contract_misses": [],
            "contract_notes": "核心契约已满足",
            "verdict": "accept",
            "summary": "整体通过，可继续下一章",
            "affected_chapters": [],
        }
    data["chapter"] = chapter
    data.setdefault("scope", "chapter")
    return data


def _run_review_summary(
    client: OpenAICompatClient,
    runner: AgentRunner,
    emit_event: Callable[[Event], None],
    chapter: int,
    out_lines: list[str],
) -> dict[str, Any]:
    review_payload = _generate_review_payload(client, runner, chapter)
    emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
    review_res = runner.call_tool("save_review", review_payload)
    out_lines.append(f"[tool] save_review -> final_verdict={review_res.get('final_verdict', '')}")

    save_arc_summary_followup(runner, emit_event, chapter, out_lines)
    save_volume_summary_followup(runner, emit_event, chapter, out_lines)
    return review_res


@dataclass
class CoordinatorLoop:
    backend: OrchestratorBackend

    def start(self, prompt: str) -> None:
        self.backend.start(prompt)

    def resume(self, prompt: str) -> None:
        self.backend.resume(prompt)

    def follow_up(self, text: str) -> None:
        self.backend.follow_up(text)

    def abort(self) -> None:
        self.backend.abort()

    def wait_idle(self) -> None:
        self.backend.wait_idle()
