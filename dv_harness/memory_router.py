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

# Engineering-tier admission bar (2026-09-03, gap-close-obsidian-memory phase
# 4+5). The confidence vocabulary this codebase already uses -- HIGH is
# inference.score_confidence()'s own top level and the bar
# inference.promote_if_high_confidence() already applies to the Engineering
# -> shared-KC push; CONFIRMED is MemoryConsolidator.from_closed_finding()'s
# own label for a single_sim+regression+reaudit-validated record. No third
# scale is invented here.
ENGINEERING_ADMISSION_CONFIDENCE_LEVELS = ("HIGH", "CONFIRMED")

# Fields any one of which carries the reusable engineering CLAIM of a record.
# A record with none of them is a note about a run, not reusable engineering
# knowledge, regardless of how well evidenced it is.
ENGINEERING_REUSABLE_CLAIM_FIELDS = ("root_cause", "fix", "lesson")

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

# Vault write-through destinations (Phase 13 -- Git Integration, 2026-09-03):
# the user's spec's real commit policy is "NOT on every Working Memory
# update, only on: verified Job result, Project Memory update, Engineering
# Memory promotion, Organizational Memory approval". ENGINEERING_MEMORY and
# ORGANIZATIONAL_MEMORY already write through their own dedicated branches
# below (obsidian-memory-core, 2026-09-03); this set adds the other two named
# destinations to the SAME generic-dispatch branch at the bottom of
# route_and_store() -- WORKING_MEMORY is deliberately absent, satisfying the
# spec's explicit negative ("not on every Working Memory update") by
# construction rather than by a separate check. JOB_MEMORY is "verified" in
# this codebase's own real-evidence sense even though route_memory() itself
# does not gate it on a `verified` flag the way PROJECT_MEMORY/
# ENGINEERING_MEMORY do: the only real writers of a JOB_MEMORY record today
# (lsf_client.py's `_write_job_tier_memory_on_terminal_reconcile`, and this
# workstream's new FAILURE_RECOVERY/RE_AUDIT-fail hook in engine.py) only
# ever fire from a real, already-reconciled LSF/gate fact, never a guess.
_VAULT_WRITE_THROUGH_DESTINATIONS = {"JOB_MEMORY", "PROJECT_MEMORY"}

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
        admitted, admission_reasons = engineering_admission_gate(record)
        if not admitted:
            # CLAUDE.md's Engineering Memory Policy, made real code rather
            # than trusted prose: "Promote an unverified hypothesis straight
            # to Engineering or Organizational Memory -- it belongs in
            # Working Memory ... until it clears verification." Demote rather
            # than raise or drop: the record is real content someone wanted
            # kept, it just has not earned engineering-tier reusability, and
            # every route_and_store() caller in the engine treats an
            # exception here as a promotion failure it then has to report.
            demoted = WorkingMemoryStore(root).add({
                **record,
                "engineering_admission_rejected": admission_reasons,
                "requested_destination": "ENGINEERING_MEMORY",
            })
            return {
                "destination": "WORKING_MEMORY", "level": demoted["level"],
                "memory_id": demoted["memory_id"],
                "requested_destination": "ENGINEERING_MEMORY",
                "engineering_admission": {"admitted": False, "reasons": admission_reasons},
            }
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
            _write_back_knowledge_commit_sha(root, mem, vault)
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
    # Phase 13 -- Git Integration: JOB_MEMORY ("verified Job result") and
    # PROJECT_MEMORY ("Project Memory update") vault write-through -- see
    # _VAULT_WRITE_THROUGH_DESTINATIONS' own comment above for why
    # WORKING_MEMORY never reaches this branch.
    if destination in _VAULT_WRITE_THROUGH_DESTINATIONS:
        vault = _maybe_write_vault_note(root, cfg, destination, mem)
        if vault is not None:
            result["vault_write"] = vault
            _write_back_knowledge_commit_sha(root, mem, vault)
    return result


