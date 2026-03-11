# Core-Direction Feed Design

**Date:** 2026-03-11

**Context**

The current daily feed mixes core LLM post-training and agent-RL work with adjacent
application papers. Today's run included papers that the generated email bodies
explicitly described as indirect overlap, domain-specific, or not frontier LLM+RL,
yet they were still sent.

The user-approved direction is to narrow the main feed to these core anchors:

- RLVR
- RLHF
- GRPO/DPO/PPO variants
- PRM
- Reward Hacking
- Agentic RL
- Tool-Calling
- Agent
- Multi-Turn Agent

Application domains such as robotics, recommendation, multimodal alignment, and
image restoration should no longer enter the main feed unless they clearly present
new methods within those core directions.

## Root Cause

Two independent issues are causing the current wide behavior:

1. Retrieval terms are too broad and include application/domain phrases as first-class
   discovery keywords.
2. The candidate gate exists in code, but the notification pipeline does not use it
   before sending email.

Narrowing keywords alone would help precision, but it would not fix the fact that
low-fit papers can still flow through the pipeline once prepared.

## Chosen Approach

Implement a focused "core-direction" feed in three coordinated changes:

1. Shrink the main retrieval keywords to a high-precision set centered on the
   approved method and agent-interaction anchors.
2. Rewrite topic groups so they score only the approved core directions instead of
   domain/application buckets.
3. Route prepared papers through the existing candidate gate before saving notes and
   sending notifications.

This keeps the current orchestrator structure intact while making the main feed
behave like a real hard-filtered research tracker instead of a broad neighborhood
discovery tool.

## Alternatives Considered

### Option 1: Config-only tightening

This is lower risk, but it leaves the missing candidate-gate enforcement in place.
Low-fit papers could still be sent if they survive retrieval and Stage1.

### Option 2: Gate-only enforcement

This would block some weak papers at the end, but the system would still spend time
preparing and analyzing many domain-adjacent papers, which wastes runtime and keeps
Stage1 noisy.

### Option 3: Retrieval tightening plus enforced candidate gate

This is the recommended option and the one approved for implementation. It reduces
noise early, preserves runtime for core papers, and finally makes the configured
candidate thresholds matter.

## Scope

### In scope

- Tighten `config.local.yaml` to the approved core-direction anchors.
- Update `config.example.yaml` to show the same public high-precision pattern.
- Refine the candidate scoring prompt so relevance is judged against the approved
  core directions and excludes domain-only overlap.
- Enforce `evaluate_candidate_gate()` in the main prepared-paper processing path.
- Add regression tests for the new gating behavior and config defaults.

### Out of scope

- Redesigning the orchestrator CLI
- Creating separate side feeds for application domains
- Changing MinerU or source-extraction behavior
- Changing whitelist semantics

## Data Flow

### Discovery

- Use only high-precision core-direction discovery keywords.
- Do not use application-domain phrases as discovery seeds.

### Stage1

- Score papers only against the new core-direction topic groups.
- Keep the existing Stage1 structure, but feed it narrower topic terms.

### Candidate Gate

- After a paper is prepared and before any note or email side effect, run
  `evaluate_candidate_gate()`.
- Reject papers that do not meet weighted score, relevance, and evidence thresholds.
- Log the rejection reason and stop processing for that paper.

### Notification

- Only gated-in papers are saved to Obsidian and sent by email.
- Rejected papers remain absent from the notification channel.

## Testing Strategy

- Add a regression test proving `_process_paper()` does not call `notify()` when the
  candidate gate rejects the paper.
- Add a regression test proving `_process_paper()` still notifies when the candidate
  gate passes.
- Add config characterization checks that the example and local configs expose the
  new core-direction keyword layout.

## Risks

- Precision will increase, but recall will drop for papers that do not mention the
  core anchor terms explicitly.
- Existing cached analysis output may still reflect old prompt wording until new runs
  generate fresh cache entries.
- The local runtime config is intentionally opinionated; if the user later wants a
  broader side feed, that should be modeled separately instead of widening the main
  feed again.
