# DE/DV Role-Based HITL — Roadmap Impact

## M7 — AI roles are orthogonal to human roles (Section 21)

```
Human roles:  DE, DV
AI/model roles: ChatGPT, Claude CLI, Codex, L5DGVA Agents
```

M7 owns `CHATGPT_PLANNING_OFFLOAD`, `CLAUDE_FOCUSED_IMPLEMENTATION`,
`CODEX_REVIEW_OFFLOAD`, `STRUCTURED_AGENT_HANDOFF`,
`CONTEXT_DISTILLATION`, `SESSION_RESUME`, `TOKEN_USAGE_OBSERVABILITY`
(already tracked as `CAP-M4.5-005..013`, owner M7, from the prior
reconciliation — unchanged by this task). M6/M8/M9/M10 own DE/DV
behavior. **ChatGPT is never modeled as DE. Codex is never modeled as
DV.** These are two orthogonal role axes (human authority vs. AI/model
function), never conflated.

## Dashboard / UX (Section 22)

Future dashboard routing concept only, not built:

```
DESIGN ACTION REQUIRED -> DE
VERIFICATION ACTION REQUIRED -> DV
SHARED ACTION REQUIRED -> DE+DV
```

The primary UI surface is project status/evidence/blockers/human
decisions — never Agent/Skill internals. No existing dedicated UI/
productization owner capability was found in
`MASTER_CAPABILITY_STATUS_MATRIX.csv` prior to this reconciliation, so
`ROLE_BASED_ACTION_DASHBOARD` is assigned to **M12** (Canonical
Cutover/Productization), per Section 22's own fallback rule. Not
implemented this wave.

## Automation principle (Section 23)

Role routing must never reduce automation. Default:
`AUTO_DISCOVERY_FIRST`. Human interaction fires only when evidence,
confidence, or governance genuinely requires it — target
`MINIMUM_NECESSARY_HUMAN_INTERRUPTION`, not approval at every stage.
This is why `DE_DV_E2E_ROLE_MATRIX.csv` sets `HUMAN_GATE_REQUIRED=NO`
for 14 of the 17 stages even though a human role is present at most of
them (`Clarification`, `Waiver`, and `Signoff` are the only 3 stages
marked `YES`) — role presence never implies a mandatory gate (Section
12's own closing line).

## Global discoverability / M4.6 (Section 27)

```
Determination: NO GLOBAL_DISCOVERABILITY_CONTRACT needed for this
  architecture at this wave.
```

Reasoning: unlike M4.6's own Research Front Door finding (a
discoverability gap a real regression caught), nothing in this
DE/DV role architecture is itself an `ALWAYS_ON`-required fact today —
it is entirely forward-looking roadmap/schema content with zero
production code consuming it yet. When M6 actually builds
`ClarificationService`/`HumanGate`/`QuestionOwner` routing, **that**
wave should re-evaluate whether a compact routing fact belongs in
`CLAUDE.md`'s `ALWAYS_ON` core (the same question M4.6 asked of its own
Research Front Door) — this reconciliation does not pre-empt that
future decision, and does not add anything to `CLAUDE.md`.

```
TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL (unchanged, re-verified)
M4.6 qualified context behavior = PRESERVED (unchanged, re-verified)
GOVERNANCE_DUMP = PROHIBITED (unchanged; nothing added to CLAUDE.md)
```

## Roadmap update (Section 28)

```
M5  -- N-Way Capability Semantic Merge; no duplicated DE/DV engines
        (unchanged scope; this reconciliation adds a constraint, not new
        M5 work items)
M6  -- Core Semantic Merge + VerificationLevel + ClarificationService +
        Role-Based HITL + Question Owner Routing + HumanGate Contract +
        RCA Role Routing
M7  -- ChatGPT/Claude/Codex operationalization + Structured Handoff +
        Context Distillation + Token Observability
M8  -- Knowledge Brain + Continuous Research Evolution + Continuous
        Project Experience Learning + Role-Aware Experience Learning +
        DESIGN/VERIFICATION/SHARED Knowledge Domain Classification
M9  -- Generic IP/Subsystem/System-Level qualification + same DE/DV
        role model across all three levels (no per-level role variants)
M10 -- vPlan -> Coverage Closure -> Traceability -> Waiver -> Signoff +
        role-aware signoff evidence
M11 -- USB Golden Qualification
M12 -- Canonical Cutover/Productization + Role-Based Action Dashboard
        (if no other owner is confirmed by then)
M13 -- PCIe Zero-Core-Change + Strict Superset + Constitutional
        Compliance
```

## NEXT_RECOMMENDED_GATE — preserved, not changed

```
NEXT_RECOMMENDED_GATE = M5_N_WAY_CAPABILITY_SEMANTIC_MERGE (unchanged)
```

**Why this reconciliation does not change it**: the current gate was
last recomputed (not assumed) in the M4.5 Governing Contract Authority
closure, on the evidence that (a) `CAP-M4.5-004` — the one P0 item whose
owner wave was M4.5 itself — is now closed, and (b) no remaining P0
blocker is M4.5-owned. This DE/DV role-based HITL reconciliation adds
**zero new P0 items** (all 12 new capability rows are P1/P2/P3 — real
future scope for M6/M8/M9/M10/M12, none blocking M5's own N-way-merge
work, and none reopening the already-closed M4.5 P0). There is
therefore no direct contradiction of the current gate, per this task's
own Section 2 instruction ("Preserve the current evidence-based
`NEXT_RECOMMENDED_GATE` unless this reconciliation proves a direct
contradiction").
