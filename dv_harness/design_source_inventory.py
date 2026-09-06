"""dv_harness/design_source_inventory.py -- a SOURCE REGISTRY for the design
sources a project actually has on disk: {source_id, type, version, hash,
authority, status, last_checked}, plus a DISCOVERY-order table answering "if
I don't have a fact yet, which of the 10 kinds of design source do I check
next" (2026-09-06 gap closure).

TWO TABLES, TWO DIFFERENT QUESTIONS -- and a THIRD mechanism this repo already
has that answers a third, easily-confused one. `dv_harness/source_authority.py`
already documents its own near-collision with
`tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`
("both are 9 items long, which is a coincidence that has already caused one
mis-identification"). This module adds a THIRD list, so the distinction is
spelled out here explicitly rather than left for a fourth mis-identification:

  1. `source_authority.AUTHORITY_ORDER` (9 tiers, imported here BY IMPORT
     ONLY -- this module never redefines or re-derives it) answers "two
     sources I ALREADY READ disagree about one fact -- which one is true".
     A CONFLICT-RESOLUTION order.

  2. `tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`
     (9 items: EXISTING_PROJECT_FILES ... ASK_USER) answers "which source do
     I consult FIRST when discovering a fact I don't have yet" for that
     tool's own trace-validation use case, at that tool's own granularity.

  3. `DISCOVERY_ORDER` in *this* module answers the SAME kind of question as
     (2) -- discovery order, not conflict order -- but at the finer, 10-item
     granularity this task specifies for a design-source REGISTRY: it splits
     "register files" out from RTL/PHY source, splits "specs/datasheets" out
     from VIP documentation, and names "VIP examples" and "existing UVM
     environment" as their own distinct kinds. It is not a replacement for
     (2) -- that gate's trace-file contract (`--trace`, `attempted_sources`)
     is untouched and unimported here -- it is a separate, purpose-built list
     for `evaluate_source()`/`build_source_registry()` below, exactly as
     `source_authority.py` itself is a separate list from (2) above.

REUSE. Authority ranking is `source_authority.authority_source()` /
`authority_rank()`, imported, never re-implemented. A source in this
registry that has no counterpart tier in the 9-level authority order (e.g.
`ask_user`, `git_history` -- discovery-order concerns that are not
conflict-resolution concerns) reports authority status `NOT_APPLICABLE` with
a real reason rather than being force-fit into a tier that does not exist,
per this module's own point above: discovery order and authority order are
different axes, and not every discovery kind has to sit on the authority
axis at all.

FRESHNESS/STALENESS. `golden_scenario.evaluate_freshness()` and
`signoff_export.evaluate_freeze_invalidation()` both derive FRESH/STALE/
UNKNOWN-shaped verdicts from real evidence (git diff against a recorded SHA,
field-by-field digest comparison against a frozen baseline) -- read for the
pattern, not imported: a design-source registry has to cover sources that
are not source-controlled at all (a datasheet PDF, a VIP example directory
outside this repo, "ask the user"), so there is no single recorded SHA every
row can be diffed against. Instead each source's CURRENT content hash
(sha256 of the file, or of a sorted "relpath:filehash" manifest for a
directory -- the same shape `signoff_export.compute_bundle_hash()` uses for a
bundle) is compared against a `recorded_hash` the caller supplies from its
own last inventory snapshot:

  * no `recorded_hash` supplied           -> UNKNOWN   (no baseline to diff
                                             against yet -- never guessed CURRENT)
  * path missing / unreadable             -> NOT_AVAILABLE
  * `superseded_by` set                   -> SUPERSEDED (checked first: a
                                             deliberately-retired source is
                                             not merely "changed", it is
                                             replaced, and that verdict must
                                             not be masked by a coincidental
                                             hash match)
  * hash matches `recorded_hash`          -> CURRENT
  * hash differs from `recorded_hash`     -> STALE

This module never writes or reads a snapshot store itself -- the caller
(whatever tracks "the last registry run") owns persistence and passes
`recorded_hash`/`superseded_by` in; that keeps this module honestly
duck-typed and independently testable today, per this batch's file-safety
scope (no import of, or wait on, any sibling module in this or the other
concurrently-running batch). A future integrator that already carries a
per-source snapshot table (e.g. from `evidence_db.py`) plugs in by populating
`recorded_hash` from that table's last-known hash for the same `source_id`,
and `superseded_by` from whatever marks a source retired -- no change to this
module needed.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from . import source_authority

__all__ = [
    "DesignSourceInventoryError",
    "STATUS_CURRENT", "STATUS_STALE", "STATUS_SUPERSEDED",
    "STATUS_NOT_AVAILABLE", "STATUS_UNKNOWN",
    "AUTHORITY_NOT_APPLICABLE", "AUTHORITY_RESOLVED",
    "DiscoveryKind", "DISCOVERY_ORDER",
    "normalize_discovery_kind", "discovery_check_order",
    "SourceEntry", "compute_source_hash", "evaluate_source",
    "build_source_registry",
]


class DesignSourceInventoryError(ValueError):
    """Typed error, same convention as the rest of this package: a short
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict -- never a
    silently-dropped source or a silently-guessed status."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

