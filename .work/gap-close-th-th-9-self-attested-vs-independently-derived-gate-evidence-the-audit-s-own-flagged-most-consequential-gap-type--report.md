# TH-9 -- Self-attested vs. independently-derived gate evidence

**Status: DONE**

**Test summary:** `dv_harness_tests/test_evidence_provenance.py` -- 42 passed
(real gate subprocesses, real `evaluate_stage_evidence()`, real dashboard over real HTTP,
real `read_signoff_stage_status()`); affected pre-existing suites re-run and passing (see
"Regression run" below).

---

## 1. Gap independently re-verified before building

```
grep -rn "evidence_provenance|AGENT_SELF_ATTESTED|TOOL_DERIVED|SIMULATION_DERIVED" \
     --include=*.py --include=*.json --include=*.md .
```
-> exactly ONE hit, an unrelated string `"git_sha_evidence_provenance"` inside
`.dv-harness/reference-bases/usb-uvm/reusable_pattern_manifest.json`. No module, no schema
field, no gate anywhere asked who produced its input. **Gap real.**

Confirmed the mechanism shape by reading the real code rather than the audit:

- `dv_harness/gates.py` `run_gate()` builds every gate's payload from the ONE fenced
  ```` ```dv-harness-evidence:<gate_id>``` ```` block the agent typed
  (`extract_evidence_blocks()`), JSON-dumps it to a temp file, and hands it to the script.
- `tools/verification_flow/system_level_deadlock_livelock_gate.py` is **nine lines**: it PASSes on
  `{"deadlock_detected": false, "livelock_detected": false, "forward_progress_assertions": [...],
  "stress_scenario_evidence": [...]}`. `per_port_queue_starvation_gate.py` is eleven lines and
  reads only `.get()`s off the agent's own dict. Same for
  `multi_port_fairness_qos_gate.py`, `interrupt_storm_latency_gate.py`,
  `scoreboard_transaction_liveness_gate.py`.
- So "the composed system is deadlock-free" really could be produced by an agent writing one
  line, and `control_plane.describe_stage()` / `dashboard.py` / `signoff_export.py` rendered the
  resulting PASS **identically** to one backed by a real tool run.

## 2. What was built (extended existing mechanisms; no parallel machinery)

New module `dv_harness/evidence_provenance.py` plus wiring into files that already own each
concern. Nothing new was stood up where something existed.

| Concern | Reused mechanism, extended |
|---|---|
| Evidence schema | the existing fenced `dv-harness-evidence:<gate_id>` block -- one new REQUIRED key, no new fence syntax, no regex change |
| Enforcement point | `gates.run_gate()`, the one place every stage gate's payload passes through (same place `_check_judgment_fields` / `JUDGMENT_FIELDS` already enforces a per-gate field-level rule) |
| Stage read path | `control_plane.describe_stage()` -- the ONE shared path the dashboard card and the CLI `explain`/`evidence`/`checklist` verbs both already use |
| Dashboard render | `stageWhyHTML()`'s existing block structure, reusing the existing `.err` bold+red class and `icon()` convention |
| Signoff surface | `signoff_export.read_signoff_stage_status()`, reading the same `state.json` it already reads, the same plain `read_text`/`json.loads` (never `StateStore`, which would MINT one) |
| Agent instruction | `dv_harness/prompts.py`'s existing per-gate evidence-block examples |

### The field

`evidence_provenance` -- REQUIRED on six gates, one of `AGENT_SELF_ATTESTED` /
`TOOL_DERIVED` / `SIMULATION_DERIVED`. **No default**: defaulting would decide the very
question the field exists to record.

**The asymmetry is the design.** `AGENT_SELF_ATTESTED` is always accepted and costs nothing --
an agent must never be pushed toward a stronger claim to get a stage moving. An independence
claim costs a real `evidence_derivation: {"tool", "artifact_path"}` whose path must EXIST under
the project root, resolved against the project being judged (not the CWD).

Five distinct refusal reasons, kept distinct because they are distinct operator problems:
`EVIDENCE_PROVENANCE_MISSING`, `_INVALID`, `_DERIVATION_MISSING`, `_ARTIFACT_NOT_FOUND`,
`_PAYLOAD_NOT_OBJECT`. Each refusal names the field, the accepted values and the claim the gate
would otherwise have made.

### The enforced set (and why it is that set)

`PROVENANCE_REQUIRED_GATES` maps each gate to the headline claim its PASS produces, so the rule
is checkable rather than asserted. The rule: **the gate's PASS asserts a measured DYNAMIC
BEHAVIOUR property, and its script is a pure shape check over agent-typed numbers.**

