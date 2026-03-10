from datetime import datetime, timezone
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


def _fake_prompt_loader(path):
    if path == orch_impl.CODEX_PROMPT_CHUNK_PATH:
        return "Chunk prompt\nTitle: {title}\nText:\n{chunk}\n"
    if path == orch_impl.CODEX_PROMPT_SCORE_PATH:
        return (
            "Score prompt\nTitle: {title}\nExcerpt:\n{clean_fulltext_excerpt}\n"
            "Summaries:\n{chunk_summaries}\n"
        )
    if path == orch_impl.CODEX_PROMPT_CLEAN_PATH:
        return "Clean prompt\nFull text:\n{chunk}\n"
    if path == orch_impl.CODEX_PROMPT_MARKDOWN_PATH:
        return (
            "Email analysis prompt\nTitle: {title}\nAuthors: {authors}\n"
            "Abstract:\n{abstract}\nCleaned:\n{clean_text}\nCompat:\n{chunk}\n"
        )
    raise RuntimeError(f"Unexpected prompt path in test: {path}")


class TestOrchestratorSinglePassCharacterization(unittest.TestCase):
    def test_clean_latex_fulltext_single_pass_uses_full_input(self) -> None:
        paper = _build_paper()
        latex_text = "LATEX-" + ("A" * 13050) + "-TAIL"
        run_mock = AsyncMock(return_value={"clean_text": "cleaned content"})
        with (
            patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
            patch.object(orch_impl, "_run_codex_json", run_mock),
        ):
            out = anyio.run(orch_impl.clean_latex_fulltext, paper, latex_text)

        self.assertEqual("cleaned content", out)
        self.assertEqual(1, run_mock.await_count)
        sent_prompt = run_mock.await_args_list[0].args[0]
        self.assertIn(latex_text, sent_prompt)

    def test_codex_process_paper_single_pass_extract_and_score(self) -> None:
        paper = _build_paper()
        clean_text = "CLEAN-" + ("B" * 41050) + "-END"
        run_mock = AsyncMock(
            side_effect=[
                {
                    "chunk_summary": ["summary item"],
                    "methods_loss": ["loss item"],
                    "hyperparams": ["lr=1e-4"],
                    "evidence_notes": ["ablation included"],
                    "github_urls": ["https://github.com/acme/repo"],
                },
                {
                    "github_urls": ["https://github.com/acme/repo"],
                    "primary_github_url": "https://github.com/acme/repo",
                    "recommendation_score": 8,
                    "recommendation_reason": "Strong evidence",
                    "direction_tags": ["inference-scaling"],
                    "tldr": "Short summary",
                    "summary": "Longer summary",
                },
            ]
        )
        with (
            patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
            patch.object(orch_impl, "_run_codex_json", run_mock),
        ):
            out = anyio.run(orch_impl.codex_process_paper, paper, clean_text)

        self.assertEqual(2, run_mock.await_count)
        extract_prompt = run_mock.await_args_list[0].args[0]
        score_prompt = run_mock.await_args_list[1].args[0]
        self.assertIn(clean_text, extract_prompt)
        self.assertIn(clean_text, score_prompt)
        self.assertEqual(8, out["recommendation_score"])
        self.assertEqual("https://github.com/acme/repo", out["primary_github_url"])
        self.assertEqual(["summary item"], out["chunk_summaries"])

    def test_codex_process_paper_extract_failure_is_strict(self) -> None:
        paper = _build_paper()
        clean_text = "CLEAN-" + ("X" * 15000)
        run_mock = AsyncMock(side_effect=RuntimeError("extract boom"))
        with (
            patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
            patch.object(orch_impl, "_run_codex_json", run_mock),
        ):
            with self.assertRaisesRegex(RuntimeError, "single-pass extract failed"):
                anyio.run(orch_impl.codex_process_paper, paper, clean_text)

    def test_codex_process_paper_score_failure_is_strict(self) -> None:
        paper = _build_paper()
        clean_text = "CLEAN-" + ("Y" * 15000)
        run_mock = AsyncMock(
            side_effect=[
                {
                    "chunk_summary": ["summary item"],
                    "methods_loss": [],
                    "hyperparams": [],
                    "evidence_notes": [],
                    "github_urls": [],
                },
                RuntimeError("score boom"),
            ]
        )
        with (
            patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
            patch.object(orch_impl, "_run_codex_json", run_mock),
        ):
            with self.assertRaisesRegex(RuntimeError, "single-pass score failed"):
                anyio.run(orch_impl.codex_process_paper, paper, clean_text)

    def test_codex_generate_email_analysis_uses_full_clean_text(self) -> None:
        paper = _build_paper()
        clean_text = "CLEAN-" + ("Z" * 36000) + "-END"
        expected = "### 创新点\n- A\n\n### 哪里值得看\n- B\n\n### 文章概括\n- C"
        run_mock = AsyncMock(return_value={"email_body_markdown": expected})
        with (
            patch.object(orch_impl, "_load_prompt", side_effect=_fake_prompt_loader),
            patch.object(orch_impl, "_run_codex_json", run_mock),
        ):
            out = anyio.run(
                orch_impl.codex_generate_email_analysis,
                paper,
                clean_text,
                "Short summary",
                "Long summary",
            )

        self.assertEqual(expected, out)
        self.assertEqual(1, run_mock.await_count)
        sent_prompt = run_mock.await_args_list[0].args[0]
        self.assertIn(clean_text, sent_prompt)

    def test_apply_config_chunk_params_are_deprecated_and_ignored(self) -> None:
        with (
            patch.object(orch_impl, "CODEX_CHUNK_CHARS", 12000),
            patch.object(orch_impl, "CODEX_CHUNK_OVERLAP", 800),
            patch.object(orch_impl, "_log") as log_mock,
        ):
            orch_impl.apply_config({"codex_chunk_chars": 3000, "codex_chunk_overlap": 100})
            self.assertEqual(12000, orch_impl.CODEX_CHUNK_CHARS)
            self.assertEqual(800, orch_impl.CODEX_CHUNK_OVERLAP)

        warn_messages = [
            call.args[1]
            for call in log_mock.call_args_list
            if len(call.args) >= 2 and call.args[0] == "WARN"
        ]
        self.assertTrue(any("codex_chunk_chars is deprecated and ignored" in msg for msg in warn_messages))
        self.assertTrue(any("codex_chunk_overlap is deprecated and ignored" in msg for msg in warn_messages))


if __name__ == "__main__":
    unittest.main()
