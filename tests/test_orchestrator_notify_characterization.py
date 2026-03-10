from datetime import datetime, timezone
from pathlib import Path
import subprocess
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

import anyio

from airesearch.cli import orchestrator as orch_impl


def _build_paper() -> orch_impl.Paper:
    return orch_impl.Paper(
        paper_id="2602.88888",
        canonical_id="2602.88888",
        title="Notify Test",
        authors=["Alice", "Bob"],
        abstract="Test abstract.",
        url="https://arxiv.org/abs/2602.88888",
        pdf_url="https://arxiv.org/pdf/2602.88888.pdf",
        published=datetime(2026, 2, 1, tzinfo=timezone.utc),
        source="arxiv",
        source_tags={"arxiv"},
        hf_score=0.0,
    )


async def _run_sync_passthrough(fn, **kwargs):
    return fn(**kwargs)


def _fake_download(pdf_url: str, output_path: Path, timeout_sec: int = 120) -> Path:
    _ = pdf_url
    _ = timeout_sec
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"%PDF-1.4\nfake")
    return output_path


def _workspace_tempdir():
    temp_root = orch_impl.REPO_ROOT / ".tmp" / "pytest-notify"
    temp_root.mkdir(parents=True, exist_ok=True)
    case_dir = temp_root / f"case_{uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=False)
    return case_dir


class TestOrchestratorNotifyCharacterization(unittest.TestCase):
    def test_notify_smtp_script_receives_attachments_argument(self) -> None:
        paper = _build_paper()
        root = _workspace_tempdir()
        run_dir = root / "out"
        script = root / "scripts" / "send_email_from_body.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# placeholder\n", encoding="utf-8")
        config = root / "config.local.yaml"
        config.write_text("email_recipients: []\n", encoding="utf-8")

        with (
            patch.object(orch_impl, "EMAIL_RECIPIENTS", ["user@example.com"]),
            patch.object(orch_impl, "BASE_DIR", root),
            patch.object(orch_impl, "CONFIG_PATH", config),
            patch.object(orch_impl, "run_sync", AsyncMock(side_effect=_run_sync_passthrough)),
            patch.object(orch_impl, "_download_pdf_attachment_sync", side_effect=_fake_download),
            patch(
                "airesearch.cli.orchestrator.subprocess.run",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ) as subprocess_mock,
        ):
            anyio.run(
                orch_impl.notify,
                paper,
                "TLDR",
                "### 创新点\n- A\n\n### 哪里值得看\n- B\n\n### 文章概括\n- C",
                "Tier: S (Full Trainer)",
                8,
                "strong",
                run_dir,
            )
        cmd = subprocess_mock.call_args.args[0]
        self.assertIn("--attachments", cmd)
        attachment_arg = cmd[cmd.index("--attachments") + 1]
        self.assertTrue(attachment_arg.endswith(".pdf"))

    def test_notify_fallback_mcp_still_receives_attachments(self) -> None:
        paper = _build_paper()
        root = _workspace_tempdir()
        run_dir = root / "out"
        script = root / "scripts" / "send_email_from_body.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# placeholder\n", encoding="utf-8")
        config = root / "config.local.yaml"
        config.write_text("email_recipients: []\n", encoding="utf-8")
        email_send_mock = Mock(return_value={"ok": True})

        with (
            patch.object(orch_impl, "EMAIL_RECIPIENTS", ["user@example.com"]),
            patch.object(orch_impl, "BASE_DIR", root),
            patch.object(orch_impl, "CONFIG_PATH", config),
            patch.object(orch_impl, "run_sync", AsyncMock(side_effect=_run_sync_passthrough)),
            patch.object(orch_impl, "_download_pdf_attachment_sync", side_effect=_fake_download),
            patch(
                "airesearch.cli.orchestrator.subprocess.run",
                return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="smtp boom"),
            ),
            patch.object(orch_impl.email_mcp, "send_email", email_send_mock),
        ):
            anyio.run(
                orch_impl.notify,
                paper,
                "TLDR",
                "### 创新点\n- A\n\n### 哪里值得看\n- B\n\n### 文章概括\n- C",
                "Tier: S (Full Trainer)",
                8,
                "strong",
                run_dir,
            )
        self.assertTrue(email_send_mock.called)
        attachments = email_send_mock.call_args.kwargs.get("attachments", [])
        self.assertEqual(1, len(attachments))
        self.assertTrue(str(attachments[0]).endswith(".pdf"))

    def test_notify_download_failure_keeps_sending_and_marks_body(self) -> None:
        paper = _build_paper()
        root = _workspace_tempdir()
        run_dir = root / "out"
        script = root / "scripts" / "send_email_from_body.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# placeholder\n", encoding="utf-8")
        config = root / "config.local.yaml"
        config.write_text("email_recipients: []\n", encoding="utf-8")

        with (
            patch.object(orch_impl, "EMAIL_RECIPIENTS", ["user@example.com"]),
            patch.object(orch_impl, "BASE_DIR", root),
            patch.object(orch_impl, "CONFIG_PATH", config),
            patch.object(orch_impl, "run_sync", AsyncMock(side_effect=_run_sync_passthrough)),
            patch.object(
                orch_impl,
                "_download_pdf_attachment_sync",
                side_effect=RuntimeError("download failed"),
            ),
            patch(
                "airesearch.cli.orchestrator.subprocess.run",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ) as subprocess_mock,
        ):
            anyio.run(
                orch_impl.notify,
                paper,
                "TLDR",
                "### 创新点\n- A\n\n### 哪里值得看\n- B\n\n### 文章概括\n- C",
                "Tier: U (Unknown)",
                6,
                "baseline",
                run_dir,
            )
        cmd = subprocess_mock.call_args.args[0]
        self.assertNotIn("--attachments", cmd)
        body_file = Path(cmd[cmd.index("--body-file") + 1])
        body = body_file.read_text(encoding="utf-8")
        self.assertIn("PDF附件下载失败", body)


if __name__ == "__main__":
    unittest.main()
