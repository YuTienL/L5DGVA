# Gap-close: AI mechanism #8 — Qualification / Signoff Engine

**Status: DONE** (with a disclosed residual that is genuinely NEEDS_SEPARATE_EFFORT — see the last section)

Date: 2026-09-04
Branch: `gap-close/env-manifest-fact-sources`

---

## 1. What I re-verified from the audit myself

All of the audit's positive findings held up when I checked them directly, so
none of them were re-litigated:

- `dv_harness/gates.py` — `STAGE_GATES["SIGNOFF"]` really lists 9 gate ids, and
  `SIGNOFF` really is reachable in the shipped graph:
  `.dv-harness/graph/main_graph.json` carries
  `{"source": "PROMOTION_READINESS", "target": "SIGNOFF", "condition": "PASS"}`
  and a real `SIGNOFF` node (`review-route` / `review-agent` /
  `skills: ["verification-signoff"]`).
- `engine.py`'s `run_stage()` PASS branch really calls
  `_persist_subsystem_registry_entry()` then `_export_signoff_bundle()`
  unconditionally, and `_export_signoff_bundle()` really is the production-path
  caller of `signoff_export.collect_signoff_bundle()`.
- `signoff_export.read_signoff_stage_status()` really reads the project's own
  `state.json` / `events.jsonl` / subsystem registry, and really refuses under
  `require_signoff_pass=True`.
- `dv_harness_tests/test_signoff_stage_gate_e2e.py` really drives a
  non-mocked 9-gate `run_stage("SIGNOFF")`.

The audit's *named* condition also held: no project in this repo has ever
reached SIGNOFF (`v50/.dv-harness/state.json` is still
`current_stage: ENV_CHECK`, `stages.SIGNOFF.status: NOT_STARTED`).

## 2. The real, in-scope defect I found while in the code

Reading `run_stage()` around the PASS branch surfaced a concrete code defect
in this exact mechanism that the audit had not isolated:

`run_stage()` deliberately holds a fully gate-verified SIGNOFF at `WAIT_USER`
when no `dv-harness approve SIGNOFF` is on record — engine.py's own comment
says why ("PROMOTION_READINESS/SIGNOFF passing their own automated gates is not
the same thing as a human sign-off", the "LSF DONE != DV PASS" principle one
level up). **But the whole `if verdict == "PASS":` side-effect block runs on
gate verdict alone, and it runs after that downgrade.**

`_export_signoff_bundle()` re-checks the recorded stage status for precisely
this reason and documents it. Its sibling
`_persist_subsystem_registry_entry()` — **the only writer anywhere of
`.dv-harness/soc-composer/subsystem_environment_registry.json`** — did not.

So: a SIGNOFF still waiting on a human already wrote its subsystem into the
real runtime registry as `PRODUCTION_QUALIFIED`, emitted a
`SUBSYSTEM_ENVIRONMENT_REGISTERED` audit event, and wrote the
`subsystem_registry` Blackboard topic.

That registry is not a log. It is consumed by:

- `environment_mode_router.read_registered_subsystem_entries()` →
  `uvm_generator.soc_environment_composer.compose_soc_environment()` (a
  SYSTEM_LEVEL composition would be built on an unapproved subsystem);
- `STAGE_GATES["SYSTEM_LEVEL"]`'s `system_level_validator`, whose
  harness-supplied `--registered` ContextFlag cross-checks agent claims
  against that file;
- `signoff_export.read_signoff_stage_status()`, which reports
  `subsystem_registry_present` as **"independent corroboration"** of a real
  SIGNOFF PASS — making an unapproved entry a false corroboration of the very
  approval it skipped.

### Proven, not asserted

Written as a failing test first, against the real 9-gate path:

```
python -m pytest dv_harness_tests/test_signoff_stage_gate_e2e.py::test_signoff_gates_passing_without_human_approval_qualifies_nothing -q
→ FAILED ... AssertionError: assert not True      (registry file existed)
```

## 3. The fix

`dv_harness/engine.py`, `_persist_subsystem_registry_entry()` — one guard,
placed in the writer rather than only at the call site so any future caller
inherits it (and because it is the sole writer of a governance-critical file):

```python
if self.state.stages.get(stage, {}).get("status") != Status.PASS.value:
    return
```

Reads `self.state.stages` (the same dict `run_stage()` just wrote `ss` into),
not on-disk `state.json`, because the final `store.save()` happens well after
this block — exactly the reasoning `_export_signoff_bundle()` already documents.
A ~28-line docstring section records the ruling in place.

No parallel mechanism was built; nothing was reinvented. The existing
approval hard-stop simply now governs the durable artifact too.

## 4. Tests

