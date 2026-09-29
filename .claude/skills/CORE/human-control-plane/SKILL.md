---
name: human-control-plane
description: Human-in-the-loop control plane for STATUS WHY EVIDENCE REVIEW PAUSE RESUME REDIRECT APPROVE REJECT STOP TAKEOVER.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# human-control-plane

Human-in-the-loop control plane for STATUS WHY EVIDENCE REVIEW PAUSE RESUME REDIRECT
APPROVE REJECT STOP TAKEOVER.

`human_commands` in `.dv-harness/l5/autonomy_policy.json` is a plain **declared list of
words** — a repo-wide search (`grep -rn "human_commands\|autonomy_policy" dv_harness/`)
confirms nothing in `dv_harness/*.py` ever reads that file or that field. The words are
not self-executing. What follows is where each word actually resolves in this codebase
today, so an agent asked to "handle a STATUS/APPROVE/etc. request" knows the real call to
make instead of inventing one.

## Two real entry points, one real backing store

1. **Direct CLI / local session** — `python -m dv_harness.cli <verb>` (or
   `dv-harness <verb>` once installed). Runs as the local OS user; no role check of its
   own. This is the path an agent normally uses.
2. **Gated Remote Control session** — `dv-harness remote-control cmd <COMMAND>
   --target-stage STAGE --reason "..."`. Every one of the 11 words below (plus
   `HYPOTHESIS`, which `autonomy_policy.json` does not list) is a real, named branch of
   `dv_harness/remote_control.py`'s `ALLOWED_COMMANDS`, run through
   `validate_and_transition()`: a supervisory gate, a state-transition gate, the real
   `ControlPlane`/`engine.py` side effect (§ below), then an audit gate and a replay gate,
   all-or-nothing (nothing is persisted if any gate fails). Use this path only when the
   request is genuinely arriving over an active Claude Code Remote Control session (see
   that module's own docstring) — it is a supervisory wrapper around the same
   `ControlPlane` calls the CLI verbs below use directly, not a second mechanism.
3. **Dashboard `POST /api/control`** — the same `ControlPlane`/`engine.py` calls, gated by
   `dashboard_auth.py`'s per-command role (`CONTROL_COMMAND_REQUIRED_ROLE`): PAUSE / RESUME
   / TAKEOVER / REDIRECT need **OPERATOR**, APPROVE needs **APPROVER**. This gate exists
   only on the dashboard's HTTP surface, behind its own per-session token
   (GUI-19) — the CLI and `remote-control` paths above have no such role check.

All three funnel into the **same one real state file**: `dv_harness/control_plane.py`'s
`ControlPlane`, backed by `.dv-harness/control.json` (pause flag, active takeover,
corrections, approvals + approval history, cosigns, suspicious-flags, bundle reviews).
`dv-harness audit` reads the real trail (`control.json` + the last N `.dv-harness/events.jsonl`
entries) for "who changed what, when."

## Command-by-command mapping

### STATUS — real, read-only
- **Invocation**: `dv-harness status` (bare) prints `h.summary()`; `dv-harness status
  <view> [--json]` (added for the Global Status Bar theme) builds a
  `harness_status.HarnessStatusService(root).serve()` snapshot and renders one of
  `full|blockers|jobs|coverage|agents|system|evidence|signoff`.
  Python: `dv_harness.cli` `args.cmd == "status"` (`cli.py` ~4171); `remote_control.get_status(root)`
  is the equivalent read inside a Remote Control session.
- **Effect**: none — pure read of `state.json` / `HarnessStatusService`'s own aggregated
  producers (`golden_flow_readiness.py`, `platform_health.py`, `loop_telemetry.py`, …).
- **Precondition / role**: none.

### WHY — real, read-only (`explain`)
- **Invocation**: `dv-harness explain [--stage STAGE]`.
  Python: `prompts.get_de_explainer(stage)` (static per-stage prose) followed by
  `control_plane.describe_stage(root, state, stage)` (this run's actual
  `blocking_reason`/evidence blocks/gate verdict/`stage_completion_percent`), printed as
  JSON, then `render_stage_checklist_report(detail)` for the human-readable form. With no
  `--stage`, explains every branch in `state.effective_active_stages()` (a live parallel
  fan-out has more than one active stage; `current_stage` alone would miss the others).
- **Effect**: none.
- **Precondition / role**: none.

### EVIDENCE — real, read-only
- **Invocation**: `dv-harness evidence [--stage STAGE]` (raw `describe_stage()`/
  `describe_stages()` JSON only — no prose, so a script can `json.loads()` the whole
  stdout); `dv-harness checklist [--stage STAGE]` is the dedicated human-readable
  rendering of the identical data.
  Python: `control_plane.describe_stage` / `describe_stages` (`control_plane.py:622`,
  `:698`).
- **Effect**: none.
- **Precondition / role**: none.

### REVIEW — real, read-only, but only inside a Remote Control session
- **Invocation**: `dv-harness remote-control cmd REVIEW --target-stage STAGE`.
  Python: `remote_control._current_stage_review_detail(root)` (`remote_control.py:441`) —
  returns the current stage's real `StageState` (`gate_verdict`/`evidence`/`attempts`/
  `blocking_reason`) plus, if present, the most recent independently-recomputed
  root-cause confidence engine.py wrote to the Blackboard `root_cause_confidence` topic.
  Deliberately different content from STATUS (not a relabeled copy of it).
