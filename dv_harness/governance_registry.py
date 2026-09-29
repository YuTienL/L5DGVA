"""TASK_SCOPED_GOVERNANCE_RETRIEVAL — the canonical governance-document
registry (M4.5 governance-context requirement).

CLAUDE.md must remain a compact, ALWAYS-ON router/governance document —
this module is what lets it stay that way while the canonical repository
accumulates real, large, task-specific governance material (protocol
contracts, migration evidence, historical audit reports, and above all the
25-document/106,132-line Parent-only "L5DGVA governing contract" corpus
found during M4) without appending any of it into CLAUDE.md itself.

Distinct from, and deliberately not merged into, `dv_harness/context_budget.py`:
that module's schema (`rule_id`/`path_globs`/`distiller`) is shaped for
DUT/VIP *evidence content* blocked by file-glob pattern — checked directly
against it before writing this module, and confirmed genuinely different
in shape and purpose. This module is shaped for *governance/knowledge
documents* routed by concept and trigger, not by file glob:

- `LOAD_POLICY`: `ALWAYS_ON` (CLAUDE.md itself and nothing else — keep this
  set minimal), `TASK_SCOPED` (loaded when the current task's domain
  matches `TRIGGER`), `EVIDENCE_ON_DEMAND` (large source material, loaded
  only for a specific question, never preloaded, never summarized into
  CLAUDE.md).
- `TRIGGER`: a short phrase naming when this document becomes relevant.
- `PRIORITY`: `HIGH`/`MEDIUM`/`LOW` — which `TASK_SCOPED` document to
  prefer when several match the same trigger.
- `TOKEN_CLASS`: a rough size/cost signal (`COMPACT`, `MEDIUM`,
  `LARGE_REFERENCE`, `SOURCE_EVIDENCE_ONLY` — the last one reserved for
  material that must never be read wholesale, only cited/distilled).
- `SUMMARY_PATH` / `FULL_SPEC_PATH`: the short and (optional) long forms.

`MINIMUM_SUFFICIENT_CONTEXT` (Article 0, P3 KNOWLEDGE_DRIVEN): retrieve
only the registry entries a task's trigger actually matches — this module
never itself reads or returns document CONTENT, only routes to a path a
caller then reads deliberately.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REGISTRY_PATH = "dv_harness/governance_registry.json"

LOAD_POLICIES = ("ALWAYS_ON", "TASK_SCOPED", "EVIDENCE_ON_DEMAND")
PRIORITIES = ("HIGH", "MEDIUM", "LOW")
TOKEN_CLASSES = ("COMPACT", "MEDIUM", "LARGE_REFERENCE", "SOURCE_EVIDENCE_ONLY")


def load_registry(root: Path) -> List[Dict[str, Any]]:
    """Real, on-disk load. Raises if the file is missing/malformed --
    a broken registry is a real defect, never silently treated as empty."""
    path = Path(root) / REGISTRY_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["entries"]


def get_entries_by_policy(entries: List[Dict[str, Any]], policy: str) -> List[Dict[str, Any]]:
    return [e for e in entries if e["load_policy"] == policy]


def get_entries_by_trigger(entries: List[Dict[str, Any]], trigger_substring: str) -> List[Dict[str, Any]]:
    """Case-insensitive substring match against each entry's TRIGGER --
    the real routing function a task-scoped retrieval caller uses."""
    needle = trigger_substring.lower()
    return sorted(
        (e for e in entries if needle in e.get("trigger", "").lower()),
        key=lambda e: PRIORITIES.index(e.get("priority", "LOW")) if e.get("priority") in PRIORITIES else 99,
    )


@dataclass(frozen=True)
class ReachabilityResult:
    broken: List[str] = field(default_factory=list)


def check_reachability(root: Path) -> ReachabilityResult:
    """Every SUMMARY_PATH/FULL_SPEC_PATH must resolve to a real file --
    a registry entry pointing nowhere is worse than no registry entry.

    Deliberately narrow, by design: this proves a declared entry's target
    FILE exists, never that a real task's phrasing actually SURFACES that
    entry. GAP-M8-005 (M8 Cohort 3)'s own diagnosis: the other real gap in
    this module was never that -- it was that nothing bridged realistic
    task phrasing to `get_entries_by_trigger()`'s own required literal
    substring. See `resolve_governance_intent()` below for that bridge."""
    root = Path(root)
    entries = load_registry(root)
    broken = []
    for e in entries:
        for key in ("summary_path", "full_spec_path"):
            p = e.get(key)
            if p and not (root / p).exists():
                broken.append("%s: %s (%s) does not exist" % (e["id"], p, key))
    return ReachabilityResult(broken=broken)


# M8 Cohort 3 (CAP-M4.6-002 / GAP-M8-005): word-level tokenizer, the same
# convention dv_harness/memory.py's own `_tok()` already established for
# MemoryRetriever.search()'s "text" query matching -- reused by shape here
# (not imported, since that one is memory.py-private and shaped for its
# own record-field search, not this module's trigger-keyword-bag shape),
# never a competing tokenization scheme.
_GOV_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "and", "or", "in", "on", "with",
    "is", "are", "be", "this", "that", "i", "need", "want", "how", "do",
    "does", "my", "our", "it", "its", "about", "into", "from", "can",
    "please", "help",
}


def _gov_tok(text: str) -> set:
    return {
        w for w in re.split(r"[^a-z0-9]+", str(text or "").lower())
        if len(w) > 1 and w not in _GOV_STOPWORDS
    }


def resolve_governance_intent(root: Path, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Classifies a free-text task description against this project's own
    TASK_SCOPED governance_registry.json entries, returning the best-
    matching entry id or `resolved: False`.

    THE GAP THIS CLOSES (GAP-M8-005 / CAP-M4.6-002, M8 Cohort 3):
    `get_entries_by_trigger()` is a real, callable resolver, but its own
    contract requires the CALLER to already know a literal trigger
    substring -- there was no real bridge from a realistic task's own
    phrasing to that substring, which is the concrete reason
    `validate_authority_execution_graph()` (claude_reference_graph.py) can
    only ever prove 5 hardcoded scopes rather than the full TASK_SCOPED
    population. This function is that bridge, the SAME `{'resolved': ...,
    'evidence': <non-empty string>}` contract shape
    `router.resolve_research_intent()` already uses (Connect Before
    Expand: mirrored, not duplicated infrastructure) -- reusing this
    module's own `load_registry()`/`get_entries_by_policy()`, never a
    second registry, index, or store.

    `evidence['task_description']` is the free-text query. Word-overlap
    scoring (not substring containment) against each TASK_SCOPED entry's
    own space-separated `trigger` keyword bag; the entry with the largest
    overlap wins (ties broken by registry order, deterministic). Zero
    overlap with every entry resolves to `False` -- ambiguity is never
    silently guessed at, matching resolve_research_intent()'s own stated
    preference (a missed match costs one follow-up question; a false
    positive risks surfacing the wrong governance document as if it were
    authoritative)."""
    root = Path(root)
    entries_preload = load_registry(root)  # raises on a missing/malformed
    # registry file -- deliberately NOT caught into a false "resolved:
    # False": a broken/absent registry for the queried root is a real
    # infrastructure defect (the same class check_reachability() already
    # treats as fatal), never the same thing as "no TASK_SCOPED trigger
    # matched this text". The one intentional divergence from
    # resolve_research_intent()'s blanket never-raises contract, which has
    # no equivalent external-file precondition to begin with.
    text = str((evidence or {}).get("task_description") or "").strip()
    if not text:
        return {
            "resolved": False, "registry_id": None, "matched_keywords": [],
            "evidence": "no populated task_description evidence field",
        }
    q_tokens = _gov_tok(text)
    if not q_tokens:
        return {
            "resolved": False, "registry_id": None, "matched_keywords": [],
            "evidence": f"task_description {text!r} produced no real (non-stopword) tokens",
        }
    scored = []
    for e in get_entries_by_policy(entries_preload, "TASK_SCOPED"):
        overlap = q_tokens & _gov_tok(e.get("trigger", ""))
        if overlap:
            scored.append((len(overlap), e["id"], sorted(overlap)))
    if not scored:
        return {
            "resolved": False, "registry_id": None, "matched_keywords": [],
            "evidence": (
                f"no TASK_SCOPED entry's trigger overlapped any token of "
                f"{sorted(q_tokens)}"),
        }
    scored.sort(key=lambda t: -t[0])
    best_count, best_id, best_keywords = scored[0]
    return {
        "resolved": True, "registry_id": best_id, "matched_keywords": best_keywords,
        "evidence": (
            f"resolve_governance_intent matched keyword(s) {best_keywords} "
            f"from task_description against '{best_id}' TASK_SCOPED trigger "
            f"(overlap score {best_count})"),
    }
