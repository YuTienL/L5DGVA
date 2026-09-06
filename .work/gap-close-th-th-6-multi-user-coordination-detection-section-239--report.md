# TH-6 — Multi-user coordination detection (spec section 239)

**Status: DONE**

**Test summary:** `dv_harness_tests/test_multi_user_coordination.py` — 32/32 pass
(4m26s); neighbouring suites `test_multi_agent_timing.py`,
`test_blackboard_automatic_path_and_concurrency.py`, `test_rca_multi_agent_fanout.py`,
`test_cli_blackboard.py`, `test_cli_adapter_command_resolution.py`,
`test_lsf_client.py`, `test_cli_preflight.py`, `test_cli_cross_project.py`,
`test_cli_question_queue.py`, `test_cli_git_guard.py` — 167/167 pass (one
wall-clock-parallelism assertion in `test_rca_multi_agent_fanout.py`,
`span < 1.8s`, flaked at 1.878s while running under load beside concurrent
close-passes; it passes in isolation and is unrelated to this change).

Commit: `0156515 feat(coord): multi-user coordination conflict detection (spec 239, TH-6)`
on branch `gap-close/env-manifest-fact-sources`.

---

## 1. Gap re-verified independently

`grep -rl "stale_sha|STALE_SHA|duplicate_regression|DUPLICATE_REGRESSION|edit_conflict|
EDIT_CONFLICT|reservation_conflict|RESERVATION_CONFLICT|cross_session|peer_session|
coordination_conflict" --include=*.py .` matched exactly two files, both false
positives on inspection (`test_engine_gates_and_routing.py:2981` uses a local
variable named `stale_sha` for a subsystem-registry `release_sha` fixture;
`test_subsystem_discovery.py:398` uses the literal string `"STALE_SHA_0000"` as a
GIT_SHA override value). Nothing anywhere compared two users' concurrent work.

The transport/auth half really is real and was **not** touched:
`USAGE_MULTI_USER_SAFETY.md` (the "never share a `--project-root`" standing rule),
`dv_harness/dashboard_auth.py` (GUI-19 token gate),
`dv_harness/user_info.summarize_user_access()` (per-root access trail),
`tools/remote/remote_relay.py`'s `handle_request()` lock. None of those files
appears in this commit.

## 2. What was built

### `dv_harness/multi_user_coordination.py` (new, 746 lines)

Because each user has their own `.dv-harness/` (that *is* the multi-user safety
rule), detection is necessarily a cross-ROOT comparison. `scan([(user, root), ...])`
reads N peer roots into `SessionSnapshot`s and compares every pair of
distinct-user sessions. **No new coordination store was invented** — every fact
comes off an artifact an existing mechanism already writes:

| Detector | Data source (existing, real) |
|---|---|
| `STALE_SHA_CONFLICT` | `change_impact.read_computed_selection()` → `.dv-harness/regression/computed_selection.json`'s `base_sha` + `changed_files` (a real `git diff --name-only base..head` written by REGRESSION_SELECT). Severity from the real `change_impact.classify_risk()`. |
| `DUPLICATE_REGRESSION_SUBMISSION` | SUBMITTED: real `lsf_client.JobState` records in `.dv-harness/lsf/jobs/*.json` (`pattern` + `git_sha`, in-flight = `PEND`/`RUN`). PLANNED: the same `computed_selection.json`'s four selected test sets against its `head_sha`. |
| `SHARED_RESOURCE_RESERVATION_CONFLICT` | `.dv-harness/agents/ownership.json` — the **existing** `AgentTaskStore.acquire()` ledger `engine.py:5103`'s `_advance_with_fanout()` already uses. |
| user identity | the **existing** `user_info.summarize_user_access()` over real `CLI_ACCESS`/`GUI_ACCESS` events (or a declared `user=` on the CLI). |
| audit | the **existing** `StateStore.event()` → one `MULTI_USER_COORDINATION_SCAN` line in the scanning root's `events.jsonl`. |

