from __future__ import annotations
import json, time
import os, signal, subprocess, sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime

from dv_harness import lsf_client
from dv_harness.sim_log_analysis import parse_sim_log_file, detect_underreporting
from dv_harness.uvm_generator.regression_list_manager import apply_verdict_to_file

# --- Background job/log monitor cadence (self_check_list.md #41) ----------
#
# #41 asks for a background mechanism that watches every job and simulation
# log and "每隔10分鐘自動確認" -- auto-confirms every 10 minutes. Read as a
# CEILING on the cycle period, not an exact value: checking more often than
# every 10 minutes still satisfies "the operator is never blind for longer
# than 10 minutes", checking less often does not.
#
# The shipped default stays 5 minutes, the cadence the 2026-09-01
# sim-output-layout/background-job-monitor design doc committed to
# (docs/superpowers/specs/2026-09-01-sim-output-layout-and-background-job-
# monitor-design.md:164) -- that is a deliberate choice, inside the ceiling,
# and is left alone.
#
# What was actually broken (gap-close pass, 2026-09-05): the two OTHER real
# entry points into this same watch loop -- `python -m
# dv_harness.regression_reporter --watch` (this module's own argparse) and
# `scripts/powershell/DV_REGRESSION_SNAPSHOT.ps1 -Watch` -- both defaulted to 30 minutes, three
# times slower than the #41 ceiling, so an operator using either of them got
# a monitor that silently violated the spec. Every default now comes from
# DEFAULT_INTERVAL_MINUTES, and any explicitly-requested interval slower than
# SPEC_MAX_INTERVAL_MINUTES is reported out loud rather than accepted
# silently (see interval_compliance() and its two callers).
DEFAULT_INTERVAL_MINUTES = 5
SPEC_MAX_INTERVAL_MINUTES = 10


def interval_compliance(interval_minutes: int) -> dict:
    """Is this watch cadence fast enough for self_check_list.md #41?

    Returns {"interval_minutes", "spec_max_interval_minutes", "compliant",
    "message"}. `compliant` is True when the loop re-confirms job/sim-log
    state at least once every SPEC_MAX_INTERVAL_MINUTES minutes.

    Deliberately advisory, not a clamp: an operator who really wants a
    slow watcher (a long overnight soak on a shared LSF cluster, say) keeps
    that control -- they just cannot get it by accident or in silence."""
    interval = max(1, int(interval_minutes))
    compliant = interval <= SPEC_MAX_INTERVAL_MINUTES
    if compliant:
        message = (f"background job/log monitor cadence {interval}min is within "
                   f"the {SPEC_MAX_INTERVAL_MINUTES}min self_check_list #41 ceiling")
    else:
        message = (f"background job/log monitor cadence {interval}min is SLOWER than "
                   f"the {SPEC_MAX_INTERVAL_MINUTES}min self_check_list #41 ceiling: "
                   f"jobs and simulation logs can go unconfirmed for up to "
                   f"{interval} minutes")
    return {"interval_minutes": interval,
            "spec_max_interval_minutes": SPEC_MAX_INTERVAL_MINUTES,
            "compliant": compliant,
            "message": message}


def load_jobs(project_root: Path):
    d=project_root/'.dv-harness'/'lsf'/'jobs'
    jobs=[]
    if not d.exists(): return jobs
    for p in sorted(d.glob('*.json')):
        try:
            x=json.loads(p.read_text(encoding='utf-8')); x['_file']=str(p); jobs.append(x)
        except Exception: pass
    return jobs

def get_job(project_root: Path, job_id):
    """Single-job lookup on top of load_jobs() -- the one shared
    implementation dv_harness/dashboard.py's GET /api/lsf/jobs/<job_id> and
    dv_harness/cli.py's `lsf <job_id>` both call, so job-id matching (str()
    comparison -- job_id in the on-disk JSON may be an int or a str
    depending on how the LSF client wrote it, and CLI/URL job ids always
    arrive as str) lives in exactly one place. Returns None if no job with
    that id exists, never raises."""
    for j in load_jobs(project_root):
        if str(j.get('job_id')) == str(job_id):
            return j
    return None

def fmt(v, default='-'):
    if v is None or v=='': return default
    return str(v)

def attach_job_memory_columns(root: Path, rows):
    """Join each snapshot row with that job's Job-tier memory record, adding
    the three debug-knowledge columns the Phase 11 spec names -- confidence,
    failure signature, prior related knowledge -- to the SINGLE per-job view
    (2026-09-04 gap closure).

    Before this, those three lived only inside
    `.dv-harness/memory/job/JOB-<id>-TERMINAL-RECONCILE.json` and appeared in
    no per-job view at all, so the harness could have already matched a
    failure against five prior vault cases and the engineer reading the
    regression table would see no sign of it.

    Mutates and returns `rows` in place. A row that already carries the
    columns (built by `to_snapshot_row(..., job_memory=...)`) is left alone;
    a job with no memory record simply gains nothing and renders as `-`."""
    for row in rows:
        if 'failure_signature' in row:
            continue
        record = lsf_client.load_job_tier_memory_record(root, row.get('job_id'))
        if not record:
            continue
        row['confidence'] = record.get('confidence')
        row['failure_signature'] = lsf_client.format_failure_signature(record.get('failure_signature'))
        row['prior_related_knowledge_count'] = len(record.get('prior_related_knowledge') or [])
    return rows