| gate | claim |
|---|---|
| `system_level_deadlock_livelock_gate` | the composed system is free of deadlock and livelock |
| `system_level_resource_contention_gate` | every shared-resource contention scenario is arbitrated and tested |
| `per_port_queue_starvation_gate` | no port starves; every port makes forward progress within its bound |
| `multi_port_fairness_qos_gate` | each port receives its minimum service share and QoS policy holds |
| `interrupt_storm_latency_gate` | interrupt ack latency is bounded and no interrupt is lost |
| `scoreboard_transaction_liveness_gate` | no transaction is missing or duplicated and latency stays in bound |

The first three are the ones the audit named. `assert_required_gates_are_registered()` holds the
set against the real `STAGE_GATES`, so unwiring or renaming one of these gates fails a test
rather than silently emptying the enforcement set.

### Consumers (one computation, every surface)

- `control_plane.describe_stage()` gains `evidence_provenance` (from
  `summarize_evidence_blocks()` over the blocks it already extracted). Computed here, not per
  UI, so a self-attested claim cannot be caveated in one surface and shown bare in the other.
- `dashboard.py`: new `provenanceBlock()` inside `stageWhyHTML()`. A self-attested claim renders
  with the existing bold+red `.err` treatment a missing checklist item gets, plus a banner
  carrying `SELF_ATTESTED_CAVEAT`. An independently-derived one renders green with
  `DERIVED_CAVEAT`, which says in as many words that the harness checked the artifact EXISTS and
  did not parse it. The card's own note text was updated too.
- `signoff_export.read_signoff_stage_status()` gains `evidence_provenance` from
  `summarize_project_provenance()` (every stage, every enforced gate, each self-attested claim
  named with its stage). This flows into the exported bundle's `signoff_stage_status.json` and
  `manifest.json`'s `signoff_stage` key via the existing `collect_signoff_bundle()` path --
  signoff is exactly where a headline claim gets believed.
- `run_gate()` also stamps `evidence_provenance` / `..._independently_derived` /
  `..._caveat` / `..._claim` onto the gate DETAIL, so `react_loop`'s signature menu and stage
  telemetry carry it without re-opening the evidence block.
- `render_caveat_lines()` is the shared plain-text rendering for any text surface.

## 3. Files changed

| file | change |
|---|---|
| `dv_harness/evidence_provenance.py` | NEW -- vocabulary, enforced set, `check_payload()`, `annotate_gate_detail()`, the two summarizers, `render_caveat_lines()`, `assert_required_gates_are_registered()` |
| `dv_harness/gates.py` | import + provenance check before the script runs + `annotate_gate_detail()` on the result |
| `dv_harness/control_plane.py` | `describe_stage()` carries `evidence_provenance` |
| `dv_harness/dashboard.py` | `provenanceBlock()`, wired into `stageWhyHTML()`; card note updated |
| `dv_harness/signoff_export.py` | `read_signoff_stage_status()` carries `evidence_provenance` |
| `dv_harness/prompts.py` | the six evidence-block examples now declare the field, with the rule stated once (VERIFY) and once (SYSTEM_LEVEL) |
| `dv_harness_tests/test_evidence_provenance.py` | NEW -- 42 tests |
| `dv_harness_tests/test_engine_gates_and_routing.py` | 4 hand-typed fixture blocks now declare `AGENT_SELF_ATTESTED` |
| `dv_harness_tests/test_system_level_soc_composition_wiring.py` | 2 hand-typed fixture blocks likewise, with a comment saying why |
| `CLAUDE.md` | new section documenting the mechanism and its bounds |

A repo-wide grep confirmed those are the ONLY places in the tree that emit one of the six
evidence blocks, so no emitter was left un-migrated.

## 4. Tests -- what gives them detection power

All 42 drive REAL machinery: the real `gates.evaluate_stage_evidence()` over the REAL shipped
`STAGE_GATES`, the REAL gate scripts as subprocesses, the REAL dashboard server over REAL HTTP
(same `_start_dashboard`/`_wait_ready`/`_get` harness every other dashboard card test uses), and
the REAL `read_signoff_stage_status()`. Nothing is mocked; no test writes a gate detail by hand.

Negative controls, which is where the power is:

- **Every one of the six clean payloads is first proven to PASS on the merits** with provenance
  declared -- so a "FAIL" assertion elsewhere can never be a shape failure wearing a provenance
  failure's name.
- The headline deadlock test **refuses** the exact payload the pre-2026-09-06 gate accepted, then
  **accepts** the identical payload once it honestly declares who wrote it.
- Both independence refusals are paired with the same claim **accepted** once the cited artifact
  really exists on disk; a file under a DIFFERENT root is still refused (path resolution proven).
- A genuinely bad payload for each of the six still fails on the **SCRIPT's own** reason with
  provenance declared -- provenance is an additional requirement, never a replacement.
- An unenforced gate (`unknown_failure_escalation_gate`) reaches its script unchanged and carries
  **no** provenance annotation.
