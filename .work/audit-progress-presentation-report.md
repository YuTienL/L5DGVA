# Audit: Does DV Agent Harness L5 SHOW the 4 requested progress/reporting behaviors?

Scope: only what the real user-facing surfaces (`dv_harness/cli.py` real subcommands,
`dv_harness/dashboard.py` real HTML/JS/HTTP output) actually **display**, regardless of whether
the underlying data exists or is correct. All line numbers are from the current working tree at
`D:\DV\Task\DV_Agent_Harness_L5\v50` as read this session.

Companion engine internals read to ground every verdict: `dv_harness/engine.py`,
`dv_harness/stage_profile.py`, `dv_harness/stage_profile_report.py`, `dv_harness/control_plane.py`
(not itself a user-facing surface, but the data source `cli.py`/`dashboard.py` render).

---

## Requirement 1 — "During execution, show current stage + pending items in that stage + % complete"

**Verdict: PARTIALLY_REAL** (real and present, but not on `status` — on other subcommands and on
the dashboard's "Why" card)

- `dv-harness status` (`cli.py:103`, handler `cli.py:490-491` → `DVHarness.summary()`,
  `engine.py:693-726`) prints `current_stage`, `active_stages`, `overall_status`,
  findings counts, pause/takeover/constraint state — **but no per-stage pending-item list and no
  completion percentage**. Real captured output against a fresh project
  (`.work/audit_tmp_project`):

  ```json
  {
    "project": "audit_tmp_project",
    "scope": "unknown",
    "current_stage": "ENV_CHECK",
    "active_stages": [],
    "effective_active_stages": ["ENV_CHECK"],
    "overall_status": "NOT_STARTED",
    "git_sha": null,
    "server_sha": null,
    "findings_total": 0,
    "findings_closed": 0,
    "findings_open": 0,
    "closure_iteration": 0,
    "paused": false,
    "paused_reason": "",
    "takeover_active": false,
    "takeover_stage": null,
    "active_constraint_count": 0,
    "dv_review_cosign_enforced": false
  }
  ```
  No `stage_completion_percent`, no pending-item list anywhere in this dict. So the literal
  target of the user's phrasing ("`dv-harness status`") does **not** show it.

- The data the user is asking for **does** exist and **is** rendered, but only via two other real
  subcommands: `dv-harness checklist [--stage X]` (`cli.py:143-148`, handler `cli.py:581-596`,
  renderer `render_stage_checklist_report`/`_render_checklist_section` at `cli.py:31-74`) and
  `dv-harness explain [--stage X]` (which appends the same rendering after its JSON block,
  `cli.py:495-536`). Real captured output against the same fresh project:

  ```
  Stage: ENV_CHECK
  Gate completion: 0% (0/1 gates passed)

  Entry checklist (evidence required before this stage runs):
    (no telemetry recorded yet -- this stage has not run this attempt)

  Exit checklist (evidence this stage should have produced):
    (no telemetry recorded yet -- this stage has not run this attempt)
  ```

  and, for a stage with a real declared checklist (INTAKE, before it has ever run):

  ```
  Stage: INTAKE
  Gate completion: 0% (0/4 gates passed)

  Entry checklist (evidence required before this stage runs):
    (no telemetry recorded yet -- this stage has not run this attempt)

  Exit checklist (evidence this stage should have produced):
    (no telemetry recorded yet -- this stage has not run this attempt)
  ```

  Once a stage has actually run at least once, `_render_checklist_section` (`cli.py:31-50`) prints
  one `[x]`/`[ ] item_id - description` line per declared item plus a `>>> STILL NEEDS TO BE
  SUPPLIED: ...` line for anything missing — this is a real, working "pending items" list, just
  gated on `checklist`/`explain`, not on `status`.

- `dashboard.py`'s "Why (current stage)" card (`dashboard.py:130-135`, JS `stageWhyHTML` at
  `dashboard.py:479-489`) shows exactly this: a `Stage completion: NN% (gp/gt gates passed)`
  line with a real progress bar (`.bar` div width bound to the percent), plus
  `checklistBlock()` (`dashboard.py:458-478`) rendering entry/exit checklists with per-item
  ✓/✗ and a "Still needs to be supplied: ..." line. This card is populated by `GET /api/state`'s
  `current_stage_detail` (`dashboard.py:1895`, built via the same `control_plane.describe_stage()`
  the CLI uses) and refreshed by a 3-second poll (`dashboard.py:1023`:
  `load(); setInterval(load,3000)`).