def render_snapshot(jobs):
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    counts={}
    for j in jobs:
        s=fmt(j.get('lsf_status'),'UNKNOWN'); counts[s]=counts.get(s,0)+1
    reg_ids=sorted({j.get('regression_id') for j in jobs if j.get('regression_id')})
    header=[f'DV Agent Harness L5 - Periodic Regression Snapshot',f'Snapshot Time: {now}']
    if reg_ids:
        header.append('Regression ID : '+(', '.join(reg_ids)))
    lines=header + [
           'SUMMARY: '+ ' | '.join([f'Total: {len(jobs)}']+[f'{k}: {v}' for k,v in sorted(counts.items())]),'',
           f"{'Job':<10} {'Pattern / Combination':<36} {'LSF':<10} {'DV Analysis':<18} {'UVM_ERR':<9} {'UVM_FATAL':<10} {'Confidence':<11} {'Failure Signature':<32} {'Prior':<6} Agent Action / Note",
           '-'*190]
    attention=[]
    for j in jobs:
        jid=fmt(j.get('job_id')); pat=fmt(j.get('pattern')); lsf=fmt(j.get('lsf_status'),'UNKNOWN')
        dv=fmt(j.get('dv_analysis_status') or j.get('sim_status'),'UNKNOWN')
        ue=fmt(j.get('uvm_error_count'),'pending' if lsf=='DONE' else '-')
        uf=fmt(j.get('uvm_fatal_count'),'pending' if lsf=='DONE' else '-')
        # Confidence / Failure Signature / Prior are populated from the Job
        # Memory record by attach_job_memory_columns() (or by
        # to_snapshot_row(job_memory=...)). A job that has no such record yet
        # renders '-' -- honestly "not computed", never a fabricated level.
        conf=fmt(j.get('confidence'),'-')
        sig=fmt(j.get('failure_signature'),'-')
        prior=fmt(j.get('prior_related_knowledge_count'),'-')
        action=fmt(j.get('agent_action') or j.get('root_cause_status') or j.get('kill_reason'),'monitoring')
        lines.append(f'{jid:<10} {pat[:35]:<36} {lsf:<10} {dv:<18} {ue:<9} {uf:<10} '
                      f'{conf:<11} {sig[:31]:<32} {prior:<6} {action}')
        if lsf=='EXIT' or dv in ('FAIL','ROOT_CAUSE','RERUN_REQUIRED') or (isinstance(j.get('uvm_error_count'),int) and j.get('uvm_error_count',0)>0):
            attention.append(f"- {jid} {pat}: LSF={lsf}, DV={dv}, UVM_ERROR={ue}, action={action}")
    lines += ['', 'ATTENTION'] + (attention or ['- none'])
    lines += ['', 'NEXT ACTIONS','- Analyze DONE jobs whose DV result is still UNKNOWN/pending.','- Continue incremental monitoring of RUN jobs.','- Triage EXIT/FAIL jobs and rerun fixed patterns when ready.']
    return '\n'.join(lines)

def registered_job_ids_on_disk(root: Path) -> list:
    """Every job id dv_harness has a persisted JobState for, read straight
    from `<root>/.dv-harness/lsf/jobs/*.json` filenames (no JSON parsing --
    a corrupt file must not hide the id of the job it belongs to). Returns
    [] when the directory does not exist yet.

    Public (not underscore-prefixed) because it is the ONE shared
    implementation of this glob: dv_harness/cli.py's `lsf-reconcile --all`
    and `lsf-auto-kill-scan` handlers both call it too, instead of each
    re-inlining the same `jobs_dir.glob("*.json")` expression."""
    d = root.joinpath(*lsf_client.JOBS_DIR_NAME)
    if not d.exists():
        return []
    ids = []
    for p in d.glob("*.json"):
        try:
            ids.append(int(p.stem))
        except ValueError:
            continue
    return sorted(ids)


def _job_still_owes_reconciliation(state) -> bool:
    """Is there anything a further live LSF query of this registered job
    could still tell us?

    True while EITHER analysis is still owed (sim_status still UNKNOWN or
    RUNNING -- no determinate PASS/FAIL verdict recorded yet) OR LSF itself
    has not yet reported the job finished (lsf_status not DONE/EXIT/KILLED).
    False only for a job that is BOTH lsf-terminal AND already analyzed.

    BUG FIX (2026-09-01 scoped re-review): the reconcile set used to
    include EVERY job id ever registered on disk, unbounded, with nothing
    ever pruning it -- so every job ever registered was re-queried against
    LSF forever. On the real server LSF keeps a finished job only for
    CLEAN_PERIOD (a fact this repo's own generated
    `uvm_generator/templates/sim_scripts/lsf_regress.sh` documents); once a
    job ages past that window `bjobs <id>` returns no record at all,
    reconcile_job() maps that empty record to lsf_status="UNKNOWN", and
    reconcile_batch() PERSISTS it -- silently overwriting the job's real,
    previously recorded terminal DONE/EXIT status with UNKNOWN. That is
    exactly the decay of recorded evidence CLAUDE.md's "LSF DONE is not
    equal to DV PASS" rule exists to prevent, and it also re-armed the
    CRITICAL sim_status -> ANALYSIS_OWED discrepancy against a status the
    harness itself had just falsified.

    The condition is deliberately OR, not AND: a job that is lsf-terminal
    but NOT yet analyzed must STAY in the set -- that aged-out-but-still-
    owed case is the whole reason the live+disk union exists (see
    test_registered_job_absent_from_live_jobs_is_still_analyzed). Only the
    fully settled tail drops out."""
    return (state.sim_status in ("UNKNOWN", "RUNNING")
            or state.lsf_status not in ("DONE", "EXIT", "KILLED"))


