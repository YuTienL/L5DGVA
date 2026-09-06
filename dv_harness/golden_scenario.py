"""dv_harness/golden_scenario.py -- spec section 225's GOLDEN SCENARIO /
REFERENCE CAPSULE store, with freshness derived from REAL git history
(2026-09-06).

THE GAP THIS CLOSES
-------------------
Section 225 asks for "proven reusable scenario/reference capsules" carrying
capsule_id / project-subsystem / requirements / DUT-TB SHA / VIP-tool versions /
configuration / command.txt inputs / test-sequence-seed / expected result /
evidence references / known limitations / freshness, and states the rule that
gives the whole thing its point: "Golden does not mean permanent. Relevant
RTL/spec/tool/config changes can make a capsule STALE."

Grepping this repo for `golden_scenario`/`GoldenScenario`/`reference capsule`
matched nothing executable. Two similarly-shaped mechanisms already exist and
are deliberately NOT extended into this, because each answers a different
question:

  * `golden_flow_readiness.py` -- despite the name, section 47's GOLDEN FLOW
    READINESS MATRIX: "are the twenty L5 workflow STAGES connected end to end
    with evidence, right now". It is about the harness's own flow, has no
    per-test record, no recorded SHA and no staleness concept.
  * `system_regression_plan.CAT_KNOWN_GOOD_SUBSYSTEM_TESTS` -- SYS-33's
    system-level regression PLAN category: which registered SUBSYSTEMS are
    known-good enough to rerun under a System-Level composition, derived from
    the subsystem registry's qualification_state at plan time. It is a
    per-subsystem planning verdict computed fresh on every call; it never
    persists a per-test capsule, and it never asks "has the RTL moved since
    that PASS".

WHAT THIS MODULE IS
-------------------
A capsule is a claim of the form "test T, at seed S, in configuration C, was
verified PASS against commit SHA on DATE, and here is the real evidence
record". That claim is only worth persisting if it can go stale, and only
worth trusting if it was checked against real evidence when recorded. So:

  * BACKING STORE: the real `evidence_db.EvidenceStore` (one new
    `golden_scenarios` table alongside `jobs`/`normalized_evidence`/...), not a
    second evidence format. `record_golden_scenario()` REFUSES to write a
    capsule whose `evidence_id` is not an existing `normalized_evidence` row
    (the real `vip_distill.py` envelope), whose recorded verdict is not a real
    PASS, or whose `test_name` disagrees with that row's own `pattern`. A
    "golden" record the store cannot tie back to a real PASS is exactly the
    fabricated result this project forbids, so it is a hard error, not a
    warning.
  * FRESHNESS: computed, never stored. `evaluate_freshness()` runs the REAL
    `change_impact.changed_files()` (a real `git diff --name-only
    <verified_sha>..<head>`) and the REAL `change_impact.classify_risk()`
    HIGH/MEDIUM/LOW path classifier -- the same two functions the
    regression-selection chain already uses, so "did the RTL move" has ONE
    answer in this codebase, not two. A HIGH-risk (design RTL) or MEDIUM-risk
    (testbench/sequence/command.txt/config) change inside the capsule's
    declared scope makes it STALE; LOW-risk documentation and harness
    bookkeeping does not. A recorded VIP/tool version that no longer matches
    the current one makes it STALE on its own, with no git change at all.

HONESTY RULES, enforced in code
-------------------------------
  * A capsule that cannot be evaluated is UNKNOWN, never FRESH. No git, an
    unresolvable recorded SHA, a failed diff, or no recorded SHA all report
    UNKNOWN with the real reason -- "we could not check" must never read as
    "still good".
  * An empty `watched_paths` widens the scope to the WHOLE repo rather than
    narrowing it to nothing, and says so in `scope`. The failure mode of this
    module is "calls a still-good capsule stale", never "calls a stale capsule
    fresh".
  * Nothing here approves, qualifies, signs off, runs, builds or submits
    anything. FRESH is an input to a human's reuse decision. There is
    deliberately no stage gate: a gate that passed on a capsule nobody re-ran
    would be worse than no gate.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import change_impact
from .change_impact import RISK_HIGH, RISK_MEDIUM, classify_risk

# --- vocabulary ------------------------------------------------------------

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

#: The verdict strings `vip_distill.py` really writes for a passing run --
#: `distill_sim_log()` passes the epilogue's own `VERDICT: PASSED` through
#: verbatim, `distill_job_record()` passes `JobState.sim_status` ("PASS")
#: through verbatim, and `merge_evidence()` emits "PASSED". Anything else
#: (FAILED/FAIL/AMBIGUOUS/None) is not a PASS and cannot back a capsule.
PASS_VERDICTS = frozenset({"PASS", "PASSED"})

#: Risks that make a capsule stale when they appear in its scope. LOW is
#: documentation and harness bookkeeping (`change_impact._DOC_SUFFIXES` /
#: `_METADATA_ROOTS`), which cannot change a simulation result.
STALENESS_RISKS = frozenset({RISK_HIGH, RISK_MEDIUM})

#: Golden Subsystem Test Set completeness (2026-09-06): the fixed
#: qualification_set vocabulary a capsule MAY self-declare -- never required,
#: since most of this project's existing capsules were recorded before this
#: field existed and must not become invalid. Naming what KIND of proven
#: result a capsule represents lets `missing_categories()` answer "which
#: categories of subsystem test coverage have we never recorded a golden
#: capsule for at all", a completeness check over capsules ALREADY recorded --
#: never a claim about which categories SHOULD exist for a given subsystem,
#: which this module has no evidence to derive.
QUALIFICATION_SET_CATEGORIES = (
    "known_pass", "known_dut_fail", "known_tb_fail", "known_vip_fail",
    "protocol_violation", "timeout", "coverage_hole", "waiver", "register", "perf",
)

SCHEMA_VERSION = "1.0"

_CAPSULE_ID_SAFE = re.compile(r"[^A-Za-z0-9_.:-]+")


class GoldenScenarioError(Exception):
    """Base for every refusal in this module."""


class CapsuleValidationError(GoldenScenarioError):
    """The capsule record itself is missing a required field."""


class EvidenceNotFoundError(GoldenScenarioError):
    """`evidence_id` names no row in the evidence store's `normalized_evidence`."""


