"""dv_harness/phy_revision_staleness.py -- the PHY-revision re-architect
trigger (2026-09-07, targeted_hardening item phy_revision_rearchitect_trigger).

THE GAP THIS CLOSES
--------------------
`dv_harness/phy_boundary.py` computes ONE PHY<->controller boundary/bind-
location decision per call, and its own module docstring says so plainly:
it is stateless. Nothing in this repo asked the follow-up question a real
bind/architecture decision needs answered LATER: has the PHY module's real
RTL changed since that decision was made, such that the decision -- a real
`bind_decision` inside a `phy_boundary.json` document, or a real, human-
decided `kind="architecture_decision"` record in Project Memory
(`memory_router.ARCHITECTURE_DECISION_KIND`) -- needs re-evaluation.

This module is that missing diff/versioning layer. It is deliberately built
ON TOP of `phy_boundary.py` rather than inside it: `phy_boundary.py` is
imported nowhere by this module (this module never re-derives a boundary
classification or a bind-location decision -- that stays entirely
`phy_boundary.py`'s own job), matching the precedent
`phy_model_behavior_ir.py`/`dynamic_connectivity_ir.py`/
`architecture_choice_ranking.py` already set for extending that module's
family without editing the file itself, which keeps this addition's blast
radius to one new file in a session where many other items may be touching
`phy_boundary.py`'s own neighbourhood concurrently.

REUSE OVER REINVENT -- THREE REAL PRIMITIVES, NOT A FOURTH HASHER
--------------------------------------------------------------------
1. **Which real file(s) declare the PHY module** is read off the SAME
   verible-parsed `dut_facts.rtl.files[]` shape `phy_boundary.py` itself
   consumes (`file_path` + `modules[].name`, `env_manifest.py`'s own real
   artifact) -- never a second RTL parse and never a filename guess.
2. **The content fingerprint** reuses `env_manifest.file_ref()` -- the same
   public sha256-of-file primitive `dependency_supply_chain.py` and
   `coverage_db_integrity.py` already reuse -- combined via
   `connectivity_check.compute_rtl_fingerprint()`'s own scheme (sorted
   relative path + digest folded into one sha256, `path \\0 digest \\n`),
   scoped down to only the file(s) that actually declare the PHY module
   rather than a project's whole `rtl_sources` glob set. An empty or
   entirely-missing file set is honestly NOT_AVAILABLE, never a vacuous
   constant fingerprint that would compare equal forever -- the identical
   anti-vacuous-fingerprint rule `connectivity_check.run_connectivity_check()`
   already enforces for its own RTL source set.
3. **Flagging an EXISTING decision as needing re-evaluation** reuses, for a
   `kind="architecture_decision"` Project Memory record, the real,
   already-tested `memory.MemoryGC.flag_stale()` -- the SAME mechanism this
   project's own CLAUDE.md documents for "needing revalidation... it has
   aged past `knowledge_center.max_age_days`" or "a related-but-not-
   identical record now conflicts with it", applied here to a THIRD real
   trigger: the PHY module's own real RTL content moved. This module never
   builds a second flagging/status mechanism for memory-tier records.
   `MemoryStore` is constructed only when `cross_project_mining.
   has_memory_store()` already confirms a real store exists -- never minted
   merely by asking whether a decision needs re-evaluation.

A `phy_boundary.json` bind decision has no such mutation mechanism (it is a
GENERATED, stateless artifact `phy_boundary.py` regenerates wholesale) --
this module never edits one. For that decision kind, "flagging" means an
honest, real evaluation result naming the change and the real re-extraction
command a human/agent should run, mirroring `connectivity_check.py`'s own
`--check-only` contract: report staleness, mutate nothing, exit nonzero.

TWO DECISION KINDS, ONE RECORD SHAPE
--------------------------------------
A `PhyRevisionDecisionRecord` (`build_phy_revision_decision_record()`,
persisted under `.dv-harness/phy_revision_decisions/<decision_id>.json`)
carries the PHY module name, the real file(s) that declare it, and the
real fingerprint computed from those files AT THE MOMENT the decision was
recorded, plus a caller-declared `decision_ref` naming what the decision
actually is:

  - `{"kind": "phy_boundary_bind", ...}` -- a `phy_boundary.json` bind
    decision. `flag_stale_phy_revision_decision()` never mutates it; it
    reports `NEEDS_REVALIDATION_REPORTED_ONLY` naming the real re-extraction
    step.
  - `{"kind": "architecture_decision", "memory_id": "..."}` -- a real
    Project Memory `architecture_decision` record. A stale evaluation calls
    `MemoryGC.flag_stale()` on that exact record, which is the real,
    checkable mutation this task asks for.

Neither kind is invented content: this module never authors what the
decision itself says, only whether the real PHY RTL it was made against has
since moved.

FOUR HONEST STALENESS STATUSES, NEVER TWO COLLAPSED INTO ONE
-----------------------------------------------------------------
`UP_TO_DATE` (recomputed now == recorded), `PHY_RTL_CHANGED` (a real,
proven content difference), `PHY_SOURCE_FILES_UNAVAILABLE` (the declared
source file(s) could not be re-hashed right now -- moved, deleted, or an
unreadable project root; "we could not check" is never silently read as
"unchanged"), `RECORD_MISSING_FINGERPRINT` (a malformed/hand-edited
record). `needs_reevaluation` is False ONLY for `UP_TO_DATE` -- the same
"an unresolved unknown outranks a clean 'not stale'" discipline
`loop_stale_detection.py`/`intake_contract_stale_detection.py` already
apply one layer over: a decision this module could not re-check is treated
as needing a human's attention, never quietly trusted.

DELIBERATELY BOUNDED
----------------------
This module decides, approves and arbitrates nothing beyond its own
staleness evaluation and the one real `MemoryGC.flag_stale()` write it may
perform: no build, job, or approval is touched, and there is deliberately
no `STAGE_GATES` entry -- a gate that passed because a bind/architecture
decision was never re-checked against moved RTL would be worse than none.
No `dv-harness` CLI verb was added and `cli.py`/`gates.py`/`dashboard.py`
were not touched, per this task's own instruction; the front door is
`python -m dv_harness.phy_revision_staleness`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import env_manifest
from . import cross_project_mining
from . import memory_router
from .memory import MemoryGC, MemoryStore
from .storage import _atomic_replace

SCHEMA_VERSION = "1.0"

DECISIONS_DIR_PARTS = (".dv-harness", "phy_revision_decisions")

# --- staleness statuses (never collapsed into two) --------------------------
STATUS_UP_TO_DATE = "UP_TO_DATE"
STATUS_PHY_RTL_CHANGED = "PHY_RTL_CHANGED"
STATUS_PHY_SOURCE_FILES_UNAVAILABLE = "PHY_SOURCE_FILES_UNAVAILABLE"
STATUS_RECORD_MISSING_FINGERPRINT = "RECORD_MISSING_FINGERPRINT"
STALENESS_STATUSES = (
    STATUS_UP_TO_DATE, STATUS_PHY_RTL_CHANGED,
    STATUS_PHY_SOURCE_FILES_UNAVAILABLE, STATUS_RECORD_MISSING_FINGERPRINT,
)

# --- flag outcomes ------------------------------------------------------
FLAG_UP_TO_DATE = "UP_TO_DATE_NO_FLAG_NEEDED"
FLAG_FLAGGED = "FLAGGED_NEEDS_REVALIDATION"
FLAG_REPORTED_ONLY = "NEEDS_REVALIDATION_REPORTED_ONLY"
FLAG_SKIPPED_NO_MEMORY_STORE = "FLAG_SKIPPED_NO_MEMORY_STORE"
FLAG_SKIPPED_RECORD_NOT_FOUND = "FLAG_SKIPPED_MEMORY_RECORD_NOT_FOUND"
FLAG_SKIPPED_KIND_MISMATCH = "FLAG_SKIPPED_DECISION_REF_KIND_MISMATCH"
FLAG_SKIPPED_MISSING_MEMORY_ID = "FLAG_SKIPPED_DECISION_REF_MISSING_MEMORY_ID"
FLAG_SKIPPED_UNKNOWN_KIND = "FLAG_SKIPPED_UNKNOWN_DECISION_REF_KIND"

#: The two decision_ref.kind values this module recognizes. An unrecognized
#: kind is never silently treated as one of these two -- see
#: FLAG_SKIPPED_UNKNOWN_KIND.
DECISION_REF_KIND_PHY_BOUNDARY_BIND = "phy_boundary_bind"
DECISION_REF_KIND_ARCHITECTURE_DECISION = "architecture_decision"
DECISION_REF_KINDS = (DECISION_REF_KIND_PHY_BOUNDARY_BIND, DECISION_REF_KIND_ARCHITECTURE_DECISION)


class PhyRevisionStalenessError(ValueError):
    """Raised for a malformed input this module refuses to act on -- never
    for a real staleness finding (that is a report field, not an
    exception), mirroring CoverageDbIntegrityError's reason/detail shape."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# (1) which real file(s) declare the PHY module -- structural evidence only
