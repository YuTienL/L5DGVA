"""dv_harness/example_composition.py -- composes multiple already-qualified VIP
examples into ONE scenario, gated by an explicit 8-condition composability
check, 2026-09-06 (extended 2026-09-07 with condition 8,
DUT_TOPOLOGY_APPLICABLE).

THE GAP THIS CLOSES
-------------------
Nothing in this repo checked whether SEVERAL qualified VIP examples can be
safely combined into one scenario. `vip_capability_extraction.py` classifies
individual VIP source CLASSES into config/transaction/scenario-pattern/
checker/coverage capability records with a qualification tag; `env_manifest.py`
records which VIP instances are configured in ONE already-generated
environment; `ip_ownership_conflict.py` flags a VIP-vs-legacy-BFM ownership
clash for a SINGLE subsystem; `system_resource_inventory.py`'s SYS-11/SYS-12
machinery flags an ACTIVE_DRIVER_CONFLICT across ALREADY-COMPOSED SoC
subsystems. None of them answers the earlier, narrower question this module
answers: given a caller-declared SET of individually-qualified VIP examples
that are ABOUT TO be combined into one scenario (e.g. a USB3 host example plus
a USB3 device example, or a host example plus an AMBA monitor example), are
they actually compatible with each other, checked against the seven concrete
conditions this task names -- VIP version, role, protocol mode, agent config,
sequencer ownership, reset assumptions, clock assumptions -- BEFORE any of
that content is merged into a single command.txt/scenario body.

REUSE OVER REINVENT / FILE-SAFETY SCOPE
----------------------------------------
Per this batch's file-safety scope, this module imports NOTHING from
`vip_capability_extraction.py`, `ip_ownership_conflict.py`,
`system_resource_inventory` (a different concurrently-running batch owns the
first; the others are separate, real, already-existing mechanisms this module
deliberately does not duplicate). `examples` is therefore accepted as a plain,
duck-typed list of dicts -- the same general SHAPE `vip_capability_extraction.py`
would produce for a "this is a real, already-qualified VIP artifact" record
(an identity, a VIP type/version, a declared role, a declared config), widened
here with the composition-specific facts this task names (protocol mode,
sequencer/interface ownership, reset/clock assumptions). A field this module
does not recognise on a supplied dict is simply never read -- never guessed
at, following the same alias-tolerant `_get()` convention
`existing_command_reuse_score.py` already established for exactly this reason.

WHAT "QUALIFIED" MEANS HERE, AND WHAT IT DOES NOT
---------------------------------------------------
This module does not itself decide whether an example is qualified -- that
judgment belongs to whatever produced the example record (a real
`vip_capability_extraction.py`-shaped classification, a project's own VIP
qualification process, or a human). Composition here means: given examples the
CALLER already asserts are individually usable, are they usable TOGETHER. It
is deliberately a narrower question than "is this a good VIP example", the
same separation `subsystem_maturity_gate.py` keeps between "does a real
producer's report say MET" and "is the underlying thing itself correct".

THE SEVEN CONDITIONS, AND HOW EACH IS CHECKED MECHANICALLY (NEVER SEMANTICALLY)
---------------------------------------------------------------------------------
Every condition is a pure structural comparison of caller-declared facts --
never an inference about protocol behaviour, and never a fabricated
compatibility rule this codebase has no evidence for:

1. **Compatible VIP version** -- examples sharing the same normalised
   `vip_type` (the same underlying VIP package) must declare the SAME
   `vip_version`. Scoped to `vip_type` alone, never to a link: running two
   different released versions of literally the same VIP package compiled
   into one environment is not a per-port variation, it is a package-identity
   conflict.
2. **Compatible role** -- on one LOGICAL LINK (see `_link_key()` below), at
   most one example may declare a role this module recognises as an ACTIVE
   driving role (`ACTIVE_ROLE_TOKENS`: HOST/MASTER/INITIATOR/DRIVER/ACTIVE/
   ROOT_COMPLEX/RC/REQUESTER). Two examples both claiming to be the active
   host/master/initiator of the same link is a real role conflict regardless
   of which underlying VIP type implements each side. A role this module does
   not recognise (e.g. a passive/responder role, or free text outside the
   fixed vocabulary) never blocks this condition -- an unrecognised role is
   "we do not know", never "we assume it is safe" NOR "we assume it
   conflicts".
3. **Compatible protocol mode** -- on one logical link, every example's
   declared `protocol_mode` (e.g. a speed/generation/lane-count string) must
   agree exactly. A host example declaring "USB3.1_GEN2x1" and a device
   example on the same link declaring "USB3.1_GEN1x1" is exactly the
   conflict this condition exists to catch.
4. **Compatible agent config** -- on one logical link, for every
   `agent_config` field TWO OR MORE examples both declare, the values must
   agree. A field only one side declares is not compared (absence is not
   evidence of a conflict); a field both declare with disagreeing values is.
5. **No conflicting sequencer ownership** -- across ALL examples regardless
   of link/vip_type, two or more examples declaring the SAME explicit
   sequencer/interface/bind path AND both resolving to an ACTIVE driver
   (declared or inferred from an ACTIVE/PASSIVE role token) is a real
   ownership collision -- the same shape `ip_ownership_conflict.py` and
   `system_resource_inventory.py`'s ACTIVE_DRIVER_CONFLICT already guard at a
   different scope, checked here structurally rather than imported.
6. **No conflicting reset assumptions** -- two or more examples naming the
   SAME reset signal must agree on its declared `active_level`/`synchronous`.
7. **No conflicting clock assumptions** -- two or more examples naming the
   SAME clock signal must agree on its declared `frequency_mhz`/`period_ns`/
   `edge`.

CONDITION 8 (2026-09-07 GAP-CLOSE): DUT_TOPOLOGY_APPLICABLE -- AN EXAMPLE'S
OWN STRUCTURE, CHECKED AGAINST REAL DUT TOPOLOGY, NOT AGAINST ANOTHER EXAMPLE
------------------------------------------------------------------------------
Every one of the seven conditions above validates examples AGAINST EACH
OTHER -- none of them ever asks whether ONE example's own declared structure
corresponds to anything in the project's REAL DUT topology before that
example is trusted as a compatibility reference at all. Condition 8 closes
exactly that gap: an example's declared `dut_target_instance` (a dot-
separated DUT hierarchy path -- the same `target_instance` vocabulary
`connectivity.py`'s own bind-entry contract already uses, per CLAUDE.md's
Bind-Location Rules, reused here rather than a second name for the same
concept) is checked against a caller-supplied, real
`design_architecture_ir.build_architecture_ir()`-shaped instance tree.
See `check_dut_topology_applicability()`'s own docstring for the full
mechanical rationale (a longest-real-suffix match, never a whole-path
assumption, never a fabricated match). Absent a real, successfully-built
topology document, this condition is honestly `NOT_APPLICABLE` -- an
example's DUT-target structure was simply never checked, never assumed
clean by omission.

`_link_key()` IS THE ONE DELIBERATE, DISCLOSED DESIGN CHOICE THIS MODULE MAKES
FOR CONDITIONS 2-4
--------------------------------------------------------------------------------
Conditions 2-4 are scoped to one "logical link" -- a caller-declared
`link_id`/`interface_id`/`port_id`, falling back to a declared
`sequencer_path` when no link identity is given, falling back further to one
shared `UNSPECIFIED_LINK` bucket when NEITHER is declared on an example. That
last fallback is deliberate and disclosed rather than silent: when a caller's
example set gives this module no way to tell two examples apart as
independent ports/links, treating them as unrelated would be an UNEARNED
assumption of independence -- the Evidence Truth Rule's "never silently
default or guess" cuts against assuming safety just as much as it cuts
against assuming danger. So examples with no declared link/port/sequencer
identity are conservatively treated as one implicit link, and a real
role/mode/config disagreement among them is surfaced rather than hidden
behind the absence of disambiguating evidence. A caller composing a genuine
independent multi-port scenario must declare `link_id`/`port_id`/
`sequencer_path` to distinguish the ports -- exactly the same evidence this
module would need to tell them apart correctly in the first place.

NEVER RESOLVES A CONFLICT -- ONLY NAMES THE PAIR
--------------------------------------------------
Every conflict this module finds is reported as `status: BLOCKED` naming the
exact conflicting pair (both examples' declared identities) and the specific
disagreeing value(s) -- never silently merged, never averaged, and this
module never picks a "winner" between two examples. Resolving which example's
assumption is correct is a human/caller decision this module does not make,
the same ARBITRATION boundary `requirement_contract.py` and
`design_knowledge_correlation.py` already keep for their own conflict
findings.

DECIDES NOTHING BEYOND THE GATE
---------------------------------
This module builds no VIP API, no RTL content, no scenario/command.txt body,
runs no build/regression/LSF job, and there is deliberately no `STAGE_GATES`
entry -- a gate that passed on a composition nobody actually generated from
would be worse than none. Malformed input (a non-dict entry, an entry with no
resolvable identity, two entries sharing one identity) is reported in
`malformed_examples` and excluded from the composition rather than crashing
the whole evaluation or being silently merged into an anonymous participant.

Front door: `python -m dv_harness.example_composition compose --examples
<file.json> [--dut-topology <file.json>] [--json]` (`execute_verb()`, the
same shared-implementation convention `power-intent`/`golden-scenario`/
`config-variants` use). `--dut-topology` is optional and feeds condition 8
only; omitted, condition 8 reports NOT_APPLICABLE and every other condition
is unaffected. Exit 0 COMPOSED, 1 BLOCKED (a real conflict was found on any
of the 8 conditions), 2 NOT_AVAILABLE (fewer than two valid examples, or a
malformed input document). There is no `dv-harness` CLI verb -- `cli.py` is
out of this batch's file-safety scope, the same disclosed choice several
sibling 2026-09-06/07 modules already state.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

STATUS_COMPOSED = "COMPOSED"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

COND_STATUS_CLEAR = "CLEAR"
COND_STATUS_CONFLICT = "CONFLICT"
COND_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

#: The seven conditions, in the task's own stated order. `assert_conditions_
#: complete()` (below) holds this tuple and the real check-function table
#: equal at import time, so a future edit adding a check without wiring it
#: into `CONDITION_CHECKS` fails a test rather than silently under-reporting.
COND_VIP_VERSION = "VIP_VERSION_COMPATIBLE"
COND_ROLE = "ROLE_COMPATIBLE"
COND_PROTOCOL_MODE = "PROTOCOL_MODE_COMPATIBLE"
COND_AGENT_CONFIG = "AGENT_CONFIG_COMPATIBLE"
COND_SEQUENCER_OWNERSHIP = "NO_SEQUENCER_OWNERSHIP_CONFLICT"
COND_RESET_ASSUMPTIONS = "NO_RESET_ASSUMPTION_CONFLICT"
COND_CLOCK_ASSUMPTIONS = "NO_CLOCK_ASSUMPTION_CONFLICT"
#: 2026-09-07 gap-close (vip_example_dut_topology_applicability): the seven
#: conditions above all validate examples AGAINST EACH OTHER. None of them
#: ever asks whether ONE example's own declared structure corresponds to
#: anything in the project's REAL DUT topology before that example is
#: trusted as a compatibility reference at all -- see
#: `check_dut_topology_applicability()` below for the full rationale.
COND_DUT_TOPOLOGY_APPLICABILITY = "DUT_TOPOLOGY_APPLICABLE"

CONDITIONS = (
    COND_VIP_VERSION,
    COND_ROLE,
    COND_PROTOCOL_MODE,
    COND_AGENT_CONFIG,
    COND_SEQUENCER_OWNERSHIP,
    COND_RESET_ASSUMPTIONS,
    COND_CLOCK_ASSUMPTIONS,
    COND_DUT_TOPOLOGY_APPLICABILITY,
)

CONDITION_DESCRIPTIONS = {
    COND_VIP_VERSION: "examples sharing one VIP type must declare the same VIP version",
    COND_ROLE: "at most one example per logical link may declare an active driving role",
    COND_PROTOCOL_MODE: "examples on one logical link must declare the same protocol mode",
    COND_AGENT_CONFIG: "examples on one logical link must agree on any agent_config field "
                        "both declare",
    COND_SEQUENCER_OWNERSHIP: "at most one active driver may claim any one sequencer/"
                              "interface/bind path",
    COND_RESET_ASSUMPTIONS: "examples naming the same reset signal must agree on its "
                            "active_level/synchronous facts",
    COND_CLOCK_ASSUMPTIONS: "examples naming the same clock signal must agree on its "
                            "frequency_mhz/period_ns/edge facts",
    COND_DUT_TOPOLOGY_APPLICABILITY: "an example's own declared DUT target-instance path must "
                                     "resolve against the project's real, parsed DUT instance "
                                     "topology before the example is trusted as a compatibility "
                                     "reference",
}

#: Role tokens (normalised upper-case, single word) this module recognises as
#: an ACTIVE, bus-driving role. Anything else is simply unrecognised for the
#: role-compatibility condition -- never assumed active, never assumed
#: passive. This is a fixed, disclosed vocabulary, not a claim that these are
#: the only active-role words any real protocol ever uses.
ACTIVE_ROLE_TOKENS = frozenset({
    "HOST", "MASTER", "INITIATOR", "DRIVER", "ACTIVE", "ROOT_COMPLEX", "RC", "REQUESTER",
})
PASSIVE_ROLE_TOKENS = frozenset({
    "DEVICE", "SLAVE", "TARGET", "RESPONDER", "ENDPOINT", "EP", "COMPLETER",
    "MONITOR", "PASSIVE", "OBSERVER",
})

UNSPECIFIED_LINK = "UNSPECIFIED_LINK"

_NUMERIC_TOLERANCE = 1e-6


class ExampleCompositionError(Exception):
    """Base for every refusal in this module."""


class CompositionInputError(ExampleCompositionError):
    """`examples` itself is not a usable sequence (not a list/tuple at all)."""


# --------------------------------------------------------------------------
# field-alias normalisation (a caller's example dict may spell any of these
# concepts differently -- never guessed at, only read through this table)
# --------------------------------------------------------------------------

_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "identity": ("example_id", "EXAMPLE_ID", "id", "ID", "name", "NAME", "instance_id"),
    "vip_type": ("vip_type", "VIP_TYPE", "vip_name", "VIP_NAME", "vip"),
    "vip_version": ("vip_version", "VIP_VERSION", "version", "VERSION"),
    "role": ("role", "ROLE"),
    "protocol_mode": ("protocol_mode", "PROTOCOL_MODE", "mode", "MODE"),
    "agent_config": ("agent_config", "AGENT_CONFIG", "config", "CONFIG", "config_fields"),
    "sequencer_path": ("sequencer_path", "SEQUENCER_PATH", "interface_path", "INTERFACE_PATH",
                       "bind_target", "BIND_TARGET", "instance_path", "INSTANCE_PATH"),
    "link_id": ("link_id", "LINK_ID", "interface_id", "INTERFACE_ID", "port_id", "PORT_ID"),
    #: The DUT-side hierarchical instance path this example claims to target
    #: -- deliberately a DIFFERENT concept from `sequencer_path` above
    #: (that is the VIP-side TB sequencer hierarchy; this is the real DUT
    #: instance chain the example's interface is claimed to bind against).
    #: `target_instance` is the exact field name `connectivity.py`'s own
    #: bind-entry contract already uses for this concept (see CLAUDE.md's
    #: Bind-Location Rules), reused here rather than inventing a second
    #: vocabulary for the same fact.
    "dut_target_instance": ("dut_target_instance", "DUT_TARGET_INSTANCE", "target_instance",
                            "TARGET_INSTANCE", "dut_instance_path", "DUT_INSTANCE_PATH"),
    "active": ("active", "ACTIVE", "is_active", "IS_ACTIVE", "driver_active"),
    "reset_assumptions": ("reset_assumptions", "RESET_ASSUMPTIONS", "reset"),
    "clock_assumptions": ("clock_assumptions", "CLOCK_ASSUMPTIONS", "clock"),
}


def _get(d: dict, concept: str, default=None):
    if not isinstance(d, dict):
        return default
    for key in _FIELD_ALIASES.get(concept, (concept,)):
        if key in d and d[key] not in (None, ""):
            return d[key]
    return default


def _norm(s: Any) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s.upper() if s else None


def _norm_lower(s: Any) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s.lower() if s else None


def _values_equal(a: Any, b: Any) -> bool:
    """Representation-tolerant, substance-strict comparator: case/whitespace
    differences in strings and numeric-repr differences (int vs float) never
    manufacture a false conflict, but a genuine value difference always
    does."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < _NUMERIC_TOLERANCE
    return a == b


