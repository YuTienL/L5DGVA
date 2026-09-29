"""Multi-Hop Memory-Promotion Lineage Walker (2026-09-07, item
multi_hop_memory_lineage).

REUSE OVER REINVENT, verified before a line of this was written. This module
adds ZERO new persistence and no `memory.py` schema change -- every field it
reads already exists and is already read by production code:

  * `source_engineering_memory_id` -- the exact single-hop back-pointer
    `memory_router.organizational_admission_gate()` itself resolves via
    `MemoryStore(root).get(str(source_id))` before admitting a promotion.
    Set, verbatim, by `memory_router.promote_to_organizational()`'s own
    record construction (memory_router.py ~line 1087).
  * `corroborating_memory_ids` -- the real multi-hop back-pointer
    `memory_router.research_engineering_admission_reasons()` already resolves
    (also via `MemoryStore(root).get(memory_id)`) to count independent
    corroborating sources for a research-origin claim. Nothing before this
    module ever walked it recursively into a full chain; that function only
    ever counts DISTINCT SOURCE DOCUMENTS among the ids it resolves.
  * `source_finding_id` -- a real field `memory.MemoryConsolidator.
    from_closed_finding()` writes (memory.py line 649), cited into a vault
    note's "Related Knowledge" section by `memory_vault.
    build_sections_from_memory_record()`. It names a Blackboard finding_id,
    not a MemoryStore memory_id -- CLAUDE.md's own Core Operating Rules
    ("Blackboard stores current verification truth", a per-run object, never
    the durable memory-tier history) is why this module reports it as a
    real, cited EXTERNAL reference and never tries to resolve it as if it
    were a memory_id.
  * `confirmation_count` / `last_confirmed_at` / `last_confirmation_evidence`
    -- the real confirmation-event fields `memory.MemoryGC.confirm()` writes
    (memory.py line ~706). VERIFIED FIRST, AND DISCLOSED HONESTLY: `confirm()`
    OVERWRITES `last_confirmation_evidence` on every call rather than
    appending to a history (there is no array, no per-event log anywhere in
    this schema) -- so a record confirmed N times only ever has the MOST
    RECENT confirming evidence recoverable from disk; the other N-1 events
    are represented only by the count. This module states that limitation on
    every node it builds rather than fabricating a confirmation history that
    does not exist.

THE ONE GENUINE GAP THIS CLOSES: nothing before this module ever WALKED any
of the above recursively into one queryable structure. `organizational_
admission_gate()` reads `source_engineering_memory_id` for exactly one
purpose (is the immediate source record real, ACTIVE, gate-validated,
sufficiently confirmed) and stops there; `research_engineering_admission_
reasons()` reads `corroborating_memory_ids` for exactly one purpose (count
distinct source documents) and also stops there, at depth 1, without ever
following a corroborating record's OWN `corroborating_memory_ids`/
`source_engineering_memory_id`. Neither builds a chain a human or another
tool could ask "how did this Organizational conclusion actually get here,
hop by hop, all the way back to the evidence" -- this module is exactly
that, and only that: a read-only walker, never a second admission gate.

WHY ORGANIZATIONAL-TIER RESOLUTION NEEDS THE DV-KNOWLEDGE VAULT.
`memory.OrganizationalMemoryStore`'s own module comment states the real
design directly: Organizational-tier records have NO local
`.dv-harness/memory/organizational/` file store -- their real backing store
is the shared, cross-user Knowledge Center (a REMOTE service this module
must never contact; establishing that connection needs the SSH/Remote
Transport Connection Intake gate and an explicit human decision this
automated pass does not have). What IS real, local and read-only is the
DV-Knowledge Vault mirror `memory_router._maybe_write_vault_note()` writes on
every real promotion (`memory_vault.py`), whose "Related Knowledge" section
already carries the exact `[[source_engineering_memory_id]]` wikilink
(`memory_vault.build_sections_from_memory_record()`, line ~1418) this module
needs. So the entry point into an Organizational record's lineage is: a
caller-supplied record dict (the record just pushed, still in hand), OR the
local vault note mirror -- never the remote Knowledge Center.

A GENUINE, DISCLOSED AMBIGUITY WHEN FALLING BACK TO THE VAULT MIRROR: that
mirror's frontmatter does not carry `source_engineering_memory_id` (only
`build_sections_from_memory_record()`'s BODY text does, as a bare
`[[id]]` wikilink with no field name attached), and the same "Related
Knowledge" section can also carry RELATED-similarity wikilinks (from
`memory_router._related_knowledge_with_links()`, always suffixed
"(related, similarity N.NN)") that are NOT a derivation/lineage hop at all.
This module filters out every similarity-suffixed link (a real, structural
distinction, not a guess) and reports every remaining bare wikilink as an
honestly AMBIGUOUS lineage candidate -- "this note derives from one of
source_finding_id/source_engineering_memory_id, the vault mirror does not
tag which" -- rather than silently picking one. This ambiguity is rare in
practice: an Organizational record's own construction in `memory_router.
promote_to_organizational()` never sets `source_finding_id`, so the
Organizational-tier root itself is unambiguous; only a deeper Engineering-tier
node reached ONLY through the vault (its own local JSON file already deleted)
could actually hit this case.

WHAT THIS MODULE DOES NOT DO. It never writes to MemoryStore, the vault, or
any memory-tier record -- read-only throughout, and it never constructs a
`MemoryStore` (which `mkdir()`s the whole tier tree) or reads
`.dv-harness/config.json` through `config.load_config()` (which WRITES a
default one) on a project that has neither a memory store nor a vault
already on disk, mirroring the exact "reading must never mint state"
discipline `cross_project_mining.has_memory_store()`/`confidence_
calibration.calibrate()`/`golden_flow_readiness.py` already established
for themselves. It performs no arbitration, no promotion, no build/
regression/LSF job, and it decides nothing about whether a record SHOULD
have promoted -- `memory_router.organizational_admission_gate()` remains the
only real gate for that; this module only reconstructs, honestly, what
lineage already exists.

Proven by `dv_harness_tests/test_memory_lineage.py` against a REAL
`MemoryStore` driven through the REAL `memory_router.route_and_store()` /
`memory_router.promote_to_organizational()` / `memory.MemoryGC.confirm()`
production write paths (never a hand-shaped stand-in for any record), plus a
REAL `memory_vault` note round trip for the Organizational-tier fallback
case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .memory import MemoryStore

# --- Real, already-existing field names this module reuses verbatim -------

# Resolved recursively: each value is a real memory_id (or list of them) this
# module tries to look up and keep walking from.
SOURCE_ENGINEERING_FIELD = "source_engineering_memory_id"
CORROBORATING_FIELD = "corroborating_memory_ids"
BACK_POINTER_FIELDS = (SOURCE_ENGINEERING_FIELD, CORROBORATING_FIELD)

# Cited but never resolved as a memory_id -- see the module docstring's
# `source_finding_id` paragraph for why (a Blackboard finding_id, not a
# MemoryStore record).
SOURCE_FINDING_FIELD = "source_finding_id"
EXTERNAL_REFERENCE_FIELDS = (SOURCE_FINDING_FIELD,)

# The vault-mirror-only relation this module additionally walks when a node
# had to be resolved through the DV-Knowledge Vault fallback (see module
# docstring's ambiguity paragraph). Not a real record field -- a synthetic
# field name this module uses on its own LineageReference rows to make that
# provenance honestly visible.
VAULT_AMBIGUOUS_LINK_FIELD = "related_knowledge_link (vault mirror; source field indeterminate)"

# Real, job/simulation-level evidence fields an Engineering (or
# Organizational) -tier record carries INLINE -- never a separate resolvable
# memory_id, but real cited evidence nonetheless. See engine.py's
# _promote_verified_fix_knowledge()/_promote_experience_knowledge() and
# memory_router.promote_to_organizational()'s own record construction for
# where each of these is actually written.
INLINE_EVIDENCE_FIELDS = (
    "evidence", "verification", "root_cause", "fix", "symptoms",
    "git_sha", "rtl_sha", "tb_sha", "test", "result",
    "source_confirmation_count", "confidence_result", "confidence_inputs",
)

RESOLUTION_LOCAL_JSON = "local_memory_store_json"
RESOLUTION_VAULT_NOTE = "vault_note_mirror"
RESOLUTION_CALLER_SUPPLIED = "caller_supplied_record"
RESOLUTION_CYCLE = "cycle_detected"

STATUS_FULLY_RESOLVED = "FULLY_RESOLVED"
STATUS_PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
STATUS_ROOT_UNAVAILABLE = "ROOT_UNAVAILABLE"

# Defensive recursion cap. Cycle detection (via the `visited` set every
# recursive call carries) is the REAL guard; this only bounds a pathological
# non-cyclic chain (e.g. a very long corroborating_memory_ids fan-out) from
# recursing unboundedly.
MAX_LINEAGE_DEPTH = 50


class MemoryLineageError(ValueError):
    pass


# --- Vault-mirror placeholder text, reused rather than re-typed -----------
# memory_router.py's own `_SECTION_PLACEHOLDERS` is the single real source of
# truth for "this vault-note section has no real content yet" -- imported
# lazily below (memory_router.py is a large, frequently-touched module; this
# module never imports it at module load time to keep import order cheap and
# to avoid a circular-import risk memory_router.py itself would introduce if
# it ever imported this module back).
def _section_placeholders() -> frozenset:
    from . import memory_router as _mr
    return _mr._SECTION_PLACEHOLDERS


def _clean_section(text: Optional[str]) -> Optional[str]:
    """A vault-note body section's rendered text, or None when it is empty
    or still holds one of memory_vault's own placeholder strings (e.g.
    "_Not captured._") -- never returned as if it were real content."""
    if text is None:
        return None
    t = text.strip()
    if not t or t in _section_placeholders():
        return None
    return t


# --- Read-only config/vault-path resolution --------------------------------
#
# Deliberately NOT `config.load_config()` / `memory_vault.resolve_vault_path()`
# directly: `load_config()` WRITES `.dv-harness/config.json` the first time it
# is called on a project that has none (config.py line ~342-344), and
# `resolve_vault_path()` calls `load_config()` internally when handed no cfg.
# A pure lineage READ must never mint either file on a project that has
# neither a memory store nor a vault to begin with -- see the module
# docstring's "WHAT THIS MODULE DOES NOT DO" paragraph.

def _read_cfg_readonly(root: Path) -> Dict[str, Any]:
    p = root / ".dv-harness" / "config.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _resolve_vault_path_readonly(root: Path, cfg: Dict[str, Any]) -> Path:
    configured = str((cfg.get("memory") or {}).get("vault_path") or "").strip()
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = root / p
        return p.resolve()
    return (root / ".dv-harness" / "vault").resolve()


# --- Data model -------------------------------------------------------------

@dataclass
class LineageReference:
    """One outgoing pointer from a `LineageNode`, real or dangling."""
    field: str
    memory_id: str
    resolved: bool
    reason: Optional[str] = None
    node: Optional["LineageNode"] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "field": self.field, "memory_id": self.memory_id, "resolved": self.resolved,
            "external_reference": self.field in EXTERNAL_REFERENCE_FIELDS,
        }
        if self.reason:
            out["reason"] = self.reason
        if self.node is not None:
            out["node"] = self.node.to_dict()
        return out


@dataclass
class LineageNode:
    memory_id: str
    level: str
    resolution_source: str
    kind: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[str] = None
    protocol: Optional[str] = None
    confirmation: Dict[str, Any] = field(default_factory=dict)
    inline_evidence: Dict[str, Any] = field(default_factory=dict)
    references: List[LineageReference] = field(default_factory=list)
    is_cycle_reference: bool = False
    vault_note_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "level": self.level,
            "resolution_source": self.resolution_source,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "confidence": self.confidence,
            "protocol": self.protocol,
            "is_cycle_reference": self.is_cycle_reference,
            "vault_note_path": self.vault_note_path,
            "confirmation": self.confirmation,
            "inline_evidence": self.inline_evidence,
            "references": [r.to_dict() for r in self.references],
        }


@dataclass
class LineageResult:
    root_memory_id: str
    status: str
    root: Optional[LineageNode]
    unresolved_reference_count: int
    external_reference_count: int
    chain: List[Dict[str, Any]]
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_memory_id": self.root_memory_id,
            "status": self.status,
            "unresolved_reference_count": self.unresolved_reference_count,
            "external_reference_count": self.external_reference_count,
            "notes": self.notes,
            "root": self.root.to_dict() if self.root is not None else None,
            "chain": self.chain,
        }


# --- Confirmation-event honesty --------------------------------------------

def _confirmation_summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Reads MemoryGC.confirm()'s three real fields off a record and states,
    on every node, the one real limitation VERIFIED FIRST in memory.py: only
    the MOST RECENT confirmation event's evidence is ever recoverable -- there
    is no per-event history anywhere in this schema (confirm() overwrites
    `last_confirmation_evidence`, it never appends)."""
    try:
        count = int(rec.get("confirmation_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    last_at = rec.get("last_confirmed_at")
    last_evidence = rec.get("last_confirmation_evidence")
    summary: Dict[str, Any] = {
        "confirmation_count": count,
        "last_confirmed_at": last_at,
        "most_recent_confirmation_evidence": last_evidence,
        "full_confirmation_history_recoverable": False,
    }
    if count > 0:
        remaining = max(count - 1, 0)
        summary["note"] = (
            f"Independently re-confirmed {count} time(s) beyond its original creation "
            "(dv_harness.memory.MemoryGC.confirm()). Only the MOST RECENT confirming "
            "evidence is retained on disk -- confirm() overwrites last_confirmation_evidence "
            f"on every call rather than appending to a history, so the other {remaining} "
            "confirmation event(s) are represented only by this count, not by their own "
            "evidence."
        )
    else:
        summary["note"] = "Never independently re-confirmed after creation."
    return summary


def _inline_evidence(rec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in INLINE_EVIDENCE_FIELDS:
        v = rec.get(k)
        if v not in (None, "", [], {}):
            out[k] = v
    return out


def _extract_ids(raw: Any) -> List[str]:
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, (list, tuple)):
        out = []
        for x in raw:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    return []


# --- Resolution (local MemoryStore, then the local vault mirror) ----------

_RELATED_SIMILARITY_RE = None
_BARE_WIKILINK_RE = None


def _wikilink_patterns():
    global _RELATED_SIMILARITY_RE, _BARE_WIKILINK_RE
    if _BARE_WIKILINK_RE is None:
        import re
        _RELATED_SIMILARITY_RE = re.compile(
            r"^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*\(related,\s*similarity", re.IGNORECASE)
        _BARE_WIKILINK_RE = re.compile(r"^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
    return _RELATED_SIMILARITY_RE, _BARE_WIKILINK_RE


def _resolve_via_local_store(store: MemoryStore, memory_id: str) -> Optional[Dict[str, Any]]:
    try:
        return store.get(memory_id)
    except Exception:
        return None


def _resolve_via_vault(root: Path, memory_id: str, cfg: Dict[str, Any],
                        vault_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """LOCAL-ONLY fallback for a memory_id with no local per-tier JSON file
    (true, by design, for every real Organizational-tier record -- see the
    module docstring). Never contacts the remote Knowledge Center:
    `memory_vault.get_active_provider()` only ever resolves to a local
    `FileSystemMarkdownAdapter`, optionally paired with a LOCAL Obsidian REST
    probe (memory_vault.py's own documented "opportunistic" contract) -- the
    same read path every other real `dv-harness memory search/get` call
    already uses. Only ever called once `vault_path` is confirmed to already
    exist on disk (see build_lineage()'s own guard), so this never mints a
    vault tree on a project that never had one."""
    from . import memory_vault as mv
    try:
        provider = mv.get_active_provider(root, cfg)
        result = provider.read(memory_id)
    except Exception as exc:
        return None, f"VAULT_READ_FAILED: {exc}"
    if not result.get("ok"):
        return None, str(result.get("error") or "NOT_FOUND_IN_VAULT")
    fm = result.get("frontmatter") or {}
    body = result.get("body") or ""
    sections = mv._body_to_sections(body)
    related_text = sections.get("Related Knowledge") or ""
    related_re, bare_re = _wikilink_patterns()
    ambiguous_links: List[str] = []
    for line in related_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or related_re.match(line):
            continue  # a RELATED-by-similarity link, never a derivation/lineage hop
        m = bare_re.match(line)
        if m:
            ambiguous_links.append(m.group(1).strip())
    rec = {
        "memory_id": fm.get("id") or memory_id,
        "level": fm.get("memory_level"),
        "status": fm.get("status"),
        "confidence": fm.get("confidence"),
        "protocol": fm.get("protocol"),
        "title": fm.get("failure"),
        "confirmation_count": fm.get("confirmation_count", 0),
        "last_confirmed_at": fm.get("last_confirmed_at"),
        "root_cause": _clean_section(sections.get("Root Cause")),
        "fix": _clean_section(sections.get("Fix")),
        "evidence": _clean_section(sections.get("Evidence")),
        "verification": _clean_section(sections.get("Verification")),
        "_vault_ambiguous_related_links": ambiguous_links,
        "_vault_note_path": result.get("path"),
    }
    return rec, None


def _resolve_record(root: Path, store: Optional[MemoryStore], memory_id: str, *,
                     cfg: Dict[str, Any], vault_path: Optional[Path],
                     caller_record: Optional[Dict[str, Any]]
                     ) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """Returns (record, resolution_source, unresolved_reason). Tries, in
    order: a caller-supplied record (for the walk's own starting point only),
    the local per-tier MemoryStore (job/engineering/project/working -- the
    system of record for those four tiers), then the local DV-Knowledge Vault
    mirror (the only local trace of an Organizational-tier record, and a
    fallback for any tier whose own per-tier JSON file has since been
    deleted)."""
    if caller_record is not None:
        return caller_record, RESOLUTION_CALLER_SUPPLIED, None
    if store is not None:
        rec = _resolve_via_local_store(store, memory_id)
        if rec is not None:
            return rec, RESOLUTION_LOCAL_JSON, None
    if vault_path is not None and vault_path.is_dir():
        rec, err = _resolve_via_vault(root, memory_id, cfg, vault_path)
        if rec is not None:
            return rec, RESOLUTION_VAULT_NOTE, None
        return None, RESOLUTION_VAULT_NOTE, err
    return None, RESOLUTION_LOCAL_JSON, "NOT_FOUND_LOCALLY_AND_NO_VAULT_ON_DISK"


# --- The recursive walk -----------------------------------------------------

def _walk(root: Path, store: Optional[MemoryStore], memory_id: str, *,
          cfg: Dict[str, Any], vault_path: Optional[Path], visited: Set[str],
          depth: int, caller_record: Optional[Dict[str, Any]] = None,
          ) -> Tuple[Optional[LineageNode], Optional[str]]:
    """Returns (node, None) on success, or (None, reason) when `memory_id`
    cannot be resolved through any real, local channel. Never raises on an
    ordinary unresolved reference -- only a genuine caller-usage error
    (handled by the public entry points below) does."""
    if memory_id in visited:
        return LineageNode(memory_id=memory_id, level="unknown",
                            resolution_source=RESOLUTION_CYCLE,
                            is_cycle_reference=True), None

    rec, source, unresolved_reason = _resolve_record(
        root, store, memory_id, cfg=cfg, vault_path=vault_path, caller_record=caller_record)
    if rec is None:
        return None, unresolved_reason or "NOT_FOUND"

    node = LineageNode(
        memory_id=str(rec.get("memory_id") or memory_id),
        level=str(rec.get("level") or "unknown"),
        resolution_source=source,
        kind=rec.get("kind"),
        title=rec.get("title"),
        status=rec.get("status"),
        confidence=rec.get("confidence"),
        protocol=rec.get("protocol"),
        confirmation=_confirmation_summary(rec),
        inline_evidence=_inline_evidence(rec),
        vault_note_path=rec.get("_vault_note_path"),
    )

    new_visited = visited | {memory_id}

    if depth >= MAX_LINEAGE_DEPTH:
        node.references.append(LineageReference(
            field="DEPTH_LIMIT_REACHED", memory_id="", resolved=False,
            reason=f"stopped recursing at MAX_LINEAGE_DEPTH={MAX_LINEAGE_DEPTH} "
                   "(a defensive cap; cycle detection is the real guard against runaway "
                   "recursion, this only bounds a pathological non-cyclic fan-out)"))
        return node, None

    for f in BACK_POINTER_FIELDS:
        for ref_id in _extract_ids(rec.get(f)):
            child, reason = _walk(root, store, ref_id, cfg=cfg, vault_path=vault_path,
                                   visited=new_visited, depth=depth + 1)
            node.references.append(LineageReference(
                field=f, memory_id=ref_id, resolved=child is not None,
                node=child, reason=reason))

    if source == RESOLUTION_VAULT_NOTE:
        for ref_id in rec.get("_vault_ambiguous_related_links") or []:
            child, reason = _walk(root, store, ref_id, cfg=cfg, vault_path=vault_path,
                                   visited=new_visited, depth=depth + 1)
            node.references.append(LineageReference(
                field=VAULT_AMBIGUOUS_LINK_FIELD, memory_id=ref_id,
                resolved=child is not None, node=child, reason=reason))

    for f in EXTERNAL_REFERENCE_FIELDS:
        raw = rec.get(f)
        if raw:
            node.references.append(LineageReference(
                field=f, memory_id=str(raw), resolved=False,
                reason="EXTERNAL_REFERENCE: cites a Blackboard finding_id "
                       "(dv_harness.memory.MemoryConsolidator.from_closed_finding()'s own "
                       "source field), not a persisted MemoryStore record. Blackboard holds "
                       "current-run verification truth (CLAUDE.md Core Operating Rules), not "
                       "a durable memory-tier history, so this citation is reported for "
                       "provenance but never resolved as a memory_id."))

    return node, None


# --- Flattening into one queryable chain -----------------------------------

def _flatten(node: LineageNode, depth: int = 0, via_field: str = "ROOT") -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = [{
        "row_kind": "node",
        "depth": depth,
        "via_field": via_field,
        "memory_id": node.memory_id,
        "level": node.level,
        "kind": node.kind,
        "title": node.title,
        "status": node.status,
        "confidence": node.confidence,
        "protocol": node.protocol,
        "resolution_source": node.resolution_source,
        "is_cycle_reference": node.is_cycle_reference,
        "confirmation_count": node.confirmation.get("confirmation_count"),
        "has_inline_evidence": bool(node.inline_evidence),
    }]
    for ref in node.references:
        rows.append({
            "row_kind": "reference",
            "depth": depth + 1,
            "via_field": ref.field,
            "memory_id": ref.memory_id,
            "resolved": ref.resolved,
            "external_reference": ref.field in EXTERNAL_REFERENCE_FIELDS,
            "reason": ref.reason,
        })
        if ref.node is not None:
            rows.extend(_flatten(ref.node, depth + 1, ref.field))
    return rows


def collect_job_tier_evidence(node: Optional[LineageNode]) -> List[Dict[str, Any]]:
    """Every piece of ORIGINAL, job/simulation-level evidence this lineage
    actually reached, honestly split into two kinds (never conflated, per the
    Evidence Truth Rule): a real, SEPARATELY-STORED Job-tier `MemoryStore`
    record (`kind="job_failure"/"job_result"/"job_rerun"`, level=="job") --
    reachable ONLY via a real `corroborating_memory_ids` link today, since no
    production write path in this codebase sets any OTHER back-pointer from
    an Engineering-tier record to a specific Job-tier memory_id -- and the
    raw evidence FIELDS an Engineering-tier record carries INLINE (evidence/
    verification/git_sha/rtl_sha/tb_sha/test/result) when no further,
    separately-resolvable memory-tier record could be reached from it. The
    second kind is reported ONLY at a genuine leaf (a node with no resolved
    back-pointer children) -- never claimed as "the original Job-tier
    evidence" for a node that in fact has further lineage to walk."""
    out: List[Dict[str, Any]] = []
    if node is None:
        return out

    def _visit(n: LineageNode, path: List[str]) -> None:
        resolved_children = [
            r for r in n.references
            if r.resolved and r.node is not None and not r.node.is_cycle_reference
            and r.field in BACK_POINTER_FIELDS + (VAULT_AMBIGUOUS_LINK_FIELD,)
        ]
        if n.level == "job":
            out.append({
                "evidence_kind": "job_tier_memory_record",
                "memory_id": n.memory_id, "path": path + [n.memory_id],
                "title": n.title, "status": n.status,
                "inline_evidence": n.inline_evidence,
            })
        elif not resolved_children and n.inline_evidence:
            out.append({
                "evidence_kind": "inline_evidence_no_separate_job_record",
                "memory_id": n.memory_id, "level": n.level,
                "path": path + [n.memory_id],
                "evidence": n.inline_evidence,
            })
        for r in resolved_children:
            _visit(r.node, path + [n.memory_id])

    _visit(node, [])
    return out


# --- Public entry points ----------------------------------------------------

def build_lineage(root: Path, memory_id: str, *,
                   record: Optional[Dict[str, Any]] = None) -> LineageResult:
    """Read-only lineage reconstruction starting from ANY memory_id (any
    tier). `build_organizational_lineage()` below is the item's own primary
    entry point (Organizational-tier, with the vault-fallback resolution that
    tier structurally needs); this function is the generic engine it and any
    other caller uses.

    `record`, when supplied, is used as the starting node's content directly
    (RESOLUTION_CALLER_SUPPLIED) instead of any lookup -- the honest path for
    an Organizational-tier record a caller already holds in hand (e.g. the
    dict `memory_router.promote_to_organizational()`/`route_and_store()` just
    returned), since that tier has no local per-tier JSON file to read back.

    Mints NOTHING on disk. If the project has neither a memory store nor a
    vault already on disk, and no `record` was supplied, this returns
    ROOT_UNAVAILABLE without constructing a `MemoryStore` (which would
    `mkdir()` the whole tier tree) or reading config.json through
    `config.load_config()` (which would WRITE a default one) -- see the
    module docstring's read-only-first-check discipline.

    Raises `MemoryLineageError` on a genuine CALLER-usage error (no
    memory_id, or a `record` that is not a dict) -- never on an ordinary
    unresolved/dangling reference found while walking, which is always
    reported honestly on the result instead."""
    if not memory_id or not isinstance(memory_id, str):
        raise MemoryLineageError(f"memory_id must be a non-empty string, got {memory_id!r}")
    if record is not None and not isinstance(record, dict):
        raise MemoryLineageError(f"record must be a dict or None, got {type(record).__name__}")
    root = Path(root).resolve()

    from . import cross_project_mining as _cpm
    has_store = _cpm.has_memory_store(root)
    # `_read_cfg_readonly()` is a plain, side-effect-free read (never
    # `config.load_config()`, which WRITES a default config.json) -- safe to
    # call unconditionally regardless of has_store/vault_present/record, so
    # a project whose only local trace is the DV-Knowledge Vault (has_store
    # False) still gets its real `memory.vault_path`/`memory.obsidian_cli`
    # overrides honored rather than silently falling back to `{}`.
    cfg = _read_cfg_readonly(root)
    vault_path = _resolve_vault_path_readonly(root, cfg)
    vault_present = vault_path.is_dir()

    if not has_store and not vault_present and record is None:
        return LineageResult(
            root_memory_id=memory_id, status=STATUS_ROOT_UNAVAILABLE, root=None,
            unresolved_reference_count=1, external_reference_count=0, chain=[],
            notes=[
                f"Neither a local memory store ({root / '.dv-harness' / 'memory'}) nor a "
                f"local DV-Knowledge Vault ({vault_path}) exists at this project root, and "
                "no record was supplied directly. Nothing was read or written to reach this "
                "conclusion (no MemoryStore/config.json/vault directory was created by this "
                "check)."
            ])

    # Deliberately NOT `MemoryStore(root)` when `has_store` is False, even if
    # `record` was supplied directly: constructing one would `mkdir()` the
    # whole `.dv-harness/memory/` tier tree on a project that genuinely has
    # none, for zero behavioural benefit -- `store=None` already makes
    # `_resolve_record()` skip straight to the vault fallback below, exactly
    # as a real (empty) MemoryStore.get() would have anyway, without the
    # side effect. Mints nothing.
    store = MemoryStore(root) if has_store else None

    node, reason = _walk(root, store, memory_id, cfg=cfg,
                          vault_path=vault_path if vault_present else None,
                          visited=set(), depth=0, caller_record=record)
    if node is None:
        return LineageResult(
            root_memory_id=memory_id, status=STATUS_ROOT_UNAVAILABLE, root=None,
            unresolved_reference_count=1, external_reference_count=0, chain=[],
            notes=[f"Could not resolve {memory_id!r}: {reason}"])

    chain = _flatten(node)
    unresolved = sum(
        1 for row in chain
        if row["row_kind"] == "reference" and not row["resolved"] and not row["external_reference"])
    external = sum(1 for row in chain if row.get("external_reference"))
    status = STATUS_FULLY_RESOLVED if unresolved == 0 else STATUS_PARTIALLY_RESOLVED
    return LineageResult(root_memory_id=memory_id, status=status, root=node,
                          unresolved_reference_count=unresolved,
                          external_reference_count=external, chain=chain, notes=[])


def build_organizational_lineage(root: Path, org_memory_id: str, *,
                                  org_record: Optional[Dict[str, Any]] = None) -> LineageResult:
    """The item's own primary entry point: reconstruct the full lineage of an
    Organizational-tier memory record, back through every recoverable
    Engineering-tier confirmation event, to whatever Job-tier evidence (a
    real Job-tier record, or the inline evidence fields carried on a terminal
    Engineering-tier record) this codebase's own real back-pointers actually
    reach.

    `org_record`, when supplied, is the pushed record a caller already holds
    (see `build_lineage()`'s own docstring for why that is the honest path
    for this tier). Omitted, this falls back to the local DV-Knowledge Vault
    mirror -- the only local trace of an Organizational-tier record, since
    that tier has no local per-tier JSON store by design."""
    result = build_lineage(root, org_memory_id, record=org_record)
    if result.root is not None and result.root.level not in ("organizational", "unknown"):
        result.notes.append(
            f"WARNING: the resolved root record's own level is {result.root.level!r}, not "
            "'organizational' -- this walker still reconstructs its lineage honestly, but the "
            "record you asked about may not actually be an Organizational-tier record.")
    return result


def render_lineage_text(result: LineageResult) -> str:
    lines = [f"Memory lineage for {result.root_memory_id}: {result.status}"]
    if result.notes:
        for n in result.notes:
            lines.append(f"  NOTE: {n}")
    for row in result.chain:
        indent = "  " * row["depth"]
        if row["row_kind"] == "node":
            conf = row.get("confirmation_count")
            conf_txt = f", confirmed x{conf}" if conf else ""
            cyc = " [CYCLE]" if row.get("is_cycle_reference") else ""
            lines.append(
                f"{indent}[{row['level']}] {row['memory_id']} "
                f"(via {row['via_field']}, {row['resolution_source']}{conf_txt}){cyc}")
        else:
            if row["resolved"]:
                continue  # the node line right after already speaks for it
            tag = "EXTERNAL" if row["external_reference"] else "UNRESOLVED"
            lines.append(f"{indent}-> {row['via_field']} = {row['memory_id']} [{tag}: "
                         f"{row.get('reason') or 'no reason recorded'}]")
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------

def execute_verb(verb: str, *, root_path: Optional[str] = None,
                  memory_id: Optional[str] = None, record_path: Optional[str] = None,
                  as_json: bool = False) -> int:
    """Shared implementation behind the ad hoc CLI and any future `dv-harness`
    wiring. Exit codes: 0 FULLY_RESOLVED, 1 PARTIALLY_RESOLVED,
    2 ROOT_UNAVAILABLE or a usage error."""
    if verb != "lineage":
        print(json.dumps({"error": f"unknown verb {verb!r}; only 'lineage' is supported"}))
        return 2
    if not root_path or not memory_id:
        print(json.dumps({"error": "--root and --memory-id are required"}))
        return 2

    record = None
    if record_path:
        try:
            with open(record_path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"could not read --record file: {exc}"}))
            return 2
        if not isinstance(record, dict):
            print(json.dumps({"error": "--record file must contain a single JSON object"}))
            return 2

    result = build_organizational_lineage(Path(root_path), memory_id, org_record=record)

    if as_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(render_lineage_text(result))

    if result.status == STATUS_FULLY_RESOLVED:
        return 0
    if result.status == STATUS_PARTIALLY_RESOLVED:
        return 1
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.memory_lineage",
        description="Multi-Hop Memory-Promotion Lineage Walker: reconstruct the full "
                    "lineage of an Organizational-tier memory record back through every "
                    "recoverable Engineering-tier confirmation event to the original "
                    "Job-tier evidence, walked recursively via the real "
                    "source_engineering_memory_id / corroborating_memory_ids back-pointers "
                    "this codebase already reads. Read-only throughout -- writes nothing, "
                    "gates nothing, contacts no remote Knowledge Center.")
    ap.add_argument("verb", choices=["lineage"])
    ap.add_argument("--root", dest="root_path", default=None, help="Project root.")
    ap.add_argument("--memory-id", dest="memory_id", default=None,
                    help="The Organizational-tier memory_id (or any tier's, for inspection) "
                         "to reconstruct lineage for.")
    ap.add_argument("--record", dest="record_path", default=None,
                    help="Optional JSON file holding the Organizational-tier record itself "
                         "(a caller-supplied starting point, since that tier has no local "
                         "per-tier JSON file to read back -- see the module docstring).")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    return execute_verb(a.verb, root_path=a.root_path, memory_id=a.memory_id,
                        record_path=a.record_path, as_json=a.as_json)


if __name__ == "__main__":
    import sys
    sys.exit(main())
