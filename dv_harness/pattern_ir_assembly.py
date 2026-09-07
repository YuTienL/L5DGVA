"""dv_harness/pattern_ir_assembly.py -- assemble a PatternIR (the
`global`/`dut`/`fw_policy`/`vip`/`check` command lists that back a
command.txt-shaped pattern) from a generic, duck-typed ScenarioIR-shaped
input, and validate its layer ordering against the KNOWN-safe convention
`.claude/skills/CORE/pattern-architecture/SKILL.md` documents.

WHAT THIS IS, AND WHY IT DOES NOT IMPORT verification_intent_ir.py
--------------------------------------------------------------------
`verification_intent_ir.py` and `vplan_artifact.py` are owned by a
concurrently-running batch and are not imported here (per this batch's file-
safety scope). This module instead accepts ANY plain dict/list whose shape is
"the same general shape a ScenarioIR would produce": a list of items, each
carrying an objective plus stimulus/checker/coverage-intent text (the same
field vocabulary `requirement_contract.py`'s real `RequirementContract`
already uses for `stimulus`/`checker`/`coverage_intent`, which is the closest
existing, tested precedent for that shape in this repo). Every field is read
duck-typed (dict `.get` or attribute access, whichever the caller's object
supports) with a small alias list per field -- never a hard `isinstance` check
against a class this module has no license to import.

Vocabulary mapping to `pattern-architecture`/`branch-mapper`'s real layer
names:

    PatternIR layer   |  pattern-architecture / branch-mapper name
    ------------------+---------------------------------------------
    global            |  `block`        (one-shot chip/SoC-global prologue)
    dut               |  `branch_a*`    (per-port DUT+PHY bring-up)
    fw_policy         |  `branch_fw`    (per-port FW/event service loop)
    vip               |  `branch_b*`    (VIP-driven test body, fork/join)
    check             |  verdict/`` `FINAL_CHECK ``

EVIDENCE TRUTH RULE, APPLIED TO WHAT THIS MODULE WILL NOT INVENT
------------------------------------------------------------------
`block`/`branch_a*`/`branch_fw` content is sourced from real DUT RTL/PHY docs
per `pattern-architecture/SKILL.md` section 5 point 8 -- this module has no
such evidence and therefore never synthesizes it. `global_commands`,
`dut_commands` and `fw_policy_commands` are accepted ONLY as caller-supplied
pass-through content (already evidenced elsewhere); this module merely
places, merges and orders them. The one thing this module DOES derive is the
`vip`/`check` split from a ScenarioIR item's own `stimulus`/`checker`/
`coverage_intent` fields (branch_b* is the VIP-driven test body carrying
stimulus and coverage sampling; the verdict layer is where `checker`/
expected-result content belongs) -- a structural convention, stated as such,
not a fact read off any RTL/VIP source.

Anything this module cannot confidently place -- an item with none of the
three intent fields, a `layer_overrides` entry naming an unrecognized layer,
a caller-supplied command entry with no text, a `declared_order` naming an
unknown layer or omitting/duplicating one -- is reported into `unclassified`
or as an `AMBIGUOUS_DECLARED_ORDER` status, never guessed into a bucket.

ORDERING VALIDATION
--------------------
`DEFAULT_LAYER_ORDER` is `pattern-architecture/SKILL.md` section 4's "stays
fixed in every real instance" ordering: `block` -> `branch_a*` (bring-up,
launched non-blocking) -> `branch_fw` (launched once, never returns) ->
fork/join of `branch_b*` (join, never join_any once branch_fw is its own
branch -- section 2's documented trap, USB job 98520) -> verdict.
`validate_layer_ordering()` compares a project-declared alternate order
against that default and reports named, cited risks for deviations that
match the skill's own load-bearing rules (`block` not first, `branch_fw`
launched after `branch_b*` needs it, verdict placed before `branch_b*`
completes) rather than a single generic "differs" verdict, plus a dedicated,
separately-triggerable `JOIN_ANY_WITH_BRANCH_FW` risk for section 2's trap
regardless of whether the declared order itself matches the default.

FW LAUNCH-TIMING WINDOW, AUDITED AND CLOSED (2026-09-07)
----------------------------------------------------------
Audit finding, confirmed against `pattern-architecture/SKILL.md` section 1
before writing anything here: `FW_POLICY_AFTER_VIP` and the declared-order
check above operate on a single ORDINAL POSITION per layer in a 5-element
list. That granularity can only ever answer "is `fw_policy` positioned
before or after `vip`/`global`/`check`" -- it has no way to represent, and
therefore cannot catch, a `branch_fw` whose launch STATEMENT sits after a
*blocking* `join` on `branch_a*`'s own per-port bring-up rather than
immediately alongside `branch_a*`'s own non-blocking dispatch. Both the
correct pattern (launched concurrently, while bring-up is still in flight)
and the buggy one (launched only once bring-up has fully joined/completed)
read as the identical `dut` -> `fw_policy` ordinal pair, so the coarse check
is structurally blind to this trap -- confirmed as a real, distinct gap
rather than already covered.

The skill's own rule is explicit and load-bearing: `branch_fw` "must be
launched before any branch that could possibly need it" (section 1), backed
by the USB illustration's own stated reason -- "port 0 can attach and need a
responder while port 1's bring-up is still running" (`common/soc_run.svh
:118-124`). A `branch_fw` dispatched only after `branch_a*` joins can never
service that in-flight need; the coarse order check would still report it
clean, since `dut` still precedes `fw_policy` in the ordinal list either
way. `validate_layer_ordering()`'s new, optional `fw_launch_timing` keyword
(closed vocabulary: `FW_TIMING_CONCURRENT_WITH_DUT_START` /
`FW_TIMING_AFTER_DUT_COMPLETION` / `FW_TIMING_UNKNOWN`) is the narrower,
additive check this confirmed gap calls for -- evaluated only when a caller
supplies real evidence about the relative launch timing, never inferred
from the ordinal `declared_order` alone, and never guessed when absent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _dataclass_field

# ===========================================================================
# Canonical layer vocabulary
# ===========================================================================

LAYER_GLOBAL = "global"        # `block`
LAYER_DUT = "dut"              # `branch_a*`
LAYER_FW_POLICY = "fw_policy"  # `branch_fw`
LAYER_VIP = "vip"              # `branch_b*`
LAYER_CHECK = "check"          # verdict / `FINAL_CHECK`

#: `pattern-architecture/SKILL.md` section 4's fixed ordering, verbatim in
#: layer-vocabulary terms. Never reorder this tuple for convenience -- it is
#: the KNOWN-safe baseline `validate_layer_ordering()` compares against.
DEFAULT_LAYER_ORDER: tuple = (
    LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY, LAYER_VIP, LAYER_CHECK,
)

CANONICAL_LAYER_NAMES: frozenset = frozenset(DEFAULT_LAYER_ORDER)

#: Aliases a caller's `declared_order`/`layer_overrides` may reasonably spell
#: a layer as, mapped onto the canonical name above. Deliberately narrow --
#: an unrecognized spelling is reported as AMBIGUOUS/unclassified, never
#: guessed at.
LAYER_ALIASES: dict = {
    "global": LAYER_GLOBAL, "block": LAYER_GLOBAL, "soc_global": LAYER_GLOBAL,
    "prologue": LAYER_GLOBAL,
    "dut": LAYER_DUT, "branch_a": LAYER_DUT, "bringup": LAYER_DUT,
    "bring_up": LAYER_DUT, "init": LAYER_DUT,
    "fw_policy": LAYER_FW_POLICY, "branch_fw": LAYER_FW_POLICY,
    "fw": LAYER_FW_POLICY, "firmware": LAYER_FW_POLICY,
    "service_loop": LAYER_FW_POLICY,
    "vip": LAYER_VIP, "branch_b": LAYER_VIP, "stimulus": LAYER_VIP,
    "traffic": LAYER_VIP,
    "check": LAYER_CHECK, "verdict": LAYER_CHECK, "final_check": LAYER_CHECK,
    "branch_check": LAYER_CHECK,
}

_TRAILING_INDEX = re.compile(r"[_-]?\d+$")


def _canonical_layer(name):
    """Normalize a layer spelling (canonical, alias, or index-suffixed like
    `branch_a0`/`branch_b1`) to one of the five canonical layer names, or
    `None` if unrecognized. Never guesses -- `None` means "report this as
    unclassified/ambiguous", not "assume a default layer"."""
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in CANONICAL_LAYER_NAMES:
        return key
    if key in LAYER_ALIASES:
        return LAYER_ALIASES[key]
    stripped = _TRAILING_INDEX.sub("", key)
    if stripped != key:
        if stripped in CANONICAL_LAYER_NAMES:
            return stripped
        if stripped in LAYER_ALIASES:
            return LAYER_ALIASES[stripped]
    return None