def _infer_active(explicit: Any, role_norm: Optional[str]) -> Optional[bool]:
    """Resolves whether an example is an ACTIVE driver: an explicit `active`
    field wins; otherwise a recognised role token; otherwise `None` (unknown
    -- never guessed either way)."""
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, str):
        s = explicit.strip().lower()
        if s in ("true", "yes", "active", "1"):
            return True
        if s in ("false", "no", "passive", "0"):
            return False
    if role_norm in ACTIVE_ROLE_TOKENS:
        return True
    if role_norm in PASSIVE_ROLE_TOKENS:
        return False
    return None


def _get_reset(d: dict) -> Optional[dict]:
    raw = _get(d, "reset_assumptions")
    if isinstance(raw, dict):
        signal = raw.get("signal") or raw.get("name") or raw.get("reset_signal")
        if not signal:
            return None
        return {
            "signal_norm": _norm_lower(signal), "signal": signal,
            "active_level": raw.get("active_level"), "synchronous": raw.get("synchronous"),
        }
    # flat aliases directly on the example dict
    signal = d.get("reset_signal") or d.get("RESET_SIGNAL")
    if not signal:
        return None
    return {
        "signal_norm": _norm_lower(signal), "signal": signal,
        "active_level": d.get("reset_active_level") or d.get("RESET_ACTIVE_LEVEL"),
        "synchronous": d.get("reset_synchronous") if "reset_synchronous" in d
                       else d.get("RESET_SYNCHRONOUS"),
    }


