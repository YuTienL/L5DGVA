# GUI-10 gap close: Research / Continuous Capability Evolution center

Status: **DONE**

Report path note: the requested filename `.work/gap-close-gui-gui-10:-report.md`
contains a `:`, which NTFS interprets as an alternate-data-stream separator
rather than a filename character (the GUI-09 pass left a stray zero-content
`.work/gap-close-gui-gui-09` entry doing exactly this). Written to
`.work/gap-close-gui-gui-10-report.md` instead.

## The gap

`dashboard.py` had zero references to the research / capability-evolution path,
despite it being installed and permanent per CLAUDE.md's "Research Front Door"
and "Research Stage Boundaries" sections: `dv_harness/capability_evolution.py`
owns the `CapabilityEvolutionCandidate` state machine and its Human Approval
Gate is already the real `ControlPlane` keyed on `RESEARCH_CAPABILITY_EVOLUTION`.
A human could file a candidate and then had no surface to act on it but a
terminal.

## What was built

**`GET /api/research`** (`dashboard._read_research_state()`), read-only, reading
the real module and nothing else:

| shown | real source |
|---|---|
| candidate rows | `capability_evolution.read_candidates()` (the one Blackboard topic) |
| KEEP/ENHANCE/ADD/EXPERIMENT/REJECT + overlap | the candidate's own `decide_recommendation()` output |
| per-promotion-state totals | `Blackboard.capability_evolution_counts()` |
| which actions are offered per row | `capability_evolution.LEGAL_TRANSITIONS` |
| unanswered L5 checks (hover) | `capability_evolution.unanswered_l5_check_questions()` |
| gate state / approval history / CLI equivalent | `capability_evolution.human_approval_status()` |
| audit trail | `capability_evolution.candidate_audit_records()` (Working Memory) |

No candidate filed yet returns an honest `available: false` with the gate state
still reported (same contract as the Coverage / AMBA cards); an unreadable topic
returns a real `reason`/`detail`, not a 500.

**Card `#researchCard`**, refreshed by `load()`, structured like the Coverage /
AMBA cards (tiles + note + filtered table + result pane).

**Three actions, through the existing dispatch only.** `POST /api/control` ->
`_dispatch_control()` -> `commands.cmd_research_approve/reject/hold`. No
research-specific POST endpoint, no second approval store:

- **Approve** — `commands.cmd_approve(RESEARCH_CAPABILITY_EVOLUTION, ...)`
  writes the identical `control.json` record `dv-harness approve
  RESEARCH_CAPABILITY_EVOLUTION` writes, and the real
  `capability_evolution.transition()` then consumes it, re-reading it off disk
  through `assert_human_approval()` and copying it into the candidate's own
  `status_history`. The legality check (`assert_legal_transition()`) runs
  **before** the approval is written, so a refused approve leaves no orphan
  standing production-write authorization.
- **Reject** — `transition(..., "REJECTED")`. No approval involved: declining a
  proposal about the harness is not a production write.
- **Hold** — `ControlPlane.clear_approval(..., outcome="WITHDRAWN_BY_HUMAN_HOLD")`.
  Real block, not a label: with no approval standing,
  `assert_no_production_write_authorized()` refuses a Stage-3 production write
  even on a candidate already at HUMAN_APPROVED.

**Supporting edits.** `ControlPlane.clear_approval()` gained an optional
`outcome` parameter (default unchanged, so `engine.py`'s existing positional
call is untouched) so "a human took this authorization back" and "the stage it
authorized passed" stay distinguishable in `approval_history`.
`_handle_control()` gained a `PermissionError -> 403` branch so the module's
`HumanApprovalRequiredError` / `ProductionWriteNotAuthorizedError` surface as a
refusal with the real authorizing command in the message, not a 500.

## Disclosed limits (stated on the card itself, not only here)

1. **Hold is stage-scoped, not candidate-scoped.** The gate `ControlPlane` owns
   is keyed on the stage string, and `PROMOTION_STATES` has no HOLD state;
   minting one would fabricate a governance state master prompt section 70
   defines verbatim, and a per-candidate approval store would be the parallel
   mechanism this project forbids. A hold withholds authorization for every
   candidate at once; the candidate it names is recorded as the reason.
2. **Approving is Stage-3 authorization only** — it authorizes a human to
   implement, implements nothing, and `main`/`master` still goes through the
   PR-only governance gate.
3. Nothing here files or advances a candidate autonomously; the card is a human
   decision surface over records the research route produces.

## Files changed

- `dv_harness/dashboard.py` — `_read_research_state()`, `GET /api/research`,
  three `RESEARCH_*` commands in `_dispatch_control()`, `PermissionError -> 403`,
  card HTML + CSS + `loadResearch()`/`renderResearchTable()`/`doResearchAction()`,
  `load()` wiring.
- `dv_harness/commands.py` — `cmd_research_approve` / `cmd_research_reject` /
  `cmd_research_hold` + `_research_candidate()`.
- `dv_harness/control_plane.py` — `clear_approval(stage, outcome=...)`.
- `dv_harness_tests/test_dashboard_research_card.py` — new, 14 tests.

## Test summary

`test_dashboard_research_card.py` 14 passed; full re-run of
`test_dashboard_*.py` + all `test_research*` / `test_capability_evolution_*`
suites: **262 passed**, 0 failed.
