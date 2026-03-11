from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

MINERU_API_BASE = "https://mineru.net"
FILE_URLS_BATCH_ENDPOINT = f"{MINERU_API_BASE}/api/v4/file-urls/batch"
EXTRACT_RESULTS_BATCH_ENDPOINT = f"{MINERU_API_BASE}/api/v4/extract-results/batch"
DEFAULT_POLL_INTERVAL_SEC = 5.0
DEFAULT_PER_RUN_TIMEOUT_SEC = 600.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SEC = 2.0
USER_AGENT = "AIResearch/1.0"


class MineruConfigurationError(RuntimeError):
    """Raised when MinerU is requested without required configuration."""


class MineruPendingError(RuntimeError):
    """Raised when a MinerU batch is still pending after the current timeout."""


class MineruProcessingError(RuntimeError):
    """Raised for retryable MinerU processing failures."""


def _state_path(state_root: Path, canonical_id: str) -> Path:
    return state_root / f"{canonical_id}.json"



def _artifact_dir(output_root: Path, canonical_id: str) -> Path:
    return output_root / canonical_id



def _load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}



def _write_state(state_path: Path, payload: Dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    state_path.write_text(rendered + "\n", encoding="utf-8")



def _require_api_key() -> str:
    api_key = os.environ.get("MINERU_API_KEY", "").strip()
    if not api_key:
        raise MineruConfigurationError("MINERU_API_KEY environment variable is required for MinerU conversion")
    return api_key



def _is_tls_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException):
            return _is_tls_transport_error(reason)
    return False



def _curl_request_bytes(
    url: str,
    *,
    headers: Dict[str, str],
    method: str = "GET",
    payload: Optional[bytes] = None,
    timeout_sec: float = DEFAULT_PER_RUN_TIMEOUT_SEC,
) -> bytes:
    cmd = [
        "curl.exe",
        "--http1.1",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "-X",
        method,
    ]
    if timeout_sec > 0:
        cmd.extend(["--max-time", str(max(1, int(timeout_sec)))])
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    if payload is not None:
        cmd.extend(["--data-binary", "@-"])
    cmd.append(url)

    result = subprocess.run(cmd, input=payload, capture_output=True, check=False)
    stdout = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout or "").encode("utf-8")
    stderr_text = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
    if result.returncode != 0:
        stdout_text = stdout.decode("utf-8", errors="replace")
        raise RuntimeError(stderr_text.strip() or stdout_text.strip() or "curl request failed")
    return stdout



