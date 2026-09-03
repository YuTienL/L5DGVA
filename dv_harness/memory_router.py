from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
from .memory import (
    MemoryStore, MemoryGC, CornerCaseLibrary, CornerCaseLibraryConsolidator,
    JobMemoryStore, ProjectMemoryStore, WorkingMemoryStore, OrganizationalMemoryStore,
)
from .blackboard import Blackboard

# Organizational promotion's "repeated confirmation" bar (Phase 5/6 wiring,
# 2026-09-03 -- see promote_to_organizational() below). Not user-configurable
# today: this is a hard-coded minimum independent-reconfirmation count, not a
# per-project policy knob, matching how MemoryConsolidator.from_closed_finding's
# single_sim/regression/reaudit gate is also unconditional.
ORGANIZATIONAL_MIN_CONFIRMATIONS = 2

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
    _SHAREABLE_DESTINATIONS. Leaving knowledge_center disabled in it makes
    this function behave exactly as before this feature: local-only, no
    network activity, no behavior change.

    REAL BUG FIX (2026-09-02, found live): `cfg` used to default to None,
    and a None cfg made `_maybe_share()` silently return None (no push
    attempted) with no error, no warning, nothing -- indistinguishable
    from "shared push attempted and vacuously nothing to share". Two
    one-off Engineering Memory persistence scripts this session called
    `route_and_store(root, record)` without cfg, wrote successfully to the
    LOCAL store, and silently never reached the shared Knowledge Center --
    caught only by manually diffing the remote store's file listing
    against local memory IDs. Every real engine.py call site already
    passed `cfg=self.cfg` explicitly and was unaffected, but nothing
    stopped a future one-off script (or a future engine call site) from
    making the exact same mistake with the exact same silent-no-op result.
    Auto-load the project's real config when the caller omits `cfg`, so
    "did I remember to pass cfg" is no longer a silent failure mode --
    a caller that explicitly wants local-only behavior can still pass
    `cfg={}`."""
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)
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
        result = {"destination": destination, **push}
        # Vault write-through (obsidian-memory-core, 2026-09-03): additive
        # only, and only attempted once the shared push itself actually
        # succeeded -- an "ok": False (e.g. NOT_CONFIGURED) push never had a
        # real promotion happen, so there is nothing yet worth mirroring
        # into the vault. See _maybe_write_vault_note()'s own docstring for
        # why a vault-write failure can never affect this result otherwise.
        if push.get("ok"):
            vault = _maybe_write_vault_note(root, cfg, destination, {**record, **push})
            if vault is not None:
                result["vault_write"] = vault
        return result
    if destination == "ENGINEERING_MEMORY":
        mem, confirmed_existing = _add_or_confirm_engineering(root, record)
        result = {"destination": destination, "level": mem["level"], "memory_id": mem["memory_id"]}
        if confirmed_existing:
            result["confirmed_existing"] = True
        shared = _maybe_share(root, cfg, destination, "_general", mem.get("protocol") or "_general", mem)
        if shared is not None:
            result["shared_push"] = shared
        vault = _maybe_write_vault_note(root, cfg, destination, mem)
        if vault is not None:
            result["vault_write"] = vault
        return result
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


def _add_or_confirm_engineering(root: Path, record: Dict[str, Any]):
    """ENGINEERING_MEMORY write path, extended (2026-09-03) to actually
    increment confirmation_count/last_confirmed_at -- real fields that
    existed on every MemoryStore record (memory.py's `add()`) with a real
    setter (`MemoryGC.confirm()`) but ZERO real call sites anywhere in this
    codebase before this (verified by full-repo grep: `client.confirm(...)`
    in cli.py is KnowledgeCenterClient.confirm, an unrelated shared-store
    concept). The natural, real trigger for "an independent later run
    re-derived the SAME conclusion" -- exactly what MemoryGC.confirm()'s own
    docstring describes -- is a SECOND route_and_store() call landing on an
    ACTIVE engineering-tier record with the same protocol and root_cause: as
    designed, that is not a new finding, it is the same one being
    reconfirmed. When no such match exists (including every record that
    simply doesn't carry both `protocol` and `root_cause`, e.g. today's real
    engine.py verified_fix records -- see this function's own limitation
    note below), behavior is byte-for-byte identical to before this change:
    a fresh MemoryStore.add("engineering", record) every time.

    KNOWN LIMITATION (honestly scoped, not silently glossed over): matching
    requires both fields present and is exact-string (case-insensitive on
    root_cause only), by design -- no fuzzy matching, consistent with this
    codebase's existing text-matching conventions (memory.py's `_tok`
    comment). engine.py's `_promote_verified_fix_knowledge()` does not
    currently populate `protocol` on its record, so this dedup path is real
    and tested but not yet reachable from that specific production call
    site -- a real, separately-scoped follow-up (adding `protocol` to that
    record), not something this module can fix without touching engine.py's
    own promotion-record construction.
    """
    store = MemoryStore(root)
    match_id = _find_confirming_engineering_match(store, record)
    if match_id is not None:
        MemoryGC(store).confirm(match_id, evidence=record.get("evidence"))
        return store.get(match_id), True
    return store.add("engineering", record), False


def _find_confirming_engineering_match(store: MemoryStore, record: Dict[str, Any]) -> Optional[str]:
    protocol = record.get("protocol")
    root_cause = record.get("root_cause")
    if not protocol or not root_cause:
        return None
    norm_rc = str(root_cause).strip().lower()
    norm_protocol = str(protocol).strip()
    for row in store._index():
        if row.get("level") != "engineering" or row.get("status") != "ACTIVE":
            continue
        if str(row.get("protocol") or "").strip() != norm_protocol:
            continue
        if str(row.get("root_cause") or "").strip().lower() != norm_rc:
            continue
        return row.get("memory_id")
    return None


def _maybe_write_vault_note(root: Path, cfg, destination: str, mem: Dict[str, Any]):
    """ADDITIVE write-through (obsidian-memory-core, 2026-09-03): mirrors an
    ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion into a real
    Markdown+YAML note in the DV-Knowledge Vault (dv_harness/memory_vault.py),
    via HybridMemoryProvider -- Obsidian used opportunistically if/when its
    own status() ever reports READY, the real FileSystemMarkdownAdapter
    otherwise (today, always). Gated on `cfg` exactly like `_maybe_share()`
    above (an explicit `cfg={}` opts out of every cfg-driven additive
    behavior this router has, not just shared-knowledge-center push) so a
    caller wanting pre-this-feature local-only behavior still gets it.

    A vault-write failure must NEVER affect the local JSON write this
    function is called after -- same non-negotiable ordering `_maybe_share`
    already establishes for the shared-knowledge-center push, now applied to
    the vault too."""
    if not cfg:
        return None
    try:
        from . import memory_vault as mv
        provider = mv.get_active_provider(root, cfg)
        project_name = None
        try:
            import json as _json
            project_json = Path(root) / ".dv-harness" / "project.json"
            if project_json.exists():
                project_name = (_json.loads(project_json.read_text(encoding="utf-8")) or {}).get("project")
        except Exception:
            project_name = None
        frontmatter = mv.build_frontmatter_from_memory_record(destination, mem, project_name=project_name)
        sections = mv.build_sections_from_memory_record(mem)
        note_id = frontmatter["id"]
        existing = provider.read(note_id)
        if existing.get("ok"):
            return provider.update(note_id, frontmatter_patch=frontmatter, sections_patch=sections)
        result = provider.create(frontmatter, sections=sections)
        if not result.get("ok") and result.get("error") == "ALREADY_EXISTS":
            return provider.update(note_id, frontmatter_patch=frontmatter, sections_patch=sections)
        return result
    except Exception as exc:  # pragma: no cover - a vault-write failure must never break the local write
        return {"ok": False, "error": "VAULT_WRITE_FAILED", "detail": str(exc)}


def promote_to_organizational(root: Path, memory_id: str, confidence_inputs: Dict[str, Any],
                               cfg: Dict[str, Any] = None, kind: str = "methodology") -> Dict[str, Any]:
    """Phase 5/6 promotion gate: Engineering -> Organizational Memory. The
    ONE place a record may cross that boundary -- grounds the user's Phase 5
    spec ("must NOT let unverified hypotheses or single-PASS results jump
    straight to Organizational") in the REAL existing confidence framework
    rather than a new parallel one, per the same spec's explicit
    instruction. Three independent, all-required gates, cheapest/most
    likely to fail first:

    1. QUALITATIVE HARD PRECONDITION (memory-consolidation skill's existing
       policy -- "只有 CLOSED/VERIFIED + single PASS + regression
       PASS/NOT_REQUIRED + re-audit CLEAN 才 promotion" -- made real here,
       not merely trusted from whenever the record first reached the
       engineering tier). Re-checked HERE, not assumed from tier membership,
       because this codebase's real engineering-tier records reach that
       tier via TWO structurally different write paths with two different
       verification-evidence vocabularies, and a plain route_and_store()
       kind="root_cause"/"debug_lesson" call never validates either shape at
       write time:
         (a) MemoryConsolidator.from_closed_finding()'s shape:
             verification={"single_sim":"PASS",
             "regression":"PASS"|"NOT_REQUIRED","reaudit":"CLEAN"}.
         (b) engine.py's _promote_verified_fix_knowledge() RE_AUDIT-gate
             shape: verification={"targeted_reproducer_passed":True,
             "broader_regression_passed":True,"new_failures_introduced":False,
             "target_pre_fix_result":"FAIL","target_post_fix_result":"PASS",
             "replay_equivalent":True} -- independently gate-verified by
             fix_effectiveness_gate/fix_regression_non_regression_gate
             before that record is ever created.
       See _verification_is_gate_validated() below -- recognizes both real
       shapes, invents no third canonical one neither real write path uses.
    2. QUANTITATIVE SCORE: inference.score_confidence() (the exact function
       the user's Phase 5 spec names as the required quantitative input,
       not a new scoring system) on caller-supplied `confidence_inputs`
       (independent_sources_count/evidence_refs_verified/
       counter_evidence_count/multi_agent_consensus_count -- only the
       caller, e.g. the future Memory Agent, knows these at promotion time).
       Requires level=="HIGH", the same bar inference.promote_if_high_confidence()
       already uses for the Engineering->shared-KC push.
    3. REPEATED CONFIRMATION: `confirmation_count` (real field, now really
       incremented -- see _add_or_confirm_engineering() above) must be >=
       ORGANIZATIONAL_MIN_CONFIRMATIONS. CLAUDE.md: "any current root cause
       must be revalidated with current evidence" -- one creation event is
       not revalidation.

    Never raises for an ordinary gate miss (MEDIUM/LOW confidence,
    insufficient confirmation, a non-CONFIRMED source record are all
    expected, common outcomes) -- only for a genuine caller error (an
    unknown memory_id). On success, delegates the actual write to
    route_and_store() (kind defaults to "methodology"; pass
    kind="best_practice"/"cross_project_lesson" for those cases) so every
    existing ORGANIZATIONAL_MEMORY routing/sharing/vault-write-through
    behavior above applies unchanged -- this function only decides WHETHER
    to call it.
    """
    from .inference import score_confidence

    store = MemoryStore(root)
    mem = store.get(memory_id)
    if mem is None:
        raise ValueError(f"no such memory_id: {memory_id}")
    if mem.get("level") != "engineering":
        return {"promoted": False, "reason": "NOT_ENGINEERING_TIER", "level": mem.get("level")}
    if mem.get("status") != "ACTIVE":
        return {"promoted": False, "reason": "NOT_ACTIVE", "status": mem.get("status")}

    gate_ok, gate_shape = _verification_is_gate_validated(mem)
    if not gate_ok:
        return {"promoted": False, "reason": "QUALITATIVE_GATE_FAILED", "detail": gate_shape}

    confidence_result = score_confidence(**confidence_inputs)
    if confidence_result.get("level") != "HIGH":
        return {"promoted": False, "reason": "CONFIDENCE_NOT_HIGH", "confidence_result": confidence_result}

    confirmation_count = int(mem.get("confirmation_count", 0))
    if confirmation_count < ORGANIZATIONAL_MIN_CONFIRMATIONS:
        return {
            "promoted": False, "reason": "INSUFFICIENT_CONFIRMATION",
            "confirmation_count": confirmation_count, "required": ORGANIZATIONAL_MIN_CONFIRMATIONS,
        }

    record = {
        "kind": kind, "verified": True,
        "title": mem.get("title"), "protocol": mem.get("protocol"), "scope": mem.get("scope"),
        "root_cause": mem.get("root_cause"), "fix": mem.get("fix"),
        "symptoms": mem.get("symptoms", []), "evidence": mem.get("evidence"),
        "verification": mem.get("verification"), "confidence_result": confidence_result,
        "confirmation_count": confirmation_count,
        "source_engineering_memory_id": memory_id,
    }
    result = route_and_store(root, record, cfg=cfg)
    result["promotion_gate"] = {
        "qualitative_shape": gate_shape, "confidence_result": confidence_result,
        "confirmation_count": confirmation_count,
    }
    return result


def _verification_is_gate_validated(mem: Dict[str, Any]):
    v = mem.get("verification") or {}
    if (v.get("single_sim") == "PASS"
            and v.get("regression") in ("PASS", "NOT_REQUIRED")
            and v.get("reaudit") == "CLEAN"):
        return True, "finding_consolidation_shape"
    if (v.get("targeted_reproducer_passed") is True
            and v.get("broader_regression_passed") is True
            and v.get("new_failures_introduced") is False
            and v.get("target_pre_fix_result") == "FAIL"
            and v.get("target_post_fix_result") == "PASS"
            and v.get("replay_equivalent") is True):
        return True, "re_audit_gate_shape"
    return False, "NEITHER_KNOWN_VERIFICATION_SHAPE_SATISFIED"


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

    # react.py's ReactRecorder pushes one of these per outer stage attempt
    # (memory-engine-schema-completion audit, 2026-09-01) -- see
    # react.py's ReactRecorder._write_working_memory_tier_record docstring.
    # An explicit branch (rather than relying on the generic WORKING_MEMORY
    # fallthrough at the bottom of this function) so the real hypothesis/
    # evidence/next-action working-memory contract has a named, documented
    # routing rule instead of an implicit default. Deliberately distinct
    # from "active_hypothesis" above (BLACKBOARD, current-run truth) --
    # a react-loop reasoning step is a durable per-attempt working-memory
    # record, not the graph's current live state.
    if kind == "react_reasoning_step":
        return "WORKING_MEMORY"

    if kind in ("project_fact","project_topology","tool_flow","known_issue") and verified:
        return "PROJECT_MEMORY"

    if kind in ("root_cause","verified_fix","debug_lesson") and verified:
        return "ENGINEERING_MEMORY"

    if kind in ("cross_project_lesson","methodology","best_practice") and verified:
        return "ORGANIZATIONAL_MEMORY"

    if kind == "corner_case" and verified:
        return "CORNER_CASE_LIBRARY"

    return "WORKING_MEMORY"
