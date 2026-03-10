from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import anyio

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorSuperWhitelistCharacterization(unittest.TestCase):
    def test_super_whitelist_match_without_force_notify_override(self) -> None:
        paper = orch_impl.Paper(
            paper_id="2602.10001",
            canonical_id="2602.10001",
            title="RLVR Study at OpenAI",
            authors=["Alice Smith"],
            abstract="This work studies RLVR at OpenAI with verifier rewards.",
            url="https://arxiv.org/abs/2602.10001",
            pdf_url="https://arxiv.org/pdf/2602.10001.pdf",
            published=datetime(2026, 2, 10, tzinfo=timezone.utc),
            source="arxiv",
            source_tags={"arxiv"},
            hf_score=0.0,
        )
        hit, reasons = orch_impl.super_whitelist_hit(
            paper,
            {
                "authors": {"alice smith"},
                "institutions": {"openai"},
            },
        )
        self.assertTrue(hit)
        self.assertTrue(any(reason.startswith("author:") for reason in reasons))

        entry = {
            "paper": paper,
            "topic_score": 0.0,
            "stage1_score": -10.0,
            "coverage_score": 0.0,
            "super_whitelist_hit": True,
        }
        with (
            patch.object(orch_impl, "CODEX_PROMPT_CANDIDATE_PATH", Path("missing_prompt.txt")),
            patch.object(orch_impl, "CODEX_CANDIDATE_SCORE_THRESHOLD", 5.0),
        ):
            out = anyio.run(orch_impl.evaluate_candidate_gate, entry, "")
        self.assertFalse(out["passed"])


if __name__ == "__main__":
    unittest.main()
