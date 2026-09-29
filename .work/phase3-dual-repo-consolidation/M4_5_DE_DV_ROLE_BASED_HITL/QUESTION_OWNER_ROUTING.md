# Question Owner Contract (Section 8)

Not implemented this wave — a future extension to `ClarificationService`
(M6), which itself preserves the frozen M-1 D2 decision (one Canonical
service over `question_queue.py` + `intake_clarification.py`, never
reopened as a pick-one choice).

## Schema

```
QUESTION_OWNER          -- DESIGN | VERIFICATION | SHARED
QUESTION_TYPE           -- e.g. discovery-gap, contradiction, architecture-
                           choice, waiver, risk-acceptance
QUESTION_REASON         -- why this specific question is being asked
EVIDENCE_ALREADY_CHECKED -- what evidence was searched before asking
                           (Evidence-Before-Human-Question, per Article 0)
CONFIDENCE              -- current confidence in any candidate answer
TARGET_HUMAN_ROLE        -- who this question is routed to
ANSWER                  -- the human's answer
ANSWER_EVIDENCE          -- evidence the human cited, if any
RESOLUTION_STATE        -- OPEN | ANSWERED | SUPERSEDED
QUESTION_AVOIDABLE      -- whether later evidence proved this question
                           didn't need to be asked (feeds Clarification
                           Learning, M8)
```

## Flow (Section 8)

```
Clarification Candidate -> Auto-Discovery/Evidence Search -> unresolved?
  -> classify -> DESIGN/VERIFICATION/SHARED -> route to DE/DV/DE+DV
```

Blank data alone is never sufficient justification to ask a human if
authoritative evidence can discover it — this reuses the existing
`Evidence-Before-Human-Question` gate
(`l5dgva_evidence_before_human_question.py`'s `EVIDENCE_PRIORITY_ORDER`
exhaustion check) rather than defining a second evidence-exhaustion rule.

## Relationship to Clarification Learning (Section 10, owned by M8)

```
Question -> QUESTION_OWNER -> DE/DV answer -> later evidence proves
  auto-discoverable -> QUESTION_AVOIDABLE=true -> Experience Candidate
  -> discovery improvement -> future interruption avoided
```

M6 owns the routing mechanics (this document); M8 owns the
learning/promotion step. Never authorize guessing as a substitute for
either — an unresolved question stays `OPEN`, it is never silently
answered by the harness itself.

**Not implemented during this task**, per Section 8's own instruction.
