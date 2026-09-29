# Generic HumanGate Contract (Section 7)

Not implemented this wave — a future schema/mechanism definition for
`ClarificationService` (M6) to consume.

## Schema

```
GATE_ID              -- stable identifier
PROJECT_ID            -- which project this gate belongs to
VERIFICATION_LEVEL     -- IP | SUBSYSTEM | SYSTEM_LEVEL
WORKFLOW_STAGE          -- one of the 17 stages (DE_DV_E2E_ROLE_MATRIX.csv)
DECISION_TYPE          -- e.g. CLARIFICATION | ARCHITECTURE_DECISION |
                          WAIVER | RISK_ACCEPTANCE | SIGNOFF
AUTHORITY_ROLE         -- DESIGN | VERIFICATION | SHARED
REQUESTED_BY           -- which engine/module/agent raised the gate
EVIDENCE_REFS          -- citations to real evidence already gathered
CONFIDENCE             -- current confidence level (reuses
                          inference.score_confidence() vocabulary where applicable)
QUESTION_OR_DECISION   -- the actual question or decision needed
OPTIONS                -- candidate answers/decisions, if enumerable
RECOMMENDATION         -- the harness's own recommendation, never presented
                          as a decision already made
HUMAN_DECISION         -- the human's actual answer/decision
DECISION_RATIONALE     -- why the human decided this way
RESOLUTION_STATE       -- OPEN | ANSWERED | SUPERSEDED | STALE
PROVENANCE             -- who/what recorded this gate and when
```

## When a gate may fire (Section 7)

Only when justified by: insufficient evidence, low confidence,
contradiction, a genuine design/verification intent question, an
architecture decision, a waiver, a risk acceptance, a signoff, or a
governance policy requirement. **Not** merely because a human role
exists for a stage (`DE_DV_AUTHORITY_MATRIX.csv`'s `PRIMARY_AUTHORITY`
column is not itself a gate trigger).

## Target metric

`MINIMUM_NECESSARY_HUMAN_INTERRUPTION`, coexisting with
`AUTO_DISCOVERY_FIRST` and `MINIMAL_STRUCTURED_CLARIFICATION` — the same
automation-first principle already governing `question_queue.py`'s
existing `Do-Not-Ask Enforcement` mechanism (canonical
`docs/architecture/canonical_detailed_governance/EXECUTION_REMOTE_REGRESSION_RCA.md`).

## Relationship to existing mechanisms (reuse, not redesign)

`HumanGate` is a **generalization** of the existing Tier-3 question
mechanism (`question_queue.HUMAN_DECISION_SOURCE`, already used by
`waveform_dump_gate.py` and others) — it adds `AUTHORITY_ROLE` as new
routing metadata, it does not replace the underlying escalation
mechanism. Building this is real M6 work (`HUMAN_GATE_CONTRACT` capability
row); nothing here is implemented by this reconciliation.
