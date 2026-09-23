# Native Claude Fast Maintenance Architecture

ROADMAP requirements only. No production code implements this document.
Does not implement Native Claude Fast Maintenance. Does not start
M10.5.

## What this is (and is not)

Native Claude CLI Fast Maintenance is a **lightweight interaction/
execution path** for bounded maintenance work, running Claude Code (this
very tool) directly inside a generated DV project directory. It is:

```
IS:  a second EXECUTION MODE of the one MAINTAIN_LIFECYCLE
IS NOT: a second product
IS NOT: a second authority model (VERIFICATION_ENVIRONMENT_AUTHORITY
        stays DV, whichever mode executes the work)
IS NOT: a second Knowledge Brain
IS NOT: a second verification engine
```

## Real entry point (Section 11)

```
cd <verification-environment>
claude
```

and/or a future `l5dgva attach` command (exact CLI syntax not frozen
here, per this task's own Section 33 instruction -- existing CLI
governance decides the real form). Native Claude must discover
project-local L5DGVA identity/bootstrap itself and must not require
launch from the Canonical source repo -- this is the SAME
`LOCATION_INDEPENDENT` (Article 0 P1) discipline every other Canonical
mechanism already follows (`l5dgva_repo.py`, `execution_profile.py`,
`root_hygiene_gate.py`).

## Project bootstrap / identity / rehydration (Section 12)

A compact project-local bootstrap file tells Claude "this directory is
L5DGVA-managed" and points at:

```
identity / manifest / ownership / snapshot references
```

Rehydration reconstructs current context from identity, manifests,
ownership, provenance, snapshot, and RTL/spec/OpenSpec/vPlan/files/
evidence. **Rehydration is not regeneration** -- it reads and
reconstructs understanding, it never regenerates artifacts as a side
effect of being asked to understand them (the same "discovery, not
generation" discipline `reference_uvm_dut_top_integration_manifest.py`'s
own docstring already states for its own fact-extraction: "THIS MODULE
DOES NOT CHANGE GENERATION BEHAVIOR").

Bootstrap metadata (see `PROJECT_ATTACH_REHYDRATION_REQUIREMENTS.md` for
the full field list): `PROJECT_ID`, `VERIFICATION_LEVEL`, `PROTOCOLS`,
`GENERATION_ID`, `SCHEMA_VERSION`, `PROJECT_ROOT`, `MANIFEST_REF`,
`OWNERSHIP_REF`, `LAST_QUALIFIED_SNAPSHOT_REF`, `CREATION_PROVENANCE`,
`CURRENT_LIFECYCLE_STATE`. **No credentials. No absolute bootstrap
paths.** The full Canonical `CLAUDE.md` is never copied into each
project -- this mirrors the existing `context_budget.py` 3-tier
discipline (Tier 1 "never into context") applied to a NEW context: a
generated project's own directory, not just this session's own context
window.

## Fast Path eligibility (Section 8) -- gate, not a formula this wave defines

`FAST_PATH_ELIGIBILITY` requires ALL of:

```
valid project identity/rehydration
known ownership (of every artifact the change would touch)
bounded scope
no unresolved design-intent issue
no unauthorized protected-artifact edit
no broad topology/architecture change
adequate confidence
available focused validation
definable rollback
understood signoff impact
```

**Thresholds belong to policy/config**, not this document -- exactly
like `dv_harness/context_budget.policy.json` externalizes its own
thresholds rather than hard-coding them in prose, and
`environment_mode_policy.json` externalizes `SUBSYSTEM_MODE`/
`SYSTEM_LEVEL_MODE` thresholds the same way. See
`FAST_PATH_ELIGIBILITY_AND_ESCALATION.md` for the full eligibility/
escalation contract.

## Debug / failure evidence (Section 16)

```
DV -> project -> claude -> rehydrate -> inspect log/FSDB/coverage/
regression -> hypotheses -> evidence/refutation -> root cause -> bounded
proposed change -> focused validation
```

This is the SAME `Hypothesis -> Evidence -> Confidence -> Validation ->
Action` discipline Article 0's own P2 `EVIDENCE_GROUNDED` dimension and
the Engineering Memory Policy already require -- Fast Path does not
relax it, it runs it with less orchestration overhead (per
`MINIMUM_SUFFICIENT_EXECUTION`, Section 20 of this task).

`RCA must not directly mutate qualified files` -- RCA produces a Root
Cause / Confidence / Authority classification, which becomes a Change
Request (`RCA_TO_CHANGE_REQUEST`, `CAP-VELM-029`), never a direct edit.

## Fast Path never bypasses governance (frozen validation requirement)

```
FAST_PATH_BYPASSES_ARTIFACT_OWNERSHIP = NO
FAST_PATH_BYPASSES_EVIDENCE           = NO
FAST_PATH_BYPASSES_SIGNOFF            = NO
```

This is the whole point of Section 5's own frozen principle -- "Fast and
Full L5DGVA share project identity, evidence, ownership, provenance,
change, validation and signoff contracts." A Fast Path change record and
a Full L5DGVA change record must be structurally compatible, so a change
started in one mode can escalate to (or later be reviewed by) the other
without translation loss.

## Execution / location / security (Section 28)

Fast Path may invoke approved focused local/remote execution; Full mode
uses the target `ExecutionService`. No hard-coded hosts. A moved/copied
project remains attachable after config resolution -- no runtime
dependency on Canonical/Parent/v50 paths, usernames, or hosts (same
`LOCATION_INDEPENDENT` requirement as everywhere else in this
architecture).

Future controlled-modification acceptance criteria (not built this
wave): path validation, project-boundary enforcement, symlink/path-
traversal handling where relevant, atomic writes, partial-write
recovery, backup/rollback, secret exclusion, overwrite protection.

## Auditability (Section 29)

Every change, in either mode, records: execution mode (`FAST`/`FULL`),
proposer, evidence, authority, affected artifacts, before/after
identity, tests, coverage impact, invalidation, approval, apply result,
rollback, and the resulting snapshot. One audit record shape for both
modes -- not two.

## Validation

```
NATIVE_CLAUDE_FAST_MAINTENANCE = ROADMAP_DEFINED
MINIMUM_SUFFICIENT_EXECUTION   = DEFINED
FAST_PATH_ELIGIBILITY          = DEFINED
FAST_PATH_ESCALATION           = DEFINED (see FAST_PATH_ELIGIBILITY_AND_ESCALATION.md)
FAST_TO_FULL_CONTEXT_HANDOFF   = DEFINED (see FAST_TO_FULL_CONTEXT_HANDOFF_CONTRACT.md)
FAST_AND_FULL_SHARE_GOVERNANCE = YES
PROJECT_LOCATION_INDEPENDENT   = REQUIRED
PRODUCTION_IMPLEMENTATION_STARTED = NO
```
