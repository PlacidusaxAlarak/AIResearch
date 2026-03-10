import json
import os
import urllib.parse
import urllib.request
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


API_BASE = "https://api.github.com"
mcp = FastMCP("github")


def _request(url: str) -> Dict[str, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcp-github-client",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_tree(owner: str, repo: str, ref: str) -> Dict[str, object]:
    url = f"{API_BASE}/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(ref)}?recursive=1"
    return _request(url)


@mcp.tool(name="repo_info")
def repo_info(owner: str, repo: str) -> Dict[str, object]:
    """Return repo metadata (stars, forks, etc.)."""
    url = f"{API_BASE}/repos/{owner}/{repo}"
    return _request(url)


@mcp.tool(name="repo_tree")
def repo_tree(owner: str, repo: str, ref: str = "main", max_depth: int = 0) -> List[str]:
    """Return a flattened list of file paths in a repo."""
    try:
        data = _get_tree(owner, repo, ref)
    except Exception:
        if ref == "main":
            data = _get_tree(owner, repo, "master")
        else:
            raise

    tree = data.get("tree", [])
    paths: List[str] = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path:
            continue
        if max_depth and path.count("/") + 1 > max_depth:
            continue
        paths.append(path)

    return paths


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