def _json_request(url: str, *, headers: Dict[str, str], method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout_sec: float = DEFAULT_PER_RUN_TIMEOUT_SEC) -> Dict[str, Any]:
    data = None
    request_headers = dict(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except Exception as exc:
        if not _is_tls_transport_error(exc):
            raise
        raw = _curl_request_bytes(
            url,
            headers=request_headers,
            method=method,
            payload=data,
            timeout_sec=timeout_sec,
        )
    if not raw:
        return {}
    decoded = json.loads(raw.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {}



def _download_bytes(url: str, *, timeout_sec: float, headers: Optional[Dict[str, str]] = None) -> bytes:
    request_headers = headers or {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = resp.read()
    except Exception as exc:
        if not _is_tls_transport_error(exc):
            raise
        payload = _curl_request_bytes(
            url,
            headers=request_headers,
            method="GET",
            timeout_sec=timeout_sec,
        )
    if not payload:
        raise MineruProcessingError(f"Empty response when downloading {url}")
    return payload



def _download_pdf(pdf_url: str, pdf_path: Path, timeout_sec: float) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _download_bytes(pdf_url, timeout_sec=timeout_sec)
    pdf_path.write_bytes(payload)
    return pdf_path



def _curl_upload(pdf_path: Path, upload_url: str, timeout_sec: float) -> None:
    cmd = [
        "curl.exe",
        "--http1.1",
        "--fail",
        "--silent",
        "--show-error",
        "-X",
        "PUT",
    ]
    if timeout_sec > 0:
        cmd.extend(["--max-time", str(max(1, int(timeout_sec)))])
    cmd.extend([
        "--upload-file",
        str(pdf_path),
        upload_url,
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "curl upload failed")



def _upload_pdf(upload_url: str, pdf_path: Path, timeout_sec: float) -> None:
    payload = pdf_path.read_bytes()
    req = urllib.request.Request(
        upload_url,
        data=payload,
        headers={"Content-Type": "application/pdf", "User-Agent": USER_AGENT},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read()
    except Exception as exc:
        if not _is_tls_transport_error(exc):
            raise
        _curl_upload(pdf_path, upload_url, timeout_sec)



def _submit_batch(api_key: str, canonical_id: str, pdf_path: Path, timeout_sec: float) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}
    payload = {
        "files": [
            {
                "name": pdf_path.name,
                "source": canonical_id,
            }
        ]
    }
    response = _json_request(
        FILE_URLS_BATCH_ENDPOINT,
        method="POST",
        headers=headers,
        payload=payload,
        timeout_sec=timeout_sec,
    )
    data = response.get("data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        raise MineruProcessingError("MinerU batch submit returned invalid payload")
    batch_id = str(data.get("batch_id", "")).strip()
    file_urls = data.get("file_urls") if isinstance(data.get("file_urls"), list) else []
    upload_url = str(file_urls[0]).strip() if file_urls else ""
    if not batch_id or not upload_url:
        raise MineruProcessingError("MinerU batch submit missing batch_id or upload url")
    return batch_id, upload_url



def _extract_markdown_from_zip(zip_bytes: bytes, extract_dir: Path) -> Path:
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    zip_path = extract_dir.parent / "result.zip"
    zip_path.write_bytes(zip_bytes)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    markdown_files = sorted(extract_dir.rglob("*.md"))
    if not markdown_files:
        raise MineruProcessingError("MinerU result zip did not contain markdown")

    canonical_path = extract_dir / "content.md"
    if markdown_files[0] != canonical_path:
        canonical_path.write_text(markdown_files[0].read_text(encoding="utf-8"), encoding="utf-8")
    return canonical_path



def _poll_batch_until_complete(api_key: str, batch_id: str, artifact_dir: Path, *, poll_interval_sec: float, timeout_sec: float) -> tuple[str, str]:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}
    status_url = f"{EXTRACT_RESULTS_BATCH_ENDPOINT}/{batch_id}"
    last_state = ""

    while True:
        response = _json_request(status_url, headers=headers, timeout_sec=timeout_sec)
        data = response.get("data") if isinstance(response, dict) else {}
        items = data.get("extract_result") if isinstance(data, dict) else None
        item = items[0] if isinstance(items, list) and items else {}
        state = str(item.get("state", "")).strip().lower()
        last_state = state or last_state
        if state == "done":
            zip_url = str(item.get("full_zip_url", "")).strip()
            if not zip_url:
                raise MineruProcessingError("MinerU done state missing full_zip_url")
            zip_bytes = _download_bytes(zip_url, timeout_sec=timeout_sec, headers={"User-Agent": USER_AGENT})
            markdown_path = _extract_markdown_from_zip(zip_bytes, artifact_dir / "extract")
            markdown_text = markdown_path.read_text(encoding="utf-8")
            return str(markdown_path), markdown_text
        if state in {"failed", "error"}:
            raise MineruProcessingError(f"MinerU batch {batch_id} failed with state={state}")
        if time.monotonic() >= deadline:
            raise MineruPendingError(f"MinerU batch {batch_id} still pending (last_state={last_state or 'unknown'})")
        time.sleep(max(0.0, poll_interval_sec))



def _maybe_cached_result(canonical_id: str, artifact_dir: Path, state_path: Path) -> Optional[Dict[str, Any]]:
    markdown_path = artifact_dir / "extract" / "content.md"
    if not markdown_path.exists():
        return None
    state = _load_state(state_path)
    pdf_path = str((artifact_dir / "source.pdf").resolve()) if (artifact_dir / "source.pdf").exists() else str(state.get("pdf_path", ""))
    return {
        "canonical_id": canonical_id,
        "status": "done",
        "batch_id": str(state.get("batch_id", "")),
        "pdf_path": pdf_path,
        "markdown_path": str(markdown_path.resolve()),
        "markdown_text": markdown_path.read_text(encoding="utf-8"),
        "cache_hit": True,
    }



def _compute_backoff_seconds(base_sec: float, attempt_index: int) -> float:
    return max(0.0, base_sec) * (2 ** max(0, attempt_index - 1))



def convert_pdf_to_markdown(
    canonical_id: str,
    pdf_url: str,
    output_root: Path,
    state_root: Path,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    per_run_timeout_sec: float = DEFAULT_PER_RUN_TIMEOUT_SEC,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_sec: float = DEFAULT_BACKOFF_BASE_SEC,
) -> Dict[str, Any]:
    artifact_dir = _artifact_dir(Path(output_root), canonical_id)
    state_path = _state_path(Path(state_root), canonical_id)
    api_key = _require_api_key()
    cached = _maybe_cached_result(canonical_id, artifact_dir, state_path)
    if cached is not None:
        return cached

    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = artifact_dir / "source.pdf"
    state = _load_state(state_path)
    attempts = max(1, int(max_attempts))
    last_exc: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            if not pdf_path.exists():
                _download_pdf(pdf_url, pdf_path, timeout_sec=per_run_timeout_sec)
            state.update(
                {
                    "canonical_id": canonical_id,
                    "pdf_url": pdf_url,
                    "pdf_path": str(pdf_path.resolve()),
                    "status": state.get("status") or "downloaded",
                }
            )
            _write_state(state_path, state)

            batch_id = str(state.get("batch_id", "")).strip()
            if not batch_id:
                batch_id, upload_url = _submit_batch(api_key, canonical_id, pdf_path, per_run_timeout_sec)
                state.update({"batch_id": batch_id, "status": "upload_url_created"})
                _write_state(state_path, state)
                _upload_pdf(upload_url, pdf_path, per_run_timeout_sec)
                state["status"] = "uploaded"
                _write_state(state_path, state)

            markdown_path, markdown_text = _poll_batch_until_complete(
                api_key,
                batch_id,
                artifact_dir,
                poll_interval_sec=poll_interval_sec,
                timeout_sec=per_run_timeout_sec,
            )
            state.update(
                {
                    "batch_id": batch_id,
                    "status": "done",
                    "markdown_path": markdown_path,
                }
            )
            _write_state(state_path, state)
            return {
                "canonical_id": canonical_id,
                "status": "done",
                "batch_id": batch_id,
                "pdf_path": str(pdf_path.resolve()),
                "markdown_path": markdown_path,
                "markdown_text": markdown_text,
                "cache_hit": False,
            }
        except MineruConfigurationError:
            raise
        except Exception as exc:
            last_exc = exc
            status = str(state.get("status", "")).strip().lower()
            keep_batch_id = bool(state.get("batch_id")) and status not in {"", "downloaded", "upload_url_created"}
            if state.get("status") != "done":
                if not keep_batch_id:
                    state.pop("batch_id", None)
                state["status"] = "retry_pending"
                state["last_error"] = str(exc)
                _write_state(state_path, state)
            if attempt >= attempts:
                break
            time.sleep(_compute_backoff_seconds(backoff_base_sec, attempt))

    assert last_exc is not None
    if isinstance(last_exc, RuntimeError):
        raise last_exc
    raise RuntimeError(str(last_exc)) from last_exc
