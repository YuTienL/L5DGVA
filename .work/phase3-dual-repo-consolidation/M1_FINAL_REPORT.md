# M1 Final Report — Canonical Repository Bootstrap and V50 Baseline Qualification

All 16 instructed items addressed. One item (full 13768-test suite regression)
is honestly reported as still IN_PROGRESS at the time of this report, not
claimed complete — see item 14 below and `M1_V50_BASELINE_QUALIFICATION.md`.
Everything else is complete with real, verified evidence.

## 1. Canonical branch identity

Renamed `repo-hygiene/phase2-h2-migration` -> `canonical/m1-bootstrap`
(branch rename only — no commit rewrite, no push, no merge; `git branch -m`).
Old -> new recorded here and in this report's `CANONICAL_BRANCH` field.

## 2. Execution-profile result: preserved

`HARDCODED_GATEWAY_HOST_IN_RUNTIME = 0`, `HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME = 0`
unchanged since commit `0622d56`. `.dv-harness/execution_profile.json` remains
local/gitignored/uncommitted (re-verified: `git check-ignore -v` still matches
it). No architecture expansion since.

## 3. config.json residual gap

`M1_CONFIG_CONSUMER_GAP_DECISION.md`: not required for M1 bootstrap
qualification (no M1 step performs live remote execution). Recorded
`EXECUTION_CONFIG_CONSUMER_MIGRATION_PENDING = TRUE` for
`knowledge_center.py`/`preflight.py`, for a future ExecutionService/
config-unification wave. No second configuration architecture built; no
config.json host literal reintroduced.

## 4. dv doctor

`dv_harness/dv_doctor.py` + `dv-harness doctor` CLI command, composing all 18
required fields (`REPOSITORY_IDENTITY` through `INTAKE_STATUS`). 9/9 real
tests pass. Never requires Obsidian; uses `KNOWLEDGE_BACKEND_DEGRADED` when
unavailable. Verified working from 3 locations: the original checkout, a
relocated copy (different path+basename), and a git-history-free deployment
copy.

## 5. IN-005 / IN-006

Both re-applied as docstring-only deltas with disclosed path-reference
adaptation (not blind copy). Full provenance in
`M1_IN005_IN006_REAPPLICATION.md`. 18/18 existing `remote_exec` tests pass;
`ast.parse()` clean on both files.

## 6. multi_agent.py protected input

`M1_MULTI_AGENT_PROTECTED_INPUT_RECORD.md`. Corrected a stale
pre-compaction-summary claim: the real dirty delta lives in the **Parent**
repo's own `dv_harness/multi_agent.py` (101 insertions/5 deletions), not
v50's — v50's copy is confirmed clean and lacks the capability entirely.
Not applied. `MULTI_AGENT_PROTECTED_CAPABILITY_RECORDED = YES`,
`MULTI_AGENT_DIRTY_DIFF_APPLIED = NO`.

## 7. KNOWN_SOURCE_B_DEFECT

`M1_KNOWN_SOURCE_B_DEFECT_DISPOSITION.md`. Re-confirmed present
(`create_environment.py` lines 346/380), currently latent (v50's router has
no IP_MODE concept). Deferred to Wave M5 (already coupled there with
`b8`/`ARCH-01` in prior governance), with an explicit regression-test
obligation recorded. Not fixed now.

## 8. Security preservation

`M1_SECURITY_PRESERVATION_GATE.md` + `test_security_preservation_gate.py`
(4 pass + 1 tracked xfail). Core secret-detection/redaction/sandboxing
confirmed byte-identical Parent vs v50. Three real Parent-only findings
recorded as future obligations (Obsidian-CLI-probe hardening, wider
`detect_secrets()` coverage, `remote_relay.py` override discrepancy). No
wholesale `memory_vault.py` copy performed.

## 9. Migration provenance

`M1_MIGRATION_PROVENANCE.json` — machine-readable, one entry per
capability_id, with source/canonical/wave fields for every item touched,
including items explicitly NOT applied (traceable absence, not silence).

## 10. Knowledge Brain inventory

