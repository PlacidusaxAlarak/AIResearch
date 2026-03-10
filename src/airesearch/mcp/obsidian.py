import os
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


mcp = FastMCP("obsidian")


def _get_vault() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if not vault:
        return Path.cwd()
    return Path(vault).expanduser().resolve()


def _safe_join(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    if base not in target.parents and base != target:
        raise ValueError("Path escapes vault")
    return target


@mcp.tool(name="write_note")
def write_note(path: str, content: str, encoding: str = "utf-8") -> Dict[str, object]:
    """Write a note inside the Obsidian vault."""
    base = _get_vault()
    target = _safe_join(base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    return {"ok": True, "path": str(target)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