- **Effect**: none — one of `remote_control.py`'s `_ENGINE_EFFECT_COMMANDS` does **not**
  include REVIEW.
- **Precondition / role**: needs an active Remote Control session
  (`dv-harness remote-control bootstrap` first). **Outside** a Remote Control session
  there is no dedicated `dv-harness review` verb — use `explain`/`evidence` above instead
  of inventing one, or the `code-review`/`security-review` skills if the ask is actually
  "review this diff," a different meaning of the word.

### PAUSE — real
- **Invocation**: `dv-harness pause [--reason "..."]`.
  Python: `commands.cmd_pause(h, reason)` (`commands.py:78`) → `ControlPlane.pause(reason)`
  (`control_plane.py:158`).
- **Effect**: writes `control.json.paused = True` (+ reason, timestamp). `engine.loop()`
  checks this at the top of every cycle and halts dispatch — a real, load-bearing effect,
  not cosmetic.
- **Precondition / role**: none via CLI/`remote-control`; **OPERATOR** via dashboard.

### RESUME — real
- **Invocation**: `dv-harness resume`.
  Python: `commands.cmd_resume(h)` (`commands.py:84`) → `ControlPlane.resume()`
  (`control_plane.py:166`).
- **Effect**: clears the pause flag; `engine.loop()` may dispatch again.
- **Precondition / role**: none via CLI/`remote-control`; **OPERATOR** via dashboard.

### REDIRECT — real
- **Invocation**: `dv-harness redirect <STAGE> [--reason "..."]`.
  Python: `commands.cmd_redirect(h, stage, reason)` (`commands.py:116`) →
  `DVHarness(root).human_redirect(stage, reason)` (lives on `DVHarness`, not
  `ControlPlane`, because it must also move `current_stage` in `StateStore`).
- **Effect**: moves `state.json.current_stage` to the named stage.
- **Precondition / role**: **raises `RuntimeError` and refuses** if a different stage is
  currently under an active TAKEOVER — a redirect cannot silently override someone else's
  takeover. Role: none via CLI/`remote-control`; **OPERATOR** via dashboard.

### APPROVE — real
- **Invocation**: `dv-harness approve <STAGE> [--note "..."] [--reviewer-id ID]
  [--reviewer-confidence LEVEL]`.
  Python: `commands.cmd_approve(h, stage, note, reviewer_id, reviewer_confidence)`
  (`commands.py:127`) → `ControlPlane.approve(stage, note, reviewer_id)`
  (`control_plane.py:272`).
- **Effect**: writes a real approval entry to `control.json.approvals[stage]` (+
  `approval_history`); `policy.can_signoff()`/gate checks for that stage consult it. A
  PASS at that stage **consumes** the approval (`ControlPlane.clear_approval`,
  `outcome="CONSUMED_BY_PASS"`) — an approval is single-use per PASS, not a standing
  authorization.
- **Precondition / role**: `stage` must be a real graph stage or one of the three
  explicit non-graph keys `commands.APPROVAL_ONLY_STAGES` (`RESEARCH_CAPABILITY_EVOLUTION`,
  `CHANGE_BLAST_RADIUS`, `BOUNDED_SELF_HEALING`, `SIGNOFF_FREEZE_REVALIDATION` — see
  `commands._check_approval_stage`, `commands.py:72`); an unknown stage name raises. Role:
  none via CLI/`remote-control`; **APPROVER** via dashboard.

### REJECT — NOT IMPLEMENTED as a generic command
- There is **no** `ControlPlane.reject()` and **no** generic `dv-harness reject <stage>`
  verb anywhere in `dv_harness/`. Confirmed directly in `remote_control.py`'s own module
  docstring: *"REJECT, STOP have no ControlPlane equivalent exists at all… these remain
  SESSION-STATUS-ONLY: this module's `session.json` will say REJECTED/whatever, but
  nothing in `engine.py` or `ControlPlane` reads that state. Do not present REJECT/STOP
  through this module as equivalent to PAUSE/TAKEOVER — they are not."*
