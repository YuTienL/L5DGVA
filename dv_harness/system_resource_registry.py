"""SYS-15..SYS-17 of the System-Level Verification Integration workflow: the
SYSTEM_RESOURCE_REGISTRY ("the authority for System-Level resource
composition"), the mandatory SUBSYSTEM INTEGRATION MATRIX, and the mandatory
VIP / AGENT DEDUPLICATION MATRIX.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
Two existing registries were candidates for "extend", and both are a
different granularity than SYS-15 asks for:

  * `.dv-harness/soc-composer/subsystem_environment_registry.json`, written
    solely by `engine._persist_subsystem_registry_entry()` on a gate-verified
    SIGNOFF PASS, holds SUBSYSTEM-granularity identity/qualification metadata:
    exactly `name`, `environment_manifest`, `release_sha`,
    `qualification_state`, `interface_compatibility`,
    `clock_reset_compatibility` (the `REQUIRED` list of
    `tools/real_env/system_level_validator.py`). One row per ENVIRONMENT. It
    answers "may this subsystem participate", not "what resources does the
    System own". Adding resource rows to it would break every reader that
    validates it against that six-field contract.
  * `connectivity.MATRIX_COLUMNS` is one row per INTERFACE of ONE environment,
    with no subsystem-identifying column at all -- so it structurally cannot
    hold `owner` / `consumer_subsystems`, which is the whole point of SYS-15.

SYS-15's registry is a THIRD granularity: one row per SYSTEM-LEVEL resource,
where the same physical resource seen in two subsystems' evidence COLLAPSES
into ONE entry whose `owner` and `consumer_subsystems` are different fields.
That collapse is only expressible over N subsystems at once, so like
`system_resource_inventory` (SYS-9..14) it has no single-subsystem home.

Everything here IMPORTS and COMPOSES the layer below rather than restating it:

  * `system_resource_inventory` (SYS-9..14) supplies every input: the SYS-9
    resource records, SYS-11's relationship verdicts, SYS-12's stopped/held
    sets, SYS-13's promotion evaluation and SYS-14's ownership preservation.
    No signal is recomputed here, and no second relationship classifier,
    conflict rule or promotion evaluator is defined.
  * `subsystem_discovery` (SYS-1..4) supplies SYS-16's Readiness and
    Environment columns -- the SAME verdicts SYS-1's own table prints, never a
    second readiness classifier.
  * `subsystem_architecture_analysis` (SYS-5..6) supplies SYS-16's Scoreboard
    column from its real SYS-6 `scoreboards` field, with that field's own
    three-valued DERIVED / NOT_AVAILABLE / NOT_APPLICABLE status preserved.
  * `subsystem_command_contract` / the SYS-7 analyses supply SYS-16's
    command.txt column.
  * `inference.score_confidence()` is SYS-15's CONFIDENCE. No second scorer.

WHY THE TABLES ARE RENDERED HERE AND NOT IN `connectivity.py`
-------------------------------------------------------------
`connectivity.render_matrix_table()` calls `build_connectivity_matrix()`,
which is hardcoded to the module-level `MATRIX_COLUMNS`; it is a fixed-width
ASCII renderer of one fixed 11-column structure and is not parameterizable
without changing what every existing caller gets. The mandated-table
precedent in THIS workflow is `subsystem_discovery.render_discovery_table()`
(SYS-1's six columns) and `system_resource_inventory.render_*_table()`
(SYS-9/SYS-11): each mandated table is a markdown renderer owned by the module
that owns its data. SYS-16 and SYS-17 follow that precedent.

SCOPE BOUNDARY (SYS-39 / SYS-40)
--------------------------------
Discovery, analysis, planning and reporting ONLY. The registry is a PLANNING
artifact: it records what a System-Level composition WOULD own. Nothing here
generates System-Level UVM source, a System command.txt, a System Virtual
Sequencer, a shared agent or any command routing/adapter, nothing writes into
a subsystem's own environment, and nothing auto-applies a registry entry into
a real bind/UVM/command.txt artifact. Every `reuse_decision` and every
`system_owner` is a RECOMMENDATION for a human. Acting on one is SYS-40 and
needs its own explicit approval that this workflow does not obtain.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import connectivity as conn
from . import inference
from . import system_resource_inventory as sri

# ---------------------------------------------------------------------------
# SYS-15 vocabulary
# ---------------------------------------------------------------------------

#: SYS-15's own field list, verbatim and in its own order:
#: "Create or extend a registry with: resource_id, resource_type, protocol,
#:  physical_hierarchy, role, owner, consumer_subsystems, active_passive,
#:  shared, exclusive, clock, reset, address_domain, source_environment,
#:  source_config, conflict_status, reuse_decision, evidence, confidence."
#: Nineteen fields, not eighteen -- counted off the requirement's own sentence
#: and held to it by a test, so neither the code nor a summary of it can drift.
SYS15_FIELDS: tuple = (
    "resource_id",
    "resource_type",
    "protocol",
    "physical_hierarchy",
    "role",
    "owner",
    "consumer_subsystems",
    "active_passive",
    "shared",
    "exclusive",
    "clock",
    "reset",
    "address_domain",
    "source_environment",
    "source_config",
    "conflict_status",
    "reuse_decision",
    "evidence",
    "confidence",
)

#: SYS-16's mandatory table, its nine column headers verbatim and in order.
SYS16_COLUMNS: tuple = (
    "Subsystem", "Environment", "command.txt", "Readiness", "VIPs",
    "Scoreboard", "Shared Resources", "Conflicts", "Integration Status",
)

#: SYS-17's mandatory table, its eight column headers verbatim and in order.
SYS17_COLUMNS: tuple = (
    "Resource", "Subsystem A", "Subsystem B", "Physical Interface",
    "Relationship", "Active Driver Conflict", "Decision", "System Owner",
)

#: SYS-17's Decision vocabulary, verbatim and closed:
#: "REUSE_SHARED / KEEP_INDEPENDENT / PASSIVE_ONLY / REMOVE_DUPLICATE /
#:  RECONFIGURE / MERGE_ACCESS_PATH / BLOCKED / UNKNOWN."
#: SYS-15's `reuse_decision` field is THIS vocabulary -- one decision function
#: (`decide_reuse()`) feeds both, so a registry entry and its row in the
#: deduplication matrix can never disagree about what was decided.
#:
#: PASSIVE_ONLY and REMOVE_DUPLICATE are two DIFFERENT decisions about the same
#: relationship class (MONITOR_ONLY_DUPLICATE) and must not be collapsed:
#: PASSIVE_ONLY keeps both monitors because the second one may still observe
#: something the first does not, REMOVE_DUPLICATE deletes one because it
#: provably cannot. `classify_duplicate_observability()` is what decides which,
#: and it only ever reaches REMOVE_DUPLICATE on positive evidence.
REUSE_SHARED = "REUSE_SHARED"
KEEP_INDEPENDENT = "KEEP_INDEPENDENT"
PASSIVE_ONLY = "PASSIVE_ONLY"
REMOVE_DUPLICATE = "REMOVE_DUPLICATE"
RECONFIGURE = "RECONFIGURE"
MERGE_ACCESS_PATH = "MERGE_ACCESS_PATH"
BLOCKED = "BLOCKED"
DECISION_UNKNOWN = "UNKNOWN"

SYS17_DECISIONS: tuple = (
    REUSE_SHARED, KEEP_INDEPENDENT, PASSIVE_ONLY, REMOVE_DUPLICATE, RECONFIGURE,
    MERGE_ACCESS_PATH, BLOCKED, DECISION_UNKNOWN,
)

#: How a REGISTRY ENTRY's single `reuse_decision` is chosen when its member
#: pairs decided differently: the most restrictive decision wins, lowest number
#: first. An entry that is BLOCKED for one pair is blocked, full stop -- the
#: opposite fold (most permissive) would let one clean pair launder a stopped
#: resource into REUSE_SHARED, which is exactly the SYS-12 stop being stepped
#: past. UNKNOWN outranks the four actionable decisions for the same reason:
#: "we do not know" must not be overwritten by "reuse it".
#:
#: PASSIVE_ONLY outranks REMOVE_DUPLICATE deliberately. In a group of three or
#: more members, one pair proving redundancy says nothing about a third member
#: that is only PASSIVE_ONLY, and deleting an agent is the less reversible of
#: the two acts -- so the KEEP answer wins the fold and the redundant pair is
#: still visible as its own SYS-17 row.
DECISION_SEVERITY: Dict[str, int] = {
    BLOCKED: 0,
    RECONFIGURE: 1,
    DECISION_UNKNOWN: 2,
    PASSIVE_ONLY: 3,
    REMOVE_DUPLICATE: 4,
    MERGE_ACCESS_PATH: 5,
    REUSE_SHARED: 6,
    KEEP_INDEPENDENT: 7,
}

#: `classify_duplicate_observability()`'s two verdicts. Both are statements
#: about EVIDENCE, not about intent: REDUNDANT is reached only when every
#: observability-bearing signal was positively compared and matched, and
#: UNIQUE_POSSIBLE covers both "they really differ" and "we could not tell" --
#: because the safe action is identical in those two cases (keep both) and
#: pretending to distinguish them would be a claim the evidence does not make.
#: Which of the two copies a human retains is NOT decided here; see
#: `RETENTION_NOT_ARBITRATED`.
DUP_REDUNDANT = "REDUNDANT_ZERO_UNIQUE_OBSERVABILITY"
DUP_UNIQUE_POSSIBLE = "UNIQUE_OBSERVABILITY_POSSIBLE"
DUPLICATE_OBSERVABILITY_VERDICTS: tuple = (DUP_REDUNDANT, DUP_UNIQUE_POSSIBLE)

#: A REMOVE_DUPLICATE decision names the two interchangeable copies and stops.
#: The two monitors were proven equivalent on every compared signal, so which
#: one survives carries no engineering content and this module states that
#: rather than picking -- the same boundary SYS-12's driver-ownership
#: ARBITRATION keeps, applied to a far smaller decision.
RETENTION_NOT_ARBITRATED = (
    "WHICH copy is retained is not decided here: the two were proven equivalent on "
    "every compared signal, so the choice carries no engineering content and belongs "
    "to the human who reviews this recommendation.")

#: SYS-17's "Active Driver Conflict" column. Three-valued, and the third value
#: is load-bearing: "two active agents proven to drive one interface" and "two
#: active agents that MIGHT be one interface" are different findings, and
#: collapsing the second into NO is how a real conflict gets integrated.
ADC_YES = "YES"
ADC_NO = "NO"
ADC_UNPROVEN = "UNPROVEN_BOTH_ACTIVE"
ADC_VALUES: tuple = (ADC_YES, ADC_NO, ADC_UNPROVEN)

#: SYS-15's `conflict_status`.
CONFLICT_NONE = "NO_CONFLICT"
CONFLICT_DRIVER = "DRIVER_CONFLICT"
CONFLICT_CONFIGURATION = "CONFIGURATION_CONFLICT"
CONFLICT_UNPROVEN_DUPLICATE = "UNPROVEN_DUPLICATE_HELD"
CONFLICT_STATUSES: tuple = (CONFLICT_NONE, CONFLICT_DRIVER, CONFLICT_CONFIGURATION,
                            CONFLICT_UNPROVEN_DUPLICATE)

#: SYS-15's `owner`. A System owner is PROPOSED, never assigned: assigning one
#: is creating the shared agent, which is SYS-40.
OWNER_PROPOSED_SYSTEM_PREFIX = "PROPOSED_SYSTEM_SHARED"
OWNER_UNRESOLVED = "OWNER_UNRESOLVED"
NO_SYSTEM_OWNER = "NO_SYSTEM_OWNER"

SHARED_ACROSS_SUBSYSTEMS = "SHARED_ACROSS_SUBSYSTEMS"
NOT_SHARED = "NOT_SHARED"

#: A field whose member records disagree is reported as a disagreement rather
#: than silently resolved to one side: the registry is an authority, and an
#: authority that hides a contradiction is worse than one that reports it.
DISAGREEMENT = "DISAGREEMENT"

#: SYS-11 relationships that establish PHYSICAL identity, and therefore merge
#: two SYS-9 records into ONE registry entry. SHARED_LOGICAL_RESOURCE is
#: deliberately absent: its own reason string says "Physical equivalence is
#: NOT established", and collapsing two records on that basis would make the
#: registry assert an equivalence nothing proved. UNKNOWN is absent for the
#: same reason, and INDEPENDENT_RESOURCE because it is positive evidence of
#: two different things.
MERGING_RELATIONSHIPS: frozenset = frozenset({
    sri.REL_SAME_PHYSICAL,
    sri.REL_DRIVER_CONFLICT,
    sri.REL_CONFIGURATION_CONFLICT,
    sri.REL_MONITOR_ONLY_DUPLICATE,
})

# ---------------------------------------------------------------------------
# SYS-16 vocabulary
# ---------------------------------------------------------------------------

INTEGRATION_BLOCKED_DRIVER_CONFLICT = "BLOCKED_ACTIVE_DRIVER_CONFLICT"
INTEGRATION_BLOCKED_NOT_READY = "BLOCKED_SUBSYSTEM_NOT_READY"
INTEGRATION_HELD = "HELD_PENDING_PHYSICAL_EQUIVALENCE_EVIDENCE"
INTEGRATION_READY = "READY_FOR_INTEGRATION_PLANNING"
INTEGRATION_UNKNOWN = "UNKNOWN"
INTEGRATION_STATUSES: tuple = (
    INTEGRATION_BLOCKED_DRIVER_CONFLICT, INTEGRATION_BLOCKED_NOT_READY,
    INTEGRATION_HELD, INTEGRATION_READY, INTEGRATION_UNKNOWN,
)

#: What a SYS-16 cell says when the artifact that would answer it was not
#: supplied. Distinct from a zero: "no scoreboard" and "nobody looked for a
#: scoreboard" are opposite findings, and SYS-6 already draws that same
#: distinction with DERIVED / NOT_AVAILABLE / NOT_APPLICABLE.
NOT_AVAILABLE = "NOT_AVAILABLE"

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-15..SYS-17 are the resource "
    "registry and the two mandatory planning tables. Every `owner`, "
    "`reuse_decision` and `system_owner` in them is a RECOMMENDATION for a human "
    "to review. No System-Level environment, System command.txt, System Virtual "
    "Sequencer, shared agent or command routing/adapter is generated, no subsystem "
    "environment is modified, and no registry entry is auto-applied into a bind, "
    "UVM or command.txt artifact. That is SYS-40 and requires a separate explicit "
    "human approval.")

REGISTRY_FILENAME = "system_resource_registry.json"
REGISTRY_DIR = Path(".dv-harness") / "soc-composer"
REGISTRY_SCHEMA_VERSION = "1.0"


class SystemResourceRegistryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# SYS-15 / SYS-17 shared decision function
# ===========================================================================

def active_driver_conflict_verdict(relationship: Mapping[str, Any]) -> str:
    """SYS-17's "Active Driver Conflict" column for one pair, computed from
    SYS-11's verdict and SYS-9's active/passive evidence ONLY -- never from
    the Decision, so the two columns stay independent readings of the same
    pair and a reader can see when they disagree."""
    if relationship["relationship"] == sri.REL_DRIVER_CONFLICT:
        return ADC_YES
    if relationship.get("both_active"):
        return ADC_UNPROVEN
    return ADC_NO


def classify_duplicate_observability(relationship: Mapping[str, Any],
                                     a: Mapping[str, Any],
                                     b: Mapping[str, Any],
                                     ) -> Dict[str, Any]:
    """Decide, for ONE MONITOR_ONLY_DUPLICATE pair, whether the second monitor
    can still observe something the first cannot.

    This is the question that separates SYS-17's PASSIVE_ONLY from its
    REMOVE_DUPLICATE, and the two answers are genuinely different acts: keep
    both passive monitors, or delete one. Getting it wrong in the REMOVE
    direction destroys real observability -- a checker, a covergroup or a
    protocol view that only the deleted monitor had -- and a simulation that
    stops observing something does not announce it. So REDUNDANT is reached
    ONLY on positive, complete evidence, and every other state, including
    "nothing was captured", is UNIQUE_OBSERVABILITY_POSSIBLE.

    What a passive monitor's observability actually depends on, and therefore
    what all three checks below are:

      1. Both sides carry a REAL captured configuration
         (`configuration.config_field_count > 0`, i.e. a live vip_config dump
         reached `env_manifest.build_vip_config()` for that instance). A
         monitor's enabled checks, its coverage groups and its analysis depth
         are configuration; with no configuration captured, "these two observe
         the same things" is an assumption, not a finding. This is the check
         that keeps an absence of evidence from reading as evidence of
         redundancy.
      2. The two `configuration_hash` values are EQUAL. That hash is over the
         whole field map, so equality means identical field SETS and identical
         values -- strictly stronger than SYS-10's `configuration` signal,
         which compares only the keys both sides happen to share and therefore
         reports AGREE for a monitor that has an extra `coverage_enable` field
         the other one does not.
      3. SYS-10's `protocol` signal AGREES. Two monitors decoding different
         protocols off one interface see different transactions however alike
         their configuration looks, and an unclassified protocol on either side
         is not an agreement.

    `intended_function` is deliberately NOT one of the checks. SYS-10 lists it
    as name-derived and forbids deciding a duplicate on class names alone; it
    is reported in the basis for the human, never used to reach REDUNDANT.
    """
    signals = (relationship.get("comparison") or {}).get("signals") or {}
    ca = a.get("configuration") or {}
    cb = b.get("configuration") or {}
    count_a, count_b = int(ca.get("config_field_count") or 0), int(cb.get("config_field_count") or 0)
    hash_a, hash_b = str(ca.get("configuration_hash") or ""), str(cb.get("configuration_hash") or "")
    protocol_verdict = str((signals.get("protocol") or {}).get("verdict") or sri.SIGNAL_UNKNOWN)

    basis = {
        "config_field_count_a": count_a,
        "config_field_count_b": count_b,
        "configuration_hash_a": hash_a,
        "configuration_hash_b": hash_b,
        "configuration_signal": str((signals.get("configuration") or {}).get("verdict")
                                    or sri.SIGNAL_UNKNOWN),
        "protocol_signal": protocol_verdict,
        "intended_function_signal": str((signals.get("intended_function") or {}).get("verdict")
                                        or sri.SIGNAL_UNKNOWN),
        "physical_identity_evidence": list(relationship.get("physical_identity_evidence") or []),
    }

    if not (count_a and count_b):
        return {
            "verdict": DUP_UNIQUE_POSSIBLE,
            "reason": (
                "no live vip_config capture on "
                + ("both sides" if not (count_a or count_b)
                   else ("side A" if not count_a else "side B"))
                + f" (config_field_count {count_a}/{count_b}), so what each monitor "
                "actually checks, covers and decodes was never compared. An absent "
                "capture is not evidence of redundancy -- generate env.manifest.json "
                "from a real vip_config dump on both subsystems to settle it"),
            "basis": basis,
        }
    if hash_a != hash_b:
        differing = [d["field"] for d in
                     ((signals.get("configuration") or {}).get("differing") or [])]
        return {
            "verdict": DUP_UNIQUE_POSSIBLE,
            "reason": (
                "both monitors are configured, but not identically: their whole-field "
                f"configuration hashes differ ({hash_a} vs {hash_b})"
                + (f"; SYS-10 saw {differing} differ on shared fields" if differing else
                   "; every field they SHARE agrees, so the difference is a field one "
                   "side carries and the other does not -- exactly the shape of an extra "
                   "check or covergroup that only one monitor has")
                + ". A monitor with configuration the other lacks may observe something "
                "the other cannot, so both are kept"),
            "basis": basis,
        }
    if protocol_verdict != sri.AGREE:
        return {
            "verdict": DUP_UNIQUE_POSSIBLE,
            "reason": (
                f"SYS-10's protocol signal is {protocol_verdict}, not AGREE, so it is not "
                "established that the two monitors decode the same protocol off this "
                "interface; identical configuration of two different decoders is not "
                "identical observability"),
            "basis": basis,
        }
    return {
        "verdict": DUP_REDUNDANT,
        "reason": (
            f"both monitors are PASSIVE on one physical interface "
            f"({relationship.get('physical_identity_evidence')}), both carry a real "
            f"captured configuration ({count_a} and {count_b} fields), those "
            f"configurations are identical field-for-field (configuration_hash "
            f"{hash_a}), and SYS-10's protocol signal AGREES -- so the second monitor "
            "decodes the same protocol, with the same checks and the same coverage, on "
            "the same signals. It contributes no observation the first does not, and "
            "no control at all, because a PASSIVE monitor drives nothing. "
            + RETENTION_NOT_ARBITRATED),
        "basis": basis,
    }


def decide_reuse(relationship: Mapping[str, Any],
                 promotion: Optional[Mapping[str, Any]],
                 conflict_rule: Mapping[str, Any],
                 resources_by_id: Mapping[str, Mapping[str, Any]],
                 ) -> Dict[str, Any]:
    """Map ONE SYS-11 relationship (plus its SYS-12 status and SYS-13
    promotion verdict) onto SYS-17's closed eight-value Decision vocabulary.

    SYS-13's vocabulary and SYS-17's are NOT the same list -- SYS-13 answers
    "may this be promoted to System-Level ownership", SYS-17 answers "what do
    we DO with this pair" -- so this is a real translation and not an alias.
    It is written once and used by both SYS-15's `reuse_decision` field and
    SYS-17's Decision column.

    Precedence, most-specific and most-restrictive first:

      1. DRIVER_CONFLICT -> BLOCKED. SYS-12 stops automatic integration of
         that resource until ownership is resolved; no other decision may be
         reached past that stop.
      2. A subsystem-specific protocol VIP on either side (SYS-13's
         NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC, which is SYS-14's rule) ->
         KEEP_INDEPENDENT. A PCIe VIP is not shared infrastructure however
         alike two of them look.
      3. INDEPENDENT_RESOURCE -> KEEP_INDEPENDENT. Positive evidence of two
         different things.
      4. CONFIGURATION_CONFLICT -> RECONFIGURE. Physical identity IS
         established and one shared agent cannot hold two configurations, so
         the action is to reconcile them. RECONFIGURE names the action; it
         deliberately does not name a winner, because
         `escalate_configuration_conflicts()` routed exactly that question
         through the 9-level source authority order and got
         UNDECIDABLE_SAME_AUTHORITY -- two live vip_config dumps are two
         tier-1 claims, and a human breaks that tie.
      5. MONITOR_ONLY_DUPLICATE -> PASSIVE_ONLY, or REMOVE_DUPLICATE when
         `classify_duplicate_observability()` PROVES the second monitor
         observes nothing the first does not. Two monitors on one interface
         are always safe to keep (neither drives), so PASSIVE_ONLY is the
         default and REMOVE_DUPLICATE needs positive evidence: a real captured
         configuration on both sides, identical field-for-field, and an agreed
         protocol. "Keep it as a monitor" and "delete it" are different acts
         and this branch is where they part.
      6. SAME_PHYSICAL_RESOURCE, SYS-13 says promotable -> REUSE_SHARED.
      6b. SAME_PHYSICAL_RESOURCE, not promotable, exactly one side ACTIVE ->
         PASSIVE_ONLY, owned by the driving subsystem. The interface is one
         interface; instantiating a second driver for it is the thing SYS-12
         forbids, and the second side observing it is the safe reading.
      6c. SAME_PHYSICAL_RESOURCE, not promotable, neither side proven ACTIVE
         -> UNKNOWN.
      7. SHARED_LOGICAL_RESOURCE -> MERGE_ACCESS_PATH, unless SYS-12 HELD the
         pair (both active, physical equivalence unproven) -> BLOCKED.
      8. UNKNOWN -> BLOCKED when held, else UNKNOWN.

    A final override: if EITHER resource is in SYS-12's stopped set -- which
    can happen because of a driver conflict on a DIFFERENT pair, including a
    collision inside one subsystem's own matrix -- and this pair asserts
    identity at all, the decision becomes BLOCKED. It is deliberately NOT
    applied to an INDEPENDENT_RESOURCE pair: those two are not the same
    resource, so another resource's stop says nothing about them.
    """
    stopped: Set[str] = set(conflict_rule.get("stopped_resource_ids") or [])
    held: Set[str] = set(conflict_rule.get("held_resource_ids") or [])
    rid_a, rid_b = relationship["resource_a"], relationship["resource_b"]
    rel = relationship["relationship"]
    a = resources_by_id.get(rid_a, {})
    b = resources_by_id.get(rid_b, {})
    promo_decision = str((promotion or {}).get("decision") or "")
    is_held = rid_a in held or rid_b in held
    is_stopped = rid_a in stopped or rid_b in stopped

    active_sides = [r for r in (a, b)
                    if str(r.get("active_passive", "")).lower() == conn.ACTIVE_INTERFACE]

    def _system_shared_owner() -> str:
        rtype = a.get("resource_type") or b.get("resource_type") or sri.RT_UNCLASSIFIED
        return f"{OWNER_PROPOSED_SYSTEM_PREFIX}::{rtype}"

    # Only the MONITOR_ONLY_DUPLICATE branch asks this question; every other
    # relationship class reports None rather than a verdict about a duplicate
    # that was never classified as one.
    duplicate_observability: Optional[Dict[str, Any]] = None

    if rel == sri.REL_DRIVER_CONFLICT:
        decision, owner, reason = BLOCKED, OWNER_UNRESOLVED, (
            "SYS-12: two ACTIVE agents would independently drive one physical "
            "interface; automatic integration of this resource is stopped until "
            "ownership is resolved. " + str(relationship.get("reason", "")))
    elif promo_decision == sri.NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC:
        decision, owner, reason = KEEP_INDEPENDENT, NO_SYSTEM_OWNER, (
            "SYS-14: a subsystem-specific protocol VIP stays inside its subsystem; "
            "only shared SoC infrastructure is promoted. "
            + str((promotion or {}).get("reason", "")))
    elif rel == sri.REL_INDEPENDENT:
        decision, owner, reason = KEEP_INDEPENDENT, NO_SYSTEM_OWNER, (
            "SYS-11 classified these as INDEPENDENT_RESOURCE -- there is nothing "
            "shared to reuse. " + str(relationship.get("reason", "")))
    elif rel == sri.REL_CONFIGURATION_CONFLICT:
        decision, owner, reason = RECONFIGURE, OWNER_UNRESOLVED, (
            "physical identity is established but the two environments configure the "
            "resource differently; one shared agent cannot hold two configurations. "
            "The disagreement was escalated through the 9-level source authority "
            "order, which returns UNDECIDABLE_SAME_AUTHORITY for two live vip_config "
            "dumps -- a human chooses the surviving configuration. "
            + str(relationship.get("reason", "")))
    elif rel == sri.REL_MONITOR_ONLY_DUPLICATE:
        duplicate_observability = classify_duplicate_observability(relationship, a, b)
        if duplicate_observability["verdict"] == DUP_REDUNDANT:
            decision, owner, reason = REMOVE_DUPLICATE, NO_SYSTEM_OWNER, (
                "both sides are PASSIVE monitors of one physical interface and the "
                "second one is provably redundant: " + duplicate_observability["reason"]
                + " RECOMMENDATION ONLY -- removing an agent from a subsystem "
                "environment is SYS-40 and no environment is modified here")
        else:
            decision, owner, reason = PASSIVE_ONLY, NO_SYSTEM_OWNER, (
                "both sides are PASSIVE monitors of one physical interface -- a duplicate "
                "but not a driver hazard; both may observe and neither drives. Kept rather "
                "than removed because unique observability could not be ruled out: "
                + duplicate_observability["reason"])
    elif rel == sri.REL_SAME_PHYSICAL:
        if promo_decision == sri.PROMOTE_TO_SYSTEM_SHARED:
            decision, owner, reason = REUSE_SHARED, _system_shared_owner(), (
                "physical equivalence established by "
                f"{relationship['physical_identity_evidence']} and SYS-13 evaluated the "
                "type as promotable shared SoC infrastructure. RECOMMENDATION ONLY -- "
                "creating the System shared agent is SYS-40")
        elif len(active_sides) == 1:
            decision, owner = PASSIVE_ONLY, str(active_sides[0].get("owner_subsystem") or
                                                OWNER_UNRESOLVED)
            reason = (
                "one physical interface with exactly one ACTIVE driver, and SYS-13 did "
                f"not evaluate the type as promotable ({promo_decision or 'not evaluated'}); "
                f"the driving subsystem keeps it and the other side observes it passively")
        else:
            decision, owner, reason = DECISION_UNKNOWN, OWNER_UNRESOLVED, (
                "one physical interface, but neither side is recorded ACTIVE, so which "
                "environment drives it is unresolved; a live vip_config dump or an "
                "active_passive value on both sides would settle it")
    elif rel == sri.REL_SHARED_LOGICAL:
        if is_held:
            decision, owner, reason = BLOCKED, OWNER_UNRESOLVED, (
                "SYS-12 HELD this pair: both sides are ACTIVE and physical equivalence "
                "is NOT established, so it cannot be said whether merging their access "
                "paths would merge two drivers onto one interface")
        else:
            decision, owner, reason = MERGE_ACCESS_PATH, OWNER_UNRESOLVED, (
                "the address domains genuinely overlap and more than one logical signal "
                "agrees -- one logical function reached through two access paths. "
                "Physical equivalence is NOT established, so no System owner is proposed")
    else:  # sri.REL_UNKNOWN
        if is_held:
            decision, owner, reason = BLOCKED, OWNER_UNRESOLVED, (
                "SYS-12 HELD this pair: both sides are ACTIVE and it cannot yet be said "
                "whether they are one interface. " + str(relationship.get("reason", "")))
        else:
            decision, owner, reason = DECISION_UNKNOWN, OWNER_UNRESOLVED, (
                str(relationship.get("reason", "")))

    overridden_by_stop = False
    if (is_stopped and decision != BLOCKED
            and rel in (MERGING_RELATIONSHIPS | {sri.REL_SHARED_LOGICAL})):
        overridden_by_stop = True
        decision, owner = BLOCKED, OWNER_UNRESOLVED
        reason = ("SYS-12 stopped automatic integration of this resource (a driver "
                  "conflict on it stands, possibly from another pair or from a "
                  "collision inside one subsystem's own connectivity matrix); a "
                  "decision on a stopped resource may not step past that stop. "
                  "Underlying verdict was: " + reason)

    if decision not in SYS17_DECISIONS:  # structural bug, not a data condition
        raise SystemResourceRegistryError("DECISION_OUTSIDE_SYS17_VOCABULARY", {
            "decision": decision, "allowed": list(SYS17_DECISIONS)})

    return {
        "decision": decision,
        "system_owner": owner,
        "reason": reason,
        "active_driver_conflict": active_driver_conflict_verdict(relationship),
        "sys11_relationship": rel,
        "sys13_promotion_decision": promo_decision or NOT_AVAILABLE,
        "sys12_stopped": is_stopped,
        "sys12_held": is_held,
        "overridden_by_sys12_stop": overridden_by_stop,
        # The PASSIVE_ONLY / REMOVE_DUPLICATE evidence, so a reader can see WHY
        # a duplicate was kept or called redundant without re-deriving it.
        # None for every relationship class that is not a monitor duplicate.
        "duplicate_observability": duplicate_observability,
        "interchangeable_copies": (sorted([rid_a, rid_b])
                                   if decision == REMOVE_DUPLICATE else []),
        "retention_choice": (RETENTION_NOT_ARBITRATED
                             if decision == REMOVE_DUPLICATE else ""),
        "recommendation_only": True,
        "implementation_phase": "SYS-40 (requires separate explicit human approval)",
    }


# ===========================================================================
# SYS-15: SYSTEM_RESOURCE_REGISTRY
# ===========================================================================

def _union_find(ids: Sequence[str],
                pairs: Sequence[Tuple[str, str]]) -> List[List[str]]:
    """Group ids into connected components over `pairs`. Identity is
    transitive by construction -- if A is the same physical resource as B and
    B as C, the registry must hold ONE entry, not two overlapping ones."""
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    groups: Dict[str, List[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return [sorted(v) for v in groups.values()]


def _agreed(values: Sequence[str], *, unknown: str = "") -> str:
    """One value if every member agrees, else DISAGREEMENT with both sides
    named. A registry cell that quietly picks a side is a lie the composer
    would then build on."""
    distinct = sorted({str(v) for v in values if str(v) and str(v) != unknown})
    if not distinct:
        return unknown or sri.UNRESOLVED
    if len(distinct) == 1:
        return distinct[0]
    # Comma-separated, not pipe-separated: every one of these values is
    # rendered into a markdown table cell, and a literal pipe there silently
    # splits the row into two columns.
    return f"{DISAGREEMENT}({','.join(distinct)})"


def _entry_resource_id(members: Sequence[Mapping[str, Any]]) -> str:
    """A stable SYSTEM-level id, deliberately different in shape from the
    subsystem-local `<SUBSYS>::<hier>::<iface>` ids of SYS-9 so the two
    granularities can never be confused in a report or a JSON file.

    Keyed on the strongest physical evidence available -- a declared
    physical-interface id, then a shared bind target -- falling back to a
    short digest of the member ids when identity came from driver ownership
    alone and there is no single shared name to key on.
    """
    rtype = _agreed([m["resource_type"] for m in members]) or sri.RT_UNCLASSIFIED
    declared = sorted({str(m.get("physical_interface_id") or "") for m in members} - {""})
    if len(declared) == 1:
        return f"SYSRES::{rtype}::{declared[0]}"
    binds = sorted({str(m.get("bind_target") or "") for m in members} - {""})
    if len(binds) == 1:
        return f"SYSRES::{rtype}::{binds[0]}"
    digest = hashlib.sha256("|".join(sorted(m["resource_id"] for m in members))
                            .encode("utf-8")).hexdigest()[:12]
    return f"SYSRES::{rtype}::{digest}"


def build_system_resource_registry(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-15: "Create or extend a registry ... This is the authority for
    System-Level resource composition."

    ONE entry per SYSTEM-LEVEL resource. Two subsystems' SYS-9 records collapse
    into one entry only when SYS-11 established PHYSICAL identity between them
    (`MERGING_RELATIONSHIPS`); a SHARED_LOGICAL_RESOURCE or an UNKNOWN pair is
    recorded as a `related_entries` cross-reference instead, because merging on
    unproven equivalence would make the authority assert something nothing
    proved.

    `owner` and `consumer_subsystems` are separate fields and that separation is
    the point of the whole registry: it is the statement the SUBSYSTEM registry
    (`.dv-harness/soc-composer/subsystem_environment_registry.json`, one row per
    ENVIRONMENT) and the connectivity matrix (one row per interface of ONE
    environment, with no subsystem column at all) are both structurally unable
    to make.

    Reads only; writes nothing. `write_system_resource_registry()` is a separate,
    explicit call.
    """
    inventory = analysis["inventory"]
    resources = list(inventory["resources"])
    by_id = {r["resource_id"]: r for r in resources}
    relationships = list(analysis.get("relationships") or [])
    promotions_by_pair = {
        (p["resource_a"], p["resource_b"]): p
        for p in analysis.get("promotion_evaluation") or []}
    conflict_rule = analysis.get("active_driver_conflict_rule") or {}
    held = set(conflict_rule.get("held_resource_ids") or [])
    stopped = set(conflict_rule.get("stopped_resource_ids") or [])

    pair_decisions: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rel in relationships:
        key = (rel["resource_a"], rel["resource_b"])
        pair_decisions[key] = decide_reuse(
            rel, promotions_by_pair.get(key), conflict_rule, by_id)

    merge_pairs = [(r["resource_a"], r["resource_b"]) for r in relationships
                   if r["relationship"] in MERGING_RELATIONSHIPS]
    # WITHIN one subsystem, two ACTIVE rows claiming one bind target are two
    # agents on ONE physical interface -- established by the bind target
    # itself, which is stronger physical evidence than anything a
    # cross-subsystem comparison infers. They merge for the same reason a
    # cross-subsystem SAME_PHYSICAL pair does: the registry holds one entry per
    # physical resource, and leaving them apart would present one interface as
    # two consumable resources to whoever reads this as the composition
    # authority. `find_active_bind_target_collisions()` already found them
    # per-subsystem in the SYS-9 layer; they are read, never re-derived.
    for per in inventory.get("per_subsystem") or []:
        for collision in per.get("within_subsystem_bind_collisions") or []:
            ids = [f"{per['subsystem_id']}::{row}" for row in collision["rows"]]
            merge_pairs += [(ids[0], other) for other in ids[1:]]
    groups = _union_find([r["resource_id"] for r in resources], merge_pairs)

    entry_of_resource: Dict[str, str] = {}
    entries: List[Dict[str, Any]] = []
    for group in sorted(groups, key=lambda g: g[0]):
        members = [by_id[i] for i in group]
        entry_id = _entry_resource_id(members)
        for rid in group:
            entry_of_resource[rid] = entry_id

        member_set = set(group)
        member_rels = [r for r in relationships
                       if r["resource_a"] in member_set and r["resource_b"] in member_set]
        related = [r for r in relationships
                   if (r["resource_a"] in member_set) ^ (r["resource_b"] in member_set)]

        decisions = [pair_decisions[(r["resource_a"], r["resource_b"])]
                     for r in member_rels]
        # SHARED_LOGICAL / UNKNOWN pairs did not merge, but their decision is
        # still a decision ABOUT this resource and must not be dropped -- a
        # BLOCKED cross-reference has to reach the entry it blocks.
        decisions += [pair_decisions[(r["resource_a"], r["resource_b"])] for r in related]

        member_stopped = sorted(member_set & stopped)
        if decisions:
            winner = min(decisions, key=lambda d: DECISION_SEVERITY[d["decision"]])
            reuse_decision, system_owner = winner["decision"], winner["system_owner"]
            decision_reason = winner["reason"]
        else:
            reuse_decision, system_owner = KEEP_INDEPENDENT, NO_SYSTEM_OWNER
            decision_reason = (
                "no cross-subsystem duplicate of this resource was established, so there "
                "is nothing to share it with; it stays where it is")
        # A member SYS-12 stopped blocks the ENTRY even when no cross-subsystem
        # pair decision reached it -- the within-subsystem bind-target collision
        # case has no pair at all, and an entry reported KEEP_INDEPENDENT while
        # two active agents claim it would be the SYS-12 stop stepped past at
        # the authority layer instead of at the pair layer.
        if member_stopped and reuse_decision != BLOCKED:
            reuse_decision, system_owner = BLOCKED, OWNER_UNRESOLVED
            decision_reason = (
                f"SYS-12 stopped automatic integration of {member_stopped} until ownership "
                "is resolved. Underlying verdict was: " + decision_reason)

        member_rel_classes = {r["relationship"] for r in member_rels}
        if sri.REL_DRIVER_CONFLICT in member_rel_classes or member_stopped:
            conflict_status = CONFLICT_DRIVER
        elif sri.REL_CONFIGURATION_CONFLICT in member_rel_classes:
            conflict_status = CONFLICT_CONFIGURATION
        elif member_set & held:
            conflict_status = CONFLICT_UNPROVEN_DUPLICATE
        else:
            conflict_status = CONFLICT_NONE

        consumers = sorted({m["owner_subsystem"] for m in members})
        shared = SHARED_ACROSS_SUBSYSTEMS if len(consumers) > 1 else NOT_SHARED

        # `owner` follows the decision, never the consumer count alone. Two
        # ACTIVE agents inside ONE subsystem claiming one interface has exactly
        # one consumer subsystem, and naming that subsystem the owner would
        # report ownership as settled at the precise moment SYS-12 stopped
        # integration because it is not.
        if reuse_decision == REUSE_SHARED:
            owner = system_owner
        elif reuse_decision == PASSIVE_ONLY and system_owner not in (NO_SYSTEM_OWNER,
                                                                    OWNER_UNRESOLVED):
            owner = system_owner
        elif reuse_decision in (BLOCKED, RECONFIGURE, DECISION_UNKNOWN):
            owner = OWNER_UNRESOLVED
        elif len(consumers) == 1:
            owner = consumers[0]
        else:
            owner = OWNER_UNRESOLVED

        # SYS-15's CONFIDENCE, from the one scorer in this codebase. Independent
        # sources are the distinct ENVIRONMENTS that contributed a record;
        # counter-evidence is every real contradiction the entry carries, so an
        # entry with a driver conflict or a clock disagreement can never be
        # reported HIGH (score_confidence's own safety floor).
        clock = _agreed([m["clock"] for m in members], unknown=sri.UNRESOLVED)
        reset = _agreed([m["reset"] for m in members], unknown=sri.UNRESOLVED)
        exclusive = _agreed([m["exclusive"] for m in members], unknown=sri.EXCLUSIVE_UNKNOWN)
        shareability = _agreed([m["shareable"] for m in members], unknown=sri.SHAREABLE_UNKNOWN)
        # `exclusive` and `shareable` are deliberately NOT counted as
        # counter-evidence even when the members disagree on them. Both are
        # DERIVED from active_passive by `derive_shareable_exclusive()`, so an
        # ACTIVE driver and a PASSIVE monitor on one interface -- the normal,
        # healthy SAME_PHYSICAL_RESOURCE case -- necessarily disagree on both.
        # Scoring that as a contradiction would cap the confidence of exactly
        # the pairs that are least problematic. The disagreement is still
        # REPORTED in the entry; it just is not evidence against it.
        counter = sum([
            conflict_status != CONFLICT_NONE,
            clock.startswith(DISAGREEMENT),
            reset.startswith(DISAGREEMENT),
        ])
        evidence = sorted({e for m in members for e in (m.get("evidence") or [])})
        confidence = inference.score_confidence(
            independent_sources_count=len({m["owner_subsystem"] for m in members}),
            evidence_refs_verified=bool(evidence),
            counter_evidence_count=int(counter),
            multi_agent_consensus_count=0)

        entry = {
            "resource_id": entry_id,
            "resource_type": _agreed([m["resource_type"] for m in members]),
            "protocol": _agreed([m["protocol"] for m in members],
                                unknown=conn.PROTOCOL_NOT_CLASSIFIED),
            # A list, not a string: two independently-generated environments
            # name their own trees independently, so one physical resource
            # genuinely has more than one hierarchy path and picking one would
            # hide the other from whoever has to bind it.
            "physical_hierarchy": sorted({m["hierarchy"] for m in members if m["hierarchy"]}),
            "role": _agreed([m["role"] for m in members], unknown=sri.UNRESOLVED),
            "owner": owner,
            "consumer_subsystems": consumers,
            "active_passive": _agreed([m["active_passive"] for m in members]),
            "shared": shared,
            "exclusive": exclusive,
            "clock": clock,
            "reset": reset,
            "address_domain": [
                {"owner_subsystem": m["owner_subsystem"],
                 "status": m["address_domain"]["status"],
                 "regions": m["address_domain"].get("regions") or []}
                for m in members],
            "source_environment": [
                {"subsystem_id": m["owner_subsystem"],
                 "release_sha": m.get("owner_release_sha") or "",
                 "member_resource_id": m["resource_id"]}
                for m in members],
            "source_config": [
                {"subsystem_id": m["owner_subsystem"],
                 "configuration_hash": m["configuration"]["configuration_hash"],
                 "config_field_count": m["configuration"]["config_field_count"],
                 "source": m["configuration"]["source"]}
                for m in members],
            "conflict_status": conflict_status,
            "reuse_decision": reuse_decision,
            "evidence": evidence,
            "confidence": confidence["level"],
            # Provenance carried BESIDE the mandated fields, never instead of
            # them: a verdict whose basis is not recorded next to it cannot be
            # checked.
            "member_resource_ids": sorted(group),
            "shareability": shareability,
            "physical_interface_id": _agreed(
                [str(m.get("physical_interface_id") or "") for m in members]),
            "reuse_decision_reason": decision_reason,
            "related_entries": sorted({r["resource_a"] if r["resource_b"] in member_set
                                       else r["resource_b"] for r in related}),
            "confidence_detail": confidence,
            "recommendation_only": True,
        }
        missing = [f for f in SYS15_FIELDS if f not in entry]
        if missing:  # structural bug, not a data condition
            raise SystemResourceRegistryError("SYS15_FIELD_MISSING", {"fields": missing})
        entries.append(entry)

    # `related_entries` is collected as member resource ids above; translate to
    # entry ids now that every resource knows its entry.
    for entry in entries:
        entry["related_entries"] = sorted(
            {entry_of_resource[rid] for rid in entry["related_entries"]
             if rid in entry_of_resource} - {entry["resource_id"]})

    entries.sort(key=lambda e: e["resource_id"])
    by_decision = {d: 0 for d in SYS17_DECISIONS}
    for entry in entries:
        by_decision[entry["reuse_decision"]] += 1
    by_conflict = {c: 0 for c in CONFLICT_STATUSES}
    for entry in entries:
        by_conflict[entry["conflict_status"]] += 1

    # A repeated entry id would silently overwrite an `entry_of_resource`
    # mapping and present two distinct SoC resources as one to whoever reads
    # this registry as the composition authority. It should be unreachable --
    # a shared bind target agrees the `physical_interface` signal, which makes
    # SYS-11 merge the pair -- so it is a structural bug, not a data condition.
    ids = [e["resource_id"] for e in entries]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise SystemResourceRegistryError("DUPLICATE_REGISTRY_ENTRY_ID", {
            "resource_ids": repeated,
            "hint": "two unmerged groups keyed to one SYSTEM-level id; the registry is the "
                    "authority for composition and cannot present two resources as one"})

    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "subsystems": list(inventory["subsystems"]),
        "entries": entries,
        "entry_of_resource": entry_of_resource,
        "pair_decisions": {f"{a}|{b}": d for (a, b), d in sorted(pair_decisions.items())},
        "summary": {
            "entry_count": len(entries),
            "member_resource_count": len(resources),
            "collapsed_resource_count": len(resources) - len(entries),
            "shared_entry_count": sum(1 for e in entries
                                      if e["shared"] == SHARED_ACROSS_SUBSYSTEMS),
            "entries_by_reuse_decision": by_decision,
            "entries_by_conflict_status": by_conflict,
        },
        "authority_scope": "PLANNING_ONLY",
        "artifacts_modified": False,
        "phase_boundary": PHASE_BOUNDARY,
    }


