from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from typing import Any, Dict, Optional
from .engine import DVHarness
from .models import Stage, Status
from .preflight import TRANSPORT_CHOICES
from .router import RESEARCH_FOCUS_DOMAINS
from .mutation_testing import (
    MUTATION_OPERATORS,
    DEFAULT_TIMEOUT_SECONDS as MUTATION_DEFAULT_TIMEOUT,
)
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


# --- Global Status Bar theme (CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md sections
# 412-413): `status full|blockers|jobs|coverage|agents|system|evidence|
# signoff` -- a persistent one-line HarnessStatusIR header (stable enough to
# print before/after any other command and compare by eye), plus 8 detailed
# subviews, both read from this batch's own `harness_status.
# HarnessStatusService` -- never a second aggregation of any field that
# module already computed. Bare `dv-harness status` (no subview) is
# UNCHANGED: it stays exactly `print(h.summary())`, the pre-existing
# engine/graph-state JSON real callers (e.g. `dv_harness_tests/
# test_session_and_info.py::test_status_shows_current_stage`) already parse.
def _harness_status_header_line(snapshot: Dict[str, Any]) -> str:
    """The one persistent, one-line header every subview prints first --
    a pure field selection over an already-computed `HarnessStatusService.
    serve()` snapshot, never a second derivation of harness state."""
    harness = snapshot.get("harness") or {}
    workflow = snapshot.get("workflow") or {}
    execution = snapshot.get("execution") or {}
    blockers = snapshot.get("blockers") or {}

    def _n(v: Any) -> str:
        return "?" if v is None else str(v)

    return (f"[dv-harness] state={harness.get('state', 'UNKNOWN')} "
            f"readiness={harness.get('readiness', 'UNKNOWN')} "
            f"signoff={harness.get('signoff_state', 'UNKNOWN')} "
            f"stage={workflow.get('current_node') or workflow.get('current_operation') or '-'} "
            f"jobs={_n(execution.get('passed_jobs'))}P/{_n(execution.get('failed_jobs'))}F/"
            f"{_n(execution.get('running_jobs'))}R "
            f"blockers={blockers.get('critical_failures', 0)} "
            f"human_gates={blockers.get('human_gates', 0)} "
            f"unknowns={len(snapshot.get('unknowns') or [])}")


