"""dv_harness/digital_thread_traceability.py -- Digital Thread / Full
Traceability: a single end-to-end trace (2026-09-06, spec section 231,
targeted_hardening item `digital_thread_traceability`).

THE CHAIN THIS ASSEMBLES. requirement -> vplan item -> pattern/command ->
test -> coverage bin -> regression evidence -> signoff. Every one of those
seven links was already a REAL, separately-computed fact somewhere in this
repo before this module existed; nothing joined them into ONE per-requirement
trace record. A human wanting to answer "is REQ-42 actually verified, all
the way through to signoff" had to open `.dv-harness/requirements.csv`, then
`env.manifest.json`'s `testplan_correspondence`, then a vPlan document, then
the evidence database, then `state.json`'s SIGNOFF stage -- five separate
artifacts -- and cross-reference them by hand.

REUSE OVER REINVENT -- verified before writing this file, not assumed. A
repo-wide grep for `digital_thread`/`DigitalThread`/`end_to_end_trace`/
`EndToEndTrace`/`full_traceability` found exactly one existing mechanism
naming the concept: `tools/verification_flow/end_to_end_trace_chain_gate.py`
(`STAGE_GATES["COMMAND_PATTERN"]`'s `end_to_end_trace_chain_gate`). Read
before building anything: that script is a pure referential-integrity check
over whatever JSON an AGENT already typed into its own evidence block --
`requirements`/`mechanisms`/`tests`/`coverage`/`results`/`links` are all
self-attested, and the script never opens `.dv-harness/requirements.csv`, an
`env.manifest.json`, a vPlan document, or the evidence database. It answers
"is the trace the AGENT CLAIMED internally consistent"; this module answers
"what does this project's OWN REAL artifacts say the trace actually is" --
a different, complementary question, and this module deliberately does not
touch that gate or its evidence-block contract.

Four real producers are read here, EACH FOR EXACTLY THE FACT IT ALREADY
COMPUTES, and NONE of their own matching/classification logic is re-derived:

  - `change_impact.load_trace_registry()` -- the REAL, already-parsed
    `.dv-harness/requirements.csv` rows (REQ_ID/SOURCE/SCOPE/VPLAN_ID/
    SCENARIO_ID/COMMAND_ID/PATTERN_ID/CHECKER_ID/COVERAGE_ID/RESULT/STATUS/
    EVIDENCE). This module never re-parses that CSV itself -- it is this
    project's own declared traceability shape and `change_impact.py` is
    already its one reader.
  - `vplan_artifact.build_vplan_hierarchy()` -- resolves a caller-supplied
    vPlan document's own `id -> row` map (`canonical_row`), used ONLY to
    check whether a registry's claimed VPLAN_ID really exists in the vPlan
    and whether that row's own `requirement_refs` really names the
    requirement the registry claims it satisfies. This module never
    re-implements duplicate/orphan/cycle detection -- `build_vplan_hierarchy`
    already does that, and its `gaps` are carried through verbatim.
  - `env_manifest.load_env_manifest()` / `env_topology.testplan_correspondence`
    -- the REAL three-way testlist/vPlan/coverage-model join `env_manifest.py`
    already computes per vPlan item (`tests_present`/`tests_missing`/
    `coverage_present`/`coverage_missing`/`verdict`). This module never
    re-joins a testlist against a vPlan or a coverage model itself -- it only
    asks, for the one item matching a registry row's VPLAN_ID, whether that
    row's own claimed PATTERN_ID/SCENARIO_ID/COMMAND_ID and COVERAGE_ID
    appear on the PRESENT or MISSING side of that item's already-computed
    verdict.
  - `golden_scenario.load_golden_scenarios()` / `evaluate_freshness()` -- the
    REAL recorded-PASS capsule store and its own FRESH/STALE/UNKNOWN
    freshness computation (itself built on `change_impact.changed_files()`).
    This module never records or re-derives freshness -- it only asks
    whether a capsule exists whose `test_name` matches the registry row's
    own claimed pattern/scenario/command id, and reports that capsule's own
    freshness verdict.
  - `signoff_export.read_signoff_stage_status()` -- the REAL SIGNOFF
    stage-gate outcome, read straight off `state.json`/`events.jsonl`
    (never re-derived; this module never opens either file itself).

HONESTY, per the Evidence Truth Rule and this repo's own worst-wins
discipline (never averaged): each of the six per-requirement links
(vplan_item, pattern_command, test, coverage_bin, regression_evidence,
signoff -- signoff is one shared project-level link, computed once and
attached to every chain) is one of five statuses, and the five are never
collapsed into fewer than five:

  - LINKED           -- real evidence from the relevant real producer
                         confirms this link.
  - BROKEN            -- real evidence from the relevant real producer
                         CONTRADICTS this link (a dangling VPLAN_ID, a
                         PATTERN_ID the testplan_correspondence's own
                         `tests_missing` names).
  - GAP               -- the registry (or the vPlan item's own claims)
                         itself declares nothing here (no PATTERN_ID, no
                         COVERAGE_ID, no recorded regression capsule, no
                         SIGNOFF stage record at all) -- a real, structural
                         absence, distinct from BROKEN (a false claim) and
                         from NOT_AVAILABLE (evidence this analysis was
                         never given).
  - STALE             -- regression-evidence only: a capsule was found, but
                         `golden_scenario.evaluate_freshness()` says it is
                         STALE.
  - NOT_AVAILABLE     -- the real producer needed to check this link was not
                         supplied to this analysis at all (no vPlan
                         document, no env.manifest.json, no evidence
                         database), or that producer's own real evidence is
                         itself inconclusive (freshness UNKNOWN, no matching
                         testplan_correspondence item). Never silently read
                         as LINKED.

Never a sixth ad hoc string, and the per-requirement `chain_status`
(TRACE_COMPLETE / TRACE_GAP / TRACE_INCOMPLETE_EVIDENCE / TRACE_BROKEN) is a
STRICT worst-wins fold over the six link severities -- one BROKEN link makes
the whole chain TRACE_BROKEN regardless of how many other links are LINKED,
one GAP/STALE (with nothing worse) makes it TRACE_GAP, one NOT_AVAILABLE
(with nothing worse) makes it TRACE_INCOMPLETE_EVIDENCE, and only six clean
LINKED links make it TRACE_COMPLETE. The whole-report `overall_status` is the
identical fold over every chain's `chain_status`, never an average or a
percentage.

This module ARBITRATES and DECIDES nothing: it builds and reports a trace.
No build, job, gate, or approval is touched, and there is deliberately no
`STAGE_GATES` entry -- a gate that passed because a chain nobody reviewed
happened to be TRACE_COMPLETE would be worse than none. No `dv-harness` CLI
verb was added (`cli.py`/`gates.py` were not touched, matching several very
recent same-day additions' own disclosed choice when those two files are
under concurrent edit pressure) -- the front door is
`python -m dv_harness.digital_thread_traceability`.

Deliberately bounded, and stated rather than implied closed. (1) A registry
row with an empty `.dv-harness/requirements.csv` (the real state of a fresh
project) reports the whole report `NOT_AVAILABLE` with the real reason,
never a vacuous TRACE_COMPLETE over zero chains. (2) CHECKER_ID is carried
through on every chain as informational metadata (this project's own
registry column) but is not one of the seven named links in this task's own
chain and is never independently classified. (3) Matching a registry row's
PATTERN_ID/SCENARIO_ID/COMMAND_ID against a testplan_correspondence item's
`tests_present`/`tests_missing`, or against a golden-scenario capsule's
`test_name`, is a LITERAL name match -- the same "never fuzzy" discipline
`env_manifest.py`'s own testplan_correspondence join already states for
itself, applied here rather than re-derived. (4) Vocabulary collision with
`models.Status` is checked at import, the same discipline several sibling
aggregator modules in this repo already apply to their own vocabularies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import change_impact
from . import env_manifest
from . import golden_scenario
from . import signoff_export
from . import vplan_artifact
from .connectivity import render_markdown_table

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

LINK_LINKED = "LINKED"
LINK_BROKEN = "BROKEN"
LINK_GAP = "GAP"
LINK_STALE = "STALE"
LINK_NOT_AVAILABLE = "NOT_AVAILABLE"

LINK_STATUSES = (LINK_LINKED, LINK_BROKEN, LINK_GAP, LINK_STALE, LINK_NOT_AVAILABLE)

#: Strict worst-wins severity. LINKED contributes nothing; everything else
#: is ranked so a single worse finding always outranks any number of better
#: ones -- never averaged, never a percentage.
_LINK_SEVERITY = {
    LINK_LINKED: 0,
    LINK_NOT_AVAILABLE: 1,
    LINK_GAP: 2,
    LINK_STALE: 2,
    LINK_BROKEN: 3,
}

TRACE_COMPLETE = "TRACE_COMPLETE"
TRACE_INCOMPLETE_EVIDENCE = "TRACE_INCOMPLETE_EVIDENCE"
TRACE_GAP = "TRACE_GAP"
TRACE_BROKEN = "TRACE_BROKEN"

_SEVERITY_TO_CHAIN_STATUS = {
    0: TRACE_COMPLETE,
    1: TRACE_INCOMPLETE_EVIDENCE,
    2: TRACE_GAP,
    3: TRACE_BROKEN,
}

REPORT_NOT_AVAILABLE = "NOT_AVAILABLE"

#: The six independently-classified links in this task's own named chain.
#: (signoff is one shared, project-level link attached to every chain.)
LINK_NAMES = (
    "vplan_item",
    "pattern_command",
    "test",
    "coverage_bin",
    "regression_evidence",
    "signoff",
)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary must never collide with a real stage-gate
    verdict -- the same guard several sibling aggregator modules in this repo
    already run on their own vocabularies (e.g. `system_closure_aggregator.py`,
    `spec_vplan_readiness_gate.py`)."""
    from .models import Status

    verdict_tokens = {member.value for member in Status}
    own_tokens = set(LINK_STATUSES) | {
        TRACE_COMPLETE, TRACE_INCOMPLETE_EVIDENCE, TRACE_GAP, TRACE_BROKEN,
        REPORT_NOT_AVAILABLE,
    }
    collision = verdict_tokens & own_tokens
    if collision:
        raise AssertionError(
            f"digital_thread_traceability vocabulary collides with models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


class DigitalThreadTraceabilityError(ValueError):
    """A caller-usage error: malformed input this module was explicitly
    handed (a structurally invalid vPlan document, an unreadable
    env.manifest.json). Never raised for an honestly ABSENT input -- that
    reports NOT_AVAILABLE on the links it affects instead."""


# ---------------------------------------------------------------------------
# Link result
# ---------------------------------------------------------------------------


@dataclass
class LinkResult:
    status: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "evidence": self.evidence}