def registry_path(root) -> Path:
    return Path(root) / REGISTRY_DIR / REGISTRY_FILENAME


def write_system_resource_registry(root, registry: Mapping[str, Any]) -> Path:
    """Persist the SYS-15 registry as a PLANNING artifact, beside -- never
    into -- the subsystem-granularity
    `subsystem_environment_registry.json`. Two different granularities in one
    file would break `tools/real_env/system_level_validator.py`, which
    validates that file against its own six-field per-subsystem contract.

    This writes a JSON planning document and nothing else. It never touches a
    subsystem environment, a bind file, a UVM source file or a command.txt,
    and nothing in this module reads the file back to apply it -- applying a
    registry entry is SYS-40.
    """
    if registry.get("authority_scope") != "PLANNING_ONLY":
        raise SystemResourceRegistryError("REGISTRY_NOT_PLANNING_SCOPED", {
            "authority_scope": registry.get("authority_scope"),
            "hint": "only a registry built by build_system_resource_registry() may be "
                    "written; it is a planning artifact and says so on its face"})
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    return path


def read_system_resource_registry(root) -> Dict[str, Any]:
    path = registry_path(root)
    if not path.is_file():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "entries": [],
                "status": "ABSENT", "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "PRESENT"
    data["path"] = str(path)
    return data