def engineering_admission_gate(record: Dict[str, Any]):
    """The (Working/Project) -> Engineering tier boundary's real gate --
    the counterpart, one tier down, of promote_to_organizational()'s
    three-gate Engineering -> Organizational bar (2026-09-03,
    gap-close-obsidian-memory phase 4+5).

    THE GAP THIS CLOSES, confirmed live before it was written: route_memory()
    routes any record whose `kind` is root_cause/verified_fix/debug_lesson and
    whose `verified` flag is True straight to ENGINEERING_MEMORY. `verified`
    is a plain caller-supplied boolean -- nothing re-derived it, and nothing
    else was checked at write time. A record reading
    {"kind": "root_cause", "verified": True, "root_cause": "unverified
    guess", "verification": {}} therefore landed in the engineering tier and
    was only ever rejected LATER, at the organizational gate. Everything
    downstream that treats engineering-tier membership as meaning "verified
    reusable engineering knowledge" (MemoryRetriever.search() results fed into
    stage prompts, _maybe_share()'s push to the cross-user Knowledge Center,
    the vault's Engineering/ note folder) inherited that unearned status.

    Three all-required gates, mirroring the spec's own
    confidence/evidence/reusable wording and reusing this module's existing
    machinery rather than inventing parallel checks:

    1. EVIDENCE: real `evidence` content, OR a verification block in one of
       the two shapes an independent gate script actually produces
       (_verification_is_gate_validated() -- the SAME function the
       organizational gate uses, not a second, looser copy). This is the gate
       the "unverified guess" case above fails.
    2. CONFIDENCE: `confidence` at HIGH/CONFIRMED
       (ENGINEERING_ADMISSION_CONFIDENCE_LEVELS), or -- equivalently and by
       construction stronger -- a gate-validated verification block, which is
       independently gate-script-verified evidence rather than a
       self-declared confidence label. engine.py's two real engineering-tier
       promotion call sites (_promote_experience_knowledge,
       _promote_verified_fix_knowledge) both already set "HIGH" explicitly.
    3. REUSABLE: `reusable` not explicitly False, AND at least one
       ENGINEERING_REUSABLE_CLAIM_FIELDS value present -- a record with
       neither a root cause nor a fix nor a lesson has nothing for a future
       run to reuse, whatever its evidence.

    Returns (admitted, reasons) -- reasons is a list of stable reason codes,
    empty when admitted, and is persisted onto the demoted Working Memory
    record by route_and_store() so a reader can see exactly what was missing.
    """
    reasons = []

    gate_validated, _shape = _verification_is_gate_validated(record)

    evidence = record.get("evidence")
    if isinstance(evidence, str):
        has_evidence = bool(evidence.strip())
    else:
        has_evidence = bool(evidence)
    if not has_evidence and not gate_validated:
        reasons.append("NO_EVIDENCE")

    confidence = str(record.get("confidence") or "").strip().upper()
    if confidence not in ENGINEERING_ADMISSION_CONFIDENCE_LEVELS and not gate_validated:
        reasons.append("CONFIDENCE_BELOW_HIGH")

    if record.get("reusable") is False:
        reasons.append("EXPLICITLY_NOT_REUSABLE")
    elif not any(str(record.get(f) or "").strip() for f in ENGINEERING_REUSABLE_CLAIM_FIELDS):
        reasons.append("NO_REUSABLE_CLAIM")

    return (not reasons), reasons


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


# Phase 13 -- Git Integration commit-message policy: `memory(<protocol>):
# <short description>`, exactly the format the user's spec names. A record
# with no real protocol (e.g. a JOB_MEMORY reconcile record before this
# workstream's engine.py FAILURE_RECOVERY hook adds one) falls back to
# "_general", matching this router's own existing "_general" convention for
# an absent protocol elsewhere (_maybe_share's category/protocol args
# above) -- never a fabricated protocol name.
def _build_vault_commit_message(mem: Dict[str, Any]) -> str:
    protocol = mem.get("protocol") or "_general"
    desc = str(mem.get("title") or mem.get("root_cause") or mem.get("failure")
               or mem.get("memory_id") or "memory update")[:160]
    return f"memory({protocol}): {desc}"


