"""Real, callable environment-generation-mode resolver -- closes the second
half of the 2026-09-01 AI-mechanism architecture audit gap: CLAUDE.md's
"Environment Generation Mode" gate and
.dv-harness/environment-router/environment_mode_policy.json document real
SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE semantics, but until this module existed
nothing executable ever computed that decision from real per-run input --
dv_harness/dashboard.py's own _environment_mode_selected() docstring (see
its "HONEST STATUS" note) confirms no stage ever emitted the
`environment_mode_selection` evidence block it scans for, because nothing
ever produced one.

This module computes the real decision from two structured evidence
fields -- `requested_subsystems` (what this run is trying to build/verify)
and `existing_registered_subsystems` (what is already registered as a
BASELINE_READY subsystem environment, read from the REAL registry file by
read_registered_subsystem_names() below, never fabricated) -- applying the
same rules already documented in CLAUDE.md's "Environment Generation Mode"
section and environment_mode_policy.json, transcribed here rather than
reinvented:

  - a single requested subsystem is a SUBSYSTEM_MODE build (policy.json
    SUBSYSTEM_MODE goal: "Generate/build a subsystem verification
    environment").
  - two or more requested subsystems is a SYSTEM_LEVEL_MODE composition
    (policy.json SYSTEM_LEVEL_MODE goal: "Select completed subsystem
    environments and compose a System-Level/Full-SoC verification
    environment").
  - CLAUDE.md: "If a required subsystem is missing in SYSTEM_LEVEL_MODE,
    build it through SUBSYSTEM_MODE then return to composition" --
    surfaced here as `needs_subsystem_mode_first`/`missing_subsystems`
    rather than silently ignored.
  - CLAUDE.md: "Before CREATE ENVIRONMENT, select: SUBSYSTEM_MODE ... /
    SYSTEM_LEVEL_MODE" (policy.json: "mode_must_be_explicit_before_
    generation": true) -- with zero requested subsystems there is nothing
    to select from, so resolve_environment_mode() returns an explicit
    unresolved result rather than guessing a default mode.

See dv_harness/engine.py's _environment_mode_router_evidence() for exactly
which real per-run source populates each of these two fields, and
tools/verification_flow/environment_mode_selection_gate.py (the new
STAGE_GATES-registered PROJECT_MODEL check) for how an agent's own
`environment_mode_selection` evidence block gets independently
cross-checked against real registry content rather than trusted verbatim --
see that gate script's header for the RULING on why it re-derives this same
decision as a small, self-contained check instead of importing this module
directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def registry_path(root: Path) -> Path:
    """The one real runtime subsystem-registry path, in one place.
    engine.py's _persist_subsystem_registry_entry() (the writer), gates.py's
    STAGE_GATES["SYSTEM_LEVEL"] system_level_validator ContextFlag (the
    harness-supplied --registered cross-check) and the two readers below all
    mean this same file -- deliberately NOT the empty
    subsystem_environment_registry_template.json example next to it."""
    return Path(root) / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"


def read_registered_subsystem_entries(root: Path) -> List[Dict[str, Any]]:
    """Reads the REAL runtime subsystem registry (see registry_path above,
    written by engine.py's _persist_subsystem_registry_entry() on an actual
    SIGNOFF PASS) and returns the FULL registered entries -- name plus the
    environment_manifest/release_sha/qualification_state/interface_
    compatibility/clock_reset_compatibility fields
    subsystem_environment_registration_gate.py validated before the entry was
    ever persisted. This is the shape
    uvm_generator.soc_environment_composer.compose_soc_environment() consumes
    as its `subsystem_registry_entries`, so a SYSTEM_LEVEL_MODE composition
    can be built from what the harness really registered rather than from
    what a caller claims. Missing/unreadable file degrades to an empty list
    (same defensive default _persist_subsystem_registry_entry() itself uses),
    never a fabricated guess."""
    import json
    path = registry_path(root)
    try:
        registry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        registry = {}
    entries = []
    for entry in (registry.get("subsystems") or []):
        if isinstance(entry, dict) and entry.get("name"):
            entries.append(entry)
    return entries


def read_registered_subsystem_names(root: Path) -> List[str]:
    """The registered subsystem `name` values only -- derived from
    read_registered_subsystem_entries() above rather than re-reading and
    re-parsing the same file a second way, so the two readers can never
    disagree about what counts as a registered entry."""
    return [str(e["name"]) for e in read_registered_subsystem_entries(root)]


def _norm_list(values: Any) -> List[str]:
    if not values:
        return []
    out = []
    for v in values:
        s = str(v).strip()
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out


def resolve_environment_mode(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Resolves SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE from structured
    evidence (module docstring above has the full ruling). `evidence` keys:
      - requested_subsystems: list[str] -- what this run wants built/verified.
      - existing_registered_subsystems: list[str] -- real registry contents
        (see read_registered_subsystem_names() above); an absent/empty list
        is treated as "nothing registered yet", not an error.

    Two structurally different evidence dicts (one requested_subsystems
    entry vs. two-or-more) are guaranteed to land on a different
    environment_mode here -- this is what makes the decision genuinely
    input-driven rather than the harness only ever falling back to reading
    the static environment_mode_policy.json file."""
    requested = _norm_list(evidence.get("requested_subsystems"))
    existing = {s.lower() for s in _norm_list(evidence.get("existing_registered_subsystems"))}

    if not requested:
        return {
            "resolved": False,
            "environment_mode": None,
            "requested_subsystems": [],
            "missing_subsystems": [],
            "reused_subsystems": [],
            "needs_subsystem_mode_first": False,
            "reason": "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION",
            "evidence": (
                "environment_mode_router.resolve_environment_mode received no "
                "requested_subsystems; CLAUDE.md 'Environment Generation Mode': "
                "'Before CREATE ENVIRONMENT, select: SUBSYSTEM_MODE / "
                "SYSTEM_LEVEL_MODE' (environment_mode_policy.json: "
                "mode_must_be_explicit_before_generation=true) -- there is "
                "nothing to select a mode FROM yet."
            ),
        }

    missing = [s for s in requested if s.lower() not in existing]
    reused = [s for s in requested if s.lower() in existing]

    if len(requested) >= 2:
        mode = "SYSTEM_LEVEL_MODE"
        needs_subsystem_mode_first = bool(missing)
        next_action = (
            f"invoke SUBSYSTEM_MODE builder for missing required subsystem(s) "
            f"{missing}, register it/them, then return to SYSTEM_LEVEL_MODE "
            "(environment_mode_policy.json missing_subsystem_behavior)"
            if needs_subsystem_mode_first else
            "proceed directly to SYSTEM_LEVEL_MODE composition -- all "
            "requested subsystems are already registered "
            "(environment_mode_policy.json system_level_reuse_rule: "
            "prefer BASELINE_READY/VERIFIED subsystem environments)"
        )
        evidence_str = (
            f"environment_mode_router.resolve_environment_mode: {len(requested)} "
            f"requested_subsystems ({requested}) >= 2 -> SYSTEM_LEVEL_MODE "
            "(policy.json SYSTEM_LEVEL_MODE goal: compose a System-Level/"
            f"Full-SoC verification environment); missing_from_registry={missing}"
        )
    else:
        mode = "SUBSYSTEM_MODE"
        needs_subsystem_mode_first = False
        name = requested[0]
        next_action = (
            f"build/register subsystem '{name}' via SUBSYSTEM_MODE"
            if missing else
            f"subsystem '{name}' is already registered; a single-subsystem "
            "request stays SUBSYSTEM_MODE by definition (policy.json "
            "SUBSYSTEM_MODE goal is single-subsystem build/regeneration)"
        )
        evidence_str = (
            f"environment_mode_router.resolve_environment_mode: exactly 1 "
            f"requested subsystem ('{name}') -> SUBSYSTEM_MODE "
            "(policy.json SUBSYSTEM_MODE goal: generate/build a subsystem "
            f"verification environment); already_registered={not missing}"
        )

    return {
        "resolved": True,
        "environment_mode": mode,
        "requested_subsystems": requested,
        "missing_subsystems": missing,
        "reused_subsystems": reused,
        "needs_subsystem_mode_first": needs_subsystem_mode_first,
        "next_action": next_action,
        "evidence": evidence_str,
    }
