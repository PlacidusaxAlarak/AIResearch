from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import anyio

from airesearch.cli import orchestrator as orch_impl


def _build_paper() -> orch_impl.Paper:
    return orch_impl.Paper(
        paper_id="2602.99999",
        canonical_id="2602.99999",
        title="Single Pass Test",
        authors=["Alice", "Bob"],
        abstract="A test abstract.",
        url="https://arxiv.org/abs/2602.99999",
        pdf_url="https://arxiv.org/pdf/2602.99999.pdf",
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
        source_markdown="# Parsed Markdown",
        source_markdown_path="output/mineru/2602.99999/extract/content.md",
        pdf_path="output/mineru/2602.99999/source.pdf",
        mineru_batch_id="batch-123",
        stage1_score=1.2,
        topic_score=1.0,
        coverage_score=0.2,
    )


def _fake_prompt_loader(path):
    if path == orch_impl.CODEX_PROMPT_PAPER_ANALYSIS_PATH:
        return (
            "Paper analysis prompt\n"
            "Title: {title}\n"
            "Authors: {authors}\n"
            "Abstract:\n{abstract}\n"
            "URL: {url}\n"
            "Markdown:\n{source_markdown}\n"
        )
    raise RuntimeError(f"Unexpected prompt path in test: {path}")


