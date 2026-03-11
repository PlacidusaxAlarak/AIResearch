# Performance Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce repeat-run latency by reusing expensive external work and eliminating the dedicated email-analysis Codex pass.

**Architecture:** Keep the current orchestrator structure, add prompt-keyed persistent caches around expensive work, and render email markdown from existing scoring output instead of issuing an additional Codex request.

**Tech Stack:** Python 3.11+, `anyio`, `pytest`/`unittest`, filesystem-backed JSON caches

---

### Task 1: Add failing tests for prompt caching and source reuse

**Files:**
- Modify: `tests/test_mcp_arxiv_characterization.py`
- Modify: `tests/test_orchestrator_single_pass_characterization.py`

**Step 1: Write the failing test**

- Add a test for `source_fetch()` that prepares an existing output directory with
  an archive and `.tex` file, then verifies no download occurs.
- Add a test for `clean_latex_fulltext()` that calls it twice with the same prompt
  and expects only one Codex invocation.
- Add a test for `codex_process_paper()` that calls it twice with the same prompt
  and expects only two total Codex invocations instead of four.
- Add a test for `codex_generate_email_analysis()` that passes scoring output and
  asserts no Codex call is made.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_mcp_arxiv_characterization.py tests/test_orchestrator_single_pass_characterization.py`

Expected: new tests fail because caching and local email rendering are not implemented yet.

### Task 2: Implement filesystem-backed reuse

**Files:**
- Modify: `src/airesearch/mcp/arxiv.py`
- Modify: `src/airesearch/cli/orchestrator.py`

**Step 1: Write minimal implementation**

- Add an arXiv helper that returns a cached extraction payload when the local output
  directory already contains a usable archive and extracted `.tex` files.
- Add orchestrator helpers for:
  - cache directory resolution
  - stable cache key hashing
  - cache read/write
  - prompt-keyed Codex JSON reuse
- Route `clean_latex_fulltext()` and `codex_process_paper()` through the new cache helper.

**Step 2: Run focused tests**

Run: `python -m pytest -q tests/test_mcp_arxiv_characterization.py tests/test_orchestrator_single_pass_characterization.py`

Expected: caching tests pass.

### Task 3: Remove the dedicated email-analysis Codex pass

**Files:**
- Modify: `src/airesearch/cli/orchestrator.py`
- Test: `tests/test_orchestrator_single_pass_characterization.py`

**Step 1: Write minimal implementation**

- Change `_process_paper()` to pass scored paper metadata into email analysis.
- Render email markdown locally from existing result fields.
- Keep a safe fallback path if the scoring output is sparse.

**Step 2: Run focused tests**

Run: `python -m pytest -q tests/test_orchestrator_single_pass_characterization.py tests/test_orchestrator_notify_characterization.py`

Expected: no email-analysis Codex call remains and notification tests still pass.

### Task 4: Verify broader behavior

**Files:**
- Verify only

**Step 1: Run relevant regression checks**

Run: `python -m pytest -q tests/test_mcp_arxiv_characterization.py tests/test_orchestrator_single_pass_characterization.py tests/test_orchestrator_notify_characterization.py`

Expected: all targeted tests pass.

**Step 2: Run broader suite**

Run: `python -m pytest -q`

Expected: full suite stays green.
