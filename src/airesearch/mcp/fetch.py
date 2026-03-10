import shutil
import urllib.request
from pathlib import Path
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


mcp = FastMCP("fetch")


@mcp.tool(name="download")
def download(url: str, path: str, timeout_sec: int = 60) -> Dict[str, object]:
    """Download a URL to a local file."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp, open(target, "wb") as f:
        shutil.copyfileobj(resp, f)

    return {
        "ok": True,
        "path": str(target),
        "bytes": target.stat().st_size,
    }


if __name__ == "__main__":
    mcp.run()