def _escalate_uvm_fatal_burst_if_needed(root: Path, jobs_for_snapshot: list) -> None:
    """Escalation-ONLY UVM_FATAL burst check (2026-09-03, see
    dv_harness/escalation_notify.py), extracted into its own function so it
    is directly testable without faking run_reconciliation_cycle()'s whole
    live/disk job-discovery machinery. Best-effort, wrapped exactly like
    every other real side-effect in that function ("a persistence problem
    here must never break this cycle's own real reconciliation work") -- a
    config-read or transport hiccup must never kill the watcher. Reads
    `.dv-harness/config.json`'s `escalation` block fresh each call (cheap:
    one small JSON file) rather than threading a notifier through
    ensure_watcher_running()/_run_one_cycle()/main(), keeping this the one
    and only place in this module that needs to know about escalation at
    all. `jobs_for_snapshot` rows follow to_snapshot_row()'s shape
    (job_id/uvm_fatal_count among others) -- a row with uvm_fatal_count
    None/0 (unregistered jobs, or a job with no fatal) never counts."""
    try:
        fatal_job_ids = [row["job_id"] for row in jobs_for_snapshot
                         if (row.get("uvm_fatal_count") or 0) > 0]
        if fatal_job_ids:
            from . import config as _config
            from . import escalation_notify as _escalation
            from . import regression_tiers as _tiers
            cfg = _config.load_config(root)
            notifier = _escalation.notifier_from_config(cfg.get("escalation"))
            # Tiered threshold (2026-09-04, Section 3 item 3c): a SMOKE run's
            # handful of fixed sanity patterns and a WEEKLY full-universe run
            # are not the same statistical population, so the same absolute
            # fatal count does not mean the same thing in both. Reads the
            # active-tier record written by `dv-harness regression-tier run`;
            # returns None when no tiered run was declared, which keeps the
            # flat pre-existing threshold exactly as it was.
            active = _tiers.read_active_tier(root)
            notifier.uvm_fatal_burst(
                len(fatal_job_ids), total_jobs=len(jobs_for_snapshot),
                job_ids=fatal_job_ids,
                tier=(active or {}).get("tier"),
                threshold=_tiers.active_uvm_fatal_burst_threshold(root, cfg))
    except Exception as e:
        print(f"[reconciliation_cycle] escalation notify failed: {e}", flush=True)


