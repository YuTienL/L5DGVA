"""SYS-34, SYS-35 and SYS-37 of the System-Level Verification Integration
workflow: the SUBSYSTEM VERSION PINNING snapshot, the SYSTEM ENVIRONMENT
READINESS derivation, and the KNOWLEDGE CENTER UPDATE record BUILDER.

WHAT THIS MODULE IS NOT
-----------------------
Stated first, because it is the boundary this whole workflow exists inside.
Nothing here creates a System-Level environment, a System command.txt, a System
Virtual Sequencer or any command routing/adapter, and nothing here PUBLISHES to
the shared Knowledge Center.

  * SYS-34 is split deliberately. `build_system_composition_record()` FILLS the
    record from real artifacts and pins `PHASE` to
    `knowledge_center.PHASE_1_PLAN`; `KnowledgeCenterClient.record_system_
    composition()` is the only thing that transports, and it REFUSES that
    phase. SYS-34's own first four words are "After successful integration",
    and this shard is read across projects and users -- a Phase-1 plan
    published there would later read as "this composition was built and
    passed". Keeping "the payload was built" and "the payload was published"
    two separately-visible events is the same split `syoscb_source_audit.
    build_component_registration_payload()` already makes for SYOSCB-3.
  * SYS-35 writes ONE planning artifact,
    `.dv-harness/soc-composer/system_composition_pins.json`, beside -- never
    into -- the real `subsystem_environment_registry.json` that engine.py owns.
  * SYS-37 derives a verdict and authorizes nothing. A READY verdict is an
    input to the SYS-39 human approval gate, not a substitute for it.

WHY SYS-35 IS A NEW ARTIFACT AND NOT A FIELD ON THE EXISTING REGISTRY
---------------------------------------------------------------------
`release_sha` pinning per subsystem is already real and gate-enforced:
`subsystem_environment_registration_gate.py` REQUIREs the field,
`engine._persist_subsystem_registry_entry()` writes it on a gate-validated
SIGNOFF PASS, and `tools/real_env/system_level_validator.py` hard-FAILs a
claimed SHA that does not match the registered one. None of that is rebuilt
here and `read_registered_subsystem_entries()` stays the single reader.

What does NOT exist is the COMPOSITION-level snapshot SYS-35's second half
needs ("...for reproducibility and Session Save/Restore"), and the reason is
structural rather than an omission: `_persist_subsystem_registry_entry()` is
insert-or-replace-BY-NAME, so a later SIGNOFF for the same subsystem
supersedes the earlier registration outright and the registry only ever holds
each subsystem's LATEST sha. A file whose every row is overwritten in place
cannot also be the immutable record of "composition X was built from
{PCIe@sha1, USB@sha2}". So the pin file is append-only and keyed by a
composition id derived from the pinned set itself: re-pinning the same set
re-mints the same id (idempotent), and pinning a set with one sha moved mints a
DIFFERENT id beside the old one rather than replacing it. That is what makes a
restore possible at all, and it is also SYS-36's base: a subsystem's diff is
taken against the sha this snapshot pinned.

`memory_router.py`/`memory_vault.py`'s `rtl_sha`/`tb_sha` are not that home
either -- they record which RTL a DEBUG FINDING was made against, a different
question from which subsystem releases one composition was assembled from.

WHY SYS-37 IS A SEPARATE VOCABULARY FROM qualification.py's
-----------------------------------------------------------
`qualification.map_to_system_level_state()` answers "how far has ONE subsystem
been proven" on a 3-value ladder (SMOKE/REGRESSION/PRODUCTION_QUALIFIED). SYS-37
asks whether a COMPOSITION of N subsystems can be integrated, which no
per-subsystem tier can express. It therefore reuses the four values
`subsystem_discovery` already defines for the READY/PARTIAL/BLOCKED/UNKNOWN
question (READINESS_CLASSES) rather than minting a fifth set of four strings --
same words, same meanings, one level up.

The per-INPUT status is a different question again and gets its own four
values: a SYS-4 factor asks "is this artifact on disk" (PRESENT/ABSENT), while
a SYS-37 input asks "is this integration concern clean" -- and an address map
that exists but contains a conflict is neither PRESENT-and-fine nor ABSENT.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import knowledge_center as kc
from . import subsystem_discovery as sd
from . import system_command_plan as scp
from . import system_regression_plan as srp
from . import system_resource_registry as srr
from . import system_scheduling_plan as ssp
from . import system_topology_analysis as sta

SCHEMA_VERSION = "1.0"

#: READY / PARTIAL / BLOCKED / UNKNOWN, reused rather than redeclared -- see the
#: module docstring. SYS-37's own four words are SYS-4's own four words.
READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN
SYSTEM_READINESS_CLASSES: tuple = sd.READINESS_CLASSES


# ===========================================================================
# SYS-35 vocabulary
# ===========================================================================

PIN_FILENAME = "system_composition_pins.json"
PIN_DIR = Path(".dv-harness") / "soc-composer"
PIN_SCHEMA_VERSION = "1.0"

#: A subsystem in the selection that carries no registered `release_sha`. It is
#: pinned as UNPINNED rather than omitted: a snapshot silently missing a
#: subsystem would restore a DIFFERENT composition than the one it claims.
UNPINNED = "UNPINNED_NO_REGISTERED_RELEASE_SHA"


class SystemReadinessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# SYS-35 -- SUBSYSTEM VERSION PINNING
# ===========================================================================

def composition_id(pins: Mapping[str, str]) -> str:
    """The composition's identity IS its pinned set. Derived from the sorted
    `subsystem@sha` pairs, so re-pinning an unchanged set is idempotent and a
    set with one sha moved is a different composition rather than a mutation of
    the old one."""
    material = "|".join(f"{name}@{pins[name]}" for name in sorted(pins))
    return "SYSCOMP-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12].upper()


def build_composition_version_pin(selection: Mapping[str, Any],
                                  registry_entries: Sequence[Mapping[str, Any]],
                                  *,
                                  pinned_at: str = "") -> Dict[str, Any]:
    """SYS-35: an immutable snapshot of exactly which subsystem release each
    member of this composition was assembled from.

    Every selected subsystem gets a row. One with no registered `release_sha`
    is pinned UNPINNED and counted, because that is the state that makes the
    whole snapshot unrestorable and SYS-36 undecidable for that subsystem --
    and a caller must be able to see it, not infer it from a short list."""
    by_name = {str(e.get("name") or "").lower(): e for e in registry_entries}
    rows: List[Dict[str, Any]] = []
    pins: Dict[str, str] = {}
    for row in selection.get("selected_rows") or []:
        sid = str(row.get("subsystem") or "")
        entry = by_name.get(sid.lower()) or {}
        sha = str(entry.get("release_sha") or "").strip()
        pins[sid] = sha or UNPINNED
        rows.append({
            "subsystem": sid,
            "release_sha": sha or UNPINNED,
            "pinned": bool(sha),
            "environment_path": str(row.get("environment_path") or ""),
            "environment_manifest": str(entry.get("environment_manifest") or ""),
            "qualification_state": entry.get("qualification_state"),
            "protocol": row.get("protocol"),
            "registered": bool(entry),
            "source": ("subsystem_environment_registry.release_sha" if sha else
                       "no registered release_sha for this subsystem"),
        })
    rows.sort(key=lambda r: r["subsystem"])
    unpinned = [r["subsystem"] for r in rows if not r["pinned"]]
    return {
        "schema_version": PIN_SCHEMA_VERSION,
        "composition_id": composition_id(pins),
        "subsystems": [r["subsystem"] for r in rows],
        "subsystem_versions": {r["subsystem"]: r["release_sha"] for r in rows},
        "subsystem_paths": {r["subsystem"]: r["environment_path"] for r in rows},
        "entries": rows,
        "pinned_at": pinned_at,
        "restorable": bool(rows) and not unpinned,
        "unpinned_subsystems": unpinned,
        "restore_note": (
            "every selected subsystem is pinned to a registered release_sha; this "
            "snapshot identifies one reproducible composition"
            if rows and not unpinned else
            "this snapshot cannot restore a composition: "
            f"{unpinned or 'no subsystem was selected'} carr(y/ies) no registered "
            "release_sha, so there is no version to restore to"),
        "supersedes_registry": False,
        "note": ("beside, never inside, .dv-harness/soc-composer/"
                 "subsystem_environment_registry.json, which engine.py owns and "
                 "which replaces each subsystem's row by name on every SIGNOFF"),
    }


def pin_path(root) -> Path:
    return Path(root) / PIN_DIR / PIN_FILENAME


def read_composition_pins(root) -> Dict[str, Any]:
    """Every pin ever recorded for this project, newest last. A missing or
    unreadable file degrades to an empty document -- the same defensive default
    `read_registered_subsystem_entries()` uses -- never a fabricated guess."""
    path = pin_path(root)
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        doc = {}
    return {"schema_version": doc.get("schema_version", PIN_SCHEMA_VERSION),
            "compositions": [c for c in (doc.get("compositions") or [])
                             if isinstance(c, dict) and c.get("composition_id")]}


def write_composition_pin(root, pin: Mapping[str, Any]) -> Path:
    """Append one SYS-35 snapshot, keyed by composition_id.

    APPEND-ONLY on purpose, and this is the whole difference from the registry
    it sits beside: `_persist_subsystem_registry_entry()` replaces a subsystem's
    row by name, which is right for "what is this subsystem's current release"
    and fatal for "what was composition X built from". Re-writing the SAME
    composition_id replaces that one entry (it is by construction the identical
    pinned set, so nothing is lost); a different set is added alongside."""
    path = pin_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_composition_pins(root)
    kept = [c for c in existing["compositions"]
            if c.get("composition_id") != pin.get("composition_id")]
    document = {"schema_version": PIN_SCHEMA_VERSION,
                "compositions": kept + [dict(pin)],
                "authority_scope": "PLANNING_ONLY",
                "note": ("SYS-35 composition snapshots. This file does not register, "
                         "qualify or authorize any subsystem; "
                         "subsystem_environment_registry.json remains the only "
                         "registration authority.")}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# ===========================================================================
# SYS-37 vocabulary
# ===========================================================================

#: SYS-37's own list, verbatim and in the requirement's own order: "subsystem
#: readiness, shared-resource conflicts, command compatibility, scoreboard
#: compatibility, address map, clock/reset, VIP dedup resolution, build
#: integration, scenario availability, regression evidence." TEN inputs -- the
#: sentence really does name ten, and a derivation over nine of them would be
#: silently dropping one. Held to that sentence by a test.
IN_SUBSYSTEM_READINESS = "subsystem_readiness"
IN_SHARED_RESOURCE_CONFLICTS = "shared_resource_conflicts"
IN_COMMAND_COMPATIBILITY = "command_compatibility"
IN_SCOREBOARD_COMPATIBILITY = "scoreboard_compatibility"
IN_ADDRESS_MAP = "address_map"
IN_CLOCK_RESET = "clock_reset"
IN_VIP_DEDUP_RESOLUTION = "vip_dedup_resolution"
IN_BUILD_INTEGRATION = "build_integration"
IN_SCENARIO_AVAILABILITY = "scenario_availability"
IN_REGRESSION_EVIDENCE = "regression_evidence"

SYS37_INPUTS: tuple = (
    IN_SUBSYSTEM_READINESS, IN_SHARED_RESOURCE_CONFLICTS, IN_COMMAND_COMPATIBILITY,
    IN_SCOREBOARD_COMPATIBILITY, IN_ADDRESS_MAP, IN_CLOCK_RESET,
    IN_VIP_DEDUP_RESOLUTION, IN_BUILD_INTEGRATION, IN_SCENARIO_AVAILABILITY,
    IN_REGRESSION_EVIDENCE,
)

#: Per-input status. Four values for the same reason SYS-4's factors have four:
#: "we looked and it is clean", "we looked and it is not", "a recorded verdict
#: stops this outright" and "we could not look" are four different facts, and
#: collapsing the last into the second is how an unexaminable composition
#: starts reporting as a broken one.
INPUT_CLEAR = "CLEAR"
INPUT_CONCERN = "CONCERN"
INPUT_BLOCKED = "BLOCKED"
INPUT_UNKNOWN = "UNKNOWN"
INPUT_STATUSES: tuple = (INPUT_CLEAR, INPUT_CONCERN, INPUT_BLOCKED, INPUT_UNKNOWN)

#: SYS-37's own closing rule: "Unresolved active-driver conflict normally
#: prevents READY." `system_resource_registry.CONFLICT_DRIVER` is the one place
#: in this repo that concept has a name, and SYS-11/12 already decided it -- so
#: this reads that field rather than re-deciding what an active-driver conflict
#: is. "Normally" is honoured as: it makes the VIP-dedup input BLOCKED, and a
#: BLOCKED input makes the whole verdict BLOCKED, which is not READY.
ACTIVE_DRIVER_CONFLICT_RULE = (
    "an unresolved DRIVER_CONFLICT in the SYS-15 registry blocks the VIP dedup "
    "resolution input, and any blocked input makes the system verdict BLOCKED")


def _input(name: str, status: str, evidence: str, **detail) -> Dict[str, Any]:
    if status not in INPUT_STATUSES:
        raise SystemReadinessError("UNKNOWN_INPUT_STATUS",
                                   {"input": name, "status": status})
    return {"input": name, "status": status, "evidence": evidence, **detail}


def _subsystem_readiness_input(selection: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-4's own per-subsystem verdicts, aggregated. A composition is no
    readier than its least ready member, so the aggregate takes the WORST
    value rather than a majority or an average."""
    rows = list(selection.get("selected_rows") or [])
    if not rows:
        return _input(IN_SUBSYSTEM_READINESS, INPUT_UNKNOWN,
                      "no subsystem was selected, so no SYS-4 readiness verdict exists",
                      per_subsystem={})
    per = {str(r.get("subsystem")): str(r.get("readiness") or sd.UNKNOWN) for r in rows}
    if any(v == sd.BLOCKED for v in per.values()):
        status, note = INPUT_BLOCKED, "at least one selected subsystem is SYS-4 BLOCKED"
    elif all(v == sd.READY for v in per.values()):
        status, note = INPUT_CLEAR, "every selected subsystem is SYS-4 READY"
    elif all(v == sd.UNKNOWN for v in per.values()):
        status, note = INPUT_UNKNOWN, "no selected subsystem could be evidenced at all"
    else:
        status, note = INPUT_CONCERN, "at least one selected subsystem is SYS-4 PARTIAL/UNKNOWN"
    return _input(IN_SUBSYSTEM_READINESS, status, f"{note}: {per}", per_subsystem=per)