- The **only** real, narrower "reject" verb in this codebase is scoped to
  capability-evolution research candidates: `dv-harness research-reject <candidate_id>
  <reason>` → `commands.cmd_research_reject()` (`commands.py:202`), which transitions a
  `CapabilityEvolutionCandidate` to `REJECTED` — this is not a stage rejection and cannot
  substitute for one.
- **If asked to REJECT a stage/decision**: there is no backing implementation. Tell the
  user directly and ask for the manual action they actually want — e.g. leave the stage
  un-approved (an absent approval already blocks `can_signoff()`), or `PAUSE`/`TAKEOVER`
  the stage so nothing advances, or hand-edit `control.json` only if the user explicitly
  directs it.

### STOP — NOT IMPLEMENTED as a generic command
- Same citation as REJECT above — `remote_control.py` explicitly documents there is no
  `ControlPlane`/`engine.py` effect for STOP either. `remote-control cmd STOP` will update
  that module's own `session.json`, but nothing in the autonomous loop reads or reacts to
  it.
- `loop_contract.LoopState.STOPPED` exists as a real terminal *state name* in the loop
  telemetry vocabulary, but nothing in `engine.py` ever transitions a loop there in
  response to a human command — every real producer of that value is
  documented in `dv_harness/loop_contract.py`/`loop_telemetry.py`, and none of them is
  "a human typed STOP."
- **The real ways to actually halt autonomous work today** are `PAUSE` (stops new stage
  dispatch, resumable) and `TAKEOVER` (stops dispatch on one specific stage until
  `release-takeover`), or killing the running process itself. **If asked to STOP**: do
  not fabricate a STOP effect — use PAUSE/TAKEOVER for the real, tested halt behavior, and
  say explicitly that STOP itself has no backing implementation if the user specifically
  asked for that word's effect.

### TAKEOVER — real
- **Invocation**: `dv-harness takeover [--message "..."]`; `dv-harness release-takeover`.
  Python: `commands.cmd_takeover(h, message)` (`commands.py:91`) →
  `ControlPlane.takeover(stage, message, taken_by)` (`control_plane.py:178`);
  `commands.cmd_release_takeover(h)` (`commands.py:109`) →
  `ControlPlane.release_takeover()` (`control_plane.py:190`).
- **Effect**: records an active takeover on a stage in `control.json`; `engine.loop()`
  checks `is_takeover_active_for(stage)` and will not dispatch that stage until released.
  A later `REDIRECT` targeting a *different* stage while a takeover is active on the
  current one is refused (see REDIRECT above).
- **Precondition / role**: none via CLI/`remote-control`; **OPERATOR** via dashboard.

## Summary table

| Command  | Real implementation | Side effect | Precondition / role |
|---|---|---|---|
| STATUS   | `cli.py` `status` → `h.summary()` / `harness_status.HarnessStatusService` | none (read) | none |
| WHY      | `cli.py` `explain` → `prompts.get_de_explainer` + `control_plane.describe_stage` | none (read) | none |
| EVIDENCE | `cli.py` `evidence`/`checklist` → `control_plane.describe_stage(s)` | none (read) | none |
| REVIEW   | `remote_control._current_stage_review_detail` (Remote Control session only) | none (read) | active RC session |
| PAUSE    | `commands.cmd_pause` → `ControlPlane.pause` | `control.json.paused=True`; halts dispatch | dashboard: OPERATOR |
| RESUME   | `commands.cmd_resume` → `ControlPlane.resume` | clears pause | dashboard: OPERATOR |
| REDIRECT | `commands.cmd_redirect` → `DVHarness.human_redirect` | moves `current_stage` | refused under a conflicting TAKEOVER; dashboard: OPERATOR |
| APPROVE  | `commands.cmd_approve` → `ControlPlane.approve` | records approval; single-use, consumed on PASS | stage must be a graph stage or `APPROVAL_ONLY_STAGES`; dashboard: APPROVER |
| REJECT   | **no backing implementation** (only `research-reject`, scoped to research candidates) | — | ask the user for manual action |
| STOP     | **no backing implementation** | — | use PAUSE/TAKEOVER instead; ask the user if STOP itself is required |
| TAKEOVER | `commands.cmd_takeover`/`cmd_release_takeover` → `ControlPlane.takeover`/`release_takeover` | blocks dispatch of that stage until released | dashboard: OPERATOR |