def _write_reconciliation_evidence_if_configured(root: Path, reconciled: dict) -> None:
    """Best-effort DuckDB evidence-store write for this cycle's reconciled
    jobs (2026-09-03, evidence-db-wiring step 1 -- see
    dv_harness/evidence_db.py's own module docstring for the real data
    shapes this mirrors). Extracted into its own function for the same
    reason _escalate_uvm_fatal_burst_if_needed() above is: directly
    testable without faking this function's whole live/disk job-discovery
    machinery. Wrapped exactly like that function too ("a persistence
    problem here must never break this cycle's own real reconciliation
    work") and reads its own tiny `evidence_db` config block fresh from
    `.dv-harness/config.json` each call rather than threading an
    EvidenceStore through every function signature in this module --
    same reasoning, same convention, so this stays the one and only place
    in this module that needs to know about the evidence store at all.

    For every reconciled job: insert_job_state(state) unconditionally -- a
    job's own state IS the fact being recorded, pass, fail, or still
    pending. insert_job_memory_record() additionally fires for every job
    that really has a Job-tier memory record on disk by this point in the
    cycle (see the "MEMORY-TIER MIRROR" paragraph below).
    insert_regression_verdict() additionally fires under the SAME
    condition the regression-list safety net above (`state.pattern and
    verdict in ("PASSED", "FAILED")`, the `apply_verdict_to_file()` call
    site a few dozen lines up in this same function) uses to decide whether
    a job has a determinate verdict and a known pattern -- mirrored here as
    `state.pattern and state.sim_status in ("PASS", "FAIL")` since
    state.sim_status is set from that exact same `verdict` in lock-step
    (PASSED->PASS, FAILED->FAIL) a few lines above that call site, and
    `verdict` itself is a local variable no longer in scope by the time
    `reconciled` reaches this function.

    BUG FIX (post-review fault injection, 2026-09-03): this used to have
    only an OUTER try/except around the whole per-job loop. A single bad
    insert (e.g. a locked row, a constraint violation for one specific job)
    raised out of the loop body, which the outer except then caught -- but
    by then every job after the bad one in iteration order had never even
    been attempted, silently losing their evidence too. Each job's own
    insert(s) now get their OWN inner try/except, same print-and-continue
    discipline `_write_normalized_evidence_if_configured()` below already
    uses per-job -- one bad job is isolated to itself and every sibling job
    in the same cycle still gets its real evidence written.

    MEMORY-TIER MIRROR (2026-09-04, 5-level-memory-engine gap-close):
    `EvidenceStore.insert_job_memory_record()` -- the one function in
    evidence_db.py whose entire purpose is mirroring the Memory engine's
    JOB tier into DuckDB, and the only reason the `job_memory_records` and
    `failure_signatures` tables exist -- had ZERO callers anywhere outside
    evidence_db.py and its own unit tests (full-repo grep, 2026-09-04),
    while both of its siblings in this very function were wired. So a real
    reconciliation cycle wrote the job's `jobs` row and its
    `regression_verdicts` row but never the job-memory row, and
    `failure_signatures` -- the cross-run "has this exact failure shape
    been seen before, how often" aggregate the whole table was built for --
    stayed permanently empty no matter how many real failures reconciled.
    This is that missing call site.

    The record is READ BACK from the real Memory store
    (`lsf_client.load_job_tier_memory_record()`, the existing named reader,
    keyed by the same deterministic `job_tier_memory_id(jid)` both writers
    use) rather than re-derived here. Two reasons, both real:
      * `_upsert_job_tier_memory_record()` runs EARLIER in this same cycle
        (the per-job analysis loop above calls it once the sim.log epilogue
        has been parsed, which is what upgrades a premature `job_result`
        classification to the accurate `job_failure` one, with its
        `failure_signature`/`prior_related_knowledge` attached). Reading at
        THIS point therefore mirrors the final, best-evidence record --
        re-deriving it here would produce a second, possibly disagreeing
        copy of a record the Memory tier already owns.
      * What lands in DuckDB is then, by construction, what the JSON
        Memory tier actually holds. The mirror cannot silently drift from
        the thing it mirrors.
    A job with no Job-tier memory record yet (never reached a terminal
    reconcile, or a project with no memory store) returns None and is
    skipped -- an absent record is a real, normal state, never backfilled
    with an invented one."""
    try:
        from . import config as _config
        cfg = _config.load_config(root).get("evidence_db", {})
        if not cfg.get("enabled", True):
            return
        from . import evidence_db as _evidence_db
        db_path = _evidence_db.default_db_path(root)
        with _evidence_db.EvidenceStore(db_path) as store:
            for jid, (state, _discrepancies) in reconciled.items():
                try:
                    store.insert_job_state(state)
                    job_memory_record = lsf_client.load_job_tier_memory_record(root, jid)
                    if job_memory_record is not None:
                        store.insert_job_memory_record(job_memory_record)
                    if state.pattern and state.sim_status in ("PASS", "FAIL"):
                        # git_sha (cross-run-trend task, 2026-09-03): the real
                        # source SHA this job ran against, already captured on
                        # JobState and already stored in the `jobs` row above.
                        # Passing it here is what lets
                        # `trend_analysis.detect_pattern_regressions()` attribute
                        # a PASS->FAIL transition to a real commit RANGE
                        # (last-good..first-bad) instead of merely noticing the
                        # flip. A JobState with no recorded SHA passes None and
                        # the transition is reported as un-bisectable -- never
                        # attributed to a guessed commit.
                        store.insert_regression_verdict(
                            state.pattern, state.sim_status == "PASS", job_id=state.job_id,
                            git_sha=state.git_sha)
                except Exception as e:
                    print(f"[reconciliation_cycle] job {jid} evidence store write failed: {e}",
                          flush=True)
    except Exception as e:
        print(f"[reconciliation_cycle] evidence store write failed: {e}", flush=True)