def _shared_resource_input(scheduling_plan: Mapping[str, Any]) -> Dict[str, Any]:
    scheduling = scheduling_plan.get("shared_resource_scheduling") or {}
    summary = scheduling.get("summary") or {}
    by_disposition = summary.get("by_disposition") or {}
    if not summary:
        return _input(IN_SHARED_RESOURCE_CONFLICTS, INPUT_UNKNOWN,
                      "no SYS-24 shared-resource scheduling plan was supplied")
    unschedulable = by_disposition.get(ssp.SCHED_NOT_SCHEDULABLE, 0)
    serialization = (scheduling_plan.get("global_serialization_check") or {}).get("verdict")
    if unschedulable:
        return _input(IN_SHARED_RESOURCE_CONFLICTS, INPUT_BLOCKED,
                      f"{unschedulable} SYS-24 row(s) are NOT_SCHEDULABLE pending "
                      "ownership resolution",
                      not_schedulable=unschedulable)
    if serialization == ssp.GLOBAL_SERIALIZATION_DETECTED:
        return _input(IN_SHARED_RESOURCE_CONFLICTS, INPUT_CONCERN,
                      "SYS-24's no-global-serialization check reported "
                      f"{ssp.GLOBAL_SERIALIZATION_DETECTED}")
    return _input(IN_SHARED_RESOURCE_CONFLICTS, INPUT_CLEAR,
                  f"{summary.get('row_count', 0)} shared-resource row(s), none "
                  f"unschedulable; serialization verdict={serialization}")


