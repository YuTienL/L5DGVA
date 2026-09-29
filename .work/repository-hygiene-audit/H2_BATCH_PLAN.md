# H2 Batch Plan — Phase 2 Repository Hygiene (Draft, Not Executed)

**PLAN ONLY.** No batch below has been run. This is the detailed, 15-field specification for each of the 9 H2 steps summarized in `REPOSITORY_HYGIENE_PHASE2_DRAFT_PLAN.md`. Every modifying batch, when and if approved for execution, follows: `PRE-STATE → ALLOWED WRITE SET → MODIFY → DIFF REVIEW → FOCUSED TESTS → RELATED TESTS → FAILURE CLASSIFICATION → STAGING REVIEW → COMMIT → RECORD SHA → NEXT BATCH`.

Failure classification for every batch reuses the taxonomy established during the C5 Standard-Flow closure: **PRE_EXISTING** (reproduces at the H2-0 baseline SHA in an isolated check) / **ENVIRONMENT** / **TEST_INFRASTRUCTURE** / **REGRESSION_CAUSED_BY_PHASE2** / **UNKNOWN**. A batch does not commit while any failure it introduced is classified UNKNOWN.

---

## H2-0 — Baseline / Governance Check

| Field | Content |
|---|---|
| 1. Purpose | Capture the pre-batch baseline every later batch diffs against, and classify `core.hooksPath`. Non-modifying. |
| 2. Authoritative evidence | `17_REGRESSION_PLAN.md` (baseline-capture recipe), `MIGRATION_REVIEW.md` (hooksPath finding), this plan's own re-verification table. |
| 3. Exact candidate files | None (read-only: git metadata + a full pytest run). |
| 4. Exact allowed write set | One new evidence file under `v50/.work/repository-hygiene-audit/` (e.g. `H2_0_BASELINE.md`) recording the captured facts. No other file. |
| 5. Explicit forbidden write set | Every other file in the repository. |
| 6. Preconditions | `git -C v50 rev-parse --show-toplevel` still equals REPO_ROOT (Repository Root Contract re-check). |
| 7. Actions | Record: branch, HEAD SHA, `git status --porcelain` (the pre-existing 3 modified tracked files + 11 UNKNOWN untracked items must be captured explicitly, so later batches don't mistake pre-existing dirt for their own effect); run `python -m pytest dv_harness_tests/ -q`, save full pass/fail counts and the failing-test list verbatim; inspect `tools/git-hooks/{pre-push,pre-merge-commit}`, `dv_harness/git_governance.py`, and the `git-guard` CLI verb; classify `core.hooksPath` using the 5-value taxonomy. |
| 8. Focused tests | Import/collection smoke test: `python -c "import dv_harness"` and `pytest --collect-only -q`. |
| 9. Related regression tests | Full suite (this batch's own baseline capture — see Actions). |
| 10. Failure classification rules | N/A to this batch's own output (it establishes the baseline other batches classify against) — but any pre-existing failure found here must be listed by name, not summarized as a count only. |
| 11. STOP conditions | Git top-level ≠ REPO_ROOT → STOP. `core.hooksPath` classification cannot be supported by direct evidence → STOP and escalate rather than guess. |
| 12. Commit boundary | One commit, the new baseline-evidence file only. |
| 13. Suggested commit message | `repo-hygiene(H2-0): capture Phase-2 baseline (HEAD, status, full regression, hooksPath classification)` |
| 14. Rollback procedure | `git revert` (removes only the evidence file; no other state to restore since nothing else changed). |
| 15. Exit criteria | Baseline SHA/branch/status recorded; full regression baseline saved; `core.hooksPath` classified as **`CURRENT_BUT_DISABLED, and REQUIRED per CLAUDE.md policy`** (see rationale in the draft plan) — not enabled. |

---

## H2-1 — Root Pollution Prevention

| Field | Content |
|---|---|
| 1. Purpose | Close the 3 confirmed `.gitignore` gaps (`.pytest_tmp/`, `.pytest-tmp-*`, `_tmp_*`). |
| 2. Authoritative evidence | `16_GITIGNORE_HYGIENE_PLAN.md`, `08_SCRIPT_CONFIG_INVENTORY.md`'s gitignore-gap section. |
| 3. Exact candidate files | `.gitignore` |
| 4. Exact allowed write set | `.gitignore` only. |
| 5. Explicit forbidden write set | The 8 `.pytest-tmp-*.tcl/.sh` files, the 3 `_tmp_*` files, `.pytest_tmp/` itself (that is H2-2), every other file. |
| 6. Preconditions | H2-0 committed. Re-grep `.gitignore` at batch time for the 3 target patterns — do not assume the Phase-1 finding still holds if time has passed. |
| 7. Actions | Append exactly the 3-line block from `16_GITIGNORE_HYGIENE_PLAN.md` (`.pytest_tmp/`, `.pytest-tmp-*`, `_tmp_*`) with its explanatory comment. |
| 8. Focused tests | `git check-ignore -v .pytest_tmp .pytest-tmp-clock-table.tcl _tmp_selfcheck_big5.txt` — all three must now report ignored. |
| 9. Related regression tests | Tier 1 (smoke) + tier 8 (full regression) — expected no-op, since no test reads `.gitignore` content. |
| 10. Failure classification rules | Any new failure vs. H2-0 baseline is surprising for a `.gitignore`-only change and must be root-caused before commit, not merely classified and passed through. |
| 11. STOP conditions | Any of the 3 patterns already present in `.gitignore` at batch time (unexpected drift) → STOP, investigate before appending a duplicate. Any new (non-baseline) regression failure → STOP. |
| 12. Commit boundary | One commit, `.gitignore` only. |
| 13. Suggested commit message | `repo-hygiene(H2-1): close 3 confirmed root .gitignore gaps (.pytest_tmp/, .pytest-tmp-*, _tmp_*)` |
| 14. Rollback procedure | `git revert <H2-1 SHA>`. |
| 15. Exit criteria | Diff is exactly the 3-line addition; all three patterns confirmed ignored; zero new regression failures; SHA recorded. |

---

## H2-2 — Proven Generated Garbage Cleanup

| Field | Content |
|---|---|
| 1. Purpose | Delete `.pytest_tmp/` (179 files) — confirmed reproducible, zero consumers. |
| 2. Authoritative evidence | `14_DELETE_GENERATED_PLAN.md`, `09_TEMP_ARTIFACTS.md`. |
| 3. Exact candidate files | All 179 files under `.pytest_tmp/`. |
| 4. Exact allowed write set | Deletion within `.pytest_tmp/` only; no other path. |
| 5. Explicit forbidden write set | `.pytest_cache/` (already correctly ignored, no action needed — do not touch), the 8 `.pytest-tmp-*.tcl/.sh` UNKNOWN files (name-similar, **not** the same path — must not be swept up by a careless glob), the 3 `_tmp_*` UNKNOWN files. |
| 6. Preconditions | H2-1 committed first, so the ignore rule is already in place and the directory cannot silently reappear untracked (per `20_MINIMUM_CHANGE_PLAN.md`'s explicit ordering rationale). |
| 7. Actions | Confirm `.pytest_tmp/` is untracked (`git ls-files .pytest_tmp` returns nothing); delete the directory; because nothing tracked is removed, this produces no git diff by itself — record the action's evidence (file count deleted, date, verification that it was untracked) as a status update appended to `09_TEMP_ARTIFACTS.md`, which **is** the tracked, committable record of this batch. |
| 8. Focused tests | `ls .pytest_tmp` fails (directory gone); `git status --porcelain` no longer lists it. |
| 9. Related regression tests | Tier 1 + tier 8 — expected no-op (zero consumers per Phase-1 evidence). |
| 10. Failure classification rules | Standard taxonomy. |
| 11. STOP conditions | If any file under `.pytest_tmp/` has an mtime newer than the H2-0 baseline capture time (meaning something wrote into it since baseline, contradicting the "zero consumers" evidence) → STOP and re-investigate before deleting. |
| 12. Commit boundary | One commit updating `09_TEMP_ARTIFACTS.md` (execution record) only — no other tracked file changes, since the deletion itself is git-invisible. |
| 13. Suggested commit message | `repo-hygiene(H2-2): delete .pytest_tmp/ (179 files, confirmed reproducible pytest scratch, zero consumers)` |
| 14. Rollback procedure | Not a `git revert` for the deletion itself (nothing tracked was removed) — regenerate via the same manual `pytest --basetemp=.pytest_tmp` invocation that created it (per `18_ROLLBACK_PLAN.md` rule 6). `git revert` handles only the `09_TEMP_ARTIFACTS.md` record update if that needs undoing. |
| 15. Exit criteria | `.pytest_tmp/` absent from disk; zero regression delta; execution-record commit recorded. |

---

## H2-3 — Archive the 48 Approved Legacy Files

| Field | Content |
|---|---|
| 1. Purpose | Relocate the 34 `.md` + 14 JSON zero-reference files to `docs/legacy/`/`docs/release/`. |
| 2. Authoritative evidence | `12_MOVE_PLAN.csv` (the literal, canonical 48-row source→destination list — referenced here, not re-transcribed, to avoid two copies drifting apart), `11_PROPOSED_TARGET_LAYOUT.md`, `04_REFERENCE_GRAPH.md` (zero-inbound-reference evidence), `15_PATH_REWRITE_PLAN.md` (confirms zero rewrites needed). |
| 3. Exact candidate files | The exact 48 rows of `12_MOVE_PLAN.csv` — no more, no fewer. |
| 4. Exact allowed write set | `git mv` for exactly those 48 files to their listed destinations (creating `docs/legacy/pre-2026-09-05-consolidation/` and `docs/release/legacy-validation-snapshots/` as needed). |
| 5. Explicit forbidden write set | Any file not in the 48-row list — especially the 11 UNKNOWN files, `WORKFLOW_MANIFEST.json` (real consumers, stays), the two LSF files (handled separately in H2-5C and not part of the 48), `CLAUDE.md`, `START_HERE.md`, any other `KEEP_ROOT`/`KEEP_IN_PLACE_FOR_COMPATIBILITY` entry. |
| 6. Preconditions | H2-2 committed. Re-run the zero-inbound-reference check fresh at batch time for all 48 (do not just trust the Phase-1 snapshot — a reference could have been introduced since). |
| 7. Actions | One `git mv` per file, exactly matching `12_MOVE_PLAN.csv`'s destination column. |
| 8. Focused tests | Tier 2 (CLAUDE.md/context-budget tests) + tier 4 (package/release-manifest tests) + an ad hoc broken-link grep across remaining root/`docs/` `.md` files for a relative link to any of the 48 old paths (the dedicated scan script from `17_REGRESSION_PLAN.md` tier 6 does not exist yet — do this manually until it is built). |
| 9. Related regression tests | Full regression (tier 8) — mandatory, since this is the only batch touching a non-trivial file count. |
| 10. Failure classification rules | Standard taxonomy, diffed against the H2-0 baseline exactly. |
| 11. STOP conditions | Any of the 48 files found to have a real inbound reference at batch time not present in the Phase-1 snapshot → STOP, exclude that file from this batch, re-scope. Any new (non-baseline) full-regression failure → STOP before commit. |
| 12. Commit boundary | One commit for all 48 moves together (splitting further adds process overhead with no additional safety, per `20_MINIMUM_CHANGE_PLAN.md`). |
| 13. Suggested commit message | `repo-hygiene(H2-3): archive 48 zero-reference legacy docs/JSON captures to docs/legacy|release/` |
| 14. Rollback procedure | `git revert <H2-3 SHA>` (git-native moves in one commit — clean revert per `18_ROLLBACK_PLAN.md` rules 1–3). |
| 15. Exit criteria | Exactly 48 files relocated; `git status` otherwise clean; zero regression delta; SHA recorded. |

---

## H2-4 — Minimal Canonical `README.md`

| Field | Content |
|---|---|
| 1. Purpose | Close the "no `README.md` exists" gap with a 2-line pointer to `START_HERE.md`. |
| 2. Authoritative evidence | `11_PROPOSED_TARGET_LAYOUT.md` (includes the explicit safeguard against a third competing entry point, independently confirmed important by the Phase-1 independent reviewer). |
| 3. Exact candidate files | New file `README.md`. |
| 4. Exact allowed write set | `README.md` (create) only. |
| 5. Explicit forbidden write set | Any content beyond the 2-line pointer — writing real content here would recreate the exact `README_*` duplicate-entry-point failure mode this audit is archiving. |
| 6. Preconditions | Re-confirm `README.md` still does not exist at batch time. |
| 7. Actions | Create exactly the 2-line content specified in `11_PROPOSED_TARGET_LAYOUT.md` (title + one-line pointer to `START_HERE.md`). |
| 8. Focused tests | Manual check: file is exactly a title line + one pointer line, no additional content. |
| 9. Related regression tests | Tier 1 + tier 8 — expected no-op (pure addition, zero prior consumers of a file that didn't exist). |
| 10. Failure classification rules | Standard taxonomy. |
| 11. STOP conditions | `README.md` already exists at batch time (unexpected drift) → STOP, do not overwrite blindly. |
| 12. Commit boundary | One commit, `README.md` only. |
| 13. Suggested commit message | `repo-hygiene(H2-4): add minimal root README.md pointing to START_HERE.md` |
| 14. Rollback procedure | `git revert` (or plain delete — pure addition). |
| 15. Exit criteria | `README.md` exists, exactly 2 lines of real content, zero regression delta, SHA recorded. |

---

## H2-5A — Correct Stale "Seven Agents" Assertions

| Field | Content |
|---|---|
| 1. Purpose | Fix `.claude/INDUSTRIAL_DV_WORKFLOW.md`'s "Seven agents" section and the two preflight scripts' hardcoded 7-name lists / `/7` denominator to reflect the real 23-agent `ROSTER.md` model — while preserving both the 23 physical agents unchanged and the (already fully reconciled, zero-gap) 7 logical orchestration roles concept. |
| 2. Authoritative evidence | `05_AUTHORITY_GRAPH.md`, `02_ROOT_CLASSIFICATION.md`, `AGENT_AUTHORITY_MAPPING.md`, `.claude/agents/ROSTER.md` itself (already correct and already contains the "Answers to the asserted role taxonomy" reconciliation). |
| 3. Exact candidate files | `.claude/INDUSTRIAL_DV_WORKFLOW.md`, `.claude/tools/check-claude-dv-env.ps1`, `.claude/tools/dv-preflight.ps1`. |
| 4. Exact allowed write set | Exactly those 3 files, content-only edits. |
| 5. Explicit forbidden write set | `.claude/agents/ROSTER.md` itself (already correct — the only correct direction is making the 3 stale files agree with it, never the reverse). **No new `.claude/agents/*.md` file is created under any circumstance** — this batch must not misread "7 logical roles" as "must have 7 physical agents" (explicit non-goal). No change to either script's actual PASS/FAIL preflight *logic*, only to the stale name-list/count text (explicit "do not modify production behavior merely for repository cleanup" non-goal). |
| 6. Preconditions | `ROSTER.md` content re-verified unchanged and still the accepted source of truth. |
| 7. Actions | Update `.claude/INDUSTRIAL_DV_WORKFLOW.md`'s "## Seven agents" section to accurately reference `ROSTER.md`'s real model (exact wording — a rewrite vs. a pointer — is an execution-time editorial decision, not fixed here). Update both `.ps1` scripts' hardcoded list and `/7` denominator so the count they check is no longer asserted as "the total" (exact mechanism — deriving the list from `ROSTER.md` programmatically vs. re-hardcoding a corrected fixed set — is an execution-time design decision, flagged here as open). |
| 8. Focused tests | `dv_harness_tests/test_agent_roster_doc.py`, `dv_harness_tests/test_agent_dispatch_map.py` (must still pass — this batch does not touch `ROSTER.md`, so they should be unaffected, but they are the nearest real regression signal for this area). |
| 9. Related regression tests | No pytest file was found referencing either `.ps1` script (per Phase-1 evidence) — real regression evidence for this batch is manual invocation of both scripts against the current repo layout, confirming a sane, unchanged-in-kind status output. |
| 10. Failure classification rules | Standard taxonomy. |
| 11. STOP conditions | If changing the hardcoded list would alter either script's PASS/FAIL verdict for the current repo state in a way not explained purely by the stale-count bug → STOP, treat as an undisclosed behavior change requiring separate review, not a hygiene fix. |
| 12. Commit boundary | One commit, all 3 files together (one coherent fix). |
| 13. Suggested commit message | `repo-hygiene(H2-5A): correct stale 'seven agents' claim in INDUSTRIAL_DV_WORKFLOW.md and 2 preflight scripts` |
| 14. Rollback procedure | `git revert`. |
| 15. Exit criteria | None of the 3 files asserts "seven agents" as the total any more; `ROSTER.md` unchanged; both roster tests still pass; both scripts still run without new errors; zero regression delta. |

---

## H2-5B — Fix `expert-feedback-closure` → `dv-expert-feedback-closure`

| Field | Content |
|---|---|
| 1. Purpose | Correct the one broken skill reference among 47 in `main_graph.json`. |
| 2. Authoritative evidence | `BROKEN_SKILL_REFERENCE.md`. |
| 3. Exact candidate files | `.dv-harness/graph/main_graph.json` — the `EXPERT_FEEDBACK_LOOP` node's `"skills"` array only. |
| 4. Exact allowed write set | That one string value in that one file. |
| 5. Explicit forbidden write set | **No replacement skill is created** (explicit instruction). The real skill directory `.claude/skills/EXPERT_FEEDBACK/dv-expert-feedback-closure/` is not touched — it is already correct. No other node/skill reference in `main_graph.json` is touched (all other 46 already resolve). |
| 6. Preconditions | Re-confirm at batch time that `dv-expert-feedback-closure` still exists and is still the only sensible match (re-run the 47-reference resolution check). |
| 7. Actions | Change `"skills": ["expert-feedback-closure"]` to `"skills": ["dv-expert-feedback-closure"]` for the `EXPERT_FEEDBACK_LOOP` node. |
| 8. Focused tests | Any existing `main_graph.json` schema/skill-reference validator test, if one exists (search first — its absence is itself a disclosed gap, not a blocker). |
| 9. Related regression tests | Full regression tier 8, plus a graph-load smoke check confirming `main_graph.json` still parses and loads via `engine.py`'s graph-loading path. |
| 10. Failure classification rules | Standard taxonomy. Also check specifically for any test asserting on `main_graph.json`'s exact byte content (Tier-2-resident artifacts sometimes are) before committing. |
| 11. STOP conditions | `dv-expert-feedback-closure` no longer exists at batch time (drift since Phase 1) → STOP, do not point the reference at a nonexistent skill. JSON fails to parse after the edit → hard STOP, not a classified regression. |
| 12. Commit boundary | One commit, `main_graph.json` only. |
| 13. Suggested commit message | `repo-hygiene(H2-5B): fix EXPERT_FEEDBACK_LOOP skill reference (expert-feedback-closure -> dv-expert-feedback-closure)` |
| 14. Rollback procedure | `git revert`. |
| 15. Exit criteria | JSON still valid; all 47 skill references now resolve (up from 46/47); zero regression delta; SHA recorded. |

---

## H2-5C — Correct the Two Stale LSF "Superseded" Banners (Conditional)

| Field | Content |
|---|---|
| 1. Purpose | Correct the "Superseded" line-1 banner on both LSF files, since both are actually current per production-code citation and `START_HERE.md`'s own listing. |
| 2. Authoritative evidence | `02_ROOT_CLASSIFICATION.md`, plus this plan's own fresh re-verification (banners still identical, `dv_harness/lsf_client.py:568` still cites the file by name in a live docstring, `START_HERE.md` still lists both as current). |
| 3. Exact candidate files | `LSF_PER_JOB_AGENT_MONITORING_v16_1.md`, `LSF_STRICT_PER_JOB_IRON_RULES_v19_1.md` — line 1 only in each. |
| 4. Exact allowed write set | Exactly those 2 files' line-1 banner text. |
| 5. Explicit forbidden write set | Any other content in either file. These files are **not** archived (they stay `KEEP_ROOT`, not part of the 48). No other LSF-named file is touched. |
| 6. Preconditions | **Conditional gate, re-checked at batch execution time, not merely at plan-drafting time**: (a) both banners still say "Superseded"; (b) production code still cites `LSF_PER_JOB_AGENT_MONITORING_v16_1.md` by name in real, non-comment-stripped code; (c) `START_HERE.md` still lists both files as current. If any of the three has changed since this plan was drafted, this batch does not apply the plan's assumption blindly — it re-derives the correction or is skipped. |
| 7. Actions | Replace the "Superseded" banner line in both files with a corrected current-status line. Exact wording is deliberately left as an execution-time human-confirmed decision (banner wording is a content/governance call the Phase-1 audit explicitly deferred to a human in `13_MERGE_REDIRECT_PLAN.md`, not something this plan pre-writes). |
| 8. Focused tests | None assert on the banner text directly (confirm via grep before commit). Run any `test_lsf_*.py` suite to confirm the production-code citation/file identity is unaffected. |
| 9. Related regression tests | Tier 8 full regression; also re-run any test that reads either LSF file's content directly (search first). |
| 10. Failure classification rules | Standard taxonomy. |
| 11. STOP conditions | **Required by this task, not merely a generic precondition**: if the re-checked evidence at batch time no longer supports the correction (production code stopped citing the file, or `START_HERE.md` was changed to actually deprecate it) → **this batch is SKIPPED, not forced** — do not apply the fix, and record the skip explicitly in H2-6's closure record rather than silently omitting it. |
| 12. Commit boundary | One commit, both files together (same defect, same fix pattern) — only if the conditional gate in field 6/11 passes. |
| 13. Suggested commit message | `repo-hygiene(H2-5C): correct stale 'Superseded' banner on 2 current LSF mechanism docs` |
| 14. Rollback procedure | `git revert`. |
| 15. Exit criteria | Both banners no longer say "Superseded"; the production-code citation still resolves to the same, unmoved file; zero regression delta; SHA recorded — **or** the batch is explicitly recorded as SKIPPED_BY_EVIDENCE_GATE. |

---

## H2-6 — Final Full Regression + Repository Baseline Freeze

| Field | Content |
|---|---|
| 1. Purpose | Run the complete regression suite against the **final integrated HEAD** (after the last real H2 commit — H2-5C's if it ran, H2-5B's if H2-5C was skipped), classify every failure, and only if `REGRESSION_CAUSED_BY_PHASE2 = 0` and `UNKNOWN_REGRESSION_FAILURES = 0`, write the freeze record and declare `REPOSITORY_HYGIENE = CLOSED`. |
| 2. Authoritative evidence | `17_REGRESSION_PLAN.md` (all 8 tiers), `18_ROLLBACK_PLAN.md`, the accumulated H2-1…H2-5C commit SHAs. |
| 3. Exact candidate files | None for modification; one new freeze-record file (e.g. `PHASE2_FINAL_REPORT.md`) under the audit directory. |
| 4. Exact allowed write set | That one new file only. |
| 5. Explicit forbidden write set | Any production/doc/config file — H2-6 is verification + record-writing only. |
| 6. Preconditions | All prior applicable batches (H2-1 through H2-5B, plus H2-5C if its gate passed) are committed. The working tree's pre-existing dirty state (the 3 tracked files modified before H2-0, per baseline) is unchanged from H2-0's capture — if it has drifted further, that is a scope violation to flag explicitly, not silently absorb into this batch's own diff. |
| 7. Actions | Run the full 8-tier regression plan against current HEAD; diff every failure against the H2-0 baseline; classify each; write the freeze record with every required field (see below). |
| 8. Focused tests | N/A — this batch's job is running the full suite. |
| 9. Related regression tests | The entire suite, by definition. |
| 10. Failure classification rules | This batch's core output — every failure gets one of the 5 labels; the batch cannot close with any `UNKNOWN`. |
| 11. STOP conditions | `REGRESSION_CAUSED_BY_PHASE2 > 0` or `UNKNOWN_REGRESSION_FAILURES > 0` → do **not** write `CLOSED`; write `PARTIAL` or `BLOCKED` instead and stop. |
| 12. Commit boundary | One commit, the freeze-record file only. |
| 13. Suggested commit message | `repo-hygiene(H2-6): final regression + Repository Baseline Freeze after Phase-2 hygiene batches H2-1..H2-5C` |
| 14. Rollback procedure | `git revert` removes only the freeze-record file; each prior batch remains independently revertible via its own SHA. |
| 15. Exit criteria | Freeze record written with: final branch; final HEAD SHA; every H2 commit SHA; root entry count before/after; archived count (48, unless H2-3 excluded any); deleted-generated count; remaining UNKNOWN count (must still be 11 — untouched, per non-goal); physical-agent authority (`ROSTER.md`, 23); logical orchestration model (7 roles, zero gap, unchanged); graph skill-reference status (47/47 resolved); hooks status (unchanged: `CURRENT_BUT_DISABLED, REQUIRED` — never enabled by this plan); worktree-policy status (`HUMAN_DECISION_PENDING`, unchanged; 0 pruned); C1–C5 regression status (main-repo placeholder tier, `v50` does not own those suites). `REPOSITORY_HYGIENE = CLOSED` only if both zero-counts hold; otherwise `PARTIAL`/`BLOCKED` with named blockers. |

---

## Compact summary table

| Batch | Modifies | Commits | Reversible via |
|---|---|---|---|
| H2-0 | Nothing (read-only) | 1 (evidence file) | `git revert` |
| H2-1 | `.gitignore` | 1 | `git revert` |
| H2-2 | `.pytest_tmp/` (untracked delete) + `09_TEMP_ARTIFACTS.md` record | 1 | Regenerate via `pytest --basetemp` |
| H2-3 | 48 files (`git mv`) | 1 | `git revert` |
| H2-4 | `README.md` (new) | 1 | `git revert` |
| H2-5A | `.claude/INDUSTRIAL_DV_WORKFLOW.md` + 2 `.ps1` scripts | 1 | `git revert` |
| H2-5B | `.dv-harness/graph/main_graph.json` | 1 | `git revert` |
| H2-5C | 2 LSF `.md` files (conditional — may be skipped) | 0 or 1 | `git revert` |
| H2-6 | New freeze-record file | 1 | `git revert` |

Expected total: **8 commits** if H2-5C's evidence gate passes, **7** if it is skipped. Neither count includes any commit to a worktree, any of the 11 UNKNOWN files, or any new physical agent file — all explicitly forbidden throughout.