#: The three statuses this task's registry table names.
STATUS_CURRENT = "CURRENT"
STATUS_STALE = "STALE"
STATUS_SUPERSEDED = "SUPERSEDED"
#: Two honest additions required by the EVIDENCE TRUTH RULE: a status field
#: must never default to CURRENT/STALE when the evidence to decide either one
#: is genuinely absent.
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"   # the source's path does not exist / is unreadable
STATUS_UNKNOWN = "UNKNOWN"               # no recorded_hash to compare against yet

VALID_STATUSES = (STATUS_CURRENT, STATUS_STALE, STATUS_SUPERSEDED,
                   STATUS_NOT_AVAILABLE, STATUS_UNKNOWN)

AUTHORITY_RESOLVED = "RESOLVED"
AUTHORITY_NOT_APPLICABLE = "NOT_APPLICABLE"


def _norm(name) -> str:
    """Same normalization convention `source_authority._key()` uses (case
    and whitespace/hyphen/slash folded to `_`), kept local rather than
    imported so this module never reaches into `source_authority`'s private
    names -- only its public, documented API."""
    return re.sub(r"[\s\-/]+", "_", str(name or "").strip().lower())


# ---------------------------------------------------------------------------
# DISCOVERY-order table (distinct axis -- see module docstring)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveryKind:
    """One of the 10 kinds of design source this registry recognizes.

    `rank` is 1-based, 1 = check FIRST, mirroring the 1-is-highest
    convention `source_authority.AuthoritySource.rank` already uses, so nobody
    reading both tables has to invert one of them in their head.
    """
    rank: int
    id: str
    label: str
    aliases: tuple = ()


#: Check-first-to-check-last. Exactly the 10 kinds named by this task, in the
#: order given. This is a DISCOVERY order (where do I look for a fact I don't
#: have) -- NOT the AUTHORITY order (source_authority.AUTHORITY_ORDER, which
#: source is right when two already-read sources disagree). See module
#: docstring for the full three-way distinction.
DISCOVERY_ORDER: tuple = (
    DiscoveryKind(1, "repo_files_on_disk", "repo files on disk",
                  ("repo_files", "project_files", "existing_project_files", "on_disk")),
    DiscoveryKind(2, "existing_uvm_environment", "existing UVM environment",
                  ("uvm_env", "existing_env", "existing_testbench", "testbench_env")),
    DiscoveryKind(3, "build_scripts_makefile", "build scripts/Makefile",
                  ("makefile", "build_script", "build_scripts", "command_txt",
                   "build_regression_scripts")),
    DiscoveryKind(4, "rtl_phy_source", "RTL/PHY source",
                  ("rtl", "phy", "rtl_source", "verilog", "systemverilog", "phy_source",
                   "rtl_parameters_defines")),
    DiscoveryKind(5, "register_files", "register files",
                  ("regfile", "register_map", "regmap", "ral", "register_description")),
    DiscoveryKind(6, "specs_datasheets", "specs/datasheets",
                  ("spec", "specs", "datasheet", "datasheets", "specification", "design_docs")),
    DiscoveryKind(7, "vip_examples", "VIP examples",
                  ("vip_example", "vip_sample", "vip_reference_env", "vip_demo")),
    DiscoveryKind(8, "regression_lists", "regression lists",
                  ("regression_list", "testlist", "test_list", "vplan_test_table")),
    DiscoveryKind(9, "git_history", "git history",
                  ("git_log", "git", "history", "commit_history", "git_history_comments")),
    DiscoveryKind(10, "ask_user", "ask the user",
                  ("ask", "human", "user", "question_queue")),
)

