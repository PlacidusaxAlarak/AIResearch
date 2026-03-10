from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

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


BASE_URL = "https://huggingface.co/api/daily_papers"
MAX_DATE_RE = re.compile(r'"(\d{4}-\d{2}-\d{2})T')
REQUEST_TIMEOUT_SEC = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 1.5

mcp = FastMCP("hf-papers")


def _paper_payload(item: Dict[str, object]) -> Dict[str, object]:
    payload = item.get("paper")
    return payload if isinstance(payload, dict) else {}


def _pick_first_str(container: Dict[str, object], keys: List[str]) -> str:
    for key in keys:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_terms(query: str) -> List[str]:
    parts = [part.strip() for part in query.split(" OR ") if part.strip()]
    return [part.lower() for part in parts] if parts else [query.lower()]


def _match(query_terms: List[str], text: str) -> bool:
    low = text.lower()
    return any(term in low for term in query_terms)


def _fetch_endpoint(params: Dict[str, str], date_str: str | None = None) -> List[Dict[str, object]]:
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and date_str:
                body = exc.read().decode("utf-8", errors="ignore")
                try:
                    payload = json.loads(body)
                    message = str(payload.get("error", ""))
                except json.JSONDecodeError:
                    message = body
                match = MAX_DATE_RE.search(message)
                if match:
                    max_date = match.group(1)
                    if max_date != date_str:
                        return _fetch_endpoint({"date": max_date}, date_str=max_date)
                return []
            last_exc = exc
        except Exception as exc:
            last_exc = exc
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SEC ** (attempt - 1))
    if last_exc:
        raise last_exc
    return []


def _fetch_day(date_str: str) -> List[Dict[str, object]]:
    return _fetch_endpoint({"date": date_str}, date_str=date_str)


def _extract_id(item: Dict[str, object]) -> str:
    for container in (item, _paper_payload(item)):
        for key in ("paperId", "arxivId", "arxiv_id", "id", "paper_id"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_authors(item: Dict[str, object]) -> List[str]:
    for container in (item, _paper_payload(item)):
        authors = container.get("authors")
        if isinstance(authors, list):
            names = []
            for author in authors:
                if isinstance(author, str):
                    author_name = author.strip()
                    if author_name:
                        names.append(author_name)
                elif isinstance(author, dict) and "name" in author:
                    author_name = str(author["name"]).strip()
                    if author_name:
                        names.append(author_name)
            if names:
                return names
        if isinstance(authors, str):
            parsed = [author.strip() for author in authors.split(",") if author.strip()]
            if parsed:
                return parsed
    return []


def _guess_arxiv_id(paper_id: str) -> str:
    if re.match(r"^\d{4}\.\d{4,5}$", paper_id):
        return paper_id
    if paper_id.startswith("arxiv:"):
        return paper_id.split(":", 1)[1]
    return ""


def _extract_id_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"arxiv\.org/(abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?", url)
    if match:
        return match.group(2)
    match = re.search(r"huggingface\.co/papers/(\d{4}\.\d{4,5})", url)
    if match:
        return match.group(1)
    return ""


def _extract_published(item: Dict[str, object]) -> str | None:
    for container in (item, _paper_payload(item)):
        for key in ("publishedAt", "published", "date", "submittedOnDailyAt"):
            value = container.get(key)
            if isinstance(value, str) and value:
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return dt.astimezone(timezone.utc).isoformat()
                except ValueError:
                    return value
    return None


def _extract_submitted_on_daily(item: Dict[str, object]) -> str | None:
    for container in (item, _paper_payload(item)):
        value = container.get("submittedOnDailyAt")
        if isinstance(value, str) and value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc).isoformat()
            except ValueError:
                return value
    return None


def _build_result(item: Dict[str, object], terms: List[str]) -> Dict[str, object] | None:
    nested_paper = _paper_payload(item)

    title = _pick_first_str(item, ["title"])
    if not title:
        title = _pick_first_str(nested_paper, ["title"])

    summary = _pick_first_str(item, ["summary", "abstract", "ai_summary"])
    if not summary:
        summary = _pick_first_str(nested_paper, ["summary", "abstract", "ai_summary"])

    if terms and not (_match(terms, title) or _match(terms, summary)):
        return None

    paper_id = _extract_id(item)
    url = _pick_first_str(item, ["url", "paperUrl"])
    if not url:
        url = _pick_first_str(nested_paper, ["url", "paperUrl"])

    if not paper_id:
        paper_id = _extract_id_from_url(url)

    arxiv_id = _guess_arxiv_id(paper_id) or _extract_id_from_url(url)
    if not paper_id and arxiv_id:
        paper_id = arxiv_id

    if not url and arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"

    pdf_url = _pick_first_str(item, ["pdf_url", "pdfUrl"])
    if not pdf_url:
        pdf_url = _pick_first_str(nested_paper, ["pdf_url", "pdfUrl"])
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    result: Dict[str, object] = {
        "id": paper_id or arxiv_id,
        "title": title,
        "abstract": summary,
        "authors": _extract_authors(item),
        "url": url or "",
        "pdf_url": pdf_url or "",
        "published": _extract_published(item),
        "submitted_on_daily": _extract_submitted_on_daily(item),
    }

    for key in ("score", "upvotes", "likes"):
        if key in item:
            result[key] = item.get(key)
            continue
        if key in nested_paper:
            result[key] = nested_paper.get(key)

    return result


@mcp.tool(name="papers_search")
def papers_search(query: str, limit: int = 50, days_back: int = 7) -> List[Dict[str, object]]:
    """Search HF daily papers by keywords (last N days)."""
    terms = _normalize_terms(query)
    results: List[Dict[str, object]] = []
    today = datetime.now(timezone.utc).date()

    for day in range(days_back):
        date_str = (today - timedelta(days=day)).strftime("%Y-%m-%d")
        items = _fetch_day(date_str)
        for item in items:
            result = _build_result(item, terms)
            if not result:
                continue
            results.append(result)

            if len(results) >= limit:
                return results

    return results


@mcp.tool(name="papers_trending")
def papers_trending(query: str, limit: int = 50) -> List[Dict[str, object]]:
    """Fetch trending HF papers and filter by keywords if provided."""
    terms = _normalize_terms(query) if query else []
    items = _fetch_endpoint({"sort": "trending", "limit": str(limit)})
    results: List[Dict[str, object]] = []

    for item in items:
        result = _build_result(item, terms)
        if not result:
            continue
        results.append(result)
        if len(results) >= limit:
            break

    return results


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
