# Master Remaining Work — L5DGVA Canonical Migration

Reconciled from accepted M-1–M4/M4.5 evidence only (per the master
reconciliation prompt's own instruction #2/#6 — no historical audit was
restarted; source was reopened only for the few concrete facts checked
directly this wave: repo identity, frozen-source SHAs, git log/status,
`constitution_gate.check_constitution_intact()`, and CSV row counts).

This is ANALYSIS/GOVERNANCE only. **No missing work was implemented as
part of producing this document.**

## What is COMPLETED

- M-1/M0/M0.5/M0.6: architecture decisions (incl. ClarificationService
  D2), protected-input capture, N-way merge policy — complete, frozen.
- M1/M1D: canonical >= v50 baseline — approved and frozen.
- M3: 5 leaf capabilities migrated (CAP-M3-001..005), Research/Experience
  capability-family audit complete, Article 0 installed.
- M4: schema/dependency/contract closure — `READY_FOR_APPROVAL`, closure
  regression clean (`REGRESSION_CAUSED_BY_M4=0`, `UNKNOWN=0`), 2 more
  capabilities migrated (CAP-M4-001/002), governing-contract-corpus
  finding disclosed, M5/M6 prerequisite matrices produced (8 and 2
  unresolved respectively).
- M4.5 (B)/(C) sub-scope: governance registry (`TASK_SCOPED_GOVERNANCE_RETRIEVAL`)
  built and now **OPERATIONAL** (upgraded from a merely-tested API once
  M4.6 made CLAUDE.md's own routing table its real, live consumer);
  ChatGPT/Codex/multi-model orchestration audited and confirmed
  `NOT_PRESENT` as a working loop; Constitution/Anti-Drift gate re-run
  clean (`PASS`, 0 reasons). **M4.5 (A) — the governing-contract-corpus
  decision — remains OPEN, P0, and is this reconciliation's own
  evidence-based `NEXT_RECOMMENDED_GATE`** (see `MASTER_PROGRAM_STATUS.md`).
- **M4.6 — CLAUDE Context Normalization: COMPLETE, APPROVED.** CLAUDE.md
  2,067,655 -> 113,125 bytes (94.53%), 22,461 -> 1,655 lines; 321 detailed
  sections relocated verbatim into 7 registered governance documents.
  A real regression (`REGRESSION_CAUSED_BY_M4_6 = 3` at checkpoint
  `030c4eb`) was found, root-caused (3 Research Front Door discoverability
  facts had moved out of `ALWAYS_ON` content), and fixed (`c877944`) —
  the fresh regression against the fix is byte-identical to the accepted
  M4 baseline (`REGRESSION_CAUSED_BY_M4_6 = 0`). New architectural lesson
  captured as `GLOBAL_DISCOVERABILITY_CONTRACT` (`CAP-M4.6-002`, `PARTIAL`
  — only the one caught instance is closed, no systematic re-audit of the
  other 300 `TASK_SCOPED` sections performed).

## What is PARTIAL

- `MINIMUM_SUFFICIENT_CONTEXT` — enforced only for the new governance
  registry's own reachability, not verifiable as a general claim.
- `L5DGVA_CONSTITUTION` compliance — installed/enforced structurally;
  `L5DGVA_CONSTITUTIONAL_COMPLIANCE` stays `NOT_YET_QUALIFIED` (final gate).
- `TOKEN_USAGE_OBSERVABILITY` — real Claude-only telemetry
  (`stage_profile.py`), never combined with a multi-model handoff.
- `STRUCTURED_AGENT_HANDOFF` — review-handoff schema real, never
  operationalized; task/planning-handoff schema not found at all.
- `CONTEXT_DISTILLATION` — real for DUT/VIP evidence content only.
- 5 M3-migrated capabilities (CAP-M3-00x, CAP-M4-002): `IMPLEMENTED,
  TESTED`, but `NOT_WIRED` into any live call site.
- `create_environment.py`/`functional_coverage_signoff.py`/
  `design_source_inventory.py` M5 foundation contracts: question named,
  not resolved.

## What is DOCUMENTED_ONLY

- The `issue.md` review-handoff schema (161-line prompt doc, part of the
  unmigrated 25-document corpus).
- `CODEX.md`/`CODEX_V50_TO_V1_MIGRATION.md` role-model documents (Parent).
- The Platform Architecture's 3-zone description (S19 of the prompt) has
  textual definition but no P1–P6 wave-content scoping artifact found.

## What is IMPLEMENTED BUT NOT OPERATIONAL

- `dv_harness/governance_registry.py` — real API, 10/10 tests, but no
  live task-routing consumer exists yet (reconciliation correction: the
  M4.5 audit's own table said `CONSUMED=YES`; this reconciliation applies
  the strict taxonomy uniformly and demotes that specific cell to
  `PARTIAL`, since only self-tested consumption exists, not a live
  routing decision — see `MASTER_CAPABILITY_STATUS_MATRIX.csv`
  CAP-M4.5-001 NOTES).
- 3 Codex package-assembly modules (Parent-only) — real, wired, tested on
  Parent, but not migrated to canonical at all.
- `ipxact_register_import.py` — real, tested, no generation call site.

## What is STILL MISSING

- The 25-document, 4.0 MB, 106,132-line governing-contract corpus (never
  migrated; a human decision on whether/how is still pending —
  `CAP-M4.5-004`, `P0`).
- `verification_level.py` / IP_MODE router support (`CAP-M5M6-VLEVEL-001`,
  `P0`) — the whole IP-level flow has no mode-selection foundation today.
- `ClarificationService` itself (architecture decided, nothing built yet —
  `CAP-M6-CLARSVC-001`, `P0`).
- Automated ChatGPT/Codex integration of any kind (`CAP-M4.5-005/006/007`).
- A unified `Experience` record type and the 3 named internal-loop stages
  (Clarification/Generation/Signoff experience learning) — confirmed
  absent on every tree, not merely unwired.
- `ExecutionService`/`RemoteEDABackend`/`TelnetSSHTransport` (TARGET
  execution architecture) — CURRENT `replay.ps1` path remains the real,
  working one.
- ~157 of the 177 `MIGRATE_REQUIRED_*` closure-membership items from
  `09_TRANSITIVE_DEPENDENCY_CLOSURE.md` remain individually untriaged
  (bulk-tracked, per M3's own disclosed scope limitation — not a new gap
  introduced by this reconciliation).

## Reconciliation-only finding (not present in any prior wave report)

M3's own audit assigned 5 pool items an owner wave of **M4**
(`l5dgva_requirement_dependency_closure.py`, `engine_maturity_state.py`,
`l5dgva_ss570_claude_verdict_truth.py`,
`l5dgva_directive_blackboard_work_queue.py` [M4 half],
`l5dgva_kc_extraction.py`). Cross-checking `M4_FINAL_REPORT.md`'s own
`FOUNDATION_ITEMS_REVIEWED = 18` (= 10 M5 targets + 7 M6 targets + 1
M3→M4 deferred item) shows only **1 of those 5** was actually reviewed
(`l5dgva_requirement_dependency_closure.py`, investigated and redeferred
to `M4.5_GOVERNING_CONTRACT_AUTHORITY`). The other 4 were never picked up
by M4, which is now closed. **Reassigned** in
`MASTER_WAVE_OWNERSHIP_MATRIX.csv` to M5 (3 items) and M8 (1 item, the
Codex-family one) — see `CAP-POOL-001..004`. This is disclosed as a real
reconciliation finding per instruction #26, not silently corrected without
a record.

## Ordered remaining-wave sequence (see `MASTER_PROGRAM_STATUS.md` for the
authoritative statement)

`M4.5 (governing-contract-corpus decision) → M5 (N-way semantic merge) →
M6 (core dispatch + ClarificationService + VerificationLevel) → M7
(consumer wiring for M3/M4-migrated leaves) → M8 (continuous-evolution
loop closure, multi-model orchestration, Constitution compliance
qualification, Knowledge-Brain multi-agent-consumption audit) → M9
(ExecutionService TARGET) → M10 → M11 (Reference USB consumption) → M12 →
M13 (final strict-superset gate)`, with `PLATFORM_P1` (scope definition)
running in parallel to M5+ once started.
