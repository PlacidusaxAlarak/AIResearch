from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4


def pytest_configure() -> None:
    # Codex runs in a workspace-write sandbox; system temp locations may be blocked.
    # Force stdlib tempfile users (TemporaryDirectory, NamedTemporaryFile, etc.) to stay
    # inside the repo so tests remain runnable.
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / ".codex_runtime" / "tmp" / "pytest"
    tmp_root.mkdir(parents=True, exist_ok=True)

    os.environ["TMPDIR"] = str(tmp_root)
    os.environ["TEMP"] = str(tmp_root)
    os.environ["TMP"] = str(tmp_root)
    tempfile.tempdir = str(tmp_root)

    # In this environment, `os.mkdir(path, 0o700)` can produce directories that are
    # not writable (PermissionError on file creation). `tempfile.mkdtemp()` uses
    # mode=0o700 by default, so we patch it to create directories with default
    # permissions instead.
    original_mkdtemp = tempfile.mkdtemp

    def mkdtemp_compat(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
        base_dir = Path(dir or tempfile.gettempdir())
        base_dir.mkdir(parents=True, exist_ok=True)
        safe_suffix = "" if suffix is None else suffix
        safe_prefix = "tmp" if prefix is None else prefix
        for _ in range(1000):
            candidate = base_dir / f"{safe_prefix}{uuid4().hex}{safe_suffix}"
            try:
                candidate.mkdir()
                return str(candidate)
            except FileExistsError:
                continue
        return original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    tempfile.mkdtemp = mkdtemp_compat