# ===========================================================================
# join / fork vocabulary (pattern-architecture SKILL.md section 2)
# ===========================================================================

JOIN_MODE_JOIN = "join"
JOIN_MODE_JOIN_ANY = "join_any"

# ===========================================================================
# branch_fw-vs-branch_a* relative launch-timing vocabulary
# (pattern-architecture SKILL.md section 1 -- "launched before any branch
# that could possibly need it", i.e. while branch_a* bring-up is still in
# flight, never only after it fully joins/completes). Caller-supplied only
# -- this module has no evidence of its own about a real command.txt's
# fork/join structure and never infers this fact from `declared_order`.
# ===========================================================================

#: branch_fw dispatched non-blocking, concurrently with branch_a*'s own
#: non-blocking bring-up (the documented-correct shape) -- no risk.
FW_TIMING_CONCURRENT_WITH_DUT_START = "concurrent_with_dut_start"
#: branch_fw's launch statement sits after a blocking join on branch_a* --
#: the confirmed trap this check exists to catch.
FW_TIMING_AFTER_DUT_COMPLETION = "after_dut_completion"
#: the caller explicitly does not know the relative timing -- honestly
#: flagged, never silently treated as either safe or unsafe.
FW_TIMING_UNKNOWN = "unknown"

#: The closed set of recognized `fw_launch_timing` values -- anything else
#: supplied is a malformed/unrecognized value, flagged rather than ignored.
FW_LAUNCH_TIMING_VALUES: frozenset = frozenset({
    FW_TIMING_CONCURRENT_WITH_DUT_START,
    FW_TIMING_AFTER_DUT_COMPLETION,
    FW_TIMING_UNKNOWN,
})

