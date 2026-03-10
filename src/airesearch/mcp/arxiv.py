from __future__ import annotations

import random
import re
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List
from urllib.error import HTTPError, URLError

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - fallback when mcp package is unavailable
    class FastMCP:  # type: ignore[override]
        def __init__(self, _name: str) -> None:
            pass

        def tool(self, *args, **kwargs):  # noqa: ANN002,ANN003
            def _decorator(func):
                return func

            return _decorator

        def run(self) -> None:
            raise RuntimeError("mcp package is required to run this server")


ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_SOURCE = "https://arxiv.org/e-print"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
SEARCH_TIMEOUT_SEC = 60
SOURCE_TIMEOUT_SEC = 120
MAX_RETRIES = 6
RETRY_BACKOFF_SEC = 1.5
RETRY_MAX_BACKOFF_SEC = 60.0
RETRY_JITTER_RATIO = 0.2
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}

mcp = FastMCP("arxiv")


def _parse_retry_after_seconds(raw_value: str | None) -> float | None:
    if not raw_value:
        return None
    value = raw_value.strip()
    if not value:
        return None

    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    wait_seconds = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, wait_seconds)


def _compute_backoff_seconds(attempt: int, retry_after_seconds: float | None = None) -> float:
    exp_backoff = RETRY_BACKOFF_SEC * (2 ** (attempt - 1))
    if retry_after_seconds is not None:
        exp_backoff = max(exp_backoff, retry_after_seconds)
    capped = min(exp_backoff, RETRY_MAX_BACKOFF_SEC)
    jitter = random.uniform(0.0, capped * RETRY_JITTER_RATIO)
    return capped + jitter


def _read_with_retries(req: urllib.request.Request, timeout_sec: int) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except HTTPError as exc:
            last_exc = exc
            if exc.code not in TRANSIENT_HTTP_STATUS or attempt >= MAX_RETRIES:
                break
            retry_after_header = exc.headers.get("Retry-After") if exc.headers else None
            retry_after_seconds = _parse_retry_after_seconds(retry_after_header)
            wait_seconds = _compute_backoff_seconds(attempt, retry_after_seconds)
            time.sleep(wait_seconds)
        except (URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt >= MAX_RETRIES:
                break
            wait_seconds = _compute_backoff_seconds(attempt)
            time.sleep(wait_seconds)
        except Exception as exc:
            last_exc = exc
            if attempt >= MAX_RETRIES:
                break
            wait_seconds = _compute_backoff_seconds(attempt)
            time.sleep(wait_seconds)
    raise last_exc or RuntimeError("Unknown download error")


def _format_term(term: str) -> str:
    term = term.strip()
    if not term:
        return ""
    if ":" in term.split()[0]:
        return term
    if " " in term:
        term = f'"{term}"'
    return f"all:{term}"


def _build_query(query: str) -> str:
    parts = [p.strip() for p in query.split(" OR ") if p.strip()]
    if not parts:
        return query
    return " OR ".join(_format_term(p) for p in parts)


def _parse_time(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _extract_pdf_url(entry: ET.Element) -> str:
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("type") == "application/pdf":
            return link.attrib.get("href", "")
    entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
    if "/abs/" in entry_id:
        return entry_id.replace("/abs/", "/pdf/") + ".pdf"
    return ""


def _extract_id(entry: ET.Element) -> str:
    entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
    if "/abs/" in entry_id:
        return entry_id.split("/abs/")[-1]
    return entry_id.rsplit("/", 1)[-1]


def _select_main_tex(tex_files: List[Path]) -> Path | None:
    main_candidates: List[Path] = []
    for path in tex_files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "\\begin{document}" in content:
            main_candidates.append(path)
    if not main_candidates:
        main_candidates = tex_files
    if not main_candidates:
        return None
    return max(main_candidates, key=lambda path: path.stat().st_size)


def _download_source(arxiv_id: str, output_dir: Path) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    url = f"{ARXIV_SOURCE}/{arxiv_id}"
    archive_path = output_dir / f"{arxiv_id}.tar.gz"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = _read_with_retries(req, timeout_sec=SOURCE_TIMEOUT_SEC)

    archive_path.write_bytes(data)

    try:
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if not member.name.lower().endswith(".tex"):
                    continue
                try:
                    tf.extract(member, output_dir)
                except (OSError, tarfile.TarError):
                    continue
    except tarfile.TarError as exc:
        raise RuntimeError(f"Failed to extract arXiv source: {exc}") from exc

    tex_files = sorted(output_dir.rglob("*.tex"))
    main_tex = _select_main_tex(tex_files)

    return {
        "ok": True,
        "archive_path": str(archive_path),
        "output_dir": str(output_dir),
        "tex_path": str(main_tex) if main_tex else "",
        "tex_files": [str(path) for path in tex_files],
    }


@mcp.tool(name="search")
def search(
    query: str,
    max_results: int = 50,
    start: int = 0,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> List[Dict[str, object]]:
    """Search arXiv and return a list of papers."""
    search_query = _build_query(query)
    params = {
        "search_query": search_query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = _read_with_retries(req, timeout_sec=SEARCH_TIMEOUT_SEC)

    root = ET.fromstring(data)
    results: List[Dict[str, object]] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        paper_id = _extract_id(entry)
        title = entry.findtext("atom:title", default="", namespaces=ATOM_NS).strip()
        summary = entry.findtext("atom:summary", default="", namespaces=ATOM_NS).strip()
        published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
        authors = [
            author.findtext("atom:name", default="", namespaces=ATOM_NS).strip()
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        item_url = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
        pdf_url = _extract_pdf_url(entry)

        results.append(
            {
                "id": paper_id,
                "title": title,
                "summary": summary,
                "authors": [author for author in authors if author],
                "url": item_url,
                "pdf_url": pdf_url,
                "published": _parse_time(published) if published else None,
            }
        )

    return results


@mcp.tool(name="source_fetch")
def source_fetch(arxiv_id: str, output_dir: str = "output/latex") -> Dict[str, object]:
    """Download and extract arXiv LaTeX source; return main .tex path."""
    out = Path(output_dir).expanduser().resolve() / arxiv_id.replace("/", "_")
    return _download_source(arxiv_id, out)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
