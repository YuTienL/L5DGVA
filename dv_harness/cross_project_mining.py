"""dv_harness/cross_project_mining.py -- surface recurring root-cause/fix
patterns ACROSS N independent projects' Memory stores (VI-2).

WHAT WAS ACTUALLY MISSING
-------------------------
The per-project tiers are real and already accumulate verified root-cause/fix
knowledge: `memory.py`'s five-tier `MemoryStore`, `memory_router.py`'s tier
promotions, `memory_vault.py`'s note mirror. Adjacent to them,
`capability_evolution.repeated_unresolved_failure_patterns()` already mines
ONE project's Job Memory for a failure signature that several INDEPENDENT RUNS
recorded and no `verified_fix` closes.

A repo-wide grep (2026-09-05) confirmed there was no equivalent one level up:
nothing enumerated more than one project root, nothing grouped evidence by
project, and the only cross-project surface in the codebase --
`knowledge_center.py`'s remote broker -- is an add/search RPC against a shared
Linux DB path, not a miner: it never groups, never counts distinct projects,
and cannot run without a real remote server. So "the same root cause keeps
recurring across our projects, and one of them already fixed it" was a fact
nothing in this harness could compute.

This module is that miner, and only that. It is a PURE READ over N project
roots plus a small registry naming them.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
Nothing here re-derives "the same failure", "a closed failure", or "an
independent observation":

  - failure identity is `evidence_db.signature_key()` -- the same stable hash
    the evidence store accumulates `occurrence_count` on and the same one
    `repeated_unresolved_failure_patterns()` groups by;
  - the evidence is read through the shared `memory.MemoryStore.find()`;
  - the Job/Engineering kinds are `capability_evolution`'s own
    `REPEAT_FAILURE_JOB_MEMORY_KIND` / `RESOLVING_ENGINEERING_MEMORY_KIND`
    constants, imported, never retyped -- so "a gate-verified closure is a
    `verified_fix` record and nothing else" stays one decision in one place;
  - a closure's claim texts come from `capability_evolution.
    failure_resolution_claims()` / `resolved_failure_claim_texts()`, so the
    join is the same exact-equality-on-normalized-text join, not a second
    fuzzier one;
  - WITHIN a project, independent observations are counted by
    `capability_evolution._run_identity()` -- three retries against one commit
    stay one observation here too;
  - the audit trail is `storage.StateStore.event()`, the one real
    `events.jsonl` every other "who did what when" view reads.

WHAT MAKES AN OBSERVATION INDEPENDENT HERE
------------------------------------------
The PROJECT, and only the project. `_run_identity()`'s discipline lifted one
level: a project that recorded the same signature on forty runs is ONE
cross-project observation, because forty runs of one environment are forty
reports of one project's circumstances. `CROSS_PROJECT_MIN_PROJECTS = 2`
distinct projects is the bar, for the same reason
`memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` and
`capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` are 2.

That bar is only worth anything if two registered "projects" cannot secretly
be one store counted twice, so the registry refuses a root whose memory store
SHARES ANY `memory_id` with an already-registered one
(`ProjectIdentityCollisionError`), and `mine_cross_project_patterns()`
re-checks the same thing on the roots actually handed to it -- a registry file
is editable text, so the guard cannot live only on the write path.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It mints nothing and promotes nothing. A cross-project pattern is a QUESTION
for a human, not verified engineering knowledge, so the only route into
Organizational Memory remains `memory_router.promote_to_organizational()`'s
three gates plus `organizational_admission_gate()`. `promotion_readiness()`
below reports what such a promotion would still need; it writes nothing, and
`mine_cross_project_patterns()` writes no memory record of any tier.

HONEST PRODUCTION STATUS (see `production_status()`)
----------------------------------------------------
This repository is ONE project with ONE memory store. There is no second real
project here to mine, exactly as CLAUDE.md's "Environment Generation Mode"
already discloses for the RTL-tree case ("this harness repo itself has no RTL
tree of its own"). The mechanism is proven against multiple real, separately
constructed memory stores in `dv_harness_tests/test_cross_project_mining.py`;
it has NOT produced a production cross-project finding, and registering this
repo's own store twice under two names is precisely what
`ProjectIdentityCollisionError` exists to refuse.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .capability_evolution import (
    REPEAT_FAILURE_JOB_MEMORY_KIND,
    RESOLVING_ENGINEERING_MEMORY_KIND,
    UNIDENTIFIED_RUN,
    _failure_signature_summary,
    _norm_text,
    _run_identity,
    failure_resolution_claims,
    resolved_failure_claim_texts,
)
from .storage import StateStore, _atomic_replace

#: How many DISTINCT projects must record the same failure signature before it
#: is a cross-project pattern rather than one project's circumstances. Two,
#: the same number and the same reasoning as
#: memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS and
#: capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES: a second INDEPENDENT
#: source re-deriving the same thing is the smallest observation that cannot
#: be one source reported twice.
CROSS_PROJECT_MIN_PROJECTS = 2

#: Where the registry of mineable project roots lives, under the host
#: project's existing .dv-harness/ directory rather than a new top-level one.
REGISTRY_RELPATH = Path(".dv-harness") / "cross_project" / "registry.json"

#: Events written to the one real events.jsonl.
EVENT_REGISTER = "CROSS_PROJECT_REGISTER"
EVENT_UNREGISTER = "CROSS_PROJECT_UNREGISTER"
EVENT_MINE = "CROSS_PROJECT_MINING"

#: Mining outcomes. INSUFFICIENT_PROJECTS is a first-class result, not an
#: error: "we do not have two projects to compare" is the honest answer and
#: must never be dressed up as "no patterns found", which would read as a
#: negative finding about the projects rather than about the sample.
STATUS_OK = "OK"
STATUS_INSUFFICIENT_PROJECTS = "INSUFFICIENT_PROJECTS"

#: Why a registered root contributed nothing to a mining pass.
SKIP_NO_MEMORY_STORE = "NO_MEMORY_STORE"
SKIP_IDENTITY_COLLISION = "IDENTITY_COLLISION"
SKIP_UNREADABLE = "UNREADABLE"


class CrossProjectRegistryError(ValueError):
    """A registry operation that cannot honestly be performed."""


class ProjectIdentityCollisionError(CrossProjectRegistryError):
    """Two "projects" that are really one memory store under two names.

    Raised when a root being registered shares at least one `memory_id` with
    an already-registered root. This is the guard that keeps
    CROSS_PROJECT_MIN_PROJECTS meaningful: without it, pointing the registry
    at one store twice would manufacture a two-project consensus out of one
    project's audit trail.
    """


# --------------------------------------------------------------------------
# Reading a project's store without creating one
# --------------------------------------------------------------------------

def memory_store_dir(root) -> Path:
    """Where memory.MemoryStore keeps its records for `root`.

    Derived from MemoryStore's own layout (`<root>/.dv-harness/memory`) so the
    existence probe below and the store the miner later opens are the same
    directory by construction.
    """
    return Path(root).resolve() / ".dv-harness" / "memory"


def has_memory_store(root) -> bool:
    """Whether `root` ALREADY has a memory store to mine.

    Checked before ever constructing a `MemoryStore`, because that
    constructor mkdir()s its tiers and writes an empty `index.json` -- fine
    for the project that owns the store, wrong for a miner reading someone
    else's tree, which must never bring a store into existence and then
    report it as an empty project.
    """
    return (memory_store_dir(root) / "index.json").is_file()


def store_memory_ids(root) -> List[str]:
    """Every memory_id the store at `root` indexes.

    Read from index.json directly rather than through MemoryStore, so an
    identity probe on an unregistered/foreign root stays a pure read: this is
    the one place that must not risk creating the very store it is checking.
    The file is MemoryStore's own index, not a second index of our own.
    """
    index_file = memory_store_dir(root) / "index.json"
    if not index_file.is_file():
        return []
    try:
        rows = json.loads(index_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    ids = set()
    for row in rows if isinstance(rows, list) else []:
        mid = str((row or {}).get("memory_id") or "").strip()
        if mid:
            ids.add(mid)
    return sorted(ids)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

class ProjectRegistry:
    """The list of project roots a mining pass may read.

    Deliberately tiny and explicit: a project is in scope because a human
    registered it, never because it was discovered by walking a filesystem.
    Auto-discovery would make "which projects agree" depend on where the
    harness happened to be run from.
    """

    def __init__(self, host_root):
        self.host_root = Path(host_root).resolve()
        self.path = self.host_root / REGISTRY_RELPATH

    # -- persistence -------------------------------------------------------

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CrossProjectRegistryError(
                f"cross-project registry at {self.path} is not readable JSON: {exc}"
            ) from exc
        rows = data.get("projects") if isinstance(data, dict) else data
        return list(rows or [])

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "host_root": str(self.host_root),
            "projects": rows,
        }
        tmp = self.path.with_name(f"registry.json.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        # storage._atomic_replace, the same retrying replace memory.py's index
        # write and blackboard.py's atomic write already go through -- not a
        # second definition of "replace this file safely".
        _atomic_replace(str(tmp), self.path)

    def _event(self, event: Dict[str, Any]) -> None:
        try:
            StateStore(self.host_root).event(event)
        except OSError:
            # Best-effort, mirroring every other bookkeeping write in this
            # codebase: an audit-trail failure must not turn a completed
            # registry change into a crash.
            pass

    # -- operations --------------------------------------------------------

    def register(self, root, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Add one project root to the registry.

        Refuses, in this order:
          - a root that does not exist, or has no memory store to mine;
          - a project_id already registered;
          - a root path already registered;
          - a root whose store shares a memory_id with a registered one
            (ProjectIdentityCollisionError -- see the class docstring).
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise CrossProjectRegistryError(
                f"cannot register {root_path}: not a directory")
        if not has_memory_store(root_path):
            raise CrossProjectRegistryError(
                f"cannot register {root_path}: no memory store at "
                f"{memory_store_dir(root_path)} -- there is nothing to mine, and "
                "registering it would let an empty tree count as a project that "
                "agrees with nothing"
            )

        pid = str(project_id or root_path.name).strip()
        if not pid:
            raise CrossProjectRegistryError("project_id must be non-empty")

        rows = self.entries()
        for row in rows:
            if str(row.get("project_id")) == pid:
                raise CrossProjectRegistryError(
                    f"project_id {pid!r} is already registered at {row.get('root')}")
            if Path(str(row.get("root"))).resolve() == root_path:
                raise CrossProjectRegistryError(
                    f"{root_path} is already registered as {row.get('project_id')!r}")

        new_ids = set(store_memory_ids(root_path))
        for row in rows:
            shared = new_ids & set(store_memory_ids(row.get("root")))
            if shared:
                raise ProjectIdentityCollisionError(
                    f"cannot register {root_path} as {pid!r}: its memory store shares "
                    f"{len(shared)} memory_id(s) with already-registered project "
                    f"{row.get('project_id')!r} (e.g. {sorted(shared)[0]}), so the two "
                    "are one store under two names. Registering it would manufacture a "
                    "cross-project agreement out of a single project's audit trail."
                )

        entry = {
            "project_id": pid,
            "root": str(root_path),
            "registered_at": time.time(),
            "indexed_record_count": len(new_ids),
        }
        rows.append(entry)
        self._save(rows)
        self._event({
            "ts": time.time(),
            "type": EVENT_REGISTER,
            "project_id": pid,
            "root": str(root_path),
            "indexed_record_count": len(new_ids),
            "registered_total": len(rows),
        })
        return entry

    def unregister(self, project_id: str) -> bool:
        rows = self.entries()
        kept = [r for r in rows if str(r.get("project_id")) != str(project_id)]
        if len(kept) == len(rows):
            return False
        self._save(kept)
        self._event({
            "ts": time.time(),
            "type": EVENT_UNREGISTER,
            "project_id": str(project_id),
            "registered_total": len(kept),
        })
        return True

    def roots(self) -> List[Dict[str, Any]]:
        """(project_id, root) pairs in registration order."""
        return [{"project_id": str(r.get("project_id")), "root": str(r.get("root"))}
                for r in self.entries()]


# --------------------------------------------------------------------------
# Mining
# --------------------------------------------------------------------------

def project_failure_index(root) -> Dict[str, Any]:
    """One project's failure signatures and its gate-verified closures.

    Job Memory `job_failure` records grouped by `evidence_db.signature_key()`,
    each carrying the memory_ids and the INDEPENDENT RUN identities behind it
    (`capability_evolution._run_identity()`), plus the normalized claim texts
    this project's Engineering Memory `verified_fix` records name.

    A pure read. Never constructs a MemoryStore for a root that has none.
    """
    from .evidence_db import signature_key
    from .memory import MemoryStore

    root_path = Path(root).resolve()
    if not has_memory_store(root_path):
        return {"root": str(root_path), "readable": False,
                "skipped_reason": SKIP_NO_MEMORY_STORE,
                "signatures": {}, "resolved_claims": []}

    store = MemoryStore(root_path)
    signatures: Dict[str, Dict[str, Any]] = {}
    for record in store.find("job", kind=REPEAT_FAILURE_JOB_MEMORY_KIND):
        signature = record.get("failure_signature")
        if not isinstance(signature, dict):
            continue
        key = signature_key(signature)
        group = signatures.setdefault(key, {
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

    resolved = set(resolved_failure_claim_texts(root_path))
    for group in signatures.values():
        group["memory_ids"] = sorted(group["memory_ids"])
        group["run_identities"] = sorted(group["run_identities"])
        group["occurrence_count"] = len(group["memory_ids"])
        group["independent_run_count"] = len(group["run_identities"])
        group["resolution_claims"] = failure_resolution_claims(group["failure_signature"])
        group["resolved_by_verified_fix"] = sorted(
            set(group["resolution_claims"]) & resolved)

    return {
        "root": str(root_path),
        "readable": True,
        "skipped_reason": None,
        "signatures": signatures,
        "resolved_claims": sorted(resolved),
    }


def verified_fix_records(root) -> List[Dict[str, Any]]:
    """This project's gate-verified closures, with the claim texts that make a
    fix joinable to another project's open failure.

    `verified_fix` and nothing else, for `capability_evolution`'s own reason:
    `engine._promote_verified_fix_knowledge()` writes it exactly once, on a
    RE_AUDIT verdict whose effectiveness AND non-regression gates both
    cleared. A bare `root_cause` or `debug_lesson` is an explanation, and
    offering an explanation to another project as a transferable FIX would be
    the expensive error.
    """
    from .memory import MemoryStore

    root_path = Path(root).resolve()
    if not has_memory_store(root_path):
        return []
    out = []
    for record in MemoryStore(root_path).find(
            "engineering", kind=RESOLVING_ENGINEERING_MEMORY_KIND):
        claims = set()
        for value in [record.get("root_cause")] + list(record.get("symptoms") or []):
            text = _norm_text(value)
            if text:
                claims.add(text)
        out.append({
            "memory_id": record.get("memory_id"),
            "title": record.get("title"),
            "root_cause": record.get("root_cause"),
            "claims": sorted(claims),
            "confidence": record.get("confidence"),
            "confirmation_count": record.get("confirmation_count", 0),
        })
    return out


def _dedupe_roots(projects: Sequence[Dict[str, Any]]) -> tuple:
    """Drop any root that is a store already being mined under another name.

    Re-checked here and not only in ProjectRegistry.register() because the
    registry file is editable text and mine_cross_project_patterns() also
    accepts roots passed directly. The FIRST occurrence is kept and every
    later collider is excluded with its reason recorded, so a mining report
    can never silently double-count one store.
    """
    kept: List[Dict[str, Any]] = []
    collisions: List[Dict[str, Any]] = []
    seen_ids: List[tuple] = []  # (project_id, set-of-memory-ids)
    for proj in projects:
        pid = str(proj.get("project_id"))
        root = Path(str(proj.get("root"))).resolve()
        ids = set(store_memory_ids(root))
        collided_with = None
        for other_pid, other_ids in seen_ids:
            if ids and (ids & other_ids):
                collided_with = other_pid
                break
        if collided_with is not None:
            collisions.append({
                "project_id": pid, "root": str(root),
                "collides_with": collided_with,
                "reason": ("shares memory_ids with an already-mined project -- one "
                           "store under two names is one project, not two"),
            })
            continue
        seen_ids.append((pid, ids))
        kept.append({"project_id": pid, "root": str(root)})
    return kept, collisions


def promotion_readiness(pattern: Dict[str, Any]) -> Dict[str, Any]:
    """What a cross-project pattern would still need to become Organizational
    Memory -- computed, never acted on.

    This function mints nothing and writes nothing. The ONLY path from here
    into the organizational tier is a human running
    `memory_router.promote_to_organizational()` on a real Engineering Memory
    record, whose three gates (gate-validated verification shape, HIGH
    `inference.score_confidence()`, `confirmation_count >=
    ORGANIZATIONAL_MIN_CONFIRMATIONS`) and whose
    `organizational_admission_gate()` re-check are untouched by this module.
    A recurrence count is evidence FOR opening that review, not a substitute
    for it.
    """
    blocking: List[str] = []
    if pattern.get("project_count", 0) < CROSS_PROJECT_MIN_PROJECTS:
        blocking.append(
            f"fewer than {CROSS_PROJECT_MIN_PROJECTS} distinct projects recorded it")
    if not pattern.get("resolved_in_projects"):
        blocking.append(
            "no project has a gate-verified verified_fix closing it -- an open "
            "recurring failure is a question, not knowledge to share")
    if not pattern.get("transferable_fix"):
        blocking.append(
            "no project still has it open, so there is no transfer to make")
    return {
        "eligible_for_promotion_review": not blocking,
        "blocking": blocking,
        "promotion_path": (
            "memory_router.promote_to_organizational() on a real Engineering "
            "Memory record, by a human. This miner never promotes."),
    }


def mine_cross_project_patterns(
    projects: Sequence[Dict[str, Any]],
    *,
    min_projects: int = CROSS_PROJECT_MIN_PROJECTS,
) -> Dict[str, Any]:
    """Recurring root-cause/fix patterns across N projects' memory stores.

    `projects` is a sequence of {"project_id", "root"} -- e.g.
    `ProjectRegistry(root).roots()`. A pure read: nothing is written to any
    memory tier, no candidate is filed, no approval is minted.

    Every returned pattern carries the whole basis of the finding -- the
    signature, which projects recorded it, each project's memory_ids and
    independent run identities, which projects closed it with a verified_fix
    and which still have it open -- so a reader re-derives the conclusion by
    hand instead of trusting a count.

    `transferable_fix` is the finding that only exists at this level: a
    gate-verified fix in project A for a signature project B still has open.
    """
    min_projects = int(min_projects)
    if min_projects < 2:
        raise ValueError(
            f"min_projects must be at least 2, got {min_projects}: one project "
            "recording a failure repeatedly is a single-project pattern, which "
            "capability_evolution.repeated_unresolved_failure_patterns() already "
            "reports -- calling it a cross-project pattern would be a false claim "
            "about how widely it was observed"
        )

    mineable, collisions = _dedupe_roots(projects)

    project_reports: List[Dict[str, Any]] = []
    indexes: Dict[str, Dict[str, Any]] = {}
    fixes: Dict[str, List[Dict[str, Any]]] = {}
    for proj in mineable:
        pid, root = proj["project_id"], proj["root"]
        index = project_failure_index(root)
        indexes[pid] = index
        fixes[pid] = verified_fix_records(root) if index["readable"] else []
        project_reports.append({
            "project_id": pid,
            "root": root,
            "readable": index["readable"],
            "skipped_reason": index["skipped_reason"],
            "failure_signature_count": len(index["signatures"]),
            "verified_fix_count": len(fixes[pid]),
        })
    for coll in collisions:
        project_reports.append({
            "project_id": coll["project_id"],
            "root": coll["root"],
            "readable": False,
            "skipped_reason": SKIP_IDENTITY_COLLISION,
            "collides_with": coll["collides_with"],
            "failure_signature_count": 0,
            "verified_fix_count": 0,
        })

    contributing = [p for p in project_reports if p["readable"]]

    # Group across projects. The unit of independence is the project id.
    groups: Dict[str, Dict[str, Any]] = {}
    for pid, index in indexes.items():
        if not index["readable"]:
            continue
        for key, group in index["signatures"].items():
            entry = groups.setdefault(key, {
                "signature_key": key,
                "failure_signature": group["failure_signature"],
                "per_project": {},
            })
            entry["per_project"][pid] = {
                "memory_ids": group["memory_ids"],
                "run_identities": group["run_identities"],
                "occurrence_count": group["occurrence_count"],
                "independent_run_count": group["independent_run_count"],
                "resolved_by_verified_fix": group["resolved_by_verified_fix"],
            }

    cross: List[Dict[str, Any]] = []
    single: List[Dict[str, Any]] = []
    for key in sorted(groups):
        entry = groups[key]
        pids = sorted(entry["per_project"])
        signature = entry["failure_signature"]
        claims = failure_resolution_claims(signature)
        resolved_in = [p for p in pids if entry["per_project"][p]["resolved_by_verified_fix"]]
        unresolved_in = [p for p in pids if not entry["per_project"][p]["resolved_by_verified_fix"]]

        transferable = None
        if resolved_in and unresolved_in:
            sources = []
            for p in resolved_in:
                for fix in fixes.get(p, []):
                    if set(fix["claims"]) & set(claims):
                        sources.append({"project_id": p, **fix})
            if sources:
                transferable = {
                    "matched_claims": claims,
                    "fixed_in": sorted({s["project_id"] for s in sources}),
                    "open_in": unresolved_in,
                    "fix_records": sources,
                }

        pattern = {
            "signature_key": key,
            "failure_signature": signature,
            "summary": _failure_signature_summary(signature),
            "project_count": len(pids),
            "project_ids": pids,
            "per_project": entry["per_project"],
            "total_occurrence_count": sum(
                v["occurrence_count"] for v in entry["per_project"].values()),
            "total_independent_run_count": sum(
                v["independent_run_count"] for v in entry["per_project"].values()),
            "resolution_claims": claims,
            "resolved_in_projects": resolved_in,
            "unresolved_in_projects": unresolved_in,
            "transferable_fix": transferable,
            "min_projects": min_projects,
        }
        pattern["promotion_readiness"] = promotion_readiness(pattern)
        if len(pids) >= min_projects:
            cross.append(pattern)
        else:
            # Reported, never silently dropped: "seen in one project only" is
            # a real, different finding, and hiding it would make an
            # empty cross-project result look like an absence of failures.
            single.append(pattern)

    cross.sort(key=lambda p: (-p["project_count"], p["signature_key"]))
    single.sort(key=lambda p: p["signature_key"])

    status = (STATUS_OK if len(contributing) >= min_projects
              else STATUS_INSUFFICIENT_PROJECTS)
    return {
        "status": status,
        "min_projects": min_projects,
        "projects": project_reports,
        "projects_mined": len(contributing),
        "identity_collisions": collisions,
        "cross_project_patterns": cross if status == STATUS_OK else [],
        "single_project_patterns": single,
        "transferable_fix_count": sum(
            1 for p in (cross if status == STATUS_OK else []) if p["transferable_fix"]),
        "disclosure": (
            f"{len(contributing)} project memory store(s) contributed; "
            f"{min_projects} distinct projects are required before any signature is "
            "reported as a cross-project pattern. This is a pure read: no memory "
            "record was written, no capability candidate filed, and nothing was "
            "promoted to Organizational Memory."
            if status == STATUS_OK else
            f"only {len(contributing)} project memory store(s) contributed, fewer than "
            f"the {min_projects} distinct projects a cross-project claim requires, so "
            "NO cross-project pattern is reported. This is the honest answer about the "
            "SAMPLE, not a finding that the projects share no failures."
        ),
    }


def mine_registered_projects(host_root, *,
                             min_projects: int = CROSS_PROJECT_MIN_PROJECTS
                             ) -> Dict[str, Any]:
    """Mine every project in `host_root`'s registry and record that the pass
    happened in the one real events.jsonl.

    The mining itself stays a pure read of the MINED projects; the single
    write is one audit event in the HOST project, exactly as
    capability_evolution's auto-discovery records every outcome including
    "nothing qualified" -- a pass on which nothing qualified is itself
    citable evidence.
    """
    registry = ProjectRegistry(host_root)
    report = mine_cross_project_patterns(registry.roots(), min_projects=min_projects)
    report["host_root"] = str(Path(host_root).resolve())
    report["registered_project_count"] = len(registry.entries())
    try:
        StateStore(Path(host_root).resolve()).event({
            "ts": time.time(),
            "type": EVENT_MINE,
            "status": report["status"],
            "registered_project_count": report["registered_project_count"],
            "projects_mined": report["projects_mined"],
            "cross_project_pattern_count": len(report["cross_project_patterns"]),
            "transferable_fix_count": report["transferable_fix_count"],
            "identity_collision_count": len(report["identity_collisions"]),
        })
    except OSError:
        pass
    return report


def production_status(host_root) -> Dict[str, Any]:
    """Whether this installation can produce a REAL cross-project result yet.

    Exists so the answer to "has this ever found anything in production?" is a
    computed fact rather than a claim in a report. In this repository it
    answers no: one project, one memory store, and no second real project to
    mine -- the same disclosure CLAUDE.md's Environment Generation Mode makes
    about this repo having no RTL tree of its own.
    """
    registry = ProjectRegistry(host_root)
    entries = registry.entries()
    readable = [e for e in entries if has_memory_store(e.get("root"))]
    return {
        "host_root": str(Path(host_root).resolve()),
        "registry_path": str(registry.path),
        "registered_project_count": len(entries),
        "registered_with_readable_store": len(readable),
        "min_projects": CROSS_PROJECT_MIN_PROJECTS,
        "can_produce_cross_project_result": len(readable) >= CROSS_PROJECT_MIN_PROJECTS,
        "disclosure": (
            "The mechanism is real and tested against multiple separately-constructed "
            "memory stores, but a cross-project FINDING requires "
            f"{CROSS_PROJECT_MIN_PROJECTS} genuinely independent registered projects; "
            f"{len(readable)} is registered here. Registering one store twice is "
            "refused by ProjectIdentityCollisionError, so this number cannot be "
            "inflated to manufacture a production-looking result."
        ),
    }
