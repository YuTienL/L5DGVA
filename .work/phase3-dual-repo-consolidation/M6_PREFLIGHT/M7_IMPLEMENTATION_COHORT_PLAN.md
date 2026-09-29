# M7 Preflight -- Implementation Cohort Plan

Dependency-ordered, derived from the real gaps `M7_EXISTING_CAPABILITY_
AUDIT.md`/`M7_OUTPUT_CONSUMPTION_ARCHITECTURE.md` found -- not blindly
accepting the dispatch's own suggested 6-cohort decomposition (section
20's own "a likely decomposition to evaluate, not blindly accept").

## Evaluating the suggested decomposition against real evidence

The dispatch's own suggested order (Structured Handoff -> Codex
consumption -> ChatGPT consumption -> Model Task Router -> Token
observability -> E2E qualification) is directionally sound but has one
real ordering problem: `M7_OUTPUT_CONSUMPTION_ARCHITECTURE.md` found
Codex's own real gap is 0/4 across PRODUCED/PARSED/VALIDATED/CONSUMED --
starting cohort work at "Codex automated review CONSUMPTION" presumes a
real Codex OUTPUT already exists to consume, which it does not (neither
in canonical nor, completely, in Parent). The dependency-correct order
puts the STRUCTURED HANDOFF + a real, minimal PRODUCE/PARSE step before
any CONSUMPTION cohort can be meaningfully scoped.

## Revised cohort plan

### Cohort 1: Structured Handoff + Result Contract (foundation, no model
integration yet)

Builds the 2 real net-new fields `M7_STRUCTURED_HANDOFF_CONTRACT.md`
identified (`EXPECTED_OUTPUT_TYPE`, `EXPECTED_OUTPUT_SCHEMA`'s own
per-type definitions), wiring them onto the ALREADY-REAL fields
(`TaskBoundary`, `evidence_refs`, `governance_registry.py`,
`AgentResult`'s own status vocabulary) rather than inventing a parallel
contract. Produces ONE real Python module (a `ModelHandoff`
dataclass, mirroring `RoutingDecision`'s own `to_dict()` pattern from
`model_agent_tool_router.py`) with tests. No Codex/ChatGPT call yet --
this cohort is pure contract/schema work.

**Depends on**: nothing new (every reused field is already real).
**Blocks**: every other cohort (the handoff shape is the common
currency all of them use).

### Cohort 2: Minimal Codex PRODUCE/PARSE round-trip

The real, missing 0/4. Builds the smallest possible real Codex
invocation + a real parser for its output into Cohort 1's own result
schema, validated via the SAME `ValidationState` pattern
`intake_field_resolution.py` already proves. Deliberately narrow scope:
proving PRODUCED->PARSED->VALIDATED works at all, before touching
CONSUMPTION.

**Depends on**: Cohort 1 (the schema to parse into).
**Human decision required first**: whether/how a real Codex
CLI/API credential and invocation mechanism is authorized for this
project (a real infrastructure/access decision, not a code design
question this PREFLIGHT can resolve on its own).

### Cohort 3: Codex output CONSUMPTION

Wires Cohort 2's own validated output into a REAL Canonical consumer --
per `M6_OUTPUT_CONSUMPTION_ARCHITECTURE.md`'s own bar, "a real Canonical
consumer that changes behavior/state," e.g. filing a real
`clarification_service`-owned question when Codex's finding needs a
human decision, or blocking a stage the same way `Task Boundary`
blocks. This is where `MODEL_OUTPUT_CONSUMED` first becomes real for any
non-Claude model.

**Depends on**: Cohort 2.

### Cohort 4: ChatGPT structured handoff / consumption

Same shape as Cohorts 2-3, applied to ChatGPT -- reusing Cohort 1's own
schema. Genuinely independent of Codex's own cohort sequence (could run
in parallel with Cohorts 2-3 once Cohort 1 exists), since ChatGPT and
Codex are separate providers with no real interdependency found in this
audit.

**Depends on**: Cohort 1 only (not Cohorts 2-3).
**Human decision required first**: same class of access-authorization
question as Cohort 2, for ChatGPT specifically.

### Cohort 5: Model Task Router (cross-provider)

Extends `model_agent_tool_router.py`'s own real, proven STRUCTURE
(fallback chains, worst-wins verdict, `routing_criteria()`) to the
cross-provider dimension (Claude vs. Codex vs. ChatGPT) it was never
built to answer -- per `M7_EXISTING_CAPABILITY_AUDIT.md`'s own finding,
this is genuine `IMPLEMENTATION_MISSING`, not `FOUNDATION_AVAILABLE`.
Routes on task properties (type/risk/context/locality/independent-
review-need/output-contract/cost/latency/human-interaction/evidence-
sensitivity), never on model name alone, per this task's own section 6.

**Depends on**: Cohorts 1-4 (needs at least one real, consumed
integration on each side to route TO).

### Cohort 6: Token/context observability and optimization

Builds the real baseline `M7_TOKEN_EFFICIENCY_BASELINE_REQUIREMENTS.md`
defines, using ONLY real/proxy metrics (never invented token counts),
against a frozen candidate -- the SAME freeze discipline this
qualification task itself used.

**Depends on**: Cohorts 1-5 (there is nothing cross-model to measure
before they exist).

### Cohort 7: End-to-end multi-model qualification

A qualification pass in the SAME shape `M6-FINAL-OPERATIONAL-SLICE-
QUALIFICATION` just performed -- a 10-plus-N-stage matrix, real
cross-run confirmation, real regression evidence -- applied to the
extended (multi-model) Golden Workflow. Only meaningful once Cohorts 1-6
are real.

**Depends on**: Cohorts 1-6.

## Dependency graph (text form)

```
Cohort 1 (Structured Handoff)
   |
   +--> Cohort 2 (Codex PRODUCE/PARSE) --> Cohort 3 (Codex CONSUME)
   |                                              |
   +--> Cohort 4 (ChatGPT handoff/consumption)    |
   |            |                                 |
   +------------+---------------------------------+
                          |
                    Cohort 5 (Model Task Router)
                          |
                    Cohort 6 (Token observability)
                          |
                    Cohort 7 (E2E multi-model qualification)
```

## Human decisions required before implementation can start (section 18's
own `HUMAN_DECISION_REQUIRED` classification, consolidated)

1. Codex CLI/API access authorization (blocks Cohort 2).
2. ChatGPT API access authorization (blocks Cohort 4) -- note: the prior
   ChatGPT usage found was UI-paste, human-mediated; a real API
   integration is a DIFFERENT, larger decision than continuing the
   manual-paste pattern.
3. The `CAP-M3-002/003/004/005`/`CAP-M14-004` Master-matrix
   `PRIMARY_OWNER_WAVE` mis-tag (`M7_EXISTING_CAPABILITY_AUDIT.md`) --
   unrelated to multi-model orchestration, flagged for correction, not
   an M7 cohort dependency.

```
M7_COHORTS_DEFINED = 7
```

Per this task's own explicit instruction: no cohort here is implemented.
This is the plan only.