class EvidenceNotPassingError(GoldenScenarioError):
    """The cited evidence row exists but does not record a real PASS."""


class EvidenceMismatchError(GoldenScenarioError):
    """The cited evidence row is real and passing, but is evidence for a
    different test than the capsule claims."""


# --- the capsule record ----------------------------------------------------


@dataclass
class GoldenScenario:
    """Section 225's capsule fields, one dataclass field each.

    `verified_sha` is that section's "DUT/TB SHA": the real git commit the
    recorded PASS was produced against, and the base every freshness diff is
    computed from. `freshness` is deliberately NOT a field -- it is derived by
    `evaluate_freshness()` from real git history at the moment it is asked,
    because a stored freshness flag is stale the instant someone commits.
    """
    capsule_id: str
    project: str
    subsystem: str
    test_name: str
    evidence_id: str
    protocol: Optional[str] = None
    sequence_name: Optional[str] = None
    seed: Optional[str] = None
    expected_result: str = "PASS"
    verified_sha: Optional[str] = None
    verified_at: Optional[str] = None
    job_id: Optional[int] = None
    requirements: List[str] = field(default_factory=list)
    vip_versions: Dict[str, str] = field(default_factory=dict)
    configuration: Dict[str, Any] = field(default_factory=dict)
    command_txt_inputs: List[str] = field(default_factory=list)
    known_limitations: List[str] = field(default_factory=list)
    #: Repo-relative path prefixes whose change can invalidate this capsule --
    #: the DUT RTL directory, the VIP config file, the command.txt directory.
    #: Empty means "the whole repo", which is wider, never narrower.
    watched_paths: List[str] = field(default_factory=list)
    #: Optional qualification_set label from `QUALIFICATION_SET_CATEGORIES`.
    #: Never required -- a capsule with no declared category is simply
    #: uncategorized, not invalid -- and validated against that fixed
    #: vocabulary by `validate_capsule()` only when present. See
    #: `missing_categories()` below.
    category: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def default_capsule_id(project: str, subsystem: str, test_name: str,
                        seed: Optional[str] = None) -> str:
    """A readable id naming the real thing it identifies -- never an opaque
    hash. `usb3.link/usb3_lfps_basic@seed42`-shaped, with characters DuckDB
    keys and shell arguments handle safely."""
    parts = [str(project or "").strip(), str(subsystem or "").strip(),
             str(test_name or "").strip()]
    if not all(parts):
        raise CapsuleValidationError(
            "default_capsule_id: project, subsystem and test_name are all required")
    base = "GS-" + ".".join(_CAPSULE_ID_SAFE.sub("_", p) for p in parts)
    if seed not in (None, ""):
        base += "@seed" + _CAPSULE_ID_SAFE.sub("_", str(seed))
    return base


