# M4.5 — ChatGPT / Claude CLI / Codex Multi-Model Orchestration Audit

Real, evidence-based audit (background investigation across Parent, v50,
and canonical). **The "believed" capability — combining ChatGPT + Claude
CLI + Codex to reduce redundant Claude context/token consumption — is
confirmed `NOT_PRESENT` as a working automated mechanism.** What is real:
(a) a stale, purely human-mediated file-staging script for one abandoned
ChatGPT migration-review round, and (b) several recent, unusually honest
`dv_harness` audit modules whose entire purpose is to assemble Codex
review *packages* while explicitly refusing to fake the review act itself.
Neither reduces Claude's own context/token consumption — neither routes
any of Claude's own work to another model at all.

**This matches the project's own prior internal audit conclusion**,
independently confirmed rather than merely cited:
`.dv-harness/l5dgva_audit_result_F.md`'s "Codex independent review + dual
signoff" row already says `status = BLOCKED`, `'Grep of entire dv_harness/
for "codex" = 0 matches'` (Parent-side grep, at the time that audit ran) —
this M4.5 audit re-derived the same honest conclusion from scratch, with
current, direct file:line evidence, not by trusting that prior claim.

## ChatGPT integration

```
CHATGPT_INTEGRATION = HUMAN_MEDIATED_CHATGPT_HANDOFF
```

Real, runnable script: `tools/migration/prepare_chatgpt_review.py` (Parent)
stages review artifacts into `.chatgpt-handoff/<round>/` for a human to
paste into ChatGPT's UI. Real observed output exists
(`.chatgpt-handoff/round2c/`, dated 2026-09-09). Zero network/API call to
ChatGPT anywhere in the codebase. The pipeline's own return leg
(`NEXT_CODEX_PROMPT.md`) was never observed to complete even once
(zero such files exist anywhere). The pipeline is stuck at
`ROUND2C_COMPLETE_PENDING_CHATGPT_REVIEW`, stale since ~2026-09-09/10,
untracked in git, not referenced by the project's own current migration
contract (`v1/CLAUDE.md` never mentions ChatGPT at all). Full detail:
`M4_5_CHATGPT_INTEGRATION_AUDIT.md`.

## Codex integration

```
CODEX_INTEGRATION = HUMAN_MEDIATED_CODEX_REVIEW
```

Three real, CLI-wired, individually-tested `dv_harness/` modules
(`codex_kc_handoff_package.py`, `codex_full_contract_review_package.py`,
`l5dgva_pre_codex_review_truth.py`) assemble real review-evidence packages
— but each one's own docstring explicitly, repeatedly states the actual
review act does not exist (`BLOCKED_NO_EXTERNAL_REVIEWER`,
`codex_review_has_occurred=False` hard-coded, `NOT_PROVEN_REQUIRES_CODEX_TOOL`
hard-coded). Zero shell-out to a `codex` binary or API anywhere in
`dv_harness/`, `tools/`, or `.claude/`. **None of these three modules are
migrated to canonical** — confirmed absent from `D:\DV\Task\L5_DGVA\dv_harness\`,
already logged as such in `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`.
Full detail: `M4_5_CODEX_INTEGRATION_AUDIT.md`.

## Operationalization (Article 0's 6-value standard, strictly applied)

| Sub-capability | IMPLEMENTED | WIRED | TRIGGERED | CONSUMED | OBSERVED | TESTED |
|---|---|---|---|---|---|---|
| ChatGPT planning offload | YES (staging script) | NO | NO | NO | YES (round2c artifacts) | NO |
| Codex review offload | YES (3 package modules) | YES (real CLI verbs + engine.py call site) | YES (fires on PASS path) | **NO** (the thing WIRED/TRIGGERED is the honest self-blocking check, never a real review) | NO | YES (61/62, 1 unrelated brittle-test failure) |
| Structured issue/handoff schema | YES (prose, 161-line prompt doc) | NO | NO | NO | **NO** (zero `issue.md`/`ISSUE-*.md` ever produced) | NO |
| Token-usage observability | YES (`stage_profile.py`) | YES | YES (per-stage) | N/A | YES (real per-stage token counts) | presumed (not independently re-verified this wave) |
| Cross-model token-reduction measurement | NO | NO | NO | NO | NO | NO |

**CONSUMED is the critical column**: nothing in the whole audit reached
it for the actual multi-model handoff. Codex's own review packages are
WIRED and TRIGGERED, but what fires is a self-honest refusal, never a
consumed external review result.

## Token-reduction claim

```
TOKEN_REDUCTION_MEASURED = NO
TOKEN_REDUCTION_EFFECT = ARCHITECTURALLY_PLAUSIBLE_BUT_NOT_MEASURED
```
Justification for "architecturally plausible" (not "not demonstrated"):
real, working per-stage Claude token telemetry already exists
(`stage_profile.py`/`stage_profile_report.py`, in/out/cache token counts
from the CLI adapter's real usage payload) and the target architecture
(ChatGPT plan → scoped task packet → Claude implements → Codex reviews →
compact issue packet → Claude fixes the delta) is a coherent, sensible
design with no evident flaw — but zero file anywhere combines this
telemetry with any ChatGPT/Codex handoff, and zero before/after comparison
exists. No percentage is asserted, per instruction.

## Structured handoff contract

A well-designed prose schema exists
(`L5DGVA/CODEX_L5_DGVA_Knowledge_Brain_Independent_Adversarial_Review_Prompt_v19.md`,
lines 112–135) covering nearly every field this audit was asked to check
for a review handoff (`Severity`, `Component`≈`AFFECTED_CAPABILITY`,
`ObservedEvidence`≈`EVIDENCE`, `RequiredRepair`≈`RECOMMENDED_ACTION`,
`Reproduction`, `ReviewerVerdict`≈`STATUS`) — but it has **never been
operationalized**: zero real `issue.md` instance exists anywhere, on
either tree. Full detail: `M4_5_STRUCTURED_HANDOFF_AUDIT.md`.

## Target vs. current state (explicitly distinguished, per instruction F)

```
TARGET_STATE (not implemented, a design only):
  Complex Goal -> ChatGPT (Planning) -> Structured Task Packet ->
  Claude CLI (Focused Implementation) -> Codex (Independent Review) ->
  Structured issue.md -> Claude CLI (Focused Correction) -> Harness
  Tests/Evidence

