r"""dv_harness/subsys_compat_matrix.py -- Subsystem Compatibility Matrix
(2026-09-06, section 233).

WHAT THIS CLOSES. Section 233 asks for a matrix of which subsystem PAIRS are
known-compatible for composition. Nothing in this repo answered that as a
matrix -- confirmed by direct search before writing a line of this: a
repo-wide grep for `compat_matrix`/`CompatibilityMatrix`/`subsys_compat`
matched nothing. `system_resource_inventory.py`'s SYS-9..14 chain (a real
resource inventory, comparison, relationship classification, and SYS-12's
active-driver-conflict stop rule) already computes exactly the evidence a
pairwise matrix needs, but only ever renders it as a flat relationship LIST
and a single project-wide ACTIVE_DRIVER_CONFLICT verdict -- there is no
per-PAIR rollup anywhere, and a human wanting "can subsystem A compose with
subsystem C specifically" had to read the whole relationship list by hand and
mentally group it. `ip_ownership_conflict.py`'s IP-level VIP-vs-legacy-BFM
check answers a DIFFERENT, narrower question (is ONE subsystem internally
clean, before any composition exists at all) that SYS-9..14 cannot see by
construction (SYS-9..14 is cross-subsystem only) -- but an internally
conflicted subsystem cannot honestly be called a "known-compatible"
composition partner for ANY other subsystem, so this module folds that
per-subsystem fact into every pair the conflicted subsystem appears in.

REUSE OVER REINVENT: NO NEW ANALYSIS, ONLY A ROLLUP. This module computes
nothing SYS-9..14 or `ip_ownership_conflict.py` did not already compute. It
calls `system_resource_inventory.analyze_selected_subsystem_resources()` --
the real SYS-1 -> SYS-5..8 -> SYS-9..14 front door, so SYS-1's refusal to
analyze an unselected/not-on-disk set is not bypassed -- and reads the
resulting `relationships` list, each of which already carries `subsystem_a`/
`subsystem_b` (assigned by `classify_resource_relationship()`, never
re-derived here by parsing a resource_id string). It calls
`ip_ownership_conflict.analyze_ip_ownership_conflict()` once per subsystem,
fed the REAL `env.manifest.json` path each subsystem's own SYS-6 analysis
already resolved (`per_subsystem[i]["inputs"]["env_manifest_path"]`), plus
whatever `legacy_bfm_declarations`/`connectivity_rows` a caller supplies --
there is no producer anywhere in this codebase for a legacy hand-written
driver declaration (confirmed by `ip_ownership_conflict.py`'s own module
docstring), so that half stays honestly caller-declared exactly as it is in
that module.

WHY `real_cross_subsystem_findings()` IS NOT WHAT THIS MODULE CALLS. That
function is `system_resource_inventory.py`'s own gate-facing FLATTENING of
the same analysis, and its `shared_relationships` list deliberately drops
`subsystem_a`/`subsystem_b` (it carries only `resource_a`/`resource_b`
resource ids) because its two real callers -- the two SYSTEM_LEVEL gate
scripts and the SoC composer -- only ever need "is there a shared resource at
all", never "which two subsystems, specifically". A pairwise MATRIX is
exactly the shape that flattening was built to not need, so recovering
subsystem attribution from it would mean re-deriving it by parsing a
resource_id's own `f"{subsystem_id}::{hierarchy}::{interface}"` string
convention -- fragile, and unnecessary when the underlying
`analyze_selected_subsystem_resources()` call already carries the real
per-relationship subsystem attribution directly. This module therefore calls
the fuller analysis one layer below the flattening, which is the SAME real
SYS-9..14 computation `real_cross_subsystem_findings()` itself wraps (that
function's own body calls `analyze_selected_subsystem_resources()`
internally) -- not a second, parallel analysis.

FIVE HONEST PAIR STATUSES, WORST-WINS.
  - `SUBSYSTEM_SELF_CONFLICT_BLOCKS_COMPOSITION` -- either subsystem in the
    pair carries its own unresolved `ip_ownership_conflict.STATUS_CONFLICT`
    (a real VIP agent and a legacy hand-written driver both ACTIVE on one of
    ITS OWN ports). This outranks every cross-subsystem finding: a subsystem
    that is not internally clean cannot be a known-compatible partner for
    anything, regardless of what SYS-9..14 finds between it and its partner.
  - `CROSS_SUBSYSTEM_DRIVER_CONFLICT` -- SYS-9..14 found a real
    `REL_DRIVER_CONFLICT` or `REL_CONFIGURATION_CONFLICT` relationship
    between a resource owned by one subsystem and a resource owned by the
    other -- SYS-12's stop rule, applied per pair. Blocked.
  - `UNKNOWN` -- real evidence exists but could not settle the question: a
    `REL_UNKNOWN` relationship between the pair's own resources (SYS-11's
    "do not decide duplicates by class names alone" case), OR either
    subsystem's own IP-ownership self-check itself came back
    `ip_ownership_conflict.STATUS_UNKNOWN` (a legacy driver shares a port
    with a real VIP but ownership could not be judged), OR a caller asked
    for a self-check but supplied no `env.manifest.json` to run it against.
    Never silently promoted to COMPATIBLE.
  - `SHARED_RESOURCE_REQUIRES_REVIEW` -- a real `REL_SAME_PHYSICAL` or
    `REL_SHARED_LOGICAL` relationship: the two subsystems genuinely reach one
    physical/logical resource, but not through two ACTIVE drivers, so SYS-12
    does not stop it -- a human should still review the arbitration/ownership
    model before signing off composition.
  - `COMPATIBLE` -- real evidence was checked (SYS-9..14 ran, both
    subsystems' self-checks, when requested, came back CLEAR/NOT_APPLICABLE)
    and none of the above fired. `known_compatible: true` is set ONLY here --
    every other status is `known_compatible: false`, because "known
    compatible" is a positive claim this module never makes without positive
    evidence.

A caller who never supplies `ip_ownership_inputs` for a subsystem gets that
subsystem's self-check reported `NOT_REQUESTED` -- distinct from `UNKNOWN`
and never forcing a pair to `UNKNOWN` on its own, mirroring
`ip_ownership_conflict.py`'s own honest default (no legacy driver declared is
the common, clean case for a subsystem built entirely on VIP, not evidence of
a problem).

SCOPE BOUNDARY -- ROLLUP ONLY, NEVER ARBITRATION. This module picks no
winner between two active drivers and resolves no shared-resource contention
-- SYS-12's own `preferred_model` text is carried through on every blocking
pair for the human who must decide, exactly as `system_resource_inventory.py`
and `ip_ownership_conflict.py` themselves already do. Nothing here builds a
system environment, submits a build/regression, or touches any
approval/governance mechanism.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import env_manifest as em
from . import ip_ownership_conflict as ioc
from . import system_resource_inventory as sri

# ---------------------------------------------------------------------------
# Vocabulary. Deliberately its own five-value spelling, not a synonym for
# SYS-11's seven relationship classes or ip_ownership_conflict.py's four
# report statuses -- this module answers a THIRD question (pairwise
# composability), not either of theirs.
# ---------------------------------------------------------------------------

PAIR_COMPATIBLE = "COMPATIBLE"
PAIR_SHARED_RESOURCE_REVIEW = "SHARED_RESOURCE_REQUIRES_REVIEW"
PAIR_CONFLICT = "CROSS_SUBSYSTEM_DRIVER_CONFLICT"
PAIR_SELF_CONFLICT = "SUBSYSTEM_SELF_CONFLICT_BLOCKS_COMPOSITION"
PAIR_UNKNOWN = "UNKNOWN"

PAIR_STATUSES: Tuple[str, ...] = (
    PAIR_COMPATIBLE, PAIR_SHARED_RESOURCE_REVIEW, PAIR_CONFLICT,
    PAIR_SELF_CONFLICT, PAIR_UNKNOWN,
)

MATRIX_ALL_COMPATIBLE = "ALL_KNOWN_COMPATIBLE"
MATRIX_NEEDS_REVIEW = "SOME_PAIRS_NEED_REVIEW"
MATRIX_BLOCKED = "BLOCKED"
MATRIX_INCOMPLETE = "INCOMPLETE_EVIDENCE"
MATRIX_NOT_AVAILABLE = "NOT_AVAILABLE"

MATRIX_STATUSES: Tuple[str, ...] = (
    MATRIX_ALL_COMPATIBLE, MATRIX_NEEDS_REVIEW, MATRIX_BLOCKED,
    MATRIX_INCOMPLETE, MATRIX_NOT_AVAILABLE,
)

# Relationship classes (system_resource_inventory.py's own vocabulary,
# imported, never re-spelled) that a pair's cross-subsystem evidence is
# judged against.
_CONFLICT_RELATIONSHIP_CLASSES = (sri.REL_DRIVER_CONFLICT, sri.REL_CONFIGURATION_CONFLICT)
_SHARED_REVIEW_RELATIONSHIP_CLASSES = (sri.REL_SAME_PHYSICAL, sri.REL_SHARED_LOGICAL)

# ip_ownership_conflict.py's own self-check outcomes this module reads (never
# re-spelled) plus the two wrapper-local outcomes for a self-check that was
# never asked for, or was asked for but had no manifest to run against.
_SELF_CHECK_NOT_REQUESTED = "NOT_REQUESTED"
_SELF_CHECK_NO_MANIFEST = "NO_MANIFEST_AVAILABLE"


class SubsysCompatMatrixError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


# ===========================================================================
# Per-subsystem IP-ownership self-check (ip_ownership_conflict.py, imported)
# ===========================================================================

def evaluate_subsystem_self_check(
        subsystem_id: str, env_manifest_path: str,
        ip_ownership_inputs: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """One subsystem's own IP-level VIP-vs-legacy-BFM ownership check, via
    `ip_ownership_conflict.analyze_ip_ownership_conflict()` -- called, never
    re-implemented. `ip_ownership_inputs[subsystem_id]` may carry
    `legacy_bfm_declarations` (the caller-declared fact that module itself
    has no producer for), `connectivity_rows` (optional, resolves each VIP
    instance's real active/passive state), and an optional pre-loaded
    `env_manifest` dict overriding the path this module would otherwise
    load."""
    entry = ip_ownership_inputs.get(subsystem_id)
    if entry is None:
        return {"status": _SELF_CHECK_NOT_REQUESTED,
                "reason": ("no ip_ownership_inputs entry supplied for this subsystem -- "
                           "IP-level self-check not requested (the common, honest case for "
                           "a subsystem built entirely on VIP with no legacy driver to "
                           "declare)")}

    manifest = entry.get("env_manifest")
    if manifest is None:
        if not env_manifest_path:
            return {"status": _SELF_CHECK_NO_MANIFEST,
                    "reason": ("a self-check was requested for this subsystem but no "
                               "env.manifest.json path was resolved for it by this "
                               "subsystem's own SYS-6 analysis -- cannot check VIP "
                               "instances against a manifest that was never produced")}
        try:
            manifest = em.load_env_manifest(env_manifest_path)
        except Exception as exc:  # a real, unreadable/invalid manifest is a real finding
            return {"status": _SELF_CHECK_NO_MANIFEST,
                    "reason": f"{env_manifest_path!r} could not be loaded: "
                              f"{type(exc).__name__}: {exc}"}

    report = ioc.analyze_ip_ownership_conflict(
        manifest,
        legacy_bfm_declarations=entry.get("legacy_bfm_declarations"),
        connectivity_rows=entry.get("connectivity_rows"))
    report = dict(report)
    report["source"] = "ip_ownership_conflict.analyze_ip_ownership_conflict"
    return report


# ===========================================================================
# Pair classification -- SYS-9..14's real relationships plus the two
# subsystems' own self-checks, worst-wins over the five statuses above.
# ===========================================================================

def classify_pair(subsystem_a: str, subsystem_b: str,
                   relationships: Sequence[Mapping[str, Any]],
                   self_checks: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """One pair's status, from real relationships already classified by
    `system_resource_inventory.classify_resource_relationship()` (each
    carrying its own `subsystem_a`/`subsystem_b`) plus the two subsystems'
    own IP-ownership self-checks. Worst-wins over five statuses, most severe
    first: SELF_CONFLICT, then CROSS_SUBSYSTEM_DRIVER_CONFLICT, then UNKNOWN,
    then SHARED_RESOURCE_REQUIRES_REVIEW, then COMPATIBLE."""
    key = frozenset((subsystem_a, subsystem_b))
    pair_relationships = [
        r for r in relationships
        if frozenset((r.get("subsystem_a"), r.get("subsystem_b"))) == key]

    base = {"subsystem_a": subsystem_a, "subsystem_b": subsystem_b,
            "relationships": pair_relationships}

    self_conflicted = [s for s in (subsystem_a, subsystem_b)
                       if self_checks.get(s, {}).get("status") == ioc.STATUS_CONFLICT]
    if self_conflicted:
        return dict(base, status=PAIR_SELF_CONFLICT, known_compatible=False,
                    reason=(f"{' and '.join(sorted(self_conflicted))} carr"
                            f"{'y' if len(self_conflicted) > 1 else 'ies'} "
                            "an unresolved IP-level VIP-vs-legacy-BFM ownership conflict on "
                            "its own environment (see self_conflict_checks) -- a subsystem "
                            "that is not internally clean cannot be a known-compatible "
                            "composition partner"),
                    blocking_self_checks={s: self_checks[s] for s in self_conflicted})

    conflict_rels = [r for r in pair_relationships
                     if r.get("relationship") in _CONFLICT_RELATIONSHIP_CLASSES]
    if conflict_rels:
        return dict(base, status=PAIR_CONFLICT, known_compatible=False,
                    reason=("real cross-subsystem resource relationship(s) found by "
                            "SYS-9..14: " + "; ".join(
                                f"{r['resource_a']} <-> {r['resource_b']} "
                                f"({r['relationship']}): {r['reason']}"
                                for r in conflict_rels)),
                    preferred_resolution_model=sri.SYS12_PREFERRED_MODEL)

    real_unknown_rels = [r for r in pair_relationships if r.get("relationship") == sri.REL_UNKNOWN]
    unresolved_self_checks = [
        s for s in (subsystem_a, subsystem_b)
        if self_checks.get(s, {}).get("status") in (ioc.STATUS_UNKNOWN, _SELF_CHECK_NO_MANIFEST)]
    if real_unknown_rels or unresolved_self_checks:
        reasons: List[str] = []
        if real_unknown_rels:
            reasons.append(
                "SYS-9..14 found relationship(s) it could not classify: " + "; ".join(
                    f"{r['resource_a']} <-> {r['resource_b']}: {r['reason']}"
                    for r in real_unknown_rels))
        if unresolved_self_checks:
            reasons.append(
                "self-check unresolved for: " + ", ".join(sorted(unresolved_self_checks)))
        return dict(base, status=PAIR_UNKNOWN, known_compatible=False,
                    reason="; ".join(reasons),
                    unresolved_self_checks={s: self_checks[s] for s in unresolved_self_checks})

    shared_rels = [r for r in pair_relationships
                   if r.get("relationship") in _SHARED_REVIEW_RELATIONSHIP_CLASSES]
    if shared_rels:
        return dict(base, status=PAIR_SHARED_RESOURCE_REVIEW, known_compatible=False,
                    reason=("real shared-resource relationship(s) found by SYS-9..14 "
                            "(not an active/active conflict, so SYS-12 does not stop it, "
                            "but the arbitration/ownership model should still be reviewed "
                            "before composition signoff): " + "; ".join(
                                f"{r['resource_a']} <-> {r['resource_b']} "
                                f"({r['relationship']}): {r['reason']}"
                                for r in shared_rels)))

    return dict(base, status=PAIR_COMPATIBLE, known_compatible=True,
                reason=("real cross-subsystem resource analysis (SYS-9..14) found no "
                        "conflicting or shared-resource relationship between these two "
                        "subsystems' resources, and neither subsystem's own IP-ownership "
                        "self-check reported an unresolved conflict"))


# ===========================================================================
# Front door
# ===========================================================================

def build_subsystem_compatibility_matrix(
        root, selected: Optional[Sequence[str]] = None, *,
        declared: Optional[Mapping[str, Any]] = None,
        ip_ownership_inputs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """The matrix itself: every unordered pair among `selected` (default: the
    REAL registered subsystem set,
    `environment_mode_router.read_registered_subsystem_names()` -- harness
    evidence, never a caller's claim), classified via `classify_pair()` over
    the REAL `system_resource_inventory.analyze_selected_subsystem_resources()`
    analysis and each subsystem's own `ip_ownership_conflict.py` self-check.

    Never guesses a matrix over subsystems it could not really analyze:
    fewer than two names, an unreadable registry, a refused SYS-1 selection,
    or an analysis failure all produce `status: NOT_AVAILABLE` with the real
    reason, and every pair is reported `UNKNOWN` citing it -- never a silent
    COMPATIBLE over nothing checked.
    """
    root = Path(root)
    ip_ownership_inputs = dict(ip_ownership_inputs or {})

    try:
        from .environment_mode_router import read_registered_subsystem_names
        names = [str(s) for s in
                 (selected if selected is not None else read_registered_subsystem_names(root))
                 if str(s).strip()]
    except Exception as exc:  # pragma: no cover - unreadable/malformed registry
        return _not_available_matrix([], f"REGISTRY_UNREADABLE: {type(exc).__name__}: {exc}")

    if len(names) < 2:
        return _not_available_matrix(names, "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE")

    try:
        result = sri.analyze_selected_subsystem_resources(root, names, declared=declared)
    except Exception as exc:
        return _not_available_matrix(names, f"ANALYSIS_FAILED: {type(exc).__name__}: {exc}")

    selection = result["selection"]
    if not selection.get("selection_admissible"):
        return _not_available_matrix(
            names, selection.get("refusal_reason") or "SELECTION_NOT_ADMISSIBLE",
            not_ready=[r.get("subsystem") for r in selection.get("not_ready") or []])

    analysis = result["resource_analysis"]
    relationships = analysis["relationships"]

    # subsystem_id -> real env.manifest.json path, off the SAME SYS-6
    # per-subsystem inputs record this whole analysis already resolved --
    # never re-derived or guessed at a second time.
    manifest_paths: Dict[str, str] = {
        str(r.get("subsystem_id")): str((r.get("inputs") or {}).get("env_manifest_path") or "")
        for r in result["synthesis"]["per_subsystem"]}

    self_checks: Dict[str, Dict[str, Any]] = {
        s: evaluate_subsystem_self_check(s, manifest_paths.get(s, ""), ip_ownership_inputs)
        for s in names}

    pairs: List[Dict[str, Any]] = []
    for i, s1 in enumerate(names):
        for s2 in names[i + 1:]:
            pairs.append(classify_pair(s1, s2, relationships, self_checks))

    return _assemble_matrix(names, pairs, self_checks)


def _not_available_matrix(names: Sequence[str], reason: str, **detail: Any) -> Dict[str, Any]:
    pairs = [
        {"subsystem_a": s1, "subsystem_b": s2, "status": PAIR_UNKNOWN, "known_compatible": False,
         "reason": f"cross-subsystem resource analysis unavailable -- {reason}",
         "relationships": []}
        for i, s1 in enumerate(names) for s2 in names[i + 1:]]
    return {
        "status": MATRIX_NOT_AVAILABLE, "reason": reason, "subsystems": list(names),
        "pairs": pairs, "self_conflict_checks": {},
        "counts": {**{s: 0 for s in PAIR_STATUSES}, PAIR_UNKNOWN: len(pairs)},
        "known_compatible_pairs": [], "artifacts_modified": False, **detail,
    }


def _assemble_matrix(names: Sequence[str], pairs: Sequence[Mapping[str, Any]],
                      self_checks: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {s: 0 for s in PAIR_STATUSES}
    for p in pairs:
        counts[p["status"]] = counts.get(p["status"], 0) + 1

    if counts[PAIR_CONFLICT] or counts[PAIR_SELF_CONFLICT]:
        overall = MATRIX_BLOCKED
    elif counts[PAIR_UNKNOWN]:
        overall = MATRIX_INCOMPLETE
    elif counts[PAIR_SHARED_RESOURCE_REVIEW]:
        overall = MATRIX_NEEDS_REVIEW
    else:
        overall = MATRIX_ALL_COMPATIBLE

    return {
        "status": overall,
        "subsystems": list(names),
        "pairs": list(pairs),
        "self_conflict_checks": dict(self_checks),
        "counts": counts,
        "known_compatible_pairs": [[p["subsystem_a"], p["subsystem_b"]] for p in pairs
                                   if p["known_compatible"]],
        "artifacts_modified": False,
    }


# ===========================================================================
# Rendering + shared ad hoc front door (no `dv-harness` CLI verb -- see the
# item's own house-style note: `cli.py`/`gates.py` are large files under
# concurrent-edit pressure across this batch, matching several recent
# modules' own disclosed choice)
# ===========================================================================

_MATRIX_COLUMNS = (
    ("subsystem_a", "Subsystem A"), ("subsystem_b", "Subsystem B"),
    ("status", "Status"), ("known_compatible", "Known Compatible"), ("reason", "Reason"),
)


def render_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    rows = [{"subsystem_a": p["subsystem_a"], "subsystem_b": p["subsystem_b"],
             "status": p["status"], "known_compatible": p["known_compatible"],
             "reason": p["reason"]} for p in matrix.get("pairs") or []]
    return render_markdown_table(list(_MATRIX_COLUMNS), rows,
                                 empty_note="(fewer than two subsystems -- no pairs to report)")


def format_matrix_report(matrix: Mapping[str, Any]) -> str:
    lines = [f"SUBSYSTEM COMPATIBILITY MATRIX: {matrix['status']}", ""]
    if matrix.get("reason"):
        lines.append(matrix["reason"])
        lines.append("")
    lines.append(f"  subsystems : {', '.join(matrix.get('subsystems') or [])}")
    counts = matrix.get("counts") or {}
    lines.append("  pair status counts: " + ", ".join(
        f"{k}={counts.get(k, 0)}" for k in PAIR_STATUSES))
    lines.append("")
    lines.append(render_matrix_markdown(matrix))
    lines.append("")
    lines.append("SCOPE: this is a rollup, never an arbitration -- a blocking pair carries "
                 "SYS-12's preferred resolution model as text for a human; nothing here picks "
                 "a winner or resolves a conflict.")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(root, *, selected_path=None, ip_ownership_inputs_path=None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.subsys_compat_matrix`.
    Returns (text, exit_code): 0 ALL_KNOWN_COMPATIBLE, 1 NEEDS_REVIEW/BLOCKED,
    2 INCOMPLETE_EVIDENCE/NOT_AVAILABLE."""
    selected = _load_json(selected_path) if selected_path else None
    ip_ownership_inputs = _load_json(ip_ownership_inputs_path) if ip_ownership_inputs_path else None
    matrix = build_subsystem_compatibility_matrix(
        root, selected=selected, ip_ownership_inputs=ip_ownership_inputs)
    text = json.dumps(matrix, indent=2) if as_json else format_matrix_report(matrix)
    code = {MATRIX_ALL_COMPATIBLE: 0, MATRIX_NEEDS_REVIEW: 1, MATRIX_BLOCKED: 1,
            MATRIX_INCOMPLETE: 2, MATRIX_NOT_AVAILABLE: 2}[matrix["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.subsys_compat_matrix",
        description="Subsystem Compatibility Matrix: which subsystem pairs are "
                    "known-compatible for composition, from the REAL SYS-9..14 "
                    "cross-subsystem resource analysis and each subsystem's own real "
                    "IP-ownership self-check. Never a hand-typed matrix.")
    ap.add_argument("--root", required=True, help="Project root (contains .dv-harness/).")
    ap.add_argument("--selected", dest="selected_path",
                    help="Path to a JSON array of subsystem names. Omit to use the real "
                         "registered subsystem set.")
    ap.add_argument("--ip-ownership-inputs", dest="ip_ownership_inputs_path",
                    help="Path to a JSON object keyed by subsystem id, each value carrying "
                         "optional legacy_bfm_declarations/connectivity_rows/env_manifest "
                         "for that subsystem's own IP-ownership self-check.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable matrix.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.root, selected_path=a.selected_path,
        ip_ownership_inputs_path=a.ip_ownership_inputs_path, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