_DISCOVERY_BY_ID = {k.id: k for k in DISCOVERY_ORDER}
_DISCOVERY_BY_ALIAS: Dict[str, DiscoveryKind] = {}
for _k in DISCOVERY_ORDER:
    for _name in (_k.id, _k.label, *_k.aliases):
        _DISCOVERY_BY_ALIAS[_norm(_name)] = _k


def normalize_discovery_kind(name) -> str:
    """Canonical `DiscoveryKind.id` for `name` (an id, a label, or a
    registered alias). Raises rather than defaulting: an unrecognized kind
    must never be silently dropped from, or silently appended to the end of,
    a check order -- both are a wrong answer to "where do I look next"."""
    if isinstance(name, DiscoveryKind):
        return name.id
    src = _DISCOVERY_BY_ALIAS.get(_norm(name))
    if src is None:
        raise DesignSourceInventoryError("UNKNOWN_DISCOVERY_KIND", {
            "kind": name,
            "known_ids": [k.id for k in DISCOVERY_ORDER],
        })
    return src.id


def discovery_check_order(fact_name: str, available_kinds: Iterable[Any]) -> dict:
    """Given a fact you don't yet have evidence for, and which of the 10
    `DISCOVERY_ORDER` kinds actually exist in this project right now, return
    the order to check them in -- highest-discovery-priority first, filtered
    to only what is available.

    `fact_name` must be stated (non-empty) -- same discipline as
    `source_authority.SourceClaim` requiring a non-empty `claim`: a check
    order for an unnamed fact cannot be told apart from any other unnamed
    fact's check order later, and the whole point of returning `fact_name`
    in the result is to make each call's answer traceable to what it was for.
    `available_kinds` entries are normalized through `normalize_discovery_kind`
    (an id, a label, or any registered alias), so a caller may pass whatever
    vocabulary its own discovery code already uses.
    """
    fact_name = str(fact_name or "").strip()
    if not fact_name:
        raise DesignSourceInventoryError("FACT_NAME_MUST_BE_STATED", {})
    available_ids = set()
    for kind in available_kinds:
        available_ids.add(normalize_discovery_kind(kind))
    check_order = [k.id for k in DISCOVERY_ORDER if k.id in available_ids]
    unavailable = [k.id for k in DISCOVERY_ORDER if k.id not in available_ids]
    return {
        "fact_name": fact_name,
        "check_order": check_order,
        "unavailable_kinds": unavailable,
        "rule": ("Check available design-source kinds in DISCOVERY_ORDER order "
                 "(repo files on disk first, ask the user last) -- a discovery "
                 "order, not the source_authority conflict-resolution order."),
    }