`M1_KNOWLEDGE_BRAIN_INVENTORY.md` — all 17 modules re-verified present,
13/17 independently tested. Honest gaps disclosed (no unified
`KnowledgeService` facade exists in this baseline; ingest/retrieve/
promotion/provenance/cross-session-recall/agent-consumption are all
IMPLEMENTED-only, none exercised end-to-end in M1, per the "successful
Obsidian search alone is not operational proof" standard). Full
integration remains M8.

## 11. Location-independence

`M1_LOCATION_INDEPENDENCE_QUALIFICATION.md` — real `git clone` to a
different absolute path AND basename, with a synthetic test execution
profile (never the real one). Identity discovery, git-root cross-check,
execution-profile resolution, `dv doctor`, imports, and 42/43 bootstrap
tests all correct there.

## 12. Deployment-copy mode

Same document, part B — `git archive | tar -x` (no `.git`).
`DEPLOYMENT_COPY_MODE` correctly detected; git-dependent checks correctly
report `GIT_CAPABILITY_UNAVAILABLE` rather than a generic failure. 38/38
selected bootstrap tests pass.

## 13. Absolute-path scan

`M1_ABSOLUTE_PATH_SCAN.md` — every real hit inspected in context; none is a
genuine bootstrap-path, historical-source-path, or local/remote
path-coupling runtime dependency. All three counts are 0.

## 14. V50 baseline qualification

`M1_V50_BASELINE_QUALIFICATION.md` — 299/300 targeted-category tests pass;
the 1 failure re-run against unmodified v50 HEAD and confirmed to fail
identically there (pre-existing environment flake, signature-matched, not
an M1 regression). C1-C5/`lifecycle.py` confirmed to be Parent-only work,
N/A for v50-baseline qualification. **Full 13768-test suite regression is
still running in the background at the time of this report (~28% complete
when last checked) — honestly reported IN_PROGRESS, not claimed complete.**

## 15. Source immutability

`M1_SOURCE_IMMUTABILITY_RECHECK.md` — all sources unchanged
(`SOURCE_A_CHANGED_SINCE_M0 = NO`, `SOURCE_B_CHANGED_SINCE_M0 = NO`,
`B7A_CHANGED = NO`, `B7B_CHANGED = NO`, `B8_CHANGED = NO`).

---

## 16. Final report fields

```
M1_STATUS = PARTIAL
  (every item complete with real evidence except item 14's full-suite
   regression, which is still running in the background, not failed or
   blocked -- targeted-category evidence for the same scope is already
   QUALIFIED. Recommend: treat as READY_FOR_APPROVAL conditional on the
   full-suite run finishing clean against the M0/H2-6 failure signature;
   this session will report that result once it completes.)

CANONICAL_BRANCH = canonical/m1-bootstrap
CANONICAL_HEAD = 3d4b84c3f5c348f5263fd1cc2998a7a7a0716649

CANONICAL_V50_BASELINE = QUALIFIED
  (targeted categories) / NOT_YET_FULLY_QUALIFIED (full suite pending)

REPOSITORY_IDENTITY = PASS
DV_DOCTOR = PASS
EXECUTION_PROFILE_RESOLUTION = PASS
EXISTING_REMOTE_TRANSPORT_PRESERVED = YES

EXECUTION_SERVICE_OPERATIONALIZED = NO
REMOTE_EDA_BACKEND_OPERATIONALIZED = NO

KNOWLEDGE_BRAIN_PRESERVED = YES
OBSIDIAN_CAPABILITY_PRESERVED = YES

MULTI_AGENT_PROTECTED_CAPABILITY_RECORDED = YES
MULTI_AGENT_DIRTY_DIFF_APPLIED = NO

CANONICAL_SECURITY_FLOOR = PRESERVED

KNOWN_SOURCE_B_DEFECT_STATUS = KNOWN_SOURCE_B_DEFECT_PRESERVED_FOR_LATER_FIX

LOCATION_INDEPENDENT = YES
REPOSITORY_RENAME_SUPPORTED = YES
DEVELOPER_MODE_SUPPORTED = YES
DEPLOYMENT_COPY_MODE_SUPPORTED = YES

ABSOLUTE_BOOTSTRAP_PATH_RUNTIME_DEPENDENCIES = 0
HISTORICAL_SOURCE_PATH_RUNTIME_DEPENDENCIES = 0
HARDCODED_GATEWAY_HOST_IN_RUNTIME = 0
HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME = 0
LOCAL_REMOTE_PATH_COUPLING = 0

SOURCE_A_CHANGED_SINCE_M0 = NO
SOURCE_B_CHANGED_SINCE_M0 = NO
B7A_CHANGED = NO
B7B_CHANGED = NO
B8_CHANGED = NO

PARENT_CAPABILITY_MIGRATION_STARTED = NO
WORKTREE_CAPABILITY_MIGRATION_STARTED = NO

REFERENCE_USB_ENV_CONSUMED = NO
C6_STARTED = NO
PLATFORM_UPGRADE_STARTED = NO

M1_IS_FINAL_PRODUCT = NO
M1_CAPABILITY_GATE = V50_BASELINE_PRESERVATION
FINAL_CAPABILITY_GATE = STRICT_SUPERSET_OF_ALL_APPROVED_SOURCES
```

**STOP. Not starting M3/M4/M5. Waiting for M1 review.** The full-suite
regression will be checked again and its final result reported as a
follow-up to this same report once it completes.