def validate_capsule(capsule: GoldenScenario) -> None:
    """Every field a capsule cannot be meaningful without. Raised before any
    store round trip so a malformed capsule never half-writes."""
    missing = [name for name in ("capsule_id", "project", "subsystem", "test_name",
                                  "evidence_id")
               if not str(getattr(capsule, name) or "").strip()]
    if missing:
        raise CapsuleValidationError(
            f"golden scenario capsule missing required field(s): {sorted(missing)}")
    if str(capsule.expected_result or "").strip().upper() not in PASS_VERDICTS:
        raise CapsuleValidationError(
            f"expected_result must be a real PASS verdict "
            f"(one of {sorted(PASS_VERDICTS)}), got {capsule.expected_result!r} -- "
            "a golden scenario records a proven-good run, not a known-failing one")
    category = str(capsule.category or "").strip()
    if category and category not in QUALIFICATION_SET_CATEGORIES:
        raise CapsuleValidationError(
            f"category {capsule.category!r} is not one of the qualification_set "
            f"categories {sorted(QUALIFICATION_SET_CATEGORIES)} -- leave category "
            "unset rather than inventing a new one")


# --- recording against the REAL evidence store -----------------------------


def _fetch_normalized_evidence(store, evidence_id: str) -> Optional[dict]:
    rows = store.query(
        "SELECT evidence_id, source_kind, job_id, pattern, protocol, verdict "
        "FROM normalized_evidence WHERE evidence_id = ?", [evidence_id])
    if not rows:
        return None
    cols = ("evidence_id", "source_kind", "job_id", "pattern", "protocol", "verdict")
    return dict(zip(cols, rows[0]))


def _fetch_job_git_sha(store, job_id: Optional[int]) -> Optional[str]:
    if job_id is None:
        return None
    rows = store.query("SELECT git_sha FROM jobs WHERE job_id = ?", [job_id])
    return rows[0][0] if rows and rows[0][0] else None


def _category_column_available(store) -> bool:
    """Whether the real `golden_scenarios` table already carries a
    `category` column, checked through the SAME `duckdb_tables()`-style
    catalog introspection `evidence_db.EvidenceStore._golden_scenario_rows()`
    already uses to check for the table itself -- there is no second
    column-introspection convention here. A store predating this addition
    (or one whose ALTER TABLE below never ran) genuinely lacks it, which
    must read as "category was never recorded", never crash and never
    guess a value."""
    try:
        rows = store.query(
            "SELECT 1 FROM duckdb_columns() WHERE table_name = 'golden_scenarios' "
            "AND column_name = 'category'")
    except Exception:
        return False
    return bool(rows)


def _ensure_category_column(store) -> None:
    """Adds `category` to the real `golden_scenarios` table via the store's
    own public `query()` -- the same raw-SQL seam `_fetch_normalized_evidence`/
    `_fetch_job_git_sha` above already use to read through `EvidenceStore` --
    so this qualification_set addition needs no change to `evidence_db.py`'s
    own column list. Idempotent, and never attempted against a read_only
    store (which DuckDB would refuse to ALTER anyway)."""
    if getattr(store, "read_only", False) or _category_column_available(store):
        return
    try:
        store.query("ALTER TABLE golden_scenarios ADD COLUMN category VARCHAR")
    except Exception:
        # Best-effort: an ALTER TABLE that genuinely fails (a DuckDB build too
        # old for it, a concurrent writer) must not turn an otherwise-good
        # capsule recording into a crash -- the capsule itself still records
        # correctly, only its category will not survive this round trip, and
        # a later load honestly reports it as not recorded rather than
        # fabricating one.
        pass


