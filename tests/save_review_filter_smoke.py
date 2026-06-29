from __future__ import annotations

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.domain.review import ConsistencyIssue, DimensionScore, ReviewEntry
from ainovel_py.domain.runtime import Phase, Progress
from ainovel_py.store.store import Store
from ainovel_py.tools.save_review import SaveReviewTool


def _dimensions() -> list[DimensionScore]:
    names = ["consistency", "continuity", "voice", "emotional_impact", "rhythm_variety", "surprise", "restraint"]
    return [DimensionScore(dimension=name, score=85, verdict="pass", comment="ok") for name in names]


def main() -> int:
    cfg = Config(
        output_dir="output/save_review_filter_smoke",
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="dummy-key")},
    )
    store = Store(cfg.output_dir)
    store.init()
    store.progress.save(
        Progress(
            novel_name="测试小说",
            phase=Phase.WRITING,
            current_chapter=7,
            total_chapters=12,
            completed_chapters=[1, 2, 3, 4, 5, 6],
            total_word_count=6000,
        )
    )

    tool = SaveReviewTool(store)
    res = tool.execute(
        {
            "chapter": 6,
            "scope": "chapter",
            "issues": [
                {
                    "type": "continuity",
                    "severity": "warning",
                    "description": "后续章节结构漂移",
                    "evidence": "第6章埋下的新冲突与后续规划不一致",
                    "suggestion": "回收后续节奏",
                }
            ],
            "dimensions": [
                {"dimension": "consistency", "score": 82, "verdict": "pass", "comment": "ok"},
                {"dimension": "continuity", "score": 75, "verdict": "warning", "comment": "ok"},
                {"dimension": "voice", "score": 82, "verdict": "pass", "comment": "ok"},
                {"dimension": "emotional_impact", "score": 83, "verdict": "pass", "comment": "ok"},
                {"dimension": "rhythm_variety", "score": 81, "verdict": "pass", "comment": "ok"},
                {"dimension": "surprise", "score": 84, "verdict": "pass", "comment": "ok"},
                {"dimension": "restraint", "score": 85, "verdict": "pass", "comment": "ok"},
            ],
            "contract_status": "met",
            "contract_misses": [],
            "contract_notes": "",
            "verdict": "rewrite",
            "summary": "需要修正连续性",
            "affected_chapters": [7, 8, 9],
        }
    )

    progress = store.progress.load()
    if progress is None:
        raise RuntimeError("progress missing")
    if progress.pending_rewrites != [6]:
        raise RuntimeError(f"unexpected pending rewrites: {progress.pending_rewrites}")
    hints = res.get("system_hints") or []
    if not any("review_filtered" in hint for hint in hints):
        raise RuntimeError("expected filtered-hint to be present")

    print("save_review_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