New end-to-end test (real subprocess gates, nothing mocked but the LLM
adapter), `dv_harness_tests/test_signoff_stage_gate_e2e.py::test_signoff_gates_passing_without_human_approval_qualifies_nothing`.
It is a controlled comparison — identical evidence, identical 9 real gates,
the *only* difference being the missing `ControlPlane.approve("SIGNOFF")`:

1. all 9 SIGNOFF gates really passed (`last_evidence_blocks` ⊇ `STAGE_GATES["SIGNOFF"]`);
2. stage correctly held at `WAIT_USER` with `HUMAN_APPROVAL_REQUIRED`;
3. **no registry file at all**, `read_signoff_stage_status()` reports
   `gate_verified: False` / `subsystem_registry_present: False`, and
   `read_registered_subsystem_entries() == []`;
4. no signoff bundle;
5. no `SUBSYSTEM_ENVIRONMENT_REGISTERED` / `SIGNOFF_BUNDLE_EXPORTED` event and
   no `subsystem_registry` Blackboard topic;
6. **the hold is not permanent** — a real `approve` followed by the same
   evidence does register, proving the guard blocks the unapproved case
   specifically rather than the mechanism as a whole.

Also refactored `_drive_signoff_to_pass` into `_drive_signoff(tmp, approve=)`
so both halves run the identical path.

Two existing tests that call the private writer directly now set its real
precondition explicitly (this is a *more* faithful setup, not a weakening):
`test_engine_gates_and_routing.py::test_engine_persists_subsystem_registry_entry_on_signoff_pass`
(which also gained a direct `WAIT_USER → persists nothing` case) and
`test_system_level_soc_composition_wiring.py::_register_subsystems`.

### Results

| Suite | Result |
|---|---|
| `test_signoff_stage_gate_e2e.py` | **5 passed** in 251.81s |
| `test_system_level_soc_composition_wiring.py` + `test_inference_engine_wiring.py` + `test_signoff_export.py` | **33 passed** in 858.81s |
| `test_environment_mode_router.py` + `test_soc_environment_composer.py` + `test_signoff_bundle_hash.py` + `test_signoff_bundle_completeness_gate.py` | **40 passed** in 139.47s |
| `test_engine_gates_and_routing.py` | **239 passed** in 1503.71s |

Total: **317 passed, 0 failed**, all after the fix.

## 5. Concurrency handling

`dv_harness/engine.py` had large uncommitted changes from other concurrent
workstreams in this same session (stage-progress-display, subsystem Blackboard
topics), and the index carried another workstream's staged memory work. The
commit was therefore produced through a **temporary index built from HEAD**
with only my single engine.py hunk applied plus my three test files — the real
index and every other workstream's staged/unstaged state were left untouched.

Commit: `984d75e signoff: the human-approval hard-stop must govern the
subsystem registry too` (4 files, +166/-4; `git diff <parent> 984d75e --stat`
confirms it reverts nothing from the concurrent commits it landed on top of).
The shared index's `engine.py` entry was then re-synced so a concurrent commit
from another workstream could not silently revert the guard.

## 6. Disclosed residual — NEEDS_SEPARATE_EFFORT

The audit's *original* literal ask — drive a real project all the way to a
SIGNOFF PASS inside this repo's own operational history — was **not** attempted
and should not be attempted as a wiring pass. It requires:

- a real subject project (not `v50` itself) with real RTL/VIP,
- a real simulator (VCS) and real regression/coverage/RCA artifacts,
- sequentially clearing ~30 real stage gates ENV_CHECK → … → PROMOTION_READINESS
  with genuine evidence at each,
- real human `dv-harness approve PROMOTION_READINESS` / `approve SIGNOFF`.

That is a full DV campaign, not a code change, and no amount of code editing
closes it. It is the same disclosed-residual shape this repo already carries
for mechanism #14 (SoC composition): the code is proven correct on a real
non-mocked path, but this harness's own dev-tree has never been the subject
project that reaches that stage.

**Scope for that follow-up effort:** run one real USB (or AMBA4) environment
generation + verification campaign end-to-end through `DVHarness.run_stage()`
against a project root with a real simulator available, and land its
`.dv-harness/state.json` (`stages.SIGNOFF.status == "PASS"`), its
`events.jsonl` `SIGNOFF_BUNDLE_EXPORTED` record, and its
`subsystem_environment_registry.json` as the first real firing.

## 7. Adjacent observation (NOT fixed — out of mechanism #8's scope)

The same "side effects run past a human-approval downgrade" shape may affect
`_promote_verified_fix_knowledge()` on a `RE_AUDIT` held at `WAIT_USER` by
`_re_audit_requires_human_approval()` (HIGH risk / DUT_BUG). That belongs to
mechanism #7 (5-Level Memory Engine); it was deliberately left alone here
rather than widened into an unscoped edit, and is flagged for whoever owns #7.

## 8. Files changed

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\engine.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_signoff_stage_gate_e2e.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_engine_gates_and_routing.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_system_level_soc_composition_wiring.py`