def _command_compatibility_input(command_plan: Mapping[str, Any]) -> Dict[str, Any]:
    summary = command_plan.get("summary") or {}
    if not summary:
        return _input(IN_COMMAND_COMPATIBILITY, INPUT_UNKNOWN,
                      "no SYS-18..22 command plan was supplied")
    blocking = summary.get("blocking_collisions", 0)
    preserved = summary.get("subsystem_modes_preserved")
    if blocking:
        return _input(IN_COMMAND_COMPATIBILITY, INPUT_BLOCKED,
                      f"{blocking} blocking SYS-22 command collision(s)",
                      blocking_collisions=blocking)
    if preserved is False:
        return _input(IN_COMMAND_COMPATIBILITY, INPUT_CONCERN,
                      "SYS-20 found at least one subsystem's SUBSYSTEM_MODE at risk")
    if preserved is None:
        return _input(IN_COMMAND_COMPATIBILITY, INPUT_UNKNOWN,
                      "the command plan recorded no backward-compatibility verdict")
    return _input(IN_COMMAND_COMPATIBILITY, INPUT_CLEAR,
                  f"{summary.get('collisions', 0)} collision(s), none blocking; "
                  "every subsystem's SUBSYSTEM_MODE preserved")


def _scoreboard_input(scheduling_plan: Mapping[str, Any]) -> Dict[str, Any]:
    scoreboards = scheduling_plan.get("scoreboard_integration") or {}
    summary = scoreboards.get("summary") or {}
    if not summary:
        return _input(IN_SCOREBOARD_COMPATIBILITY, INPUT_UNKNOWN,
                      "no SYS-26 scoreboard integration plan was supplied")
    if summary.get("scoreboards_modified") or summary.get("scoreboards_replaced"):
        return _input(IN_SCOREBOARD_COMPATIBILITY, INPUT_BLOCKED,
                      "a subsystem scoreboard is recorded as modified or replaced, "
                      "which SYS-26 forbids")
    missing = summary.get("topology_descriptor_parts_missing", 0)
    reused = summary.get("scoreboards_reused", 0)
    if not reused:
        return _input(IN_SCOREBOARD_COMPATIBILITY, INPUT_UNKNOWN,
                      "no subsystem scoreboard appears in the SYS-9 inventory or the "
                      "SYS-15 registry, so compatibility could not be assessed",
                      topology_descriptor_parts_missing=missing)
    if missing:
        return _input(IN_SCOREBOARD_COMPATIBILITY, INPUT_CONCERN,
                      f"{reused} subsystem scoreboard(s) reusable, but {missing} "
                      "cross-subsystem topology descriptor part(s) the correlation "
                      "layer needs are absent",
                      topology_descriptor_parts_missing=missing)
    return _input(IN_SCOREBOARD_COMPATIBILITY, INPUT_CLEAR,
                  f"{reused} subsystem scoreboard(s) reused unmodified; every "
                  "topology descriptor part is available")