def _severity(status: str) -> int:
    return _LINK_SEVERITY.get(status, 3)


# ---------------------------------------------------------------------------
# Per-link classifiers -- each reads one real producer's ALREADY-COMPUTED
# fact and never re-derives that producer's own matching/classification.
# ---------------------------------------------------------------------------


def _vplan_item_link(row: Dict[str, str], vplan_hierarchy: Optional[Dict[str, Any]]) -> LinkResult:
    vplan_id = (row.get("VPLAN_ID") or "").strip()
    req_id = (row.get("REQ_ID") or "").strip()

    if vplan_hierarchy is None:
        return LinkResult(LINK_NOT_AVAILABLE,
                           "no vplan_rows supplied to this analysis -- cannot confirm the "
                           "registry's VPLAN_ID against a real vPlan document")
    if not vplan_id:
        return LinkResult(LINK_GAP, "registry row declares no VPLAN_ID")

    canonical_row = vplan_hierarchy.get("canonical_row", {})
    if vplan_id not in canonical_row:
        return LinkResult(
            LINK_BROKEN,
            f"VPLAN_ID {vplan_id!r} is not the id of any row in the supplied vPlan document "
            "(dangling reference from the requirements.csv registry)",
            {"vplan_id": vplan_id})

    vrow = canonical_row[vplan_id]
    req_refs = list(vrow.get("requirement_refs") or [])
    if req_id and req_id in req_refs:
        return LinkResult(LINK_LINKED,
                           f"vPlan item {vplan_id!r} declares requirement_refs including "
                           f"{req_id!r}", {"vplan_id": vplan_id, "requirement_refs": req_refs})
    if not req_id:
        return LinkResult(LINK_GAP, "registry row declares no REQ_ID", {"vplan_id": vplan_id})
    return LinkResult(
        LINK_GAP,
        f"vPlan item {vplan_id!r} exists but its own requirement_refs ({req_refs!r}) do not "
        f"name {req_id!r} -- the registry's claimed link is unconfirmed by the vPlan itself",
        {"vplan_id": vplan_id, "requirement_refs": req_refs})