def _attach_categories(store, rows: List[dict]) -> List[dict]:
    """Merges the real `category` column back onto rows
    `EvidenceStore.get_golden_scenario()`/`list_golden_scenarios()` return --
    those methods do not know this column exists (it lives outside
    `evidence_db.py`'s own column list), so it is read back here through the
    same public `query()` seam it was written through, never a second table.
    A store that never gained the column reports every row's category as
    unset rather than raising."""
    if not rows:
        return rows
    if not _category_column_available(store):
        for row in rows:
            row.setdefault("category", None)
        return rows
    ids = [row["capsule_id"] for row in rows if row.get("capsule_id")]
    if not ids:
        return rows
    placeholders = ", ".join("?" for _ in ids)
    cat_rows = store.query(
        f"SELECT capsule_id, category FROM golden_scenarios "
        f"WHERE capsule_id IN ({placeholders})", ids)
    cat_map = dict(cat_rows)
    for row in rows:
        row["category"] = cat_map.get(row.get("capsule_id"))
    return rows


def record_golden_scenario(store, capsule: GoldenScenario, *,
                            now: Optional[str] = None) -> GoldenScenario:
    """Validate `capsule` against the REAL evidence it cites, then upsert it.

    The four refusals, in the order they are checked:
      1. a malformed capsule (`validate_capsule`);
      2. `evidence_id` naming no `normalized_evidence` row -- there is no such
         evidence in this project, so there is nothing "proven" to record;
      3. that row's `verdict` not being a real PASS -- a capsule is a
         proven-good claim and a FAILED/AMBIGUOUS/absent verdict does not
         support one;
      4. that row's `pattern` disagreeing with `capsule.test_name` -- evidence
         for a different test proves nothing about this one.

    Fields the evidence row already knows (job_id, protocol, and via the real
    `jobs` row the `git_sha` this run was produced against) are filled in from
    it when the caller left them blank, and are never overwritten when the
    caller supplied them. The returned capsule is the one actually stored.
    """
    validate_capsule(capsule)
    row = _fetch_normalized_evidence(store, capsule.evidence_id)
    if row is None:
        raise EvidenceNotFoundError(
            f"evidence_id {capsule.evidence_id!r} is not in this project's "
            "normalized_evidence table -- a golden scenario must cite real, "
            "already-ingested evidence")
    verdict = str(row.get("verdict") or "").strip().upper()
    if verdict not in PASS_VERDICTS:
        raise EvidenceNotPassingError(
            f"evidence {capsule.evidence_id!r} records verdict {row.get('verdict')!r}, "
            f"not a PASS ({sorted(PASS_VERDICTS)}) -- refusing to record it as a "
            "golden scenario")
    ev_pattern = str(row.get("pattern") or "").strip()
    if ev_pattern and ev_pattern != str(capsule.test_name).strip():
        raise EvidenceMismatchError(
            f"evidence {capsule.evidence_id!r} is evidence for pattern {ev_pattern!r}, "
            f"but the capsule claims test_name {capsule.test_name!r}")

    stored = GoldenScenario(**capsule.to_dict())
    if stored.job_id is None and row.get("job_id") is not None:
        stored.job_id = int(row["job_id"])
    if not stored.protocol and row.get("protocol"):
        stored.protocol = str(row["protocol"])
    if not stored.verified_sha:
        stored.verified_sha = _fetch_job_git_sha(store, stored.job_id)
    if not stored.verified_at:
        stored.verified_at = now or datetime.now(timezone.utc).isoformat()

    store.insert_golden_scenario(stored.to_dict(), evidence_verdict=verdict)
    # qualification_set category is not one of evidence_db.py's own known
    # columns (see the module-level note above `_category_column_available`),
    # so it is persisted through the store's public `query()` seam rather
    # than through `insert_golden_scenario()` -- best-effort, never fatal to
    # an otherwise-successful recording.
    if not getattr(store, "read_only", False):
        _ensure_category_column(store)
        if _category_column_available(store):
            try:
                store.query(
                    "UPDATE golden_scenarios SET category = ? WHERE capsule_id = ?",
                    [stored.category, stored.capsule_id])
            except Exception:
                pass
    return stored


def load_golden_scenario(store, capsule_id: str) -> Optional[GoldenScenario]:
    row = store.get_golden_scenario(capsule_id)
    if row is None:
        return None
    _attach_categories(store, [row])
    return _row_to_capsule(row)


