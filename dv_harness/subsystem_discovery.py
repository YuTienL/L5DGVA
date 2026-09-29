"""SYS-1..SYS-4 of the System-Level Verification Integration workflow: the
DISCOVER-AND-PRESENT step that must run BEFORE a user selects which subsystem
environments participate in a System-Level composition, and the three
classifications that step has to produce for each candidate.

  SYS-1  discover candidates and present SUBSYSTEM / ENVIRONMENT PATH /
         KNOWLEDGE CENTER STATUS / READINESS / PROTOCOL / VERSION-SHA, then
         require an explicit user selection.
  SYS-2  prove each selected subsystem's environment EXISTS from repository
         evidence and classify EXISTS_READY / EXISTS_PARTIAL /
         EXISTS_BLOCKED / EXISTS_UNKNOWN / NOT_FOUND.
  SYS-3  retrieve the shared Knowledge Center's own 21-field record for it;
         current repository evidence overrides a stale KC record, and the
         contradiction is REPORTED rather than quietly resolved.
  SYS-4  classify readiness READY / PARTIAL / BLOCKED / UNKNOWN from 13
         independent factors, not from one self-attested maturity string.

WHY A NEW MODULE RATHER THAN AN EXTENSION OF AN EXISTING ONE. Everything
here operates on MANY subsystems' evidence at once and has no single-subsystem
home:

  - environment_mode_router.resolve_environment_mode() answers "given a
    selection already made, which generation mode is this" -- it reacts to a
    caller's `requested_subsystems`, and by design never computes what could
    have been requested. It is EXTENDED (not duplicated) with an optional
    `candidate_subsystems` input so the refusal it already raises for an
    empty request can name what the user may choose from, and so a
    deliberately-unselected candidate is reported instead of silently
    dropped. This module is that field's real producer.
  - tools/verification_flow/subsystem_environment_registration_gate.py and
    tools/real_env/system_level_validator.py are per-run PASS/FAIL gates over
    ONE claimed registry payload. They stay that; system_level_validator.py
    gains an additive `--classify` flag that reports this module's SYS-2
    five-way class alongside its unchanged verdict.
  - dashboard.py's _subsystem_registry() renders only ALREADY-REGISTERED
    subsystems, i.e. ones that already cleared SIGNOFF. A pre-selection view
    whose entire purpose is to surface EXISTS_PARTIAL / EXISTS_BLOCKED /
    NOT_FOUND candidates cannot be built on a reader that structurally cannot
    see them.

WHAT THIS MODULE DOES NOT DO. It is discovery/analysis/planning/reporting
only, per the master prompt's own SYS-39 stop condition. It generates no
System-Level UVM source, no System command.txt, no System Virtual Sequencer
and no command routing -- all of that is SYS-40, gated on a separate explicit
human approval. Nothing here writes to the real subsystem registry either:
engine.py's _persist_subsystem_registry_entry() remains its only writer, and
this module is a pure reader of it via environment_mode_router.

HONESTY OF THE ARTIFACT PROBE. probe_environment_artifacts() matches file
NAMES against declared or conventional patterns. That is real repository
evidence and it is what SYS-2 asks for ("prove ... using repository/project
evidence"), but a name match is not a proof of content, so every PRESENT
carries the actual matched paths for a human to check, an unreadable
environment root reports UNKNOWN rather than ABSENT, and a project may
declare exact paths per artifact kind to bypass the conventions entirely.
"""
from __future__ import annotations

import fnmatch
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .environment_mode_router import (
    read_registered_subsystem_entries,
    registry_path,
    resolve_environment_mode,
)
from .qualification import SYSTEM_LEVEL_STATES

# The registry entry contract, in one place. Byte-identical to the REQUIRED
# list in tools/verification_flow/subsystem_environment_registration_gate.py
# (the writer-side gate) and tools/real_env/system_level_validator.py (the
# reader-side gate). Those two stay standalone stdlib-only argparse scripts
# on purpose -- they run as gate subprocesses -- so this is a third statement
# of the same contract, held to the other two by
# test_subsystem_discovery.py::test_registry_required_fields_match_both_real_gate_scripts,
# the same drift-guard pattern source_authority.assert_doc_matches_code()
# already uses for the 9-level order.
REGISTRY_REQUIRED_FIELDS: tuple = (
    "name",
    "environment_manifest",
    "release_sha",
    "qualification_state",
    "interface_compatibility",
    "clock_reset_compatibility",
)

# --- SYS-2: the five-way existence classification ---------------------------
EXISTS_READY = "EXISTS_READY"
EXISTS_PARTIAL = "EXISTS_PARTIAL"
EXISTS_BLOCKED = "EXISTS_BLOCKED"
EXISTS_UNKNOWN = "EXISTS_UNKNOWN"
NOT_FOUND = "NOT_FOUND"
EXISTENCE_CLASSES: tuple = (
    EXISTS_READY, EXISTS_PARTIAL, EXISTS_BLOCKED, EXISTS_UNKNOWN, NOT_FOUND,
)

# --- SYS-4: the four-way readiness classification ---------------------------
READY = "READY"
PARTIAL = "PARTIAL"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
READINESS_CLASSES: tuple = (READY, PARTIAL, BLOCKED, UNKNOWN)

# Per-factor evidence status. Deliberately four values, not a bool: "we
# looked and it is not there" (ABSENT) and "we could not look" (UNKNOWN) are
# different facts, and collapsing them is how an unexaminable environment
# starts reporting as an incomplete one.
PRESENT = "PRESENT"
ABSENT = "ABSENT"
FACTOR_STATUSES: tuple = (PRESENT, ABSENT, BLOCKED, UNKNOWN)