Negative rules that are deliberate, not omissions: same base SHA is not a
stale-SHA conflict; different SHAs with disjoint files is not one either; the same
pattern against two different commits is two legitimate results; a terminal
(`DONE`/`EXIT`/`KILLED`) job is history, not a live collision; two READ claims do
not conflict.

### `dv_harness/multi_agent.py` (extended, +117/−2)

`acquire()` gains `scope` / `kind` / `mode`, defaulting to the pre-existing
behaviour so `engine.py`'s call site is byte-identical in meaning. `release()` and
a read-only module-level `read_reservations()` / `ownership_path()` were added.

The `scope` is load-bearing, not cosmetic: `acquire()`'s only production caller
claims blackboard TOPIC names (`findings`, `verification_state`, …) that are
identical in every project by construction, so a scope-blind cross-root comparison
would report a conflict on **every** pair of sessions that ever ran a fan-out. A
`SCOPE_SHARED` claim must name a kind from the closed `SHARED_RESOURCE_KINDS` set
(`amba_fabric_port`, `vip_instance`, `license_feature`, `regression_slot`,
`shared_path`) — free-text kinds would let two users' "AXI_M0" silently never
collide. A record with no `scope` key (everything written before today) reads as
`SCOPE_LOCAL`. `release()` is required because a SHARED reservation persists on
disk; without it every finished reservation would collide with the next user
forever. A non-holder cannot release someone else's claim.

### `dv_harness/cli.py` (+50)

`dv-harness coord detect|reserve|release|list`, one implementation shared with
`python -m dv_harness.multi_user_coordination` via `execute_verb` (the
`power-intent` / `golden-scenario` / `system-smoke-proof` convention). Exit 0
CLEAR / reservation made, 1 CONFLICTS_DETECTED / reservation refused, 2 UNKNOWN.

### `CLAUDE.md` (+90)

New section "Multi-User Coordination Conflict Detection (2026-09-06, section 239)"
recording the gap, the mechanism, the reuse decisions and the disclosed bounds.

## 3. Governance / safety

- **No approval gate was weakened.** No `gates.py`, no
  `tools/verification_flow/*_gate.py`, no `STAGE_GATES` entry, and no
  `control_plane`/`policy` file appears in this commit. A test
  (`test_no_approval_gate_or_stage_gate_is_introduced`) asserts `STAGE_GATES`
  names nothing from this module and that the module's source contains no `bsub`,
  `subprocess.run`, `approve(` or `can_signoff`.
- **Deliberately no stage gate.** A gate that passed because a scan could not see
  the other user's project root would be worse than no gate. Stated in both the
  module docstring and CLAUDE.md rather than implied closed.
- **DETECTION only; ARBITRATION untouched.** No lock, no job cancellation, no
  claim revocation, no winner picked. `claimed_first` is reported as information,
  never applied as a rule. Every conflict carries
  `"arbitration": "NOT_PERFORMED -- detection only; a human decides"`.
- **No production build/regression/LSF submission.** Everything ran against
  synthetic tmp_path fixtures and throwaway git repos. `JobState` records were
  written with `save_job_state()` into tmp roots; nothing called `bsub`, `bjobs`,
  `lmutil` or the remote relay.
- **Read-only against peers.** A scan creates no file in another user's root
  (`state.json` is read raw rather than through `StateStore.load()`, which would
  create one; `read_reservations()` is a module function rather than
  `AgentTaskStore.__init__`, which mkdirs). Proven by
  `test_scan_never_writes_into_a_peer_project_root`.
- **Concurrent-edit discipline.** `dv_harness/cli.py` was concurrently modified by
  another close-pass (a `schema-compat` verb) while I worked. I staged only my two
  hunks with the hand-scoped patch technique (`git diff > patch`, trimmed to the
  hunks containing `coord`, `git apply --cached --check` then `--cached`); the
  other pass's hunks remain unstaged in the working tree. `CLAUDE.md` and
  `multi_agent.py` were verified to contain only my hunks before `git add`.