def _address_map_input(topology_analysis: Mapping[str, Any]) -> Dict[str, Any]:
    address = topology_analysis.get("address_map_reconciliation") or {}
    summary = address.get("summary") or {}
    if not summary:
        return _input(IN_ADDRESS_MAP, INPUT_UNKNOWN,
                      "no SYS-28 address-map reconciliation was supplied")
    conflicts = summary.get("conflicts", 0)
    self_overlap = list(summary.get("subsystems_with_self_overlap") or [])
    unknowns = (summary.get("by_verdict") or {}).get(sta.ADDRESS_UNKNOWN, 0)
    if conflicts:
        return _input(IN_ADDRESS_MAP, INPUT_BLOCKED,
                      f"{conflicts} cross-subsystem ADDRESS_OVERLAP_CONFLICT(s)",
                      conflicts=conflicts)
    if self_overlap:
        return _input(IN_ADDRESS_MAP, INPUT_CONCERN,
                      f"{self_overlap} declare an address map that overlaps itself",
                      subsystems_with_self_overlap=self_overlap)
    if not summary.get("region_count"):
        return _input(IN_ADDRESS_MAP, INPUT_UNKNOWN,
                      "no subsystem supplied an address map to reconcile")
    if unknowns:
        return _input(IN_ADDRESS_MAP, INPUT_CONCERN,
                      f"{unknowns} overlap(s) classified UNKNOWN -- the inputs "
                      "themselves are in doubt", unknown_overlaps=unknowns)
    return _input(IN_ADDRESS_MAP, INPUT_CLEAR,
                  f"{summary['region_count']} region(s), "
                  f"{summary.get('overlapping_pairs', 0)} overlap(s), no conflict")