# SYS-4's 13 factors, verbatim from the requirement's own list and in its own
# order: "RTL, UVM env, VIP, build, tests, sequences, scoreboard/reference
# model, command.txt, clock/reset assumptions, top hierarchy, config, PASS
# evidence, regression evidence".
READINESS_FACTORS: tuple = (
    "rtl",
    "uvm_env",
    "vip",
    "build",
    "tests",
    "sequences",
    "scoreboard_reference_model",
    "command_txt",
    "clock_reset_assumptions",
    "top_hierarchy",
    "config",
    "pass_evidence",
    "regression_evidence",
)

# Which probed artifact kind evidences which SYS-4 factor. One artifact
# vocabulary serves both SYS-2's evidence list and SYS-4's factor list --
# they overlap almost entirely, and probing the same tree twice under two
# vocabularies is how the two would come to disagree about the same file.
FACTOR_ARTIFACT: Dict[str, str] = {
    "rtl": "rtl",
    "uvm_env": "uvm_env_source",
    "vip": "vip_setup",
    "build": "build_scripts",
    "tests": "tests",
    "sequences": "sequences",
    "scoreboard_reference_model": "scoreboards",
    "command_txt": "command_txt",
    "clock_reset_assumptions": "clock_reset_config",
    "top_hierarchy": "top_hierarchy",
    "config": "config_objects",
    "pass_evidence": "pass_evidence",
    "regression_evidence": "regression_lists",
}

# SYS-2's own evidence list, minus the two non-filesystem sources it names
# (Subsystem Registry and Knowledge Center, both supplied separately).
# fnmatch patterns against POSIX-relative paths under the environment root;
# note fnmatch's `*` crosses `/`, so "*env/*.sv" matches "uvm/env/foo_env.sv".
ARTIFACT_GLOBS: Dict[str, tuple] = {
    "rtl": ("*rtl/*.v", "*rtl/*.sv", "*dut/*.v", "*dut/*.sv", "*.vhd"),
    "uvm_env_source": ("*_env.sv", "*env/*.sv", "*_agent.sv", "*_driver.sv", "*_monitor.sv"),
    "vip_setup": ("*vip*.sv", "*vip*.f", "*vip/*", "*svt_*.sv"),
    "build_scripts": ("Makefile", "*/Makefile", "*.mk", "*vcs.opt", "*/vcs.opt"),
    "filelists": ("*.f",),
    "tests": ("*_test.sv", "*test/*.sv", "*tests/*.sv", "*testlist*"),
    "sequences": ("*_seq.sv", "*_sequence.sv", "*seq/*.sv", "*sequences/*.sv"),
    "scoreboards": ("*_scoreboard.sv", "*_sb.sv", "*_refmodel.sv",
                     "*_reference_model.sv", "*_predictor.sv"),
    "command_txt": ("command.txt", "*/command.txt", "*command*.txt"),
    "clock_reset_config": ("*clock*reset*", "*clk*rst*", "*reset*.sv", "*clocking*.sv"),
    "top_hierarchy": ("*tb_top.sv", "*_top.sv", "top.sv", "*hierarchy.json"),
    "config_objects": ("*_config.sv", "*_cfg.sv", "env.manifest.json",
                        "*env.manifest.json", "*_config.json"),
    "pass_evidence": ("*sim.log", "*signoff*.json", "*pass_evidence*", "*PASS*"),
    "regression_lists": ("*regression.list", "*regression*.log", "*regression*.json"),
    "docs": ("*.md", "*doc/*", "*docs/*"),
    "agents_skills": ("*SKILL.md", "*agent*.md"),
}

# Bounds on the environment-tree walk. A candidate environment is somebody
# else's repository; an unbounded walk of one is not an acceptable cost for a
# discovery listing, and a truncated walk must SAY it was truncated rather
# than report the artifacts it never reached as ABSENT.
MAX_WALK_FILES = 20000
MAX_WALK_DEPTH = 8

def candidate_sources_path(root: Path) -> Path:
    """Where a project declares its candidate subsystem environments. Same
    per-project declared-config convention as
    .dv-harness/connectivity_check.json: an absent file means NOT_CONFIGURED
    (an honest "nothing was declared"), never a fabricated candidate list."""
    return Path(root) / ".dv-harness" / "soc-composer" / "subsystem_candidate_sources.json"


# --- SYS-2/SYS-4 evidence probe ---------------------------------------------

def _walk_relative_paths(env_root: Path) -> Dict[str, Any]:
    """Bounded walk of one environment tree -> POSIX-relative path strings.

    Returns {"readable": bool, "paths": [...], "truncated": bool, "reason": str}.
    An unreadable/absent root is `readable: False` with a reason -- the caller
    turns that into UNKNOWN, never ABSENT."""
    if not env_root:
        return {"readable": False, "paths": [], "truncated": False,
                "reason": "NO_ENVIRONMENT_PATH"}
    p = Path(env_root)
    if not p.exists():
        return {"readable": False, "paths": [], "truncated": False,
                "reason": f"ENVIRONMENT_PATH_DOES_NOT_EXIST: {p}"}
    if not p.is_dir():
        return {"readable": False, "paths": [], "truncated": False,
                "reason": f"ENVIRONMENT_PATH_IS_NOT_A_DIRECTORY: {p}"}
    paths: List[str] = []
    truncated = False
    base_depth = len(p.resolve().parts)
    try:
        import os
        for dirpath, dirnames, filenames in os.walk(p):
            here = Path(dirpath)
            if len(here.resolve().parts) - base_depth >= MAX_WALK_DEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".svn"}]
            for fn in filenames:
                paths.append((here / fn).relative_to(p).as_posix())
                if len(paths) >= MAX_WALK_FILES:
                    truncated = True
                    break
            if truncated:
                break
    except OSError as exc:
        return {"readable": False, "paths": [], "truncated": False,
                "reason": f"ENVIRONMENT_PATH_UNREADABLE: {exc}"}
    return {"readable": True, "paths": paths, "truncated": truncated, "reason": ""}