def _pattern_command_link(row: Dict[str, str]) -> LinkResult:
    pattern_id = (row.get("PATTERN_ID") or "").strip()
    scenario_id = (row.get("SCENARIO_ID") or "").strip()
    command_id = (row.get("COMMAND_ID") or "").strip()
    if pattern_id or scenario_id or command_id:
        return LinkResult(
            LINK_LINKED,
            "registry row declares a pattern/scenario/command identity",
            {"pattern_id": pattern_id, "scenario_id": scenario_id, "command_id": command_id})
    return LinkResult(LINK_GAP,
                       "registry row declares none of PATTERN_ID/SCENARIO_ID/COMMAND_ID")


def _candidate_ids(row: Dict[str, str]) -> List[str]:
    return [v for v in (
        (row.get("PATTERN_ID") or "").strip(),
        (row.get("SCENARIO_ID") or "").strip(),
        (row.get("COMMAND_ID") or "").strip(),
    ) if v]


def _find_testplan_item(testplan_correspondence: Optional[Dict[str, Any]],
                         vplan_id: str) -> Any:
    if not testplan_correspondence:
        return None
    for item in testplan_correspondence.get("items") or []:
        if item.get("id") == vplan_id:
            return item
    return None


def _test_and_coverage_links(row: Dict[str, str],
                              testplan_correspondence: Optional[Dict[str, Any]]):
    vplan_id = (row.get("VPLAN_ID") or "").strip()

    if testplan_correspondence is None:
        na = LinkResult(LINK_NOT_AVAILABLE,
                         "no env.manifest.json testplan_correspondence supplied to this analysis")
        return na, LinkResult(na.status, na.reason)

    if testplan_correspondence.get("status") == "NOT_AVAILABLE":
        reason = ("env.manifest.json testplan_correspondence is NOT_AVAILABLE: "
                  f"{testplan_correspondence.get('reason')}")
        na = LinkResult(LINK_NOT_AVAILABLE, reason)
        return na, LinkResult(na.status, na.reason)

    item = _find_testplan_item(testplan_correspondence, vplan_id)
    if item is None:
        reason = (f"no testplan_correspondence item found for VPLAN_ID {vplan_id!r} -- the "
                  "real testplan_sources.json this manifest was built from carries no "
                  "vplan_items entry with this id")
        na = LinkResult(LINK_NOT_AVAILABLE, reason)
        return na, LinkResult(na.status, na.reason)

    candidates = _candidate_ids(row)
    tests_present = set(item.get("tests_present") or [])
    tests_missing = set(item.get("tests_missing") or [])
    coverage_present = set(item.get("coverage_present") or [])
    coverage_missing = set(item.get("coverage_missing") or [])
    coverage_id = (row.get("COVERAGE_ID") or "").strip()
    verdict = item.get("verdict")

    # -- test link --
    broken_candidates = [c for c in candidates if c in tests_missing]
    linked_candidates = [c for c in candidates if c in tests_present]
    if broken_candidates:
        test_link = LinkResult(
            LINK_BROKEN,
            f"testplan_correspondence item {vplan_id!r} lists {broken_candidates} among its "
            f"own tests_missing (verdict={verdict})",
            {"tests_missing": sorted(tests_missing)})
    elif linked_candidates:
        test_link = LinkResult(
            LINK_LINKED,
            f"testplan_correspondence item {vplan_id!r} confirms {linked_candidates} present "
            "in the real testlist",
            {"tests_present": sorted(tests_present)})
    elif not candidates:
        test_link = LinkResult(LINK_GAP,
                                "registry row declares no PATTERN_ID/SCENARIO_ID/COMMAND_ID "
                                "to check against the testplan_correspondence")
    elif not (tests_present or tests_missing):
        test_link = LinkResult(
            LINK_GAP,
            f"vPlan item {vplan_id!r} claims no tests at all (testplan_correspondence "
            f"verdict={verdict})")
    else:
        test_link = LinkResult(
            LINK_NOT_AVAILABLE,
            f"none of {candidates} is named among vPlan item {vplan_id!r}'s own declared "
            "test claims -- testplan_correspondence cannot confirm or refute this link")

    # -- coverage link --
    if coverage_id and coverage_id in coverage_missing:
        coverage_link = LinkResult(
            LINK_BROKEN,
            f"testplan_correspondence item {vplan_id!r} lists {coverage_id!r} among its own "
            f"coverage_missing (verdict={verdict})",
            {"coverage_missing": sorted(coverage_missing)})
    elif coverage_id and coverage_id in coverage_present:
        coverage_link = LinkResult(
            LINK_LINKED,
            f"testplan_correspondence item {vplan_id!r} confirms {coverage_id!r} present in "
            "the real coverage model",
            {"coverage_present": sorted(coverage_present)})
    elif not coverage_id:
        coverage_link = LinkResult(LINK_GAP, "registry row declares no COVERAGE_ID")
    elif not (coverage_present or coverage_missing):
        coverage_link = LinkResult(
            LINK_GAP,
            f"vPlan item {vplan_id!r} claims no coverage at all (testplan_correspondence "
            f"verdict={verdict})")
    else:
        coverage_link = LinkResult(
            LINK_NOT_AVAILABLE,
            f"{coverage_id!r} is not named among vPlan item {vplan_id!r}'s own declared "
            "coverage claims -- testplan_correspondence cannot confirm or refute this link")

    return test_link, coverage_link