# ---------------------------------------------------------------------------

def _normalize_rtl_files(rtl_modules: Any) -> List[dict]:
    """Accept the same three input shapes `phy_boundary.py`'s own consumers
    already use: a full env.manifest.json dict (has `dut_facts`), a
    `dut_facts.rtl`-shaped dict (has `files`), or a bare list of file
    entries (each `{"file_path": ..., "modules": [...]}`, `verible_parser.
    to_dict()`'s own real shape). This module re-parses nothing; it only
    reads whichever of these three already-real shapes it was handed."""
    if isinstance(rtl_modules, dict):
        if "dut_facts" in rtl_modules:
            rtl_modules = ((rtl_modules.get("dut_facts") or {}).get("rtl") or {}).get("files") or []
        elif "files" in rtl_modules:
            rtl_modules = rtl_modules.get("files") or []
        else:
            rtl_modules = [rtl_modules]
    out: List[dict] = []
    for entry in rtl_modules or []:
        if isinstance(entry, dict) and entry.get("file_path"):
            out.append(entry)
    return out


def derive_phy_module_files(rtl_modules: Any, phy_module: str) -> List[str]:
    """Every real, already-parsed RTL file that declares a module named
    `phy_module`, sorted. Structural evidence (a module name a real verible
    parse actually found inside that file) -- never a filename-similarity
    guess. Returns [] honestly when no supplied file declares it, which is
    the anti-fabrication case a caller must check before trusting a
    fingerprint built from this list."""
    if not phy_module or not str(phy_module).strip():
        raise PhyRevisionStalenessError(
            "PHY_MODULE_NOT_DECLARED",
            {"reason": "phy_module is required and must be a non-empty module name"},
        )
    entries = _normalize_rtl_files(rtl_modules)
    matches = set()
    for entry in entries:
        for m in (entry.get("modules") or []):
            if isinstance(m, dict) and m.get("name") == phy_module:
                matches.add(entry["file_path"])
    return sorted(matches)


