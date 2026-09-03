"""vip_distill.py -- Evidence Normalization ONLY.

Scope (user's own spec, 2026-09-03, verbatim Traditional Chinese):
"vip_distill.py 定位：只負責 evidence normalization（Raw VIP/sim evidence ->
vip_distill.py -> Normalized Evidence JSON -> DuckDB -> Analysis Agent ->
Hypothesis->Evidence->Confidence -> Memory Agent），不負責 orchestration、
memory promotion 或 job control。"

This module takes real, already-produced evidence artifacts this project's
own tools already emit -- a sim.log path/text, a job-tier memory record
shaped exactly like `dv_harness.lsf_client._upsert_job_tier_memory_record()`
already builds (or a raw `JobState`-shaped dict), an `fsdbreport` text
extract (`dv_harness.fsdb_report`) -- and re-shapes them into ONE stable
"Normalized Evidence" JSON envelope (schema documented below). It is
deliberately a thin re-shaping/aggregation layer, not a second parser: all
real marker/epilogue extraction stays in `sim_log_analysis.py`, all real
fsdbreport CSV structuring stays in `fsdb_report.py`. This module only
normalizes their outputs (plus a job record's already-known fields) into
one consistent envelope so a downstream DuckDB loader can ingest any
evidence source through one schema instead of three different shapes.

Explicit non-goals (never add these here -- they belong to other, separate
workstreams per the user's own layering):
  - NO orchestration: this module never decides what runs next, never
    calls `bsub`/`bjobs`/`pueue`/`just`, never touches
    `dv_harness.lsf_client.bsub_submit*()` or any scheduler.
  - NO memory promotion: this module never calls
    `dv_harness.memory_router.route_and_store()`/`promote_to_organizational()`
    and never writes into `.dv-harness/memory/**` itself. A Normalized
    Evidence JSON this module produces is an INPUT a separate Analysis/
    Memory Agent may later choose to act on -- producing it is not itself
    a memory write.
  - NO job control: no kill/requeue/retry decisions, no `JobState` mutation
    (`distill_job_record()` below only READS a job-record-shaped dict it is
    handed; it never loads/saves `.dv-harness/lsf/jobs/*.json` itself).
  - NO DuckDB access: this module only emits JSON. Loading that JSON into
    DuckDB is a separate Evidence-Store workstream's job (see "Schema
    reconciliation" note below) -- at the time this module was written, no
    `evidence_db.py` (or similarly-named DuckDB loader) existed anywhere in
    this repo to coordinate a schema against (grep-confirmed), so the
    schema below is this module's own reasonable, documented design; it
    must be reconciled against that workstream's real schema once it
    exists, rather than assumed to already match it.

Every distill_*() function here is pure (dict/str/Path in, dict out) --
the same "no file I/O except a thin path-reading wrapper, no subprocess, no
UVM/simulator dependency" convention `sim_log_analysis.py`'s own module
docstring already documents -- so this works against evidence from any
protocol/VIP, not one hardcoded target. The only I/O in this module is
`write_normalized_evidence()`, a thin JSON writer with no decision logic
(mirrors `fsdb_report.write_topic_report()`'s "just write the file" shape).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from . import fsdb_report as fsdb_report_mod
from . import sim_log_analysis

# Bumped only on a real, deliberate shape change to the envelope below.
# "-draft" until reconciled against a real evidence_db.py schema (see module
# docstring's "Schema reconciliation" note) -- this is a documented, honest
# marker that the shape is this module's own design, not yet confirmed
# against a consuming DuckDB loader's real expectations.
NORMALIZED_EVIDENCE_SCHEMA_VERSION = "0.1.0-draft"

SOURCE_KINDS = ("sim_log", "job_record", "fsdbreport", "combined")


class VipDistillError(ValueError):
    """Raised only for programmer-error inputs (e.g. neither log_text nor
    log_path supplied) -- never for a real runtime/evidence condition (a
    missing file, an unparseable report, an empty log). Same convention as
    `fsdb_report.FsdbReportError`."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _now() -> float:
    return time.time()


