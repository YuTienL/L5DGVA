# Gap close — AI mechanism #8: Qualification / Signoff Engine

**Verdict: DONE.**

Audit verdict was PARTIALLY_WIRED with two concrete, in-scope gaps. Both are closed for real,
with tests that fail against the pre-change code.

## What the audit found (re-verified myself before touching anything)

1. `read`-only re-check of this repo's own real governance state, via the new reader:

   ```
   $ python -c "from pathlib import Path; from dv_harness import signoff_export; ..."
   {"state_file_present": true, "current_stage": "ENV_CHECK", "stage_status": "NOT_STARTED",
    "gate_verified": false, "signoff_event_count": 0, "subsystem_registry_present": false,
    "required_signoff_gates": [ ...the 9 real gates... ]}
   ```

   Exactly the audit's finding, now as a machine-readable fact instead of a hand-run grep:
   SIGNOFF `NOT_STARTED`, zero `"stage": "SIGNOFF"` records in `events.jsonl`, and no
   `.dv-harness/soc-composer/subsystem_environment_registry.json` (the file
   `engine._persist_subsystem_registry_entry()` writes ONLY on a real SIGNOFF PASS).

2. `grep -rn 'run_stage(\s*"SIGNOFF"' dv_harness_tests/*.py` → zero matches, and
   `test_engine_gates_and_routing.py:3046`'s own comment says why: it calls the private
   persistence method directly "rather than driving a full `run_stage()` SIGNOFF PASS, which
   would require constructing valid payloads for all 9 real SIGNOFF gates".

3. `signoff_export.collect_signoff_bundle()` contained no reference to `current_stage`,
   `state.json` or `STAGE_GATES["SIGNOFF"]` — confirmed by reading the whole 333-line file.

## What changed

### 1. `dv_harness/signoff_export.py` — the export is now gate-aware

- **New `read_signoff_stage_status(root)`**: reads the REAL harness-owned files — `state.json`'s
  `stages["SIGNOFF"]["status"]`, the count of `events.jsonl` records naming the SIGNOFF stage,
  and the presence of `subsystem_environment_registry.json` — never an agent-attested claim.
  Deliberately reads `state.json` with a plain `json.loads` rather than through
  `storage.StateStore`, because `StateStore.load()` *creates* a `state.json` when none exists;
  an export must never mutate governance state, and "never recorded" must not become
  "freshly-minted NOT_STARTED". Those two are kept as distinct values (`NOT_RECORDED` vs
  `NOT_STARTED`) — the repo really does contain a `state.json` with no `stages` map at all
  (`.work/_e2e_demo_usb3_lfps/`), and that is a different fact from a recorded not-started.
- **`collect_signoff_bundle()` stamps it** into three places: a real bundled file
  `signoff_stage_status.json` (an 11th manifest artifact, so its presence is covered by
  `bundle_hash`), `manifest.json`'s new top-level `signoff_stage` + `bundle_kind` keys, and the
  return dict. `bundle_kind` is `SIGNOFF_GATE_VERIFIED` or `PRE_SIGNOFF_GATE_INPUT`, so a bundle
  from a project that never ran a SIGNOFF gate can no longer look equivalent to one that did.
- **`require_signoff_pass=True`** (CLI `--require-signoff-pass`, exit code 2) refuses outright
  and writes *nothing at all* — not even an empty `out_dir` a later reader could mistake for a
  partial bundle.

  **Deliberate design ruling, differing from the audit's first suggestion:** refusal is opt-in,
  not the default. `signoff_bundle_completeness_gate` — one of the 9 SIGNOFF gates — takes a real
  `bundle_dir` produced by `collect_signoff_bundle()` as its own INPUT and recomputes
  `compute_bundle_hash()` over its real `manifest.json`. A bundle therefore *has* to be producible
  before SIGNOFF can pass; defaulting to refusal would make the SIGNOFF gate battery unsatisfiable
  by construction. The honest fix is that a pre-gate bundle can no longer *look* gate-verified,
  not that pre-gate bundles are forbidden. `compute_bundle_hash`'s material is unchanged (artifact
  list only) so the gate's independent recomputation still works byte-for-byte.

  Proven live against this repo:

  ```
  $ python -m dv_harness.cli --project-root . signoff-export --out .work/_audit_signoff_gateaware_check --require-signoff-pass
  {"status": "REFUSED", "reason": "SIGNOFF_STAGE_NOT_PASSED", ...}
  EXIT=2
  $ ls .work/_audit_signoff_gateaware_check
  ls: cannot access '.work/_audit_signoff_gateaware_check': No such file or directory
  ```

### 2. `dv_harness/engine.py` — the real production-path caller that never existed