def _regression_evidence_link(row: Dict[str, str], store, root: Path) -> LinkResult:
    candidates = _candidate_ids(row)
    if store is None:
        return LinkResult(LINK_NOT_AVAILABLE,
                           "no evidence database supplied to this analysis -- cannot check "
                           "for a recorded golden-scenario capsule")
    if not candidates:
        return LinkResult(LINK_GAP,
                           "registry row declares no PATTERN_ID/SCENARIO_ID/COMMAND_ID to "
                           "match regression evidence against")

    capsules = golden_scenario.load_golden_scenarios(store)
    match = next((c for c in capsules if c.test_name in candidates), None)
    if match is None:
        return LinkResult(
            LINK_GAP,
            f"no golden-scenario capsule recorded with test_name in {candidates}",
            {"candidates": candidates})

    fresh = golden_scenario.evaluate_freshness(root, match)
    freshness = fresh.get("freshness")
    req_id = (row.get("REQ_ID") or "").strip()
    corroborated = bool(req_id) and req_id in (match.requirements or [])
    evidence = {
        "capsule_id": match.capsule_id,
        "job_id": match.job_id,
        "verified_sha": match.verified_sha,
        "requirement_corroborated": corroborated,
    }
    if freshness == golden_scenario.FRESH:
        return LinkResult(LINK_LINKED,
                           f"golden-scenario capsule {match.capsule_id!r} is FRESH", evidence)
    if freshness == golden_scenario.STALE:
        evidence["reasons"] = fresh.get("reasons")
        return LinkResult(LINK_STALE,
                           f"golden-scenario capsule {match.capsule_id!r} is STALE: "
                           f"{fresh.get('reasons')}", evidence)
    evidence["reasons"] = fresh.get("reasons")
    return LinkResult(LINK_NOT_AVAILABLE,
                       f"golden-scenario capsule {match.capsule_id!r} freshness is UNKNOWN: "
                       f"{fresh.get('reasons')}", evidence)