def probe_environment_artifacts(env_root: Optional[Path],
                                declared: Optional[Mapping[str, Sequence[str]]] = None,
                                ) -> Dict[str, Dict[str, Any]]:
    """Probe one subsystem environment tree for each SYS-2 artifact kind.

    `declared` optionally maps an artifact kind to explicit project-relative
    paths, which BEAT the name conventions entirely: a declared path that
    exists is PRESENT, a declared path that does not is ABSENT. A project
    that declares its own layout is never at the mercy of this module's
    guesses about what a scoreboard file is called.

    Returns {artifact_kind: {"status", "matched", "basis"}} for every key of
    ARTIFACT_GLOBS. status is PRESENT/ABSENT/UNKNOWN -- BLOCKED is never
    produced here, because a file being on disk cannot itself be a blocker;
    blockers come from registry compatibility verdicts (see
    _registry_blocked_factors())."""
    walk = _walk_relative_paths(Path(env_root) if env_root else None)
    declared = {str(k): list(v or []) for k, v in (declared or {}).items()}
    out: Dict[str, Dict[str, Any]] = {}
    for kind, globs in ARTIFACT_GLOBS.items():
        if kind in declared:
            matched, missing = [], []
            for rel in declared[kind]:
                target = (Path(env_root) / rel) if env_root else Path(rel)
                (matched if target.exists() else missing).append(rel)
            out[kind] = {
                "status": PRESENT if matched else ABSENT,
                "matched": matched[:3],
                "basis": ("DECLARED_PATHS" if matched
                          else f"DECLARED_PATHS_NOT_ON_DISK: {missing[:3]}"),
            }
            continue
        if not walk["readable"]:
            out[kind] = {"status": UNKNOWN, "matched": [],
                         "basis": f"NOT_PROBED ({walk['reason']})"}
            continue
        hits = [rel for rel in walk["paths"]
                if any(fnmatch.fnmatch(rel, g) for g in globs)]
        if hits:
            out[kind] = {"status": PRESENT, "matched": sorted(hits)[:3],
                         "basis": f"NAME_CONVENTION {list(globs)}"}
        elif walk["truncated"]:
            # The walk hit its file cap before reaching everything, so an
            # absence here is not an established absence.
            out[kind] = {"status": UNKNOWN, "matched": [],
                         "basis": f"WALK_TRUNCATED_AT_{MAX_WALK_FILES}_FILES"}
        else:
            out[kind] = {"status": ABSENT, "matched": [],
                         "basis": f"NO_MATCH_FOR {list(globs)}"}
    out["_walk"] = {"status": PRESENT if walk["readable"] else UNKNOWN,
                    "matched": [], "basis": walk["reason"] or
                    f"{len(walk['paths'])} files walked"}
    return out