# ---------------------------------------------------------------------------
# (2) content fingerprint -- fresh from disk, reusing env_manifest.file_ref()
# ---------------------------------------------------------------------------

def _relativize(path_str: str, root: Path) -> str:
    p = Path(path_str)
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def compute_phy_module_fingerprint(project_root: Any, phy_module_source_files: Sequence[str]) -> dict:
    """Content fingerprint of the PHY module's real declaring file(s),
    RE-HASHED from disk right now (never trusted from a prior record) --
    the same "recompute and compare against a prior claim" contract
    `connectivity_check.py`'s own RTL staleness trigger uses, scoped down to
    exactly the file(s) that declare this one PHY module.

    Reuses `env_manifest.file_ref()` (the public sha256-of-file helper
    `dependency_supply_chain.py`/`coverage_db_integrity.py` already reuse)
    and `connectivity_check.compute_rtl_fingerprint()`'s own combination
    scheme (sorted relative path + digest folded into one sha256) -- there
    is one definition of "combine per-file digests into a fingerprint" in
    this codebase, not a second one minted here.

    An empty file list, or every declared file missing from disk, is
    honestly NOT_AVAILABLE -- never a vacuous constant fingerprint that
    would compare equal forever, mirroring
    `connectivity_check.run_connectivity_check()`'s own refusal to
    fingerprint an empty rtl_sources match."""
    root = Path(project_root).resolve()
    files = sorted({str(f) for f in (phy_module_source_files or []) if f})
    if not files:
        return {"status": "NOT_AVAILABLE",
                "reason": "no PHY module source file(s) declared -- nothing to fingerprint",
                "fingerprint": None, "file_count": 0, "files": {}, "missing_files": []}
    present: List[tuple] = []
    missing: List[str] = []
    for f in files:
        p = Path(f)
        if not p.is_absolute():
            p = root / p
        if p.is_file():
            present.append((f, p))
        else:
            missing.append(f)
    if not present:
        return {"status": "NOT_AVAILABLE",
                "reason": f"none of the declared PHY module source file(s) exist on disk: {files}",
                "fingerprint": None, "file_count": 0, "files": {}, "missing_files": missing}
    h = hashlib.sha256()
    per_file: Dict[str, str] = {}
    for orig, p in sorted(present, key=lambda t: t[0]):
        rel = _relativize(orig, root)
        digest = env_manifest.file_ref(p)["sha256"]
        per_file[rel] = digest
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    result = {"status": "COMPUTED", "reason": None,
              "fingerprint": h.hexdigest(), "file_count": len(present), "files": per_file,
              "missing_files": missing}
    return result