def _signoff_link(signoff_status: Dict[str, Any]) -> LinkResult:
    if signoff_status.get("gate_verified"):
        return LinkResult(LINK_LINKED,
                           "SIGNOFF stage is gate-verified (state.json)",
                           {"stage_status": signoff_status.get("stage_status")})
    stage_status = signoff_status.get("stage_status")
    if not signoff_status.get("state_file_present") or not stage_status:
        return LinkResult(LINK_GAP, "SIGNOFF stage has never been recorded (no state.json, "
                                     "or no SIGNOFF stage entry)")
    return LinkResult(LINK_GAP,
                       f"SIGNOFF stage status is {stage_status!r}, not gate-verified",
                       {"stage_status": stage_status})


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _open_evidence_store(root: Path, db_path: Optional[str]):
    from .evidence_db import EvidenceStore, default_db_path
    path = Path(db_path) if db_path else default_db_path(root)
    if not Path(path).exists():
        return None
    return EvidenceStore(path, read_only=True)


def _load_testplan_correspondence(root: Path, env_manifest_path: Optional[str]):
    path = Path(env_manifest_path) if env_manifest_path else env_manifest.default_manifest_path(root)
    if not path or not Path(path).exists():
        return None, {"supplied": False, "path": str(path) if path else None}
    try:
        manifest = env_manifest.load_env_manifest(path)
    except env_manifest.EnvManifestValidationError as exc:
        return None, {"supplied": True, "path": str(path), "load_error": str(exc)}
    tp = ((manifest.get("env_topology") or {}).get("testplan_correspondence"))
    return tp, {"supplied": True, "path": str(path)}


