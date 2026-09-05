# TH-8 — Signoff Freeze / Baseline (spec section 238)

**Status: DONE**

**Test summary:** `dv_harness_tests/test_signoff_freeze_baseline.py` — 27 passed (549s);
pre-existing `test_signoff_export.py` / `test_signoff_bundle_hash.py` /
`test_signoff_bundle_completeness_gate.py` re-run unchanged (26 passed).

---

## 1. Gap independently re-verified before building

- `grep -rn "freeze\|frozen\|baseline_capsule\|INVALIDATED" --include=*.py dv_harness/ tools/`
  matched **only `frozenset`** — no freeze mechanism, no invalidation check, anywhere.
- Read `CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md:7932-7955` (section 238). It names
  **fifteen** baseline fields and the rule "post-freeze material changes trigger impact analysis
  and invalidate/revalidate affected signoff evidence".
- Read `dv_harness/signoff_export.py` (513 lines pre-change). It carried **none** of the fifteen.
  Its `manifest` entries are `{artifact, present, bundled_path}` and `compute_bundle_hash()`
  hashes exactly those three — artifact **presence**, never **content** — so a bundled file could
  be replaced wholesale without moving the bundle hash.
- Confirmed PARTIALLY_WIRED, exactly as the brief said: the gate-aware bundle/hash half
  (`read_signoff_stage_status()`, `bundle_kind`, `require_signoff_pass`) is real and was reused,
  not replaced.

## 2. What was built (all inside `dv_harness/signoff_export.py` — no parallel exporter)

`D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/signoff_export.py` (+1127 lines)

**(a) `capture_baseline(root, declared=None)`** — all fifteen section-238 fields, each from a REAL
producer or `NOT_AVAILABLE` with a real reason. `SECTION_238_FIELDS` and `BASELINE_CAPTURES` are
held equal in both directions by `assert_baseline_covers_section_238()` at import.

| field | real producer reused |
|---|---|
| `dut_sha` | `connectivity_check.compute_rtl_fingerprint()` over the project's own `rtl_sources` |
| `tb_sha` | the bundle's own `_find_tb_source_dir()` + content manifest |
| `requirement_vplan_version` | `.dv-harness/vplan/` + `.dv-harness/requirements.csv` content |
| `agent_skill_versions` | `harness_deploy.load_manifest()/collect_local_files()/compute_local_manifest()` over `.claude/skills` + `.claude/agents` |
| `vip_tool_versions` | `env.manifest.json` `vip_config.vip_release` (its own status/reason verbatim) |
| `schema_policy_versions` | `dv_harness/schemas/*` + the policy JSONs + `.dv-harness/graph/main_graph.json` |
| `configuration` | `.dv-harness/config.json` |
| `test_list` | `.dv-harness/regression.list` + `regression/computed_selection.json` |
| `coverage_databases` | `.dv-harness/coverage/summary.json` + `history.json` |
| `assertion_status` | real `lsf_client.JobState` records' `assertion_failure`/`uvm_*_count` |
| `waivers` | `waiver_store.status_report()` — TH-7's ledger, DERIVED statuses |
| `evidence_hashes` | `normalized_evidence.evidence_id` (vip_distill's own content hashes), read-only |
| `reproducibility_capsules` | `golden_scenario.load_golden_scenarios()` |
| `spec_version` | **NOT_AVAILABLE by construction** — no artifact producer exists; only agent-attested `spec_revision` text. A human may declare one (`attested: true, machine_verified: false`). |
| `dashboard_snapshot` | **NOT_AVAILABLE by construction** — `dashboard.py` renders live from sources already frozen by other fields; no snapshot artifact producer exists. |

Every aggregate goes through `tools/remote/source_identity.aggregate_source_id()` (imported via
`harness_deploy`) — no second aggregation rule was written.

**(b) `freeze_signoff_baseline()` / `load_freeze()` / `list_freezes()`** — immutable records at
`.dv-harness/signoff/freezes/<freeze_id>.json` (plus a copy in the bundle), one real
`SIGNOFF_BASELINE_FROZEN` event through `StateStore.event()` into the existing `events.jsonl`.
A standalone freeze **recomputes** the bundle hash off `manifest.json` rather than trusting the
value stored in the file.

**(c) `evaluate_freeze_invalidation()` / `evaluate_all_freezes()`** — `VALID` / `INVALIDATED` /
`UNKNOWN`, worst-wins over three independent comparisons:
1. all fifteen fields re-derived NOW and compared by digest (moved or vanished ⇒ INVALIDATED;
   newly-appearing evidence ⇒ INDETERMINATE, not invalidating);
2. post-freeze impact analysis = the REAL `change_impact.changed_files()` + `classify_risk()`
   against the freeze's recorded git HEAD, run exactly as `golden_scenario.evaluate_freshness()`
   runs it (HIGH/MEDIUM invalidate and are named; LOW does not);
3. bundle integrity = `compute_bundle_hash()` recomputed independently off the frozen bundle.
The verdict is **derived on every read, never stored**.

**(d) `content_sha256` on each bundle manifest entry** — the content half section 238 asked for.
Deliberately a FOURTH key and NOT material to `compute_bundle_hash()`, so
`signoff_bundle_completeness_gate.py`'s independent recomputation is provably unaffected (asserted
by a test that strips the key and reproduces the identical hash).