# ---------------------------------------------------------------------------
# decision record: build, persist, list, load
# ---------------------------------------------------------------------------

def _decision_id(phy_module: str, files: Sequence[str], fingerprint: str) -> str:
    material = f"{phy_module}\n" + "\n".join(sorted(files)) + f"\n{fingerprint}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _validate_decision_ref(decision_ref: Any) -> dict:
    if not isinstance(decision_ref, dict) or not str(decision_ref.get("kind") or "").strip():
        raise PhyRevisionStalenessError(
            "DECISION_REF_MISSING_KIND",
            {"reason": "decision_ref must be a dict carrying a non-empty 'kind' naming what real "
                        "decision this record tracks",
             "decision_ref": decision_ref})
    kind = decision_ref["kind"]
    if kind == DECISION_REF_KIND_ARCHITECTURE_DECISION and not str(decision_ref.get("memory_id") or "").strip():
        raise PhyRevisionStalenessError(
            "DECISION_REF_MISSING_MEMORY_ID",
            {"reason": f"decision_ref.kind={kind!r} requires a real 'memory_id' naming the "
                        "Project Memory architecture_decision record this tracks",
             "decision_ref": decision_ref})
    return decision_ref


def build_phy_revision_decision_record(project_root: Any, phy_module: str, rtl_modules: Any,
                                        decision_ref: dict, *,
                                        decision_id: Optional[str] = None) -> dict:
    """Build (never persist) a PhyRevisionDecisionRecord: the PHY module's
    real declaring file(s), the real fingerprint of their content AT THIS
    MOMENT, and a caller-declared pointer to the real decision this record
    tracks. Raises rather than recording a null baseline when the PHY
    module cannot be located in the supplied RTL evidence or its
    fingerprint cannot be computed -- mirroring `intake_baseline.
    freeze_intake_baseline()`'s / `signoff_export.
    freeze_signoff_baseline()`'s refusal to freeze bad input."""
    decision_ref = _validate_decision_ref(decision_ref)
    files = derive_phy_module_files(rtl_modules, phy_module)
    if not files:
        raise PhyRevisionStalenessError(
            "PHY_MODULE_NOT_FOUND_IN_RTL",
            {"phy_module": phy_module,
             "reason": f"no real parsed RTL file declares a module named {phy_module!r}; a bind/"
                        "architecture decision cannot be fingerprinted against RTL this project's "
                        "own parse never located"})
    fp = compute_phy_module_fingerprint(project_root, files)
    if fp["status"] != "COMPUTED":
        raise PhyRevisionStalenessError(
            "PHY_MODULE_FINGERPRINT_NOT_COMPUTABLE",
            {"phy_module": phy_module, "reason": fp["reason"], "declared_files": files})
    record = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id or _decision_id(phy_module, list(fp["files"]), fp["fingerprint"]),
        "recorded_at": _now_iso(),
        "phy_module": phy_module,
        "phy_module_source_files": sorted(fp["files"]),
        "fingerprint_at_decision": fp["fingerprint"],
        "fingerprint_files_at_decision": fp["files"],
        "decision_ref": decision_ref,
    }
    return record


