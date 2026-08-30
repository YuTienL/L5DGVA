from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
from .memory import (
    MemoryStore, CornerCaseLibrary, CornerCaseLibraryConsolidator,
    JobMemoryStore, ProjectMemoryStore, WorkingMemoryStore, OrganizationalMemoryStore,
)
from .blackboard import Blackboard

_STORE_LEVEL = {
    "JOB_MEMORY": "job",
    "PROJECT_MEMORY": "project",
    "ENGINEERING_MEMORY": "engineering",
    "WORKING_MEMORY": "working",
}

# Tier-specific store class for every destination that has one (2026-08-29:
# wires up the previously-dead WorkingMemoryStore/JobMemoryStore/
# ProjectMemoryStore/OrganizationalMemoryStore -- see dv_harness/memory.py's
# _TierMemoryStore comment). ENGINEERING_MEMORY deliberately has no entry:
# by design (memory.py's comment above WorkingMemoryStore et al.) it gets a
# dedicated write-path via MemoryConsolidator for the strict single_sim+
# regression+reaudit-validated route, and the plain base MemoryStore for the
# lighter-weight "debug lesson" route below -- no tier wrapper class was
# ever written for it and adding one now would just be a second name for
# the same `MemoryStore(root).add("engineering", record)` call already used
# both here and in MemoryConsolidator. ORGANIZATIONAL_MEMORY is handled in
# its own branch below (its constructor/return shape differ from the other
# three -- see there), not through this generic per-level dispatch.
_TIER_STORE_CLASSES = {
    "JOB_MEMORY": JobMemoryStore,
    "PROJECT_MEMORY": ProjectMemoryStore,
    "WORKING_MEMORY": WorkingMemoryStore,
}

# Destinations eligible for an ADDITIONAL best-effort push to the shared,
# cross-user Linux-server knowledge center (dv_harness/knowledge_center.py),
# on top of (never instead of) the local write above. BLACKBOARD is
# deliberately excluded: CLAUDE.md defines Blackboard as "current
# verification truth" for THIS run, distinct from Memory's "prior
# knowledge" -- sharing it across users/projects would let one user's
# current-run state leak into another's as if it were their own, which is
# exactly what the Evidence Truth Rule exists to prevent. JOB/PROJECT/
# WORKING memory are also excluded: they are inherently per-run/per-project
# scoped, not generalizable knowledge. ORGANIZATIONAL_MEMORY is excluded
# here too (2026-08-29) -- it no longer has a separate local write to
# additionally share: its branch below writes straight to
# OrganizationalMemoryStore/KnowledgeCenterClient, which IS the push.
_SHAREABLE_DESTINATIONS = {"ENGINEERING_MEMORY", "CORNER_CASE_LIBRARY"}


def route_and_store(root: Path, record: Dict[str, Any], cfg: Dict[str, Any] = None) -> Dict[str, Any]:
    """The actual entry point route_memory() was missing: takes a raw
    "New Knowledge" record, routes it via route_memory(), and persists it to
    wherever it belongs. Nothing in the codebase called route_memory() before
    this -- callers (e.g. MemoryConsolidator) wrote straight to a hardcoded
    MemoryStore level, bypassing the router entirely.

    `cfg` (optional, the harness's loaded .dv-harness/config.json) enables an
    ADDITIONAL best-effort push to the shared knowledge center when the
    local write lands on a shareable destination -- see
    _SHAREABLE_DESTINATIONS. Omitting `cfg` (or leaving knowledge_center
    disabled in it) makes this function behave exactly as before this
    feature: local-only, no network activity, no behavior change."""
    destination = route_memory(record)
    if destination == "REJECT":
        raise ValueError("route_memory: record rejected (credential/secret-like kind), not persisted")
    if destination == "BLACKBOARD":
        topic = record.get("topic") or f"working/{record.get('kind','unknown')}"
        Blackboard(root).write(topic, record.get("value", record), source="memory_router")
        return {"destination": destination, "topic": topic}
    if destination == "CLAUDE_PROJECT_MEMORY":
        # Claude's own project/native memory is written by Claude Code itself
        # (files under its memory/ directory), not by this Python process --
        # route_and_store cannot write it directly. Surface the routing
        # decision so the calling agent knows to persist it that way instead
        # of silently dropping it.
        return {"destination": destination, "action": "SURFACE_TO_CLAUDE_PROJECT_MEMORY", "record": record}
    if destination == "CORNER_CASE_LIBRARY":
        corner_case = record.get("corner_case", record)
        resolution = record.get("resolution", {})
        entry = CornerCaseLibraryConsolidator(CornerCaseLibrary(root)).from_resolved_corner_case(
            corner_case, resolution)
        result = {"destination": destination, "ccl_id": entry["ccl_id"]}
        shared = _maybe_share(root, cfg, destination, entry.get("category"), entry.get("protocol"), entry)
        if shared is not None:
            result["shared_push"] = shared
        return result
    if destination == "ORGANIZATIONAL_MEMORY":
        # Unlike the other four levels, organizational memory has no local
        # `.dv-harness/memory/organizational/` file store of its own by
        # design (see memory.py's OrganizationalMemoryStore comment): its
        # only real backing store IS the shared, cross-user Knowledge
        # Center. Route straight to it instead of falling into the generic
        # MemoryStore(root).add("organizational", record) dispatch below,
        # which used to write a local file that nothing else ever read and
        # that duplicated/contradicted this exact design decision.
        push = OrganizationalMemoryStore(root, cfg=cfg).add(record)
        return {"destination": destination, **push}
    tier_cls = _TIER_STORE_CLASSES.get(destination)
    if tier_cls is not None:
        mem = tier_cls(root).add(record)
    else:
        mem = MemoryStore(root).add(_STORE_LEVEL[destination], record)
    result = {"destination": destination, "level": mem["level"], "memory_id": mem["memory_id"]}
    if destination in _SHAREABLE_DESTINATIONS:
        shared = _maybe_share(root, cfg, destination, "_general", mem.get("protocol") or "_general", mem)
        if shared is not None:
            result["shared_push"] = shared
    return result


def _maybe_share(root: Path, cfg, destination: str, category, protocol, record: Dict[str, Any]):
    if not cfg:
        return None
    try:
        from .knowledge_center import maybe_push_to_shared
        return maybe_push_to_shared(cfg, root, destination, category or "_general",
                                     protocol or "_general", record)
    except Exception as exc:  # pragma: no cover - a shared-push failure must never break the local write
        return {"ok": False, "error": "SHARE_FAILED", "detail": str(exc)}


def route_memory(record: Dict[str, Any]) -> str:
    kind = str(record.get("kind","")).lower()
    verified = bool(record.get("verified", False))
    scope = str(record.get("scope","")).lower()

    if kind in ("credential","password","token","secret"):
        return "REJECT"

    if kind in ("project_instruction","coding_convention","workflow_rule","user_preference"):
        return "CLAUDE_PROJECT_MEMORY"

    if kind in ("current_state","active_hypothesis","graph_state","plan_state"):
        return "BLACKBOARD"

    if kind in ("job_result","job_failure","job_rerun"):
        return "JOB_MEMORY"

    if kind in ("project_fact","project_topology","tool_flow","known_issue") and verified:
        return "PROJECT_MEMORY"

    if kind in ("root_cause","verified_fix","debug_lesson") and verified:
        return "ENGINEERING_MEMORY"

    if kind in ("cross_project_lesson","methodology","best_practice") and verified:
        return "ORGANIZATIONAL_MEMORY"

    if kind == "corner_case" and verified:
        return "CORNER_CASE_LIBRARY"

    return "WORKING_MEMORY"
