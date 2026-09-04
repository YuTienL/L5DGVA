from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from typing import Any, Dict, Optional
from .engine import DVHarness
from .models import Stage, Status
from .preflight import TRANSPORT_CHOICES
from .router import RESEARCH_FOCUS_DOMAINS
from . import commands as _commands


def _access_user() -> str:
    # Same fallback chain control_plane.py/knowledge_center.py already use
    # for their own private copies -- kept separate rather than a
    # cross-module import, matching this codebase's established pattern.
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _access_host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-host"


def _dump_scope_decided_by(store, scope: str) -> str:
    """Who actually answered this scope's waveform-dump question, or "" if
    nobody has. Used only by `waveform-dump-scope status` when the caller
    supplied no --confirmed-by: the attribution half of the gate's check is
    then not what is being asked, so feed it the real decider and let the
    existence/human-source halves do the work."""
    from . import waveform_dump_gate
    decision = store.find_decision(waveform_dump_gate.dump_scope_question_key(scope))
    return str(((decision or {}).get("current") or {}).get("decided_by") or "")


# --- Human-readable stage completion / checklist rendering (2026-09-01,
# runtime-progress-visibility pass) ------------------------------------------
# control_plane.describe_stage() carries stage_completion_percent/
# gates_passed/gates_total and entry_checklist/exit_checklist as real data,
# but `explain`/`evidence` only ever printed it as raw JSON -- a human had to
# read a dict to find out which specific item is still missing. This renders
# the same dict as checkmarks/x-marks per item plus an explicit "still needs
# to be supplied" line, shared by `explain --stage` (appended after its
# existing JSON block, kept for backward compatibility) and the new
# `checklist --stage` subcommand (see main()'s RULING comment at its call
# site for why `evidence --stage` itself is left JSON-only).
def _render_checklist_section(title: str, checklist: Optional[Dict[str, Any]]) -> str:
    lines = [f"{title}:"]
    if checklist is None:
        lines.append("  (no telemetry recorded yet -- this stage has not run this attempt)")
        return "\n".join(lines)
    total = checklist.get("total_count", 0) or 0
    present = checklist.get("present_count", 0) or 0
    pct = checklist.get("completeness_percent", 100.0)
    lines.append(f"  {present}/{total} present ({pct:.0f}%)")
    items = checklist.get("items") or []
    if not items:
        lines.append("  (no items declared for this stage)")
    for it in items:
        mark = "[x]" if it.get("present") else "[ ]"
        desc = f" - {it['description']}" if it.get("description") else ""
        lines.append(f"  {mark} {it.get('item_id')}{desc}")
    missing = checklist.get("missing_item_ids") or []
    if missing:
        lines.append(f"  >>> STILL NEEDS TO BE SUPPLIED: {', '.join(str(m) for m in missing)}")
    return "\n".join(lines)


def render_stage_checklist_report(detail: Dict[str, Any]) -> str:
    """Human-readable rendering of describe_stage()'s numeric completion
    percent and entry/exit evidence checklists -- a percent line plus a
    checkmark/x-mark per declared item and an explicit "still needs to be
    supplied" note for any missing one, so a gap prompts the reader for the
    exact item rather than requiring them to diff raw JSON by eye."""
    pct = detail.get("stage_completion_percent")
    gp, gt = detail.get("gates_passed"), detail.get("gates_total")
    note = detail.get("stage_completion_note")
    lines = [
        f"Stage: {detail.get('stage')}",
        f"Gate completion: {pct if pct is not None else '-'}% "
        f"({gp if gp is not None else '-'}/{gt if gt is not None else '-'} gates passed)"
        + (f" -- {note}" if note else ""),
        "",
        _render_checklist_section("Entry checklist (evidence required before this stage runs)",
                                   detail.get("entry_checklist")),
        "",
        _render_checklist_section("Exit checklist (evidence this stage should have produced)",
                                   detail.get("exit_checklist")),
    ]
    return "\n".join(lines)