- A derived claim is proven **not** to be caveated in `describe_stage()`.
- `read_signoff_stage_status()` on a bare project reports `NO_STATE_FILE` and **creates no**
  `.dv-harness` tree; a byte-level snapshot proves summarizing provenance writes nothing.
- `assert_no...`-style boundary test: `evidence_provenance.py`'s own source contains no
  `ControlPlane` / `can_signoff` / `assert_human_approval` / `bsub` / `run_stage(`, with
  `control_plane.py` as the control proving that check can fire.
- The provenance vocabulary is asserted to share no token with `models.Status`.

## 5. Regression run

- `dv_harness_tests/test_evidence_provenance.py` -- **42 passed**.
- `test_engine_gates_and_routing.py`, `test_system_level_soc_composition_wiring.py`,
  `test_system_level_track_b_gate_crosscheck.py`, `test_system_scheduling_plan.py`,
  `test_hard_gate_script_smoke.py` -- **511 passed, 1 transient unrelated failure** (details at
  the bottom of this file), re-verified passing in isolation.
- `self_audit.JSON_GATES` was checked for overlap with the enforced set: **empty intersection**,
  so `dv-harness self-audit` / `GET /api/self-audit` are unaffected.
- `signoff_bundle_completeness_gate.py` recomputes `bundle_hash` over the manifest's ARTIFACT
  list only; adding a key under `signoff_stage` cannot move it.

## 6. Governance / safety

- **No human-approval gate was weakened or touched.** `ControlPlane.approve()`,
  `policy.can_signoff()`, `assert_human_approval()`, `assert_no_production_write_authorized()`
  and the PR-only main/master governance are unreferenced by this module (asserted by a test).
  Everything added here can only STOP a gate; nothing authorizes any work.
- **No production build / regression / LSF submission was triggered.** Every test runs against
  synthetic local fixtures and throwaway temp roots. Nothing in the new module or tests calls
  `bsub`, `run_stage()`, a composer generation entry point, or a remote relay.
- Shared files were patched by hand-scoped edits; `git diff` on `gates.py`, `dashboard.py`,
  `signoff_export.py`, `control_plane.py` and `prompts.py` was verified CLEAN before touching
  them, and each edit is a single localized hunk.

## 7. Deferred / disclosed residual (honest boundary)

1. **This does not verify deadlock freedom, and nothing here pretends to.** A real deadlock/
   livelock checker needs a formal tool this project does not have. What is closed is the
   INDISTINGUISHABILITY, which is what the audit actually flagged.
2. **The artifact check proves a FILE EXISTS**, not that the file contains the claim. It is a
   real cost that stops a free upgrade from AGENT_SELF_ATTESTED to TOOL_DERIVED; it does not make
   TOOL_DERIVED mean "verified", and `DERIVED_CAVEAT` says exactly that on every surface.
3. **A FALSE declaration is not detectable.** An agent typing `TOOL_DERIVED` and citing a real
   unrelated file passes. Closing that needs a gate that re-derives the claim
   (`remote_execution_provenance_gate` is the model for what that would look like).
4. **Only six gates are enforced.** Every other gate is byte-for-byte unaffected and carries no
   provenance annotation. Widening the set is a per-gate judgment (does its PASS assert a
   measured dynamic property?), deliberately not applied wholesale -- requiring the field on all
   ~200 gates would retroactively break every project without closing anything the audit named.
5. **No stage gate of its own, and no CLI verb.** There is deliberately no
   `evidence_provenance_gate` (a gate that passed because nobody declared provenance would be
   worse than none), and no `dv-harness` verb was added -- `cli.py` is being modified by
   concurrent work this session. Front doors are the enforcement inside `run_gate()`, the
   dashboard card, and `read_signoff_stage_status()`.
6. **`self_audit.py`'s SMOKE_PAYLOADS were not extended** -- none of the six is in `JSON_GATES`,
   so there was nothing to migrate.

---

### Regression run result

`python -m pytest dv_harness_tests/test_engine_gates_and_routing.py
dv_harness_tests/test_system_level_soc_composition_wiring.py
dv_harness_tests/test_system_level_track_b_gate_crosscheck.py
dv_harness_tests/test_system_scheduling_plan.py
dv_harness_tests/test_hard_gate_script_smoke.py`

**1 failed, 511 passed in 21m39s.** The single failure was
`test_engine_gates_and_routing.py::test_self_audit_against_real_repo_reports_real_current_findings`
asserting `test_collection_health_gate == PASS`, which is a repo-wide `pytest --collect-only`
health check. It is **transient and not caused by this change**: a separate concurrently-running
close-pass had an in-flight test file on disk at that instant. Re-verified immediately after by
running `tools/verification_flow/test_collection_health_gate.py --root .` directly (`{"status":
"PASS"}`) and re-running that one test on its own (**1 passed**). No other failure in 512 tests.