def _get_clock(d: dict) -> Optional[dict]:
    raw = _get(d, "clock_assumptions")
    if isinstance(raw, dict):
        signal = raw.get("signal") or raw.get("name") or raw.get("clock_signal")
        if not signal:
            return None
        return {
            "signal_norm": _norm_lower(signal), "signal": signal,
            "frequency_mhz": raw.get("frequency_mhz"), "period_ns": raw.get("period_ns"),
            "edge": raw.get("edge"),
        }
    signal = d.get("clock_signal") or d.get("CLOCK_SIGNAL")
    if not signal:
        return None
    return {
        "signal_norm": _norm_lower(signal), "signal": signal,
        "frequency_mhz": d.get("clock_frequency_mhz") or d.get("CLOCK_FREQUENCY_MHZ"),
        "period_ns": d.get("clock_period_ns") or d.get("CLOCK_PERIOD_NS"),
        "edge": d.get("clock_edge") or d.get("CLOCK_EDGE"),
    }


def _link_key(vip_ex: "VipExample") -> str:
    """A logical-link grouping key: an explicit `link_id` wins, then a
    declared `sequencer_path`, then the shared `UNSPECIFIED_LINK` bucket --
    see the module docstring's disclosed rationale for that fallback."""
    if vip_ex.link_id:
        return f"LINK:{_norm_lower(vip_ex.link_id)}"
    if vip_ex.sequencer_path:
        return f"PATH:{_norm_lower(vip_ex.sequencer_path)}"
    return UNSPECIFIED_LINK


