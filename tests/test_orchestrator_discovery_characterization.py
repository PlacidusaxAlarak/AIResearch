from datetime import date
import unittest
from unittest.mock import patch

import anyio

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorDiscoveryCharacterization(unittest.TestCase):
    def test_discovery_chunks_queries_and_merges_trending(self) -> None:
        window = orch_impl.DateWindow(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))

        arxiv_item = {
            "id": "2602.00001v1",
            "title": "TTS Paper",
            "summary": "test-time scaling",
            "authors": ["Alice"],
            "url": "https://arxiv.org/abs/2602.00001v1",
            "pdf_url": "https://arxiv.org/pdf/2602.00001v1.pdf",
            "published": "2026-02-10T00:00:00Z",
        }
        hf_item = {
            "id": "2602.00001",
            "title": "TTS Paper",
            "abstract": "test-time scaling",
            "authors": ["Alice"],
            "url": "https://huggingface.co/papers/2602.00001",
            "pdf_url": "https://arxiv.org/pdf/2602.00001.pdf",
            "published": "2026-02-10T00:00:00Z",
            "submitted_on_daily": "2026-02-10T00:00:00Z",
            "score": 10,
        }

        with (
            patch.object(
                orch_impl,
                "KEYWORDS",
                ["k1", "k2", "k3", "k4", "k5"],
            ),
            patch.object(orch_impl, "ARXIV_QUERY_MAX_TERMS", 2),
            patch.object(orch_impl, "ARXIV_MAX_RESULTS_PER_QUERY", 10),
            patch.object(orch_impl, "HF_TRENDING_LIMIT", 10),
            patch.object(orch_impl, "HF_DATE_FIELD", "submitted_on_daily"),
            patch.object(orch_impl, "DAYS_BACK", 7),
            patch.object(orch_impl.arxiv_mcp, "search", return_value=[arxiv_item]) as mocked_arxiv,
            patch.object(orch_impl.hf_papers_mcp, "papers_search", return_value=[hf_item]) as mocked_hf_daily,
            patch.object(orch_impl.hf_papers_mcp, "papers_trending", return_value=[hf_item]) as mocked_hf_trending,
        ):
            out = anyio.run(orch_impl.discover_papers, window)

        self.assertEqual(3, mocked_arxiv.call_count)  # 5 terms with chunk size 2 => 3 queries
        self.assertEqual(3, mocked_hf_daily.call_count)
        mocked_hf_trending.assert_called_once()

        self.assertEqual(1, len(out))
        paper = out[0]
        self.assertIn("arxiv", paper.source_tags)
        self.assertIn("hf_papers", paper.source_tags)
        self.assertIn("hf_trending", paper.source_tags)
        self.assertEqual("2602.00001", paper.canonical_id)


if __name__ == "__main__":
    unittest.main()