def _clock_reset_input(topology_analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-29's own computed verdict, read rather than recomputed.
    `clock_reset_compatibility_input()` is deliberately three-valued and its
    UNKNOWN must never round up to PASS -- that is the whole reason it exists
    beside the self-attested PASS/FAIL string the registration gate takes on
    trust."""
    computed = topology_analysis.get("clock_reset_compatibility_input") or {}
    comparison = topology_analysis.get("clock_reset_comparison") or {}
    value = computed.get("computed_value")
    if not value:
        return _input(IN_CLOCK_RESET, INPUT_UNKNOWN,
                      "no SYS-29 clock/reset comparison was supplied")
    conflicts = (comparison.get("summary") or {}).get("conflicts", 0)
    if value == "FAIL" or conflicts:
        return _input(IN_CLOCK_RESET, INPUT_BLOCKED,
                      f"SYS-29 computed clock_reset_compatibility={value} "
                      f"({conflicts} conflict(s)): {computed.get('reason')}",
                      conflicts=conflicts)
    if value == "PASS":
        return _input(IN_CLOCK_RESET, INPUT_CLEAR,
                      f"SYS-29 computed clock_reset_compatibility=PASS: "
                      f"{computed.get('reason')}")
    return _input(IN_CLOCK_RESET, INPUT_UNKNOWN,
                  f"SYS-29 computed clock_reset_compatibility={value}: "
                  f"{computed.get('reason')}")


def _vip_dedup_input(integration_plan: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-37's named exception lives here. `CONFLICT_DRIVER` is SYS-11/12's
    verdict, already recorded on the registry entry -- this reads it."""
    registry = integration_plan.get("system_resource_registry") or {}
    dedup = integration_plan.get("vip_agent_deduplication_matrix") or {}
    summary = registry.get("summary") or {}
    if not summary:
        return _input(IN_VIP_DEDUP_RESOLUTION, INPUT_UNKNOWN,
                      "no SYS-15 registry was supplied")
    by_conflict = summary.get("entries_by_conflict_status") or {}
    driver_conflicts = by_conflict.get(srr.CONFLICT_DRIVER, 0)
    held = by_conflict.get(srr.CONFLICT_UNPROVEN_DUPLICATE, 0)
    blocked_decisions = (dedup.get("summary") or {}).get("blocked", 0)
    conflicting_entries = sorted(
        e["resource_id"] for e in (registry.get("entries") or [])
        if e.get("conflict_status") == srr.CONFLICT_DRIVER)
    if driver_conflicts or blocked_decisions:
        return _input(IN_VIP_DEDUP_RESOLUTION, INPUT_BLOCKED,
                      f"{driver_conflicts} unresolved DRIVER_CONFLICT registry "
                      f"entr(y/ies) and {blocked_decisions} BLOCKED dedup decision(s). "
                      + ACTIVE_DRIVER_CONFLICT_RULE,
                      driver_conflicts=driver_conflicts,
                      blocked_decisions=blocked_decisions,
                      conflicting_resources=conflicting_entries)
    if held:
        return _input(IN_VIP_DEDUP_RESOLUTION, INPUT_CONCERN,
                      f"{held} duplicate(s) HELD pending physical-equivalence evidence",
                      held=held)
    unknown_decisions = (summary.get("entries_by_reuse_decision") or {}).get(
        srr.DECISION_UNKNOWN, 0)
    if unknown_decisions:
        return _input(IN_VIP_DEDUP_RESOLUTION, INPUT_CONCERN,
                      f"{unknown_decisions} registry entr(y/ies) carry an UNKNOWN "
                      "reuse decision", unknown_decisions=unknown_decisions)
    return _input(IN_VIP_DEDUP_RESOLUTION, INPUT_CLEAR,
                  f"{summary.get('entry_count', 0)} registry entr(y/ies), no "
                  "DRIVER_CONFLICT and no blocked dedup decision")


def _build_integration_input(selection: Mapping[str, Any],
                             pin: Mapping[str, Any]) -> Dict[str, Any]:
    """Build integration at Phase 1 is a question about INPUTS, not about a
    build: no System-Level filelist exists to compile, because writing one is
    SYS-40. What can be evidenced is whether every selected subsystem has its
    own build present (SYS-4's `build` factor) and is pinned to a release the
    build could be reproduced from."""
    rows = list(selection.get("selected_rows") or [])
    if not rows:
        return _input(IN_BUILD_INTEGRATION, INPUT_UNKNOWN,
                      "no subsystem was selected, so no build inputs exist")
    per: Dict[str, str] = {}
    for row in rows:
        factor = ((row.get("readiness_factors") or {}).get("build") or {})
        per[str(row.get("subsystem"))] = str(factor.get("status") or sd.UNKNOWN)
    missing_build = sorted(s for s, v in per.items() if v == sd.ABSENT)
    blocked_build = sorted(s for s, v in per.items() if v == sd.BLOCKED)
    unknown_build = sorted(s for s, v in per.items() if v == sd.UNKNOWN)
    unpinned = list(pin.get("unpinned_subsystems") or [])
    if blocked_build:
        return _input(IN_BUILD_INTEGRATION, INPUT_BLOCKED,
                      f"{blocked_build} carry a BLOCKED SYS-4 build factor",
                      per_subsystem=per)
    if missing_build or unpinned:
        return _input(IN_BUILD_INTEGRATION, INPUT_CONCERN,
                      f"absent build scripts for {missing_build or 'none'}; "
                      f"unpinned subsystems {unpinned or 'none'}",
                      per_subsystem=per, unpinned_subsystems=unpinned)
    if unknown_build:
        return _input(IN_BUILD_INTEGRATION, INPUT_UNKNOWN,
                      f"{unknown_build} could not be probed for build scripts",
                      per_subsystem=per)
    return _input(IN_BUILD_INTEGRATION, INPUT_CLEAR,
                  "every selected subsystem has its own build scripts on disk and is "
                  "pinned to a registered release_sha",
                  per_subsystem=per,
                  system_filelist="NOT_WRITTEN_SYS40_REQUIRES_HUMAN_APPROVAL")


def _scenario_availability_input(topology_analysis: Mapping[str, Any]) -> Dict[str, Any]:
    model = topology_analysis.get("system_scenario_model") or {}
    summary = model.get("summary") or {}
    if not summary:
        return _input(IN_SCENARIO_AVAILABILITY, INPUT_UNKNOWN,
                      "no SYS-30 scenario model was supplied")
    cross = summary.get("cross_subsystem_scenarios", 0)
    total = summary.get("scenario_count", 0)
    if not cross:
        return _input(IN_SCENARIO_AVAILABILITY, INPUT_CONCERN,
                      f"{total} scenario shape(s) planned, none of them cross-subsystem: "
                      "there is nothing a System-Level run would exercise that a "
                      "subsystem run does not", scenario_count=total)
    return _input(IN_SCENARIO_AVAILABILITY, INPUT_CLEAR,
                  f"{cross} cross-subsystem scenario shape(s) of {total} planned "
                  f"(bodies: {summary.get('scenario_bodies_generated', 0)} generated -- "
                  "SYS-40 writes those)", cross_subsystem_scenarios=cross)


def _regression_evidence_input(selection: Mapping[str, Any],
                               regression_plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Two halves, both required: each subsystem's OWN recorded regression
    evidence (SYS-4's `regression_evidence` factor), and whether a SYS-33 plan
    could be built at all. A composition with healthy subsystem regressions but
    no derivable system plan is not ready, and neither is the reverse."""
    rows = list(selection.get("selected_rows") or [])
    per = {str(r.get("subsystem")):
           str(((r.get("readiness_factors") or {}).get("regression_evidence")
                or {}).get("status") or sd.UNKNOWN)
           for r in rows}
    missing = sorted(s for s, v in per.items() if v != sd.PRESENT)
    planned = (regression_plan or {}).get("summary", {}).get("entry_count")
    if regression_plan is None:
        return _input(IN_REGRESSION_EVIDENCE, INPUT_UNKNOWN,
                      "no SYS-33 regression plan was supplied; per-subsystem "
                      f"regression evidence is {per}", per_subsystem=per)
    if not rows:
        return _input(IN_REGRESSION_EVIDENCE, INPUT_UNKNOWN,
                      "no subsystem was selected, so no regression evidence exists")
    if not planned:
        return _input(IN_REGRESSION_EVIDENCE, INPUT_CONCERN,
                      "the SYS-33 plan derived no regression entry at all",
                      per_subsystem=per, planned_entries=0)
    if missing:
        return _input(IN_REGRESSION_EVIDENCE, INPUT_CONCERN,
                      f"{missing} carry no PRESENT SYS-4 regression evidence "
                      f"(SYS-33 planned {planned} entr(y/ies))",
                      per_subsystem=per, planned_entries=planned)
    return _input(IN_REGRESSION_EVIDENCE, INPUT_CLEAR,
                  f"every selected subsystem has recorded regression evidence and "
                  f"SYS-33 planned {planned} entr(y/ies)",
                  per_subsystem=per, planned_entries=planned)


def derive_system_readiness(selection: Mapping[str, Any],
                            integration_plan: Mapping[str, Any],
                            command_plan: Mapping[str, Any],
                            scheduling_plan: Mapping[str, Any],
                            topology_analysis: Mapping[str, Any],
                            *,
                            version_pin: Optional[Mapping[str, Any]] = None,
                            regression_plan: Optional[Mapping[str, Any]] = None,
                            ) -> Dict[str, Any]:
    """SYS-37: READY / PARTIAL / BLOCKED / UNKNOWN over the ten inputs SYS-37
    names, with the same precedence `subsystem_discovery.
    derive_subsystem_readiness()` established one level down -- deliberately,
    so "READY" means the same thing at both levels:

      BLOCKED  any input is BLOCKED. A known blocker outranks everything, and
               an unresolved active-driver conflict is exactly such a blocker
               (SYS-37's own closing sentence).
      UNKNOWN  no blocker, and NOTHING could be evidenced (every input
               UNKNOWN). A composition nobody could examine must not be
               reported with the same word as one examined and found lacking.
      READY    no blocker, and all ten inputs CLEAR. Nothing less: a single
               UNKNOWN input keeps a composition out of READY, because
               not-yet-checked never rounds up.
      PARTIAL  everything else.

    A READY verdict authorizes nothing. SYS-39 still stops for a human.
    """
    pin = dict(version_pin or {})
    inputs = [
        _subsystem_readiness_input(selection),
        _shared_resource_input(scheduling_plan),
        _command_compatibility_input(command_plan),
        _scoreboard_input(scheduling_plan),
        _address_map_input(topology_analysis),
        _clock_reset_input(topology_analysis),
        _vip_dedup_input(integration_plan),
        _build_integration_input(selection, pin),
        _scenario_availability_input(topology_analysis),
        _regression_evidence_input(selection, regression_plan),
    ]
    names = [i["input"] for i in inputs]
    if names != list(SYS37_INPUTS):
        raise SystemReadinessError("SYS37_INPUT_SET_MISMATCH", {
            "produced": names, "required": list(SYS37_INPUTS)})

    by_status = {s: [i["input"] for i in inputs if i["status"] == s]
                 for s in INPUT_STATUSES}
    if by_status[INPUT_BLOCKED]:
        readiness = BLOCKED
        why = ("blocked input(s): " + "; ".join(
            f"{i['input']}: {i['evidence']}" for i in inputs
            if i["status"] == INPUT_BLOCKED))
    elif len(by_status[INPUT_UNKNOWN]) == len(SYS37_INPUTS):
        readiness = UNKNOWN
        why = ("no SYS-37 input could be evidenced at all -- insufficient evidence to "
               "classify system readiness (not the same as evidenced-and-incomplete)")
    elif not by_status[INPUT_CONCERN] and not by_status[INPUT_UNKNOWN]:
        readiness = READY
        why = f"all {len(SYS37_INPUTS)} SYS-37 inputs are CLEAR"
    else:
        readiness = PARTIAL
        why = (f"{len(by_status[INPUT_CLEAR])}/{len(SYS37_INPUTS)} inputs clear; "
               f"concerns={by_status[INPUT_CONCERN]}; unknown={by_status[INPUT_UNKNOWN]}")

    driver_input = next(i for i in inputs if i["input"] == IN_VIP_DEDUP_RESOLUTION)
    return {
        "schema_version": SCHEMA_VERSION,
        "readiness_classes": list(SYSTEM_READINESS_CLASSES),
        "system_readiness": readiness,
        "evidence": why,
        "inputs": inputs,
        "by_status": by_status,
        "active_driver_conflict": {
            "rule": ACTIVE_DRIVER_CONFLICT_RULE,
            "unresolved": driver_input["status"] == INPUT_BLOCKED,
            "conflicting_resources": list(driver_input.get("conflicting_resources") or []),
            "prevents_ready": (driver_input["status"] == INPUT_BLOCKED
                               and readiness != READY),
        },
        "authorizes": "NOTHING -- SYS-39 stops for explicit user approval regardless "
                      "of this verdict; integration is SYS-40",
        "summary": {
            "system_readiness": readiness,
            "inputs_total": len(SYS37_INPUTS),
            "inputs_clear": len(by_status[INPUT_CLEAR]),
            "inputs_concern": len(by_status[INPUT_CONCERN]),
            "inputs_blocked": len(by_status[INPUT_BLOCKED]),
            "inputs_unknown": len(by_status[INPUT_UNKNOWN]),
        },
    }


# ===========================================================================
# SYS-34 -- KNOWLEDGE CENTER UPDATE (record builder; no transport)
# ===========================================================================

def build_system_composition_record(version_pin: Mapping[str, Any],
                                    integration_plan: Mapping[str, Any],
                                    command_plan: Mapping[str, Any],
                                    scheduling_plan: Mapping[str, Any],
                                    topology_analysis: Mapping[str, Any],
                                    readiness: Mapping[str, Any],
                                    *,
                                    regression_plan: Optional[Mapping[str, Any]] = None,
                                    protocol: str = "_general",
                                    ) -> Dict[str, Any]:
    """SYS-34's field set, filled from real artifacts. Performs no transport.

    PHASE is pinned to `knowledge_center.PHASE_1_PLAN` and cannot be raised
    here: SYS-34 records knowledge AFTER successful integration, and
    `record_system_composition()` refuses this phase for exactly that reason.
    A SYS-40 caller that has really integrated re-stamps it, having something
    to stamp it with."""
    registry = integration_plan.get("system_resource_registry") or {"entries": []}
    dedup = integration_plan.get("vip_agent_deduplication_matrix") or {}
    routing = command_plan.get("system_command_routing_plan") or {}
    scoreboards = scheduling_plan.get("scoreboard_integration") or {}
    scenarios = topology_analysis.get("system_scenario_model") or {}

    shared_decisions = [
        {"resource_id": e["resource_id"], "reuse_decision": e.get("reuse_decision"),
         "owner": e.get("owner"), "consumer_subsystems": list(e.get("consumer_subsystems") or []),
         "conflict_status": e.get("conflict_status")}
        for e in (registry.get("entries") or [])
        if e.get("shared") == srr.SHARED_ACROSS_SUBSYSTEMS
        or e.get("reuse_decision") != srr.KEEP_INDEPENDENT]

    # SYS-17's matrix rows are keyed by its own mandated COLUMN HEADERS
    # (`SYS17_COLUMNS`), not by snake_case field names -- read them as they are
    # rather than guessing at both spellings.
    dedup_decisions = [
        {"resource": row.get("Resource"),
         "subsystems": [row.get("Subsystem A"), row.get("Subsystem B")],
         "physical_interface": row.get("Physical Interface"),
         "relationship": row.get("Relationship"),
         "active_driver_conflict": row.get("Active Driver Conflict"),
         "decision": row.get("Decision"),
         "system_owner": row.get("System Owner")}
        for row in (dedup.get("rows") or [])]

    command_mappings = [
        {"system_command": row.get("system_command"),
         "source_subsystem": row.get("source_subsystem"),
         "source_command": row.get("source_command"),
         "routes_to_agent": row.get("routes_to_agent"),
         "routes_to_sequence": row.get("routes_to_sequence"),
         "route_verdict": row.get("route_verdict")}
        for row in (routing.get("rows") or [])]

    limitations: List[str] = [
        "SYS-40 not performed: no System-Level environment, System command.txt, "
        "System Virtual Sequencer or command routing/adapter exists for this "
        "composition.",
        "Scenario bodies are NOT_GENERATED "
        f"({scenarios.get('summary', {}).get('scenario_bodies_generated', 0)} generated); "
        "the SYS-26 correlation layer is PLANNED_NOT_IMPLEMENTED.",
    ]
    if version_pin.get("unpinned_subsystems"):
        limitations.append(
            "Not reproducible: no registered release_sha for "
            f"{version_pin['unpinned_subsystems']}.")
    missing_topology = (scoreboards.get("summary") or {}).get(
        "topology_descriptor_parts_missing", 0)
    if missing_topology:
        limitations.append(
            f"{missing_topology} cross-subsystem topology descriptor part(s) absent, so "
            "cross-subsystem checking content has no primary source.")
    for row in (readiness.get("inputs") or []):
        if row["status"] in (INPUT_BLOCKED, INPUT_CONCERN):
            limitations.append(f"SYS-37 {row['input']} = {row['status']}: {row['evidence']}")

    return {
        "COMPOSITION_ID": version_pin.get("composition_id", ""),
        "SYSTEM_COMPOSITION": list(version_pin.get("subsystems") or []),
        "SUBSYSTEM_VERSIONS": dict(version_pin.get("subsystem_versions") or {}),
        "SUBSYSTEM_PATHS": dict(version_pin.get("subsystem_paths") or {}),
        "SHARED_RESOURCE_DECISIONS": shared_decisions,
        "DEDUPLICATION_DECISIONS": dedup_decisions,
        "COMMAND_MAPPINGS": command_mappings,
        # Deliberately a POINTER to the plan, never command text. SYS-34's own
        # field is "System command.txt"; at Phase 1 the honest value of that
        # field is the plan's identity plus the fact that nothing was written.
        "SYSTEM_COMMAND_TXT": {
            "status": "NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL",
            "plan_reference": "system_command_plan.build_system_command_plan()",
            "system_commands_planned": (command_plan.get("summary") or {}).get(
                "system_commands", 0),
            "command_txt_written": 0,
        },
        "KNOWN_LIMITATIONS": limitations,
        "PASS_EVIDENCE": {
            "system_level_pass": "NONE -- no System-Level run has occurred",
            "per_subsystem": {
                r["subsystem"]: r.get("qualification_state")
                for r in (version_pin.get("entries") or [])},
        },
        "REGRESSION_EVIDENCE": {
            "system_regression_executed": 0,
            "planned_entries": (regression_plan or {}).get("summary", {}).get(
                "entry_count", 0),
            "concatenation_verdict": (regression_plan or {}).get(
                "concatenation_check", {}).get("verdict"),
        },
        "ARCHITECTURE_DECISIONS": {
            "system_architecture": (command_plan.get("system_architecture") or {}).get(
                "root", scp.SYSTEM_ROOT),
            "registry_entries": (registry.get("summary") or {}).get("entry_count", 0),
            "collapsed_resources": (registry.get("summary") or {}).get(
                "collapsed_resource_count", 0),
            "scoreboards_reused": (scoreboards.get("summary") or {}).get(
                "scoreboards_reused", 0),
            "scoreboards_replaced": 0,
            "cross_subsystem_scenarios_planned": (scenarios.get("summary") or {}).get(
                "cross_subsystem_scenarios", 0),
        },
        "SYSTEM_READINESS": readiness.get("system_readiness", UNKNOWN),
        "PHASE": kc.PHASE_1_PLAN,
        "EVIDENCE": readiness.get("evidence", ""),
        "CONFIDENCE": "PLANNING_ONLY -- derived from static repository evidence; no "
                      "System-Level simulation has been run",
        "_protocol": protocol,
    }


def publish_system_composition_record(client: Any,
                                      record: Mapping[str, Any]) -> Dict[str, Any]:
    """Hand a built record to the real `KnowledgeCenterClient`. Kept as a thin
    named function so the ONE place this workflow could reach the shared store
    is greppable, and so a caller with no client configured gets an honest
    result rather than an AttributeError."""
    if client is None:
        return {"ok": False, "error": "NO_KNOWLEDGE_CENTER_CLIENT",
                "detail": "SYS-34 is a no-op without a configured Knowledge Center"}
    return client.record_system_composition(
        dict(record), protocol=str(record.get("_protocol") or "_general"))


# ===========================================================================
# Front door
# ===========================================================================

def assess_system_readiness(root, selected: Sequence[str], *,
                            declared: Optional[Mapping[str, Any]] = None,
                            knowledge_center_client: Any = None,
                            inventory_overlay_path=None,
                            question_store: Any = None,
                            head_rev: str = "HEAD",
                            pinned_at: str = "",
                            ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..30 analysis (reused wholesale
    through `system_topology_analysis.analyze_system_topology()`) -> SYS-33
    regression plan -> SYS-35 pin -> SYS-36 change impact -> SYS-37 readiness
    -> SYS-34 record.

    Nothing is written and nothing is published. `write_composition_pin()` and
    `publish_system_composition_record()` are separate, explicit calls."""
    from .environment_mode_router import read_registered_subsystem_entries

    result = sta.analyze_system_topology(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path,
        question_store=question_store)
    registry_entries = read_registered_subsystem_entries(Path(root))

    regression_plan = srp.build_system_regression_plan(
        result["selection"], result["integration_plan"], result["command_plan"],
        result["scheduling_plan"], result["topology_analysis"],
        registry_entries=registry_entries)
    version_pin = build_composition_version_pin(
        result["selection"], registry_entries, pinned_at=pinned_at)
    change_impact = srp.compute_subsystem_change_impact(
        root, result["selection"], result["integration_plan"], result["command_plan"],
        result["scheduling_plan"], result["topology_analysis"],
        registry_entries=registry_entries, head_rev=head_rev)
    targeted = srp.select_targeted_system_regression(regression_plan, change_impact)
    readiness = derive_system_readiness(
        result["selection"], result["integration_plan"], result["command_plan"],
        result["scheduling_plan"], result["topology_analysis"],
        version_pin=version_pin, regression_plan=regression_plan)
    record = build_system_composition_record(
        version_pin, result["integration_plan"], result["command_plan"],
        result["scheduling_plan"], result["topology_analysis"], readiness,
        regression_plan=regression_plan)
    return {**result,
            "registry_entries": registry_entries,
            "regression_plan": regression_plan,
            "version_pin": version_pin,
            "change_impact": change_impact,
            "targeted_regression": targeted,
            "system_readiness": readiness,
            "knowledge_center_record": record}


# ===========================================================================
# Reporting
# ===========================================================================

def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_version_pin_table(pin: Mapping[str, Any]) -> str:
    header = "| Subsystem | release_sha | Pinned | Qualification | Environment path |"
    lines = [header, "|" + "---|" * 5]
    for row in pin.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["subsystem"], row["release_sha"][:16],
            "YES" if row["pinned"] else "NO",
            row.get("qualification_state") or "-",
            row.get("environment_path") or "-")) + " |")
    if len(lines) == 2:
        lines.append("| _no subsystem was selected to pin_ |" + " |" * 4)
    return "\n".join(lines)


def render_system_readiness_table(readiness: Mapping[str, Any]) -> str:
    header = "| SYS-37 input | Status | Evidence |"
    lines = [header, "|---|---|---|"]
    for row in readiness.get("inputs") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["input"], row["status"], row["evidence"])) + " |")
    return "\n".join(lines)