# --------------------------------------------------------------------------
# normalized example record
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VipExample:
    identity: str
    vip_type: Optional[str]
    vip_version: Optional[str]
    role: Optional[str]
    protocol_mode: Optional[str]
    agent_config: Dict[str, Any]
    sequencer_path: Optional[str]
    link_id: Optional[str]
    active: Optional[bool]
    reset: Optional[dict]
    clock: Optional[dict]
    dut_target_instance: Optional[str]
    raw: dict = field(repr=False)


def normalize_examples(examples: Sequence[Any]) -> Tuple[List[VipExample], List[dict]]:
    """Splits `examples` into (usable, malformed). A non-dict entry, an entry
    with no resolvable identity, and every entry sharing a duplicate identity
    are all reported in the malformed list and EXCLUDED from composition --
    never silently included as an anonymous participant (which would make a
    later conflict un-citable) and never silently resolved by picking one of
    the duplicates (which would be exactly the "pick a winner" this module
    refuses to do, extended to malformed input as well as real conflicts)."""
    by_identity: Dict[str, List[int]] = {}
    provisional: List[Optional[VipExample]] = []
    malformed: List[dict] = []

    for idx, raw in enumerate(examples):
        if not isinstance(raw, dict):
            malformed.append({"index": idx, "reason": "EXAMPLE_NOT_A_DICT", "value": repr(raw)})
            provisional.append(None)
            continue
        identity = _get(raw, "identity")
        if not identity:
            malformed.append({"index": idx, "reason": "NO_RESOLVABLE_IDENTITY",
                              "reason_detail": "no example_id/id/name field was supplied; a "
                                                "conflict cannot cite an unnamed example"})
            provisional.append(None)
            continue
        identity = str(identity)
        role_norm = _norm(_get(raw, "role"))
        vip_ex = VipExample(
            identity=identity,
            vip_type=_get(raw, "vip_type"),
            vip_version=_get(raw, "vip_version"),
            role=_get(raw, "role"),
            protocol_mode=_get(raw, "protocol_mode"),
            agent_config=_get(raw, "agent_config") if isinstance(_get(raw, "agent_config"), dict) else {},
            sequencer_path=_get(raw, "sequencer_path"),
            link_id=_get(raw, "link_id"),
            active=_infer_active(_get(raw, "active"), role_norm),
            reset=_get_reset(raw),
            clock=_get_clock(raw),
            dut_target_instance=_get(raw, "dut_target_instance"),
            raw=raw,
        )
        provisional.append(vip_ex)
        by_identity.setdefault(identity, []).append(idx)

    duplicate_indexes = {i for idxs in by_identity.values() if len(idxs) > 1 for i in idxs}
    for identity, idxs in by_identity.items():
        if len(idxs) > 1:
            for idx in idxs:
                malformed.append({"index": idx, "reason": "DUPLICATE_EXAMPLE_ID",
                                  "identity": identity,
                                  "reason_detail": f"{len(idxs)} examples share identity "
                                                    f"{identity!r}; composing them under one "
                                                    "identity is ambiguous, so all of them are "
                                                    "excluded rather than one being picked"})

    usable = [ve for idx, ve in enumerate(provisional)
              if ve is not None and idx not in duplicate_indexes]
    return usable, malformed