def _write_normalized_evidence_if_configured(root: Path, reconciled: dict) -> None:
    """Best-effort vip_distill.py -> EvidenceStore.normalized_evidence
    bridge for this cycle's reconciled jobs (2026-09-03, evidence-db-wiring
    STEP 2). This is the exact gap both sides of the pipeline had already
    disclosed as open when they landed independently: vip_distill.py's own
    report noted `write_normalized_evidence()`'s output "has nowhere to
    land" and that a real evidence_db.py schema/loader "must be reconciled
    ... once that workstream lands" (see
    .work/governance-vip-distill-report.md's "Follow-ups" #1/#2); this
    module's own evidence-db-wiring step 1 left `insert_normalized_evidence`
    /vip_distill among the "remaining-unwired API surface" (see
    .work/evidence-db-wiring-step1-report.md). This function is that
    reconciliation: the caller lives here (not inside vip_distill.py itself
    -- its own AST-enforced test, test_vip_distill.py's
    test_module_does_not_import_orchestration_or_memory_modules(),
    permanently forbids it importing `evidence_db`/`regression_reporter`/
    `duckdb`/`lsf_client`/`memory_router`/`memory_vault`), using
    vip_distill's Normalized Evidence envelope UNCHANGED (this module never
    re-shapes or second-guesses it, only stores it).

    Same discipline as `_write_reconciliation_evidence_if_configured()` and
    `_escalate_uvm_fatal_burst_if_needed()` above: try/except, print-and-
    continue -- a distill/store failure here must never break this cycle's
    own real reconciliation work. Deliberately reuses the SAME `evidence_db`
    config block those functions read (not a second config key): the
    `normalized_evidence` table lives in the same `evidence.duckdb` file
    this cycle's `jobs`/`regression_verdicts` rows already land in, so one
    on/off switch controls the whole evidence store rather than two
    independently toggleable ones.

    For every reconciled job with a real `state.sim_log`: `distill_sim_log()`
    alone (fresh `log_path` parse -- mirrors
    `_write_reconciliation_evidence_if_configured()`'s own "reads fresh
    rather than threaded" precedent, not the earlier per-job loop's already-
    parsed result a few dozen lines up in this same function) is what gets
    normalized and stored, NOT a `merge_evidence()` of `distill_sim_log()`
    plus `distill_job_record()`. Deliberate: `state.uvm_error_count`/
    `uvm_fatal_count`/`sim_status` were themselves DERIVED from this SAME
    log's epilogue a few lines above in this same function's per-job loop
    (`if verdict == "PASSED": state.sim_status = "PASS"`, etc.) -- so a
    `distill_job_record(asdict(state))` envelope would restate the identical
    real fact `distill_sim_log()` already captured, only under a different
    source's own verdict vocabulary ("PASS" vs. sim_log's "PASSED").
    `merge_evidence()`'s combined-verdict logic (by design, per vip_distill's
    own docstring: each source's real vocabulary is "never coerced") reads
    that cosmetic vocabulary mismatch as genuinely conflicting evidence and
    reports `AMBIGUOUS` -- which would misrepresent a real, unambiguous
    PASS/FAIL as ambiguous on every single job, not a real disagreement
    worth surfacing. `distill_sim_log()` alone is also the richer of the two
    sources here (full classified signatures + epilogue detail, not just
    passthrough fields), so nothing is lost by not merging. A job with no
    `sim_log` (nothing for vip_distill to normalize) is silently skipped,
    not an error."""
    try:
        from . import config as _config
        cfg = _config.load_config(root).get("evidence_db", {})
        if not cfg.get("enabled", True):
            return
        from . import evidence_db as _evidence_db
        from . import vip_distill as _vip_distill
        db_path = _evidence_db.default_db_path(root)
        with _evidence_db.EvidenceStore(db_path) as store:
            for jid, (state, _discrepancies) in reconciled.items():
                if not state.sim_log:
                    continue
                try:
                    envelope = _vip_distill.distill_sim_log(
                        log_path=state.sim_log, job_id=state.job_id,
                        pattern=state.pattern, run_dir=state.run_dir)
                    store.insert_normalized_evidence(envelope)
                except Exception as e:
                    print(f"[reconciliation_cycle] job {jid} normalized evidence distill "
                          f"failed: {e}", flush=True)
    except Exception as e:
        print(f"[reconciliation_cycle] normalized evidence store write failed: {e}", flush=True)


