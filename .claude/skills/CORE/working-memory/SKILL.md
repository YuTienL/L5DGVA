---
name: working-memory
description: 保存當前 Graph Node、Plan Step、Agent Task、hypothesis 與短期 execution context；未驗證 hypothesis 不得升級為長期記憶。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# working-memory
保存當前 Graph Node、Plan Step、Agent Task、hypothesis 與短期 execution context；未驗證 hypothesis 不得升級為長期記憶。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: durable, per-attempt storage for reasoning-in-progress -- the
Hypothesis/Evidence/Confidence/Gap/Next-Best-Action trail survives a crashed
session or a context-window reset even before anything is verified.

**Inputs**: a record dict with `kind` (most commonly `"react_reasoning_step"`
for a react.py ReactRecorder stage attempt, or any kind that does not match
a more specific router rule), plus whatever hypothesis/evidence/gap fields
the caller has at that point.

**Outputs**: `dv_harness.memory_router.route_and_store(root, record, cfg)`
returns `{"destination": "WORKING_MEMORY", "level": "working",
"memory_id": "MEM-XXXXXXXXXX"}`. The record lands under
`.dv-harness/memory/working/<memory_id>.json` via
`dv_harness.memory.WorkingMemoryStore`.

**Preconditions**: none -- this is the router's fallback destination
(`route_memory()`'s final `return "WORKING_MEMORY"`), so any record whose
`kind` does not match a JOB/PROJECT/ENGINEERING/ORGANIZATIONAL/
CORNER_CASE/BLACKBOARD/CLAUDE_PROJECT_MEMORY rule lands here by default --
including an unverified hypothesis, which is exactly where it belongs.

**Execution Steps**:
1. Build the record (hypothesis, supporting/counter evidence refs, current
   gap, next-best-action -- see `dv_harness.inference`).
2. Call `route_and_store(root, record, cfg)` (or let react.py's
   `ReactRecorder` do it per stage attempt automatically).
3. Never call `WorkingMemoryStore.add()` directly from a debugging agent --
   go through the router so routing/sharing rules stay centralized.

**What the engine itself already writes here (2026-09-04)**: for every real
stage attempt, `engine.DVHarness.run_stage()` computes
`_react_step_inference()` and hands `ReactRecorder.record()` a real `gap`
(`inference.identify_gap()` over the stage's configured gates vs. the
evidence blocks the attempt actually supplied), a real `confidence` +
`confidence_detail` (`inference.score_confidence()`'s exact
level/score/capped_by_counter_evidence dict) and a real `next_action`
(`inference.next_best_action()`'s suggestion for the first gap, a
`reroute:<node>` when the inner ReAct loop chose one, or the real failing
gate ids to retry). These used to be hardcoded strings keyed off the stage
status; do not re-derive them by hand in an agent -- read the persisted
record.

**Fallback**: none needed -- writing here never fails on missing
verification, since nothing here claims to be verified.

**Evidence Requirements**: none beyond whatever the caller already has --
working memory intentionally accepts partial/low-confidence state.

**Failure Conditions**: a `kind` of `credential`/`password`/`token`/`secret`
is REJECTed by the router before it ever reaches this tier (see
`route_memory()`); Never rule in the Engineering Memory Policy
(`CLAUDE.md`) still applies here.

**Example**:
```python
from dv_harness.memory_router import route_and_store
route_and_store(root, {
    "kind": "react_reasoning_step", "protocol": "USB", "scope": "branch_b0",
    "hypothesis": "scoreboard mismatch is a checker off-by-one, not a DUT bug",
    "evidence": ["sim.log:1204: UVM_ERROR scoreboard mismatch"],
    "gap": ["waveform not yet inspected"], "confidence": "LOW",
}, cfg=cfg)
```
