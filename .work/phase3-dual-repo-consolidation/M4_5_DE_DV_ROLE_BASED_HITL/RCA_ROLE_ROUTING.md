# RCA Human Role Routing (Section 11)

Not implemented this wave — a future extension of the existing RCA
evidence-gathering fan-out (`analysis_debug`, `rtl-evidence-agent`,
`log-evidence-agent`, `vip-spec-evidence-agent` and the root-cause
classification modules already real in this program).

## Routing table

| Root-cause classification | Authority role | Notes |
|---|---|---|
| RTL/DESIGN_BEHAVIOR | DESIGN / DE | Register semantics, reset/IRQ/clock intent, undocumented behavior |
| SPEC_INTENT_AMBIGUITY | SHARED, where appropriate | Only when the ambiguity genuinely spans design intent and verification interpretation — never a default bucket for an unclear root cause |
| TB/TEST/SEQUENCE/CONSTRAINT | VERIFICATION / DV | |
| CHECKER/SCOREBOARD/ASSERTION | VERIFICATION / DV | |
| VIP_CONFIGURATION | VERIFICATION / DV | |
| COVERAGE_MODEL | VERIFICATION / DV | |
| EDA/LSF/TOOL/ENVIRONMENT | Automatic handling first, then appropriate escalation | Not a DE/DV authority question at all until automatic remediation (bounded retry, preflight-resource-guard-agent) is exhausted |

## Reuse, not redesign

This routing table is a thin classification layer over
**already-real** mechanisms — it introduces no new RCA engine:

- Root-cause taxonomy itself: `root_cause_ontology.py` /
  `failure_signature_normalization.py` (existing).
- Evidence gathering: the existing `analysis_debug` /
  `rtl-evidence-agent` / `log-evidence-agent` /
  `vip-spec-evidence-agent` fan-out (existing).
- Next-best-evidence arbitration: `inference.arbitrate_next_best_evidence()`
  (existing, real).
- Escalation itself: the (target) `HumanGate`/`ClarificationService`
  mechanism — this document only supplies the `AUTHORITY_ROLE`
  classification a `HumanGate` record would carry when an RCA
  escalation is genuinely warranted.

## Not implemented during this task

No code path currently reads this table. Building the actual
classification-to-role dispatcher is real M6 work
(`RCA_ROLE_ROUTING` capability row).