class TestOrchestratorSinglePassCharacterization(unittest.TestCase):
    def test_codex_process_paper_uses_single_analysis_prompt(self) -> None:
        paper = _build_paper()
        source_markdown = "# Heading\n\nParsed paper markdown."
        run_mock = AsyncMock(
            return_value={
                "chunk_summaries": ["summary item"],
                "methods_loss": ["loss item"],
                "hyperparams": ["lr=1e-4"],
                "evidence_notes": ["ablation included"],
                "github_urls": ["https://github.com/acme/repo"],
                "primary_github_url": "https://github.com/acme/repo",
                "recommendation_score": 8,
                "recommendation_reason": "Strong evidence",
                "direction_tags": ["inference-scaling"],
                "tldr": "Short summary",
                "summary": "Longer summary",
                "email_body_markdown": "## Email\n- already rendered",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            with (
                patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
                patch.object(orch_impl, "_run_codex_json", run_mock),
                patch.object(orch_impl, "STATE_DIR", state_dir),
            ):
                out = anyio.run(orch_impl.codex_process_paper, paper, source_markdown)

        self.assertEqual(1, run_mock.await_count)
        sent_prompt = run_mock.await_args_list[0].args[0]
        self.assertIn(source_markdown, sent_prompt)
        self.assertEqual(8, out["recommendation_score"])
        self.assertEqual("## Email\n- already rendered", out["email_body_markdown"])

    def test_codex_process_paper_reuses_cached_single_result(self) -> None:
        paper = _build_paper()
        source_markdown = "# Heading\n\nParsed paper markdown."
        run_mock = AsyncMock(
            return_value={
                "chunk_summaries": ["summary item"],
                "methods_loss": ["loss item"],
                "hyperparams": ["lr=1e-4"],
                "evidence_notes": ["ablation included"],
                "github_urls": ["https://github.com/acme/repo"],
                "primary_github_url": "https://github.com/acme/repo",
                "recommendation_score": 8,
                "recommendation_reason": "Strong evidence",
                "direction_tags": ["inference-scaling"],
                "tldr": "Short summary",
                "summary": "Longer summary",
                "email_body_markdown": "## Email\n- cached",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            with (
                patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
                patch.object(orch_impl, "_run_codex_json", run_mock),
                patch.object(orch_impl, "STATE_DIR", state_dir),
            ):
                first = anyio.run(orch_impl.codex_process_paper, paper, source_markdown)
                second = anyio.run(orch_impl.codex_process_paper, paper, source_markdown)

        self.assertEqual(first, second)
        self.assertEqual(1, run_mock.await_count)

    def test_prepare_paper_uses_pdf_markdown_not_latex_helpers(self) -> None:
        paper = _build_paper()
        prepare_mock = AsyncMock(
            return_value={
                "status": "done",
                "markdown_path": "G:/AIResearch/output/mineru/2602.99999/extract/content.md",
                "pdf_path": "G:/AIResearch/output/mineru/2602.99999/source.pdf",
                "batch_id": "batch-123",
                "markdown_text": "# Parsed Markdown",
            }
        )
        with (
            patch.object(orch_impl, "passes_filters", AsyncMock(return_value=(True, 0.0, False))),
            patch.object(orch_impl, "prepare_pdf_markdown", prepare_mock, create=True),
            patch.object(orch_impl, "fetch_latex_source", side_effect=AssertionError("latex fetch should not be used"), create=True),
            patch.object(orch_impl, "codex_select_main_tex", side_effect=AssertionError("main tex should not be used"), create=True),
            patch.object(orch_impl, "clean_latex_fulltext", side_effect=AssertionError("latex cleaning should not be used"), create=True),
        ):
            prepared = anyio.run(orch_impl._prepare_paper, paper, set(), {})

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual("# Parsed Markdown", prepared.source_markdown)
        self.assertEqual("batch-123", prepared.mineru_batch_id)
        self.assertTrue(prepared.source_markdown_path.endswith("content.md"))
        self.assertTrue(prepared.pdf_path.endswith("source.pdf"))
        prepare_mock.assert_awaited_once()

    def test_prepare_paper_skips_pending_mineru_job(self) -> None:
        paper = _build_paper()
        with (
            patch.object(orch_impl, "passes_filters", AsyncMock(return_value=(True, 0.0, False))),
            patch.object(
                orch_impl,
                "prepare_pdf_markdown",
                AsyncMock(
                    return_value={
                        "status": "pending",
                        "batch_id": "batch-pending",
                        "pdf_path": "G:/AIResearch/output/mineru/2602.99999/source.pdf",
                    }
                ),
                create=True,
            ),
        ):
            prepared = anyio.run(orch_impl._prepare_paper, paper, set(), {})

        self.assertIsNone(prepared)

    def test_prepare_paper_falls_back_to_latex_after_mineru_failure(self) -> None:
        paper = _build_paper()
        with (
            patch.object(orch_impl, "passes_filters", AsyncMock(return_value=(True, 0.0, False))),
            patch.object(
                orch_impl,
                "prepare_pdf_markdown",
                AsyncMock(side_effect=RuntimeError("MinerU attempts exhausted")),
                create=True,
            ),
            patch.object(
                orch_impl,
                "fetch_latex_source",
                AsyncMock(
                    return_value={
                        "tex_path": "G:/AIResearch/output/latex/2602.99999/main.tex",
                        "tex_files": ["G:/AIResearch/output/latex/2602.99999/main.tex"],
                    }
                ),
            ),
            patch.object(
                orch_impl.latex_reader,
                "read_latex_tree",
                return_value=("Fallback LaTeX Source", ["G:/AIResearch/output/latex/2602.99999/main.tex"]),
            ),
        ):
            prepared = anyio.run(orch_impl._prepare_paper, paper, set(), {})

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual("latex_fallback", prepared.source_backend)
        self.assertEqual("Fallback LaTeX Source", prepared.source_markdown)
        self.assertTrue(prepared.source_path.endswith("main.tex"))

    def test_run_pipeline_fails_when_mineru_key_missing(self) -> None:
        paper = _build_paper()
        window = orch_impl.DateWindow(
            start_date=datetime(2026, 2, 1, tzinfo=timezone.utc).date(),
            end_date=datetime(2026, 2, 2, tzinfo=timezone.utc).date(),
        )

        with (
            patch.object(orch_impl, "load_whitelist", return_value=set()),
            patch.object(orch_impl, "load_super_whitelist", return_value={}),
            patch.object(orch_impl, "discover_papers", AsyncMock(return_value=[paper])),
            patch.object(orch_impl, "apply_stage1_prefilter", side_effect=lambda entries: entries),
            patch.object(
                orch_impl,
                "_prepare_paper",
                AsyncMock(side_effect=RuntimeError("MINERU_API_KEY environment variable is required")),
            ),
            patch.object(orch_impl, "PAPER_EVAL_CONCURRENCY", 1),
        ):
            with self.assertRaisesRegex(RuntimeError, "MINERU_API_KEY"):
                anyio.run(orch_impl.run_pipeline, window)

    def test_codex_generate_email_analysis_uses_existing_scored_markdown_without_codex(self) -> None:
        paper = _build_paper()
        scored_result = {
            "email_body_markdown": "## Email\n- rendered once",
        }
        run_mock = AsyncMock(side_effect=AssertionError("email analysis should not call codex"))

        async def _invoke():
            return await orch_impl.codex_generate_email_analysis(
                paper,
                "source markdown is not needed here",
                "Short summary",
                "Long summary",
                scored_result=scored_result,
            )

        with patch.object(orch_impl, "_run_codex_json", run_mock):
            out = anyio.run(_invoke)

        self.assertEqual("## Email\n- rendered once", out)
        self.assertEqual(0, run_mock.await_count)


    def test_process_paper_skips_side_effects_when_candidate_gate_rejects(self) -> None:
        paper = _build_paper()
        prepared = _build_prepared(paper)
        gate_mock = AsyncMock(return_value={
            "mode": "codex",
            "scores": {"relevance_score": 1.5, "evidence_score": 2.0},
            "weighted_score": 2.1,
            "passed": False,
            "reason": "domain paper only",
        })
        codex_result = {
            "chunk_summaries": ["summary item"],
            "methods_loss": ["loss item"],
            "hyperparams": ["lr=1e-4"],
            "evidence_notes": ["ablation included"],
            "github_urls": [],
            "primary_github_url": "",
            "recommendation_score": 8,
            "recommendation_reason": "Strong evidence",
            "direction_tags": ["rlvr"],
            "tldr": "Short summary",
            "summary": "Longer summary",
            "email_body_markdown": "## Email\n- already rendered",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(orch_impl, "evaluate_candidate_gate", gate_mock),
                patch.object(orch_impl, "codex_process_paper", AsyncMock(return_value=codex_result)) as process_mock,
                patch.object(orch_impl, "check_reproducibility", AsyncMock(return_value=("Tier: U (Unknown)", []))) as repro_mock,
                patch.object(orch_impl, "save_to_obsidian", AsyncMock()) as save_mock,
                patch.object(orch_impl, "codex_generate_email_analysis", AsyncMock(return_value="## Email\n- rendered")) as email_mock,
                patch.object(orch_impl, "notify", AsyncMock()) as notify_mock,
            ):
                out = anyio.run(orch_impl._process_paper, prepared, Path(tmpdir))

        self.assertEqual(set(), out)
        gate_mock.assert_awaited_once()
        process_mock.assert_not_awaited()
        repro_mock.assert_not_awaited()
        save_mock.assert_not_awaited()
        email_mock.assert_not_awaited()
        notify_mock.assert_not_awaited()

    def test_process_paper_notifies_after_candidate_gate_passes(self) -> None:
        paper = _build_paper()
        prepared = _build_prepared(paper)
        gate_mock = AsyncMock(return_value={
            "mode": "codex",
            "scores": {"relevance_score": 4.4, "evidence_score": 4.2},
            "weighted_score": 4.3,
            "passed": True,
            "reason": "core direction fit",
        })
        codex_result = {
            "chunk_summaries": ["summary item"],
            "methods_loss": ["loss item"],
            "hyperparams": ["lr=1e-4"],
            "evidence_notes": ["ablation included"],
            "github_urls": [],
            "primary_github_url": "",
            "recommendation_score": 8,
            "recommendation_reason": "Strong evidence",
            "direction_tags": ["rlvr"],
            "tldr": "Short summary",
            "summary": "Longer summary",
            "email_body_markdown": "## Email\n- already rendered",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(orch_impl, "evaluate_candidate_gate", gate_mock),
                patch.object(orch_impl, "codex_process_paper", AsyncMock(return_value=codex_result)) as process_mock,
                patch.object(orch_impl, "check_reproducibility", AsyncMock(return_value=("Tier: U (Unknown)", []))) as repro_mock,
                patch.object(orch_impl, "save_to_obsidian", AsyncMock()) as save_mock,
                patch.object(orch_impl, "codex_generate_email_analysis", AsyncMock(return_value="## Email\n- rendered")) as email_mock,
                patch.object(orch_impl, "notify", AsyncMock()) as notify_mock,
            ):
                out = anyio.run(orch_impl._process_paper, prepared, Path(tmpdir))

        self.assertEqual({paper.canonical_id, paper.paper_id}, out)
        gate_mock.assert_awaited_once()
        process_mock.assert_awaited_once()
        repro_mock.assert_awaited_once()
        save_mock.assert_awaited_once()
        email_mock.assert_awaited_once()
        notify_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
