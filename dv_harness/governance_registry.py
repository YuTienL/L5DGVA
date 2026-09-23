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
    a registry entry pointing nowhere is worse than no registry entry."""
    root = Path(root)
    entries = load_registry(root)
    broken = []
    for e in entries:
        for key in ("summary_path", "full_spec_path"):
            p = e.get(key)
            if p and not (root / p).exists():
                broken.append("%s: %s (%s) does not exist" % (e["id"], p, key))
    return ReachabilityResult(broken=broken)