def load_golden_scenarios(store) -> List[GoldenScenario]:
    rows = store.list_golden_scenarios()
    _attach_categories(store, rows)
    return [_row_to_capsule(r) for r in rows]


# --- qualification_set completeness (Golden Subsystem Test Set, 2026-09-06) -


def missing_categories(capsules: Sequence[GoldenScenario], *,
                        required: Sequence[str] = QUALIFICATION_SET_CATEGORIES
                        ) -> List[str]:
    """Which of `required` qualification_set categories have NO capsule among
    `capsules` declaring it.

    A pure completeness check over ALREADY-LOADED capsules (typically
    `load_golden_scenarios(store)`) -- it runs no query of its own and is not
    a new store: this module still has exactly one backing table,
    `golden_scenarios`. A capsule whose `category` is unset, blank, or
    outside `QUALIFICATION_SET_CATEGORIES` counts toward NONE of `required`
    -- an uncategorized capsule proves nothing about which category it was
    meant to cover, so it must never be silently credited to one. Returns
    the missing category names in `required`'s own order (never a set), so a
    caller or a test can compare the result against a literal list."""
    present = {c.category for c in capsules
               if getattr(c, "category", None) in QUALIFICATION_SET_CATEGORIES}
    return [cat for cat in required if cat not in present]


def qualification_set_report(store, *,
                              required: Sequence[str] = QUALIFICATION_SET_CATEGORIES
                              ) -> dict:
    """Loads every real capsule in `store` and reports Golden Subsystem Test
    Set completeness: which required categories already have a recorded
    capsule, which do not, and how many capsules total (including
    uncategorized ones). `status` is COMPLETE only when every required
    category is covered -- a store with zero capsules reports INCOMPLETE
    with every category missing, never a vacuous COMPLETE over nothing."""
    capsules = load_golden_scenarios(store)
    missing = missing_categories(capsules, required=required)
    present_counts = {cat: sum(1 for c in capsules if c.category == cat)
                      for cat in required}
    uncategorized = sum(1 for c in capsules
                        if not c.category or c.category not in QUALIFICATION_SET_CATEGORIES)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE" if not missing else "INCOMPLETE",
        "required_categories": list(required),
        "present_counts": present_counts,
        "missing_categories": missing,
        "capsule_count": len(capsules),
        "uncategorized_capsule_count": uncategorized,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def format_qualification_set_report(report: dict) -> str:
    lines = [f"GOLDEN SUBSYSTEM TEST SET (qualification_set): {report.get('status')}  "
             f"(capsules={report.get('capsule_count')}, "
             f"uncategorized={report.get('uncategorized_capsule_count')})"]
    missing = report.get("missing_categories") or []
    if missing:
        lines.append(f"  MISSING ({len(missing)}): {', '.join(missing)}")
    else:
        lines.append("  every required category has at least one recorded capsule")
    lines.append("  present counts:")
    for cat, count in (report.get("present_counts") or {}).items():
        lines.append(f"    {cat}: {count}")
    return "\n".join(lines)


def _row_to_capsule(row: dict) -> GoldenScenario:
    fields = set(GoldenScenario.__dataclass_fields__)
    return GoldenScenario(**{k: v for k, v in row.items() if k in fields})


# --- freshness: derived from REAL git history ------------------------------


def _in_scope(path: str, watched_paths: Sequence[str]) -> bool:
    """A changed file is in a capsule's scope when it sits under one of its
    declared watched paths. No watched paths at all => everything is in
    scope, which widens the capsule's staleness surface rather than emptying
    it."""
    if not watched_paths:
        return True
    p = str(path).replace("\\", "/").strip().lstrip("./")
    for raw in watched_paths:
        w = str(raw).replace("\\", "/").strip().lstrip("./").rstrip("/")
        if not w:
            continue
        if p == w or p.startswith(w + "/"):
            return True
    return False


def _version_drift(recorded: Dict[str, str],
                    current: Optional[Dict[str, str]]) -> List[Dict[str, str]]:
    """VIP/tool versions that no longer match what the capsule was verified
    with. `current` is supplied by the caller (this module never guesses a
    tool version); a tool the caller does not report on is not evaluated,
    never assumed unchanged-and-fine."""
    if not current:
        return []
    drift: List[Dict[str, str]] = []
    for tool, recorded_version in sorted((recorded or {}).items()):
        if tool not in current:
            continue
        if str(current[tool]) != str(recorded_version):
            drift.append({"tool": tool, "recorded": str(recorded_version),
                          "current": str(current[tool])})
    return drift