def _registry_blocked_factors(registry_entry: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Which SYS-4 factors a real registry verdict BLOCKS, and why.

    The three fields the registration gate already validates are not merely
    metadata -- each is a recorded verdict about a factor SYS-4 asks about,
    so a non-PASS verdict must block that factor rather than sit beside a
    PRESENT derived from file names:
      - interface_compatibility != PASS   -> the UVM environment cannot be
        integrated as-is, whatever source files exist.
      - clock_reset_compatibility != PASS -> the clock/reset assumptions are
        the recorded disagreement.
      - qualification_state outside the canonical system-level set -> the
        recorded PASS evidence does not support system-level reuse
        (qualification.SYSTEM_LEVEL_STATES is the one canonical vocabulary
        here; this module does not invent a second)."""
    if not registry_entry:
        return {}
    blocked: Dict[str, str] = {}
    iface = registry_entry.get("interface_compatibility")
    if iface is not None and iface != "PASS":
        blocked["uvm_env"] = f"registry interface_compatibility={iface!r}, not PASS"
    ck = registry_entry.get("clock_reset_compatibility")
    if ck is not None and ck != "PASS":
        blocked["clock_reset_assumptions"] = f"registry clock_reset_compatibility={ck!r}, not PASS"
    qs = registry_entry.get("qualification_state")
    if qs is not None and qs not in SYSTEM_LEVEL_STATES:
        blocked["pass_evidence"] = (
            f"registry qualification_state={qs!r} is not one of "
            f"{list(SYSTEM_LEVEL_STATES)}")
    return blocked


def readiness_factors_from_evidence(artifacts: Mapping[str, Mapping[str, Any]],
                                    registry_entry: Optional[Mapping[str, Any]] = None,
                                    ) -> Dict[str, Dict[str, Any]]:
    """Map the probed artifacts + the registry's own verdicts onto SYS-4's 13
    factors. Every factor is derived; none is read from a self-attested
    field."""
    blocked = _registry_blocked_factors(registry_entry)
    factors: Dict[str, Dict[str, Any]] = {}
    for factor in READINESS_FACTORS:
        if factor in blocked:
            factors[factor] = {"status": BLOCKED, "evidence": blocked[factor],
                               "matched": []}
            continue
        probe = artifacts.get(FACTOR_ARTIFACT[factor]) or {}
        factors[factor] = {
            "status": probe.get("status", UNKNOWN),
            "evidence": probe.get("basis", "NOT_PROBED"),
            "matched": list(probe.get("matched") or []),
        }
    return factors


def derive_subsystem_readiness(factors: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """SYS-4's readiness gate: READY / PARTIAL / BLOCKED / UNKNOWN from the 13
    factors, as a total function with an explicit precedence:

      BLOCKED  any factor is BLOCKED. A known blocker outranks everything --
               a subsystem with 12 healthy factors and a clock/reset conflict
               is not "mostly ready", it is blocked on that conflict.
      UNKNOWN  no blocker, and NOTHING could be evidenced (every factor
               UNKNOWN). This is the "insufficient evidence to classify"
               state, and it is why READY/PARTIAL/BLOCKED alone was never
               enough: an environment nobody could open must not be reported
               with the same word as one that was opened and found lacking.
      READY    no blocker, and all 13 factors PRESENT. Nothing less, because
               READY is what a System-Level composition would rely on.
      PARTIAL  everything else -- some evidence found, some missing or
               unexaminable. A single UNKNOWN factor therefore keeps a
               subsystem out of READY: not-yet-checked never rounds up.
    """
    statuses = {f: (factors.get(f) or {}).get("status", UNKNOWN) for f in READINESS_FACTORS}
    blocking = [f for f, s in statuses.items() if s == BLOCKED]
    missing = [f for f, s in statuses.items() if s == ABSENT]
    unknown = [f for f, s in statuses.items() if s == UNKNOWN]
    present = [f for f, s in statuses.items() if s == PRESENT]

    if blocking:
        readiness = BLOCKED
        why = (f"{len(blocking)} blocked factor(s): "
               + "; ".join(f"{f}: {(factors.get(f) or {}).get('evidence', '')}" for f in blocking))
    elif len(unknown) == len(READINESS_FACTORS):
        readiness = UNKNOWN
        why = ("no factor could be evidenced at all -- insufficient evidence to "
               "classify readiness (not the same as evidenced-and-incomplete)")
    elif not missing and not unknown:
        readiness = READY
        why = f"all {len(READINESS_FACTORS)} SYS-4 factors evidenced PRESENT"
    else:
        readiness = PARTIAL
        why = (f"{len(present)}/{len(READINESS_FACTORS)} factors present; "
               f"absent={missing}; unknown={unknown}")

    return {
        "readiness": readiness,
        "blocking_factors": blocking,
        "missing_factors": missing,
        "unknown_factors": unknown,
        "present_factors": present,
        "evidence": why,
    }


# --- SYS-2 classification ----------------------------------------------------

def classify_subsystem_existence(*,
                                 name: str,
                                 registry_entry: Optional[Mapping[str, Any]],
                                 readiness: Mapping[str, Any],
                                 environment_path_readable: bool,
                                 knowledge_center_status: str = "KC_NOT_CHECKED",
                                 ) -> Dict[str, Any]:
    """SYS-2's five-way classification, in a fixed precedence:

      NOT_FOUND       nothing anywhere: no registry entry, no readable
                      environment path, no KC record. SYS-2: "If NOT_FOUND,
                      do not invent it" -- the returned next_action says so.
      EXISTS_BLOCKED  a recorded verdict says it cannot be used as-is (the
                      registration gate's own three FAIL reasons), or the
                      SYS-4 readiness gate is BLOCKED.
      EXISTS_PARTIAL  a registry entry exists but is missing required fields
                      (the gate's MISSING_REQUIRED_FIELDS), or evidence
                      exists but is incomplete.
      EXISTS_UNKNOWN  something claims it exists, but the evidence cannot say
                      what state it is in -- typically a KC record or a
                      declared path pointing at a tree that cannot be read.
      EXISTS_READY    registered with every required field, no blocker, and
                      all 13 SYS-4 factors evidenced.
    """
    reasons: List[str] = []
    registered = bool(registry_entry)
    kc_found = knowledge_center_status == "KC_RECORD_FOUND"

    if not registered and not environment_path_readable and not kc_found:
        return {
            "existence_class": NOT_FOUND,
            "reasons": [
                f"no entry for {name!r} in the real persisted subsystem registry",
                "no readable environment path",
                f"knowledge center: {knowledge_center_status}",
            ],
            "next_action": ("SCOPE_CORRECTION_OR_SEPARATE_SUBSYSTEM_CREATION_WORKFLOW "
                            "-- SYS-2 forbids inventing a missing subsystem environment"),
            "confidence": "HIGH",
        }

    missing_fields: List[str] = []
    if registered:
        missing_fields = [f for f in REGISTRY_REQUIRED_FIELDS if not registry_entry.get(f)]

    readiness_class = (readiness or {}).get("readiness", UNKNOWN)

    if readiness_class == BLOCKED:
        reasons.append((readiness or {}).get("evidence", "readiness gate BLOCKED"))
        return {"existence_class": EXISTS_BLOCKED, "reasons": reasons,
                "next_action": "RESOLVE_BLOCKING_FACTORS_BEFORE_SYSTEM_LEVEL_SELECTION",
                "confidence": "HIGH" if registered else "MEDIUM"}

    if registered and missing_fields:
        reasons.append(f"registry entry missing required field(s): {missing_fields}")
        return {"existence_class": EXISTS_PARTIAL, "reasons": reasons,
                "next_action": "COMPLETE_REGISTRY_ENTRY_VIA_SUBSYSTEM_MODE_SIGNOFF",
                "confidence": "HIGH"}

    if not environment_path_readable:
        reasons.append("environment path is not readable, so no repository artifact "
                       "evidence could be gathered")
        if registered:
            reasons.append("a registry entry exists but points at a tree this run could not open")
        if kc_found:
            reasons.append("a Knowledge Center record claims this subsystem exists")
        return {"existence_class": EXISTS_UNKNOWN, "reasons": reasons,
                "next_action": "SUPPLY_A_READABLE_ENVIRONMENT_PATH_THEN_RE_RUN_DISCOVERY",
                "confidence": "LOW"}

    if registered and readiness_class == READY:
        return {"existence_class": EXISTS_READY,
                "reasons": ["registered with every required field",
                            (readiness or {}).get("evidence", "")],
                "next_action": "ELIGIBLE_FOR_EXPLICIT_USER_SELECTION",
                "confidence": "HIGH"}

    if not registered:
        reasons.append("environment artifacts found on disk, but this subsystem has never "
                       "been registered (no SIGNOFF-gated registry entry)")
    reasons.append((readiness or {}).get("evidence", ""))
    return {"existence_class": EXISTS_PARTIAL, "reasons": [r for r in reasons if r],
            "next_action": ("REGISTER_VIA_SUBSYSTEM_MODE_SIGNOFF" if not registered
                            else "CLOSE_MISSING_READINESS_FACTORS"),
            "confidence": "MEDIUM"}


# --- SYS-3 Knowledge Center check -------------------------------------------

# Which SYS-3 KC field is a claim about which piece of repository evidence.
# Only fields with a real repository counterpart can contradict anything --
# KNOWN_LIMITATIONS or OWNER_SKILL have no repository twin to disagree with.
KC_REPO_FIELD_MAP: Dict[str, str] = {
    "GIT_SHA": "version_sha",
    "VERSION": "version_sha",
    "ENVIRONMENT_PATH": "environment_path",
    "PROTOCOL": "protocol",
    "READINESS": "readiness",
}


def knowledge_center_subsystem_check(client: Any,
                                     subsystem_id: str,
                                     repo_evidence: Mapping[str, Any],
                                     *,
                                     protocol: str = "",
                                     max_age_days: float = 180.0,
                                     now: Optional[float] = None,
                                     ) -> Dict[str, Any]:
    """SYS-3. Reads the SHARED Knowledge Center through the existing
    KnowledgeCenterClient (never a parallel store) and compares its record
    against this run's repository evidence.

    SYS-3's rule -- "Current repository evidence overrides stale Knowledge
    Center records. Report contradictions/staleness." -- is implemented as a
    fixed precedence, not a judgement call: on every disagreement the
    repository value is the resolved value and the KC value is recorded as
    `overridden_value`. Nothing is written back and no KC record is
    deprecated here; discovery reports, it does not mutate shared state.

    Five distinct statuses, because collapsing them would hide exactly the
    difference SYS-2 needs: KC_NOT_CHECKED (no client supplied),
    KC_NOT_CONFIGURED (this project has no shared KC), KC_UNAVAILABLE (it has
    one and it could not be reached -- an operator problem, not an absence),
    KC_RECORD_ABSENT (reachable, holds nothing for this subsystem),
    KC_RECORD_FOUND."""
    base = {"knowledge_center_status": "KC_NOT_CHECKED", "record": None,
            "contradictions": [], "staleness": None, "detail": ""}
    if client is None:
        base["detail"] = "no KnowledgeCenterClient supplied to discovery"
        return base
    try:
        if not client.configured():
            base["knowledge_center_status"] = "KC_NOT_CONFIGURED"
            base["detail"] = ("knowledge_center.enabled/remote_root are unset for this "
                              "project -- see `dv-harness knowledge setup`")
            return base
        res = client.subsystem_record(subsystem_id, protocol=protocol)
    except Exception as exc:  # pragma: no cover - client is documented never-raising
        base["knowledge_center_status"] = "KC_UNAVAILABLE"
        base["detail"] = f"CLIENT_EXCEPTION: {exc}"
        return base

    if not res.get("ok"):
        base["knowledge_center_status"] = "KC_UNAVAILABLE"
        base["detail"] = f"{res.get('error', 'UNKNOWN_ERROR')}: {res.get('detail', '')}"
        return base
    if not res.get("found"):
        base["knowledge_center_status"] = "KC_RECORD_ABSENT"
        base["detail"] = "knowledge center reachable; no record for this subsystem"
        return base

    record = res.get("record") or {}
    contradictions = []
    for kc_field, repo_field in KC_REPO_FIELD_MAP.items():
        kc_value = record.get(kc_field)
        repo_value = (repo_evidence or {}).get(repo_field)
        if kc_value in (None, "") or repo_value in (None, ""):
            continue
        if str(kc_value).strip().lower() != str(repo_value).strip().lower():
            contradictions.append({
                "field": kc_field,
                "knowledge_center_value": kc_value,
                "repository_value": repo_value,
                "resolution": "REPOSITORY_EVIDENCE_WINS",
                "overridden_value": kc_value,
                "basis": ("SYS-3: current repository evidence overrides stale "
                          "Knowledge Center records"),
            })

    now = time.time() if now is None else now
    written_at = (record.get("_kc") or {}).get("written_at")
    age_days = None
    if isinstance(written_at, (int, float)) and written_at > 0:
        age_days = round((now - float(written_at)) / 86400.0, 2)
    sha_contradiction = any(c["field"] == "GIT_SHA" for c in contradictions)
    stale = bool(sha_contradiction or (age_days is not None and age_days > max_age_days))
    staleness = {
        "stale": stale,
        "age_days": age_days,
        "max_age_days": max_age_days,
        "reasons": [r for r in [
            ("KC GIT_SHA disagrees with the repository's current release SHA"
             if sha_contradiction else ""),
            (f"KC record is {age_days} days old, past the {max_age_days}-day window"
             if age_days is not None and age_days > max_age_days else ""),
        ] if r],
    }
    return {"knowledge_center_status": "KC_RECORD_FOUND", "record": record,
            "contradictions": contradictions, "staleness": staleness,
            "detail": f"{len(contradictions)} contradiction(s) against repository evidence"}


# --- SYS-1 discovery ---------------------------------------------------------

def _load_candidate_sources(root: Path) -> Dict[str, Any]:
    """Read the project's declared candidate environments. Absent file ->
    NOT_CONFIGURED plus an empty declaration, never an invented candidate."""
    path = candidate_sources_path(root)
    if not path.exists():
        return {"status": "NOT_CONFIGURED", "declared": [], "path": str(path),
                "detail": ("no subsystem_candidate_sources.json -- discovery falls back "
                           "to the real subsystem registry alone")}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "UNREADABLE", "declared": [], "path": str(path),
                "detail": f"{type(exc).__name__}: {exc}"}
    declared = [c for c in (data.get("candidates") or []) if isinstance(c, dict) and c.get("name")]
    return {"status": "CONFIGURED", "declared": declared, "path": str(path),
            "detail": f"{len(declared)} declared candidate(s)"}


def _protocol_of(declared: Mapping[str, Any], registry_entry: Optional[Mapping[str, Any]],
                 name: str) -> str:
    for source in (declared, registry_entry or {}):
        value = (source or {}).get("protocol")
        if value:
            return str(value)
    return "UNKNOWN"


def _version_sha_of(declared: Mapping[str, Any],
                    registry_entry: Optional[Mapping[str, Any]]) -> str:
    for source in (registry_entry or {}, declared):
        for key in ("release_sha", "git_sha", "version"):
            value = (source or {}).get(key)
            if value:
                return str(value)
    return ""


def discover_subsystem_candidates(root: Path, *,
                                  knowledge_center_client: Any = None,
                                  requested: Optional[Sequence[str]] = None,
                                  ) -> Dict[str, Any]:
    """SYS-1: build the candidate table a user selects FROM.

    Candidates are the UNION of three real sources, never a guess:
      1. the real persisted subsystem registry (environment_mode_router.
         read_registered_subsystem_entries() -- written only by engine.py's
         _persist_subsystem_registry_entry() on a gate-validated SIGNOFF PASS);
      2. this project's declared candidate environments
         (.dv-harness/soc-composer/subsystem_candidate_sources.json), which
         is how an environment that exists on disk but was never registered
         becomes visible -- the case dashboard.py's registry view structurally
         cannot show;
      3. any name in `requested` that neither of the above knows about, so a
         user asking for a subsystem that does not exist gets a NOT_FOUND row
         rather than silence.

    Every row carries SYS-1's six columns plus the SYS-2 class, the SYS-4
    readiness derivation and the SYS-3 KC check. Nothing is written."""
    root = Path(root)
    registry_entries = read_registered_subsystem_entries(root)
    by_name: Dict[str, Dict[str, Any]] = {str(e["name"]).lower(): dict(e) for e in registry_entries}
    sources = _load_candidate_sources(root)
    declared_by_name: Dict[str, Dict[str, Any]] = {
        str(c["name"]).lower(): dict(c) for c in sources["declared"]}

    order: List[str] = []
    for key in list(by_name) + list(declared_by_name) + [str(r).lower() for r in (requested or [])]:
        if key not in order:
            order.append(key)

    rows: List[Dict[str, Any]] = []
    for key in order:
        registry_entry = by_name.get(key)
        declared = declared_by_name.get(key, {})
        name = str((registry_entry or declared or {}).get("name")
                   or next((r for r in (requested or []) if str(r).lower() == key), key))

        # Where this subsystem's environment lives. A declared candidate wins;
        # otherwise fall back to the DIRECTORY HOLDING the registry entry's own
        # environment_manifest, which is the only environment location a
        # registry entry carries. That fallback is what makes the registry
        # alone sufficient for discovery in a project that never wrote a
        # subsystem_candidate_sources.json -- without it, every registered
        # subsystem would report EXISTS_UNKNOWN for want of a path nobody
        # asked the project to declare twice.
        env_path_raw = (declared.get("environment_path")
                        or (registry_entry or {}).get("environment_path") or "")
        env_path_basis = "DECLARED_ENVIRONMENT_PATH"
        if not env_path_raw and (registry_entry or {}).get("environment_manifest"):
            env_path_raw = str(Path(registry_entry["environment_manifest"]).parent)
            env_path_basis = "REGISTRY_ENVIRONMENT_MANIFEST_PARENT"
        env_path = None
        if env_path_raw and env_path_raw not in (".", ""):
            candidate_path = Path(env_path_raw)
            env_path = candidate_path if candidate_path.is_absolute() else (root / candidate_path)
        else:
            env_path_basis = "NO_ENVIRONMENT_PATH_AVAILABLE"

        artifacts = probe_environment_artifacts(env_path, declared.get("declared_artifacts"))
        env_readable = artifacts["_walk"]["status"] == PRESENT
        factors = readiness_factors_from_evidence(artifacts, registry_entry)
        readiness = derive_subsystem_readiness(factors)
        protocol = _protocol_of(declared, registry_entry, name)
        version_sha = _version_sha_of(declared, registry_entry)

        kc = knowledge_center_subsystem_check(
            knowledge_center_client, name,
            {"version_sha": version_sha, "environment_path": str(env_path or ""),
             "protocol": protocol, "readiness": readiness["readiness"]},
            protocol=protocol if protocol != "UNKNOWN" else "")

        existence = classify_subsystem_existence(
            name=name, registry_entry=registry_entry, readiness=readiness,
            environment_path_readable=env_readable,
            knowledge_center_status=kc["knowledge_center_status"])

        rows.append({
            # SYS-1's six mandated columns, in its own order.
            "subsystem": name,
            "environment_path": str(env_path) if env_path else "",
            "knowledge_center_status": kc["knowledge_center_status"],
            "readiness": readiness["readiness"],
            "protocol": protocol,
            "version_sha": version_sha,
            # SYS-2 / SYS-3 / SYS-4 detail behind those columns.
            "existence_class": existence["existence_class"],
            "existence_reasons": existence["reasons"],
            "next_action": existence["next_action"],
            "confidence": existence["confidence"],
            "registered": bool(registry_entry),
            "readiness_detail": readiness,
            "readiness_factors": factors,
            "knowledge_center": kc,
            "environment_path_readable": env_readable,
            "environment_path_basis": env_path_basis,
        })

    return {
        "candidates": rows,
        "candidate_source_status": sources["status"],
        "candidate_source_detail": sources["detail"],
        "candidate_source_path": sources["path"],
        "registry_path": str(registry_path(root)),
        "registered_count": len(registry_entries),
        "conflicts": detect_candidate_conflicts(rows),
        "evidence": (
            f"{len(rows)} candidate subsystem(s) from {len(registry_entries)} registered "
            f"entr(ies) + {len(declared_by_name)} declared candidate(s) "
            f"({sources['status']})"),
    }


def detect_candidate_conflicts(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Ambiguities in the candidate set itself, before any selection is made.

    Two candidates resolving to the SAME environment path is the one that
    matters at this stage: it means "PCIe" and "PCIE_GEN5" may be two names
    for one environment, and selecting both would double-count one
    environment's agents into a System-Level composition -- the SYS-10
    duplicate-resource problem arriving one step early, at discovery. Reported
    here, never auto-merged: which of the two names is correct is a user
    decision, and this workflow's own gate is that the user selects."""
    by_path: Dict[str, List[str]] = {}
    for row in rows:
        path = str(row.get("environment_path") or "")
        if path:
            by_path.setdefault(path, []).append(str(row.get("subsystem")))
    conflicts = []
    for path, names in by_path.items():
        if len(names) > 1:
            conflicts.append({
                "conflict": "DUPLICATE_ENVIRONMENT_PATH",
                "environment_path": path,
                "subsystems": sorted(names),
                "resolution": "USER_MUST_DISAMBIGUATE_BEFORE_SELECTION",
                "detail": ("two or more discovered candidates point at one environment "
                           "tree; selecting both would compose the same environment twice"),
            })
    return conflicts


def require_explicit_selection(root: Path,
                               requested: Optional[Sequence[str]] = None,
                               *,
                               knowledge_center_client: Any = None,
                               ) -> Dict[str, Any]:
    """SYS-1's second half: discover, present, then REQUIRE an explicit
    selection -- wired straight into the existing
    environment_mode_router.resolve_environment_mode(), which already refuses
    to pick a mode from an empty request. This adds the half that was
    missing: the candidate list that refusal is made against, and the
    per-selection SYS-2/SYS-4 verdicts.

    `selection_admissible` is True only when a selection was made, every
    selected subsystem classified EXISTS_READY, and no candidate-set conflict
    stands. It is a PLANNING verdict for the SYS-39 report -- it authorizes
    nothing on its own, and nothing downstream of it is generated here."""
    discovery = discover_subsystem_candidates(
        root, knowledge_center_client=knowledge_center_client, requested=requested)
    rows = {str(r["subsystem"]).lower(): r for r in discovery["candidates"]}
    selected = [str(s) for s in (requested or [])]

    decision = resolve_environment_mode({
        "requested_subsystems": selected,
        "existing_registered_subsystems": [r["subsystem"] for r in discovery["candidates"]
                                            if r["registered"]],
        "candidate_subsystems": [r["subsystem"] for r in discovery["candidates"]],
    })

    selected_rows = [rows[s.lower()] for s in selected if s.lower() in rows]
    not_ready = [{"subsystem": r["subsystem"], "existence_class": r["existence_class"],
                  "readiness": r["readiness"], "next_action": r["next_action"]}
                 for r in selected_rows if r["existence_class"] != EXISTS_READY]
    blocking_conflicts = [c for c in discovery["conflicts"]
                          if any(n.lower() in {s.lower() for s in selected}
                                 for n in c["subsystems"])]

    return {
        "discovery": discovery,
        "environment_mode_decision": decision,
        "selected_subsystems": selected,
        "selected_rows": selected_rows,
        "not_ready": not_ready,
        "blocking_conflicts": blocking_conflicts,
        "selection_admissible": bool(selected) and not not_ready and not blocking_conflicts,
        "refusal_reason": (
            "NO_EXPLICIT_SELECTION" if not selected
            else "SELECTED_SUBSYSTEM_NOT_EXISTS_READY" if not_ready
            else "CANDIDATE_SET_CONFLICT" if blocking_conflicts
            else ""),
    }


# --- SYS-1 presentation ------------------------------------------------------

def render_discovery_table(discovery: Mapping[str, Any]) -> str:
    """SYS-1's mandated table, exactly its six columns, as markdown."""
    header = ("| SUBSYSTEM | ENVIRONMENT PATH | KNOWLEDGE CENTER STATUS | "
              "READINESS | PROTOCOL | VERSION-SHA |")
    sep = "|---|---|---|---|---|---|"
    lines = [header, sep]
    for row in discovery.get("candidates") or []:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            row.get("subsystem") or "-",
            row.get("environment_path") or "-",
            row.get("knowledge_center_status") or "-",
            row.get("readiness") or "-",
            row.get("protocol") or "-",
            row.get("version_sha") or "-"))
    if len(lines) == 2:
        lines.append("| _(no candidate subsystem environments discovered)_ | - | - | - | - | - |")
    return "\n".join(lines)


def format_report(result: Mapping[str, Any]) -> str:
    """Human-readable SYS-1..4 discovery report. Reporting only -- this is
    the deliverable of the discovery/analysis phase, and it deliberately
    stops short of anything SYS-40 would generate."""
    discovery = result.get("discovery", result)
    out = ["# SYSTEM-LEVEL INTEGRATION DISCOVERY (SYS-1..SYS-4)", "",
           "## SYS-1 CANDIDATE SUBSYSTEM ENVIRONMENTS", "",
           render_discovery_table(discovery), "",
           f"- registry: {discovery.get('registry_path')} "
           f"({discovery.get('registered_count')} registered)",
           f"- declared candidates: {discovery.get('candidate_source_status')} "
           f"-- {discovery.get('candidate_source_detail')}", ""]

    out += ["## SYS-2 EXISTENCE CLASSIFICATION", ""]
    for row in discovery.get("candidates") or []:
        out.append(f"- **{row['subsystem']}**: {row['existence_class']} "
                   f"(confidence {row['confidence']}) -> {row['next_action']}")
        for reason in row.get("existence_reasons") or []:
            out.append(f"  - {reason}")
    if not (discovery.get("candidates") or []):
        out.append("- _(nothing to classify -- no candidates discovered)_")
    out.append("")

    out += ["## SYS-3 KNOWLEDGE CENTER CHECK", ""]
    for row in discovery.get("candidates") or []:
        kc = row.get("knowledge_center") or {}
        out.append(f"- **{row['subsystem']}**: {kc.get('knowledge_center_status')} "
                   f"-- {kc.get('detail', '')}")
        for c in kc.get("contradictions") or []:
            out.append(f"  - CONTRADICTION {c['field']}: KC={c['knowledge_center_value']!r} "
                       f"vs repository={c['repository_value']!r} -> {c['resolution']}")
        staleness = kc.get("staleness") or {}
        if staleness.get("stale"):
            out.append(f"  - STALE: {'; '.join(staleness.get('reasons') or [])}")
    out.append("")

    out += ["## SYS-4 SUBSYSTEM READINESS GATE", ""]
    for row in discovery.get("candidates") or []:
        detail = row.get("readiness_detail") or {}
        out.append(f"- **{row['subsystem']}**: {row['readiness']} -- {detail.get('evidence', '')}")
    out.append("")

    conflicts = discovery.get("conflicts") or []
    if conflicts:
        out += ["## CANDIDATE-SET CONFLICTS", ""]
        for c in conflicts:
            out.append(f"- {c['conflict']}: {c['subsystems']} share "
                       f"{c['environment_path']} -> {c['resolution']}")
        out.append("")

    if "selection_admissible" in result:
        out += ["## SELECTION", "",
                f"- selected: {result.get('selected_subsystems') or '(none)'}",
                f"- admissible: {result.get('selection_admissible')}"]
        if result.get("refusal_reason"):
            out.append(f"- refusal: {result['refusal_reason']}")
        for nr in result.get("not_ready") or []:
            out.append(f"  - {nr['subsystem']}: {nr['existence_class']} / "
                       f"readiness {nr['readiness']} -> {nr['next_action']}")
        decision = result.get("environment_mode_decision") or {}
        out.append(f"- environment mode: {decision.get('environment_mode') or 'UNRESOLVED'} "
                   f"({decision.get('reason') or decision.get('next_action') or ''})")
        if decision.get("unselected_candidates"):
            out.append(f"- deliberately NOT selected: {decision['unselected_candidates']}")
        out.append("")

    out += ["## PHASE BOUNDARY", "",
            "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- this report is SYS-1..SYS-4 "
            "discovery/analysis only. No System-Level environment, System command.txt, "
            "System Virtual Sequencer or command routing is generated by this tool; "
            "that is SYS-40 and requires a separate explicit human approval."]
    return "\n".join(out)


# --- registry-only classification, for the gate scripts ----------------------

def classify_registry_claim(claim: Mapping[str, Any],
                            registered_entry: Optional[Mapping[str, Any]],
                            *, registry_cross_check_available: bool = True,
                            ) -> Dict[str, Any]:
    """SYS-2's five-way class derived from REGISTRY EVIDENCE ALONE -- no
    filesystem probe. This is what tools/real_env/system_level_validator.py
    can honestly compute at gate time, where the only inputs are the agent's
    claimed entry and the harness-supplied real registry.

    The mapping from that gate's existing FAIL reasons is deliberate rather
    than invented: MISSING_REQUIRED_FIELDS is partial evidence
    (EXISTS_PARTIAL), the two *_NOT_PASS verdicts and an invalid
    qualification_state are recorded blockers (EXISTS_BLOCKED), and
    SUBSYSTEM_NOT_REGISTERED is NOT_FOUND. A release_sha mismatch is the
    genuine EXISTS_UNKNOWN case: the subsystem certainly exists, but this
    evidence cannot tell you WHICH version of it you have, and guessing
    either way would be the fabrication SYS-2 forbids. So is the case where
    no real registry was supplied to cross-check against at all."""
    missing = [f for f in REGISTRY_REQUIRED_FIELDS if not claim.get(f)]
    if missing:
        return {"existence_class": EXISTS_PARTIAL,
                "reason": "MISSING_REQUIRED_FIELDS", "detail": missing}
    if claim.get("qualification_state") not in SYSTEM_LEVEL_STATES:
        return {"existence_class": EXISTS_BLOCKED,
                "reason": "INVALID_QUALIFICATION_STATE",
                "detail": claim.get("qualification_state")}
    if claim.get("interface_compatibility") != "PASS":
        return {"existence_class": EXISTS_BLOCKED,
                "reason": "INTERFACE_COMPATIBILITY_NOT_PASS",
                "detail": claim.get("interface_compatibility")}
    if claim.get("clock_reset_compatibility") != "PASS":
        return {"existence_class": EXISTS_BLOCKED,
                "reason": "CLOCK_RESET_COMPATIBILITY_NOT_PASS",
                "detail": claim.get("clock_reset_compatibility")}
    if not registry_cross_check_available:
        return {"existence_class": EXISTS_UNKNOWN,
                "reason": "NO_REGISTRY_CROSS_CHECK_SUPPLIED",
                "detail": ("the claim is internally complete but was not checked against "
                           "the real persisted registry, so registration cannot be told")}
    if registered_entry is None:
        return {"existence_class": NOT_FOUND, "reason": "SUBSYSTEM_NOT_REGISTERED",
                "detail": claim.get("name")}
    if registered_entry.get("release_sha") != claim.get("release_sha"):
        return {"existence_class": EXISTS_UNKNOWN,
                "reason": "SUBSYSTEM_RELEASE_SHA_MISMATCH",
                "detail": {"claimed": claim.get("release_sha"),
                           "registered": registered_entry.get("release_sha")}}
    return {"existence_class": EXISTS_READY, "reason": "REGISTERED_AND_COMPATIBLE",
            "detail": claim.get("release_sha")}