def main():
    # BUG FIX (2026-08-28, multi-persona interaction review): 4/5 personas
    # independently hit garbled Traditional-Chinese output (mojibake) as
    # their literal first `dv-harness explain`/`status` call on a stock
    # Windows shell, since CLAUDE.md mandates Chinese output but Python's
    # stdout on Windows defaults to the console's legacy codepage, not
    # UTF-8. Force UTF-8 unconditionally rather than relying on
    # PYTHONIOENCODING/chcp being set by the caller.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass  # non-reconfigurable stream (e.g. redirected to a pipe that already fixed encoding) -- not fatal

    ap = argparse.ArgumentParser(prog="dv-harness", description="DV Agent Harness Edition v15")
    ap.add_argument("--project-root", default=".")
    # DEGRADED-mode probe transport (2026-09-04). Overrides config.json's
    # `degradation.transport` for this invocation. This is the flag that
    # makes the "license 全滿 / farm 塞車" triggers reachable at all from a
    # shipped command path: before it, the only documented way to give them a
    # transport on a PC-side REMOTE_EXECUTION session was to hand-write
    # Python assigning DVHarness.degradation_runner. Applies to every
    # subcommand because the harness is constructed once, below.
    ap.add_argument("--degradation-transport", dest="degradation_transport",
                     default=None, choices=list(TRANSPORT_CHOICES),
                     help="Transport for DEGRADED mode's license/queue probes. "
                          "'auto' (config default) arms one only on real evidence -- a READY "
                          "persistent relay for $VCHOST/$VCHOP, else lmutil+bqueues actually on "
                          "PATH, else nothing. 'local'/'remote_relay' force one; 'off' disables "
                          "resource probing. Overrides config.json's degradation.transport; the "
                          "resolved decision is shown by `dv-harness status`.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # --dry-run (2026-09-03, user spec: "agent 產出完整計畫但不執行, 人可事前
    # 檢視。導入初期與大改動前必用"). Produces the full intended plan/evidence-
    # request for the stage -- real route/agent/protocol decisions, real plan
    # steps, the real required gates, and the byte-exact prompt that would
    # have been sent -- into .dv-harness/dry_run/<stage>-<ts>.json, WITHOUT
    # calling the adapter, submitting any job, or writing any run state. See
    # DVHarness._dry_run_stage() for the exact list of suppressed side
    # effects, and config.json's `dry_run` block to turn it on for every
    # invocation during an onboarding/large-change period.
    _DRY_RUN_HELP = ("Produce the full plan for the stage and STOP: no adapter/LLM call, no job "
                     "submission, no state mutation. Writes a reviewable plan report to "
                     ".dv-harness/dry_run/. ORs with config.json's dry_run.enabled.")

    pstart = sub.add_parser("start")
    pstart.add_argument("--goal", required=True)
    pstart.add_argument("--loop", action="store_true")
    pstart.add_argument("--dry-run", action="store_true", dest="dry_run", help=_DRY_RUN_HELP)

    prun = sub.add_parser("run-stage")
    prun.add_argument("--goal", required=True)
    prun.add_argument("--stage", choices=[s.value for s in Stage])
    prun.add_argument("--dry-run", action="store_true", dest="dry_run", help=_DRY_RUN_HELP)

    sub.add_parser("status")
    sub.add_parser("advance")
    sub.add_parser("stats")

    pset = sub.add_parser("set-stage")
    pset.add_argument("stage", choices=[s.value for s in Stage])

    pmark = sub.add_parser("mark")
    pmark.add_argument("status", choices=[s.value for s in Status])
    pmark.add_argument("--message", default="")

    pexplain = sub.add_parser("explain")
    pexplain.add_argument("--stage", choices=[s.value for s in Stage], default=None)

    # --- Human Control Plane subcommands (write to .dv-harness/control.json,
    # actually read/respected by engine.py's loop()/run_stage() -- see
    # dv_harness/control_plane.py) ---
    ppause = sub.add_parser("pause", help="Stop the autonomous loop cleanly before its next stage.")
    ppause.add_argument("--reason", default="")

    sub.add_parser("resume", help="Clear a PAUSE so the loop may run again.")

    ptakeover = sub.add_parser("takeover", help="Human-control the CURRENT stage; loop()/run_stage() refuse to touch it.")
    ptakeover.add_argument("--message", default="")

    sub.add_parser("release-takeover", help="Release TAKEOVER, returning the stage to the harness.")

    predirect = sub.add_parser("redirect", help="Force the next stage as an explicit, audited human decision.")
    predirect.add_argument("stage", choices=[s.value for s in Stage])
    predirect.add_argument("--reason", default="")

    papprove = sub.add_parser("approve", help="Record a human sign-off for a stage (required for PROMOTION_READINESS/SIGNOFF).")
    # commands.approval_stage_choices() = the graph stages PLUS
    # commands.APPROVAL_ONLY_STAGES (real code-owned approval points that are
    # not graph stages -- see that constant's own comment for why the previous
    # `[s.value for s in Stage]` made capability_evolution.py's Human Approval
    # Gate un-operable by a human). One source, so the parser and the
    # validation in commands.py cannot disagree.
    papprove.add_argument("stage", choices=_commands.approval_stage_choices())
    papprove.add_argument("--note", default="")
    papprove.add_argument("--reviewer-id", default=None)
    papprove.add_argument("--reviewer-confidence", default="HIGH", choices=["HIGH", "MEDIUM", "LOW"])

    pevidence = sub.add_parser("evidence", help="Show the real evidence blocks/gate verdict a stage's last response produced.")
    pevidence.add_argument("--stage", choices=[s.value for s in Stage], default=None)

    pchecklist = sub.add_parser("checklist", help="Human-readable stage completion percent plus entry/exit evidence "
                                                     "checklist (checkmarks/x-marks per item, and an explicit "
                                                     "'still needs to be supplied' list for anything missing) -- "
                                                     "the same describe_stage() data `explain`/`evidence` carry as "
                                                     "raw JSON, rendered for a human instead.")
    pchecklist.add_argument("--stage", choices=[s.value for s in Stage], default=None)

    pcorrect = sub.add_parser("correct", help="Provide a human correction to a stage without re-running the agent.")
    pcorrect.add_argument("stage", choices=[s.value for s in Stage])
    pcorrect.add_argument("--note", required=True)
    pcorrect.add_argument("--reset-attempts", action="store_true")

    pconstraint = sub.add_parser("constraint", help="Manage persisted constraints folded into every subsequent stage prompt.")
    pconstraint.add_argument("--add", default=None)
    pconstraint.add_argument("--list", action="store_true")
    pconstraint.add_argument("--remove", default=None)

    pcosign = sub.add_parser("cosign", help="Durably co-sign a specific DV_JUDGMENT field value (gates.JUDGMENT_FIELDS) "
                                             "so the NEXT evaluate_stage_evidence() re-check can accept it without an "
                                             "inline reviewer wrapper -- see gates.py's Tier-5 section for exact semantics.")
    pcosign.add_argument("stage", choices=[s.value for s in Stage])
    pcosign.add_argument("field_path", help="'<gate_id>/<location>' -- location matches the loc label "
                                             "'dv-harness explain'/'evidence' (or the dashboard's DV Review panel) "
                                             "already shows for a pending field, e.g. 'root_cause_evidence_gate/root_cause'.")
    pcosign.add_argument("--value", required=True, help="The exact bare field value being co-signed, as JSON "
                                                          "(e.g. '\"HIGH\"', 'true', '{\"a\":1}'); falls back to the "
                                                          "raw string if it is not valid JSON.")
    pcosign.add_argument("--reviewer-id", required=True)
    pcosign.add_argument("--reviewer-confidence", default="HIGH", choices=["HIGH", "MEDIUM", "LOW"])

    pblackboard = sub.add_parser("blackboard", help="Real Blackboard.write()/read() access for one topic. Exists so a "
                                                      "Workflow-tool script (JS, no filesystem/Python access of its "
                                                      "own) can have one of its subagents perform a genuine "
                                                      "Blackboard write/read via a real tool call -- see "
                                                      ".claude/workflows/rca-multi-agent-fusion.js's Evidence Fusion "
                                                      "and RCA Review stages.")
    pblackboard_sub = pblackboard.add_subparsers(dest="bb_cmd", required=True)
    pbb_write = pblackboard_sub.add_parser("write", help="Write one Blackboard topic entry.")
    pbb_write.add_argument("topic")
    pbb_write_value = pbb_write.add_mutually_exclusive_group(required=True)
    pbb_write_value.add_argument("--value", help="The value to write, as a JSON string.")
    pbb_write_value.add_argument("--file", help="Path to a JSON file whose parsed content is the value to write.")
    pbb_write.add_argument("--source", default="", help="Who/what produced this value (free text).")
    pbb_write.add_argument("--confidence", default="HIGH", choices=["HIGH", "MEDIUM", "LOW", "UNKNOWN"])
    pbb_read = pblackboard_sub.add_parser("read", help="Read one Blackboard topic entry (null if never written).")
    pbb_read.add_argument("topic")

    plsf = sub.add_parser("lsf", help="Per-job LSF drill-down (GET /api/lsf/jobs[/<job_id>] equivalent).")
    plsf.add_argument("job_id", nargs="?", default=None,
                       help="Show a single job's detail (an error + exit 1 if no such job exists). "
                            "Omit to list every job (same as --list).")
    plsf.add_argument("--list", action="store_true", help="List every job. Implied when job_id is omitted.")

    # --- Real LSF submit/kill/reconcile (dv_harness/lsf_client.py) -----------
    # BUG FIX (2026-08-28, gui-cli-completeness-audit): lsf_client.py's
    # bsub_submit/bjobs_query_many/bkill_job/reconcile_batch were fully
    # implemented and unit-tested but had NO CLI or GUI entry point anywhere
    # -- nothing in the shipped product ever actually called `bsub`/`bjobs`/
    # `bkill`. The `lsf` command above only ever READ whatever per-job JSON
    # files happened to already exist under .dv-harness/lsf/jobs/. These three
    # subcommands are the missing write path: submitting a job, killing a
    # job, and reconciling agent-reported state against live `bjobs` truth
    # writes/refreshes those same JSON files, per CLAUDE.md's "one submitted
    # LSF job = one isolated Job Agent context" and "LSF DONE is not equal to
    # DV PASS" rules.
    plsf_submit = sub.add_parser("lsf-submit", help="Real `bsub` submission; writes/creates the job's "
                                                      ".dv-harness/lsf/jobs/<JOB_ID>.json state file.")
    plsf_submit.add_argument("command", help="The command line bsub should run (e.g. the vcs/simv invocation).")
    plsf_submit.add_argument("--queue", required=True)
    plsf_submit.add_argument("--cores", type=int, default=1)
    plsf_submit.add_argument("--mem-mb", type=int, default=None)
    plsf_submit.add_argument("--run-dir", default=None)
    plsf_submit.add_argument("--pattern", default=None, help="Regression pattern/testcase name for the job snapshot.")
    plsf_submit.add_argument("--options", default=None, help="Sim options string (WAVE/PA/etc) for the job snapshot.")
    plsf_submit.add_argument("--regression-id", default=None)
    plsf_submit.add_argument("--sim-log", default=None)
    # --seed/--fsdb-path (session-snapshot-extension, 2026-09-01): structural
    # JobState fields (see lsf_client.JobState's own docstring comment) --
    # explicit here because job-submission time is exactly the point a
    # caller naturally already knows the seed it is about to run with (and,
    # if waveform is enabled per CLAUDE.md's Waveform Dump User Gate, the
    # FSDB path it will write). Left unset (None) falls back to
    # lsf_client.extract_seed_from_options()/extract_fsdb_path_from_options()
    # at reconcile time if --options happens to carry one of those markers.
    plsf_submit.add_argument("--seed", default=None, help="Simulation seed for the job snapshot.")
    plsf_submit.add_argument("--fsdb-path", default=None, help="FSDB waveform path for the job snapshot, if known at submit time.")
    # --runlimit-min (2026-09-03, gap-close-obsidian-memory phase 4+5): the
    # real `bsub -W <minutes>` wall-clock limit, recorded onto JobState as
    # this job's timeout budget so the Job Memory record written at terminal
    # reconcile can state it. Omitted passes no -W at all (queue default) and
    # honestly records no limit.
    plsf_submit.add_argument("--runlimit-min", type=int, default=None, dest="runlimit_minutes",
                              help="Wall-clock run limit in minutes (bsub -W). Also stored on the job snapshot.")
    # lmstat + scheduler preflight gate (2026-09-03, highest-priority
    # workstream): dv_harness.preflight.run_preflight() runs BEFORE bsub --
    # see lsf_client.bsub_submit_with_preflight(). --skip-preflight is an
    # explicit, audited escape hatch (never a silent default) for the rare
    # case a human has already verified conditions out-of-band; every other
    # invocation is gated.
    plsf_submit.add_argument("--skip-preflight", action="store_true",
        help="Bypass the lmstat/queue/host/disk/workdir/env preflight gate "
             "(dv_harness/preflight.py) and submit directly. Explicit, "
             "audited escape hatch -- never the default.")

    # Standalone preflight gate (2026-09-03): lets a caller (in particular
    # the Preflight/Resource Guard Agent -- .claude/agents/
    # preflight-resource-guard-agent.md) run the exact same
    # license/queue/host/disk/workdir/env gate lsf-submit runs internally,
    # WITHOUT submitting anything -- e.g. to advise a human/agent whether a
    # regression batch is even worth queuing up before spending time
    # building bsub command lines.
    ppreflight = sub.add_parser("preflight", help="Run the real lmstat + scheduler preflight gate "
                                                    "(dv_harness/preflight.py) standalone, without submitting "
                                                    "any job. Exits 1 on BLOCKED.")
    ppreflight.add_argument("--queue", default=None, help="Overrides config.json's preflight.queue for this run.")
    ppreflight.add_argument("--workdir", default=None, help="Overrides config.json's preflight.workdir for this run.")
    ppreflight.add_argument("--license-server", default=None,
                             help="Overrides config.json's preflight.license_server for this run (e.g. 2900@host-a).")
    ppreflight.add_argument("--remote", action="store_true",
                             help="Route checks through the persistent relay (tools/remote/remote_exec.py) "
                                  "instead of running them as local subprocesses -- use this on a Windows-PC-side "
                                  "session in REMOTE_EXECUTION mode. Requires VCHOST/VCHOP env vars and an "
                                  "already-READY relay (see `python tools/remote/remote_exec.py --status`).")

    plsf_kill = sub.add_parser("lsf-kill", help="Real `bkill` on one job id, verifying it actually left RUN/PEND.")
    plsf_kill.add_argument("job_id", type=int)
    plsf_kill.add_argument("--no-verify", action="store_true", help="Skip polling bjobs to confirm the kill took effect.")
    plsf_kill.add_argument("--poll-timeout-s", type=int, default=30)

    plsf_reconcile = sub.add_parser("lsf-reconcile", help="Real `bjobs` query reconciled against each job's "
                                                            "reported state; updates the JSON state file and "
                                                            "reports any WARN/CRITICAL discrepancy (e.g. LSF says "
                                                            "DONE but sim_status is still UNKNOWN -- ANALYSIS_OWED).")
    plsf_reconcile.add_argument("job_id", nargs="*", type=int,
                                 help="Job ids to reconcile. Omit with --all to reconcile every job id that "
                                      "currently has a state file.")
    plsf_reconcile.add_argument("--all", action="store_true",
                                 help="Reconcile every job id under .dv-harness/lsf/jobs/ instead of listing them.")

    # Background job/log monitor (Part 2 of the 2026-09-01 sim-output-layout
    # spec): regression_reporter.ensure_watcher_running()/stop_watcher()/
    # watcher_status() are real and tested (dv_harness_tests/
    # test_regression_reporter.py's TestWatcherLifecycle) but had no CLI
    # entry point -- these three subcommands are the missing invocation path.
    plsf_watch_start = sub.add_parser("lsf-watch-start",
        help="Start the background job/log monitor (Part 2 of the "
             "2026-09-01 sim-output-layout spec) if not already running.")
    plsf_watch_start.add_argument("--vcuser", required=True)
    plsf_watch_start.add_argument("--uvm-root-path", default=None)
    plsf_watch_start.add_argument("--interval-minutes", type=int, default=5)

    sub.add_parser("lsf-watch-stop", help="Stop the background job/log monitor.")
    sub.add_parser("lsf-watch-status", help="Report whether the background job/log monitor is running.")

    # BUG FIX (poster-compliance audit, "異常自動 Kill Job"): evaluate_auto_kill()
    # in lsf_client.py existed with no caller anywhere -- this is the missing
    # explicit, human-invoked scan/kill path. It never runs on its own; it only
    # fires when this subcommand (or a future explicit scheduled call to it) is
    # actually invoked -- see lsf_client.evaluate_auto_kill()'s docstring for
    # exactly which .dv-harness/lsf/early_fail_policy.json toggles drive it.
    ppueue = sub.add_parser("pueue", help="Real LOCAL PC-side task orchestration via pueue "
        "(dv_harness/pueue_client.py). Sequences local/remote_exec.py-driven harness steps as "
        "a real dependency chain; NEVER manages a real farm job's own lifecycle -- the real "
        "farm submission is one caller-supplied step command (which must be the "
        "preflight-gated `dv-harness lsf-submit ...`, never a raw bsub/sbatch), and pueue's "
        "role ends the moment that command's process exits (ongoing farm-job tracking stays "
        "lsf-watch-start).")
    ppueue_sub = ppueue.add_subparsers(dest="pueue_cmd", required=True)
    ppueue_add = ppueue_sub.add_parser("add", help="Enqueue one local task; starts the pueued "
        "daemon first if it is not already running.")
    ppueue_add.add_argument("command", help="Shell command this task runs (e.g. a "
        "`python tools/remote/remote_exec.py \"...\"` call, or a local build/lint command). "
        "A command that would run a raw `bsub`/`sbatch` is REFUSED (exit 2, "
        "UNGATED_FARM_SUBMISSION) because it would bypass the preflight gate -- submit "
        "through `dv-harness lsf-submit ...` as the task command instead.")
    ppueue_add.add_argument("--label", default=None)
    ppueue_add.add_argument("--after", type=int, action="append", default=None,
        help="Task id this task depends on (repeatable). Only starts once every listed "
             "dependency has SUCCEEDED; fails automatically if one of them fails.")
    ppueue_add.add_argument("--group", default=None, help="Overrides config.json's pueue.group.")
    ppueue_add.add_argument("--working-directory", default=None)
    ppueue_sub.add_parser("status", help="Real `pueue status -j`.").add_argument(
        "--group", default=None)
    ppueue_log = ppueue_sub.add_parser("log", help="Real `pueue log -j` for one or more tasks.")
    ppueue_log.add_argument("task_ids", nargs="*", type=int)
    ppueue_log.add_argument("--full", action="store_true")
    ppueue_wait = ppueue_sub.add_parser("wait", help="Poll a task until Done; exits 1 if its "
        "result was not Success (a nonzero exit, a killed task, or a failed dependency).")
    ppueue_wait.add_argument("task_id", type=int)
    ppueue_wait.add_argument("--timeout", type=int, default=1800)
    ppueue_chain = ppueue_sub.add_parser("chain", help="Enqueue the real build->verify->submit->"
        "fsdbreport local-PC chain as dependent pueue tasks. Every step's command is exactly "
        "what you pass here -- this never fabricates a bsub/remote_exec.py command itself; "
        "omit a step to leave it out of the chain. Every step is preflight-gate-checked "
        "BEFORE any task is enqueued: one raw `bsub`/`sbatch` step refuses the whole chain.")
    ppueue_chain.add_argument("--build", default=None)
    ppueue_chain.add_argument("--verify", default=None)
    ppueue_chain.add_argument("--submit", default=None)
    ppueue_chain.add_argument("--fsdbreport", default=None)
    ppueue_chain.add_argument("--group", default=None)

    plsf_autokill = sub.add_parser("lsf-auto-kill-scan",
        help="Scan every RUNNING job under .dv-harness/lsf/jobs/ against "
             ".dv-harness/lsf/early_fail_policy.json via evaluate_auto_kill(); "
             "bkill (exact job id, verified) any job it flags. Human/scheduler-"
             "invoked only -- never runs by itself.")
    plsf_autokill.add_argument("--dry-run", action="store_true",
        help="Report should_kill/reason for each RUNNING job without calling bkill.")

    # BUG FIX (2026-08-28, gui-cli-completeness-audit): stage_profile_report.py
    # renders real, already-collected wall-clock/token/tool-call/retry data
    # per stage (engine.py wires StageExecutionProfiler into every real stage
    # run) but had no CLI or GUI entry point at all -- the only way to see it
    # was running the module as a standalone script outside `dv-harness`.
    sub.add_parser("stage-profile", help="Per-stage wall-clock/token/tool-call/retry report plus aggregate "
                                          "parallelism efficiency, from data engine.py already collects on "
                                          "every real stage run. See dv_harness/stage_profile_report.py.")

    # 2026-09-04, stage-progress-display gap-close: run_stage() already PRINTS
    # and SAVES a stage-start/stage-done display at every real stage boundary
    # (engine._emit_stage_start_display/_emit_stage_done_display). This is the
    # re-read surface for those saved reports -- scrollback is lost, the report
    # files are not.
    pstage_report = sub.add_parser("stage-report",
        help="Re-render a saved stage start/done progress report "
             "(.dv-harness/stage_reports/), or list what has been saved.")
    pstage_report.add_argument("stage", nargs="?",
        help="Stage id to show the latest report for; omit to list all saved reports.")
    pstage_report.add_argument("--phase", choices=["start", "done"],
        help="Restrict to the stage-start or stage-done report.")
    pstage_report.add_argument("--list", action="store_true",
        help="List matching report files instead of printing the latest one's content.")

    # BUG FIX (2026-08-28, plan-remote-control-wiring design pass):
    # dv_harness/remote_control.py's session/gate substrate (bootstrap_session/
    # validate_and_transition/get_status) was complete, tested, and gated by 4
    # real registered gates -- but had no caller anywhere. Per its own
    # docstring, the real network transport (SSH, or Claude Code's own Remote
    # Control feature) stays out of scope here; this only gives it a real
    # local execution/audit binding, matching the lsf-submit/lsf-kill/
    # lsf-reconcile precedent above.
    prc = sub.add_parser("remote-control", help="Real state/gate binding for the Human Control Plane commands "
                                                  "(STATUS/WHY/EVIDENCE/REVIEW/HYPOTHESIS/PAUSE/RESUME/REDIRECT/"
                                                  "APPROVE/REJECT/STOP/TAKEOVER) arriving over an active Claude "
                                                  "Code Remote Control session. See dv_harness/remote_control.py "
                                                  "for exactly what this does and does not do.")
    prc_sub = prc.add_subparsers(dest="rc_cmd", required=True)
    prc_bootstrap = prc_sub.add_parser("bootstrap", help="Establish a new session, landing directly on RUNNING "
                                                           "(fixes the dead-end STARTING state "
                                                           "REMOTE_CONTROL_START.ps1 used to hand-write).")
    prc_bootstrap.add_argument("--host", default=None)
    prc_bootstrap.add_argument("--working-directory", default=None)
    prc_bootstrap.add_argument("--session-id", default=None)
    prc_sub.add_parser("status", help="Read-only: current session.json plus the most recent audit entry.")
    prc_cmd = prc_sub.add_parser("cmd", help="Validate and apply one Human Control Plane command through the "
                                              "real supervisory/transition/audit/replay gates.")
    prc_cmd.add_argument("command", choices=sorted(
        ["STATUS", "WHY", "EVIDENCE", "REVIEW", "HYPOTHESIS", "PAUSE", "RESUME", "REDIRECT",
         "APPROVE", "REJECT", "STOP", "TAKEOVER"]))
    prc_cmd.add_argument("--target-stage", default=None, choices=[s.value for s in Stage], metavar="STAGE",
                          help="Required for APPROVE/REJECT/REDIRECT/STOP/TAKEOVER.")
    prc_cmd.add_argument("--reason", default=None)
    prc_cmd.add_argument("--actor", default=None, help="Defaults to the current OS user, same as other commands.")
    prc_cmd.add_argument("--env-mode", default="SYSTEM_LEVEL_ENV_MODE",
                          choices=["SUBSYSTEM_ENV_MODE", "SYSTEM_LEVEL_ENV_MODE"])

    paudit = sub.add_parser("audit", help="Who changed what, when: the last N events.jsonl entries plus current "
                                           "control.json corrections/approvals/approval_history/cosigns.")
    paudit.add_argument("--limit", type=int, default=50)

    # gh CLI + PR-only governance policy (2026-09-03, L5 governance
    # workstream): the real enforcement point behind "an agent may branch/
    # commit/open a PR, but must never merge/push directly into main/master
    # -- human review via PR is the only path onto those branches". Invoked
    # by the real git hook templates under tools/git-hooks/ -- see
    # dv_harness/git_governance.py for the full detection/decision logic.
    pgg = sub.add_parser("git-guard", help="PR-only governance gate for main/master: blocks a direct git "
                                            "push/merge into a protected branch from a detected AI-agent "
                                            "environment. See dv_harness/git_governance.py and "
                                            "tools/git-hooks/.")
    pgg.add_argument("--check", required=True, choices=["pre-push", "pre-merge-commit"],
                      help="Which git hook is calling this. pre-push reads proposed refspecs from "
                           "stdin (githooks(5)); pre-merge-commit takes --branch instead.")
    pgg.add_argument("--branch", default=None,
                      help="Current branch (pre-merge-commit only) -- the hook script supplies "
                           "`git rev-parse --abbrev-ref HEAD`. Ignored/unused for --check pre-push.")

    # Research-Capability Evolution master prompt sections 19/53 -- the
    # `/research` front door, in this repo's own native command mechanism.
    # `.claude/commands/` does not exist here and never has, so section 19's
    # explicit fallback applies ("implement equivalent behavior using the
    # repository's native mechanism rather than forcing this exact syntax").
    # This parser holds no business logic of its own: it hands its arguments
    # to commands.cmd_research(), which routes through
    # router.resolve_research_intent()/research_route_plan() -- the SAME
    # functions a natural-language research request goes through, never a
    # second implementation.
    pres = sub.add_parser("research",
        help="Route a research request (one or more external technical documents) into the "
             "installed research-ingestion skill + research-architect agent + Human Approval "
             "Gate. Prints the resolved intent and the ordered route; it does not ingest, "
             "analyze or approve anything itself.")
    pres.add_argument("documents", nargs="*", default=[],
        help="Document path(s). More than one selects RESEARCH_MULTI_DOCUMENT (one independent "
             "ResearchEvidenceCard per document first, master prompt section 52).")
    pres.add_argument("--compare", action="store_true",
        help="Section 53: standard analysis + stronger prior-evidence comparison.")
    pres.add_argument("--impact", action="store_true",
        help="Section 53: current-L5 architecture-impact emphasis.")
    pres.add_argument("--deep", action="store_true",
        help="Section 53: extended evidence + contradiction + benchmark analysis.")
    pres.add_argument("--focus", default=None, choices=list(RESEARCH_FOCUS_DOMAINS),
        help="Section 53: narrow emphasis to one domain. Emphasis only -- the route is unchanged.")
    pres.add_argument("--request", default="",
        help="A natural-language research request, classified by the same "
             "router.resolve_research_intent() an unassisted request goes through. Used only "
             "when no mode flag and at most one document are given.")

    paudit_self = sub.add_parser("self-audit",
        help="Run the 23 harness self-audit gates (registry/skill/pipeline/protocol-catalog "
             "meta-consistency) against the harness's OWN current repo state -- not per-DUT "
             "stage evidence. See dv_harness/self_audit.py.")
    paudit_self.add_argument("--gate", action="append", default=None,
        help="Run only this gate id; repeatable. Omit to run all 23 (same as --all).")
    paudit_self.add_argument("--all", action="store_true")
    paudit_self.add_argument("--smoke", action="store_true",
        help="For gates with no real harness-state source file, run against a constructed "
             "representative payload to prove the SCRIPT works (SCRIPT_SMOKE_PASS/FAIL) -- "
             "not a verdict on current state, distinct from PASS/FAIL/NO_SOURCE_DATA.")

    psignoff = sub.add_parser("signoff-export", help="One-click final signoff export: bundle vPlan/"
                                                       "blackboard signoff+regression+requirements+findings "
                                                       "state/stage-execution telemetry/pattern registry/"
                                                       "generated UVM testbench source/regression manifest "
                                                       "into a single out dir, plus a fresh self-audit result, "
                                                       "with a manifest.json recording what was actually "
                                                       "present. See dv_harness/signoff_export.py.")
    psignoff.add_argument("--out", required=True, help="Directory to write the signoff bundle into.")
    psignoff.add_argument("--require-signoff-pass", action="store_true",
                          help="Refuse to export unless this project's REAL SIGNOFF stage gate has "
                               "passed (state.json stages.SIGNOFF.status == PASS). Off by default "
                               "because signoff_bundle_completeness_gate -- one of the 9 SIGNOFF "
                               "gates -- consumes a bundle as its own input, so a bundle must be "
                               "producible before SIGNOFF can pass. Either way the bundle records "
                               "the real stage status and a bundle_kind of SIGNOFF_GATE_VERIFIED "
                               "or PRE_SIGNOFF_GATE_INPUT.")

    pkc = sub.add_parser("knowledge", help="Shared, cross-user knowledge center on a fixed Linux-server "
                                            "path (Engineering/Organizational Memory + Corner-Case Library). "
                                            "See dv_harness/knowledge_center.py.")
    pkc_sub = pkc.add_subparsers(dest="kc_cmd", required=True)
    pkc_setup = pkc_sub.add_parser("setup", help="Interactively ask for (never assume/guess) the shared "
                                                  "knowledge center's Linux-server path, per CLAUDE.md's "
                                                  "SSH/Remote Transport Connection Intake rule.")
    pkc_setup.add_argument("--remote-root", default=None,
        help="Skip the interactive prompt and use this path directly (for scripted setup). "
             "Still requires --yes to actually write it.")
    pkc_setup.add_argument("--hop-script", default=None)
    pkc_setup.add_argument("--yes", action="store_true", help="Required together with --remote-root "
                                                                "to skip the interactive confirmation.")
    pkc_setup.add_argument("--disable", action="store_true", help="Turn the shared knowledge center back off.")
    pkc_sub.add_parser("status", help="Show current knowledge_center config + a live --ping of the server.")
    pkc_search = pkc_sub.add_parser("search")
    pkc_search.add_argument("--category", default="")
    pkc_search.add_argument("--protocol", default="")
    pkc_search.add_argument("--text", default="")
    pkc_search.add_argument("--limit", type=int, default=8)
    pkc_deprecate = pkc_sub.add_parser("deprecate", help="Mark a shared record RETRACTED (wrong / superseded).")
    pkc_deprecate.add_argument("record_id")
    pkc_deprecate.add_argument("--category", required=True)
    pkc_deprecate.add_argument("--protocol", required=True)
    pkc_deprecate.add_argument("--reason", required=True)
    pkc_confirm = pkc_sub.add_parser("confirm", help="Re-confirm a shared record with fresh evidence "
                                                       "(resets its staleness clock; clears NEEDS_REVALIDATION).")
    pkc_confirm.add_argument("record_id")
    pkc_confirm.add_argument("--category", required=True)
    pkc_confirm.add_argument("--protocol", required=True)
    pkc_dbinfo = pkc_sub.add_parser("db-info", help="Who added/updated/retracted what across the shared "
                                                      "knowledge center, and when -- the DB-wide activity "
                                                      "log, not any single record's own history.")
    pkc_dbinfo.add_argument("--category", default="")
    pkc_dbinfo.add_argument("--protocol", default="")
    pkc_dbinfo.add_argument("--action", default="", choices=["", "CREATED", "RETRACTED", "CONFIRMED"])
    pkc_dbinfo.add_argument("--limit", type=int, default=100)

    puser = sub.add_parser("user-info", help="Who has used THIS project-root deployment, and when "
                                              "(inferred login/logout sessions from events.jsonl's "
                                              "CLI_ACCESS/GUI_ACCESS + control-plane events). "
                                              "See dv_harness/user_info.py.")
    puser.add_argument("--limit", type=int, default=200)

    psave = sub.add_parser("save-session", help="Snapshot the current run-state layer (state/control/"
                                                 "blackboard/plans/react/agents/telemetry/config/events) "
                                                 "under .dv-harness/sessions/<name>/ -- never the Memory "
                                                 "Hierarchy/Corner-Case Library, which is durable knowledge, "
                                                 "not session state. See dv_harness/session_snapshot.py.")
    psave.add_argument("--name", default=None, help="Omit for an auto timestamp name.")
    psave.add_argument("--note", default="")

    prestore = sub.add_parser("restore-session", help="Restore a previously saved run-state snapshot. "
                                                        "Auto-backs-up the state being overwritten first "
                                                        "(unless --no-backup) so this is never one-way.")
    prestore.add_argument("name", nargs="?", default=None,
        help="Session name to restore. Omit (or use --list) to just list what's available.")
    prestore.add_argument("--list", action="store_true")
    prestore.add_argument("--no-backup", action="store_true")
    prestore.add_argument("--require-sha-match", action="store_true",
        help="Refuse to restore if the current git SHA differs from the snapshot's saved git_sha "
             "(CLAUDE.md's 'same source/build/config identity' rule enforced at restore time).")

    prp = sub.add_parser("run-profile", help="run_profile.json: reverse-derive the machine-readable IR of a "
                                              "generated environment's Makefile (its sole execution authority), "
                                              "and generate the justfile an agent must use instead of composing "
                                              "vcs/simv command lines itself. See dv_harness/uvm_generator/"
                                              "run_profile.py.")
    prp_sub = prp.add_subparsers(dest="rp_cmd", required=True)
    prp_extract = prp_sub.add_parser("extract", help="Parse a Makefile and write run_profile.json.")
    prp_extract.add_argument("--makefile", required=True, help="Path to the environment's Makefile.")
    prp_extract.add_argument("--out", required=True, help="Where to write run_profile.json.")
    prp_extract.add_argument("--target-ip", required=True, help="Upper-case protocol name, e.g. USB, PCIE.")
    prp_extract.add_argument("--ip-prefix", required=True, help="Lower-case file/class prefix, e.g. usb_.")
    prp_justfile = prp_sub.add_parser("justfile", help="Generate a justfile (+ its standalone, "
                                                         "dv_harness-independent argument validator) from an "
                                                         "already-extracted run_profile.json.")
    prp_justfile.add_argument("--profile", required=True, help="Path to run_profile.json.")
    prp_justfile.add_argument("--out", required=True, help="Where to write the justfile.")

    penvm = sub.add_parser("env-manifest", help="env.manifest.json: generated, diffable, git-tracked fact file "
                                                   "with three layers -- vip_config (a real UVM simv's own "
                                                   "already-resolved VIP config dump), dut_facts (verible-parsed "
                                                   "RTL ports/params/signals plus a structured register-map "
                                                   "input), env_topology (uvm_top component hierarchy + "
                                                   "+UVM_CONFIG_DB_TRACE). See dv_harness/env_manifest.py.")
    penvm_sub = penvm.add_subparsers(dest="envm_cmd", required=True)
    penvm_gen = penvm_sub.add_parser("generate", help="Build env.manifest.json from whatever real inputs are "
                                                         "supplied. Any input omitted reports its layer "
                                                         "NOT_AVAILABLE with an honest reason -- never a "
                                                         "fabricated example.")
    penvm_gen.add_argument("--out", required=True, help="Where to write env.manifest.json.")
    penvm_gen.add_argument("--rtl-file", action="append", default=None, dest="rtl_files",
                            help="A real RTL source file to parse via verible (repeatable). Omit entirely to "
                                 "report dut_facts.rtl as NOT_AVAILABLE.")
    penvm_gen.add_argument("--register-map", default=None, dest="register_map_path",
                            help="Path to a register-map JSON file conforming to "
                                 "dv_harness/schemas/register_map.schema.json. Omit to report "
                                 "dut_facts.registers as NOT_AVAILABLE.")
    penvm_gen.add_argument("--vip-config-dump", default=None, dest="vip_config_dump_path",
                            help="Path to a real vip_config dump JSON produced by a live UVM simv run (see "
                                 "dv_harness/uvm_generator/templates/uvm_env_manifest/dv_env_manifest_pkg.sv). "
                                 "Omit to report vip_config as NOT_AVAILABLE.")
    penvm_gen.add_argument("--topology-dump", default=None, dest="topology_dump_path",
                            help="Path to a real component_hierarchy dump JSON produced by the same template. "
                                 "Omit to report env_topology.component_hierarchy as NOT_AVAILABLE.")
    penvm_gen.add_argument("--config-db-trace-log", default=None, dest="config_db_trace_log_path",
                            help="Path to a real sim log from a run with +UVM_CONFIG_DB_TRACE set. Omit to "
                                 "report env_topology.config_db_trace as NOT_AVAILABLE.")
    penvm_gen.add_argument("--verible-bin", default=None, help="Override the verible-verilog-syntax binary name.")
    penvm_gen.add_argument("--designware-home", default=None, dest="designware_home",
                            help="VIP install tree to scan for package versions / release notes / feature "
                                 "matrices. Omit to use the real $DESIGNWARE_HOME environment variable; "
                                 "vip_config.vip_release reports NOT_AVAILABLE when neither is set.")
    penvm_gen.add_argument("--user-guide-ref", action="append", default=None,
                            dest="user_guide_reference_paths",
                            help="Path to a .reference.json produced by `dv-harness vip-user-guide distill` "
                                 "(repeatable). Only the POINTER is recorded -- the guide's own text is "
                                 "never read into env.manifest.json. Omit to report "
                                 "vip_config.user_guide_refs as NOT_AVAILABLE.")
    penvm_gen.add_argument("--soc-arch-map", default=None, dest="soc_arch_map_path",
                            help="Path to a SoC architecture-map JSON conforming to "
                                 "dv_harness/schemas/soc_arch_map.schema.json (address map + clock/reset "
                                 "topology from the project's own SoC spec pipeline). Omit to report "
                                 "dut_facts.address_map and dut_facts.clock_reset as NOT_AVAILABLE.")
    penvm_gen.add_argument("--testplan-sources", default=None, dest="testplan_sources_path",
                            help="Path to a testplan-sources JSON conforming to "
                                 "dv_harness/schemas/testplan_sources.schema.json (the project's real "
                                 "testlist + vPlan items + coverage model). Omit to report "
                                 "env_topology.testplan_correspondence as NOT_AVAILABLE.")

    pvug = sub.add_parser("vip-user-guide", help="OFFLINE distillation of a VIP user guide (or any protocol "
                                                    "spec / programming guide) into a bounded reference index "
                                                    "plus a full-text extract, so the guide itself is never "
                                                    "loaded into runtime context. See "
                                                    "dv_harness/vip_user_guide_distill.py.")
    pvug_sub = pvug.add_subparsers(dest="vug_cmd", required=True)
    pvug_d = pvug_sub.add_parser("distill", help="Distil ONE real document. Writes <stem>.fulltext.txt "
                                                    "(targeted-read target), <stem>.reference.md (bounded "
                                                    "section index) and <stem>.reference.json (the record "
                                                    "`env-manifest generate --user-guide-ref` consumes).")
    pvug_d.add_argument("--source", required=True, help="Real .pdf / .txt / .md document to distil.")
    pvug_d.add_argument("--out-dir", required=True, help="Directory to write the three artifacts into.")
    pvug_d.add_argument("--title", default=None, help="Document title; defaults to the source file's stem.")
    pvug_d.add_argument("--doc-kind", default="vip_user_guide",
                         help="What the document actually is: vip_user_guide (default), protocol_spec, "
                              "programming_guide, ...")

    pfsdb = sub.add_parser("fsdb-report", help="Run the real `fsdbreport` CLI tool against an FSDB file and "
                                                 "parse/emit its text report. See dv_harness/fsdb_report.py.")
    pfsdb.add_argument("--fsdb", required=True, help="Path to the .fsdb file.")
    pfsdb.add_argument("--out", default=None, help="Write the result JSON here instead of stdout.")
    pfsdb.add_argument("--fsdbreport-bin", default="fsdbreport")
    pfsdb.add_argument("--timeout", type=int, default=60)
    # Provenance for the normalized_evidence row this command now lands via
    # vip_distill.distill_fsdbreport(). All three are optional -- an
    # fsdbreport extract taken outside any registered LSF job is real
    # evidence too, and vip_distill stores them as honest NULLs rather than
    # inventing a job/pattern the run did not have.
    pfsdb.add_argument("--topic", default=None,
                        help="What signal-level question this extract answers (e.g. 'lfps_handshake'). "
                             "Recorded on the normalized_evidence row.")
    pfsdb.add_argument("--job-id", type=int, default=None,
                        help="LSF job id this FSDB came from, if any. Recorded on the "
                             "normalized_evidence row so it joins to that job's other evidence.")
    pfsdb.add_argument("--pattern", default=None,
                        help="Pattern/testcase name this FSDB came from, if any.")

    psimlog = sub.add_parser("sim-log-analyze", help="Real sim.log marker parsing/classification/epilogue "
                                                        "extraction. See dv_harness/sim_log_analysis.py.")
    psimlog_group = psimlog.add_mutually_exclusive_group(required=True)
    psimlog_group.add_argument("--log", default=None, help="Path to a sim.log file.")
    psimlog_group.add_argument("--log-text", default=None, help="Inline log text (for testing).")

    # Cross-run time dimension (2026-09-03). Reads .dv-harness/evidence/
    # evidence.duckdb READ-ONLY -- never creates or migrates it, so running
    # this while a background `lsf-watch` writer is live is safe.
    ptrend = sub.add_parser("trend", help="Cross-run trend over the evidence DB: daily pass-rate/coverage/"
                                            "runtime/license-hour curves plus day-over-day, PASS->FAIL "
                                            "regressions bisected to the responsible RTL commit range, and "
                                            "passed-but-abnormally-slow runtime anomalies. See "
                                            "dv_harness/trend_analysis.py.")
    ptrend.add_argument("--json", action="store_true", help="Emit the raw report dict instead of the text table.")
    ptrend.add_argument("--seats-per-job", type=float, default=None,
                         help="Simulator seats one running job is modelled as holding, for the license-hours "
                              "curve (default 1). This harness reads no license manager -- license_hours is a "
                              "derived estimate from real measured job runtime; see trend_analysis."
                              "LICENSE_HOURS_MODEL.")
    ptrend.add_argument("--rtl-pathspec", action="append", default=None,
                         help="Git pathspec deciding which commits in a regression's range count as RTL "
                              "(repeatable; default *.v/*.sv/*.svh/*.vh).")
    ptrend.add_argument("--min-baseline-samples", type=int, default=None,
                         help="Prior PASS runs a pattern needs before any runtime-anomaly verdict is issued "
                              "for it (default 5).")
    ptrend.add_argument("--ratio-threshold", type=float, default=None,
                         help="Flag a passing job at or above this multiple of its pattern's baseline median "
                              "runtime (default 2.0).")
    ptrend.add_argument("--z-threshold", type=float, default=None,
                         help="Flag a passing job at or above this many standard deviations over its "
                              "pattern's baseline mean runtime (default 3.0).")

    prt = sub.add_parser("regression-tier", help="Tiered regression cadence (SMOKE/NIGHTLY/WEEKLY): which "
                                                    "tests, what time budget, which UVM_FATAL escalation "
                                                    "threshold. See dv_harness/regression_tiers.py.")
    prt_sub = prt.add_subparsers(dest="rt_cmd", required=True)
    prt_sub.add_parser("list", help="Print every tier's effective policy (defaults + config.json overrides).")
    prt_plan = prt_sub.add_parser("plan", help="Resolve the concrete test list one tier would run, from the "
                                                 "harness-COMPUTED change-impact selection "
                                                 "(.dv-harness/regression/computed_selection.json). Read-only.")
    prt_plan.add_argument("tier", help="SMOKE | NIGHTLY | WEEKLY")
    prt_plan.add_argument("--base-sha", default=None,
                           help="Recompute the change-impact selection against this base revision first "
                                "(default: use the already-computed selection on disk, if any).")
    prt_start = prt_sub.add_parser("start", help="Declare that the regression now being submitted belongs to "
                                                   "this tier -- writes .dv-harness/regression/active_tier.json, "
                                                   "which the lsf-watch reconciliation loop reads to apply this "
                                                   "tier's UVM_FATAL escalation threshold instead of the flat one.")
    prt_start.add_argument("tier", help="SMOKE | NIGHTLY | WEEKLY")
    prt_start.add_argument("--base-sha", default=None,
                           help="Recompute the change-impact selection against this base revision first.")
    prt_sub.add_parser("status", help="Print the active-tier record (null if no tiered run is declared).")
    prt_sub.add_parser("clear", help="Clear the active-tier record; escalation returns to the flat threshold.")

    pvplan = sub.add_parser("vplan-export", help="Write a real, openable vPlan .xlsx workbook (verification_plan + "
                                                   "coverage_summary sheets) from a JSON list of structured "
                                                   "verification-item dicts, validated against real pattern-dir/"
                                                   "dispatcher-file/task-declaration-source evidence first. See "
                                                   "dv_harness/vplan_writer/writer.py.")
    pvplan.add_argument("items_json", help="Path to a JSON file containing a list of VPlanItem dicts.")
    pvplan.add_argument("--out", required=True, help="Output .xlsx path.")
    pvplan.add_argument("--protocol", required=True, help="Protocol/IP name (e.g. USB, PCIe) -- documentation-only, "
                                                             "carried into the workbook, never used to pick a "
                                                             "hardcoded directory layout.")
    pvplan.add_argument("--pattern-dir", required=True, help="Directory of real pattern/command.txt files.")
    pvplan.add_argument("--pattern-glob", default="*.txt")
    pvplan.add_argument("--dispatcher-file", required=True, help="Runtime dispatcher source file (e.g. "
                                                                    "dv_uvm_pattern_pool.svh) scanned for real "
                                                                    "pattern-name string literals.")
    pvplan.add_argument("--dispatcher-pattern-regex", default=r'"(?P<pattern>[A-Za-z0-9_]+)"')
    pvplan.add_argument("--task-declaration-source", action="append", default=None, dest="task_declaration_sources",
                         help="Glob (e.g. 'tb/tests/*.sv') scanned for real task/class declarations. Repeatable.")
    pvplan.add_argument("--task-declaration-regex",
                         default=r'\btask\s+automatic\s+(?P<task>[A-Za-z0-9_]+)\b|\bclass\s+(?P<task2>[A-Za-z0-9_]+)\s+extends\b')
    pvplan.add_argument("--known-check-name", action="append", default=None, dest="known_check_names",
                         help="A known scoreboard check_name (repeatable). Omit entirely to skip the "
                              "checkers_active cross-check.")
    pvplan.add_argument("--constraint-declaration-source", action="append", default=None,
                         dest="constraint_declaration_sources",
                         help="Glob (e.g. 'tb/tests/*.sv') scanned for real 'constraint <name> { ... }' "
                              "declarations (4th vPlan validation rule, 2026-09-01). Repeatable. Omit "
                              "both this and --known-constraint-name to skip the constraint_items-"
                              "exist-in-SV-source cross-check entirely.")
    pvplan.add_argument("--constraint-declaration-regex",
                         default=r'\bconstraint\s+(?P<constraint>[A-Za-z0-9_]+)\b')
    pvplan.add_argument("--known-constraint-name", action="append", default=None, dest="known_constraint_names",
                         help="A known SV constraint name (repeatable), bypassing source scanning "
                              "(same relationship to --constraint-declaration-source as "
                              "--known-check-name has to scoreboard checks).")
    pvplan.add_argument("--sheet", action="append", default=None, dest="sheets",
                         help="Sheet registry key (repeatable). Default: verification_plan, coverage_summary.")
    pvplan.add_argument("--workbook-title", default=None)

    # --- Structured deliberate-exemption records (2026-09-03,
    # exemptions-yaml, see dv_harness/exemptions.py's own module docstring
    # for the full design rationale). `valid_until` is REQUIRED on every
    # entry -- schema-enforced, no "no expiry" escape hatch -- so `check`/
    # `expire-report` have something real to report once an entry lapses.
    pexempt = sub.add_parser("exemptions", help="Structured record of every check/gate/assertion/coverage-bin "
                                                  "deliberately disabled or relaxed for a cited reason (e.g. an "
                                                  "IP/tooling restriction), so an agent never re-litigates or "
                                                  "silently deletes a deliberate exemption. Every entry carries a "
                                                  "REQUIRED valid_until -- an expired entry surfaces via `check`/"
                                                  "`expire-report`, it never stays in force forever unreviewed. "
                                                  "See dv_harness/exemptions.py.")
    pexempt_sub = pexempt.add_subparsers(dest="exemptions_cmd", required=True)

    pexempt_list = pexempt_sub.add_parser("list", help="List exemption entries as JSON.")
    pexempt_list.add_argument("--path", default=None, help="Override exemptions.yaml path "
                                                              "(default: .dv-harness/exemptions/exemptions.yaml "
                                                              "under --project-root).")
    pexempt_list.add_argument("--expired-only", action="store_true", dest="expired_only")
    pexempt_list.add_argument("--as-of", default=None, dest="as_of",
                               help="YYYY-MM-DD to evaluate expiry against (default: today). Only affects "
                                    "--expired-only.")

    pexempt_add = pexempt_sub.add_parser("add", help="Append one new exemption entry. Schema-validated before "
                                                        "write -- a missing/malformed field (valid_until included) "
                                                        "refuses the write rather than persisting a bad record.")
    pexempt_add.add_argument("--id", default=None, help="Omit to auto-generate EXEMPT-NNNN.")
    pexempt_add.add_argument("--check-id", required=True, dest="check_id",
                              help="The exact check/gate/assertion/coverage-bin being exempted.")
    pexempt_add.add_argument("--reason", required=True, help="Free text: the actual engineering why.")
    pexempt_add.add_argument("--basis-document", required=True, dest="basis_document",
                              help="A citation: file path (optionally with a line range), doc reference, or "
                                   "ticket id. Never empty.")
    pexempt_add.add_argument("--owner", required=True, help="Accountable person/team, not a role placeholder.")
    pexempt_add.add_argument("--valid-until", required=True, dest="valid_until",
                              help="YYYY-MM-DD. REQUIRED -- no permanent exemptions.")
    pexempt_add.add_argument("--protocol", default=None, help="Optional protocol/IP scope, e.g. USB.")
    pexempt_add.add_argument("--notes", default=None)
    pexempt_add.add_argument("--path", default=None)

    pexempt_check = pexempt_sub.add_parser("check", help="Report expired vs. active entries. Exits 1 if any "
                                                            "entry's valid_until has passed (CI-friendly), same "
                                                            "convention as the generated environment's own "
                                                            "dv-check run_all.sh.")
    pexempt_check.add_argument("--path", default=None)
    pexempt_check.add_argument("--as-of", default=None, dest="as_of")

    pexempt_report = pexempt_sub.add_parser("expire-report", help="Write .dv-harness/exemptions/review_queue.json "
                                                                     "listing every currently-expired entry. Reports "
                                                                     "only; use `escalate` to also file each one as a "
                                                                     "real blocking question. Exits 1 if any entry "
                                                                     "expired (CI-friendly).")
    pexempt_report.add_argument("--path", default=None)
    pexempt_report.add_argument("--out", default=None, help="Override review_queue.json output path.")
    pexempt_report.add_argument("--as-of", default=None, dest="as_of")

    # 2026-09-04 (vplan-single-source-of-truth gap-close): `expire-report`
    # above writes review_queue.json and stops. That file was the documented
    # hand-off point for a consumer that did not exist, so an expired
    # exemption reached a human only if someone ran this command by hand.
    # `escalate` files each expired entry as a real Tier-3 blocking question
    # in the real QuestionQueueStore -- with a Q-ID, an owner and a digest
    # slot, like anything else the harness cannot assume its way past.
    pexempt_escalate = pexempt_sub.add_parser(
        "escalate",
        help="File every currently-expired exemption as a real Tier-3 blocking question in the "
              "question queue (and refresh review_queue.json). Idempotent: the question_key is "
              "derived from the exemption id, so re-running files nothing new. Exits 1 if any "
              "expired entry exists, whether or not it was newly filed (CI-friendly, same "
              "convention as `check`/`expire-report`).")
    pexempt_escalate.add_argument("--path", default=None)
    pexempt_escalate.add_argument("--as-of", default=None, dest="as_of")

    # Reference-pattern coverage audit (2026-09-03, gap-close-reference-audit
    # workstream): closes the confirmed gap that reference/bfm_patterns/*.txt
    # files were only ever consulted reactively, bug by bug -- never with an
    # upfront systematic pass. See dv_harness/reference_pattern_audit.py and
    # .work/gap-close-reference-audit-report.md. Required (not optional) as
    # the first step of IP_UVM_DV_Gen.md's Step 7 before writing/converting
    # any bring-up pattern.
    prefaudit = sub.add_parser("reference-audit", help="Mechanically extract every register-write macro call "
                                                          "(CPUWRITE*B/HOSTWRITE*B/similar) from a directory of "
                                                          "reference BFM pattern files and flag any host/DUT "
                                                          "register-write asymmetry (a paired host-side/DUT-side "
                                                          "register block where one side writes an offset the "
                                                          "other side never touches, per file) -- the class of "
                                                          "fact that would have caught the real usb_p2_switch_en "
                                                          "TCA asymmetry on day one instead of after 3 debugging "
                                                          "rounds. See dv_harness/reference_pattern_audit.py. "
                                                          "Exits 1 if any asymmetry is found.")
    prefaudit.add_argument("pattern_dir", help="Directory of reference BFM pattern files (e.g. reference/bfm_patterns/).")
    prefaudit.add_argument("--glob", default="*.txt")
    prefaudit.add_argument("--json", action="store_true", help="Print raw JSON instead of the human-readable report.")
    prefaudit.add_argument("--escalate", action="store_true",
                           help="Also file every asymmetry into the real question queue "
                                "(--project-root's .dv-harness/question_queue/) as a Tier-3 "
                                "entry carrying BOTH sides' evidence paths -- the written-side "
                                "file:line and the cited absence on the paired base. Idempotent: "
                                "the Q-ID is derived from the finding, so re-running over "
                                "unchanged patterns re-mints the same id, never a duplicate.")

    # SYS-1..SYS-4 of the System-Level Verification Integration workflow
    # (2026-09-04): discover candidate subsystem environments and present
    # SUBSYSTEM / ENVIRONMENT PATH / KNOWLEDGE CENTER STATUS / READINESS /
    # PROTOCOL / VERSION-SHA, so that the explicit user selection
    # environment_mode_router.resolve_environment_mode() already REQUIRES is
    # made against a real candidate list instead of from memory. Discovery/
    # analysis/reporting only -- it generates no System-Level environment,
    # which is SYS-40 and needs its own human approval.
    psd = sub.add_parser("subsystem-discovery",
                         help="SYS-1..4: list every candidate subsystem verification "
                              "environment with its existence class (EXISTS_READY/"
                              "EXISTS_PARTIAL/EXISTS_BLOCKED/EXISTS_UNKNOWN/NOT_FOUND), "
                              "13-factor readiness (READY/PARTIAL/BLOCKED/UNKNOWN) and "
                              "shared Knowledge Center status, then require an explicit "
                              "selection. Reports only; composes nothing.")
    psd.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                     help="Name one subsystem to select for System-Level composition. "
                          "Repeatable. Omitted means pure discovery: the candidate table "
                          "is printed and the selection is explicitly refused, per SYS-1's "
                          "'the Harness must NOT assume all available subsystems "
                          "participate'.")
    psd.add_argument("--knowledge-center", action="store_true", dest="knowledge_center",
                     help="Also query the SHARED Knowledge Center (SYS-3) for each "
                          "candidate and report contradictions/staleness against current "
                          "repository evidence. Off by default: it is a real remote call.")
    psd.add_argument("--json", action="store_true",
                     help="Print raw JSON instead of the human-readable SYS-1..4 report.")

    # SYS-5..SYS-8 of the same workflow (2026-09-04): one INDEPENDENT analysis
    # per selected subsystem (SYS-5, isolation enforced), the per-subsystem
    # verification-architecture report over SYS-6's own 24-field list, the
    # mandatory command.txt grammar/ordering/dependency analysis (SYS-7), and
    # the SubsystemCommandContract set with its cross-subsystem conflicts
    # (SYS-8). Every command.txt is read-only, and nothing here composes a
    # System-Level environment -- that is SYS-40 and needs its own approval.
    psa = sub.add_parser("subsystem-analysis",
                         help="SYS-5..8: analyze each SELECTED subsystem's verification "
                              "architecture and command.txt independently, then report the "
                              "SubsystemCommandContracts and the cross-subsystem conflicts "
                              "(duplicate active drivers, shared resources, address write "
                              "collisions). Reads only; composes nothing.")
    psa.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                     help="Name one subsystem to analyze. Repeatable. Required -- SYS-1's "
                          "explicit-selection refusal is not bypassed by this command.")
    psa.add_argument("--knowledge-center", action="store_true", dest="analysis_kc",
                     help="Also query the shared Knowledge Center during the SYS-1 "
                          "discovery this command runs first. Off by default (real remote call).")
    psa.add_argument("--command-inventory", default=None, metavar="CSV",
                     help="Path to a command_inventory.csv to read as a DECLARED overlay "
                          "(its HANDLER/VIP_SEQUENCE columns are reused rather than "
                          "re-derived). Read-only; never rewritten.")
    psa.add_argument("--json", action="store_true",
                     help="Print raw JSON instead of the human-readable SYS-5..8 report.")

    # SYS-9..SYS-14 of the same workflow (2026-09-04): the CROSS-subsystem
    # layer. Every check in connectivity.py is closed-world over ONE matrix, so
    # a resource duplicated across two subsystems passes both subsystems' own
    # self-checks with the duplicate never surfaced. This is the step that
    # holds two subsystems' evidence at once. Reads only; composes nothing,
    # and promotes nothing -- SYS-13's verdicts are recommendations for a human.
    psri = sub.add_parser("system-resource-inventory",
                          help="SYS-9..14: inventory every SELECTED subsystem's resources with "
                               "OWNER_SUBSYSTEM, detect duplicate VIP/agents ACROSS subsystems, "
                               "classify each relationship, apply the active-driver conflict "
                               "rule, and evaluate shared-VIP promotion. Reads only.")
    psri.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to inventory. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    psri.add_argument("--knowledge-center", action="store_true", dest="resource_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 discovery "
                           "this command runs first. Off by default (real remote call).")
    psri.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay for "
                           "the SYS-8 contract set this command's driver-ownership signal uses. "
                           "Read-only; never rewritten.")
    psri.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the human-readable SYS-9..14 report.")

    # SYS-15..SYS-17 of the same workflow (2026-09-04): the SYSTEM_RESOURCE_
    # REGISTRY plus the two tables the requirement calls "Mandatory". The
    # registry is a THIRD granularity -- one entry per SYSTEM-level resource,
    # with `owner` and `consumer_subsystems` as separate fields -- distinct
    # from the SUBSYSTEM-granularity subsystem_environment_registry.json (one
    # row per environment, six identity/qualification fields, validated by
    # tools/real_env/system_level_validator.py) and from the connectivity
    # matrix (one row per interface of ONE environment, no subsystem column).
    # Planning only: every owner and reuse_decision is a recommendation.
    psip = sub.add_parser("system-integration-plan",
                          help="SYS-15..17: build the SYSTEM_RESOURCE_REGISTRY (one entry per "
                               "SYSTEM-level resource, owner vs consumer_subsystems) and render "
                               "the mandatory SUBSYSTEM INTEGRATION MATRIX and VIP/AGENT "
                               "DEDUPLICATION MATRIX for the selected subsystems. Reads only; "
                               "generates no System-Level UVM, command.txt or routing.")
    psip.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to include. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    psip.add_argument("--knowledge-center", action="store_true", dest="plan_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 discovery "
                           "this command runs first. Off by default (real remote call).")
    psip.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay for "
                           "the SYS-8 contract set. Read-only; never rewritten.")
    psip.add_argument("--write-registry", action="store_true",
                      help="Also persist the SYS-15 registry to "
                           ".dv-harness/soc-composer/system_resource_registry.json. A PLANNING "
                           "document beside -- never inside -- the subsystem registry; nothing "
                           "reads it back to apply it. Off by default.")
    psip.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the human-readable SYS-15..17 report.")

    pscp = sub.add_parser("system-command-plan",
                          help="SYS-18..22: report the System-Level ARCHITECTURE, plan the System "
                               "command.txt as routing/namespacing over existing subsystem command "
                               "contracts, assess backward compatibility, derive the System Command "
                               "IR, and detect command collisions. Reads only; emits no System "
                               "command.txt, router, virtual sequencer, adapter or UVM source.")
    pscp.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to include. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    pscp.add_argument("--knowledge-center", action="store_true", dest="cmdplan_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 discovery "
                           "this command runs first. Off by default (real remote call).")
    pscp.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay for "
                           "the SYS-8 contract set. Read-only; never rewritten.")
    pscp.add_argument("--escalate", action="store_true",
                      help="Also file every SYS-22 collision into the real question queue, "
                           "through source_authority.escalate_conflict(). Idempotent: a re-run "
                           "over unchanged command.txt files re-mints the same Q-IDs.")
    pscp.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the human-readable SYS-18..22 report.")

    # SYS-23..27, the SCHEDULING layer on top of SYS-18..22's command layer:
    # what may run once vs. repeatedly, which shared physical agent every user
    # routes through, which command pairs may overlap, which subsystem
    # scoreboards are reused under a correlation layer, and which of SYS-27's
    # own six candidate flows the selected architecture actually supports.
    # Planning only: no command is removed, no sequencer/driver/queue is built,
    # no scoreboard is modified or replaced, and no check content is emitted.
    pssp = sub.add_parser("system-scheduling-plan",
                          help="SYS-23..27: classify each System command's initialization "
                               "scope, plan shared-resource scheduling through a single "
                               "named access point, classify cross-subsystem command-pair "
                               "parallelism, plan subsystem-scoreboard REUSE under a "
                               "correlation layer, and evaluate SYS-27's six candidate "
                               "flows for architectural support. Reads only; removes no "
                               "command and generates no sequencer, scoreboard or check.")
    pssp.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to include. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    pssp.add_argument("--knowledge-center", action="store_true", dest="schedplan_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 "
                           "discovery this command runs first. Off by default (real "
                           "remote call).")
    pssp.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay "
                           "for the SYS-8 contract set. Read-only; never rewritten.")
    pssp.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the human-readable SYS-23..27 report.")

    psta = sub.add_parser("system-topology-analysis",
                          help="SYS-28..30: reconcile the selected subsystems' address maps "
                               "and interrupt maps across subsystems (ADDRESS_OVERLAP_VALID / "
                               "ADDRESS_OVERLAP_CONFLICT / SHARED_MEMORY / UNKNOWN), compare "
                               "their clock sources/frequencies and reset "
                               "sources/polarities/sequencing including CDC boundaries, and "
                               "plan the SHAPE of a multi-subsystem scenario. Reads only; "
                               "relocates no address region, creates no clock or reset, and "
                               "writes no System command.txt or scenario body.")
    psta.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to include. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    psta.add_argument("--knowledge-center", action="store_true", dest="topology_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 "
                           "discovery this command runs first. Off by default (real "
                           "remote call).")
    psta.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay "
                           "for the SYS-8 contract set. Read-only; never rewritten.")
    psta.add_argument("--escalate", action="store_true", dest="topology_escalate",
                      help="Also file every cross-subsystem address conflict into the REAL "
                           "question queue through source_authority.escalate_conflict(). "
                           "Idempotent: a re-run over unchanged address maps re-mints the "
                           "same Q-IDs.")
    psta.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the human-readable SYS-28..30 report.")

    # The 9-level source authority order (2026-09-04): docs/RUN_PROFILE.md's
    # ordering as an executable, queryable rule rather than prose an agent is
    # trusted to have read. NOT the same list as tools/verification_flow/
    # evidence_source_priority_gate.py's ORDER, which is a discovery/search
    # order -- see dv_harness/source_authority.py's module docstring.
    pauth = sub.add_parser("authority", help="The 9-level source authority order (which source wins when "
                                             "two sources disagree) and the conflict escalation built on it. "
                                             "See dv_harness/source_authority.py.")
    pauth_sub = pauth.add_subparsers(dest="authority_cmd", required=True)
    pauth_sub.add_parser("order", help="Print the 9 levels, highest authority first.").add_argument(
        "--json", action="store_true", dest="auth_json")
    pauth_sub.add_parser("check-doc", help="Verify docs/RUN_PROFILE.md's written order and the code's "
                                           "AUTHORITY_ORDER are still the same list, level for level. "
                                           "Exits 1 on drift.")
    pauth_resolve = pauth_sub.add_parser(
        "resolve", help="Apply the order to a JSON file of claims "
                        "([{source, claim, evidence_path, qualifier?}, ...]) and print the verdict.")
    pauth_resolve.add_argument("claims", help="Path to the claims JSON file ('-' for stdin).")
    pauth_resolve.add_argument("--json", action="store_true", dest="auth_json")
    pauth_resolve.add_argument("--escalate", action="store_true",
                               help="Also file the conflict into the real question queue.")
    pauth_resolve.add_argument("--domain", choices=["vip", "dut", "env"], default="dut",
                               help="Question domain, which decides the owner it routes to.")
    pauth_resolve.add_argument("--subject", default=None,
                               help="What the two sources disagree ABOUT (required with --escalate).")

    pconfig = sub.add_parser("config", help="View/update .dv-harness/config.json's policy block.")
    pconfig_sub = pconfig.add_subparsers(dest="config_cmd", required=True)
    pconfig_set = pconfig_sub.add_parser("set", help="dv-harness config set require_dv_review_cosign true|false")
    pconfig_set.add_argument("key", choices=["require_dv_review_cosign"])
    pconfig_set.add_argument("value", choices=["true", "false"])
    pconfig_sub.add_parser("get", help="Print the current policy block.")

    pst = sub.add_parser("self-tune", help="Autonomous gate self-tuning: status/list/approve/reject/revert. "
                                           "See dv_harness/self_tuning.py and docs/superpowers/specs/"
                                           "2026-09-02-autonomous-gate-self-tuning-design.md.")
    pst_sub = pst.add_subparsers(dest="self_tune_cmd", required=True)
    pst_status = pst_sub.add_parser("status")
    pst_list = pst_sub.add_parser("list")
    pst_list.add_argument("--pending", action="store_true")
    pst_list.add_argument("--applied", action="store_true")
    pst_approve = pst_sub.add_parser("approve")
    pst_approve.add_argument("memory_id")
    pst_reject = pst_sub.add_parser("reject")
    pst_reject.add_argument("memory_id")
    pst_revert = pst_sub.add_parser("revert")
    pst_revert.add_argument("memory_id")

    # --- DV-Knowledge Vault CLI surface (2026-09-03, obsidian-memory-cli,
    # Workstream 2 of 4): status/search/show/add/promote/graph/validate/
    # sync/doctor over dv_harness/memory_vault.py's MemoryProvider (never a
    # bare adapter -- always get_active_provider()'s Hybrid), plus
    # dv_harness/memory_dedup.py (Phase 18) and dv_harness/memory_doctor.py
    # (Phase 21). Deliberately a SEPARATE command group from the pre-existing
    # `dv_harness/memory_cli.py` standalone script (memory.py's JSON
    # MemoryStore/CornerCaseLibrary) -- this one is specifically the
    # Markdown/YAML Vault's own surface, matching this module's own scope.
    pmem = sub.add_parser("memory", help="DV-Knowledge Vault (Obsidian+Git/Markdown Hybrid Engineering "
                                          "Memory) status/search/show/add/promote/graph/validate/sync/doctor. "
                                          "See dv_harness/memory_vault.py, memory_dedup.py, memory_doctor.py.")
    pmem_sub = pmem.add_subparsers(dest="memory_cmd", required=True)

    pmem_sub.add_parser("status", help="Provider status (Obsidian detection + filesystem-adapter readiness) "
                                        "plus real note counts per memory tier.")

    pmem_search = pmem_sub.add_parser("search", help="Real keyword/tag/property/wiki-link search over vault notes "
                                                       "(FileSystemMarkdownAdapter.search() -- no embedding/vector DB).")
    pmem_search.add_argument("query", nargs="?", default="", help="Free-text query. Omit for filter-only search.")
    pmem_search.add_argument("--protocol", default=None)
    pmem_search.add_argument("--tag", default=None)
    pmem_search.add_argument("--level", default=None, choices=["working", "job", "project", "engineering", "organizational"],
                              dest="memory_level")
    # Every remaining filter FileSystemMarkdownAdapter.search() already
    # accepts, exposed on the CLI too (2026-09-04, gap-close-obsidian-memory
    # phase 9) -- previously reachable only from the Python API, which made
    # them unusable from an agent/shell invocation.
    pmem_search.add_argument("--exact", default=None,
                              help="Substring that must appear literally in the note's raw text "
                                   "(frontmatter + body), for signatures a tokenizer would split.")
    pmem_search.add_argument("--property", action="append", default=[], dest="properties", metavar="KEY=VALUE",
                              help="Arbitrary YAML frontmatter filter, repeatable "
                                   "(e.g. --property subsystem=link_training).")
    pmem_search.add_argument("--linked-to", default=None, dest="linked_to", metavar="NOTE_ID",
                              help="Only notes whose body wiki-links to this note id, e.g. [[MEM-1A2B3C4D5E]].")
    pmem_search.add_argument("--project", default=None)
    pmem_search.add_argument("--confidence", default=None, choices=["CONFIRMED", "HIGH", "MEDIUM", "LOW", "UNKNOWN"])
    pmem_search.add_argument("--status", default=None, help="Note status to match, e.g. ACTIVE or DEPRECATED.")
    pmem_search.add_argument("--limit", type=int, default=10)

    pmem_show = pmem_sub.add_parser("show", help="Print one note's full frontmatter + body.")
    pmem_show.add_argument("note_id")

    pmem_add = pmem_sub.add_parser("add", help="Write a new Engineering/Organizational vault note directly "
                                                "(Phase 18 dedup classification runs FIRST -- a DUPLICATE match "
                                                "refuses the write unless --force).")
    pmem_add.add_argument("--level", default="engineering", choices=["engineering", "organizational"], dest="memory_level")
    pmem_add.add_argument("--protocol", required=True)
    pmem_add.add_argument("--failure", default=None, help="Failure/symptom summary (the note's `failure` field).")
    pmem_add.add_argument("--root-cause", default=None, dest="root_cause")
    pmem_add.add_argument("--configuration", default=None, help="Config/context this occurred under (-> Context section).")
    pmem_add.add_argument("--error-pattern", default=None, dest="error_pattern",
                           help="Distinguishing error/log signature (-> Symptom section).")
    pmem_add.add_argument("--fix", default=None)
    pmem_add.add_argument("--confidence", default="MEDIUM", choices=["HIGH", "MEDIUM", "LOW", "UNKNOWN"])
    pmem_add.add_argument("--status", default="ACTIVE")
    pmem_add.add_argument("--tag", action="append", default=[], dest="tags")
    pmem_add.add_argument("--force", action="store_true",
                           help="Write anyway even if dedup classifies this as DUPLICATE of an existing note.")

    pmem_promote = pmem_sub.add_parser("promote", help="Engineering -> Organizational promotion gate "
                                                         "(memory_router.promote_to_organizational()) -- "
                                                         "operates on a JSON MemoryStore engineering-tier "
                                                         "memory_id (MEM-...), not a vault note id.")
    pmem_promote.add_argument("memory_id")
    pmem_promote.add_argument("--independent-sources", type=int, default=0, dest="independent_sources_count")
    pmem_promote.add_argument("--evidence-refs-verified", action="store_true", dest="evidence_refs_verified")
    pmem_promote.add_argument("--counter-evidence", type=int, default=0, dest="counter_evidence_count")
    pmem_promote.add_argument("--multi-agent-consensus", type=int, default=0, dest="multi_agent_consensus_count")
    pmem_promote.add_argument("--kind", default="methodology",
                               choices=["methodology", "best_practice", "cross_project_lesson"])

    pmem_graph = pmem_sub.add_parser("graph", help="Forward-link/backlink graph around one note "
                                                     "(BFS over real [[WikiLink]] entries, no external graph lib).")
    pmem_graph.add_argument("note_id")
    pmem_graph.add_argument("--depth", type=int, default=2)

    pmem_sub.add_parser("validate", help="Note-correctness subset of `doctor` (schema -- required frontmatter "
                                          "fields AND the 11-section body shape -- plus duplicate-ID/"
                                          "invalid-YAML/broken-link/secret checks) over real "
                                          "06_Agent_Memory/** notes. See dv_harness/memory_doctor.run_validate().")

    pmem_sync = pmem_sub.add_parser("sync", help="Bootstrap the vault, then (if memory.git_enabled) commit any "
                                                  "pending vault changes and report recent commit history.")
    pmem_sync.add_argument("--message", default=None)

    pmem_resync = pmem_sub.add_parser("resync-notes",
                                       help="Re-render vault notes from the durable MemoryStore records they "
                                            "mirror, repairing a note left schema-PARTIAL by an older mapper. "
                                            "Invents nothing: a note whose source record is gone is reported "
                                            "skipped, not rewritten. Exits 2 if any note is still PARTIAL after "
                                            "the pass. See memory_vault.resync_notes_from_memory_store().")
    pmem_resync.add_argument("--note-id", action="append", default=[], dest="note_ids",
                              help="Repeatable. Limit the re-render to these note ids; default is every note.")

    pmem_sub.add_parser("doctor", help="Phase 21 full health check: vault writable, git status, Obsidian CLI, "
                                        "filesystem fallback, schema (frontmatter fields + body-section shape), "
                                        "broken links, duplicate IDs, invalid YAML, "
                                        "large/forbidden-artifact files, secret leakage -> READY/PARTIAL/BLOCKED. "
                                        "See dv_harness/memory_doctor.run_doctor().")

    # --- 3-tier ask-a-human question queue (2026-09-03, question-queue task,
    # spec Part B): add/list/answer/digest/status over
    # dv_harness/question_queue.py's QuestionQueueStore. Deliberately its own
    # command group (not folded into `memory`/`knowledge`) -- a question here
    # is a live, pending decision awaiting a human, not settled Engineering/
    # Organizational knowledge.
    pqq = sub.add_parser("question-queue", help="3-tier ask-a-human protocol: self-resolve / safe-to-assume / "
                                                  "cannot-assume, standardized Q-ID questions, decisions.md "
                                                  "persistence (a repeat ask self-resolves, never re-escalates), "
                                                  "daily/end-of-run digest batching, and the 4 tracking metrics. "
                                                  "See dv_harness/question_queue.py.")
    pqq_sub = pqq.add_subparsers(dest="qq_cmd", required=True)

    pqq_add = pqq_sub.add_parser("add", help="Ask one question. Never pings -- only persists; classify_tier() "
                                               "runs immediately (a Tier-1 hit self-resolves, a Tier-2 hit logs "
                                               "its assumption and continues, only a genuine Tier-3 stays OPEN/"
                                               "blocking, awaiting a `digest`+`answer`).")
    pqq_add.add_argument("--domain", required=True, choices=["vip", "dut", "env"])
    pqq_add.add_argument("--question", required=True)
    pqq_add.add_argument("--context-path", required=True, dest="context_path")
    pqq_add.add_argument("--option", action="append", required=True, dest="options",
                          help="Repeatable, 2-3 required (pre-researched options, never open-ended). "
                               "Each becomes {'label': <this value>}.")
    pqq_add.add_argument("--recommendation", required=True, help="Must equal one of the --option values given.")
    pqq_add.add_argument("--assumption-if-unanswered", required=True, dest="assumption_if_unanswered")
    pqq_add.add_argument("--question-key", default=None, dest="question_key",
                          help="Stable dedup key. Omit to derive one from domain+context-path+question.")
    pqq_add.add_argument("--affects-pass-fail-verdict", action="store_true", dest="affects_pass_fail_verdict")
    pqq_add.add_argument("--affects-spec-intent", action="store_true", dest="affects_spec_intent")
    pqq_add.add_argument("--affects-read-only-file-change", action="store_true", dest="affects_read_only_file_change")
    pqq_add.add_argument("--blast-radius", default="single_regression", dest="blast_radius",
                          choices=["single_regression", "multi_regression", "unbounded"])
    pqq_add.add_argument("--resolvable-from-manifest", action="store_true", dest="resolvable_from_manifest")
    pqq_add.add_argument("--manifest-value", default=None, dest="manifest_value")

    pqq_list = pqq_sub.add_parser("list", help="List questions, optionally filtered.")
    pqq_list.add_argument("--status", default=None, choices=["OPEN", "SELF_RESOLVED", "ASSUMED", "ANSWERED"])
    pqq_list.add_argument("--tier", type=int, default=None, choices=[1, 2, 3])
    pqq_list.add_argument("--blocking", action="store_true", default=None, dest="blocking_only")
    pqq_list.add_argument("--domain", default=None, choices=["vip", "dut", "env"])

    pqq_answer = pqq_sub.add_parser("answer", help="Record a human's real answer to one question by Q-ID -- "
                                                     "persists to decisions.json/decisions.md so this exact "
                                                     "question_key never re-escalates.")
    pqq_answer.add_argument("question_id")
    pqq_answer.add_argument("--answer", required=True)
    pqq_answer.add_argument("--basis", required=True)
    pqq_answer.add_argument("--decided-by", default=None, dest="decided_by")

    pqq_revoke = pqq_sub.add_parser("revoke", help="Withdraw the persisted decision for one question_key so the "
                                                      "next ask re-classifies from scratch. The sanctioned undo for "
                                                      "a wrong Tier-2 auto-assumption -- decisions.md tells its "
                                                      "reader not to hand-edit the store, and this is the only "
                                                      "other way out. The entry is moved to the store's `revoked` "
                                                      "list with who/when/why, never deleted.")
    pqq_revoke.add_argument("question_key")
    pqq_revoke.add_argument("--reason", required=True,
                             help="Why this decision is being withdrawn -- recorded in decisions.json/decisions.md.")
    pqq_revoke.add_argument("--revoked-by", default=None, dest="revoked_by")

    pqq_digest = pqq_sub.add_parser("digest", help="Batch never-yet-digested OPEN/ASSUMED questions into one "
                                                      "digest, grouped by owner. Never real-time -- run this "
                                                      "once daily (e.g. from cron) or at end-of-run.")
    pqq_digest.add_argument("--trigger", default="manual", choices=["manual", "stage_boundary", "scheduled"])
    pqq_digest.add_argument("--stage", default=None, help="Required for --trigger stage_boundary -- the stage "
                                                             "that just completed (dv_harness.models.Stage value).")
    pqq_digest.add_argument("--min-hours-since-last", type=float, default=24.0, dest="min_hours_since_last")

    pqq_sub.add_parser("status", help="Print the 4 tracking metrics: self-resolve rate, blocking-questions/week, "
                                        "repeat-question-rate, assumption-overturned-rate.")

    # --- Waveform Dump User Gate (2026-09-04, AI-mechanism #12 closure) -----
    # The ASK half of CLAUDE.md's "before any waveform-enabled simulation, ask
    # the user to confirm dump scope and level/depth". Deliberately a thin
    # front end onto `question-queue` -- it files one canonically-keyed Tier-3
    # question through the same QuestionQueueStore, and a human answers it
    # with the existing `question-queue answer <Q-ID>`. There is no separate
    # "waveform confirm" verb, because a second way to record a confirmation
    # would be a second thing focused_wave_debug_window_gate has to trust.
    pwd_ = sub.add_parser("waveform-dump-scope",
                           help="Ask a human to confirm this rerun's waveform dump scope/level, and check "
                                "whether they already have. The gate "
                                "(tools/verification_flow/focused_wave_debug_window_gate.py) verifies the "
                                "answer recorded here, not the evidence block's own claim.")
    pwd_sub = pwd_.add_subparsers(dest="wds_cmd", required=True)
    pwd_ask = pwd_sub.add_parser("ask", help="File the dump-scope confirmation question (Tier 3, blocking). "
                                                "Re-asking the same scope re-mints the same Q-ID; once answered "
                                                "it self-resolves instead of escalating again.")
    pwd_ask.add_argument("--scope", required=True,
                          help="The proposed dump scope, e.g. top.usb_dev.ctrl. This IS the question's identity: "
                               "a different scope is a different decision.")
    pwd_ask.add_argument("--level-or-depth", required=True, dest="level_or_depth",
                          help="The proposed dump level/depth, e.g. 'signal-level, block-scoped'.")
    pwd_ask.add_argument("--failure-cone", default="", dest="failure_cone",
                          help="The current failure cone this scope is minimally sufficient for.")
    pwd_status = pwd_sub.add_parser("status", help="Report whether a real human answer exists for one scope -- "
                                                     "the same check the gate runs. Exits 0 when confirmed, 2 "
                                                     "when not.")
    pwd_status.add_argument("--scope", required=True)
    pwd_status.add_argument("--confirmed-by", default=None, dest="confirmed_by",
                             help="Cross-check that this name matches the human who actually answered. "
                                  "Omit to check against whoever did.")

    args = ap.parse_args()
    h = DVHarness(Path(args.project_root))
    # Per-invocation override of the DEGRADED-mode probe transport, applied
    # before any subcommand runs so `status` reports the transport this
    # invocation would actually use, not the config default it overrode.
    if getattr(args, "degradation_transport", None):
        _decision = h.set_degradation_transport(args.degradation_transport)
        print(f"[dv-harness] degradation probe transport: {_decision.resolved} "
               f"({_decision.reason})", file=sys.stderr)
    # Usage record for `user-info` (dv_harness/user_info.py): logged for
    # EVERY subcommand, including read-only ones (status/explain/...) --
    # user-info's whole point is "who has used this deployment, and when",
    # which read-only access is part of, not just mutating actions (those
    # already separately log their own PAUSE/APPROVE/etc event with the
    # same user attribution via control_plane.py's _default_user()).
    from .control_plane import now as cp_now
    h.store.event({"ts": cp_now(), "event": "CLI_ACCESS", "cmd": args.cmd,
                    "user": _access_user(), "host": _access_host()})

    if args.cmd == "status":
        print(h.summary())
    elif args.cmd == "stats":
        from .stats_snapshot import compute_stats
        print(json.dumps(compute_stats(h.root), ensure_ascii=False, indent=2))
    elif args.cmd == "explain":
        from .prompts import get_de_explainer
        from .control_plane import describe_stage
        if args.stage:
            stages = [args.stage]
        else:
            # No --stage given: during a live parallel fan-out, current_stage
            # alone only names the parked source node, not the concurrently
            # running branches -- explain every branch in active_stages (falls
            # back to [current_stage] when there is no fan-out in flight, via
            # effective_active_stages()) rather than silently picking one.
            stages = h.state.effective_active_stages()
        for stage in stages:
            if len(stages) > 1:
                print(f"\n=== {stage} ===")
            # Original static, generic per-stage explainer (unchanged -- kept
            # first so existing callers/tests that only look for this text still
            # find it verbatim), followed by the strengthened WHY: this run's
            # ACTUAL blocking_reason / evidence blocks / gate verdict for stage.
            print(get_de_explainer(stage))
            print("\n--- Current run state (WHY, not a generic description) ---")
            # describe_stage()'s dict is printed verbatim (no field
            # allowlist), so its gates_total/gates_passed/
            # stage_completion_percent/stage_completion_note/entry_checklist/
            # exit_checklist fields (stage-SCOPED completion, alongside
            # gate_verdict/gate_reasons) surface here automatically.
            detail = describe_stage(h.root, h.state, stage)
            print(json.dumps(detail, ensure_ascii=False, indent=2))
            # RULING: `explain` already mixes prose (get_de_explainer above)
            # with a JSON block, so appending a human-readable rendering of
            # the same completion/checklist data here is purely additive --
            # existing callers that only look for the JSON block are
            # unaffected. `evidence` below is intentionally left emitting
            # ONLY the raw describe_stage() JSON (unchanged shape, still
            # carries these same fields for a machine reader) because at
            # least one existing test (test_cli_evidence_stage_prints_
            # completion_fields) does a bare json.loads() over `evidence`'s
            # entire stdout -- appending trailing text there would break that
            # contract. The new `checklist` subcommand below is the
            # dedicated human-readable entry point for evidence's data.
            print("\n--- Stage completion checklist (human-readable) ---")
            print(render_stage_checklist_report(detail))
    elif args.cmd == "pause":
        from . import commands
        commands.cmd_pause(h, args.reason)
        print(f"PAUSED{': ' + args.reason if args.reason else ''}")
    elif args.cmd == "resume":
        from . import commands
        commands.cmd_resume(h)
        print("RESUMED")
    elif args.cmd == "takeover":
        from . import commands
        res = commands.cmd_takeover(h, args.message)
        print(f"TAKEOVER active on {res['stage']}: {args.message}")
    elif args.cmd == "release-takeover":
        from . import commands
        commands.cmd_release_takeover(h)
        print("TAKEOVER released")
    elif args.cmd == "redirect":
        from . import commands
        try:
            commands.cmd_redirect(h, args.stage, args.reason)
            print(f"REDIRECTED to {args.stage}")
        except (ValueError, RuntimeError) as e:
            print(str(e))
            raise SystemExit(1)
    elif args.cmd == "approve":
        from . import commands
        entry = commands.cmd_approve(h, args.stage, args.note, args.reviewer_id, args.reviewer_confidence)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    elif args.cmd == "evidence":
        from .control_plane import describe_stage, describe_stages
        if args.stage:
            # Same describe_stage() dict as `explain` above, printed whole --
            # gates_total/gates_passed/stage_completion_percent/
            # stage_completion_note surface here automatically too.
            print(json.dumps(describe_stage(h.root, h.state, args.stage), ensure_ascii=False, indent=2))
        else:
            # No --stage given: same fan-out consideration as `explain` above
            # -- show evidence for every active branch, not just the parked
            # source node named by current_stage.
            stages = h.state.effective_active_stages()
            if len(stages) == 1:
                print(json.dumps(describe_stage(h.root, h.state, stages[0]), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(describe_stages(h.root, h.state, stages), ensure_ascii=False, indent=2))
    elif args.cmd == "checklist":
        # Dedicated human-readable entry point for the same
        # stage_completion_percent/gates_passed/gates_total/entry_checklist/
        # exit_checklist data `evidence --stage` carries as raw JSON -- see
        # the RULING comment at `explain`'s call site above for why this
        # exists as its own subcommand rather than also being appended to
        # `evidence` directly.
        from .control_plane import describe_stage
        if args.stage:
            stages = [args.stage]
        else:
            stages = h.state.effective_active_stages()
        for stage in stages:
            if len(stages) > 1:
                print(f"\n=== {stage} ===")
            print(render_stage_checklist_report(describe_stage(h.root, h.state, stage)))
    elif args.cmd == "correct":
        from . import commands
        commands.cmd_correct(h, args.stage, args.note, args.reset_attempts)
        print(f"CORRECTED {args.stage}")
    elif args.cmd == "constraint":
        from . import commands
        if args.add is not None:
            entry = commands.cmd_constraint_add(h, args.add)
            print(json.dumps(entry, ensure_ascii=False, indent=2))
        elif args.remove is not None:
            removed = commands.cmd_constraint_remove(h, args.remove)
            print("REMOVED" if removed else "NOT_FOUND")
        else:
            print(json.dumps(commands.cmd_constraint_list(h), ensure_ascii=False, indent=2))
    elif args.cmd == "cosign":
        from . import commands
        try:
            value = json.loads(args.value)
        except Exception:
            value = args.value
        entry = commands.cmd_cosign(h, args.stage, args.field_path, value, args.reviewer_id, args.reviewer_confidence)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    elif args.cmd == "blackboard":
        from . import commands
        if args.bb_cmd == "write":
            if args.file:
                value = json.loads(Path(args.file).read_text(encoding="utf-8"))
            else:
                value = json.loads(args.value)
            entry = commands.cmd_blackboard_write(h, args.topic, value, args.source, args.confidence)
            print(json.dumps(entry, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(commands.cmd_blackboard_read(h, args.topic), ensure_ascii=False, indent=2))
    elif args.cmd == "lsf":
        from .regression_reporter import load_jobs, get_job
        if args.job_id:
            j = get_job(h.root, args.job_id)
            if j is None:
                print(json.dumps({"error": "NOT_FOUND", "message": f"no such job: {args.job_id}"}, ensure_ascii=False))
                raise SystemExit(1)
            print(json.dumps(j, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(load_jobs(h.root), ensure_ascii=False, indent=2))
    elif args.cmd == "preflight":
        from . import preflight as _preflight
        from . import escalation_notify as _escalation
        pf_cfg = _preflight.config_from_dict(
            h.cfg.get("preflight"), queue=args.queue, workdir=args.workdir,
            license_server=args.license_server)
        runner = _preflight.RemoteRelayCommandRunner() if args.remote else None
        result = _preflight.run_preflight(pf_cfg, runner=runner)
        if result.overall != "PASS":
            notifier = _escalation.notifier_from_config(h.cfg.get("escalation"))
            for check in result.checks:
                if check.name == "eda_license" and check.status == "FAIL":
                    notifier.license_starvation(check)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.overall == "PASS" else 1)
    elif args.cmd == "lsf-submit":
        from . import lsf_client
        from . import preflight as _preflight
        from . import escalation_notify as _escalation
        # lmstat + scheduler preflight gate (2026-09-03): build the real
        # PreflightConfig from config.json's `preflight` block (never
        # guessed/hardcoded -- see config.py's own comment), overridden by
        # this submission's own --queue/--run-dir so the gate checks the
        # SAME queue/workdir this job is actually about to use.
        pf_cfg = _preflight.config_from_dict(
            h.cfg.get("preflight"), queue=args.queue, workdir=args.run_dir)
        notifier = _escalation.notifier_from_config(h.cfg.get("escalation"))
        try:
            job_id, pf_result = lsf_client.bsub_submit_with_preflight(
                args.command, queue=args.queue, cores=args.cores,
                mem_mb=args.mem_mb, run_dir=args.run_dir,
                runlimit_minutes=args.runlimit_minutes,
                preflight_cfg=pf_cfg, skip_preflight=args.skip_preflight,
                notifier=notifier,
            )
        except lsf_client.PreflightBlockedError as e:
            print(json.dumps({"error": "PREFLIGHT_BLOCKED", "preflight": e.result.to_dict()},
                              ensure_ascii=False, indent=2))
            raise SystemExit(1)
        except lsf_client.LsfUnavailableError as e:
            print(json.dumps({"error": "LSF_UNAVAILABLE", "message": str(e)}, ensure_ascii=False))
            raise SystemExit(1)
        seed = args.seed if args.seed is not None else lsf_client.extract_seed_from_options(args.options)
        fsdb_path = args.fsdb_path if args.fsdb_path is not None else lsf_client.extract_fsdb_path_from_options(args.options)
        state = lsf_client.JobState(
            job_id=job_id, regression_id=args.regression_id, pattern=args.pattern,
            options=args.options, run_dir=args.run_dir, sim_log=args.sim_log,
            seed=seed, fsdb_path=fsdb_path,
            command=args.command, runlimit_minutes=args.runlimit_minutes,
            lsf_status="PEND",
        )
        lsf_client.save_job_state(h.root, state)
        out = {"job_id": job_id, "state": lsf_client.asdict(state)}
        if pf_result is not None:
            out["preflight"] = pf_result.to_dict()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "pueue":
        from . import pueue_client
        pq_cfg = pueue_client.config_from_dict(h.cfg.get("pueue"))
        client = pueue_client.PueueClient(pq_cfg)
        if args.pueue_cmd == "add":
            if not client.ensure_daemon():
                print(json.dumps({"error": "PUEUED_NOT_AVAILABLE"}, ensure_ascii=False))
                raise SystemExit(1)
            try:
                task_id = client.add(args.command, label=args.label, after=args.after,
                                      group=args.group, working_directory=args.working_directory)
            except pueue_client.UngatedFarmSubmissionError as e:
                # Exit 2, and a distinct error code from PUEUE_ADD_FAILED: this
                # is the preflight gate refusing an un-gated farm submission,
                # not pueue itself failing.
                print(json.dumps({"error": "UNGATED_FARM_SUBMISSION", "message": str(e),
                                   "tokens": e.tokens,
                                   "use_instead": f"dv-harness {pueue_client.GATED_SUBMIT_CLI_SUBCOMMAND}"},
                                  ensure_ascii=False))
                raise SystemExit(2)
            except pueue_client.PueueError as e:
                print(json.dumps({"error": "PUEUE_ADD_FAILED", "message": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            print(json.dumps({"task_id": task_id}, ensure_ascii=False))
        elif args.pueue_cmd == "status":
            print(json.dumps(client.status(group=args.group), ensure_ascii=False, indent=2))
        elif args.pueue_cmd == "log":
            print(json.dumps(client.log(args.task_ids or None, full=args.full),
                              ensure_ascii=False, indent=2))
        elif args.pueue_cmd == "wait":
            result = client.wait(args.task_id, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result.get("success") else 1)
        elif args.pueue_cmd == "chain":
            steps = [(name, cmd) for name, cmd in
                     (("build", args.build), ("verify", args.verify),
                      ("submit", args.submit), ("fsdbreport", args.fsdbreport))
                     if cmd]
            if not steps:
                print(json.dumps({"error": "NO_STEPS"}, ensure_ascii=False))
                raise SystemExit(2)
            # Gate-check every step BEFORE touching the daemon, so an un-gated
            # `bsub`/`sbatch` step is refused on its own merits rather than
            # depending on whether pueued happened to be reachable.
            try:
                for step_name, step_cmd in steps:
                    pueue_client.assert_farm_submission_is_preflight_gated(step_cmd)
            except pueue_client.UngatedFarmSubmissionError as e:
                print(json.dumps({"error": "UNGATED_FARM_SUBMISSION", "step": step_name,
                                   "message": str(e), "tokens": e.tokens,
                                   "use_instead": f"dv-harness {pueue_client.GATED_SUBMIT_CLI_SUBCOMMAND}"},
                                  ensure_ascii=False))
                raise SystemExit(2)
            if not client.ensure_daemon():
                print(json.dumps({"error": "PUEUED_NOT_AVAILABLE"}, ensure_ascii=False))
                raise SystemExit(1)
            enqueued = pueue_client.enqueue_harness_chain(client, steps, group=args.group)
            print(json.dumps({"chain": enqueued}, ensure_ascii=False, indent=2))
    elif args.cmd == "lsf-kill":
        from . import lsf_client
        try:
            ok = lsf_client.bkill_job(args.job_id, verify=not args.no_verify, poll_timeout_s=args.poll_timeout_s)
        except lsf_client.LsfUnavailableError as e:
            print(json.dumps({"error": "LSF_UNAVAILABLE", "message": str(e)}, ensure_ascii=False))
            raise SystemExit(1)
        print(json.dumps({"job_id": args.job_id, "killed": ok}, ensure_ascii=False))
        raise SystemExit(0 if ok else 1)
    elif args.cmd == "lsf-watch-start":
        from . import regression_reporter
        uvm_root = args.uvm_root_path or str(h.root / "uvm")
        result = regression_reporter.ensure_watcher_running(
            h.root, args.vcuser, uvm_root, interval_minutes=args.interval_minutes)
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "lsf-watch-stop":
        from . import regression_reporter
        result = regression_reporter.stop_watcher(h.root)
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "lsf-watch-status":
        from . import regression_reporter
        result = regression_reporter.watcher_status(h.root)
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "lsf-reconcile":
        from . import lsf_client
        from . import regression_reporter
        job_ids = args.job_id
        if args.all or not job_ids:
            job_ids = regression_reporter.registered_job_ids_on_disk(h.root)
        if not job_ids:
            print(json.dumps({"reconciled": [], "message": "no known job ids to reconcile"}, ensure_ascii=False))
            raise SystemExit(0)
        try:
            result = lsf_client.reconcile_batch(h.root, job_ids)
        except lsf_client.LsfUnavailableError as e:
            print(json.dumps({"error": "LSF_UNAVAILABLE", "message": str(e)}, ensure_ascii=False))
            raise SystemExit(1)
        out = []
        any_critical = False
        for jid, (state, discrepancies) in result.items():
            d_list = [lsf_client.asdict(d) for d in discrepancies]
            any_critical = any_critical or any(d["severity"] == "CRITICAL" for d in d_list)
            out.append({"job_id": jid, "state": lsf_client.asdict(state), "discrepancies": d_list})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        raise SystemExit(1 if any_critical else 0)
    elif args.cmd == "lsf-auto-kill-scan":
        from . import lsf_client, regression_reporter
        job_ids = regression_reporter.registered_job_ids_on_disk(h.root)
        policy = lsf_client.load_early_fail_policy(h.root)
        out = []
        any_kill_failed = False
        for jid in job_ids:
            state = lsf_client.load_job_state(h.root, jid)
            if state.lsf_status != "RUN":
                continue
            decision = lsf_client.evaluate_auto_kill(state, policy)
            entry = {"job_id": jid, "should_kill": decision["should_kill"], "reason": decision["reason"]}
            if decision["should_kill"] and not args.dry_run:
                try:
                    killed = lsf_client.bkill_job(jid, verify=True)
                except lsf_client.LsfUnavailableError as e:
                    killed = False
                    entry["error"] = str(e)
                entry["killed"] = killed
                if killed:
                    state.early_kill = True
                    state.kill_reason = decision["reason"]
                    state.lsf_status = "KILLED"
                    lsf_client.save_job_state(h.root, state)
                else:
                    any_kill_failed = True
            print(json.dumps(entry, ensure_ascii=False))
            out.append(entry)
        raise SystemExit(1 if any_kill_failed else 0)
    elif args.cmd == "stage-profile":
        from . import stage_profile_report
        print(stage_profile_report.render(str(h.root)))
    elif args.cmd == "stage-report":
        from . import stage_progress_display as spd
        reports = spd.list_stage_reports(h.root, stage=args.stage, phase=args.phase)
        if not reports:
            print(f"no saved stage reports found under {spd.stage_report_dir(h.root)}"
                  + (f" for stage {args.stage}" if args.stage else ""))
            raise SystemExit(2)
        if args.list or not args.stage:
            for p in reports:
                print(p)
        else:
            print(reports[-1].read_text(encoding="utf-8"))
    elif args.cmd == "remote-control":
        from . import remote_control
        if args.rc_cmd == "bootstrap":
            session = remote_control.bootstrap_session(
                h.root, host=args.host, working_directory=args.working_directory,
                session_id=args.session_id, actor=_access_user(),
            )
            print(json.dumps(session, ensure_ascii=False, indent=2))
        elif args.rc_cmd == "status":
            print(json.dumps(remote_control.get_status(h.root), ensure_ascii=False, indent=2))
        elif args.rc_cmd == "cmd":
            try:
                ok, new_state, entry, error_reason = remote_control.validate_and_transition(
                    args.command, target_stage=args.target_stage, reason=args.reason,
                    actor=args.actor or _access_user(), env_mode=args.env_mode, project_root=h.root,
                )
            except remote_control.GateUnavailableError as e:
                print(json.dumps({"ok": False, "error": "GATE_UNAVAILABLE", "message": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            print(json.dumps({"ok": ok, "state": new_state, "entry": entry, "error": error_reason},
                              ensure_ascii=False, indent=2))
            raise SystemExit(0 if ok else 1)
    elif args.cmd == "research":
        # Formatting only -- every decision was made by commands.cmd_research()
        # -> router.resolve_research_intent()/research_route_plan().
        try:
            plan = _commands.cmd_research(
                h, documents=args.documents, compare=args.compare,
                impact=args.impact, deep=args.deep, focus=args.focus,
                request=args.request)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("")
        print(f"intent: {plan['intent']}"
              + (f"  focus: {plan['focus']}" if plan['focus'] else ""))
        for i, step in enumerate(plan["steps"], 1):
            print(f"  {i}. {step['step']} ({step['kind']}) -> {step['asset']}")
        print("STOP: research is not implementation (master prompt section 2.4). "
              f"Nothing proceeds past the Human Approval Gate without "
              f"`dv-harness approve {plan['human_approval_stage']} "
              f"--note ... --reviewer-id ...`.")
    elif args.cmd == "audit":
        from .dashboard import _audit_trail
        print(json.dumps(_audit_trail(h.root, args.limit), ensure_ascii=False, indent=2))
    elif args.cmd == "git-guard":
        from . import git_governance as _gg
        if args.check == "pre-push":
            decision = _gg.evaluate_pre_push(sys.stdin.read(), os.environ)
        else:
            if not args.branch:
                print(json.dumps({"error": "BRANCH_REQUIRED_FOR_PRE_MERGE_COMMIT"}))
                raise SystemExit(2)
            decision = _gg.evaluate_pre_merge_commit(args.branch, os.environ)
        # Audit/Change Governance trail: log every decision that actually
        # touched a protected branch (allowed-for-a-human or
        # blocked-for-an-agent) into the SAME events.jsonl every other "who
        # changed what, when" view already reads (dv-harness audit /
        # dashboard._audit_trail) -- reuse the one real audit substrate
        # this harness has, never a second parallel audit file.
        if decision.branch is not None:
            h.store.event({"ts": cp_now(), "event": "GIT_GUARD_DECISION",
                            "hook": decision.hook, "allowed": decision.allowed,
                            "branch": decision.branch, "detected_markers": decision.detected_markers,
                            "reason": decision.reason, "user": _access_user(), "host": _access_host()})
        print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if decision.allowed else 1)
    elif args.cmd == "self-audit":
        from . import self_audit
        result = self_audit.run_self_audit(h.root, args.gate, smoke=args.smoke)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["summary"]["fail"] == 0 and result["summary"]["smoke_fail"] == 0 else 1)
    elif args.cmd == "signoff-export":
        from . import signoff_export
        from . import escalation_notify as _escalation
        notifier = _escalation.notifier_from_config(h.cfg.get("escalation"))
        result = signoff_export.collect_signoff_bundle(
            h.root, Path(args.out), notifier=notifier,
            require_signoff_pass=args.require_signoff_pass)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # Non-zero exit for a refusal: a caller scripting `signoff-export
        # --require-signoff-pass` into a release pipeline must fail there,
        # not read a 0 and carry on with an empty out dir.
        if result["status"] == "REFUSED":
            raise SystemExit(2)
    elif args.cmd == "knowledge":
        from .config import load_config, save_config
        from .knowledge_center import KnowledgeCenterClient, _default_user
        cfg = load_config(h.root)
        if args.kc_cmd == "setup":
            import time as _time
            kc = cfg.setdefault("knowledge_center", {})
            if args.disable:
                kc["enabled"] = False
                save_config(h.root, cfg)
                print("Shared knowledge center DISABLED.")
                return
            # CLAUDE.md's SSH/Remote Transport Connection Intake rule: never
            # assume or silently attempt a remote path -- always ask, even
            # when --remote-root is passed non-interactively (--yes is a
            # separate, explicit opt-out of the PROMPT, not of asking).
            remote_root = args.remote_root
            if remote_root is None:
                print("目前尚未設定共用知識中心的 Linux server 路徑。" if cfg["policy"]["language"] == "zh-TW"
                      else "No shared knowledge center path is configured yet.")
                remote_root = input("請輸入共用知識中心在 Linux server 上的固定路徑\n"
                                     "Enter the shared knowledge center's fixed path on the Linux server: ").strip()
            if not remote_root:
                print("(未輸入路徑，取消設定 / no path entered, setup cancelled)")
                raise SystemExit(1)
            if not args.yes:
                confirm = input(f"將把 {remote_root} 設為共用知識中心路徑，確定嗎？[y/N] "
                                 f"(confirm setting {remote_root} as the shared knowledge center path) ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("(取消 / cancelled)")
                    raise SystemExit(1)
            kc["remote_root"] = remote_root
            kc["enabled"] = True
            if args.hop_script:
                kc["hop_script"] = args.hop_script
            kc["configured_by"] = _default_user()
            kc["configured_at"] = _time.time()
            save_config(h.root, cfg)
            client = KnowledgeCenterClient(cfg, h.root)
            ping = client.test_connection()
            print(json.dumps({"saved": True, "remote_root": remote_root, "ping": ping},
                              ensure_ascii=False, indent=2))
        elif args.kc_cmd == "status":
            kc = dict(cfg.get("knowledge_center") or {})
            out = {"config": kc}
            if kc.get("enabled") and kc.get("remote_root"):
                out["ping"] = KnowledgeCenterClient(cfg, h.root).test_connection()
            print(json.dumps(out, ensure_ascii=False, indent=2))
        elif args.kc_cmd == "search":
            client = KnowledgeCenterClient(cfg, h.root)
            res = client.search(args.category, args.protocol, args.text, args.limit)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.kc_cmd == "deprecate":
            client = KnowledgeCenterClient(cfg, h.root)
            res = client.deprecate(args.record_id, args.category, args.protocol, args.reason)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.kc_cmd == "confirm":
            client = KnowledgeCenterClient(cfg, h.root)
            res = client.confirm(args.record_id, args.category, args.protocol)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.kc_cmd == "db-info":
            client = KnowledgeCenterClient(cfg, h.root)
            res = client.db_info(args.category, args.protocol, args.action, args.limit)
            print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "user-info":
        from . import user_info
        print(json.dumps(user_info.summarize_user_access(h.root, args.limit), ensure_ascii=False, indent=2))
    elif args.cmd == "save-session":
        from . import session_snapshot
        from .control_plane import now as cp_now
        manifest = session_snapshot.save_session(h.root, args.name, args.note)
        h.store.event({"ts": cp_now(), "event": "SESSION_SAVED", "name": manifest["name"]})
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.cmd == "restore-session":
        from . import session_snapshot
        from .control_plane import now as cp_now
        if args.list or not args.name:
            print(json.dumps(session_snapshot.list_sessions(h.root), ensure_ascii=False, indent=2))
        else:
            try:
                result = session_snapshot.restore_session(
                    h.root, args.name, backup_current=not args.no_backup,
                    require_sha_match=args.require_sha_match)
            except FileNotFoundError as e:
                print(json.dumps({"error": "NOT_FOUND", "message": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            except session_snapshot.SourceIdentityMismatchError as e:
                print(json.dumps({"error": "SOURCE_IDENTITY_MISMATCH", "message": str(e),
                                   "saved_sha": e.saved_sha, "current_sha": e.current_sha},
                                  ensure_ascii=False))
                raise SystemExit(1)
            # events.jsonl is deliberately NOT one of the files restore_session()
            # copies back (see session_snapshot.RESTORE_FILES) -- an
            # append-only audit log should never be destructively rewound,
            # so this marker lands on the same continuous, live log.
            # artifact_reference_verification (session_snapshot Ruling 4): the
            # per-key roll-up only, so the audit trail records whether the
            # never-copied raw command.txt source this session was saved
            # against is still the file on disk. A restore that resumed
            # against a MODIFIED source is exactly the "what changed, with
            # what evidence" question `dv-harness audit` reads this log for;
            # the full per-file detail stays in the printed result.
            h.store.event({"ts": cp_now(), "event": "SESSION_RESTORED",
                            "name": args.name, "auto_backup": result.get("auto_backup"),
                            "artifact_reference_verification": {
                                k: v.get("status") for k, v
                                in (result.get("artifact_reference_verification") or {}).items()}})
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "run-profile":
        from .uvm_generator.run_profile import RunProfileValidationError
        try:
            if args.rp_cmd == "extract":
                from .uvm_generator.makefile_to_run_profile import extract_and_write
                profile = extract_and_write(
                    Path(args.makefile), Path(args.out), target_ip=args.target_ip, ip_prefix=args.ip_prefix
                )
                print(json.dumps(profile, ensure_ascii=False, indent=2))
            elif args.rp_cmd == "justfile":
                from .uvm_generator.run_profile_to_justfile import generate_and_write
                text = generate_and_write(Path(args.profile), Path(args.out))
                print(text)
        except RunProfileValidationError as exc:
            print(f"run-profile {args.rp_cmd} FAILED: {exc}", file=sys.stderr)
            raise SystemExit(1)
    elif args.cmd == "env-manifest":
        from . import env_manifest
        from .env_manifest import (EnvManifestValidationError, RegisterMapValidationError,
                                    SocArchMapValidationError, TestplanSourcesValidationError)
        from .verible_parser import DEFAULT_VERIBLE_BIN, VeribleParseError, VeribleUnavailableError
        from .vip_user_guide_distill import UserGuideDistillError
        if args.envm_cmd == "generate":
            try:
                manifest = env_manifest.generate_and_write(
                    Path(args.out),
                    rtl_files=args.rtl_files,
                    register_map_path=args.register_map_path,
                    vip_config_dump_path=args.vip_config_dump_path,
                    topology_dump_path=args.topology_dump_path,
                    config_db_trace_log_path=args.config_db_trace_log_path,
                    verible_bin=args.verible_bin or DEFAULT_VERIBLE_BIN,
                    designware_home=args.designware_home,
                    user_guide_reference_paths=args.user_guide_reference_paths,
                    soc_arch_map_path=args.soc_arch_map_path,
                    testplan_sources_path=args.testplan_sources_path,
                )
            except (EnvManifestValidationError, RegisterMapValidationError,
                    SocArchMapValidationError, TestplanSourcesValidationError,
                    UserGuideDistillError,
                    VeribleParseError, VeribleUnavailableError) as exc:
                print(f"env-manifest generate FAILED: {exc}", file=sys.stderr)
                raise SystemExit(1)
            # verible parse -> DuckDB (2026-09-04). The manifest write above
            # was previously the ONLY destination this run's real verible
            # output reached; evidence_db.insert_rtl_parse() and its four
            # rtl_* traceability tables had zero live callers. Runs on the
            # parse this generation already performed -- verible is not
            # re-run -- and is best-effort, so it can never turn an
            # already-written, already-validated manifest into a failure.
            env_manifest.ingest_rtl_parse_to_evidence_db(h.root, manifest)
            # env.manifest.json -> Blackboard (2026-09-04). The manifest is
            # current verification truth (CLAUDE.md's Blackboard rule), but it
            # reached only its own git-tracked fact file: no graph node could
            # name it in `blackboard_read`, so no stage could see the real VIP
            # instances / parsed RTL modules / captured topology through the
            # harness's own current-truth channel. Writes a prompt-sized
            # summary (statuses, reasons, names, counts -- never the full
            # verible parse trees); see env_manifest.sync_to_blackboard.
            env_manifest.sync_to_blackboard(h.blackboard, manifest, manifest_path=args.out)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.cmd == "vip-user-guide":
        # Deliberately its own command, not a step inside `env-manifest
        # generate`: "distilled OFFLINE, never loaded into runtime context"
        # is enforced structurally by keeping the only code path that opens
        # a source document off the manifest-generation path entirely.
        from . import vip_user_guide_distill
        from .vip_user_guide_distill import UserGuideDistillError
        if args.vug_cmd == "distill":
            try:
                record = vip_user_guide_distill.distill_user_guide(
                    args.source, args.out_dir, title=args.title, doc_kind=args.doc_kind,
                )
            except UserGuideDistillError as exc:
                print(f"vip-user-guide distill FAILED: {exc}", file=sys.stderr)
                raise SystemExit(1)
            print(json.dumps(record, ensure_ascii=False, indent=2))
    elif args.cmd == "fsdb-report":
        from . import fsdb_report
        result = fsdb_report.run_fsdbreport(args.fsdb, fsdbreport_bin=args.fsdbreport_bin, timeout=args.timeout)
        if result.get("ok"):
            result["parsed_report"] = fsdb_report.parse_fsdbreport_output(result["report_text"])
            # FSDB -> Distillation -> vip_distill -> DuckDB (2026-09-04).
            # vip_distill.distill_fsdbreport() had zero live callers; this
            # real fsdbreport run is the project's only real producer of the
            # evidence it normalizes. Passes the ALREADY-parsed report
            # (never a second parse of the same text) and records the
            # evidence_id it landed in the emitted JSON, so the row is
            # traceable from this command's own output.
            evidence_id = fsdb_report.ingest_report_to_evidence_db(
                h.root, fsdb_path=args.fsdb, parsed_report=result["parsed_report"],
                topic=args.topic, job_id=args.job_id, pattern=args.pattern)
            if evidence_id:
                result["evidence_id"] = evidence_id
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        if not result.get("ok"):
            print(f"fsdb-report FAILED: {result.get('error')}", file=sys.stderr)
            raise SystemExit(1)
    elif args.cmd == "vplan-export":
        from . import vplan_writer
        items = json.loads(Path(args.items_json).read_text(encoding="utf-8"))
        try:
            known_constraint_names = (
                frozenset(args.known_constraint_names) if args.known_constraint_names else None
            )
            evidence = vplan_writer.build_evidence_context(
                pattern_dir=args.pattern_dir, pattern_glob=args.pattern_glob,
                dispatcher_file=args.dispatcher_file,
                dispatcher_pattern_regex=args.dispatcher_pattern_regex,
                task_declaration_sources=args.task_declaration_sources,
                task_declaration_regex=args.task_declaration_regex,
                constraint_declaration_sources=args.constraint_declaration_sources,
                constraint_declaration_regex=args.constraint_declaration_regex,
                known_constraint_names=known_constraint_names,
            )
            known_check_names = frozenset(args.known_check_names) if args.known_check_names else None
            sheets = tuple(args.sheets) if args.sheets else ("verification_plan", "coverage_summary")
            result = vplan_writer.write_vplan_workbook(
                items, output_path=args.out, evidence=evidence, protocol=args.protocol,
                known_check_names=known_check_names, sheets=sheets, workbook_title=args.workbook_title,
            )
        except (vplan_writer.EvidenceSourceEmptyError, vplan_writer.VPlanSchemaError,
                vplan_writer.UnresolvedPatternFileError, vplan_writer.UnknownTaskDeclarationError,
                vplan_writer.PatternNotInDispatcherError, vplan_writer.UnknownCheckerNameError,
                vplan_writer.ConstraintNotInSVSourceError) as e:
            print(json.dumps({"error": type(e).__name__, "reason": e.reason, "detail": e.detail},
                              ensure_ascii=False, indent=2))
            raise SystemExit(1)
        print(json.dumps({
            "path": str(result.path), "row_count": result.row_count,
            "coverage_percent": result.coverage_percent, "counts_by_state": result.counts_by_state,
            "gaps_ranked_count": len(result.gaps_ranked),
        }, ensure_ascii=False, indent=2))
    elif args.cmd == "regression-tier":
        from . import change_impact, regression_tiers

        def _selection_payload(base_sha):
            """The harness-COMPUTED selection: recomputed when a base SHA is
            given, else whatever the last real computation left on disk.
            Never fabricated -- with neither available, the tier resolves
            against an empty selection and says so through
            full_universe_available/empty class lists."""
            if base_sha:
                return change_impact.compute_and_write(h.root, base_sha=base_sha, cfg=h.cfg)
            return change_impact.read_computed_selection(h.root) or {}

        if args.rt_cmd == "list":
            print(regression_tiers.render_tier_table(h.cfg))
        elif args.rt_cmd in ("plan", "start"):
            payload = _selection_payload(getattr(args, "base_sha", None))
            resolved = regression_tiers.tests_for_tier(
                args.tier, payload.get("selection") or {}, cfg=h.cfg,
                full_pattern_universe=change_impact.full_pattern_universe(h.root))
            resolved["change_impact_evidence_id"] = payload.get("change_impact_evidence_id")
            if args.rt_cmd == "start":
                resolved["active_tier_record"] = regression_tiers.record_active_tier(
                    h.root, args.tier, cfg=h.cfg, tests=resolved["tests"],
                    selection_evidence_id=payload.get("change_impact_evidence_id"))
            print(json.dumps(resolved, ensure_ascii=False, indent=2))
        elif args.rt_cmd == "status":
            print(json.dumps(regression_tiers.read_active_tier(h.root),
                              ensure_ascii=False, indent=2))
        elif args.rt_cmd == "clear":
            print(json.dumps({"cleared": regression_tiers.clear_active_tier(h.root)},
                              ensure_ascii=False))
    elif args.cmd == "trend":
        from . import trend_analysis
        kwargs = {}
        if args.seats_per_job is not None:
            kwargs["seats_per_job"] = args.seats_per_job
        if args.rtl_pathspec:
            kwargs["rtl_pathspecs"] = tuple(args.rtl_pathspec)
        if args.min_baseline_samples is not None:
            kwargs["min_samples"] = args.min_baseline_samples
        if args.ratio_threshold is not None:
            kwargs["ratio_threshold"] = args.ratio_threshold
        if args.z_threshold is not None:
            kwargs["z_threshold"] = args.z_threshold
        report = trend_analysis.trend_report(h.root, **kwargs)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(trend_analysis.render_trend_report_text(report))
    elif args.cmd == "sim-log-analyze":
        from . import sim_log_analysis
        if args.log:
            parsed = sim_log_analysis.parse_sim_log_file(args.log)
        else:
            parsed = sim_log_analysis.parse_sim_log(args.log_text)
        classified = sim_log_analysis.classify_signatures(parsed["signatures"])
        result = {
            "total_lines": parsed["total_lines"],
            "epilogue": parsed["epilogue"],
            "signatures": classified,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "exemptions":
        from . import exemptions as exemptions_mod
        from .exemptions import ExemptionValidationError
        ex_path = Path(args.path) if getattr(args, "path", None) else exemptions_mod.default_exemptions_path(h.root)
        try:
            if args.exemptions_cmd == "list":
                as_of = exemptions_mod.parse_as_of(args.as_of)
                entries = exemptions_mod.list_exemptions(ex_path)
                if args.expired_only:
                    entries = exemptions_mod.find_expired(entries, as_of)
                print(json.dumps(entries, ensure_ascii=False, indent=2))
            elif args.exemptions_cmd == "add":
                entry = {
                    "id": args.id,
                    "check_id": args.check_id,
                    "reason": args.reason,
                    "basis_document": args.basis_document,
                    "owner": args.owner,
                    "valid_until": args.valid_until,
                }
                if args.protocol:
                    entry["protocol"] = args.protocol
                if args.notes:
                    entry["notes"] = args.notes
                entry = {k: v for k, v in entry.items() if v is not None}
                saved = exemptions_mod.add_exemption(ex_path, entry)
                print(json.dumps(saved, ensure_ascii=False, indent=2))
            elif args.exemptions_cmd == "check":
                as_of = exemptions_mod.parse_as_of(args.as_of)
                result = exemptions_mod.check_expiry(ex_path, as_of=as_of)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                raise SystemExit(0 if not result["expired"] else 1)
            elif args.exemptions_cmd == "expire-report":
                as_of = exemptions_mod.parse_as_of(args.as_of)
                out_path = Path(args.out) if args.out else exemptions_mod.default_review_queue_path(h.root)
                queue = exemptions_mod.build_review_queue(ex_path, as_of=as_of)
                exemptions_mod.write_review_queue(queue, out_path)
                print(json.dumps({"review_queue_path": str(out_path), "expired_count": len(queue),
                                   "entries": queue}, ensure_ascii=False, indent=2))
                raise SystemExit(0 if not queue else 1)
            elif args.exemptions_cmd == "escalate":
                from .question_queue import QuestionQueueStore
                as_of = exemptions_mod.parse_as_of(args.as_of)
                store = QuestionQueueStore(h.root, exemptions_path=ex_path)
                filed = store.escalate_expired_exemptions(as_of=as_of)
                expired = exemptions_mod.find_expired(exemptions_mod.list_exemptions(ex_path), as_of)
                print(json.dumps({
                    "expired_count": len(expired),
                    "newly_filed_count": len(filed),
                    "questions": [{"id": q["id"], "question_key": q["question_key"],
                                    "tier": q["tier"], "blocking": q["blocking"]} for q in filed],
                    "review_queue_path": str(exemptions_mod.default_review_queue_path(h.root)),
                }, ensure_ascii=False, indent=2))
                # Exit on EXPIRED, not on newly-filed: a second run of this
                # command files nothing (idempotent) but the exemption is
                # still expired and still unanswered, so a CI step must not
                # start passing just because the question already exists.
                raise SystemExit(0 if not expired else 1)
        except ExemptionValidationError as exc:
            # BUG FIX (2026-09-03): before this, a schema-invalid write (add)
            # or a hand-edited bad file on disk (list/check/expire-report,
            # e.g. a calendar-invalid valid_until like "2026-02-30") raised a
            # raw ExemptionValidationError/ValueError traceback straight out
            # of main(). Same clean-message-then-exit(1) convention as
            # run-profile's RunProfileValidationError handling above.
            print(f"exemptions {args.exemptions_cmd} FAILED: {exc}", file=sys.stderr)
            raise SystemExit(1)
    elif args.cmd == "authority":
        from . import source_authority as sa
        try:
            if args.authority_cmd == "order":
                if args.auth_json:
                    print(json.dumps(sa.describe_order(), ensure_ascii=False, indent=2))
                else:
                    print(sa.format_order())
            elif args.authority_cmd == "check-doc":
                print(json.dumps(sa.assert_doc_matches_code(), ensure_ascii=False, indent=2))
            else:  # resolve
                raw = sys.stdin.read() if args.claims == "-" else Path(args.claims).read_text(encoding="utf-8")
                claims = [sa.SourceClaim(**c) for c in json.loads(raw)]
                conflict = sa.resolve_conflict(claims)
                if args.escalate:
                    if not args.subject:
                        print("authority resolve --escalate requires --subject", file=sys.stderr)
                        raise SystemExit(2)
                    rec = sa.escalate_conflict(h.root, conflict, domain=args.domain,
                                                subject=args.subject)
                    conflict["escalated_question_id"] = rec["id"] if rec else None
                if args.auth_json:
                    print(json.dumps(conflict, ensure_ascii=False, indent=2))
                else:
                    print(f"{conflict['verdict']}: {conflict['rule']}")
                    for c in conflict["claims"]:
                        print(f"  tier {c['rank']} {c['doc_phrase']}: {c['claim']}")
                        print(f"      evidence: {c['evidence_path']}")
                    if conflict.get("escalated_question_id"):
                        print(f"  escalated as {conflict['escalated_question_id']}")
                raise SystemExit(0 if conflict["verdict"] == sa.VERDICT_NO_CONFLICT else 1)
        except sa.SourceAuthorityError as exc:
            print(f"authority {args.authority_cmd} FAILED: {exc.reason} "
                  f"{json.dumps(exc.detail, ensure_ascii=False, default=str)}", file=sys.stderr)
            raise SystemExit(1)
    elif args.cmd == "subsystem-discovery":
        from . import subsystem_discovery as sd
        kc_client = None
        if args.knowledge_center:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = sd.require_explicit_selection(
            h.root, args.select or [], knowledge_center_client=kc_client)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(sd.format_report(result))
        # Exit 0 for a pure listing (no --select is a legitimate discovery
        # run, not a failure); exit 2 when a selection was made but is not
        # admissible -- a selected subsystem that is not EXISTS_READY, or a
        # candidate-set conflict that stands. CI-friendly, same convention as
        # `connectivity-check --check-only`.
        raise SystemExit(0 if (not args.select or result["selection_admissible"]) else 2)
    elif args.cmd == "subsystem-analysis":
        from . import subsystem_architecture_analysis as saa
        kc_client = None
        if args.analysis_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = saa.analyze_selected_subsystems(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            # The SYS-1 selection verdict is printed FIRST when it refused, so
            # an empty analysis reads as "nothing was selected", never as
            # "these subsystems are clean".
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(saa.format_analysis_report(result["synthesis"]))
        # Exit 2 when no admissible selection was made (SYS-1's refusal), or
        # when a cross-subsystem conflict stands -- a DUPLICATE_ACTIVE_DRIVER
        # is SYS-12's "stop automatic integration of that resource", so it must
        # not read as a clean run to a CI step.
        conflicts = result["synthesis"]["summary"]["cross_subsystem_conflicts"]
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"] and not conflicts) else 2)
    elif args.cmd == "system-resource-inventory":
        from . import system_resource_inventory as sri
        kc_client = None
        if args.resource_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = sri.analyze_selected_subsystem_resources(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(sri.format_resource_report(result["resource_analysis"]))
        # Exit 2 while SYS-12 has stopped or held any resource: automatic
        # integration is not allowed until ownership is resolved, so a CI step
        # must not read that as a clean run.
        rule = result["resource_analysis"]["active_driver_conflict_rule"]
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and rule["automatic_integration_allowed"]) else 2)
    elif args.cmd == "system-integration-plan":
        from . import system_resource_registry as srr
        kc_client = None
        if args.plan_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = srr.plan_system_integration(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory)
        plan = result["integration_plan"]
        written = (str(srr.write_system_resource_registry(
            h.root, plan["system_resource_registry"])) if args.write_registry else "")
        if args.json:
            print(json.dumps({**result, "registry_written_to": written},
                             ensure_ascii=False, indent=2, default=str))
        else:
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(srr.format_integration_plan_report(plan))
            if written:
                print(f"\nSYS-15 registry written to {written} (planning artifact; nothing "
                      "applies it -- that is SYS-40).")
        # Exit 2 while any SYS-17 Decision is BLOCKED or any subsystem's
        # Integration Status is a BLOCKED_* class: a System-Level composition
        # must not be attempted on that plan, so a CI step must not read it as
        # a clean run.
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and plan["summary"]["integration_plan_clean"]) else 2)
    elif args.cmd == "system-command-plan":
        from . import system_command_plan as scp
        kc_client = None
        if args.cmdplan_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = scp.plan_system_commands(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory)
        document = result["command_plan"]
        escalated = []
        if args.escalate:
            from . import question_queue
            escalated = scp.escalate_command_collisions(
                question_queue.QuestionQueueStore(h.root), document["command_collisions"])
        if args.json:
            print(json.dumps({**result, "escalated_question_ids": [q["id"] for q in escalated]},
                             ensure_ascii=False, indent=2, default=str))
        else:
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(scp.format_system_command_plan_report(document))
            if escalated:
                print(f"\n{len(escalated)} collision question(s) filed into the real "
                      "question queue: " + ", ".join(q["id"] for q in escalated))
        # Exit 2 while any collision blocks integration, any subsystem's mode is
        # at risk, or any command's System-level name is ambiguous. A System
        # command.txt must not be synthesised on that plan, so a CI step must
        # not read it as a clean run.
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and document["summary"]["command_plan_clean"]) else 2)
    elif args.cmd == "system-scheduling-plan":
        from . import system_scheduling_plan as ssp
        kc_client = None
        if args.schedplan_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        result = ssp.plan_system_scheduling(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory)
        document = result["scheduling_plan"]
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(ssp.format_system_scheduling_plan_report(document))
        # Exit 2 while independent subsystems would be globally serialized, any
        # shared resource is unschedulable pending ownership, or the composer's
        # cross-subsystem stubs have stopped raising. A System-Level schedule
        # must not be built on any of those, so a CI step must not read it as a
        # clean run.
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and document["summary"]["scheduling_plan_clean"]) else 2)
    elif args.cmd == "system-topology-analysis":
        from . import system_topology_analysis as sta
        kc_client = None
        if args.topology_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        question_store = None
        if args.topology_escalate:
            from . import question_queue
            question_store = question_queue.QuestionQueueStore(h.root)
        result = sta.analyze_system_topology(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory,
            question_store=question_store)
        document = result["topology_analysis"]
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            if not result["selection"]["selection_admissible"]:
                from . import subsystem_discovery as sd
                print(sd.format_report(result["selection"]))
                print()
            print(sta.format_system_topology_report(document))
            filed = document["address_map_reconciliation"]["summary"]["escalations_filed"]
            if filed:
                print(f"\n{filed} cross-subsystem address question(s) filed into the real "
                      "question queue.")
        # Exit 2 while any cross-subsystem address range conflicts, any clock or
        # reset disagrees, or a subsystem's own address map overlaps itself. A
        # System-Level environment must not be composed over any of those, so a
        # CI step must not read it as a clean run.
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and document["summary"]["topology_clean"]) else 2)
    elif args.cmd == "reference-audit":
        from . import reference_pattern_audit
        result = reference_pattern_audit.audit_directory(
            Path(args.pattern_dir), glob=args.glob,
            question_store=h.root if args.escalate else None)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(reference_pattern_audit.format_report(result))
        raise SystemExit(0 if result["summary"]["verdict"] == "CLEAN" else 1)
    elif args.cmd == "config":
        from .config import load_config, save_config
        cfg = load_config(h.root)
        if args.config_cmd == "set":
            cfg["policy"][args.key] = (args.value == "true")
            save_config(h.root, cfg)
            print(json.dumps({args.key: cfg["policy"][args.key]}, ensure_ascii=False))
        else:  # get
            print(json.dumps(cfg["policy"], ensure_ascii=False, indent=2))
    elif args.cmd == "self-tune":
        from . import self_tuning
        from .memory import MemoryStore
        root = Path(args.project_root)
        store = MemoryStore(root)

        def _project_self_tuning_records():
            ids = [r["memory_id"] for r in store._index() if r.get("level") == "project"]
            out = []
            for mid in ids:
                rec = store.get(mid)
                if rec and rec.get("kind") == "self_tuning_adjustment":
                    out.append(rec)
            return out

        if args.self_tune_cmd == "status":
            # Finding I8 fix (2026-09-02 follow-up): the design spec's own
            # CLI usage comment says `self-tune status` reports "counter,
            # pending count, and last review time" -- this used to print
            # ONLY read_execution_state()'s raw dict (just the counter).
            # pending_count reuses the existing _project_self_tuning_records()
            # helper (same enumeration every other self-tune subcommand
            # already goes through); last_review_at reuses self_tuning's new
            # read_last_review_at() accessor (self_tuning.reset_execution_
            # counter() now stamps it on every review-cycle completion, see
            # that function's own docstring).
            status = dict(self_tuning.read_execution_state(root))
            status["pending_count"] = sum(
                1 for r in _project_self_tuning_records() if r.get("status") == "PENDING")
            status["last_review_at"] = self_tuning.read_last_review_at(root)
            print(json.dumps(status))
            return 0
        if args.self_tune_cmd == "list":
            records = _project_self_tuning_records()
            if args.pending:
                records = [r for r in records if r.get("status") == "PENDING"]
            if args.applied:
                records = [r for r in records if r.get("status") == "APPLIED"]
            print(json.dumps({"records": records}))
            return 0
        if args.self_tune_cmd == "approve":
            record = store.get(args.memory_id)
            if not record or record.get("kind") != "self_tuning_adjustment" or record.get("status") != "PENDING":
                print(json.dumps({"ok": False, "error": "NOT_FOUND_OR_NOT_PENDING"}))
                return 1
            proposal = {"gate_id": record.get("gate_id"), "stage": record.get("stage"),
                        "change": record.get("change"), "rationale": record.get("rationale"),
                        "confidence": record.get("confidence"), "risk_level": record.get("risk_level")}
            # Finding I3 fix (2026-09-02 final-review fix wave): capture the
            # REAL prior parameter state right before applying -- this is the
            # defer-then-approve counterpart to engine.py's AUTO_APPLY-path
            # capture. Only meaningful for a param-change proposal (add/remove
            # proposals have no single scalar "prior value").
            change = proposal.get("change") or {}
            param = change.get("param") if change.get("action") not in ("add", "remove") else None
            prior_state = (
                self_tuning.capture_prior_param_state(root, proposal.get("gate_id"), param)
                if param is not None else {"prior_value": None, "prior_was_absent": None}
            )
            try:
                self_tuning.apply_proposal(root, proposal)
            except ValueError as e:
                # Findings I1/I2 (2026-09-02 final-review fix wave):
                # apply_proposal() now raises ValueError for a proposal
                # targeting a PROTECTED_PARAMETERS entry (I1) or a blocked
                # PROTECTED_REMOVALS removal (I2) instead of either silently
                # overwriting a safety-critical threshold or succeeding as a
                # no-op that still got recorded as APPLIED. Record
                # BLOCKED_PROTECTED (never APPLIED) so the audit trail never
                # misrepresents a blocked change as having succeeded, and
                # return a clean JSON error response instead of a raw
                # traceback -- same {"ok": False, "error": ...} shape every
                # other failure case in this command already uses.
                record["status"] = "BLOCKED_PROTECTED"
                store.add("project", record)
                print(json.dumps({"ok": False, "error": "BLOCKED_PROTECTED", "detail": str(e)}, ensure_ascii=False))
                return 1
            record["status"] = "APPLIED"
            record["prior_value"] = prior_state["prior_value"]
            record["prior_was_absent"] = prior_state["prior_was_absent"]
            store.add("project", record)  # same memory_id already in record -> overwrites in place
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
        if args.self_tune_cmd == "reject":
            record = store.get(args.memory_id)
            if not record or record.get("kind") != "self_tuning_adjustment" or record.get("status") != "PENDING":
                print(json.dumps({"ok": False, "error": "NOT_FOUND_OR_NOT_PENDING"}))
                return 1
            record["status"] = "REJECTED"
            store.add("project", record)
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
        if args.self_tune_cmd == "revert":
            record = store.get(args.memory_id)
            if not record or record.get("kind") != "self_tuning_adjustment" or record.get("status") != "APPLIED":
                print(json.dumps({"ok": False, "error": "NOT_FOUND_OR_NOT_APPLIED"}))
                return 1
            change = record.get("change") or {}
            if change.get("action") == "add":
                # Revert an add: remove it from the overlay's add list.
                overrides = self_tuning.read_overrides(root)
                stage_entry = overrides.get(record.get("stage"), {})
                if change.get("gate_id") in stage_entry.get("add", []):
                    stage_entry["add"].remove(change["gate_id"])
                self_tuning._write_json_atomic(self_tuning._overrides_path(root), overrides)
            elif change.get("action") == "remove":
                overrides = self_tuning.read_overrides(root)
                stage_entry = overrides.get(record.get("stage"), {})
                if change.get("gate_id") in stage_entry.get("remove", []):
                    stage_entry["remove"].remove(change["gate_id"])
                self_tuning._write_json_atomic(self_tuning._overrides_path(root), overrides)
            else:
                # Finding I3 fix (2026-09-02 final-review fix wave): use the
                # REAL prior state captured at approve/auto-apply time
                # (record["prior_value"]/["prior_was_absent"], written by
                # this same approve handler above and by engine.py's
                # AUTO_APPLY path), never the proposal's own self-reported
                # change["from"] -- an LLM-hallucinated "from", or a
                # parameter that was never actually set before (using the
                # gate's own hardcoded default), must not be trusted.
                prior_was_absent = record.get("prior_was_absent")
                if prior_was_absent is None:
                    # Legacy/pre-fix record with no captured prior state
                    # (e.g. written directly via record_adjustment() outside
                    # the approve handler) -- fall back to the old
                    # change["from"] behavior rather than erroring, since
                    # there is genuinely nothing better to use.
                    self_tuning.set_param(root, record.get("gate_id"), change.get("param"), change.get("from"))
                elif prior_was_absent:
                    self_tuning.delete_param(root, record.get("gate_id"), change.get("param"))
                else:
                    self_tuning.set_param(root, record.get("gate_id"), change.get("param"), record.get("prior_value"))
            record["status"] = "REVERTED"
            store.add("project", record)
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
    elif args.cmd == "memory":
        from . import memory_vault as mv
        from . import memory_dedup
        from . import memory_doctor
        from . import memory_router

        if args.memory_cmd == "status":
            provider = mv.get_active_provider(h.root, h.cfg)
            vault_path = mv.resolve_vault_path(h.root, h.cfg)
            all_notes = provider.search({}, limit=1000000)
            counts: Dict[str, int] = {}
            for r in all_notes.get("results", []):
                lvl = str((r.get("frontmatter") or {}).get("memory_level") or "unknown")
                counts[lvl] = counts.get(lvl, 0) + 1
            counts["total"] = sum(counts.values())
            memory_cfg = h.cfg.get("memory") or {}
            print(json.dumps({
                "vault_path": str(vault_path),
                "config": {"provider": memory_cfg.get("provider"), "obsidian_cli": memory_cfg.get("obsidian_cli"),
                           "git_enabled": memory_cfg.get("git_enabled")},
                "provider_status": provider.status(),
                "note_counts": counts,
            }, ensure_ascii=False, indent=2))
        elif args.memory_cmd == "search":
            from .memory import PropertyFilterError, parse_property_filters

            provider = mv.get_active_provider(h.root, h.cfg)
            query: Dict[str, Any] = {"text": args.query}
            if args.tag:
                query["tag"] = args.tag
            if args.exact:
                query["exact"] = args.exact
            if args.linked_to:
                query["linked_to"] = args.linked_to
            if args.memory_level:
                query["memory_level"] = args.memory_level
            for flag in ("protocol", "project", "confidence", "status"):
                value = getattr(args, flag, None)
                if value:
                    query[flag] = value
            if args.properties:
                try:
                    query["property"] = parse_property_filters(args.properties)
                except PropertyFilterError as e:
                    print(json.dumps({"ok": False, "error": "BAD_PROPERTY_FILTER", "detail": str(e)},
                                      ensure_ascii=False))
                    raise SystemExit(2)
            result = provider.search(query, limit=args.limit)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.memory_cmd == "show":
            provider = mv.get_active_provider(h.root, h.cfg)
            result = provider.read(args.note_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result.get("ok") else 1)
        elif args.memory_cmd == "add":
            candidate = {
                "protocol": args.protocol, "failure_signature": args.failure,
                "root_cause": args.root_cause, "configuration": args.configuration,
                "error_pattern": args.error_pattern,
            }
            classification = memory_dedup.classify_note_candidate(h.root, candidate, cfg=h.cfg)
            if classification["classification"] == "DUPLICATE" and not args.force:
                print(json.dumps({"ok": False, "error": "DUPLICATE_KNOWLEDGE",
                                   "classification": classification["classification"],
                                   "best_match": classification.get("best_match")},
                                  ensure_ascii=False, indent=2))
                raise SystemExit(1)
            provider = mv.get_active_provider(h.root, h.cfg)
            frontmatter = {
                "memory_level": args.memory_level, "protocol": args.protocol,
                "status": args.status, "confidence": args.confidence,
                "failure": args.failure, "tags": args.tags,
            }
            sections = {
                "Root Cause": args.root_cause or "", "Context": args.configuration or "",
                "Symptom": args.error_pattern or "", "Fix": args.fix or "",
            }
            result = provider.create(frontmatter, sections=sections)
            result["dedup_classification"] = classification["classification"]
            if classification.get("matches"):
                result["related_notes"] = [m["note_id"] for m in classification["matches"][:5]]
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result.get("ok") else 1)
        elif args.memory_cmd == "promote":
            confidence_inputs = {
                "independent_sources_count": args.independent_sources_count,
                "evidence_refs_verified": args.evidence_refs_verified,
                "counter_evidence_count": args.counter_evidence_count,
                "multi_agent_consensus_count": args.multi_agent_consensus_count,
            }
            try:
                result = memory_router.promote_to_organizational(
                    h.root, args.memory_id, confidence_inputs, cfg=h.cfg, kind=args.kind)
            except ValueError as e:
                print(json.dumps({"promoted": False, "error": "NOT_FOUND", "detail": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            # promote_to_organizational() signals a GATE rejection via
            # "promoted": False + "reason" (see its own docstring/tests --
            # dv_harness_tests/test_memory_vault.py's
            # test_promote_to_organizational_succeeds_once_every_gate_is_satisfied
            # is explicit that a genuine 3-gate PASS is signaled by
            # "destination" being present, NOT by any "promoted": True key,
            # which this function never sets -- the separate "ok"/"error"
            # keys on a gate-passed result instead reflect whether the
            # downstream shared-Knowledge-Center push itself succeeded, an
            # unrelated concern this exit code deliberately does not fold in).
            raise SystemExit(0 if "destination" in result else 1)
        elif args.memory_cmd == "graph":
            provider = mv.get_active_provider(h.root, h.cfg)
            visited = set()
            edges = []
            frontier = [args.note_id]
            for _ in range(max(1, args.depth)):
                next_frontier = []
                for nid in frontier:
                    if nid in visited:
                        continue
                    visited.add(nid)
                    links = provider.list_links(nid)
                    if not links.get("ok"):
                        continue
                    for fwd in links.get("forward_links", []):
                        edges.append({"from": nid, "to": fwd, "type": "forward"})
                        if fwd not in visited:
                            next_frontier.append(fwd)
                    for back in links.get("backlinks", []):
                        edges.append({"from": back, "to": nid, "type": "backlink"})
                        if back not in visited:
                            next_frontier.append(back)
                frontier = next_frontier
                if not frontier:
                    break
            print(json.dumps({"root": args.note_id, "nodes": sorted(visited), "edges": edges},
                              ensure_ascii=False, indent=2))
        elif args.memory_cmd == "validate":
            result = memory_doctor.run_validate(h.root, h.cfg)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result["overall"] != "BLOCKED" else 1)
        elif args.memory_cmd == "sync":
            import shutil as _shutil
            vault_path = mv.resolve_vault_path(h.root, h.cfg)
            mv.bootstrap_vault(vault_path)
            memory_cfg = h.cfg.get("memory") or {}
            git_enabled = bool(memory_cfg.get("git_enabled", False))
            result: Dict[str, Any] = {"vault_path": str(vault_path), "git_enabled": git_enabled}
            if not git_enabled:
                result["message"] = "git integration disabled (memory.git_enabled=false); nothing to sync"
            elif _shutil.which("git") is None:
                result["message"] = "git not found on PATH"
            else:
                mv._ensure_git_repo(vault_path)
                status = mv._run_git(vault_path, ["status", "--porcelain"])
                pending = [l for l in (status.stdout or "").splitlines() if l.strip()] if status else []
                if pending:
                    result["committed"] = mv._commit_vault_change(
                        vault_path, args.message or "manual sync via `dv-harness memory sync`")
                    result["files_changed"] = len(pending)
                else:
                    result["committed"] = False
                    result["files_changed"] = 0
                log = mv._run_git(vault_path, ["log", "--oneline", "-5"])
                result["recent_commits"] = [l for l in (log.stdout or "").splitlines() if l.strip()] if log else []
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.memory_cmd == "resync-notes":
            result = mv.resync_notes_from_memory_store(h.root, h.cfg, note_ids=args.note_ids or None)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if not result["still_partial"] else 2)
        elif args.memory_cmd == "doctor":
            result = memory_doctor.run_doctor(h.root, h.cfg)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result["overall"] != "BLOCKED" else 1)
    elif args.cmd == "question-queue":
        from .question_queue import QuestionQueueStore
        # Every decision written or revoked through this command refreshes the
        # `open_questions_decisions` Blackboard topic (2026-09-04) -- a
        # decision, once made, is current-run truth, and before this a later
        # stage had no way to see it without opening the question queue's own
        # private store. The store would build its own Blackboard from
        # h.root anyway; handing it this session's already-open one just
        # avoids a second object over the same directory.
        qq = QuestionQueueStore(h.root, blackboard=h.blackboard)
        if args.qq_cmd == "add":
            if len(args.options) < 2:
                print(json.dumps({"ok": False, "error": "AT_LEAST_TWO_OPTIONS_REQUIRED"}, ensure_ascii=False))
                raise SystemExit(1)
            context = {
                "affects_pass_fail_verdict": args.affects_pass_fail_verdict,
                "affects_spec_intent": args.affects_spec_intent,
                "affects_read_only_file_change": args.affects_read_only_file_change,
                "blast_radius": args.blast_radius,
                "resolvable_from_manifest": args.resolvable_from_manifest,
                "manifest_value": args.manifest_value,
            }
            try:
                record = qq.add_question(
                    domain=args.domain, question=args.question, context_path=args.context_path,
                    options=args.options, recommendation=args.recommendation,
                    assumption_if_unanswered=args.assumption_if_unanswered,
                    question_key=args.question_key, context=context,
                )
            except ValueError as e:  # QuestionValidationError is a ValueError subclass
                print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            h.store.event({"ts": cp_now(), "cmd": "question-queue-add", "id": record["id"],
                            "tier": record["tier"], "status": record["status"]})
            print(json.dumps(record, ensure_ascii=False, indent=2))
        elif args.qq_cmd == "list":
            results = qq.list_questions(status=args.status, tier=args.tier,
                                          blocking=(True if args.blocking_only else None), domain=args.domain)
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.qq_cmd == "answer":
            try:
                record = qq.answer_question(args.question_id, answer=args.answer, basis=args.basis,
                                              decided_by=args.decided_by or _access_user())
            except KeyError as e:
                print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            h.store.event({"ts": cp_now(), "cmd": "question-queue-answer", "id": record["id"],
                            "overturned": record["overturned"]})
            print(json.dumps(record, ensure_ascii=False, indent=2))
        elif args.qq_cmd == "revoke":
            try:
                revocation = qq.revoke_decision(args.question_key, reason=args.reason,
                                                  revoked_by=args.revoked_by or _access_user())
            except KeyError as e:
                print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            h.store.event({"ts": cp_now(), "cmd": "question-queue-revoke",
                            "question_key": args.question_key, "reason": args.reason,
                            "revoked_by": revocation["revoked_by"]})
            print(json.dumps(revocation, ensure_ascii=False, indent=2))
        elif args.qq_cmd == "digest":
            digest = qq.build_digest(trigger=args.trigger, stage=args.stage,
                                       min_hours_since_last=args.min_hours_since_last)
            h.store.event({"ts": cp_now(), "cmd": "question-queue-digest", "trigger": args.trigger,
                            "emitted": digest["emitted"], "batch_id": digest["batch_id"]})
            print(json.dumps(digest, ensure_ascii=False, indent=2))
        elif args.qq_cmd == "status":
            print(json.dumps(qq.compute_metrics(), ensure_ascii=False, indent=2))
    elif args.cmd == "waveform-dump-scope":
        from . import waveform_dump_gate
        from .question_queue import QuestionQueueStore
        wq = QuestionQueueStore(h.root, blackboard=h.blackboard)
        if args.wds_cmd == "ask":
            try:
                record = waveform_dump_gate.ask_dump_scope_confirmation(
                    h.root, scope=args.scope, proposed_level_or_depth=args.level_or_depth,
                    failure_cone=args.failure_cone, store=wq)
            except ValueError as e:
                print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                raise SystemExit(1)
            h.store.event({"ts": cp_now(), "cmd": "waveform-dump-scope-ask", "id": record["id"],
                            "scope": args.scope, "tier": record["tier"], "status": record["status"]})
            print(json.dumps(record, ensure_ascii=False, indent=2))
        elif args.wds_cmd == "status":
            ok, detail = waveform_dump_gate.verify_dump_scope_confirmation(
                h.root, {"scope": args.scope,
                          # No --confirmed-by means "check that SOMEONE really
                          # answered", so mirror back the real decider rather
                          # than failing the attribution check on an empty
                          # string the caller never claimed.
                          "confirmed_by": args.confirmed_by} if args.confirmed_by else
                {"scope": args.scope, "confirmed_by": _dump_scope_decided_by(wq, args.scope)},
                store=wq)
            print(json.dumps({"confirmed": ok, **detail}, ensure_ascii=False, indent=2))
            raise SystemExit(0 if ok else 2)
    elif args.cmd == "advance":
        # BUG FIX (2026-08-28, multi-persona interaction review -- DV
        # Engineer: "silently bypass all gates AND the event log ... a live,
        # one-command undercut of the harness's core 'LSF DONE != DV PASS'
        # premise"): advance/set-stage/mark move state without any gate
        # ever running. They cannot be removed (useful for recovery/admin),
        # but they must at minimum be audited like every other state-
        # mutating command, and the fact that no gate ran must be visible on
        # the resulting stage state, not indistinguishable from a real PASS.
        # (Logic now lives in dv_harness.commands so dashboard.py's HTTP
        # POST /api/control reuses the exact same implementation.)
        from . import commands
        res = commands.cmd_advance(h)
        print(res["to_stage"] or "END")
    elif args.cmd == "set-stage":
        from . import commands
        commands.cmd_set_stage(h, args.stage)
        print(args.stage)
    elif args.cmd == "mark":
        from . import commands
        commands.cmd_mark(h, args.status, args.message)
        print(args.status)
    elif args.cmd == "run-stage":
        r = h.run_stage(args.goal, args.stage, dry_run=args.dry_run)
        print(r.text)
        raise SystemExit(0 if r.ok else 1)
    elif args.cmd == "start":
        if args.loop:
            # loop(dry_run=True) plans the CURRENT stage and returns without
            # looping -- see DVHarness.loop()'s docstring for why a dry-run
            # deliberately never speculates past one real stage.
            h.loop(args.goal, dry_run=args.dry_run)
            print(h.summary())
        else:
            r = h.run_stage(args.goal, dry_run=args.dry_run)
            print(r.text)
            raise SystemExit(0 if r.ok else 1)

if __name__ == "__main__":
    main()
