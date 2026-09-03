# Gap Close — AI Mechanism #5: Plan-and-Execute / ReAct Engine

**Verdict: DONE**

Execution mode: LOCAL_ANALYSIS (pure local read/edit/pytest; no server, no VCS,
no real `claude` CLI invocation — every engine-driven test below drives the
REAL `DVHarness.run_stage()` with the real `main_graph.json` and the real
`tools/verification_flow/*.py` gate scripts against a fake adapter, which is
the local equivalent of the audit's stated re-run verification).

Date: 2026-09-04

---

## What the audit found (re-confirmed against the live tree before touching anything)

The audit's PARTIALLY_WIRED verdict held exactly as written. Re-read and
re-confirmed first-hand:

1. `InnerReactLoop` really is unconditionally wired into the real stage flow
   (`engine.py`, the `elif node.react and cfg["policy"].get("enable_inner_react_loop", True)`
   branch; `graph.Node.react` defaults `True`, and no node in
   `.dv-harness/graph/main_graph.json` sets it False).
2. Every real persisted `reflect_*.json` in this repo showed a **1-option
   menu** (`CONVERGE_TERMINATE`) and a trivial "choice" of it —
   `.dv-harness/react/INTAKE/attempt_001/reflect_001.json` is the clearest:
   two of INTAKE's four configured gates report
   `{"status": "FAIL", "reason": "NO_EVIDENCE_BLOCK_SUPPLIED"}` with **no
   other detail keys at all**, and `build_menu()`'s four original option
   sources every one require the failing gate's own `detail` to already
   enumerate a `missing` / `dv_review_unresolved_fields` /
   `missing_subpayload` list, or a `protocol`+`missing` pair.
3. `.dv-harness/memory/working/WM-REACT-*.json` carried no `gap` field at
   all, and its `confidence`/`next_action` came from a hardcoded
   status-keyed string map in `engine.py`, not from
   `dv_harness/inference.py` — despite CLAUDE.md's Engineering Memory Policy
   naming `score_confidence()`/`identify_gap()`/`next_best_action()` as the
   mechanism for exactly this record kind.

This is a wiring gap, not a new capability — closed in this pass.

---

## What changed

### 1. `dv_harness/react_loop.py` — `build_menu()` source #5

New option source for the failure shape that actually occurs in production:
a gate the agent supplied **no evidence block for**. The missing thing there
is unambiguous real data (that gate's own ```` ```dv-harness-evidence:<gate_id>` ````
block, named by `STAGE_GATES[stage]` via the signature list
`gates._evaluate_stage_evidence_core()` already builds from it), so a real
`REQUEST_EVIDENCE` option is now synthesized for it.

- The missing set is computed through the **real `inference.identify_gap()`**
  set difference over the stage's own configured gate-id vocabulary — not a
  hand-rolled comprehension.
- `next_best_action()` is consulted for a real
  `protocol_builder_registry.json` item and the rationale cites it when one
  exists; the option is offered either way, because "supply the block this
  gate requires" is actionable regardless of registry coverage.
- Suppressed under `no_new_information`, exactly like the pre-existing
  `RETRY_TARGETED` sources — re-asking for the same block after a
  demonstrably no-op retry is not a different action.
- Additive `protocol=None` parameter on `build_menu()` and
  `InnerReactLoop.__init__` (documented as "THIRD DEVIATION" in the module
  header, alongside the two existing ones): `engine.py` passes the real
  `route_info["protocol_decision"]["protocol"]` it already resolved, because
  a gate that never ran cannot name a protocol in its own detail. `None`
  degrades to `"_general"`.

### 2. `dv_harness/engine.py` — `_react_step_inference()`

New method computing the full Hypothesis → Evidence → **Confidence → Gap →
Next-Best-Action** chain for the **in-flight** attempt, from data that
attempt really produced:

| field | real source |
|---|---|
| `gap` | `identify_gap(effective_stage_gates(stage), gates that really got a block)` |
| `confidence` / `confidence_detail` | `score_confidence(independent_sources_count=len(supplied), evidence_refs_verified=<adapter ok AND no gate missing its block AND every signature ok>, counter_evidence_count=len(failing signatures), multi_agent_consensus_count=_rca_fanout_agent_evidence_count() at RCA_JOIN)` |
| `next_action` | `reroute:<node>` when the inner loop really chose a REROUTE, else `next_best_action()`'s suggestion for the first gap, else `retry_targeted:<real failing gate ids>`, else `advance` |

This deliberately does **not** duplicate `_root_cause_confidence_inputs()`:
that derives its counts from a `root_cause_evidence_gate` block that only
exists after a stage has already passed. The in-flight attempt has a
different real evidence surface (configured gates + this attempt's own
signatures), and both feed the same single `score_confidence()`
implementation.

Wired at the real `self.react.record(...)` call site, replacing:

```python
confidence=("HIGH" if ss["status"] == Status.PASS.value
            else "LOW" if ss["status"] == Status.FAIL.value else "MEDIUM"),
next_action=("advance" if ss["status"] == Status.PASS.value else "retry_or_reroute"),
```

Two supporting corrections in the same method:
- `structured_signatures` is now initialized alongside `evidence_blocks` so
  the ADAPTER_FAIL path (which never evaluates a gate) still scores honestly
  instead of raising.
- This attempt's reroute choice is now a **local**, not a read-back of
  `ss["react_reroute_target"]` — that state key survives across attempts and
  would have attributed a prior attempt's reroute to one that made none.

### 3. `dv_harness/react.py` — `gap` + `confidence_detail` on the record

`ReactRecorder.record()` takes two additive optional parameters (`gap=None`,
`confidence_detail=None`) and persists both into **both** write targets:
`iteration_NNN.json` and the `react_reasoning_step` Working Memory
projection routed through `memory_router.route_and_store()`. `MemoryStore.add()`
is pass-through, so no schema change was needed on the store side. Every
pre-existing caller/test that omits them is unaffected.

### 4. `.claude/skills/CORE/working-memory/SKILL.md`

The skill already described the Hypothesis/Evidence/Confidence/Gap/
Next-Best-Action contract; it now states what the engine really writes for
every stage attempt, so an agent reads the persisted record rather than
re-deriving these by hand (Methodology Consolidation Rule). No `industrial`/
`PACKAGE` deliverable trees exist under `v50`, so no sync was applicable.

---

## Behavioral consequence, stated openly

A stage with **no configured gate at all** (`NO_GATE_REQUIRED`) now records
`confidence: LOW` where the old string map said `HIGH` purely because the
status read PASS. That is the honest answer under this project's own formula
(zero independent sources, nothing verified) and the same principle
`run_stage()` already applies one level up ("transport success is NOT the
same as DV PASS"). A single-gate stage that really passes scores MEDIUM; a
multi-gate stage that really passes scores HIGH. The number now tracks how
much real evidence backs the step.

---

## Tests

New: `dv_harness_tests/test_react_inference_wiring.py` (10 tests), all
asserting against the **real persisted artifacts** the audit itself read:

- the real degenerate signature shape is reproduced from the real gate core
  (grounding assertion), then `build_menu()` yields `len(menu) > 1` with real
  `REQUEST_EVIDENCE` targets equal to the real configured-gate set difference;
- the new option is suppressed on `no_new_information`, and cites a real
  registry item only when the resolved protocol has one;
- `run_stage()` end to end: the persisted
  `.dv-harness/react/ARCH_CALIBRATION/attempt_001/reflect_001.json` now has
  `len(menu) > 1`, a chosen `REQUEST_EVIDENCE:*` option with
  `source == "stage_gate_missing_evidence_block"`, `converged: false`, and a
  real targeted adapter re-invocation naming that gate — the audit's exact
  stated verification criterion;
- `run_stage()` end to end: `WM-REACT-ARCH_CALIBRATION-001.json` carries a
  real `gap` equal to `identify_gap()` over the real configured gates, a
  `confidence_detail` whose `score` equals the real formula on real counts
  (`1*2 - 2*3`), and a `next_action` equal to the real `next_best_action()`
  suggestion and explicitly `!= "retry_or_reroute"`;
- **contrast case** proving the number is evidence-driven, not status-driven:
  the same stage with the same resulting `PARTIAL` status but every gate
  supplied (one failing on content) scores `3*2 - 1*3` / MEDIUM with an empty
  gap and `next_action == "reroute:ARCH_DISCOVERY"` — where the old map
  reported an identical MEDIUM/`retry_or_reroute` for both runs;
- ADAPTER_FAIL stays honest (whole gate list is the gap, score 0, LOW, no
  invented counter-evidence);
- regression guard that `node.react` and the graph file keep this live.

**Test summary**: `test_react_inference_wiring.py` 10 passed; the relevant
existing suites (`test_react_loop.py`, `test_react_working_memory_bridge.py`,
`test_inference.py`, `test_inference_engine_wiring.py`,
`test_engine_gates_and_routing.py`, `test_debug_flow_memory.py`,
`test_memory_search_filters.py`, `test_memory_write_guard_and_job_evidence.py`)
all pass — see the commit for the exact run.

---

## Concurrency handling

`dv_harness/engine.py` is shared with other concurrent workstreams and moved
twice during this task:

- At the start it was dirty with ~92 uncommitted lines from the Section-3
  resource/cost workstream (`_escalate_unreachable_coverage_holes`,
  `_computed_regression_selection`).
- Mid-task, that workstream committed (`a8d97f2`) and swept up one of this
  task's already-made edits in the process — the `structured_signatures` /
  `react_reroute_target` local initialization now sits in HEAD under their
  commit rather than this one. Noted here rather than re-litigated: the code
  is correct and present either way, and re-cutting it out would have
  rewritten another workstream's commit.
- A third workstream (harness-reliability: `_resolve_degradation_transport`,
  `degraded_probe_transport`) then landed further uncommitted engine.py edits.

The commit therefore uses the **hand-scoped patch technique**: `git diff` was
split into hunks, only this task's four (`_react_step_inference`, the
`InnerReactLoop(protocol=...)` + reroute-local hunk, the `step_inference`
computation, and the `record()` arguments) were applied to the index with
`git apply --cached`, and the staged blob was verified to contain none of the
other workstreams' identifiers and to parse. Their work remains uncommitted in
the working tree, untouched (`git status` still shows `M dv_harness/engine.py`).

`react.py`, `react_loop.py`, the new test file and the skill file were clean at
HEAD and are committed whole.

Commit: `c2d6efd` (local, on `master`; not pushed — per CLAUDE.md's PR-only
governance an agent never pushes/merges a protected branch).