def _maybe_write_vault_note(root: Path, cfg, destination: str, mem: Dict[str, Any]):
    """ADDITIVE write-through (obsidian-memory-core, 2026-09-03; extended to
    JOB_MEMORY/PROJECT_MEMORY by Phase 13, 2026-09-03): mirrors a
    commit-worthy promotion/update into a real Markdown+YAML note in the
    DV-Knowledge Vault (dv_harness/memory_vault.py), via HybridMemoryProvider
    -- Obsidian used opportunistically if/when its own status() ever reports
    READY, the real FileSystemMarkdownAdapter otherwise (today, always).
    Gated on `cfg` exactly like `_maybe_share()` above (an explicit `cfg={}`
    opts out of every cfg-driven additive behavior this router has, not just
    shared-knowledge-center push) so a caller wanting pre-this-feature
    local-only behavior still gets it.

    Passes the real `memory(<protocol>): <short description>` commit message
    (Phase 13's exact required format, see `_build_vault_commit_message()`)
    through to the provider's `commit_message` parameter -- when git
    integration is enabled (`memory.git_enabled`), this is the one real
    commit-message policy this vault ever produces; every OTHER note
    operation the codebase can also perform (e.g. a hand-authored
    provider.create() call with no router involved) keeps
    FileSystemMarkdownAdapter's own generic default message unchanged.

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
        commit_message = _build_vault_commit_message(mem)
        existing = provider.read(note_id)
        if existing.get("ok"):
            return provider.update(note_id, frontmatter_patch=frontmatter, sections_patch=sections,
                                    commit_message=commit_message)
        result = provider.create(frontmatter, sections=sections, commit_message=commit_message)
        if not result.get("ok") and result.get("error") == "ALREADY_EXISTS":
            return provider.update(note_id, frontmatter_patch=frontmatter, sections_patch=sections,
                                    commit_message=commit_message)
        return result
    except Exception as exc:  # pragma: no cover - a vault-write failure must never break the local write
        return {"ok": False, "error": "VAULT_WRITE_FAILED", "detail": str(exc)}


def _write_back_knowledge_commit_sha(root: Path, mem: Dict[str, Any], vault_result: Dict[str, Any]) -> None:
    """Phase 13 traceability: after a real vault git commit, patch the SAME
    local MemoryStore/tier-store record (`mem`, already written by this
    router's own JOB_MEMORY/PROJECT_MEMORY/ENGINEERING_MEMORY branches above)
    with the resulting `knowledge_commit_sha` -- so the durable JSON record
    (the system of record) carries a real pointer to exactly which vault
    commit captured it, alongside its existing `rtl_sha`/`tb_sha` fields
    (memory_vault.MEMORY_NOTE_OPTIONAL_FIELDS). Deliberately never re-embeds
    the SHA into the vault note's OWN frontmatter a second time: the note's
    content was already committed by the time the SHA is known, so writing
    it back into that same note would need a second, circular commit -- the
    JSON record is the one real place this cross-reference belongs.

    ORGANIZATIONAL_MEMORY is never passed here (see its own route_and_store()
    branch): it has no local `.dv-harness/memory/organizational/` file store
    to patch (memory.py's OrganizationalMemoryStore design), only the shared
    Knowledge Center push. Best-effort: a failure here must never affect the
    already-completed local write or vault write."""
    sha = vault_result.get("knowledge_commit_sha") if isinstance(vault_result, dict) else None
    if not sha or not mem.get("memory_id") or not mem.get("level"):
        return
    try:
        MemoryStore(root).add(mem["level"], {**mem, "knowledge_commit_sha": sha})
    except Exception:
        pass


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
        # PROVENANCE of the source engineering record, deliberately NOT named
        # `confirmation_count`: that field is owned by MemoryGC.confirm() and
        # counts THIS record's own independent re-confirmations, of which a
        # freshly-promoted organizational record has zero. Carrying the
        # source's count under that name would have let a promoted record
        # look pre-confirmed (and, before MemoryStore._apply_confirmation_
        # integrity(), would have been written through verbatim).
        "source_confirmation_count": confirmation_count,
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
