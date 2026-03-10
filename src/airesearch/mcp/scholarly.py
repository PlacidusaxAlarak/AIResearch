import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict

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


API_BASE = "https://api.semanticscholar.org/graph/v1"
mcp = FastMCP("scholarly")


def _make_request(url: str) -> Dict[str, object]:
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key

    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"citationCount": 0, "notFound": True}
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait_sec = int(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    wait_sec = 2 ** attempt
                time.sleep(min(max(wait_sec, 1), 30))
                continue
            raise

    return {"citationCount": 0, "rateLimited": True}


def _strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def _normalize_paper_id(paper_id: str) -> str:
    if ":" in paper_id:
        if paper_id.upper().startswith("ARXIV:"):
            base = paper_id.split(":", 1)[1]
            base = _strip_arxiv_version(base)
            return f"ARXIV:{base}"
        return paper_id
    return f"ARXIV:{_strip_arxiv_version(paper_id)}"


@mcp.tool(name="paper_lookup")
def paper_lookup(paper_id: str) -> Dict[str, object]:
    """Lookup a paper on Semantic Scholar."""
    pid = _normalize_paper_id(paper_id)
    fields = "citationCount"
    url = f"{API_BASE}/paper/{urllib.parse.quote(pid)}?fields={fields}"
    return _make_request(url)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
