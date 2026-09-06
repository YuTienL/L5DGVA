"""dv_harness/functional_coverage_signoff.py -- FUNCTIONAL_COVERAGE_SIGNOFF_READY
verdict + Closure metric, a read-only rollup over three real existing sources
(2026-09-06).

THE GAP THIS CLOSES. "Is functional coverage closed enough to sign off" is
answered today only by a human reading three unrelated artifacts by hand: the
waiver ledger (`dv_harness/waiver_store.py`), the coverage hole classifier
(`dv_harness/coverage_analysis.py`) and the testplan/coverage correspondence
(`dv_harness/env_manifest.py`'s `testplan_correspondence`, cross-checked
against the real recorded numbers in `evidence_db.EvidenceStore`). Nothing
joined the three into one Closure percentage or one READY/NOT_READY verdict,
so two audits of the same project could disagree about the same facts --
exactly the gap `golden_flow_readiness.py` and `platform_health.py` closed for
their own domains, and this module follows their same rollup-module
convention (reader only, honest absence, one shared `execute()`).

WHAT THIS MODULE READS, and reads ONLY -- nothing here re-measures a fact
another module already computed:

  - `waiver_store.status_report()`     -- every recorded waiver with its
                                          DERIVED status (VALID /
                                          REVALIDATION_REQUIRED / EXPIRED /
                                          REVOKED / UNKNOWN). A waiver is
                                          matched to a coverage bin by a
                                          literal `item == coverage_id` name
                                          join -- the same "never fuzzy"
                                          discipline env_manifest.py's own
                                          testplan/coverage join applies.
  - `coverage_analysis.identify_holes()` / `classify_coverage_hole()` -- the
                                          real differentiated hole verdict
                                          (MISSING_TEST / INSUFFICIENT_
                                          CONSTRAINT / UNREACHABLE_STIMULUS /
                                          INSUFFICIENT_SEED_ATTEMPTS), fed the
                                          project's own recorded
                                          `root_cause_classification` claim
                                          (read from the real COVERAGE_CLOSURE
                                          stage's `coverage_hole_regeneration_
                                          gate` evidence block, never
                                          invented).
  - `env_manifest.py`'s `testplan_correspondence` -- which coverage bin names
                                          are DECLARED by at least one real
                                          vPlan item (`coverage_present`),
                                          i.e. which bins the project's own
                                          testplan says must close.
  - `evidence_db.EvidenceStore` (read-only) -- the `coverage_samples` table's
                                          most-recently-landed row per
                                          category is the ACTUALLY-RECORDED
                                          percent/bins_total/bins_hit this
                                          module computes Covered/Total from
                                          -- never the live (possibly
                                          hand-edited, possibly stale)
                                          `.dv-harness/coverage/summary.json`,
                                          which `dashboard.py`'s own
                                          `_ingest_coverage_summary_to_
                                          evidence_db()` is what lands into
                                          this same table in the first place.

WHY "PROVEN unreachable" NEEDS A HUMAN, NOT JUST A CLASSIFICATION.
`classify_coverage_hole()`'s UNREACHABLE_STIMULUS verdict is the AGENT's own
claim -- that module's own docstring says "only the design owner can confirm
that" and its `escalate_unreachable_stimulus()` routes exactly this question
to `question_queue.py` as a Tier-3 cannot-assume question owned by the
designer. A hole only counts here as PROVEN once a real human has ANSWERED
that question `STRUCTURALLY_UNREACHABLE` (`question_queue.QuestionQueueStore.
answer_question()`, the one path that reaches `status == "ANSWERED"`) --
never on the agent's classification alone, and never on a Tier-2 auto-assumed
or Tier-1 self-resolved record, which this module's own read never even
looks at. A later reconsideration (the design owner answers again) overrides
an earlier confirmation, because the most recently ANSWERED record for that
bin decides.

CLOSURE FORMULA, over the DECLARED coverage-goal bins that have real recorded
numbers:

    Closure % = 100 * (Covered_bins + ApprovedWaiver_bins + ProvenUnreachable_bins)
                / Total_declared_goal_bins

  - Covered_bins           = sum(bins_hit) over declared, recorded categories.
  - ApprovedWaiver_bins    = bins_missing for a category carrying at least one
                             VALID waiver (`item == coverage_id`).
  - ProvenUnreachable_bins = bins_missing for a category classified
                             UNREACHABLE_STIMULUS AND confirmed by a real
                             human answer (see above). An UNDER-SAMPLED hole
                             (INSUFFICIENT_SEED_ATTEMPTS) NEVER counts here,
                             by construction -- classify_coverage_hole() only
                             reaches UNREACHABLE_STIMULUS once the seed-attempt
                             floor is cleared, so "not enough seeds yet" and
                             "structurally unreachable" can never be credited
                             through the same path.
  - A waiver takes priority when both apply to the same category (the
    category is credited once, never twice, for one bins_missing value).

FUNCTIONAL_COVERAGE_SIGNOFF_READY is true only when: the evidence database and
at least one declared coverage bin are available; every declared bin has a
real recorded number (a declared bin with NO recorded evidence at all reports
INCOMPLETE_EVIDENCE and blocks readiness -- a percentage computed only over
the bins somebody happened to measure must never be presented as the whole
project's closure); Closure reaches 100%; and no waiver matching any declared
bin (whether or not it is the one being credited) carries status EXPIRED,
REVOKED or UNKNOWN.

HONEST ABSENCE, NEVER A SILENT 0 OR 100. An absent evidence database or an
absent waiver ledger is reported as `NOT_AVAILABLE` for that specific input --
never treated as "0% covered" and never treated as "no waivers, so nothing to
block on" being silently folded into a passing verdict without saying so. An
absent evidence database makes the WHOLE report NOT_AVAILABLE (Covered/Total
both come from it, so there is nothing left to compute); an absent waiver
ledger only means zero waiver credit and zero waiver blocking are contributed
-- a real, disclosed zero, not a fabricated one.

THIS MODULE DECIDES, APPROVES AND ARBITRATES NOTHING. No stage runs, no gate
script is invoked, no waiver is recorded or revoked, no question is asked or
answered, and no approval is minted. It is a reader whose verdict is an input
to a human's signoff decision, exactly like `golden_flow_readiness.py`'s own
matrix and `platform_health.py`'s own health report.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import coverage_analysis as ca
from . import waiver_store as ws

SCHEMA_VERSION = "1.0"

STATUS_SIGNOFF_READY = "SIGNOFF_READY"
STATUS_OPEN = "OPEN"
STATUS_BLOCKED_BY_WAIVER = "BLOCKED_BY_WAIVER"
STATUS_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
CLOSURE_STATUSES: Tuple[str, ...] = (
    STATUS_SIGNOFF_READY, STATUS_OPEN, STATUS_BLOCKED_BY_WAIVER,
    STATUS_INCOMPLETE_EVIDENCE, STATUS_NOT_AVAILABLE,
)

#: Section 237's own five-value vocabulary (`waiver_store.WAIVER_STATUSES`)
#: is what a matched waiver's status is drawn from; these three are the ones
#: THIS module's own formula names as signoff-blocking. REVALIDATION_REQUIRED
#: is deliberately NOT in this set: it neither counts toward closure (only
#: VALID does) nor blocks signoff by this module's own stated formula.
BLOCKING_WAIVER_STATUSES: Tuple[str, ...] = ("EXPIRED", "REVOKED", "UNKNOWN")

#: coverage_analysis.escalate_unreachable_stimulus()'s own option label for
#: "the design owner confirmed this bin cannot be reached". Named as a
#: constant here (rather than re-typed inline) so a future rename of that
#: label breaks this module's import-time reasoning, not just its runtime
#: matching.
UNREACHABLE_CONFIRMED_ANSWER = "STRUCTURALLY_UNREACHABLE"

CREDIT_MEASURED = "MEASURED_COVERED"
CREDIT_APPROVED_WAIVER = "APPROVED_WAIVER"
CREDIT_PROVEN_UNREACHABLE = "PROVEN_UNREACHABLE"
CREDIT_NONE = "OPEN_GAP"


class FunctionalCoverageSignoffError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Source 1: waiver_store.status_report()
# ===========================================================================

def _waiver_input(root: Path) -> Dict[str, Any]:
    """Every recorded waiver with its derived status, or a real
    NOT_AVAILABLE when no ledger exists -- never a silent "zero waivers"
    standing in for "we could not check"."""
    if not ws.store_exists(root):
        return {"status": "NOT_AVAILABLE", "reason": "NO_WAIVER_LEDGER", "rows": []}
    report = ws.status_report(root)
    return {"status": "AVAILABLE", "rows": list(report.get("waivers") or [])}


def _waivers_for_item(waiver_rows: List[Dict[str, Any]], item_name: str) -> List[Dict[str, Any]]:
    """Literal name join on `item` -- never fuzzy, the same discipline
    env_manifest.build_testplan_correspondence() applies to its own join."""
    return [r for r in waiver_rows if str(r.get("item") or "") == item_name]


# ===========================================================================
# Source 3a: env_manifest.py testplan_correspondence
# ===========================================================================

def _testplan_declared_bins(root: Path) -> Dict[str, Any]:
    """coverage-bin name -> {"vplan_items": [...]} for every coverage-model
    name a real vPlan item claims (`coverage_present`), read from
    env.manifest.json's own `testplan_correspondence`. NOT_AVAILABLE (with a
    real reason) when no manifest exists, it cannot be read, or the
    correspondence itself was never built -- an empty declared set must never
    be produced by silently swallowing an absence."""
    from . import env_manifest as em
    try:
        path = em.default_manifest_path(root)
    except Exception as e:
        return {"status": "NOT_AVAILABLE",
                "reason": f"ENV_MANIFEST_POLICY_UNREADABLE:{e}", "declared": {}}
    if path is None or not Path(path).exists():
        return {"status": "NOT_AVAILABLE", "reason": "NO_ENV_MANIFEST", "declared": {}}
    try:
        manifest = em.load_env_manifest(path)
    except Exception as e:
        return {"status": "NOT_AVAILABLE",
                "reason": f"ENV_MANIFEST_UNREADABLE:{e}", "declared": {}}
    corr = ((manifest.get("env_topology") or {}).get("testplan_correspondence")
            if isinstance(manifest, dict) else None)
    if not isinstance(corr, dict) or corr.get("status") == "NOT_AVAILABLE":
        reason = (corr or {}).get("reason") if isinstance(corr, dict) else None
        return {"status": "NOT_AVAILABLE",
                "reason": str(reason or "NO_TESTPLAN_CORRESPONDENCE"), "declared": {}}
    declared: Dict[str, Dict[str, Any]] = {}
    for item in corr.get("items") or []:
        for name in item.get("coverage_present") or []:
            declared.setdefault(name, {"vplan_items": []})["vplan_items"].append(item.get("id"))
    return {"status": "AVAILABLE", "declared": declared}


# ===========================================================================
# Source 3b: evidence_db.EvidenceStore, read-only -- actually-recorded numbers
# ===========================================================================

def _recorded_coverage_categories(root: Path) -> Dict[str, Any]:
    """Most-recent `coverage_samples` row per category, from the real,
    read-only evidence database -- never the live summary.json, which may be
    stale, hand-edited, or simply not yet landed as evidence. NOT_AVAILABLE
    (with a real reason) when the database does not exist or cannot be
    opened -- never a silent 0% standing in for "nothing was measured"."""
    try:
        from .evidence_db import EvidenceStore, default_db_path
    except Exception as e:
        return {"status": "NOT_AVAILABLE",
                "reason": f"EVIDENCE_DB_MODULE_UNAVAILABLE:{e}", "categories": {}}
    db_path = default_db_path(Path(root))
    if not Path(db_path).exists():
        return {"status": "NOT_AVAILABLE", "reason": "NO_EVIDENCE_DATABASE", "categories": {}}
    try:
        with EvidenceStore(db_path, read_only=True) as store:
            rows = store.query(
                "SELECT category_name, percent, bins_total, bins_hit, sample_timestamp, id "
                "FROM coverage_samples ORDER BY id DESC")
    except Exception as e:
        return {"status": "NOT_AVAILABLE",
                "reason": f"EVIDENCE_DB_UNREADABLE:{e}", "categories": {}}
    categories: Dict[str, Dict[str, Any]] = {}
    for name, percent, bins_total, bins_hit, ts, _id in rows:
        if name is None or name in categories:
            continue  # ORDER BY id DESC: the first row seen per name is the latest
        categories[str(name)] = {"percent": percent, "bins_total": bins_total,
                                  "bins_hit": bins_hit, "sample_timestamp": ts}
    return {"status": "AVAILABLE", "categories": categories}


# ===========================================================================
# Source 2 support: the agent's own recorded hole classification claim, and
# the real human confirmation of an UNREACHABLE_STIMULUS claim
# ===========================================================================

def _agent_hole_claims(root: Path) -> Dict[str, Dict[str, Any]]:
    """coverage_id -> the project's own recorded `coverage_hole_regeneration_
    gate` evidence entry for the COVERAGE_CLOSURE stage (the real
    `root_cause_classification` / `escalation_question_id` an agent claimed),
    or {} when none was ever recorded. Read through
    `dashboard._read_json_file()` (never `storage.StateStore.load()`, which
    would MINT a state.json for a project that has never run) -- this module
    is a reader and must never change the readiness it reports on, the same
    discipline `golden_flow_readiness.py` holds itself to."""
    from .dashboard import _read_json_file
    from .gates import extract_evidence_blocks
    state = _read_json_file(Path(root) / ".dv-harness" / "state.json")
    if not isinstance(state, dict):
        return {}
    rec = (state.get("stages") or {}).get("COVERAGE_CLOSURE") or {}
    try:
        blocks = extract_evidence_blocks(rec.get("last_message") or "")
    except Exception:
        return {}
    payload = blocks.get("coverage_hole_regeneration_gate")
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for h in payload.get("coverage_holes") or []:
        if isinstance(h, dict) and h.get("coverage_id"):
            out[str(h["coverage_id"])] = h
    return out


def _human_confirmed_unreachable(root: Path, coverage_id: str,
                                  escalation_question_id: Optional[str] = None
                                  ) -> Optional[Dict[str, Any]]:
    """The real, human-ANSWERED confirmation of one bin's unreachability
    escalation, or None. Never the agent's classification alone -- see the
    module docstring. Prefers the agent's own cited `escalation_question_id`
    (the exact question `coverage_hole_regeneration_gate.py` itself requires);
    falls back to the newest ANSWERED question filed against this bin's own
    `coverage/<id>` context_path (the shape
    `coverage_analysis.escalate_unreachable_stimulus()` files). A later
    reconsideration overrides an earlier one: only the most recently answered
    record decides, never an OR across every answer ever given."""
    from .question_queue import QuestionQueueStore
    store = QuestionQueueStore(Path(root))
    context_path = f"coverage/{coverage_id}"
    candidate = None
    if escalation_question_id:
        q = store.get_question(str(escalation_question_id))
        if q is not None and q.get("context_path") == context_path:
            candidate = q
    if candidate is None:
        matches = [q for q in store.list_questions(status="ANSWERED", domain="dut")
                   if q.get("context_path") == context_path]
        if matches:
            candidate = max(matches, key=lambda q: q.get("answered_at") or "")
    if candidate is None or candidate.get("status") != "ANSWERED":
        return None
    if str(candidate.get("answer") or "").strip().upper() != UNREACHABLE_CONFIRMED_ANSWER:
        return None
    return candidate


# ===========================================================================
# The rollup
# ===========================================================================

def analyze_functional_coverage_signoff(root, cfg: Optional[Dict[str, Any]] = None
                                          ) -> Dict[str, Any]:
    """The FUNCTIONAL_COVERAGE_SIGNOFF_READY verdict + Closure metric for one
    real project root. Read-only and total: every input's own status is
    always reported, including its absences."""
    root = Path(root)
    waiver_in = _waiver_input(root)
    testplan_in = _testplan_declared_bins(root)
    recorded_in = _recorded_coverage_categories(root)
    agent_claims = _agent_hole_claims(root)
    waiver_rows = waiver_in.get("rows") or []

    if testplan_in["status"] == "AVAILABLE":
        declared_names = sorted(testplan_in["declared"])
        scope_source = "TESTPLAN_CORRESPONDENCE"
        scope_reason = None
    elif recorded_in["status"] == "AVAILABLE":
        declared_names = sorted(recorded_in["categories"])
        scope_source = "ALL_RECORDED_CATEGORIES"
        scope_reason = ("no testplan correspondence was available "
                         f"({testplan_in.get('reason')}); scope widened to every "
                         "category the evidence database has ever recorded")
    else:
        declared_names = []
        scope_source = "NONE"
        scope_reason = testplan_in.get("reason")

    base: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "waiver_input": {"status": waiver_in["status"], "reason": waiver_in.get("reason")},
        "testplan_input": {"status": testplan_in["status"], "reason": testplan_in.get("reason")},
        "evidence_db_input": {"status": recorded_in["status"], "reason": recorded_in.get("reason")},
        "declared_scope_source": scope_source,
        "declared_scope_reason": scope_reason,
    }

    def _not_available(reason: str) -> Dict[str, Any]:
        return {
            **base, "status": STATUS_NOT_AVAILABLE, "reason": reason,
            "functional_coverage_signoff_ready": None, "closure_percent": None,
            "covered_bins": None, "credited_bins": None, "total_goal_bins": None,
            "rows": [], "unrecorded_declared": [], "malformed_categories": [],
            "blocking_waivers": [],
        }

    if recorded_in["status"] != "AVAILABLE":
        return _not_available(recorded_in.get("reason") or "EVIDENCE_DATABASE_UNAVAILABLE")
    if not declared_names:
        return _not_available("NO_DECLARED_COVERAGE_GOAL")

    recorded = recorded_in["categories"]
    unrecorded_declared = [n for n in declared_names if n not in recorded]

    cat_list = []
    malformed: List[Dict[str, Any]] = []
    for name in declared_names:
        rec = recorded.get(name)
        if rec is None:
            continue
        try:
            cat_list.append({"name": name, "percent": float(rec["percent"]),
                              "bins_total": int(rec["bins_total"]),
                              "bins_hit": int(rec["bins_hit"])})
        except Exception as e:
            malformed.append({"coverage_id": name, "reason": str(e)})

    holes_by_name: Dict[str, Dict[str, Any]] = {}
    if cat_list:
        try:
            parsed = ca.parse_coverage_summary({"categories": cat_list})
        except ca.CoverageAnalysisError as e:
            out = _not_available(f"MALFORMED_RECORDED_COVERAGE:{e.reason}")
            out["unrecorded_declared"] = unrecorded_declared
            out["malformed_categories"] = malformed
            return out
        holes_by_name = {h["name"]: h for h in ca.identify_holes(parsed)}

    rows: List[Dict[str, Any]] = []
    blocking_waivers: List[Dict[str, Any]] = []
    covered_bins = 0
    credited_bins = 0
    total_goal_bins = 0

    for name in declared_names:
        rec = recorded.get(name)
        if rec is None:
            continue
        bins_total = int(rec["bins_total"])
        bins_hit = int(rec["bins_hit"])
        bins_missing = bins_total - bins_hit
        total_goal_bins += bins_total
        covered_bins += bins_hit

        waivers_here = _waivers_for_item(waiver_rows, name)
        valid_waiver = next((w for w in waivers_here if w.get("status") == "VALID"), None)
        for w in waivers_here:
            if w.get("status") in BLOCKING_WAIVER_STATUSES:
                blocking_waivers.append({"coverage_id": name, "waiver_id": w.get("waiver_id"),
                                          "status": w.get("status")})

        row: Dict[str, Any] = {
            "coverage_id": name,
            "percent": rec["percent"], "bins_total": bins_total, "bins_hit": bins_hit,
            "bins_missing": bins_missing,
            "declared_by_vplan_items": (testplan_in["declared"].get(name, {}).get("vplan_items")
                                         if testplan_in["status"] == "AVAILABLE" else None),
            "sample_timestamp": rec.get("sample_timestamp"),
            "waiver_status": valid_waiver.get("status") if valid_waiver else
                              (waivers_here[0].get("status") if waivers_here else None),
        }

        hole = holes_by_name.get(name)
        if hole is None:
            row.update({"classification": None, "classification_basis": None,
                        "credited_bins": 0, "credit_source": CREDIT_MEASURED,
                        "human_confirmed_unreachable": False})
            rows.append(row)
            continue

        agent_hole = agent_claims.get(name) or {}
        cls_hole = {"coverage_id": name,
                    "root_cause_classification": agent_hole.get("root_cause_classification")}
        verdict = ca.classify_coverage_hole(root, cls_hole, cfg=cfg)
        classification = verdict.get("classification")

        credit = 0
        credit_source = CREDIT_NONE
        proven = None
        if valid_waiver is not None:
            credit = bins_missing
            credit_source = CREDIT_APPROVED_WAIVER
        elif classification == ca.ROOT_CAUSE_UNREACHABLE_STIMULUS:
            proven = _human_confirmed_unreachable(
                root, name, escalation_question_id=agent_hole.get("escalation_question_id"))
            if proven is not None:
                credit = bins_missing
                credit_source = CREDIT_PROVEN_UNREACHABLE
        credited_bins += credit

        row.update({
            "classification": classification,
            "classification_basis": verdict.get("basis"),
            "distinct_seed_attempts": verdict.get("distinct_seed_attempts"),
            "min_seed_attempts": verdict.get("min_seed_attempts"),
            "credited_bins": credit,
            "credit_source": credit_source,
            "human_confirmed_unreachable": bool(proven),
        })
        rows.append(row)

    incomplete = bool(unrecorded_declared)
    closure_percent = (round(100.0 * (covered_bins + credited_bins) / total_goal_bins, 4)
                        if total_goal_bins else None)
    ready = bool(
        total_goal_bins > 0 and not incomplete and closure_percent is not None
        and closure_percent >= 100.0 and not blocking_waivers
    )

    if total_goal_bins == 0:
        status = STATUS_NOT_AVAILABLE
        reason = ("ALL_DECLARED_BINS_LACK_RECORDED_EVIDENCE" if unrecorded_declared
                  else "NO_RECORDED_BINS_FOR_DECLARED_SCOPE")
        ready_field: Optional[bool] = None
    elif incomplete:
        status, reason, ready_field = STATUS_INCOMPLETE_EVIDENCE, None, False
    elif blocking_waivers:
        status, reason, ready_field = STATUS_BLOCKED_BY_WAIVER, None, False
    elif ready:
        status, reason, ready_field = STATUS_SIGNOFF_READY, None, True
    else:
        status, reason, ready_field = STATUS_OPEN, None, False

    return {
        **base,
        "status": status,
        "reason": reason,
        "functional_coverage_signoff_ready": ready_field,
        "closure_percent": closure_percent,
        "covered_bins": covered_bins, "credited_bins": credited_bins,
        "total_goal_bins": total_goal_bins,
        "rows": rows,
        "unrecorded_declared": unrecorded_declared,
        "malformed_categories": malformed,
        "blocking_waivers": blocking_waivers,
    }


# ===========================================================================
# Rendering
# ===========================================================================

def render_functional_coverage_signoff_table(report: Dict[str, Any]) -> str:
    """The per-bin table, in `connectivity.render_markdown_table()` --
    this repo's only parameterized table renderer, reused rather than a
    second hand-rolled `"| " + " | ".join(...)` loop."""
    from .connectivity import render_markdown_table
    columns = [
        ("coverage_id", "Coverage Bin"), ("percent", "Percent"),
        ("bins_missing", "Bins Missing"), ("classification", "Classification"),
        ("credit_source", "Credit"), ("waiver_status", "Waiver"),
    ]
    rows = []
    for r in report.get("rows") or []:
        rows.append({
            "coverage_id": r["coverage_id"],
            "percent": f'{r["percent"]}%',
            "bins_missing": r["bins_missing"],
            "classification": r.get("classification") or "-",
            "credit_source": r.get("credit_source") or "-",
            "waiver_status": r.get("waiver_status") or "-",
        })
    return render_markdown_table(
        columns, rows, empty_note="(no coverage bin is in the declared scope)")


def format_functional_coverage_signoff_report(report: Dict[str, Any]) -> str:
    """The full report: the verdict, every input's own status, the per-bin
    table, and the two disclosure sections (unrecorded declared bins, and
    waivers blocking signoff)."""
    def _tag(block: Dict[str, Any]) -> str:
        r = block.get("reason")
        return f"{block['status']}" + (f" ({r})" if r else "")

    lines = [
        "# FUNCTIONAL COVERAGE SIGNOFF",
        "",
        f"**{report['status']}** -- "
        f"FUNCTIONAL_COVERAGE_SIGNOFF_READY={report['functional_coverage_signoff_ready']}"
        + (f", Closure={report['closure_percent']}%"
           if report.get('closure_percent') is not None else ""),
        "",
        f"Project root: `{report['root']}`",
        f"Waiver ledger: {_tag(report['waiver_input'])}",
        f"Evidence database: {_tag(report['evidence_db_input'])}",
        f"Testplan correspondence: {_tag(report['testplan_input'])}",
        f"Declared coverage-goal scope: {report['declared_scope_source']}"
        + (f" ({report['declared_scope_reason']})" if report.get('declared_scope_reason') else ""),
        "",
        render_functional_coverage_signoff_table(report),
    ]
    if report.get("unrecorded_declared"):
        lines += ["", "## Declared bins with no recorded coverage evidence", ""]
        lines += [f"- {n}" for n in report["unrecorded_declared"]]
    if report.get("blocking_waivers"):
        lines += ["", "## Waivers blocking signoff (EXPIRED / REVOKED / UNKNOWN)", ""]
        lines += [f"- {b['coverage_id']}: waiver {b['waiver_id']} is {b['status']}"
                  for b in report["blocking_waivers"]]
    if report.get("reason"):
        lines += ["", f"Reason: {report['reason']}"]
    lines += ["", "This verdict authorizes nothing: it is an input to a human's signoff "
                   "decision, exactly like golden_flow_readiness.py's matrix and "
                   "platform_health.py's health report. It approves no promotion and no "
                   "production write."]
    return "\n".join(lines)


# ===========================================================================
# One shared entry point for a future `dv-harness functional-coverage-signoff`
# and `python -m dv_harness.functional_coverage_signoff`
# ===========================================================================

def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False) -> Tuple[int, Dict[str, Any], str]:
    """(exit_code, report, text). Exit 0 when FUNCTIONAL_COVERAGE_SIGNOFF_READY
    is True, 1 when a real (non-ready) finding was computed, 2 when the
    essential inputs are NOT_AVAILABLE -- nothing to report. Neither an
    approval nor a rejection in either direction; a human still decides."""
    report = analyze_functional_coverage_signoff(root, cfg=cfg)
    text = "" if as_json else format_functional_coverage_signoff_report(report)
    if report["status"] == STATUS_NOT_AVAILABLE:
        code = 2
    elif report["functional_coverage_signoff_ready"]:
        code = 0
    else:
        code = 1
    return code, report, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.functional_coverage_signoff",
        description="FUNCTIONAL_COVERAGE_SIGNOFF_READY verdict + Closure metric, aggregated "
                    "read-only from waiver_store, coverage_analysis and "
                    "env_manifest/evidence_db. Reads only; runs no stage.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    root = Path(args.project_root).resolve()
    cfg = None
    try:
        from .config import load_config
        if (root / ".dv-harness" / "config.json").exists():
            cfg = load_config(root)
    except Exception:
        cfg = None
    code, report, text = execute(root, cfg=cfg, as_json=args.as_json)
    print(_json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
