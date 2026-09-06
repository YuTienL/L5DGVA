"""dv_harness/protocol_compliance_aggregation.py -- Protocol Compliance
Aggregation ONLY (2026-09-06).

Scope, stated up front because it is the whole point of this module: **this
harness has no formal protocol-checker TOOL, and this module does not build
one.** Verified before writing anything here: `grep -rn
"protocol.checker|checker_verdict|protocol_violation|vip_checker" --include=
*.py dv_harness/` (excluding this file) matches no real producer of a
protocol-checker verdict anywhere in this repository, and
`dv_harness/uvm_generator/protocol_model_layer.py` -- named in this task as
one of the two real modules to read for "the real shape these carry" --
carries no `verdict`/`checker`/`PASS`/`FAIL`/`violation` token at all (it
compiles LTSSM state-transition legality into SVA assertions; it produces no
runtime checker RESULT). `vip_distill.py`'s own `SOURCE_KINDS` is exactly
`("sim_log", "job_record", "fsdbreport", "combined")` -- there is no
`"protocol_checker"` source kind, and none of `distill_sim_log()`/
`distill_job_record()`/`distill_fsdbreport()`/`merge_evidence()`'s `detail`
dicts (epilogue/signatures/counts/lsf_status/sim_status/topic/fsdbreport)
ever carries a checker-specific verdict field. So a real protocol-checker
verdict, distinct from the scoreboard verdict `vip_distill.py` already
normalizes, is not something this repository's own evidence pipeline
produces today.

What THIS module builds is only the AGGREGATION RULE the task asks for, over
whatever real evidence a stage actually has: a scoreboard PASS/FAIL verdict
(the real, already-normalized `vip_distill.py` envelope's own `verdict`
field, read via `evidence_db.py`'s real `normalized_evidence` table -- see
`load_normalized_evidence_rows()` below, which reuses that table's real
column list rather than re-parsing evidence a second way) plus, IF a real
protocol-checker verdict is present in the SAME evidence set, that verdict
too. The hard rule this module enforces, verbatim from the task: **a
scoreboard PASS alongside a real protocol-checker violation is still an
overall FAIL** -- a functional PASS must never silently outrank a real
protocol violation. And the honesty rule alongside it: **absent
protocol-checker evidence reports `NOT_CHECKED`, distinct from `CLEAN` or
`PASS`, and is never assumed clean.**

Because no real producer in this repo tags a normalized_evidence row as
"the protocol-checker verdict for this evidence set" today,
`PROTOCOL_CHECKER_DETAIL_KEYS` below is a documented, honest EXTENSION
POINT, not a claim that such data exists anywhere yet: if a future real
protocol-checker distiller starts writing one of those keys into a
normalized_evidence row's own free-form `detail` dict (the one place the
real schema is flexible enough to carry it without a schema migration),
`extract_verdicts_from_evidence_set()` will pick it up unchanged. Until then
it correctly finds nothing and this module reports `NOT_CHECKED`, exactly as
the task requires -- never a fabricated "CLEAN" it has no evidence for.

Per this batch's file-safety scope, this module imports ONLY
`dv_harness/evidence_db.py` (a stable, pre-existing module, not part of
either concurrently-running batch) and the Python standard library. It does
NOT import `dv_harness/golden_scenario.py` even though that module also
reads `normalized_evidence` PASS verdicts, because `golden_scenario.py` is
one of the files a separate, already-running batch of 12 agents is
concurrently editing. `SCOREBOARD_PASS_VERDICTS`/`SCOREBOARD_FAIL_VERDICTS`
below are this module's own, independently-stated citation of the same real
`vip_distill.py` verdict vocabulary (`distill_sim_log()` passes an epilogue's
own `VERDICT: PASSED` through verbatim; `distill_job_record()` passes
`JobState.sim_status` through verbatim; `merge_evidence()` emits `"PASSED"`)
-- not a second, drifting definition of new logic.

This module also accepts a plain, duck-typed evidence-set shape (any
sequence of dicts carrying `verdict`/`source_kind`/`detail`/`evidence_id`
keys) wherever it reads evidence, so it can consume a real
`vip_distill.py` envelope handed to it directly by a caller, evidence rows
read back from a real `evidence_db.EvidenceStore`, or -- once a real
protocol-checker tool is ever built by a separate task -- that tool's own
output, without this module importing anything from that not-yet-existing
module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# --- vocabulary --------------------------------------------------------------

#: The real verdict strings `vip_distill.py` normalizes a scoreboard/
#: functional result into (see this module's own docstring for the exact
#: citations). Any other non-None string is a real recorded verdict this
#: module simply does not recognize (e.g. "AMBIGUOUS") -- reported UNKNOWN,
#: never guessed at.
SCOREBOARD_PASS_VERDICTS = frozenset({"PASS", "PASSED"})
SCOREBOARD_FAIL_VERDICTS = frozenset({"FAIL", "FAILED"})

#: A real protocol-checker verdict has no established vocabulary anywhere in
#: this repo (see module docstring) -- these are this module's own honest,
#: minimal recognition set for the day a real checker exists, covering the
#: literal English words a checker verdict would plainly use.
CHECKER_PASS_VERDICTS = frozenset({"PASS", "PASSED", "CLEAN"})
CHECKER_FAIL_VERDICTS = frozenset({"FAIL", "FAILED", "VIOLATION", "VIOLATED"})

#: Scoreboard state vocabulary. NOT_AVAILABLE means no scoreboard evidence
#: was supplied at all (the raw verdict is None); UNKNOWN means a raw verdict
#: string WAS supplied but is not one this module recognizes as PASS/FAIL --
#: two different kinds of "we cannot certify PASS", never collapsed into one.
SCOREBOARD_PASS = "PASS"
SCOREBOARD_FAIL = "FAIL"
SCOREBOARD_UNKNOWN = "UNKNOWN"
SCOREBOARD_NOT_AVAILABLE = "NOT_AVAILABLE"
SCOREBOARD_STATES = (SCOREBOARD_PASS, SCOREBOARD_FAIL, SCOREBOARD_UNKNOWN,
                     SCOREBOARD_NOT_AVAILABLE)

#: Protocol-checker state vocabulary. NOT_CHECKED is the task's own required
#: distinct value for "no real protocol-checker evidence was present in this
#: evidence set" -- it must never be reported as, or read as, CLEAN/PASS.
CHECKER_PASS = "PASS"
CHECKER_FAIL = "FAIL"
CHECKER_UNKNOWN = "UNKNOWN"
CHECKER_NOT_CHECKED = "NOT_CHECKED"
CHECKER_STATES = (CHECKER_PASS, CHECKER_FAIL, CHECKER_UNKNOWN, CHECKER_NOT_CHECKED)

#: The composite verdict this module reports. PASS/FAIL are shared with
#: `models.Status` deliberately -- like `connectivity.GateStatus`, this
#: module's whole subject IS a pass/fail verdict, not a differently-shaped
#: domain vocabulary, so reusing the two real verdict words is correct here
#: rather than a collision to guard against. UNKNOWN/NOT_AVAILABLE are the
#: two honest "cannot judge" states, kept distinct for the same reason the
#: scoreboard states above are.
OVERALL_PASS = "PASS"
OVERALL_FAIL = "FAIL"
OVERALL_UNKNOWN = "UNKNOWN"
OVERALL_NOT_AVAILABLE = "NOT_AVAILABLE"
OVERALL_STATES = (OVERALL_PASS, OVERALL_FAIL, OVERALL_UNKNOWN, OVERALL_NOT_AVAILABLE)

#: `vip_distill.py`'s real `SOURCE_KINDS` that carry a scoreboard/functional
#: verdict at all -- `fsdbreport` deliberately does not (that module's own
#: docstring: "fsdbreport has no PASS/FAIL verdict concept of its own -- it
#: is signal-level trace evidence, not a checker"). Read, never re-derived.
SCOREBOARD_SOURCE_KINDS = ("sim_log", "job_record", "combined")

#: Documented extension point -- see module docstring. No real producer in
#: this repository writes any of these keys today; this is where a future
#: real protocol-checker distiller's verdict would land inside a
#: normalized_evidence row's own free-form `detail` dict.
PROTOCOL_CHECKER_DETAIL_KEYS = (
    "protocol_checker_verdict", "vip_checker_verdict", "checker_verdict",
)

#: The real `normalized_evidence` table's own column order
#: (`evidence_db.py`'s `CREATE TABLE` statement) -- used to zip
#: `EvidenceStore.query()`'s positional tuples back into named fields rather
#: than indexing them by string key (that indexing is a real, separately
#: disclosed defect in this codebase -- see `signoff_export.py`'s
#: `_capture_evidence_hashes()`, per `subsystem_contract.py`'s own CLAUDE.md
#: note -- this module avoids repeating it).
NORMALIZED_EVIDENCE_COLUMNS = (
    "evidence_id", "schema_version", "source_kind", "job_id", "pattern",
    "protocol", "run_dir", "verdict", "counts_json", "detail_json",
    "provenance_json", "distilled_at", "distiller",
)

_JSON_COLUMNS = ("counts_json", "detail_json", "provenance_json")


class ProtocolComplianceError(Exception):
    """Base for every refusal in this module."""


# --- pure normalization ------------------------------------------------------


def normalize_scoreboard_state(raw_verdict: Optional[str]) -> str:
    """`None` (no scoreboard evidence at all) -> NOT_AVAILABLE. A real,
    recognized verdict string -> PASS/FAIL. Anything else non-None (e.g.
    "AMBIGUOUS") -> UNKNOWN -- evidence was present but is not one this
    module can certify as a clean PASS."""
    if raw_verdict is None:
        return SCOREBOARD_NOT_AVAILABLE
    text = str(raw_verdict).strip().upper()
    if text in SCOREBOARD_PASS_VERDICTS:
        return SCOREBOARD_PASS
    if text in SCOREBOARD_FAIL_VERDICTS:
        return SCOREBOARD_FAIL
    return SCOREBOARD_UNKNOWN


def normalize_checker_state(raw_verdict: Optional[str]) -> str:
    """`None` (no protocol-checker evidence in this evidence set) ->
    NOT_CHECKED -- the task's own required distinct value, never CLEAN/PASS.
    A real, recognized verdict string -> PASS/FAIL. Anything else non-None ->
    UNKNOWN."""
    if raw_verdict is None:
        return CHECKER_NOT_CHECKED
    text = str(raw_verdict).strip().upper()
    if text in CHECKER_PASS_VERDICTS:
        return CHECKER_PASS
    if text in CHECKER_FAIL_VERDICTS:
        return CHECKER_FAIL
    return CHECKER_UNKNOWN


def _decide_overall(scoreboard_state: str, checker_state: str) -> Tuple[str, str]:
    """The one rule this whole module exists for, decided in this exact
    priority order (most severe / most certain first):

    1. A REAL protocol-checker violation (checker_state == FAIL) is an
       overall FAIL no matter what the scoreboard says -- this is the task's
       own headline rule: a scoreboard PASS must never silently outrank a
       real protocol violation.
    2. A scoreboard FAIL is an overall FAIL (checker did not already decide
       it above).
    3. No scoreboard evidence at all (NOT_AVAILABLE) -- nothing here
       certifies PASS without it, even when a checker happened to report
       PASS; the scoreboard is the primary functional evidence this
       aggregation is over.
    4. Either side is UNKNOWN (evidence present but not a clean PASS/FAIL) --
       reported as UNKNOWN, never rounded up to PASS or down to FAIL.
    5. Scoreboard PASS + checker PASS -> PASS.
    6. Scoreboard PASS + checker NOT_CHECKED -> PASS, but the caller-facing
       report ALWAYS carries `protocol_checker_status: "NOT_CHECKED"`
       alongside it (see `aggregate_protocol_compliance()`), so this can
       never be read as "protocol compliance verified clean" -- only as
       "no protocol-checker evidence existed to contradict the scoreboard".
    """
    if checker_state == CHECKER_FAIL:
        return (OVERALL_FAIL,
                "real protocol-checker violation present (protocol_checker_status=FAIL) -- "
                "this overrides any scoreboard verdict, including a scoreboard PASS")
    if scoreboard_state == SCOREBOARD_FAIL:
        return OVERALL_FAIL, "scoreboard verdict is FAIL"
    if scoreboard_state == SCOREBOARD_NOT_AVAILABLE:
        return (OVERALL_NOT_AVAILABLE,
                "no scoreboard evidence available in this evidence set -- cannot judge")
    if scoreboard_state == SCOREBOARD_UNKNOWN or checker_state == CHECKER_UNKNOWN:
        return (OVERALL_UNKNOWN,
                f"scoreboard_status={scoreboard_state}, protocol_checker_status={checker_state} "
                "-- evidence present but not cleanly interpretable as PASS or FAIL")
    if scoreboard_state == SCOREBOARD_PASS and checker_state == CHECKER_PASS:
        return OVERALL_PASS, "scoreboard PASS and a real protocol-checker verdict of PASS"
    if scoreboard_state == SCOREBOARD_PASS and checker_state == CHECKER_NOT_CHECKED:
        return (OVERALL_PASS,
                "scoreboard PASS; no protocol-checker evidence was present in this evidence "
                "set (protocol_checker_status=NOT_CHECKED, never assumed clean)")
    # Every (scoreboard_state, checker_state) combination in
    # SCOREBOARD_STATES x CHECKER_STATES is covered by one of the branches
    # above; this is unreachable and exists only so a future vocabulary
    # addition fails loudly instead of silently falling through.
    raise ProtocolComplianceError(
        f"_decide_overall: unclassified combination scoreboard_state={scoreboard_state!r} "
        f"checker_state={checker_state!r}")


# --- the aggregation ---------------------------------------------------------


def aggregate_protocol_compliance(
    scoreboard_verdict: Optional[str],
    protocol_checker_verdict: Optional[str] = None,
    *,
    scoreboard_evidence_id: Optional[str] = None,
    checker_evidence_id: Optional[str] = None,
    job_id: Optional[int] = None,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """The aggregation this whole module exists for. Takes a stage's real
    scoreboard verdict and, if present, a real protocol-checker verdict from
    the SAME evidence set, and returns one composite report -- never a bare
    boolean, so a caller (or a human reading the report) can always see
    which of the two inputs actually decided the outcome and cannot mistake
    an absent protocol-checker input for a clean one.
    """
    scoreboard_state = normalize_scoreboard_state(scoreboard_verdict)
    checker_state = normalize_checker_state(protocol_checker_verdict)
    overall_status, reason = _decide_overall(scoreboard_state, checker_state)
    return {
        "overall_status": overall_status,
        "reason": reason,
        "scoreboard_status": scoreboard_state,
        "scoreboard_verdict_raw": scoreboard_verdict,
        "scoreboard_evidence_id": scoreboard_evidence_id,
        "protocol_checker_status": checker_state,
        "protocol_checker_verdict_raw": protocol_checker_verdict,
        "protocol_checker_evidence_id": checker_evidence_id,
        "job_id": job_id,
        "pattern": pattern,
        "rule": "scoreboard_pass_with_real_protocol_violation_is_overall_fail",
    }


# --- reading a real evidence set ---------------------------------------------


def extract_verdicts_from_evidence_set(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Duck-typed over ANY sequence of dicts carrying `verdict`/
    `source_kind`/`detail`/`evidence_id` keys -- the real `vip_distill.py`
    envelope shape, whether obtained via `load_normalized_evidence_rows()`
    below or handed directly by a caller that already holds them in memory.
    Never mutates or re-derives a verdict; it only locates the two real
    values, if present, among the rows that make up one evidence set.

    The scoreboard verdict is the first row's own top-level `verdict` whose
    `source_kind` is one of `SCOREBOARD_SOURCE_KINDS` (fsdbreport rows are
    skipped -- they carry no verdict concept, per `vip_distill.py`'s own
    documented rule). The protocol-checker verdict is found by scanning
    every row's `detail` dict for a recognized key in
    `PROTOCOL_CHECKER_DETAIL_KEYS` -- see this module's own docstring for why
    that is an honest extension point and not a claim about existing data.
    A row missing either key contributes nothing; it is never an error for
    an evidence set to carry no protocol-checker evidence, or even no
    scoreboard evidence at all -- both are reported to the caller as their
    own real, honest state (`None` here; `NOT_AVAILABLE`/`NOT_CHECKED` once
    passed through `aggregate_protocol_compliance()`).
    """
    scoreboard_verdict: Optional[str] = None
    scoreboard_evidence_id: Optional[str] = None
    checker_verdict: Optional[str] = None
    checker_evidence_id: Optional[str] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if scoreboard_verdict is None and row.get("verdict") is not None \
                and row.get("source_kind") in SCOREBOARD_SOURCE_KINDS:
            scoreboard_verdict = row.get("verdict")
            scoreboard_evidence_id = row.get("evidence_id")
        if checker_verdict is None:
            detail = row.get("detail") or {}
            if isinstance(detail, dict):
                for key in PROTOCOL_CHECKER_DETAIL_KEYS:
                    if detail.get(key) is not None:
                        checker_verdict = detail[key]
                        checker_evidence_id = row.get("evidence_id")
                        break
    return {
        "scoreboard_verdict": scoreboard_verdict,
        "scoreboard_evidence_id": scoreboard_evidence_id,
        "protocol_checker_verdict": checker_verdict,
        "protocol_checker_evidence_id": checker_evidence_id,
    }