def _harness_status_view_payload(view: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Which already-computed `HarnessStatusIR` fields each named subview
    shows -- a pure field selection, never a second derivation of any value
    `HarnessStatusService.serve()` already computed."""
    if view == "blockers":
        return dict(snapshot.get("blockers") or {})
    if view == "jobs":
        return dict(snapshot.get("execution") or {})
    if view == "coverage":
        closure = snapshot.get("closure") or {}
        return {k: closure.get(k) for k in ("functional_coverage", "code_coverage")}
    if view == "agents":
        return dict(snapshot.get("workflow") or {})
    if view == "system":
        identity = snapshot.get("identity") or {}
        closure = snapshot.get("closure") or {}
        payload = {"system": identity.get("system"), "subsystem": identity.get("subsystem"),
                   "closure_system": closure.get("system"), "closure_subsystem": closure.get("subsystem")}
        payload.update(snapshot.get("integration") or {})
        return payload
    if view == "evidence":
        return dict(snapshot.get("evidence") or {})
    if view == "signoff":
        harness = snapshot.get("harness") or {}
        payload = {"signoff_state": harness.get("signoff_state")}
        payload.update(snapshot.get("baseline") or {})
        return payload
    raise ValueError(f"unknown status view: {view!r}")


def _render_harness_status_view(view: str, snapshot: Dict[str, Any], *, as_json: bool) -> str:
    """Render one of the 8 `status <view>` subviews over a real
    `HarnessStatusService.serve()` snapshot. Always leads with the one-line
    header (see above); `full` additionally walks every IR section."""
    header = _harness_status_header_line(snapshot)

    if view == "full":
        if as_json:
            return json.dumps(snapshot, ensure_ascii=False, indent=2)
        lines = [header, ""]
        for section in ("identity", "baseline", "harness", "workflow", "execution",
                         "closure", "integration", "blockers", "resources",
                         "freshness", "evidence"):
            lines.append(f"{section}:")
            for k, v in (snapshot.get(section) or {}).items():
                lines.append(f"  {k}: {v}")
        unknowns = snapshot.get("unknowns") or []
        if unknowns:
            lines.append(f"\n{len(unknowns)} unresolved field(s):")
            for u in unknowns[:10]:
                lines.append(f"  - {u['field']}: {u['reason']}")
        return "\n".join(lines)

    payload = _harness_status_view_payload(view, snapshot)
    if as_json:
        return json.dumps({"header": header, view: payload}, ensure_ascii=False, indent=2)
    lines = [header, "", f"{view}:"]
    for k, v in payload.items():
        lines.append(f"  {k}: {v}")
    if view == "evidence":
        unknowns = snapshot.get("unknowns") or []
        if unknowns:
            lines.append(f"\n{len(unknowns)} unresolved field(s):")
            for u in unknowns[:10]:
                lines.append(f"  - {u['field']}: {u['reason']}")
    return "\n".join(lines)


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

    pstatus = sub.add_parser(
        "status",
        help="Bare: the existing engine/graph-state summary (unchanged). With a subview "
             "(full|blockers|jobs|coverage|agents|system|evidence|signoff): a persistent "
             "one-line HarnessStatusIR header plus that subview's detail, read from "
             "HarnessStatusService (dv_harness/harness_status.py) -- never a second "
             "aggregation. See CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md sections 412-413.")
    pstatus.add_argument(
        "status_view", nargs="?", default=None,
        choices=["full", "blockers", "jobs", "coverage", "agents",
                 "system", "evidence", "signoff"],
        help="Optional HarnessStatusIR subview; omit for the unchanged bare summary.")
    pstatus.add_argument("--json", action="store_true",
                          help="With a subview: print the selected fields as JSON "
                               "instead of plain text.")
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
    # Default kept as a literal (importing regression_reporter here would drag
    # lsf_client + sim_log_analysis into EVERY `dv-harness` invocation just to
    # build the parser). dv_harness_tests/test_watch_cadence_spec.py pins it
    # equal to regression_reporter.DEFAULT_INTERVAL_MINUTES so the two cannot
    # drift apart, and asserts it stays within self_check_list #41's 10-minute
    # ceiling.
    plsf_watch_start.add_argument("--interval-minutes", type=int, default=5,
        help="watch-loop cadence in minutes (default 5; self_check_list #41 "
             "requires the monitor to re-confirm at least every 10 minutes)")

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
    # Second, STRICTLY ADDITIVE gate (2026-09-06): change-budget/blast-radius.
    # The branch gate above asks WHERE the change lands; this one asks HOW FAR
    # it reaches (files touched, transitive importer reach through the real
    # dv_harness import graph, whether it edits a gate/policy file). It runs
    # only on a push the branch gate ALREADY ALLOWED and can only turn an
    # allow into a block -- see dv_harness/change_blast_radius.py.
    pgg.add_argument("--merge-head", default=None,
                      help="MERGE_HEAD (pre-merge-commit only) -- the hook script supplies "
                           "`git rev-parse MERGE_HEAD`, which git does not pass to the hook. "
                           "Used by the blast-radius check to score the commits the merge would "
                           "actually bring in. Absent -> that check reports NOT_ASSESSABLE and "
                           "allows; the branch gate is unaffected either way.")
    pgg.add_argument("--skip-blast-radius", action="store_true",
                      help="Run ONLY the PR-only branch gate, skipping the blast-radius check. "
                           "For diagnosing the branch gate in isolation; it cannot be used to "
                           "weaken the branch gate, which always runs.")

    # Change-budget / blast-radius assessment, standalone. Same computation the
    # git-guard hook path runs, callable before you push so the tier and the
    # digest can be seen (and confirmed) without provoking a blocked push.
    pbr = sub.add_parser("blast-radius",
        help="Estimate a change's blast radius (files touched, transitive dv_harness import "
             "reach, governance/policy files edited) for a real git range, and report whether "
             "it needs human confirmation. See dv_harness/change_blast_radius.py.")
    pbr.add_argument("--base", required=True, help="Base revision (any rev git resolves).")
    pbr.add_argument("--head", default="HEAD", help="Head revision (default HEAD).")

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

    # Mutation testing of THIS repo's own Python test suite. Sits next to
    # self-audit because it answers the neighbouring question: self-audit asks
    # "is the repo's declared state self-consistent", this asks "would the
    # tests guarding a module actually FAIL if that module were wrong".
    # Explicitly NOT DUT/RTL fault injection -- see dv_harness/mutation_testing.py.
    pmut = sub.add_parser("mutation-test",
        help="Inject small AST-level faults (comparison flips, off-by-one boundary constants, "
             "and/or swaps, True/False flips) into a dv_harness/*.py module and re-run that "
             "module's real test file against each mutant, reporting mutants killed/survived. "
             "Measures THIS repo's own test suite -- never a DUT/RTL fault campaign. "
             "See dv_harness/mutation_testing.py.")
    pmut.add_argument("--module", action="append", default=None,
        help="Dotted module to mutate (e.g. dv_harness.qualification); repeatable. "
             "Omit to run every pair registered in mutation_testing.DEFAULT_TARGETS.")
    pmut.add_argument("--test", default=None,
        help="Test file to run against each mutant. Required for a --module with no "
             "DEFAULT_TARGETS entry; must live under dv_harness_tests/.")
    pmut.add_argument("--operator", action="append", default=None,
        choices=list(MUTATION_OPERATORS),
        help="Restrict to this mutation operator; repeatable. Default: all four.")
    pmut.add_argument("--max-mutants", type=int, default=None, dest="max_mutants",
        help="Run at most N mutants (in source order). The rest are reported NOT_RUN, "
             "never silently dropped from the denominator.")
    pmut.add_argument("--lines", default=None,
        help="Only mutate sites on lines A:B of the module.")
    pmut.add_argument("--timeout", type=int, default=None,
        help=f"Per-mutant pytest timeout in seconds (default {MUTATION_DEFAULT_TIMEOUT}). "
             "A mutant that exceeds it is reported TIMEOUT, which is NOT counted as killed.")
    pmut.add_argument("--list", action="store_true", dest="list_only",
        help="Generate and print the mutants without running any tests.")
    pmut.add_argument("--min-score", type=float, default=None, dest="min_score",
        help="Exit non-zero if the mutation score falls below this. Opt-in only -- "
             "mutation score is a measurement here, not a gate.")

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

    psyssignoff = sub.add_parser("system-signoff-package",
        help="System-scope signoff package: assembles real subsystem_contract.py records plus a "
             "system_verification_contract.py rollup and a system_closure_aggregator.py rollup into "
             "one exportable package, reusing signoff_export.py's bundle-manifest mechanics -- the "
             "system-scope sibling of `signoff-export`. See dv_harness/system_signoff_package.py.")
    psyssignoff.add_argument("--root", default=".")
    psyssignoff.add_argument("--out-dir", required=True, dest="out_dir")
    psyssignoff.add_argument("--subsystem", action="append", default=[], dest="subsystems",
        help="a registered subsystem name to live-assemble (repeatable).")
    psyssignoff.add_argument("--subsystem-contracts", default=None, dest="subsystem_contracts_path",
        help="JSON file: a bare array, or {'subsystem_contracts': [...]}, of already-built "
             "subsystem_contract.py-shaped records.")
    psyssignoff.add_argument("--topology", default=None, dest="topology_path")
    psyssignoff.add_argument("--resource-registry", default=None, dest="resource_registry_path")
    psyssignoff.add_argument("--command-registry", default=None, dest="command_registry_path")
    psyssignoff.add_argument("--closure-dimensions", default=None, dest="closure_dimensions_path",
        help="JSON file: a bare list of {dimension_name, status} records, or {'dimensions': [...]}.")
    psyssignoff.add_argument("--system-name", default=None)
    psyssignoff.add_argument("--manifest", default=None, dest="manifest_path",
        help="explicit env.manifest.json path for every live-assembled subsystem.")
    psyssignoff.add_argument("--requirements", default=None, dest="requirements_path")
    psyssignoff.add_argument("--db", default=None, dest="db_path")
    psyssignoff.add_argument("--declared-spec-version", default=None, dest="declared_spec_version")
    psyssignoff.add_argument("--require-system-signoff-pass", action="store_true")
    psyssignoff.add_argument("--json", action="store_true")

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

    pusl = sub.add_parser("uvm-lint", help="Deterministic PRE-SIMULATION structural lint of GENERATED UVM "
                                              "source (factory registration, UVM phase-method signatures, "
                                              "config_db set/get matching, TLM port/export connection "
                                              "completeness, objection raise/drop balance). Parses the real "
                                              "code with verible (same front end as `env-manifest`'s RTL "
                                              "parsing), never regex over raw file text. See "
                                              "dv_harness/uvm_structural_lint.py for the checked subset and "
                                              "its stated limits.")
    pusl_target = pusl.add_mutually_exclusive_group(required=True)
    pusl_target.add_argument("--env-dir", default=None,
                              help="A generated environment directory; every .sv/.svh under it is analysed "
                                   "TOGETHER (config_db, TLM connect and base-class resolution are "
                                   "whole-environment properties).")
    pusl_target.add_argument("--file", action="append", default=None, dest="lint_files",
                              help="An explicit source file to analyse (repeatable), instead of --env-dir.")
    pusl.add_argument("--json", action="store_true", help="Emit the full machine-readable report instead of "
                                                             "the human-readable summary.")
    pusl.add_argument("--fail-on-error", action="store_true",
                       help="Exit 1 when the lint reports ERROR-severity findings (status FAIL). Without it "
                            "the report is printed and the exit code stays 0.")
    pusl.add_argument("--verible-bin", default=None, help="Override the verible-verilog-syntax binary name.")

    ppi = sub.add_parser("power-intent", help="Parse REAL UPF (IEEE 1801) power intent into a structured "
                                                 "model (power domains, supply topology, power switches, "
                                                 "isolation and retention strategies) and check that intent "
                                                 "against ITSELF -- undeclared domains/supplies, a "
                                                 "switchable domain with no isolation, a retention strategy "
                                                 "with no save/restore. Reads files only: nothing is checked "
                                                 "against RTL or simulation and no low-power BEHAVIOR is "
                                                 "verified. Sources with no power intent report "
                                                 "NOT_AVAILABLE (exit 2), never PASS -- spec section 224's "
                                                 "UNSUPPORTED/UNKNOWN outcome. See dv_harness/power_intent.py "
                                                 "for the modelled UPF subset and its stated limits.")
    ppi.add_argument("--upf", action="append", required=True, dest="upf_paths",
                      help="A UPF file to parse (repeatable; parsed in the order given, which is the order "
                           "UPF itself depends on -- a set_isolation_control must follow its set_isolation).")
    ppi.add_argument("--json", action="store_true",
                      help="Emit the full machine-readable report (findings plus the extracted power-intent "
                           "model) instead of the human-readable summary.")
    ppi.add_argument("--fail-on-error", action="store_true",
                      help="Exit 1 when the analysis reports ERROR findings. Without it the report is "
                           "printed and an analysis FAIL still exits 0; NOT_AVAILABLE always exits 2.")

    prc = sub.add_parser("requirement-contract", help="Spec section 184 Canonical Requirement Contract: check "
                                                      "requirement records against the fifteen-field contract "
                                                      "(ID/Source/Feature/Protocol/Configuration/Precondition/"
                                                      "Stimulus/Expected Result/Observability/Checker/Coverage "
                                                      "Intent/Priority/Criticality/Confidence/Status) and its "
                                                      "COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status "
                                                      "vocabulary. The status is RE-DERIVED from each record's "
                                                      "own content, so a record claiming COMPLETE with a field "
                                                      "still TBD, or stepping over an ambiguity/contradiction it "
                                                      "filed itself, is rejected. A CONTRADICTORY requirement "
                                                      "stops for a human -- this never arbitrates between two "
                                                      "disagreeing sources. Same check the extended "
                                                      "REQUIREMENTS_TRACEABILITY gate runs.")
    prc.add_argument("--requirements", required=True,
                     help="JSON file with a top-level `requirements` list. Records that do not declare "
                          "`contract_schema_version` are not in this shape and are not analyzed.")
    prc.add_argument("--json", action="store_true",
                     help="Emit the full machine-readable report instead of the human-readable summary.")
    prc.add_argument("--fail-on-error", action="store_true",
                     help="Also fail on WARNING findings, not only ERROR.")

    psc = sub.add_parser("schema-compat", help="Classify a JSON Schema change as BACKWARD_COMPATIBLE / "
                                               "BREAKING / UNKNOWN, where compatible means every document "
                                               "valid under the old schema is still valid under the new "
                                               "one -- the direction env_manifest.py's 1.0 -> 1.1 bump "
                                               "cared about. Every BREAKING verdict is backed by a witness "
                                               "document this command actually validated with jsonschema "
                                               "against both schemas; a keyword with no compatibility rule "
                                               "(pattern, format, oneOf, ...) reports UNKNOWN rather than "
                                               "being assumed harmless. With --base it also enforces the "
                                               "env_manifest precedent: a breaking schema edit must bump "
                                               "the owning module's SCHEMA_VERSION.")
    psc.add_argument("--old", help="the previous schema file (use with --new)")
    psc.add_argument("--new", help="the new schema file (use with --old)")
    psc.add_argument("--base", help="git revision to compare this working tree's "
                                    "dv_harness/schemas/*.schema.json against")
    psc.add_argument("--root", default=".", help="repository root for --base")
    psc.add_argument("--corpus", nargs="*", default=[],
                     help="real documents to check the verdict against; one that passes the old "
                          "schema and fails the new one proves the change breaking even when the "
                          "static rules missed it.")
    psc.add_argument("--json", action="store_true",
                     help="Emit the full machine-readable report, witness documents included.")

    pgs = sub.add_parser("golden-scenario", help="Spec section 225 golden scenario / reference capsules: "
                                                    "record a proven-good test/scenario against a REAL "
                                                    "evidence_db normalized_evidence PASS row, and derive "
                                                    "FRESH/STALE/UNKNOWN from REAL git history (a real "
                                                    "`git diff <verified_sha>..HEAD` classified by the same "
                                                    "change_impact risk model the regression-selection chain "
                                                    "uses). Freshness is computed, never stored. Recording "
                                                    "REFUSES evidence that is missing, not a PASS, or for a "
                                                    "different test. Runs, builds, submits and approves "
                                                    "nothing. See dv_harness/golden_scenario.py.")
    pgs.add_argument("gs_verb", choices=("record", "list", "status"))
    pgs.add_argument("--json-file", default=None,
                      help="record: the capsule JSON file (GoldenScenario fields) to record.")
    pgs.add_argument("--capsule-id", default=None, help="status: evaluate one capsule only.")
    pgs.add_argument("--head", default="HEAD",
                      help="status: the revision to compare the recorded verified_sha against.")
    pgs.add_argument("--db", default=None,
                      help="Evidence database path (default: <root>/.dv-harness/evidence/evidence.duckdb).")
    pgs.add_argument("--vip-version", action="append", default=None, dest="gs_vip_versions",
                      metavar="TOOL=VERSION",
                      help="status: a CURRENT VIP/tool version (repeatable). A recorded version that no "
                           "longer matches makes the capsule STALE with no git change at all.")
    pgs.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pgsrg = sub.add_parser("global-status-ready-gate",
                            help="GLOBAL_STATUS_READY / CLI_STATUS_READY composite gates over an "
                                 "already-assembled HarnessStatusIR document (its to_dict() JSON) -- "
                                 "structural readiness of the Global Status Bar's own data shape, "
                                 "never a project readiness verdict. Reads only; assembles nothing, "
                                 "runs no stage/gate/build/regression/LSF job, and authorizes "
                                 "nothing. See dv_harness/global_status_ready_gate.py.")
    pgsrg.add_argument("document", help="path to a HarnessStatusIR.to_dict() JSON file")
    pgsrg.add_argument("--json", action="store_true", dest="gsrg_as_json",
                        help="Emit the full machine-readable gates report.")

    ppqf = sub.add_parser("plan-quality-feedback",
                           help="Cross-run stage-sequencing efficiency feedback: groups loop "
                                "sessions (from loop_telemetry.read_loop_telemetry(), never a "
                                "second aggregation) by the graph-traversal SHAPE they took and "
                                "classifies each shape THRASHING/MIXED/EFFICIENT/"
                                "INSUFFICIENT_DATA from real loop_convergence oscillation/plateau "
                                "verdicts and retry ratios. Reads only; runs, builds, submits and "
                                "approves nothing. See dv_harness/plan_quality_feedback.py.")
    ppqf.add_argument("pqf_verb", choices=("show", "report"))
    ppqf.add_argument("--run-id", default=None,
                       help="Restrict the underlying loop_telemetry read to one run_id.")
    ppqf.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pvvd = sub.add_parser("vip-version-drift-detection",
                           help="Cross-environment VIP version drift detection: cross-checks every "
                                "subsystem's env.manifest.json-derived VIP release facts against each "
                                "other and reports STATUS_NO_DRIFT / STATUS_DRIFT_DETECTED / "
                                "STATUS_INCOMPLETE_EVIDENCE / STATUS_NOT_AVAILABLE. One shared "
                                "implementation with `python -m dv_harness.vip_version_drift_detection`. "
                                "Reads only; runs, builds, submits and approves nothing. See "
                                "dv_harness/vip_version_drift_detection.py.")
    pvvd.add_argument("--root", required=True, help="project root under which subsystem manifests "
                                                       "are discovered (or overridden with --manifests).")
    pvvd.add_argument("--manifests", default=None,
                       help="comma-separated name=path pairs overriding registry discovery.")
    pvvd.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pdcg = sub.add_parser("design-completeness-gate",
                           help="Worst-wins completeness rollup over the thirteen real Design "
                                "Intelligence extraction categories (register map, register-to-RTL "
                                "trace, PHY boundary, PHY model behavior, architecture IR, "
                                "interrupt/DMA/clock-reset, programming sequence, verification "
                                "intent, DUT-evidence correlation, design-knowledge correlation, "
                                "design source inventory, spec/doc map, power intent). Each row "
                                "calls that category's own real extractor with caller-supplied "
                                "per-project inputs; a category with no input supplied is UNKNOWN, "
                                "never silently NOT_AVAILABLE. Reads and reports only -- runs, "
                                "builds, submits and approves nothing. Same shared implementation "
                                "as `python -m dv_harness.design_completeness_gate` "
                                "(design_completeness_gate.execute).")
    pdcg.add_argument("--inputs", default=None,
                       help="Path to a JSON file: {row_id: {kwarg: value, ...}} per-category real "
                            "inputs for this project. Omitted or absent categories are UNKNOWN.")
    pdcg.add_argument("--json", action="store_true", help="Print the full matrix as JSON.")

    pspc = sub.add_parser("scenario-pattern-command-txt-correspondence",
                           help="Cross-reference vip_capability_extraction.py's real, classified "
                                "VIPScenarioPatternIR declared sequence-pattern classes against a "
                                "project's real command.txt/pattern branch_b* (VIP-owned) sequence "
                                "usages: CORRESPONDENCE_CONFIRMED/CORRESPONDENCE_NOT_FOUND per usage "
                                "and USED_IN_COMMAND_TXT/NOT_USED_IN_COMMAND_TXT per declared pattern. "
                                "Never a second VIP indexer, command.txt parser, or branch-ownership "
                                "heuristic -- reads real vip_capability_extraction.json + real "
                                "de_command_style_learning classification only. Runs, builds, submits "
                                "and approves nothing. See "
                                "dv_harness/scenario_pattern_command_txt_correspondence.py.")
    pspc.add_argument("--capability-report", required=True,
                       help="A vip_capability_extraction.json document "
                            "(write_capability_extraction_report()'s own output).")
    pspc.add_argument("--command-file", action="append", default=None, dest="spc_command_files",
                       help="A real command.txt/pattern file to scan (repeatable).")
    pspc.add_argument("--out-dir", default=None,
                       help="Also write scenario_pattern_command_txt_correspondence.json here.")
    pspc.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pmuc = sub.add_parser("coord", help="Spec section 239 multi-user coordination CONFLICT "
                                          "DETECTION between two or more concurrent users' "
                                          "project roots: stale-SHA conflict (different base "
                                          "SHAs touching the same file, off the real "
                                          "change_impact computation), duplicate regression "
                                          "submission (same pattern + same commit, off real "
                                          "JobState records and the real computed selection), "
                                          "and shared-resource reservation conflict (off the "
                                          "same AgentTaskStore.acquire() claim ledger the "
                                          "parallel_group fan-out already uses). Reports and "
                                          "arbitrates nothing: it takes no lock, cancels no "
                                          "job, revokes no claim and touches no approval "
                                          "gate. See dv_harness/multi_user_coordination.py.")
    pmuc.add_argument("coord_verb", choices=("detect", "reserve", "release", "list"))
    pmuc.add_argument("--session", action="append", default=None, dest="coord_sessions",
                       metavar="[USER=]PROJECT_ROOT",
                       help="detect: one concurrent session (repeatable, at least twice). "
                            "USER may be omitted, in which case it is read off that root's "
                            "own real CLI_ACCESS/GUI_ACCESS trail.")
    pmuc.add_argument("--resource", default=None, help="reserve/release: the resource id.")
    pmuc.add_argument("--kind", default=None, dest="coord_kind",
                       help="reserve/release: amba_fabric_port | vip_instance | "
                            "license_feature | regression_slot | shared_path.")
    pmuc.add_argument("--agent", default=None, dest="coord_agent",
                       help="reserve: who is claiming it.")
    pmuc.add_argument("--task", default=None, dest="coord_task",
                       help="reserve/release: the claiming task id (a release must come "
                            "from the holding task).")
    pmuc.add_argument("--mode", default="WRITE", choices=("WRITE", "READ"),
                       dest="coord_mode",
                       help="reserve: WRITE (exclusive intent) or READ.")
    pmuc.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pva = sub.add_parser("vip-api-check",
                          help="Spec section 187 VIPApiCard: validate every VIP API call a "
                               "generated sequence makes against a REAL vip_symbol_index over "
                               "real VIP source, and emit the VIPApiCard artifact. A call to a "
                               "VIP class/method the index cannot prove exists is BLOCKED "
                               "(section 187's own 'If API cannot be proven: UNKNOWN / "
                               "BLOCKED'), never silently generated. A citation the index "
                               "cannot DECIDE is UNPROVABLE, never a silent pass. Reports "
                               "only: runs nothing, builds nothing, approves nothing. See "
                               "dv_harness/vip_api_card.py.")
    pva.add_argument("--source", action="append", required=True, dest="va_sources",
                      help="Generated .sv/.svh file or directory to validate (repeatable).")
    pva.add_argument("--index", required=True, dest="va_index",
                      help="vip_symbol_index JSON document (dv_harness.vip_symbol_index).")
    pva.add_argument("--relative-to", default=None, dest="va_relative_to",
                      help="Root for the reported generated-source paths.")
    pva.add_argument("--out-dir", default=None, dest="va_out_dir",
                      help="Also write the VIPApiCard artifact (vip_api_cards.json) here.")
    pva.add_argument("--strict-unprovable", action="store_true", dest="va_strict",
                      help="Exit non-zero on UNPROVABLE citations too, not just BLOCKED ones.")
    pva.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pcv = sub.add_parser("config-variants", help="Spec section 232 configuration variant explosion "
                                                    "control: generate a REDUCED t-way (default pairwise) "
                                                    "covering set of CONFIGURATIONS from a declared config "
                                                    "space (dimensions, legal values, forbidden "
                                                    "combinations, declared critical combinations) instead "
                                                    "of a blind Cartesian product. Real IPOG (Lei et al., "
                                                    "ECBS 2007 -- the algorithm behind NIST ACTS), "
                                                    "deterministic and constraint-aware; a declared "
                                                    "critical configuration is never dropped to reduce "
                                                    "compute, and a pair no legal configuration can contain "
                                                    "is reported UNREACHABLE_UNDER_CONSTRAINTS rather than "
                                                    "silently missing. `verify` checks any combination list "
                                                    "(including a hand-written one) by independent "
                                                    "recount. SELECTS only: runs no build, submits no job, "
                                                    "gates nothing. See dv_harness/config_variant_coverage.py.")
    pcv.add_argument("cv_verb", choices=("plan", "verify"))
    pcv.add_argument("--space", required=True,
                      help="Configuration space JSON (dimensions/constraints/critical_combinations).")
    pcv.add_argument("--strength", type=int, default=2,
                      help="Interaction strength t (default 2 = pairwise).")
    pcv.add_argument("--combinations", default=None,
                      help="verify: JSON list of configurations, or a plan file with a "
                           "'combinations' key, to check against the space.")
    pcv.add_argument("--out", default=None, help="plan: also write the plan JSON to this path.")
    pcv.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    psc = sub.add_parser("supply-chain",
                          help="Dependency / supply-chain governance: inventory this project's "
                               "REAL declared dependencies (pyproject.toml's build-system and "
                               "project requirements, every root requirements*.txt, and the "
                               "installed DesignWare VIP packages env_manifest's own "
                               "$DESIGNWARE_HOME scan finds) and check them against a real "
                               "policy -- pinned-version enforcement, declared-vs-REALLY-"
                               "INSTALLED resolution against this interpreter, and a "
                               "vulnerability-advisory lookup that reports NOT_AVAILABLE rather "
                               "than a fabricated clean result when no real offline advisory "
                               "source exists. Reads only: writes nothing and gates nothing. "
                               "See dv_harness/dependency_supply_chain.py.")
    psc.add_argument("sc_verb", choices=("inventory", "check", "advisory-status"))
    psc.add_argument("--designware-home", default=None,
                      help="Explicit VIP install tree to scan (default: $DESIGNWARE_HOME).")
    psc.add_argument("--no-vip", action="store_true",
                      help="Skip the DesignWare VIP install scan entirely.")
    psc.add_argument("--policy", default=None,
                      help="Supply-chain policy JSON (default: "
                           "<root>/.dv-harness/supply_chain/policy.json).")
    psc.add_argument("--advisory-db", default=None,
                      help="Offline advisory database JSON to check REALLY INSTALLED versions "
                           "against. Without one the advisory check is NOT_AVAILABLE, never "
                           "clean -- no network advisory API is ever contacted.")
    psc.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pbd = sub.add_parser("benchmark-dataset",
                          help="Spec section 226 agent/skill benchmark dataset governance: a "
                               "VERSIONED, content-addressed eval corpus. A registered version is "
                               "immutable (editing a case is refused; bump instead), a bump that "
                               "changes no case is refused, editing a stored case in place is "
                               "reported as CONTENT_DRIFT, and train/test leakage is tracked per "
                               "(case question digest, subject version) so a capability is never "
                               "scored only on the examples used to tune it. Registers and "
                               "inspects; RUNNING an eval is a Python call "
                               "(benchmark_dataset.run_benchmark_eval), because it must name the "
                               "subject under evaluation. See dv_harness/benchmark_dataset.py.")
    pbd.add_argument("bd_verb", choices=("register", "list", "verify", "diff",
                                          "record-tuning-use", "leakage", "runs"))
    pbd.add_argument("--dataset-id", default=None)
    pbd.add_argument("--json-file", default=None,
                      help="register: the dataset version JSON file to register.")
    pbd.add_argument("--version", type=int, default=None, dest="bd_version",
                      help="Operate on this dataset version (default: the latest).")
    pbd.add_argument("--old-version", type=int, default=None, help="diff: the earlier version.")
    pbd.add_argument("--new-version", type=int, default=None, help="diff: the later version.")
    pbd.add_argument("--case-id", default=None)
    pbd.add_argument("--subject-id", default=None,
                      help="The agent/skill being evaluated or tuned.")
    pbd.add_argument("--subject-version", default=None)
    pbd.add_argument("--used-for", default=None,
                      help="record-tuning-use: what the case was used to tune.")
    pbd.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    psbp = sub.add_parser("system-smoke-proof",
                           help="Spec section 206 SYSTEM BUILD & PROOF: the static system MERGE "
                                "COLLISION check (duplicate package/class/interface/module, UVM "
                                "factory type-name collision, overlapping GLOBAL uvm_config_db "
                                "set, virtual-interface conflict) over the REGISTERED subsystem "
                                "environments analysed TOGETHER, plus the smoke-proof ladder "
                                "(Build -> Elaborate -> Boot/Reset/Init -> Shared-Resource-Access "
                                "-> One-Subsystem -> Two-Subsystem-Interaction -> "
                                "End-to-End-Scenario -> WAVE=1/fsdbreport -> "
                                "Scoreboard/Assertion -> SYSTEM_READY). Each rung calls an "
                                "EXISTING real mechanism (connectivity.py's machine gates, the "
                                "Track-B cross-subsystem analysis, fsdb_report.py, evidence_db) "
                                "or reports NOT_AVAILABLE with its real reason -- never a "
                                "fabricated PASS. Generates nothing, submits nothing, enables no "
                                "waveform dump, and arbitrates no driver conflict. Exit 0 "
                                "SYSTEM_READY, 1 SMOKE_FAIL, 2 SMOKE_NOT_PROVEN. See "
                                "dv_harness/system_build_proof.py.")
    psbp.add_argument("--subsystem", action="append", default=None, dest="sbp_subsystems",
                       help="Limit to these REGISTERED subsystems (repeatable). Default: every "
                            "subsystem in the real subsystem_environment_registry.json.")
    psbp.add_argument("--composed-dir", default=None,
                       help="The composed system environment directory (Track A's soc_tb_top.sv "
                            "/ soc_virtual_sequencer.sv), merged into the analysed set under the "
                            "key __system__.")
    psbp.add_argument("--filelist", action="append", default=None, dest="sbp_filelists",
                       help="A system-level filelist for the ELABORATE rung (repeatable). "
                            "Without one that rung is NOT_AVAILABLE: writing a system filelist "
                            "is SYS-40, which stops for human approval.")
    psbp.add_argument("--top-module", default="soc_tb_top")
    psbp.add_argument("--merge-only", action="store_true",
                       help="Run only the static merge-collision check (the BUILD rung), which "
                            "needs no simulator at all.")
    psbp.add_argument("--db", default=None,
                       help="Evidence database path for the SCOREBOARD_ASSERTION rung.")
    psbp.add_argument("--system-job-id", type=int, default=None,
                       help="The system run's job id, whose normalized_evidence rows the "
                            "SCOREBOARD_ASSERTION rung reads.")
    psbp.add_argument("--fsdb", default=None,
                       help="An EXISTING system-level FSDB for the WAVE_FSDBREPORT rung. This "
                            "verb reads a dump; it never enables one.")
    psbp.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    psbp.add_argument("--verible-bin", default=None, help="Override the verible binary name.")

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
    # Spec section 210's per-artifact generation provenance tuple. Each flag
    # is optional and its omission is recorded as an honest NOT_DECLARED --
    # never a default attribution -- so an un-migrated project is never
    # retroactively failed. --require-provenance is the strict opt-in.
    penvm_gen.add_argument("--generated-by", default=None, dest="generated_by",
                            help="Identifier of the agent/skill producing this manifest, in the convention the "
                                 "profiles use to self-identify: the front-matter `name:` of a "
                                 ".claude/agents/*.md profile or a .claude/skills/**/SKILL.md skill "
                                 "(e.g. 'debug-agent'). Checked against the real profiles on disk; an "
                                 "identifier matching none is recorded as declared, never as verified. Omit "
                                 "to report generator.agent as NOT_DECLARED.")
    penvm_gen.add_argument("--input-requirements", default=None, dest="input_requirements_path",
                            help="Path to the requirements document holding the section 184 requirement "
                                 "contract that drove this generation. Use with --input-requirement-id.")
    penvm_gen.add_argument("--input-requirement-id", default=None, dest="input_requirement_id",
                            help="requirement_id of the contract that drove this generation. The record is "
                                 "located in --input-requirements, validated, and run through "
                                 "requirement_contract.downstream_consumable(), so the manifest records "
                                 "whether the cited requirement was actually fit to generate from.")
    penvm_gen.add_argument("--input-file", default=None, dest="input_file_path",
                            help="Fallback input-IR form for a project with no contract-shaped IR: a real "
                                 "driving input file, recorded as path + sha256 + byte size, never content. "
                                 "Mutually exclusive with the requirement-contract form.")
    penvm_gen.add_argument("--project-root", default=None, dest="provenance_project_root",
                            help="Project root whose git HEAD this manifest belongs to, recorded as "
                                 "generator.repository_sha.project. The HARNESS's own SHA is always recorded "
                                 "and is never taken from this path.")
    penvm_gen.add_argument("--require-provenance", action="store_true", dest="require_provenance",
                            help="Strict section 210 contract: fail (exit 1) unless every part of the "
                                 "provenance tuple -- schema version, tool version, a resolved agent, a "
                                 "resolved input IR and a real harness git SHA -- is answered by real "
                                 "content. Off by default.")

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

    pdx = sub.add_parser("doc-extract", help="Fan out this repo's real document extractors CONCURRENTLY "
                                               "across self_check_list.md item #40's eleven document "
                                               "categories (VIP doc/source/examples, DUT doc/registers, IP "
                                               "doc, programming guide, DUT RTL, IP source, top TB, "
                                               "command.txt, standard specs). See "
                                               "dv_harness/doc_extraction_fanout.py.")
    pdx_sub = pdx.add_subparsers(dest="dx_cmd", required=True)
    pdx_sub.add_parser("categories", help="Print the eleven declared categories, each with the real "
                                           "extractor that handles it -- or, for the two that genuinely "
                                           "have none, why none exists.")
    pdx_plan = pdx_sub.add_parser("plan", help="Dry run: what a `run` WOULD dispatch. Opens no document "
                                                "and writes nothing.")
    pdx_run = pdx_sub.add_parser("run", help="Dispatch every selected category's extractor concurrently; "
                                              "each writes into <out>/<category_id>/. Exit 1 if any "
                                              "category FAILED.")
    for _p in (pdx_plan, pdx_run):
        _p.add_argument("--inputs", help="JSON file keyed by category_id (see `doc-extract categories` "
                                          "for each category's input_keys).")
        _p.add_argument("--only", nargs="+", help="Restrict the fan-out to these category ids.")
    pdx_run.add_argument("--out", required=True, help="Output root; each category writes into "
                                                       "<out>/<category_id>/.")
    pdx_run.add_argument("--project-root", help="Project root owning the DocumentIndex that records every "
                                                 "consumed source document (default: --out).")
    pdx_run.add_argument("--max-workers", type=int, help="ThreadPoolExecutor width (default: min(8, "
                                                          "selected categories)).")
    pdx_run.add_argument("--incremental", action="store_true",
                          help="Skip a category whose declared sources are all already registered in the "
                               "DocumentIndex with a matching sha256 and whose artifacts are on disk.")
    pdx_run.add_argument("--no-register", action="store_true",
                          help="Do not record consumed source documents in the DocumentIndex.")

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

    # PC-2's platform observability (2026-09-06, dv_harness/platform_health.py).
    # Deliberately beside `trend` above: `trend` answers "what changed between
    # runs" from the evidence DB alone; this answers "is each subsystem healthy
    # right now, and are we meeting the objectives we declared" by aggregating
    # the degradation state, the recorded execution-preflight events, the
    # connectivity gate state file and `trend`'s own detectors. Read-only --
    # runs no stage, starts no build, submits no job, grants no approval.
    pph = sub.add_parser("platform-health",
                         help="Per-subsystem platform health (HEALTHY/DEGRADED/CRITICAL/"
                              "UNKNOWN) aggregated from the degradation state, the recorded "
                              "EXECUTION_PREFLIGHT events, the connectivity gate state and "
                              "trend_analysis's detectors, plus error budgets for the two "
                              "SLOs this harness can honestly measure. UNKNOWN is never "
                              "reported as a pass. Exit 2 only on DEGRADED/CRITICAL. See "
                              "dv_harness/platform_health.py.")
    pph.add_argument("--json", action="store_true",
                     help="Print the raw report dict (per-subsystem state/reason/detail/"
                          "fact_source/observations, every error budget, and the "
                          "unmeasurable-SLI refusal list) instead of the text report.")
    pph.add_argument("--window-days", type=int, default=None,
                     help="Rolling window both SLOs and the self-reporting subsystem are "
                          "measured over (default: config.json platform_health.window_days, "
                          "else 14).")

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

    pspr = sub.add_parser("system-phase1-report",
                          help="SYS-33..39: plan the System regression from known-good "
                               "subsystem tests, selected command sequences, "
                               "cross-subsystem scenarios, shared-resource contention, "
                               "boot/config, interrupt, DMA and stress/concurrency; pin "
                               "each subsystem's release_sha as one composition snapshot; "
                               "diff each subsystem against that pin for change impact; "
                               "derive READY/PARTIAL/BLOCKED/UNKNOWN; then produce SYS-38's "
                               "twenty-two-section Phase-1 report and STOP per SYS-39. "
                               "Runs no regression, submits no job, writes no System "
                               "command.txt and publishes nothing to the Knowledge Center.")
    pspr.add_argument("--select", action="append", default=None, metavar="SUBSYSTEM",
                      help="Name one subsystem to include. Repeatable. Required -- SYS-1's "
                           "explicit-selection refusal is not bypassed by this command.")
    pspr.add_argument("--knowledge-center", action="store_true", dest="phase1_kc",
                      help="Also query the shared Knowledge Center during the SYS-1 "
                           "discovery this command runs first. Off by default (real "
                           "remote call). It only READS: SYS-34's composition record is "
                           "built and printed, never published, because SYS-39 stops "
                           "before the integration SYS-34 records.")
    pspr.add_argument("--command-inventory", default=None, metavar="CSV",
                      help="Path to a command_inventory.csv to read as a DECLARED overlay "
                           "for the SYS-8 contract set. Read-only; never rewritten.")
    pspr.add_argument("--escalate", action="store_true", dest="phase1_escalate",
                      help="Also file every cross-subsystem address conflict into the REAL "
                           "question queue through source_authority.escalate_conflict(). "
                           "Idempotent: a re-run over unchanged address maps re-mints the "
                           "same Q-IDs.")
    pspr.add_argument("--head-rev", default="HEAD", metavar="REV",
                      help="The revision each subsystem's own tree is diffed TO for SYS-36 "
                           "change impact. The BASE is always that subsystem's registered "
                           "release_sha and is never overridable -- a pin the caller could "
                           "move is not a pin.")
    pspr.add_argument("--write-pin", action="store_true", dest="phase1_write_pin",
                      help="Also append the SYS-35 composition snapshot to "
                           ".dv-harness/soc-composer/system_composition_pins.json. Off by "
                           "default: producing the report writes nothing.")
    pspr.add_argument("--json", action="store_true",
                      help="Print raw JSON instead of the SYS-38 twenty-two-section report.")

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

    psaov = sub.add_parser("source-authority-order-validation",
                            help="Report whether source_authority.py's fixed 9-level AUTHORITY_ORDER "
                                 "actually matches which side a human has picked in practice, over this "
                                 "project's real, answered Tier-3 conflict escalations. Read-only -- "
                                 "never edits AUTHORITY_ORDER. See "
                                 "dv_harness/source_authority_order_validation.py.")
    psaov.add_argument("--json", action="store_true",
                        help="Emit the machine-readable report.")

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
    # Cross-project pattern mining (VI-2, dv_harness/cross_project_mining.py):
    # the tier ABOVE the per-project memory stores -- "the same root cause
    # keeps recurring across our projects, and one of them already fixed it".
    # A pure read of N registered project roots; it writes no memory record of
    # any tier and promotes nothing (promote_to_organizational() remains the
    # only route into the organizational tier).
    pxproj = sub.add_parser("cross-project",
                             help="Mine recurring root-cause/fix patterns ACROSS registered projects' "
                                  "memory stores. Pure read -- promotes nothing. "
                                  "See dv_harness/cross_project_mining.py.")
    pxproj_sub = pxproj.add_subparsers(dest="xproj_cmd", required=True)
    pxproj_reg = pxproj_sub.add_parser("register", help="Register another project root as mineable. Refused if it "
                                                          "has no memory store, or if its store shares memory_ids "
                                                          "with an already-registered one (one store under two "
                                                          "names is one project, not two).")
    pxproj_reg.add_argument("root", help="Path to the other project's root (the directory holding its .dv-harness/).")
    pxproj_reg.add_argument("--id", dest="xproj_id", default=None,
                             help="Project id to register it under (default: the directory name).")
    pxproj_unreg = pxproj_sub.add_parser("unregister", help="Remove one project id from the registry.")
    pxproj_unreg.add_argument("project_id")
    pxproj_sub.add_parser("list", help="Every registered project root.")
    pxproj_sub.add_parser("status", help="Whether this installation can produce a real cross-project result yet "
                                           "-- computed from the registry, not claimed.")
    pxproj_mine = pxproj_sub.add_parser("mine", help="Mine every registered project and report cross-project "
                                                       "patterns, including any fix verified in one project for a "
                                                       "failure another still has open.")
    pxproj_mine.add_argument("--min-projects", type=int, default=None, dest="xproj_min_projects",
                              help="Distinct projects required before a signature is reported as cross-project "
                                   "(default and minimum 2).")

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

    # USAGE_MULTI_USER_SAFETY.md:16-19 records as standing policy that "every
    # harness update must sync to /home/svcacct/AI/Agent". The Knowledge
    # Center half of that policy has been real since knowledge_center.py; the
    # CODEBASE half had no verb here at all (2026-09-05 audit), so every sync
    # in this repo's history was a hand-performed file-by-file copy narrated
    # in a .work report. dv_harness/harness_deploy.py is that mechanism; this
    # is its front door.
    phd = sub.add_parser("harness-deploy",
                          help="Sync THIS harness checkout (dv_harness/, .claude/skills, .claude/agents, "
                               "tools/, CLAUDE.md -- declared in harness_deploy.manifest.json) to the shared "
                               "Linux Agent deployment path. Diffs by md5 and pushes only what differs; "
                               "server-side-only files are surfaced as a human decision, never deleted.")
    phd_sub = phd.add_subparsers(dest="hd_verb", required=True)
    phd_man = phd_sub.add_parser("manifest", help="Print the resolved file set + local SOURCE_ID. "
                                                   "Needs no remote side and makes no network call.")
    phd_man.add_argument("--print-md5sum-command", action="store_true", dest="print_md5sum_command",
                          help="Also print the real `remote_exec.py \"md5sum ...\"` command that captures "
                               "the remote side for `plan --remote-md5sum-transcript`.")
    phd_man.add_argument("--remote-root", default=None, dest="remote_root")
    for _hd_name, _hd_help in (
        ("plan", "Compute the push delta. ZERO network calls: the remote side comes from a local "
                 "--target-root directory or an already-captured transcript. Exits 1 when there is "
                 "work to push, 3 when server-only files need a human decision."),
        ("apply", "Push the delta. --target-root copies into a local/staging directory for real; the "
                  "relay path builds the tarball and PRINTS the remote_exec.py sequence unless "
                  "--execute is given."),
    ):
        _hd = phd_sub.add_parser(_hd_name, help=_hd_help)
        _hd.add_argument("--target-root", default=None, dest="target_root",
                          help="A local directory standing in for the remote deployment path.")
        _hd.add_argument("--remote-md5sum-transcript", default=None, dest="remote_md5sum_transcript",
                          help="A real captured `remote_exec.py \"md5sum ...\"` stdout transcript "
                               "(REMOTE_HOST=/EXIT_CODE=/STATUS= markers required, same convention "
                               "server_sync_identity_gate.py already uses).")
        _hd.add_argument("--assume-remote-empty", action="store_true", dest="assume_remote_empty",
                          help="Declare a first-ever deployment explicitly. Never inferred from a "
                               "missing/unreadable transcript.")
        _hd.add_argument("--remote-root", default=None, dest="remote_root")
        # core.autocrlf is true on this checkout, so the Windows working copy
        # holds CRLF while a git-cloned Linux deployment holds LF -- the raw
        # byte diff would be every text file, forever. Tolerant by default;
        # this flag asks for the raw diff.
        _hd.add_argument("--strict-line-endings", action="store_true", dest="strict_line_endings",
                          help="Report the raw byte diff, without treating a CRLF-vs-LF-only "
                               "difference as unchanged.")
        if _hd_name == "apply":
            _hd.add_argument("--execute", action="store_true",
                              help="Actually run the remote_exec.py transport sequence. Only from a "
                                   "session that has completed CLAUDE.md's SSH/Remote Transport "
                                   "Connection Intake -- omitted, nothing touches the network.")

    # LOOP_ENGINEERING sections 85/86: the LoopContract schema and the canonical
    # loop state machine. Every contract is DERIVED from its driver module's own
    # constants (dv_harness/loop_contract.py), never hand-maintained, so this is
    # a read-only front door -- there is no `sync`/`set` verb precisely because a
    # second, editable copy of a contract would be the parallel mechanism this
    # project forbids.
    plc = sub.add_parser("loop-contract",
                          help="The LoopContract (section 85) and LoopState machine (section 86) "
                               "for this harness's three real loops: verification_closure, "
                               "project_learning, capability_evolution. Read-only; contracts are "
                               "derived from the driver modules' own constants.")
    plc_sub = plc.add_subparsers(dest="lc_verb", required=True)
    plc_sub.add_parser("states", help="Print the LoopState vocabulary, the legal transition "
                                       "table, and the total models.Status -> LoopState mapping.")
    plc_sub.add_parser("list", help="One line per loop: id, type, owner, driver entry point, "
                                     "machine-checkable done condition.")
    _plc_show = plc_sub.add_parser("show", help="One loop's full section-85 contract. Schema-"
                                                 "validated and its driver entry point resolved "
                                                 "through the import system before printing.")
    _plc_show.add_argument("loop_id", help="verification_closure | project_learning | "
                                            "capability_evolution")
    _plc_show.add_argument("--format", default="json", choices=["json", "yaml"], dest="lc_format",
                            help="yaml renders section 85's own YAML shape.")
    plc_sub.add_parser("observe", help="Each loop's CURRENT LoopState, derived from real state "
                                        "on disk (state.json, control.json, the Blackboard "
                                        "debug_loop_history and capability_evolution_candidates "
                                        "topics). A loop with no persisted state reports "
                                        "NOT_OBSERVABLE with its reason, never a guess.")
    # Sections 88-90 (dv_harness/loop_convergence.py). Read-only like the rest
    # of this front door: it classifies the real coverage series and reports
    # which coverage bins would need escalation -- it escalates none of them.
    plc_sub.add_parser("convergence",
                        help="Sections 88-90: classify this project's real coverage series as "
                             "CONVERGING/SLOW_CONVERGENCE/NO_PROGRESS/PLATEAU/REGRESSION/"
                             "OSCILLATING/UNKNOWN, run the plateau (unreachable-bin / "
                             "stimulus-gap) investigation, and report both oscillation "
                             "fingerprints. Exit 2 when no usable series exists.")

    # LOOP_ENGINEERING sections 91/92/93: the unified loop budget ledger, the
    # failure-type taxonomy and the circuit breaker (dv_harness/loop_budget.py).
    # `reset`/`breaker-reset` are the only two mutating verbs, and both REQUIRE
    # a real reason and a real actor -- section 91's "budget exhaustion is
    # explicit and cannot silently reset", enforced at the front door as well as
    # in the engine. Neither authorizes any work; they only let a stopped loop
    # try again, and every approval gate that stood before still stands.
    plb = sub.add_parser("loop-budget",
                          help="Sections 91/92/93: this run's unified budget ledger (what was "
                               "spent on each of the eleven dimensions, against which limit, "
                               "read from the real config keys that enforce them), the "
                               "failure-type taxonomy, and the circuit breaker.")
    plb_sub = plb.add_subparsers(dest="lb_verb", required=True)
    plb_sub.add_parser("dimensions",
                       help="Section 91's eleven budget dimensions with each one's REAL limit "
                            "and the real config key that sets it -- or, where nothing bounds "
                            "it, the honest reason nothing does. Plus the ten failure types "
                            "and which of them retrying can resolve.")
    plb_sub.add_parser("status",
                       help="This project's ledger: spend, remaining, exhaustion history, "
                            "recorded resets and the circuit-breaker state. Exit 2 while any "
                            "declared budget is exhausted or the breaker is OPEN.")
    _plb_cls = plb_sub.add_parser("classify",
                                  help="Classify one failure text (a stage's blocking_reason, "
                                       "an adapter stderr, a sim.log excerpt) into section "
                                       "93's taxonomy, showing the rule that decided it.")
    _plb_cls.add_argument("--text", required=True, help="The failing attempt's evidence text.")
    _plb_reset = plb_sub.add_parser("reset",
                                    help="Clear ONE dimension's spend. Requires --reason and "
                                         "--by; appends an append-only record of the spend "
                                         "that was cleared.")
    _plb_reset.add_argument("--dimension", required=True)
    _plb_reset.add_argument("--reason", required=True,
                            help="Why this budget may be reset. Recorded verbatim.")
    _plb_reset.add_argument("--by", required=True,
                            help="Who decided. Recorded verbatim.")
    _plb_br = plb_sub.add_parser("breaker-reset",
                                 help="Section 93's REQUIRE RECOVERY CONDITION: close an OPEN "
                                      "circuit breaker. Requires --reason (what recovery "
                                      "condition was actually met) and --by.")
    _plb_br.add_argument("--reason", required=True)
    _plb_br.add_argument("--by", required=True)

    # Section 47's GOLDEN FLOW READINESS MATRIX (dv_harness/golden_flow_readiness.py).
    # Read-only aggregation over sources that are ALREADY real -- state.json,
    # gates.effective_stage_gates(), dashboard.py's coverage/LSF/memory/protocol
    # readers, signoff_export, env.manifest.json's testplan_correspondence,
    # memory_doctor -- rendered into the document's own five-column row shape.
    # It runs no stage, invokes no gate script and writes no governance state.
    pgfr = sub.add_parser("golden-flow-readiness",
                          help="Section 47's twenty-row Golden Flow Readiness Matrix "
                               "(Golden Flow Stage | Status | Evidence | Gap | "
                               "Next-Best-Action) for this project, aggregated from the "
                               "real per-domain sources that already exist. Read-only: "
                               "runs no stage and writes no state. Exit 2 unless every "
                               "row is READY.")
    pgfr.add_argument("--json", action="store_true",
                      help="Print the raw matrix JSON (row_id, harness_stages, "
                           "fact_source and basis per row) instead of the report.")

    # Section 211's GENERATION READINESS MATRIX (dv_harness/generation_readiness.py).
    # A SEPARATE matrix from golden-flow-readiness above, not an overload of it:
    # section 47 asks "did this project's twenty GOLDEN FLOW STAGES connect with
    # evidence" and reads stage run state; section 211 asks "does this FACTORY
    # have the generation capability each rung of Flow A (spec -> subsystem UVM)
    # and Flow B (subsystem UVM -> system-level UVM) needs" and reads GENERATION
    # ARTIFACTS -- env.manifest.json's layers, the protocol capability registry,
    # the subsystem environment registry and the real SYS-1..40 cross-subsystem
    # analysis. Neither table is derivable from the other and neither reads the
    # other's sources. Read-only: runs no stage, starts no build, arbitrates no
    # active-driver ownership conflict.
    pgenr = sub.add_parser("generation-readiness",
                           help="Section 211's twenty-row Generation Readiness Matrix "
                                "(Capability | Status | Existing Reuse | Evidence | Gap | "
                                "Priority | Action) for this project, aggregated from the "
                                "real generation mechanisms and generation artifacts that "
                                "already exist. Read-only: runs no stage, starts no build "
                                "and never arbitrates a driver conflict. Exit 2 unless "
                                "every row is READY.")
    pgenr.add_argument("--json", action="store_true",
                       help="Print the raw matrix JSON (row_id, capability, "
                            "project_evidence_status, fact_source, priority_basis and "
                            "basis per row) instead of the report.")
    pgenr.add_argument("--no-deep", action="store_true",
                       help="Skip the SYS-1..SYS-30 cross-subsystem topology chain; the "
                            "Flow-B topology/command rows then report UNKNOWN with that "
                            "as their recorded reason rather than a guessed status.")

    # VI-4's VERIFICATION STRATEGY OPTIMIZER (dv_harness/verification_strategy.py).
    # Read-only, and deliberately loud about its own boundary: this harness can
    # EXECUTE simulation only, so `capabilities` exists as a first-class verb --
    # a caller must be able to ask "which of these can you actually run" without
    # first asking for a recommendation. Every executability value is derived
    # from the import system at report time, never declared.
    pvs = sub.add_parser("verification-strategy",
                         help="VI-4: which verification strategy (simulation / formal / PSS / "
                              "emulation / FPGA prototype) the REAL signals indicate for a "
                              "goal -- coverage-closure difficulty, failure density, protocol "
                              "capability and declared scope. Names honestly which strategies "
                              "this harness can EXECUTE (simulation) vs. only RECOMMEND. "
                              "Read-only: runs nothing and writes nothing. Exit 2 when the "
                              "recommendation names a strategy this harness cannot execute.")
    pvs_sub = pvs.add_subparsers(dest="vs_verb", required=True)
    pvs_sub.add_parser("capabilities",
                       help="Per strategy: EXECUTABLE_HERE (with the real entry points it "
                            "goes through) or RECOMMEND_ONLY_NO_BACKEND (with the reason no "
                            "backend exists). Derived by resolving each declared backend "
                            "through the import system.")
    _pvs_rec = pvs_sub.add_parser("recommend",
                                  help="The full five-row recommendation for one goal, each row "
                                       "carrying its verdict, its executability and the real "
                                       "signal that decided it.")
    _pvs_rec.add_argument("--goal", default="",
                          help="The verification goal. RECORDED VERBATIM and never parsed into "
                               "a verdict (goal_text_machine_evaluated is always false).")
    _pvs_rec.add_argument("--scope", default="UNDECLARED",
                          choices=["BLOCK", "SUBSYSTEM", "SYSTEM", "UNDECLARED"],
                          help="Declared verification scope -- a caller fact, never inferred "
                               "from --goal. SYSTEM is what opens the PSS rule.")
    _pvs_rec.add_argument("--protocol", default=None,
                          help="Protocol key, resolved through protocol_capability.")
    _pvs_rec.add_argument("--holes", default=None,
                          help="JSON file of real coverage holes (a list, or {\"holes\": [...]}) "
                               "-- the same shape loop_convergence.investigate_plateau() takes.")
    _pvs_rec.add_argument("--json", action="store_true",
                          help="Print the raw report JSON instead of the rendered report.")

    # ------------------------------------------------------------------
    # grpA wiring (2026-09-06): pure front-door wiring for 14 already-built,
    # already-tested real dv_harness modules. Each module already has its own
    # `python -m dv_harness.<module>` front door (execute_verb()/main()); the
    # blocks below add a matching dv-harness verb that imports the module and
    # calls that same real implementation. No new logic here.
    # ------------------------------------------------------------------

    pacc = sub.add_parser("agent-checkpoint-check",
                          help="Checks a build/investigation tree for a resume-state artifact "
                               "matching CORE/agent-checkpoint-discipline/SKILL.md's schema "
                               "(dual-file CLAUDE.md+docs/*.md, or single-file RESUME.md/"
                               "STATUS.md). Exit 0 current, 1 missing/incomplete/stale. See "
                               "dv_harness/agent_checkpoint_check.py.")
    pacc.add_argument("build_tree", help="Path to the build/investigation tree to check "
                                          "(need not be a DVHarness project itself).")
    pacc.add_argument("--stale-threshold-hours", type=float, default=None,
                      help="Hours of gap (artifact mtime vs. newest other file in tree) before "
                           "flagging stale. Defaults to the module's own threshold.")

    papp = sub.add_parser("agent-parallelism-policy",
                          help="Task-class priority policy (Critical/Normal/Deferred/Blocked) "
                               "and per-resource concurrency caps layered on top of "
                               "resource_orchestrator.py's GRANTED/QUEUED/DEFERRED ranking. "
                               "Same convention as `python -m dv_harness.agent_parallelism_policy`. "
                               "See dv_harness/agent_parallelism_policy.py.")
    papp.add_argument("app_verb", choices=("policy", "plan"))
    papp.add_argument("--policy-path", default=None,
                      help="Path to an agent_parallelism_policy.json-shaped file; defaults to "
                           "dv_harness/agent_parallelism_policy.json.")
    papp.add_argument("--requests", default="",
                      help="plan: JSON list of contenders (project_id/stage/"
                           "consumes_scarce_resource/[task_class]/...).")
    papp.add_argument("--resource-name", default="",
                      help="plan: the resource name to look up in the policy's per-resource "
                           "caps, e.g. 'eda_license' or 'lsf_queue:regression'.")
    papp.add_argument("--queue", default="")
    papp.add_argument("--json", action="store_true",
                      help="Emit the machine-readable payload (default: still JSON -- this "
                           "module's own front door always prints JSON).")

    pafc = sub.add_parser("amba-functional-coverage-ir",
                          help="Builds an AMBAFunctionalCoverageIR (connectivity/memory-map/"
                               "routing/ordering coverpoints, 7-value reachability, meaningful "
                               "crosses only) from a caller-declared facts file. See "
                               "dv_harness/amba_functional_coverage_ir.py.")
    pafc.add_argument("--facts", required=True,
                      help="JSON file: {'legal_edges','address_regions','route_facts',"
                           "'ordering_facts','cross_requests'}.")
    pafc.add_argument("--json", action="store_true", help="Emit the machine-readable IR.")

    paprg = sub.add_parser("amba-performance-readiness-gates",
                           help="BUS_PERFORMANCE_READY / BUS_PERFORMANCE_SIGNOFF_READY composite "
                                "gates over caller-supplied condition records -- never computes "
                                "a performance number itself. See "
                                "dv_harness/amba_performance_readiness_gates.py.")
    paprg.add_argument("aprg_verb", choices=("gates", "conditions", "evaluate"))
    paprg.add_argument("--gate", default=None, help="conditions: one gate name.")
    paprg.add_argument("--conditions", default=None,
                       help="evaluate: path to a JSON list of condition records.")
    paprg.add_argument("--not-applicable", default=None,
                       help="evaluate: path to a JSON object mapping gate name to its "
                            "NOT_APPLICABLE declaration.")
    paprg.add_argument("--json", action="store_true")

    parg = sub.add_parser("amba-readiness-gates",
                          help="The 9 named composite AMBA readiness gates from section 71 "
                               "(L3_REFERENCE_READY .. AMBA_SIGNOFF_READY), each a real "
                               "AND-formula over caller-supplied condition records. See "
                               "dv_harness/amba_readiness_gates.py.")
    parg.add_argument("arg_verb", choices=("gates", "conditions", "evaluate"))
    parg.add_argument("--gate", default=None, help="conditions: one gate name.")
    parg.add_argument("--conditions", default=None,
                      help="evaluate: path to a JSON list of condition records.")
    parg.add_argument("--json", action="store_true")

    papi = sub.add_parser("arbitration-policy-ir",
                          help="Classifies a fabric's real arbitration scheme (FIXED_PRIORITY / "
                               "ROUND_ROBIN / WEIGHTED_ROUND_ROBIN / AGE_BASED / QOS_BASED / "
                               "UNKNOWN) strictly from supplied RTL/spec evidence text, plus a "
                               "starvation-risk assessment. Reads and reports only. See "
                               "dv_harness/arbitration_policy_ir.py.")
    papi.add_argument("--evidence-file", default=None,
                      help="Path to a text file containing the real RTL/spec evidence to "
                           "classify.")
    papi.add_argument("--request-pattern-file", default=None,
                      help="JSON file with a declared request pattern.")
    papi.add_argument("--fabric-name", default=None, help="Label only -- never used to classify.")
    papi.add_argument("--component-name", default=None,
                      help="Label only -- never used to classify.")
    papi.add_argument("--json", action="store_true", help="Emit the machine-readable IR.")

    pafcm = sub.add_parser("artifact-completeness",
                           help="Assesses whether a named artifact category (per project's own "
                                "declared sub-fact inventory) is structurally complete. See "
                                "dv_harness/artifact_completeness.py.")
    pafcm.add_argument("category", help="Artifact category name (see the module for the known "
                                         "set).")
    pafcm.add_argument("subfact_inventory", nargs="?", default=None,
                       help="Optional JSON file: the category's own sub-fact inventory.")

    pard = sub.add_parser("artifact-relationship-discovery",
                          help="Discovers real DUPLICATE/SUPERSEDES/CONTRADICTS/RELATED "
                               "relationships across a design_source_inventory registry (or a "
                               "bare list of registry rows). See "
                               "dv_harness/artifact_relationship_discovery.py.")
    pard.add_argument("--sources", required=True,
                      help="Path to a JSON file: a design_source_inventory "
                           "build_source_registry() result, or a bare list of registry rows.")
    pard.add_argument("--json", action="store_true", help="Print JSON instead of markdown.")

    pbpm = sub.add_parser("backpressure-model",
                          help="Classifies legal-backpressure-tolerance (BOUNDED/UNBOUNDED/"
                               "NOT_AVAILABLE, plus a declared max-stall-cycles figure where "
                               "BOUNDED) on named AMBA channels strictly from supplied per-"
                               "channel RTL/spec evidence text. See "
                               "dv_harness/backpressure_model.py.")
    pbpm.add_argument("--evidence-file", default=None,
                      help="JSON file: {\"<channel>\": \"<evidence text>\", ...}.")
    pbpm.add_argument("--observed-stalls-file", default=None,
                      help="JSON file: {\"<channel>\": <observed max stall cycles>, ...} for an "
                           "optional per-channel stall-violation check.")
    pbpm.add_argument("--json", action="store_true", help="Emit the machine-readable model.")

    pbsh = sub.add_parser("bounded-self-healing",
                          help="Classifies a failure's self-healing eligibility and evaluates "
                               "whether a bounded self-heal action is authorized for a stage "
                               "(requires a real recorded human approval under the module's "
                               "own HUMAN_APPROVAL_STAGE). See dv_harness/bounded_self_healing.py.")
    pbsh.add_argument("bsh_verb", choices=("eligible-types", "classify", "evaluate", "ledger"))
    pbsh.add_argument("--text", default="",
                      help="classify/evaluate: the failing attempt's blocking_reason / log "
                           "excerpt.")
    pbsh.add_argument("--stage", default="", help="evaluate: the graph stage name.")

    pbor = sub.add_parser("branch-ownership-resolver",
                          help="Classifies a proposed operation's ownership tier "
                               "(GLOBAL/DUT/FW/VIP/AMBIGUOUS/UNKNOWN) and validates an existing "
                               "block/branch_a*/branch_fw/branch_b* assignment against it. See "
                               "dv_harness/branch_ownership_resolver.py.")
    pbor.add_argument("bor_verb", choices=("classify", "validate"))
    pbor.add_argument("--payload", required=True,
                      help="JSON file carrying operation_kind, optional per_port/driven_by/"
                           "arbitration_policy, and (for 'validate') branch_label.")

    pcc = sub.add_parser("change-cascade",
                         help="Given a changed upstream field name, reports which of this "
                              "harness's own already-computed downstream artifacts are now "
                              "suspect and why; on request, revokes a named stale question-"
                              "queue decision through the real question_queue.revoke_decision(). "
                              "See dv_harness/change_cascade.py.")
    pcc.add_argument("cc_verb", choices=("fields", "assess", "revoke"))
    pcc.add_argument("--changed-field", default=None,
                     help="assess/revoke: one changed field name (see `fields` for the list).")
    pcc.add_argument("--changes-file", default=None,
                     help="assess: a JSON file holding a field name, a list of field names, or "
                          "a list of {'field': ...} records to assess together.")
    pcc.add_argument("--question-key", action="append", default=None, dest="question_keys",
                     help="revoke: a question_key to revoke (repeatable).")
    pcc.add_argument("--revoked-by", default=None, help="revoke: who is revoking this decision.")
    pcc.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pcsq = sub.add_parser("checker-sb-qualification",
                          help="Folds a set of real, cited defect-detection/false-PASS trials "
                               "into a worst-wins qualification verdict per named checker/"
                               "scoreboard component, and an overall gate across all of them. "
                               "See dv_harness/checker_sb_qualification.py.")
    pcsq.add_argument("csq_verb", choices=("evaluate",))
    pcsq.add_argument("--trials", dest="csq_trials_path", default=None,
                      help="JSON file: a bare list of trial records, or {'trials': [...]}.")
    pcsq.add_argument("--required", action="append", default=None,
                      help="A required 'component_id:component_kind' pair (repeatable).")
    pcsq.add_argument("--json", action="store_true", dest="csq_as_json",
                      help="Emit the machine-readable gate report.")

    pcci = sub.add_parser("coherency-capability-ir",
                          help="Classifies ACE-style behavioral coherency capability (snoop-"
                               "type support, coherency-domain membership, barrier-transaction "
                               "support, dirty/clean tracking) strictly from supplied caller "
                               "evidence -- ACE support is never assumed from an AXI base "
                               "protocol. See dv_harness/coherency_capability_ir.py.")
    pcci.add_argument("--evidence", required=True,
                      help="Path to a JSON evidence document: "
                           "{\"protocol\"?, \"dut_name\"?, \"ir_id\"?, \"axes\": {...}}.")
    pcci.add_argument("--json", action="store_true", help="Emit the IR as JSON.")

    pcpg = sub.add_parser("command-precondition-gate",
                          help="Validates a command's declared preconditions against "
                               "runtime_event_registry's current propagated event state before "
                               "dispatch. Reports only. See dv_harness/command_precondition_gate.py.")
    pcpg.add_argument("cpg_verb", choices=("list", "check"))
    pcpg.add_argument("--commands", required=True,
                      help="Declared command/precondition JSON file.")
    pcpg.add_argument("--registry", default=None,
                      help="check: runtime event registry JSON file.")
    pcpg.add_argument("--out", default=None,
                      help="check: also write the dispatch report JSON here.")
    pcpg.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pctt = sub.add_parser("command-task-trace",
                          help="Traces a DE command name through task/macro -> UVM bridge -> "
                               "VIP API -> checker via real grep-based cross-reference over a "
                               "generated environment's own files. "
                               "See dv_harness/command_task_trace.py.")
    pctt.add_argument("--env-dir", required=True, help="generated environment directory")
    pctt.add_argument("--command", action="append", dest="ctt_commands", required=True,
                      help="DE command name to trace; may be repeated")
    pctt.add_argument("--vip-prefix", action="append", dest="ctt_vip_prefixes", default=None,
                      help="identifier prefix marking a VIP API reference (e.g. svt_); may be "
                           "repeated")
    pctt.add_argument("--no-verible", action="store_true",
                      help="skip the optional verible task-signature enrichment")
    pctt.add_argument("--verible-bin", default=None)
    pctt.add_argument("--json", action="store_true")

    pctci = sub.add_parser("command-txt-change-impact",
                           help="Semantic diff between two DECommandRegistryIR-shaped DE command "
                                "registry snapshots. See dv_harness/command_txt_change_impact.py.")
    pctci.add_argument("--old", required=True, help="Path to the OLD (before) snapshot JSON file.")
    pctci.add_argument("--new", required=True, help="Path to the NEW (after) snapshot JSON file.")
    pctci.add_argument("--json", action="store_true", help="Emit the machine-readable report.")

    pconfcal = sub.add_parser("confidence-calibration",
                              help="Does a confidence tier's real track record in this project's "
                                   "Memory records match the ordering this harness acts on? "
                                   "See dv_harness/confidence_calibration.py.")
    pconfcal.add_argument("cal_verb", choices=("tiers", "report", "show"))
    pconfcal.add_argument("--json", action="store_true")

    pconn = sub.add_parser("connectivity-check",
                           help="Standing connectivity check: re-runs connectivity.py's 3 machine "
                                "gates (elaboration / static zero-time connectivity / transaction "
                                "activity) and records the RTL fingerprint they were produced "
                                "against. See dv_harness/connectivity_check.py.")
    pconn.add_argument("--config", default=None,
                       help="Config JSON (default: <project-root>/.dv-harness/"
                            "connectivity_check.json)")
    pconn.add_argument("--state", default=None, help="State JSON path override.")
    pconn.add_argument("--report", default=None, help="Markdown report path override.")
    pconn.add_argument("--check-only", action="store_true",
                       help="Do not run the gates; only compare the current RTL fingerprint "
                            "against the last recorded gate run.")

    pckb = sub.add_parser("consolidated-kpi-benchmark",
                          help="Consolidated cross-cutting KPI/benchmark report -- self-resolve "
                               "rate, repeated-question count, time-to-first-PASS, false-PASS/"
                               "false-READY count, and honest NOT_MEASURED disclosures. "
                               "See dv_harness/consolidated_kpi_benchmark.py.")
    pckb.add_argument("ckb_verb", choices=("names", "report", "show"))
    pckb.add_argument("--json", action="store_true")

    pcb = sub.add_parser("context-budget",
                         help="3-tier context budget: classify a path/command, emit the "
                              "PreToolUse deny for a tier-1 read, or build the tier-2 resident "
                              "pack. See dv_harness/context_budget.py.")
    pcb_sub = pcb.add_subparsers(dest="cb_verb", required=True)
    pcb_sub.add_parser("hook", help="Read a PreToolUse payload on stdin; print a deny JSON.")
    pcb_sub.add_parser("session-start", help="Print the SessionStart hook JSON.")
    _pcb_cl = pcb_sub.add_parser("classify", help="Classify one path (or --command) into a tier.")
    _pcb_cl.add_argument("target", nargs="?", default="")
    _pcb_cl.add_argument("--command", default=None, help="Classify a shell command string instead.")
    _pcb_res = pcb_sub.add_parser("resident", help="Report tier-2 artifact residency.")
    _pcb_res.add_argument("--json", action="store_true")

    pccau = sub.add_parser("coverage-closure-action-utility",
                           help="Ranks candidate coverage-closure actions by utility = "
                                "expected_coverage_gain x requirement_priority x risk_coverage / "
                                "cost; excludes FLAGGED_INCORRECT/HIGH_RISK actions before cost "
                                "is ever considered. "
                                "See dv_harness/coverage_closure_action_utility.py.")
    pccau.add_argument("--candidates-file", required=True,
                       help="JSON file holding a list of candidate-action objects.")
    pccau.add_argument("--json", action="store_true")

    pcchc = sub.add_parser("coverage-closure-hole-correlation",
                           help="Correlates coverage holes by real declared shared evidence and "
                                "annotates the coverage_closure_action_utility ranking with which "
                                "already-cleared actions would close a correlated multi-hole "
                                "bundle. See dv_harness/coverage_closure_hole_correlation.py.")
    pcchc.add_argument("--holes-file", required=True,
                       help="JSON file holding a list of coverage-hole records.")
    pcchc.add_argument("--candidates-file", dest="cchc_candidates_file", required=True,
                       help="JSON file holding a list of candidate coverage-closure actions.")
    pcchc.add_argument("--closes-holes-field", default=None)
    pcchc.add_argument("--parsed-summary-file", default=None)
    pcchc.add_argument("--json", action="store_true")

    pcdi = sub.add_parser("coverage-db-integrity",
                          help="Coverage-DB merge integrity: real content fingerprint of a "
                               "coverage database, and per-entry fingerprint/tool-config "
                               "compatibility checking before a merge. "
                               "See dv_harness/coverage_db_integrity.py.")
    pcdi_sub = pcdi.add_subparsers(dest="cdi_verb", required=True)
    _pcdi_fp = pcdi_sub.add_parser("fingerprint",
                                   help="Compute one coverage DB's content fingerprint.")
    _pcdi_fp.add_argument("--db-path", required=True)
    _pcdi_chk = pcdi_sub.add_parser("check", help="Verify a merge request.")
    _pcdi_chk.add_argument("--merge-request", required=True)

    pdcrr = sub.add_parser("de-command-runtime-readiness-gate",
                           help="Composite DE_COMMAND_RUNTIME_READY verdict: aggregates "
                                "runtime_event_registry state, command_precondition_gate "
                                "results, and a caller-supplied branch/grammar-side result set. "
                                "See dv_harness/de_command_runtime_readiness_gate.py.")
    pdcrr.add_argument("dcrr_verb", choices=("check",))
    pdcrr.add_argument("--registry", dest="dcrr_registry", required=True,
                       help="Runtime event registry JSON file.")
    pdcrr.add_argument("--commands", dest="dcrr_commands", default=None,
                       help="Declared command/precondition JSON file.")
    pdcrr.add_argument("--branch-grammar", default=None,
                       help="Duck-typed branch/grammar-side result set JSON file.")
    pdcrr.add_argument("--out", dest="dcrr_out", default=None)
    pdcrr.add_argument("--json", action="store_true")

    pdq = sub.add_parser("dependency-qualification",
                         help="The QUALIFICATION record for a dependency/VIP/third-party "
                              "component: has it been vetted, by whom, against what criteria -- "
                              "distinct from dependency_supply_chain.py's inventory/pinning/"
                              "advisory checks. See dv_harness/dependency_qualification.py.")
    pdq.add_argument("dq_verb", choices=("statuses", "list", "coverage", "record", "revoke"))
    pdq.add_argument("--inventory", default=None,
                     help="Path to a dependency_supply_chain build_inventory() JSON dump "
                          "(required for `coverage`).")
    pdq.add_argument("--record-file", default=None, help="Required for `record`.")
    pdq.add_argument("--qualification-id", default=None, help="Required for `revoke`.")
    pdq.add_argument("--revoked-by", default=None, help="Required for `revoke`.")
    pdq.add_argument("--reason", default=None, help="Required for `revoke`.")
    pdq.add_argument("--json", action="store_true")

    pdai = sub.add_parser("design-architecture-ir",
                          help="Wraps verible_parser.py's per-file RTL facts into a full "
                               "multi-file ArchitectureIR: a complete recursive instance tree "
                               "plus a best-effort FSM-candidate literal scan. "
                               "See dv_harness/design_architecture_ir.py.")
    pdai.add_argument("--rtl", action="append", required=True, dest="dai_rtl_files",
                      help="An RTL file to include in this build (repeatable).")
    pdai.add_argument("--top-module", default=None)
    pdai.add_argument("--verible-bin", default=None)
    pdai.add_argument("--out", default=None, help="Also write the full JSON IR to this path.")
    pdai.add_argument("--json", action="store_true")

    pdkc = sub.add_parser("design-knowledge-correlation",
                          help="General cross-source correlation engine over IR-shaped design "
                               "knowledge facts: real CONFLICT/GAP/DOCUMENTED_VS_IMPLEMENTED "
                               "findings plus a Design Knowledge Graph. Never arbitrates a "
                               "conflict. See dv_harness/design_knowledge_correlation.py.")
    pdkc.add_argument("--sources", required=True, help="JSON file: a list of source dicts.")
    pdkc.add_argument("--expected-facts", default=None,
                      help="JSON file: a list of {fact_key, reason?, required_by?}.")
    pdkc.add_argument("--json", action="store_true")

    pdtt = sub.add_parser("digital-thread", help="Assemble the digital-thread traceability "
                                                   "report (requirement -> vPlan -> command -> "
                                                   "test -> evidence), read-only, joining "
                                                   "env.manifest.json and evidence.duckdb facts. "
                                                   "See dv_harness/digital_thread_traceability.py.")
    pdtt.add_argument("--vplan-file", default=None,
                      help="JSON file: a list of vplan_artifact-shaped rows.")
    pdtt.add_argument("--env-manifest", default=None, help="Explicit env.manifest.json path.")
    pdtt.add_argument("--db-path", default=None, help="Explicit evidence.duckdb path.")
    pdtt.add_argument("--json", action="store_true")

    pdcc = sub.add_parser("doc-citation-check", help="Check every citation of a real source "
                                                       "artifact inside a doc against that "
                                                       "artifact's current real content -- drift, "
                                                       "missing source, out-of-range, unverifiable. "
                                                       "See dv_harness/doc_citation_check.py.")
    pdcc.add_argument("docs", nargs="*",
                      help="Doc paths (repo-relative or absolute) to check. Omitted (with no "
                           "--memory-docs) checks this project's own memory docs by default, "
                           "exactly like the standalone `python -m` front door.")
    pdcc.add_argument("--memory-docs", action="store_true",
                      help="Explicitly check this project's own memory docs, in addition to any "
                           "docs named positionally.")

    pdec = sub.add_parser("dut-evidence-correlation", help="Correlate a caller-declared "
                                                             "requirement fact (an interrupt, a "
                                                             "clock/reset signal, a mode, ...) "
                                                             "against env.manifest.json's real "
                                                             "assembled RTL/register/clock-reset/"
                                                             "address-map facts. "
                                                             "See dv_harness/dut_evidence_correlation.py.")
    pdec.add_argument("--manifest", required=True, help="Path to env.manifest.json.")
    pdec.add_argument("--items", required=True,
                      help="JSON file: a list of declared-fact items.")
    pdec.add_argument("--json", action="store_true")

    pdci = sub.add_parser("dynamic-connectivity", help="Classify a fabric path's routing/decode "
                                                         "as RECONFIGURABLE_CONFIRMED / "
                                                         "STATIC_CONFIRMED / UNKNOWN / AMBIGUOUS "
                                                         "from real, cited caller evidence only "
                                                         "-- never from the protocol/fabric name. "
                                                         "See dv_harness/dynamic_connectivity_ir.py.")
    pdci_sub = pdci.add_subparsers(dest="dci_verb", required=True)
    pdci_sub.add_parser("statuses", help="List the reconfigurability-status vocabulary.")
    pdci_classify = pdci_sub.add_parser("classify",
                                        help="Classify every declared path in a JSON path-spec "
                                             "file.")
    pdci_classify.add_argument("--paths", required=True,
                               help="JSON file of {\"paths\": [...]}, or a bare list.")
    pdci_classify.add_argument("--json", action="store_true")

    pdig = sub.add_parser("dynamic-intake-graph", help="Build a queryable graph view over an "
                                                         "already-assembled IntakeState -- field "
                                                         "nodes, category groupings, and "
                                                         "caller-declared artifact-relationship "
                                                         "edges. A view, never a gate. "
                                                         "See dv_harness/dynamic_intake_graph.py.")
    pdig.add_argument("--intake-state", required=True,
                      help="Path to an IntakeState.to_dict()-shaped JSON file.")
    pdig.add_argument("--relationships", default=None,
                      help="Path to a caller-supplied artifact-relationship-edges JSON file.")
    pdig.add_argument("--json", action="store_true", help="Emit the full graph as JSON.")

    pexc = sub.add_parser("example-composition", help="Composability gate over several "
                                                        "individually-qualified VIP examples "
                                                        "about to be combined into one scenario: "
                                                        "7 real structural conditions, never a "
                                                        "semantic judgement. "
                                                        "See dv_harness/example_composition.py.")
    pexc.add_argument("verb", choices=("compose",))
    pexc.add_argument("--examples", required=True, help="JSON file: a list of example dicts.")
    pexc.add_argument("--json", action="store_true")

    pecr = sub.add_parser("existing-command-reuse", help="Rank existing DE command.txt commands "
                                                           "against a new vPlan-driven need: "
                                                           "semantic-name match, argument-shape "
                                                           "compatibility, branch-ownership "
                                                           "compatibility, real evidence_db "
                                                           "regression history. Never forces a "
                                                           "low-confidence pick. "
                                                           "See dv_harness/existing_command_reuse_score.py.")
    pecr.add_argument("--need-file", required=True, help="JSON file: the need dict.")
    pecr.add_argument("--commands-file", required=True,
                      help="JSON file: a list of existing-command dicts.")
    pecr.add_argument("--db", default=None, help="Evidence database path override.")
    pecr.add_argument("--json", action="store_true")

    pfpi = sub.add_parser("fabric-progress", help="Deadlock/livelock risk over a caller-declared "
                                                    "resource-dependency wait graph, plus real "
                                                    "credit/outstanding-transaction exhaustion "
                                                    "arithmetic. Never claims deadlock-freedom "
                                                    "from an incomplete graph. "
                                                    "See dv_harness/fabric_progress_ir.py.")
    pfpi.add_argument("--resource-dependency", default=None,
                      help="JSON file: a list of {resource, held_by, waiting_for} facts.")
    pfpi.add_argument("--credit-outstanding", default=None,
                      help="JSON file: a list of credit/outstanding-transaction facts.")
    pfpi.add_argument("--json", action="store_true")

    pfcr = sub.add_parser("file-candidate-rank", help="Evidence-only ranking of an ambiguous "
                                                        "file choice: real git-log reference "
                                                        "count/recency, real build-script "
                                                        "reference count, real file mtime. Never "
                                                        "picks a winner. "
                                                        "See dv_harness/file_candidate_ranker.py.")
    pfcr.add_argument("verb", choices=("rank",))
    pfcr.add_argument("candidates", nargs="+", help="Candidate file paths.")
    pfcr.add_argument("--repo-root", default=None, help="Git repository root.")
    pfcr.add_argument("--fcr-project-root", dest="fcr_project_root", default=None,
                      help="Project root to scan for build scripts/Makefiles "
                           "(default: this project's own root).")

    pfcs = sub.add_parser("functional-coverage-signoff", help="FUNCTIONAL_COVERAGE_SIGNOFF_READY "
                                                                "verdict + Closure metric, "
                                                                "aggregated read-only from "
                                                                "waiver_store, coverage_analysis "
                                                                "and env_manifest/evidence_db. "
                                                                "See dv_harness/functional_coverage_signoff.py.")
    pfcs.add_argument("--json", action="store_true")

    pgcq = sub.add_parser("gen-code-quality-gate", help="Composite PASS/FAIL/INCOMPLETE_EVIDENCE "
                                                          "quality gate over generated UVM/SV "
                                                          "code: folds uvm_structural_lint.py's "
                                                          "real findings and vip_api_card.py's "
                                                          "real BLOCKED-citation findings "
                                                          "worst-wins. "
                                                          "See dv_harness/gen_code_quality_gate.py.")
    pgcq.add_argument("--env-dir", default=None,
                      help="Generated UVM environment directory to lint.")
    pgcq.add_argument("--verible-bin", default=None)
    pgcq.add_argument("--vip-source", action="append", default=None, dest="gcq_vip_sources",
                      help="Generated .sv/.svh file or directory to VIP-API-validate "
                           "(repeatable; requires --vip-index).")
    pgcq.add_argument("--vip-index", default=None, help="vip_symbol_index JSON document.")
    pgcq.add_argument("--relative-to", default=None,
                      help="Root for reported VIP-API usage paths (default: --env-dir).")
    pgcq.add_argument("--json", action="store_true")

    pgsb = sub.add_parser("golden-subsystem-benchmark", help="Golden Subsystem Benchmark / KPI / "
                                                               "Critical False-Architecture-Claim "
                                                               "Metrics: a versioned corpus of "
                                                               "hand-curated ground-truth "
                                                               "architecture claims, graded "
                                                               "against verification_architecture.py "
                                                               "and design_architecture_ir.py's own "
                                                               "output, with a worst-wins "
                                                               "false-positive-architecture-claim "
                                                               "KPI. "
                                                               "See dv_harness/golden_subsystem_benchmark.py.")
    pgsb.add_argument("gsb_verb", choices=("register", "list", "verify", "diff",
                                            "record-tuning-use", "leakage", "eval", "runs"))
    pgsb.add_argument("--dataset-id", default=None)
    pgsb.add_argument("--json-file", default=None, help="register: the dataset version JSON file.")
    pgsb.add_argument("--version", type=int, default=None,
                      help="Operate on this dataset version (default: the latest).")
    pgsb.add_argument("--old-version", type=int, default=None, help="diff: the earlier version.")
    pgsb.add_argument("--new-version", type=int, default=None, help="diff: the later version.")
    pgsb.add_argument("--case-id", default=None)
    pgsb.add_argument("--subject-id", default=None,
                      help="The extractor/agent version being graded.")
    pgsb.add_argument("--subject-version", default=None)
    pgsb.add_argument("--subject-kind", default=None)
    pgsb.add_argument("--used-for", default=None,
                      help="record-tuning-use: what the case was used to tune.")
    pgsb.add_argument("--extracted-docs-file", default=None,
                      help="eval: JSON file mapping case_id -> the real extracted doc for that "
                           "case.")
    pgsb.add_argument("--json", action="store_true")

    pgal = sub.add_parser("gui-audit-log", help="Structured 7-field GUI action audit records "
                                                  "(who/when/before/after/evidence/approval/result) "
                                                  "for every dashboard-issued /api/control command -- "
                                                  "the same events.jsonl entries `dv-harness audit` "
                                                  "already reads, filtered to the structured subset "
                                                  "gui_audit_log.py's wrap_dispatch() writes. "
                                                  "See dv_harness/gui_audit_log.py.")
    pgal.add_argument("gal_verb", choices=("show",))
    pgal.add_argument("--limit", type=int, default=50)
    pgal.add_argument("--action", default=None,
                       help="Narrow to one dashboard command, e.g. APPROVE.")
    pgal.add_argument("--json", action="store_true")

    pgiw = sub.add_parser("gui-intake-wizard", help="GUI-01 Interactive Intake Wizard: start the "
                                                      "real, standalone HTTP server (GET current "
                                                      "step, POST answer, POST advance), grounded "
                                                      "entirely in intake_state.py's real per-field "
                                                      "IntakeFieldRecord data. Blocks until "
                                                      "interrupted. "
                                                      "See dv_harness/gui_intake_wizard.py.")
    pgiw.add_argument("--host", default="127.0.0.1")
    pgiw.add_argument("--port", type=int, default=8799)

    pgcp = sub.add_parser("gui-intake-control-plane", help="GUI Intake Control Plane: a real "
                                                              "backend over question_queue.py + "
                                                              "intake_state.py (pending questions, "
                                                              "per-field intake statuses, answer/ "
                                                              "approve from the UI). 'serve' starts "
                                                              "its own standalone, session-token-"
                                                              "gated HTTP server and blocks until "
                                                              "interrupted; 'snapshot' prints the "
                                                              "real control-plane state as JSON. "
                                                              "See dv_harness/gui_intake_control_plane.py.")
    pgcp.add_argument("gicp_verb", choices=("serve", "snapshot"))
    pgcp.add_argument("--host", default="127.0.0.1")
    pgcp.add_argument("--port", type=int, default=0)
    pgcp.add_argument("--no-auth", action="store_true",
                       help="serve: disable the session-token gate (local debugging only).")

    phcl = sub.add_parser("human-correction-lesson", help="Capture a structured human correction "
                                                            "(a false claim -> the human's real "
                                                            "correcting evidence) as a debug_lesson "
                                                            "Engineering Memory record, and ask "
                                                            "whether this exact mistake has been "
                                                            "corrected before. "
                                                            "See dv_harness/human_correction_lesson.py.")
    phcl_sub = phcl.add_subparsers(dest="hcl_verb", required=True)
    phcl_record = phcl_sub.add_parser("record",
                                      help="Capture one structured human correction as a "
                                           "debug_lesson.")
    phcl_record.add_argument("--before-claim", required=True)
    phcl_record.add_argument("--after-claim", required=True)
    phcl_record.add_argument("--correction-evidence", required=True)
    phcl_record.add_argument("--corrected-by", required=True)
    phcl_record.add_argument("--mistake-category", required=True)
    phcl_record.add_argument("--before-reasoning", default=None)
    phcl_record.add_argument("--protocol", default=None)
    phcl_record.add_argument("--scope", default=None)
    phcl_record.add_argument("--title", default=None)
    phcl_record.add_argument("--confidence", default=None)
    phcl_query = phcl_sub.add_parser("query",
                                     help="Ask whether a human has corrected this exact mistake "
                                          "before.")
    phcl_query.add_argument("--before-claim", required=True)
    phcl_query.add_argument("--mistake-category", default=None)
    phcl.add_argument("--json", action="store_true")

    pivb = sub.add_parser("iface-contract-vip-bind", help="Spec section 219: validate that a "
                                                            "declared interface contract (signal "
                                                            "list, protocol, direction) matches "
                                                            "what a real, already-existing VIP "
                                                            "bind actually connects to. "
                                                            "See dv_harness/iface_contract_vip_bind_validator.py.")
    pivb.add_argument("--contracts", required=True,
                      help="JSON file: a list of declared-interface-contract records, or "
                           "{\"interfaces\": [...]}.")
    pivb.add_argument("--bind-root", default=None,
                      help="Root directory to grep for real 'bind ...' statements.")
    pivb.add_argument("--modules", default=None,
                      help="JSON file of already-parsed RTL modules.")
    pivb.add_argument("--json", action="store_true")
    pivb.add_argument("--strict-unprovable", action="store_true",
                      help="Exit non-zero on UNPROVABLE cards too, not just BLOCKED ones.")

    pib = sub.add_parser("intake-baseline",
                         help="Freeze/evaluate the twelve pre-generation intake facts "
                              "(DUT top/boundary, DUT/TB SHA, source file hashes, VIP "
                              "declaration, bind topology hash, reference-UVM hash, DE "
                              "command.txt hash, known-test list, unresolved-unknowns/"
                              "conflicts/decisions counts). "
                              "See dv_harness/intake_baseline.py.")
    pib.add_argument("ib_verb", choices=["fields", "baseline", "freeze", "list", "status"])
    pib.add_argument("--root", default=None, help="Defaults to the project root.")
    pib.add_argument("--facts", default=None,
                     help="JSON object of intake facts, keyed by the field names the "
                          "'fields' verb prints.")
    pib.add_argument("--freeze-id", default=None)
    pib.add_argument("--frozen-by", default=None)
    pib.add_argument("--note", default="")
    pib.add_argument("--json", action="store_true")

    pics = sub.add_parser("intake-contract-stale",
                          help="Section 18: is a VerificationIntakeContract's BASELINED "
                               "evidence still fresh, real detection over a real git diff "
                               "and a real declared staleness window. "
                               "See dv_harness/intake_contract_stale_detection.py.")
    pics.add_argument("ics_verb", choices=["window", "detect"])
    pics.add_argument("--contract", default=None,
                      help="For 'detect': a VerificationIntakeContract.to_dict() JSON file.")
    pics.add_argument("--recorded-sha", default=None)
    pics.add_argument("--window-seconds", type=float, default=None)

    pie = sub.add_parser("intake-events",
                         help="The fixed 18-event INTAKE_* taxonomy over "
                              ".dv-harness/events.jsonl -- section 34. "
                              "See dv_harness/intake_events.py.")
    pie.add_argument("ie_verb", choices=["names", "events"])
    pie.add_argument("--json", action="store_true")

    pim = sub.add_parser("intake-modes",
                         help="Intake rigor MODE (FAST/STANDARD/STRICT/SIGNOFF): which "
                              "intake_state.py fields/categories are mandatory for each "
                              "mode. See dv_harness/intake_modes.py.")
    pim.add_argument("im_verb", choices=["modes", "conditions", "evaluate"])
    pim.add_argument("--mode", default=None, help="FAST|STANDARD|STRICT|SIGNOFF.")
    pim.add_argument("--intake-state", default=None,
                     help="For 'evaluate': an IntakeState.to_dict()-shaped JSON document.")
    pim.add_argument("--json", action="store_true")

    piqp = sub.add_parser("intake-question-priority",
                          help="Confidence x Criticality ask-gating, next-best-question "
                               "ranking, and LOW-risk batching over a generic list of "
                               "pending-question dicts. "
                               "See dv_harness/intake_question_priority.py.")
    piqp.add_argument("--pending-questions", required=True,
                      help="Path to a JSON array of pending-question dicts.")
    piqp.add_argument("--max-batch-size", type=int, default=None)
    piqp.add_argument("--json", action="store_true")

    pisp = sub.add_parser("intake-source-priority",
                          help="The 10-step DISCOVERY ladder for a fact not yet known -- "
                               "distinct from source_authority.py's 9-level CONFLICT "
                               "order. See dv_harness/intake_source_priority.py.")
    pisp.add_argument("isp_verb", choices=["order", "next", "self-check"])
    pisp.add_argument("--fact", default=None)
    pisp.add_argument("--available", default=None,
                      help="Comma-separated source ids/aliases actually available.")
    pisp.add_argument("--json", action="store_true")

    piag = sub.add_parser("integration-adapter-gen",
                          help="Generate adapter glue code (a `define macro-redirect .svh "
                               "file) from an already-resolved SubsystemAdapterIR mapping. "
                               "See dv_harness/integration_adapter_gen.py.")
    piag.add_argument("mapping_file",
                      help="JSON file: a list of {operation, "
                           "existing_task_or_sequence_name} mapping entries, or an object "
                           "carrying 'mapping_entries' and optionally 'subsystem_name'.")
    piag.add_argument("--subsystem-name", default=None)
    piag.add_argument("--out", default=None, help="Write the generated .svh to this path.")

    pidce = sub.add_parser("interrupt-dma-clock-reset",
                           help="Extract interrupt architecture, DMA architecture, and a "
                                "clock/reset fact extension from real supplied spec/RTL "
                                "text -- never inferred. "
                                "See dv_harness/interrupt_dma_clock_reset_extraction.py.")
    pidce.add_argument("--sources", nargs="+", required=True,
                       help="One or more real spec/programming-guide/RTL text files.")
    pidce.add_argument("--json", action="store_true")

    ptre = sub.add_parser("timing-requirements",
                          help="Extract DOCUMENTED setup/hold/latency timing requirements "
                               "(a stated bound with a comparison direction and unit) from "
                               "real spec/programming-guide/RTL-comment text -- never a "
                               "measured/simulated value, and never inferred. Section 289. "
                               "See dv_harness/timing_requirement_extraction.py.")
    ptre.add_argument("--sources", nargs="+", required=True,
                       help="One or more real spec/programming-guide/RTL text files.")
    ptre.add_argument("--json", action="store_true")

    pioc = sub.add_parser("ip-ownership-conflict",
                          help="IP-level (single-subsystem) check: is a real VIP agent AND "
                               "a legacy hand-written BFM/driver both declared ACTIVE on "
                               "the same interface/port? Detection only. "
                               "See dv_harness/ip_ownership_conflict.py.")
    pioc.add_argument("--env-manifest", required=True,
                      help="Path to this subsystem's env.manifest.json (or any JSON "
                           "carrying its vip_config layer).")
    pioc.add_argument("--legacy-bfm", default=None,
                      help="JSON array of caller-declared legacy BFM/driver records.")
    pioc.add_argument("--connectivity-rows", default=None,
                      help="JSON array of real connectivity-matrix rows for this SAME "
                           "subsystem.")
    pioc.add_argument("--json", action="store_true")

    plsd = sub.add_parser("loop-stale-detection",
                          help="Section 97: is a loop session's evidence still fresh, real "
                               "detection over a real elapsed-time window and a real git "
                               "diff. See dv_harness/loop_stale_detection.py.")
    plsd.add_argument("lsd_verb", choices=["window", "detect"])
    plsd.add_argument("--run-id", default=None)
    plsd.add_argument("--window-seconds", type=float, default=None)

    plt = sub.add_parser("loop-telemetry",
                         help="Section 107/108's Loop Engineering Center table over the "
                              "real section-108 loop telemetry events in "
                              ".dv-harness/events.jsonl. "
                              "See dv_harness/loop_telemetry.py.")
    plt.add_argument("lt_verb", choices=["names", "events", "rows", "show"])
    plt.add_argument("--run-id", default=None)
    plt.add_argument("--json", action="store_true")

    pmqp = sub.add_parser("memory-quality-policy",
                          help="Recommend (and optionally apply, via the real MemoryGC) "
                               "stale/deprecate actions over this project's own Memory "
                               "store. See dv_harness/memory_quality_policy.py.")
    pmqp.add_argument("mqp_verb", choices=["report", "apply"])
    pmqp.add_argument("--stale-after-days", type=int, default=None)
    pmqp.add_argument("--deprecate-after-days", type=int, default=None)
    pmqp.add_argument("--json", action="store_true")

    matr = sub.add_parser("model-agent-tool-router",
                          help="Model/Agent/Tool Router: task-type -> agent/model/tool "
                              "with a documented, data-driven fallback policy. "
                              "See dv_harness/model_agent_tool_router.py.")
    matr.add_argument("matr_verb", choices=["task-types", "criteria", "route"])
    matr.add_argument("--task-type", default=None)
    matr.add_argument("--unavailable-agents", default="")
    matr.add_argument("--unavailable-models", default="")
    matr.add_argument("--unavailable-tools", default="")
    matr.add_argument("--json", action="store_true")

    podg = sub.add_parser("ordering-domain-graph",
                          help="Build and report on an ordering-domain graph from a JSON "
                               "document carrying 'domains'/'memberships'/'edges' lists -- "
                               "every fact caller-declared and evidence-cited, never "
                               "inferred. See dv_harness/ordering_domain_graph.py.")
    podg.add_argument("--facts-file", required=True,
                      help="JSON file with {'domains': [...], 'memberships': [...], "
                           "'edges': [...]}.")
    podg.add_argument("--json", action="store_true")

    # ------------------------------------------------------------------
    # grpE wiring (2026-09-06): pure front-door wiring for 14 already-built,
    # already-tested real dv_harness modules. Each module already has its own
    # `python -m dv_harness.<module>` front door (execute_verb()/main()); the
    # blocks below add a matching dv-harness verb that imports the module and
    # calls that same real implementation. No new logic here.
    # ------------------------------------------------------------------

    povpe = sub.add_parser("org-verification-policy",
                           help="Org-declarable, EXECUTABLE verification-policy rules engine "
                                "(CLAUDE.md sections 135-137, vi_meta_governance/ovpe). A policy "
                                "is DATA (org_verification_policy.schema.json), never Python "
                                "code: a `condition` (three-valued True/False/UNRESOLVABLE over "
                                "project facts), an `action_if_matched` (BLOCK/WARN/ALLOW) for a "
                                "named `governs` topic, a scope and severity. See "
                                "dv_harness/org_verification_policy_engine.py.")
    povpe.add_argument("ovpe_verb", choices=("validate", "evaluate"))
    povpe.add_argument("--policies", required=True, help="Policy document JSON file.")
    povpe.add_argument("--facts", default=None, help="evaluate: facts JSON file to check the "
                                                       "policies against.")
    povpe.add_argument("--json", action="store_true")

    ppcc = sub.add_parser("pattern-coverage-contribution",
                          help="Per-pattern marginal functional-coverage contribution -- new "
                               "bins hit (and meaningful new cross-coverage bins) attributed to "
                               "ONE named pattern's own recorded evidence.duckdb checkpoints, "
                               "plus its real jobs runtime/failure evidence. Distinct from "
                               "loop_convergence.py's project-wide aggregate curve. See "
                               "dv_harness/pattern_coverage_contribution.py.")
    ppcc.add_argument("--db-path", required=True, help="evidence.duckdb path.")
    ppcc.add_argument("--pattern", required=True, help="Pattern/test name to attribute.")
    ppcc.add_argument("--attribution", required=True,
                      help="JSON file: list of {'source','pattern'} records mapping a "
                           "coverage_samples checkpoint's own 'source' to the pattern that "
                           "produced it.")
    ppcc.add_argument("--cross-definitions", default=None,
                      help="JSON file: list of {'cross_name','axes'} records.")
    ppcc.add_argument("--json", action="store_true")

    ppee = sub.add_parser("pattern-execution-evidence",
                          help="Per-DISPATCHED-TASK execution evidence inside one command.txt/"
                               "pattern run's block/branch_a*/branch_fw/branch_b* task-"
                               "composition layers, read from real @<time> lifecycle narration "
                               "in a sim.log (reusing sim_log_analysis.py's marker scan) -- "
                               "never a guessed timestamp. See "
                               "dv_harness/pattern_execution_evidence.py.")
    ppee.add_argument("log_path", help="Path to a sim.log.")
    ppee.add_argument("--command", default=None,
                      help="Real command.txt/pattern name this log belongs to.")
    ppee.add_argument("--json", action="store_true")

    pprs = sub.add_parser("pattern-runtime-state",
                          help="Per-PATTERN execution state machine: CREATED -> PARSED -> "
                               "VALIDATED -> READY -> RUNNING -> WAITING -> CHECKING -> "
                               "PASS/FAIL/TIMEOUT/BLOCKED/CANCELLED, with legal-transition "
                               "enforcement plus evidence-derived terminal-verdict observation "
                               "from a real sim.log. Deliberately a separate vocabulary from "
                               "loop_contract.LoopState, no bridge. See "
                               "dv_harness/pattern_runtime_state_machine.py.")
    pprs.add_argument("prs_verb", choices=("states", "show", "list", "observe"))
    pprs.add_argument("--pattern-id", default=None, help="show: which pattern's record to print.")
    pprs.add_argument("--log-file", default=None, help="observe: a real sim.log file to read.")
    pprs.add_argument("--json", action="store_true")

    ppsr = sub.add_parser("platform-startup-readiness",
                          help="STARTUP-TIME readiness check: is the harness itself correctly "
                               "configured, are its declared Python dependencies present, is "
                               "config.json valid -- before a single stage has ever run, "
                               "distinct from platform-health's ongoing operational aggregator "
                               "over recorded run history. See "
                               "dv_harness/platform_startup_readiness.py.")
    ppsr.add_argument("--json", action="store_true")

    psgd = sub.add_parser("spec-gap-detector",
                          help="Five structural-absence patterns over a requirement set "
                               "(normal-vs-error condition, enable-vs-disable, interrupt "
                               "assert-vs-clear, reset-vs-in-flight-operation, error-condition-"
                               "vs-recovery), each reported POTENTIAL_SPEC_GAP for a human to "
                               "review -- never auto-promoted to an approved requirement. See "
                               "dv_harness/potential_spec_gap_detector.py.")
    psgd.add_argument("requirements", help="JSON file: a list of requirement objects, or "
                                            "{\"requirements\": [...]}.")
    psgd.add_argument("--json", action="store_true")

    ppdr = sub.add_parser("prior-decision-reevaluation",
                          help="Flags a PRIOR capability-evolution decision (REJECTED/HOLD/"
                               "SUPERSEDED) for human RECONSIDERATION when new real repeated-"
                               "failure or cross-project evidence has accumulated against it "
                               "since the decision was made. Detection only -- never reverses a "
                               "decision or files a new candidate itself (Research-Capability "
                               "Evolution master prompt section 77). See "
                               "dv_harness/prior_decision_reevaluation.py.")
    ppdr.add_argument("pdr_verb", choices=("detect", "file"))
    ppdr.add_argument("--candidates", default=None,
                      help="JSON file of persisted CapabilityEvolutionCandidate records "
                           "(default: read from this project's own Blackboard/memory store).")
    ppdr.add_argument("--cross-project-patterns", default=None,
                      help="JSON file: the caller's own already-computed "
                           "cross_project_mining.mine_cross_project_patterns() "
                           "'cross_project_patterns' list.")
    ppdr.add_argument("--min-occurrences", type=int, default=None)
    ppdr.add_argument("--json", action="store_true")

    ppsir = sub.add_parser("programming-sequence-ir",
                           help="Canonical Programming Sequence IR (Init->Configure->Enable->"
                                "...->Reset) validator: phase-order monotonicity, register "
                                "access-type legality, and depends_on ordering against a "
                                "duck-typed register-facts list; or build/query a project-wide "
                                "register dependency graph. Reads only. See "
                                "dv_harness/programming_sequence_ir.py.")
    ppsir.add_argument("psir_verb", choices=("validate", "graph"))
    ppsir.add_argument("--sequence", default=None,
                       help="ProgrammingSequenceIR JSON document (required for 'validate').")
    ppsir.add_argument("--facts", default=None,
                       help="Register facts JSON: a list of {name, offset, access_type, "
                            "depends_on} dicts (required for 'graph'; optional for 'validate').")
    ppsir.add_argument("--catalog", default=None,
                       help="Illegal sequence catalog JSON (optional, 'validate' only).")
    ppsir.add_argument("--json", action="store_true")

    purc = sub.add_parser("usage-recipe-catalog",
                          help="Documented, purpose-cited step-by-step USAGE RECIPES assembled "
                               "over programming_sequence_ir.py's real per-sequence facts -- "
                               "named ordered step subsets ('here is how to bring the link up: "
                               "steps 0-3, per programming-guide section 4.2'), never a parallel "
                               "step-ordering validator: ordering validation delegates entirely "
                               "to programming_sequence_ir.validate_step_ordering(). Reads only. "
                               "See dv_harness/usage_recipe_catalog.py.")
    purc.add_argument("urc_verb", choices=("catalog", "validate"))
    purc.add_argument("--recipes", default=None, dest="recipes_json",
                      help="Usage recipe catalog JSON: a list of {recipe_id, purpose, citation, "
                           "steps, ...} dicts (required).")
    purc.add_argument("--facts", default=None, dest="facts_json",
                      help="Register facts JSON (as programming_sequence_ir.py's --facts). "
                           "Optional for 'validate'; omitting it reports NOT_AVAILABLE per recipe.")
    purc.add_argument("--catalog", default=None, dest="catalog_json",
                      help="Illegal sequence catalog JSON (as programming_sequence_ir.py's "
                           "--catalog). Optional, 'validate' only.")
    purc.add_argument("--recipe-id", default=None, dest="urc_recipe_id",
                      help="Validate only this one recipe (default: validate every recipe and "
                           "report the worst-wins rollup). 'validate' only.")
    purc.add_argument("--json", action="store_true")

    ppcap = sub.add_parser("protocol-capability",
                           help="What protocol-specific generation this harness can actually "
                                "DO, derived from the code that exists (GENERIC_SKELETON_ONLY / "
                                "PROTOCOL_MODEL_PARTIAL / PROTOCOL_MODEL_COMPLETE / DUT_PROVEN), "
                                "never from a label typed into a registry JSON file. "
                                "--check/--sync are mutually exclusive; with neither, prints "
                                "the capability rows. See dv_harness/protocol_capability.py.")
    _ppcap_g = ppcap.add_mutually_exclusive_group()
    _ppcap_g.add_argument("--check", action="store_true",
                          help="Exit 2 if the registry claims more than the code supports.")
    _ppcap_g.add_argument("--sync", action="store_true",
                          help="Rewrite the registry (and semantic-models) capability fields "
                               "from the code.")
    ppcap.add_argument("--capability-root", default=None,
                       help="Project root to check/sync/report over (default: this repo).")
    ppcap.add_argument("--json", action="store_true")

    ppco = sub.add_parser("protocol-compliance-oracle",
                          help="Checks whether a GENERATED sequence/pattern's own declared "
                               "STIMULUS (a list of transaction dicts) is itself protocol-legal, "
                               "BEFORE anything is simulated -- a static, evidence-grounded lint "
                               "reusing amba_transaction_ir.py's applicability facts and "
                               "amba_master_slave_constraint_ir.py's legal-value facts (spec "
                               "section 222). Distinct from protocol_compliance_aggregation.py, "
                               "which reads an ALREADY-COMPUTED scoreboard verdict from a real "
                               "simulation run. See dv_harness/protocol_compliance_oracle.py.")
    ppco.add_argument("--pattern", required=True,
                      help="JSON file: {protocol, transactions, concurrent_groups?, "
                           "data_width_bytes?}.")
    ppco.add_argument("--json", action="store_true")

    prca = sub.add_parser("rca-ontology",
                          help="Fixed root-cause CATEGORY ontology (DUT/testbench/VIP/stimulus/"
                               "checker/coverage-model/spec/toolchain/configuration/flaky/"
                               "accepted-limitation) for a CLOSED Engineering-Memory record, plus "
                               "failure-signature-based aggregation across records -- a coarser, "
                               "deliberately disjoint axis from command_error_taxonomy.py and "
                               "system_failure_taxonomy.py. See dv_harness/rca_ontology.py.")
    prca.add_argument("rca_verb", choices=("categories", "classify"))
    prca.add_argument("--records", default=None,
                      help="classify: JSON array of closed Engineering-Memory records.")
    prca.add_argument("--rca-root", default=None, help="classify: project root.")

    pree = sub.add_parser("register-excel-extract",
                          help="Turns a real register-map .xlsx/.csv spreadsheet into a "
                               "structured RegisterIR and, where the row's access type/width "
                               "are schema-legal, a register_map.schema.json-shaped document "
                               "env_manifest.py can load -- a real transcription, never a "
                               "guessed register. See dv_harness/register_excel_extract.py.")
    pree.add_argument("excel_path", help="Register-map .xlsx/.csv file.")
    pree.add_argument("--sheet", default=None, help="Sheet name (default: first sheet).")
    pree.add_argument("--block", default=None, help="Default block name for rows with none.")
    pree.add_argument("--base-address", default=None,
                      help="Hex (0x.../...h) or decimal block base address.")
    pree.add_argument("--json", action="store_true")

    prrt = sub.add_parser("register-rtl-trace",
                          help="Traces a register_map.schema.json field's declared name to a "
                               "real RTL signal/control-logic reference via the real verible "
                               "declaration-level parse (import only, no second SystemVerilog "
                               "parser) -- TRACE_CONFIRMED is its ceiling, never a claim of "
                               "verified elaboration-time behavior. See "
                               "dv_harness/register_rtl_trace.py.")
    prrt.add_argument("--register-map", required=True,
                      help="Path to a register_map.schema.json document.")
    prrt.add_argument("--rtl", action="append", required=True, dest="rrt_rtl_paths",
                      help="An RTL source file to parse (repeatable).")
    prrt.add_argument("--strict-partial", action="store_true",
                      help="Exit non-zero when any field's trace is TRACE_PARTIAL (ambiguous).")
    prrt.add_argument("--json", action="store_true")

    prri = sub.add_parser("requirement-risk-ir",
                          help="Six-factor requirement risk profile (complexity, "
                               "change_frequency, bug_history, customer_impact, "
                               "observability_difficulty, protocol_criticality). "
                               "change_frequency is MEASURED from real git history; the four "
                               "other declared factors come only from --facts-file; bug_history "
                               "is always NOT_AVAILABLE (no real producer in this repo). Reads "
                               "and reports only. See dv_harness/requirement_risk_ir.py.")
    prri.add_argument("--facts-file", default=None,
                      help="JSON file with requirement facts (requirement_id/id, complexity, "
                           "customer_impact, observability_difficulty, protocol_criticality, "
                           "and optional '<factor>_rationale' keys).")
    prri.add_argument("--source-file", default=None,
                      help="Path (relative to --project-root) whose git history measures "
                           "change_frequency.")
    prri.add_argument("--requirement-project-root", default=None,
                      help="Git repository root that --source-file is measured against "
                           "(default: this dv-harness project root).")
    prri.add_argument("--json", action="store_true")

    prqt = sub.add_parser("requirement-testability",
                          help="Spec section 218 requirement testability classification: "
                               "TESTABLE / UNTESTABLE_PROSE / INDETERMINATE over "
                               "requirement_contract.py-shaped records -- a requirement can "
                               "be schema-COMPLETE and still untestable prose. Reads and "
                               "reports only. See dv_harness/requirement_testability.py.")
    prqt.add_argument("--requirements", required=True,
                      help="JSON file with a top-level `requirements` list.")
    prqt.add_argument("--json", action="store_true")
    prqt.add_argument("--fail-on-indeterminate", action="store_true",
                      help="Also fail on INDETERMINATE findings, not only UNTESTABLE_PROSE.")

    preso = sub.add_parser("resource-orchestrator",
                           help="Global cross-job resource orchestration: ranking-rule / "
                                "contenders / capacity / plan over real preflight checks and "
                                "the cross-project registry. A grant is advisory only -- it "
                                "reserves nothing and authorizes no real submission. "
                                "See dv_harness/resource_orchestrator.py.")
    preso.add_argument("reso_verb", choices=["ranking-rule", "contenders", "capacity", "plan"])
    preso.add_argument("--requests", default="",
                       help="JSON list of resource requests; omit to build them from the "
                            "cross-project registry.")
    preso.add_argument("--queue", default="")

    prcc = sub.add_parser("runtime-control-commands",
                          help="Validate that every CONTROL-classified command.txt/pattern "
                               "command belongs to the closed vocabulary WAIT/POLL/REPEAT/"
                               "BOUNDED_LOOP/SYNC/BARRIER, and that REPEAT/BOUNDED_LOOP declare "
                               "a real iteration limit. Reads one file; verifies no behavior. "
                               "See dv_harness/runtime_control_commands.py.")
    prcc.add_argument("--command-file", required=True,
                      help="A command.txt/pattern file to parse and check.")
    prcc.add_argument("--json", action="store_true")

    prer = sub.add_parser("runtime-events",
                          help="Runtime event registry: event_name/producer/consumer/payload/"
                               "timeout/scope/status over a declared event set, with REQUIRES/"
                               "WAITS_FOR/TRIGGERS/UNBLOCKS dependency-graph stop-on-failure "
                               "propagation. Reports only. See dv_harness/runtime_event_registry.py.")
    prer.add_argument("re_verb", choices=("graph", "status"))
    prer.add_argument("--registry", required=True, help="Runtime event registry JSON file.")
    prer.add_argument("--out", default=None,
                      help="status: also write the propagation report JSON here.")
    prer.add_argument("--json", action="store_true")

    pswr = sub.add_parser("safe-write-rollback",
                          help="Safe Write / Rollback Contract: snapshot-before-write plus a "
                               "checkable, attributable undo record for any real production "
                               "write this harness performs. See dv_harness/safe_write_rollback.py.")
    pswr_sub = pswr.add_subparsers(dest="swr_verb", required=True)
    pswr_write = pswr_sub.add_parser("write", help="Snapshot and perform one write.")
    pswr_write.add_argument("--path", required=True, help="project-relative destination path")
    pswr_write.add_argument("--content-file", required=True,
                            help="local file whose bytes to write")
    pswr_write.add_argument("--actor", required=True)
    pswr_write.add_argument("--reason", required=True)
    pswr_write.add_argument("--write-id", default=None)
    pswr_plan = pswr_sub.add_parser("plan", help="Check whether a rollback is safe right now.")
    pswr_plan.add_argument("--write-id", required=True)
    pswr_apply = pswr_sub.add_parser("apply", help="Actually undo one write.")
    pswr_apply.add_argument("--write-id", required=True)
    pswr_apply.add_argument("--actor", required=True)
    pswr_apply.add_argument("--reason", required=True)
    pswr_bplan = pswr_sub.add_parser("batch-plan", help="Check a batched-write rollback plan.")
    pswr_bplan.add_argument("--batch-id", required=True)
    pswr_bapply = pswr_sub.add_parser("batch-apply", help="Undo a whole recorded batch.")
    pswr_bapply.add_argument("--batch-id", required=True)
    pswr_bapply.add_argument("--actor", required=True)
    pswr_bapply.add_argument("--reason", required=True)
    pswr_sub.add_parser("list", help="List every recorded write_id.")
    pswr_sub.add_parser("list-batches", help="List every recorded batch_id.")

    pssb = sub.add_parser("safety-sandbox",
                          help="Declare a sandbox scope, then check a proposed change (or "
                               "verify a real git diff) stays within it. "
                               "See dv_harness/safety_sandbox.py.")
    pssb_sub = pssb.add_subparsers(dest="ss_verb", required=True)
    pssb_declare = pssb_sub.add_parser("declare", help="Declare a sandbox over a path set.")
    pssb_declare.add_argument("--paths", nargs="*", default=[])
    pssb_declare.add_argument("--declared-by", required=True)
    pssb_declare.add_argument("--reason", required=True)
    pssb_declare.add_argument("--sandbox-id", default=None)
    pssb_check = pssb_sub.add_parser("check", help="Check a proposed path set against a sandbox.")
    pssb_check.add_argument("--sandbox-id", required=True)
    pssb_check.add_argument("--paths", nargs="+", required=True)
    pssb_verify = pssb_sub.add_parser("verify-diff",
                                      help="Verify a real git diff stays within a sandbox.")
    pssb_verify.add_argument("--sandbox-id", required=True)
    pssb_verify.add_argument("--base", required=True)
    pssb_verify.add_argument("--head", default="HEAD")
    pssb_status = pssb_sub.add_parser("status", help="Print one sandbox declaration.")
    pssb_status.add_argument("--sandbox-id", required=True)
    pssb_sub.add_parser("list", help="List every declared sandbox_id.")

    psps = sub.add_parser("scoreboard-placement-scope",
                          help="Classify a scoreboard's compare-operation placement scope "
                               "(PORT_LOCAL..END_TO_END, 8 values) strictly from caller-"
                               "declared facts, never from a naming heuristic. "
                               "See dv_harness/scoreboard_placement_scope.py.")
    psps_sub = psps.add_subparsers(dest="sps_verb", required=True)
    psps_sub.add_parser("scopes", help="List the 8 scope values and their definitions.")
    psps_classify = psps_sub.add_parser("classify",
                                        help="Classify a scoreboard's placement scope.")
    psps_classify.add_argument("--description", required=True,
                               help="Path to a JSON file of compare_description facts.")
    psps_classify.add_argument("--evidence", default=None,
                               help="Path to a JSON file of project_evidence facts.")
    psps_classify.add_argument("--json", action="store_true")

    pspi = sub.add_parser("security-policy-ir",
                          help="Classify a proposed AMBA access (master/region/secure/"
                               "privileged) against a declared, cited security access matrix. "
                               "Never infers a decision from a name. "
                               "See dv_harness/security_policy_ir.py.")
    pspi_sub = pspi.add_subparsers(dest="spi_verb", required=True)
    pspi_sub.add_parser("statuses",
                        help="List the access-status and verification-status vocabularies.")
    pspi_classify = pspi_sub.add_parser("classify",
                                        help="Classify a proposed access against a declared policy.")
    pspi_classify.add_argument("--policy", required=True,
                               help="JSON file of {rules, default_decision, default_evidence}.")
    pspi_classify.add_argument("--master", required=True)
    pspi_classify.add_argument("--region", required=True)
    pspi_classify.add_argument("--secure", required=True, choices=["true", "false"])
    pspi_classify.add_argument("--privileged", required=True, choices=["true", "false"])
    pspi_classify.add_argument("--json", action="store_true")
    pspi_verify = pspi_sub.add_parser("verify-negative-test",
                                      help="Verify a denial was actually observed.")
    pspi_verify.add_argument("--policy", required=True)
    pspi_verify.add_argument("--master", required=True)
    pspi_verify.add_argument("--region", required=True)
    pspi_verify.add_argument("--secure", required=True, choices=["true", "false"])
    pspi_verify.add_argument("--privileged", required=True, choices=["true", "false"])
    pspi_verify.add_argument("--test-result", required=True,
                             help="JSON file of the test_result dict.")
    pspi_verify.add_argument("--json", action="store_true")

    pslr = sub.add_parser("self-learning-readiness",
                          help="Section 55's SELF-LEARNING READINESS MATRIX (22 rows), "
                               "aggregated from real research/capability-evolution and "
                               "five-tier-memory sources. Reads only; runs and writes "
                               "nothing. See dv_harness/self_learning_readiness.py.")
    pslr.add_argument("--json", action="store_true")

    psbrr = sub.add_parser("shared-bus-resource-registry",
                           help="Intra-subsystem shared-bus-resource registry: does a real "
                                "branch_fw programmer and a real branch_a* programmer reach "
                                "the same shared resource without a common named lock? "
                                "Detection only -- never picks a lock. "
                                "See dv_harness/shared_bus_resource_registry.py.")
    psbrr.add_argument("--resource-declarations", dest="sbrr_resource_declarations",
                       help="JSON array of caller-declared shared-resource records.")
    psbrr.add_argument("--connectivity-rows", dest="sbrr_connectivity_rows", default=None,
                       help="JSON array of real connectivity-matrix rows for this subsystem.")
    psbrr.add_argument("--json", action="store_true")

    psdm = sub.add_parser("spec-doc-map",
                          help="Offline STRUCTURAL distiller for non-VIP DUT spec/datasheet/"
                               "programming-guide documents: chapter/section titles, table "
                               "locations, register-chapter page ranges. Never extracts or "
                               "persists full body prose. See dv_harness/spec_doc_map.py.")
    psdm_sub = psdm.add_subparsers(dest="sdm_verb", required=True)
    psdm_ex = psdm_sub.add_parser("extract",
                                  help="Extract a structure map from one source document.")
    psdm_ex.add_argument("--source", required=True, dest="sdm_source_path")
    psdm_ex.add_argument("--out-dir", required=True, dest="sdm_out_dir")
    psdm_ex.add_argument("--title", dest="sdm_title", default=None)
    psdm_ex.add_argument("--doc-kind", dest="sdm_doc_kind", default="dut_spec")
    psdm_ex.add_argument("--json", action="store_true")
    psdm_sh = psdm_sub.add_parser("show",
                                  help="Print an already-extracted structure_map.json record.")
    psdm_sh.add_argument("--record", required=True, dest="sdm_record_path")
    psdm_sh.add_argument("--json", action="store_true")

    psi = sub.add_parser("spec-intelligence",
                         help="Build a SpecMap structure index, or validate an atomic "
                              "requirement extraction/relation/dependency document (section "
                              "184/187 contract + relation re-derivation). "
                              "See dv_harness/spec_intelligence.py.")
    psi_sub = psi.add_subparsers(dest="si_cmd", required=True)
    psi_map = psi_sub.add_parser("spec-map",
                                 help="Build a SpecMap from a vip_user_guide_distill reference record.")
    psi_map.add_argument("--reference", required=True, dest="si_reference")
    psi_map.add_argument("--out", required=True, dest="si_out")
    psi_map.add_argument("--json", action="store_true")
    psi_an = psi_sub.add_parser("analyze", help="Validate an extraction document.")
    psi_an.add_argument("--extraction", required=True, dest="si_extraction")
    psi_an.add_argument("--project-root", dest="si_project_root", default=None)
    psi_an.add_argument("--json", action="store_true")
    psi_an.add_argument("--fail-on-error", action="store_true")

    psvd = sub.add_parser("spec-vplan-delta",
                          help="Semantic diff of two requirement-IR-shaped snapshots: "
                               "ADDED/MODIFIED/REMOVED/REVALIDATION_REQUIRED per requirement. "
                               "See dv_harness/spec_vplan_delta.py.")
    psvd.add_argument("--before", required=True, help="Baseline requirement-IR JSON file.")
    psvd.add_argument("--after", required=True, help="Current requirement-IR JSON file.")
    psvd.add_argument("--vplan-delta-root", default=None,
                      help="Project root whose .dv-harness/requirements.csv grounds "
                           "vPlan/pattern/coverage linkage (default: this project's own root).")
    psvd.add_argument("--json", action="store_true")

    psvrg = sub.add_parser("spec-vplan-readiness-gate",
                           help="The SPEC_VPLAN_READY conjunction over caller-named spec-to-"
                                "vplan-stage conditions -- worst-wins, never averaged. "
                                "See dv_harness/spec_vplan_readiness_gate.py.")
    psvrg.add_argument("svrg_verb", choices=("statuses", "verdicts", "evaluate"))
    psvrg.add_argument("--conditions", dest="svrg_conditions",
                       help="evaluate: JSON list of {condition_name, status, reason} records.")
    psvrg.add_argument("--json", action="store_true")

    pscm = sub.add_parser("subsys-compat-matrix",
                          help="Subsystem Compatibility Matrix: which subsystem pairs are "
                               "known-compatible for composition, from the REAL SYS-9..14 "
                               "cross-subsystem resource analysis and each subsystem's own "
                               "real IP-ownership self-check. Never a hand-typed matrix. "
                               "See dv_harness/subsys_compat_matrix.py.")
    pscm.add_argument("--root", dest="scm_root", default=None,
                      help="Project root (contains .dv-harness/). Default: this project's own.")
    pscm.add_argument("--selected", dest="scm_selected", default=None,
                      help="Path to a JSON array of subsystem names. Omit to use the real "
                           "registered subsystem set.")
    pscm.add_argument("--ip-ownership-inputs", dest="scm_ip_ownership_inputs", default=None,
                      help="Path to a JSON object keyed by subsystem id, each value carrying "
                           "optional legacy_bfm_declarations/connectivity_rows/env_manifest "
                           "for that subsystem's own IP-ownership self-check.")
    pscm.add_argument("--json", action="store_true")

    pssc = sub.add_parser("subsystem-contract",
                          help="Assemble one authoritative SubsystemVerificationContract "
                               "record from this project's existing real readers "
                               "(env_manifest, requirement_contract, golden_scenario, "
                               "signoff_export, waiver_store). 'assemble' reads only; "
                               "'snapshot' additionally writes "
                               ".dv-harness/subsystem_contract.json. "
                               "See dv_harness/subsystem_contract.py.")
    pssc.add_argument("ssc_verb", choices=("assemble", "snapshot"))
    pssc.add_argument("--root", dest="ssc_root", default=None)
    pssc.add_argument("--subsystem", dest="ssc_subsystem", default=None,
                      help="Registered subsystem name (environment_mode_router registry). "
                           "Omit for project scope.")
    pssc.add_argument("--manifest", dest="ssc_manifest", default=None,
                      help="Explicit env.manifest.json path (default: this project's own).")
    pssc.add_argument("--requirements", dest="ssc_requirements", default=None,
                      help="Requirement-contract JSON file (default: a few conventional "
                           "paths).")
    pssc.add_argument("--db", dest="ssc_db", default=None,
                      help="Evidence database path (default: "
                           "<root>/.dv-harness/evidence/evidence.duckdb).")
    pssc.add_argument("--declared-spec-version", dest="ssc_spec_version", default=None,
                      help="A human-declared spec version (attested, never machine-"
                           "verified).")
    pssc.add_argument("--json", action="store_true")

    psmg = sub.add_parser("subsystem-maturity-gate",
                          help="Composite 9.0/9.5/10.0 subsystem maturity qualification "
                               "gates. Reads only; runs no stage, gate script, build, "
                               "regression or LSF job. "
                               "See dv_harness/subsystem_maturity_gate.py.")
    psmg_sub = psmg.add_subparsers(dest="smg_verb", required=True)
    psmg_cond = psmg_sub.add_parser("conditions", help="List the declared conditions.")
    psmg_cond.add_argument("--json", action="store_true")
    psmg_eval = psmg_sub.add_parser("evaluate", help="Evaluate one maturity level.")
    psmg_eval.add_argument("--level", required=True, choices=("9.0", "9.5", "10.0"))
    psmg_eval.add_argument("--root", dest="smg_root", default=None)
    psmg_eval.add_argument("--json", action="store_true")
    psmg_eval.add_argument("--vip-api-cards", dest="smg_vip_api_cards", default=None,
                           help="path to a written vip_api_cards.json artifact")
    psmg_eval.add_argument("--vip-source", action="append", default=None,
                           dest="smg_vip_sources",
                           help="generated SystemVerilog source/dir to validate "
                                "(repeatable); used only if --vip-api-cards is not given")
    psmg_eval.add_argument("--vip-index", dest="smg_vip_index", default=None,
                           help="a vip_symbol_index document, used with --vip-source")
    psmg_eval.add_argument("--bind-topology", dest="smg_bind_topology", default=None,
                           help="a manifest_inputs/*_bind_topology.json path")
    psmg_eval.add_argument("--require-tier", dest="smg_require_tier", action="store_true")
    psmg_eval.add_argument("--evidence-db", dest="smg_evidence_db", default=None,
                           help="override the default .dv-harness/evidence/evidence.duckdb "
                                "path")
    psmg_eval.add_argument("--smoke-proof-report", dest="smg_smoke_proof_report",
                           default=None,
                           help="a JSON file holding a "
                                "system_build_proof.SmokeProofReport.to_dict()")

    pspr = sub.add_parser("subsystem-practicality-score",
                          help="A 10-dimension weighted maturity rollup over this project's "
                               "own generation_readiness/golden_flow_readiness/"
                               "loop_convergence/coverage_analysis/confidence_calibration "
                               "reports. Reads only; runs no stage. "
                               "See dv_harness/subsystem_practicality_score.py.")
    pspr.add_argument("spr_verb", nargs="?", default="show",
                      choices=["dimensions", "report", "show"])
    pspr.add_argument("--project-root", dest="spr_project_root", default=None)
    pspr.add_argument("--json", action="store_true")
    pspr.add_argument("--deep", action="store_true",
                      help="also run generation_readiness.py's expensive SYS-1..SYS-30 "
                           "cross-subsystem chain")

    psyo = sub.add_parser("syoscb-source-audit",
                          help="SYOSCB-1 read-only audit of an uvm_syoscb source tree, and "
                               "the SYOSCB-3 Knowledge Center registration payload built "
                               "from it. Reads only; never copies, never publishes. "
                               "See dv_harness/syoscb_source_audit.py.")
    psyo.add_argument("syo_root", help="upstream source directory to audit, read-only")
    psyo.add_argument("--json", action="store_true", help="emit the audit as JSON")
    psyo.add_argument("--registration-payload", dest="syo_registration_payload",
                      action="store_true",
                      help="also build (never publish) the SYOSCB-3 registration payload")
    psyo.add_argument("--l5-destination", dest="syo_l5_destination", default=None,
                      help="the approved in-repo destination, if a human has decided one")
    psyo.add_argument("--assert-not-vendored", dest="syo_assert_not_vendored",
                      metavar="REPO_ROOT", default=None,
                      help="fail if any upstream file is already inside this repository")

    psct = sub.add_parser("system-checker-taxonomy",
                          help="Classify a SYSTEM-scope checker's KIND (data-flow, "
                               "resource-arbitration, address-routing, clock-reset-"
                               "sequencing, command-compatibility, build-integrity, "
                               "scoreboard-composition, recovery, error-propagation) from a "
                               "declared or keyword-matched description. "
                               "See dv_harness/system_checker_taxonomy.py.")
    psct_sub = psct.add_subparsers(dest="sct_cmd", required=True)
    psct_sub.add_parser("types", help="List the fixed nine checker categories.")
    psct_classify = psct_sub.add_parser("classify",
                                        help="Classify a list of checker descriptions.")
    psct_classify.add_argument("sct_path",
                               help="JSON file: bare list, or {\"checkers\": [...]}.")
    psct_classify.add_argument("--json", action="store_true")

    psca = sub.add_parser("system-closure-aggregator",
                          help="Strict worst-wins CLOSED/NOT_CLOSED/INCOMPLETE_EVIDENCE "
                               "rollup over twelve caller-declared system closure "
                               "dimensions -- never averaged. "
                               "See dv_harness/system_closure_aggregator.py.")
    psca.add_argument("--dimensions", dest="sca_dimensions", required=True,
                      help="path to a JSON file: a bare list of "
                           "{dimension_name, status} records, or "
                           "{\"dimensions\": [...]}")
    psca.add_argument("--markdown", dest="sca_markdown", action="store_true",
                      help="render as a markdown table instead of JSON")

    pscg = sub.add_parser("system-command-grammar-ir",
                          help="Compose several subsystems' own command.txt style learning "
                               "into one system-level grammar verdict. "
                               "See dv_harness/system_command_grammar_ir.py.")
    pscg.add_argument("--subsystem", action="append", default=[], dest="scg_subsystem",
                      metavar="ID=PATH",
                      help="one subsystem's id and its real command.txt-style file path, "
                           "e.g. --subsystem usb0=usb0/command.txt (repeatable)")
    pscg.add_argument("--json", action="store_true")

    psep = sub.add_parser("system-error-propagation",
                          help="Trace an ErrorPropagationIR: given an origin subsystem and "
                               "an error/failure condition, over a real-or-duck-typed "
                               "cross-subsystem topology document, find which OTHER "
                               "subsystems the topology's own proven relationships show a "
                               "path to, and whether each declares a real recovery action. "
                               "Reads only; runs/submits/approves nothing. "
                               "See dv_harness/system_error_propagation.py.")
    psep.add_argument("sep_verb", choices=("trace",))
    psep.add_argument("--origin", required=True, help="Origin subsystem_id.")
    psep.add_argument("--condition", dest="sep_condition_text", default=None,
                      help="Error condition, as a bare string, or free text treated as "
                           "GENERIC.")
    psep.add_argument("--condition-file", dest="sep_condition_path", default=None,
                      help="Path to a JSON document {\"kind\", \"description\"} instead of "
                           "--condition.")
    psep.add_argument("--topology", required=True, dest="sep_topology_path",
                      help="Path to a topology JSON document shaped like "
                           "system_topology_analysis.build_system_topology_analysis()'s "
                           "output.")
    psep.add_argument("--declared-responses", dest="sep_declared_responses_path",
                      default=None,
                      help="Path to a JSON array of caller-declared "
                           "{\"subsystem_id\", \"response_action\", \"evidence\"} records.")
    psep.add_argument("--json", action="store_true")

    psfw = sub.add_parser("system-fw-service-registry",
                          help="Per-SYSTEM branch_fw service-loop ownership registry across "
                               "composed subsystems. Reuses branch_ownership_resolver.py's "
                               "FW classification and system_resource_inventory.py's real "
                               "cross-subsystem findings; re-derives neither. "
                               "See dv_harness/system_fw_service_registry.py.")
    psfw.add_argument("--input", dest="sfw_input", default=None,
                      help="Path to a JSON file: {\"subsystem_declarations\": [...], "
                           "\"cross_subsystem_findings\": {...}} (the latter optional).")
    psfw.add_argument("--json", action="store_true")

    psvc = sub.add_parser("system-verification-contract",
                          help="Assemble one authoritative SystemVerificationContract "
                               "record from N caller-supplied subsystem_contract.py-shaped "
                               "records plus a system_topology_analysis.py-shaped document, "
                               "a system_resource_inventory."
                               "real_cross_subsystem_findings()-shaped record and a "
                               "system_command_plan.py-shaped document. "
                               "See dv_harness/system_verification_contract.py.")
    psvc.add_argument("svc_verb", choices=("assemble", "snapshot"))
    psvc.add_argument("--root", dest="svc_root", default=None)
    psvc.add_argument("--subsystem-contracts", dest="svc_subsystem_contracts", default=None,
                      help="JSON file: a bare array, or {'subsystem_contracts': [...]}, of "
                           "subsystem_contract.py-shaped records.")
    psvc.add_argument("--topology", dest="svc_topology", default=None,
                      help="JSON file: a system_topology_analysis.py-shaped document.")
    psvc.add_argument("--resource-registry", dest="svc_resource_registry", default=None,
                      help="JSON file: a system_resource_inventory."
                           "real_cross_subsystem_findings()-shaped record.")
    psvc.add_argument("--command-registry", dest="svc_command_registry", default=None,
                      help="JSON file: a system_command_plan.py-shaped document.")
    psvc.add_argument("--system-name", dest="svc_system_name", default=None)
    psvc.add_argument("--json", action="store_true")

    pmad = sub.add_parser("missing-artifact-detector",
                          help="Target-conditioned missing-artifact detector: given a "
                               "downstream TARGET name (VIP_UVM_CREATION/SIGNOFF_PACKAGE/"
                               "COVERAGE_CLOSURE/REGRESSION_SUBMISSION) and a caller-"
                               "declared source-inventory, reports READY/"
                               "MISSING_ARTIFACTS/INCOMPLETE_EVIDENCE/UNKNOWN_TARGET. "
                               "See dv_harness/target_conditioned_missing_artifact_detector.py.")
    pmad.add_argument("mad_target", help="Downstream target name.")
    pmad.add_argument("mad_inventory", nargs="?", default=None,
                      help="Path to a JSON inventory file: {category_id: True/False/"
                           "omitted}. Omit for an empty inventory.")

    ptrm = sub.add_parser("task-return-model",
                          help="Cross-check a declared task list against a real sim.log "
                               "and report each task's resolved outcome ('no silent "
                               "command failure'). "
                               "See dv_harness/task_return_model.py.")
    ptrm.add_argument("--tasks", required=True, dest="trm_tasks",
                      help="Path to a JSON file: a list of task_id strings, or a list of "
                           "{task_id, layer, command} dicts.")
    ptrm.add_argument("--log", required=True, dest="trm_log",
                      help="Path to the real sim.log.")
    ptrm.add_argument("--json", action="store_true")

    ptci = sub.add_parser("transaction-correlation",
                          help="Correlate observed AMBA request/response/data-beat/sub-"
                               "transaction records into the Transaction Correlation IR. "
                               "Reads and reports only -- writes nothing, gates nothing. "
                               "See dv_harness/transaction_correlation_ir.py.")
    ptci_sub = ptci.add_subparsers(dest="tci_cmd", required=True)
    ptci_resp = ptci_sub.add_parser("responses", help="Correlate responses to requests.")
    ptci_resp.add_argument("--requests", required=True, dest="tci_requests",
                           help="JSON file: a list of request records.")
    ptci_resp.add_argument("--responses", required=True, dest="tci_responses",
                           help="JSON file: a list of response records.")
    ptci_resp.add_argument("--json", action="store_true")
    ptci_data = ptci_sub.add_parser("data",
                                    help="Associate data beats with transactions.")
    ptci_data.add_argument("--transactions", required=True, dest="tci_transactions",
                           help="JSON file: a list of transaction records.")
    ptci_data.add_argument("--beats", required=True, dest="tci_beats",
                           help="JSON file: a list of data-beat records.")
    ptci_data.add_argument("--json", action="store_true")
    ptci_link = ptci_sub.add_parser("linkage",
                                    help="Link burst split/merge sub-transactions to their "
                                         "parent.")
    ptci_link.add_argument("--event", required=True, dest="tci_event",
                           help="JSON file: one detected split/merge event.")
    ptci_link.add_argument("--parent", required=True, dest="tci_parent",
                           help="JSON file: one parent transaction record.")
    ptci_link.add_argument("--children", required=True, dest="tci_children",
                           help="JSON file: a list of child transaction records.")
    ptci_link.add_argument("--json", action="store_true")
    ptci_recon = ptci_sub.add_parser(
        "reconstruct",
        help="Reassemble one full logical AXI transaction record per declared "
             "transaction by joining already-computed response-correlation and "
             "data-association results.")
    ptci_recon.add_argument("--transactions", required=True, dest="tci_transactions",
                            help="JSON file: a list of {transaction_ref, request_ref, "
                                 "scope, evidence} records.")
    ptci_recon.add_argument("--requests", required=True, dest="tci_requests",
                            help="JSON file: a list of request records.")
    ptci_recon.add_argument("--responses", required=True, dest="tci_responses",
                            help="JSON file: a list of response records.")
    ptci_recon.add_argument("--data-transactions", required=True,
                            dest="tci_data_transactions",
                            help="JSON file: the transaction records for data-beat "
                                 "association.")
    ptci_recon.add_argument("--beats", required=True, dest="tci_beats",
                            help="JSON file: a list of data-beat records.")
    ptci_recon.add_argument("--json", action="store_true")

    psti = sub.add_parser("system-transaction-ir",
                          help="Compose amba_transaction_ir.py's per-fabric transaction facts "
                               "across subsystems into one System Transaction IR, over the "
                               "declared 22-field amba_transaction_ir shape plus real "
                               "cross-subsystem system_transaction_links evidence. Reads and "
                               "reports only -- writes nothing, gates nothing. "
                               "See dv_harness/system_transaction_ir.py.")
    psti_sub = psti.add_subparsers(dest="sti_cmd", required=True)
    psti_sub.add_parser("fields", help="List the reused 22-field amba_transaction_ir shape.")
    psti_build = psti_sub.add_parser(
        "build",
        help="Build the SystemTransactionIR from declared per-fabric templates and "
             "cross-subsystem link evidence.")
    psti_build.add_argument("--fabrics", required=True,
                            help="JSON file: {subsystem_id: [per-fabric IR templates]}.")
    psti_build.add_argument("--links", required=True,
                            help="JSON file: a list of system_transaction_links entries.")
    psti_build.add_argument("--json", action="store_true")

    # --- grpH wiring: unknown_uncertainty_registry, user_correction_trigger,
    # verification_boundary_ir, verification_intake_contract,
    # verification_intent_ir, verification_knowledge_graph,
    # vip_capability_extraction, vip_learning_gate, vplan_baseline,
    # vplan_item_executability_score, waiver_store, plus the two overlap-
    # checked items memory_cli.py (genuinely distinct from the existing
    # `memory` verb, which is the Markdown Vault surface only -- memory_cli.py
    # is the raw JSON MemoryStore/CornerCaseLibrary front door and was never
    # wired) and schema_config_governance.py (genuinely distinct from the
    # existing `schema-compat` verb -- it extends that module's own
    # classifier with the FORWARD_COMPATIBLE/MIGRATION_REQUIRED verdicts and
    # the section-146 governance registry, reusing schema_compat.py rather
    # than duplicating it). Each verb below reconstructs the module's own
    # `python -m dv_harness.<module>` argv and calls that module's real
    # execute_verb()/main(), same convention as transaction-correlation above.

    puur = sub.add_parser("unknown-uncertainty-registry",
                          help="Collect every open UNKNOWN row across this project's real "
                               "row-based readiness reports (golden_flow_readiness.py, "
                               "generation_readiness.py) into one registry. Derives no new "
                               "fact and resolves nothing. See "
                               "dv_harness/unknown_uncertainty_registry.py.")
    puur.add_argument("uur_verb", choices=["assemble", "snapshot"], metavar="{assemble,snapshot}")
    puur.add_argument("--no-deep", action="store_true", dest="uur_no_deep",
                      help="skip generation_readiness's expensive SYS-1..SYS-30 topology chain")
    puur.add_argument("--json", action="store_true")

    puct = sub.add_parser("user-correction-trigger",
                          help="Detect repeated user-correction patterns and file a DISCOVERED "
                               "capability-evolution candidate for each one found. "
                               "See dv_harness/user_correction_trigger.py.")
    puct.add_argument("uct_verb", choices=["detect", "file"], metavar="{detect,file}")
    puct.add_argument("--min-occurrences", type=int, default=None, dest="uct_min_occurrences")

    pvbi = sub.add_parser("verification-boundary-ir",
                          help="Classify a verification boundary into the fixed 10-value "
                               "boundary-class taxonomy and record cited 7-role ownership. "
                               "See dv_harness/verification_boundary_ir.py.")
    pvbi_sub = pvbi.add_subparsers(dest="vbi_cmd", required=True)
    pvbi_sub.add_parser("classes", help="list the fixed 10-value boundary-class taxonomy")
    pvbi_sub.add_parser("roles", help="list the fixed 7-role ownership vocabulary")
    pvbi_build = pvbi_sub.add_parser("build", help="build and report VerificationBoundaryIR(s)")
    pvbi_build.add_argument("--boundaries", required=True, dest="vbi_boundaries",
                            help="path to a JSON file: a list of boundary dicts")
    pvbi_build.add_argument("--json", action="store_true")

    pvic = sub.add_parser("verification-intake-contract",
                          help="The whole-project VerificationIntakeContract lifecycle "
                               "(13-state machine) and the INTAKE_READY conjunction over "
                               "caller-named critical conditions. "
                               "See dv_harness/verification_intake_contract.py.")
    pvic.add_argument("vic_verb", choices=["states", "transitions", "evaluate"],
                      metavar="{states,transitions,evaluate}")
    pvic.add_argument("--state", default=None, dest="vic_state",
                      help="For 'transitions': the current state to list legal next states for.")
    pvic.add_argument("--conditions", default=None, dest="vic_conditions",
                      help="For 'evaluate': JSON file of {name,status,reason} condition records.")
    pvic.add_argument("--json", action="store_true")

    pvii = sub.add_parser("verification-intent-ir",
                          help="Build the Verification Intent IR set (state_machine/"
                               "register_csr/interrupt/reset_clock/low_power/performance/"
                               "error_recovery domain plans) for every requirement in a "
                               "requirement-contract-shaped JSON file. "
                               "See dv_harness/verification_intent_ir.py.")
    pvii.add_argument("--requirements", required=True, dest="vii_requirements",
                      help='JSON file: a bare list of requirement records, or {"requirements":[...]}')
    pvii.add_argument("--source-paths", nargs="*", default=None, dest="vii_source_paths",
                      help="RTL/spec text files for interrupt_dma_clock_reset_extraction.py")
    pvii.add_argument("--sys-regmap", default=None, dest="vii_sys_regmap", help="sys_regmap.json path")
    pvii.add_argument("--upf", nargs="*", default=None, dest="vii_upf", help="UPF file(s)")
    pvii.add_argument("--json", action="store_true")

    pvkg = sub.add_parser("verification-knowledge-graph",
                          help="Build the cross-linked graph over real evidence-DB rows, "
                               "requirement-contract records and memory-store records, with "
                               "the section-184 traceability-gap report. "
                               "See dv_harness/verification_knowledge_graph.py.")
    pvkg.add_argument("--evidence-db", default=None, dest="vkg_evidence_db",
                      help="path to a real evidence.duckdb")
    pvkg.add_argument("--requirements", default=None, dest="vkg_requirements",
                      help="path to a requirement_contract-shaped JSON file")
    pvkg.add_argument("--memory-root", default=None, dest="vkg_memory_root",
                      help="project root containing .dv-harness/memory")
    pvkg.add_argument("--json", action="store_true")

    pvce = sub.add_parser("vip-capability-extraction",
                          help="Classify a real vip_symbol_index into VIPConfigIR/"
                               "VIPTransactionIR/VIPScenarioPatternIR/VIPCheckerCapabilityIR/"
                               "VIPCoverageCapabilityIR, each carrying a 5-level qualification "
                               "tag. See dv_harness/vip_capability_extraction.py.")
    pvce.add_argument("--index", required=True, dest="vce_index",
                      help="vip_symbol_index JSON document.")
    pvce.add_argument("--project-source", action="append", default=None, dest="vce_project_sources",
                      help="Generated project .sv/.svh file or directory (repeatable).")
    pvce.add_argument("--example-source", action="append", default=None, dest="vce_example_sources",
                      help="VIP Examples/ .sv/.svh file or directory (repeatable).")
    pvce.add_argument("--user-guide-reference-md", action="append", default=None,
                      dest="vce_user_guide_reference_md",
                      help="A <stem>.reference.md produced by vip_user_guide_distill (repeatable).")
    pvce.add_argument("--out-dir", default=None, dest="vce_out_dir",
                      help="Also write vip_capability_extraction.json here.")
    pvce.add_argument("--json", action="store_true")

    pvlg = sub.add_parser("vip-learning-gate",
                          help="One pre-generation checkpoint over four already-real signals: "
                               "vip_api_card.py, phy_boundary.py, connectivity.py bind-tier "
                               "resolution and env_manifest.py's vip_config layer. "
                               "See dv_harness/vip_learning_gate.py.")
    pvlg.add_argument("--vip-source", action="append", dest="vlg_vip_sources", default=None,
                      help="Generated .sv/.svh source or directory to VIP-API-validate (repeatable).")
    pvlg.add_argument("--vip-index", default=None, dest="vlg_vip_index", help="vip_symbol_index JSON document.")
    pvlg.add_argument("--vip-relative-to", default=None, dest="vlg_vip_relative_to",
                      help="Root for reported VIP API usage paths.")
    pvlg.add_argument("--phy-boundary", default=None, dest="vlg_phy_boundary",
                      help="A real phy_boundary.json document.")
    pvlg.add_argument("--bind-entries", default=None, dest="vlg_bind_entries",
                      help="A JSON file: a list of bind entries.")
    pvlg.add_argument("--require-tier", action="store_true", dest="vlg_require_tier",
                      help="Also refuse a bind entry carrying no tier at all.")
    pvlg.add_argument("--env-manifest", default=None, dest="vlg_env_manifest",
                      help="A real env.manifest.json document.")
    pvlg.add_argument("--json", action="store_true")

    pvpb = sub.add_parser("vplan-baseline",
                          help="vPlan-scoped signoff freeze / baseline (mirrors "
                               "signoff_export.py's freeze/invalidation pattern) over "
                               "spec_version/requirement_ir_version/configuration_ir_version/"
                               "vplan_items. See dv_harness/vplan_baseline.py.")
    pvpb.add_argument("vpb_verb", choices=["fields", "baseline", "freeze", "list", "status"],
                      metavar="{fields,baseline,freeze,list,status}")
    pvpb.add_argument("--vplan", default=None, dest="vpb_vplan", help="path to a vPlan JSON document")
    pvpb.add_argument("--requirements", default=None, dest="vpb_requirements",
                      help="path to a requirement-contract records JSON file")
    pvpb.add_argument("--configuration-ir", default=None, dest="vpb_configuration_ir",
                      help="path to a configuration-IR JSON document")
    pvpb.add_argument("--freeze-id", default=None, dest="vpb_freeze_id")
    pvpb.add_argument("--frozen-by", default=None, dest="vpb_frozen_by")
    pvpb.add_argument("--spec-version", default=None, dest="vpb_spec_version",
                      help="declare the spec version this vPlan is against")
    pvpb.add_argument("--head", default="HEAD", dest="vpb_head")
    pvpb.add_argument("--json", action="store_true")

    pvie = sub.add_parser("vplan-item-executability-score",
                          help="Score one/many vPlan items on the fixed 5-point "
                               "NO_EVIDENCE/IDENTIFIED_UNMAPPED/PARTIALLY_MAPPED/"
                               "MAPPED_OPEN_QUESTIONS/FULLY_READY executability scale -- "
                               "never conflated with a separately-reported critical blocker. "
                               "See dv_harness/vplan_item_executability_score.py.")
    pvie.add_argument("--items", required=True, dest="vie_items",
                      help="JSON file: a list of vPlan item records")
    pvie.add_argument("--required-facts", default=None, dest="vie_required_facts",
                      help="comma-separated fact names")
    pvie.add_argument("--json", action="store_true")

    pwvs = sub.add_parser("waiver-store",
                          help="Report on the real waiver ledger (.dv-harness/waivers/"
                               "waivers.json) this project's real waiver gates already read -- "
                               "derived VALID/REVALIDATION_REQUIRED/EXPIRED/REVOKED/UNKNOWN "
                               "status per waiver, never stored. "
                               "See dv_harness/waiver_store.py.")
    pwvs.add_argument("wvs_verb", choices=["statuses", "list", "status"], metavar="{statuses,list,status}")
    pwvs.add_argument("--json", action="store_true")

    pmst = sub.add_parser("memory-store",
                          help="The raw JSON MemoryStore/CornerCaseLibrary front door "
                               "(dv_harness/memory.py) -- search/get/deprecate over durable "
                               "5-tier memory records and the corner-case library, plus "
                               "index-check/reindex. Deliberately a SEPARATE command group from "
                               "the `memory` verb above, which is specifically the Markdown/"
                               "YAML Vault's own surface (dv_harness/memory_vault.py). "
                               "See dv_harness/memory_cli.py.")
    pmst_sub = pmst.add_subparsers(dest="mst_cmd", required=True)
    pmst_search = pmst_sub.add_parser("search")
    pmst_search.add_argument("--protocol", default="")
    pmst_search.add_argument("--scope", default="")
    pmst_search.add_argument("--symptom", action="append", default=[], dest="mst_symptom")
    pmst_search.add_argument("--text", default="")
    pmst_search.add_argument("--level", action="append", default=[], dest="mst_level",
                             choices=["working", "job", "project", "engineering", "organizational"],
                             help="Restrict to one or more memory tiers (repeatable).")
    pmst_search.add_argument("--confidence", default="")
    pmst_search.add_argument("--status", default="")
    pmst_search.add_argument("--property", action="append", default=[], dest="mst_properties",
                             metavar="KEY=VALUE")
    pmst_search.add_argument("--rank-by", default="relevance", dest="mst_rank_by",
                             choices=["relevance", "usefulness"],
                             help="Ranking mode (2026-09-07). 'relevance' (default) is the "
                                  "pre-existing fixed heuristic, unchanged. 'usefulness' "
                                  "additionally weights real reuse_count/MemoryGC.mark_used() "
                                  "history into the score -- an explicit, opt-in alternative "
                                  "that never changes which records match, only their order.")
    pmst_search.add_argument("--usefulness-weight", type=float, default=1.0, dest="mst_usefulness_weight",
                             help="Multiplier on log1p(reuse_count) when --rank-by usefulness is used.")
    pmst_search.add_argument("--limit", type=int, default=8)
    pmst_get = pmst_sub.add_parser("get")
    pmst_get.add_argument("memory_id")
    pmst_dep = pmst_sub.add_parser("deprecate")
    pmst_dep.add_argument("memory_id")
    pmst_dep.add_argument("--reason", required=True)
    pmst_ccs = pmst_sub.add_parser("corner-case-search")
    pmst_ccs.add_argument("--protocol", default="")
    pmst_ccs.add_argument("--category", default="")
    pmst_ccs.add_argument("--text", default="")
    pmst_ccg = pmst_sub.add_parser("corner-case-get")
    pmst_ccg.add_argument("ccl_id")
    pmst_cca = pmst_sub.add_parser("corner-case-add")
    pmst_cca.add_argument("--record", required=True, dest="mst_record",
                          help="path to a JSON file with the corner_case fields")
    pmst_cca.add_argument("--resolution", default=None, dest="mst_resolution",
                          help="optional path to a JSON file with {test_mapping,semantic_verdict,"
                               "runtime_evidence_hash} -- runs through CornerCaseLibraryConsolidator")
    pmst_ccd = pmst_sub.add_parser("corner-case-deprecate")
    pmst_ccd.add_argument("ccl_id")
    pmst_ccd.add_argument("--reason", required=True)
    pmst_sub.add_parser("index-check", help="Read-only drift report between the per-tier record "
                                             "files on disk and index.json's rows. Repairs nothing.")
    pmst_rix = pmst_sub.add_parser("reindex", help="Rebuild index.json from the real record files "
                                                    "on disk (MemoryStore.reindex()).")
    pmst_rix.add_argument("--prune-missing", action="store_true", dest="mst_prune_missing",
                          help="Also DROP index rows whose record file no longer exists.")

    pscg = sub.add_parser("schema-config-governance",
                          help="Section 146 schema/configuration governance registry over "
                               "dv_harness/schemas/*.schema.json (schema_id/schema_version/"
                               "unknown_field_policy/required_field_policy/validation/"
                               "compatibility, plus the fifteen named logical schemas), plus "
                               "the FORWARD_COMPATIBLE/MIGRATION_REQUIRED verdicts and impact-"
                               "analysis artifacts (consumer inventory, rollback, tests, "
                               "human-gate) that `schema-compat` (dv_harness/schema_compat.py) "
                               "does not cover -- reuses that module's own "
                               "classify_schema_change() rather than re-deriving JSON Schema "
                               "comparison logic. See dv_harness/schema_config_governance.py.")
    pscg_sub = pscg.add_subparsers(dest="scg_cmd", required=True)
    pscg_reg = pscg_sub.add_parser("registry", help="audit every real dv_harness/schemas/*.schema.json "
                                                     "plus the fifteen named logical schemas")
    pscg_reg.add_argument("--json", action="store_true")
    pscg_cla = pscg_sub.add_parser("classify", help="five-value BACKWARD/FORWARD/MIGRATION_REQUIRED/"
                                                     "BREAKING/UNKNOWN classification of one schema change")
    pscg_cla.add_argument("--old", required=True, dest="scg_old")
    pscg_cla.add_argument("--new", required=True, dest="scg_new")
    pscg_cla.add_argument("--schema-filename", dest="scg_schema_filename",
                          help="the real dv_harness/schemas/<file> this change targets")
    pscg_cla.add_argument("--owning-module", dest="scg_owning_module",
                          help="the real dv_harness/<file>.py that owns this schema")
    pscg_cla.add_argument("--migration-fn", dest="scg_migration_fn",
                          help="module.path:function_name of a real migration function")
    pscg_cla.add_argument("--corpus", nargs="*", default=[], dest="scg_corpus")
    pscg_cla.add_argument("--json", action="store_true")

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
        if getattr(args, "status_view", None) is None:
            print(h.summary())
        else:
            from .harness_status import HarnessStatusService
            _hs_snapshot = HarnessStatusService(h.root).serve()
            print(_render_harness_status_view(args.status_view, _hs_snapshot,
                                               as_json=args.json))
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
        # self_check_list #41 caps how long the harness may go without
        # re-confirming job/sim-log state. A slower interval is still allowed
        # (the operator asked for it explicitly), but never silently: the
        # warning goes to stderr so stdout stays pure JSON for callers.
        compliance = regression_reporter.interval_compliance(args.interval_minutes)
        if not compliance["compliant"]:
            print(f"[warn] {compliance['message']}", file=sys.stderr)
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
        # stdin can be consumed ONCE, and both gates need the refspecs, so it
        # is captured here and handed to each rather than read twice.
        _push_stdin = sys.stdin.read() if args.check == "pre-push" else ""
        if args.check == "pre-push":
            decision = _gg.evaluate_pre_push(_push_stdin, os.environ)
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
        # The branch gate's verdict is FINAL when it blocks: print ITS decision
        # alone and exit, byte-for-byte as before this second gate existed.
        if not decision.allowed:
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
            raise SystemExit(1)

        # SECOND GATE, additive only. Reached only on a push/merge the branch
        # gate allowed, so it can never turn a block into an allow. A crash in
        # here must not become a bypass of the branch gate NOR an unexplained
        # abort of a legitimate push -- an unexpected exception is reported and
        # allowed (fail-open on our own ignorance, per that module's docstring;
        # a real over-threshold measurement still blocks below).
        #
        # OUTPUT CONTRACT: exactly ONE json document on stdout, always -- the
        # branch decision, with the blast-radius verdict NESTED under
        # "blast_radius". Found by test_cli_git_guard.py, which (like any hook
        # or script consuming this command) does json.loads() on the whole of
        # stdout: printing a second top-level document made every existing
        # caller fail with "Extra data". The pre-existing top-level keys are
        # untouched, so this is an additive field, not a changed shape.
        payload = decision.to_dict()
        if args.skip_blast_radius:
            payload["blast_radius"] = {"skipped": True,
                                        "reason": "--skip-blast-radius"}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        from . import change_blast_radius as _cbr
        try:
            if args.check == "pre-push":
                br = _cbr.evaluate_pre_push(h.root, _push_stdin, os.environ)
            else:
                br = _cbr.evaluate_pre_merge_commit(h.root, args.merge_head, os.environ)
        except Exception as exc:  # noqa: BLE001 -- see the comment above
            payload["blast_radius"] = {
                "allowed": True,
                "reason": f"blast-radius check errored ({type(exc).__name__}: {exc}) -- "
                          "allowing; the PR-only branch gate already ran and is unaffected."}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        # Same real audit trail as the branch gate -- one events.jsonl, never a
        # second parallel governance log. Logged whenever a tier was really
        # measured (NOT_ASSESSABLE carries no finding worth a trail entry).
        if br.tier != _cbr.TIER_NOT_ASSESSABLE:
            h.store.event({"ts": cp_now(), "event": "BLAST_RADIUS_DECISION",
                            "hook": br.hook, "allowed": br.allowed, "tier": br.tier,
                            "digest": (br.assessment or {}).get("digest"),
                            "file_count": (br.assessment or {}).get("file_count"),
                            "reach": (br.assessment or {}).get("reach"),
                            "governance_files_touched": (br.assessment or {}).get(
                                "governance_files_touched"),
                            "detected_markers": br.detected_markers, "reason": br.reason,
                            "user": _access_user(), "host": _access_host()})
        payload["blast_radius"] = br.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0 if br.allowed else 1)
    elif args.cmd == "blast-radius":
        from . import change_blast_radius as _cbr
        assessment = _cbr.assess_range(h.root, args.base, args.head)
        status = _cbr.confirmation_status(h.root, assessment.digest)
        print(json.dumps({
            **assessment.to_dict(),
            "requires_confirmation": assessment.tier in _cbr.TIERS_REQUIRING_CONFIRMATION,
            "confirmation": status,
            "confirmation_command": _cbr.confirmation_command(assessment.digest),
        }, ensure_ascii=False, indent=2))
    elif args.cmd == "mutation-test":
        from . import mutation_testing as _mut
        modules = args.module or list(_mut.DEFAULT_TARGETS)
        if args.test and len(modules) != 1:
            raise SystemExit("--test names one test file, so pass exactly one --module with it")
        line_range = None
        if args.lines:
            low, _, high = args.lines.partition(":")
            line_range = (int(low), int(high or low))
        operators = args.operator or _mut.MUTATION_OPERATORS
        payload, failed = [], False
        for name in modules:
            module_file, test_file = _mut.resolve_target(h.root, name, args.test)
            if args.list_only:
                _mut.assert_safe_target(h.root, module_file, test_file)
                mutants = _mut.generate_mutants(
                    module_file.read_text(encoding="utf-8"), str(module_file),
                    operators=operators, line_range=line_range)
                payload.append({"module": name, "module_path": str(module_file),
                                 "test_path": str(test_file),
                                 "generated": len(mutants),
                                 "mutants": [m.to_dict() for m in mutants]})
                continue
            report = _mut.run_mutation_test(
                h.root, name, test_path=args.test, operators=operators,
                max_mutants=args.max_mutants, line_range=line_range,
                timeout=args.timeout or _mut.DEFAULT_TIMEOUT_SECONDS)
            payload.append(report.to_dict())
            if report.baseline != _mut.BASELINE_OK:
                failed = True
            elif args.min_score is not None and (report.mutation_score is None
                                                  or report.mutation_score < args.min_score):
                failed = True
        print(json.dumps(payload if len(payload) != 1 else payload[0],
                         ensure_ascii=False, indent=2))
        raise SystemExit(1 if failed else 0)
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
    elif args.cmd == "system-signoff-package":
        from . import system_signoff_package
        argv = ["collect", "--root", args.root, "--out-dir", args.out_dir]
        for name in args.subsystems:
            argv += ["--subsystem", name]
        for flag, val in (
            ("--subsystem-contracts", args.subsystem_contracts_path),
            ("--topology", args.topology_path),
            ("--resource-registry", args.resource_registry_path),
            ("--command-registry", args.command_registry_path),
            ("--closure-dimensions", args.closure_dimensions_path),
            ("--system-name", args.system_name),
            ("--manifest", args.manifest_path),
            ("--requirements", args.requirements_path),
            ("--db", args.db_path),
            ("--declared-spec-version", args.declared_spec_version),
        ):
            if val is not None:
                argv += [flag, val]
        if args.require_system_signoff_pass:
            argv.append("--require-system-signoff-pass")
        if args.json:
            argv.append("--json")
        raise SystemExit(system_signoff_package.execute_verb(argv))
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
    elif args.cmd == "uvm-lint":
        from . import uvm_structural_lint
        from .verible_parser import DEFAULT_VERIBLE_BIN
        vbin = args.verible_bin or DEFAULT_VERIBLE_BIN
        if args.env_dir:
            report = uvm_structural_lint.lint_uvm_environment(args.env_dir, verible_bin=vbin)
        else:
            report = uvm_structural_lint.lint_uvm_sources(args.lint_files, verible_bin=vbin)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(uvm_structural_lint.format_report(report))
        # NOT_AVAILABLE is deliberately not an exit-1 even under
        # --fail-on-error: "verible could not be run" is a missing tool, not a
        # defect in the generated environment, and conflating the two would
        # make an absent verible look like broken UVM.
        if args.fail_on_error and report.status == "FAIL":
            raise SystemExit(1)
    elif args.cmd == "power-intent":
        # One shared implementation with `python -m dv_harness.power_intent`
        # (power_intent.execute_verb), same convention as verification-strategy
        # and loop-contract. NOT_AVAILABLE exits 2 unconditionally: "this project
        # has no power intent" is spec section 224's UNSUPPORTED/UNKNOWN answer
        # and must never be reportable as a clean PASS, with or without
        # --fail-on-error.
        from . import power_intent as _pi
        _pi_text, _pi_code = _pi.execute_verb(args.upf_paths, as_json=args.json)
        print(_pi_text)
        if _pi_code == 1 and not args.fail_on_error:
            _pi_code = 0
        if _pi_code:
            raise SystemExit(_pi_code)
    elif args.cmd == "requirement-contract":
        # One shared implementation with
        # `python -m dv_harness.requirement_contract`
        # (requirement_contract.execute_verb), same convention as power-intent
        # above. Exit codes: 0 clean, 1 ERROR findings, 2 NOT_AVAILABLE (no
        # record declares the contract shape, so there was nothing to check --
        # an empty analysis must never read as a clean PASS).
        from . import requirement_contract as _rqc
        _rqc_text, _rqc_code = _rqc.execute_verb(
            args.requirements, as_json=args.json, fail_on_error=args.fail_on_error)
        print(_rqc_text)
        if _rqc_code:
            raise SystemExit(_rqc_code)
    elif args.cmd == "schema-compat":
        # One shared implementation with `python -m dv_harness.schema_compat`
        # (schema_compat.execute_verb), same convention as power-intent above.
        # Exit codes: 0 BACKWARD_COMPATIBLE, 1 BREAKING, 2 NOT_AVAILABLE
        # (nothing comparable / a schema could not be read), 3 UNKNOWN --
        # "could not decide" gets its own code so it can never be read as a
        # clean PASS by a caller that only checks for zero.
        from . import schema_compat as _scc
        _sc_text, _sc_code = _scc.execute_verb(
            old=args.old, new=args.new, base=args.base, root=args.root,
            corpus=args.corpus, as_json=args.json)
        print(_sc_text)
        if _sc_code:
            raise SystemExit(_sc_code)
    elif args.cmd == "golden-scenario":
        # One shared implementation with `python -m dv_harness.golden_scenario`
        # (golden_scenario.execute_verb), same convention as power-intent above.
        # Exit codes: 0 recorded / all FRESH, 1 at least one STALE, 2 UNKNOWN or
        # nothing recorded -- an uncheckable capsule must never exit 0.
        from . import golden_scenario as _gsc
        _gs_versions = None
        if args.gs_vip_versions:
            _gs_versions = {}
            for _item in args.gs_vip_versions:
                if "=" not in _item:
                    print(f"--vip-version expects TOOL=VERSION, got {_item!r}")
                    raise SystemExit(2)
                _tool, _ver = _item.split("=", 1)
                _gs_versions[_tool.strip()] = _ver.strip()
        try:
            _gs_text, _gs_code = _gsc.execute_verb(
                args.gs_verb, root=h.root, db_path=args.db, json_file=args.json_file,
                capsule_id=args.capsule_id, head=args.head, as_json=args.json,
                current_vip_versions=_gs_versions)
        except _gsc.GoldenScenarioError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_gs_text)
        if _gs_code:
            raise SystemExit(_gs_code)
    elif args.cmd == "global-status-ready-gate":
        # One shared implementation with `python -m dv_harness.global_status_ready_gate`
        # (global_status_ready_gate.execute_verb), same convention as golden-scenario
        # above. This gate reads an already-assembled HarnessStatusIR document from
        # disk (its to_dict() JSON) -- it assembles nothing itself; nothing in this
        # repo yet builds a real HarnessStatusIR for it to be handed (see the
        # HarnessStatusIR CLAUDE.md section: this is the front door to a REACHED
        # capability, not yet a WIRED one). Exit codes: 0 GLOBAL_STATUS_READY,
        # 1 NOT_READY, 2 INCOMPLETE_EVIDENCE / a document that could not be read.
        from . import global_status_ready_gate as _gsrg
        try:
            _gsrg_text, _gsrg_code = _gsrg.execute_verb(
                args.document, as_json=args.gsrg_as_json)
        except (_gsrg.GlobalStatusReadyGateError, _gsrg.hsi.HarnessStatusIRError,
                OSError, json.JSONDecodeError) as e:
            print(f"ERROR: {e}")
            raise SystemExit(2)
        print(_gsrg_text)
        if _gsrg_code:
            raise SystemExit(_gsrg_code)
    elif args.cmd == "plan-quality-feedback":
        # One shared implementation with `python -m dv_harness.plan_quality_feedback`
        # (plan_quality_feedback.execute_verb), same convention as golden-scenario
        # above. Exit codes: 0 available, 2 NOT_AVAILABLE (no section-108 loop
        # telemetry recorded for this project -- never a fabricated clean matrix).
        from . import plan_quality_feedback as _pqf
        _pqf_code, _pqf_payload = _pqf.execute_verb(
            h.root, args.pqf_verb, run_id=args.run_id, as_json=args.json)
        if args.json:
            print(json.dumps(_pqf_payload, indent=2, ensure_ascii=False, default=str))
        else:
            print(_pqf_payload)
        if _pqf_code:
            raise SystemExit(_pqf_code)
    elif args.cmd == "vip-version-drift-detection":
        # One shared implementation with
        # `python -m dv_harness.vip_version_drift_detection`
        # (vip_version_drift_detection.execute_verb), same convention as
        # power-intent/golden-scenario above. That module's own execute_verb
        # takes and parses a raw argv list itself, so this dispatch just
        # rebuilds one from the already-parsed cli.py args and hands it
        # through unmodified -- no drift logic is reimplemented here. Exit
        # codes (module's own docstring): 0 STATUS_NO_DRIFT, 1
        # STATUS_DRIFT_DETECTED, 2 STATUS_INCOMPLETE_EVIDENCE /
        # STATUS_NOT_AVAILABLE / a usage error.
        from . import vip_version_drift_detection as _vvd
        _vvd_argv = ["--root", args.root]
        if args.manifests:
            _vvd_argv += ["--manifests", args.manifests]
        if args.json:
            _vvd_argv += ["--json"]
        _vvd_code = _vvd.execute_verb(_vvd_argv)
        if _vvd_code:
            raise SystemExit(_vvd_code)
    elif args.cmd == "design-completeness-gate":
        # One shared implementation with
        # `python -m dv_harness.design_completeness_gate` (design_completeness_gate.execute),
        # same convention as golden-scenario/power-intent above. Exit codes: 0 every declared
        # Design Intelligence extraction category is READY, 2 otherwise (PARTIAL/BLOCKED/UNKNOWN
        # anywhere in the matrix) -- never a silent pass on an incomplete intake.
        from . import design_completeness_gate as _dcg
        try:
            _dcg_text, _dcg_code = _dcg.execute(args.inputs, as_json=args.json)
        except _dcg.DesignCompletenessError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_dcg_text)
        if _dcg_code:
            raise SystemExit(_dcg_code)
    elif args.cmd == "scenario-pattern-command-txt-correspondence":
        # One shared implementation with
        # `python -m dv_harness.scenario_pattern_command_txt_correspondence`
        # (execute_verb), same convention as golden-scenario above. Exit
        # codes: 0 every branch_b* usage corresponds and every declared
        # pattern is used, 1 at least one real CORRESPONDENCE_NOT_FOUND or
        # NOT_USED_IN_COMMAND_TXT finding, 2 NOT_AVAILABLE (no scenario-
        # pattern records, no command files, or none could be read -- never
        # a silent pass).
        from . import scenario_pattern_command_txt_correspondence as _spc
        try:
            _spc_text, _spc_code = _spc.execute_verb(
                args.capability_report, args.spc_command_files or [],
                as_json=args.json, out_dir=args.out_dir)
        except (_spc.ScenarioPatternCommandTxtCorrespondenceError, json.JSONDecodeError) as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_spc_text)
        if _spc_code:
            raise SystemExit(_spc_code)
    elif args.cmd == "vip-api-check":
        # One shared implementation with `python -m dv_harness.vip_api_card`
        # (vip_api_card.execute_verb), same convention as power-intent /
        # golden-scenario above. Exit codes: 0 every VIP API citation PROVEN at
        # a real file:line, 1 at least one BLOCKED (unprovable API the
        # generator must not emit), 2 nothing real to check (NOT_AVAILABLE --
        # never a pass), 3 UNPROVABLE citations only, which is reported but
        # non-fatal unless --strict-unprovable is given.
        from . import vip_api_card as _vac
        try:
            _va_text, _va_code = _vac.execute_verb(
                args.va_sources, args.va_index, relative_to=args.va_relative_to,
                as_json=args.json, out_dir=args.va_out_dir)
        except _vac.VipApiValidationError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_va_text)
        if _va_code == 3 and not args.va_strict:
            _va_code = 0
        if _va_code:
            raise SystemExit(_va_code)
    elif args.cmd == "config-variants":
        # One shared implementation with
        # `python -m dv_harness.config_variant_coverage`
        # (config_variant_coverage.execute_verb), same convention as
        # power-intent / golden-scenario above. Exit codes: 0 full t-way
        # coverage, 1 a real coverage finding (an uncovered interaction, an
        # illegal/incomplete configuration, a missing declared critical
        # combination), 2 a broken config-space declaration or usage error.
        from . import config_variant_coverage as _cvc
        try:
            _cv_text, _cv_code = _cvc.execute_verb(
                args.cv_verb, root=h.root, space_path=args.space, strength=args.strength,
                combinations_path=args.combinations, out_path=args.out, as_json=args.json)
        except _cvc.ConfigSpaceError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_cv_text)
        if _cv_code:
            raise SystemExit(_cv_code)
    elif args.cmd == "supply-chain":
        # One shared implementation with
        # `python -m dv_harness.dependency_supply_chain`
        # (dependency_supply_chain.execute_verb), same convention as
        # config-variants / power-intent above. Exit codes: 0 POLICY_CLEAN,
        # 1 a real policy finding (unpinned dependency, declared-but-not-
        # installed, an installed version outside its declared range, a known
        # advisory hit), 2 a check that could not run -- above all the
        # vulnerability check with no real offline advisory source, which is
        # NOT_FULLY_CHECKED and deliberately never exits 0.
        from . import dependency_supply_chain as _dsc
        try:
            _sc_text, _sc_code = _dsc.execute_verb(
                args.sc_verb, root=h.root, designware_home=args.designware_home,
                include_vip=not args.no_vip, policy_path=args.policy,
                advisory_db_path=args.advisory_db, as_json=args.json)
        except _dsc.SupplyChainError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_sc_text)
        if _sc_code:
            raise SystemExit(_sc_code)
    elif args.cmd == "benchmark-dataset":
        # One shared implementation with `python -m dv_harness.benchmark_dataset`
        # (benchmark_dataset.execute_verb), same convention as golden-scenario
        # above. Exit codes: 0 fine, 1 a real finding (content drift, leakage
        # present, a recorded eval run that was not met), 2 nothing to report or
        # a usage error.
        from . import benchmark_dataset as _bd
        try:
            _bd_text, _bd_code = _bd.execute_verb(
                args.bd_verb, root=h.root, dataset_id=args.dataset_id,
                json_file=args.json_file, version=args.bd_version,
                old_version=args.old_version, new_version=args.new_version,
                case_id=args.case_id, subject_id=args.subject_id,
                subject_version=args.subject_version, used_for=args.used_for,
                as_json=args.json)
        except _bd.BenchmarkDatasetError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_bd_text)
        if _bd_code:
            raise SystemExit(_bd_code)
    elif args.cmd == "system-smoke-proof":
        # One shared implementation with `python -m dv_harness.system_build_proof`
        # (system_build_proof.execute_verb), same convention as power-intent /
        # golden-scenario / benchmark-dataset above. Exit codes: 0 SYSTEM_READY,
        # 1 SMOKE_FAIL, 2 SMOKE_NOT_PROVEN or a merge check that could not run --
        # anything short of proven never exits 0 (GF-AT-28).
        from . import system_build_proof as _sbp
        from .verible_parser import DEFAULT_VERIBLE_BIN as _SBP_VERIBLE
        _sbp_text, _sbp_code = _sbp.execute_verb(
            h.root, subsystems=args.sbp_subsystems, composed_dir=args.composed_dir,
            filelist_paths=args.sbp_filelists, top_module=args.top_module,
            merge_only=args.merge_only, evidence_db_path=args.db,
            system_job_id=args.system_job_id, fsdb_path=args.fsdb,
            as_json=args.json, verible_bin=args.verible_bin or _SBP_VERIBLE)
        print(_sbp_text)
        if _sbp_code:
            raise SystemExit(_sbp_code)
    elif args.cmd == "coord":
        # One shared implementation with
        # `python -m dv_harness.multi_user_coordination`
        # (multi_user_coordination.execute_verb), same convention as
        # power-intent / golden-scenario / system-smoke-proof above. Exit codes:
        # 0 CLEAR (or reservation made), 1 CONFLICTS_DETECTED (or a refused
        # reservation), 2 UNKNOWN / malformed request -- "we could not check"
        # never exits 0. DETECTION ONLY: no lock is taken, no job is cancelled,
        # no claim is revoked and no approval gate is consulted or weakened.
        from . import multi_user_coordination as _muc
        _muc_text, _muc_code = _muc.execute_verb(
            args.coord_verb, root=h.root, sessions=args.coord_sessions,
            resource=args.resource, kind=args.coord_kind, agent=args.coord_agent,
            task_id=args.coord_task, mode=args.coord_mode, as_json=args.json)
        print(_muc_text)
        if _muc_code:
            raise SystemExit(_muc_code)
    elif args.cmd == "env-manifest":
        from . import env_manifest
        from .env_manifest import (EnvManifestValidationError, RegisterMapValidationError,
                                    SocArchMapValidationError, TestplanSourcesValidationError,
                                    GenerationProvenanceIncompleteError, InputIrDeclarationError)
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
                    generated_by=args.generated_by,
                    project_root=args.provenance_project_root,
                    input_requirements_path=args.input_requirements_path,
                    input_requirement_id=args.input_requirement_id,
                    input_file_path=args.input_file_path,
                    require_provenance=args.require_provenance,
                )
            except (EnvManifestValidationError, RegisterMapValidationError,
                    SocArchMapValidationError, TestplanSourcesValidationError,
                    UserGuideDistillError, GenerationProvenanceIncompleteError,
                    InputIrDeclarationError,
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
    elif args.cmd == "doc-extract":
        # The DISPATCH layer over the individual extractors above, not a
        # replacement for any of them: every category's work is done by the
        # same real module its own single-purpose verb calls.
        from . import doc_extraction_fanout
        from .doc_extraction_fanout import DocExtractionFanoutError
        try:
            code = doc_extraction_fanout.execute_verb(args)
        except DocExtractionFanoutError as exc:
            print(f"doc-extract {args.dx_cmd} FAILED: {exc}", file=sys.stderr)
            raise SystemExit(2)
        if code:
            raise SystemExit(code)
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
    elif args.cmd == "platform-health":
        # One shared implementation with `python -m dv_harness.platform_health`
        # (platform_health.execute), same convention as trend/loop-contract
        # above. h.cfg is this session's already-loaded config, so a project's
        # own SLO targets in config.json's `platform_health` block are honoured
        # without this reading config a second time.
        from . import platform_health as _ph
        _ph_code, _ph_report, _ph_text = _ph.execute(
            h.root, cfg=h.cfg, as_json=args.json, window_days=args.window_days)
        print(json.dumps(_ph_report, ensure_ascii=False, indent=2)
              if args.json else _ph_text)
        raise SystemExit(_ph_code)
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
    elif args.cmd == "source-authority-order-validation":
        # One shared implementation with
        # `python -m dv_harness.source_authority_order_validation` (execute_verb(argv)).
        # Exit codes: 0 the fixed 9-level order matches real practice, 1
        # ORDER_DIVERGES_FROM_PRACTICE, 2 NO_EVALUABLE_CASES.
        from . import source_authority_order_validation as _saov
        _saov_argv = ["--root", str(h.root)]
        if args.json:
            _saov_argv.append("--json")
        raise SystemExit(_saov.execute_verb(_saov_argv))
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
    elif args.cmd == "system-phase1-report":
        from . import system_phase1_report as spr
        from . import system_readiness as sr
        kc_client = None
        if args.phase1_kc:
            from .config import load_config
            from .knowledge_center import KnowledgeCenterClient
            kc_client = KnowledgeCenterClient(load_config(h.root), h.root)
        question_store = None
        if args.phase1_escalate:
            from . import question_queue
            question_store = question_queue.QuestionQueueStore(h.root)
        result = spr.produce_phase1_report(
            h.root, args.select or [], knowledge_center_client=kc_client,
            inventory_overlay_path=args.command_inventory,
            question_store=question_store, head_rev=args.head_rev)
        if args.phase1_write_pin:
            sr.write_composition_pin(h.root, result["version_pin"])
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(result["phase1_report_text"])
            if args.phase1_write_pin:
                print(f"\nSYS-35 composition snapshot appended to "
                      f"{sr.pin_path(h.root)}")
        # Exit 2 unless the selection was admissible AND SYS-37 derived READY.
        # PARTIAL/BLOCKED/UNKNOWN each mean a human still has something to
        # decide, and a CI step must not read any of them as a clean run. This
        # exit code is NOT an approval signal in either direction: SYS-39 stops
        # for an explicit human decision whatever it returns.
        raise SystemExit(
            0 if (result["selection"]["selection_admissible"]
                  and result["system_readiness"]["system_readiness"] == sr.READY)
            else 2)
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
    elif args.cmd == "cross-project":
        from . import cross_project_mining as cpm

        if args.xproj_cmd == "register":
            try:
                entry = cpm.ProjectRegistry(h.root).register(args.root, project_id=args.xproj_id)
            except cpm.CrossProjectRegistryError as exc:
                # Including ProjectIdentityCollisionError -- refusing a second
                # "project" that is really one store under two names is a
                # normal, expected outcome to report, not a crash.
                print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 1
            print(json.dumps({"ok": True, "registered": entry}, ensure_ascii=False, indent=2))
            return 0
        if args.xproj_cmd == "unregister":
            removed = cpm.ProjectRegistry(h.root).unregister(args.project_id)
            print(json.dumps({"ok": removed, "project_id": args.project_id}, ensure_ascii=False, indent=2))
            return 0 if removed else 1
        if args.xproj_cmd == "list":
            print(json.dumps({"projects": cpm.ProjectRegistry(h.root).entries()},
                             ensure_ascii=False, indent=2))
            return 0
        if args.xproj_cmd == "status":
            print(json.dumps(cpm.production_status(h.root), ensure_ascii=False, indent=2))
            return 0
        if args.xproj_cmd == "mine":
            kwargs = ({} if args.xproj_min_projects is None
                      else {"min_projects": args.xproj_min_projects})
            try:
                report = cpm.mine_registered_projects(h.root, **kwargs)
            except (ValueError, cpm.CrossProjectRegistryError) as exc:
                print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(report, ensure_ascii=False, indent=2))
            # Exit 0 for a completed pass whatever it found: INSUFFICIENT_PROJECTS
            # is an honest answer about the sample, not a failure of the command.
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
    elif args.cmd == "harness-deploy":
        # One shared implementation with `python -m dv_harness.harness_deploy`
        # (harness_deploy.execute_verb) -- two CLI handlers orchestrating the
        # same behavior is the parallel-mechanism defect this project forbids,
        # just at CLI scale. `store=h.store` reuses this session's already-open
        # StateStore so the HARNESS_DEPLOY_SYNC event lands in the same
        # events.jsonl `dv-harness audit` reads.
        from . import harness_deploy as _hd
        _hd_code, _hd_payload = _hd.execute_verb(
            h.root, args.hd_verb,
            target_root=getattr(args, "target_root", None),
            remote_md5sum_transcript=getattr(args, "remote_md5sum_transcript", None),
            assume_remote_empty=getattr(args, "assume_remote_empty", False),
            remote_root=args.remote_root,
            execute=getattr(args, "execute", False),
            print_md5sum_command=getattr(args, "print_md5sum_command", False),
            strict_line_endings=getattr(args, "strict_line_endings", False),
            store=h.store)
        print(json.dumps(_hd_payload, ensure_ascii=False, indent=2))
        raise SystemExit(_hd_code)
    elif args.cmd == "loop-contract":
        # One shared implementation with `python -m dv_harness.loop_contract`
        # (loop_contract.execute_verb), same convention as harness-deploy above.
        # h.cfg is this session's already-loaded config, so the contract's
        # budgets report what THIS project actually enforces, not the defaults.
        from . import loop_contract as _lc
        _lc_code, _lc_payload = _lc.execute_verb(
            h.root, args.lc_verb,
            loop_id=getattr(args, "loop_id", None),
            cfg=h.cfg,
            fmt=getattr(args, "lc_format", "json"))
        if getattr(args, "lc_format", "json") == "yaml" and "yaml" in _lc_payload:
            print(_lc_payload["yaml"])
        else:
            print(json.dumps(_lc_payload, ensure_ascii=False, indent=2))
        raise SystemExit(_lc_code)
    elif args.cmd == "loop-budget":
        # One shared implementation with `python -m dv_harness.loop_budget`
        # (loop_budget.execute_verb), same convention as loop-contract above.
        # h.cfg is this session's already-loaded config, so `dimensions`
        # reports what THIS project's policy really enforces.
        from . import loop_budget as _lb
        _lb_code, _lb_payload = _lb.execute_verb(
            h.root, args.lb_verb, cfg=h.cfg,
            dimension=getattr(args, "dimension", None),
            reason=getattr(args, "reason", "") or "",
            by=getattr(args, "by", "") or "",
            text=getattr(args, "text", "") or "")
        print(json.dumps(_lb_payload, ensure_ascii=False, indent=2))
        raise SystemExit(_lb_code)
    elif args.cmd == "golden-flow-readiness":
        # One shared implementation with `python -m dv_harness.golden_flow_readiness`
        # (golden_flow_readiness.execute), same convention as loop-contract above.
        # h.cfg is this session's already-loaded config, so the rows that consult
        # policy read what THIS project enforces rather than the defaults.
        from . import golden_flow_readiness as _gfr
        _gfr_code, _gfr_matrix, _gfr_text = _gfr.execute(
            h.root, cfg=h.cfg, as_json=args.json)
        print(json.dumps(_gfr_matrix, ensure_ascii=False, indent=2)
              if args.json else _gfr_text)
        raise SystemExit(_gfr_code)
    elif args.cmd == "generation-readiness":
        # One shared implementation with `python -m dv_harness.generation_readiness`
        # (generation_readiness.execute), same convention as golden-flow-readiness
        # above. h.cfg is this session's already-loaded config.
        from . import generation_readiness as _genr
        _genr_code, _genr_matrix, _genr_text = _genr.execute(
            h.root, cfg=h.cfg, as_json=args.json, deep=not args.no_deep)
        print(json.dumps(_genr_matrix, ensure_ascii=False, indent=2)
              if args.json else _genr_text)
        raise SystemExit(_genr_code)
    elif args.cmd == "verification-strategy":
        # One shared implementation with `python -m dv_harness.verification_strategy`
        # (verification_strategy.execute_verb), same convention as loop-contract
        # above. h.cfg is this session's already-loaded config, so the throughput
        # and multi-subsystem thresholds are what THIS project set, not defaults.
        from . import verification_strategy as _vs
        _vs_code, _vs_payload, _vs_text = _vs.execute_verb(
            h.root, args.vs_verb, cfg=h.cfg,
            goal=getattr(args, "goal", "") or "",
            scope=getattr(args, "scope", "UNDECLARED") or "UNDECLARED",
            protocol=getattr(args, "protocol", None),
            holes_path=getattr(args, "holes", None))
        print(json.dumps(_vs_payload, ensure_ascii=False, indent=2)
              if (getattr(args, "json", False) or not _vs_text) else _vs_text)
        raise SystemExit(_vs_code)
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
    elif args.cmd == "agent-checkpoint-check":
        # One shared implementation with `python -m
        # dv_harness.agent_checkpoint_check` -- same real
        # check_resume_state_artifact() the module's own CLI calls. Exit 0
        # RESUME_ARTIFACT_CURRENT, 1 missing/incomplete/stale.
        import json as _acc_json
        from . import agent_checkpoint_check as _acc
        _acc_kwargs = {}
        if args.stale_threshold_hours is not None:
            _acc_kwargs["stale_threshold_seconds"] = int(args.stale_threshold_hours * 3600)
        _acc_result = _acc.check_resume_state_artifact(args.build_tree, **_acc_kwargs)
        print(_acc_json.dumps(_acc_result.to_dict(), indent=2, default=str))
        raise SystemExit(0 if _acc_result.ok else 1)
    elif args.cmd == "agent-parallelism-policy":
        # One shared implementation with `python -m
        # dv_harness.agent_parallelism_policy` (execute_verb), same convention
        # as power-intent above.
        import json as _app_json
        from . import agent_parallelism_policy as _app
        _app_code, _app_payload = _app.execute_verb(
            h.root, args.app_verb, policy_path=args.policy_path,
            requests_path=args.requests, resource_name=args.resource_name,
            queue=args.queue)
        print(_app_json.dumps(_app_payload, ensure_ascii=False, indent=2, default=str))
        if _app_code:
            raise SystemExit(_app_code)
    elif args.cmd == "amba-functional-coverage-ir":
        # One shared implementation with `python -m
        # dv_harness.amba_functional_coverage_ir` (execute_verb(argv)); that
        # module's own front door does its own argparse, so this passes the
        # equivalent argv straight through -- same real implementation.
        from . import amba_functional_coverage_ir as _afc
        _afc_argv = ["build", "--facts", args.facts]
        if args.json:
            _afc_argv.append("--json")
        raise SystemExit(_afc.execute_verb(_afc_argv))
    elif args.cmd == "amba-performance-readiness-gates":
        from . import amba_performance_readiness_gates as _aprg
        _aprg_argv = [args.aprg_verb]
        if args.aprg_verb == "conditions":
            if args.gate:
                _aprg_argv += ["--gate", args.gate]
        elif args.aprg_verb == "evaluate":
            if args.conditions:
                _aprg_argv += ["--conditions", args.conditions]
            if args.not_applicable:
                _aprg_argv += ["--not-applicable", args.not_applicable]
        if args.json:
            _aprg_argv.append("--json")
        raise SystemExit(_aprg.execute_verb(_aprg_argv))
    elif args.cmd == "amba-readiness-gates":
        from . import amba_readiness_gates as _arg
        _arg_argv = [args.arg_verb]
        if args.arg_verb == "conditions":
            if args.gate:
                _arg_argv += ["--gate", args.gate]
        elif args.arg_verb == "evaluate":
            if args.conditions:
                _arg_argv += ["--conditions", args.conditions]
        if args.json:
            _arg_argv.append("--json")
        raise SystemExit(_arg.execute_verb(_arg_argv))
    elif args.cmd == "arbitration-policy-ir":
        # One shared implementation with `python -m
        # dv_harness.arbitration_policy_ir` (main(argv)).
        from . import arbitration_policy_ir as _api
        _api_argv = []
        if args.evidence_file:
            _api_argv += ["--evidence-file", args.evidence_file]
        if args.request_pattern_file:
            _api_argv += ["--request-pattern-file", args.request_pattern_file]
        if args.fabric_name:
            _api_argv += ["--fabric-name", args.fabric_name]
        if args.component_name:
            _api_argv += ["--component-name", args.component_name]
        if args.json:
            _api_argv.append("--json")
        raise SystemExit(_api.main(_api_argv))
    elif args.cmd == "artifact-completeness":
        # One shared implementation with `python -m
        # dv_harness.artifact_completeness` (execute_verb(argv)).
        from . import artifact_completeness as _afcm
        _afcm_argv = [args.category]
        if args.subfact_inventory:
            _afcm_argv.append(args.subfact_inventory)
        _afcm_code, _afcm_report, _afcm_text = _afcm.execute_verb(_afcm_argv)
        print(_afcm_text)
        if _afcm_code:
            raise SystemExit(_afcm_code)
    elif args.cmd == "artifact-relationship-discovery":
        # One shared implementation with `python -m
        # dv_harness.artifact_relationship_discovery` (main(argv)).
        from . import artifact_relationship_discovery as _ard
        _ard_argv = ["--sources", args.sources]
        if args.json:
            _ard_argv.append("--json")
        raise SystemExit(_ard.main(_ard_argv))
    elif args.cmd == "backpressure-model":
        # One shared implementation with `python -m
        # dv_harness.backpressure_model` (main(argv)).
        from . import backpressure_model as _bpm
        _bpm_argv = []
        if args.evidence_file:
            _bpm_argv += ["--evidence-file", args.evidence_file]
        if args.observed_stalls_file:
            _bpm_argv += ["--observed-stalls-file", args.observed_stalls_file]
        if args.json:
            _bpm_argv.append("--json")
        raise SystemExit(_bpm.main(_bpm_argv))
    elif args.cmd == "bounded-self-healing":
        # One shared implementation with `python -m
        # dv_harness.bounded_self_healing` (execute_verb); approval itself
        # still goes through the real, existing `dv-harness approve` verb.
        import json as _bsh_json
        from . import bounded_self_healing as _bsh
        _bsh_code, _bsh_payload = _bsh.execute_verb(
            h.root, args.bsh_verb, text=args.text, stage=args.stage)
        print(_bsh_json.dumps(_bsh_payload, ensure_ascii=False, indent=2, default=str))
        if _bsh_code:
            raise SystemExit(_bsh_code)
    elif args.cmd == "branch-ownership-resolver":
        # One shared implementation with `python -m
        # dv_harness.branch_ownership_resolver` (execute_verb).
        import json as _bor_json
        from . import branch_ownership_resolver as _bor
        _bor_code, _bor_result = _bor.execute_verb(args.bor_verb, payload_path=args.payload)
        print(_bor_json.dumps(_bor_result, indent=2, sort_keys=True, default=str))
        if _bor_code:
            raise SystemExit(_bor_code)
    elif args.cmd == "change-cascade":
        # One shared implementation with `python -m dv_harness.change_cascade`
        # (execute_verb) -- that module's own docstring already names this
        # exact `dv-harness change-cascade <verb>` convention.
        from . import change_cascade as _cc
        _cc_text, _cc_code = _cc.execute_verb(
            args.cc_verb, root=h.root, changed_field=args.changed_field,
            changes_json_file=args.changes_file, question_keys=args.question_keys,
            revoked_by=args.revoked_by, as_json=args.json)
        print(_cc_text)
        if _cc_code:
            raise SystemExit(_cc_code)
    elif args.cmd == "checker-sb-qualification":
        # One shared implementation with `python -m
        # dv_harness.checker_sb_qualification` (execute_verb).
        from . import checker_sb_qualification as _csq
        raise SystemExit(_csq.execute_verb(
            args.csq_verb, trials_path=args.csq_trials_path, required=args.required,
            as_json=args.csq_as_json))
    elif args.cmd == "coherency-capability-ir":
        # One shared implementation with `python -m
        # dv_harness.coherency_capability_ir` (execute_verb(args)); that
        # module's execute_verb takes an argparse.Namespace, so a matching one
        # is built here from this parser's own values.
        import argparse as _cci_argparse
        from . import coherency_capability_ir as _cci
        _cci_ns = _cci_argparse.Namespace(evidence=args.evidence, json=args.json)
        _cci_code, _cci_ir, _cci_text = _cci.execute_verb(_cci_ns)
        print(_cci_text)
        if _cci_code:
            raise SystemExit(_cci_code)
    elif args.cmd == "command-precondition-gate":
        # One shared implementation with `python -m
        # dv_harness.command_precondition_gate` (main(argv)).
        from . import command_precondition_gate as _cpg
        _cpg_argv = [args.cpg_verb, "--commands", args.commands, "--root", str(h.root)]
        if args.registry:
            _cpg_argv += ["--registry", args.registry]
        if args.out:
            _cpg_argv += ["--out", args.out]
        if args.json:
            _cpg_argv.append("--json")
        raise SystemExit(_cpg.main(_cpg_argv))
    elif args.cmd == "command-task-trace":
        # One shared implementation with `python -m
        # dv_harness.command_task_trace` (main(argv), execute_verb aliased to
        # main).
        from . import command_task_trace as _ctt
        _ctt_argv = ["--env-dir", args.env_dir]
        for _c in args.ctt_commands:
            _ctt_argv += ["--command", _c]
        for _p in (args.ctt_vip_prefixes or []):
            _ctt_argv += ["--vip-prefix", _p]
        if args.no_verible:
            _ctt_argv.append("--no-verible")
        if args.verible_bin:
            _ctt_argv += ["--verible-bin", args.verible_bin]
        if args.json:
            _ctt_argv.append("--json")
        raise SystemExit(_ctt.main(_ctt_argv))
    elif args.cmd == "command-txt-change-impact":
        # One shared implementation with `python -m
        # dv_harness.command_txt_change_impact` (main(argv)).
        from . import command_txt_change_impact as _ctci
        _ctci_argv = ["--old", args.old, "--new", args.new]
        if args.json:
            _ctci_argv.append("--json")
        raise SystemExit(_ctci.main(_ctci_argv))
    elif args.cmd == "confidence-calibration":
        # One shared implementation with `python -m
        # dv_harness.confidence_calibration` (main(argv)).
        from . import confidence_calibration as _cconf
        _cconf_argv = [args.cal_verb, "--project-root", str(h.root)]
        if args.json:
            _cconf_argv.append("--json")
        raise SystemExit(_cconf.main(_cconf_argv))
    elif args.cmd == "connectivity-check":
        # One shared implementation with `python -m
        # dv_harness.connectivity_check` (main(argv)).
        from . import connectivity_check as _connchk
        _connchk_argv = ["--project-root", str(h.root)]
        if args.config:
            _connchk_argv += ["--config", args.config]
        if args.state:
            _connchk_argv += ["--state", args.state]
        if args.report:
            _connchk_argv += ["--report", args.report]
        if args.check_only:
            _connchk_argv.append("--check-only")
        raise SystemExit(_connchk.main(_connchk_argv))
    elif args.cmd == "consolidated-kpi-benchmark":
        # One shared implementation with `python -m
        # dv_harness.consolidated_kpi_benchmark` (main(argv)).
        from . import consolidated_kpi_benchmark as _ckb
        _ckb_argv = [args.ckb_verb, "--project-root", str(h.root)]
        if args.json:
            _ckb_argv.append("--json")
        raise SystemExit(_ckb.main(_ckb_argv))
    elif args.cmd == "context-budget":
        # One shared implementation with `python -m dv_harness.context_budget`
        # (main(argv)).
        from . import context_budget as _cbud
        if args.cb_verb == "hook":
            raise SystemExit(_cbud.main(["hook"]))
        elif args.cb_verb == "session-start":
            raise SystemExit(_cbud.main(["session-start", "--root", str(h.root)]))
        elif args.cb_verb == "classify":
            _cbud_argv = ["classify"]
            if args.command:
                _cbud_argv += ["--command", args.command]
            elif args.target:
                _cbud_argv.append(args.target)
            raise SystemExit(_cbud.main(_cbud_argv))
        else:
            _cbud_argv = ["resident", "--root", str(h.root)]
            if args.json:
                _cbud_argv.append("--json")
            raise SystemExit(_cbud.main(_cbud_argv))
    elif args.cmd == "coverage-closure-action-utility":
        # One shared implementation with `python -m
        # dv_harness.coverage_closure_action_utility` (main(argv)).
        from . import coverage_closure_action_utility as _ccau
        _ccau_argv = ["--candidates-file", args.candidates_file]
        if args.json:
            _ccau_argv.append("--json")
        raise SystemExit(_ccau.main(_ccau_argv))
    elif args.cmd == "coverage-closure-hole-correlation":
        # One shared implementation with `python -m
        # dv_harness.coverage_closure_hole_correlation` (main(argv)).
        from . import coverage_closure_hole_correlation as _cchc
        _cchc_argv = ["--root", str(h.root), "--holes-file", args.holes_file,
                      "--candidates-file", args.cchc_candidates_file]
        if args.closes_holes_field:
            _cchc_argv += ["--closes-holes-field", args.closes_holes_field]
        if args.parsed_summary_file:
            _cchc_argv += ["--parsed-summary-file", args.parsed_summary_file]
        if args.json:
            _cchc_argv.append("--json")
        raise SystemExit(_cchc.main(_cchc_argv))
    elif args.cmd == "coverage-db-integrity":
        # One shared implementation with `python -m
        # dv_harness.coverage_db_integrity` (execute_verb(argv)).
        from . import coverage_db_integrity as _cdi
        if args.cdi_verb == "fingerprint":
            raise SystemExit(_cdi.execute_verb(["fingerprint", "--db-path", args.db_path]))
        else:
            raise SystemExit(_cdi.execute_verb(["check", "--merge-request", args.merge_request]))
    elif args.cmd == "de-command-runtime-readiness-gate":
        # One shared implementation with `python -m
        # dv_harness.de_command_runtime_readiness_gate` (main(argv)).
        from . import de_command_runtime_readiness_gate as _dcrr
        _dcrr_argv = [args.dcrr_verb, "--registry", args.dcrr_registry, "--root", str(h.root)]
        if args.dcrr_commands:
            _dcrr_argv += ["--commands", args.dcrr_commands]
        if args.branch_grammar:
            _dcrr_argv += ["--branch-grammar", args.branch_grammar]
        if args.dcrr_out:
            _dcrr_argv += ["--out", args.dcrr_out]
        if args.json:
            _dcrr_argv.append("--json")
        raise SystemExit(_dcrr.main(_dcrr_argv))
    elif args.cmd == "dependency-qualification":
        # One shared implementation with `python -m
        # dv_harness.dependency_qualification` (main(argv)).
        from . import dependency_qualification as _dq
        _dq_argv = [args.dq_verb, "--root", str(h.root)]
        if args.inventory:
            _dq_argv += ["--inventory", args.inventory]
        if args.record_file:
            _dq_argv += ["--record-file", args.record_file]
        if args.qualification_id:
            _dq_argv += ["--qualification-id", args.qualification_id]
        if args.revoked_by:
            _dq_argv += ["--revoked-by", args.revoked_by]
        if args.reason:
            _dq_argv += ["--reason", args.reason]
        if args.json:
            _dq_argv.append("--json")
        raise SystemExit(_dq.main(_dq_argv))
    elif args.cmd == "design-architecture-ir":
        # One shared implementation with `python -m
        # dv_harness.design_architecture_ir` (main(argv)).
        from . import design_architecture_ir as _dai
        _dai_argv = []
        for _r in args.dai_rtl_files:
            _dai_argv += ["--rtl", _r]
        if args.top_module:
            _dai_argv += ["--top-module", args.top_module]
        if args.verible_bin:
            _dai_argv += ["--verible-bin", args.verible_bin]
        if args.out:
            _dai_argv += ["--out", args.out]
        if args.json:
            _dai_argv.append("--json")
        raise SystemExit(_dai.main(_dai_argv))
    elif args.cmd == "design-knowledge-correlation":
        # One shared implementation with `python -m
        # dv_harness.design_knowledge_correlation` (execute_verb(argv)).
        from . import design_knowledge_correlation as _dkc
        _dkc_argv = ["--sources", args.sources]
        if args.expected_facts:
            _dkc_argv += ["--expected-facts", args.expected_facts]
        if args.json:
            _dkc_argv.append("--json")
        raise SystemExit(_dkc.execute_verb(_dkc_argv))
    elif args.cmd == "digital-thread":
        # One shared implementation with `python -m
        # dv_harness.digital_thread_traceability` (main(argv)).
        from . import digital_thread_traceability as _dtt
        _dtt_argv = ["--root", str(h.root)]
        if args.vplan_file:
            _dtt_argv += ["--vplan-file", args.vplan_file]
        if args.env_manifest:
            _dtt_argv += ["--env-manifest", args.env_manifest]
        if args.db_path:
            _dtt_argv += ["--db-path", args.db_path]
        if args.json:
            _dtt_argv.append("--json")
        raise SystemExit(_dtt.main(_dtt_argv))
    elif args.cmd == "doc-citation-check":
        # One shared implementation with `python -m dv_harness.doc_citation_check`
        # (main(argv)) -- that module's own argv is a bare list of doc paths
        # (or `--memory-docs`), not a real argparse tree, so this dispatch
        # reconstructs that exact shape rather than a parsed-flags call.
        from . import doc_citation_check as _dcc
        _dcc_argv = list(args.docs)
        if args.memory_docs:
            _dcc_argv.append("--memory-docs")
        raise SystemExit(_dcc.main(_dcc_argv))
    elif args.cmd == "dut-evidence-correlation":
        # One shared implementation with `python -m
        # dv_harness.dut_evidence_correlation` (execute_verb(argv), that
        # module's own argv-taking front door).
        from . import dut_evidence_correlation as _dec
        _dec_argv = ["--manifest", args.manifest, "--items", args.items]
        if args.json:
            _dec_argv.append("--json")
        raise SystemExit(_dec.execute_verb(_dec_argv))
    elif args.cmd == "dynamic-connectivity":
        # One shared implementation with `python -m dv_harness.dynamic_connectivity_ir`
        # (main(argv)).
        from . import dynamic_connectivity_ir as _dci
        if args.dci_verb == "statuses":
            raise SystemExit(_dci.main(["statuses"]))
        _dci_argv = ["classify", "--paths", args.paths]
        if args.json:
            _dci_argv.append("--json")
        raise SystemExit(_dci.main(_dci_argv))
    elif args.cmd == "dynamic-intake-graph":
        # One shared implementation with `python -m dv_harness.dynamic_intake_graph`
        # (main(argv)).
        from . import dynamic_intake_graph as _dig
        _dig_argv = ["--intake-state", args.intake_state]
        if args.relationships:
            _dig_argv += ["--relationships", args.relationships]
        if args.json:
            _dig_argv.append("--json")
        raise SystemExit(_dig.main(_dig_argv))
    elif args.cmd == "example-composition":
        # One shared implementation with `python -m dv_harness.example_composition`
        # (main(argv)).
        from . import example_composition as _exc
        _exc_argv = ["compose", "--examples", args.examples]
        if args.json:
            _exc_argv.append("--json")
        raise SystemExit(_exc.main(_exc_argv))
    elif args.cmd == "existing-command-reuse":
        # One shared implementation with `python -m
        # dv_harness.existing_command_reuse_score` (main(argv)).
        from . import existing_command_reuse_score as _ecr
        _ecr_argv = ["--need-file", args.need_file, "--commands-file", args.commands_file,
                     "--root", str(h.root)]
        if args.db:
            _ecr_argv += ["--db", args.db]
        if args.json:
            _ecr_argv.append("--json")
        raise SystemExit(_ecr.main(_ecr_argv))
    elif args.cmd == "fabric-progress":
        # One shared implementation with `python -m dv_harness.fabric_progress_ir`
        # (main(argv)).
        from . import fabric_progress_ir as _fpi
        _fpi_argv = []
        if args.resource_dependency:
            _fpi_argv += ["--resource-dependency", args.resource_dependency]
        if args.credit_outstanding:
            _fpi_argv += ["--credit-outstanding", args.credit_outstanding]
        if args.json:
            _fpi_argv.append("--json")
        raise SystemExit(_fpi.main(_fpi_argv))
    elif args.cmd == "file-candidate-rank":
        # One shared implementation with `python -m dv_harness.file_candidate_ranker`
        # (main(argv)).
        from . import file_candidate_ranker as _fcr
        _fcr_argv = ["rank"] + list(args.candidates)
        if args.repo_root:
            _fcr_argv += ["--repo-root", args.repo_root]
        _fcr_argv += ["--project-root", args.fcr_project_root or str(h.root)]
        raise SystemExit(_fcr.main(_fcr_argv))
    elif args.cmd == "functional-coverage-signoff":
        # One shared implementation with `python -m
        # dv_harness.functional_coverage_signoff` (main(argv)).
        from . import functional_coverage_signoff as _fcs
        _fcs_argv = ["--project-root", str(h.root)]
        if args.json:
            _fcs_argv.append("--json")
        raise SystemExit(_fcs.main(_fcs_argv))
    elif args.cmd == "gen-code-quality-gate":
        # One shared implementation with `python -m dv_harness.gen_code_quality_gate`
        # (main(argv)).
        from . import gen_code_quality_gate as _gcq
        _gcq_argv = []
        if args.env_dir:
            _gcq_argv += ["--env-dir", args.env_dir]
        if args.verible_bin:
            _gcq_argv += ["--verible-bin", args.verible_bin]
        for _s in (args.gcq_vip_sources or []):
            _gcq_argv += ["--vip-source", _s]
        if args.vip_index:
            _gcq_argv += ["--vip-index", args.vip_index]
        if args.relative_to:
            _gcq_argv += ["--relative-to", args.relative_to]
        if args.json:
            _gcq_argv.append("--json")
        raise SystemExit(_gcq.main(_gcq_argv))
    elif args.cmd == "golden-subsystem-benchmark":
        # One shared implementation with `python -m
        # dv_harness.golden_subsystem_benchmark` (main(argv)).
        from . import golden_subsystem_benchmark as _gsb
        _gsb_argv = [args.gsb_verb, "--root", str(h.root)]
        if args.dataset_id:
            _gsb_argv += ["--dataset-id", args.dataset_id]
        if args.json_file:
            _gsb_argv += ["--json-file", args.json_file]
        if args.version is not None:
            _gsb_argv += ["--version", str(args.version)]
        if args.old_version is not None:
            _gsb_argv += ["--old-version", str(args.old_version)]
        if args.new_version is not None:
            _gsb_argv += ["--new-version", str(args.new_version)]
        if args.case_id:
            _gsb_argv += ["--case-id", args.case_id]
        if args.subject_id:
            _gsb_argv += ["--subject-id", args.subject_id]
        if args.subject_version:
            _gsb_argv += ["--subject-version", args.subject_version]
        if args.subject_kind:
            _gsb_argv += ["--subject-kind", args.subject_kind]
        if args.used_for:
            _gsb_argv += ["--used-for", args.used_for]
        if args.extracted_docs_file:
            _gsb_argv += ["--extracted-docs-file", args.extracted_docs_file]
        if args.json:
            _gsb_argv.append("--json")
        raise SystemExit(_gsb.main(_gsb_argv))
    elif args.cmd == "gui-audit-log":
        # One shared implementation with `python -m dv_harness.gui_audit_log`
        # (execute_verb(argv), that module's own argv-taking front door --
        # it does its own argparse and printing, so this just builds the
        # identical argv list rather than re-deriving its output).
        from . import gui_audit_log as _gal
        _gal_argv = [args.gal_verb, "--root", str(h.root), "--limit", str(args.limit)]
        if args.action:
            _gal_argv += ["--action", args.action]
        if args.json:
            _gal_argv.append("--json")
        raise SystemExit(_gal.execute_verb(_gal_argv))
    elif args.cmd == "gui-intake-wizard":
        # One shared implementation with `python -m dv_harness.gui_intake_wizard`
        # (main(argv)) -- that module's own standalone ThreadingHTTPServer,
        # grounded entirely in intake_state.py's real per-field data. Ships
        # as its own standalone server (not a dashboard.py card) per that
        # module's own disclosed reasoning; this verb is the thin real
        # connection this gap-close item adds. Blocks until interrupted.
        from . import gui_intake_wizard as _giw
        raise SystemExit(_giw.main(["--project-root", str(h.root),
                                     "--host", args.host, "--port", str(args.port)]))
    elif args.cmd == "gui-intake-control-plane":
        # One shared implementation with `python -m
        # dv_harness.gui_intake_control_plane` (main(argv)) -- a real backend
        # over question_queue.py + intake_state.py, ships as its own
        # standalone, session-token-gated server (not a dashboard.py card)
        # per that module's own disclosed reasoning; this verb is the thin
        # real connection this gap-close item adds. 'serve' blocks until
        # interrupted.
        from . import gui_intake_control_plane as _gicp
        _gicp_argv = [args.gicp_verb, "--project-root", str(h.root)]
        if args.gicp_verb == "serve":
            _gicp_argv += ["--host", args.host, "--port", str(args.port)]
            if args.no_auth:
                _gicp_argv.append("--no-auth")
        raise SystemExit(_gicp.main(_gicp_argv))
    elif args.cmd == "human-correction-lesson":
        # One shared implementation with `python -m
        # dv_harness.human_correction_lesson` (execute_verb(argv), that
        # module's own argv-taking front door).
        from . import human_correction_lesson as _hcl
        _hcl_argv = ["--root", str(h.root)]
        if args.json:
            _hcl_argv.append("--json")
        _hcl_argv.append(args.hcl_verb)
        if args.hcl_verb == "record":
            _hcl_argv += ["--before-claim", args.before_claim, "--after-claim", args.after_claim,
                          "--correction-evidence", args.correction_evidence,
                          "--corrected-by", args.corrected_by,
                          "--mistake-category", args.mistake_category]
            if args.before_reasoning:
                _hcl_argv += ["--before-reasoning", args.before_reasoning]
            if args.protocol:
                _hcl_argv += ["--protocol", args.protocol]
            if args.scope:
                _hcl_argv += ["--scope", args.scope]
            if args.title:
                _hcl_argv += ["--title", args.title]
            if args.confidence:
                _hcl_argv += ["--confidence", args.confidence]
        else:
            _hcl_argv += ["--before-claim", args.before_claim]
            if args.mistake_category:
                _hcl_argv += ["--mistake-category", args.mistake_category]
        raise SystemExit(_hcl.execute_verb(_hcl_argv))
    elif args.cmd == "iface-contract-vip-bind":
        # One shared implementation with `python -m
        # dv_harness.iface_contract_vip_bind_validator` (main(argv)).
        from . import iface_contract_vip_bind_validator as _ivb
        _ivb_argv = ["--contracts", args.contracts]
        if args.bind_root:
            _ivb_argv += ["--bind-root", args.bind_root]
        if args.modules:
            _ivb_argv += ["--modules", args.modules]
        if args.json:
            _ivb_argv.append("--json")
        if args.strict_unprovable:
            _ivb_argv.append("--strict-unprovable")
        raise SystemExit(_ivb.main(_ivb_argv))
    elif args.cmd == "intake-baseline":
        # One shared implementation with `python -m dv_harness.intake_baseline`
        # (execute_verb(argv)).
        from . import intake_baseline as _ib
        _ib_argv = [args.ib_verb, "--root", args.root or str(h.root)]
        if args.facts:
            _ib_argv += ["--facts", args.facts]
        if args.freeze_id:
            _ib_argv += ["--freeze-id", args.freeze_id]
        if args.frozen_by:
            _ib_argv += ["--frozen-by", args.frozen_by]
        if args.note:
            _ib_argv += ["--note", args.note]
        raise SystemExit(_ib.execute_verb(_ib_argv))
    elif args.cmd == "intake-contract-stale":
        # One shared implementation with
        # `python -m dv_harness.intake_contract_stale_detection` (main(argv)).
        from . import intake_contract_stale_detection as _icsd
        _icsd_argv = [args.ics_verb, "--project-root", str(h.root)]
        if args.contract:
            _icsd_argv += ["--contract", args.contract]
        if args.recorded_sha:
            _icsd_argv += ["--recorded-sha", args.recorded_sha]
        if args.window_seconds is not None:
            _icsd_argv += ["--window-seconds", str(args.window_seconds)]
        raise SystemExit(_icsd.main(_icsd_argv))
    elif args.cmd == "intake-events":
        # One shared implementation with `python -m dv_harness.intake_events`
        # (main(argv)).
        from . import intake_events as _ie
        _ie_argv = [args.ie_verb, "--project-root", str(h.root)]
        if args.json:
            _ie_argv.append("--json")
        raise SystemExit(_ie.main(_ie_argv))
    elif args.cmd == "intake-modes":
        # One shared implementation with `python -m dv_harness.intake_modes`
        # (main(argv)).
        from . import intake_modes as _im
        _im_argv = [args.im_verb]
        if args.mode:
            _im_argv += ["--mode", args.mode]
        if args.intake_state:
            _im_argv += ["--intake-state", args.intake_state]
        if args.json:
            _im_argv.append("--json")
        raise SystemExit(_im.main(_im_argv))
    elif args.cmd == "intake-question-priority":
        # One shared implementation with
        # `python -m dv_harness.intake_question_priority` (main(argv)).
        from . import intake_question_priority as _iqp
        _iqp_argv = ["--pending-questions", args.pending_questions]
        if args.max_batch_size is not None:
            _iqp_argv += ["--max-batch-size", str(args.max_batch_size)]
        if args.json:
            _iqp_argv.append("--json")
        raise SystemExit(_iqp.main(_iqp_argv))
    elif args.cmd == "intake-source-priority":
        # One shared implementation with
        # `python -m dv_harness.intake_source_priority` (execute_verb(argv)).
        from . import intake_source_priority as _isp
        _isp_argv = [args.isp_verb]
        if args.isp_verb == "next":
            if args.fact:
                _isp_argv += ["--fact", args.fact]
            if args.available:
                _isp_argv += ["--available", args.available]
            if args.json:
                _isp_argv.append("--json")
        raise SystemExit(_isp.execute_verb(_isp_argv))
    elif args.cmd == "integration-adapter-gen":
        # One shared implementation with
        # `python -m dv_harness.integration_adapter_gen` (main(argv)).
        from . import integration_adapter_gen as _iag
        _iag_argv = [args.mapping_file]
        if args.subsystem_name:
            _iag_argv += ["--subsystem-name", args.subsystem_name]
        if args.out:
            _iag_argv += ["--out", args.out]
        raise SystemExit(_iag.main(_iag_argv))
    elif args.cmd == "interrupt-dma-clock-reset":
        # One shared implementation with `python -m
        # dv_harness.interrupt_dma_clock_reset_extraction` (execute_verb(argv)).
        from . import interrupt_dma_clock_reset_extraction as _idce
        _idce_argv = ["extract", "--sources"] + list(args.sources)
        if args.json:
            _idce_argv.append("--json")
        raise SystemExit(_idce.execute_verb(_idce_argv))
    elif args.cmd == "timing-requirements":
        # One shared implementation with `python -m
        # dv_harness.timing_requirement_extraction` (execute_verb(argv)).
        from . import timing_requirement_extraction as _tre
        _tre_argv = ["extract", "--sources"] + list(args.sources)
        if args.json:
            _tre_argv.append("--json")
        raise SystemExit(_tre.execute_verb(_tre_argv))
    elif args.cmd == "ip-ownership-conflict":
        # One shared implementation with `python -m dv_harness.ip_ownership_conflict`
        # (main(argv)).
        from . import ip_ownership_conflict as _ioc
        _ioc_argv = ["--env-manifest", args.env_manifest]
        if args.legacy_bfm:
            _ioc_argv += ["--legacy-bfm", args.legacy_bfm]
        if args.connectivity_rows:
            _ioc_argv += ["--connectivity-rows", args.connectivity_rows]
        if args.json:
            _ioc_argv.append("--json")
        raise SystemExit(_ioc.main(_ioc_argv))
    elif args.cmd == "loop-stale-detection":
        # One shared implementation with `python -m dv_harness.loop_stale_detection`
        # (main(argv)).
        from . import loop_stale_detection as _lsd
        _lsd_argv = [args.lsd_verb, "--project-root", str(h.root)]
        if args.run_id:
            _lsd_argv += ["--run-id", args.run_id]
        if args.window_seconds is not None:
            _lsd_argv += ["--window-seconds", str(args.window_seconds)]
        raise SystemExit(_lsd.main(_lsd_argv))
    elif args.cmd == "loop-telemetry":
        # One shared implementation with `python -m dv_harness.loop_telemetry`
        # (main(argv)).
        from . import loop_telemetry as _lt
        _lt_argv = [args.lt_verb, "--project-root", str(h.root)]
        if args.run_id:
            _lt_argv += ["--run-id", args.run_id]
        if args.json:
            _lt_argv.append("--json")
        raise SystemExit(_lt.main(_lt_argv))
    elif args.cmd == "memory-quality-policy":
        # One shared implementation with `python -m dv_harness.memory_quality_policy`
        # (execute_verb(argv)).
        from . import memory_quality_policy as _mqp
        _mqp_argv = ["--root", str(h.root), args.mqp_verb]
        if args.stale_after_days is not None:
            _mqp_argv += ["--stale-after-days", str(args.stale_after_days)]
        if args.deprecate_after_days is not None:
            _mqp_argv += ["--deprecate-after-days", str(args.deprecate_after_days)]
        if args.json:
            _mqp_argv.append("--json")
        raise SystemExit(_mqp.execute_verb(_mqp_argv))
    elif args.cmd == "model-agent-tool-router":
        # One shared implementation with `python -m dv_harness.model_agent_tool_router`
        # (execute_verb(argv)).
        from . import model_agent_tool_router as _matr
        _matr_argv = [args.matr_verb]
        if args.matr_verb == "route":
            if args.task_type:
                _matr_argv += ["--task-type", args.task_type]
            _matr_argv += ["--root", str(h.root)]
            if args.unavailable_agents:
                _matr_argv += ["--unavailable-agents", args.unavailable_agents]
            if args.unavailable_models:
                _matr_argv += ["--unavailable-models", args.unavailable_models]
            if args.unavailable_tools:
                _matr_argv += ["--unavailable-tools", args.unavailable_tools]
        if args.json:
            _matr_argv.append("--json")
        raise SystemExit(_matr.execute_verb(_matr_argv))
    elif args.cmd == "ordering-domain-graph":
        # One shared implementation with `python -m dv_harness.ordering_domain_graph`
        # (main(argv)).
        from . import ordering_domain_graph as _odg
        _odg_argv = ["--facts-file", args.facts_file]
        if args.json:
            _odg_argv.append("--json")
        raise SystemExit(_odg.main(_odg_argv))
    elif args.cmd == "org-verification-policy":
        # One shared implementation with `python -m dv_harness.org_verification_policy_engine`
        # (execute_verb(argv)).
        from . import org_verification_policy_engine as _ovpe
        _ovpe_argv = [args.ovpe_verb, "--policies", args.policies]
        if args.ovpe_verb == "evaluate" and args.facts:
            _ovpe_argv += ["--facts", args.facts]
        if args.json:
            _ovpe_argv.append("--json")
        raise SystemExit(_ovpe.execute_verb(_ovpe_argv))
    elif args.cmd == "pattern-coverage-contribution":
        # One shared implementation with `python -m dv_harness.pattern_coverage_contribution`
        # (execute_verb(argv)).
        from . import pattern_coverage_contribution as _pcc
        _pcc_argv = ["contribution", "--db-path", args.db_path, "--pattern", args.pattern,
                     "--attribution", args.attribution]
        if args.cross_definitions:
            _pcc_argv += ["--cross-definitions", args.cross_definitions]
        if args.json:
            _pcc_argv.append("--json")
        raise SystemExit(_pcc.execute_verb(_pcc_argv))
    elif args.cmd == "pattern-execution-evidence":
        # One shared implementation with `python -m dv_harness.pattern_execution_evidence`
        # (main(argv)).
        from . import pattern_execution_evidence as _pee
        _pee_argv = [args.log_path]
        if args.command:
            _pee_argv += ["--command", args.command]
        if args.json:
            _pee_argv.append("--json")
        raise SystemExit(_pee.main(_pee_argv))
    elif args.cmd == "pattern-runtime-state":
        # One shared implementation with `python -m dv_harness.pattern_runtime_state_machine`
        # (main(argv)).
        from . import pattern_runtime_state_machine as _prs
        _prs_argv = [args.prs_verb, "--root", str(h.root)]
        if args.pattern_id:
            _prs_argv += ["--pattern-id", args.pattern_id]
        if args.log_file:
            _prs_argv += ["--log-file", args.log_file]
        if args.json:
            _prs_argv.append("--json")
        raise SystemExit(_prs.main(_prs_argv))
    elif args.cmd == "platform-startup-readiness":
        # One shared implementation with `python -m dv_harness.platform_startup_readiness`
        # (main(argv)).
        from . import platform_startup_readiness as _psr
        _psr_argv = ["--root", str(h.root)]
        if args.json:
            _psr_argv.append("--json")
        raise SystemExit(_psr.main(_psr_argv))
    elif args.cmd == "spec-gap-detector":
        # One shared implementation with `python -m dv_harness.potential_spec_gap_detector`
        # (main(argv)).
        from . import potential_spec_gap_detector as _psgd
        _psgd_argv = [args.requirements]
        if args.json:
            _psgd_argv.append("--json")
        raise SystemExit(_psgd.main(_psgd_argv))
    elif args.cmd == "prior-decision-reevaluation":
        # One shared implementation with `python -m dv_harness.prior_decision_reevaluation`
        # (main(argv)).
        from . import prior_decision_reevaluation as _pdr
        _pdr_argv = [args.pdr_verb, "--root", str(h.root)]
        if args.candidates:
            _pdr_argv += ["--candidates", args.candidates]
        if args.cross_project_patterns:
            _pdr_argv += ["--cross-project-patterns", args.cross_project_patterns]
        if args.min_occurrences is not None:
            _pdr_argv += ["--min-occurrences", str(args.min_occurrences)]
        raise SystemExit(_pdr.main(_pdr_argv))
    elif args.cmd == "programming-sequence-ir":
        # One shared implementation with `python -m dv_harness.programming_sequence_ir`
        # (main(argv)).
        from . import programming_sequence_ir as _psir
        _psir_argv = [args.psir_verb]
        if args.sequence:
            _psir_argv += ["--sequence", args.sequence]
        if args.facts:
            _psir_argv += ["--facts", args.facts]
        if args.catalog:
            _psir_argv += ["--catalog", args.catalog]
        if args.json:
            _psir_argv.append("--json")
        raise SystemExit(_psir.main(_psir_argv))
    elif args.cmd == "usage-recipe-catalog":
        # One shared implementation with `python -m dv_harness.usage_recipe_catalog`
        # (execute_verb(verb, ...)).
        from . import usage_recipe_catalog as _urc
        _urc_text, _urc_code = _urc.execute_verb(
            args.urc_verb,
            recipes_json=args.recipes_json,
            facts_json=args.facts_json,
            catalog_json=args.catalog_json,
            recipe_id=args.urc_recipe_id,
            as_json=args.json,
        )
        print(_urc_text)
        raise SystemExit(_urc_code)
    elif args.cmd == "protocol-capability":
        # One shared implementation with `python -m dv_harness.protocol_capability`
        # (module-private _main(argv)).
        from . import protocol_capability as _ppcap
        _ppcap_argv = []
        if args.check:
            _ppcap_argv.append("--check")
        if args.sync:
            _ppcap_argv.append("--sync")
        if args.capability_root:
            _ppcap_argv += ["--root", args.capability_root]
        if args.json:
            _ppcap_argv.append("--json")
        raise SystemExit(_ppcap._main(_ppcap_argv))
    elif args.cmd == "protocol-compliance-oracle":
        # One shared implementation with `python -m dv_harness.protocol_compliance_oracle`
        # (execute_verb(argv)).
        from . import protocol_compliance_oracle as _ppco
        _ppco_argv = ["--pattern", args.pattern]
        if args.json:
            _ppco_argv.append("--json")
        raise SystemExit(_ppco.execute_verb(_ppco_argv))
    elif args.cmd == "rca-ontology":
        # One shared implementation with `python -m dv_harness.rca_ontology`
        # (execute_verb(argv) -- main() itself already raises SystemExit, so
        # execute_verb() is called directly here rather than double-wrapping).
        from . import rca_ontology as _prca
        if args.rca_verb == "categories":
            _prca_argv = ["categories"]
        else:
            if not args.records:
                print("rca-ontology classify requires --records", file=sys.stderr)
                raise SystemExit(2)
            _prca_argv = ["classify", "--records", args.records]
            if args.rca_root:
                _prca_argv += ["--root", args.rca_root]
        raise SystemExit(_prca.execute_verb(_prca_argv))
    elif args.cmd == "register-excel-extract":
        # One shared implementation with `python -m dv_harness.register_excel_extract`
        # (execute_verb(argv)).
        from . import register_excel_extract as _pree
        _pree_argv = [args.excel_path]
        if args.sheet:
            _pree_argv += ["--sheet", args.sheet]
        if args.block:
            _pree_argv += ["--block", args.block]
        if args.base_address:
            _pree_argv += ["--base-address", args.base_address]
        if args.json:
            _pree_argv.append("--json")
        raise SystemExit(_pree.execute_verb(_pree_argv))
    elif args.cmd == "register-rtl-trace":
        # One shared implementation with `python -m dv_harness.register_rtl_trace`
        # (main(argv)).
        from . import register_rtl_trace as _prrt
        _prrt_argv = ["--register-map", args.register_map]
        for _rp in args.rrt_rtl_paths:
            _prrt_argv += ["--rtl", _rp]
        if args.strict_partial:
            _prrt_argv.append("--strict-partial")
        if args.json:
            _prrt_argv.append("--json")
        raise SystemExit(_prrt.main(_prrt_argv))
    elif args.cmd == "requirement-risk-ir":
        # One shared implementation with `python -m dv_harness.requirement_risk_ir`
        # (main(argv)).
        from . import requirement_risk_ir as _prri
        _prri_argv = []
        if args.facts_file:
            _prri_argv += ["--facts-file", args.facts_file]
        if args.source_file:
            _prri_argv += ["--source-file", args.source_file]
        _prri_root = args.requirement_project_root or str(h.root)
        _prri_argv += ["--project-root", _prri_root]
        if args.json:
            _prri_argv.append("--json")
        raise SystemExit(_prri.main(_prri_argv))
    elif args.cmd == "requirement-testability":
        # One shared implementation with `python -m dv_harness.requirement_testability`
        # (execute_verb()).
        from . import requirement_testability as _prqt
        _prqt_text, _prqt_code = _prqt.execute_verb(
            args.requirements, as_json=args.json,
            fail_on_indeterminate=args.fail_on_indeterminate)
        print(_prqt_text)
        raise SystemExit(_prqt_code)
    elif args.cmd == "resource-orchestrator":
        # One shared implementation with `python -m dv_harness.resource_orchestrator`
        # (execute_verb()).
        from . import resource_orchestrator as _preso
        _preso_code, _preso_payload = _preso.execute_verb(
            h.root, args.reso_verb, requests_path=args.requests, queue=args.queue)
        print(json.dumps(_preso_payload, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(_preso_code)
    elif args.cmd == "runtime-control-commands":
        # One shared implementation with `python -m dv_harness.runtime_control_commands`
        # (execute_verb()).
        from . import runtime_control_commands as _prcc
        _prcc_text, _prcc_code = _prcc.execute_verb(args.command_file, as_json=args.json)
        print(_prcc_text)
        raise SystemExit(_prcc_code)
    elif args.cmd == "runtime-events":
        # One shared implementation with `python -m dv_harness.runtime_event_registry`
        # (execute_verb()).
        from . import runtime_event_registry as _prer
        _prer_text, _prer_code = _prer.execute_verb(
            args.re_verb, root=h.root, registry_path=args.registry, out_path=args.out,
            as_json=args.json)
        print(_prer_text)
        raise SystemExit(_prer_code)
    elif args.cmd == "safe-write-rollback":
        # One shared implementation with `python -m dv_harness.safe_write_rollback`
        # (execute_verb(argv) -- that module's own execute_verb parses its own argv
        # and prints/returns an exit code directly, so it is called with a
        # reconstructed argv list rather than the (text, code) convention).
        from . import safe_write_rollback as _pswr
        _pswr_argv = ["--root", str(h.root), args.swr_verb]
        if args.swr_verb == "write":
            _pswr_argv += ["--path", args.path, "--content-file", args.content_file,
                          "--actor", args.actor, "--reason", args.reason]
            if args.write_id:
                _pswr_argv += ["--write-id", args.write_id]
        elif args.swr_verb == "plan":
            _pswr_argv += ["--write-id", args.write_id]
        elif args.swr_verb == "apply":
            _pswr_argv += ["--write-id", args.write_id, "--actor", args.actor,
                          "--reason", args.reason]
        elif args.swr_verb == "batch-plan":
            _pswr_argv += ["--batch-id", args.batch_id]
        elif args.swr_verb == "batch-apply":
            _pswr_argv += ["--batch-id", args.batch_id, "--actor", args.actor,
                          "--reason", args.reason]
        raise SystemExit(_pswr.execute_verb(_pswr_argv))
    elif args.cmd == "safety-sandbox":
        # One shared implementation with `python -m dv_harness.safety_sandbox`
        # (execute_verb(argv) -- see the safe-write-rollback wiring above for why
        # a reconstructed argv list is used here instead).
        from . import safety_sandbox as _pssb
        _pssb_argv = ["--root", str(h.root), args.ss_verb]
        if args.ss_verb == "declare":
            if args.paths:
                _pssb_argv += ["--paths"] + list(args.paths)
            _pssb_argv += ["--declared-by", args.declared_by, "--reason", args.reason]
            if args.sandbox_id:
                _pssb_argv += ["--sandbox-id", args.sandbox_id]
        elif args.ss_verb == "check":
            _pssb_argv += ["--sandbox-id", args.sandbox_id, "--paths"] + list(args.paths)
        elif args.ss_verb == "verify-diff":
            _pssb_argv += ["--sandbox-id", args.sandbox_id, "--base", args.base,
                           "--head", args.head]
        elif args.ss_verb == "status":
            _pssb_argv += ["--sandbox-id", args.sandbox_id]
        raise SystemExit(_pssb.execute_verb(_pssb_argv))
    elif args.cmd == "scoreboard-placement-scope":
        # One shared implementation with `python -m dv_harness.scoreboard_placement_scope`
        # (main(argv)).
        from . import scoreboard_placement_scope as _psps
        _psps_argv = [args.sps_verb]
        if args.sps_verb == "classify":
            _psps_argv += ["--description", args.description]
            if args.evidence:
                _psps_argv += ["--evidence", args.evidence]
            if args.json:
                _psps_argv.append("--json")
        raise SystemExit(_psps.main(_psps_argv))
    elif args.cmd == "security-policy-ir":
        # One shared implementation with `python -m dv_harness.security_policy_ir`
        # (main(argv)).
        from . import security_policy_ir as _pspi
        _pspi_argv = [args.spi_verb]
        if args.spi_verb == "classify":
            _pspi_argv += ["--policy", args.policy, "--master", args.master,
                          "--region", args.region, "--secure", args.secure,
                          "--privileged", args.privileged]
            if args.json:
                _pspi_argv.append("--json")
        elif args.spi_verb == "verify-negative-test":
            _pspi_argv += ["--policy", args.policy, "--master", args.master,
                          "--region", args.region, "--secure", args.secure,
                          "--privileged", args.privileged, "--test-result", args.test_result]
            if args.json:
                _pspi_argv.append("--json")
        raise SystemExit(_pspi.main(_pspi_argv))
    elif args.cmd == "self-learning-readiness":
        # One shared implementation with `python -m dv_harness.self_learning_readiness`
        # (execute()).
        from . import self_learning_readiness as _pslr
        _pslr_code, _pslr_matrix, _pslr_text = _pslr.execute(h.root, as_json=args.json)
        print(json.dumps(_pslr_matrix, ensure_ascii=False, indent=2) if args.json else _pslr_text)
        raise SystemExit(_pslr_code)
    elif args.cmd == "shared-bus-resource-registry":
        # One shared implementation with `python -m dv_harness.shared_bus_resource_registry`
        # (execute_verb()).
        from . import shared_bus_resource_registry as _psbrr
        _psbrr_text, _psbrr_code = _psbrr.execute_verb(
            args.sbrr_resource_declarations,
            connectivity_rows_path=args.sbrr_connectivity_rows, as_json=args.json)
        print(_psbrr_text)
        raise SystemExit(_psbrr_code)
    elif args.cmd == "spec-doc-map":
        # One shared implementation with `python -m dv_harness.spec_doc_map`
        # (execute_verb()).
        from . import spec_doc_map as _psdm
        _psdm_text, _psdm_code = _psdm.execute_verb(
            args.sdm_verb,
            source_path=getattr(args, "sdm_source_path", None),
            out_dir=getattr(args, "sdm_out_dir", None),
            record_path=getattr(args, "sdm_record_path", None),
            title=getattr(args, "sdm_title", None),
            doc_kind=getattr(args, "sdm_doc_kind", "dut_spec"),
            as_json=args.json)
        print(_psdm_text)
        raise SystemExit(_psdm_code)
    elif args.cmd == "spec-intelligence":
        # One shared implementation with `python -m dv_harness.spec_intelligence`
        # (execute_verb_spec_map()/execute_verb_analyze()).
        from . import spec_intelligence as _psi
        if args.si_cmd == "spec-map":
            _psi_text, _psi_code = _psi.execute_verb_spec_map(
                args.si_reference, args.si_out, as_json=args.json)
        else:
            _psi_text, _psi_code = _psi.execute_verb_analyze(
                args.si_extraction, as_json=args.json,
                fail_on_error=args.fail_on_error, project_root=args.si_project_root)
        print(_psi_text)
        raise SystemExit(_psi_code)
    elif args.cmd == "spec-vplan-delta":
        # One shared implementation with `python -m dv_harness.spec_vplan_delta`
        # (execute_verb()).
        from . import spec_vplan_delta as _psvd
        _psvd_root = args.vplan_delta_root or str(h.root)
        _psvd_text, _psvd_code = _psvd.execute_verb(
            args.before, args.after, root=_psvd_root, as_json=args.json)
        print(_psvd_text)
        raise SystemExit(_psvd_code)
    elif args.cmd == "spec-vplan-readiness-gate":
        # One shared implementation with `python -m dv_harness.spec_vplan_readiness_gate`
        # (execute_verb()).
        from . import spec_vplan_readiness_gate as _psvrg
        _psvrg_text, _psvrg_code = _psvrg.execute_verb(
            args.svrg_verb, conditions_path=args.svrg_conditions, as_json=args.json)
        print(_psvrg_text)
        raise SystemExit(_psvrg_code)
    elif args.cmd == "subsys-compat-matrix":
        # One shared implementation with `python -m dv_harness.subsys_compat_matrix`
        # (subsys_compat_matrix.execute_verb()), same convention as power-intent above.
        from . import subsys_compat_matrix as _scm
        _scm_text, _scm_code = _scm.execute_verb(
            args.scm_root or str(h.root), selected_path=args.scm_selected,
            ip_ownership_inputs_path=args.scm_ip_ownership_inputs, as_json=args.json)
        print(_scm_text)
        raise SystemExit(_scm_code)
    elif args.cmd == "subsystem-contract":
        # One shared implementation with `python -m dv_harness.subsystem_contract`
        # (subsystem_contract.execute_verb()), same convention as
        # system-verification-contract below.
        from . import subsystem_contract as _ssc
        try:
            _ssc_text, _ssc_code = _ssc.execute_verb(
                args.ssc_verb, root=args.ssc_root or str(h.root),
                subsystem=args.ssc_subsystem, manifest_path=args.ssc_manifest,
                requirements_path=args.ssc_requirements, db_path=args.ssc_db,
                declared_spec_version=args.ssc_spec_version, as_json=args.json)
        except _ssc.SubsystemContractError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_ssc_text)
        raise SystemExit(_ssc_code)
    elif args.cmd == "subsystem-maturity-gate":
        # One shared implementation with `python -m dv_harness.subsystem_maturity_gate`
        # (main(argv)).
        from . import subsystem_maturity_gate as _smg
        _smg_argv = [args.smg_verb]
        if args.smg_verb == "conditions":
            if args.json:
                _smg_argv.append("--json")
        else:
            _smg_argv += ["--level", args.level, "--root", args.smg_root or str(h.root)]
            if args.json:
                _smg_argv.append("--json")
            if args.smg_vip_api_cards:
                _smg_argv += ["--vip-api-cards", args.smg_vip_api_cards]
            for _smg_vs in (args.smg_vip_sources or []):
                _smg_argv += ["--vip-source", _smg_vs]
            if args.smg_vip_index:
                _smg_argv += ["--vip-index", args.smg_vip_index]
            if args.smg_bind_topology:
                _smg_argv += ["--bind-topology", args.smg_bind_topology]
            if args.smg_require_tier:
                _smg_argv.append("--require-tier")
            if args.smg_evidence_db:
                _smg_argv += ["--evidence-db", args.smg_evidence_db]
            if args.smg_smoke_proof_report:
                _smg_argv += ["--smoke-proof-report", args.smg_smoke_proof_report]
        raise SystemExit(_smg.main(_smg_argv))
    elif args.cmd == "subsystem-practicality-score":
        # One shared implementation with
        # `python -m dv_harness.subsystem_practicality_score` (main(argv)).
        from . import subsystem_practicality_score as _spr
        _spr_argv = [args.spr_verb, "--project-root", args.spr_project_root or str(h.root)]
        if args.json:
            _spr_argv.append("--json")
        if args.deep:
            _spr_argv.append("--deep")
        raise SystemExit(_spr.main(_spr_argv))
    elif args.cmd == "syoscb-source-audit":
        # One shared implementation with `python -m dv_harness.syoscb_source_audit`
        # (module-private _main(argv)).
        from . import syoscb_source_audit as _syo
        _syo_argv = [args.syo_root]
        if args.json:
            _syo_argv.append("--json")
        if args.syo_registration_payload:
            _syo_argv.append("--registration-payload")
        if args.syo_l5_destination:
            _syo_argv += ["--l5-destination", args.syo_l5_destination]
        if args.syo_assert_not_vendored:
            _syo_argv += ["--assert-not-vendored", args.syo_assert_not_vendored]
        raise SystemExit(_syo._main(_syo_argv))
    elif args.cmd == "system-checker-taxonomy":
        # One shared implementation with `python -m dv_harness.system_checker_taxonomy`
        # (execute_verb(argv)).
        from . import system_checker_taxonomy as _sct
        _sct_argv = [args.sct_cmd]
        if args.sct_cmd == "classify":
            _sct_argv.append(args.sct_path)
            if args.json:
                _sct_argv.append("--json")
        raise SystemExit(_sct.execute_verb(_sct_argv))
    elif args.cmd == "system-closure-aggregator":
        # One shared implementation with `python -m dv_harness.system_closure_aggregator`
        # (execute_verb(argv)).
        from . import system_closure_aggregator as _sca
        _sca_argv = ["--dimensions", args.sca_dimensions]
        if args.sca_markdown:
            _sca_argv.append("--markdown")
        raise SystemExit(_sca.execute_verb(_sca_argv))
    elif args.cmd == "system-command-grammar-ir":
        # One shared implementation with `python -m dv_harness.system_command_grammar_ir`
        # (main(argv)).
        from . import system_command_grammar_ir as _scg
        _scg_argv = []
        for _scg_entry in args.scg_subsystem:
            _scg_argv += ["--subsystem", _scg_entry]
        if args.json:
            _scg_argv.append("--json")
        raise SystemExit(_scg.main(_scg_argv))
    elif args.cmd == "system-error-propagation":
        # One shared implementation with `python -m dv_harness.system_error_propagation`
        # (system_error_propagation.execute_verb()), same convention as power-intent above.
        from . import system_error_propagation as _sep
        _sep_text, _sep_code = _sep.execute_verb(
            origin=args.origin, condition_path=args.sep_condition_path,
            condition_text=args.sep_condition_text, topology_path=args.sep_topology_path,
            declared_responses_path=args.sep_declared_responses_path, as_json=args.json)
        print(_sep_text)
        raise SystemExit(_sep_code)
    elif args.cmd == "system-fw-service-registry":
        # One shared implementation with `python -m dv_harness.system_fw_service_registry`
        # (execute_verb()).
        from . import system_fw_service_registry as _sfw
        _sfw_text, _sfw_code = _sfw.execute_verb(args.sfw_input, as_json=args.json)
        print(_sfw_text)
        raise SystemExit(_sfw_code)
    elif args.cmd == "system-verification-contract":
        # One shared implementation with
        # `python -m dv_harness.system_verification_contract` (execute_verb()), same
        # convention as subsystem-contract above.
        from . import system_verification_contract as _svc
        try:
            _svc_text, _svc_code = _svc.execute_verb(
                args.svc_verb, root=args.svc_root or str(h.root),
                subsystem_contracts_path=args.svc_subsystem_contracts,
                topology_path=args.svc_topology,
                resource_registry_path=args.svc_resource_registry,
                command_registry_path=args.svc_command_registry,
                system_name=args.svc_system_name, as_json=args.json)
        except _svc.SystemVerificationContractError as e:
            print(f"{type(e).__name__}: {e}")
            raise SystemExit(2)
        print(_svc_text)
        raise SystemExit(_svc_code)
    elif args.cmd == "missing-artifact-detector":
        # One shared implementation with
        # `python -m dv_harness.target_conditioned_missing_artifact_detector`
        # (execute_verb(argv)).
        from . import target_conditioned_missing_artifact_detector as _mad
        _mad_argv = [args.mad_target]
        if args.mad_inventory:
            _mad_argv.append(args.mad_inventory)
        _mad_code, _mad_report, _mad_text = _mad.execute_verb(_mad_argv)
        print(_mad_text)
        raise SystemExit(_mad_code)
    elif args.cmd == "task-return-model":
        # One shared implementation with `python -m dv_harness.task_return_model`
        # (main(argv)).
        from . import task_return_model as _trm
        _trm_argv = ["--tasks", args.trm_tasks, "--log", args.trm_log]
        if args.json:
            _trm_argv.append("--json")
        raise SystemExit(_trm.main(_trm_argv))
    elif args.cmd == "transaction-correlation":
        # One shared implementation with `python -m dv_harness.transaction_correlation_ir`
        # (main(argv)).
        from . import transaction_correlation_ir as _tci
        _tci_argv = [args.tci_cmd]
        if args.tci_cmd == "responses":
            _tci_argv += ["--requests", args.tci_requests, "--responses", args.tci_responses]
        elif args.tci_cmd == "data":
            _tci_argv += ["--transactions", args.tci_transactions, "--beats", args.tci_beats]
        elif args.tci_cmd == "linkage":
            _tci_argv += ["--event", args.tci_event, "--parent", args.tci_parent,
                          "--children", args.tci_children]
        elif args.tci_cmd == "reconstruct":
            _tci_argv += ["--transactions", args.tci_transactions,
                          "--requests", args.tci_requests,
                          "--responses", args.tci_responses,
                          "--data-transactions", args.tci_data_transactions,
                          "--beats", args.tci_beats]
        if args.json:
            _tci_argv.append("--json")
        raise SystemExit(_tci.main(_tci_argv))
    elif args.cmd == "system-transaction-ir":
        # One shared implementation with `python -m dv_harness.system_transaction_ir`
        # (main(argv)).
        from . import system_transaction_ir as _sti
        _sti_argv = [args.sti_cmd]
        if args.sti_cmd == "build":
            _sti_argv += ["--fabrics", args.fabrics, "--links", args.links]
            if args.json:
                _sti_argv.append("--json")
        raise SystemExit(_sti.main(_sti_argv))
    elif args.cmd == "unknown-uncertainty-registry":
        # One shared implementation with
        # `python -m dv_harness.unknown_uncertainty_registry` (execute_verb(argv)).
        from . import unknown_uncertainty_registry as _uur
        _uur_argv = [args.uur_verb, "--project-root", str(h.root)]
        if args.uur_no_deep:
            _uur_argv.append("--no-deep")
        if args.json:
            _uur_argv.append("--json")
        raise SystemExit(_uur.execute_verb(_uur_argv))
    elif args.cmd == "user-correction-trigger":
        # One shared implementation with
        # `python -m dv_harness.user_correction_trigger` (execute_verb(argv)).
        from . import user_correction_trigger as _uct
        _uct_argv = [args.uct_verb, "--root", str(h.root)]
        if args.uct_min_occurrences is not None:
            _uct_argv += ["--min-occurrences", str(args.uct_min_occurrences)]
        raise SystemExit(_uct.execute_verb(_uct_argv))
    elif args.cmd == "verification-boundary-ir":
        # One shared implementation with
        # `python -m dv_harness.verification_boundary_ir` (main(argv)).
        from . import verification_boundary_ir as _vbi
        _vbi_argv = [args.vbi_cmd]
        if args.vbi_cmd == "build":
            _vbi_argv += ["--boundaries", args.vbi_boundaries]
            if args.json:
                _vbi_argv.append("--json")
        raise SystemExit(_vbi.main(_vbi_argv))
    elif args.cmd == "verification-intake-contract":
        # One shared implementation with
        # `python -m dv_harness.verification_intake_contract`
        # (verification_intake_contract.execute_verb, keyword form).
        from . import verification_intake_contract as _vic
        _vic_text, _vic_code = _vic.execute_verb(
            args.vic_verb, conditions_path=args.vic_conditions, state=args.vic_state,
            as_json=args.json)
        print(_vic_text)
        raise SystemExit(_vic_code)
    elif args.cmd == "verification-intent-ir":
        # One shared implementation with
        # `python -m dv_harness.verification_intent_ir`
        # (verification_intent_ir.execute_verb, keyword form).
        from . import verification_intent_ir as _vii
        _vii_text, _vii_code = _vii.execute_verb(
            args.vii_requirements, source_paths=args.vii_source_paths,
            sys_regmap_path=args.vii_sys_regmap, upf_paths=args.vii_upf, as_json=args.json)
        print(_vii_text)
        raise SystemExit(_vii_code)
    elif args.cmd == "verification-knowledge-graph":
        # One shared implementation with
        # `python -m dv_harness.verification_knowledge_graph` (main(argv)).
        from . import verification_knowledge_graph as _vkg
        _vkg_argv = []
        if args.vkg_evidence_db:
            _vkg_argv += ["--evidence-db", args.vkg_evidence_db]
        if args.vkg_requirements:
            _vkg_argv += ["--requirements", args.vkg_requirements]
        if args.vkg_memory_root:
            _vkg_argv += ["--memory-root", args.vkg_memory_root]
        if args.json:
            _vkg_argv.append("--json")
        raise SystemExit(_vkg.main(_vkg_argv))
    elif args.cmd == "vip-capability-extraction":
        # One shared implementation with
        # `python -m dv_harness.vip_capability_extraction` (main(argv)).
        from . import vip_capability_extraction as _vce
        _vce_argv = ["--index", args.vce_index]
        for _s in (args.vce_project_sources or []):
            _vce_argv += ["--project-source", _s]
        for _s in (args.vce_example_sources or []):
            _vce_argv += ["--example-source", _s]
        for _s in (args.vce_user_guide_reference_md or []):
            _vce_argv += ["--user-guide-reference-md", _s]
        if args.vce_out_dir:
            _vce_argv += ["--out-dir", args.vce_out_dir]
        if args.json:
            _vce_argv.append("--json")
        raise SystemExit(_vce.main(_vce_argv))
    elif args.cmd == "vip-learning-gate":
        # One shared implementation with `python -m dv_harness.vip_learning_gate`
        # (vip_learning_gate.execute_verb, keyword form).
        from . import vip_learning_gate as _vlg
        _vlg_text, _vlg_code = _vlg.execute_verb(
            vip_sources=args.vlg_vip_sources, vip_index_path=args.vlg_vip_index,
            vip_relative_to=args.vlg_vip_relative_to, phy_boundary_path=args.vlg_phy_boundary,
            bind_entries_path=args.vlg_bind_entries, bind_require_tier=args.vlg_require_tier,
            env_manifest_path=args.vlg_env_manifest, as_json=args.json)
        print(_vlg_text)
        raise SystemExit(_vlg_code)
    elif args.cmd == "vplan-baseline":
        # One shared implementation with `python -m dv_harness.vplan_baseline`
        # (execute_verb(argv)).
        from . import vplan_baseline as _vpb
        _vpb_argv = [args.vpb_verb, "--root", str(h.root)]
        if args.vpb_vplan:
            _vpb_argv += ["--vplan", args.vpb_vplan]
        if args.vpb_requirements:
            _vpb_argv += ["--requirements", args.vpb_requirements]
        if args.vpb_configuration_ir:
            _vpb_argv += ["--configuration-ir", args.vpb_configuration_ir]
        if args.vpb_freeze_id:
            _vpb_argv += ["--freeze-id", args.vpb_freeze_id]
        if args.vpb_frozen_by:
            _vpb_argv += ["--frozen-by", args.vpb_frozen_by]
        if args.vpb_spec_version:
            _vpb_argv += ["--spec-version", args.vpb_spec_version]
        if args.vpb_head:
            _vpb_argv += ["--head", args.vpb_head]
        if args.json:
            _vpb_argv.append("--json")
        raise SystemExit(_vpb.execute_verb(_vpb_argv))
    elif args.cmd == "vplan-item-executability-score":
        # One shared implementation with
        # `python -m dv_harness.vplan_item_executability_score` (execute_verb(args)).
        from . import vplan_item_executability_score as _vie
        _vie_argv = ["--items", args.vie_items]
        if args.vie_required_facts:
            _vie_argv += ["--required-facts", args.vie_required_facts]
        if args.json:
            _vie_argv.append("--json")
        raise SystemExit(_vie.execute_verb(_vie_argv))
    elif args.cmd == "waiver-store":
        # One shared implementation with `python -m dv_harness.waiver_store`
        # (execute_verb(argv)).
        from . import waiver_store as _wvs
        _wvs_argv = [args.wvs_verb, "--root", str(h.root)]
        if args.json:
            _wvs_argv.append("--json")
        raise SystemExit(_wvs.execute_verb(_wvs_argv))
    elif args.cmd == "memory-store":
        # Overlap-checked (grpH): genuinely distinct from the `memory` verb
        # above, which is the Markdown/YAML Vault surface (memory_vault.py)
        # only. This wires the pre-existing dv_harness/memory_cli.py script
        # (memory.py's raw JSON MemoryStore/CornerCaseLibrary) for the first
        # time -- same dispatch logic that script's own main() already runs.
        from .memory import (
            MemoryStore as _MStore, MemoryRetriever as _MRetriever, MemoryGC as _MGC,
            CornerCaseLibrary as _CCLibrary, CornerCaseLibraryConsolidator as _CCConsolidator,
            PropertyFilterError as _PropertyFilterError, parse_property_filters as _parse_property_filters,
        )
        _mst_store = _MStore(h.root)
        if args.mst_cmd == "search":
            try:
                _mst_props = _parse_property_filters(args.mst_properties)
            except _PropertyFilterError as e:
                print(json.dumps({"ok": False, "error": "BAD_PROPERTY_FILTER", "detail": str(e)}, ensure_ascii=False))
                raise SystemExit(2)
            print(json.dumps(_MRetriever(_mst_store).search({
                "protocol": args.protocol, "scope": args.scope, "symptoms": args.mst_symptom,
                "text": args.text, "level": args.mst_level, "confidence": args.confidence,
                "status": args.status, "property": _mst_props,
            }, limit=args.limit, rank_by=args.mst_rank_by,
               usefulness_weight=args.mst_usefulness_weight), ensure_ascii=False, indent=2))
        elif args.mst_cmd == "get":
            print(json.dumps(_mst_store.get(args.memory_id), ensure_ascii=False, indent=2))
        elif args.mst_cmd == "deprecate":
            print("OK" if _MGC(_mst_store).deprecate(args.memory_id, args.reason) else "NOT_FOUND")
        elif args.mst_cmd == "corner-case-search":
            _mst_lib = _CCLibrary(h.root)
            print(json.dumps(_mst_lib.search({
                "protocol": args.protocol, "category": args.category, "text": args.text,
            }), ensure_ascii=False, indent=2))
        elif args.mst_cmd == "corner-case-get":
            _mst_lib = _CCLibrary(h.root)
            print(json.dumps(_mst_lib.get(args.ccl_id), ensure_ascii=False, indent=2))
        elif args.mst_cmd == "corner-case-add":
            _mst_lib = _CCLibrary(h.root)
            _mst_record = json.loads(Path(args.mst_record).read_text(encoding="utf-8"))
            if args.mst_resolution:
                _mst_resolution = json.loads(Path(args.mst_resolution).read_text(encoding="utf-8"))
                _mst_rec = _CCConsolidator(_mst_lib).from_resolved_corner_case(_mst_record, _mst_resolution)
            else:
                _mst_rec = _mst_lib.add(_mst_record)
            print(json.dumps(_mst_rec, ensure_ascii=False, indent=2))
        elif args.mst_cmd == "corner-case-deprecate":
            _mst_lib = _CCLibrary(h.root)
            print("OK" if _mst_lib.deprecate(args.ccl_id, args.reason) else "NOT_FOUND")
        elif args.mst_cmd == "index-check":
            print(json.dumps(_mst_store.index_integrity(), ensure_ascii=False, indent=2))
        elif args.mst_cmd == "reindex":
            print(json.dumps(_mst_store.reindex(prune_missing=args.mst_prune_missing), ensure_ascii=False, indent=2))
    elif args.cmd == "schema-config-governance":
        # Overlap-checked (grpH): genuinely distinct from the `schema-compat`
        # verb above -- extends that module's own classify_schema_change()
        # with the FORWARD_COMPATIBLE/MIGRATION_REQUIRED verdicts and the
        # section-146 governance registry, reusing rather than duplicating it.
        from . import schema_config_governance as _scg
        if args.scg_cmd == "registry":
            _scg_text, _scg_code = _scg.execute_verb(action="registry", root=str(h.root), as_json=args.json)
        else:
            _scg_text, _scg_code = _scg.execute_verb(
                action="classify", root=str(h.root), old=args.scg_old, new=args.scg_new,
                schema_filename=args.scg_schema_filename, owning_module=args.scg_owning_module,
                migration_fn=args.scg_migration_fn, corpus=args.scg_corpus, as_json=args.json)
        print(_scg_text)
        raise SystemExit(_scg_code)

if __name__ == "__main__":
    main()
