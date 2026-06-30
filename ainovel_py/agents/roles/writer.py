from __future__ import annotations

from datetime import datetime
from typing import Any

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.host.events import Event

from .base import BaseAgent


class WriterAgent(BaseAgent):
    name = "writer"

    def system_prompt(self) -> str:
        return self.assets.prompts.get("writer") or (
            "你是长篇网文写作助手。输出完整章节正文，不要解释，不要分点，不要写提示语。"
            "必须写出具有场景推进、人物决策、冲突升级和章末钩子的小说章节。"
        )

    def execute(self, *, seed_text: str, chapter: int, context: dict[str, Any], plan: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
        client = self.build_client()
        draft, wc = self._generate_chapter_with_context(client, seed_text, chapter, context, plan, contract)
        summary = self._summarize_chapter(client, chapter, draft)
        return {"draft": draft, "word_count": wc, "summary": summary, "chapter": chapter}

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
        recent = "\n".join(
            f"- 第{item.get('chapter')}: {item.get('summary', '')}" for item in (context.get("recent_summaries") or []) if isinstance(item, dict)
        )
        review_focus = "\n".join(
            f"- {item.get('description', '')}" for item in ((context.get("latest_review") or {}).get("issues") or []) if isinstance(item, dict)
        )
        rewrite_focus = "\n".join(
            f"- {item.get('description', '')}" for item in (context.get("rewrite_issues") or []) if isinstance(item, dict)
        )
        foreshadow = "\n".join(
            f"- {item.get('id', '')}: {item.get('description', '')}" for item in (context.get("foreshadow_ledger") or [])[:6] if isinstance(item, dict)
        )
        character_lines = "\n".join(
            f"- {item.get('name', '')} / {item.get('role', '')}: {item.get('description', '')}" for item in (context.get("characters") or [])[:8] if isinstance(item, dict)
        )
        world_rule_lines = "\n".join(
            f"- {item.get('category', '')}: {item.get('rule', '')} {item.get('boundary', '')}".strip()
            for item in (context.get("world_rules") or [])[:8] if isinstance(item, dict)
        )
        continuity = "\n".join(f"- {x}" for x in (contract.get("continuity_checks") or []))
        required_beats = "\n".join(f"- {x}" for x in (contract.get("required_beats") or []))
        forbidden = "\n".join(f"- {x}" for x in (contract.get("forbidden_moves") or []))
        payoff = "\n".join(f"- {x}" for x in (contract.get("payoff_points") or []))
        style_rules = context.get("style_rules") or {}
        prose_rules = "\n".join(f"- {x}" for x in (style_rules.get("prose") or []))

        system_prompt = self.system_prompt()
        user_prompt = f"""
基于以下信息创作第{chapter}章正文。

[用户方向]
{seed_text}

{pack.summary_block or ''}

[本章计划]
标题：{plan.get('title', '')}
目标：{plan.get('goal', '')}
冲突：{plan.get('conflict', '')}
钩子：{plan.get('hook', '')}
情绪曲线：{plan.get('emotion_arc', '')}

[必须完成]
{required_beats or '- 推进主线'}

[禁止事项]
{forbidden or '- 不要提前完结主线'}

[连续性检查]
{continuity or '- 角色状态前后一致'}

[近期摘要]
{recent or '- 无'}

[最近评审关注]
{review_focus or '- 无'}

[本轮重写/打磨重点]
{rewrite_focus or '- 无'}

[主要人物]
{character_lines or '- 无'}

[世界规则]
{world_rule_lines or '- 无'}

[活跃伏笔]
{foreshadow or '- 无'}

[待兑现点]
{payoff or '- 无'}

[风格规则]
{prose_rules or '- 节奏紧凑，因果清晰，章末留钩子'}

{pack.restore_block or ''}

要求：
1. 用中文小说正文直接写作。
2. 只输出正文内容，不要输出章节标题、`第X章` 标题头、小标题、说明语或任何非正文包装。
3. 目标长度 {target_words} 字左右，最低不少于 {min_words} 字，最高不超过 {max_words} 字。
4. 章节内必须有明确场景推进，不要只是摘要式概述。
5. 章节要吸收最近评审提醒，避免重复问题。
6. 如果已提供人物名单，优先使用这些人物，名字必须保持一致，不要私自替换主角或额外创造同位角色。
7. 结尾必须形成强悬念或明确追读欲望。
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

    def generate_chapter_with_context(
        self,
        client: OpenAICompatClient,
        seed_text: str,
        chapter: int,
        context: dict[str, Any],
        plan: dict[str, Any],
        contract: dict[str, Any],
    ) -> tuple[str, int]:
        return self._generate_chapter_with_context(client, seed_text, chapter, context, plan, contract)

    def _summarize_chapter(self, client: OpenAICompatClient, chapter: int, draft: str) -> str:
        summary_prompt = (
            f"请用一到两句话总结第{chapter}章的关键推进、冲突变化和章末悬念，控制在80字以内。\n\n{draft}"
        )
        summary_system = self.assets.references.get("quality_checklist") or "你是摘要助手。"
        summary = client.complete(summary_system, summary_prompt, temperature=0.3)
        if not summary:
            raise RuntimeError(f"chapter {chapter} summary is empty")
        return summary

    def summarize_chapter(self, client: OpenAICompatClient, chapter: int, draft: str) -> str:
        return self._summarize_chapter(client, chapter, draft)