def format_system_readiness_report(readiness: Mapping[str, Any],
                                   version_pin: Optional[Mapping[str, Any]] = None,
                                   record: Optional[Mapping[str, Any]] = None) -> str:
    """The SYS-35/SYS-37/SYS-34 section of the Phase-1 report."""
    summary = readiness["summary"]
    out = [
        "# SYSTEM ENVIRONMENT READINESS (SYS-37), VERSION PINNING (SYS-35) AND "
        "KNOWLEDGE CENTER UPDATE (SYS-34)",
        "",
        "## SYS-35 SUBSYSTEM VERSION PINNING",
        "",
    ]
    if version_pin is None:
        out.append("_Not computed. Run "
                   "`system_readiness.build_composition_version_pin()`._")
    else:
        out += [
            f"Composition `{version_pin['composition_id']}` over "
            f"{len(version_pin['subsystems'])} subsystem(s); "
            f"restorable={version_pin['restorable']}.",
            "",
            version_pin["restore_note"],
            "",
            render_version_pin_table(version_pin),
        ]
    out += [
        "",
        "## SYS-37 SYSTEM ENVIRONMENT READINESS",
        "",
        f"**{readiness['system_readiness']}** -- {readiness['evidence']}",
        "",
        f"{summary['inputs_clear']} clear / {summary['inputs_concern']} concern / "
        f"{summary['inputs_blocked']} blocked / {summary['inputs_unknown']} unknown, "
        f"of {summary['inputs_total']} SYS-37 inputs.",
        "",
        render_system_readiness_table(readiness),
        "",
        f"Active-driver conflict rule: {readiness['active_driver_conflict']['rule']}. "
        f"Unresolved: {readiness['active_driver_conflict']['unresolved']}"
        + (f" ({readiness['active_driver_conflict']['conflicting_resources']})"
           if readiness["active_driver_conflict"]["conflicting_resources"] else ""),
        "",
        f"This verdict authorizes: {readiness['authorizes']}",
        "",
        "## SYS-34 KNOWLEDGE CENTER UPDATE",
        "",
    ]
    if record is None:
        out.append("_Not built. Run "
                   "`system_readiness.build_system_composition_record()`._")
    else:
        out += [
            f"Record built for `{record['COMPOSITION_ID']}` on the existing shared "
            f"Knowledge Center's `{kc.SYSTEM_COMPOSITION_CATEGORY}` category "
            f"({len(kc.SYSTEM_COMPOSITION_FIELDS)} fields). No parallel knowledge "
            "store is created.",
            "",
            f"PHASE = `{record['PHASE']}`, which "
            "`KnowledgeCenterClient.record_system_composition()` REFUSES to publish: "
            "SYS-34 records knowledge after successful integration, and SYS-39 stops "
            "before SYS-40.",
            "",
            "### Recorded limitations",
            "",
        ]
        for limitation in record["KNOWN_LIMITATIONS"]:
            out.append(f"- {limitation}")
    return "\n".join(out)


def _assert_input_set_matches_the_requirement() -> None:
    """SYS-37 names ten inputs in one sentence. Import-time check that the
    tuple still has exactly those ten -- the audit that preceded this module
    counted nine, which is precisely the mistake a derivation over a
    hand-transcribed list makes silently."""
    if len(SYS37_INPUTS) != 10 or len(set(SYS37_INPUTS)) != 10:
        raise SystemReadinessError("SYS37_INPUT_SET_CHANGED", {
            "inputs": list(SYS37_INPUTS), "expected_count": 10,
            "requirement": "SYS-37: subsystem readiness, shared-resource conflicts, "
                           "command compatibility, scoreboard compatibility, address "
                           "map, clock/reset, VIP dedup resolution, build integration, "
                           "scenario availability, regression evidence"})


_assert_input_set_matches_the_requirement()
