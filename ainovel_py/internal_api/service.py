from __future__ import annotations

from pathlib import Path
import uuid
from typing import Optional

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.bootstrap.configfile import load_config
from ainovel_py.domain.review import ForeshadowEntry
from ainovel_py.domain.story import Character
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.host import Host
from ainovel_py.internal_api.artifacts import ArtifactService
from ainovel_py.internal_api.dto import CreateRunRequest, InstructionRequest, ResumeRunRequest
from ainovel_py.internal_api.errors import ApiError
from ainovel_py.internal_api.registry import RunRegistry, RunSession
from ainovel_py.internal_api.tasks import RunTask
from ainovel_py.tools.parsers import parse_outline_entry, parse_relationship_entry, parse_timeline_event, parse_world_rule


class RunService:
    def __init__(self, registry: Optional[RunRegistry] = None, artifact_service: Optional[ArtifactService] = None) -> None:
        self.registry = registry or RunRegistry()
        self.artifact_service = artifact_service or ArtifactService()

    def create_run(self, req: CreateRunRequest) -> RunSession:
        existing = self.registry.get(req.run_id)
        if existing is not None:
            return existing
        prompt = (req.input.prompt or "").strip()
        if not prompt:
            raise ApiError("INVALID_ARGUMENT", "prompt is required", 400)
        cfg = self._build_config(req)
        host = Host(cfg)
        self._seed_story_context(host, req)
        session = RunSession(
            run_id=req.run_id,
            story_id=req.story.story_id or req.run_id,
            output_dir=cfg.output_dir,
            cfg=cfg,
            host=host,
            last_operation="create",
        )
        self.registry.put(session)
        self.registry.put_task(RunTask(task_id=str(uuid.uuid4()), run_id=req.run_id, op="start", payload={"prompt": prompt}))
        return session

    def get_run(self, run_id: str) -> RunSession:
        session = self.registry.get(run_id)
        if session is None:
            raise ApiError("RUN_NOT_FOUND", "run not found", 404, {"run_id": run_id})
        return session

    def resume_run(self, run_id: str, req: ResumeRunRequest) -> RunSession:
        session = self.get_run(run_id)
        prompt = (req.input.prompt or "").strip()
        decision = (req.decision or "").strip().lower()
        feedback = (req.feedback or "").strip()
        if session.is_busy():
            raise ApiError("CONFLICT", "run is busy", 409, {"run_id": run_id})
        pending_checkpoint = session.host.store.signals.load_pending_checkpoint()
        if pending_checkpoint is None:
            pending_checkpoint = self._recover_pending_checkpoint(session)
        session.last_operation = "resume"
        if session.state_override == "failed":
            session.state_override = ""
            session.last_error_code = ""
            session.last_error_message = ""
        self.registry.persist(session)
        if decision in {"approve", "continue"}:
            if pending_checkpoint is None:
                raise ApiError("RUN_CONFIRMATION_NOT_REQUIRED", "run does not require confirmation", 400)
            task = RunTask(task_id=str(uuid.uuid4()), run_id=run_id, op="continue", payload={"text": "__RUN_CONTINUE__"})
        elif decision == "reject":
            raise ApiError("INVALID_ARGUMENT", "reject is not supported for run checkpoint confirmation", 400)
        else:
            if pending_checkpoint is not None:
                raise ApiError("RUN_CONFIRMATION_REQUIRED", "run confirmation required before continuing", 400)
            task = RunTask(task_id=str(uuid.uuid4()), run_id=run_id, op="resume", payload={"prompt": prompt} if prompt else {})
        self.registry.put_task(task)
        return session

    def pause_run(self, run_id: str) -> RunSession:
        session = self.get_run(run_id)
        session.last_operation = "pause"
        session.host.abort()
        self.registry.persist(session)
        return session

    def _recover_pending_checkpoint(self, session: RunSession) -> PendingRunCheckpoint | None:
        progress = session.host.store.progress.load()
        if progress is None:
            return None
        completed = list(progress.completed_chapters or [])
        if not completed:
            return None
        completed_count = len(completed)
        current_chapter = int(progress.current_chapter or 0)
        if completed_count > 0 and completed_count % 5 == 0 and current_chapter == max(completed) + 1:
            pending = PendingRunCheckpoint(
                pause_after_chapter=max(completed),
                next_chapter=current_chapter,
                completed_count=completed_count,
            )
            session.host.store.signals.save_pending_checkpoint(pending)
            return pending
        return None

    def cancel_run(self, run_id: str) -> RunSession:
        session = self.get_run(run_id)
        session.last_operation = "cancel"
        session.host.abort()
        session.state_override = "canceled"
        for task in self.registry.list_tasks(run_id):
            if task.status in {"queued", "running"}:
                task.status = "canceled"
                self.registry.persist_task(task)
        self.registry.persist(session)
        return session

    def add_instruction(self, run_id: str, req: InstructionRequest) -> RunSession:
        session = self.get_run(run_id)
        instruction_type = (req.instruction.type or "follow_up").strip() or "follow_up"
        text = (req.instruction.text or "").strip()
        decision = (req.instruction.decision or "").strip().lower()
        feedback = (req.instruction.feedback or "").strip()
        if session.is_busy():
            raise ApiError("CONFLICT", "run is busy", 409, {"run_id": run_id})
        pending_checkpoint = session.host.store.signals.load_pending_checkpoint()
        session.last_operation = instruction_type
        self.registry.persist(session)
        if instruction_type == "steer":
            if not text:
                raise ApiError("INVALID_ARGUMENT", "instruction text is required", 400)
            session.host.steer(text)
            self.registry.persist(session)
        elif instruction_type in {"continue", "run_continue"} or decision in {"approve", "continue"}:
            if pending_checkpoint is None:
                raise ApiError("RUN_CONFIRMATION_NOT_REQUIRED", "run does not require confirmation", 400)
            self.registry.put_task(RunTask(task_id=str(uuid.uuid4()), run_id=run_id, op="continue", payload={"text": "__RUN_CONTINUE__"}))
        else:
            if pending_checkpoint is not None:
                raise ApiError("RUN_CONFIRMATION_REQUIRED", "run confirmation required before continuing", 400)
            if not text:
                raise ApiError("INVALID_ARGUMENT", "instruction text is required", 400)
            self.registry.put_task(RunTask(task_id=str(uuid.uuid4()), run_id=run_id, op="continue", payload={"text": text}))
        return session

    def list_runs(self, status: str = "", story_id: str = "") -> list[tuple[RunSession, dict[str, object]]]:
        out: list[tuple[RunSession, dict[str, object]]] = []
        for session in self.registry.list():
            if story_id and session.story_id != story_id:
                continue
            report = session.host.report()
            if status:
                lifecycle = str(report.get("lifecycle", "") or "idle")
                from ainovel_py.internal_api.mappers import map_product_status

                if map_product_status(session, lifecycle) != status:
                    continue
            out.append((session, report))
        return out

    def get_report(self, run_id: str) -> tuple[RunSession, dict[str, object]]:
        session = self.get_run(run_id)
        report = session.host.report()
        return session, report

    def get_events(self, run_id: str, after_seq: int, limit: int) -> tuple[RunSession, list, int]:
        session = self.get_run(run_id)
        items = session.host.replay_queue(after_seq)
        total = len(items)
        if limit > 0:
            return session, items[:limit], total
        return session, items, total

    def get_chapter(self, run_id: str, chapter_number: int) -> tuple[RunSession, dict[str, object]]:
        session = self.get_run(run_id)
        if chapter_number <= 0:
            raise ApiError("INVALID_ARGUMENT", "chapter_number must be positive", 400)
        store = session.host.store
        content = store.drafts.load_chapter_text(chapter_number)
        if not content:
            content = store.drafts.load_draft(chapter_number)
        if not content:
            raise ApiError("RUN_NOT_FOUND", "chapter not found", 404, {"chapter_number": chapter_number})
        outline = store.outline.get_chapter_outline(chapter_number)
        title = outline.title if outline is not None and outline.title else f"第{chapter_number}章"
        summary = store.summaries.load_summary(chapter_number)
        review = store.world.load_review(chapter_number)
        return session, {
            "title": title,
            "content": content,
            "summary": summary,
            "review": review,
        }

    def get_artifacts(self, run_id: str, artifact_type: str = "", chapter: int = 0) -> tuple[RunSession, list[dict[str, object]]]:
        session = self.get_run(run_id)
        items = self.artifact_service.list_artifacts(session.output_dir, session.run_id)
        if artifact_type:
            items = [item for item in items if str(item.get("type", "")) == artifact_type]
        if chapter > 0:
            items = [item for item in items if int(item.get("chapter", 0) or 0) == chapter]
        return session, items

    def _build_config(self, req: CreateRunRequest) -> Config:
        if req.config_path:
            cfg = load_config(req.config_path)
        else:
            provider = req.execution.provider or "openai"
            model = req.execution.model or "gpt-4o-mini"
            cfg = Config(
                output_dir=self._resolve_output_dir(req),
                provider=provider,
                model=model,
                providers={provider: ProviderConfig(api_key="dummy-key")},
                style="default",
                context_window=req.execution.context_window or 128000,
            )
        cfg.output_dir = self._resolve_output_dir(req)
        if req.execution.provider:
            cfg.provider = req.execution.provider
        if req.execution.model:
            cfg.model = req.execution.model
        if req.execution.context_window > 0:
            cfg.context_window = req.execution.context_window
        cfg.fill_defaults()
        if cfg.provider not in cfg.providers:
            cfg.providers[cfg.provider] = ProviderConfig(api_key="dummy-key")
        if not cfg.providers[cfg.provider].api_key and cfg.providers[cfg.provider].requires_api_key(cfg.provider):
            cfg.providers[cfg.provider].api_key = "dummy-key"
        return cfg

    def _resolve_output_dir(self, req: CreateRunRequest) -> str:
        base = (req.storage.base_path or "").strip()
        if base:
            return base
        story_id = (req.story.story_id or "").strip()
        if story_id:
            return str(Path("output") / "workspace" / story_id)
        return str(Path("output") / "novel" / req.run_id)

    def _seed_story_context(self, host: Host, req: CreateRunRequest) -> None:
        premise = (req.story.premise or "").strip()
        if premise:
            host.store.outline.save_premise(premise)
        characters = [
            Character(
                name=(item.name or "").strip(),
                role=(item.role or "").strip(),
                description=(item.description or "").strip(),
            )
            for item in req.story.characters
            if (item.name or "").strip()
        ]
        if characters:
            host.store.characters.save(characters)
        metadata = req.metadata or MetadataPayload()
        reference_snapshot = metadata.extra.get("reference_snapshot") if isinstance(metadata.extra, dict) else None
        if isinstance(reference_snapshot, dict):
            premise_override = str(reference_snapshot.get("premise", "") or "").strip()
            if premise_override:
                host.store.outline.save_premise(premise_override)
            outline = [
                parse_outline_entry(item)
                for item in (reference_snapshot.get("outline") or [])
                if isinstance(item, dict)
            ]
            if outline:
                host.store.outline.save_outline(outline)
            world_rules = [
                parse_world_rule(item)
                for item in (reference_snapshot.get("world_rules") or reference_snapshot.get("worldRules") or [])
                if isinstance(item, dict)
            ]
            if world_rules:
                host.store.world.save_world_rules(world_rules)
            timeline = [
                parse_timeline_event(item)
                for item in (reference_snapshot.get("timeline") or [])
                if isinstance(item, dict)
            ]
            if timeline:
                host.store.world.save_timeline(timeline)
            relationships = [
                parse_relationship_entry(item)
                for item in (reference_snapshot.get("relationship_state") or reference_snapshot.get("relationshipState") or [])
                if isinstance(item, dict)
            ]
            if relationships:
                host.store.world.save_relationships(relationships)
            foreshadow_entries = []
            for item in (reference_snapshot.get("foreshadow_ledger") or reference_snapshot.get("foreshadowLedger") or []):
                if not isinstance(item, dict):
                    continue
                if item.get("planted_at") is not None or item.get("status") is not None:
                    foreshadow_entries.append(
                        ForeshadowEntry(
                            id=str(item.get("id", "") or "").strip(),
                            description=str(item.get("description", "") or "").strip(),
                            planted_at=int(item.get("planted_at", 0) or 0),
                            status=str(item.get("status", "planted") or "planted"),
                            resolved_at=int(item.get("resolved_at", 0) or 0),
                        )
                    )
            if foreshadow_entries:
                host.store.world.save_foreshadow_ledger(foreshadow_entries)
        word_count = req.story.word_count
        min_words = max(2000, int(word_count.min_words or 2000))
        target_words = max(min_words, int(word_count.target_words or 2500))
        host.store.run_meta.set_story_defaults(
            title=(req.story.title or "").strip(),
            genre=(req.story.genre or "").strip(),
            min_words=min_words,
            target_words=target_words,
            max_words=target_words,
        )
