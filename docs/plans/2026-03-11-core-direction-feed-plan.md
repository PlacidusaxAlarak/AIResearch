# Core-Direction Feed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Tighten the main research feed to core RL/agent directions and enforce the existing candidate gate before notes and notifications are emitted.

**Architecture:** Keep the current orchestrator pipeline, but narrow discovery/topic config to core-direction anchors and insert the existing candidate gate into `_process_paper()` so low-fit papers stop before downstream side effects.

**Tech Stack:** Python 3.11+, `anyio`, `pytest`/`unittest`, YAML config, prompt templates

---

### Task 1: Add failing regression tests for notification gating

**Files:**
- Modify: `tests/test_orchestrator_single_pass_characterization.py`

**Step 1: Write the failing test**

- Add one test where `_process_paper()` receives a prepared paper, the candidate gate
  returns `passed=False`, and `notify()` must not be called.
- Add one test where the candidate gate returns `passed=True` and `notify()` must be
  called exactly once.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_orchestrator_single_pass_characterization.py -k candidate_gate`

Expected: the new rejection-path test fails because `_process_paper()` currently
always notifies after analysis.

### Task 2: Add failing config characterization tests

**Files:**
- Modify: `tests/test_orchestrator_cli_characterization.py`

**Step 1: Write the failing test**

- Add a test that loads `config.example.yaml` and verifies its `keywords` list is a
  compact high-precision core-direction set without the old domain/application terms.
- Add a test that loads `config.local.yaml` and verifies it follows the same core
  direction theme.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_orchestrator_cli_characterization.py -k keyword`

Expected: tests fail because the current configs still contain broad domain terms.

### Task 3: Implement candidate-gate enforcement

**Files:**
- Modify: `src/airesearch/cli/orchestrator.py`
- Test: `tests/test_orchestrator_single_pass_characterization.py`

**Step 1: Write minimal implementation**

- In `_process_paper()`, evaluate the prepared paper source text through
  `evaluate_candidate_gate()`.
- If the gate rejects the paper, log the decision and return without calling
  `save_to_obsidian()` or `notify()`.
- Preserve the whitelist exception path.

**Step 2: Run focused tests**

Run: `python -m pytest -q tests/test_orchestrator_single_pass_characterization.py -k candidate_gate`

Expected: the new gating tests pass.

### Task 4: Tighten prompts and configs

**Files:**
- Modify: `config.example.yaml`
- Modify: `config.local.yaml`
- Modify: `prompts/codex_candidate_score.txt`

**Step 1: Write minimal implementation**

- Replace broad application-heavy keyword lists with the approved core-direction
  anchors.
- Rewrite topic groups to focus on:
  - RLVR
  - RLHF
  - PPO/GRPO/DPO variants
  - PRM
  - Reward Hacking / oversight failures
  - Agentic RL / tool-calling / multi-turn agents
- Update the candidate-scoring prompt so relevance explicitly requires one of those
  core directions and treats domain-only overlap as low relevance.

**Step 2: Run focused tests**

Run: `python -m pytest -q tests/test_orchestrator_cli_characterization.py -k keyword`

Expected: config characterization tests pass.

### Task 5: Verify targeted regressions

**Files:**
- Verify only

**Step 1: Run targeted regression suite**

Run: `python -m pytest -q tests/test_orchestrator_single_pass_characterization.py tests/test_orchestrator_cli_characterization.py tests/test_orchestrator_candidate_gate_characterization.py`

Expected: all targeted tests pass.

### Task 6: Verify broader orchestrator behavior

**Files:**
- Verify only

**Step 1: Run broader regression suite**

Run: `python -m pytest -q tests/test_orchestrator_notify_characterization.py tests/test_orchestrator_seen_behavior_characterization.py tests/test_orchestrator_super_whitelist_characterization.py`

Expected: surrounding orchestrator behavior remains green.