def aggregate_stage_evidence_set(
    rows: Sequence[Dict[str, Any]], *, job_id: Optional[int] = None,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience: extract + aggregate in one call over a real (or
    duck-typed) evidence-set row sequence."""
    extracted = extract_verdicts_from_evidence_set(rows)
    return aggregate_protocol_compliance(
        extracted["scoreboard_verdict"], extracted["protocol_checker_verdict"],
        scoreboard_evidence_id=extracted["scoreboard_evidence_id"],
        checker_evidence_id=extracted["protocol_checker_evidence_id"],
        job_id=job_id, pattern=pattern,
    )


def load_normalized_evidence_rows(
    db_path: Union[str, Path], *, job_id: Optional[int] = None,
    pattern: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Real, read-only query against `evidence_db.py`'s own
    `normalized_evidence` table for the rows that make up ONE stage's
    evidence set -- every row recorded for the same `job_id` and/or
    `pattern`. Reused rather than reinvented: this is the SAME table
    `vip_distill.py`'s `write_normalized_evidence()`-produced envelopes are
    upserted into by `EvidenceStore.insert_normalized_evidence()`, read back
    through the real column list above rather than a second parser. Rows are
    re-shaped back into the same dict keys the `vip_distill.py` envelope
    uses (`counts`/`detail`/`provenance` parsed back from their `*_json`
    columns) -- never left as `EvidenceStore.query()`'s raw positional
    tuples, which `extract_verdicts_from_evidence_set()` above expects as
    dicts.

    At least one of `job_id`/`pattern` is required -- an unscoped query
    would silently aggregate every evidence row this project has ever
    recorded, across every unrelated stage, as if it were one evidence set.
    """
    if job_id is None and pattern is None:
        raise ProtocolComplianceError(
            "load_normalized_evidence_rows: at least one of job_id/pattern is required")
    from . import evidence_db as evidence_db_mod

    conditions = []
    params: List[Any] = []
    if job_id is not None:
        conditions.append("job_id = ?")
        params.append(job_id)
    if pattern is not None:
        conditions.append("pattern = ?")
        params.append(pattern)
    where_clause = " AND ".join(conditions)

    store = evidence_db_mod.EvidenceStore(db_path, read_only=True)
    try:
        cols_sql = ", ".join(NORMALIZED_EVIDENCE_COLUMNS)
        raw_rows = store.query(
            f"SELECT {cols_sql} FROM normalized_evidence WHERE {where_clause}", params)
    finally:
        store.close()

    out: List[Dict[str, Any]] = []
    for raw in raw_rows:
        rec = dict(zip(NORMALIZED_EVIDENCE_COLUMNS, raw))
        for json_col, key in (("counts_json", "counts"), ("detail_json", "detail"),
                               ("provenance_json", "provenance")):
            text = rec.pop(json_col, None)
            rec[key] = json.loads(text) if text else ({} if key != "counts" else None)
        out.append(rec)
    return out


def aggregate_from_evidence_db(
    db_path: Union[str, Path], *, job_id: Optional[int] = None,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end convenience: read a stage's real evidence set out of a real
    `evidence.duckdb` and aggregate it. Front door for a caller that has a
    database path rather than an in-memory evidence-row list."""
    rows = load_normalized_evidence_rows(db_path, job_id=job_id, pattern=pattern)
    return aggregate_stage_evidence_set(rows, job_id=job_id, pattern=pattern)
