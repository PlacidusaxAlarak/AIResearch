import io
import json
import os
import ssl
import subprocess
import tempfile
import urllib.error
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from airesearch.core import mineru_pdf


class _FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type
        _ = exc
        _ = tb


def _zip_with_markdown(markdown_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("paper/content.md", markdown_text)
    return buf.getvalue()


class TestMineruPdfCharacterization(unittest.TestCase):
    def test_json_request_uses_curl_fallback_after_wrapped_tls_failure(self) -> None:
        wrapped_exc = urllib.error.URLError(ssl.SSLEOFError("EOF occurred in violation of protocol"))
        payload = {
            "data": {
                "batch_id": "batch-wrapped",
                "file_urls": ["https://upload.example.com/wrapped.pdf"],
            }
        }

        with (
            patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=wrapped_exc),
            patch.object(
                mineru_pdf.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["curl.exe"],
                    returncode=0,
                    stdout=json.dumps(payload),
                    stderr="",
                ),
            ) as curl_mock,
        ):
            result = mineru_pdf._json_request(
                "https://mineru.net/api/v4/file-urls/batch",
                headers={"Authorization": "Bearer token-123", "User-Agent": "AIResearch/1.0"},
                method="POST",
                payload={"files": [{"name": "paper.pdf", "source": "2603.00000"}]},
                timeout_sec=30,
            )

        self.assertEqual(payload, result)
        curl_cmd = curl_mock.call_args.args[0]
        self.assertEqual("curl.exe", curl_cmd[0])
        self.assertIn("--http1.1", curl_cmd)
        self.assertIn("https://mineru.net/api/v4/file-urls/batch", curl_cmd)

    def test_upload_pdf_uses_curl_fallback_after_wrapped_tls_failure(self) -> None:
        wrapped_exc = urllib.error.URLError(ssl.SSLEOFError("EOF occurred in violation of protocol"))

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfake")

            with (
                patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=wrapped_exc),
                patch.object(
                    mineru_pdf.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(args=["curl.exe"], returncode=0, stdout="", stderr=""),
                ) as curl_mock,
            ):
                mineru_pdf._upload_pdf("https://upload.example.com/wrapped.pdf", pdf_path, timeout_sec=30)

        curl_cmd = curl_mock.call_args.args[0]
        self.assertEqual("curl.exe", curl_cmd[0])
        self.assertIn("--http1.1", curl_cmd)
        self.assertIn("https://upload.example.com/wrapped.pdf", curl_cmd)

    def test_convert_pdf_to_markdown_requires_mineru_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MINERU_API_KEY"):
                    mineru_pdf.convert_pdf_to_markdown(
                        canonical_id="2603.00001",
                        pdf_url="https://arxiv.org/pdf/2603.00001.pdf",
                        output_root=output_root,
                        state_root=state_root,
                    )

    def test_convert_pdf_to_markdown_requires_mineru_api_key_even_when_markdown_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            extract_dir = output_root / "2603.00001-cache" / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            (extract_dir / "content.md").write_text("# Cached Markdown", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MINERU_API_KEY"):
                    mineru_pdf.convert_pdf_to_markdown(
                        canonical_id="2603.00001-cache",
                        pdf_url="https://arxiv.org/pdf/2603.00001-cache.pdf",
                        output_root=output_root,
                        state_root=state_root,
                    )

    def test_convert_pdf_to_markdown_uses_bearer_token_and_extracts_markdown(self) -> None:
        requests: list[tuple[str, str, dict[str, str]]] = []
        zip_bytes = _zip_with_markdown("# Parsed Markdown\n\nBody text")

        def _urlopen(req, timeout=0):  # noqa: ANN001
            _ = timeout
            if isinstance(req, str):
                url = req
                method = "GET"
                headers = {}
            else:
                url = req.full_url
                method = req.get_method()
                headers = dict(req.header_items())
            requests.append((method, url, headers))

            if url == "https://arxiv.org/pdf/2603.00002.pdf":
                return _FakeResponse(b"%PDF-1.4\nfake")
            if url.endswith("/api/v4/file-urls/batch"):
                payload = {
                    "data": {
                        "batch_id": "batch-123",
                        "file_urls": ["https://upload.example.com/file.pdf"],
                    }
                }
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            if url == "https://upload.example.com/file.pdf":
                return _FakeResponse(b"")
            if url.endswith("/api/v4/extract-results/batch/batch-123"):
                payload = {
                    "data": {
                        "extract_result": [
                            {
                                "state": "done",
                                "full_zip_url": "https://download.example.com/result.zip",
                            }
                        ]
                    }
                }
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            if url == "https://download.example.com/result.zip":
                return _FakeResponse(zip_bytes)
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            with (
                patch.dict(os.environ, {"MINERU_API_KEY": "token-123"}, clear=True),
                patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=_urlopen),
            ):
                result = mineru_pdf.convert_pdf_to_markdown(
                    canonical_id="2603.00002",
                    pdf_url="https://arxiv.org/pdf/2603.00002.pdf",
                    output_root=output_root,
                    state_root=state_root,
                    poll_interval_sec=0,
                    per_run_timeout_sec=30,
                )
                markdown_path = Path(result["markdown_path"])
                self.assertTrue(markdown_path.exists())
                self.assertIn("Parsed Markdown", markdown_path.read_text(encoding="utf-8"))

        batch_requests = [item for item in requests if item[1].endswith("/api/v4/file-urls/batch")]
        self.assertEqual(1, len(batch_requests))
        self.assertEqual("Bearer token-123", batch_requests[0][2]["Authorization"])
        self.assertEqual("done", result["status"])

    def test_convert_pdf_to_markdown_keeps_batch_id_after_pending_timeout(self) -> None:
        def _urlopen(req, timeout=0):  # noqa: ANN001
            _ = timeout
            if isinstance(req, str):
                url = req
                method = "GET"
            else:
                url = req.full_url
                method = req.get_method()

            if url.endswith("/api/v4/extract-results/batch/batch-pending"):
                payload = {
                    "data": {
                        "extract_result": [
                            {
                                "state": "pending",
                            }
                        ]
                    }
                }
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            artifact_dir = output_root / "2603.00003-pending"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "source.pdf").write_bytes(b"%PDF-1.4\nfake")
            state_root.mkdir(parents=True, exist_ok=True)
            state_path = state_root / "2603.00003-pending.json"
            state_path.write_text(
                json.dumps(
                    {
                        "canonical_id": "2603.00003-pending",
                        "pdf_url": "https://arxiv.org/pdf/2603.00003-pending.pdf",
                        "batch_id": "batch-pending",
                        "status": "uploaded",
                        "pdf_path": str(artifact_dir / "source.pdf"),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {"MINERU_API_KEY": "token-123"}, clear=True),
                patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=_urlopen),
            ):
                with self.assertRaisesRegex(RuntimeError, "still pending"):
                    mineru_pdf.convert_pdf_to_markdown(
                        canonical_id="2603.00003-pending",
                        pdf_url="https://arxiv.org/pdf/2603.00003-pending.pdf",
                        output_root=output_root,
                        state_root=state_root,
                        poll_interval_sec=0,
                        per_run_timeout_sec=0,
                        max_attempts=1,
                    )

            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("batch-pending", state_payload.get("batch_id"))
            self.assertEqual("retry_pending", state_payload.get("status"))
            self.assertIn("still pending", state_payload.get("last_error", ""))

    def test_convert_pdf_to_markdown_resumes_existing_batch_without_resubmitting(self) -> None:
        zip_bytes = _zip_with_markdown("# Resumed Markdown\n")
        batch_posts: list[str] = []

        def _urlopen(req, timeout=0):  # noqa: ANN001
            _ = timeout
            if isinstance(req, str):
                url = req
                method = "GET"
            else:
                url = req.full_url
                method = req.get_method()

            if url.endswith("/api/v4/file-urls/batch"):
                batch_posts.append(url)
                raise AssertionError("batch submit should not happen when resuming")
            if url.endswith("/api/v4/extract-results/batch/batch-resume"):
                payload = {
                    "data": {
                        "extract_result": [
                            {
                                "state": "done",
                                "full_zip_url": "https://download.example.com/resume.zip",
                            }
                        ]
                    }
                }
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            if url == "https://download.example.com/resume.zip":
                return _FakeResponse(zip_bytes)
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            artifact_dir = output_root / "2603.00003"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "source.pdf").write_bytes(b"%PDF-1.4\nfake")
            state_root.mkdir(parents=True, exist_ok=True)
            (state_root / "2603.00003.json").write_text(
                json.dumps(
                    {
                        "canonical_id": "2603.00003",
                        "pdf_url": "https://arxiv.org/pdf/2603.00003.pdf",
                        "batch_id": "batch-resume",
                        "status": "uploaded",
                        "pdf_path": str(artifact_dir / "source.pdf"),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {"MINERU_API_KEY": "token-123"}, clear=True),
                patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=_urlopen),
            ):
                result = mineru_pdf.convert_pdf_to_markdown(
                    canonical_id="2603.00003",
                    pdf_url="https://arxiv.org/pdf/2603.00003.pdf",
                    output_root=output_root,
                    state_root=state_root,
                    poll_interval_sec=0,
                    per_run_timeout_sec=30,
                )

        self.assertEqual([], batch_posts)
        self.assertEqual("batch-resume", result["batch_id"])
        self.assertEqual("done", result["status"])

    def test_convert_pdf_to_markdown_returns_cache_hit_when_markdown_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            extract_dir = output_root / "2603.00004" / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            markdown_path = extract_dir / "content.md"
            markdown_path.write_text("# Existing Markdown", encoding="utf-8")

            with (
                patch.dict(os.environ, {"MINERU_API_KEY": "token-123"}, clear=True),
                patch.object(
                    mineru_pdf.urllib.request,
                    "urlopen",
                    side_effect=AssertionError("network should not be used on cache hit"),
                ),
            ):
                result = mineru_pdf.convert_pdf_to_markdown(
                    canonical_id="2603.00004",
                    pdf_url="https://arxiv.org/pdf/2603.00004.pdf",
                    output_root=output_root,
                    state_root=state_root,
                )

        self.assertEqual("done", result["status"])
        self.assertTrue(result["cache_hit"])
        self.assertEqual(str(markdown_path), result["markdown_path"])

    def test_convert_pdf_to_markdown_uses_curl_fallback_after_tls_upload_failure(self) -> None:
        def _urlopen(req, timeout=0):  # noqa: ANN001
            _ = timeout
            if isinstance(req, str):
                url = req
            else:
                url = req.full_url

            if url == "https://arxiv.org/pdf/2603.00005.pdf":
                return _FakeResponse(b"%PDF-1.4\nfake")
            if url.endswith("/api/v4/file-urls/batch"):
                payload = {
                    "data": {
                        "batch_id": "batch-555",
                        "file_urls": ["https://upload.example.com/tls.pdf"],
                    }
                }
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            if url == "https://upload.example.com/tls.pdf":
                raise ssl.SSLEOFError("EOF occurred in violation of protocol")
            raise AssertionError(f"Unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            state_root = Path(tmpdir) / "state"
            with (
                patch.dict(os.environ, {"MINERU_API_KEY": "token-123"}, clear=True),
                patch.object(mineru_pdf.urllib.request, "urlopen", side_effect=_urlopen),
                patch.object(
                    mineru_pdf.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(args=["curl.exe"], returncode=1, stdout="", stderr="curl failed"),
                ) as curl_mock,
            ):
                with self.assertRaisesRegex(RuntimeError, "curl failed"):
                    mineru_pdf.convert_pdf_to_markdown(
                        canonical_id="2603.00005",
                        pdf_url="https://arxiv.org/pdf/2603.00005.pdf",
                        output_root=output_root,
                        state_root=state_root,
                        poll_interval_sec=0,
                        per_run_timeout_sec=30,
                        max_attempts=1,
                    )

        curl_cmd = curl_mock.call_args.args[0]
        self.assertEqual("curl.exe", curl_cmd[0])
        self.assertIn("--http1.1", curl_cmd)


if __name__ == "__main__":
    unittest.main()
