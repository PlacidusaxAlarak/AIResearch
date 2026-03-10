# Usage Guide

## Overview

This document expands on the public README with concrete local setup and common execution patterns.

## Recommended Setup

1. Install dependencies:
   `python -m pip install -r requirements-dev.txt`
   `python -m pip install -e .`
2. Duplicate the public templates into local files:
   `config.example.yaml` -> `config.local.yaml`
   `mcp.example.json` -> `mcp.local.json`
3. Edit local-only values:
   recipients, vault path, MCP email account name, and any machine-specific paths.
4. Export environment variables required by your chosen integrations.

## Common Run Modes

Single run with default date window:

```bash
python -m airesearch --config config.local.yaml --run-once
```

Installed package equivalent:

```bash
airesearch --config config.local.yaml --run-once
```

Force a same-day rerun:

```bash
python -m airesearch --config config.local.yaml --run-once --force-run
```

Explicit CST date window:

```bash
python -m airesearch --config config.local.yaml --run-once --force-run --start-date 2026-03-01 --end-date 2026-03-07
```

Write logs to a file while keeping stdout:

```bash
python -m airesearch --config config.local.yaml --run-once --log-file output/logs/manual.log
```

## Configuration Notes

- `config.local.yaml` overrides the public example and should remain local.
- CLI `--config` has highest priority.
- `AIRESEARCH_CONFIG` and `AIRESEARCH_MCP_CONFIG` are supported for non-default file locations.
- `seen_cache_path` remains in the example file only for backward compatibility. The public pipeline does not actively persist sent-paper dedupe state.

## MCP Notes

The project exposes several MCP modules directly through Python module execution:

```bash
python -m airesearch.mcp.arxiv
python -m airesearch.mcp.hf_papers
python -m airesearch.mcp.scholarly
python -m airesearch.mcp.github
python -m airesearch.mcp.obsidian
```

The example JSON config uses those module entrypoints. Email is intentionally separate because many users already have their own MCP email server deployment.

## Optional Operator Helpers

- [run_with_date_range.ps1](/G:/AIResearch/ops/run_with_date_range.ps1) prompts for a CST date range and then calls the Python module entrypoint.
- [run_super_whitelist_service.ps1](/G:/AIResearch/ops/run_super_whitelist_service.ps1) runs the one-shot pipeline with the local config.
- [send_email_from_body.py](/G:/AIResearch/scripts/send_email_from_body.py) is a helper for sending a prepared body file through the core SMTP sender.

These helpers are optional convenience scripts, not the canonical public interface.

## Output and State

- `output/out/<run_id>/` stores run-specific artifacts and summaries.
- `output/latest_run.json` and `output/latest_run.txt` point to the newest run.
- `state/last_run.json` stores the daily guard used by `--run-once`.
- `runtime/` is treated as local runtime space and should not be published.

## Contributor Workflow

- Run tests with `python -m pytest -q`.
- Prefer package imports from `src/airesearch/` instead of root wrappers.
- Keep local secrets out of tracked files.
- Update [AGENTS.md](/G:/AIResearch/AGENTS.md) when changing agent-facing workflow expectations.