# --------------------------------------------------------------------------
# per-condition checks -- each a pure structural comparison, never a semantic
# judgment about protocol behaviour
# --------------------------------------------------------------------------

def _pair_entry(a: VipExample, b: VipExample, detail: dict) -> dict:
    return {"pair": [a.identity, b.identity], "detail": detail}


def _single_entry(a: VipExample, detail: dict) -> dict:
    """The single-example counterpart of `_pair_entry()` -- condition 8 below
    is not a pairwise comparison, it is one example checked against real
    external evidence (the DUT topology), so there is only ever one identity
    to cite. `pair` is kept as a single-element list (rather than dropped)
    purely so `format_composition_report()`'s existing `conflict['pair']`
    rendering keeps working unmodified for every condition, seven pairwise
    and this one single-example condition alike."""
    return {"pair": [a.identity], "example": a.identity, "detail": detail}


def check_vip_version_compatibility(vip_examples: Sequence[VipExample]) -> dict:
    groups: Dict[str, List[VipExample]] = {}
    for ve in vip_examples:
        if ve.vip_type:
            groups.setdefault(_norm_lower(ve.vip_type), []).append(ve)
    conflicts: List[dict] = []
    checked = 0
    for group in groups.values():
        versioned = [ve for ve in group if ve.vip_version]
        if len(versioned) < 2:
            continue
        checked += 1
        for i in range(len(versioned)):
            for j in range(i + 1, len(versioned)):
                a, b = versioned[i], versioned[j]
                if not _values_equal(a.vip_version, b.vip_version):
                    conflicts.append(_pair_entry(a, b, {
                        "vip_type": a.vip_type,
                        "vip_version_a": a.vip_version, "vip_version_b": b.vip_version,
                    }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": "no VIP-type group had two or more examples declaring a vip_version"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked}


def _link_groups(vip_examples: Sequence[VipExample]) -> Dict[str, List[VipExample]]:
    groups: Dict[str, List[VipExample]] = {}
    for ve in vip_examples:
        groups.setdefault(_link_key(ve), []).append(ve)
    return groups


def check_role_compatibility(vip_examples: Sequence[VipExample]) -> dict:
    conflicts: List[dict] = []
    checked = 0
    for link, group in _link_groups(vip_examples).items():
        active_role = [ve for ve in group if _norm(ve.role) in ACTIVE_ROLE_TOKENS]
        if len(active_role) < 2:
            continue
        checked += 1
        for i in range(len(active_role)):
            for j in range(i + 1, len(active_role)):
                a, b = active_role[i], active_role[j]
                conflicts.append(_pair_entry(a, b, {
                    "link": link, "role_a": a.role, "role_b": b.role,
                    "reason": "both examples declare an active driving role on the same "
                              "logical link",
                }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": "no logical link had two or more examples declaring a recognised "
                          "active role"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked}


def check_protocol_mode_compatibility(vip_examples: Sequence[VipExample]) -> dict:
    conflicts: List[dict] = []
    checked = 0
    for link, group in _link_groups(vip_examples).items():
        moded = [ve for ve in group if ve.protocol_mode]
        if len(moded) < 2:
            continue
        checked += 1
        for i in range(len(moded)):
            for j in range(i + 1, len(moded)):
                a, b = moded[i], moded[j]
                if not _values_equal(a.protocol_mode, b.protocol_mode):
                    conflicts.append(_pair_entry(a, b, {
                        "link": link,
                        "protocol_mode_a": a.protocol_mode, "protocol_mode_b": b.protocol_mode,
                    }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": "no logical link had two or more examples declaring a protocol_mode"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked}


def check_agent_config_compatibility(vip_examples: Sequence[VipExample]) -> dict:
    conflicts: List[dict] = []
    checked = 0
    for link, group in _link_groups(vip_examples).items():
        configured = [ve for ve in group if ve.agent_config]
        if len(configured) < 2:
            continue
        checked += 1
        for i in range(len(configured)):
            for j in range(i + 1, len(configured)):
                a, b = configured[i], configured[j]
                shared = sorted(set(a.agent_config) & set(b.agent_config))
                disagreeing = [
                    {"field": k, "value_a": a.agent_config[k], "value_b": b.agent_config[k]}
                    for k in shared if not _values_equal(a.agent_config[k], b.agent_config[k])
                ]
                if disagreeing:
                    conflicts.append(_pair_entry(a, b, {"link": link, "fields": disagreeing}))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": "no logical link had two or more examples declaring an agent_config"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked}


def check_sequencer_ownership(vip_examples: Sequence[VipExample]) -> dict:
    groups: Dict[str, List[VipExample]] = {}
    for ve in vip_examples:
        if ve.sequencer_path:
            groups.setdefault(_norm_lower(ve.sequencer_path), []).append(ve)
    conflicts: List[dict] = []
    unknown_active: List[dict] = []
    checked = 0
    for path, group in groups.items():
        if len(group) < 2:
            continue
        checked += 1
        for ve in group:
            if ve.active is None:
                unknown_active.append({"identity": ve.identity, "sequencer_path": path})
        active = [ve for ve in group if ve.active is True]
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                a, b = active[i], active[j]
                conflicts.append(_pair_entry(a, b, {
                    "sequencer_path": path,
                    "reason": "both examples resolve to an ACTIVE driver of the same "
                              "sequencer/interface/bind path",
                }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": "no sequencer/interface/bind path was declared by two or more "
                          "examples", "unresolved_active_status": []}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked,
            "unresolved_active_status": unknown_active}


def _signal_conflict_check(vip_examples: Sequence[VipExample], getter, compare_fields,
                           kind_label: str) -> dict:
    groups: Dict[str, List[Tuple[VipExample, dict]]] = {}
    for ve in vip_examples:
        s = getter(ve)
        if s is not None:
            groups.setdefault(s["signal_norm"], []).append((ve, s))
    conflicts: List[dict] = []
    checked = 0
    for signal, group in groups.items():
        if len(group) < 2:
            continue
        checked += 1
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                (a, sa), (b, sb) = group[i], group[j]
                disagreeing = [
                    {"field": f, "value_a": sa.get(f), "value_b": sb.get(f)}
                    for f in compare_fields
                    if sa.get(f) is not None and sb.get(f) is not None
                    and not _values_equal(sa.get(f), sb.get(f))
                ]
                if disagreeing:
                    conflicts.append(_pair_entry(a, b, {
                        "signal": group[i][1]["signal"], "fields": disagreeing,
                    }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "groups_checked": 0,
                "reason": f"no {kind_label} signal was named by two or more examples"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "groups_checked": checked}


def check_reset_assumptions(vip_examples: Sequence[VipExample]) -> dict:
    return _signal_conflict_check(vip_examples, lambda ve: ve.reset,
                                  ("active_level", "synchronous"), "reset")


def check_clock_assumptions(vip_examples: Sequence[VipExample]) -> dict:
    return _signal_conflict_check(vip_examples, lambda ve: ve.clock,
                                  ("frequency_mhz", "period_ns", "edge"), "clock")


# --------------------------------------------------------------------------
# condition 8 (2026-09-07 gap-close): DUT_TOPOLOGY_APPLICABLE
#
# THE GAP THIS CLOSES
# --------------------
# The seven conditions above are all EXAMPLE-vs-EXAMPLE comparisons -- they
# ask "do these declared facts agree with EACH OTHER", never "is this
# example's own declared structure real". An example whose declared
# `dut_target_instance` names a DUT hierarchy path that does not exist
# anywhere in this project's actual RTL -- a hallucinated bind target, a
# stale path left over from a different project, a typo -- would pass all
# seven existing conditions cleanly (nothing else disagrees with a fact
# nobody else mentions) and be composed and trusted regardless. This
# condition is the missing check: BEFORE an example is trusted as a
# compatibility reference, does its own declared DUT-facing structure
# actually correspond to something real in the project's parsed DUT
# topology.
#
# WHAT "REAL DUT TOPOLOGY" MEANS HERE
# ------------------------------------
# `dut_topology` is the caller-supplied output of
# `design_architecture_ir.build_architecture_ir()` (or an equivalent
# `design_architecture_ir.save_architecture_ir()`-written JSON document
# loaded back) -- this module never imports `design_architecture_ir.py`
# itself and never builds one: verifying real RTL needs a real verible
# parse this module has no business performing, exactly the same
# duck-typed-input discipline this file's own docstring already commits to
# for VIP capability records. Absent a real, successfully `status: "BUILT"`
# topology document, this condition is honestly NOT_APPLICABLE -- an
# example's DUT-target structure was simply never checked, never assumed
# clean.
#
# HOW THE CHECK WORKS, MECHANICALLY (NEVER SEMANTICALLY)
# ---------------------------------------------------------
# An example's declared `dut_target_instance` (a dot-separated hierarchical
# instance path, e.g. "chip.core.subsys0.usb0") is compared against every
# real instantiation chain the topology's own instance tree actually
# contains. A testbench-level path commonly carries a leading prefix
# (a TB top instance) the DUT-only topology never parsed, so this is
# deliberately a real, contiguous SUFFIX match rather than requiring the
# whole path to match from an assumed root: the longest tail of the
# declared path that exactly equals a real, contiguous chain of instance
# names anywhere in the tree decides the result. A two-or-more-segment
# declared path requires at least a 2-segment real match (a single common
# instance-name word such as "clk" or "if" coinciding by chance is not
# treated as evidence); a single-segment declared path requires only that
# one name to appear. Zero real match at all is the finding this condition
# exists to catch -- reported, never silently passed and never fabricated
# into a guessed match.
# --------------------------------------------------------------------------

def _flatten_dut_instance_chains(dut_topology: Any) -> List[Tuple[Tuple[str, ...], bool, Optional[str]]]:
    """Walks a `design_architecture_ir.build_architecture_ir()`-shaped
    `dut_topology["instance_tree"]["trees"]` into a flat list of every real
    instantiation chain it contains: `(chain_of_instance_names, resolved,
    module_name)`. Tolerant of a malformed/foreign document -- never raises,
    simply contributes no chains, since an unusable topology is exactly the
    NOT_APPLICABLE case this condition already handles honestly."""
    if not isinstance(dut_topology, dict):
        return []
    tree = dut_topology.get("instance_tree")
    if not isinstance(tree, dict):
        return []
    chains: List[Tuple[Tuple[str, ...], bool, Optional[str]]] = []

    def _walk(node: Any, prefix: Tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        instance_name = node.get("instance_name")
        chain = prefix + (str(instance_name),) if instance_name else prefix
        if chain:
            chains.append((chain, bool(node.get("resolved")), node.get("module_name")))
        for child in node.get("children") or []:
            _walk(child, chain)

    for root in tree.get("trees") or []:
        _walk(root, ())
    return chains


def _best_topology_suffix_match(segments: Tuple[str, ...],
                                chains: Sequence[Tuple[Tuple[str, ...], bool, Optional[str]]]) -> Tuple[int, bool]:
    """The longest contiguous SUFFIX of `segments` that exactly equals a
    contiguous suffix of some real chain in `chains` (case-insensitive) --
    see the condition-8 docstring above for why a suffix match, not a
    whole-path match. Returns `(best_match_len, resolved_of_best_match)`;
    `(0, False)` means no real instance chain corresponds to any tail of
    the declared path at all."""
    seg_lower = tuple(s.lower() for s in segments)
    best_len = 0
    best_resolved = False
    for chain, resolved, _module_name in chains:
        chain_lower = tuple(c.lower() for c in chain)
        max_len = min(len(chain_lower), len(seg_lower))
        for length in range(max_len, 0, -1):
            if chain_lower[-length:] == seg_lower[-length:]:
                if length > best_len or (length == best_len and resolved and not best_resolved):
                    best_len, best_resolved = length, resolved
                break
    return best_len, best_resolved


def check_dut_topology_applicability(vip_examples: Sequence[VipExample],
                                     dut_topology: Optional[Any]) -> dict:
    if not isinstance(dut_topology, dict) or dut_topology.get("status") != "BUILT":
        reason = ("no real DUT topology (design_architecture_ir.py's own instance tree) was "
                  "supplied to validate against")
        if isinstance(dut_topology, dict) and dut_topology.get("status"):
            reason = (f"the supplied DUT topology reports status={dut_topology.get('status')!r} "
                      f"({dut_topology.get('reason')!r}) -- no real instance tree to validate "
                      "against")
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "examples_checked": 0,
                "reason": reason}

    chains = _flatten_dut_instance_chains(dut_topology)
    conflicts: List[dict] = []
    checked = 0
    for ve in vip_examples:
        declared = ve.dut_target_instance
        if not declared:
            continue
        checked += 1
        segments = tuple(s for s in str(declared).split(".") if s)
        if not segments:
            continue
        min_required = 2 if len(segments) >= 2 else 1
        best_len, _resolved = _best_topology_suffix_match(segments, chains)
        if best_len < min_required:
            conflicts.append(_single_entry(ve, {
                "declared_dut_target_instance": declared,
                "reason": "no real instance chain in the project's parsed DUT topology matches "
                          "any tail of this declared path -- this example cannot be trusted as "
                          "a compatibility reference until its DUT target is verified against "
                          "real RTL",
                "longest_real_match_segments": best_len,
                "segments_required": min_required,
            }))
    if checked == 0:
        return {"status": COND_STATUS_NOT_APPLICABLE, "conflicts": [], "examples_checked": 0,
                "reason": "no example declared a dut_target_instance to validate against the "
                          "real DUT topology"}
    return {"status": COND_STATUS_CONFLICT if conflicts else COND_STATUS_CLEAR,
            "conflicts": conflicts, "examples_checked": checked}


CONDITION_CHECKS = {
    COND_VIP_VERSION: check_vip_version_compatibility,
    COND_ROLE: check_role_compatibility,
    COND_PROTOCOL_MODE: check_protocol_mode_compatibility,
    COND_AGENT_CONFIG: check_agent_config_compatibility,
    COND_SEQUENCER_OWNERSHIP: check_sequencer_ownership,
    COND_RESET_ASSUMPTIONS: check_reset_assumptions,
    COND_CLOCK_ASSUMPTIONS: check_clock_assumptions,
    #: Dispatched specially in `evaluate_vip_example_composition()` (it needs
    #: the caller-supplied `dut_topology` as a second argument, unlike the
    #: seven pairwise checks above) -- still listed here so
    #: `assert_conditions_complete()` holds it total the same way.
    COND_DUT_TOPOLOGY_APPLICABILITY: check_dut_topology_applicability,
}


def assert_conditions_complete() -> None:
    """Every declared condition has exactly one check function and one
    description -- held total in both directions so a future edit adding a
    condition without wiring it fails at import rather than silently
    under-reporting."""
    declared = set(CONDITIONS)
    checked = set(CONDITION_CHECKS)
    described = set(CONDITION_DESCRIPTIONS)
    if declared != checked:
        raise AssertionError(f"CONDITIONS/CONDITION_CHECKS mismatch: {declared ^ checked}")
    if declared != described:
        raise AssertionError(f"CONDITIONS/CONDITION_DESCRIPTIONS mismatch: {declared ^ described}")


assert_conditions_complete()


# --------------------------------------------------------------------------
# top-level evaluation
# --------------------------------------------------------------------------

def evaluate_vip_example_composition(examples: Sequence[Any],
                                     dut_topology: Optional[Any] = None) -> dict:
    """Composes `examples` (a plain sequence of dicts) into one scenario,
    validated against the 8 conditions (see module docstring for the first
    seven; `dut_topology`, optional, is condition 8's real
    `design_architecture_ir.build_architecture_ir()`-shaped instance-tree
    document -- omitted, condition 8 reports the honest NOT_APPLICABLE it
    always reported before this parameter existed, so every pre-existing
    caller's behaviour is unchanged). Returns a report dict; see module
    docstring for the `status`/`conflicts` shape. Never raises on malformed
    per-example data (reported in `malformed_examples` instead); raises
    `CompositionInputError` only when `examples` itself is not a usable
    sequence."""
    evaluated_at = datetime.now(timezone.utc).isoformat()
    if isinstance(examples, (str, bytes)) or not isinstance(examples, (list, tuple)):
        raise CompositionInputError(
            "examples must be a list/tuple of dicts, one per qualified VIP example; "
            f"got {type(examples).__name__}")

    usable, malformed = normalize_examples(examples)
    base = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": evaluated_at,
        "example_count_supplied": len(examples),
        "example_count_valid": len(usable),
        "malformed_examples": malformed,
    }

    if len(usable) < 2:
        return {**base, "status": STATUS_NOT_AVAILABLE, "conditions": {},
                "conflict_count": 0, "composed_scenario": None,
                "reason": "at least two valid, uniquely-identified qualified VIP examples are "
                          f"required to compose a scenario; {len(usable)} valid example(s) "
                          "supplied"}

    conditions: Dict[str, dict] = {}
    conflict_count = 0
    for cond_id in CONDITIONS:
        if cond_id == COND_DUT_TOPOLOGY_APPLICABILITY:
            result = CONDITION_CHECKS[cond_id](usable, dut_topology)
        else:
            result = CONDITION_CHECKS[cond_id](usable)
        result = {"condition": cond_id, "description": CONDITION_DESCRIPTIONS[cond_id], **result}
        conditions[cond_id] = result
        conflict_count += len(result.get("conflicts") or [])

    blocked = conflict_count > 0
    status = STATUS_BLOCKED if blocked else STATUS_COMPOSED
    composed_scenario = None
    if not blocked:
        composed_scenario = {
            "example_ids": [ve.identity for ve in usable],
            "vip_types": sorted({ve.vip_type for ve in usable if ve.vip_type}),
            "protocol_modes": sorted({ve.protocol_mode for ve in usable if ve.protocol_mode}),
        }

    report = {**base, "status": status, "conditions": conditions,
              "conflict_count": conflict_count, "composed_scenario": composed_scenario}
    if blocked:
        blocking = [cid for cid, c in conditions.items() if c["status"] == COND_STATUS_CONFLICT]
        report["reason"] = ("composition BLOCKED: a real conflict was found on "
                            f"{len(blocking)} condition(s): {', '.join(blocking)}")
    return report


# --------------------------------------------------------------------------
# rendering / CLI
# --------------------------------------------------------------------------

def format_composition_report(report: dict) -> str:
    lines = [f"VIP EXAMPLE COMPOSITION: {report.get('status')}"]
    if report.get("reason"):
        lines.append(f"  {report['reason']}")
    lines.append(f"  examples supplied={report.get('example_count_supplied')} "
                 f"valid={report.get('example_count_valid')} "
                 f"malformed={len(report.get('malformed_examples') or [])}")
    for entry in report.get("malformed_examples") or []:
        lines.append(f"    MALFORMED[{entry['index']}] {entry['reason']}")
    for cond_id, c in (report.get("conditions") or {}).items():
        lines.append(f"  [{c['status']}] {cond_id} -- {c['description']}")
        for conflict in c.get("conflicts") or []:
            lines.append(f"      CONFLICT {conflict['pair']} :: {conflict['detail']}")
        if c["status"] == COND_STATUS_NOT_APPLICABLE:
            lines.append(f"      ({c.get('reason')})")
    scenario = report.get("composed_scenario")
    if scenario:
        lines.append(f"  composed_scenario: {scenario}")
    return "\n".join(lines)


_EXIT_BY_STATUS = {
    STATUS_COMPOSED: 0,
    STATUS_BLOCKED: 1,
    STATUS_NOT_AVAILABLE: 2,
}


def execute_verb(examples: Sequence[Any], *, dut_topology: Optional[Any] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.example_composition`.
    Returns (text, exit_code): 0 COMPOSED, 1 BLOCKED, 2 NOT_AVAILABLE / a
    malformed `examples` document. Runs nothing, writes nothing."""
    try:
        report = evaluate_vip_example_composition(examples, dut_topology=dut_topology)
    except CompositionInputError as e:
        return f"CompositionInputError: {e}", 2
    text = _json.dumps(report, indent=2) if as_json else format_composition_report(report)
    return text, _EXIT_BY_STATUS.get(report["status"], 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.example_composition",
        description="Composes multiple qualified VIP examples (a JSON list of dicts) into one "
                    "scenario, validated against an 8-condition composition gate: VIP version, "
                    "role, protocol mode, agent config, sequencer ownership, reset assumptions, "
                    "clock assumptions, and (with --dut-topology) DUT topology applicability. A "
                    "real conflict on any condition BLOCKS composition and names the specific "
                    "conflicting pair -- it never picks a winner.")
    ap.add_argument("verb", choices=("compose",))
    ap.add_argument("--examples", required=True, help="JSON file: a list of example dicts.")
    ap.add_argument("--dut-topology", default=None,
                    help="Optional JSON file: a design_architecture_ir.build_architecture_ir()"
                         "-shaped document, used only for condition 8 (DUT_TOPOLOGY_APPLICABLE). "
                         "Omitted, condition 8 reports NOT_APPLICABLE.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    examples = _json.loads(Path(a.examples).read_text(encoding="utf-8"))
    dut_topology = (_json.loads(Path(a.dut_topology).read_text(encoding="utf-8"))
                    if a.dut_topology else None)
    text, code = execute_verb(examples, dut_topology=dut_topology, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