def assemble_digital_thread(root, *,
                             vplan_rows: Optional[List[Dict[str, Any]]] = None,
                             env_manifest_path: Optional[str] = None,
                             db_path: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the full end-to-end digital thread trace for a project.

    Every requirement in `.dv-harness/requirements.csv` becomes one chain
    record. `vplan_rows` / `env_manifest_path` / `db_path` are optional --
    an omitted one degrades only the links it feeds to NOT_AVAILABLE,
    never fabricates a value for it.
    """
    root = Path(root)
    registry = change_impact.load_trace_registry(root)
    if not registry:
        return {
            "status": REPORT_NOT_AVAILABLE,
            "reason": "no rows in .dv-harness/requirements.csv -- nothing to trace",
            "chains": [],
            "sources": {
                "requirements_csv": str(root.joinpath(".dv-harness", "requirements.csv")),
                "vplan_supplied": vplan_rows is not None,
                "env_manifest_supplied": False,
                "evidence_db_supplied": False,
            },
            "summary": {},
        }

    vplan_hierarchy = None
    if vplan_rows is not None:
        try:
            vplan_artifact.validate_vplan_document(vplan_rows)
        except vplan_artifact.VPlanArtifactValidationError as exc:
            raise DigitalThreadTraceabilityError(
                f"vplan_rows is not a structurally valid vPlan document: {exc}") from exc
        vplan_hierarchy = vplan_artifact.build_vplan_hierarchy(vplan_rows)

    testplan_correspondence, manifest_source = _load_testplan_correspondence(root, env_manifest_path)

    store = _open_evidence_store(root, db_path)
    signoff_status = signoff_export.read_signoff_stage_status(root)
    signoff_link = _signoff_link(signoff_status)

    chains: List[Dict[str, Any]] = []
    try:
        for index, row in enumerate(registry):
            vplan_link = _vplan_item_link(row, vplan_hierarchy)
            pattern_link = _pattern_command_link(row)
            test_link, coverage_link = _test_and_coverage_links(row, testplan_correspondence)
            regression_link = _regression_evidence_link(row, store, root)

            links = {
                "vplan_item": vplan_link,
                "pattern_command": pattern_link,
                "test": test_link,
                "coverage_bin": coverage_link,
                "regression_evidence": regression_link,
                "signoff": signoff_link,
            }
            chain_status = _SEVERITY_TO_CHAIN_STATUS[max(
                _severity(links[name].status) for name in LINK_NAMES)]

            chains.append({
                "row_index": index,
                "req_id": row.get("REQ_ID", ""),
                "vplan_id": row.get("VPLAN_ID", ""),
                "pattern_id": row.get("PATTERN_ID", ""),
                "scenario_id": row.get("SCENARIO_ID", ""),
                "command_id": row.get("COMMAND_ID", ""),
                "checker_id": row.get("CHECKER_ID", ""),
                "coverage_id": row.get("COVERAGE_ID", ""),
                "links": {name: links[name].to_dict() for name in LINK_NAMES},
                "chain_status": chain_status,
            })
    finally:
        if store is not None:
            store.close()

    overall_status = _worst_chain_status(chains)

    counts: Dict[str, int] = {}
    for c in chains:
        counts[c["chain_status"]] = counts.get(c["chain_status"], 0) + 1

    return {
        "status": overall_status,
        "reason": None,
        "chains": chains,
        "sources": {
            "requirements_csv": str(root.joinpath(".dv-harness", "requirements.csv")),
            "requirements_csv_row_count": len(registry),
            "vplan_supplied": vplan_rows is not None,
            "env_manifest": manifest_source,
            "evidence_db_supplied": store is not None,
        },
        "summary": {"total_chains": len(chains), "by_chain_status": counts},
    }


def _worst_chain_status(chains: Sequence[Dict[str, Any]]) -> str:
    """Worst-wins fold across every chain's own `chain_status` -- a single
    TRACE_BROKEN chain makes the whole report's overall status TRACE_BROKEN,
    never averaged against however many other chains are TRACE_COMPLETE."""
    if not chains:
        return REPORT_NOT_AVAILABLE
    order = [TRACE_BROKEN, TRACE_GAP, TRACE_INCOMPLETE_EVIDENCE, TRACE_COMPLETE]
    present = {c["chain_status"] for c in chains}
    for status in order:
        if status in present:
            return status
    return REPORT_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_digital_thread_markdown(report: Dict[str, Any]) -> str:
    if report.get("status") == REPORT_NOT_AVAILABLE and not report.get("chains"):
        return f"Digital Thread Trace: NOT_AVAILABLE -- {report.get('reason')}"
    rows = []
    for c in report["chains"]:
        row = {
            "req_id": c["req_id"],
            "vplan_id": c["vplan_id"],
            "pattern_id": c["pattern_id"] or c["scenario_id"] or c["command_id"],
            "test": c["links"]["test"]["status"],
            "coverage_bin": c["links"]["coverage_bin"]["status"],
            "regression_evidence": c["links"]["regression_evidence"]["status"],
            "signoff": c["links"]["signoff"]["status"],
            "chain_status": c["chain_status"],
        }
        rows.append(row)
    columns = [
        ("req_id", "REQ_ID"), ("vplan_id", "VPLAN_ID"), ("pattern_id", "PATTERN/COMMAND"),
        ("test", "Test"), ("coverage_bin", "Coverage Bin"),
        ("regression_evidence", "Regression Evidence"), ("signoff", "Signoff"),
        ("chain_status", "Chain Status"),
    ]
    header = f"Digital Thread Trace: {report['status']} " \
             f"({report['summary'].get('total_chains', 0)} requirement(s))\n\n"
    return header + render_markdown_table(columns, rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def execute_verb(root, *, vplan_file: Optional[str] = None, env_manifest_path: Optional[str] = None,
                  db_path: Optional[str] = None, as_json: bool = False):
    vplan_rows = None
    if vplan_file:
        vplan_rows = json.loads(Path(vplan_file).read_text(encoding="utf-8"))
    report = assemble_digital_thread(root, vplan_rows=vplan_rows,
                                      env_manifest_path=env_manifest_path, db_path=db_path)
    text = json.dumps(report, indent=2) if as_json else render_digital_thread_markdown(report)
    if report["status"] == REPORT_NOT_AVAILABLE:
        code = 2
    elif report["status"] in (TRACE_BROKEN, TRACE_GAP):
        code = 1
    elif report["status"] == TRACE_INCOMPLETE_EVIDENCE:
        code = 2
    else:
        code = 0
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m dv_harness.digital_thread_traceability")
    ap.add_argument("--root", default=".")
    ap.add_argument("--vplan-file", default=None,
                     help="JSON file: a list of vplan_artifact-shaped rows")
    ap.add_argument("--env-manifest", default=None, help="explicit env.manifest.json path")
    ap.add_argument("--db-path", default=None, help="explicit evidence.duckdb path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    text, code = execute_verb(args.root, vplan_file=args.vplan_file,
                               env_manifest_path=args.env_manifest, db_path=args.db_path,
                               as_json=args.json)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
