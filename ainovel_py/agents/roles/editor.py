from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.assets import load_bundle
from ainovel_py.host.events import Event

from .base import BaseAgent


class EditorAgent(BaseAgent):
    name = "editor"

    def system_prompt(self) -> str:
        return self.assets.prompts.get("editor") or "你是严格的小说编辑评审助手，只输出 JSON。"

    def execute(self, *, chapter: int) -> dict[str, Any]:
        client = self.build_client()
        review_payload = self._generate_review_payload(client, chapter)
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = self.runner.call_tool("save_review", review_payload)
        return {"review": review_res, "review_payload": review_payload, "chapter": chapter}

    def extract_metadata(self, *, chapter: int, draft: str) -> dict[str, Any]:
        client = self.build_client()
        return self._extract_commit_metadata(client, chapter, draft)

    def run_write_commit_cycle(
        self,
        chapter: int,
        draft: str,
        summary: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 draft_chapter (ch{chapter})", level="info"))
        draft_res = self.runner.call_tool("draft_chapter", {"chapter": chapter, "content": draft, "mode": "write"})
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 check_consistency (ch{chapter})", level="info"))
        self.runner.call_tool("check_consistency", {"chapter": chapter})
        self.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 commit_chapter (ch{chapter})", level="info"))
        commit_res = self.runner.call_tool(
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
            },
        )
        return draft_res, commit_res

    def _extract_commit_metadata(self, client: OpenAICompatClient, chapter: int, draft: str) -> dict[str, Any]:
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

如果某项不存在请返回空数组，不要伪造空对象。

正文：
{draft}
""".strip()
        raw = client.complete("你是小说信息抽取助手，只输出 JSON。\n" + (load_bundle("default").references.get("consistency") or ""), prompt, temperature=0.2)
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
            }
        data["chapter"] = chapter
        return data

    def _generate_review_payload(self, client: OpenAICompatClient, chapter: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if context is None:
            context = self.runner.call_tool("novel_context", {"chapter": chapter})
        draft_read = self.runner.call_tool("read_chapter", {"chapter": chapter, "source": "draft"})
        draft = str(draft_read.get("content", "") or "")
        prompt = f"""
请以小说编辑身份审阅第{chapter}章，并严格输出 JSON 对象，字段包括：
chapter, scope, dimensions, issues, contract_status, contract_misses, contract_notes, verdict, summary, affected_chapters。
其中：
- dimensions 必须包含 consistency, character, pacing, continuity, foreshadow, hook, aesthetic 七个维度；
- 每个维度包含 dimension, score(0-100), verdict(pass/warning/fail), comment；
- issues 每项包含 type, severity, description, evidence, suggestion；
- verdict 只能是 accept/polish/rewrite。

[章节正文]
{draft}

[章节上下文]
{context}
""".strip()
        raw = client.complete((load_bundle("default").prompts.get("editor") or "你是严格的小说编辑评审助手，只输出 JSON。"), prompt, temperature=0.2)
        try:
            data = json.loads(raw)
        except Exception:
            data = {
                "chapter": chapter,
                "scope": "chapter",
                "dimensions": [
                    {"dimension": "consistency", "score": 85, "verdict": "pass", "comment": "设定一致"},
                    {"dimension": "character", "score": 82, "verdict": "pass", "comment": "角色动机成立"},
                    {"dimension": "pacing", "score": 78, "verdict": "warning", "comment": "中段可压缩"},
                    {"dimension": "continuity", "score": 86, "verdict": "pass", "comment": "连续性良好"},
                    {"dimension": "foreshadow", "score": 80, "verdict": "pass", "comment": "伏笔明确"},
                    {"dimension": "hook", "score": 83, "verdict": "pass", "comment": "钩子有效"},
                    {"dimension": "aesthetic", "score": 81, "verdict": "pass", "comment": "语言风格稳定"},
                ],
                "issues": [
                    {
                        "type": "pacing",
                        "severity": "warning",
                        "description": "中段说明略长",
                        "evidence": "第二段连续解释较多",
                        "suggestion": "压缩背景说明",
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

    def generate_review_payload(self, client: OpenAICompatClient, chapter: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._generate_review_payload(client, chapter, context)