New `_export_signoff_bundle(stage)`, called from `run_stage()`'s `verdict == "PASS"` side-effect
block right after `_persist_subsystem_registry_entry()`. Before this, `signoff_export`'s only
callers were the `signoff-export` CLI and the dashboard's POST button — **both of which bypass
`STAGE_GATES["SIGNOFF"]` entirely**, so no bundle anywhere was ever the consequence of a
gate-verified signoff. It writes `.dv-harness/signoff_bundle/` and logs a real
`SIGNOFF_BUNDLE_EXPORTED` event.

Two conditions are re-checked inside it rather than assumed from the call site, because that
block runs on gate verdict alone:
- the stage's own in-memory status must really be `PASS` — SIGNOFF is downgraded to `WAIT_USER`
  when no `dv-harness approve SIGNOFF` is on record, and gates passing is not the same as the
  stage closing;
- `state.json` is flushed to disk **first**. `run_stage()`'s final `store.save()` happens well
  after this side-effect block, so without the flush the export would read back the `RUNNING`
  status written at the *start* of the attempt and stamp a genuinely gate-verified bundle
  `PRE_SIGNOFF_GATE_INPUT`.

Same best-effort contract as its neighbours: an export failure logs `SIGNOFF_BUNDLE_EXPORT_FAILED`
and never downgrades an already-earned SIGNOFF PASS.

### 3. `dv_harness_tests/test_signoff_stage_gate_e2e.py` (new) — the exact fix condition

`test_run_stage_signoff_passes_all_nine_real_gates_end_to_end` is the first
`h.run_stage()` → SIGNOFF PASS anywhere in this repo. It drives the real engine with a real
`main_graph.json` and the project's own copy of `tools/`, real `gates.run_gate()` subprocesses,
a real `ControlPlane.approve("SIGNOFF")`, and evidence answering all 9 gates. Only the LLM
adapter is stubbed. It asserts:

- `state.json`'s `stages["SIGNOFF"]["status"] == "PASS"` (on disk, not just in memory),
- the submitted evidence blocks cover every id in `STAGE_GATES["SIGNOFF"]` — so the test cannot
  silently go stale if a 10th gate is added,
- `subsystem_environment_registry.json` gets written with this run's real entry,
- `events.jsonl` carries real `"stage": "SIGNOFF"` records including
  `SUBSYSTEM_ENVIRONMENT_REGISTERED`.

Note the gate battery is genuinely unfakeable at two points: `signoff_bundle_completeness_gate`
recomputes the bundle hash off a real on-disk manifest, and `signoff_snapshot_immutability_gate`
recomputes the snapshot digest — so the test derives both rather than hardcoding a literal.

Three more tests cover the export side: the gate-verified bundle appearing on the real path,
`--require-signoff-pass` refusing before the gate and allowing after it (both halves of the
audit's named bypass condition, in one test), and `read_signoff_stage_status` reporting absence
honestly without minting a `state.json`.

## Files changed

- `dv_harness/signoff_export.py`
- `dv_harness/engine.py`
- `dv_harness/cli.py` (`--require-signoff-pass` flag + non-zero exit on refusal)
- `dv_harness_tests/test_signoff_stage_gate_e2e.py` (new)
- `dv_harness_tests/test_signoff_export.py`, `dv_harness_tests/test_dashboard_interactive.py`
  (updated for the 11th manifest artifact)

`cli.py` also carried a *staged, uncommitted* change from a concurrent workstream (a
`question_queue` `options=` fix). A hand-scoped blob — HEAD's `cli.py` plus my two hunks only,
staged through a temporary index — was prepared for that case; by commit time that workstream had
landed its own commit (`7603119 question-queue: accept the spec's flat-string options shape at one
door`), so `cli.py`'s remaining diff was mine alone and a plain per-file `git add` was correct.
`dv_harness/connectivity.py` / `dv_harness_tests/test_connectivity.py` had unstaged changes from
another concurrent workstream and were deliberately left untouched and uncommitted.

## Test summary

`dv_harness_tests/test_signoff_stage_gate_e2e.py` 4 passed; the pre-existing signoff/export/
escalation/bundle-gate suites 38 passed; `test_engine_gates_and_routing.py` +
`test_blackboard_subsystem_wiring.py` re-run clean after the engine change.

## Not attempted (out of scope for this pass, per the audit's own item 3)

Driving the real 34-stage graph end-to-end against `.work/_e2e_demo_usb3_lfps` to a genuine
SIGNOFF PASS. That needs an agent walking `ENV_CHECK → … → PROMOTION_READINESS → SIGNOFF` with
real evidence at every stage, which is a run, not a code fix. The mechanism it would have proven
is now proven mechanically by the e2e test instead.
