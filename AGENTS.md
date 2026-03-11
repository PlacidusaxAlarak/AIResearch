# Repository Guidelines

## GitHub Release Tracker
- Main Objective: Publish AIResearch as a GitHub-ready, cross-platform Python project with a clear public entrypoint and accurate documentation.
- Scope Guardrails: Keep current orchestrator CLI semantics; do not redesign scoring logic; do not introduce hosted infrastructure assumptions.
- Confirmed Decisions: Official entrypoints are `python -m airesearch` and installed `airesearch`; public MCP examples use `python -m airesearch.mcp.<adapter>`; root wrapper files and Windows `.cmd` launchers are removed from the public interface.
- Phase Checklist:
  - [x] Add failing tests for the new public interface.
  - [x] Implement package and MCP module entrypoints.
  - [x] Remove deprecated root wrappers and Windows-first launchers.
  - [x] Rewrite README and add detailed usage documentation.
  - [x] Run final verification and capture the results here.
- Current Progress: Release-hardening work is complete and verified; MinerU TLS fallback hardening and public config cleanup were completed on 2026-03-11.
- Verification Log:
  - 2026-03-11: `python -m pytest -q tests/test_core_mineru_pdf_characterization.py` -> 9 passed after handling URLError-wrapped MinerU TLS EOF failures with curl fallback.
  - 2026-03-11: `python -m pytest -q tests/test_orchestrator_single_pass_characterization.py tests/test_orchestrator_seen_behavior_characterization.py` -> 8 passed after MinerU transport hardening.
  - 2026-03-11: `python -m pytest -q` -> 67 passed after MinerU transport hardening and config/doc cleanup.
  - 2026-03-10: `python -m pytest -q tests/test_orchestrator_cli_characterization.py tests/test_wrapper_smoke.py` -> pass after entrypoint changes.
  - 2026-03-10: `python -m airesearch --help` -> pass after adding `airesearch.__main__`.
  - 2026-03-10: `python -m pip install -e .` -> pass after rewriting `README.md` as UTF-8.
  - 2026-03-10: `python -m pytest -q` -> 53 passed.
  - 2026-03-10: installed console script verification via Python scripts directory fallback -> pass.
  - 2026-03-10: `python -c "from pathlib import Path; Path('README.md').read_text(encoding='utf-8')"` -> pass.
- Remaining Risks:
  - MinerU still depends on external network reachability; non-TLS transport failures can still exhaust retries and trigger LaTeX fallback.
  - Older `config.local.yaml` files copied from pre-cleanup templates may still include deprecated keys and continue to emit startup warnings until manually removed.
  - Local permission-locked temp directories such as `.tmp/`, `.codex_runtime/`, and `tests/_tmp_runtime/` may require manual OS-level cleanup even though they are ignored.
  - Public docs assume users will provide their own credentials and optional MCP email backend.

## Project Structure & Module Organization
- Canonical implementation lives in `src/airesearch/`.
- `src/airesearch/cli/orchestrator.py` is the main pipeline entrypoint behind both public CLI modes.
- `airesearch/__init__.py` is a lightweight source-checkout shim so local package imports work before installation.
- Public templates are `config.example.yaml` and `mcp.example.json`.
- Local runtime configs are `config.local.yaml` and `mcp.local.json` (gitignored).
- PowerShell operator helpers live under `ops/`.
- Prompt assets live under `prompts/`.
- Runtime artifacts include `state/`, `output/`, `runtime/`, `.tmp/`, and `.codex_runtime/` and should remain untracked.

## Build, Test, and Development Commands
- Install dependencies: `python -m pip install -r requirements-dev.txt` then `python -m pip install -e .`.
- Run once from a checkout: `python -m airesearch --config config.local.yaml --run-once`.
- Run once from an installed editable package: `airesearch --config config.local.yaml --run-once`.
- Run tests: `python -m pytest -q`.
- Run an MCP adapter example: `python -m airesearch.mcp.arxiv`.

## Coding Style & Naming Conventions
- Use 4-space indentation, snake_case for functions and variables, and UPPER_SNAKE for constants.
- Prefer type hints and dataclasses where they improve clarity.
- Keep public imports and scripts pointed at package modules, not deleted root wrappers.
- New MCP adapters should live under `src/airesearch/mcp/` and expose module-based launch paths.

## Testing Guidelines
- Tests live in `tests/` and use `test_*.py` naming.
- Keep tests deterministic and avoid hard dependencies on local secrets or external services.
- For interface changes, prefer tests that exercise public package entrypoints instead of implementation-only imports.

## Commit & Pull Request Guidelines
- Use short imperative commit messages.
- Mention config or environment variable changes in PR descriptions.
- Include verification commands and results in PR notes.

## Security & Configuration Tips
- Keep secrets in environment variables, never in tracked files.
- Do not commit `config.local.yaml`, `mcp.local.json`, or `.env`.
- Sanitize logs, output artifacts, and screenshots before sharing.