def decisions_dir(root: Any) -> Path:
    return Path(root).joinpath(*DECISIONS_DIR_PARTS)


def save_phy_revision_decision_record(root: Any, record: dict) -> Path:
    """Persist a decision record to `.dv-harness/phy_revision_decisions/
    <decision_id>.json`, atomically, and nothing else."""
    root = Path(root).resolve()
    if not record.get("decision_id"):
        raise PhyRevisionStalenessError(
            "RECORD_MISSING_DECISION_ID", {"record": record})
    ddir = decisions_dir(root)
    ddir.mkdir(parents=True, exist_ok=True)
    path = ddir / f"{record['decision_id']}.json"
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, dir=str(ddir), encoding="utf-8")
    try:
        json.dump(record, tmp, indent=2, sort_keys=True)
        tmp.close()
        _atomic_replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            Path(tmp.name).unlink()
        except FileNotFoundError:
            pass
        raise
    return path


def record_phy_revision_decision(project_root: Any, phy_module: str, rtl_modules: Any,
                                  decision_ref: dict, *, decision_id: Optional[str] = None) -> dict:
    """Build and persist one PhyRevisionDecisionRecord in a single call --
    the normal write path a caller (e.g. immediately after saving a real
    `phy_boundary.json`, or immediately after recording a real
    `architecture_decision` memory record) uses."""
    root = Path(project_root).resolve()
    record = build_phy_revision_decision_record(
        root, phy_module, rtl_modules, decision_ref, decision_id=decision_id)
    save_phy_revision_decision_record(root, record)
    return record