# ---------------------------------------------------------------------------
# Content hashing (own implementation -- see module docstring for why this
# is not imported from golden_scenario.py / signoff_export.py)
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_tree(path: Path) -> str:
    """Deterministic sha256 over every real file under `path`: sorted
    "relpath:filehash" lines, newline-joined, hashed -- the same shape
    `signoff_export.compute_bundle_hash()` uses for a bundle manifest, so a
    directory source (a VIP example tree, a regression-list directory) has
    the same kind of single content hash a single file gets."""
    lines = []
    for p in sorted(path.rglob("*")):
        if p.is_file():
            lines.append(f"{p.relative_to(path).as_posix()}:{_sha256_file(p)}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def compute_source_hash(path: Union[str, Path, None]) -> dict:
    """Real content hash for one source path, or an honest NOT_AVAILABLE.

    Never fabricates a hash for a path that does not exist or cannot be
    read -- a missing/unreadable source is reported as such, not silently
    skipped or silently treated as unchanged.
    """
    if not path:
        return {"status": STATUS_NOT_AVAILABLE, "hash": None,
                "reason": "NO_PATH_SUPPLIED: this source entry has no `path` to hash"}
    p = Path(path)
    if not p.exists():
        return {"status": STATUS_NOT_AVAILABLE, "hash": None,
                "reason": f"PATH_DOES_NOT_EXIST: {p}"}
    try:
        digest = _sha256_tree(p) if p.is_dir() else _sha256_file(p)
    except OSError as exc:
        return {"status": STATUS_NOT_AVAILABLE, "hash": None,
                "reason": f"PATH_UNREADABLE: {p} ({exc})"}
    return {"status": "CAPTURED", "hash": digest, "reason": None}


# ---------------------------------------------------------------------------
# Registry rows
# ---------------------------------------------------------------------------

@dataclass
class SourceEntry:
    """One row a caller wants inventoried, BEFORE evaluation. Duck-typed on
    purpose (plain fields, no dependency on any other new module in this or
    the concurrently-running batch): `build_source_registry()` also accepts
    plain dicts with these same keys and converts them via `SourceEntry(**d)`.

    `authority_hint`, if given, is anything `source_authority.normalize_source`
    already accepts (an id, a doc phrase, or a registered alias, e.g.
    "dut_rtl", "register_file", "spec_doc", "vip_document"). Left `None` for a
    source whose kind has no counterpart in the 9-level authority order (see
    module docstring) -- `evaluate_source()` then reports authority
    `NOT_APPLICABLE` rather than guessing a tier.

    `recorded_hash` / `superseded_by` are the caller-supplied "what did I
    record last time" inputs the freshness derivation compares against; see
    module docstring's FRESHNESS/STALENESS section.
    """
    source_id: str
    type: str
    path: Optional[str] = None
    version: Optional[str] = None
    authority_hint: Optional[str] = None
    recorded_hash: Optional[str] = None
    superseded_by: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        self.source_id = str(self.source_id or "").strip()
        if not self.source_id:
            raise DesignSourceInventoryError("SOURCE_ID_MUST_BE_STATED", {})
        self.type = str(self.type or "").strip()
        if not self.type:
            raise DesignSourceInventoryError("SOURCE_TYPE_MUST_BE_STATED",
                                              {"source_id": self.source_id})


def _resolve_authority(authority_hint: Optional[str]) -> dict:
    """Authority-tier lookup, by IMPORT ONLY against `source_authority`'s
    public API (`authority_source`) -- never a re-derived ranking."""
    if not authority_hint:
        return {
            "status": AUTHORITY_NOT_APPLICABLE, "rank": None, "id": None,
            "doc_phrase": None,
            "reason": ("NO_AUTHORITY_HINT_SUPPLIED: discovery order and authority "
                       "order are different axes (see module docstring) -- not every "
                       "design-source kind has to sit on the conflict-resolution axis "
                       "at all (e.g. ask_user, git_history)."),
        }
    try:
        src = source_authority.authority_source(authority_hint)
    except source_authority.SourceAuthorityError as exc:
        return {
            "status": AUTHORITY_NOT_APPLICABLE, "rank": None, "id": None,
            "doc_phrase": None,
            "reason": (f"UNRESOLVED_AUTHORITY_HINT: source_authority has no tier for "
                       f"{authority_hint!r} ({exc.reason})"),
        }
    return {
        "status": AUTHORITY_RESOLVED, "rank": src.rank, "id": src.id,
        "doc_phrase": src.doc_phrase, "reason": None,
    }


def _resolve_status(entry: SourceEntry, hash_result: dict) -> Sequence[Any]:
    """CURRENT/STALE/SUPERSEDED/NOT_AVAILABLE/UNKNOWN, worst-decided-first:
    a deliberately superseded source is reported as such even if its content
    happens to still match the last recorded hash (retirement is a fact
    about the SOURCE, not about its bytes, and must not be masked by a
    coincidental hash match); a missing/unreadable path is reported before
    any hash comparison is attempted; only then is CURRENT vs STALE decided,
    and only when there is a `recorded_hash` to decide it against -- absent
    that baseline the honest answer is UNKNOWN, never a guessed CURRENT."""
    if entry.superseded_by:
        return (STATUS_SUPERSEDED,
                [f"SUPERSEDED_BY: {entry.superseded_by}"])
    if hash_result["status"] == STATUS_NOT_AVAILABLE:
        return (STATUS_NOT_AVAILABLE, [hash_result["reason"]])
    if not entry.recorded_hash:
        return (STATUS_UNKNOWN,
                ["NO_RECORDED_HASH: no prior snapshot's hash was supplied to compare "
                 "against, so freshness is not yet decidable for this source"])
    if hash_result["hash"] == entry.recorded_hash:
        return (STATUS_CURRENT, ["HASH_MATCHES_RECORDED_SNAPSHOT"])
    return (STATUS_STALE,
            [f"HASH_CHANGED_SINCE_LAST_CHECK: recorded={entry.recorded_hash[:16]}... "
             f"current={hash_result['hash'][:16]}..."])


def evaluate_source(entry: Union[SourceEntry, dict], *,
                     now: Optional[datetime] = None) -> dict:
    """Evaluate one design source into the registry row shape this task
    names: {source_id, type, version, hash, authority, status, last_checked},
    plus `reasons`/`path`/`recorded_hash`/`superseded_by`/`detail` for
    traceability. `now` is injectable so a test gets a deterministic
    `last_checked` without needing to freeze real wall-clock time.
    """
    if not isinstance(entry, SourceEntry):
        entry = SourceEntry(**dict(entry))
    hash_result = compute_source_hash(entry.path)
    status, reasons = _resolve_status(entry, hash_result)
    authority = _resolve_authority(entry.authority_hint)
    last_checked = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "source_id": entry.source_id,
        "type": entry.type,
        "version": entry.version,
        "hash": hash_result["hash"],
        "authority": authority,
        "status": status,
        "last_checked": last_checked,
        "path": entry.path,
        "recorded_hash": entry.recorded_hash,
        "superseded_by": entry.superseded_by,
        "reasons": list(reasons),
        "detail": dict(entry.detail),
    }


def build_source_registry(entries: Iterable[Union[SourceEntry, dict]], *,
                           now: Optional[datetime] = None) -> dict:
    """Evaluate a whole batch of sources into the registry table plus a
    per-status summary count. `entries` is duck-typed (a `SourceEntry` or a
    plain dict with the same keys per source) -- exactly the generic input
    shape this batch's file-safety rule requires for any data another new
    module in this (or the concurrently-running) batch would eventually
    supply: a real per-source-kind producer (a repo-file walker, a
    Makefile/regression-list scanner, a git-history reader) can populate
    this list's `path`/`type`/`authority_hint`/`recorded_hash` fields once it
    exists, with no import of it needed here.
    """
    rows = [evaluate_source(e, now=now) for e in entries]
    summary = {status: 0 for status in VALID_STATUSES}
    for row in rows:
        summary[row["status"]] += 1
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "source_count": len(rows),
        "sources": rows,
        "summary": summary,
    }