def evaluate_freshness(root, capsule: GoldenScenario, *, head: str = "HEAD",
                        current_vip_versions: Optional[Dict[str, str]] = None,
                        diff: Optional[dict] = None) -> dict:
    """FRESH / STALE / UNKNOWN for one capsule, from real evidence only.

    `diff` is injectable (the same seam `change_impact.compute_change_impact()`
    already offers) so a caller that has already run one diff for a batch of
    capsules does not pay for N git invocations, and so a test can drive the
    UNKNOWN branches without breaking a repository.
    """
    root = Path(root)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    base_result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capsule_id": capsule.capsule_id,
        "test_name": capsule.test_name,
        "evidence_id": capsule.evidence_id,
        "verified_sha": capsule.verified_sha,
        "verified_at": capsule.verified_at,
        "head": head,
        "scope": ("WATCHED_PATHS" if capsule.watched_paths
                  else "WHOLE_REPO_NO_WATCHED_PATHS_DECLARED"),
        "watched_paths": list(capsule.watched_paths or []),
        "evaluated_at": evaluated_at,
        "reasons": [],
        "triggering_changes": [],
        "vip_version_drift": [],
        "changed_files_in_scope": [],
        "diff_status": None,
        "diff_detail": None,
        "head_sha": None,
    }

    # Version drift is computable with no git at all, so it is evaluated
    # first and survives even an UNKNOWN diff -- a capsule whose VIP moved is
    # stale whether or not we can read git history.
    drift = _version_drift(capsule.vip_versions or {}, current_vip_versions)
    base_result["vip_version_drift"] = drift

    if not capsule.verified_sha:
        base_result["freshness"] = STALE if drift else UNKNOWN
        base_result["reasons"] = (
            [f"VIP_TOOL_VERSION_CHANGED: {d['tool']} {d['recorded']} -> {d['current']}"
             for d in drift]
            or ["NO_RECORDED_SHA: capsule has no verified_sha, so no change since the "
                "recorded PASS can be computed"])
        return base_result

    d = diff if diff is not None else change_impact.changed_files(
        root, capsule.verified_sha, head)
    base_result["diff_status"] = d.get("status")
    base_result["diff_detail"] = d.get("detail")
    base_result["head_sha"] = d.get("head_sha")

    if d.get("status") != "REAL_DIFF":
        base_result["freshness"] = STALE if drift else UNKNOWN
        reasons = [f"VIP_TOOL_VERSION_CHANGED: {x['tool']} {x['recorded']} -> {x['current']}"
                   for x in drift]
        reasons.append(
            f"GIT_HISTORY_UNAVAILABLE: {d.get('status')}"
            + (f" ({d.get('detail')})" if d.get("detail") else "")
            + " -- cannot prove the capsule is still current, so it is not reported FRESH")
        base_result["reasons"] = reasons
        return base_result

    in_scope = [f for f in (d.get("files") or []) if _in_scope(f, capsule.watched_paths)]
    triggering = [{"path": f, "risk": classify_risk(f)} for f in in_scope
                  if classify_risk(f) in STALENESS_RISKS]
    base_result["changed_files_in_scope"] = in_scope
    base_result["triggering_changes"] = triggering

    reasons = [f"VIP_TOOL_VERSION_CHANGED: {x['tool']} {x['recorded']} -> {x['current']}"
               for x in drift]
    if triggering:
        reasons.append(
            "DESIGN_OR_CONFIG_CHANGED_SINCE_VERIFIED_SHA: "
            + ", ".join(f"{t['path']} ({t['risk']})" for t in triggering))
    if reasons:
        base_result["freshness"] = STALE
        base_result["reasons"] = reasons
        return base_result

    base_result["freshness"] = FRESH
    base_result["reasons"] = [
        f"NO_BEHAVIORAL_CHANGE_IN_SCOPE_SINCE {capsule.verified_sha[:12]}"
        f" ({len(d.get('files') or [])} file(s) changed in the repo, "
        f"{len(in_scope)} in this capsule's scope, none HIGH/MEDIUM risk)"]
    return base_result


