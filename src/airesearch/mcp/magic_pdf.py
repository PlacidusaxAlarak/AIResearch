import subprocess
from pathlib import Path
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


mcp = FastMCP("magic-pdf")


def _find_markdown_files(output_dir: Path) -> List[str]:
    return [str(p) for p in output_dir.rglob("*.md")]


@mcp.tool()
def magic_pdf_parse(
    pdf_path: str,
    output_dir: str,
    mode: str = "auto",
    timeout_sec: int = 0,
) -> Dict[str, object]:
    """Run magic-pdf in pipeline mode and return output paths."""
    pdf = Path(pdf_path).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmd = ["magic-pdf", "-p", str(pdf), "-o", str(out), "-m", mode]
    timeout = None if timeout_sec <= 0 else timeout_sec
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError("magic-pdf failed: " + (result.stderr.strip() or "unknown error"))

    md_files = _find_markdown_files(out)
    return {
        "ok": True,
        "output_dir": str(out),
        "markdown_files": md_files,
        "stdout_tail": result.stdout[-2000:],
    }


if __name__ == "__main__":
    mcp.run()
