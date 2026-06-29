from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.domain.review import ForeshadowUpdate, RelationshipEntry, TimelineEvent
from ainovel_py.domain.runtime import Phase, Progress
from ainovel_py.domain.story import OutlineEntry
from ainovel_py.domain.writing import ChapterPlan, ChapterSummary
from ainovel_py.internal_api.workspace_dto import WorkspaceIntentRequest
from ainovel_py.internal_api.workspace_service import WorkspaceService
from ainovel_py.store.store import Store


class WorkspaceIntentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WorkspaceService()
        self.workspace_root = Path("output") / "workspace"
        self._cleanup_paths: list[Path] = []

    def tearDown(self) -> None:
        for path in reversed(self._cleanup_paths):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()

    def _register_cleanup(self, path: Path) -> Path:
        self._cleanup_paths.append(path)
        return path

    def _make_workspace_store(self, story_id: str) -> Store:
        path = self._register_cleanup(self.workspace_root / story_id)
        shutil.rmtree(path, ignore_errors=True)
        store = Store(str(path))
        store.init()
        return store

    def test_assistant_intent_routes_to_workspace_agent(self) -> None:
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="assistant_reply",
                story={"story_id": "workspace_intent_cfg_story_1", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
                action="conflict",
                instruction="把冲突压得更紧一些",
                content="主角推门而入，却发现房间里早有人等着。",
            )
        )

        self.assertEqual(response["route"], "workspace_agent")
        self.assertIn("content", response["result"])
        self.assertTrue(response["result"]["content"].strip())
        self.assertFalse(response["fallback_used"])

    def test_consistency_intent_returns_issues(self) -> None:
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="consistency_scan",
                story={"story_id": "workspace_intent_cfg_story_1", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
                content="TODO 第二天发生在第一天之前",
            )
        )

        self.assertEqual(response["route"], "workspace_agent")
        self.assertGreaterEqual(len(response["result"]["issues"]), 2)

    def test_run_intent_routes_to_run_agent(self) -> None:
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="run_continue",
                story={"story_id": "workspace_intent_cfg_story_1", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
                instruction="继续推进",
            )
        )

        self.assertEqual(response["route"], "run_agent")
        self.assertEqual(response["result"], {})

    def test_workspace_reference_snapshot_reads_store_assets(self) -> None:
        store = self._make_workspace_store("workspace_snapshot_story")
        store.outline.save_premise("设定")
        store.outline.save_outline([OutlineEntry(chapter=1, title="第一章", core_event="开场", hook="门响了", scenes=["入场"])])
        store.characters.save([])
        store.world.save_world_rules([])
        store.world.append_timeline_events([TimelineEvent(chapter=1, time="夜里", event="抵达", characters=["主角"])])
        store.world.update_relationships([RelationshipEntry(character_a="主角", character_b="同伴", relation="试探", chapter=1)])
        store.world.update_foreshadow(1, [ForeshadowUpdate(id="f1", action="plant", description="门锁异常")])

        snapshot = self.service.get_workspace_reference_snapshot("workspace_snapshot_story")

        self.assertEqual(snapshot["premise"], "设定")
        self.assertEqual(snapshot["outline"][0]["title"], "第一章")
        self.assertEqual(snapshot["timeline"][0]["event"], "抵达")
        self.assertEqual(snapshot["relationship_state"][0]["relation"], "试探")
        self.assertEqual(snapshot["foreshadow_ledger"][0]["id"], "f1")

    def test_workspace_context_uses_deterministic_store_path(self) -> None:
        store = self._make_workspace_store("workspace_intent_cfg_story_1")
        store.progress.save(Progress(novel_name="标题", phase=Phase.WRITING, completed_chapters=[1], current_chapter=2))
        store.outline.save_premise("旧版设定")

        req = WorkspaceIntentRequest(
            intent_type="assistant_reply",
            story={"story_id": "workspace_intent_cfg_story_1", "title": "标题", "premise": "新设定", "style": "default"},
            node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
            action="continue",
            instruction="继续写第二章",
            metadata={"request_id": "request-123", "workspace_id": "workspace_intent_cfg_story_1"},
        )

        context = self.service._workspace_context(req, style="default")

        self.assertEqual(context.get("premise"), "旧版设定")
        self.assertEqual(context.get("progress_status", {}).get("next_chapter"), 2)
        self.assertNotIn("story_title", context)

    def test_workspace_context_infers_chapter_for_rich_store_fields(self) -> None:
        store = self._make_workspace_store("workspace_intent_story_2")
        store.progress.save(Progress(novel_name="标题", phase=Phase.WRITING, completed_chapters=[1], current_chapter=2))
        store.outline.save_premise("设定")
        store.outline.save_outline([
            OutlineEntry(chapter=2, title="第二章", core_event="进入新场景", hook="门后有人", scenes=["入场", "对峙"])
        ])
        store.drafts.save_chapter_plan(ChapterPlan(chapter=2, title="第二章", goal="推进", conflict="冲突", hook="钩子"))
        store.summaries.save_summary(ChapterSummary(chapter=1, summary="第一章摘要", characters=["主角"], key_events=["事件1"]))
        store.world.append_timeline_events([TimelineEvent(chapter=1, time="夜里", event="抵达宅邸", characters=["主角"])])
        store.world.update_foreshadow(1, [ForeshadowUpdate(id="f1", action="plant", description="门锁异常")])
        store.world.update_relationships([RelationshipEntry(character_a="主角", character_b="管家", relation="试探", chapter=1)])

        req = WorkspaceIntentRequest(
            intent_type="assistant_reply",
            story={"story_id": "workspace_intent_story_2", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
            action="continue",
            instruction="继续写第二章",
        )

        context = self.service._workspace_context(req, style="default")

        self.assertEqual(context.get("recent_summaries", [{}])[0].get("summary"), "第一章摘要")
        self.assertEqual(context.get("timeline", [{}])[0].get("event"), "抵达宅邸")
        self.assertEqual(context.get("foreshadow_ledger", [{}])[0].get("id"), "f1")
        self.assertEqual(context.get("relationship_state", [{}])[0].get("relation"), "试探")
        self.assertEqual(context.get("current_chapter_outline", {}).get("core_event"), "进入新场景")
        self.assertEqual(context.get("chapter_plan", {}).get("goal"), "推进")

    def test_workspace_config_ignores_random_request_id(self) -> None:
        req = WorkspaceIntentRequest(
            intent_type="assistant_reply",
            story={"story_id": "workspace_intent_cfg_story_1", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
            action="continue",
            instruction="继续写第一章",
            metadata={"request_id": "request-123", "workspace_id": "workspace_intent_cfg_story_1"},
        )

        cfg = self.service._build_workspace_config(req)

        self.assertEqual(cfg.provider, "openrouter")
        self.assertEqual(cfg.model, "qwen3.5-flash")
        self.assertEqual(cfg.output_dir, str(Path("output") / "workspace" / "workspace_intent_cfg_story_1"))
        self.assertNotEqual(cfg.providers[cfg.provider].api_key, "dummy-key")

    def test_workspace_config_allows_request_id_file_for_config_only(self) -> None:
        config_path = self._register_cleanup(Path("output") / "workspace_intent_test_config.json")
        config_path.write_text(
            json.dumps(
                {
                    "provider": "openai",
                    "model": "gpt-test",
                    "providers": {"openai": {"api_key": "dummy-key"}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        req = WorkspaceIntentRequest(
            intent_type="assistant_reply",
            story={"story_id": "story_cfg", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-1", "type": "chapter", "title": "第一章", "summary": "摘要"},
            metadata={"request_id": str(config_path), "workspace_id": "story_cfg"},
        )

        cfg = self.service._build_workspace_config(req)

        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.model, "gpt-test")
        self.assertEqual(cfg.providers["openai"].api_key, "dummy-key")
        self.assertEqual(cfg.output_dir, str(Path("output") / "workspace" / "story_cfg"))

    def test_chapter_plan_writes_plan_asset(self) -> None:
        self._make_workspace_store("workspace_intent_plan_story")
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="chapter_plan",
                story={"story_id": "workspace_intent_plan_story", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-3", "type": "chapter", "title": "第三章", "summary": "摘要"},
                payload={"title": "第三章", "goal": "推进调查", "conflict": "线索互斥", "hook": "门突然开了"},
            )
        )

        self.assertEqual(response["route"], "workspace_agent")
        self.assertEqual(response["result"]["asset_type"], "plan")
        self.assertEqual(response["result"]["asset_path"], "drafts/03.plan.json")
        plan = Store("output/workspace/workspace_intent_plan_story").drafts.load_chapter_plan(3)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.goal, "推进调查")

    def test_chapter_draft_and_read_asset_flow(self) -> None:
        self._make_workspace_store("workspace_intent_draft_story")
        draft_req = WorkspaceIntentRequest(
            intent_type="chapter_draft",
            story={"story_id": "workspace_intent_draft_story", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
            content="第一段草稿。",
        )
        response = self.service.handle_workspace_intent(draft_req)
        self.assertEqual(response["result"]["asset_type"], "draft")
        self.assertEqual(response["result"]["content"], "第一段草稿。")

        append_req = WorkspaceIntentRequest(
            intent_type="chapter_draft",
            story={"story_id": "workspace_intent_draft_story", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
            action="append",
            content="第二段草稿。",
        )
        self.service.handle_workspace_intent(append_req)

        read_req = WorkspaceIntentRequest(
            intent_type="chapter_read_asset",
            story={"story_id": "workspace_intent_draft_story", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要", "asset_type": "draft"},
        )
        read_response = self.service.handle_workspace_intent(read_req)
        self.assertIn("第一段草稿。", read_response["result"]["content"])
        self.assertIn("第二段草稿。", read_response["result"]["content"])

    def test_chapter_commit_writes_final_assets(self) -> None:
        store = self._make_workspace_store("workspace_intent_commit_story")
        store.drafts.save_draft(2, "正式提交内容。")
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="chapter_commit",
                story={"story_id": "workspace_intent_commit_story", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                payload={
                    "summary": "第二章摘要",
                    "characters": ["主角"],
                    "key_events": ["事件1"],
                    "timeline_events": [{"time": "夜里", "event": "进入大厅", "characters": ["主角"]}],
                },
            )
        )

        self.assertEqual(response["result"]["asset_type"], "chapter")
        self.assertEqual(response["result"]["asset_path"], "chapters/02.md")
        self.assertEqual(Store("output/workspace/workspace_intent_commit_story").drafts.load_chapter_text(2), "正式提交内容。")
        saved_summary = Store("output/workspace/workspace_intent_commit_story").summaries.load_summary(2)
        self.assertIsNotNone(saved_summary)
        self.assertEqual(saved_summary.summary, "第二章摘要")

    def test_chapter_read_asset_uses_explicit_node_chapter(self) -> None:
        store = self._make_workspace_store("workspace_intent_explicit_chapter_story")
        store.drafts.save_draft(5, "第五章草稿")
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="chapter_read_asset",
                story={"story_id": "workspace_intent_explicit_chapter_story", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要", "chapter": 5, "asset_type": "draft"},
            )
        )

        self.assertEqual(response["result"]["chapter"], 5)
        self.assertEqual(response["result"]["content"], "第五章草稿")

    def test_chapter_review_can_save_review_asset(self) -> None:
        store = self._make_workspace_store("workspace_intent_review_story")
        store.progress.save(Progress(novel_name="标题", phase=Phase.WRITING, completed_chapters=[2], current_chapter=3))
        response = self.service.handle_workspace_intent(
            WorkspaceIntentRequest(
                intent_type="chapter_review",
                story={"story_id": "workspace_intent_review_story", "title": "标题", "premise": "设定", "style": "default"},
                node={"node_id": "chapter-2", "type": "chapter", "title": "第二章", "summary": "摘要"},
                payload={
                    "chapter": 2,
                    "scope": "chapter",
                    "summary": "需要打磨",
                    "verdict": "polish",
                    "affected_chapters": [2],
                    "issues": [
                        {"type": "continuity", "severity": "medium", "description": "动机偏弱", "evidence": "第二段", "suggestion": "补动机"}
                    ],
                    "dimensions": [
                        {"dimension": "consistency", "score": 85, "verdict": "pass", "comment": "ok"},
                        {"dimension": "continuity", "score": 81, "verdict": "pass", "comment": "ok"},
                        {"dimension": "voice", "score": 82, "verdict": "pass", "comment": "ok"},
                        {"dimension": "emotional_impact", "score": 83, "verdict": "pass", "comment": "ok"},
                        {"dimension": "rhythm_variety", "score": 79, "verdict": "warning", "comment": "ok"},
                        {"dimension": "surprise", "score": 83, "verdict": "pass", "comment": "ok"},
                        {"dimension": "restraint", "score": 88, "verdict": "pass", "comment": "ok"},
                    ],
                },
            )
        )

        self.assertEqual(response["result"]["asset_type"], "review")
        self.assertEqual(response["result"]["summary"], "需要打磨")

    def test_workspace_context_falls_back_when_store_missing(self) -> None:
        req = WorkspaceIntentRequest(
            intent_type="assistant_reply",
            story={"story_id": "missing_story", "title": "标题", "premise": "设定", "style": "default"},
            node={"node_id": "node-1", "type": "chapter", "title": "节点", "summary": "摘要"},
            instruction="继续写",
        )

        context = self.service._workspace_context(req, style="default")

        self.assertEqual(context.get("story_title"), "标题")
        self.assertEqual(context.get("instruction"), "继续写")
        self.assertNotIn("progress_status", context)


if __name__ == "__main__":
    unittest.main()