**Conclusion**: the exact literal ask ("`dv-harness status`... show stage + pending + %") is
NOT what `status` does. But the underlying capability — stage, pending items, percent — is
WIRED_AND_REAL as a running display, just on `checklist`/`explain` (CLI) and the dashboard's
"Why" card (GUI), not on `status`. Scored PARTIALLY_REAL because the specific command named in
the requirement doesn't do it, while a real running surface does.

---

## Requirement 2 — "At each stage START: prominent Logo/banner + required-materials checklist +
completeness % + a prompt naming what still needs detail"

**Verdict: NOT_IMPLEMENTED** (as a stage-START-specific display; the underlying entry-checklist
capability is real but is not shown as a start-of-stage event, and there is no logo/banner
anywhere)

- The full extent of any "banner-style" print anywhere in the codebase around a stage start is
  exactly the one line already known from prior evidence:

  `engine.py:145`: `STAGE_MARKER_PREFIX = "[DV-HARNESS-STAGE]"`
  `engine.py:148-149`:
  ```python
  def _emit_stage_start_marker(stage: str) -> None:
      print(f"{STAGE_MARKER_PREFIX} ===== STAGE START: {stage} =====", flush=True)
  ```
  called once, at `engine.py:1837`, inside `run_stage()`, right after the TAKEOVER
  short-circuit and before any state mutation. Grepping the entire `dv_harness/` tree for any
  other banner/ASCII-art print (`=====`, `#####`, `pyfiglet`, `figlet`, "banner", "logo") turns up
  **nothing else** in engine/CLI/dashboard code — every other `=====` hit is an unrelated `#`
  comment-block header inside generated build-script *templates*
  (`uvm_generator/templates/sim_scripts/*.sh`, `Makefile`, `waves.tcl`), not runtime output.
  So yes: `[DV-HARNESS-STAGE] ===== STAGE START: X =====` is the full extent of it. It is:
  - a single plain-text line, not a "prominent Logo" (no ASCII art, no distinct visual weight,
    no color/highlighting — it's `print()` to whatever stdout the caller happens to have).
  - printed only when `DVHarness.run_stage()` runs in-process. The dashboard's background runner
    invokes the harness in the **same Python process** on a daemon thread
    (`dashboard.py:1674-1718`, `_start_background_run`/`_worker`, `threading.Thread(...).start()`
    at `dashboard.py:1718`) — so this marker goes to the dashboard server's own console/log, not
    anywhere in the HTML/JSON the browser receives. The dashboard UI has **zero** reference to
    `STAGE_MARKER_PREFIX` or to "STAGE START" text anywhere in its HTML/JS (grepped, no hits).
  - carries no materials checklist, no completeness %, no "needs more detail" prompt — it is
    exactly one line naming the stage, nothing else.

- The entry-materials checklist itself is real code (`build_stage_entry_checklist`,
  `engine.py:368-401`, computed at `engine.py:1973` as `entry_checklist` and persisted into the
  per-attempt telemetry record at `engine.py:1976-1977`) — but it is **never printed to any
  console/HTML at the moment the stage starts**. It is only ever surfaced later, on demand, via
  `dv-harness checklist`/`explain` (CLI, req 1 above) or the dashboard's continuously-polled
  "Why" card (`dashboard.py:479-489`), which shows the *current* stage's entry checklist
  indefinitely while that stage is current — not as a "just started" event with a distinct look.
  There is no `--reason`-style prompt/nag specifically fired at stage-start time either; the
  closest thing is `checklistBlock()`'s per-missing-item red "Still needs to be supplied: ..."
  line (`dashboard.py:472-474`), which is real, but again is a steady-state display, not an
  entry-moment banner.

**Conclusion**: no logo/banner of any kind exists anywhere in this codebase (the one plain-text
`===== STAGE START ... =====` line is genuinely all there is, confirming the session's prior
evidence was already the full extent). The materials checklist + completeness % + missing-item
prompt the user wants tied to that moment exist as real, working code — but as a continuously
displayed "current stage" panel, not as a start-of-stage event with any distinguishing visual
treatment. Because neither the "prominent Logo" half nor the "tied to the START moment
specifically" half is real, this is scored NOT_IMPLEMENTED rather than PARTIALLY_REAL.

---

## Requirement 3 — "At each stage END: prominent Logo/banner + output-files checklist +
completeness % + total execution time (incl. per-agent) + token count"

**Verdict: NOT_IMPLEMENTED** (as a single, stage-END-tied display combining all four elements;
each individual ingredient is real but scattered across separate, manually-triggered surfaces)

- Symmetric one-line marker, `engine.py:152-155`:
  ```python
  def _emit_stage_done_marker(stage: str, gate_verdict: str, stage_completion_percent) -> None:
      pct = f"{stage_completion_percent:.0f}" if isinstance(stage_completion_percent, (int, float)) else "-"
      print(f"{STAGE_MARKER_PREFIX} ===== STAGE DONE: {stage} [{gate_verdict}] "
            f"({pct}% gates satisfied) =====", flush=True)
  ```
  called once at `engine.py:2342-2343`, after `stage_detail = describe_stage(...)` and after
  `self.state.last_transition` is set (`engine.py:2337-2341`). Same properties as the START
  marker: plain text, no logo/banner styling, console-only (invisible to the dashboard browser
  when the run is dashboard-driven, same in-process-thread reasoning as req 2). It carries a gate
  verdict and a percent — but that percent is the *gate*-completion percent, not an output-files
  checklist, and it carries no time/token figures at all.

- The dashboard's one END-tied display element is `renderLastTransitionBanner()`
  (`dashboard.py:431-443`), fed by `state.last_transition` (`models.py:173`, set only at
  `engine.py:2338-2341`, i.e. only at stage END — there is no equivalent START field). Rendered
  as a single colored one-line strip (`dashboard.py:91-97,101`):
  `"<STAGE> → <STATUS> at <time>"`. This is the closest thing to an "end of stage" visual marker
  in the GUI — a colored bar, not a logo, carrying stage/status/timestamp only (no files
  checklist, no percent, no time-spent, no tokens).

- The exit/output-files checklist is real (`build_stage_exit_checklist`, `engine.py:403-...`,
  computed at `engine.py:2319-2320`, persisted at `engine.py:2321-2323`) and rendered by the exact
  same generic mechanisms as the entry checklist in req 2 (`dv-harness checklist`/`explain`, and
  the dashboard's continuously-polled "Why" card's `checklistBlock('Exit checklist ...', d.exit_checklist)`
  at `dashboard.py:489`) — again a steady-state panel, not something that fires distinctly at the
  stage-END moment.

- Total execution time + per-agent/per-stage breakdown + token counts DO exist as real, already
  collected data (`StageExecutionProfiler` in `stage_profile.py`, wired into every real stage run
  via `engine.py`'s `profiler.begin_stage()`/`profiler.add_agent_run()`/`profiler.end_stage()`),
  and DO have a real renderer, `stage_profile_report.render()` (`stage_profile_report.py:51-86`),
  exposed as:
  - CLI: `dv-harness stage-profile` (`cli.py:279-281`, handler `cli.py:734-736`)
  - Dashboard: a "Stage Execution Profile" card (`dashboard.py:279-285`) with a manual
    **"Refresh" button** (`dashboard.py:283`, `onclick="loadStageProfile()"`) hitting
    `GET /api/stage-profile` (`dashboard.py:1948-1954`).

  Real captured output (fresh project, no stage ever run — table empty but the shape/columns are
  real):
  ```
  DV Agent Harness L5 - Stage Execution Profile
  Stage                          Wall    Input   Output    Total  Tools  Retry   Status
  --------------------------------------------------------------------------------------
  --------------------------------------------------------------------------------------
  TOTAL WORKFLOW                0m00s      N/A      N/A      N/A
  ```
  On a real run this table gets one row per stage (`Wall`/`Input`/`Output`/`Total` tokens/`Tools`/
  `Retry`/`Status`), a `TOTAL WORKFLOW` row, and (when `workflow_profile.json` exists) an
  `AGGREGATE AGENT TIME` / `PARALLEL SAVING` / `PARALLEL EFFICIENCY` / `TOOL CALLS / RETRIES`
  block (`stage_profile_report.py:77-82`) — this is a genuine "total execution time including
  per-agent/parallel breakdown, and token count" report. But: it is **its own separate
  command/card**, pulled **on demand by the user**, never automatically shown, printed, or
  surfaced at the moment any individual stage ends. Nothing wires it into
  `_emit_stage_done_marker()` or into `renderLastTransitionBanner()`.

**Conclusion**: every individual ingredient the user asked for (files checklist w/ %, execution
time, per-agent breakdown, token count) is real, computed, and has *some* real display surface —
but they are four separate surfaces (a bare one-line console marker, a bare one-line colored GUI
strip, a continuously-polled checklist panel, and a manually-refreshed profiling table), none of
which is a single "stage just ended" event carrying all four plus a logo. Scored
NOT_IMPLEMENTED for the requirement as stated (a unified, logo'd, stage-end moment display);
the constituent data/rendering pieces are real but not assembled into that moment.

---

## Requirement 4 — "Persist the displays from #2 and #3 as saved reports"

**Verdict: NOT_IMPLEMENTED** (no artifact that saves "the display" itself; the raw data the
display would be built from is durably persisted, which is the closest real analog)

- Since #2 and #3 do not exist as discrete displays (see above), there is nothing named
  "stage-start report" / "stage-end report" anywhere in the codebase. Grepped
  `dv_harness/` for `save_report`, `stage_report`, `banner.*persist`, `saved_report`,
  `export_stage`, `stage_snapshot_report` — **zero hits**.

- What IS real and durable is the underlying telemetry the checklists/time/token displays are
  computed from: `StageExecutionProfiler` writes one JSON file per stage attempt under
  `.dv-harness/telemetry/stages/*.json` (`stage_profile.py:51-57` for the paths;
  `begin_stage()`/`end_stage()` write `entry_checklist`/`exit_checklist`/wall-clock/token fields
  into that same per-attempt record, `stage_profile.py:59-132`) plus one
  `.dv-harness/telemetry/workflow_profile.json` aggregate file (`stage_profile.py:57,191`). This
  IS a genuine saved record containing the same fields the checklist/profile displays read from —
  but it is raw machine-readable JSON telemetry, not a rendered "report" resembling what a human
  sees on `checklist`/`stage-profile`/the dashboard cards. Re-deriving the human display from it
  requires re-running `dv-harness checklist`/`stage-profile` (or opening the dashboard) — nothing
  writes the *rendered* banner/checklist/time-token report itself to disk at the moment it would
  have been shown.

- `dv-harness signoff-export --out <dir>` (`cli.py:332-339`, `signoff_export.py:252-260`) does
  copy the entire `.dv-harness/telemetry/` directory verbatim into a signoff bundle alongside
  other final-deliverable artifacts — this is the one place telemetry (including per-stage
  entry/exit checklists) gets bundled for hand-off. But it is a one-shot, human-invoked, final
  *signoff* export (bundling vPlan/blackboard/self-audit/etc. together), not a per-stage
  save-on-start/save-on-end report, and it still ships raw JSON, not the rendered display.

**Conclusion**: the raw ingredients for #2/#3 are durably saved (telemetry JSON per stage
attempt, an aggregate workflow file, and a copy of both inside `signoff-export` bundles), so a
report COULD be reconstructed from disk after the fact — but no code path saves the actual
banner/checklist/time/token *display* the user is asking to persist, at stage-start or stage-end
time or otherwise. Scored NOT_IMPLEMENTED against the literal ask ("save the displays"), noting
the real underlying persistence as the closest existing analog.

---

## Summary table

| # | Requirement (short) | Verdict | Key evidence |
|---|---|---|---|
| 1 | `status`/CLI shows stage + pending + % | PARTIALLY_REAL | `status` (`cli.py:490`, `engine.py:693-726`) shows stage but no %/pending; `checklist`/`explain` (`cli.py:581-596`, `31-74`) and dashboard "Why" card (`dashboard.py:479-489`, polled every 3s at `dashboard.py:1023`) do show stage+%+pending, just not on `status` |
| 2 | Stage-START logo + materials checklist + % + prompt | NOT_IMPLEMENTED | Only banner-like thing anywhere is the plain-text `[DV-HARNESS-STAGE] ===== STAGE START: X =====` line (`engine.py:148-149`, called `engine.py:1837`) — console-only, no logo, no checklist attached to it. Entry checklist is real (`engine.py:368-401`, `1973`) but shown only as a continuous panel, not a start-moment event |
| 3 | Stage-END logo + output checklist + % + time + tokens | NOT_IMPLEMENTED | Symmetric one-line `STAGE DONE` marker (`engine.py:152-155`, called `2342`) + a one-line colored `lastTransitionBanner` (`dashboard.py:431-443`) are the only end-tied displays; exit checklist, execution-time, and token data are all real but live in separate, non-auto-shown surfaces (`checklist`, `stage-profile` CLI+card at `dashboard.py:279-285`) |
| 4 | Persist #2/#3 displays as saved reports | NOT_IMPLEMENTED | No `stage_report`/`save_report` artifact exists anywhere (grepped, zero hits). Underlying raw telemetry (`entry_checklist`/`exit_checklist`/timing/tokens) IS durably saved per stage attempt (`stage_profile.py:51-132`, files under `.dv-harness/telemetry/stages/`) and gets bundled by `signoff-export` (`signoff_export.py:252-260`) — but that is raw JSON data, not a saved rendering of the display itself |

## Commands actually run this session (fresh project, no side effects to any real project)

```
PYTHONPATH=D:\DV\Task\DV_Agent_Harness_L5\v50 python -m dv_harness.cli --project-root .work/audit_tmp_project status
PYTHONPATH=D:\DV\Task\DV_Agent_Harness_L5\v50 python -m dv_harness.cli --project-root .work/audit_tmp_project checklist
PYTHONPATH=D:\DV\Task\DV_Agent_Harness_L5\v50 python -m dv_harness.cli --project-root .work/audit_tmp_project checklist --stage INTAKE
PYTHONPATH=D:\DV\Task\DV_Agent_Harness_L5\v50 python -m dv_harness.cli --project-root .work/audit_tmp_project stage-profile
```
(No real stage was ever executed against this project — that would invoke a real Claude
adapter subprocess/session, which is not a safe, side-effect-free operation to run as part of an
audit — so all captured output above reflects a project at its initial, never-run state. Outputs
with populated checklist items/timing/tokens are the code-cited, not independently re-executed,
behavior for a project that has actually run stages.)