CURRENT_STATE (real, evidenced):
  A human-run staging script for one abandoned ChatGPT review round
  (Parent-only, stale) + three honest, self-blocking Codex
  package-assembly modules (Parent-only, not yet migrated to canonical) +
  real but disconnected Claude-only token telemetry. No automated routing
  of any of Claude's own work to another model exists anywhere.
```

## Model authority boundaries (per instruction I)

Not violated by anything found — because nothing found actually lets
ChatGPT or Codex output become a source of truth: every real code path
either requires human mediation or explicitly self-blocks rather than
fabricate a review verdict (`codex_full_contract_review_package.py`'s own
`BLOCKED_NO_EXTERNAL_REVIEWER` status is itself a model-authority-boundary
safeguard, not a bug).

## Article 0 evaluation

```
P2 EVIDENCE_GROUNDED = satisfied BY THE GAP ITSELF -- every one of the
  found modules refuses to fabricate a review verdict it cannot back with
  evidence (BLOCKED_NO_EXTERNAL_REVIEWER, codex_review_has_occurred=False,
  NOT_PROVEN_REQUIRES_CODEX_TOOL). This is Article 0 working correctly,
  not failing.
P3 KNOWLEDGE_DRIVEN = N/A for this specific capability (no knowledge
  retrieval decision is at stake; this is about task/context ROUTING,
  not knowledge retrieval)
P4 CONTINUOUS_EVOLUTION = NOT_PRESENT for this specific capability (no
  external-research-to-capability loop touches multi-model orchestration)
MINIMUM_SUFFICIENT_CONTEXT (supporting principle under P3) = the NEW
  dv_harness/governance_registry.py built earlier this M4.5 wave is a
  real, separate, working step toward this principle -- unrelated to the
  ChatGPT/Codex finding, not conflated with it.
```

`L5DGVA_CONSTITUTIONAL_COMPLIANCE` is **not** claimed PASS from this audit,
per instruction.

## Result

```
TOKEN_EFFICIENT_MULTI_MODEL_ORCHESTRATION = NOT_PRESENT
  (as a working automated mechanism; DOCUMENTED_ONLY / partially
   IMPLEMENTED for its individual building blocks -- see the capability
   matrix, M4_5_TOKEN_EFFICIENCY_CAPABILITY_MATRIX.csv, for the per-
   sub-capability breakdown)
CHATGPT_INTEGRATION = HUMAN_MEDIATED_CHATGPT_HANDOFF
CODEX_INTEGRATION = HUMAN_MEDIATED_CODEX_REVIEW
CHATGPT_OUTPUT_CONSUMED = NO
CODEX_OUTPUT_CONSUMED = NO
STRUCTURED_AGENT_HANDOFF = PARTIAL (schema designed, never operationalized)
TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL (dv_harness/governance_registry.py,
  built this same M4.5 wave -- a real, separate, working capability,
  unrelated to the ChatGPT/Codex finding)
MINIMUM_SUFFICIENT_CONTEXT = PARTIAL (enforced for the new governance
  registry's own reachability; not verifiable as a claim about Claude's
  broader task behavior in general)
TOKEN_USAGE_OBSERVABILITY = PARTIAL (real per-stage Claude-only telemetry;
  never combined with any multi-model handoff)
TOKEN_REDUCTION_MEASURED = NO
TOKEN_REDUCTION_EFFECT = ARCHITECTURALLY_PLAUSIBLE_BUT_NOT_MEASURED
CANONICAL_CAPABILITY_GAP = 5
  1. No automated ChatGPT-to-Claude handoff exists (human-mediated only)
  2. No automated Codex-to-Claude handoff exists (human-mediated only,
     and the honest self-blocking modules aren't even migrated to
     canonical yet)
  3. The real, well-designed issue.md schema has never been operationalized
     (zero real instances ever produced)
  4. No telemetry combines Claude's own token usage with any multi-model
     offload -- impossible to prove or disprove a reduction claim today
  5. The 3 real Codex-package-assembly modules found in Parent are not
     yet migrated to canonical (a real, disclosed migration gap, distinct
     from the operationalization gap above)
```

Not implemented during M4.5, per instruction. All 5 gaps assigned to a
future wave (see `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`'s new rows) --
none fixed here.