## 4. Tests (32) — what they actually prove

Every test builds **two or three real, separate project roots** in the layout
`USAGE_MULTI_USER_SAFETY.md` prescribes, against a **real throwaway git repo**
with three real commits, and populates each root through the **real producing
mechanism**: `change_impact.compute_and_write()` over a real `git diff`, a real
`.dv-harness/requirements.csv` traceability registry (so PLANNED sets are what the
real `select_regression()` selects), real `save_job_state()` records, real
`AgentTaskStore.acquire(scope=SHARED)` claims, real `CLI_ACCESS` events.

Central proofs, each with matching negatives:
- `test_two_sessions_on_different_shas_touching_the_same_rtl_file` — asserts the
  overlapping file is the real `rtl/usb3_link_ctrl.v`, its risk is the real
  `RISK_HIGH`, and the two baselines are the two real commit SHAs. Negatives:
  same base SHA, disjoint files, doc-only overlap → LOW.
- `test_two_sessions_submitting_the_same_pattern_against_the_same_commit` —
  asserts both real job ids appear in the conflict. Negatives: different commits,
  terminal jobs. Plus a planned→submitted escalation test asserting MEDIUM becomes
  HIGH and that HIGH sorts first.
- `test_two_sessions_claiming_the_same_vip_instance` — plus amba_fabric_port and
  license_feature, READ/READ (no conflict), READ vs WRITE (conflict), and the
  false-positive guard `test_local_fanout_topic_claims_never_become_a_cross_user_conflict`,
  which drives the **real default `acquire()` signature engine.py uses** on both
  roots and asserts no cross-user conflict — then asserts the LOCAL claims really
  are on disk, i.e. the detector filtered them by scope rather than failing to see
  them.
- Honest-failure contract: one session, no `.dv-harness/`, no computed selection,
  and unknown user identity each produce a named UNKNOWN, never CLEAR.
- Both real entry points driven as subprocesses (`dv-harness coord` reserve →
  detect → release → detect, asserting the shared-resource conflict really clears;
  and `python -m dv_harness.multi_user_coordination`).

## 5. Built vs. deferred — stated honestly

**Built:** the three detectors the task named (a), (b), (c), the SHARED-claim
extension to the existing ownership ledger with a release verb, both CLI entry
points, the audit event, and the CLAUDE.md record.

**Deferred, and why** (section 239 lists nine concerns; three are implemented):
- *ownership / authorized role* — this is the auth layer the task explicitly
  scoped out (`dashboard_auth.py` / `USAGE_MULTI_USER_SAFETY.md`).
- *generic edit conflict* — the stale-SHA detector covers the
  divergent-baseline case, which is the one with a real per-project artifact
  behind it. A true line-level edit conflict needs uncommitted working-tree
  content from another user's machine, which no shared artifact carries.
- *conflicting Human Gates*, *simultaneous memory promotion*, *simultaneous
  capability changes* — these need cross-root visibility into
  `control_plane`'s approvals, `memory_router.promote_to_organizational()`'s
  provenance and `capability_evolution`'s governance state. Those are all
  per-project today with no shared ledger to compare, so a detector over them
  would either be vacuous or would require building the shared governance store
  this task explicitly told me not to invent. Recorded as a disclosed residual in
  CLAUDE.md rather than half-built.

**One honest limit on the mechanism as built:** a `SCOPE_SHARED` reservation is
recorded by a deliberate `coord reserve` call. Nothing in `engine.py` auto-mints
one today, because "which VIP instance / fabric port does this stage actually
claim" is not derivable from any current stage evidence — inventing that
inference would have been the fabricated half. Detector (c) therefore fires on
reservations a human or a script really declared; detectors (a) and (b) fire on
state the engine already writes with no extra declaration at all.
