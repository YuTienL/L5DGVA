"""dv_harness/l5dgva_kc_extraction.py -- SS211 ("KC from vPlan/Test/Coverage
Closure") EXTRACTION half, built narrow per the L5DGVA domain-E audit's own
NOT_PROVEN finding for this concept (`.dv-harness/l5dgva_audit_result_E.md`).

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- this
module is CAP-POOL-004's target capability. Depends on `l5dgva_gap_queue.py`
(chain B, migrated identically to canonical earlier in this batch) and on
canonical's real `protocol_capability.PROTOCOL_CAPABILITIES`, independently
confirmed compatible before this migration: `ProtocolCapability` carries
`protocol: str` and `aliases: Tuple[str, ...] = ()` (dv_harness/protocol_capability.py:146,151),
exactly the `.protocol`/`.aliases` shape `_protocol_registry_tokens()` below
already assumes.

DISCLOSED SCOPE NOTE (new evidence found during this migration's own dependency
sweep, not previously listed in Batch 1's dependency graph): this module's real
dependency chain is `l5dgva_gap_queue.py` + `protocol_capability.py`, not only
`l5dgva_gap_queue.py` as Batch 1's graph named. Both are now migrated/confirmed
present in canonical, so this is a disclosed correction, not an open gap.

Two real Parent-side callers this docstring itself names below
(`kc_extraction_trigger_and_outcome_registration_gap.py`,
`l5dgva_kc_semantic_dedup.py`) are NOT part of Batch 2's registered scope and
are NOT migrated here -- canonical's copy of this module therefore has 0 real
callers today, a disclosed limitation consistent with this batch's own
M6-boundary/no-unrelated-module-absorption rule, not a regression this
migration is responsible for closing.

Primary contract text (read directly, not paraphrased --
`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v9.md`, section 211):

    ## 211. KC from vPlan/Test/Coverage Closure

    Extract reusable methods from requirement discovery, scenario synthesis,
    VIP example reuse, checking selection, coverage-hole diagnosis and
    targeted closure. Semantic dedup; classify
    GENERIC/SCOPE/PROTOCOL_FAMILY/PROTOCOL_SPECIFIC/TOOL/PROJECT; persist
    through qualified KC pipeline; register phase triggers; verify runtime
    reuse.

    Required: `VPlanTestCoverageKCExtraction_PASS = true`
    `VPlanTestCoverageKCRuntimeTrigger_PASS = true`

SS211 names FIVE distinct pieces under two required booleans. This module
builds exactly the parts that are narrow, evidence-only and callable without
touching `engine.py` (out of scope this wave -- a separate workstream owns
it):

  1. EXTRACTION -- given one already-classified, already-cited `ClosureRow`
     (`dv_harness/l5dgva_gap_queue.py`'s own real audit-output shape) that is
     currently a PASSING status, build a real
     `memory_router.route_and_store()`-shaped record carrying that row's own
     real evidence/confidence/notes -- no invented content. See
     `build_kc_extraction_record()`.
  2. CLASSIFICATION -- `classify_kc_scope_class()` assigns one of SS211's six
     named values using only grounded, mechanically-checkable signals (a real
     protocol name/alias from `protocol_capability.PROTOCOL_CAPABILITIES`, a
     real module/tool path token, a real project/task-ID-shaped token). A row
     matching none of those signals is never force-fit toward one specific
     value by guessing; it falls to one of two honestly coarser buckets
     (GENERIC for one of this audit's own meta/methodology domains, SCOPE
     otherwise).
  3. "Persist through qualified KC pipeline" -- satisfied structurally:
     `build_kc_extraction_record()`'s output IS the plain dict shape
     `memory_router.route_and_store()` already accepts, so every existing
     gate that dict passes through (`route_memory()`, the engineering/
     organizational admission gates) applies to it completely unchanged.
     This module invents no shortcut around any of them, and does not itself
     call `route_and_store()` -- the caller does, exactly like every other
     record-building helper in this codebase (see
     `capability_evolution.persist_candidate()`).
  4. `find_newly_closed_rows()` / `build_kc_extraction_records_for_newly_closed()`
     -- the real "a gap just closed" EVENT, computed honestly from two real
     `ClosureRow` snapshots (keyed by `(domain, cluster)`) rather than assumed
     from a single one.

Deliberately NOT built here, and NOT claimed to be:

  * Semantic dedup across extracted records -- a genuine NLP-similarity/
    near-duplicate-detection problem, distinct work, out of this pass's scope.
  * "Register phase triggers" -- auto-invoking this module at a real closure
    event is `engine.py`'s own stage-loop wiring, explicitly out of scope for
    this wave. 2026-09-18 correction (found stale by `kc_dead_artifact_
    census.py`'s SS539 census, which compares this claim against current
    call-site evidence rather than trusting it): this module is no longer
    zero-caller in Parent -- `dv_harness/kc_extraction_trigger_and_outcome_
    registration_gap.py` and `dv_harness/l5dgva_kc_semantic_dedup.py` both
    really import and call `build_kc_extraction_record()` there today. Neither
    caller is an `engine.py` stage-loop AUTO-TRIGGER, though: both are
    themselves manually-invoked helper modules, not a closure-event
    dispatcher, so "register phase triggers" (an automatic
    closure-event-to-extraction wiring) remains genuinely open. Neither
    caller is part of this Batch-2 migration (see the disclosed scope note
    above), so canonical's copy has 0 real callers today.
  * "Verify runtime reuse" -- still unmeasurable without the phase-trigger
    wiring above existing first.

  So `VPlanTestCoverageKCRuntimeTrigger_PASS` stays NOT_PROVEN/open on
  purpose -- that is an honest, disclosed limit of this module, not a bug in
  it. `VPlanTestCoverageKCExtraction_PASS`'s own "persist through qualified KC
  pipeline" clause is the one genuinely closeable by a narrow, callable
  mechanism, and that is what this module is.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .l5dgva_gap_queue import ClosureRow, PASSING_STATUSES

#: SS211's own six-value taxonomy, verbatim.
KC_SCOPE_CLASSES: Tuple[str, ...] = (
    "GENERIC", "SCOPE", "PROTOCOL_FAMILY", "PROTOCOL_SPECIFIC", "TOOL", "PROJECT",
)

# The L5DGVA audit's own meta/methodology domains (l5dgva_gap_queue's real
# `_DOMAIN_DEFAULT_PRIORITY` key set, not re-invented here): these clusters are
# about the harness's OWN reusable methodology -- requirement discovery,
# KC/memory, contract-as-code, foundational engine -- not about one specific
# protocol, tool file or project, so they default GENERIC rather than the
# coarser SCOPE fallback when no stronger protocol/tool/project signal fires.
_GENERIC_METHODOLOGY_DOMAINS = frozenset({
    "A_orchestration_engines", "E_evidence_vplan_coverage_signoff",
    "F_contract_as_code_meta", "G_foundational_v1",
})

# A concrete module/tool path token: a bare `*.py` path, a `dv_harness/...`
# path, or a `dv-harness <verb>` CLI invocation -- all real, checkable string
# shapes, never a semantic guess about "is this about a tool".
_TOOL_PATH_RE = re.compile(r"\b(?:[\w./-]+\.py|dv-harness\s+[\w-]+|dv_harness/[\w./-]+)\b")

# This project's own real task-ID convention (e.g. R5-D-ENUM1C,
# VERDICT-CONFLICT-DEBUG-P1C, R6-USB-E2E-PILOT-001): at least 3
# hyphen-separated ALL-CAPS/digit segments.
_PROJECT_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,}\b")


class KCExtractionError(Exception):
    """A real caller-usage error -- never a silently-repaired input."""


def _protocol_registry_tokens() -> List[Tuple[str, str]]:
    """`[(family_root, full_name_or_alias)]` over every real
    `protocol_capability.PROTOCOL_CAPABILITIES` entry -- the harness's own
    real, already-verified protocol name list, not a second hardcoded one
    (CLAUDE.md: "which protocols exist is deliberately not listed" in this
    file's own governing document -- so this module asks the real registry
    instead of hardcoding a list of its own)."""
    from . import protocol_capability as pc
    tokens: List[Tuple[str, str]] = []
    for cap in pc.PROTOCOL_CAPABILITIES:
        family = re.split(r"[_0-9]", cap.protocol, maxsplit=1)[0].upper()
        for name in (cap.protocol, *cap.aliases):
            tokens.append((family, name.upper()))
    return tokens


def classify_kc_scope_class(row: ClosureRow) -> str:
    """SS211's six-value taxonomy, decided on grounded signals only -- never a
    semantic guess:

    1. a literal, full protocol name/alias from the real
       `protocol_capability` registry present as a whole word ->
       `PROTOCOL_SPECIFIC`
    2. only that protocol's FAMILY root present (e.g. "MIPI", "AMBA") with no
       full name/alias hit -> `PROTOCOL_FAMILY`
    3. a concrete module/tool path token -> `TOOL`
    4. a project/task-ID-shaped token -> `PROJECT`
    5. domain is one of this audit's own meta/methodology domains -> `GENERIC`
    6. otherwise -> `SCOPE` (a real, domain-specific cluster with no stronger
       signal -- the honestly coarser default; never silently `GENERIC`)
    """
    text = f"{row.domain} {row.cluster} {row.notes} {row.evidence}".upper()
    tokens = _protocol_registry_tokens()

    if any(re.search(rf"\b{re.escape(name)}\b", text) for _fam, name in tokens):
        return "PROTOCOL_SPECIFIC"
    if any(re.search(rf"\b{re.escape(fam)}\b", text) for fam, _name in tokens if len(fam) >= 3):
        return "PROTOCOL_FAMILY"
    if _TOOL_PATH_RE.search(f"{row.notes} {row.evidence}"):
        return "TOOL"
    if _PROJECT_ID_RE.search(f"{row.notes} {row.evidence}"):
        return "PROJECT"
    if row.domain in _GENERIC_METHODOLOGY_DOMAINS:
        return "GENERIC"
    return "SCOPE"


def build_kc_extraction_record(row: ClosureRow, *, mark_verified: bool = False) -> Dict[str, Any]:
    """SS211 `VPlanTestCoverageKCExtraction`: one PASSING `ClosureRow` -> one
    real `memory_router.route_and_store()`-shaped record.

    Raises `KCExtractionError` on a row that is not currently passing
    (nothing closed to extract a reusable method from) or that carries no
    real evidence (persisting a KC record with no real citation would be
    exactly the invented content this project's Evidence Truth Rule and
    No-Golden-Reference-Content-Mining rule both forbid).

    `mark_verified` defaults False: a single audit-classified row is not, by
    itself, the "gate-validated + `confirmation_count >= 2`" bar
    `memory_router.organizational_admission_gate()` requires (CLAUDE.md's
    Engineering Memory Policy). Setting it True is the CALLER's own assertion
    that a second, independent confirmation already exists -- made explicit
    here rather than defaulted quietly to True. Either way, `route_and_store()`
    (not this function) makes the actual admission decision -- this function
    only ever builds the record.
    """
    if row.status not in PASSING_STATUSES:
        raise KCExtractionError(
            f"build_kc_extraction_record: row {row.cluster!r} (domain {row.domain!r}) "
            f"status is {row.status.value!r}, not a passing status -- nothing closed "
            "to extract a reusable method from")
    if not str(row.evidence or "").strip():
        raise KCExtractionError(
            f"build_kc_extraction_record: row {row.cluster!r} (domain {row.domain!r}) "
            "carries no evidence -- refusing to persist a KC record with no real citation")

    scope_class = classify_kc_scope_class(row)
    lesson = (
        f"[{row.domain}/{row.cluster}] closed as {row.status.value} "
        f"({row.confidence} confidence)" + (f": {row.notes}" if row.notes else "")
    )
    return {
        "kind": "methodology",
        "verified": bool(mark_verified),
        "scope": scope_class.lower(),
        "kc_scope_class": scope_class,
        "source_domain": row.domain,
        "source_cluster": row.cluster,
        "requirement_ids": list(row.requirement_ids),
        "status": row.status.value,
        "confidence": row.confidence,
        "evidence": row.evidence,
        "lesson": lesson,
        "extraction_origin": "l5dgva_kc_extraction.build_kc_extraction_record",
    }


def find_newly_closed_rows(
    previous_rows: Sequence[ClosureRow], current_rows: Sequence[ClosureRow],
) -> List[ClosureRow]:
    """Diff two `ClosureRow` snapshots of the same audited universe, keyed by
    `(domain, cluster)` -- the same identity `l5dgva_gap_queue.py`'s own rows
    already carry -- and return every CURRENT row that is now PASSING but was
    NOT passing (a gap, or simply absent) in the previous snapshot. This is
    the real "a gap just closed" event SS207/SS211 both talk about, computed
    honestly from two real `ClosureRow` lists rather than assumed from a
    single snapshot."""
    prev_status = {(r.domain, r.cluster): r.status for r in previous_rows}
    newly_closed: List[ClosureRow] = []
    for row in current_rows:
        if row.status not in PASSING_STATUSES:
            continue
        was = prev_status.get((row.domain, row.cluster))
        was_passing = was is not None and was in PASSING_STATUSES
        if not was_passing:
            newly_closed.append(row)
    return newly_closed


def build_kc_extraction_records_for_newly_closed(
    previous_rows: Sequence[ClosureRow], current_rows: Sequence[ClosureRow],
    *, mark_verified: bool = False,
) -> List[Dict[str, Any]]:
    """`find_newly_closed_rows()` + `build_kc_extraction_record()` composed --
    the one call a caller (a future engine.py trigger, or a human running the
    audit CLI by hand today) actually needs: two `ClosureRow` snapshots in,
    one list of real `route_and_store()`-shaped records out."""
    return [
        build_kc_extraction_record(row, mark_verified=mark_verified)
        for row in find_newly_closed_rows(previous_rows, current_rows)
    ]