def evaluate_store_freshness(root, store, *, head: str = "HEAD",
                              current_vip_versions: Optional[Dict[str, str]] = None) -> dict:
    """Every capsule in the store, evaluated against the same `head`.

    The report's own `status` is the WORST outcome present -- one STALE
    capsule makes the report STALE -- because a caller asking "can I reuse my
    golden scenarios" must not read a mostly-fresh set as an all-clear.
    """
    capsules = load_golden_scenarios(store)
    results = [evaluate_freshness(root, c, head=head,
                                  current_vip_versions=current_vip_versions)
               for c in capsules]
    counts = {FRESH: 0, STALE: 0, UNKNOWN: 0}
    for r in results:
        counts[r["freshness"]] = counts.get(r["freshness"], 0) + 1
    if not results:
        status = "NOT_AVAILABLE"
    elif counts[STALE]:
        status = STALE
    elif counts[UNKNOWN]:
        status = UNKNOWN
    else:
        status = FRESH
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "head": head,
        "capsule_count": len(results),
        "counts": counts,
        "capsules": results,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# --- rendering / CLI -------------------------------------------------------


def format_freshness_report(report: dict) -> str:
    lines = [f"GOLDEN SCENARIO FRESHNESS: {report.get('status')}  "
             f"(head={report.get('head')}, capsules={report.get('capsule_count')})"]
    counts = report.get("counts") or {}
    lines.append(f"  FRESH={counts.get(FRESH, 0)}  STALE={counts.get(STALE, 0)}  "
                 f"UNKNOWN={counts.get(UNKNOWN, 0)}")
    if not report.get("capsules"):
        lines.append("  no golden scenario capsules recorded in this project's evidence store")
        return "\n".join(lines)
    for c in report["capsules"]:
        lines.append("")
        lines.append(f"  [{c['freshness']}] {c['capsule_id']}")
        lines.append(f"      test={c['test_name']}  verified_sha={c.get('verified_sha')}  "
                     f"verified_at={c.get('verified_at')}")
        lines.append(f"      evidence_id={c['evidence_id']}  scope={c['scope']}")
        for reason in c.get("reasons") or []:
            lines.append(f"      - {reason}")
    return "\n".join(lines)


def capsule_from_json(data: dict) -> GoldenScenario:
    """Build a capsule from a plain dict (a JSON file, or an agent's evidence
    block). Unknown keys are a hard error, not silently dropped -- a typo'd
    `watched_path` must not become an unwatched capsule."""
    if not isinstance(data, dict):
        raise CapsuleValidationError("golden scenario record must be a JSON object")
    known = set(GoldenScenario.__dataclass_fields__)
    unknown = sorted(set(data) - known)
    if unknown:
        raise CapsuleValidationError(
            f"unknown golden scenario field(s) {unknown}; known fields: {sorted(known)}")
    if "capsule_id" not in data:
        data = dict(data)
        data["capsule_id"] = default_capsule_id(
            data.get("project", ""), data.get("subsystem", ""),
            data.get("test_name", ""), data.get("seed"))
    return GoldenScenario(**data)


def _open_store(root: Path, db_path: Optional[str], *, read_only: bool):
    from .evidence_db import EvidenceStore, default_db_path
    path = Path(db_path) if db_path else default_db_path(root)
    if read_only and not Path(path).exists():
        return None
    return EvidenceStore(path, read_only=read_only)


