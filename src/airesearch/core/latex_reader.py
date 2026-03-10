from __future__ import annotations

import re
from pathlib import Path
from typing import List, Set, Tuple

INPUT_RE = re.compile(r"\\(input|include)\{([^}]+)\}")


def select_main_tex(tex_files: List[Path]) -> Path | None:
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
    return max(main_candidates, key=lambda p: p.stat().st_size)


def _resolve_include(base_dir: Path, name: str) -> Path | None:
    candidate = (base_dir / name).resolve()
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".tex")
    if candidate.exists():
        return candidate
    return None


def _strip_full_line_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        lines.append(line)
    return "\n".join(lines)


def read_latex_tree(entry: Path) -> Tuple[str, List[str]]:
    visited: Set[Path] = set()
    used_files: List[str] = []

    def _read_file(path: Path) -> str:
        if path in visited:
            return ""
        visited.add(path)
        used_files.append(str(path))

        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

        raw = _strip_full_line_comments(raw)
        output_parts: List[str] = []
        for line in raw.splitlines():
            output_parts.append(line)
            for match in INPUT_RE.finditer(line):
                include_name = match.group(2).strip()
                include_path = _resolve_include(path.parent, include_name)
                if include_path:
                    output_parts.append(_read_file(include_path))
        return "\n".join(output_parts)

    full_text = _read_file(entry)
    return full_text, used_files
