# Master End-to-End DV Status — IP / SUBSYSTEM / SYSTEM_LEVEL (v2, post-M4.6)

Per reconciliation instruction section F: 17 named stages, evaluated
separately per verification level, with the exact first non-operational
stage and its owner wave identified for each. Reused evidence only
(M4/M4.5/M4.6 artifacts, `environment_mode_router.py`,
`intake_routing.py`); no new source audit performed. Where no accepted
artifact independently covers a stage at this granularity, it is marked
`NOT_RE-AUDITED_THIS_WAVE` rather than guessed.

## IP_MODE

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | **BLOCKED (first non-operational stage)** | `environment_mode_router.py` has no `IP_MODE` concept at all; there is no entry point to reach IP-level intake in the first place |
| 2–17 | Knowledge Retrieval … Experience Consolidation | BLOCKED (downstream of #1) | Every later stage is unreachable while #1 has no router entry point |

```
IP_MODE_FIRST_NON_OPERATIONAL_STAGE = "1. OpenSpec Intake" (mode-selection foundation itself)
IP_MODE_OWNER_WAVE = M6 (CAP-M5M6-VLEVEL-001 -- verification_level.py / IP_MODE genericity foundation)
```

## SUBSYSTEM_MODE

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | WIRED | `intake_routing.py` + `environment_mode_router.py` real dispatch confirmed |
| 2 | Knowledge Retrieval | NOT_RE-AUDITED_THIS_WAVE | |
| 3 | Discovery | NOT_RE-AUDITED_THIS_WAVE | |
| 4 | Clarification | **BLOCKED (first non-operational stage)** | `ClarificationService` not yet built (architecture decided, D2; feature work not started — CAP-M6-CLARSVC-001) |
| 5 | vPlan | PARTIAL (downstream of #4, but `VPLAN_COVERAGE_TRACEABILITY_FOUNDATION = READY` per M4) | |
| 6 | VIP/UVM Generation | WIRED, 1 latent defect | `create_environment.py` -> `ProtocolEnvGenerator`; `KNOWN_SOURCE_B_DEFECT` re-confirmed unchanged (CAP-M5-ARCH-001) |
| 7–17 | Sequence/Scenario/FW … Experience Consolidation | NOT_RE-AUDITED_THIS_WAVE except where already tracked (Coverage Closure PARTIAL per CAP-M5-COV-001; Experience Consolidation ABSENT per CAP-CE-014) | |

```
SUBSYSTEM_MODE_FIRST_NON_OPERATIONAL_STAGE = "4. Clarification"
SUBSYSTEM_MODE_OWNER_WAVE = M6 (CAP-M6-CLARSVC-001)
```

## SYSTEM_LEVEL_MODE

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | WIRED | same router dispatch as SUBSYSTEM_MODE |
| 2 | Knowledge Retrieval | NOT_RE-AUDITED_THIS_WAVE | |
| 3 | Discovery | NOT_RE-AUDITED_THIS_WAVE | |
| 4 | Clarification | **BLOCKED (first non-operational stage)** | same `ClarificationService` gap as SUBSYSTEM_MODE |
| 5 | vPlan | PARTIAL | |
| 6 | VIP/UVM Generation | WIRED, 1 unresolved foundation contract | `compose_soc_environment()` real registered-subsystem-registry check + cross-subsystem pre-check; `soc_environment_composer.py`'s ARCH-03 contract UNRESOLVED (CAP-M5-ARCH-002) |
| 7 | Sequence/Scenario/FW | PARTIAL, disclosed scope boundary | cross-subsystem behavioral scenario content is explicitly `NotImplementedError` by design (No Golden-Reference Content Mining rule), not a defect |
| 8 | Checker/Scoreboard/Assertion | PARTIAL, same disclosed boundary | |
| 9–17 | Execution … Experience Consolidation | NOT_RE-AUDITED_THIS_WAVE except where already tracked (Coverage Closure PARTIAL; Experience Consolidation ABSENT) | |

```
SYSTEM_LEVEL_MODE_FIRST_NON_OPERATIONAL_STAGE = "4. Clarification"
SYSTEM_LEVEL_MODE_OWNER_WAVE = M6 (CAP-M6-CLARSVC-001)
```

## Cross-level reading

`IP_MODE` is blocked at the very first stage (no router entry point at
all) — a strictly earlier and more severe gap than `SUBSYSTEM_MODE`/
`SYSTEM_LEVEL_MODE`, both of which reach real intake dispatch before
hitting the shared `ClarificationService` gap at stage 4. **Closing
`CAP-M5M6-VLEVEL-001` (owner M6) unblocks IP_MODE's stage 1;
closing `CAP-M6-CLARSVC-001` (owner M6) unblocks stage 4 for all three
levels.** Both are M6-owned, not M5 — reinforcing that M5's own N-way
merge scope (env_manifest.py, vip_capability_extraction.py, etc.) is
not what stands between today's state and a further-operational E2E
flow at any level; M6's core-dispatch/ClarificationService/
VerificationLevel work is the more load-bearing near-term blocker.

No stage at any level is claimed `OPERATIONAL` end-to-end — consistent
with `CANONICAL_CAPABILITY_STRICT_SUPERSET = NOT_YET_QUALIFIED`.

## DE/DV Role-Based HITL overlay (added by the DE/DV roadmap reconciliation)

The 17-stage table above is extended with per-stage
`AUTOMATION_OWNER`/`HUMAN_ROLE`/`HUMAN_GATE_REQUIRED`/`QUESTION_OWNER`
columns in
`.work/phase3-dual-repo-consolidation/M4_5_DE_DV_ROLE_BASED_HITL/DE_DV_E2E_ROLE_MATRIX.csv`
(51 rows = 17 stages × 3 levels) — a genuinely one, generic role model
applied identically across `IP_MODE`/`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`,
per the frozen architecture decision "DE and DV are not separate
pipelines; they are human authority roles participating in the same
end-to-end lifecycle" (`DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md`). Only 3
of the 17 stages (`Clarification`, `Waiver`, `Signoff`) carry
`HUMAN_GATE_REQUIRED=YES` — role presence at a stage never implies a
mandatory gate.

This overlay does **not** change any `CURRENT_STATUS`/`BLOCKER`/
`PRIMARY_OWNER_WAVE` value in the table above — it is a role/authority
classification layered on top of the same evidence, not a re-audit. The
`Clarification` stage's existing blocker (`CAP-M6-CLARSVC-001`) is now
additionally the stage where `ROLE_BASED_HUMAN_IN_THE_LOOP`,
`QUESTION_OWNER_ROUTING`, and `HUMAN_GATE_CONTRACT` (all owner M6, all
new capability rows from this reconciliation) converge — reinforcing,
not changing, M6's status as the load-bearing near-term wave.