def _evidence_id(source_kind: str, *parts: Any) -> str:
    """Deterministic content-derived id: the same real input always yields
    the same evidence_id (so re-distilling the same sim.log twice produces
    the same id, letting a downstream loader de-duplicate by id instead of
    minting a fresh one every run) -- never a random uuid."""
    h = hashlib.sha256()
    h.update(source_kind.encode("utf-8"))
    for p in parts:
        h.update(b"\x00")
        h.update(str(p).encode("utf-8", errors="replace"))
    return f"EVID-{h.hexdigest()[:24]}"


def _envelope(source_kind: str, *, evidence_id: str, job_id: Optional[int] = None,
              pattern: Optional[str] = None, protocol: Optional[str] = None,
              run_dir: Optional[str] = None, source_path: Optional[str] = None,
              verdict: Optional[str] = None,
              counts: Optional[Dict[str, Optional[int]]] = None,
              detail: Optional[Dict[str, Any]] = None,
              provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The one shared envelope shape every distill_*() function below
    returns. Optional identity fields (job_id/pattern/protocol/run_dir) are
    included only when the caller actually supplied them -- never
    defaulted to a placeholder that would look like real identity evidence
    when none was given, matching `_upsert_job_tier_memory_record()`'s own
    "omit rather than write a null placeholder" convention for seed/
    fsdb_path."""
    if source_kind not in SOURCE_KINDS:
        raise VipDistillError("UNKNOWN_SOURCE_KIND", source_kind)
    env: Dict[str, Any] = {
        "schema_version": NORMALIZED_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "source_kind": source_kind,
        "distilled_at": _now(),
        "distiller": "vip_distill.py",
    }
    for key, val in (("job_id", job_id), ("pattern", pattern),
                     ("protocol", protocol), ("run_dir", run_dir)):
        if val is not None:
            env[key] = val
    env["verdict"] = verdict
    # `counts` is passed through exactly as the caller supplied it -- a real
    # explicit `None` (fsdbreport has no PASS/FAIL/count concept at all)
    # stays `None`, never silently upgraded into a dict of null placeholders
    # that would look like "counts were checked and are unknown" instead of
    # "this evidence kind has no counts".
    env["counts"] = counts
    env["detail"] = detail or {}
    env["provenance"] = dict(provenance or {})
    if source_path is not None:
        env["provenance"].setdefault("source_path", source_path)
    return env


def distill_sim_log(*, log_text: Optional[str] = None, log_path: Optional[Union[str, Path]] = None,
                     job_id: Optional[int] = None, pattern: Optional[str] = None,
                     protocol: Optional[str] = None, run_dir: Optional[str] = None) -> Dict[str, Any]:
    """Normalize one sim.log's evidence. Delegates all real parsing to
    `sim_log_analysis.parse_sim_log[_file]()`/`classify_signatures()` --
    this function only re-shapes their output into the shared envelope,
    it never re-implements marker/epilogue detection itself.

    Exactly one of log_text/log_path must be given (mirrors the CLI's own
    `sim-log-analyze` mutually-exclusive --log/--log-text convention).
    """
    if (log_text is None) == (log_path is None):
        raise VipDistillError("EXACTLY_ONE_OF_LOG_TEXT_OR_LOG_PATH_REQUIRED")

    if log_path is not None:
        parsed = sim_log_analysis.parse_sim_log_file(log_path)
        source_path = str(log_path)
        id_key = source_path
    else:
        parsed = sim_log_analysis.parse_sim_log(log_text)
        source_path = None
        id_key = log_text

    classified = sim_log_analysis.classify_signatures(parsed["signatures"])
    epilogue = parsed.get("epilogue")
    verdict = epilogue.get("verdict") if epilogue else None
    counts = {
        "uvm_fatal": (epilogue or {}).get("uvm_fatal"),
        "uvm_error": (epilogue or {}).get("uvm_error"),
        "uvm_warning": (epilogue or {}).get("uvm_warning"),
    }
    evidence_id = _evidence_id("sim_log", id_key, job_id, pattern)
    return _envelope(
        "sim_log", evidence_id=evidence_id, job_id=job_id, pattern=pattern,
        protocol=protocol, run_dir=run_dir, source_path=source_path, verdict=verdict,
        counts=counts,
        detail={
            "total_lines": parsed["total_lines"],
            "epilogue": epilogue,
            "signatures": classified,
        },
        provenance={"parser": "sim_log_analysis.parse_sim_log"},
    )


# Job-record fields this function reads verbatim as evidence, never
# recomputes -- the exact vocabulary `_upsert_job_tier_memory_record()`
# writes (job_failure/job_result kind) and `JobState.__dataclass_fields__`
# both already use. Anything outside this list on the input dict is
# ignored, not an error -- callers may pass a full JobState.asdict() dump
# or the smaller job_failure/job_result record shape interchangeably.
_JOB_RECORD_PASSTHROUGH_FIELDS = (
    "lsf_status", "sim_status", "uvm_error_count", "uvm_fatal_count",
    "assertion_failure", "simulator_crash", "terminal_signature",
    "seed", "fsdb_path", "dv_analysis_status", "failure_signature",
    "prior_related_knowledge", "kind",
)


def distill_job_record(job_record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a job-record-shaped dict -- either the `job_failure`/
    `job_result` record `lsf_client._upsert_job_tier_memory_record()`
    already builds, or a raw `JobState.asdict()` dump -- into the shared
    envelope. READS ONLY: this never loads/saves a `JobState` file itself
    and never decides a kill/requeue/promotion action -- it is handed a
    dict a caller already has and only re-shapes it.
    """
    if not isinstance(job_record, dict) or not job_record:
        raise VipDistillError("JOB_RECORD_MUST_BE_A_NONEMPTY_DICT")

    job_id = job_record.get("job_id")
    pattern = job_record.get("pattern")
    lsf_status = job_record.get("lsf_status")
    sim_status = job_record.get("sim_status")
    # A job record has no "PASSED"/"FAILED" epilogue verdict field of its
    # own -- `sim_status` ("FAIL"/"PASS"/"UNKNOWN"/...) is the closest real
    # verdict-shaped fact already on this shape (see JobState.sim_status /
    # `_upsert_job_tier_memory_record()`'s own `is_failure` derivation from
    # it) -- carried through as-is, never re-derived or guessed here.
    verdict = sim_status if sim_status not in (None, "UNKNOWN") else None
    counts = {
        "uvm_fatal": job_record.get("uvm_fatal_count"),
        "uvm_error": job_record.get("uvm_error_count"),
        "uvm_warning": None,  # not a field this record shape carries
    }
    detail = {k: job_record[k] for k in _JOB_RECORD_PASSTHROUGH_FIELDS if k in job_record}
    detail["lsf_status"] = lsf_status
    detail["sim_status"] = sim_status

    evidence_id = _evidence_id(
        "job_record", job_record.get("memory_id") or job_id, pattern,
        job_record.get("terminal_signature"),
    )
    return _envelope(
        "job_record", evidence_id=evidence_id, job_id=job_id, pattern=pattern,
        run_dir=job_record.get("run_dir"), verdict=verdict, counts=counts, detail=detail,
        provenance={
            "source_memory_id": job_record.get("memory_id"),
            "source_kind_original": job_record.get("kind"),
        },
    )


def distill_fsdbreport(*, report_text: Optional[str] = None,
                        parsed_report: Optional[Dict[str, Any]] = None,
                        fsdb_path: Optional[str] = None, topic: Optional[str] = None,
                        job_id: Optional[int] = None, pattern: Optional[str] = None) -> Dict[str, Any]:
    """Normalize one fsdbreport text extract. Delegates real CSV structuring
    to `fsdb_report.parse_fsdbreport_output()` -- this function only wraps
    its already-honest `{"parsed": True/False, ...}` result into the shared
    envelope, it never second-guesses that result's own parsed/raw-text
    distinction.

    Exactly one of report_text/parsed_report must be given -- pass
    parsed_report when the caller already ran
    `fsdb_report.parse_fsdbreport_output()` itself (e.g. the CLI's
    `fsdb-report` command already does), report_text to have this function
    call it.
    """
    if (report_text is None) == (parsed_report is None):
        raise VipDistillError("EXACTLY_ONE_OF_REPORT_TEXT_OR_PARSED_REPORT_REQUIRED")

    parsed = parsed_report if parsed_report is not None else fsdb_report_mod.parse_fsdbreport_output(report_text)
    id_key = report_text if report_text is not None else json.dumps(parsed, sort_keys=True, default=str)
    evidence_id = _evidence_id("fsdbreport", fsdb_path or "", topic or "", id_key, job_id, pattern)

    # fsdbreport has no PASS/FAIL verdict concept of its own -- it is
    # signal-level trace evidence, not a checker -- so verdict/counts stay
    # structurally absent (None) rather than inventing a fabricated verdict.
    return _envelope(
        "fsdbreport", evidence_id=evidence_id, job_id=job_id, pattern=pattern,
        source_path=fsdb_path, verdict=None, counts=None,
        detail={"topic": topic, "fsdbreport": parsed},
        provenance={"parser": "fsdb_report.parse_fsdbreport_output"},
    )


_SEVERITY_ORDER = sim_log_analysis.SEVERITY_ORDER  # single shared enum, never redefined here


def _worst_severity(components: Sequence[Dict[str, Any]]) -> Optional[str]:
    worst = None
    worst_rank = len(_SEVERITY_ORDER)
    for comp in components:
        for sig in comp.get("detail", {}).get("signatures", []) or []:
            sev = sig.get("severity")
            if sev in _SEVERITY_ORDER:
                rank = _SEVERITY_ORDER.index(sev)
                if rank < worst_rank:
                    worst_rank = rank
                    worst = sev
    return worst


def merge_evidence(components: Sequence[Dict[str, Any]], *,
                    job_id: Optional[int] = None, pattern: Optional[str] = None,
                    protocol: Optional[str] = None, run_dir: Optional[str] = None) -> Dict[str, Any]:
    """Combine two or more already-normalized envelopes (as returned by the
    distill_*() functions above) for the SAME job/pattern into one
    "combined" envelope with an `aggregate` summary. Pure re-shaping/
    arithmetic (sums, worst-severity pick) over fields the inputs already
    carry -- never re-parses raw evidence, never introduces a new fact the
    components didn't already state.
    """
    if not components or len(components) < 2:
        raise VipDistillError("MERGE_REQUIRES_AT_LEAST_TWO_COMPONENT_ENVELOPES")
    for comp in components:
        if comp.get("source_kind") not in SOURCE_KINDS or comp.get("source_kind") == "combined":
            raise VipDistillError("INVALID_COMPONENT_ENVELOPE", str(comp.get("source_kind")))

    def _sum(field: str) -> Optional[int]:
        vals = [c["counts"].get(field) for c in components if c.get("counts") and c["counts"].get(field) is not None]
        return sum(vals) if vals else None

    verdicts = {c.get("verdict") for c in components if c.get("verdict")}
    # FAILED/FAIL from any single component is authoritative for the
    # combined verdict (one real failure signal must never be averaged away
    # by other components that simply have no verdict opinion) -- mirrors
    # `_upsert_job_tier_memory_record()`'s own is_failure-wins-out posture.
    if "FAILED" in verdicts or "FAIL" in verdicts:
        combined_verdict = "FAILED"
    elif verdicts == {"PASSED"} or verdicts == {"PASS"}:
        combined_verdict = "PASSED"
    elif verdicts:
        combined_verdict = "AMBIGUOUS"
    else:
        combined_verdict = None

    evidence_id = _evidence_id("combined", *(c["evidence_id"] for c in components))
    return _envelope(
        "combined", evidence_id=evidence_id, job_id=job_id, pattern=pattern,
        protocol=protocol, run_dir=run_dir, verdict=combined_verdict,
        counts={"uvm_fatal": _sum("uvm_fatal"), "uvm_error": _sum("uvm_error"), "uvm_warning": _sum("uvm_warning")},
        detail={
            "components": list(components),
            "aggregate": {
                "component_source_kinds": [c["source_kind"] for c in components],
                "worst_severity": _worst_severity(components),
                "component_count": len(components),
            },
        },
        provenance={"merged_from_evidence_ids": [c["evidence_id"] for c in components]},
    )


def write_normalized_evidence(record: Dict[str, Any], out_path: Union[str, Path]) -> Path:
    """Thin JSON writer, no decision logic -- mirrors
    `fsdb_report.write_topic_report()`'s "build the shape, then just write
    it" split. Never chooses the path, never routes into memory/DuckDB
    itself; the caller (a future Evidence-Store loader) owns what happens
    to the written file next."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
