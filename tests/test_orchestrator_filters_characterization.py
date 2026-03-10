import unittest
from datetime import datetime, timedelta, timezone

import anyio
from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorFiltersCharacterization(unittest.TestCase):
    def test_parse_github_repo_and_select_urls(self) -> None:
        repo = orch_impl.parse_github_repo("https://github.com/owner/repo.git/issues")
        self.assertEqual(("owner", "repo"), repo)

        selected = orch_impl.select_github_urls(
            "https://github.com/a/b",
            [
                "https://github.com/a/b/",
                "https://github.com/c/d",
                "https://not-github.com/e/f",
                "https://github.com/e/f",
            ],
            max_count=2,
        )
        self.assertEqual(["https://github.com/a/b", "https://github.com/c/d"], selected)

    def test_combine_tiers(self) -> None:
        self.assertEqual(
            "Tier: S (Full Trainer)",
            orch_impl.combine_tiers(["Tier: C (Demo Only)", "Tier: S (Full Trainer)"]),
        )
        self.assertEqual("Tier: U (No Code Link)", orch_impl.combine_tiers([]))

    def test_chunk_text_respects_overlap(self) -> None:
        chunks = orch_impl._chunk_text("abcdefghij", chunk_size=5, overlap=2)
        self.assertEqual(["abcde", "defgh", "ghij"], chunks)

    def test_compute_topic_score_nonzero_for_keywords(self) -> None:
        text = "post-training methods with rl agent and tool use"
        self.assertGreater(orch_impl.compute_topic_score(text), 0)

    def test_stage1_frontier_year_rank_higher(self) -> None:
        recent = orch_impl.Paper(
            paper_id="2601.00001",
            canonical_id="2601.00001",
            title="Test-Time Scaling for RL",
            authors=["Alice"],
            abstract="test-time scaling and process reward model",
            url="https://arxiv.org/abs/2601.00001",
            pdf_url="https://arxiv.org/pdf/2601.00001.pdf",
            published=datetime(2025, 1, 1, tzinfo=timezone.utc),
            source="arxiv",
            source_tags={"arxiv"},
            hf_score=0.0,
        )
        old = orch_impl.Paper(
            paper_id="2101.00001",
            canonical_id="2101.00001",
            title="Test-Time Scaling for RL",
            authors=["Alice"],
            abstract="test-time scaling and process reward model",
            url="https://arxiv.org/abs/2101.00001",
            pdf_url="https://arxiv.org/pdf/2101.00001.pdf",
            published=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="arxiv",
            source_tags={"arxiv"},
            hf_score=0.0,
        )
        recent_clean_text = (
            "we propose test-time scaling with process reward model benchmark ablation evaluation"
        )
        old_clean_text = "generic optimization note"
        recent_score = orch_impl.compute_stage1_score(recent_clean_text)["stage1_score"]
        old_score = orch_impl.compute_stage1_score(old_clean_text)["stage1_score"]
        self.assertGreater(recent_score, old_score)

    def test_passes_filters_new_paper_social_disabled(self) -> None:
        paper = orch_impl.Paper(
            paper_id="2602.20001",
            canonical_id="2602.20001",
            title="Social Filter Disabled",
            authors=["Alice"],
            abstract="test-time scaling",
            url="https://arxiv.org/abs/2602.20001",
            pdf_url="https://arxiv.org/pdf/2602.20001.pdf",
            published=datetime.now(timezone.utc) - timedelta(days=1),
            source="arxiv",
            source_tags={"arxiv"},
            hf_score=0.0,
        )
        passed, citation_velocity, whitelisted = anyio.run(orch_impl.passes_filters, paper, set())
        self.assertTrue(passed)
        self.assertEqual(0.0, citation_velocity)
        self.assertFalse(whitelisted)


if __name__ == "__main__":
    unittest.main()
