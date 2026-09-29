# Repository Hygiene — Phase 2 Draft Plan

**STATUS: PLAN ONLY. NOTHING BELOW HAS BEEN EXECUTED.** No file was moved, deleted, archived, staged, or committed to produce this document. No git configuration was changed. No worktree was touched. This document and its companion `H2_BATCH_PLAN.md` are the only two files written by this task, both under `v50/.work/repository-hygiene-audit/`.

**Execution mode: LOCAL_ANALYSIS** (re-verification of accepted evidence only — no server, no VCS mutation).

## Pre-drafting re-verification

Per the instruction to validate rather than assume the proposed H2 structure is correct, the following facts were re-checked directly against the repository (not merely re-quoted from prior audit prose) immediately before drafting:

| Fact | Re-checked value | Matches prior artifact? |
|---|---|---|
| Git identity | `master` @ `9abb10f234bc46ea9877982f959cd4e9ae07b365`, top-level = `v50` | Yes — unchanged since `FINAL_AUDIT_REPORT.md` and `MIGRATION_REVIEW.md` |
| `12_MOVE_PLAN.csv` row composition | 48 rows exactly, 34 `.md` + 14 `.json` | Yes — matches `02_ROOT_CLASSIFICATION.md`'s ARCHIVE breakdown |
| `01_ROOT_INVENTORY.csv` action counts | KEEP_ROOT 65, ARCHIVE 48, UNKNOWN 11, DELETE_GENERATED 2, KEEP_IN_PLACE_FOR_COMPATIBILITY 2, MOVE/MERGE/REDIRECT 0 (total 128) | Yes |
| Both LSF files' line 1 | Byte-identical: `> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.` | Yes — confirms `02_ROOT_CLASSIFICATION.md`'s claim that both banners currently say "superseded" |
| `dv_harness/lsf_client.py:568` docstring | Cites `LSF_PER_JOB_AGENT_MONITORING_v16_1.md`'s "Early-Fail" section by name, in a real, non-comment docstring for a live function (`evaluate_auto_kill`) | Yes — confirms production code treats the file as current documentation, not a superseded one |
| `START_HERE.md` | Lists both LSF files (lines 223–224) among its "standalone one-page mechanism" docs | Yes — confirms it does **not** treat them as superseded |
| `tools/git-hooks/` | `pre-push` (140 lines), `pre-merge-commit` (33 lines), `README.md` all present and non-trivial; `dv_harness/git_governance.py` (10,760 bytes) and a real `git-guard` CLI subcommand (`dv_harness/cli.py:596,4583`) exist | **New finding, not previously stated this precisely**: the hook mechanism is real, current, and substantial — not stale/legacy code. See `core.hooksPath` classification below. |
| `.gitignore` | 156 lines, lines 1–5 confirmed (`__pycache__/`, `*.pyc`, `.pytest_cache/`, `.superpowers/`) | Yes — matches `16_GITIGNORE_HYGIENE_PLAN.md`'s description |

**Conclusion of re-verification: the proposed H2-0…H2-6 structure is supported by re-checked evidence, with one refinement** — H2-5C's LSF-banner fix is confirmed still valid (both files still say "superseded," which is still contradicted by `START_HERE.md` and live production code), so H2-5C proceeds as proposed, not skipped.

## `core.hooksPath` classification (diagnostic only — no config change proposed or made)

Observed: `git config --get core.hooksPath` returns empty in this `v50` checkout (confirmed in the prior Migration Review and re-confirmed as still true; no change was made or is proposed).

Choosing among the five offered labels from direct evidence:

- Not **STALE**: the underlying mechanism (`tools/git-hooks/pre-push`, `pre-merge-commit`, `dv_harness/git_governance.py`, the `git-guard` CLI verb) is real, current, non-trivial, and actively referenced by `CLAUDE.md`'s own governance policy — nothing about it is legacy or superseded.
- Not **OPTIONAL**: `CLAUDE.md`'s gh CLI + PR-Only Governance Policy describes local hook enforcement as one of three **layered, hard** enforcement mechanisms (server-side branch protection, local hooks, blast-radius escalation) backing a policy stated as non-negotiable ("must never merge or push directly into a protected branch").
- Not **UNKNOWN**: the facts needed to classify it (mechanism exists, is current, is unset in this checkout) are all directly observed, not missing.
- Best fit is **both `REQUIRED` (policy stance) and `CURRENT_BUT_DISABLED` (observed state) simultaneously** — these are different axes, not competing single answers: `CLAUDE.md` requires this be confirmed/set (`REQUIRED`), and the real, current mechanism it requires is presently unwired in this checkout (`CURRENT_BUT_DISABLED`). Reported as: **`CURRENT_BUT_DISABLED, and REQUIRED per CLAUDE.md policy`**.

