"""dv_harness/intra_project_root_cause_clustering.py -- cluster THIS ONE
project's own Memory-store `job_failure` records to detect that two
DIFFERENTLY-WORDED failure signatures are actually the same underlying root
cause.

WHAT THIS IS, AND WHAT IT IS DELIBERATELY NOT
-----------------------------------------------
`capability_evolution.repeated_unresolved_failure_patterns()` already groups
this project's own `job_failure` records by `evidence_db.signature_key()` --
an EXACT hash of the whole `failure_signature` dict. That is the right tool
for "the same failure, recorded twice" (a retry, a re-run against the same
commit). It is the WRONG tool for "two agents independently described the
SAME real root cause in slightly different words" -- `signature_key()` hashes
the dict verbatim, so `symptom="link training timeout on lane 0"` and
`symptom="link training timeout observed on lane zero"` hash to two entirely
different keys and are never grouped, even though a human reading both would
immediately recognise them as the same bug. `cross_project_mining.py` solves
an adjacent but genuinely different problem -- the SAME exact signature_key
recurring across SEVERAL PROJECTS' stores -- and is explicitly out of scope
here: this module never registers a project, never reads a second project's
store, and never mints a cross-project finding.

This module is the missing layer BETWEEN those two: within ONE project's own
store, cluster DISTINCT signature_key groups whose own real symptom/
root_cause_hint/terminal_signature text is similar enough that a human should
be asked whether they are really one root cause under two names.

REUSE, NOT REINVENTION
-----------------------
Nothing here re-derives what already has one real definition in this
codebase:
  - the EXACT-match grouping (which records share one signature_key) is
    `evidence_db.signature_key()`, imported, never a second hash;
  - "which records were INDEPENDENT observations" is
    `capability_evolution._run_identity()`, imported -- three retries against
    one commit stay one observation here too, exactly as it does one layer up
    in `repeated_unresolved_failure_patterns()`;
  - "is this signature already closed" is
    `capability_evolution.failure_resolution_claims()` /
    `resolved_failure_claim_texts()`, imported -- the same exact-equality
    join against a real `verified_fix` record's own `root_cause`/`symptoms`
    text, never a second, fuzzier definition of "resolved";
  - the tokenizer is `memory._tok`, imported as `_tokenize` -- the exact
    stopword-aware tokenizer `memory_dedup.py` and `memory_vault.py` already
    reuse the same way, not a third copy;
  - evidence is read through the shared `MemoryStore.find()`, and a bare
    project with no memory store yet is checked via
    `cross_project_mining.has_memory_store()` BEFORE ever constructing a
    `MemoryStore` -- that constructor `mkdir()`s the five-tier tree and
    writes an empty `index.json`, so asking "does this project have anything
    to cluster" must never itself create the store it is asking about.

CLUSTERING IS SUGGESTIONS ONLY -- IT NEVER MUTATES A RECORD
-------------------------------------------------------------
This module is a PURE READ. It never calls `MemoryStore.add()`,
`MemoryGC.confirm()`/`retract()`/`supersede()`, never merges two records into
one, and never writes a memory record of any tier. A "cluster" is a
recommendation, carrying the whole real evidence basis (which two signature
keys, their real shared tokens, their real similarity score, their real
memory_ids) so a human/caller can decide by hand whether to actually merge
the underlying knowledge -- e.g. by hand-writing one `verified_fix` record
whose `root_cause`/`symptoms` cover both signatures' claim texts, or by
recording a `MemoryGC.supersede()` decision themselves. Nothing in this
module performs either act.

CLUSTERING RULE, STATED PLAINLY
--------------------------------
Two DISTINCT signature_key groups are merged into one cluster only when BOTH
hold:
  1. both declare the SAME real, non-empty `protocol` (normalized,
     case-insensitive) -- a different protocol is a different subsystem, not
     the same root cause reworded, and is never bridged by incidental text
     overlap;
  2. the Jaccard token overlap of their own `symptom` + `root_cause_hint` +
     `terminal_signature` text is at or above `min_similarity` (default
     `DEFAULT_MIN_SIMILARITY`), a deterministic, disclosed heuristic a caller
     may override -- never a semantic/embedding model, since none exists in
     this codebase and inventing one would be exactly the unverifiable
     machinery the Evidence Truth Rule forbids.

A group missing a protocol, or carrying too little descriptive text to
compare honestly, is never silently paired with anything -- it is reported,
by name, as `ineligible_signature_groups` with the real reason, mirroring
`spec_intelligence.py`'s own "never let an absence of proof read as a
finding" discipline for its own dedup scan.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .capability_evolution import (
    REPEAT_FAILURE_JOB_MEMORY_KIND,
    UNIDENTIFIED_RUN,
    _failure_signature_summary,
    _norm_text,
    _run_identity,
    failure_resolution_claims,
    resolved_failure_claim_texts,
)
from .memory import _tok as _tokenize  # reuse the existing stopword-aware
                                        # tokenizer -- see memory_dedup.py and
                                        # memory_vault.py, which do the same.
from .models import Status

# --------------------------------------------------------------------------
# Thresholds -- disclosed heuristics, never a measurement
# --------------------------------------------------------------------------

#: A Jaccard token-overlap bar at or above which two DIFFERENT signature_key
#: groups' own descriptive text is judged similar enough to suggest they are
#: the same underlying root cause. Deliberately the same order of magnitude
#: as `spec_intelligence.DUPLICATE_SIMILARITY_LOW_THRESHOLD` (0.5) -- a
#: moderate bar for a SUGGESTION a human still reviews, not an
#: auto-merge threshold. A project may raise or lower it per call.
DEFAULT_MIN_SIMILARITY = 0.5

#: Below this many real descriptive tokens (symptom + root_cause_hint +
#: terminal_signature, combined), a group's text is too thin to compare
#: honestly -- a one-word symptom trivially scores 1.0 against any other
#: signature sharing that one word, which would be a false cluster, not a
#: real one.
MIN_TOKENS_FOR_COMPARISON = 2

#: The pairwise similarity scan is O(n^2) over the ELIGIBLE signature groups.
#: Above this count the scan is SKIPPED (never silently truncated) rather
#: than silently costing an unbounded amount of time on a store with many
#: distinct failure signatures -- the same discipline
#: `spec_intelligence.MAX_DEDUP_SCAN_SIZE` already applies to an analogous
#: pairwise text-similarity scan.
MAX_CLUSTER_SCAN_SIZE = 300

# --------------------------------------------------------------------------
# Vocabulary -- checked disjoint from a real stage verdict at import time
# --------------------------------------------------------------------------

STATUS_CLUSTERS_FOUND = "CLUSTERS_FOUND"
STATUS_NO_CLUSTERS_FOUND = "NO_CLUSTERS_FOUND"
STATUS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATUS_SCAN_SKIPPED = "SCAN_SKIPPED_TOO_LARGE"

REASON_MISSING_PROTOCOL = "MISSING_PROTOCOL"
REASON_INSUFFICIENT_TEXT = "INSUFFICIENT_DESCRIPTIVE_TEXT"

RESOLUTION_ALL_OPEN = "CLUSTER_ALL_OPEN"
RESOLUTION_PARTIALLY_RESOLVED = "CLUSTER_PARTIALLY_RESOLVED"
RESOLUTION_ALL_RESOLVED = "CLUSTER_ALL_RESOLVED"

# Mutated only by tests, to prove the collision guard below has real
# detection power rather than merely never firing by accident.
_VOCAB_TOKENS = frozenset({
    STATUS_CLUSTERS_FOUND, STATUS_NO_CLUSTERS_FOUND, STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_SCAN_SKIPPED, RESOLUTION_ALL_OPEN, RESOLUTION_PARTIALLY_RESOLVED,
    RESOLUTION_ALL_RESOLVED,
})


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status/resolution vocabulary must share no token
    with `dv_harness.models.Status` -- a clustering SUGGESTION must never be
    spelled the same way as a real stage-gate PASS/FAIL verdict."""
    collision = _VOCAB_TOKENS & {s.value for s in Status}
    if collision:
        raise AssertionError(
            "intra_project_root_cause_clustering vocabulary collides with "
            f"dv_harness.models.Status: {sorted(collision)}"
        )