def run_reconciliation_cycle(root: Path, vcuser: str, uvm_root_path: Path) -> str:
    """One pass of Part 2's reconciliation cycle: discover every live job
    under vcuser, MERGE that set with every job dv_harness already has a
    registered JobState for on disk, reconcile+analyze the registered ones,
    apply Part 3's regression-list safety net for any job with a real
    PASS/FAIL verdict and a known pattern, then render and persist the
    snapshot.

    BUG FIX (2026-09-01 whole-branch review): the job set was previously an
    INTERSECTION -- only jobs that appeared in discover_live_jobs()'s output
    AND had a registered JobState were reconciled -- which silently violated
    the spec's own "Merge both sets" wording (Part 2 step 3). A registered
    job that has aged out of the `bjobs -u` listing then never got
    reconciled or analyzed again, so it could never be observed reaching
    DONE/EXIT and Part 3's safety net never fired for it. reconcile_batch()
    queries LSF by explicit job id, not by account, so it still returns a
    real, current status for a registered job that is absent from this
    poll's live_jobs list for any reason.

    The disk-sourced half of that union is BOUNDED by
    _job_still_owes_reconciliation() (BUG FIX, 2026-09-01 scoped
    re-review): a job that is both lsf-terminal and already analyzed drops
    out permanently instead of being re-queried forever and eventually
    having its real DONE/EXIT status overwritten with UNKNOWN once LSF's
    CLEAN_PERIOD forgets it. Such a job still appears in the snapshot,
    rendered from its persisted JobState rather than from a fresh poll.

    A single failed discover_live_jobs()/reconcile_batch() call is caught
    and logged rather than raised, per the spec's error-handling
    requirement -- one bad LSF poll must not kill the whole cycle."""
    try:
        live_jobs = lsf_client.discover_live_jobs(vcuser)
    except lsf_client.LsfUnavailableError as e:
        print(f"[reconciliation_cycle] discover_live_jobs failed: {e}", flush=True)
        live_jobs = []

    # Disk half of the union, minus the settled tail.
    pending_ids = set()
    settled_states = {}
    for jid in registered_job_ids_on_disk(root):
        try:
            state = lsf_client.load_job_state(root, jid)
        except Exception as e:
            # An unreadable/corrupt state file (OSError, or the bare
            # json.JSONDecodeError load_job_state() lets through) cannot
            # PROVE the job is settled, so keep reconciling it rather than
            # silently dropping it -- the same conservative stance
            # registered_job_ids_on_disk() takes by reading filenames
            # instead of parsing JSON. Broad by design: this filter must
            # never be the thing that kills a cycle.
            print(f"[reconciliation_cycle] could not load state for job {jid}: {e}", flush=True)
            pending_ids.add(jid)
            continue
        if _job_still_owes_reconciliation(state):
            pending_ids.add(jid)
        else:
            settled_states[jid] = state

    # Live half of the union: a discovered job dv_harness has a registered
    # JobState for. Held to the same settled filter as the disk half.
    for j in live_jobs:
        jid = j["job_id"]
        if jid in pending_ids or jid in settled_states:
            continue
        state = lsf_client.load_job_state(root, jid)
        if state.pattern is not None or state.sim_log is not None:
            pending_ids.add(jid)
    registered_ids = sorted(pending_ids)

    if registered_ids:
        try:
            reconciled = lsf_client.reconcile_batch(root, registered_ids)
        except Exception as e:
            print(f"[reconciliation_cycle] reconcile_batch failed: {e}", flush=True)
            reconciled = {}
    else:
        reconciled = {}

    for jid, (state, _discrepancies) in reconciled.items():
        if state.lsf_status not in ("DONE", "EXIT", "KILLED"):
            continue
        if not state.sim_log:
            continue
        try:
            parsed = parse_sim_log_file(state.sim_log)
        except OSError as e:
            print(f"[reconciliation_cycle] could not read {state.sim_log}: {e}", flush=True)
            continue
        epilogue = parsed.get("epilogue")
        if epilogue:
            state.uvm_error_count = epilogue.get("uvm_error") or 0
            state.uvm_fatal_count = epilogue.get("uvm_fatal") or 0
        verdict = (epilogue or {}).get("verdict")
        try:
            # NOTE on which detect_underreporting() branches are live HERE:
            # state.uvm_error_count/uvm_fatal_count were just overwritten
            # FROM this same epilogue a few lines above, so at this specific
            # call site the declared COUNTS can never disagree with the
            # epilogue's -- UNDER_REPORTED_EPILOGUE_UVM_FATAL and
            # _UVM_ERROR (and only those two) are structurally unable to
            # fire. That is intentional, not broken; detect_underreporting()
            # keeps them for its other callers (e.g. an agent-populated
            # JobState never derived from the epilogue at all).
            # UNDER_REPORTED_EPILOGUE_VERDICT is NOT dead here: it fires on
            # epilogue verdict == "FAILED" with both declared counts zero,
            # a real parser-permitted combination (a timeout, or an
            # objection/phase-declared failure that raised no UVM_ERROR or
            # UVM_FATAL) and a meaningful "LSF DONE is not equal to DV PASS"
            # signal worth logging. Also live: the branches comparing the
            # log BODY's raw marker/signature counts against what the
            # epilogue declared, which catch a simulation whose final tally
            # under-reports its own log content.
            discrepancies = detect_underreporting(asdict(state), parsed)
            for d in discrepancies:
                print(f"[reconciliation_cycle] job {jid} under-reporting: {d}", flush=True)
            if verdict == "PASSED":
                state.sim_status = "PASS"
            elif verdict == "FAILED":
                state.sim_status = "FAIL"
            # BUG FIX (2026-09-01 whole-branch review): an INDETERMINATE
            # verdict (no epilogue, or an epilogue with no PASSED/FAILED)
            # must NOT advance sim_status. Stamping "ANALYZED" here left the
            # job looking analyzed while its verdict was never actually
            # determined, and permanently silenced reconcile_job()'s
            # CRITICAL sim_status -> ANALYSIS_OWED discrepancy (which only
            # fires while sim_status is UNKNOWN/RUNNING, and is the sole
            # trigger for the Job-tier memory write). Per CLAUDE.md's "LSF
            # DONE is not equal to DV PASS", an unparseable/truncated log
            # must keep raising the analysis-owed alarm on every later
            # reconciliation pass, never be silently guessed at.
            lsf_client.save_job_state(root, state)

            # Phase 11 (2026-09-03, obsidian-memory-debugflow task --
            # Regression Integration): re-upsert the SAME deterministic
            # Job-tier memory record `reconcile_batch()` (inside
            # `lsf_client.reconcile_batch()`, called a few lines above via
            # this cycle's `registered_ids` pass) already wrote for this
            # job, now that state.uvm_error_count/uvm_fatal_count reflect
            # this REAL sim.log epilogue parse rather than whatever they
            # were at the earlier, coarser bjobs-only reconcile point -- see
            # lsf_client._upsert_job_tier_memory_record()'s own "THE GAP
            # THIS CLOSES" docstring for why a second call site is needed
            # rather than relying on the earlier one alone. Real UVM_ERROR/
            # UVM_FATAL counts (or a real "FAILED" epilogue verdict with a
            # terminal_signature -- e.g. a timeout/objection failure that
            # raised neither) upgrade an earlier `job_result` classification
            # to the accurate `job_failure` one, this time with a real
            # failure_signature + prior_related_knowledge search attached.
            # Best-effort, same discipline as every other call site of this
            # function: a persistence problem here must never break this
            # cycle's own real reconciliation work already completed above.
            try:
                lsf_client._upsert_job_tier_memory_record(root, jid, state)
            except Exception as e:
                print(f"[reconciliation_cycle] job {jid} memory upsert failed: {e}", flush=True)

            if state.pattern and verdict in ("PASSED", "FAILED"):
                regression_list_path = Path(uvm_root_path) / "regression.list"
                apply_verdict_to_file(regression_list_path, state.pattern, verdict == "PASSED")
        except Exception as e:
            print(f"[reconciliation_cycle] job {jid} analysis failed: {e}", flush=True)
            continue

    jobs_for_snapshot = []
    seen_ids = set()
    for j in live_jobs:
        jid = j["job_id"]
        seen_ids.add(jid)
        if jid in reconciled:
            state, _ = reconciled[jid]
            jobs_for_snapshot.append(lsf_client.to_snapshot_row(state, agent_action="monitoring"))
        elif jid in settled_states:
            # Registered, lsf-terminal AND already analyzed: deliberately
            # not re-queried this cycle (see
            # _job_still_owes_reconciliation()), but it is still a real job
            # of this regression, so render it from its persisted state.
            # Falling through to the else-branch below would mislabel it
            # UNREGISTERED.
            jobs_for_snapshot.append(
                lsf_client.to_snapshot_row(settled_states[jid], agent_action="monitoring"))
        else:
            # An unregistered row's status goes through the SAME
            # map_bjobs_stat_to_lsf_status() normalization a registered row
            # gets via to_snapshot_row()/reconcile_job(); otherwise one
            # column would mix raw LSF codes (PSUSP/USUSP/UNKWN/ZOMBI) with
            # normalized ones (PEND/RUN/DONE/EXIT/UNKNOWN) row by row.
            jobs_for_snapshot.append({
                "job_id": jid, "pattern": j.get("job_name"),
                "lsf_status": lsf_client.map_bjobs_stat_to_lsf_status(j.get("stat")),
                "dv_analysis_status": "UNREGISTERED",
                "uvm_error_count": None, "uvm_fatal_count": None,
                "agent_action": "monitoring", "note": None})

    # Registered jobs that this poll's live_jobs did not list (see the
    # union in the docstring) still belong in the snapshot -- they were
    # reconciled against LSF by explicit job id and carry a real status.
    for jid in registered_ids:
        if jid in seen_ids or jid not in reconciled:
            continue
        state, _ = reconciled[jid]
        jobs_for_snapshot.append(lsf_client.to_snapshot_row(state, agent_action="monitoring"))

    # Settled registered jobs (terminal + already analyzed) that this poll
    # did not list either: rendered from their persisted JobState, never
    # re-queried. Dropping them from the reconcile set must not also drop
    # them out of the regression's own snapshot.
    for jid, state in sorted(settled_states.items()):
        if jid in seen_ids:
            continue
        jobs_for_snapshot.append(lsf_client.to_snapshot_row(state, agent_action="monitoring"))

    _escalate_uvm_fatal_burst_if_needed(root, jobs_for_snapshot)
    _write_reconciliation_evidence_if_configured(root, reconciled)
    _write_normalized_evidence_if_configured(root, reconciled)

    # Join AFTER every writer above (reconcile_batch() and the epilogue-parse
    # re-upsert) has finished writing this cycle's Job-tier memory records, so
    # the snapshot shows this cycle's failure signature / prior-knowledge
    # matches rather than the previous cycle's.
    snapshot = render_snapshot(attach_job_memory_columns(root, jobs_for_snapshot))
    snapshot_path = root / ".dv-harness" / "lsf" / "latest_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")
    print(snapshot, flush=True)
    return snapshot