**This plan does not enable `core.hooksPath`** (explicit non-goal, honored). The classification exists only so a human approving this plan has an accurate diagnostic, not a proposal to act on it.

## Batch sequence (summary — full detail in `H2_BATCH_PLAN.md`)

| Batch | Purpose | Files touched | Type |
|---|---|---|---|
| H2-0 | Baseline capture + governance check (read-only) | none (records facts only) | Non-modifying |
| H2-1 | Root pollution prevention — 3 new `.gitignore` entries | `.gitignore` | Modifying |
| H2-2 | Delete `.pytest_tmp/` (179 files, proven-generated) | `.pytest_tmp/` (deletion) | Modifying |
| H2-3 | Archive the 48 approved legacy files | 48 files (34 `.md` + 14 `.json`) → `docs/legacy/...` / `docs/release/...` | Modifying |
| H2-4 | New root `README.md` (2-line pointer to `START_HERE.md`) | `README.md` (new) | Modifying |
| H2-5A | Correct stale "seven agents" assertions | `.claude/INDUSTRIAL_DV_WORKFLOW.md`, `.claude/tools/check-claude-dv-env.ps1`, `.claude/tools/dv-preflight.ps1` | Modifying (content-only) |
| H2-5B | Fix `expert-feedback-closure` → `dv-expert-feedback-closure` | `.dv-harness/graph/main_graph.json` | Modifying (content-only) |
| H2-5C | Fix both LSF "superseded" banners | `LSF_PER_JOB_AGENT_MONITORING_v16_1.md`, `LSF_STRICT_PER_JOB_IRON_RULES_v19_1.md` | Modifying (content-only) |
| H2-6 | Final full regression + Repository Baseline Freeze | none (verification + one freeze-record artifact) | Non-modifying (verification) |

**H2_BATCH_COUNT = 9** (H2-0 through H2-6, with H2-5 split into 5A/5B/5C = 9 total steps, 6 of which perform a file modification).

## Non-goals carried into every batch definition (repeated verbatim per instruction, not paraphrased away)

Do not execute any H2 batch. Do not move files. Do not delete files. Do not archive files. Do not stage. Do not commit. Do not prune or modify any worktree. Do not touch the 11 UNKNOWN root files. Do not create seven new physical agents. Do not automatically enable `core.hooksPath`. Do not start C6. Do not start Platform P0–P6. Do not start WSL2 migration. Do not start Docker migration. Do not implement `RemoteExecutionBackend`. Do not start Wave 3. Do not consume the Reference USB Environment.

## Accepted findings preserved unchanged by this plan

```
AGENT_PHYSICAL_SOURCE_OF_TRUTH = .claude/agents/ROSTER.md
PHYSICAL_AGENT_COUNT = 23
LOGICAL_ORCHESTRATION_MODEL = 7 roles, fully reconciled, zero gap
WORKTREE_AUTHORITY_STATUS = HUMAN_DECISION_PENDING
ARCHIVE_AMBIGUOUS_INTERSECTION = 0
EXPERT_FEEDBACK_CLOSURE_STATUS = MISTYPED_REFERENCE
```

Worktree disposition preserved exactly as given, not re-derived:
- `b1, b2, b4, b5, b6` = merged/stale — **not pruned by any H2 batch**.
- `b7a, b7b, b8` = real unmerged/uncommitted work — **not touched by any H2 batch**.
- `b3` = unexplained naming gap — left unexplained; no H2 batch investigates or resolves it further.

## What H2-6's closure record must contain (restated as a requirement on that batch, detailed further in `H2_BATCH_PLAN.md`)

Final branch; final HEAD SHA; every H2 commit SHA (H2-1 through H2-5C, 6 commits expected); root entry count before/after; archived count; deleted-generated count; remaining UNKNOWN count; physical-agent authority; logical orchestration model; graph skill-reference status; hooks status; worktree-policy status; C1–C5 regression status (main-repo placeholder tier, per `17_REGRESSION_PLAN.md` — `v50` does not itself own the C1–C5 suites).

## Approval gate

This plan is not self-executing. Per instruction, no H2 batch runs until a separate, explicit approval is given. This document and `H2_BATCH_PLAN.md` are the deliverable; execution (were it approved) would follow the PRE-STATE → ALLOWED WRITE SET → MODIFY → DIFF REVIEW → FOCUSED TESTS → RELATED TESTS → FAILURE CLASSIFICATION → STAGING REVIEW → COMMIT → RECORD SHA → NEXT BATCH sequence specified for every modifying batch in `H2_BATCH_PLAN.md`.
