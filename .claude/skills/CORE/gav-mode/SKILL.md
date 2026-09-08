---
name: gav-mode
description: Governed Autonomous Verification mode: autonomous closure under Graph, Skills, Evidence, Approval Gates and Human Override.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# gav-mode

Governed Autonomous Verification mode: autonomous closure under Graph, Skills, Evidence,
Approval Gates and Human Override.

## What "GAV mode" actually is in code

`.dv-harness/l5/autonomy_policy.json` defines GAV as one of three named `modes`
(`MANUAL`, `REVIEW`, `GAV`), `mode_name: "GAV"`, `default_mode: "REVIEW"`, with this
definition:

> "Goal-driven autonomous verification to evidence-closed SIGNOFF-READY with continuous
> human observability, intervention, approval, and takeover."

That is a **description of `dv_harness.engine.DVHarness.loop()`** — this project's one
real autonomous run loop, driven by `dv-harness start --loop "<goal>"` /
`commands.cmd_advance` — plus the human-control-plane commands (`human-control-plane`
skill) that can observe/interrupt/approve/take over that loop while it runs. There is no
separate "GAV mode" object, flag, or code path distinct from that loop; GAV mode is what
running `engine.loop()` with the human-control-plane always reachable *is*.

**Confirmed by direct search** (`grep -rn "autonomy_policy\|MANUAL_MODE\|GAV_MODE\|mode_name" dv_harness/`):
nothing in `dv_harness/*.py` reads `autonomy_policy.json` at all, and `policy.py`/
`config.py` have no `MANUAL`/`REVIEW`/`GAV` concept. **The MANUAL/REVIEW/GAV mode switch,
and `default_mode`, have no backing implementation.** `engine.loop()` always runs the same
way regardless of which mode a human might believe is "selected" — there is no code
gating dispatch, approval requirements, or autonomy level on that field. Do not tell a
user "the harness is in REVIEW mode" or "switching to GAV mode enables X" — no code
computes or enforces that distinction today. If a user wants mode-dependent behavior
(e.g. MANUAL should require an approval before every stage, REVIEW should require one
before signoff-adjacent stages only, GAV should run fully autonomously except the fixed
approval gates below), that is a real, currently-unimplemented feature — say so plainly
rather than acting as if `policy.can_signoff()` or `gates.py` already consult
`autonomy_policy.json`.

## What genuinely IS real and enforced: the five GAV pillars, mapped to code

- **Graph** — `.dv-harness/graph/main_graph.json`, read by `policy.graph_next()` /
  `engine.run_stage()`. `dv-harness graph` shows it; this is the real global workflow
  authority CLAUDE.md's Core Operating Rules name.
- **Skills** — each graph node's declared `route`/`skills`, dispatched via
  `router.RouteResolver.resolve()` and `MultiAgentOrchestrator`/`ClaudeCLIAdapter`.
- **Evidence** — `gates.py`'s `STAGE_GATES` table; every stage's PASS/FAIL is decided by
  running that stage's registered gate scripts against the agent's own fenced
  `dv-harness-evidence:<gate_id>` block (`gates.evaluate_stage_evidence()`). This is a
  real, load-bearing check, not advisory.
- **Approval Gates** — `ControlPlane.approve()`/`get_approval()`, consulted by
  `policy.can_signoff()` and by any `STAGE_GATES` entry keyed to a stage in
  `commands.APPROVAL_ONLY_STAGES`. See the human-control-plane skill's APPROVE section
  for the exact call chain.
- **Human Override** — always valid per CLAUDE.md's Core Operating Rules, and real in
  code: `engine.loop()` checks `ControlPlane.is_paused()` and
  `is_takeover_active_for(stage)` **before** every dispatch — a real PAUSE or TAKEOVER
  genuinely stops the autonomous loop, not merely records intent. See the
  human-control-plane skill for PAUSE/RESUME/REDIRECT/APPROVE/TAKEOVER — those commands
  ARE how a human exercises override during a GAV-mode run; there is nothing extra to
  invoke for "override" beyond them.

## `critical_approval_gates`: named, but not mechanically enforced as a set

`autonomy_policy.json` also lists seven `critical_approval_gates` ("high-impact DUT RTL
change", "force push/history rewrite", "mass LSF kill", "shared infrastructure change",
"mandatory regression removal", "signoff policy change", "credential persistence"). No
single mechanism in this codebase reads that list and gates on it as a set — confirmed by
the same search above. Several of the seven items *do* have their own real, independent
enforcement elsewhere, under their own names, unrelated to this JSON file:

| Named gate | Real, separately-triggered mechanism (not driven by `autonomy_policy.json`) |
|---|---|
| force push/history rewrite | `tools/git-hooks/pre-push` + `dv_harness/git_governance.py` (`dv-harness git-guard`) — blocks a direct agent push/merge to `main`/`master`; see CLAUDE.md's "gh CLI + PR-Only Governance Policy" section |
| shared infrastructure change | `dv_harness/change_blast_radius.py` (`dv-harness blast-radius`) — a real `WIDE`/`GOVERNANCE`-tier change requires a pinned `dv-harness approve CHANGE_BLAST_RADIUS` |
| mass LSF kill | `dv_harness/lsf_client.py`'s kill-verb preflight (`preflight.py` checks) — real, but not keyed to this JSON list |
| high-impact DUT RTL change | no dedicated mechanical gate found; relies on the ordinary `STAGE_GATES` evidence discipline plus human review of the diff (Engineering Discipline Rules) |
| mandatory regression removal | no dedicated mechanical gate found |
| signoff policy change | no dedicated mechanical gate found |
| credential persistence | no mechanical gate; a **policy rule** in CLAUDE.md's "Remote Linux Execution" section (never persist a password) — enforced by discipline, not code |

**If a user or workflow needs one of the four "no dedicated mechanical gate found" rows
enforced**, do not claim `autonomy_policy.json` already covers it — that file is
currently descriptive text with one confirmed reader (nothing) and zero enforcement.
Route the actual decision through `dv-harness approve <stage>` (human-control-plane
skill) on whatever real stage the change belongs to, or ask the user how they want it
gated if no stage fits.

## Practical guidance for an agent operating "in GAV mode"

1. Drive the loop with `dv-harness start --loop "<goal>"` (or `dv-harness next` /
   `commands.cmd_advance` one stage at a time) — this is the real GAV mechanism, not a
   mode flag.
2. Never claim a `MANUAL`/`REVIEW`/`GAV` mode switch changed engine behavior; it did not
   and cannot today.
3. When a human issues STATUS/WHY/EVIDENCE/REVIEW/PAUSE/RESUME/REDIRECT/APPROVE/
   REJECT/STOP/TAKEOVER during a GAV-mode run, use the human-control-plane skill's
   real mapping — do not invent a GAV-specific variant of any of those commands.
4. Treat the seven `critical_approval_gates` names as a **human-readable checklist** to
   apply judgment against, not as an enforced allowlist — three of the seven items have
   no mechanical gate at all yet.