WATCHER_PID_FILE = ('.dv-harness', 'lsf', 'watcher.pid')


def _pid_file_path(root: Path) -> Path:
    return root.joinpath(*WATCHER_PID_FILE)


def _pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        # BUG FIX (2026-09-01, found while wiring up the `lsf-watch-*` CLI
        # commands): os.kill(pid, 0) on Windows is implemented via
        # GenerateConsoleCtrlEvent, which only succeeds when called by the
        # process that originally spawned the target's console/process
        # group (or one of that process's still-live descendants) -- a
        # relationship real usage never has, since every dv-harness CLI
        # invocation (including the one that spawned the watcher via
        # ensure_watcher_running()) is a separate, short-lived process
        # that exits right after spawning/checking. A LATER, unrelated
        # process checking the pid (e.g. every real `lsf-watch-status`
        # call) got OSError WinError 87 from the os.kill(pid, 0) call
        # below, which the `except OSError: return False` branch then
        # silently mistook for "not running" even while the watcher was
        # genuinely alive. Query the OS directly via OpenProcess/
        # GetExitCodeProcess instead, which has no such console-lineage
        # restriction.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        # restype/argtypes are mandatory here, not cosmetic: ctypes defaults
        # every unprototyped return value to C int, which TRUNCATES a 64-bit
        # HANDLE to 32 bits on 64-bit Windows -- the truncated value can be
        # a bogus handle (and is then passed to GetExitCodeProcess/
        # CloseHandle) or can even come back as 0 and be misread as "process
        # not running".
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by a different user/UID -- alive,
        # just not signalable by us. Must not be conflated with "not
        # running", or ensure_watcher_running()/stop_watcher() would treat
        # a live watcher as dead.
        return True
    except OSError:
        return False
    except AttributeError:
        # os.kill(pid, 0) is not universally available; treat as unknown
        # rather than crash -- caller falls through to "start a new one".
        return False
    return True