assert_no_verification_verdict_vocabulary()


class IntraProjectClusteringError(ValueError):
    """A usage error -- an invalid `min_similarity`, never a data problem
    (a data problem is reported, never raised)."""


# --------------------------------------------------------------------------
# Building the exact-match signature groups (never filtered, never mutated)
# --------------------------------------------------------------------------

def build_signature_groups(root) -> Dict[str, Dict[str, Any]]:
    """Every DISTINCT `job_failure` signature this project's store has ever
    recorded, grouped by `evidence_db.signature_key()` -- the same exact
    identity `capability_evolution.repeated_unresolved_failure_patterns()`
    and `cross_project_mining.project_failure_index()` already group by.

    Deliberately UNFILTERED by occurrence count or resolution status: a
    signature that occurred only once, or that a `verified_fix` already
    closed, still needs to be visible to the clustering pass below -- two
    once-only signatures that are individually below
    `capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` can still be the
    SAME underlying root cause once clustered together, and a resolved
    signature clustered against an unresolved one is itself a real, useful
    finding (see `RESOLUTION_PARTIALLY_RESOLVED`).

    A pure read. Never constructs a `MemoryStore` for a project that has
    none -- see `cross_project_mining.has_memory_store()`."""
    from .evidence_db import signature_key
    from .cross_project_mining import has_memory_store
    from .memory import MemoryStore

    root_path = Path(root).resolve()
    if not has_memory_store(root_path):
        return {}

    store = MemoryStore(root_path)
    resolved = set(resolved_failure_claim_texts(root_path))
    groups: Dict[str, Dict[str, Any]] = {}
    for record in store.find("job", kind=REPEAT_FAILURE_JOB_MEMORY_KIND):
        signature = record.get("failure_signature")
        if not isinstance(signature, dict):
            continue
        key = signature_key(signature)
        group = groups.setdefault(key, {
            "signature_key": key,
            "failure_signature": signature,
            "memory_ids": [],
            "run_identities": [],
        })
        mid = str(record.get("memory_id") or "").strip()
        if mid and mid not in group["memory_ids"]:
            group["memory_ids"].append(mid)
        run = _run_identity(record)
        if run != UNIDENTIFIED_RUN and run not in group["run_identities"]:
            group["run_identities"].append(run)

    for group in groups.values():
        group["memory_ids"] = sorted(group["memory_ids"])
        group["run_identities"] = sorted(group["run_identities"])
        group["occurrence_count"] = len(group["memory_ids"])
        group["independent_run_count"] = len(group["run_identities"])
        group["resolution_claims"] = failure_resolution_claims(group["failure_signature"])
        group["resolved_by_verified_fix"] = sorted(
            set(group["resolution_claims"]) & resolved
        )
        group["summary"] = _failure_signature_summary(group["failure_signature"])
    return groups


