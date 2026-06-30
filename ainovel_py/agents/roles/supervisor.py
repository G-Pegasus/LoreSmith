from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ainovel_py.host.events import Event

from .base import BaseAgent


@dataclass
class SupervisorDecision:
    next_agent: str
    reasoning: str
    task_instruction: str = ""


class SupervisorAgent(BaseAgent):
    name = "supervisor"

    def system_prompt(self) -> str:
        return (
            "你是小说创作流程的调度器。根据当前工作流状态，决定下一步应该调用哪个 Agent。\n"
            "可选的 Agent：\n"
            "- editor: 进行章节评审\n"
            "- rewrite: 进行章节重写\n"
            "- architect: 规划下一章\n"
            "- checkpoint: 检查点/流程控制\n"
            "- FINISH: 结束创作\n\n"
            "请输出 JSON：{\"next_agent\": \"...\", \"reasoning\": \"...\", \"task_instruction\": \"...\"}"
        )

    def execute(self, *, state: dict[str, Any]) -> dict[str, Any]:
        client = self.build_client()

        chapter = state.get("current_chapter", 0)
        commit_result = state.get("latest_commit_result") or {}
        review_result = state.get("latest_review_result") or {}
        hints = commit_result.get("system_hints") or []
        verdict = review_result.get("final_verdict") or ""

        context_summary = (
            f"当前章节: {chapter}\n"
            f"提交结果 hints: {hints}\n"
            f"评审结论: {verdict}\n"
            f"待处理动作: {state.get('pending_actions', [])}\n"
        )

        prompt = (
            f"当前工作流状态:\n{context_summary}\n"
            "请决定下一步应该调用哪个 Agent，输出 JSON。"
        )

        try:
            raw = client.complete(self.system_prompt(), prompt, temperature=0.2)
            data = json.loads(raw)
            decision = SupervisorDecision(
                next_agent=str(data.get("next_agent", "checkpoint")),
                reasoning=str(data.get("reasoning", "")),
                task_instruction=str(data.get("task_instruction", "")),
            )
            pending_action = self._map_agent_to_action(decision.next_agent)
        except Exception:
            decision = None
            pending_action = "checkpoint"

        self.emit_event(Event(
            time=datetime.now(),
            category="AGENT",
            summary=f"SupervisorAgent: next={pending_action}",
            level="info",
        ))

        return {
            "supervisor_decision": decision.__dict__ if decision else None,
            "pending_action": pending_action,
        }

    @staticmethod
    def _map_agent_to_action(agent_name: str) -> str:
        mapping = {
            "architect": "novel_context",
            "writer": "generate_draft",
            "editor": "review",
            "rewrite": "rewrite",
            "arc_summary": "arc_summary",
            "volume_summary": "volume_summary",
            "expand_arc": "expand_arc",
            "checkpoint": "checkpoint",
            "FINISH": "finish",
        }
        return mapping.get(agent_name, "checkpoint")
