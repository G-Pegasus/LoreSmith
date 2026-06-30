from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from ainovel_py.domain.story import OutlineEntry, WorldRule

from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.bootstrap.configfile import load_config
from ainovel_py.domain.review import ForeshadowEntry
from ainovel_py.host.host import Host
from ainovel_py.internal_api.errors import ApiError
from ainovel_py.internal_api.workspace_dto import WorkspaceIntentRequest
from ainovel_py.store.store import Store
from ainovel_py.tools.check_consistency import CheckConsistencyTool
from ainovel_py.tools.commit_chapter import CommitChapterTool
from ainovel_py.tools.draft_chapter import DraftChapterTool
from ainovel_py.tools.novel_context import NovelContextTool
from ainovel_py.tools.parsers import parse_character, parse_foreshadow_update, parse_outline_entry, parse_relationship_entry, parse_timeline_event, parse_world_rule
from ainovel_py.tools.plan_chapter import PlanChapterTool
from ainovel_py.tools.read_chapter import ReadChapterTool
from ainovel_py.tools.save_review import SaveReviewTool


class WorkspaceService:
    _TODO_PATTERN = re.compile(r"TODO|待补|xxx", re.IGNORECASE)
    _TIMELINE_HINTS = (("第二天", "第一天"), ("晚上", "清晨"))
    _CHAPTER_NODE_PATTERN = re.compile(r"chapter[-_ ]?(\d+)", re.IGNORECASE)
    _CHAPTER_TITLE_PATTERN = re.compile(r"第\s*(\d+)\s*章")

    def get_workspace_snapshot(self, story_id: str) -> dict[str, object]:
        workspace_id = (story_id or "").strip()
        if not workspace_id:
            raise ApiError("INVALID_ARGUMENT", "story_id is required", 400)
        store = Store(str(Path("output") / "workspace" / workspace_id))
        store.init()
        outline = store.outline.load_outline()
        premise = store.outline.load_premise() or ""
        meta = self._load_workspace_meta(store)
        progress = store.progress.load()
        run_meta = store.run_meta.load()
        chapter_numbers = self._collect_workspace_chapter_numbers(store, outline, progress)
        nodes: list[dict[str, object]] = [{
            "id": "volume-1",
            "parentId": None,
            "type": "volume",
            "title": "第一卷",
            "order": 0,
            "summary": premise,
        }]
        content_by_node_id: dict[str, str] = {}
        for index, chapter in enumerate(chapter_numbers, start=1):
            node_id = f"chapter-{chapter}"
            outline_item = next((item for item in outline if item.chapter == chapter), None)
            plan = store.drafts.load_chapter_plan(chapter)
            content = store.drafts.load_chapter_text(chapter)
            if not content:
                content = store.drafts.load_draft(chapter)
            content_by_node_id[node_id] = content or ""
            nodes.append({
                "id": node_id,
                "parentId": "volume-1",
                "type": "chapter",
                "title": self._resolve_workspace_chapter_title(chapter, meta, outline_item.title if outline_item else "", plan.title if plan else ""),
                "order": index - 1,
                "summary": (outline_item.core_event if outline_item else "") or "",
            })
        completed_count = len(progress.completed_chapters) if progress else 0
        current_run = meta.get("activeRunId")
        run_sync_updated_at = meta.get("runSyncUpdatedAt")
        pending_checkpoint = store.signals.load_pending_checkpoint()
        run_sync_status = self._resolve_workspace_run_status(str(current_run or ""), progress, pending_checkpoint)
        return {
            "storyId": workspace_id,
            "title": self._resolve_workspace_title(workspace_id, premise, run_meta.story_title if run_meta else ""),
            "premise": premise,
            "style": (run_meta.style if run_meta else "") or "default",
            "updatedAt": run_sync_updated_at,
            "localOnly": False,
            "nodes": nodes,
            "activeNodeId": self._resolve_active_node_id(nodes, meta, progress),
            "contentByNodeId": content_by_node_id,
            "assistantThread": meta.get("assistantThread") or [],
            "runBridge": {
                "activeRunId": current_run,
                "runAfterSeq": int(meta.get("runAfterSeq", 0) or 0),
                "runSyncStatus": run_sync_status,
                "runSyncUpdatedAt": run_sync_updated_at,
                "lastCompletedChapter": f"第 {max(progress.completed_chapters)} 章" if progress and progress.completed_chapters else None,
            },
        }

    def _resolve_workspace_run_status(self, run_id: str, progress, pending_checkpoint) -> str:
        if not run_id:
            return "idle"
        if pending_checkpoint is not None:
            return "waiting_input"
        registry_status = self._load_registry_run_status(run_id)
        if registry_status:
            return registry_status
        completed = progress.completed_chapters if progress else []
        if progress and (progress.in_progress_chapter > 0 or progress.current_chapter > len(completed or [])):
            return "running"
        return "idle"

    def _load_registry_run_status(self, run_id: str) -> str:
        registry_path = Path("output") / "internal_api" / "runs.json"
        if not registry_path.exists():
            return ""
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if not isinstance(data, list):
            return ""
        for item in data:
            if not isinstance(item, dict) or str(item.get("run_id", "") or "") != run_id:
                continue
            state_override = str(item.get("state_override", "") or "")
            if state_override in {"failed", "canceled"}:
                return state_override
            if state_override:
                return state_override
            return ""
        return ""

    def create_workspace_node(self, story_id: str, req) -> dict[str, object]:
        snapshot = self.get_workspace_snapshot(story_id)
        parent_id = (req.parentId or "").strip() or None
        node_type = (req.type or "").strip().lower()
        if node_type not in {"volume", "chapter"}:
            raise ApiError("INVALID_ARGUMENT", f"unsupported node type: {node_type}", 400)
        nodes = list(snapshot.get("nodes") or [])
        sibling_count = sum(1 for node in nodes if node.get("type") == node_type and node.get("parentId") == parent_id)
        node_id = f"{node_type}-{uuid.uuid4()}"
        nodes.append({
            "id": node_id,
            "parentId": parent_id,
            "type": node_type,
            "title": f"第 {sibling_count + 1} {'卷' if node_type == 'volume' else '章'}",
            "order": sibling_count,
            "summary": "",
        })
        content_by_node_id = dict(snapshot.get("contentByNodeId") or {})
        if node_type == "chapter":
            content_by_node_id[node_id] = ""
        snapshot["nodes"] = nodes
        snapshot["activeNodeId"] = node_id
        snapshot["contentByNodeId"] = content_by_node_id
        return snapshot

    def update_workspace_node(self, story_id: str, node_id: str, req) -> dict[str, object]:
        snapshot = self.get_workspace_snapshot(story_id)
        nodes = list(snapshot.get("nodes") or [])
        updated = []
        chapter_number = self._infer_workspace_chapter_from_snapshot(node_id, nodes)
        title_value = None
        for node in nodes:
            if node.get("id") == node_id:
                title_value = req.title if req and req.title is not None else node.get("title", "")
                node = {
                    **node,
                    "title": title_value,
                    "summary": req.summary if req and req.summary is not None else node.get("summary", ""),
                }
            updated.append(node)
        snapshot["nodes"] = updated
        snapshot["activeNodeId"] = node_id
        store = Store(str(Path("output") / "workspace" / story_id))
        store.init()
        meta = self._load_workspace_meta(store)
        meta["activeNodeId"] = node_id
        titles = meta.get("chapterTitles") if isinstance(meta.get("chapterTitles"), dict) else {}
        if chapter_number > 0 and title_value is not None:
            titles[str(chapter_number)] = str(title_value)
            meta["chapterTitles"] = titles
        self._save_workspace_meta(store, meta)
        if req and req.content is not None:
            content_by_node_id = dict(snapshot.get("contentByNodeId") or {})
            content_by_node_id[node_id] = req.content
            snapshot["contentByNodeId"] = content_by_node_id
            if chapter_number > 0:
                store.drafts.save_draft(chapter_number, req.content)
                store.drafts.save_final_chapter(chapter_number, req.content)
        return snapshot

    def get_workspace_reference_snapshot(self, story_id: str) -> dict[str, object]:
        detail = self.get_workspace_reference_detail(story_id)
        return {
            "premise": detail.get("premise", ""),
            "outline": detail.get("outline", []),
            "characters": detail.get("characters", []),
            "world_rules": detail.get("world_rules", []),
            "timeline": detail.get("timeline", []),
            "relationship_state": detail.get("relationship_state", []),
            "foreshadow_ledger": detail.get("foreshadow_ledger", []),
        }

    def get_workspace_reference_detail(self, story_id: str) -> dict[str, object]:
        workspace_id = (story_id or "").strip()
        if not workspace_id:
            raise ApiError("INVALID_ARGUMENT", "story_id is required", 400)
        store = Store(str(Path("output") / "workspace" / workspace_id))
        store.init()
        premise = store.outline.load_premise()
        outline_items = store.outline.load_outline()
        if not outline_items:
            outline_items = self._outline_from_chapter_plans(store)
        layered_outline = store.outline.load_layered_outline()
        compass = store.outline.load_compass()
        world_rules = store.world.load_world_rules()
        if not world_rules:
            world_rules = self._world_rules_from_premise(premise)
        progress = store.progress.load()
        run_meta = store.run_meta.load()
        volume_summaries = store.summaries.load_all_volume_summaries()
        arc_summaries: list[dict[str, object]] = []
        for volume in layered_outline:
            summaries = store.summaries.load_arc_summaries(volume.index)
            arc_summaries.extend(asdict(item) for item in summaries)
        snapshots = store.world.load_latest_character_snapshots()
        title = self._resolve_workspace_title(workspace_id, premise, run_meta.story_title if run_meta else "")
        return {
            "story_id": workspace_id,
            "title": title,
            "premise": premise,
            "outline": [asdict(item) for item in outline_items],
            "layered_outline": [asdict(item) for item in layered_outline],
            "compass": asdict(compass) if compass is not None else {},
            "characters": [asdict(item) for item in store.characters.load()],
            "character_snapshots": [asdict(item) for item in snapshots],
            "world_rules": [asdict(item) for item in world_rules],
            "timeline": [asdict(item) for item in store.world.load_timeline()],
            "relationship_state": [asdict(item) for item in store.world.load_relationships()],
            "foreshadow_ledger": [asdict(item) for item in store.world.load_foreshadow_ledger()],
            "arc_summaries": arc_summaries,
            "volume_summaries": [asdict(item) for item in volume_summaries],
            "progress": {
                "completed_chapters": len(progress.completed_chapters) if progress else 0,
                "current_chapter": progress.current_chapter if progress else 0,
                "total_word_count": progress.total_word_count if progress else 0,
                "current_volume": progress.current_volume if progress else 0,
            },
        }

    def save_workspace_reference_snapshot(self, story_id: str, payload: dict[str, object]) -> dict[str, object]:
        workspace_id = (story_id or "").strip()
        if not workspace_id:
            raise ApiError("INVALID_ARGUMENT", "story_id is required", 400)
        store = Store(str(Path("output") / "workspace" / workspace_id))
        store.init()
        premise = str(payload.get("premise", "") or "")
        store.outline.save_premise(premise)
        outline_items = [
            parse_outline_entry(item)
            for item in self._reference_items(payload, "outline")
            if isinstance(item, dict)
        ]
        store.outline.save_outline(outline_items)
        characters = [
            parse_character(item)
            for item in self._reference_items(payload, "characters")
            if isinstance(item, dict)
        ]
        store.characters.save([item for item in characters if item.name])
        world_rules = [
            parse_world_rule(item)
            for item in self._reference_items(payload, "world_rules", "worldRules")
            if isinstance(item, dict)
        ]
        store.world.save_world_rules([item for item in world_rules if item.category or item.rule or item.boundary])
        timeline = [
            parse_timeline_event(item)
            for item in self._reference_items(payload, "timeline")
            if isinstance(item, dict)
        ]
        store.world.save_timeline([item for item in timeline if item.time or item.event or item.characters])
        relationship_state = [
            parse_relationship_entry(item)
            for item in self._reference_items(payload, "relationship_state", "relationshipState")
            if isinstance(item, dict)
        ]
        store.world.save_relationships([item for item in relationship_state if item.character_a and item.character_b and item.relation])
        foreshadow_entries = self._parse_reference_foreshadow_entries(payload)
        store.world.save_foreshadow_ledger(foreshadow_entries)
        meta = self._load_workspace_meta(store)
        meta["referenceSnapshot"] = self.get_workspace_reference_snapshot(workspace_id)
        self._save_workspace_meta(store, meta)
        return self.get_workspace_reference_snapshot(workspace_id)

    def update_workspace_run_bridge(self, story_id: str, req) -> dict[str, object]:
        workspace_id = (story_id or "").strip()
        if not workspace_id:
            raise ApiError("INVALID_ARGUMENT", "story_id is required", 400)
        store = Store(str(Path("output") / "workspace" / workspace_id))
        store.init()
        meta = self._load_workspace_meta(store)
        meta["activeRunId"] = req.activeRunId
        meta["runAfterSeq"] = req.runAfterSeq
        meta["runSyncStatus"] = req.runSyncStatus
        meta["runSyncUpdatedAt"] = req.runSyncUpdatedAt
        meta["lastCompletedChapter"] = req.lastCompletedChapter
        self._save_workspace_meta(store, meta)
        return self.get_workspace_snapshot(workspace_id)

    def update_workspace_assistant_thread(self, story_id: str, req) -> dict[str, object]:
        workspace_id = (story_id or "").strip()
        if not workspace_id:
            raise ApiError("INVALID_ARGUMENT", "story_id is required", 400)
        store = Store(str(Path("output") / "workspace" / workspace_id))
        store.init()
        meta = self._load_workspace_meta(store)
        meta["assistantThread"] = self._normalize_assistant_thread(req.assistantThread)
        self._save_workspace_meta(store, meta)
        return self.get_workspace_snapshot(workspace_id)

    def stream_workspace_intent(self, req: WorkspaceIntentRequest):
        intent_type = (req.intent_type or "").strip()
        if intent_type != "assistant_reply":
            payload = self.handle_workspace_intent(req)
            yield self._sse_event("done", payload)
            return
        yield from self._stream_assistant_reply(req)

    def handle_workspace_intent(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        intent_type = (req.intent_type or "").strip()
        if not intent_type:
            raise ApiError("INVALID_ARGUMENT", "intent_type is required", 400)
        if intent_type == "assistant_reply":
            return self.handle_assistant_reply(req)
        if intent_type == "rewrite":
            return self.handle_rewrite(req)
        if intent_type == "consistency_scan":
            return self.handle_consistency_scan(req)
        if intent_type == "chapter_plan":
            return self.handle_chapter_plan(req)
        if intent_type == "chapter_draft":
            return self.handle_chapter_draft(req)
        if intent_type == "chapter_review":
            return self.handle_chapter_review(req)
        if intent_type == "chapter_commit":
            return self.handle_chapter_commit(req)
        if intent_type == "chapter_read_asset":
            return self.handle_chapter_read_asset(req)
        if intent_type in {"run_start", "run_resume", "run_continue", "run_batch"}:
            return {
                "route": "run_agent",
                "result": {},
                "fallback_used": False,
                "reason": "intent belongs to run agent",
                "provider": "",
                "model": "",
                "latency_ms": 0,
                "usage": {},
            }
        raise ApiError("INVALID_ARGUMENT", f"unsupported intent_type: {intent_type}", 400)

    def handle_assistant_reply(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        fallback = self._build_assistant_fallback(req.action, req.instruction, req.story.story_id, req.content)
        try:
            content = self._build_assistant_reply(req)
            return {
                "route": "workspace_agent",
                "result": {"content": content},
                "fallback_used": False,
                "reason": "workspace assistant intent handled",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "assistant-reply",
                "latency_ms": 0,
                "usage": {},
            }
        except Exception as exc:
            return {
                "route": "workspace_agent",
                "result": {"content": fallback},
                "fallback_used": True,
                "reason": f"assistant fallback: {exc}",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "assistant-reply",
                "latency_ms": 0,
                "usage": {},
            }

    def handle_rewrite(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        try:
            content = self._rewrite_content(req)
            return {
                "route": "workspace_agent",
                "result": {"content": content, "label": req.label or "AI 改写"},
                "fallback_used": False,
                "reason": "workspace rewrite intent handled",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "rewrite",
                "latency_ms": 0,
                "usage": {},
            }
        except Exception as exc:
            return {
                "route": "workspace_agent",
                "result": {"content": req.content or "", "label": req.label or "AI 改写"},
                "fallback_used": True,
                "reason": f"rewrite fallback: {exc}",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "rewrite",
                "latency_ms": 0,
                "usage": {},
            }

    def handle_consistency_scan(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        try:
            issues = self._scan_consistency(req)
            return {
                "route": "workspace_agent",
                "result": {"issues": issues},
                "fallback_used": False,
                "reason": "workspace consistency intent handled",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "consistency",
                "latency_ms": 0,
                "usage": {},
            }
        except Exception as exc:
            issues = self._rule_based_issues(req.story.story_id, req.node.node_id, req.content)
            return {
                "route": "workspace_agent",
                "result": {"issues": issues},
                "fallback_used": True,
                "reason": f"consistency fallback: {exc}",
                "provider": req.metadata.tenant_id or "workspace-agent",
                "model": req.metadata.user_id or "consistency",
                "latency_ms": 0,
                "usage": {},
            }

    def handle_chapter_plan(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        chapter = self._resolve_workspace_chapter(req)
        payload = dict(req.payload or {})
        payload["chapter"] = chapter
        result = PlanChapterTool(self._workspace_store(req)).execute(payload)
        return self._workspace_action_response(
            req,
            self._enrich_asset_result(req, chapter, asset_type="plan", payload=result),
            reason="workspace chapter plan handled",
        )

    def handle_chapter_draft(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        chapter = self._resolve_workspace_chapter(req)
        payload = dict(req.payload or {})
        payload["chapter"] = chapter
        if req.content and not payload.get("content"):
            payload["content"] = req.content
        if req.action and not payload.get("mode"):
            payload["mode"] = req.action
        result = DraftChapterTool(self._workspace_store(req)).execute(payload)
        return self._workspace_action_response(
            req,
            self._enrich_asset_result(req, chapter, asset_type="draft", payload=result),
            reason="workspace chapter draft handled",
        )

    def handle_chapter_review(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        chapter = self._resolve_workspace_chapter(req)
        store = self._workspace_store(req)
        payload = dict(req.payload or {})
        if payload.get("summary"):
            payload["chapter"] = chapter
            result = SaveReviewTool(store).execute(payload)
            enriched = self._enrich_asset_result(req, chapter, asset_type="review", payload=result)
        else:
            result = CheckConsistencyTool(store).execute({"chapter": chapter})
            enriched = self._enrich_asset_result(req, chapter, asset_type="review", payload=result)
        return self._workspace_action_response(req, enriched, reason="workspace chapter review handled")

    def handle_chapter_commit(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        chapter = self._resolve_workspace_chapter(req)
        payload = dict(req.payload or {})
        payload["chapter"] = chapter
        result = CommitChapterTool(self._workspace_store(req)).execute(payload)
        return self._workspace_action_response(
            req,
            self._enrich_asset_result(req, chapter, asset_type="chapter", payload=result),
            reason="workspace chapter commit handled",
        )

    def handle_chapter_read_asset(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        chapter = self._resolve_workspace_chapter(req)
        asset_type = self._resolve_workspace_asset_type(req)
        result = self._read_workspace_asset(req, chapter, asset_type)
        return self._workspace_action_response(req, result, reason="workspace chapter asset read handled")

    def _build_assistant_reply(self, req: WorkspaceIntentRequest) -> str:
        cfg = self._build_workspace_config(req)
        context = self._workspace_context(req, cfg.style)
        client = self._build_llm_client(cfg)
        chunks: list[str] = []
        client.complete_stream(
            self._assistant_system_prompt(req),
            self._assistant_user_prompt(req, context),
            on_delta=chunks.append,
            temperature=0.6,
        )
        message = "".join(chunks).strip()
        if message:
            return message
        raise RuntimeError("assistant reply is empty")

    def _stream_assistant_reply(self, req: WorkspaceIntentRequest):
        fallback = self._build_assistant_fallback(req.action, req.instruction, req.story.story_id, req.content)
        try:
            cfg = self._build_workspace_config(req)
            context = self._workspace_context(req, cfg.style)
            client = self._build_llm_client(cfg)
            delta_queue: queue.Queue[str | None] = queue.Queue()
            chunks: list[str] = []
            error_holder: list[Exception] = []

            def on_delta(delta: str) -> None:
                if not delta:
                    return
                chunks.append(delta)
                delta_queue.put(delta)

            def worker() -> None:
                try:
                    client.complete_stream(
                        self._assistant_system_prompt(req),
                        self._assistant_user_prompt(req, context),
                        on_delta=on_delta,
                        temperature=0.6,
                    )
                except Exception as exc:
                    error_holder.append(exc)
                finally:
                    delta_queue.put(None)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            while True:
                delta = delta_queue.get()
                if delta is None:
                    break
                yield self._sse_event("delta", {"delta": delta})

            if error_holder:
                raise error_holder[0]

            message = "".join(chunks).strip()
            if not message:
                raise RuntimeError("assistant reply is empty")
            yield self._sse_event(
                "done",
                {
                    "route": "workspace_agent",
                    "result": {"content": message},
                    "fallback_used": False,
                    "reason": "workspace assistant intent handled",
                    "provider": req.metadata.tenant_id or "workspace-agent",
                    "model": req.metadata.user_id or "assistant-reply",
                    "latency_ms": 0,
                    "usage": {},
                },
            )
        except Exception as exc:
            for delta in self._split_for_stream(fallback):
                yield self._sse_event("delta", {"delta": delta})
            yield self._sse_event(
                "done",
                {
                    "route": "workspace_agent",
                    "result": {"content": fallback},
                    "fallback_used": True,
                    "reason": f"assistant fallback: {exc}",
                    "provider": req.metadata.tenant_id or "workspace-agent",
                    "model": req.metadata.user_id or "assistant-reply",
                    "latency_ms": 0,
                    "usage": {},
                },
            )

    def _rewrite_content(self, req: WorkspaceIntentRequest) -> str:
        text = (req.content or "").strip()
        if not text:
            return ""
        cfg = self._build_workspace_config(req)
        prompt_context = self._workspace_context(req, cfg.style)
        system_prompt = (
            "你是小说工作台改写助手。保留原意和情节信息，优化语言节奏、细节密度和风格一致性。"
            "只输出改写后的正文，不要解释。"
        )
        user_prompt = (
            f"作品：{req.story.story_id or '当前作品'}\n"
            f"节点：{req.node.node_id or '当前节点'}\n"
            f"目标标签：{req.label or 'AI 改写'}\n"
            f"补充上下文：{prompt_context}\n\n"
            f"原文：\n{text}"
        )
        client = self._build_llm_client(cfg)
        rewritten = client.complete(system_prompt, user_prompt, temperature=0.4).strip()
        return rewritten or text

    def _scan_consistency(self, req: WorkspaceIntentRequest) -> list[dict[str, object]]:
        issues = self._rule_based_issues(req.story.story_id, req.node.node_id, req.content)
        context = self._workspace_context(req, style="default")
        if context.get("recent_summaries") and req.content:
            issues.append(
                self._issue(
                    req.node.node_id,
                    "low",
                    "plot",
                    "建议复核近期剧情承接",
                    "当前节点已有近期章节摘要，可结合前文确认信息承接和推进节奏是否自然。",
                )
            )
        if context.get("characters") and req.content:
            issues.append(
                self._issue(
                    req.node.node_id,
                    "low",
                    "character",
                    "建议复核人物状态延续",
                    "已检测到人物档案上下文，建议确认当前节点中的称呼、动机与前文是否保持稳定。",
                )
            )
        return issues

    def _rule_based_issues(self, story_id: str, node_id: str, content: str) -> list[dict[str, object]]:
        _ = story_id
        text = content or ""
        trimmed = text.strip()
        issues: list[dict[str, object]] = []
        if trimmed and len(trimmed) < 80:
            issues.append(self._issue(node_id, "medium", "draft", "内容偏短", "这一节内容偏短，可能还不足以承载一个完整动作或信息推进。"))
        if self._TODO_PATTERN.search(text):
            issues.append(self._issue(node_id, "high", "draft", "存在未完成标记", "正文中仍保留 TODO、待补 或 xxx 之类的占位内容。"))
        for later, earlier in self._TIMELINE_HINTS:
            later_index = text.find(later)
            earlier_index = text.find(earlier)
            if later_index >= 0 and earlier_index >= 0 and later_index < earlier_index:
                issues.append(self._issue(node_id, "medium", "timeline", "时间顺序可疑", f"这一节内出现“{later}”先于“{earlier}”的表达，建议确认时间线。"))
                break
        if text and "伏笔" in text and "回收" not in text:
            issues.append(self._issue(node_id, "low", "plot", "伏笔可能未闭合", "正文提到伏笔但未出现回收线索，建议确认是否需要在后续节点承接。"))
        return issues

    def _workspace_context(self, req: WorkspaceIntentRequest, style: str) -> dict[str, object]:
        base_path = self._resolve_workspace_output_dir(req)
        if base_path.exists():
            store = Store(str(base_path))
            tool = NovelContextTool(store, style=style)
            args: dict[str, object] = {}
            chapter = self._resolve_workspace_chapter(req)
            if chapter > 0:
                args["chapter"] = chapter
            try:
                return tool.execute(args)
            except Exception:
                return self._build_request_fallback_context(req)
        return self._build_request_fallback_context(req)

    def _build_request_fallback_context(self, req: WorkspaceIntentRequest) -> dict[str, object]:
        return {
            "story_id": req.story.story_id,
            "story_title": req.story.title,
            "premise": req.story.premise,
            "style": "",
            "node_id": req.node.node_id,
            "node_type": req.node.type,
            "node_title": req.node.title,
            "node_summary": req.node.summary,
            "instruction": req.instruction,
        }

    def _workspace_store(self, req: WorkspaceIntentRequest) -> Store:
        store = Store(str(self._resolve_workspace_output_dir(req)))
        store.init()
        return store

    def _workspace_action_response(self, req: WorkspaceIntentRequest, result: dict[str, object], reason: str) -> dict[str, object]:
        return {
            "route": "workspace_agent",
            "result": result,
            "fallback_used": False,
            "reason": reason,
            "provider": req.metadata.tenant_id or "workspace-agent",
            "model": req.metadata.user_id or req.intent_type,
            "latency_ms": 0,
            "usage": {},
        }

    def _resolve_workspace_output_dir(self, req: WorkspaceIntentRequest) -> Path:
        workspace_id = (req.story.story_id or "").strip() or (req.metadata.workspace_id or "").strip() or "workspace"
        return Path("output") / "workspace" / workspace_id

    def _workspace_meta_path(self) -> str:
        return "meta/workspace.json"

    @staticmethod
    def _reference_items(payload: dict[str, object], *keys: str) -> list[object]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _parse_reference_foreshadow_entries(payload: dict[str, object]) -> list[ForeshadowEntry]:
        entries: list[ForeshadowEntry] = []
        for item in WorkspaceService._reference_items(payload, "foreshadow_ledger", "foreshadowLedger"):
            if not isinstance(item, dict):
                continue
            if item.get("planted_at") is not None or item.get("status") is not None:
                entry = ForeshadowEntry(
                    id=str(item.get("id", "") or "").strip(),
                    description=str(item.get("description", "") or "").strip(),
                    planted_at=int(item.get("planted_at", 0) or 0),
                    status=str(item.get("status", "planted") or "planted").strip() or "planted",
                    resolved_at=int(item.get("resolved_at", 0) or 0),
                )
            else:
                update = parse_foreshadow_update(item)
                if not update.id:
                    continue
                entry = ForeshadowEntry(
                    id=update.id,
                    description=update.description,
                    planted_at=0,
                    status="resolved" if update.action == "resolve" else ("advanced" if update.action == "advance" else "planted"),
                    resolved_at=0,
                )
            if entry.id:
                entries.append(entry)
        return entries

    def _load_workspace_meta(self, store: Store) -> dict[str, object]:
        try:
            data = store.progress.io.read_json(self._workspace_meta_path())
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    def _save_workspace_meta(self, store: Store, data: dict[str, object]) -> None:
        store.progress.io.write_json(self._workspace_meta_path(), data)

    def _normalize_assistant_thread(self, items: list[dict]) -> list[dict[str, str]]:
        thread: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "") or "").strip()
            if role not in {"user", "assistant", "system"}:
                continue
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue
            message_id = str(item.get("id", "") or item.get("messageId", "") or uuid.uuid4()).strip()
            created_at = str(item.get("createdAt", "") or item.get("created_at", "") or "").strip()
            thread.append({
                "id": message_id,
                "role": role,
                "content": content,
                "createdAt": created_at,
            })
        return thread[-100:]

    def _collect_workspace_chapter_numbers(self, store: Store, outline: list, progress) -> list[int]:
        chapter_numbers: set[int] = {item.chapter for item in outline if getattr(item, "chapter", 0) > 0}
        patterns = [
            "drafts/*.draft.md",
            "drafts/*.plan.json",
            "chapters/*.md",
            "summaries/[0-9][0-9].json",
            "reviews/[0-9][0-9].json",
        ]
        for pattern in patterns:
            for path in store.progress.io.path("").glob(pattern):
                match = re.match(r"^(\d+)", path.name)
                if match:
                    chapter_numbers.add(int(match.group(1)))
        if progress:
            chapter_numbers.update(progress.completed_chapters)
            if progress.current_chapter > 0:
                chapter_numbers.add(progress.current_chapter)
            if progress.in_progress_chapter > 0:
                chapter_numbers.add(progress.in_progress_chapter)
        return sorted(number for number in chapter_numbers if number > 0)

    @staticmethod
    def _resolve_workspace_title(workspace_id: str, premise: str, story_title: str) -> str:
        if story_title.strip():
            return story_title.strip()
        for raw in premise.splitlines():
            line = raw.strip().strip("# ")
            if line:
                return line
        return workspace_id

    @staticmethod
    def _outline_from_chapter_plans(store: Store) -> list[OutlineEntry]:
        entries: list[OutlineEntry] = []
        for path in sorted(store.progress.io.path("").glob("drafts/*.plan.json")):
            match = re.match(r"^(\d+)", path.name)
            if not match:
                continue
            chapter = int(match.group(1))
            plan = store.drafts.load_chapter_plan(chapter)
            if plan is None:
                continue
            entries.append(
                OutlineEntry(
                    chapter=chapter,
                    title=plan.title,
                    core_event=plan.goal,
                    hook=plan.hook,
                    scenes=[],
                )
            )
        return entries

    @staticmethod
    def _world_rules_from_premise(premise: str) -> list[WorldRule]:
        text = str(premise or "").strip()
        if not text:
            return []
        return [WorldRule(category="作品设定", rule=text, boundary="")]

    @staticmethod
    def _resolve_workspace_chapter_title(chapter: int, meta: dict[str, object], outline_title: str, plan_title: str) -> str:
        titles = meta.get("chapterTitles") if isinstance(meta.get("chapterTitles"), dict) else {}
        persisted = str(titles.get(str(chapter), "") or "").strip()
        if persisted:
            return persisted
        if outline_title.strip():
            return outline_title.strip()
        if plan_title.strip():
            return plan_title.strip()
        return f"第 {chapter} 章"

    @staticmethod
    def _resolve_active_node_id(nodes: list[dict[str, object]], meta: dict[str, object], progress) -> str | None:
        chapter_ids = {str(node.get("id", "")) for node in nodes if node.get("type") == "chapter"}
        persisted = str(meta.get("activeNodeId", "") or "")
        if persisted and persisted in chapter_ids:
            return persisted
        for chapter in (
            getattr(progress, "in_progress_chapter", 0) if progress else 0,
            getattr(progress, "current_chapter", 0) if progress else 0,
            max(getattr(progress, "completed_chapters", []) or [0]),
        ):
            if chapter and f"chapter-{chapter}" in chapter_ids:
                return f"chapter-{chapter}"
        for node in nodes:
            if node.get("type") == "chapter":
                return str(node.get("id", "")) or None
        return None

    def _infer_workspace_chapter_from_snapshot(self, node_id: str, nodes: list[dict[str, object]]) -> int:
        for node in [item for item in nodes if item.get("type") == "chapter"]:
            if str(node.get("id", "")) == node_id:
                matched = self._CHAPTER_NODE_PATTERN.search(node_id)
                if matched:
                    return int(matched.group(1))
        return 0

    def _resolve_workspace_chapter(self, req: WorkspaceIntentRequest) -> int:
        if req.node.chapter > 0:
            return req.node.chapter
        return self._infer_workspace_chapter(req)

    def _resolve_workspace_asset_type(self, req: WorkspaceIntentRequest) -> str:
        asset_type = (req.node.asset_type or "").strip().lower()
        if asset_type in {"plan", "draft", "chapter", "summary", "review"}:
            return asset_type
        node_type = (req.node.type or "").strip().lower()
        if node_type == "chapter":
            return "chapter"
        return "draft"

    def _infer_workspace_chapter(self, req: WorkspaceIntentRequest) -> int:
        for value, pattern in (
            (req.node.node_id, self._CHAPTER_NODE_PATTERN),
            (req.node.title, self._CHAPTER_TITLE_PATTERN),
        ):
            matched = pattern.search((value or "").strip())
            if matched:
                return int(matched.group(1))
        return 0

    def _enrich_asset_result(self, req: WorkspaceIntentRequest, chapter: int, asset_type: str, payload: dict[str, object]) -> dict[str, object]:
        result = {
            "chapter": chapter,
            "asset_type": asset_type,
            "asset_path": self._workspace_asset_path(chapter, asset_type),
            "payload": payload,
        }
        if isinstance(payload.get("next_step"), str) and payload.get("next_step"):
            result["next_step"] = payload["next_step"]
        asset_snapshot = self._read_workspace_asset(req, chapter, asset_type)
        if asset_snapshot.get("content"):
            result["content"] = asset_snapshot["content"]
        if asset_snapshot.get("summary"):
            result["summary"] = asset_snapshot["summary"]
        return result

    def _workspace_asset_path(self, chapter: int, asset_type: str) -> str:
        if asset_type == "plan":
            return f"drafts/{chapter:02d}.plan.json"
        if asset_type == "draft":
            return f"drafts/{chapter:02d}.draft.md"
        if asset_type == "summary":
            return f"summaries/{chapter:02d}.json"
        if asset_type == "review":
            return f"reviews/{chapter:02d}.json"
        return f"chapters/{chapter:02d}.md"

    def _read_workspace_asset(self, req: WorkspaceIntentRequest, chapter: int, asset_type: str) -> dict[str, object]:
        store = self._workspace_store(req)
        result: dict[str, object] = {
            "chapter": chapter,
            "asset_type": asset_type,
            "asset_path": self._workspace_asset_path(chapter, asset_type),
        }
        if asset_type == "plan":
            plan = store.drafts.load_chapter_plan(chapter)
            if plan is None:
                result["exists"] = False
                return result
            result["exists"] = True
            result["payload"] = asdict(plan)
            result["summary"] = plan.goal
            return result
        if asset_type == "summary":
            summary = store.summaries.load_summary(chapter)
            if summary is None:
                result["exists"] = False
                return result
            result["exists"] = True
            result["payload"] = asdict(summary)
            result["summary"] = summary.summary
            return result
        if asset_type == "review":
            review = store.world.load_review(chapter)
            if review is None:
                result["exists"] = False
                return result
            result["exists"] = True
            result["payload"] = asdict(review)
            result["summary"] = review.summary
            return result
        source = "draft" if asset_type == "draft" else "final"
        content_result = ReadChapterTool(store).execute({"chapter": chapter, "source": source})
        result["exists"] = bool(content_result.get("exists", True))
        if content_result.get("content"):
            result["content"] = str(content_result["content"])
        if content_result.get("word_count") is not None:
            result["word_count"] = int(content_result["word_count"])
        if content_result.get("hint"):
            result["hint"] = str(content_result["hint"])
        return result

    def _assistant_system_prompt(self, req: WorkspaceIntentRequest) -> str:
        return (
            "你是小说工作台的章节润色助手。你的任务是直接改写当前章节正文。"
            "必须根据用户要求对现有正文进行润色、改写、续写或优化，并输出最终章节正文。"
            "不要解释，不要点评，不要输出 JSON、标题、步骤、日志、reasoning 或 tool 痕迹。"
            f"当前 action={req.action or 'polish'}。"
        )

    def _assistant_user_prompt(self, req: WorkspaceIntentRequest, context: dict[str, object]) -> str:
        premise = context.get("premise") or ""
        outline = context.get("chapter_plan") or {}
        characters = context.get("characters") or []
        world_rules = context.get("world_rules") or []
        foreshadow_ledger = context.get("foreshadow_ledger") or []
        relationships = context.get("relationship_state") or []
        return (
            f"作品：{req.story.story_id or '当前作品'}\n"
            f"章节：{req.node.title or req.node.node_id or '当前章节'}\n"
            f"操作：{req.action or 'polish'}\n"
            f"用户要求：{req.instruction or '在保持剧情方向不变的前提下优化当前章节'}\n"
            f"作品设定：{premise}\n"
            f"章节规划：{outline}\n"
            f"人物：{characters}\n"
            f"世界规则：{world_rules}\n"
            f"伏笔：{foreshadow_ledger}\n"
            f"人物关系：{relationships}\n\n"
            f"当前正文：\n{req.content or '（当前未传正文）'}\n\n"
            "请直接输出修改后的完整中文章节正文。"
        )

    def _build_assistant_fallback(self, action: str, instruction: str, story_id: str, content: str) -> str:
        excerpt = (content or "").strip()
        if excerpt:
            return excerpt
        return (
            f"作品：{story_id or '当前作品'}\n"
            f"用户要求：{instruction or '未补充额外说明'}\n\n"
            "请先补充这一章的正文，再继续使用 AI 润色。"
        )

    def _build_workspace_config(self, req: WorkspaceIntentRequest) -> Config:
        config_path = (req.metadata.request_id or "").strip()
        if config_path and Path(config_path).is_file():
            cfg = load_config(config_path)
        else:
            cfg = load_config()
        cfg.output_dir = str(self._resolve_workspace_output_dir(req))
        cfg.fill_defaults()
        if cfg.provider not in cfg.providers:
            cfg.providers[cfg.provider] = ProviderConfig(api_key="")
        return cfg

    def _build_llm_client(self, cfg: Config) -> OpenAICompatClient:
        cfg.fill_defaults()
        pc = cfg.providers.get(cfg.provider)
        if pc is None or (pc.requires_api_key(cfg.provider) and not pc.api_key):
            raise RuntimeError("provider api_key 未配置")
        return OpenAICompatClient(
            api_key=pc.api_key,
            model=cfg.model,
            base_url=pc.base_url,
            timeout=60.0,
        )

    def _split_for_stream(self, text: str) -> list[str]:
        if not text:
            return []
        return [text[index : index + 24] for index in range(0, len(text), 24)]

    def _sse_event(self, event: str, payload: dict[str, object]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _issue(self, node_id: str, severity: str, category: str, title: str, description: str) -> dict[str, object]:
        return {
            "id": f"issue-{uuid.uuid4()}",
            "severity": severity,
            "category": category,
            "title": title,
            "description": description,
            "nodeId": node_id or None,
            "status": "open",
        }