def execute_verb(verb: str, *, root, db_path: Optional[str] = None,
                  json_file: Optional[str] = None, capsule_id: Optional[str] = None,
                  head: str = "HEAD", as_json: bool = False,
                  current_vip_versions: Optional[Dict[str, str]] = None) -> Tuple[str, int]:
    """Shared implementation for `dv-harness golden-scenario <verb>` and
    `python -m dv_harness.golden_scenario <verb>`. Returns (text, exit_code):
    0 all FRESH / recorded / qualification_set COMPLETE, 1 at least one
    STALE (or, for `qualification-set`, at least one required category still
    missing), 2 UNKNOWN or nothing to report. Nothing here runs, builds,
    submits or approves anything."""
    root = Path(root)
    if verb == "record":
        if not json_file:
            return ("golden-scenario record requires --json-file <capsule.json>", 2)
        capsule = capsule_from_json(json.loads(Path(json_file).read_text(encoding="utf-8")))
        store = _open_store(root, db_path, read_only=False)
        try:
            stored = record_golden_scenario(store, capsule)
        finally:
            store.close()
        text = (json.dumps(stored.to_dict(), indent=2) if as_json
                else f"recorded golden scenario {stored.capsule_id} "
                     f"(test={stored.test_name}, verified_sha={stored.verified_sha}, "
                     f"evidence_id={stored.evidence_id})")
        return text, 0

    store = _open_store(root, db_path, read_only=True)
    if store is None:
        return ("NOT_AVAILABLE: no evidence database at "
                f"{db_path or Path(root).joinpath('.dv-harness', 'evidence', 'evidence.duckdb')}"
                " -- no golden scenarios have ever been recorded", 2)
    try:
        if verb == "list":
            capsules = load_golden_scenarios(store)
            if as_json:
                return json.dumps([c.to_dict() for c in capsules], indent=2), (0 if capsules else 2)
            if not capsules:
                return "NOT_AVAILABLE: no golden scenario capsules recorded", 2
            lines = [f"{len(capsules)} golden scenario capsule(s):"]
            for c in capsules:
                lines.append(f"  {c.capsule_id}  test={c.test_name}  "
                             f"verified_sha={c.verified_sha}  evidence_id={c.evidence_id}")
            return "\n".join(lines), 0
        if verb == "qualification-set":
            report = qualification_set_report(store)
            text = (json.dumps(report, indent=2) if as_json
                    else format_qualification_set_report(report))
            return text, (0 if report["status"] == "COMPLETE" else 1)
        if verb == "status":
            if capsule_id:
                capsule = load_golden_scenario(store, capsule_id)
                if capsule is None:
                    return f"NOT_AVAILABLE: no golden scenario capsule {capsule_id!r}", 2
                one = evaluate_freshness(root, capsule, head=head,
                                         current_vip_versions=current_vip_versions)
                report = {"schema_version": SCHEMA_VERSION, "status": one["freshness"],
                          "head": head, "capsule_count": 1,
                          "counts": {FRESH: 0, STALE: 0, UNKNOWN: 0,
                                     one["freshness"]: 1},
                          "capsules": [one], "evaluated_at": one["evaluated_at"]}
            else:
                report = evaluate_store_freshness(
                    root, store, head=head, current_vip_versions=current_vip_versions)
        else:
            return f"unknown golden-scenario verb {verb!r}", 2
    finally:
        store.close()
    text = json.dumps(report, indent=2) if as_json else format_freshness_report(report)
    code = {FRESH: 0, STALE: 1, UNKNOWN: 2, "NOT_AVAILABLE": 2}[report["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.golden_scenario",
        description="Spec section 225 golden scenario / reference capsules: record a "
                    "proven-good test against real evidence_db evidence, and derive "
                    "FRESH/STALE/UNKNOWN from real git history. Runs nothing.")
    ap.add_argument("verb", choices=("record", "list", "status", "qualification-set"))
    ap.add_argument("--root", default=".", help="Project root (the git repo whose history "
                                                 "freshness is derived from).")
    ap.add_argument("--db", default=None, help="Evidence database path "
                                                "(default: <root>/.dv-harness/evidence/evidence.duckdb).")
    ap.add_argument("--json-file", default=None, help="record: the capsule JSON file to record.")
    ap.add_argument("--capsule-id", default=None, help="status: evaluate one capsule only.")
    ap.add_argument("--head", default="HEAD", help="status: the revision to compare against.")
    ap.add_argument("--vip-version", action="append", default=None, dest="vip_versions",
                    metavar="TOOL=VERSION",
                    help="status: a CURRENT VIP/tool version (repeatable). A recorded "
                         "version that no longer matches makes the capsule STALE.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    current = None
    if a.vip_versions:
        current = {}
        for item in a.vip_versions:
            if "=" not in item:
                print(f"--vip-version expects TOOL=VERSION, got {item!r}")
                return 2
            tool, version = item.split("=", 1)
            current[tool.strip()] = version.strip()
    try:
        text, code = execute_verb(a.verb, root=a.root, db_path=a.db, json_file=a.json_file,
                                  capsule_id=a.capsule_id, head=a.head, as_json=a.json,
                                  current_vip_versions=current)
    except GoldenScenarioError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
