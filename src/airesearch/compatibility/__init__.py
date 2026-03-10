from __future__ import annotations

import os
import sys
from pathlib import Path


def src_root() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_src_on_path() -> Path:
    root = src_root()
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def _resolve_user_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def resolve_config_path(cli_value: str | None = None) -> Path:
    if cli_value:
        return _resolve_user_path(cli_value)

    env_value = os.environ.get("AIRESEARCH_CONFIG", "").strip()
    if env_value:
        return _resolve_user_path(env_value)

    root = repo_root()
    local_cfg = root / "config.local.yaml"
    if local_cfg.exists():
        return local_cfg
    return root / "config.example.yaml"


def resolve_mcp_config_path() -> Path:
    env_value = os.environ.get("AIRESEARCH_MCP_CONFIG", "").strip()
    if env_value:
        return _resolve_user_path(env_value)

    root = repo_root()
    local_cfg = root / "mcp.local.json"
    if local_cfg.exists():
        return local_cfg
    return root / "mcp.example.json"