# --------------------------------------------------------------------------
# Eligibility + pairwise similarity
# --------------------------------------------------------------------------

_COMPARISON_TEXT_FIELDS = ("symptom", "root_cause_hint", "terminal_signature")


def _protocol_of(signature: Dict[str, Any]) -> str:
    return _norm_text(signature.get("protocol"))


def _comparison_tokens(signature: Dict[str, Any]) -> set:
    text = " ".join(_norm_text(signature.get(field)) for field in _COMPARISON_TEXT_FIELDS)
    return _tokenize(text)


def eligibility_reason(group: Dict[str, Any]) -> Optional[str]:
    """Why a signature group can never be paired with any other -- checked
    ONCE per group, so an ineligible group reports its own real reason
    rather than one reason per pair it might have been compared against.
    `None` means the group IS eligible for pairwise comparison."""
    if not _protocol_of(group["failure_signature"]):
        return REASON_MISSING_PROTOCOL
    if len(_comparison_tokens(group["failure_signature"])) < MIN_TOKENS_FOR_COMPARISON:
        return REASON_INSUFFICIENT_TEXT
    return None


def pair_similarity(group_a: Dict[str, Any], group_b: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic Jaccard token-overlap between two ELIGIBLE signature
    groups' own symptom/root_cause_hint/terminal_signature text -- never a
    substring or fuzzy match, and never consulted for a protocol mismatch
    (the caller checks that separately, see `cluster_intra_project_root_causes`)."""
    tokens_a = _comparison_tokens(group_a["failure_signature"])
    tokens_b = _comparison_tokens(group_b["failure_signature"])
    overlap = tokens_a & tokens_b
    union = tokens_a | tokens_b
    score = round(len(overlap) / len(union), 4) if union else 0.0
    return {"score": score, "shared_tokens": sorted(overlap)}


class _UnionFind:
    """Plain union-find over signature_key strings -- connected components
    ARE the suggested clusters."""

    def __init__(self, keys) -> None:
        self.parent: Dict[str, str] = {k: k for k in keys}

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_id(member_keys: Sequence[str]) -> str:
    """A stable, content-derived id: the same member set always hashes to
    the same id, so a later re-run's cluster is recognisable as "the same
    suggestion again" rather than a random new one."""
    digest = hashlib.sha256("|".join(sorted(member_keys)).encode("utf-8")).hexdigest()
    return f"RCC-{digest[:16].upper()}"


def _disclosure_for(status: str, cluster_count: int, eligible_count: int,
                    ineligible_count: int) -> str:
    if status == STATUS_INSUFFICIENT_EVIDENCE:
        return (
            "no job_failure signature was found in this project's own memory "
            "store -- there is nothing to cluster. This is the honest answer "
            "about the evidence, not a finding that no failures were ever "
            "recorded."
        )
    if status == STATUS_SCAN_SKIPPED:
        return (
            f"{eligible_count} eligible signature groups exceeds "
            f"MAX_CLUSTER_SCAN_SIZE={MAX_CLUSTER_SCAN_SIZE}; the pairwise "
            "similarity scan was skipped rather than run unbounded. Every "
            "eligible group is reported as an unclustered single below, "
            "never silently dropped."
        )
    if status == STATUS_CLUSTERS_FOUND:
        return (
            f"{cluster_count} cluster(s) suggested from real, cited pairwise "
            "text-similarity evidence. This is a SUGGESTION ONLY -- no memory "
            "record was read for anything but display, and nothing was "
            "merged, retracted or superseded. A human/caller decides whether "
            "to act on it."
        )
    # STATUS_NO_CLUSTERS_FOUND
    return (
        f"{eligible_count} eligible signature group(s) were compared and none "
        f"cleared the similarity bar; {ineligible_count} group(s) could not "
        "be compared at all (see ineligible_signature_groups). No cluster is "
        "suggested."
    )


# --------------------------------------------------------------------------
# The main entry point
# --------------------------------------------------------------------------

def cluster_intra_project_root_causes(
    root, *, min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> Dict[str, Any]:
    """Suggest, from real evidence only, which of THIS project's own distinct
    `job_failure` signature groups likely share one underlying root cause.

    A pure read: nothing is written to any memory tier, no memory record is
    mutated, and no store is created for a project that has none. Every
    returned cluster carries the whole basis of the suggestion -- the member
    signature keys, their real memory_ids, the real pairwise similarity
    evidence that connected them, and each member's own real resolution
    status -- so a reader re-derives the conclusion by hand instead of
    trusting a bare cluster id.
    """
    min_similarity = float(min_similarity)
    if not (0.0 < min_similarity <= 1.0):
        raise IntraProjectClusteringError(
            f"min_similarity must be in (0, 1], got {min_similarity}"
        )

    root_path = Path(root).resolve()
    groups = build_signature_groups(root_path)

    if not groups:
        return {
            "root": str(root_path),
            "status": STATUS_INSUFFICIENT_EVIDENCE,
            "min_similarity": min_similarity,
            "signature_group_count": 0,
            "eligible_signature_group_count": 0,
            "clusters": [],
            "single_signature_groups": [],
            "ineligible_signature_groups": [],
            "disclosure": _disclosure_for(STATUS_INSUFFICIENT_EVIDENCE, 0, 0, 0),
        }

    eligible: Dict[str, Dict[str, Any]] = {}
    ineligible: List[Dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        reason = eligibility_reason(group)
        if reason is None:
            eligible[key] = group
        else:
            ineligible.append({
                "signature_key": key,
                "reason": reason,
                "protocol": _protocol_of(group["failure_signature"]) or None,
                "occurrence_count": group["occurrence_count"],
                "memory_ids": group["memory_ids"],
            })

    scan_skipped = len(eligible) > MAX_CLUSTER_SCAN_SIZE

    clusters: List[Dict[str, Any]] = []
    singles: List[Dict[str, Any]] = []

    if scan_skipped:
        note = (
            f"pairwise clustering scan skipped: {len(eligible)} eligible "
            f"signature groups exceeds MAX_CLUSTER_SCAN_SIZE={MAX_CLUSTER_SCAN_SIZE}"
        )
        for key in sorted(eligible):
            group = eligible[key]
            singles.append({
                "signature_key": key,
                "protocol": _protocol_of(group["failure_signature"]) or None,
                "occurrence_count": group["occurrence_count"],
                "independent_run_count": group["independent_run_count"],
                "memory_ids": group["memory_ids"],
                "summary": group["summary"],
                "note": note,
            })
        status = STATUS_SCAN_SKIPPED
    else:
        eligible_keys = sorted(eligible)
        edges: List[Dict[str, Any]] = []
        uf = _UnionFind(eligible_keys)
        for i, a in enumerate(eligible_keys):
            protocol_a = _protocol_of(eligible[a]["failure_signature"])
            for b in eligible_keys[i + 1:]:
                if protocol_a != _protocol_of(eligible[b]["failure_signature"]):
                    continue
                pair = pair_similarity(eligible[a], eligible[b])
                if pair["score"] >= min_similarity:
                    uf.union(a, b)
                    edges.append({
                        "signature_key_a": a, "signature_key_b": b,
                        "similarity_score": pair["score"],
                        "shared_tokens": pair["shared_tokens"],
                    })

        components: Dict[str, List[str]] = {}
        for key in eligible_keys:
            components.setdefault(uf.find(key), []).append(key)

        for members in components.values():
            member_keys = sorted(members)
            if len(member_keys) < 2:
                group = eligible[member_keys[0]]
                singles.append({
                    "signature_key": member_keys[0],
                    "protocol": _protocol_of(group["failure_signature"]) or None,
                    "occurrence_count": group["occurrence_count"],
                    "independent_run_count": group["independent_run_count"],
                    "memory_ids": group["memory_ids"],
                    "summary": group["summary"],
                })
                continue

            member_edges = [
                e for e in edges
                if e["signature_key_a"] in member_keys and e["signature_key_b"] in member_keys
            ]
            run_union = sorted({
                run for k in member_keys for run in eligible[k]["run_identities"]
            })
            memory_union = sorted({
                mid for k in member_keys for mid in eligible[k]["memory_ids"]
            })
            resolved_flags = [bool(eligible[k]["resolved_by_verified_fix"]) for k in member_keys]
            if all(resolved_flags):
                resolution_status = RESOLUTION_ALL_RESOLVED
            elif any(resolved_flags):
                resolution_status = RESOLUTION_PARTIALLY_RESOLVED
            else:
                resolution_status = RESOLUTION_ALL_OPEN

            clusters.append({
                "cluster_id": _cluster_id(member_keys),
                "protocol": _protocol_of(eligible[member_keys[0]]["failure_signature"]) or None,
                "member_signature_keys": member_keys,
                "members": [
                    {
                        "signature_key": k,
                        "summary": eligible[k]["summary"],
                        "occurrence_count": eligible[k]["occurrence_count"],
                        "independent_run_count": eligible[k]["independent_run_count"],
                        "memory_ids": eligible[k]["memory_ids"],
                        "resolved_by_verified_fix": eligible[k]["resolved_by_verified_fix"],
                    }
                    for k in member_keys
                ],
                "pairwise_evidence": sorted(
                    member_edges, key=lambda e: (e["signature_key_a"], e["signature_key_b"])
                ),
                "total_occurrence_count": len(memory_union),
                "total_independent_run_count": len(run_union),
                "run_identities": run_union,
                "memory_ids": memory_union,
                "resolution_status": resolution_status,
                "min_similarity": min_similarity,
            })

        clusters.sort(key=lambda c: (-c["total_independent_run_count"], c["cluster_id"]))
        status = STATUS_CLUSTERS_FOUND if clusters else STATUS_NO_CLUSTERS_FOUND

    singles.sort(key=lambda s: s["signature_key"])
    ineligible.sort(key=lambda r: r["signature_key"])

    return {
        "root": str(root_path),
        "status": status,
        "min_similarity": min_similarity,
        "signature_group_count": len(groups),
        "eligible_signature_group_count": len(eligible),
        "clusters": clusters,
        "single_signature_groups": singles,
        "ineligible_signature_groups": ineligible,
        "disclosure": _disclosure_for(status, len(clusters), len(eligible), len(ineligible)),
    }


# --------------------------------------------------------------------------
# Rendering + ad hoc CLI (no dv-harness verb / gates.py entry -- standalone,
# matching several sibling same-day modules' own disclosed choice)
# --------------------------------------------------------------------------

def render_report_markdown(report: Dict[str, Any]) -> str:
    from .connectivity import render_markdown_table

    lines = [
        "# Intra-Project Root-Cause Clustering",
        "",
        f"root: {report.get('root')}",
        f"status: {report.get('status')}",
        f"min_similarity: {report.get('min_similarity')}",
        f"signature_group_count: {report.get('signature_group_count')}",
        f"eligible_signature_group_count: {report.get('eligible_signature_group_count')}",
        "",
        report.get("disclosure", ""),
        "",
        "## Suggested Clusters",
    ]
    cluster_rows = [
        {
            "cluster_id": c["cluster_id"],
            "protocol": c.get("protocol") or "-",
            "members": len(c["member_signature_keys"]),
            "total_occurrence_count": c["total_occurrence_count"],
            "total_independent_run_count": c["total_independent_run_count"],
            "resolution_status": c["resolution_status"],
        }
        for c in report.get("clusters", [])
    ]
    lines.append(render_markdown_table(
        [("cluster_id", "Cluster"), ("protocol", "Protocol"), ("members", "Members"),
         ("total_occurrence_count", "Occurrences"),
         ("total_independent_run_count", "Independent Runs"),
         ("resolution_status", "Resolution")],
        cluster_rows,
        empty_note="(no clusters suggested)",
    ))
    return "\n".join(lines)


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="intra_project_root_cause_clustering")
    parser.add_argument("--root", default=".")
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = cluster_intra_project_root_causes(
            args.root, min_similarity=args.min_similarity
        )
    except IntraProjectClusteringError as exc:
        print(f"usage error: {exc}")
        return 2

    if args.json:
        print(_json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(render_report_markdown(report))

    if report["status"] == STATUS_CLUSTERS_FOUND:
        return 1
    if report["status"] in (STATUS_SCAN_SKIPPED, STATUS_INSUFFICIENT_EVIDENCE):
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