**(e) Wiring.** `collect_signoff_bundle(freeze=None)` (the default) freezes **exactly when the
bundle is `SIGNOFF_GATE_VERIFIED`** — i.e. on a real gate-verified SIGNOFF PASS. That makes
`engine._export_signoff_bundle()` the real production producer of section 238's freeze with **no
engine.py change** (engine.py was being touched by a concurrent pass). A `PRE_SIGNOFF_GATE_INPUT`
bundle is deliberately not frozen.

**(f) Front door.** `python -m dv_harness.signoff_export fields|baseline|freeze|list|status`
(`execute_verb()`, the `power-intent`/`golden-scenario`/`waiver-store` convention). Exit 0 clear,
1 INVALIDATED, 2 nothing to report/refusal. `freeze` requires `--frozen-by`.

## 3. Governance boundaries preserved

- **No human-approval gate touched.** A test asserts `ControlPlane`, `can_signoff`,
  `assert_human_approval`, `HumanApprovalRequiredError`, `bsub` and `run_preflight` appear
  **nowhere** in `signoff_export.py`.
- **No stage gate added** — a test walks the real `gates.STAGE_GATES` and asserts no gate id
  contains "freeze". A gate that passed because a freeze was absent would be worse than none.
- **No production build/regression/LSF submission** anywhere; every test fixture is a synthetic
  throwaway git repo under `tmp_path`.
- **Reading writes nothing** — a byte-level snapshot of the whole project root proves evaluating a
  freeze mutates no file; `capture_baseline()` on an empty directory creates nothing (asserted).
- `require_signoff_pass`'s existing opt-in refusal semantics are unchanged.

## 4. Tests (27, all real, nothing mocked)

`D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_signoff_freeze_baseline.py`

Central proof: **freeze a real bundle → assert VALID → change the fixture's RTL and commit →
assert the SAME frozen record now reads INVALIDATED**, naming `dut_sha` (digest moved) AND
`rtl/usb3_link_ctrl.v` at its real `HIGH` risk, with the freeze record byte-identical on disk.

Negative controls that give it detection power: an unchanged fixture is VALID with zero findings;
a committed **documentation-only** change does NOT invalidate; **revoking a waiver** invalidates
with no git change at all; evidence that **disappears** invalidates while evidence that **appears**
is UNKNOWN not INVALIDATED; a **deleted** bundle is UNKNOWN while an **edited** one is INVALIDATED;
a project with **no git history** is UNKNOWN not VALID; stripping `content_sha256` reproduces the
identical `bundle_hash`; a `PRE_SIGNOFF` bundle mints no freeze while a gate-verified one does;
a standalone freeze refuses a lied-about `bundle_hash`; both import-time drift assertions fire.

One real fixture defect was found and fixed during the run: the copied `tools/` tree's freshly
written `.pyc` files were landing in the post-freeze commit and reading as MEDIUM-risk material
changes — the fixture now gitignores `__pycache__/`/`*.pyc`, which is what a real project does.

## 5. Documentation

`CLAUDE.md` gained one section, **"Signoff Freeze / Baseline + Post-Freeze Invalidation
(2026-09-06, TH-8)"** (append-only, 129 lines), following the file's existing convention: what the
gap was and how it was re-verified, what was reused vs. built, what is deliberately bounded, and a
disclosed residual.

## 6. Deferred / disclosed residual

1. **No `dv-harness` CLI verb.** `cli.py` was modified by concurrent work in this same session
   (confirmed in `git status`), so adding a verb there would have collided. The ad-hoc door is
   `python -m dv_harness.signoff_export`; the production door is the auto-freeze on a real
   gate-verified SIGNOFF PASS.
2. **`spec_version` and `dashboard_snapshot` are structurally NOT_AVAILABLE.** Closing either
   needs a producer this repo does not have; fabricating one is what section 238's own
   reproducibility claim would be undermined by.
3. **This repository's own baseline honestly captures 4 of 15 fields today** (no RTL tree, no
   generated TB, no VIP install, no waiver ledger, no coverage database of its own). The mechanism
   is proven against real fixtures; it was not made to look complete by writing fabricated
   artifacts into this project's real audit trail.
4. **It detects; it does not re-baseline.** There is no `revalidate` verb — deciding an
   invalidated signoff is acceptable is a human judgment, and re-freezing is `freeze` again with a
   human named on it.
5. Not extended: the nine `REQUIRED_CLASSES` in `signoff_bundle_completeness_gate.py`
   (SPEC_TRACE/BUILD/TEST/…), which that gate's own RULING already declares out of scope for want
   of a real class→artifact mapping. Unchanged here.

## 7. Files touched

- `dv_harness/signoff_export.py` (extended, +1127/-3)
- `dv_harness_tests/test_signoff_freeze_baseline.py` (new, 27 tests)
- `CLAUDE.md` (append-only section)

Commit scoped by hand to exactly those three — `cli.py`, `commands.py`, `env_manifest.py`,
`schemas/env_manifest.schema.json`, `mcp_manifest_fixture.py`, `test_env_manifest_fact_sources.py`
and `tools/git-hooks/pre-merge-commit` were concurrently modified by other passes and were
deliberately left out of the index.
