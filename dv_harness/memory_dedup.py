"""Knowledge deduplication for the DV-Knowledge Vault (Phase 18 of the
Obsidian+Git/Markdown Hybrid Engineering Memory spec, Workstream 2).

Before writing a new Engineering/Organizational vault note, computes a
fingerprint from the 5 structured fields the spec names --
{protocol, failure_signature, root_cause, configuration, error_pattern} --
and compares it against every existing Engineering/Organizational note's
same fields, classifying the candidate as one of:

  NEW              -- no meaningfully similar existing note.
  RELATED          -- some overlap, but not the same underlying issue.
  UPDATE_EXISTING  -- same protocol + root cause, but a different
                      configuration/error signature -- this looks like the
                      SAME root cause showing up under new circumstances,
                      which the existing note should be extended to cover
                      rather than duplicated.
  DUPLICATE        -- effectively the same claim already on file.

Two real callers, both BEFORE a note is written: the manual
`dv-harness memory add` verb (cli.py -- refuses a DUPLICATE unless
`--force`) and, since 2026-09-04, the automatic ENGINEERING_MEMORY/
ORGANIZATIONAL_MEMORY vault write-through the engine's own promotion flow
uses (`memory_router._maybe_write_vault_note()`, which folds a DUPLICATE/
UPDATE_EXISTING candidate into the note already on file instead of minting
a second one). The automatic path had been the ONLY populated path in this
project and had never run this gate, which is precisely how the spec's
`USB3_LFPS_issue1/issue2/issue3` shape stays reachable in production.

Deliberately NO embedding/vector database, per the spec's own instruction
that string/set-based similarity on these 5 structured fields is sufficient
here -- this reuses memory.py's existing stopword-aware tokenizer (`_tok`)
for a real, inspectable Jaccard-similarity comparison, the same convention
memory_vault.py's own search() already established for this codebase.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .memory import _tok as _tokenize
from . import memory_vault as mv

# The 5 fields the spec names, exactly.
FINGERPRINT_FIELDS = ["protocol", "failure_signature", "root_cause", "configuration", "error_pattern"]

# Similarity weights for the 4 content fields (protocol is used as a hard
# gate below, not a weighted similarity component -- a different protocol is
# a different knowledge domain full stop, never "a little bit similar").
# root_cause and failure_signature carry the most identifying weight (the
# actual "what went wrong"); configuration/error_pattern are secondary
# distinguishing detail. Simple, fixed, inspectable weights -- not a learned
# model -- matching the spec's explicit "do not over-build this" guidance.
FIELD_WEIGHTS = {
    "failure_signature": 0.30,
    "root_cause": 0.35,
    "configuration": 0.15,
    "error_pattern": 0.20,
}

# The memory tiers this gate compares against. Working/Job/Project are
# excluded on purpose -- see _iter_dedup_scope_notes() below.
DEDUP_SCOPE_MEMORY_LEVELS = ("engineering", "organizational")

# Thresholds, likewise fixed/inspectable rather than tuned/learned.
DUPLICATE_THRESHOLD = 0.90
UPDATE_EXISTING_ROOT_CAUSE_THRESHOLD = 0.80
RELATED_THRESHOLD = 0.35


def _normalize(value: Any) -> str:
    return " ".join(sorted(_tokenize(value)))


def compute_fingerprint(record: Dict[str, Any]) -> Dict[str, Any]:
    """Real, inspectable fingerprint from the 5 structured fields: normalized
    token sets per field (for similarity scoring) plus one exact-match SHA256
    hash over all 5 normalized fields together (for a fast identical-claim
    short-circuit -- two records that tokenize to the exact same content in
    every field, in any word order, hash identically)."""
    fields = {f: record.get(f) for f in FINGERPRINT_FIELDS}
    tokens: Dict[str, Set[str]] = {f: _tokenize(v) for f, v in fields.items()}
    normalized = {f: _normalize(v) for f, v in fields.items()}
    exact_key = "|".join(normalized.get(f, "") for f in FINGERPRINT_FIELDS)
    exact_hash = hashlib.sha256(exact_key.encode("utf-8")).hexdigest()
    return {"fields": fields, "tokens": tokens, "normalized": normalized, "hash": exact_hash}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    # Both empty is treated as "no signal", not "perfect match" -- two
    # records that both simply omit a field are not thereby similar in that
    # field; scoring that as 1.0 would let sparse candidates falsely
    # inflate into DUPLICATE/UPDATE_EXISTING against equally-sparse notes.
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def extract_note_fields(frontmatter: Dict[str, Any], sections: Dict[str, str]) -> Dict[str, Any]:
    """Maps a real vault note's frontmatter/body sections onto the same 5
    fingerprint fields memory_router.build_sections_from_memory_record()
    populates them from, so a note produced by the real ENGINEERING_MEMORY/
    ORGANIZATIONAL_MEMORY write-through and a fresh `memory add` candidate
    are compared on genuinely like-for-like data:
      failure_signature <- frontmatter.failure
      root_cause        <- body "Root Cause" section
      configuration     <- body "Context" section (built from record.scope)
      error_pattern     <- body "Symptom" section (built from record.symptoms)

    Public because memory_router.py's automatic write-through builds its
    candidate through this exact mapping too (see `_classify_vault_candidate()`
    there) -- candidate and corpus must be derived by ONE function, or the
    gate compares a note against a differently-shaped version of itself."""
    return {
        "protocol": frontmatter.get("protocol"),
        "failure_signature": frontmatter.get("failure"),
        "root_cause": sections.get("Root Cause"),
        "configuration": sections.get("Context"),
        "error_pattern": sections.get("Symptom"),
    }


def _similarity(fp_a: Dict[str, Any], fp_b: Dict[str, Any]) -> Dict[str, Any]:
    per_field = {}
    weighted_sum = 0.0
    weight_total = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        sim = _jaccard(fp_a["tokens"].get(field, set()), fp_b["tokens"].get(field, set()))
        per_field[field] = sim
        weighted_sum += sim * weight
        weight_total += weight
    overall = weighted_sum / weight_total if weight_total else 0.0
    return {"overall": overall, "per_field": per_field}


def _iter_dedup_scope_notes(vault_path: Path, memory_levels: Optional[Sequence[str]] = None):
    """Engineering + Organizational note files only -- Working/Job/Project
    tiers are inherently per-run/per-project scoped, not generalizable
    knowledge this dedup gate needs to protect. Folder names come from
    memory_vault's own `_MEMORY_LEVEL_FOLDER` rather than a second copy of
    the vault layout kept in sync by hand.

    `memory_levels` narrows that scope to specific tiers (see
    classify_note_candidate's own parameter)."""
    levels = [str(x).lower() for x in (memory_levels or DEDUP_SCOPE_MEMORY_LEVELS)]
    for level in levels:
        sub = mv._MEMORY_LEVEL_FOLDER.get(level)
        if sub is None:
            continue
        d = vault_path / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            yield p


def classify_note_candidate(root: Path, candidate: Dict[str, Any],
                             cfg: Optional[Dict[str, Any]] = None,
                             exclude_note_id: Optional[str] = None,
                             memory_levels: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Phase 18's real entry point: classify `candidate` (a dict carrying
    any/all of FINGERPRINT_FIELDS) against real existing vault notes as
    NEW/RELATED/DUPLICATE/UPDATE_EXISTING, BEFORE it is written.

    A candidate's `protocol` (when given) is a hard gate, not a weighted
    similarity component: a note whose own `protocol` differs is skipped
    entirely, regardless of how similar the other 4 fields happen to be --
    a different protocol is a different knowledge domain. A candidate with
    no protocol given compares broadly against every note (no gate applied).

    `exclude_note_id`: skip this note id when comparing (for the "does an
    already-written note still look like a duplicate of some OTHER note"
    case, e.g. a future `memory validate` self-check -- not used by `memory
    add`, which by definition compares a not-yet-written candidate against
    everything).

    `memory_levels`: restrict the comparison corpus to those tiers (default:
    both DEDUP_SCOPE_MEMORY_LEVELS). memory_router.py's automatic
    write-through passes the candidate's OWN tier, because an
    Engineering -> Organizational promotion writes the same knowledge a
    second time BY DESIGN: compared across tiers it is a textbook DUPLICATE
    of its own engineering note, and folding it there would make the
    Organizational tier unwritable. Within a tier, that same comparison is
    exactly the duplicate this gate exists to stop."""
    fp = compute_fingerprint(candidate)
    candidate_protocol = str(candidate.get("protocol") or "").strip().lower()

    vault_path = mv.resolve_vault_path(root, cfg)
    mv.bootstrap_vault(vault_path)

    matches: List[Dict[str, Any]] = []
    for p in _iter_dedup_scope_notes(vault_path, memory_levels):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = mv.parse_note_markdown(text)
        note_id = frontmatter.get("id") or p.stem
        if exclude_note_id and note_id == exclude_note_id:
            continue
        note_protocol = str(frontmatter.get("protocol") or "").strip().lower()
        if candidate_protocol and note_protocol and note_protocol != candidate_protocol:
            continue
        sections = mv._body_to_sections(body)
        note_fields = extract_note_fields(frontmatter, sections)
        note_fp = compute_fingerprint(note_fields)
        sim = _similarity(fp, note_fp)
        matches.append({
            "note_id": note_id,
            "path": str(p.relative_to(vault_path)),
            "exact_hash_match": note_fp["hash"] == fp["hash"],
            "similarity": sim["overall"],
            "per_field_similarity": sim["per_field"],
        })

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    best = matches[0] if matches else None
    classification = _classify(best)

    return {
        "classification": classification,
        "fingerprint": fp,
        "candidate_count_compared": len(matches),
        "matches": matches[:10],
        "best_match": best,
    }


def _classify(best: Optional[Dict[str, Any]]) -> str:
    if best is None:
        return "NEW"
    if best["exact_hash_match"] or best["similarity"] >= DUPLICATE_THRESHOLD:
        return "DUPLICATE"
    if (best["per_field_similarity"].get("root_cause", 0.0) >= UPDATE_EXISTING_ROOT_CAUSE_THRESHOLD
            and best["similarity"] < DUPLICATE_THRESHOLD):
        return "UPDATE_EXISTING"
    if best["similarity"] >= RELATED_THRESHOLD:
        return "RELATED"
    return "NEW"
