from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from .engine import DVHarness
from .models import Stage, Status


def _access_user() -> str:
    # Same fallback chain control_plane.py/knowledge_center.py already use
    # for their own private copies -- kept separate rather than a
    # cross-module import, matching this codebase's established pattern.
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _access_host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-host"


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
    sub = ap.add_subparsers(dest="cmd", required=True)

    pstart = sub.add_parser("start")
    pstart.add_argument("--goal", required=True)
    pstart.add_argument("--loop", action="store_true")

    prun = sub.add_parser("run-stage")
    prun.add_argument("--goal", required=True)
    prun.add_argument("--stage", choices=[s.value for s in Stage])

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
    papprove.add_argument("stage", choices=[s.value for s in Stage])
    papprove.add_argument("--note", default="")
    papprove.add_argument("--reviewer-id", default=None)
    papprove.add_argument("--reviewer-confidence", default="HIGH", choices=["HIGH", "MEDIUM", "LOW"])

    pevidence = sub.add_parser("evidence", help="Show the real evidence blocks/gate verdict a stage's last response produced.")
    pevidence.add_argument("--stage", choices=[s.value for s in Stage], default=None)

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

    pfsdb = sub.add_parser("fsdb-report", help="Run the real `fsdbreport` CLI tool against an FSDB file and "
                                                 "parse/emit its text report. See dv_harness/fsdb_report.py.")
    pfsdb.add_argument("--fsdb", required=True, help="Path to the .fsdb file.")
    pfsdb.add_argument("--out", default=None, help="Write the result JSON here instead of stdout.")
    pfsdb.add_argument("--fsdbreport-bin", default="fsdbreport")
    pfsdb.add_argument("--timeout", type=int, default=60)

    psimlog = sub.add_parser("sim-log-analyze", help="Real sim.log marker parsing/classification/epilogue "
                                                        "extraction. See dv_harness/sim_log_analysis.py.")
    psimlog_group = psimlog.add_mutually_exclusive_group(required=True)
    psimlog_group.add_argument("--log", default=None, help="Path to a sim.log file.")
    psimlog_group.add_argument("--log-text", default=None, help="Inline log text (for testing).")

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
    pvplan.add_argument("--sheet", action="append", default=None, dest="sheets",
                         help="Sheet registry key (repeatable). Default: verification_plan, coverage_summary.")
    pvplan.add_argument("--workbook-title", default=None)

    pconfig = sub.add_parser("config", help="View/update .dv-harness/config.json's policy block.")
    pconfig_sub = pconfig.add_subparsers(dest="config_cmd", required=True)
    pconfig_set = pconfig_sub.add_parser("set", help="dv-harness config set require_dv_review_cosign true|false")
    pconfig_set.add_argument("key", choices=["require_dv_review_cosign"])
    pconfig_set.add_argument("value", choices=["true", "false"])
    pconfig_sub.add_parser("get", help="Print the current policy block.")

    args = ap.parse_args()
    h = DVHarness(Path(args.project_root))
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
            print(json.dumps(describe_stage(h.root, h.state, stage), ensure_ascii=False, indent=2))
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
    elif args.cmd == "lsf-submit":
        from . import lsf_client
        try:
            job_id = lsf_client.bsub_submit(
                args.command, queue=args.queue, cores=args.cores,
                mem_mb=args.mem_mb, run_dir=args.run_dir,
            )
        except lsf_client.LsfUnavailableError as e:
            print(json.dumps({"error": "LSF_UNAVAILABLE", "message": str(e)}, ensure_ascii=False))
            raise SystemExit(1)
        state = lsf_client.JobState(
            job_id=job_id, regression_id=args.regression_id, pattern=args.pattern,
            options=args.options, run_dir=args.run_dir, sim_log=args.sim_log,
            lsf_status="PEND",
        )
        lsf_client.save_job_state(h.root, state)
        print(json.dumps({"job_id": job_id, "state": lsf_client.asdict(state)}, ensure_ascii=False, indent=2))
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
    elif args.cmd == "audit":
        from .dashboard import _audit_trail
        print(json.dumps(_audit_trail(h.root, args.limit), ensure_ascii=False, indent=2))
    elif args.cmd == "self-audit":
        from . import self_audit
        result = self_audit.run_self_audit(h.root, args.gate, smoke=args.smoke)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["summary"]["fail"] == 0 and result["summary"]["smoke_fail"] == 0 else 1)
    elif args.cmd == "signoff-export":
        from . import signoff_export
        result = signoff_export.collect_signoff_bundle(h.root, Path(args.out))
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
            h.store.event({"ts": cp_now(), "event": "SESSION_RESTORED",
                            "name": args.name, "auto_backup": result.get("auto_backup")})
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "fsdb-report":
        from . import fsdb_report
        result = fsdb_report.run_fsdbreport(args.fsdb, fsdbreport_bin=args.fsdbreport_bin, timeout=args.timeout)
        if result.get("ok"):
            result["parsed_report"] = fsdb_report.parse_fsdbreport_output(result["report_text"])
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
            evidence = vplan_writer.build_evidence_context(
                pattern_dir=args.pattern_dir, pattern_glob=args.pattern_glob,
                dispatcher_file=args.dispatcher_file,
                dispatcher_pattern_regex=args.dispatcher_pattern_regex,
                task_declaration_sources=args.task_declaration_sources,
                task_declaration_regex=args.task_declaration_regex,
            )
            known_check_names = frozenset(args.known_check_names) if args.known_check_names else None
            sheets = tuple(args.sheets) if args.sheets else ("verification_plan", "coverage_summary")
            result = vplan_writer.write_vplan_workbook(
                items, output_path=args.out, evidence=evidence, protocol=args.protocol,
                known_check_names=known_check_names, sheets=sheets, workbook_title=args.workbook_title,
            )
        except (vplan_writer.EvidenceSourceEmptyError, vplan_writer.VPlanSchemaError,
                vplan_writer.UnresolvedPatternFileError, vplan_writer.UnknownTaskDeclarationError,
                vplan_writer.PatternNotInDispatcherError, vplan_writer.UnknownCheckerNameError) as e:
            print(json.dumps({"error": type(e).__name__, "reason": e.reason, "detail": e.detail},
                              ensure_ascii=False, indent=2))
            raise SystemExit(1)
        print(json.dumps({
            "path": str(result.path), "row_count": result.row_count,
            "coverage_percent": result.coverage_percent, "counts_by_state": result.counts_by_state,
            "gaps_ranked_count": len(result.gaps_ranked),
        }, ensure_ascii=False, indent=2))
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
    elif args.cmd == "config":
        from .config import load_config, save_config
        cfg = load_config(h.root)
        if args.config_cmd == "set":
            cfg["policy"][args.key] = (args.value == "true")
            save_config(h.root, cfg)
            print(json.dumps({args.key: cfg["policy"][args.key]}, ensure_ascii=False))
        else:  # get
            print(json.dumps(cfg["policy"], ensure_ascii=False, indent=2))
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
        r = h.run_stage(args.goal, args.stage)
        print(r.text)
        raise SystemExit(0 if r.ok else 1)
    elif args.cmd == "start":
        if args.loop:
            h.loop(args.goal)
            print(h.summary())
        else:
            r = h.run_stage(args.goal)
            print(r.text)
            raise SystemExit(0 if r.ok else 1)

if __name__ == "__main__":
    main()