def list_phy_revision_decisions(root: Any) -> List[dict]:
    """Every real persisted decision record for this project, sorted by
    `decision_id` for a stable order. An unreadable/malformed file is
    skipped rather than crashing the whole listing -- a corrupt record
    should not hide every OTHER real, valid decision from a staleness
    scan."""
    ddir = decisions_dir(root)
    if not ddir.is_dir():
        return []
    out = []
    for p in sorted(ddir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_phy_revision_decision_record(root: Any, decision_id: str) -> Optional[dict]:
    p = decisions_dir(root) / f"{decision_id}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# staleness evaluation -- re-derived on every call, never trusted from disk
# ---------------------------------------------------------------------------

def evaluate_phy_revision_staleness(record: dict, project_root: Any) -> dict:
    """The standing trigger. Re-hashes the PHY module's real declaring
    file(s) fresh from disk and compares against the fingerprint recorded
    at decision time. `needs_reevaluation` is False ONLY for
    STATUS_UP_TO_DATE -- an unresolvable current fingerprint is treated as
    needing a human's attention, never silently trusted as unchanged."""
    record = record or {}
    recorded_fp = record.get("fingerprint_at_decision")
    files = record.get("phy_module_source_files") or []
    if not recorded_fp:
        return {"status": STATUS_RECORD_MISSING_FINGERPRINT, "needs_reevaluation": True,
                "detail": "the supplied decision record carries no recorded "
                           "fingerprint_at_decision -- cannot compare against current PHY RTL "
                           "content",
                "recorded_fingerprint": None, "current_fingerprint": None}
    current = compute_phy_module_fingerprint(project_root, files)
    if current["status"] != "COMPUTED":
        return {"status": STATUS_PHY_SOURCE_FILES_UNAVAILABLE, "needs_reevaluation": True,
                "detail": current["reason"],
                "recorded_fingerprint": recorded_fp, "current_fingerprint": None}
    if current["fingerprint"] != recorded_fp:
        return {"status": STATUS_PHY_RTL_CHANGED, "needs_reevaluation": True,
                "detail": (
                    f"PHY module {record.get('phy_module')!r}'s real RTL content changed since "
                    f"this decision was recorded: recorded {recorded_fp[:12]}... != current "
                    f"{current['fingerprint'][:12]}..."
                ),
                "recorded_fingerprint": recorded_fp, "current_fingerprint": current["fingerprint"]}
    return {"status": STATUS_UP_TO_DATE, "needs_reevaluation": False,
            "detail": "PHY module RTL content is unchanged since this decision was recorded",
            "recorded_fingerprint": recorded_fp, "current_fingerprint": current["fingerprint"]}


# ---------------------------------------------------------------------------
# flagging -- the real mutation, reusing MemoryGC.flag_stale() for a memory
# record, an honest report-only result for a stateless phy_boundary.json
# ---------------------------------------------------------------------------

def flag_stale_phy_revision_decision(record: dict, project_root: Any, *,
                                      evaluation: Optional[dict] = None) -> dict:
    """Flags `record`'s referenced decision as needing re-evaluation when
    (and only when) `evaluate_phy_revision_staleness()` says so. Never
    mints a `MemoryStore` merely to check -- `cross_project_mining.
    has_memory_store()` is checked first, so a project with no memory tree
    is never given one by asking whether a decision needs re-evaluation."""
    evaluation = evaluation if evaluation is not None else evaluate_phy_revision_staleness(record, project_root)
    if not evaluation.get("needs_reevaluation"):
        return {"outcome": FLAG_UP_TO_DATE, "evaluation": evaluation}

    decision_ref = (record or {}).get("decision_ref") or {}
    kind = decision_ref.get("kind")

    if kind == DECISION_REF_KIND_ARCHITECTURE_DECISION:
        memory_id = decision_ref.get("memory_id")
        if not memory_id:
            return {"outcome": FLAG_SKIPPED_MISSING_MEMORY_ID, "evaluation": evaluation}
        root = Path(project_root).resolve()
        if not cross_project_mining.has_memory_store(root):
            return {"outcome": FLAG_SKIPPED_NO_MEMORY_STORE, "evaluation": evaluation,
                    "memory_id": memory_id}
        store = MemoryStore(root)
        mem = store.get(memory_id)
        if mem is None:
            return {"outcome": FLAG_SKIPPED_RECORD_NOT_FOUND, "evaluation": evaluation,
                    "memory_id": memory_id}
        if mem.get("kind") != memory_router.ARCHITECTURE_DECISION_KIND:
            return {"outcome": FLAG_SKIPPED_KIND_MISMATCH, "evaluation": evaluation,
                    "memory_id": memory_id, "found_kind": mem.get("kind")}
        ok = MemoryGC(store).flag_stale(memory_id, reason=evaluation["detail"])
        return {"outcome": FLAG_FLAGGED if ok else FLAG_SKIPPED_RECORD_NOT_FOUND,
                "evaluation": evaluation, "memory_id": memory_id}

    if kind == DECISION_REF_KIND_PHY_BOUNDARY_BIND:
        return {"outcome": FLAG_REPORTED_ONLY, "evaluation": evaluation,
                "next_action": (
                    "re-run dv_harness.phy_boundary.extract_phy_boundary() / "
                    "extract_from_env_manifest() against the current RTL and re-save "
                    "phy_boundary.json -- this module never mutates that generated document"
                ), "phy_boundary_path": decision_ref.get("path")}

    return {"outcome": FLAG_SKIPPED_UNKNOWN_KIND, "evaluation": evaluation,
            "decision_ref_kind": kind}


def scan_phy_revision_decisions(project_root: Any) -> dict:
    """Evaluate (and, where applicable, flag) every real persisted decision
    record for this project. Never a partial silent skip -- every recorded
    decision gets an evaluation and a flag outcome, including the honest
    outcomes for a decision this module could not check or could not
    flag."""
    root = Path(project_root).resolve()
    records = list_phy_revision_decisions(root)
    results = []
    stale_count = 0
    flagged_count = 0
    for rec in records:
        evaluation = evaluate_phy_revision_staleness(rec, root)
        flag = flag_stale_phy_revision_decision(rec, root, evaluation=evaluation)
        if evaluation["needs_reevaluation"]:
            stale_count += 1
        if flag["outcome"] == FLAG_FLAGGED:
            flagged_count += 1
        results.append({
            "decision_id": rec.get("decision_id"), "phy_module": rec.get("phy_module"),
            "decision_ref": rec.get("decision_ref"),
            "evaluation": evaluation, "flag": flag,
        })
    return {"decision_count": len(records), "stale_count": stale_count,
            "flagged_count": flagged_count, "decisions": results}


# ---------------------------------------------------------------------------
# front door -- no `dv-harness` CLI verb; standalone `python -m` only
# ---------------------------------------------------------------------------

EXIT_UP_TO_DATE = 0
EXIT_STALE = 1
EXIT_ERROR = 2


def _load_json_arg(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="phy-revision-staleness", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)

    p_fp = sub.add_parser("fingerprint",
                           help="Compute the real current content fingerprint of a PHY module's "
                                "declaring RTL file(s).")
    p_fp.add_argument("--project-root", required=True)
    p_fp.add_argument("--phy-module", required=True)
    p_fp.add_argument("--rtl-modules", required=True,
                       help="Path to a JSON file: env.manifest.json, a dut_facts.rtl dict, or a "
                            "bare list of {file_path, modules[]} entries.")

    p_rec = sub.add_parser("record",
                            help="Build and persist a real PhyRevisionDecisionRecord.")
    p_rec.add_argument("--project-root", required=True)
    p_rec.add_argument("--phy-module", required=True)
    p_rec.add_argument("--rtl-modules", required=True)
    p_rec.add_argument("--decision-ref", required=True,
                        help="Path to a JSON file: {\"kind\": \"phy_boundary_bind\"|"
                             "\"architecture_decision\", ...}")

    p_eval = sub.add_parser("evaluate",
                             help="Evaluate one real persisted decision record's staleness.")
    p_eval.add_argument("--project-root", required=True)
    p_eval.add_argument("--decision-id", required=True)
    p_eval.add_argument("--flag", action="store_true",
                         help="Also flag the decision (real memory-tier mutation for an "
                              "architecture_decision kind) if it is found stale.")

    p_scan = sub.add_parser("scan",
                             help="Evaluate (and flag) every real persisted decision record for "
                                  "this project.")
    p_scan.add_argument("--project-root", required=True)

    args = ap.parse_args(list(argv))

    try:
        if args.verb == "fingerprint":
            rtl_modules = _load_json_arg(args.rtl_modules)
            files = derive_phy_module_files(rtl_modules, args.phy_module)
            report = compute_phy_module_fingerprint(args.project_root, files)
            report["phy_module"] = args.phy_module
            report["phy_module_source_files"] = files
            print(json.dumps(report, indent=2))
            return EXIT_UP_TO_DATE if report["status"] == "COMPUTED" else EXIT_ERROR

        if args.verb == "record":
            rtl_modules = _load_json_arg(args.rtl_modules)
            decision_ref = _load_json_arg(args.decision_ref)
            record = record_phy_revision_decision(
                args.project_root, args.phy_module, rtl_modules, decision_ref)
            print(json.dumps(record, indent=2))
            return EXIT_UP_TO_DATE

        if args.verb == "evaluate":
            record = load_phy_revision_decision_record(args.project_root, args.decision_id)
            if record is None:
                print(json.dumps({"error": "DECISION_RECORD_NOT_FOUND",
                                   "decision_id": args.decision_id}, indent=2))
                return EXIT_ERROR
            evaluation = evaluate_phy_revision_staleness(record, args.project_root)
            result = {"decision_id": args.decision_id, "evaluation": evaluation}
            if args.flag:
                result["flag"] = flag_stale_phy_revision_decision(
                    record, args.project_root, evaluation=evaluation)
            print(json.dumps(result, indent=2))
            return EXIT_STALE if evaluation["needs_reevaluation"] else EXIT_UP_TO_DATE

        report = scan_phy_revision_decisions(args.project_root)
        print(json.dumps(report, indent=2))
        return EXIT_STALE if report["stale_count"] else EXIT_UP_TO_DATE
    except PhyRevisionStalenessError as exc:
        print(json.dumps({"error": exc.reason, "detail": exc.detail}, indent=2))
        return EXIT_ERROR


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
