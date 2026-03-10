from datetime import datetime, timezone
import unittest

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorDateWindowCharacterization(unittest.TestCase):
    def test_explicit_start_end_override_days_back(self) -> None:
        window = orch_impl._resolve_date_window(3, "2026-02-01", "2026-02-10")
        self.assertEqual("2026-02-01", window.start_date.isoformat())
        self.assertEqual("2026-02-10", window.end_date.isoformat())
        self.assertEqual(10, orch_impl._window_days(window))

    def test_days_back_effective_when_explicit_range_missing(self) -> None:
        window = orch_impl._resolve_date_window(5, None, None)
        self.assertEqual(5, orch_impl._window_days(window))

    def test_partial_date_range_is_invalid(self) -> None:
        with self.assertRaises(ValueError):
            orch_impl._resolve_date_window(None, "2026-02-01", None)

    def test_window_filters_by_configured_field(self) -> None:
        window = orch_impl.DateWindow(
            start_date=orch_impl._parse_cli_date("2026-02-01"),
            end_date=orch_impl._parse_cli_date("2026-02-10"),
        )
        inside = orch_impl.Paper(
            paper_id="2602.00001",
            canonical_id="2602.00001",
            title="inside",
            authors=[],
            abstract="",
            url="",
            pdf_url="",
            published=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="hf_papers",
            source_tags={"hf_papers"},
            hf_score=1.0,
            submitted_on_daily=datetime(2026, 2, 3, tzinfo=timezone.utc),
        )
        outside = orch_impl.Paper(
            paper_id="2601.00001",
            canonical_id="2601.00001",
            title="outside",
            authors=[],
            abstract="",
            url="",
            pdf_url="",
            published=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="hf_papers",
            source_tags={"hf_papers"},
            hf_score=1.0,
            submitted_on_daily=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(orch_impl._paper_in_date_window(inside, window, "submitted_on_daily"))
        self.assertFalse(orch_impl._paper_in_date_window(outside, window, "submitted_on_daily"))


if __name__ == "__main__":
    unittest.main()

