from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import anyio

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorCandidateGateCharacterization(unittest.TestCase):
    def _build_entry(self, year: int = 2025, stage1_score: float = 4.0, topic_score: float = 3.0) -> dict:
        paper = orch_impl.Paper(
            paper_id=f"{year}01.00001",
            canonical_id=f"{year}01.00001",
            title="Test-Time Scaling with PRM",
            authors=["Alice"],
            abstract="test-time scaling and process reward model",
            url=f"https://arxiv.org/abs/{year}01.00001",
            pdf_url=f"https://arxiv.org/pdf/{year}01.00001.pdf",
            published=datetime(year, 1, 1, tzinfo=timezone.utc),
            source="arxiv",
            source_tags={"arxiv"},
            hf_score=5.0,
        )
        return {
            "paper": paper,
            "stage1_score": stage1_score,
            "topic_score": topic_score,
            "coverage_score": 0.6,
            "super_whitelist_hit": False,
        }

    def test_candidate_gate_heuristic_fallback_when_prompt_missing(self) -> None:
        entry = self._build_entry()
        with (
            patch.object(orch_impl, "CODEX_PROMPT_CANDIDATE_PATH", Path("missing_prompt.txt")),
            patch.object(orch_impl, "CODEX_CANDIDATE_SCORE_THRESHOLD", 0.1),
            patch.object(orch_impl, "CANDIDATE_RELEVANCE_MIN", 1.0),
            patch.object(orch_impl, "CANDIDATE_EVIDENCE_MIN", 1.0),
        ):
            out = anyio.run(
                orch_impl.evaluate_candidate_gate,
                entry,
                "We propose a new process reward model with benchmark and ablation results.",
            )
        self.assertEqual("heuristic", out["mode"])
        self.assertIn("weighted_score", out)
        self.assertTrue(out["passed"])

    def test_candidate_gate_respects_weighted_threshold(self) -> None:
        entry = self._build_entry(stage1_score=0.0, topic_score=0.0)
        with (
            patch.object(orch_impl, "CODEX_PROMPT_CANDIDATE_PATH", Path("missing_prompt.txt")),
            patch.object(orch_impl, "CODEX_CANDIDATE_SCORE_THRESHOLD", 4.8),
            patch.object(orch_impl, "CANDIDATE_RELEVANCE_MIN", 1.0),
            patch.object(orch_impl, "CANDIDATE_EVIDENCE_MIN", 1.0),
        ):
            out = anyio.run(
                orch_impl.evaluate_candidate_gate,
                entry,
                "short note without benchmark evidence",
            )
        self.assertFalse(out["passed"])
        self.assertLess(out["weighted_score"], 4.8)

    def test_candidate_gate_rejects_missing_clean_text(self) -> None:
        entry = self._build_entry()
        out = anyio.run(orch_impl.evaluate_candidate_gate, entry, "")
        self.assertFalse(out["passed"])
        self.assertEqual("missing_clean_text", out["mode"])


if __name__ == "__main__":
    unittest.main()
