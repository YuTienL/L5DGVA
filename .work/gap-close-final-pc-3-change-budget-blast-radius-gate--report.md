# PC-3 — Change-budget / blast-radius gate

**Status: DONE**
**Tests: 33 new (`test_change_blast_radius.py`) all pass; 220 passed across the governance/approval suite (git_governance, cli_git_guard, git_hooks_e2e, self_test_gate_e2e, research_intent_routing, capability_evolution_research_architect, fix_risk_approval_gate, signoff_stage_gate_e2e); 177 passed across the `commands.py`-importer + question_queue sweep (capability_evolution_auto_discovery, capability_evolution_controlled_experiment, confidence_calibration, harness_reliability, question_queue, confidence_vocabulary_separation); `self_test.py --only import-sanity` PASS. 0 failures anywhere.**
**Commit: `fa562a0`**

---

## 1. Gap independently re-verified (audit was accurate)

`grep -rn "blast_radius|change_budget"` returns hits in only one real mechanism:
`question_queue.py:334`, where `blast_radius` is a **hand-declared string** the asker
supplies in the ask context (`"single_regression"` / `"multi_regression"` /
`"unbounded"`) and `classify_tier()` simply believes. `cli.py:1666` exposes it as
`--blast-radius`, defaulting to `single_regression`. `waveform_dump_gate.py` and
`coverage_analysis.py` likewise *declare* a value.

Nothing anywhere **estimates** blast radius from real signals. `git_governance.py`
(the named prior art) gates on exactly one fact — the destination branch — and says so:
"keyed on the destination branch and on nothing else". Gap is real.

## 2. What I built

`dv_harness/change_blast_radius.py` (546 lines) — measures reach from three signals,
none of them attested:

| Signal | Source | Real, not declared |
|---|---|---|
| Files touched | `change_impact.changed_files()` — **reused**, not re-implemented | real `git diff --name-only` |
| Shared-across-subsystems reach | transitive **importer closure** from a real `ast` parse of `dv_harness/*.py` | `models.py` → 90; `cli.py` → 1 |
| Governance self-modification | **derived** from `autonomy_levels.LEVEL_C_ENFORCEMENT`'s `cites` + `tools/git-hooks/` | follows the repo's own checked enforcement table |

Tiers: `CONTAINED` / `WIDE` / `GOVERNANCE` / `NOT_ASSESSABLE`.
`WIDE_REACH_THRESHOLD = 40` is this repo's **measured p90** of per-module reach
(median 19, p75 28, p90 40, max 88, n=134) — calibrated, not guessed.

**Confirmation reuses existing real code**: `ControlPlane.approve()` under
`CHANGE_BLAST_RADIUS`, registered in `commands.APPROVAL_ONLY_STAGES` — the extension
point that already exists for "real code-owned approval points that are not graph
stages". No new approval store, no new CLI verb on the human side (`dv-harness approve`
is the command). The approval is **pinned to the assessment digest**, so growing the
change retires it — it cannot degrade into a blanket bypass.

Also added: `dv-harness blast-radius --base <rev> [--head <rev>]` to inspect any range
without pushing; `BLAST_RADIUS_DECISION` into the **same** `.dv-harness/events.jsonl`
trail (never a second governance log).

## 3. Existing gates preserved — the non-negotiable

- `cli.py` runs the branch gate **first and unchanged**. On a block it prints
  `git_governance`'s own decision and exits 1 **before** the new check runs at all.
  The new check is reached only on an already-allowed push, so it can turn an allow
  into a block and **never a block into an allow**.
- Explicitly tested: `test_a_blast_radius_approval_cannot_unlock_a_protected_branch_push`
  — a `CHANGE_BLAST_RADIUS` approval does **not** get an agent onto `master`.
- Human pushes are never gated on change size (same rule as the branch gate).
- No production build / regression / LSF submission touched. Every git operation runs
  in a pytest `tmp_path` throwaway repo against a **local bare** remote.
- `golden_flow_readiness.py` untouched.

## 4. Two real defects the tests caught (not review)

1. **Fabricated measurement.** First push of a branch to a remote lacking it →
   `merge-base(master, master) == master` → `head..head` → the gate reported a
   truthful-looking **"CONTAINED, 0 files changed"** for a push whose real content is
   the entire branch. Now rejected as `NOT_ASSESSABLE`. A fabricated measurement is
   worse than no measurement. Regression test:
   `test_publishing_a_branch_to_an_empty_remote_is_not_scored_as_zero_files`.
2. **Broken CLI output contract.** I printed a second top-level JSON document;
   every existing consumer does `json.loads()` on the whole of stdout and got
   `Extra data` (4 failures in `test_cli_git_guard.py`). The verdict is now **nested
   under `"blast_radius"`** in the one document, pre-existing top-level keys untouched.

## 5. One existing test rewritten — stronger, not relaxed

`test_research_intent_routing.py::test_approval_only_stages_do_not_leak_into_the_engine_driving_verbs`
asserted `APPROVAL_ONLY_STAGES == frozenset({HUMAN_APPROVAL_STAGE})`. That equality
fails on the mere **arrival** of a second key while never checking the new key for the
leak the test is actually about. Rewritten to assert the no-leak property (not a graph
stage, rejected by `_check_stage`, accepted by `_check_approval_stage`) over **every**
member. Strictly stronger.

## 6. Self-check

This change's own blast radius, scored by the gate it adds: **GOVERNANCE**
(reach 21, touching `change_blast_radius.py` and `tools/git-hooks/pre-merge-commit`).
The gate correctly flags itself.

## 7. Deferred, and why

- **No `pre-commit` hook.** The gate sits on push/merge, where the existing hooks and
  the PR-only policy already live. Blocking every local commit would be a different
  policy than the one CLAUDE.md states.
- **Reach graph covers top-level `dv_harness/*.py` only**, not subpackages or
  `tools/`. That is where this repo's modules actually live (134 of them); extending it
  to subpackages would add surface with no signal today.
- **Thresholds are module constants with no env override** — deliberate. An
  env-var override on a gate is a bypass hole.
- **Server-side branch protection remains the authoritative layer** and is still not
  in force (origin empty). Unchanged by this work; disclosed in CLAUDE.md already.

## 8. Files

- `dv_harness/change_blast_radius.py` (new)
- `dv_harness_tests/test_change_blast_radius.py` (new, 33 tests)
- `dv_harness/cli.py` — additive second gate in `git-guard`; `blast-radius` command
- `dv_harness/commands.py` — register `CHANGE_BLAST_RADIUS` in `APPROVAL_ONLY_STAGES`
- `tools/git-hooks/pre-push`, `tools/git-hooks/pre-merge-commit` — header hygiene;
  `pre-merge-commit` now supplies `MERGE_HEAD`
- `CLAUDE.md` — layer 3 documented in the gh CLI + PR-Only Governance Policy section
- `dv_harness_tests/test_research_intent_routing.py` — assertion strengthened

Shared files were hand-scoped: another close-pass's `env_manifest` provenance work was
interleaved in `cli.py` (since committed as `cdd125a`); every staged diff was verified
to contain only this pass's hunks before commit.
