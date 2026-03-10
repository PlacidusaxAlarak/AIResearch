from __future__ import annotations

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple


def _resolve_codex_exe() -> str:
    for name in ("codex.cmd", "codex"):
        path = shutil.which(name)
        if path:
            return path
    return "codex"


def _parse_json_payload(text: str) -> Tuple[Dict[str, Any], str | None]:
    raw = text.strip()
    if not raw:
        return {}, "empty stdout"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1]), "salvaged"
            except json.JSONDecodeError as exc:
                return {}, f"invalid json: {exc}"
        return {}, "invalid json"


def _can_use_codex_home(path_str: str) -> bool:
    try:
        root = Path(path_str).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)

        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "skills").mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _build_codex_env(cwd: str | None = None) -> dict[str, str]:
    env = os.environ.copy()

    candidates: list[str] = []
    existing = env.get("CODEX_HOME")
    if existing:
        candidates.append(existing)

    user_profile = env.get("USERPROFILE")
    if user_profile:
        candidates.append(str(Path(user_profile) / ".codex"))
    else:
        candidates.append(str(Path.home() / ".codex"))

    if cwd:
        candidates.append(str(Path(cwd) / ".codex_runtime"))

    candidates.append(str(Path.cwd() / ".codex_runtime"))

    for candidate in candidates:
        if _can_use_codex_home(candidate):
            env["CODEX_HOME"] = str(Path(candidate).expanduser().resolve())
            return env

    return env


def run_json(
    prompt: str,
    timeout_sec: int = 600,
    cwd: str | None = None,
    skip_git_repo_check: bool = False,
    use_search: bool = False,
) -> Dict[str, Any]:
    exe = _resolve_codex_exe()
    # codex CLI expects --search before subcommand (e.g., "codex --search exec")
    cmd = [exe]
    if use_search:
        cmd.append("--search")
    cmd.append("exec")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_sec,
        cwd=cwd,
        env=_build_codex_env(cwd),
    )
    if result.returncode != 0:
        raise RuntimeError(
            "codex exec failed: " + (result.stderr.strip() or "unknown error")
        )

    payload, err = _parse_json_payload(result.stdout)
    if err and not payload:
        raise RuntimeError(f"codex output not json ({err})")
    return payload

