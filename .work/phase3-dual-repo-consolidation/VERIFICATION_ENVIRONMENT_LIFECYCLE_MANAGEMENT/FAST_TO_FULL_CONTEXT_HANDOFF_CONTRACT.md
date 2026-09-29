# Fast-to-Full Context Handoff Contract

ROADMAP requirements only. No production code implements this document.

## Purpose

When a Fast Path session escalates (see
`FAST_PATH_ELIGIBILITY_AND_ESCALATION.md`), the Full L5DGVA session that
picks up the work must not restart from zero. This document defines the
record shape that carries context across that boundary.

## Real existing precedent (not invented from nothing)

`dv_harness/agent_checkpoint_check.py` already closes an analogous gap
for a DIFFERENT scope: a dispatched sub-agent working an arbitrary
external tree, resumed across sessions or AI providers (the Agent Task
Lifecycle wave's own `TASK_IDENTITY` analysis, `CAP-ATL-002`, names this
as one of 3 composable identity primitives, "Gap #4" in its own origin
story). `FAST_TO_FULL_CONTEXT_HANDOFF` is a real, DIFFERENT scope
(Fast-Path-session-to-Full-L5DGVA-session, not dispatched-subagent-to-
resumed-subagent) but the SAME shape of problem, and should reuse
`agent_checkpoint_check.py`'s resume-artifact CONVENTION rather than
inventing an unrelated one -- this is disclosed as the real precedent to
build from, not a claim that the mechanism already exists for this
scope.

## Required fields (`FAST_TO_FULL_CONTEXT_HANDOFF`, `CAP-VELM-023`)

```
PROJECT_ID
CHANGE_ID / FAILURE_ID
intent
affected artifacts
ownership (per affected artifact)
evidence refs
hypotheses / refutations
confidence
proposed changes
validation already run
remaining failures
rollback state
authority decisions (already made, if any)
```

Every field here is either a direct carry-over from `FAILURE_EVIDENCE_
COLLECTION` (`CAP-VELM-028`)/`RCA_TO_CHANGE_REQUEST` (`CAP-VELM-029`)'s
own real records (once those exist), or the escalation trigger itself
(from `FAST_PATH_ELIGIBILITY_AND_ESCALATION.md`) -- this contract does
not ask Fast Path to produce anything it would not already need to
produce for its own internal bookkeeping.

## What "preserving session evidence" concretely means

The Full L5DGVA session that receives this handoff must be able to
answer, without re-deriving from scratch: what was being investigated,
what evidence already exists, what has already been ruled out
(refutations), what confidence level was reached, and what was already
validated. A handoff record that omits any of these forces the Full
session to redo work the Fast session already did -- exactly the
"restart from zero" this contract exists to prevent.

## Validation

```
FAST_TO_FULL_CONTEXT_HANDOFF = DEFINED
```