# ===========================================================================
# Honest-status sentinels (Evidence Truth Rule)
# ===========================================================================

NOT_AVAILABLE = "NOT_AVAILABLE"
UNKNOWN = "UNKNOWN"

ORDER_STATUS_DEFAULT_ASSUMED = "DEFAULT_ORDER_ASSUMED"
ORDER_STATUS_PASS = "PASS"
ORDER_STATUS_DEVIATION_RISK = "DEVIATION_RISK"
ORDER_STATUS_AMBIGUOUS = "AMBIGUOUS_DECLARED_ORDER"


class PatternIrAssemblyError(ValueError):
    """The `scenario_ir` argument (or a `commands` list nested in it) is not
    duck-typed to any shape this module can reasonably iterate -- e.g. a bare
    scalar, or a dict claiming an items key whose value is not a list. Raised
    rather than silently treated as zero items, per the Evidence Truth Rule:
    "no items found" and "the input's shape could not even be read" are
    different facts."""

    def __init__(self, reason: str, detail: dict | None = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(f"{reason}: {self.detail}")


# ===========================================================================
# Duck-typed field access
# ===========================================================================

def _field(item, *names):
    """Return the first non-empty value found under any of `names`, trying
    dict-style `.get` first (for a dict or any Mapping-shaped duck type) and
    falling back to attribute access -- so a plain dict, a dataclass, or a
    SimpleNamespace-shaped ScenarioIR item are all accepted without importing
    a class from the module that would actually define one. Returns `None`
    (never `""`) when nothing is found, so callers can use a plain truthiness
    check."""
    use_get = hasattr(item, "get") and hasattr(item, "__contains__")
    for name in names:
        if use_get:
            try:
                value = item.get(name)
            except TypeError:
                value = None
        else:
            value = getattr(item, name, None)
        if value not in (None, ""):
            return value
    return None


#: Per-field alias lists for the three ScenarioIR intent fields this module
#: reads. `objective` is descriptive metadata attached to every command entry
#: for traceability, not itself turned into a command.
INTENT_FIELD_ALIASES: dict = {
    "stimulus": ("stimulus_intent", "stimulus_commands"),
    "checker": ("checker_intent", "expected_result"),
    "coverage_intent": ("coverage",),
}

#: The structural convention this module derives the vip/check split from
#: (see module docstring "EVIDENCE TRUTH RULE" section) -- not a fact read off
#: any RTL/VIP source, and overridable per item via `layer_overrides`.
FIELD_TO_DEFAULT_LAYER: dict = {
    "stimulus": LAYER_VIP,
    "checker": LAYER_CHECK,
    "coverage_intent": LAYER_VIP,
}


def _normalize_items(scenario_ir):
    """Return `(items, top_level)`: `items` is a list of duck-typed
    ScenarioIR items, `top_level` is the dict `scenario_ir` itself when it is
    one (used as a fallback source for `global_commands`/`dut_commands`/
    `fw_policy_commands`/`declared_order`/`vip_join_mode` if the caller did
    not pass those as keyword arguments), else `{}`."""
    if scenario_ir is None:
        return [], {}
    if isinstance(scenario_ir, (list, tuple)):
        return list(scenario_ir), {}
    if isinstance(scenario_ir, dict):
        for key in ("items", "scenarios", "scenario_items", "scenario_list"):
            if key in scenario_ir:
                value = scenario_ir[key]
                if isinstance(value, (list, tuple)):
                    return list(value), scenario_ir
                raise PatternIrAssemblyError("SCENARIO_IR_ITEMS_NOT_A_LIST", {
                    "key": key, "type": type(value).__name__})
        # No items key: if the dict itself looks like a single scenario item
        # (carries an intent field directly), treat it as a one-item list.
        if any(k in scenario_ir for k in
               ("objective", "stimulus", "checker", "coverage_intent",
                "intent", "description")):
            return [scenario_ir], scenario_ir
        # A dict with none of the above is pattern-level config only (e.g.
        # just {"global_commands": [...], "declared_order": [...]}) -- zero
        # scenario items, not an error.
        return [], scenario_ir
    raise PatternIrAssemblyError("SCENARIO_IR_SHAPE_UNRECOGNIZED", {
        "type": type(scenario_ir).__name__})


def _process_scenario_item(idx, item, buckets, unclassified):
    item_id = _field(item, "id", "scenario_id", "name") or f"item_{idx}"
    is_duck_typed = (isinstance(item, dict)
                     or (hasattr(item, "get") and hasattr(item, "__contains__"))
                     or hasattr(item, "__dict__"))
    if not is_duck_typed:
        unclassified.append({"item_id": item_id, "reason": "ITEM_NOT_DUCK_TYPED",
                              "raw_type": type(item).__name__})
        return

    objective = _field(item, "objective", "intent", "description")
    port = _field(item, "port", "port_id", "branch_index")

    overrides = _field(item, "layer_overrides", "layer_override")
    if overrides is not None and not isinstance(overrides, dict):
        unclassified.append({"item_id": item_id, "reason": "LAYER_OVERRIDE_MALFORMED",
                              "raw_type": type(overrides).__name__})
        overrides = {}
    overrides = overrides or {}

    found_any = False
    for field_name, aliases in INTENT_FIELD_ALIASES.items():
        value = _field(item, field_name, *aliases)
        if value is None:
            continue
        found_any = True
        raw_override = overrides.get(field_name)
        if raw_override is not None:
            layer = _canonical_layer(raw_override)
            if layer is None:
                unclassified.append({
                    "item_id": item_id, "field": field_name,
                    "reason": "LAYER_OVERRIDE_UNKNOWN_LAYER",
                    "raw_override": raw_override})
                continue
        else:
            layer = FIELD_TO_DEFAULT_LAYER[field_name]
        buckets[layer].append({
            "item_id": item_id, "field": field_name, "text": str(value),
            "layer": layer, "objective": objective, "port": port,
            "source": "scenario_ir",
        })

    if not found_any:
        unclassified.append({"item_id": item_id, "reason": "NO_INTENT_FIELDS_PRESENT"})


def _merge_passthrough_commands(layer, supplied, buckets, unclassified):
    """Merge already-evidenced `global`/`dut`/`fw_policy` command content the
    caller supplies directly. This module never invents content for these
    three layers (see module docstring) -- it only places what is given."""
    if supplied is None:
        return
    if not isinstance(supplied, (list, tuple)):
        unclassified.append({"layer": layer, "reason": "COMMAND_LIST_NOT_A_LIST",
                              "raw_type": type(supplied).__name__})
        return
    for i, entry in enumerate(supplied):
        if isinstance(entry, str):
            if not entry.strip():
                unclassified.append({"layer": layer, "index": i,
                                      "reason": "COMMAND_ENTRY_EMPTY"})
                continue
            buckets[layer].append({"text": entry, "layer": layer,
                                    "source": "caller_supplied"})
            continue
        if isinstance(entry, dict):
            text = entry.get("text") or entry.get("command")
            if not text:
                unclassified.append({"layer": layer, "index": i,
                                      "reason": "COMMAND_ENTRY_MISSING_TEXT"})
                continue
            normalized = dict(entry)
            normalized["text"] = text
            normalized.setdefault("layer", layer)
            normalized.setdefault("source", "caller_supplied")
            buckets[layer].append(normalized)
            continue
        unclassified.append({"layer": layer, "index": i,
                              "reason": "COMMAND_ENTRY_NOT_DUCK_TYPED",
                              "raw_type": type(entry).__name__})


# ===========================================================================
# Ordering validation (pattern-architecture SKILL.md sections 2 and 4)
# ===========================================================================

def validate_layer_ordering(declared_order=None, *, vip_join_mode=None,
                             branch_fw_present=None,
                             fw_launch_timing=None) -> dict:
    """Validate a project-declared layer order against `DEFAULT_LAYER_ORDER`,
    plus the independent join/fork trap from section 2, plus the independent
    branch_fw-vs-branch_a* relative launch-timing window from section 1
    (`fw_launch_timing`, see module docstring "FW LAUNCH-TIMING WINDOW" --
    the coarse ordinal order check above cannot see this: a `branch_fw`
    launched only after a blocking join on `branch_a*` still reads as
    `dut` before `fw_policy` in `declared_order`, identically to the
    documented-correct concurrent-launch case). Returns a dict:

        status        -- one of ORDER_STATUS_DEFAULT_ASSUMED / _PASS /
                          _DEVIATION_RISK / _AMBIGUOUS
        declared_order -- the raw input, echoed back (or None)
        order_used     -- the canonicalized tuple actually validated against
                           DEFAULT_LAYER_ORDER (None when AMBIGUOUS)
        risks          -- list of {"risk": <name>, "detail": <str>} dicts.
                           NOTE: `risks` can be non-empty even when `status`
                           is PASS or DEFAULT_ORDER_ASSUMED -- the join_any
                           trap is independent of layer ordering. Callers
                           must check `risks`, not only `status`.

    Never silently accepts a deviation: any declared order that differs from
    the default gets DEVIATION_RISK plus at least one named risk (falling
    back to a generic, still-named entry if none of the specific checks
    below match, per the Evidence Truth Rule -- "flagged conservatively"
    beats "accepted silently")."""
    risks: list = []

    if declared_order is None:
        status = ORDER_STATUS_DEFAULT_ASSUMED
        order_used = DEFAULT_LAYER_ORDER
    else:
        try:
            raw = list(declared_order)
        except TypeError:
            return {"status": ORDER_STATUS_AMBIGUOUS, "declared_order": declared_order,
                    "order_used": None,
                    "risks": [{"risk": "DECLARED_ORDER_NOT_ITERABLE",
                               "detail": f"type={type(declared_order).__name__}"}]}

        canon = []
        unknown = []
        for name in raw:
            c = _canonical_layer(name)
            if c is None:
                unknown.append(name)
            else:
                canon.append(c)
        if unknown:
            return {"status": ORDER_STATUS_AMBIGUOUS, "declared_order": raw,
                    "order_used": None,
                    "risks": [{"risk": "UNKNOWN_LAYER_NAME_IN_DECLARED_ORDER",
                               "detail": f"unrecognized: {unknown}"}]}
        if len(canon) != len(CANONICAL_LAYER_NAMES) or set(canon) != CANONICAL_LAYER_NAMES:
            return {"status": ORDER_STATUS_AMBIGUOUS, "declared_order": raw,
                    "order_used": None,
                    "risks": [{"risk": "INCOMPLETE_OR_DUPLICATE_DECLARED_ORDER",
                               "detail": f"got {canon}, need exactly one each of "
                                         f"{sorted(CANONICAL_LAYER_NAMES)}"}]}

        order_used = tuple(canon)
        if order_used == DEFAULT_LAYER_ORDER:
            status = ORDER_STATUS_PASS
        else:
            status = ORDER_STATUS_DEVIATION_RISK
            idx = {name: i for i, name in enumerate(order_used)}
            if idx[LAYER_GLOBAL] != 0:
                risks.append({"risk": "GLOBAL_NOT_FIRST",
                              "detail": "block is a one-shot, chip/SoC-global prologue that "
                                        "must run to completion before anything else starts "
                                        "(pattern-architecture SKILL.md section 1) -- a broken "
                                        "register-access path and a broken DUT are otherwise "
                                        "indistinguishable"})
            if idx[LAYER_DUT] < idx[LAYER_GLOBAL]:
                risks.append({"risk": "DUT_BEFORE_GLOBAL",
                              "detail": "branch_a* bring-up depends on block's global init "
                                        "having reached its ready condition first "
                                        "(branch-mapper SKILL.md 'Initialization Task "
                                        "Hierarchy' point 3)"})
            if idx[LAYER_FW_POLICY] > idx[LAYER_VIP]:
                risks.append({"risk": "FW_POLICY_AFTER_VIP",
                              "detail": "branch_fw must be launched before any branch_b* "
                                        "that could possibly need it (pattern-architecture "
                                        "SKILL.md section 1, 'launched before any branch that "
                                        "could possibly need it')"})
            if idx[LAYER_CHECK] < idx[LAYER_VIP]:
                risks.append({"risk": "CHECK_BEFORE_VIP",
                              "detail": "verdict must run only after every branch_b* has "
                                        "genuinely completed via join (pattern-architecture "
                                        "SKILL.md section 1 and section 2)"})
            if not risks:
                risks.append({"risk": "LAYER_ORDER_DEVIATION_UNCLASSIFIED",
                              "detail": f"declared order {order_used} differs from the "
                                        f"KNOWN-safe default {DEFAULT_LAYER_ORDER} in a way "
                                        f"not matched by a specific check above; flagged "
                                        f"conservatively rather than accepted silently"})

    if vip_join_mode is not None:
        jm = str(vip_join_mode).strip().lower()
        if jm not in (JOIN_MODE_JOIN, JOIN_MODE_JOIN_ANY):
            risks.append({"risk": "JOIN_MODE_UNRECOGNIZED",
                          "detail": f"got {vip_join_mode!r}, expected "
                                    f"'{JOIN_MODE_JOIN}' or '{JOIN_MODE_JOIN_ANY}'"})
        elif jm == JOIN_MODE_JOIN_ANY:
            if branch_fw_present is None:
                risks.append({"risk": "JOIN_ANY_BRANCH_FW_PRESENCE_UNKNOWN",
                              "detail": "join_any was declared for the branch_b* fork but "
                                        "whether branch_fw exists as its own branch is "
                                        f"{UNKNOWN} -- cannot clear or confirm the section-2 "
                                        "trap without that fact"})
            elif branch_fw_present:
                risks.append({"risk": "JOIN_ANY_WITH_BRANCH_FW",
                              "detail": "join_any on the branch_b* fork was only ever safe "
                                        "because branch_a* ended in a forever loop and never "
                                        "finished; once firmware/event-service is its own "
                                        "branch_fw, branch_a* completes on its own and "
                                        "join_any would end the pattern at the first "
                                        "branch_b* to finish (pattern-architecture SKILL.md "
                                        "section 2, citing USB job 98520: '0 UVM_ERROR and no "
                                        "SvtTestEpilog, which reads exactly like a pass')"})
            else:
                risks.append({"risk": "JOIN_ANY_REQUIRES_JUSTIFICATION",
                              "detail": "join_any always requires an explicit, written "
                                        "justification that is revisited whenever the fork's "
                                        "composition changes (pattern-architecture SKILL.md "
                                        "section 2), even with branch_fw absent"})

    if fw_launch_timing is not None:
        timing = str(fw_launch_timing).strip().lower()
        if branch_fw_present is False:
            risks.append({"risk": "FW_LAUNCH_TIMING_CONTRADICTS_ABSENT_BRANCH_FW",
                          "detail": f"fw_launch_timing={fw_launch_timing!r} was declared but "
                                    "branch_fw_present=False says no branch_fw branch exists to "
                                    "have a launch timing at all -- flagged as a contradiction "
                                    "between two caller-supplied facts rather than one silently "
                                    "overriding the other"})
        elif timing == FW_TIMING_AFTER_DUT_COMPLETION:
            risks.append({"risk": "FW_LAUNCHED_AFTER_DUT_COMPLETION",
                          "detail": "branch_fw must be launched non-blocking while branch_a* "
                                    "bring-up is still in flight, not only after branch_a* "
                                    "fully joins/completes (pattern-architecture SKILL.md "
                                    "section 1, 'launched before any branch that could possibly "
                                    "need it'; USB illustration: 'port 0 can attach and need a "
                                    "responder while port 1's bring-up is still running', "
                                    "common/soc_run.svh:118-124) -- a narrower, distinct trap "
                                    "from FW_POLICY_AFTER_VIP above: the five-layer ordinal "
                                    "declared_order alone cannot see a blocking join placed "
                                    "between branch_a*'s own non-blocking dispatch and "
                                    "branch_fw's launch statement, since both still read as "
                                    "'dut before fw_policy' at that granularity"})
        elif timing == FW_TIMING_UNKNOWN:
            risks.append({"risk": "FW_LAUNCH_TIMING_UNKNOWN",
                          "detail": "whether branch_fw launches while branch_a* bring-up is "
                                    f"still in flight or only after it completes is {UNKNOWN} "
                                    "-- cannot confirm or rule out the section-1 timing trap "
                                    "without that fact"})
        elif timing != FW_TIMING_CONCURRENT_WITH_DUT_START:
            risks.append({"risk": "FW_LAUNCH_TIMING_UNRECOGNIZED_VALUE",
                          "detail": f"got fw_launch_timing={fw_launch_timing!r}, expected one "
                                    f"of {sorted(FW_LAUNCH_TIMING_VALUES)} -- flagged "
                                    "conservatively rather than silently ignored"})

    return {"status": status, "declared_order": declared_order,
            "order_used": order_used, "risks": risks}


# ===========================================================================
# PatternIR
# ===========================================================================

@dataclass
class PatternIR:
    global_commands: list = _dataclass_field(default_factory=list)
    dut_commands: list = _dataclass_field(default_factory=list)
    fw_policy_commands: list = _dataclass_field(default_factory=list)
    vip_commands: list = _dataclass_field(default_factory=list)
    check_commands: list = _dataclass_field(default_factory=list)
    ordering: dict = _dataclass_field(default_factory=dict)
    unclassified: list = _dataclass_field(default_factory=list)
    #: True/False when this call could determine it, else None (UNKNOWN) --
    #: see `assemble_pattern_ir`'s resolution rule below.
    branch_fw_present: object = None

    @property
    def ordering_status(self) -> str:
        return self.ordering.get("status", UNKNOWN)

    @property
    def ordering_risks(self) -> list:
        return list(self.ordering.get("risks", []))

    @property
    def command_counts(self) -> dict:
        return {
            LAYER_GLOBAL: len(self.global_commands),
            LAYER_DUT: len(self.dut_commands),
            LAYER_FW_POLICY: len(self.fw_policy_commands),
            LAYER_VIP: len(self.vip_commands),
            LAYER_CHECK: len(self.check_commands),
        }

    def as_dict(self) -> dict:
        return {
            "global_commands": list(self.global_commands),
            "dut_commands": list(self.dut_commands),
            "fw_policy_commands": list(self.fw_policy_commands),
            "vip_commands": list(self.vip_commands),
            "check_commands": list(self.check_commands),
            "ordering": dict(self.ordering),
            "unclassified": list(self.unclassified),
            "branch_fw_present": (self.branch_fw_present
                                  if self.branch_fw_present is not None else UNKNOWN),
            "command_counts": self.command_counts,
        }


def assemble_pattern_ir(scenario_ir, *, global_commands=None, dut_commands=None,
                         fw_policy_commands=None, declared_order=None,
                         vip_join_mode=None, branch_fw_present=None,
                         fw_launch_timing=None) -> PatternIR:
    """Assemble a `PatternIR` from a generic, duck-typed ScenarioIR-shaped
    `scenario_ir` (a list of items, or a dict carrying an `items`/
    `scenarios`/`scenario_items`/`scenario_list` key, or a single item dict).

    `global_commands`/`dut_commands`/`fw_policy_commands` are optional,
    already-evidenced pass-through command lists for the three layers this
    module never invents content for (see module docstring); if omitted here
    they are also looked up as same-named top-level keys on `scenario_ir`
    when it is a dict, so a single config dict can carry both the scenario
    items and the pattern-level layer content. `declared_order`,
    `vip_join_mode` and `fw_launch_timing` (the branch_fw-vs-branch_a*
    relative launch-timing window, see module docstring) all follow the
    same fallback rule.

    Raises `PatternIrAssemblyError` only when `scenario_ir` itself (or a
    declared items list inside it) is not iterable to a list of items --
    never for a merely-ambiguous individual item, which instead lands in the
    returned `PatternIR.unclassified`.
    """
    items, top = _normalize_items(scenario_ir)

    if global_commands is None and isinstance(top, dict):
        global_commands = top.get("global_commands")
    if dut_commands is None and isinstance(top, dict):
        dut_commands = top.get("dut_commands")
    if fw_policy_commands is None and isinstance(top, dict):
        fw_policy_commands = top.get("fw_policy_commands")
    if declared_order is None and isinstance(top, dict):
        declared_order = top.get("declared_order")
    if vip_join_mode is None and isinstance(top, dict):
        vip_join_mode = top.get("vip_join_mode")
    if branch_fw_present is None and isinstance(top, dict) and "branch_fw_present" in top:
        branch_fw_present = top.get("branch_fw_present")
    if fw_launch_timing is None and isinstance(top, dict):
        fw_launch_timing = top.get("fw_launch_timing")

    buckets = {LAYER_GLOBAL: [], LAYER_DUT: [], LAYER_FW_POLICY: [],
               LAYER_VIP: [], LAYER_CHECK: []}
    unclassified: list = []

    for idx, item in enumerate(items):
        _process_scenario_item(idx, item, buckets, unclassified)

    for layer, supplied in ((LAYER_GLOBAL, global_commands),
                            (LAYER_DUT, dut_commands),
                            (LAYER_FW_POLICY, fw_policy_commands)):
        _merge_passthrough_commands(layer, supplied, buckets, unclassified)

    if branch_fw_present is None:
        if fw_policy_commands is not None or buckets[LAYER_FW_POLICY]:
            branch_fw_present = True
        # else stays None -> UNKNOWN; validate_layer_ordering treats that
        # honestly rather than assuming either safe or unsafe.

    ordering = validate_layer_ordering(declared_order, vip_join_mode=vip_join_mode,
                                       branch_fw_present=branch_fw_present,
                                       fw_launch_timing=fw_launch_timing)

    return PatternIR(
        global_commands=buckets[LAYER_GLOBAL],
        dut_commands=buckets[LAYER_DUT],
        fw_policy_commands=buckets[LAYER_FW_POLICY],
        vip_commands=buckets[LAYER_VIP],
        check_commands=buckets[LAYER_CHECK],
        ordering=ordering,
        unclassified=unclassified,
        branch_fw_present=branch_fw_present,
    )