def ensure_watcher_running(root: Path, vcuser: str, uvm_root_path,
                            interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> dict:
    """Start the --watch loop as a detached background process if one is
    not already running for this project, tracked via a PID file. A stale
    PID file (process no longer alive) is detected and cleaned up
    automatically rather than blocking a fresh start.

    The child's stdio is redirected to `.dv-harness/lsf/watcher.log`
    (append) with stdin on DEVNULL. This is load-bearing on both platforms
    (BUG FIX, 2026-09-01 whole-branch review): on POSIX the child would
    otherwise inherit the launching agent's own stdout pipe and hold its
    write end open forever -- hanging whatever ran `dv-harness
    lsf-watch-start` -- and would die with an uncaught BrokenPipeError out
    of its own print() calls once the reader went away; on Windows
    DETACHED_PROCESS gives the child no console at all, so every log line,
    including the reconciliation cycle's under-reporting findings and its
    failure logging, was silently discarded. The log file also gives those
    findings a durable, discoverable home."""
    pid_path = _pid_file_path(root)
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text().strip())
        except ValueError:
            existing_pid = None
        if existing_pid is not None and _pid_is_running(existing_pid):
            return {"started": False, "pid": existing_pid}
        pid_path.unlink()

    argv = [sys.executable, "-m", "dv_harness.regression_reporter",
            "--project-root", str(root), "--watch",
            "--interval-minutes", str(interval_minutes),
            "--vcuser", vcuser, "--uvm-root-path", str(uvm_root_path)]
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    log_path = root / ".dv-harness" / "lsf" / "watcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                 stdout=log_fh, stderr=subprocess.STDOUT,
                                 **popen_kwargs)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    return {"started": True, "pid": proc.pid}


def stop_watcher(root: Path) -> dict:
    """Terminate the running watcher (if any) and remove its PID file.
    A missing PID file is a no-op, not an error -- nothing was running.

    `stopped` is honest about what actually happened: True only when a live
    process was found and signaled. A tracked PID that was already dead
    yields {"stopped": False} with the stale PID file still cleaned up --
    cleaning up a stale file is not the same as stopping a running
    watcher, and reporting it as such (the pre-2026-09-01 behavior) hid
    watchers that had crashed on their own."""
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"stopped": False}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid_path.unlink()
        return {"stopped": False}
    was_running = _pid_is_running(pid)
    if was_running:
        os.kill(pid, signal.SIGTERM if os.name != "nt" else 15)
    pid_path.unlink()
    return {"stopped": was_running}


def watcher_status(root: Path) -> dict:
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        return {"running": False, "pid": None}
    return {"running": _pid_is_running(pid), "pid": pid if _pid_is_running(pid) else None}


def main(project_root='.', once=True, interval_minutes=DEFAULT_INTERVAL_MINUTES,
         vcuser=None, uvm_root_path=None):
    """Last-resort exception guard around each cycle (2026-09-01
    whole-branch review): run_reconciliation_cycle() isolates only
    discover_live_jobs()'s LsfUnavailableError and the per-job analysis
    block. Other real exceptions can still escape -- load_job_state()'s bare
    json.JSONDecodeError on a corrupt jobs/<id>.json, PermissionError/other
    OSError subtypes out of reconcile_batch()'s subprocess.run calls, an
    OSError from the snapshot mkdir/write_text -- and any one of them would
    permanently kill a background watcher meant to run unattended for hours.
    The guard belongs HERE, at the loop level, not inside
    run_reconciliation_cycle(): one bad cycle must log and fall through to
    the next time.sleep(), while a single-shot (`once=True`) caller still
    gets its exception surfaced by the re-raise below."""
    root = Path(project_root).resolve()
    if not once:
        # One honest cadence line at the top of the watcher's own log
        # (ensure_watcher_running() redirects this child's stdout to
        # .dv-harness/lsf/watcher.log), so the cadence a running watcher is
        # actually on is discoverable without re-deriving it from argv.
        print(f"[watch loop] {interval_compliance(interval_minutes)['message']}",
              flush=True)
    while True:
        try:
            _run_one_cycle(root, vcuser, uvm_root_path)
        except Exception as e:
            if once:
                raise
            print(f"[watch loop] cycle failed: {e}", flush=True)
        if once:
            break
        time.sleep(max(1, interval_minutes) * 60)


def _run_one_cycle(root: Path, vcuser, uvm_root_path) -> None:
    if vcuser:
        uvm_root = Path(uvm_root_path) if uvm_root_path else root / 'uvm'
        run_reconciliation_cycle(root, vcuser, uvm_root)
    else:
        # No vcuser means discover_live_jobs() has nothing to query --
        # fall back to the pre-existing behavior of re-rendering
        # whatever is already registered locally, rather than crashing.
        print(render_snapshot(attach_job_memory_columns(root, load_jobs(root))), flush=True)


if __name__=='__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', default='.')
    ap.add_argument('--watch', action='store_true')
    ap.add_argument('--interval-minutes', type=int, default=DEFAULT_INTERVAL_MINUTES,
                     help=f'watch-loop cadence in minutes (default '
                          f'{DEFAULT_INTERVAL_MINUTES}; self_check_list #41 '
                          f'requires <= {SPEC_MAX_INTERVAL_MINUTES})')
    ap.add_argument('--vcuser', default=None,
                     help='LSF account to discover live jobs under; omit for legacy local-only mode')
    ap.add_argument('--uvm-root-path', default=None,
                     help='UVM_ROOT_PATH for regression.list; defaults to <project-root>/uvm')
    a = ap.parse_args()
    main(a.project_root, not a.watch, a.interval_minutes, a.vcuser, a.uvm_root_path)
