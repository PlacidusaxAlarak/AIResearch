from datetime import date, datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

import anyio

from airesearch.cli import orchestrator as orch_impl


def _build_paper() -> orch_impl.Paper:
    return orch_impl.Paper(
        paper_id="2602.20001",
        canonical_id="2602.20001",
        title="Seen Behavior Test",
        authors=["Alice"],
        abstract="test-time scaling",
        url="https://arxiv.org/abs/2602.20001",
        pdf_url="https://arxiv.org/pdf/2602.20001.pdf",
        published=datetime(2026, 2, 1, tzinfo=timezone.utc),
        source="arxiv",
        source_tags={"arxiv"},
        hf_score=0.0,
    )


def _build_prepared(paper: orch_impl.Paper) -> orch_impl.PreparedPaper:
    return orch_impl.PreparedPaper(
        paper=paper,
        whitelisted=False,
        super_whitelist_hit=False,
        super_whitelist_hit_reasons=[],
        citation_velocity=0.0,
        latex_text="\\section{A}",
        used_files=["main.tex"],
        clean_text="clean text",
        stage1_score=1.0,
        topic_score=1.0,
        coverage_score=1.0,
    )


class TestOrchestratorSeenBehaviorCharacterization(unittest.TestCase):
    def test_run_pipeline_does_not_use_history_seen_filter(self) -> None:
        paper = _build_paper()
        prepared = _build_prepared(paper)
        window = orch_impl.DateWindow(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 2),
        )
        prepare_mock = AsyncMock(return_value=prepared)
        process_mock = AsyncMock(return_value={paper.canonical_id, paper.paper_id})

        with (
            patch.object(orch_impl, "load_seen", side_effect=AssertionError("load_seen must not be called")),
            patch.object(orch_impl, "save_seen", side_effect=AssertionError("save_seen must not be called")),
            patch.object(orch_impl, "load_whitelist", return_value=set()),
            patch.object(orch_impl, "load_super_whitelist", return_value={}),
            patch.object(orch_impl, "discover_papers", AsyncMock(return_value=[paper])),
            patch.object(orch_impl, "_prepare_paper", prepare_mock),
            patch.object(orch_impl, "apply_stage1_prefilter", side_effect=lambda entries: entries),
            patch.object(orch_impl, "_process_paper", process_mock),
            patch.object(orch_impl, "PAPER_EVAL_CONCURRENCY", 1),
            patch.object(orch_impl, "_log") as log_mock,
        ):
            anyio.run(orch_impl.run_pipeline, window)

        prepare_mock.assert_awaited_once()
        process_mock.assert_awaited_once()
        messages = [call.args[1] for call in log_mock.call_args_list if len(call.args) >= 2]
        self.assertFalse(any("Skip already seen" in msg for msg in messages))
        self.assertTrue(any("History sent-paper dedupe disabled" in msg for msg in messages))


if __name__ == "__main__":
    unittest.main()