# ===========================================================================
# SYS-16: SUBSYSTEM INTEGRATION MATRIX
# ===========================================================================

def _scoreboard_cell(per_subsystem_analysis: Optional[Mapping[str, Any]],
                     inventory_entry: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-16's Scoreboard column, from SYS-6's real `scoreboards` field when
    the SYS-5..6 analysis was run -- preserving its own three-valued status,
    because "this environment has no scoreboard" and "nobody analyzed this
    environment" are opposite findings and SYS-6 already draws that line."""
    field = ((per_subsystem_analysis or {}).get("fields") or {}).get("scoreboards")
    if field:
        hits = field.get("components") or []
        names = [str(h.get("full_name") or h.get("type_name") or h)
                 if isinstance(h, Mapping) else str(h) for h in hits]
        return {"status": field.get("status"), "count": len(names),
                "names": names[:8], "source": field.get("source", "")}
    count = sum(1 for r in inventory_entry["resources"]
                if r["resource_type"] == sri.RT_SCOREBOARD)
    return {"status": NOT_AVAILABLE, "count": count, "names": [],
            "source": "no SYS-5/SYS-6 architecture analysis supplied; the count is the "
                      "SYS-9 inventory's own SCOREBOARD resources"}


def build_subsystem_integration_matrix(analysis: Mapping[str, Any],
                                       registry: Mapping[str, Any],
                                       *,
                                       selection: Optional[Mapping[str, Any]] = None,
                                       synthesis: Optional[Mapping[str, Any]] = None,
                                       ) -> Dict[str, Any]:
    """SYS-16's mandatory table: one row per SELECTED subsystem, nine columns.

    `selection` (SYS-1..4) and `synthesis` (SYS-5..8) are OPTIONAL. When one is
    absent the columns it would fill report NOT_AVAILABLE rather than a
    plausible value -- an unanalyzed subsystem and a subsystem with nothing to
    report are different findings, and SYS-16's table is read as a readiness
    statement.

    "Every selected subsystem must appear" is enforced by
    `assert_every_selected_subsystem_present()`, which this function calls: a
    subsystem the user selected and that then silently vanishes from the
    integration table is precisely the omission SYS-16's sentence exists to
    prevent.
    """
    inventory = analysis["inventory"]
    conflict_rule = analysis.get("active_driver_conflict_rule") or {}
    stopped = set(conflict_rule.get("stopped_resource_ids") or [])
    held = set(conflict_rule.get("held_resource_ids") or [])

    selected: List[str] = list((selection or {}).get("selected_subsystems")
                               or inventory["subsystems"])
    discovery_rows = {str(r["subsystem"]): r
                      for r in ((selection or {}).get("selected_rows") or [])}
    analyses = {str(r["subsystem_id"]): r
                for r in ((synthesis or {}).get("per_subsystem") or [])}
    inventories = {inv["subsystem_id"]: inv for inv in inventory["per_subsystem"]}

    shared_by_subsystem: Dict[str, Set[str]] = {s: set() for s in selected}
    for entry in registry["entries"]:
        if entry["shared"] != SHARED_ACROSS_SUBSYSTEMS:
            continue
        for member in entry["source_environment"]:
            shared_by_subsystem.setdefault(member["subsystem_id"], set()).add(
                entry["resource_id"])

    conflicts_by_subsystem: Dict[str, List[Dict[str, Any]]] = {s: [] for s in selected}
    for decision in conflict_rule.get("decisions") or []:
        for subsystem in decision.get("subsystems") or []:
            conflicts_by_subsystem.setdefault(subsystem, []).append({
                "scope": decision["scope"],
                "integration_status": decision["integration_status"],
                "resources": decision["resources"],
            })
    for escalation in analysis.get("configuration_conflict_escalations") or []:
        for rid in (escalation["resource_a"], escalation["resource_b"]):
            owner = rid.split("::", 1)[0]
            conflicts_by_subsystem.setdefault(owner, []).append({
                "scope": "CROSS_SUBSYSTEM",
                "integration_status": "CONFIGURATION_CONFLICT_ESCALATED",
                "resources": [escalation["resource_a"], escalation["resource_b"]],
                "field": escalation["field"],
            })

    rows: List[Dict[str, Any]] = []
    for subsystem in selected:
        inv = inventories.get(subsystem)
        row_analysis = analyses.get(subsystem)
        discovery_row = discovery_rows.get(subsystem)

        if inv is None:
            # Selected, but no resource inventory reached this layer. Reported
            # as a row rather than dropped -- SYS-16 says every selected
            # subsystem must appear, and this is exactly the case a reader
            # most needs to see.
            rows.append({
                "Subsystem": subsystem,
                "Environment": str((discovery_row or {}).get("environment_path")
                                   or NOT_AVAILABLE),
                "command.txt": NOT_AVAILABLE,
                "Readiness": str((discovery_row or {}).get("readiness") or NOT_AVAILABLE),
                "VIPs": NOT_AVAILABLE,
                "Scoreboard": NOT_AVAILABLE,
                "Shared Resources": NOT_AVAILABLE,
                "Conflicts": len(conflicts_by_subsystem.get(subsystem) or []),
                "Integration Status": INTEGRATION_UNKNOWN,
                "detail": {"reason": "selected, but no SYS-9 resource inventory was "
                                     "produced for this subsystem"},
            })
            continue

        owned = [r["resource_id"] for r in inv["resources"]]
        owned_set = set(owned)
        command_files = [a["command_file"] for a in (row_analysis or {}).get(
            "command_analyses") or []]
        command_cell = (str(len(command_files)) if row_analysis else NOT_AVAILABLE)
        readiness = str((discovery_row or {}).get("readiness") or NOT_AVAILABLE)
        existence = str((discovery_row or {}).get("existence_class") or NOT_AVAILABLE)
        scoreboard = _scoreboard_cell(row_analysis, inv)
        shared_ids = sorted(shared_by_subsystem.get(subsystem) or ())
        conflicts = conflicts_by_subsystem.get(subsystem) or []

        subsystem_stopped = sorted(owned_set & stopped)
        subsystem_held = sorted(owned_set & held)

        if subsystem_stopped:
            status = INTEGRATION_BLOCKED_DRIVER_CONFLICT
            status_reason = (f"SYS-12 stopped {len(subsystem_stopped)} of this "
                             "subsystem's resources until ownership is resolved")
        elif discovery_row is not None and (
                readiness == "BLOCKED" or existence != "EXISTS_READY"):
            status = INTEGRATION_BLOCKED_NOT_READY
            status_reason = (f"SYS-2/SYS-4: existence {existence}, readiness {readiness} "
                             "-- the subsystem itself is not integrable yet")
        elif subsystem_held:
            status = INTEGRATION_HELD
            status_reason = (f"SYS-12 held {len(subsystem_held)} of this subsystem's "
                             "resources pending physical-equivalence evidence")
        elif discovery_row is not None and readiness == "READY" and not conflicts:
            status = INTEGRATION_READY
            status_reason = ("EXISTS_READY, readiness READY, and no active-driver or "
                             "configuration conflict touches this subsystem")
        else:
            status = INTEGRATION_UNKNOWN
            status_reason = (
                "no SYS-1..4 discovery row supplied, so readiness is unknown"
                if discovery_row is None else
                f"readiness {readiness} with {len(conflicts)} conflict finding(s) -- "
                "not blocked, not proven ready")

        rows.append({
            "Subsystem": subsystem,
            "Environment": str(inv.get("environment_root")
                               or (discovery_row or {}).get("environment_path")
                               or NOT_AVAILABLE),
            "command.txt": command_cell,
            "Readiness": readiness,
            "VIPs": str(len(owned)),
            "Scoreboard": (f"{scoreboard['status']}({scoreboard['count']})"
                           if scoreboard["status"] != NOT_AVAILABLE
                           else f"{NOT_AVAILABLE}({scoreboard['count']})"),
            "Shared Resources": str(len(shared_ids)),
            "Conflicts": str(len(conflicts)),
            "Integration Status": status,
            "detail": {
                "existence_class": existence,
                "release_sha": inv.get("release_sha") or "",
                "command_files": command_files,
                "vip_resource_ids": owned,
                "scoreboard": scoreboard,
                "shared_registry_entry_ids": shared_ids,
                "conflicts": conflicts,
                "stopped_resource_ids": subsystem_stopped,
                "held_resource_ids": subsystem_held,
                "integration_status_reason": status_reason,
                "connectivity_matrix_status": inv.get("connectivity_matrix_status"),
                "matrix_self_check": inv.get("matrix_self_check", {}).get("status"),
            },
        })

    matrix = {
        "columns": list(SYS16_COLUMNS),
        "rows": rows,
        "selected_subsystems": selected,
        "summary": {
            "row_count": len(rows),
            "by_integration_status": {
                s: sum(1 for r in rows if r["Integration Status"] == s)
                for s in INTEGRATION_STATUSES},
        },
        "artifacts_modified": False,
    }
    assert_every_selected_subsystem_present(matrix, selected)
    return matrix


def assert_every_selected_subsystem_present(matrix: Mapping[str, Any],
                                            selected: Sequence[str]) -> None:
    """SYS-16: "Every selected subsystem must appear." Raises rather than
    warns -- a table that silently omits a selected subsystem is read as a
    complete statement about the selection, and a reader has no way to tell
    the omission from an empty result."""
    present = {str(r["Subsystem"]) for r in matrix.get("rows") or []}
    missing = [s for s in selected if s not in present]
    if missing:
        raise SystemResourceRegistryError("SYS16_SELECTED_SUBSYSTEM_MISSING_FROM_MATRIX", {
            "missing": missing, "present": sorted(present),
            "hint": "SYS-16 requires a row for every selected subsystem, including one "
                    "whose analysis produced nothing"})


def _cell(value: Any) -> str:
    """One markdown table cell. A literal pipe in a value -- a hierarchy path,
    a bind target, a disagreement -- silently splits the row into extra
    columns, which is the kind of corruption a reader cannot see."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_subsystem_integration_matrix(matrix: Mapping[str, Any]) -> str:
    """SYS-16's mandated table as markdown, its nine columns in its own order."""
    lines = ["| " + " | ".join(SYS16_COLUMNS) + " |",
             "|" + "---|" * len(SYS16_COLUMNS)]
    for row in matrix.get("rows") or []:
        lines.append("| " + " | ".join(_cell(row.get(c, "-")) for c in SYS16_COLUMNS) + " |")
    if len(lines) == 2:
        lines.append("| _(no subsystem selected)_ |"
                     + " - |" * (len(SYS16_COLUMNS) - 1))
    return "\n".join(lines)


# ===========================================================================
# SYS-17: VIP / AGENT DEDUPLICATION MATRIX
# ===========================================================================

def _physical_interface_cell(relationship: Mapping[str, Any],
                             a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    """SYS-17's "Physical Interface" column: the concrete thing the two
    resources were found to share, or UNRESOLVED. Never a hierarchy path
    invented from one side -- if the two environments do not share a declared
    physical-interface id or a bind target, the honest cell is UNRESOLVED, and
    that is exactly the cell that tells a reviewer why the row is UNKNOWN."""
    declared = {str(a.get("physical_interface_id") or ""),
                str(b.get("physical_interface_id") or "")} - {""}
    if len(declared) == 1:
        return declared.pop()
    binds = {str(a.get("bind_target") or ""), str(b.get("bind_target") or "")} - {""}
    if len(binds) == 1:
        return binds.pop()
    if relationship.get("physical_identity_evidence"):
        return ("UNNAMED(identity from "
                f"{','.join(relationship['physical_identity_evidence'])})")
    return sri.UNRESOLVED


def build_vip_deduplication_matrix(analysis: Mapping[str, Any],
                                   registry: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-17's mandatory table: one row per apparent duplicate, eight columns,
    a Decision from the closed eight-value vocabulary.

    Two row sources, because SYS-12's rule is about two ACTIVE AGENTS and not
    about two subsystems:

      * every cross-subsystem pair SYS-10/SYS-11 produced, and
      * every WITHIN-subsystem active bind-target collision
        (`connectivity.find_active_bind_target_collisions()`, run per subsystem
        by the SYS-9 layer). Those rows carry the same subsystem in both the
        A and B columns, which is visible in the rendered table. Omitting them
        because the mandated columns are named "Subsystem A"/"Subsystem B"
        would drop a real BLOCKED finding out of the decision table that a
        human signs off on.
    """
    by_id = {r["resource_id"]: r for r in analysis["inventory"]["resources"]}
    entry_of = dict(registry.get("entry_of_resource") or {})
    pair_decisions = dict(registry.get("pair_decisions") or {})

    rows: List[Dict[str, Any]] = []
    for rel in analysis.get("relationships") or []:
        rid_a, rid_b = rel["resource_a"], rel["resource_b"]
        a, b = by_id.get(rid_a, {}), by_id.get(rid_b, {})
        decision = pair_decisions.get(f"{rid_a}|{rid_b}") or {}
        # One entry id when the pair MERGED (physical identity established);
        # both, joined, when it did not. A row that printed only one side's
        # entry for an unmerged pair would read as though the registry had
        # collapsed them, which is the opposite of what it recorded.
        entry_a = entry_of.get(rid_a, rid_a)
        entry_b = entry_of.get(rid_b, rid_b)
        rows.append({
            "Resource": entry_a if entry_a == entry_b else f"{entry_a} ~ {entry_b}",
            "Subsystem A": rel["subsystem_a"],
            "Subsystem B": rel["subsystem_b"],
            "Physical Interface": _physical_interface_cell(rel, a, b),
            "Relationship": rel["relationship"],
            "Active Driver Conflict": decision.get(
                "active_driver_conflict", active_driver_conflict_verdict(rel)),
            "Decision": decision.get("decision", DECISION_UNKNOWN),
            "System Owner": decision.get("system_owner", OWNER_UNRESOLVED),
            "detail": {
                "scope": "CROSS_SUBSYSTEM",
                "resource_a": rid_a, "resource_b": rid_b,
                "resource_type_a": a.get("resource_type"),
                "resource_type_b": b.get("resource_type"),
                "physical_identity_evidence": rel["physical_identity_evidence"],
                "logical_identity_evidence": rel["logical_identity_evidence"],
                "decision_reason": decision.get("reason", ""),
                "sys13_promotion_decision": decision.get("sys13_promotion_decision"),
                "overridden_by_sys12_stop": decision.get("overridden_by_sys12_stop", False),
                "duplicate_observability": decision.get("duplicate_observability"),
                "interchangeable_copies": decision.get("interchangeable_copies") or [],
                "retention_choice": decision.get("retention_choice", ""),
                "recommendation_only": True,
            },
        })

    for per in analysis["inventory"].get("per_subsystem") or []:
        subsystem = per["subsystem_id"]
        for collision in per.get("within_subsystem_bind_collisions") or []:
            ids = [f"{subsystem}::{r}" for r in collision["rows"]]
            rows.append({
                "Resource": entry_of.get(ids[0], ids[0]),
                "Subsystem A": subsystem,
                "Subsystem B": subsystem,
                "Physical Interface": collision["bind_target"],
                "Relationship": sri.REL_DRIVER_CONFLICT,
                "Active Driver Conflict": ADC_YES,
                "Decision": BLOCKED,
                "System Owner": OWNER_UNRESOLVED,
                "detail": {
                    "scope": "WITHIN_SUBSYSTEM",
                    "resource_ids": ids,
                    "decision_reason": (
                        "two ACTIVE rows of this subsystem's OWN connectivity matrix "
                        f"claim bind target {collision['bind_target']!r} "
                        "(connectivity.find_active_bind_target_collisions); SYS-12's rule "
                        "is about two active agents, not two subsystems"),
                    "recommendation_only": True,
                },
            })

    rows.sort(key=lambda r: (DECISION_SEVERITY[r["Decision"]], r["Resource"],
                             r["Subsystem A"], r["Subsystem B"]))
    by_decision = {d: 0 for d in SYS17_DECISIONS}
    for row in rows:
        by_decision[row["Decision"]] += 1
    by_adc = {v: 0 for v in ADC_VALUES}
    for row in rows:
        by_adc[row["Active Driver Conflict"]] += 1
    return {
        "columns": list(SYS17_COLUMNS),
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "by_decision": by_decision,
            "by_active_driver_conflict": by_adc,
            "blocked": by_decision[BLOCKED],
            "reuse_shared": by_decision[REUSE_SHARED],
        },
        "decision_vocabulary": list(SYS17_DECISIONS),
        "artifacts_modified": False,
    }


def render_vip_deduplication_matrix(matrix: Mapping[str, Any]) -> str:
    """SYS-17's mandated table as markdown, its eight columns in its own order."""
    lines = ["| " + " | ".join(SYS17_COLUMNS) + " |",
             "|" + "---|" * len(SYS17_COLUMNS)]
    for row in matrix.get("rows") or []:
        lines.append("| " + " | ".join(_cell(row.get(c, "-")) for c in SYS17_COLUMNS) + " |")
    if len(lines) == 2:
        lines.append("| _(no apparent duplicate found across the selected subsystems -- "
                     "an absence of candidates, not a proof that none exists)_ |"
                     + " - |" * (len(SYS17_COLUMNS) - 1))
    return "\n".join(lines)


# ===========================================================================
# Orchestration
# ===========================================================================

def build_system_integration_plan(analysis: Mapping[str, Any], *,
                                  selection: Optional[Mapping[str, Any]] = None,
                                  synthesis: Optional[Mapping[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """SYS-15 -> SYS-16 -> SYS-17 over one SYS-9..14 cross-subsystem resource
    analysis. Reads only; writes nothing anywhere."""
    registry = build_system_resource_registry(analysis)
    integration_matrix = build_subsystem_integration_matrix(
        analysis, registry, selection=selection, synthesis=synthesis)
    dedup_matrix = build_vip_deduplication_matrix(analysis, registry)
    return {
        "system_resource_registry": registry,
        "subsystem_integration_matrix": integration_matrix,
        "vip_agent_deduplication_matrix": dedup_matrix,
        "summary": {
            "subsystems": list(analysis["inventory"]["subsystems"]),
            "registry_entries": registry["summary"]["entry_count"],
            "collapsed_resources": registry["summary"]["collapsed_resource_count"],
            "shared_entries": registry["summary"]["shared_entry_count"],
            "entries_by_reuse_decision": registry["summary"]["entries_by_reuse_decision"],
            "integration_rows": integration_matrix["summary"]["row_count"],
            "by_integration_status": integration_matrix["summary"]["by_integration_status"],
            "deduplication_rows": dedup_matrix["summary"]["row_count"],
            "deduplication_by_decision": dedup_matrix["summary"]["by_decision"],
            "blocked_decisions": dedup_matrix["summary"]["blocked"],
            "integration_plan_clean": (
                dedup_matrix["summary"]["blocked"] == 0
                and integration_matrix["summary"]["by_integration_status"][
                    INTEGRATION_BLOCKED_DRIVER_CONFLICT] == 0
                and integration_matrix["summary"]["by_integration_status"][
                    INTEGRATION_BLOCKED_NOT_READY] == 0),
        },
        "artifacts_modified": False,
        "phase_boundary": PHASE_BOUNDARY,
    }


def plan_system_integration(root, selected: Sequence[str], *,
                            declared: Optional[Mapping[str, Any]] = None,
                            knowledge_center_client: Any = None,
                            inventory_overlay_path=None,
                            ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..8 analysis -> SYS-9..14 resource
    analysis -> SYS-15..17 registry and mandatory tables.

    The whole lower stack is reused as-is through
    `system_resource_inventory.analyze_selected_subsystem_resources()`, which
    itself goes through `subsystem_discovery.require_explicit_selection()` --
    so SYS-1's refusal to compose a set the user did not choose is not
    bypassed by adding a verb on top of it.
    """
    result = sri.analyze_selected_subsystem_resources(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path)
    plan = build_system_integration_plan(
        result["resource_analysis"], selection=result["selection"],
        synthesis=result["synthesis"])
    return {"selection": result["selection"], "synthesis": result["synthesis"],
            "resource_analysis": result["resource_analysis"],
            "integration_plan": plan}


# ===========================================================================
# Reporting
# ===========================================================================

def render_registry_table(registry: Mapping[str, Any]) -> str:
    """The SYS-15 registry as markdown. SYS-15 mandates the registry's FIELDS,
    not a table shape (SYS-16 and SYS-17 are the mandated tables), so this is
    a readable projection: `owner` and `consumer_subsystems` next to each
    other, because their being different fields is the whole reason this
    registry exists. Every one of the 19 fields is in the JSON entry."""
    columns = ["RESOURCE_ID", "TYPE", "PROTOCOL", "OWNER", "CONSUMER_SUBSYSTEMS",
               "ACTIVE/PASSIVE", "SHARED", "EXCLUSIVE", "CLOCK", "RESET",
               "CONFLICT_STATUS", "REUSE_DECISION", "CONFIDENCE"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for entry in registry.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["resource_id"], entry["resource_type"], entry["protocol"],
            entry["owner"], ",".join(entry["consumer_subsystems"]),
            entry["active_passive"] or sri.UNRESOLVED, entry["shared"],
            entry["exclusive"], entry["clock"], entry["reset"],
            entry["conflict_status"], entry["reuse_decision"], entry["confidence"],
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no resources inventoried)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def format_integration_plan_report(plan: Mapping[str, Any]) -> str:
    """The SYS-15..SYS-17 deliverable. Reporting only -- this function emits no
    SystemVerilog, no command.txt and no routing table."""
    summary = plan["summary"]
    registry = plan["system_resource_registry"]
    integration = plan["subsystem_integration_matrix"]
    dedup = plan["vip_agent_deduplication_matrix"]

    out = ["# SYSTEM RESOURCE REGISTRY AND INTEGRATION MATRICES (SYS-15..SYS-17)", "",
           f"- subsystems: {summary['subsystems']}",
           f"- registry entries: {summary['registry_entries']} "
           f"({summary['collapsed_resources']} subsystem-local resources collapsed into "
           f"shared entries; {summary['shared_entries']} entries are consumed by more "
           "than one subsystem)",
           f"- reuse decisions: {summary['entries_by_reuse_decision']}",
           f"- deduplication rows: {summary['deduplication_rows']} "
           f"({summary['blocked_decisions']} BLOCKED)",
           f"- integration status: {summary['by_integration_status']}",
           f"- integration plan clean: {summary['integration_plan_clean']}", "",
           "## SYS-15 SYSTEM_RESOURCE_REGISTRY", "",
           "The authority for System-Level resource composition, at RESOURCE "
           "granularity -- one entry per SYSTEM-level resource, `owner` and "
           "`consumer_subsystems` as separate fields. This is a different registry "
           "from `.dv-harness/soc-composer/subsystem_environment_registry.json`, "
           "which is one row per ENVIRONMENT and carries only identity/qualification "
           "metadata.", "",
           render_registry_table(registry), ""]

    conflicted = [e for e in registry["entries"]
                  if e["conflict_status"] != CONFLICT_NONE
                  or e["reuse_decision"] in (BLOCKED, RECONFIGURE, DECISION_UNKNOWN)]
    if conflicted:
        out += ["### Entries needing a human decision", ""]
        for entry in conflicted:
            out.append(f"- [{entry['reuse_decision']}] {entry['resource_id']} "
                       f"({entry['conflict_status']}): "
                       f"{entry['reuse_decision_reason'].replace(chr(10), ' ')[:400]}")
        out.append("")

    out += ["## SYS-16 SUBSYSTEM INTEGRATION MATRIX", "",
            render_subsystem_integration_matrix(integration), "",
            "Every selected subsystem appears; a cell reading NOT_AVAILABLE means the "
            "artifact that would answer it was not supplied, which is a different "
            "finding from a zero.", ""]

    out += ["## SYS-17 VIP / AGENT DEDUPLICATION MATRIX", "",
            render_vip_deduplication_matrix(dedup), "",
            f"Decision vocabulary: {' / '.join(SYS17_DECISIONS)}.",
            "A row whose Subsystem A and Subsystem B are the same subsystem is a "
            "WITHIN-subsystem active bind-target collision: SYS-12's rule is about two "
            "active agents, not two subsystems, so it is reported in the same decision "
            "table rather than dropped.", ""]

    blocked_rows = [r for r in dedup["rows"] if r["Decision"] == BLOCKED]
    if blocked_rows:
        out += ["### BLOCKED pairs", ""]
        for row in blocked_rows:
            out.append(f"- {row['Resource']} ({row['Subsystem A']} / "
                       f"{row['Subsystem B']}): "
                       f"{row['detail']['decision_reason'].replace(chr(10), ' ')[:400]}")
        out.append("")

    out += ["## PHASE BOUNDARY", "", plan["phase_boundary"]]
    return "\n".join(out)
