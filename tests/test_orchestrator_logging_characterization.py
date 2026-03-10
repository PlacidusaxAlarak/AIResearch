import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import anyio

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorLoggingCharacterization(unittest.TestCase):
    def tearDown(self) -> None:
        orch_impl._close_log_file()
        orch_impl.LOG_FILE_PATH = None

    def test_configure_logging_writes_log_lines(self) -> None:
        orch_impl._close_log_file()
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.log"
            orch_impl.configure_logging(str(log_path))
            orch_impl._log("INFO", "hello")
            orch_impl._close_log_file()

            text = log_path.read_text(encoding="utf-8")
            self.assertIn("AIResearch run start", text)
            self.assertIn("hello", text)

    def test_log_exception_writes_traceback(self) -> None:
        orch_impl._close_log_file()
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "exc.log"
            orch_impl.configure_logging(str(log_path))
            try:
                raise RuntimeError("boom")
            except Exception as exc:
                orch_impl._log_exception("ctx", exc)
            orch_impl._close_log_file()

            text = log_path.read_text(encoding="utf-8")
            self.assertIn("ctx", text)
            self.assertIn("RuntimeError", text)
            self.assertIn("boom", text)
            self.assertIn("Traceback", text)

    def test_run_pipeline_writes_latest_run_pointers_on_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "output"
            window = orch_impl.DateWindow(start_date=date(2026, 2, 22), end_date=date(2026, 2, 22))

            with (
                patch.object(orch_impl, "OUTPUT_ROOT", output_root),
                patch.object(orch_impl, "discover_papers", AsyncMock(return_value=[])),
                patch.object(orch_impl, "load_whitelist", return_value=set()),
                patch.object(orch_impl, "load_super_whitelist", return_value={}),
            ):
                anyio.run(orch_impl.run_pipeline, window)

            latest_json_path = output_root / "out" / "latest_run.json"
            latest_payload = json.loads(latest_json_path.read_text(encoding="utf-8"))

            run_dir = Path(latest_payload["run_dir"])
            self.assertTrue(run_dir.exists())

            summary_path = run_dir / "run_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual("ok", summary["status"])
            self.assertEqual(0, summary["discovered_count"])
            self.assertEqual(0, summary["shortlist_count"])
            self.assertEqual(0, summary["processed_count"])


if __name__ == "__main__":
    unittest.main()

