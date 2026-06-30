from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

from ainovel_py.agents import CoordinatorLoop, build_coordinator_loop
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.build import build_tool_registry
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.runtime import Phase
from ainovel_py.domain.runtime_events import RuntimeQueueItem, RuntimeQueueKind, RuntimeQueuePriority
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event, StreamChunk, UISnapshot, build_start_prompt
from ainovel_py.host.resume import build_resume_prompt
from ainovel_py.store.store import Store


@dataclass
class _DummyAskUser:
    handler: object = None

    def set_handler(self, handler: object) -> None:
        self.handler = handler


class Host:
    def __init__(self, cfg: Config) -> None:
        cfg.fill_defaults()
        cfg.validate_base()
        self.cfg = cfg
        self.store = Store(cfg.output_dir)
        self.store.init()
        self.store.run_meta.init(cfg.style, cfg.provider, cfg.model)
        self.loop: CoordinatorLoop = build_coordinator_loop(
            self.cfg,
            self.store,
            emit_event=self._emit_event,
            emit_stream=self._emit_stream_chunk,
        )

        self.events: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self.stream_ch: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=256)
        self.clear_ch: asyncio.Queue[bool] = asyncio.Queue(maxsize=4)
        self.done_ch: asyncio.Queue[bool] = asyncio.Queue(maxsize=4)

        self.lifecycle = "idle"
        self.idle_resume_count = 0
        self._closed = False
        self._ask_user = _DummyAskUser()

    def dir(self) -> str:
        return self.store.dir()

    def report(self) -> dict[str, object]:
        progress = self.store.progress.load()
        latest_cp = self.store.checkpoints.latest_global()
        last_commit = self.store.signals.load_last_commit()
        pending_checkpoint = self.store.signals.load_pending_checkpoint()
        current_chapter = progress.current_chapter if progress else 0
        if pending_checkpoint is not None:
            current_chapter = pending_checkpoint.next_chapter
        return {
            "provider": self.cfg.provider,
            "model": self.cfg.model,
            "style": self.cfg.style,
            "lifecycle": self.lifecycle,
            "output_dir": self.store.dir(),
            "completed_chapters": len(progress.completed_chapters) if progress else 0,
            "current_chapter": current_chapter,
            "total_word_count": progress.total_word_count if progress else 0,
            "flow": progress.flow if progress else "",
            "phase": progress.phase if progress else "",
            "latest_checkpoint": {
                "step": latest_cp.step,
                "scope": latest_cp.scope.kind,
                "seq": latest_cp.seq,
            }
            if latest_cp
            else None,
            "has_last_commit": bool(last_commit),
            "awaiting_confirmation": self._pending_checkpoint_payload(pending_checkpoint),
        }

    def ask_user(self) -> _DummyAskUser:
        return self._ask_user

    def configured_providers(self) -> list[str]:
        return sorted(self.cfg.providers.keys())

    def configured_models(self, provider: str) -> list[str]:
        return self.cfg.candidate_models(provider)

    def current_model_selection(self, role: str = "default") -> tuple[str, str, bool]:
        if role and role != "default":
            rc = self.cfg.roles.get(role)
            if rc:
                return rc.provider, rc.model, True
        return self.cfg.provider, self.cfg.model, False

    def co_create_reply(self, history: list[dict[str, str]], on_delta=None) -> dict[str, object]:
        user_text = "\n".join(
            item.get("content", "") for item in history if item.get("role") == "user"
        ).strip()
        if not user_text:
            raise ValueError("co-create history is empty")

        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise ValueError("provider api_key 未配置")
        client = OpenAICompatClient(api_key=pc.api_key, model=self.cfg.model, base_url=pc.base_url, timeout=120.0)
        from ainovel_py.assets import load_bundle
        bundle = load_bundle(self.cfg.style)
        prompt = bundle.prompts.get("coordinator") or (
            "你在进行小说共创规划。请先给用户一段简短回复，再提供一段可直接开始写作的创作 prompt。"
            "输出格式必须为 JSON: {\"message\": string, \"prompt\": string, \"ready\": bool}。"
        )
        user_prompt = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history)
        raw = client.complete_stream(prompt, user_prompt, on_delta=on_delta, temperature=0.6)
        if not (raw or "").strip():
            raw = client.complete(prompt, user_prompt, temperature=0.6)
        try:
            data = self._extract_json_object(raw)
            return {
                "message": str(data.get("message", "") or ""),
                "prompt": str(data.get("prompt", "") or ""),
                "ready": bool(data.get("ready", False)),
            }
        except ValueError:
            text = (raw or "").strip()
            if not text:
                raise RuntimeError("assistant reply is empty")
            return {
                "message": text,
                "prompt": "",
                "ready": False,
            }

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, object]:
        text = (raw or "").strip()
        if not text:
            raise ValueError("empty co-create reply")
        candidates = [text]
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                fence_body = "\n".join(lines[1:-1]).strip()
                if fence_body:
                    candidates.insert(0, fence_body)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        raise ValueError("co-create reply is not valid JSON")

    def switch_model(self, role: str, provider: str, model: str) -> None:
        if not provider or not model:
            raise ValueError("provider and model are required")
        if provider not in self.cfg.providers:
            raise ValueError(f"provider {provider} is not configured")
        if role and role != "default":
            rc = self.cfg.roles.get(role)
            if rc is None:
                raise ValueError(f"role {role} is not configured")
            rc.provider = provider
            rc.model = model
            self.cfg.roles[role] = rc
        else:
            self.cfg.provider = provider
            self.cfg.model = model

        self.loop = build_coordinator_loop(
            self.cfg,
            self.store,
            emit_event=self._emit_event,
            emit_stream=self._emit_stream_chunk,
        )
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"模型已切换：{role or 'default'} -> {provider}/{model}", level="info"))

    def snapshot(self) -> UISnapshot:
        progress = self.store.progress.load()
        meta = self.store.run_meta.load()
        snap = UISnapshot(
            provider=self.cfg.provider,
            model_name=self.cfg.model,
            style=self.cfg.style,
            runtime_state=self.lifecycle,
            status_label=self._derive_status_label(progress),
            backend=f"llm/langgraph",
            context_window=self.cfg.context_window,
        )
        if progress:
            snap.phase = progress.phase
            snap.flow = progress.flow
            snap.current_chapter = progress.current_chapter
            snap.total_chapters = progress.total_chapters
            snap.completed_count = len(progress.completed_chapters)
            snap.total_word_count = progress.total_word_count
            snap.pending_rewrites = list(progress.pending_rewrites)
            snap.rewrite_reason = progress.rewrite_reason
        if meta:
            snap.pending_steer = meta.pending_steer

        premise = self.store.outline.load_premise()
        if premise:
            snap.premise = premise[:240]
        snap.outline = [
            {"chapter": item.chapter, "title": item.title, "core_event": item.core_event}
            for item in self.store.outline.load_outline()[:8]
        ]
        snap.characters = [
            f"{c.name}（{c.role}）" if c.role else c.name
            for c in self.store.characters.load()[:12]
        ]
        if progress and progress.completed_chapters:
            for ch in progress.completed_chapters[-3:]:
                summary = self.store.summaries.load_summary(ch)
                if summary:
                    snap.recent_summaries.append(f"第{ch}章: {summary.summary[:80]}")
            review = self.store.world.load_review(progress.completed_chapters[-1])
            if review:
                snap.last_review_summary = f"{review.verdict}: {review.summary[:80]}"

        if progress:
            approx_tokens = max(progress.total_word_count // 2, 0)
            snap.context_tokens = approx_tokens
            if self.cfg.context_window > 0:
                snap.context_percent = round((approx_tokens / self.cfg.context_window) * 100, 2)
        snap.agent_status = ["coordinator: ready", f"backend: llm/langgraph"]
        return snap

    def _derive_status_label(self, progress) -> str:
        if progress and progress.phase == Phase.COMPLETE:
            return "COMPLETE"
        if self.store.signals.load_pending_checkpoint() is not None:
            return "AWAITING_CONFIRMATION"
        if progress and progress.flow == "reviewing":
            return "REVIEW"
        if progress and progress.flow in {"rewriting", "polishing"}:
            return "REWRITE"
        if self.lifecycle == "running":
            return "RUNNING"
        return "READY"

    def replay_queue(self, after_seq: int) -> list[RuntimeQueueItem]:
        return self.store.runtime.load_queue_after(after_seq)

    def start(self, prompt: str) -> None:
        self.start_prepared(build_start_prompt(prompt))

    def start_prepared(self, prompt_text: str) -> None:
        if self.lifecycle == "running":
            raise ValueError("already running")
        text = prompt_text.strip()
        if not text:
            raise ValueError("prompt is required")

        self.store.runtime.reset()
        self.store.progress.init("", 0)
        self.store.signals.clear_pending_commit()
        self.store.signals.clear_stale_signals()
        self.store.checkpoints.reset()
        self.lifecycle = "running"
        self.idle_resume_count = 0

        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="开始创作", level="info"))
        self._emit_clear()
        self.loop.start(text)
        self.loop.wait_idle()
        self._mark_idle_or_complete()

    def resume(self) -> str:
        if self.lifecycle == "running":
            raise ValueError("already running")
        prompt, label = build_resume_prompt(self.store)
        if not label:
            return ""

        self.lifecycle = "running"
        self.idle_resume_count = 0
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"恢复创作: {label}", level="info"))
        self.loop.resume(prompt)
        self.loop.wait_idle()
        self._mark_idle_or_complete()
        return label

    def continue_run(self, text: str) -> None:
        content = text.strip()
        if not content:
            raise ValueError("text is required")

        if self.lifecycle != "running":
            self.lifecycle = "running"
        self.loop.follow_up(content)
        self.loop.wait_idle()
        self._mark_idle_or_complete()

    def steer(self, text: str) -> None:
        content = text.strip()
        if not content:
            return
        if self.lifecycle == "running":
            self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"干预已提交: {content[:40]}", level="info"))
            return
        self.store.run_meta.set_pending_steer(content)
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="干预已保存，下次启动时生效", level="info"))

    def abort(self) -> bool:
        if self.lifecycle != "running":
            return False
        self.lifecycle = "paused"
        self.loop.abort()
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="用户手动暂停当前创作", level="warn"))
        self._safe_put(self.done_ch, True)
        return True

    def close(self) -> None:
        self._closed = True

    def _mark_idle_or_complete(self) -> None:
        progress = self.store.progress.load()
        if progress and progress.phase == Phase.COMPLETE:
            self.lifecycle = "completed"
            self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="创作完成", level="success"))
        else:
            if self.store.signals.load_pending_checkpoint() is not None:
                self.lifecycle = "paused"
                self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="等待用户确认继续编写", level="info"))
            else:
                self.lifecycle = "idle"
                self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="Coordinator 停止", level="warn"))
        self._safe_put(self.done_ch, True)

    def _append_runtime_item(self, item: RuntimeQueueItem) -> None:
        self.store.runtime.append_queue(item)

    def _append_runtime_stream_chunk(self, channel: str, delta: str) -> None:
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.STREAM_CHUNK,
                priority=RuntimeQueuePriority.BACKGROUND,
                payload={"channel": channel, "delta": delta},
            )
        )

    def emit_checkpoint_pending(self, pending: PendingRunCheckpoint) -> None:
        payload = self._pending_checkpoint_payload(pending)
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.UI_EVENT,
                priority=RuntimeQueuePriority.CONTROL,
                category="RUN",
                summary=f"已完成第{pending.pause_after_chapter}章，等待用户确认继续",
                payload={"level": "info", "event": "run.awaiting_confirmation", "awaiting_confirmation": payload},
            )
        )
        self._safe_put(self.events, Event(time=datetime.now(), category="RUN", summary=f"已完成第{pending.pause_after_chapter}章，等待用户确认继续", level="info"))

    @staticmethod
    def _pending_checkpoint_payload(pending: PendingRunCheckpoint | None) -> dict[str, object] | None:
        if pending is None:
            return None
        return {
            "pause_after_chapter": pending.pause_after_chapter,
            "next_chapter": pending.next_chapter,
            "completed_count": pending.completed_count,
            "status": pending.status,
        }

    def _emit_event(self, ev: Event) -> None:
        self._safe_put(self.events, ev)
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.UI_EVENT,
                priority=RuntimeQueuePriority.BACKGROUND,
                category=ev.category,
                summary=ev.summary,
                payload={"level": ev.level},
            )
        )

    def _emit_delta(self, channel: str, delta: str) -> None:
        if not delta:
            return
        self._safe_put(self.stream_ch, StreamChunk(channel=channel, delta=delta))

    def _emit_stream_chunk(self, channel: str, text: str) -> None:
        channel_norm = (channel or "content").strip().lower()
        if channel_norm not in {"content", "thinking"}:
            channel_norm = "content"
        self._emit_delta(channel_norm, text)
        self._append_runtime_stream_chunk(channel_norm, text)

    def _emit_stream_text(self, text: str) -> None:
        self._emit_stream_chunk("content", text)

    def _emit_clear(self) -> None:
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.STREAM_CLEAR,
                priority=RuntimeQueuePriority.BACKGROUND,
                payload={},
            )
        )
        self._safe_put(self.clear_ch, True)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, value: object) -> None:
        try:
            queue.put_nowait(value)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(value)
            except Exception:
                pass
