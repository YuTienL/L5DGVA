"""dv_harness/connectivity.py -- bind-location / VIP-connectivity /
checker-scoreboard planning system (2026-09-03, "mcp-bind-connectivity"
workstream; user's own emphasis: "尤其是bind location，和VIP種類和數量所對應的
DUT instance hierarchy path及checker，scoreboard作法分析後的規劃建議和確認").

This module builds a CONNECTIVITY MANIFEST from four real inputs -- never
guessed -- classifies every bind-path match into a 4-tier confidence system,
runs three machine gates before any plan reaches a human, and generates a
checker/scoreboard PLANNING table (a plan a human reviews and confirms, not
an implementation). See `.work/mcp-bind-connectivity-report.md` for the full
real-vs-NOT_AVAILABLE inventory this session confirmed live.

Coordination note (explicit, not silently resolved): the env.manifest.json
workstream (Part A/B of the same user spec, running concurrently) also
consumes a `uvm_top.print_topology()` / `+UVM_CONFIG_DB_TRACE` capture for
its own env-layer topology section. This module's `parse_topology_dump()`/
`parse_config_db_trace()` below were built independently against the
DOCUMENTED shape of those two real UVM mechanisms (see each function's own
docstring for the exact shape assumed) -- NOT against that sibling
workstream's own file, which this module never imports. A reconciliation
pass across both workstreams' capture-shape assumptions is expected and is
flagged in the report rather than guessed away here.

Four real inputs (Part C):
1. DUT instance tree       -> capture_dut_instance_tree(), via EITHER
                              parse_slang_ast_json() (`slang --ast-json`) OR
                              parse_scope_tree_dump() (`simv -ucli -do
                              "scope -tree"`) -- both alternatives implemented,
                              neither assumed equivalent to the other
2. Interface signal sets   -> build_interface_fingerprints() (extends verible_parser.py)
3. Existing binds          -> grep_existing_binds()
4. VIP instances/config_db -> parse_topology_dump() / parse_config_db_trace()

Everything in this module that depends on a live simv, a licensed VCS
install, or a `slang` binary is explicitly marked NOT_AVAILABLE in this
environment (confirmed: no `slang`, no `vcs`, no live simulation database
here -- `verible-verilog-syntax` IS real and present, and is reused, not
re-implemented, via `dv_harness.verible_parser`) rather than fabricated.
Every NOT_AVAILABLE path still carries its real logic plus a synthetic
fixture proving that logic is correct, and documents the live-integration
point honestly rather than pretending it already works.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from . import verible_parser

# ---------------------------------------------------------------------------
# Shared constants / sentinels
# ---------------------------------------------------------------------------

#: Sentinel value for a checker/scoreboard planning field that Part C
#: explicitly forbids the agent from ever guessing a default for. A generator
#: function may only replace this with a human-supplied value passed in by
#: the caller -- it must never compute one itself. Kept as a plain, greppable
#: string (not `None`) so a planning-table JSON dump makes an unfilled field
#: visually obvious to a human reviewer.
#:
#: As of 2026-09-04 this covers ALL of the scoreboard planning table's
#: required fields, not only ORDERING/LEGAL_DROP: an omitted
#: `transformation_rules` used to resolve to `[]`, which READS AS the
#: positive assertion "this path performs no width conversion, no
#: packetization and no byte-enable remapping" -- a claim no generator can
#: derive and the single most common source of a scoreboard that compares
#: two differently-shaped payloads and passes anyway. Empty
#: `endpoint_pairs`/`matching_key` were likewise accepted silently. Both now
#: resolve to this sentinel. See `SCOREBOARD_PLAN_FIELDS` and
#: `unfilled_plan_fields()`.
REQUIRED_HUMAN_INPUT = "REQUIRED_HUMAN_INPUT"


class ConnectivityError(ValueError):
    """Base class for every hard-fail error this module raises. Matches the
    house convention already established by
    `uvm_generator.bind_mechanism_generator.BindTopologyError` and
    `uvm_generator.amba_fabric_generator.AddressMapError`: `.reason` is a
    short machine-matchable code, `.detail` is a dict of the exact evidence
    that triggered it."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class ConnectivitySelfCheckError(ConnectivityError):
    """The hard self-check identity
    (sum(verified interfaces) == sum(VIP instances) + sum(exemptions))
    failed. Part C is explicit this must FAIL LOUDLY, never degrade to a
    warning -- this is a real exception, not a bool return."""


class BindTierError(ConnectivityError):
    """A tier-classification input was internally inconsistent (e.g. a T3
    naming-only candidate was asked to be marked auto-acceptable) -- guards
    against a caller silently overriding the "T3 never auto-accepted" rule
    at a call site instead of through this module's own classifier."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(obj: Any) -> str:
    """Stable hash of a JSON-serializable object, used by the row-lock
    diff mechanism to detect whether a row's content actually changed."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ===========================================================================
# 4-tier bind-decision-provenance system (Part C)
#
# Named "confidence" in Part C's own prose, but it is NOT
# dv_harness.inference.score_confidence()'s HIGH/MEDIUM/LOW confidence and is
# deliberately not expressed through it (2026-09-04). These four tiers rank
# where a bind decision CAME FROM, in strict priority order, and that ordering
# is not a function of any evidence count: one already-existing bind (T1)
# outranks a structural fingerprint match on several signals (T2) because of
# the source, not the quantity. score_confidence() counts quantity, so it
# scores both at MEDIUM and cannot express T1 > T2 at all. See inference.py's
# module docstring for the full rationale and
# dv_harness_tests/test_confidence_vocabulary_separation.py, which keeps the
# two vocabularies token-disjoint.
# ===========================================================================

class BindTier(str, Enum):
    T1_ALREADY_DECIDED = "T1_ALREADY_DECIDED"          # existing bind / config_db entry found -- accept as-is
    T2_STRUCTURAL_MATCH = "T2_STRUCTURAL_MATCH"        # protocol-fingerprint match -- auto-acceptable, still listed
    T3_NAMING_HEURISTIC = "T3_NAMING_HEURISTIC"        # name-only match -- ALWAYS requires human confirmation
    T4_UNDECIDABLE = "T4_UNDECIDABLE"                  # goes to the question queue


@dataclass
class BindTierResult:
    tier: BindTier
    rationale: str
    auto_acceptable: bool
    requires_human_confirmation: bool
    requires_question_queue_entry: bool


def classify_bind_tier(
    *,
    existing_bind: Optional[dict] = None,
    structural_match: Optional[dict] = None,
    naming_match: Optional[str] = None,
) -> BindTierResult:
    """The 4-tier classifier, exactly as Part C defines it. Evaluated in
    strict priority order T1 > T2 > T3 > T4 -- a candidate that happens to
    have BOTH a naming match and a structural match is T2 (the structural
    evidence outranks the naming heuristic), never silently upgraded to a
    non-existent "T1.5". `existing_bind`/`structural_match` are dicts of
    real evidence (a parsed `BindStatement`-shaped dict, or a
    `match_protocol_fingerprint()` result) -- this function classifies, it
    never re-derives that evidence itself.

    T3 is HARD-CODED as `auto_acceptable=False`, `requires_human_confirmation
    =True` with no parameter anywhere in this signature that can flip it --
    "ALWAYS requires human confirmation, NEVER auto-accepted" per Part C,
    even for a naming match that looks unambiguous (e.g. `u_usb3_top`)."""
    if existing_bind:
        target = existing_bind.get("target") or existing_bind.get("target_instance") or "?"
        return BindTierResult(
            tier=BindTier.T1_ALREADY_DECIDED,
            rationale=f"already-decided: existing bind/config_db evidence found at {target!r} -- accepted as-is, no re-litigation.",
            auto_acceptable=True,
            requires_human_confirmation=False,
            requires_question_queue_entry=False,
        )
    if structural_match and structural_match.get("matched"):
        proto = structural_match.get("protocol", "?")
        matched_sigs = structural_match.get("matched_signals", [])
        return BindTierResult(
            tier=BindTier.T2_STRUCTURAL_MATCH,
            rationale=(
                f"structural protocol-fingerprint match for {proto!r}: "
                f"{sorted(matched_sigs)} present. High-confidence, auto-acceptable, "
                f"but still listed in the report for visibility."
            ),
            auto_acceptable=True,
            requires_human_confirmation=False,
            requires_question_queue_entry=False,
        )
    if naming_match:
        return BindTierResult(
            tier=BindTier.T3_NAMING_HEURISTIC,
            rationale=(
                f"naming-heuristic-only match on {naming_match!r} -- no structural "
                f"corroboration. Flagged as the most error-prone tier (multi-instance "
                f"IP, generate-block paths, inconsistent wrapper depth); ALWAYS "
                f"requires human confirmation, never auto-accepted."
            ),
            auto_acceptable=False,
            requires_human_confirmation=True,
            requires_question_queue_entry=False,
        )
    return BindTierResult(
        tier=BindTier.T4_UNDECIDABLE,
        rationale="undecidable from DUT tree, interface fingerprint, existing binds, or VIP/config_db trace -- routed to the question queue, never guessed.",
        auto_acceptable=False,
        requires_human_confirmation=False,
        requires_question_queue_entry=True,
    )


def assert_t3_never_auto_accepted(result: BindTierResult) -> None:
    """Defense-in-depth regression guard: raises BindTierError if a T3
    result is ever found marked auto-acceptable, regardless of how it was
    constructed. Intended to be called by any downstream consumer (e.g. a
    "generate bind_entries for auto-acceptable rows" step) right before it
    would act on a tier result, so a future refactor that accidentally lets
    T3 slip through fails immediately and loudly rather than silently
    emitting an unconfirmed bind."""
    if result.tier == BindTier.T3_NAMING_HEURISTIC and (
        result.auto_acceptable or not result.requires_human_confirmation
    ):
        raise BindTierError(
            "T3_MUST_NEVER_AUTO_ACCEPT",
            {"tier": result.tier.value, "auto_acceptable": result.auto_acceptable,
             "requires_human_confirmation": result.requires_human_confirmation},
        )


#: The only two tiers whose `bind` statement a generator may emit with no
#: human sign-off. T3 needs a real human confirmation; T4 must never be
#: emitted at all (it belongs in the question queue).
AUTO_EMITTABLE_TIERS = frozenset({BindTier.T1_ALREADY_DECIDED, BindTier.T2_STRUCTURAL_MATCH})

#: Tier recorded for a bind entry that was never run through
#: classify_bind_tier(). A real, greppable value rather than a silent `None`
#: so a legacy topology JSON reads as visibly UNCLASSIFIED in the policy
#: decision list instead of merely absent from it.
BIND_TIER_UNCLASSIFIED = "UNCLASSIFIED"


def _t3_human_confirmation_is_real(entry: dict) -> bool:
    """A T3 bind entry may only be emitted once a REAL human confirmed it.
    Reuses `question_queue.HUMAN_DECISION_SOURCE` -- the single sanctioned
    decision source that module already uses to stop the harness answering
    its own Tier-3 escalation with its own earlier guess -- rather than
    inventing a second, parallel notion of "confirmed" here."""
    from . import question_queue  # local import, same convention as
                                  # build_t4_question_queue_entry() below
    conf = entry.get("human_confirmation")
    if not isinstance(conf, dict):
        return False
    if conf.get("source") != question_queue.HUMAN_DECISION_SOURCE:
        return False
    return bool(conf.get("confirmed_by")) and bool(conf.get("basis"))


def assert_bind_entry_tier_allows_emission(
    entry: dict, *, index: int = 0, require_tier: bool = False,
) -> str:
    """Hard tier gate for ONE bind entry, called right before a generator
    would emit its `bind` statement. This is the "downstream consumer"
    `assert_t3_never_auto_accepted()`'s own docstring names and which did not
    previously exist anywhere in this repo -- without it, the real emission
    path (`uvm_generator.bind_mechanism_generator.emit_bind_sv`, driven by
    `tools/generate_bind_mechanism.py`) would write a naming-heuristic-only
    bind into a `.sv` file with no human ever confirming it.

    Returns the entry's tier value (`BIND_TIER_UNCLASSIFIED` when absent and
    `require_tier` is False). Raises `BindTierError` for every case Part C
    says must never reach a generated bind file:
      * T4 -> never emittable; it belongs in the question queue
        (`build_t4_question_queue_entry()`), not in a bind file.
      * T3 -> emittable ONLY with a real human confirmation, per "ALWAYS
        requires human confirmation, NEVER auto-accepted".
      * an unrecognized tier string -> never silently treated as safe.
      * a missing tier, when `require_tier=True`.

    `require_tier` defaults to False so the existing 3-field bind-entry
    contract (`target_instance`/`ports`/`reason`, documented in every
    PROTOCOL_BUILDERS skill and used by the real
    `examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json`)
    keeps working unchanged. That is a deliberate, disclosed residual: an
    entry carrying NO tier is still emittable. What this gate closes hard is
    the dangerous case -- an entry the pipeline already classified as
    unconfirmed (T3) or undecidable (T4) being emitted anyway."""
    raw = entry.get("tier")
    if raw is None or raw == "":
        if require_tier:
            raise BindTierError("BIND_ENTRY_MISSING_TIER", {
                "index": index, "target_instance": entry.get("target_instance"),
                "hint": "run classify_bind_tier() on the candidate and record its tier on the bind entry",
            })
        return BIND_TIER_UNCLASSIFIED

    value = raw.value if isinstance(raw, BindTier) else str(raw)
    try:
        tier = BindTier(value)
    except ValueError:
        raise BindTierError("BIND_ENTRY_UNKNOWN_TIER", {
            "index": index, "target_instance": entry.get("target_instance"),
            "tier": value, "known_tiers": [t.value for t in BindTier],
        }) from None

    if tier is BindTier.T4_UNDECIDABLE:
        raise BindTierError("T4_BIND_MUST_GO_TO_QUESTION_QUEUE", {
            "index": index, "target_instance": entry.get("target_instance"),
            "tier": tier.value,
        })

    if tier is BindTier.T3_NAMING_HEURISTIC:
        # Defense in depth: re-run the standalone guard against a result
        # rebuilt from this entry's OWN claimed flags, so an entry that
        # hand-writes `auto_acceptable: true` is caught by the very function
        # the "T3 never auto-accepted" rule was written into.
        assert_t3_never_auto_accepted(BindTierResult(
            tier=tier,
            rationale="rebuilt from bind entry for emission-time re-check",
            auto_acceptable=bool(entry.get("auto_acceptable", False)),
            requires_human_confirmation=bool(entry.get("requires_human_confirmation", True)),
            requires_question_queue_entry=False,
        ))
        if not _t3_human_confirmation_is_real(entry):
            raise BindTierError("T3_BIND_REQUIRES_HUMAN_CONFIRMATION", {
                "index": index, "target_instance": entry.get("target_instance"),
                "tier": tier.value,
                "required_shape": {"human_confirmation": {
                    "source": "human_answer", "confirmed_by": "<who>", "basis": "<why>"}},
            })
    return tier.value


def enforce_bind_tier_policy(bind_entries: list, *, require_tier: bool = False) -> list[dict]:
    """Whole-list form of `assert_bind_entry_tier_allows_emission()`. Raises
    on the FIRST offending entry (so nothing is emitted from a list that
    contains even one unconfirmed T3 or any T4), otherwise returns one
    decision record per entry for a report/audit trail."""
    decisions = []
    auto_ok = {t.value for t in AUTO_EMITTABLE_TIERS}
    for i, entry in enumerate(bind_entries or []):
        tier = assert_bind_entry_tier_allows_emission(entry, index=i, require_tier=require_tier)
        decisions.append({
            "index": i,
            "target_instance": entry.get("target_instance"),
            "tier": tier,
            "auto_emittable": tier in auto_ok,
            "human_confirmed": tier == BindTier.T3_NAMING_HEURISTIC.value,
        })
    return decisions


# ===========================================================================
# Input 1: DUT instance tree -- two independent capture methods, EITHER of
# which produces the same DutInstanceNode tree:
#   (a) `slang --ast-json`            -> parse_slang_ast_json()
#   (b) `simv -ucli -do "scope -tree"` -> parse_scope_tree_dump()
# Both are implemented so the input is not single-tool-dependent: neither
# `slang` nor `simv` is on PATH in this environment (confirmed live
# 2026-09-03 via `which slang` / `which simv` / `which vcs`, all exit 1), so
# method (a) alone would leave this input with no usable code path at any
# site that has VCS but not slang -- the common case for a real DV team.
# ===========================================================================

DEFAULT_SLANG_BIN = "slang"
DEFAULT_SIMV_BIN = "simv"


def check_slang_available(which_fn: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """Real availability check -- confirmed this session via `which slang`:
    NOT on PATH in this environment. Returns the resolved path if present,
    else None. Kept as a real function (not a hardcoded False) so it goes
    live automatically the moment slang is installed, with no code change
    needed here."""
    return which_fn(DEFAULT_SLANG_BIN)


def check_simv_available(which_fn: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """Availability check for capture method (b)'s binary, the same real
    (not hardcoded) shape as `check_slang_available()`. Confirmed this
    session via `which simv`: NOT on PATH here. Note a real project's `simv`
    is usually a build-local executable rather than a PATH entry, so a
    caller that already knows its own build directory should pass that
    binary's path directly rather than relying on this PATH probe."""
    return which_fn(DEFAULT_SIMV_BIN)


@dataclass
class DutInstanceNode:
    instance_name: Optional[str]
    module_name: Optional[str]
    full_path: str
    children: list = field(default_factory=list)  # list[DutInstanceNode]


def parse_slang_ast_json(ast: dict) -> DutInstanceNode:
    """Parses slang's own documented `--ast-json` instance-tree shape:
    an `InstanceSymbol` node carries `"kind": "Instance"`, `"name"`
    (instance name), `"body"` -> `{"name": <module/definition name>, ...}`,
    and a `"members"` list of child symbol nodes (only the `"kind" ==
    "Instance"` members are structurally relevant here; other member kinds
    -- ports, variables, procedural blocks -- are outside this function's
    scope, matching `verible_parser.py`'s own module/port/signal-only
    scoping precedent).

    HONESTY NOTE: this node-shape contract is built from slang's own public
    `--ast-json` documentation, NOT verified against a live slang run in
    this environment -- `check_slang_available()` confirms slang is not on
    PATH here. `capture_dut_instance_tree()` below is the honest
    NOT_AVAILABLE entry point; this parser exists and is unit-tested against
    a synthetic fixture built to that same documented shape, so it is real,
    tested code ready the moment a live slang install is used to feed it
    real `--ast-json` output -- but that live confirmation itself is the
    NOT_AVAILABLE-by-honest-design item, not this parsing logic."""
    def _walk(node: dict, parent_path: str) -> DutInstanceNode:
        inst_name = node.get("name") or ""
        body = node.get("body") or {}
        module_name = body.get("name") or node.get("type")
        full_path = f"{parent_path}.{inst_name}" if parent_path else inst_name
        children = []
        for member in (body.get("members") or node.get("members") or []):
            if isinstance(member, dict) and member.get("kind") == "Instance":
                children.append(_walk(member, full_path))
        return DutInstanceNode(instance_name=inst_name or None, module_name=module_name,
                                full_path=full_path, children=children)
    return _walk(ast, "")


def flatten_instance_tree(node: DutInstanceNode) -> list[DutInstanceNode]:
    """Depth-first flattening of either capture method's tree into the flat
    `full_path` list the bind-target/tier logic actually consumes. Shared by
    both methods so a caller never has to know which one produced the tree."""
    out = [node]
    for child in node.children:
        out.extend(flatten_instance_tree(child))
    return out


@dataclass
class ScopeTreeParseResult:
    """Result of parsing one `scope -tree` capture. `unparsed_lines` is the
    fail-closed half: every non-blank line the parser did NOT recognize is
    reported rather than silently dropped, because a silently-dropped line
    is a silently-missing bind target -- exactly the failure mode Rule 1
    ("SoC-level work must always bind by full instance path") depends on not
    happening."""
    roots: list = field(default_factory=list)          # list[DutInstanceNode]
    unparsed_lines: list = field(default_factory=list)  # list[tuple[int, str]]
    parsed_node_count: int = 0


#: Lines a real UCLI capture carries around the actual tree that are NOT
#: hierarchy rows: the `ucli%` prompt (with or without the echoed command),
#: pure ASCII rules, and the VCS/simv startup banner lines. Deliberately
#: NARROW -- anything else unrecognized goes to `unparsed_lines` instead of
#: being quietly discarded.
_SCOPE_TREE_IGNORE_RE = re.compile(
    r"^\s*(?:ucli%.*|[-=_]{3,}|Chronologic VCS.*|Copyright \(c\).*|"
    r"Compiler version.*|Runtime version.*|\$?finish.*|V C S .*)\s*$",
    re.IGNORECASE,
)

#: One hierarchy row of a `scope -tree` capture. Leading indentation may be
#: plain spaces or the ASCII tree glyphs some UCLI builds draw (`|`, `+`,
#: `` ` ``, `-`); both are treated purely as indentation, and the NESTING
#: DEPTH is taken from the column the name starts at, never guessed from the
#: name text. Backslash is deliberately EXCLUDED from the indent class even
#: though a UCLI variant may draw with it: `\` also begins a SystemVerilog
#: escaped identifier (`\u_phy[0] `), and letting it count as indentation
#: would silently shift such a row one level shallower -- a corrupted
#: hierarchy is worse than a row that lands in `unparsed_lines` and shows up
#: as REAL_PARTIAL. The optional trailing module/definition name is accepted
#: in the three annotation forms seen across UCLI builds: `name (module)`,
#: `name {module}`, and `name : module`; a row with no annotation yields
#: `module_name=None` (honest unknown, never back-filled from the instance
#: name).
_SCOPE_TREE_ROW_RE = re.compile(
    r"^(?P<indent>[\s|`+-]*)"
    r"(?P<name>[A-Za-z_$\\][\w$.\[\]]*)"
    r"(?:\s*[({]\s*(?P<type_paren>[\w$]+)\s*[)}]"
    r"|\s*:\s*(?P<type_colon>[\w$]+)"
    r"|\s{2,}(?P<type_col>[\w$]+))?"
    r"\s*$"
)


def parse_scope_tree_dump(text: str) -> ScopeTreeParseResult:
    """Capture method (b): parses a `simv -ucli -do "scope -tree"` hierarchy
    dump into the SAME `DutInstanceNode` tree `parse_slang_ast_json()`
    produces, so the two methods are genuinely interchangeable at every
    downstream call site rather than one being a docstring-only promise.

    Shape parsed (indent-nested, one instance per line, module/definition
    name optional)::

        tb_top
          dut (chip_top)
            usb0 (usb3_subsystem)
              phy (usb3_phy)

    Nesting comes from each row's own start column (ASCII tree glyphs count
    as indentation), matching `parse_topology_dump()`'s already-proven
    parent-stack approach. Multiple roots are supported -- a real UCLI dump
    commonly lists `$unit`/`$root` alongside the testbench top -- so
    `roots` is a list, not a single node.

    HONESTY NOTE (the same caveat `parse_slang_ast_json()` carries, and for
    the same reason): the exact text UCLI emits varies by VCS version and is
    NOT verified against a live simv here -- `check_simv_available()`
    confirms no simv on PATH in this environment. That uncertainty is the
    precise reason this parser is FAIL-CLOSED rather than tolerant: an
    unrecognized line is recorded in `unparsed_lines` and surfaces as a
    `REAL_PARTIAL`/`PARSE_FAILED` status from `capture_dut_instance_tree()`,
    so a real format mismatch shows up as a visibly incomplete hierarchy
    instead of a confident-looking tree that is quietly missing the very
    instance a bind was going to target."""
    result = ScopeTreeParseResult()
    stack: list[tuple[int, DutInstanceNode]] = []  # (indent_col, node)
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or _SCOPE_TREE_IGNORE_RE.match(line):
            continue
        m = _SCOPE_TREE_ROW_RE.match(line)
        if not m:
            result.unparsed_lines.append((line_no, line.rstrip()))
            continue
        indent_col = len(m.group("indent"))
        name = m.group("name")
        module_name = m.group("type_paren") or m.group("type_colon") or m.group("type_col")
        while stack and stack[-1][0] >= indent_col:
            stack.pop()
        parent = stack[-1][1] if stack else None
        # A name that already carries dots is an ABSOLUTE path -- some UCLI
        # builds emit a flat `scope -tree` listing of full paths rather than
        # an indent-nested one. Prepending a parent to it would produce a
        # doubled, non-existent hierarchy path, so it is taken as-is.
        if "." in name:
            full_path = name
        else:
            full_path = f"{parent.full_path}.{name}" if parent else name
        node = DutInstanceNode(instance_name=name, module_name=module_name,
                                full_path=full_path, children=[])
        if parent is not None:
            parent.children.append(node)
        else:
            result.roots.append(node)
        stack.append((indent_col, node))
        result.parsed_node_count += 1
    return result


def capture_dut_instance_tree(
    ast_json_path: Optional[str] = None,
    slang_bin: str = DEFAULT_SLANG_BIN,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    scope_tree_path: Optional[str] = None,
) -> dict:
    """The honest entry point for Input 1, covering BOTH documented capture
    methods. Supply exactly one already-captured input file:

    * `ast_json_path`   -- output of a real `slang --ast-json <top>.sv > f`
    * `scope_tree_path` -- output of a real
      `simv -ucli -do "scope -tree; quit" > f`

    With neither supplied, probes whether either tool is on PATH and returns
    a documented NOT_AVAILABLE / TOOL_PRESENT_NO_INPUT result rather than
    fabricating a tree -- matching this repo's own NOT_AVAILABLE convention
    (see `uvm_generator/address_map_verifier.py`, `memory_vault.py`).

    The `scope -tree` result additionally carries a fail-closed completeness
    verdict, because its source text's exact form varies by VCS version (see
    `parse_scope_tree_dump()`'s honesty note):

    * `REAL`         -- every non-blank line parsed into a node
    * `REAL_PARTIAL` -- nodes parsed, but `unparsed_lines` is non-empty; the
      hierarchy may be missing instances, so a bind target absent from
      `instance_paths` must NOT be read as "that instance does not exist"
    * `PARSE_FAILED` -- the file was read but produced zero nodes"""
    if ast_json_path and scope_tree_path:
        raise BindTierError(
            "AMBIGUOUS_DUT_TREE_SOURCE",
            {"detail": "Supply either ast_json_path or scope_tree_path, not both -- "
                       "the two capture methods are alternatives, and silently "
                       "preferring one would hide a disagreement between them.",
             "ast_json_path": ast_json_path, "scope_tree_path": scope_tree_path},
        )
    if ast_json_path:
        raw = json.loads(Path(ast_json_path).read_text(encoding="utf-8"))
        tree = parse_slang_ast_json(raw)
        return {"status": "REAL", "source": "slang_ast_json", "path": ast_json_path, "tree": tree}
    if scope_tree_path:
        parsed = parse_scope_tree_dump(
            Path(scope_tree_path).read_text(encoding="utf-8", errors="replace"))
        if parsed.parsed_node_count == 0:
            status = "PARSE_FAILED"
        elif parsed.unparsed_lines:
            status = "REAL_PARTIAL"
        else:
            status = "REAL"
        return {
            "status": status,
            "source": "simv_ucli_scope_tree",
            "path": scope_tree_path,
            "roots": parsed.roots,
            "tree": parsed.roots[0] if parsed.roots else None,
            "instance_paths": [n.full_path for r in parsed.roots
                               for n in flatten_instance_tree(r)],
            "parsed_node_count": parsed.parsed_node_count,
            "unparsed_lines": parsed.unparsed_lines,
        }
    resolved = check_slang_available(which_fn)
    if resolved:
        return {
            "status": "TOOL_PRESENT_NO_INPUT",
            "source": "slang_ast_json",
            "detail": (
                f"slang resolved at {resolved!r} but no ast_json_path was supplied. "
                f"Run: `slang --ast-json <top_module>.sv -f <filelist> > ast.json` "
                f"then call capture_dut_instance_tree(ast_json_path='ast.json')."
            ),
        }
    resolved_simv = check_simv_available(which_fn)
    if resolved_simv:
        return {
            "status": "TOOL_PRESENT_NO_INPUT",
            "source": "simv_ucli_scope_tree",
            "detail": (
                f"simv resolved at {resolved_simv!r} but no scope_tree_path was "
                f"supplied. Run: `{resolved_simv} -ucli -do \"scope -tree; quit\" "
                f"> scope_tree.txt` then call "
                f"capture_dut_instance_tree(scope_tree_path='scope_tree.txt')."
            ),
        }
    return {
        "status": "NOT_AVAILABLE",
        "source": "slang_ast_json_or_simv_ucli_scope_tree",
        "detail": (
            "Neither capture method's binary is on PATH in this environment "
            "(confirmed 2026-09-03 via `which slang` / `which simv` / `which vcs`, "
            "all exit 1). Either method yields the same instance tree: (a) install "
            "slang (https://github.com/MikePopoloski/slang), run "
            "`slang --ast-json <top>.sv -f <filelist> > ast.json`, and pass that path "
            "as `ast_json_path`; or (b) against an already-compiled DUT run "
            "`./simv -ucli -do \"scope -tree; quit\" > scope_tree.txt` and pass that "
            "path as `scope_tree_path` -- a project-local ./simv needs no PATH entry, "
            "pass its captured output directly."
        ),
    }


# ===========================================================================
# Input 2: interface signal sets / protocol fingerprints (extends
# verible_parser.py -- never re-implements RTL parsing)
# ===========================================================================

# ---------------------------------------------------------------------------
# AMBA-4 spec-fixed signal sets (AMBA4 SoC bus-fabric discovery, 2026-09-04)
#
# One source of truth for every AMBA signal name this module knows: the
# `PROTOCOL_FINGERPRINTS` entries below are BUILT from these constants, and
# `classify_amba_protocol()` discriminates between sub-protocols using the
# same constants. There is deliberately no second AMBA signal table anywhere.
#
# Every name here is spec-fixed (AMBA AHB/AHB-Lite, APB2/APB3/APB4,
# AXI3/AXI4/AXI4-Lite, ACE-Lite, AXI4-Stream) -- unlike the ILLUSTRATIVE
# CSI2/DSI/USB3/PCIE/SDIO sets below, these do NOT carry that honesty caveat.
# ---------------------------------------------------------------------------

#: Signals every AHB-family interface (full AHB and AHB-Lite alike) carries.
AHB_CORE_SIGNALS = frozenset({"HADDR", "HTRANS", "HWRITE", "HWDATA", "HRDATA", "HREADY"})

#: Arbitration / split-transaction signals that exist ONLY in full multi-master
#: AHB and are absent from AHB-Lite. This is the real AHB-vs-AHB-Lite
#: discriminator. NOTE `HMASTLOCK` is deliberately NOT in this set: AHB-Lite
#: carries HMASTLOCK too, so using it as a discriminator would misclassify
#: every AHB-Lite interface as full AHB. `HLOCK` (master->arbiter) IS
#: multi-master-only and is distinct from `HMASTLOCK` under token matching.
AHB_MULTI_MASTER_ONLY_SIGNALS = frozenset({"HMASTER", "HSPLIT", "HBUSREQ", "HGRANT", "HLOCK"})

#: Additional AHB evidence the doc lists as "may include" -- reported when
#: found, never required for a match.
AHB_OPTIONAL_EVIDENCE_SIGNALS = frozenset(
    {"HSIZE", "HBURST", "HPROT", "HRESP", "HREADYOUT", "HSEL", "HMASTLOCK"})

#: APB base (APB2). Present in APB3 and APB4 as well.
APB_CORE_SIGNALS = frozenset({"PADDR", "PSEL", "PENABLE", "PWRITE", "PWDATA", "PRDATA"})
#: APB3 additions -- their presence is what separates APB3 from base APB.
APB3_EVIDENCE_SIGNALS = frozenset({"PREADY", "PSLVERR"})
#: APB4 additions -- their presence is what separates APB4 from APB3.
APB4_EVIDENCE_SIGNALS = frozenset({"PSTRB", "PPROT"})

#: The five AXI memory-mapped channels (AW/W/B/AR/R), handshake + payload.
#: Shared by AXI3, AXI4, AXI4-Lite and ACE-Lite -- i.e. this set alone can
#: never decide WHICH of them an interface is; the evidence sets below do.
AXI_MM_CORE_SIGNALS = frozenset({
    "AWVALID", "AWREADY", "AWADDR",
    "WVALID", "WREADY", "WDATA",
    "BVALID", "BREADY", "BRESP",
    "ARVALID", "ARREADY", "ARADDR",
    "RVALID", "RREADY", "RDATA", "RRESP",
})
#: Burst signalling. Absent from AXI4-Lite by definition (single-beat only).
AXI_BURST_EVIDENCE_SIGNALS = frozenset({
    "AWLEN", "ARLEN", "AWSIZE", "ARSIZE", "AWBURST", "ARBURST", "WLAST", "RLAST"})
#: Transaction IDs. Absent from AXI4-Lite by definition.
AXI_ID_EVIDENCE_SIGNALS = frozenset({"AWID", "ARID", "BID", "RID"})
#: AXI3-ONLY: the write-data-channel ID. AXI4 removed WID (write interleaving
#: was dropped), so its presence is the doc's own AXI3-vs-AXI4 discriminator.
#: Requires TOKEN matching, not substring matching -- "AWID" CONTAINS "WID",
#: so a substring test would read every AXI4 interface as AXI3.
AXI3_ONLY_EVIDENCE_SIGNALS = frozenset({"WID"})
#: AXI4 additions over AXI3 -- corroborating evidence, reported when found.
AXI4_ONLY_EVIDENCE_SIGNALS = frozenset({"AWQOS", "ARQOS", "AWREGION", "ARREGION"})
#: AXI4-Lite's mandatory protection/strobe signals.
AXI4_LITE_EVIDENCE_SIGNALS = frozenset({"AWPROT", "ARPROT", "WSTRB"})
#: ACE-Lite coherency signalling layered on top of an AXI4 interface. The doc
#: requires reporting WHICH of these were actually found, not just the verdict.
ACE_LITE_COHERENCY_SIGNALS = frozenset({
    "AWSNOOP", "ARSNOOP", "AWDOMAIN", "ARDOMAIN", "AWBAR", "ARBAR"})

#: AXI4-Stream: NOT memory-mapped, and reported as its own class per the doc
#: ("Report AXI4-Stream separately from memory-mapped AXI").
AXI4_STREAM_CORE_SIGNALS = frozenset({"TVALID", "TREADY", "TDATA"})
AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS = frozenset(
    {"TSTRB", "TKEEP", "TLAST", "TID", "TDEST", "TUSER"})

#: The ten classifications AMBA-3/AMBA-4 mandate, in the doc's own order.
#: These are `PROTOCOL_FINGERPRINTS` keys; `AMBA4_DISPLAY_NAMES` maps each to
#: the doc's exact label for the AMBA-6 counting table and any downstream
#: topology JSON, so a report never invents a spelling ("AXI4_LITE" is the
#: key, "AXI4-Lite" is what a human-facing table must print).
AMBA4_PROTOCOLS: tuple = (
    "AHB", "AHB_LITE", "APB", "APB3", "APB4",
    "AXI3", "AXI4", "AXI4_LITE", "ACE_LITE", "AXI4_STREAM",
)
AMBA4_DISPLAY_NAMES: dict = {
    "AHB": "AHB", "AHB_LITE": "AHB-Lite", "APB": "APB", "APB3": "APB3",
    "APB4": "APB4", "AXI3": "AXI3", "AXI4": "AXI4", "AXI4_LITE": "AXI4-Lite",
    "ACE_LITE": "ACE-Lite", "AXI4_STREAM": "AXI4-Stream",
}

#: Family -> the core signal set that decides "is this interface of that
#: family at all". Sub-protocol resolution WITHIN a family is a separate,
#: evidence-based step (see `classify_amba_protocol()`); two families both
#: matching at once is an ambiguity, not a ranking problem.
AMBA_FAMILY_CORE_SIGNALS: dict = {
    "AHB": AHB_CORE_SIGNALS,
    "APB": APB_CORE_SIGNALS,
    "AXI_MM": AXI_MM_CORE_SIGNALS,
    "AXI_STREAM": AXI4_STREAM_CORE_SIGNALS,
}

#: Structural signal-name fingerprints, from Part C's own worked examples
#: ("AXI needs AWVALID/AWREADY/WLAST/BRESP present; CSI-2 needs D-PHY +
#: clock lanes present"). Matching is case-insensitive substring matching
#: against a module's real, verible-extracted port names -- deliberately
#: conservative (a MINIMUM required subset per protocol), so a T2 match
#: never over-claims from a partial coincidental name overlap.
#:
#: HONESTY CAVEAT (2026-09-03 review): the AMBA sets (AXI/AXI_LITE/APB/AHB)
#: and USB's DP/DM are standard, spec-fixed signal names. The rest --
#: CSI2's CLK_LANE_HS/CLK_LANE_LP/DATA_LANE0_HS, DSI's TE, USB3's
#: TX_HS_P/N + RX_HS_P/N, PCIE's PERST_N/TX_P/RX_P, SDIO's SD_* -- are
#: ILLUSTRATIVE and have NOT been verified against a real VIP example or a
#: real DUT's port list in this repo; a real PHY may well name these lanes
#: differently. That is acceptable here (and is why they are kept rather
#: than deleted) ONLY because the matching logic below FAILS SAFE: a match
#: requires the FULL required set, so a wrong/incomplete fingerprint yields
#: `matched=False` and the row falls through to T3 -- naming-heuristic-only,
#: never auto-accepted, always routed to human confirmation. A wrong
#: fingerprint therefore costs a human review, never a silent T2
#: auto-accept. Do NOT relax the full-set requirement into a partial/scored
#: match to "improve" recall: that is precisely what would turn this
#: unverified data into a false-PASS path. Verify a given protocol's real
#: signal names against that VIP's own example/interface before relying on
#: its T2 result as evidence.
#:
#: AMBA-4 addendum (2026-09-04): the ten AMBA sub-protocol entries below are
#: built from the spec-fixed constants above, and are matched with TOKEN
#: matching rather than the legacy substring matching (see
#: `match_protocol_fingerprint`'s `strict_tokens`) -- substring matching would
#: find "WID" inside "AWID" and read every AXI4 port list as AXI3. Several of
#: them are strict supersets of each other by construction (APB c APB3 c APB4;
#: AXI4_LITE c AXI4 c ACE_LITE), which is correct for this table's own
#: question ("does this port set FULLY exhibit protocol X's signature?") but
#: means the table alone cannot answer "which ONE protocol is this interface?".
#: That second question is `classify_amba_protocol()`'s, which resolves the
#: family first and then applies the real spec discriminators.
#:
#: The pre-existing "AXI"/"AXI_LITE" keys are kept BYTE-UNCHANGED as coarse
#: FAMILY-level buckets for the callers/tests that already use them; they are
#: not among `AMBA4_PROTOCOLS` and must not be used to answer an AMBA-3/AMBA-4
#: classification question.
#:
#: "AHB" and "APB", however, ARE AMBA-4 classification labels, so they could
#: not stay as coarse buckets meaning something else under the same key --
#: two meanings for one key is how a report ends up printing a mandated label
#: it did not actually establish. Both were CORRECTED on 2026-09-04:
#:   - "APB" was {PSEL,PENABLE,PWRITE,PREADY}: it omitted PADDR/PWDATA/PRDATA
#:     and REQUIRED PREADY, which is APB3 evidence -- i.e. the old "APB" entry
#:     could not match a base APB2 interface at all, and matched APB3 while
#:     reporting "APB". It is now the doc's base set exactly.
#:   - "AHB" was {HTRANS,HADDR,HWRITE,HREADY}, which matches AHB-Lite just as
#:     well as full AHB. It now additionally requires HMASTER -- the
#:     multi-master indicator every full-AHB slave interface carries, chosen
#:     over HSPLIT/HBUSREQ/HGRANT because those appear only on split-capable
#:     slaves and on master-side arbitration ports respectively.
#: No caller in this repo read either entry (verified by grep before the
#: change); their only consumers are this module's own matcher and classifier.
PROTOCOL_FINGERPRINTS: dict[str, set[str]] = {
    "AXI": {"AWVALID", "AWREADY", "WLAST", "BRESP"},
    "AXI_LITE": {"AWVALID", "AWREADY", "WVALID", "BVALID"},
    # --- AMBA-4 sub-protocol classifications (the ten AMBA4_PROTOCOLS) ---
    "AHB": set(AHB_CORE_SIGNALS | {"HMASTER"}),
    # AHB_LITE is AHB's core set with NO multi-master/arbitration signal. The
    # variant decision itself belongs to classify_amba_protocol(), which
    # applies the full AHB_MULTI_MASTER_ONLY_SIGNALS any-of test rather than
    # this table's single required discriminator.
    "AHB_LITE": set(AHB_CORE_SIGNALS),
    "APB": set(APB_CORE_SIGNALS),
    "APB3": set(APB_CORE_SIGNALS | APB3_EVIDENCE_SIGNALS),
    "APB4": set(APB_CORE_SIGNALS | APB3_EVIDENCE_SIGNALS | APB4_EVIDENCE_SIGNALS),
    "AXI3": set(AXI_MM_CORE_SIGNALS | AXI_BURST_EVIDENCE_SIGNALS
                | AXI_ID_EVIDENCE_SIGNALS | AXI3_ONLY_EVIDENCE_SIGNALS),
    "AXI4": set(AXI_MM_CORE_SIGNALS | AXI_BURST_EVIDENCE_SIGNALS
                | AXI_ID_EVIDENCE_SIGNALS),
    "AXI4_LITE": set(AXI_MM_CORE_SIGNALS | AXI4_LITE_EVIDENCE_SIGNALS),
    "ACE_LITE": set(AXI_MM_CORE_SIGNALS | AXI_BURST_EVIDENCE_SIGNALS
                    | AXI_ID_EVIDENCE_SIGNALS | ACE_LITE_COHERENCY_SIGNALS),
    "AXI4_STREAM": set(AXI4_STREAM_CORE_SIGNALS),
    "CSI2": {"CLK_LANE_HS", "CLK_LANE_LP", "DATA_LANE0_HS"},
    "DSI": {"CLK_LANE_HS", "DATA_LANE0_HS", "TE"},
    "USB": {"DP", "DM"},
    "USB3": {"TX_HS_P", "TX_HS_N", "RX_HS_P", "RX_HS_N"},
    "PCIE": {"PERST_N", "TX_P", "RX_P"},
    "SDIO": {"SD_CLK", "SD_CMD", "SD_DAT0"},
}


def build_interface_fingerprints(modules: list) -> dict[str, set[str]]:
    """Extends `verible_parser.ModuleInfo.ports` (real port extraction --
    never re-implemented here) into a per-module upper-cased port-name-set
    fingerprint, the shape `match_protocol_fingerprint()` below matches
    against. `modules` is the `FileParseResult.modules` list
    `verible_parser.parse_file()` already returns, or the equivalent list
    from `verible_parser.to_dict()['modules']` (dict form is also accepted,
    per-item, for callers reading a persisted JSON parse result rather than
    holding live dataclasses)."""
    out: dict[str, set[str]] = {}
    for mod in modules:
        name = mod.name if hasattr(mod, "name") else mod.get("name")
        ports = mod.ports if hasattr(mod, "ports") else mod.get("ports", [])
        if not name:
            continue
        names = set()
        for p in ports:
            pname = p.name if hasattr(p, "name") else p.get("name")
            if pname:
                names.add(pname.upper())
        out[name] = names
    return out


#: Splits a port name into alphanumeric tokens: "S00_AXI_AWVALID" ->
#: {S00, AXI, AWVALID}. Case is normalized by the caller.
_AMBA_TOKEN_SPLIT_RE = re.compile(r"[^A-Z0-9]+")
#: A trailing index on an otherwise-spec-named token ("HADDR0" -> "HADDR").
_AMBA_TOKEN_INDEX_RE = re.compile(r"([A-Z]+)(\d+)")


def amba_signal_tokens(port_names) -> set:
    """Token set for a module's real port names, used for AMBA signal presence
    instead of the legacy substring test.

    Substring matching cannot answer AMBA-4's own questions: "WID" is a
    substring of "AWID", so `"WID" in "AWID"` reports AXI3's discriminator
    present on every AXI4 interface; "HREADY" is a substring of "HREADYOUT";
    "TID" would be found inside a port merely spelled `..._TIDLE`. Tokenizing
    on non-alphanumeric boundaries makes `S_AXI_AWID` contribute AWID and NOT
    WID, while still matching the common real spellings (`haddr`, `HADDR`,
    `s00_axi_awvalid`, `m_axis_tvalid`). A trailing index is also folded in
    ("HADDR0" contributes HADDR), because per-port index suffixes are common
    in fabric wrappers.

    Known limitation, stated rather than implied away: a port declared as a
    SystemVerilog INTERFACE (`AXI4 s_axi`) exposes no individual signals, so
    it tokenizes to nothing AMBA-shaped and classifies as NOT_AMBA/partial.
    `verible_parser` does not model modports (AMBA-2's own gap), so this
    module cannot see through an interface port. That is reported honestly by
    the classifier rather than guessed at from the port's type name -- which
    would be exactly the name-based classification AMBA-4 forbids."""
    toks: set = set()
    for p in port_names or ():
        upper = str(p).upper()
        for tok in _AMBA_TOKEN_SPLIT_RE.split(upper):
            if not tok:
                continue
            toks.add(tok)
            m = _AMBA_TOKEN_INDEX_RE.fullmatch(tok)
            if m:
                toks.add(m.group(1))
    return toks


def match_protocol_fingerprint(port_names: set[str], protocol: str,
                               strict_tokens: Optional[bool] = None) -> dict:
    """Structural T2 match check for one (module port-set, protocol) pair.
    `matched=True` only when the FULL required signature subset is present
    (a partial hit is reported as `matched=False` with `missing_signals`
    listed, never rounded up to a match).

    `strict_tokens` selects the presence test. `None` (the default) means
    "decide from the protocol": the ten `AMBA4_PROTOCOLS` use TOKEN matching,
    because their discriminators are substrings of each other (`WID` inside
    `AWID`, `HREADY` inside `HREADYOUT`) and substring matching would silently
    invert the AXI3/AXI4 verdict. Every other protocol keeps the original
    substring behavior byte-for-byte, so no existing caller changes meaning.
    Pass True/False to force one explicitly."""
    proto = protocol.upper()
    required = PROTOCOL_FINGERPRINTS.get(proto)
    if required is None:
        return {"matched": False, "protocol": protocol, "reason": "UNKNOWN_PROTOCOL_FINGERPRINT",
                "matched_signals": [], "missing_signals": []}
    use_tokens = (proto in AMBA4_PROTOCOLS) if strict_tokens is None else bool(strict_tokens)
    if use_tokens:
        toks = amba_signal_tokens(port_names)
        present = {sig for sig in required if sig in toks}
    else:
        present = {sig for sig in required if any(sig in p for p in port_names)}
    missing = required - present
    return {
        "matched": not missing,
        "protocol": proto,
        "match_method": "TOKEN" if use_tokens else "SUBSTRING",
        "matched_signals": sorted(present),
        "missing_signals": sorted(missing),
    }


# ===========================================================================
# AMBA-4: protocol classification from RTL evidence
#
# AMBA-3 requires every fabric-facing interface to be resolved into ONE of
# ten classifications; AMBA-4 dictates that the resolution come from actual
# signal evidence and states the prohibition outright: "Never classify
# protocol solely by filename, module name, or port prefix."
#
# `classify_amba_protocol()` therefore takes a PORT-NAME SET and nothing
# else. There is deliberately no module-name parameter to accidentally
# consult, which is the structural version of that prohibition -- the
# alternative already in this repo is `protocol_router._ALIASES`, which maps
# free-text tokens like "axi3"/"ahb-lite" onto the single "amba" profile and
# is explicitly documented there as informational routing, never an RTL
# classification. This function does not call it and does not duplicate it:
# the two answer different questions (which profile handles this request vs.
# which protocol is this interface).
#
# The result is single-valued ONLY when the evidence supports a single value.
# Two families matching at once, contradictory sub-protocol evidence, and a
# partially-wired interface each get their own status rather than being
# rounded to a best guess -- AMBA-3's "do not silently omit partial/incomplete
# interfaces" and this project's own hard-won rule that an unresolved trace
# state must be reportable, not collapsed into the happy path.
# ===========================================================================

class AmbaClassificationStatus(str, Enum):
    RESOLVED = "RESOLVED"                                            # exactly one of AMBA4_PROTOCOLS
    AMBIGUOUS_MULTIPLE_PROTOCOLS = "AMBIGUOUS_MULTIPLE_PROTOCOLS"    # >1 AMBA family fully present
    AMBIGUOUS_CONTRADICTORY_EVIDENCE = "AMBIGUOUS_CONTRADICTORY_EVIDENCE"  # one family, mutually exclusive sub-protocol evidence
    UNRESOLVED_PARTIAL_EVIDENCE = "UNRESOLVED_PARTIAL_EVIDENCE"      # AMBA-shaped but incomplete -- reported, never dropped
    NOT_AMBA = "NOT_AMBA"                                            # no AMBA evidence at all


#: `protocol` value carried by every non-RESOLVED classification. A real,
#: greppable string rather than `None`, for the same reason
#: REQUIRED_HUMAN_INPUT is: an unresolved protocol must be visible in a JSON
#: dump, never read as a missing/defaulted field.
AMBA_PROTOCOL_UNRESOLVED = "AMBA_PROTOCOL_UNRESOLVED"

#: A family is considered "partially present" (worth reporting as an
#: incomplete interface rather than as NOT_AMBA) once at least this many of
#: its core signals are found. 2, not 1: a lone `TDATA` or `HADDR` token on
#: an otherwise non-AMBA module is coincidence, two co-occurring spec names
#: is evidence of a wired-but-incomplete interface.
AMBA_PARTIAL_EVIDENCE_MIN_SIGNALS = 2


@dataclass
class AmbaProtocolClassification:
    """One interface's AMBA-4 verdict plus the real evidence behind it."""
    protocol: str                       # an AMBA4_PROTOCOLS key, or AMBA_PROTOCOL_UNRESOLVED
    status: str                         # an AmbaClassificationStatus value
    family: Optional[str] = None        # AHB / APB / AXI_MM / AXI_STREAM, when one was established
    candidates: list = field(default_factory=list)   # what it could be, when not RESOLVED
    evidence_signals: list = field(default_factory=list)   # AMBA signals actually found
    missing_signals: list = field(default_factory=list)    # required-but-absent, for a partial
    discriminators: list = field(default_factory=list)     # why this verdict, in words
    requires_human_confirmation: bool = False

    @property
    def display_name(self) -> str:
        """The doc's own spelling ("AXI4-Lite", not "AXI4_LITE") for the
        AMBA-6 counting table and any human-facing report."""
        return AMBA4_DISPLAY_NAMES.get(self.protocol, self.protocol)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "display_name": self.display_name,
            "status": self.status,
            "family": self.family,
            "candidates": list(self.candidates),
            "evidence_signals": list(self.evidence_signals),
            "missing_signals": list(self.missing_signals),
            "discriminators": list(self.discriminators),
            "requires_human_confirmation": self.requires_human_confirmation,
        }


#: Every AMBA signal name this module knows, for evidence reporting.
_ALL_AMBA_SIGNALS = frozenset().union(
    AHB_CORE_SIGNALS, AHB_MULTI_MASTER_ONLY_SIGNALS, AHB_OPTIONAL_EVIDENCE_SIGNALS,
    APB_CORE_SIGNALS, APB3_EVIDENCE_SIGNALS, APB4_EVIDENCE_SIGNALS,
    AXI_MM_CORE_SIGNALS, AXI_BURST_EVIDENCE_SIGNALS, AXI_ID_EVIDENCE_SIGNALS,
    AXI3_ONLY_EVIDENCE_SIGNALS, AXI4_ONLY_EVIDENCE_SIGNALS, AXI4_LITE_EVIDENCE_SIGNALS,
    ACE_LITE_COHERENCY_SIGNALS,
    AXI4_STREAM_CORE_SIGNALS, AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS,
)


def _resolve_ahb_variant(toks: set) -> tuple:
    """AHB vs AHB-Lite. The discriminator is the PRESENCE of arbitration /
    split-transaction signalling, which AHB-Lite (single master, no split)
    does not have. HMASTLOCK is not consulted -- AHB-Lite carries it too."""
    multi = sorted(AHB_MULTI_MASTER_ONLY_SIGNALS & toks)
    if multi:
        return "AHB", [f"multi-master/split-transaction signalling present ({multi}) -- "
                       f"full AHB, not AHB-Lite"]
    return "AHB_LITE", ["no arbitration/split signalling "
                        f"({sorted(AHB_MULTI_MASTER_ONLY_SIGNALS)}) present -- AHB-Lite. "
                        "HMASTLOCK deliberately not used as a discriminator: AHB-Lite has it too."]


def _resolve_apb_variant(toks: set) -> tuple:
    """APB2 vs APB3 vs APB4, by the doc's own evidence tiers."""
    apb4 = sorted(APB4_EVIDENCE_SIGNALS & toks)
    apb3 = sorted(APB3_EVIDENCE_SIGNALS & toks)
    if apb4:
        return "APB4", [f"APB4 evidence present ({apb4})"]
    if apb3:
        return "APB3", [f"APB3 evidence present ({apb3}), no APB4 evidence "
                        f"({sorted(APB4_EVIDENCE_SIGNALS)}) found"]
    return "APB", ["base APB: neither APB3 evidence "
                   f"({sorted(APB3_EVIDENCE_SIGNALS)}) nor APB4 evidence "
                   f"({sorted(APB4_EVIDENCE_SIGNALS)}) found"]


def _resolve_axi_mm_variant(toks: set) -> tuple:
    """ACE-Lite vs AXI3 vs AXI4 vs AXI4-Lite, all sharing the AW/W/B/AR/R
    channels. Returns (protocol_or_None, discriminators, candidates); a None
    protocol means the evidence contradicts itself and must not be resolved."""
    coherency = sorted(ACE_LITE_COHERENCY_SIGNALS & toks)
    wid = sorted(AXI3_ONLY_EVIDENCE_SIGNALS & toks)
    burst = sorted(AXI_BURST_EVIDENCE_SIGNALS & toks)
    ids = sorted(AXI_ID_EVIDENCE_SIGNALS & toks)
    axi4_only = sorted(AXI4_ONLY_EVIDENCE_SIGNALS & toks)

    if coherency and wid:
        # ACE-Lite extends AXI4, and AXI4 removed WID. Both cannot be true of
        # one real interface; resolving it either way would invent a fact.
        return None, [
            f"contradictory: ACE-Lite coherency signals {coherency} imply an AXI4 base, "
            f"but AXI3-only {wid} is also present. ACE-Lite is defined on AXI4, which "
            f"removed WID -- these cannot both hold."], ["ACE_LITE", "AXI3"]
    if coherency:
        return "ACE_LITE", [f"AXI memory-mapped channels plus coherency signals {coherency}"], []
    if wid:
        return "AXI3", [f"{wid} present -- AXI3 (AXI4 removed the write-data-channel ID). "
                        "Established by token match, not substring: AWID contains WID."], []
    if axi4_only and not burst and not ids:
        # AXI4-only QoS/REGION signals on an otherwise burst-less, ID-less
        # interface: neither a clean AXI4 nor a clean AXI4-Lite.
        return None, [
            f"contradictory: AXI4-only signals {axi4_only} present, but no burst "
            f"({sorted(AXI_BURST_EVIDENCE_SIGNALS)}) and no ID "
            f"({sorted(AXI_ID_EVIDENCE_SIGNALS)}) signalling, which AXI4-Lite forbids "
            "carrying QoS/REGION on."], ["AXI4", "AXI4_LITE"]
    if burst or ids:
        why = [f"AXI memory-mapped channels with burst {burst} / ID {ids} signalling, and no "
               f"{sorted(AXI3_ONLY_EVIDENCE_SIGNALS)} -- AXI4, not AXI3"]
        if axi4_only:
            why.append(f"corroborated by AXI4-only signals {axi4_only}")
        return "AXI4", why, []
    return "AXI4_LITE", [
        "reduced memory-mapped subset: AW/W/B/AR/R present with no burst "
        f"({sorted(AXI_BURST_EVIDENCE_SIGNALS)}) and no ID "
        f"({sorted(AXI_ID_EVIDENCE_SIGNALS)}) signalling -- AXI4-Lite, "
        "deliberately NOT reported as full AXI4"], []


def classify_amba_protocol(port_names) -> AmbaProtocolClassification:
    """AMBA-4: resolve one interface's port-name set into ONE of the ten
    `AMBA4_PROTOCOLS`, from signal evidence only.

    `port_names` is a real port-name collection -- typically one value out of
    `build_interface_fingerprints()`, i.e. verible-extracted RTL ports, never
    a hand-typed list. The module/instance/file name is not a parameter here
    by design (AMBA-4: "Never classify protocol solely by filename, module
    name, or port prefix").

    Four non-RESOLVED outcomes, each distinct and each reportable:
      * AMBIGUOUS_MULTIPLE_PROTOCOLS -- more than one AMBA family is fully
        present. The common real case is a protocol BRIDGE module (an
        AHB-to-APB bridge's port list contains both), where answering with a
        single protocol would be wrong at module granularity.
      * AMBIGUOUS_CONTRADICTORY_EVIDENCE -- one family, but sub-protocol
        evidence that cannot simultaneously hold.
      * UNRESOLVED_PARTIAL_EVIDENCE -- AMBA-shaped but incomplete; the
        missing required signals are named.
      * NOT_AMBA -- no AMBA evidence.
    Every one of them sets `requires_human_confirmation=True` and carries
    `AMBA_PROTOCOL_UNRESOLVED` as its `protocol`."""
    toks = amba_signal_tokens(port_names)
    evidence = sorted(_ALL_AMBA_SIGNALS & toks)

    full_families = []
    partial_families = {}
    for family, core in AMBA_FAMILY_CORE_SIGNALS.items():
        present = core & toks
        if present == core:
            full_families.append(family)
        elif len(present) >= AMBA_PARTIAL_EVIDENCE_MIN_SIGNALS:
            partial_families[family] = sorted(core - present)

    if len(full_families) > 1:
        return AmbaProtocolClassification(
            protocol=AMBA_PROTOCOL_UNRESOLVED,
            status=AmbaClassificationStatus.AMBIGUOUS_MULTIPLE_PROTOCOLS.value,
            family=None,
            candidates=sorted(full_families),
            evidence_signals=evidence,
            discriminators=[
                f"{len(full_families)} AMBA families are fully present at once "
                f"({sorted(full_families)}). Typical of a bridge/wrapper module whose port "
                "list spans both sides; a single protocol verdict at this granularity would "
                "be an invented fact. Split the port set per interface and re-classify."],
            requires_human_confirmation=True,
        )

    if len(full_families) == 1:
        family = full_families[0]
        if family == "AHB":
            proto, why = _resolve_ahb_variant(toks)
            candidates = []
        elif family == "APB":
            proto, why = _resolve_apb_variant(toks)
            candidates = []
        elif family == "AXI_STREAM":
            optional = sorted(AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS & toks)
            proto, candidates = "AXI4_STREAM", []
            why = [f"TVALID/TREADY/TDATA present with optional evidence {optional} -- "
                   "AXI4-Stream, reported separately from memory-mapped AXI per AMBA-4."]
        else:
            proto, why, candidates = _resolve_axi_mm_variant(toks)

        if proto is None:
            return AmbaProtocolClassification(
                protocol=AMBA_PROTOCOL_UNRESOLVED,
                status=AmbaClassificationStatus.AMBIGUOUS_CONTRADICTORY_EVIDENCE.value,
                family=family, candidates=candidates, evidence_signals=evidence,
                discriminators=why, requires_human_confirmation=True,
            )
        return AmbaProtocolClassification(
            protocol=proto,
            status=AmbaClassificationStatus.RESOLVED.value,
            family=family, candidates=[], evidence_signals=evidence,
            discriminators=why, requires_human_confirmation=False,
        )

    if partial_families:
        best = sorted(partial_families.items(), key=lambda kv: (len(kv[1]), kv[0]))[0]
        family, missing = best
        return AmbaProtocolClassification(
            protocol=AMBA_PROTOCOL_UNRESOLVED,
            status=AmbaClassificationStatus.UNRESOLVED_PARTIAL_EVIDENCE.value,
            family=family, candidates=sorted(partial_families),
            evidence_signals=evidence, missing_signals=missing,
            discriminators=[
                f"{family} evidence found but the interface is incomplete: required signals "
                f"{missing} are absent from the port list. Reported rather than dropped, per "
                "AMBA-3 ('Do not silently omit partial/incomplete interfaces')."],
            requires_human_confirmation=True,
        )

    return AmbaProtocolClassification(
        protocol=AMBA_PROTOCOL_UNRESOLVED,
        status=AmbaClassificationStatus.NOT_AMBA.value,
        family=None, candidates=[], evidence_signals=evidence,
        discriminators=["no AMBA family core signal set reached the "
                        f"{AMBA_PARTIAL_EVIDENCE_MIN_SIGNALS}-signal evidence floor. Note a "
                        "SystemVerilog interface port exposes no individual signals, so an "
                        "interface-typed fabric port lands here rather than being guessed at "
                        "from its type name."],
        requires_human_confirmation=True,
    )


def amba_structural_match(port_names) -> dict:
    """Bridges `classify_amba_protocol()` into the existing 4-tier classifier
    without a second notion of "matched": returns a dict in exactly
    `match_protocol_fingerprint()`'s shape, so it can be handed straight to
    `classify_bind_tier(structural_match=...)`.

    A RESOLVED classification yields `matched=True` -> T2_STRUCTURAL_MATCH.
    Every ambiguous/partial/non-AMBA outcome yields `matched=False`, so it
    falls through to T3 (human confirmation) or T4 (question queue) and can
    never be auto-accepted -- the same fail-safe direction the fingerprint
    table's own docstring commits to."""
    result = classify_amba_protocol(port_names)
    resolved = result.status == AmbaClassificationStatus.RESOLVED.value
    return {
        "matched": resolved,
        "protocol": result.protocol,
        "match_method": "TOKEN",
        "matched_signals": list(result.evidence_signals),
        "missing_signals": list(result.missing_signals),
        "amba_classification": result.to_dict(),
    }


def classify_amba_interfaces(interface_fingerprints: dict) -> dict:
    """Runs `classify_amba_protocol()` over the whole
    `build_interface_fingerprints()` result -- {module_name: port_name_set} ->
    {module_name: AmbaProtocolClassification}. A convenience over the real
    per-interface function, deliberately not a second classifier."""
    return {name: classify_amba_protocol(ports)
            for name, ports in (interface_fingerprints or {}).items()}


# ===========================================================================
# Input 3: existing binds (repo-wide grep of "^\s*bind ")
# ===========================================================================

_BIND_LINE_RE = re.compile(r'^\s*bind\s+(\S+)\s+(\S+)\s+(\S+)\s*\(')


@dataclass
class BindStatement:
    target: str            # module name or full instance path being bound into
    bound_module: str       # the module the bind statement instantiates
    instance_name: str      # the instance name given to that bound module
    source_file: str
    line_no: int
    raw_line: str


def parse_bind_line(line: str) -> Optional[tuple]:
    """Parses one SystemVerilog `bind <target> <bound_module> <instance_name>
    (...)` statement's leading tokens -- pure regex over the REAL grammar
    (`bind <target_module_or_instance> <bind_module_name> <bind_instance_name>
    (port_list);`), no invented text. Returns (target, bound_module,
    instance_name) or None if the line does not match."""
    m = _BIND_LINE_RE.match(line)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def grep_existing_binds(root_dir, glob_patterns=("*.sv", "*.svh")) -> list[BindStatement]:
    """The real repo-wide (or generated-environment-wide) equivalent of
    `grep -n "^\\s*bind " -- reads every file under `root_dir` matching
    `glob_patterns` and returns one BindStatement per matching line, in
    file order. Pure filesystem walk + regex (no external `grep` dependency
    assumed present), so this runs identically on Windows and Linux. What's
    already decided (an existing bind statement) is read here, never
    re-derived or second-guessed."""
    root = Path(root_dir)
    results: list[BindStatement] = []
    if not root.exists():
        return results
    seen_files = set()
    for pattern in glob_patterns:
        for path in sorted(root.rglob(pattern)):
            if path in seen_files:
                continue
            seen_files.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                parsed = parse_bind_line(line)
                if parsed:
                    target, bound_module, instance_name = parsed
                    results.append(BindStatement(
                        target=target, bound_module=bound_module, instance_name=instance_name,
                        source_file=str(path), line_no=line_no, raw_line=line.strip(),
                    ))
    return results


def find_existing_bind_for_target(binds: list[BindStatement], target_instance: str) -> Optional[BindStatement]:
    """Exact-path match first (bind targeted at a specific instance path),
    falling back to a bare-module-name match (CLAUDE.md Bind-Location Rule
    1: a bind on a bare module name applies to EVERY instance of that
    module) only when the target's own leaf module name is supplied via
    `target_instance` containing no '.' -- this function does not itself
    decide which is "correct" for a given project, it only reports which
    kind of existing-bind evidence (if any) was found."""
    for b in binds:
        if b.target == target_instance:
            return b
    return None


# ===========================================================================
# Input 4: VIP instances / config_db trace
#   (uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE)
# ===========================================================================

@dataclass
class TopologyComponent:
    path: str
    type_name: str
    depth: int


_TOPOLOGY_ROW_RE = re.compile(r'^(?P<indent> *)(?P<name>\S+)\s{2,}(?P<type>\S+)')


def parse_topology_dump(text: str) -> list[TopologyComponent]:
    """Parses UVM's own documented `uvm_top.print_topology()` default
    table-report shape:

        Name                    Type                Size
        ------------------------------------------------------
        uvm_test_top            my_test             -
          env                   my_env              -
            agent0              my_agent            -
              driver            my_driver           -

    Hierarchy is recovered from each row's own leading-whitespace INDENT
    (consistent 2-space nesting is UVM's own default `uvm_default_printer`
    behavior) rather than assumed from name text. A `path` is built by
    walking a parent stack keyed on indent depth. Separator/header lines
    (no `Type` column match, or literal `---`/`Name` header) are skipped.

    HONESTY NOTE: built against UVM's documented default report format, not
    verified against a live simulation's real stdout in this environment
    (no live simv here -- see module docstring). Real, unit-tested parsing
    logic; the live-capture step itself is the NOT_AVAILABLE-by-honest-
    design item (`capture_vip_topology()` below)."""
    components: list[TopologyComponent] = []
    stack: list[tuple[int, str]] = []  # (indent_len, path)
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("-") or line.strip().startswith("Name "):
            continue
        m = _TOPOLOGY_ROW_RE.match(line)
        if not m:
            continue
        indent_len = len(m.group("indent"))
        name = m.group("name")
        type_name = m.group("type")
        while stack and stack[-1][0] >= indent_len:
            stack.pop()
        parent_path = stack[-1][1] if stack else ""
        path = f"{parent_path}.{name}" if parent_path else name
        stack.append((indent_len, path))
        components.append(TopologyComponent(path=path, type_name=type_name, depth=len(stack) - 1))
    return components


@dataclass
class ConfigDbEvent:
    op: str            # "SET" or "GET"
    field: str
    context_path: str
    raw_line: str


#: UVM's own documented `+UVM_CONFIG_DB_TRACE` message shape:
#: 'UVM_INFO ... [CFGDB/SET] ... Configuration '<field>' ... set in "<path>" ...'
#: and the analogous '[CFGDB/GET] ... get ... in "<path>"' form. This regex
#: is deliberately tolerant of the free-text portions UVM's own
#: implementation varies across versions, anchoring only on the two fixed
#: tokens (`[CFGDB/SET]`/`[CFGDB/GET]`) and the quoted field/path UVM always
#: emits.
_CFGDB_RE = re.compile(
    r'\[CFGDB/(?P<op>SET|GET)\].*?[\'"](?P<field>[^\'"]+)[\'"].*?[\'"](?P<path>[^\'"]+)[\'"]'
)


def parse_config_db_trace(text: str) -> list[ConfigDbEvent]:
    """Parses `+UVM_CONFIG_DB_TRACE` log lines into structured SET/GET
    events. HONESTY NOTE: same as `parse_topology_dump()` -- built against
    UVM's documented trace message shape, not yet verified against a live
    simulation's real log text in this environment."""
    events: list[ConfigDbEvent] = []
    for line in text.splitlines():
        m = _CFGDB_RE.search(line)
        if not m:
            continue
        events.append(ConfigDbEvent(op=m.group("op"), field=m.group("field"),
                                     context_path=m.group("path"), raw_line=line.strip()))
    return events


def find_set_with_no_get(events: list[ConfigDbEvent]) -> list[ConfigDbEvent]:
    """The direct-evidence miswired-vif check Part C names: a config_db
    `SET` for a given (field, context_path) with no matching `GET` anywhere
    in the same trace is returned as-is -- direct evidence of a component
    that never actually consumed the value that was set for it, available
    from a static log, before any transaction runs."""
    gets = {(e.field, e.context_path) for e in events if e.op == "GET"}
    return [e for e in events if e.op == "SET" and (e.field, e.context_path) not in gets]


@dataclass
class VipInstanceRecord:
    vip_type: str
    instance_path: str
    active_passive: str   # "active" | "passive"


def capture_vip_topology(topology_log_path: Optional[str] = None,
                          config_db_trace_path: Optional[str] = None) -> dict:
    """The honest entry point for Input 4. Given real captured log text
    (produced by a live `+UVM_TOPOLOGY`/`uvm_top.print_topology()` run and a
    real `+UVM_CONFIG_DB_TRACE` run), parses and returns REAL structured
    data. With no paths supplied -- the actual state of this repo, no live
    simv exists here -- returns a documented NOT_AVAILABLE result with the
    exact real command line needed to produce that capture."""
    if not topology_log_path and not config_db_trace_path:
        return {
            "status": "NOT_AVAILABLE",
            "source": "uvm_topology_and_config_db_trace",
            "detail": (
                "No live simv/UVM run exists in this repo to capture from. Real "
                "capture recipe: run the environment once with "
                "`+UVM_CONFIG_DB_TRACE` on the sim command line and add a "
                "`uvm_top.print_topology();` call (e.g. in a `report_phase` or a "
                "dedicated `end_of_elaboration_phase` callback) so its table is "
                "written to the sim log; then pass that log's path as "
                "`topology_log_path` and/or `config_db_trace_path` to this "
                "function. Coordinate with the env.manifest.json workstream's "
                "own env-topology capture -- see this module's docstring."
            ),
        }
    out: dict[str, Any] = {"status": "REAL", "source": "uvm_topology_and_config_db_trace"}
    if topology_log_path:
        out["components"] = parse_topology_dump(Path(topology_log_path).read_text(encoding="utf-8", errors="replace"))
    if config_db_trace_path:
        events = parse_config_db_trace(Path(config_db_trace_path).read_text(encoding="utf-8", errors="replace"))
        out["config_db_events"] = events
        out["set_with_no_get"] = find_set_with_no_get(events)
    return out


# ===========================================================================
# Count-matching self-check equations (Part C -- real, computable, not prose)
# ===========================================================================

def check_vip_instance_count_matches_active_interfaces(
    vip_instances: list, active_interface_count: int,
) -> dict:
    """VIP instance count must equal ACTIVE INTERFACE count, never raw IP
    instance count -- a passive-monitor-only IP contributes 0 active
    interfaces even though it is 1 IP instance. Caller supplies
    `active_interface_count` computed independently (e.g. from the
    connectivity matrix's own `active_passive` column), never re-derived
    from `vip_instances` itself, so this stays a genuine cross-check rather
    than a tautology."""
    vip_count = len(vip_instances)
    ok = vip_count == active_interface_count
    return {
        "ok": ok,
        "vip_instance_count": vip_count,
        "active_interface_count": active_interface_count,
        "delta": vip_count - active_interface_count,
    }


def determine_role_from_port_direction(dut_port_direction: str) -> str:
    """Whether a VIP must be configured as bus slave/responder is
    determined STRICTLY from the DUT's real port direction at that
    boundary -- this function takes no instance-name parameter at all, by
    design, so a caller cannot accidentally feed naming evidence in here.
    DUT driving the request/address/control signals as OUTPUT means the DUT
    is the initiator, so the VIP on the other end must be slave/responder;
    DUT receiving them as INPUT means the DUT is the target, so the VIP
    must be master/initiator."""
    d = (dut_port_direction or "").strip().lower()
    if d == "output":
        return "vip_role=slave_responder (DUT drives request signals as OUTPUT => DUT is initiator)"
    if d == "input":
        return "vip_role=master_initiator (DUT receives request signals as INPUT => DUT is target)"
    if d == "inout":
        return "vip_role=AMBIGUOUS_FROM_DIRECTION_ALONE (inout boundary -- requires protocol-specific structural analysis, never guessed)"
    raise ConnectivityError("UNKNOWN_PORT_DIRECTION", {"dut_port_direction": dut_port_direction})


def compute_path_combination_count(
    masters: list, slaves: list, reachability: Optional[dict] = None,
) -> dict:
    """A passive monitor on a shared fabric is NOT the same count dimension
    as master-agent count -- the real scoreboard-sizing dimension is
    PATH-COMBINATION count: every master x every reachable slave.
    `reachability` (optional) maps a master id -> the set of slave ids it
    can actually reach (e.g. per an address-decode/fabric-topology
    evidence source); omitted, this defaults to full mesh (every master
    reaches every slave), which callers should only rely on for a
    single-fabric, no-partitioning topology -- pass real `reachability`
    evidence whenever a fabric has any access restriction."""
    per_master = {}
    total = 0
    for m in masters:
        reachable = reachability.get(m, set(slaves)) if reachability is not None else set(slaves)
        reachable = reachable & set(slaves)  # never count a "reachable" slave outside the known slave set
        per_master[m] = sorted(reachable)
        total += len(reachable)
    return {"total_path_combinations": total, "per_master": per_master,
            "master_count": len(masters), "slave_count": len(slaves)}


def verify_self_check_identity(
    verified_interface_count: int, vip_instance_count: int, exemptions: list,
) -> bool:
    """The hard self-check identity: sum(verified interfaces) ==
    sum(VIP instances) + sum(explicit exemptions). FAILS LOUDLY
    (ConnectivitySelfCheckError), never a warning/bool-False return, per
    Part C. Every exemption must itself carry a non-empty `reason` -- an
    exemption with no per-line explanation is rejected before the identity
    is even evaluated, since an unexplained gap is never acceptable."""
    for i, ex in enumerate(exemptions):
        if not isinstance(ex, dict) or not ex.get("interface") or not ex.get("reason"):
            raise ConnectivitySelfCheckError(
                "EXEMPTION_MISSING_EXPLANATION",
                {"index": i, "exemption": ex},
            )
    lhs = verified_interface_count
    rhs = vip_instance_count + len(exemptions)
    if lhs != rhs:
        raise ConnectivitySelfCheckError(
            "SELF_CHECK_IDENTITY_MISMATCH",
            {
                "verified_interface_count": verified_interface_count,
                "vip_instance_count": vip_instance_count,
                "exemption_count": len(exemptions),
                "lhs_verified_interfaces": lhs,
                "rhs_vip_plus_exemptions": rhs,
                "gap": lhs - rhs,
            },
        )
    return True


# ===========================================================================
# AMBA-5: master/slave terminology -- BOTH perspectives, always
#
# "Never output only 'Master' or 'Slave' without perspective."
#
# `determine_role_from_port_direction()` above already answers the question
# this project needed first -- "which way must the VIP be configured" -- and
# answers it from real port direction with no name parameter to consult. What
# it does NOT do is name the two perspectives AMBA-5 mandates. It bundles them
# into one composite string ("vip_role=slave_responder (DUT drives request
# signals as OUTPUT => DUT is initiator)"), so the fabric-side fact and the
# endpoint-side fact are present but neither is separately queryable, and
# neither uses AMBA-5's vocabulary.
#
# The two perspectives are exact inverses, so this is a rendering/vocabulary
# layer over that one function -- NOT a second direction->role decision. Every
# path below calls `determine_role_from_port_direction()` and dispatches on
# ITS answer, which is why `assert_role_provenance()` still holds for any row
# built from these results.
# ===========================================================================

#: AMBA-5's four mandated memory-mapped role values, spelled exactly as the
#: doc spells them. FABRIC_SIDE_* describe the fabric's own port; ENDPOINT_*
#: describe whatever is on the other end of it.
FABRIC_SIDE_SLAVE_INTERFACE = "SLAVE_INTERFACE"
FABRIC_SIDE_MASTER_INTERFACE = "MASTER_INTERFACE"
EXTERNAL_ENDPOINT_MASTER = "MASTER_ENDPOINT"
EXTERNAL_ENDPOINT_SLAVE = "SLAVE_ENDPOINT"

#: AXI4-Stream's own perspective pair ("For AXI4-Stream also report
#: SOURCE/SINK where appropriate"). Reported ALONGSIDE the memory-mapped pair
#: rather than instead of it, so one vocabulary is never silently substituted
#: for the other in a mixed-protocol table.
STREAM_FABRIC_SIDE_SINK_INTERFACE = "SINK_INTERFACE"
STREAM_FABRIC_SIDE_SOURCE_INTERFACE = "SOURCE_INTERFACE"
STREAM_EXTERNAL_ENDPOINT_SOURCE = "SOURCE_ENDPOINT"
STREAM_EXTERNAL_ENDPOINT_SINK = "SINK_ENDPOINT"

#: What both perspectives report when the direction evidence does not settle
#: them. A real, greppable value rather than `None`, for the same reason
#: `AMBA_PROTOCOL_UNRESOLVED` is one: an unresolved perspective must be
#: visible in a JSON dump, never read as a missing/defaulted field.
ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS = "ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS"

FABRIC_SIDE_ROLE_VALUES = frozenset({
    FABRIC_SIDE_SLAVE_INTERFACE, FABRIC_SIDE_MASTER_INTERFACE,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS})
EXTERNAL_ENDPOINT_ROLE_VALUES = frozenset({
    EXTERNAL_ENDPOINT_MASTER, EXTERNAL_ENDPOINT_SLAVE,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS})

#: `direction` value of a role result whose direction was never established.
DIRECTION_UNRESOLVED = "DIRECTION_UNRESOLVED"

#: Per family, the signals the TRANSACTION INITIATOR drives -- the request
#: phase only (who issues a transaction), deliberately not the full
#: initiator-driven set. Response-channel handshakes (BREADY/RREADY) and
#: sideband are also initiator-driven, but including them widens the
#: all-must-agree test below onto signals whose direction a legal-but-unusual
#: port list is more likely to spell differently, turning a resolvable
#: interface into a reported contradiction for no gain in evidence.
#:
#: HSEL is here because a decoder drives it TOWARD the selected slave, i.e. it
#: travels with the request like HADDR does.
AMBA_INITIATOR_DRIVEN_REQUEST_SIGNALS: dict = {
    "AHB": frozenset({"HADDR", "HTRANS", "HWRITE", "HWDATA", "HSIZE", "HBURST",
                      "HPROT", "HSEL"}),
    "APB": frozenset({"PADDR", "PSEL", "PENABLE", "PWRITE", "PWDATA", "PSTRB", "PPROT"}),
    "AXI_MM": frozenset({"AWVALID", "AWADDR", "WVALID", "WDATA", "ARVALID", "ARADDR"}),
    "AXI_STREAM": frozenset({"TVALID", "TDATA", "TLAST", "TSTRB", "TKEEP",
                             "TID", "TDEST", "TUSER"}),
}

_ALL_INITIATOR_DRIVEN_REQUEST_SIGNALS = frozenset().union(
    *AMBA_INITIATOR_DRIVEN_REQUEST_SIGNALS.values())

#: `resolve_fabric_request_direction()` outcomes.
REQUEST_DIRECTION_RESOLVED = "RESOLVED"
REQUEST_DIRECTION_NO_EVIDENCE = "NO_USABLE_REQUEST_SIGNAL_EVIDENCE"
REQUEST_DIRECTION_CONTRADICTORY = "CONTRADICTORY_REQUEST_SIGNAL_DIRECTIONS"

_LEGAL_PORT_DIRECTIONS = frozenset({"input", "output", "inout"})


def resolve_fabric_request_direction(signal_directions: dict) -> dict:
    """AMBA-5's implied follow-up for the case `determine_role_from_port_direction()`
    honestly refuses: an interface whose AGGREGATE direction is `inout` (or was
    never recorded as a single value at all, which is the normal case for a real
    AMBA interface -- AWVALID goes one way and AWREADY the other).

    The structural analysis is the real one: look at the direction of the
    signals the transaction INITIATOR drives. If every request signal present
    agrees, the interface's request direction is established from RTL evidence.
    If they disagree, that is reported as a contradiction, never averaged or
    majority-voted into a guess.

    `signal_directions` maps real port names -> real port directions (the
    `verible_parser.PortInfo` pair). Port NAMES appear here only as keys whose
    AMBA signal identity is recovered by `amba_signal_tokens()`; a port whose
    name carries no AMBA request-signal token contributes nothing at all, so a
    port called `M00_AXI_MASTER_PORT` cannot influence the verdict. That keeps
    AMBA-4's "never classify by name" prohibition intact -- the name selects
    WHICH spec signal a direction belongs to, it never supplies the direction.

    Returns `{direction, status, evidence, families}`; `direction` is None
    unless `status` is RESOLVED."""
    evidence: dict = {}
    families: set = set()
    for port_name, direction in (signal_directions or {}).items():
        d = str(direction or "").strip().lower()
        if d not in _LEGAL_PORT_DIRECTIONS:
            raise ConnectivityError("UNKNOWN_PORT_DIRECTION",
                                    {"port": port_name, "dut_port_direction": direction})
        hits = amba_signal_tokens([port_name]) & _ALL_INITIATOR_DRIVEN_REQUEST_SIGNALS
        for sig in sorted(hits):
            evidence[str(port_name)] = {"signal": sig, "direction": d}
            for fam, sigs in AMBA_INITIATOR_DRIVEN_REQUEST_SIGNALS.items():
                if sig in sigs:
                    families.add(fam)

    usable = {v["direction"] for v in evidence.values()} - {"inout"}
    if not usable:
        return {"direction": None, "status": REQUEST_DIRECTION_NO_EVIDENCE,
                "evidence": evidence, "families": sorted(families)}
    if len(usable) > 1:
        return {"direction": None, "status": REQUEST_DIRECTION_CONTRADICTORY,
                "evidence": evidence, "families": sorted(families)}
    return {"direction": next(iter(usable)), "status": REQUEST_DIRECTION_RESOLVED,
            "evidence": evidence, "families": sorted(families)}


@dataclass
class AmbaInterfaceRoles:
    """One fabric interface's roles from BOTH perspectives AMBA-5 mandates.

    `vip_role` is `determine_role_from_port_direction()`'s own answer, kept
    verbatim so a matrix row built from this result still satisfies
    `assert_role_provenance()`. It is None only when no direction was declared
    AND none could be established structurally, i.e. when the function had no
    direction string to hand that underlying function at all -- distinct from
    the case where the caller declared `inout` and it returned its own
    AMBIGUOUS answer. `resolved` is the property to branch on; both of those
    cases report False."""
    fabric_side_role: str
    external_endpoint_role: str
    direction: str
    direction_evidence: str
    vip_role: Optional[str] = None
    stream_fabric_side_role: Optional[str] = None
    stream_external_endpoint_role: Optional[str] = None
    requires_human_confirmation: bool = False
    unresolved_reason: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.fabric_side_role != ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS

    def to_dict(self) -> dict:
        return {
            "fabric_side_role": self.fabric_side_role,
            "external_endpoint_role": self.external_endpoint_role,
            "direction": self.direction,
            "direction_evidence": self.direction_evidence,
            "vip_role": self.vip_role,
            "stream_fabric_side_role": self.stream_fabric_side_role,
            "stream_external_endpoint_role": self.stream_external_endpoint_role,
            "requires_human_confirmation": self.requires_human_confirmation,
            "unresolved_reason": self.unresolved_reason,
        }

    def render_lines(self) -> str:
        """The two mandated lines, in AMBA-5's own layout. There is no
        single-perspective rendering anywhere in this module, so "Master" or
        "Slave" alone cannot be emitted by accident."""
        lines = [f"FABRIC_SIDE_ROLE = {self.fabric_side_role}",
                 f"EXTERNAL_ENDPOINT_ROLE = {self.external_endpoint_role}"]
        if self.stream_fabric_side_role:
            lines += [f"FABRIC_SIDE_STREAM_ROLE = {self.stream_fabric_side_role}",
                      f"EXTERNAL_ENDPOINT_STREAM_ROLE = {self.stream_external_endpoint_role}"]
        return "\n".join(lines)


def determine_fabric_interface_roles(dut_port_direction: Optional[str] = None, *,
                                     protocol: Optional[str] = None,
                                     signal_directions: Optional[dict] = None,
                                     ) -> AmbaInterfaceRoles:
    """AMBA-5: report FABRIC_SIDE_ROLE and EXTERNAL_ENDPOINT_ROLE for one
    fabric interface, from real port direction only.

    The whole decision is `determine_role_from_port_direction()`'s; this
    function only names the two perspectives its verdict already implies:
      * fabric port RECEIVES the request signals (input) -> the fabric is the
        target, so FABRIC_SIDE_ROLE = SLAVE_INTERFACE and whatever drives it is
        a MASTER_ENDPOINT (the doc's "external CPU master drives fabric S00_AXI");
      * fabric port DRIVES them (output) -> MASTER_INTERFACE / SLAVE_ENDPOINT
        (the doc's "fabric M00_AXI drives DDR controller").

    Supply `dut_port_direction`, or `signal_directions` (real port name ->
    real direction), or both. With both, an aggregate `inout` -- the case the
    underlying function refuses to guess at -- is escalated to
    `resolve_fabric_request_direction()`'s structural analysis rather than left
    unresolved. There is deliberately still no interface/module NAME parameter.

    `protocol` (an `AMBA4_PROTOCOLS` key) adds AXI4-Stream's SOURCE/SINK pair
    when the interface is AXI4-Stream; it never changes the memory-mapped pair,
    and an unresolved protocol simply omits the stream pair."""
    if dut_port_direction is None and signal_directions is None:
        raise ConnectivityError("NO_DIRECTION_EVIDENCE", {
            "hint": "AMBA-5 roles are derived from real port direction: pass "
                    "dut_port_direction, signal_directions, or both",
        })

    direction: Optional[str] = None
    evidence = ""
    if dut_port_direction is not None:
        # Called for its validation as much as its answer: an unrecognised
        # direction string must raise here, not fall through to the structural
        # path and quietly produce a verdict from half the evidence.
        determine_role_from_port_direction(dut_port_direction)
        d = str(dut_port_direction).strip().lower()
        if d in ("input", "output"):
            direction, evidence = d, f"declared DUT port direction {d!r}"

    if direction is None and signal_directions is not None:
        structural = resolve_fabric_request_direction(signal_directions)
        if structural["status"] == REQUEST_DIRECTION_RESOLVED:
            direction = structural["direction"]
            evidence = (f"structural analysis of {len(structural['evidence'])} "
                        f"initiator-driven request signal(s), all {direction!r} "
                        f"(families {structural['families']})")
        else:
            unresolved_reason = (
                f"{structural['status']}: request-signal direction evidence "
                f"{structural['evidence'] or '(none found)'}")
            return AmbaInterfaceRoles(
                fabric_side_role=ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
                external_endpoint_role=ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
                direction=DIRECTION_UNRESOLVED,
                direction_evidence=evidence or "structural analysis attempted",
                vip_role=determine_role_from_port_direction(dut_port_direction)
                if dut_port_direction is not None else None,
                requires_human_confirmation=True,
                unresolved_reason=unresolved_reason,
            )

    if direction is None:
        return AmbaInterfaceRoles(
            fabric_side_role=ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
            external_endpoint_role=ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
            direction=DIRECTION_UNRESOLVED,
            direction_evidence=f"declared DUT port direction "
                               f"{str(dut_port_direction).strip().lower()!r}",
            vip_role=determine_role_from_port_direction(dut_port_direction),
            requires_human_confirmation=True,
            unresolved_reason="an inout aggregate direction settles neither perspective, "
                              "and no per-signal directions were supplied to resolve it "
                              "structurally",
        )

    vip_role = determine_role_from_port_direction(direction)
    if vip_role.startswith("vip_role=master_initiator"):
        fabric_side = FABRIC_SIDE_SLAVE_INTERFACE
        endpoint = EXTERNAL_ENDPOINT_MASTER
        stream_fabric = STREAM_FABRIC_SIDE_SINK_INTERFACE
        stream_endpoint = STREAM_EXTERNAL_ENDPOINT_SOURCE
    else:
        fabric_side = FABRIC_SIDE_MASTER_INTERFACE
        endpoint = EXTERNAL_ENDPOINT_SLAVE
        stream_fabric = STREAM_FABRIC_SIDE_SOURCE_INTERFACE
        stream_endpoint = STREAM_EXTERNAL_ENDPOINT_SINK

    is_stream = str(protocol or "").upper() == "AXI4_STREAM"
    return AmbaInterfaceRoles(
        fabric_side_role=fabric_side,
        external_endpoint_role=endpoint,
        direction=direction,
        direction_evidence=evidence,
        vip_role=vip_role,
        stream_fabric_side_role=stream_fabric if is_stream else None,
        stream_external_endpoint_role=stream_endpoint if is_stream else None,
    )


# ===========================================================================
# AMBA-6: count all interfaces before endpoint tracing
#
# The mandatory per-protocol summary table plus its three TOTAL lines. This is
# the PER-PROTOCOL generalization of `verify_self_check_identity()` above: that
# function is a single scalar identity over the whole environment
# (sum(interfaces) == sum(VIP) + sum(exemptions)), which is protocol-agnostic
# by construction and therefore cannot answer "did the AXI4 ports reconcile".
# `verify_per_protocol_interface_count_identity()` below runs that SAME scalar
# function once per protocol bucket and once over the grand total -- it does
# not re-derive the arithmetic or the exemption-reason rule, so there is one
# identity implementation in this module, not two.
# ===========================================================================

#: An AMBA-shaped interface whose protocol could not be resolved to one of the
#: ten. It gets its OWN table row rather than being dropped -- AMBA-3's "do not
#: silently omit partial/incomplete interfaces" applies to the count table just
#: as much as to the classifier.
AMBA6_UNRESOLVED_PROTOCOL_ROW = AMBA_PROTOCOL_UNRESOLVED
AMBA6_UNRESOLVED_PROTOCOL_DISPLAY = "UNRESOLVED (AMBA-shaped, protocol not established)"


@dataclass
class AmbaFabricInterface:
    """One externally visible fabric interface: its AMBA-4 protocol verdict and
    its AMBA-5 dual-perspective roles, held together as the single record the
    AMBA-6 count table groups over.

    Composed from the two existing functions, never re-deciding either."""
    interface: str
    classification: AmbaProtocolClassification
    roles: AmbaInterfaceRoles
    port_names: list = field(default_factory=list)
    dut_instance: str = ""

    @property
    def protocol(self) -> str:
        return self.classification.protocol

    @property
    def display_name(self) -> str:
        return self.classification.display_name

    @property
    def status(self) -> str:
        return self.classification.status

    @property
    def fabric_side_role(self) -> str:
        return self.roles.fabric_side_role

    def to_dict(self) -> dict:
        return {
            "interface": self.interface,
            "dut_instance": self.dut_instance,
            "protocol": self.protocol,
            "display_name": self.display_name,
            "status": self.status,
            "port_names": sorted(self.port_names),
            "classification": self.classification.to_dict(),
            "roles": self.roles.to_dict(),
        }

    def render_amba5_block(self) -> str:
        """This interface as AMBA-5 requires it be reported."""
        return (f"{self.interface} ({self.display_name})\n"
                + self.roles.render_lines())


def build_amba_fabric_interface(interface: str, port_names, *,
                                dut_port_direction: Optional[str] = None,
                                signal_directions: Optional[dict] = None,
                                dut_instance: str = "") -> AmbaFabricInterface:
    """Classify one fabric interface (AMBA-4) and derive its two perspectives
    (AMBA-5) in the order those steps must happen: the protocol verdict is what
    tells AMBA-5 whether the AXI4-Stream SOURCE/SINK pair applies.

    `signal_directions` alone is enough -- it supplies both the port names and
    their directions -- but `port_names` is a separate parameter so an
    interface whose direction is known only in aggregate can still be
    classified from its full port list."""
    ports = list(port_names) if port_names is not None else list(signal_directions or {})
    classification = classify_amba_protocol(ports)
    roles = determine_fabric_interface_roles(
        dut_port_direction, protocol=classification.protocol,
        signal_directions=signal_directions)
    return AmbaFabricInterface(interface=interface, classification=classification,
                               roles=roles, port_names=ports, dut_instance=dut_instance)


def build_amba_fabric_inventory(interface_specs) -> list:
    """`build_amba_fabric_interface()` over a whole fabric.

    `interface_specs` is a list of dicts, one per externally visible fabric
    interface: `{interface, port_names?, signal_directions?,
    dut_port_direction?, dut_instance?}`. Typically assembled from
    `build_interface_fingerprints()` (port names) plus the same
    `verible_parser` port table's directions -- never hand-typed roles."""
    return [build_amba_fabric_interface(
        spec["interface"], spec.get("port_names"),
        dut_port_direction=spec.get("dut_port_direction"),
        signal_directions=spec.get("signal_directions"),
        dut_instance=spec.get("dut_instance", ""))
        for spec in interface_specs]


def _amba_interface_record(x) -> dict:
    """Normalise an inventory entry to the four fields the count table groups
    on. Accepts an `AmbaFabricInterface`, or a plain dict re-loaded from a
    persisted artifact (the same both-shapes tolerance
    `build_connectivity_matrix()` already offers)."""
    if isinstance(x, AmbaFabricInterface):
        return {"interface": x.interface, "protocol": x.protocol,
                "status": x.status, "fabric_side_role": x.fabric_side_role}
    d = dict(x)
    roles = d.get("roles") or {}
    return {
        "interface": d.get("interface"),
        "protocol": d.get("protocol"),
        "status": d.get("status"),
        "fabric_side_role": d.get("fabric_side_role")
        or roles.get("fabric_side_role")
        or ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
    }


def build_protocol_interface_count_table(interfaces: list) -> dict:
    """AMBA-6's mandatory summary: per-protocol fabric slave / fabric master
    interface counts, plus TOTAL FABRIC SLAVE PORTS / TOTAL FABRIC MASTER PORTS
    / TOTAL AMBA PORTS.

    Three deliberate properties, each of which exists because the obvious
    alternative loses a real finding:

    * All ten `AMBA4_PROTOCOLS` rows are always present, in the doc's own
      order, including zero-count ones -- a protocol absent from a fabric is a
      fact the table should state, not one the reader has to infer from a
      missing row.
    * An AMBA-shaped interface whose PROTOCOL is unresolved gets its own extra
      row (only when non-zero, so a clean fabric renders exactly the ten
      mandated rows) and is counted in TOTAL AMBA PORTS. Dropping it is the
      silent omission AMBA-3 forbids; raising instead would make the table
      unproducible for the very common real case of a bridge/wrapper module,
      which is when a human most needs to see the count.
    * An interface whose ROLE is unresolved is counted in its protocol's Total
      and in TOTAL AMBA PORTS but in NEITHER the slave nor the master column,
      and every such interface is named in `role_unresolved_interfaces`. So the
      three totals do not add up by subtraction, and the renderer says so --
      an unresolvable perspective is visible rather than quietly filed as one
      side or the other.

    A NOT_AMBA interface is not an AMBA port and is excluded from every count,
    but it is listed in `excluded_not_amba` so the exclusion is auditable."""
    records = [_amba_interface_record(x) for x in interfaces]

    buckets: dict = {p: {"slave": [], "master": [], "role_unresolved": []}
                     for p in AMBA4_PROTOCOLS}
    buckets[AMBA6_UNRESOLVED_PROTOCOL_ROW] = {"slave": [], "master": [],
                                              "role_unresolved": []}
    excluded_not_amba = []

    for rec in records:
        if rec["status"] == AmbaClassificationStatus.NOT_AMBA.value:
            excluded_not_amba.append(rec["interface"])
            continue
        key = rec["protocol"] if rec["protocol"] in buckets else AMBA6_UNRESOLVED_PROTOCOL_ROW
        role = rec["fabric_side_role"]
        if role == FABRIC_SIDE_SLAVE_INTERFACE:
            buckets[key]["slave"].append(rec["interface"])
        elif role == FABRIC_SIDE_MASTER_INTERFACE:
            buckets[key]["master"].append(rec["interface"])
        else:
            buckets[key]["role_unresolved"].append(rec["interface"])

    def _row(key, display):
        b = buckets[key]
        return {
            "protocol": key,
            "display_name": display,
            "fabric_slave_interfaces": len(b["slave"]),
            "fabric_master_interfaces": len(b["master"]),
            "role_unresolved_interfaces": len(b["role_unresolved"]),
            "total": len(b["slave"]) + len(b["master"]) + len(b["role_unresolved"]),
        }

    rows = [_row(p, AMBA4_DISPLAY_NAMES[p]) for p in AMBA4_PROTOCOLS]
    unresolved_row = _row(AMBA6_UNRESOLVED_PROTOCOL_ROW, AMBA6_UNRESOLVED_PROTOCOL_DISPLAY)
    if unresolved_row["total"]:
        rows.append(unresolved_row)

    role_unresolved = sorted(i for b in buckets.values() for i in b["role_unresolved"])
    return {
        "rows": rows,
        "total_fabric_slave_ports": sum(r["fabric_slave_interfaces"] for r in rows),
        "total_fabric_master_ports": sum(r["fabric_master_interfaces"] for r in rows),
        "total_amba_ports": sum(r["total"] for r in rows),
        "role_unresolved_interfaces": role_unresolved,
        "unresolved_protocol_interfaces": sorted(
            buckets[AMBA6_UNRESOLVED_PROTOCOL_ROW]["slave"]
            + buckets[AMBA6_UNRESOLVED_PROTOCOL_ROW]["master"]
            + buckets[AMBA6_UNRESOLVED_PROTOCOL_ROW]["role_unresolved"]),
        "excluded_not_amba": sorted(excluded_not_amba),
    }


def render_protocol_interface_count_table(table: dict) -> str:
    """AMBA-6's table in the doc's exact four-column shape, plus the three
    mandated TOTAL lines.

    The role-unresolved and not-AMBA sets are rendered as named lists BELOW the
    table rather than as extra columns, so the mandated shape is preserved
    while nothing is silently absorbed into it."""
    lines = ["| Protocol | Fabric Slave Interfaces | Fabric Master Interfaces | Total |",
             "|---|---:|---:|---:|"]
    for r in table["rows"]:
        lines.append("| {display_name} | {fabric_slave_interfaces} | "
                     "{fabric_master_interfaces} | {total} |".format(**r))
    lines += [
        "",
        f"TOTAL FABRIC SLAVE PORTS: {table['total_fabric_slave_ports']}",
        f"TOTAL FABRIC MASTER PORTS: {table['total_fabric_master_ports']}",
        f"TOTAL AMBA PORTS: {table['total_amba_ports']}",
    ]
    if table["role_unresolved_interfaces"]:
        lines += [
            "",
            "ROLE-UNRESOLVED AMBA PORTS "
            f"({len(table['role_unresolved_interfaces'])}) -- counted in TOTAL AMBA PORTS "
            "and in their protocol's Total, but in NEITHER the slave nor the master "
            "column, because the direction evidence does not settle which perspective "
            "they hold:",
        ]
        lines += [f"  - {i}" for i in table["role_unresolved_interfaces"]]
    if table["excluded_not_amba"]:
        lines += [
            "",
            f"EXCLUDED, NOT AMBA ({len(table['excluded_not_amba'])}) -- no AMBA family "
            "signal evidence, so not counted as AMBA ports:",
        ]
        lines += [f"  - {i}" for i in table["excluded_not_amba"]]
    return "\n".join(lines) + "\n"


def assert_amba_interface_table_fully_resolved(table: dict) -> None:
    """Hard assertion for a caller that requires a fully-resolved table before
    proceeding (AMBA-6 runs BEFORE endpoint tracing, and tracing an interface
    whose protocol or perspective is unknown traces in an unknown direction).

    Kept separate from `build_protocol_interface_count_table()` on purpose: the
    table must remain producible for a fabric that has unresolved interfaces --
    that is exactly when a human needs to read it -- while any step that cannot
    proceed on unresolved input refuses here, loudly."""
    unresolved_protocol = table.get("unresolved_protocol_interfaces") or []
    unresolved_role = table.get("role_unresolved_interfaces") or []
    if unresolved_protocol or unresolved_role:
        raise ConnectivitySelfCheckError("AMBA_INTERFACE_TABLE_NOT_FULLY_RESOLVED", {
            "unresolved_protocol_interfaces": unresolved_protocol,
            "role_unresolved_interfaces": unresolved_role,
            "hint": "resolve these through real RTL evidence, or route them to the "
                    "question queue -- they must not be counted as if decided",
        })


def verify_per_protocol_interface_count_identity(
    table: dict, vip_instance_counts: dict, exemptions: Optional[list] = None,
) -> dict:
    """The per-protocol generalization of `verify_self_check_identity()`:
    for EVERY protocol row, sum(interfaces) == sum(VIP instances) +
    sum(exemptions), and then the same identity once more over the grand total.

    The scalar function is CALLED per bucket rather than re-implemented, so the
    arithmetic, the fail-loud behaviour and the "every exemption carries a
    non-empty reason" rule have exactly one implementation in this module. What
    this adds is the dimension the scalar form structurally cannot have: it is
    handed two integers, so a fabric with one uncovered AXI4 port and one
    spurious extra APB4 VIP reconciles perfectly in aggregate while both
    findings are real.

    `vip_instance_counts` maps an `AMBA4_PROTOCOLS` key (or
    `AMBA_PROTOCOL_UNRESOLVED`) -> planned VIP instance count. Every exemption
    must carry `protocol` in addition to `interface`/`reason`, since an
    exemption that cannot be routed to a bucket would close the grand total
    while leaving a per-protocol gap open -- the aggregate-hiding-a-real-gap
    failure this function exists to prevent."""
    exemptions = list(exemptions or [])
    known = {r["protocol"] for r in table["rows"]} | set(AMBA4_PROTOCOLS) \
        | {AMBA6_UNRESOLVED_PROTOCOL_ROW}

    for proto in vip_instance_counts or {}:
        if proto not in known:
            raise ConnectivitySelfCheckError("VIP_COUNT_FOR_UNKNOWN_PROTOCOL", {
                "protocol": proto, "known_protocols": sorted(known)})

    by_protocol: dict = {}
    for i, ex in enumerate(exemptions):
        proto = (ex or {}).get("protocol")
        if proto not in known:
            raise ConnectivitySelfCheckError("EXEMPTION_PROTOCOL_UNROUTABLE", {
                "index": i, "exemption": ex, "protocol": proto,
                "known_protocols": sorted(known),
                "hint": "an exemption with no routable protocol closes the grand total "
                        "while leaving a per-protocol gap unexplained",
            })
        by_protocol.setdefault(proto, []).append(ex)

    per_protocol = {}
    for row in table["rows"]:
        proto = row["protocol"]
        vip = int((vip_instance_counts or {}).get(proto, 0))
        ex = by_protocol.get(proto, [])
        if row["total"] == 0 and vip == 0 and not ex:
            continue
        verify_self_check_identity(row["total"], vip, ex)
        per_protocol[proto] = {"interface_count": row["total"],
                               "vip_instance_count": vip,
                               "exemption_count": len(ex)}

    for proto, ex in by_protocol.items():
        if proto not in per_protocol:
            # An exemption for a protocol with no interfaces and no VIP: the
            # per-row loop skipped that row, so run the identity explicitly
            # rather than letting the exemption pass unchecked.
            verify_self_check_identity(0, int((vip_instance_counts or {}).get(proto, 0)), ex)

    verify_self_check_identity(
        table["total_amba_ports"], sum(int(v) for v in (vip_instance_counts or {}).values()),
        exemptions)
    return {"per_protocol": per_protocol,
            "total_amba_ports": table["total_amba_ports"],
            "total_vip_instances": sum(int(v) for v in (vip_instance_counts or {}).values()),
            "total_exemptions": len(exemptions),
            "identity_holds": True}


# ===========================================================================
# Connectivity matrix (required output artifact)
# ===========================================================================

#: Two columns were appended on 2026-09-04 (AMBA-5/AMBA-6): `protocol` and
#: `fabric_side_role`. They are what makes the matrix groupable by the two
#: dimensions AMBA-6's count table is defined on -- before them the matrix had
#: no protocol dimension at all, so there was nothing to group by, and `role`
#: carried the VIP-configuration answer rather than AMBA-5's fabric-side one.
#: Both default to an explicit NOT_CLASSIFIED sentinel rather than to empty, so
#: a row from a non-AMBA (e.g. USB) environment says it was never classified
#: instead of reading as an unresolved AMBA port.
MATRIX_COLUMNS = [
    "dut_instance", "interface", "direction", "role", "vip_type",
    "count", "active_passive", "bind_target", "tier",
    "protocol", "fabric_side_role",
]

#: `protocol` / `fabric_side_role` of a row that was never put through the
#: AMBA-4/AMBA-5 classifiers. Distinct from `AMBA_PROTOCOL_UNRESOLVED` and
#: `ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS`, which mean "classified, and
#: the evidence did not settle it" -- a different, and much more interesting,
#: statement than "never asked".
PROTOCOL_NOT_CLASSIFIED = "PROTOCOL_NOT_CLASSIFIED"
FABRIC_SIDE_ROLE_NOT_CLASSIFIED = "FABRIC_SIDE_ROLE_NOT_CLASSIFIED"


@dataclass
class ConnectivityRow:
    dut_instance: str
    interface: str
    direction: str
    role: str
    vip_type: str
    count: int
    active_passive: str
    bind_target: str
    tier: str
    protocol: str = PROTOCOL_NOT_CLASSIFIED
    fabric_side_role: str = FABRIC_SIDE_ROLE_NOT_CLASSIFIED

    def row_id(self) -> str:
        """Stable identity for row-lock/diff purposes: (dut_instance,
        interface) -- the pair Part C's matrix is keyed on ("one row per
        interface")."""
        return f"{self.dut_instance}::{self.interface}"

    def to_dict(self) -> dict:
        return {col: getattr(self, col) for col in MATRIX_COLUMNS}

    @classmethod
    def from_dut_port(cls, *, dut_instance: str, interface: str,
                      dut_port_direction: str, vip_type: str, count: int,
                      active_passive: str, bind_target: str, tier: str) -> "ConnectivityRow":
        """Build a matrix row whose `role` is DERIVED, not typed in: the only
        constructor that guarantees the role came from
        `determine_role_from_port_direction()` (real DUT port direction) and
        not from an instance name. `direction` is likewise taken from the
        same single source, so the two columns can never disagree.

        Prefer this over the bare `ConnectivityRow(...)` constructor -- the
        plain one still accepts any string for `role`, which is exactly the
        naming-derived-role hole `determine_role_from_port_direction()`'s
        name-free signature exists to prevent."""
        return cls(
            dut_instance=dut_instance, interface=interface,
            direction=dut_port_direction,
            role=determine_role_from_port_direction(dut_port_direction),
            vip_type=vip_type, count=count, active_passive=active_passive,
            bind_target=bind_target, tier=tier,
        )

    @classmethod
    def from_amba_fabric_interface(cls, iface: "AmbaFabricInterface", *, vip_type: str,
                                   count: int, active_passive: str, bind_target: str,
                                   tier: str) -> "ConnectivityRow":
        """Build a matrix row from a real AMBA-4/AMBA-5 discovery record, so
        the row's `protocol` and `fabric_side_role` are the classifier's and
        the direction analysis's own answers rather than typed-in strings.

        REFUSES an interface whose direction was never established: with no
        perspective there is no VIP orientation to plan, and a row asserting
        one would be an invented fact. Such an interface belongs in the
        question queue (`build_t4_question_queue_entry()`), not in the matrix.

        This constructs a PLANNING row only. It emits no `bind` statement and
        writes no SystemVerilog -- AMBA-30/AMBA-31 hold implementation behind a
        human review gate, and `bind_target` here is a planned target string a
        human reviews, never generated output."""
        if not iface.roles.resolved:
            raise ConnectivityError("AMBA_INTERFACE_HAS_NO_ESTABLISHED_DIRECTION", {
                "interface": iface.interface,
                "fabric_side_role": iface.roles.fabric_side_role,
                "unresolved_reason": iface.roles.unresolved_reason,
                "hint": "route this interface to the question queue; a matrix row would "
                        "assert a VIP orientation the RTL evidence does not support",
            })
        return cls(
            dut_instance=iface.dut_instance, interface=iface.interface,
            direction=iface.roles.direction, role=iface.roles.vip_role,
            vip_type=vip_type, count=count, active_passive=active_passive,
            bind_target=bind_target, tier=tier,
            protocol=iface.protocol, fabric_side_role=iface.fabric_side_role,
        )


#: Value substituted for a matrix column absent from a plain dict row (e.g. one
#: re-loaded from a manifest written before that column existed).
_MATRIX_COLUMN_DEFAULTS = {
    "protocol": PROTOCOL_NOT_CLASSIFIED,
    "fabric_side_role": FABRIC_SIDE_ROLE_NOT_CLASSIFIED,
}


def build_connectivity_matrix(rows: list) -> list[dict]:
    """Fixed-column JSON form of the required matrix. `rows` may be
    `ConnectivityRow` instances or already-plain dicts (accepted so a
    caller re-loading a persisted manifest can re-render without
    reconstructing dataclasses)."""
    out = []
    for r in rows:
        d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
        out.append({col: (d[col] if d.get(col) is not None
                          else _MATRIX_COLUMN_DEFAULTS.get(col))
                    for col in MATRIX_COLUMNS})
    return out


def render_matrix_table(rows: list) -> str:
    """Human-readable fixed-width table renderer for the same matrix."""
    matrix = build_connectivity_matrix(rows)
    if not matrix:
        return "(empty connectivity matrix)"
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in matrix)) for c in MATRIX_COLUMNS}
    header = " | ".join(c.ljust(widths[c]) for c in MATRIX_COLUMNS)
    sep = "-+-".join("-" * widths[c] for c in MATRIX_COLUMNS)
    lines = [header, sep]
    for r in matrix:
        lines.append(" | ".join(str(r.get(c, "")).ljust(widths[c]) for c in MATRIX_COLUMNS))
    return "\n".join(lines)


#: `vip_type` values that mean "this verified interface has NO VIP on it".
#: Such a row must be covered by an explicit, reasoned exemption or the
#: self-check identity below fails -- that is the "no unexplained gap" rule.
NO_VIP_MARKERS = frozenset({"", "-", "NONE", "N/A", "NA", REQUIRED_HUMAN_INPUT})

#: The three legal outputs of `determine_role_from_port_direction()`, by
#: prefix. Any other `role` value in a matrix row was not derived from a real
#: DUT port direction.
LEGAL_ROLE_PREFIXES = (
    "vip_role=slave_responder",
    "vip_role=master_initiator",
    "vip_role=AMBIGUOUS_FROM_DIRECTION_ALONE",
)

#: The only two legal values of the matrix's `active_passive` column. This
#: column is not decoration: it is the sole evidence for the ACTIVE-interface
#: count, which is the dimension Part C's first count-mismatch source is
#: measured in ("VIP count = ACTIVE interface count, never raw IP instance
#: count"). An unrecognised value there makes that count silently wrong, so
#: `assert_active_passive_vocabulary()` hard-rejects one rather than guessing
#: which side a typo meant.
ACTIVE_INTERFACE = "active"
PASSIVE_INTERFACE = "passive"
ACTIVE_PASSIVE_VALUES = frozenset({ACTIVE_INTERFACE, PASSIVE_INTERFACE})


def _row_has_vip(row: dict) -> bool:
    """Whether one already-normalised matrix row carries a real VIP instance."""
    return str(row.get("vip_type") or "").strip().upper() not in NO_VIP_MARKERS


def _row_active_passive(row: dict) -> str:
    """The row's `active_passive` value, case/whitespace-normalised. Returns
    the raw string unchanged when it is not vocabulary, so the caller that
    reports the violation can quote what was actually written."""
    raw = str(row.get("active_passive") or "").strip()
    return raw.lower() if raw.lower() in ACTIVE_PASSIVE_VALUES else raw


def count_vip_instances_in_matrix(rows: list) -> int:
    """How many matrix rows actually carry a VIP instance -- the `vip_instance
    _count` term of the self-check identity, read off the real matrix rather
    than supplied by the caller as a separate (and therefore forgeable)
    number."""
    return sum(1 for r in build_connectivity_matrix(rows) if _row_has_vip(r))


def assert_active_passive_vocabulary(rows: list) -> None:
    """Every row's `active_passive` must be exactly `active` or `passive`.

    Until 2026-09-04 this column was free text that nothing ever read for
    counting -- only `render_hierarchy_diagram()` printed it -- so a matrix
    could carry `"actve-ish maybe?"` and still write a manifest that looked
    authoritative. Once the ACTIVE-interface count below is derived from this
    column, an unvocabulary value is no longer cosmetic: it silently drops a
    row out of the very count Part C's first mismatch source is defined in."""
    for i, r in enumerate(build_connectivity_matrix(rows)):
        value = _row_active_passive(r)
        if value not in ACTIVE_PASSIVE_VALUES:
            raise ConnectivityError("ACTIVE_PASSIVE_NOT_IN_VOCABULARY", {
                "row_index": i, "dut_instance": r.get("dut_instance"),
                "interface": r.get("interface"), "active_passive": r.get("active_passive"),
                "legal_values": sorted(ACTIVE_PASSIVE_VALUES),
            })


def count_active_interfaces_in_matrix(rows: list) -> int:
    """The ACTIVE-interface count, read off the matrix's own `active_passive`
    column -- the right-hand term of Part C's first count-mismatch source.
    Assumes the vocabulary assert above has already run."""
    return sum(1 for r in build_connectivity_matrix(rows)
               if _row_active_passive(r) == ACTIVE_INTERFACE)


def matrix_vip_instance_records(rows: list) -> list:
    """The matrix's VIP-carrying rows as real `VipInstanceRecord`s, so the
    matrix can be fed to `check_vip_instance_count_matches_active_interfaces()`
    -- which had no caller anywhere outside its own test until 2026-09-04."""
    out = []
    for r in build_connectivity_matrix(rows):
        if _row_has_vip(r):
            out.append(VipInstanceRecord(
                vip_type=str(r.get("vip_type")),
                instance_path=f"{r.get('dut_instance')}::{r.get('interface')}",
                active_passive=_row_active_passive(r),
            ))
    return out


def reconcile_exemptions_against_matrix(rows: list, exemptions: list) -> list[dict]:
    """Every exemption must actually name an uncovered no-VIP interface of
    THIS matrix, and no two may name the same one.

    `verify_self_check_identity()` can only ever count exemptions (`len()`) --
    it is handed two integers and a list, and has no rows to match against. So
    an exemption naming an interface that is not in the matrix at all, or one
    that already HAS a VIP, still closed the identity for a completely
    different uncovered interface. That defeats the "no unexplained gap" rule
    with an arbitrary string while leaving the real gap unexplained. This is
    the matrix-level check that layer could not perform; the scalar identity
    function keeps its existing signature and contract untouched.

    Returns one record per exemption naming the row it covers and whether that
    row is `active` -- an exempted ACTIVE interface is the serious kind and is
    surfaced in the manifest rather than being indistinguishable from an
    exempted passive one."""
    matrix = build_connectivity_matrix(rows)
    uncovered = {}
    for r in matrix:
        if not _row_has_vip(r):
            uncovered.setdefault(str(r.get("interface") or ""), r)
    known = {str(r.get("interface") or "") for r in matrix}

    records, claimed = [], set()
    for i, ex in enumerate(exemptions):
        iface = str((ex or {}).get("interface") or "")
        if iface not in known:
            raise ConnectivitySelfCheckError("EXEMPTION_INTERFACE_NOT_IN_MATRIX", {
                "index": i, "interface": iface, "matrix_interfaces": sorted(known),
                "hint": "an exemption must name a real interface of this matrix, "
                        "otherwise it closes the identity for a gap it does not explain",
            })
        if iface not in uncovered:
            raise ConnectivitySelfCheckError("EXEMPTION_COVERS_AN_INTERFACE_THAT_HAS_A_VIP", {
                "index": i, "interface": iface,
                "hint": "this interface already carries a VIP, so exempting it double-counts "
                        "and silently absorbs a different interface's real gap",
            })
        if iface in claimed:
            raise ConnectivitySelfCheckError("DUPLICATE_EXEMPTION", {
                "index": i, "interface": iface,
                "hint": "two exemptions naming the same interface count twice in the identity",
            })
        claimed.add(iface)
        records.append({
            "interface": iface,
            "reason": (ex or {}).get("reason"),
            "dut_instance": uncovered[iface].get("dut_instance"),
            "active_passive": _row_active_passive(uncovered[iface]),
            "exempts_an_active_interface":
                _row_active_passive(uncovered[iface]) == ACTIVE_INTERFACE,
        })
    return records


def verify_matrix_vip_active_interface_count(rows: list,
                                             exemptions: Optional[list] = None) -> dict:
    """Part C's FIRST count-mismatch source, run against a real matrix: the
    VIP count is measured against the ACTIVE-interface count, never the raw
    row/IP-instance count.

    `check_vip_instance_count_matches_active_interfaces()` existed and was
    tested but had no caller outside its own test, and its scalar `delta`
    cannot be used alone on matrix data: a legitimate PASSIVE-monitor VIP
    (+1) and a genuinely uncovered ACTIVE interface (-1) cancel exactly, so
    two real findings of opposite sign report `ok: True`. This decomposes the
    delta into its two independent halves so neither can hide the other, and
    raises on the half that is a real defect -- an ACTIVE interface with no
    VIP driving it and no exemption explaining why."""
    exemptions = list(exemptions or [])
    matrix = build_connectivity_matrix(rows)
    exempted = {str((ex or {}).get("interface") or "") for ex in exemptions}

    active_total = count_active_interfaces_in_matrix(rows)
    vip_records = matrix_vip_instance_records(rows)
    scalar = check_vip_instance_count_matches_active_interfaces(vip_records, active_total)

    passive_vip = [v.instance_path for v in vip_records
                   if v.active_passive == PASSIVE_INTERFACE]
    uncovered_active = [
        f"{r.get('dut_instance')}::{r.get('interface')}" for r in matrix
        if _row_active_passive(r) == ACTIVE_INTERFACE and not _row_has_vip(r)
        and str(r.get("interface") or "") not in exempted
    ]
    if uncovered_active:
        raise ConnectivitySelfCheckError("ACTIVE_INTERFACE_WITHOUT_VIP", {
            "uncovered_active_interfaces": uncovered_active,
            "active_interface_count": active_total,
            "passive_vip_instances": passive_vip,
            "scalar_delta": scalar["delta"],
            "hint": "an ACTIVE interface with no VIP is not covered by the scalar "
                    "delta when a passive-monitor VIP cancels it -- give it a VIP, "
                    "or an explicit exemption naming this interface with a reason",
        })
    return {
        "active_interface_count": active_total,
        "passive_interface_count": len(matrix) - active_total,
        "vip_instance_count": scalar["vip_instance_count"],
        "passive_vip_instances": passive_vip,
        "uncovered_active_interfaces": [],
        "scalar_delta": scalar["delta"],
        "scalar_ok": scalar["ok"],
        "delta_fully_explained": True,
    }


def assert_role_provenance(rows: list) -> None:
    """Matrix-level enforcement that every `role` value is one
    `determine_role_from_port_direction()` could actually have produced.
    Closes the gap between that function's deliberately name-free signature
    and `ConnectivityRow.role` being a plain, hand-settable string: a
    naming-derived role such as "master (u_axi_m looks like a master)" is
    rejected here even though the dataclass itself would accept it."""
    for i, r in enumerate(build_connectivity_matrix(rows)):
        role = str(r.get("role") or "")
        if not role.startswith(LEGAL_ROLE_PREFIXES):
            raise ConnectivityError("ROLE_NOT_DERIVED_FROM_PORT_DIRECTION", {
                "row_index": i, "dut_instance": r.get("dut_instance"),
                "interface": r.get("interface"), "role": role,
                "legal_prefixes": list(LEGAL_ROLE_PREFIXES),
                "hint": "build the row with ConnectivityRow.from_dut_port(), which derives role from the real DUT port direction",
            })


def verify_matrix_self_check_identity(rows: list, exemptions: Optional[list] = None) -> dict:
    """Run Part C's hard identity over a REAL connectivity matrix:
    sum(verified interfaces) == sum(VIP instances) + sum(explicit exemptions),
    with both left- and right-hand terms read off the matrix itself
    (one row per verified interface; a row whose `vip_type` is a
    `NO_VIP_MARKERS` value contributes no VIP instance).

    This is the wiring `verify_self_check_identity()` previously lacked: the
    equation existed and was tested, but nothing ever fed a real matrix into
    it, so a matrix containing an uncovered no-VIP interface could still be
    rendered and persisted. Raises `ConnectivitySelfCheckError` (never a
    bool/warning) exactly as that function does.

    Three things the scalar identity cannot check on its own, because it is
    handed integers rather than rows, run here FIRST -- and the order is the
    point, not an implementation detail. The scalar identity's own failure
    names no interface: an ACTIVE interface with no VIP reports only as
    `gap: 1`, leaving the reader to find which row it meant. Running the
    row-aware checks first means the most specific true statement is the one
    raised, with the arithmetic left as the backstop for what they cannot see:
      * the `active_passive` vocabulary, without which the ACTIVE-interface
        count is silently wrong;
      * that each exemption really names an uncovered no-VIP interface OF
        THIS MATRIX (`reconcile_exemptions_against_matrix()`) -- the scalar
        form can only `len()` them, so any string closed any gap;
      * Part C's ACTIVE-interface count dimension
        (`verify_matrix_vip_active_interface_count()`), which names the
        offending interface and whose two halves cancel if compared only as
        a scalar delta.
    The scalar identity then still runs, and is what catches an uncovered
    PASSIVE interface carrying no exemption."""
    exemptions = list(exemptions or [])
    assert_active_passive_vocabulary(rows)
    exemption_records = reconcile_exemptions_against_matrix(rows, exemptions)
    vip_count_check = verify_matrix_vip_active_interface_count(rows, exemptions)
    verified = len(build_connectivity_matrix(rows))
    vip = count_vip_instances_in_matrix(rows)
    verify_self_check_identity(verified, vip, exemptions)
    return {
        "verified_interface_count": verified,
        "vip_instance_count": vip,
        "exemption_count": len(exemptions),
        "exemptions": exemptions,
        "exemptions_reconciled": exemption_records,
        "vip_count_check": vip_count_check,
        "identity_holds": True,
    }


#: Matrix `protocol` values that make a row an AMBA fabric port for counting
#: purposes: one of the ten, or an AMBA-shaped port whose protocol the evidence
#: did not settle. `PROTOCOL_NOT_CLASSIFIED` is excluded -- a row that was never
#: put through the classifier is not evidence of an AMBA port.
AMBA_MATRIX_PROTOCOL_VALUES = frozenset(AMBA4_PROTOCOLS) | {AMBA_PROTOCOL_UNRESOLVED}


def count_amba_ports_in_matrix(rows: list) -> int:
    """How many matrix rows are AMBA fabric ports, read off the matrix's own
    `protocol` column."""
    return sum(1 for r in build_connectivity_matrix(rows)
               if str(r.get("protocol") or "") in AMBA_MATRIX_PROTOCOL_VALUES)


def cross_check_amba_table_against_matrix(table: dict, rows: list) -> dict:
    """AMBA-6's count table and the connectivity matrix count the same ports by
    two independent routes -- the discovery inventory and the persisted planning
    matrix. This is the assertion that they can never silently disagree.

    Without it the two mechanisms drift the moment an interface is discovered
    but never given a matrix row (or vice versa), and both artifacts still look
    internally consistent: `verify_matrix_self_check_identity()` reconciles the
    rows that ARE there, and the table counts the interfaces that WERE
    discovered, and neither can see the other's omission."""
    matrix_amba = count_amba_ports_in_matrix(rows)
    if matrix_amba != table["total_amba_ports"]:
        raise ConnectivitySelfCheckError("AMBA_TABLE_AND_MATRIX_PORT_COUNTS_DISAGREE", {
            "table_total_amba_ports": table["total_amba_ports"],
            "matrix_amba_port_count": matrix_amba,
            "gap": table["total_amba_ports"] - matrix_amba,
            "hint": "every discovered AMBA interface must have a matrix row and every "
                    "AMBA matrix row must come from a discovered interface -- a gap "
                    "either way means one artifact is describing a fabric the other "
                    "does not",
        })
    return {"total_amba_ports": table["total_amba_ports"],
            "matrix_amba_port_count": matrix_amba, "counts_agree": True}


def annotate_rows_with_confirmation(rows: list, lock_store: Optional["RowLockStore"] = None,
                                    row_id_fn: Optional[Callable[[Any], str]] = None) -> list:
    """The matrix rows, each carrying a `confirmation` block read off the real
    `RowLockStore` -- `{status, row_id, confirmed_by, confirmed_date,
    evidence, content_hash}`.

    This is the manifest WRITEBACK the per-row confirmation mechanism
    previously lacked: before 2026-09-04 confirmation state lived only in a
    side lock file, so the connectivity manifest -- the artifact a human
    actually reads and a downstream generator actually consumes -- showed no
    trace of who had signed off on which bind target, or of the fact that a
    row had changed since the last sign-off. `status` is one of the three
    `CONFIRMATION_*` values; with no lock store it is UNCONFIRMED for every
    row, which is the honest reading of "no confirmation record exists"."""
    row_id_fn = row_id_fn or (lambda r: r.row_id() if hasattr(r, "row_id") else
                              f"{r.get('dut_instance')}::{r.get('interface')}")
    out = []
    for row in rows:
        content = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        matrix_row = {col: content.get(col) for col in MATRIX_COLUMNS}
        row_id = row_id_fn(row)
        if lock_store is None:
            block = {"status": CONFIRMATION_UNCONFIRMED, "row_id": row_id,
                     "confirmed_by": None, "confirmed_date": None,
                     "evidence": None, "content_hash": _content_hash(matrix_row)}
        else:
            status = lock_store.confirmation_status(row_id, matrix_row)
            rec = lock_store.confirmation(row_id) or {}
            block = {
                "status": status,
                "row_id": row_id,
                "confirmed_by": rec.get("confirmed_by"),
                "confirmed_date": rec.get("confirmed_date"),
                "evidence": rec.get("evidence"),
                "content_hash": _content_hash(matrix_row),
            }
            if status == CONFIRMATION_CHANGED_SINCE_CONFIRMATION:
                block["confirmed_content_hash"] = rec.get("content_hash")
                block["diff_since_confirmation"] = lock_store.row_diff(row_id, matrix_row)
        matrix_row["confirmation"] = block
        out.append(matrix_row)
    return out


def write_connectivity_manifest(path, rows: list, metadata: Optional[dict] = None,
                                exemptions: Optional[list] = None,
                                lock_store: Optional["RowLockStore"] = None,
                                row_id_fn: Optional[Callable[[Any], str]] = None) -> dict:
    """Persist the connectivity matrix. The self-check identity and role
    provenance are verified BEFORE anything is written, so a manifest file
    that exists on disk is one that reconciled -- a matrix with an
    unexplained no-VIP interface, or a hand-typed naming-derived role,
    raises instead of silently producing an authoritative-looking artifact.

    Pass `lock_store` to write per-row human confirmation back into the
    manifest itself (`confirmed_by`/`confirmed_date`/`evidence`/`status` per
    row, plus a `confirmation_summary` roll-up). Omitting it is honest, not
    silent: every row is then stamped UNCONFIRMED rather than being left
    with no confirmation field at all, so a manifest can never be read as
    "reviewed" merely because it lacks the evidence that it wasn't."""
    assert_role_provenance(rows)
    self_check = verify_matrix_self_check_identity(rows, exemptions)
    annotated = annotate_rows_with_confirmation(rows, lock_store, row_id_fn)
    summary: dict = {CONFIRMATION_UNCONFIRMED: 0, CONFIRMATION_CONFIRMED: 0,
                     CONFIRMATION_CHANGED_SINCE_CONFIRMATION: 0}
    for r in annotated:
        summary[r["confirmation"]["status"]] += 1
    manifest = {
        "generated_at": _utcnow_iso(),
        "metadata": metadata or {},
        "columns": MATRIX_COLUMNS,
        "rows": annotated,
        "self_check": self_check,
        "confirmation_summary": {
            "lock_store": str(lock_store.path) if lock_store is not None else None,
            "counts": summary,
            "all_rows_confirmed": summary[CONFIRMATION_CONFIRMED] == len(annotated) and bool(annotated),
        },
    }
    Path(path).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _mermaid_id(path: str) -> str:
    """A mermaid-safe node id derived from a real hierarchy path (mermaid
    node ids cannot contain '.', '[', ']' or '/')."""
    return "N_" + re.sub(r"[^0-9A-Za-z_]", "_", path)


def render_hierarchy_diagram(rows: list, instance_tree: Optional["DutInstanceNode"] = None,
                             lock_store: Optional["RowLockStore"] = None,
                             row_id_fn: Optional[Callable[[Any], str]] = None) -> str:
    """Mermaid rendering of the DUT hierarchy with every BIND POINT and VIP
    MOUNT LOCATION marked -- the second of Part C's 3 final artifacts
    (matrix / hierarchy diagram / question queue).

    Two modes, deliberately distinct rather than one degrading silently into
    the other:

    - `instance_tree=None` (the original mode): a flat one-edge-per-row
      overview, `DUT_instance/interface --tier: bind_target--> VIP`. Honest
      about what it is -- with no captured DUT instance tree there is no
      hierarchy to draw, and inventing nesting from dotted path strings alone
      would be a guess about module structure this module never makes
      elsewhere.
    - `instance_tree` supplied (a real `DutInstanceNode` from
      `capture_dut_instance_tree()` / `parse_slang_ast_json()` /
      `parse_scope_tree_dump()`): the actual nested module hierarchy is
      rendered as nested mermaid `subgraph`s, each node labelled
      `instance : module`, with a `:::bindpoint` class on every node that is
      a bind target and an edge out to each VIP mount at that point. A bind
      target naming a path NOT present in the captured tree is emitted into
      an explicit `UNRESOLVED_BIND_TARGETS` subgraph rather than silently
      dropped -- a bind target that does not exist in the real hierarchy is
      exactly the T3/T4 error class this module exists to surface.

    `lock_store`, when given, appends each row's confirmation status to its
    VIP node label, so the diagram shows unreviewed bind points at a glance
    instead of presenting every edge as equally settled.
    """
    matrix = build_connectivity_matrix(rows)
    row_id_fn = row_id_fn or (lambda r: f"{r.get('dut_instance')}::{r.get('interface')}")

    def _conf_suffix(r: dict) -> str:
        if lock_store is None:
            return ""
        status = lock_store.confirmation_status(row_id_fn(r), r)
        return f"<br/>[{status}]"

    if instance_tree is None:
        lines = ["flowchart LR"]
        for i, r in enumerate(matrix):
            dut_node = f'D{i}["{r["dut_instance"]}<br/>{r["interface"]}"]'
            vip_node = f'V{i}["{r["vip_type"]}<br/>({r["active_passive"]}){_conf_suffix(r)}"]'
            lines.append(f"  {dut_node} -->|{r['tier']}: {r['bind_target']}| {vip_node}")
        return "\n".join(lines)

    # Rows grouped by the hierarchy path they bind into.
    by_bind_target: dict[str, list] = {}
    for r in matrix:
        by_bind_target.setdefault(str(r.get("bind_target")), []).append(r)

    tree_paths: set = set()

    lines = ["flowchart TB",
             "  classDef bindpoint stroke-width:3px;",
             "  classDef vipmount stroke-dasharray: 4 3;"]
    vip_edges: list = []

    def _walk(node: "DutInstanceNode", depth: int) -> None:
        pad = "  " * (depth + 1)
        tree_paths.add(node.full_path)
        nid = _mermaid_id(node.full_path)
        label = f"{node.instance_name or node.full_path} : {node.module_name or '?'}"
        rows_here = by_bind_target.get(node.full_path, [])
        if node.children:
            lines.append(f'{pad}subgraph {nid}["{label}"]')
            lines.append(f"{pad}  direction TB")
            for child in node.children:
                _walk(child, depth + 1)
            lines.append(f"{pad}end")
            anchor = nid
        else:
            lines.append(f'{pad}{nid}["{label}"]')
            anchor = nid
        if rows_here:
            lines.append(f"{pad}class {nid} bindpoint;")
            for r in rows_here:
                vid = _mermaid_id(f"{node.full_path}__{r['interface']}__{r['vip_type']}")
                vip_edges.append(
                    f'  {vid}["VIP {r["vip_type"]}<br/>({r["active_passive"]} x{r["count"]})'
                    f'<br/>{r["interface"]}{_conf_suffix(r)}"]')
                vip_edges.append(f"  class {vid} vipmount;")
                vip_edges.append(f"  {anchor} -->|bind {r['tier']}| {vid}")

    _walk(instance_tree, 0)

    unresolved = [t for t in by_bind_target if t not in tree_paths]
    if unresolved:
        lines.append('  subgraph UNRESOLVED_BIND_TARGETS["UNRESOLVED_BIND_TARGETS"]')
        lines.append("    direction TB")
        for t in sorted(unresolved):
            uid = _mermaid_id("unresolved_" + t)
            lines.append(f'    {uid}["{t}<br/>NOT FOUND IN CAPTURED DUT TREE"]')
            for r in by_bind_target[t]:
                vid = _mermaid_id(f"unresolved_{t}__{r['interface']}__{r['vip_type']}")
                vip_edges.append(
                    f'  {vid}["VIP {r["vip_type"]}<br/>({r["active_passive"]} x{r["count"]})'
                    f'<br/>{r["interface"]}{_conf_suffix(r)}"]')
                vip_edges.append(f"  class {vid} vipmount;")
                vip_edges.append(f"  {uid} -->|bind {r['tier']}| {vid}")
        lines.append("  end")

    return "\n".join(lines + vip_edges)


# ---------------------------------------------------------------------------
# The 3 final artifacts, emitted together
# ---------------------------------------------------------------------------

#: Filenames `emit_connectivity_artifacts()` writes into its output directory.
#: Fixed (not caller-chosen) so a downstream reader/CI step can locate all
#: three by name without being told where each one went.
ARTIFACT_FILENAMES = {
    "matrix_manifest": "connectivity_matrix.json",
    "matrix_table": "connectivity_matrix.md",
    "hierarchy_diagram": "connectivity_hierarchy.md",
    "question_queue": "connectivity_questions.md",
    # AMBA-6's per-protocol interface count. Written only when a real AMBA
    # fabric inventory is supplied -- a non-AMBA environment gets no empty AMBA
    # file, which would be noise rather than honesty.
    "amba_interface_counts": "amba_interface_counts.md",
}


def render_question_queue_artifact(question_store, *, context_prefix: Optional[str] = None) -> str:
    """Markdown rendering of the OPEN/ASSUMED entries of the REAL
    `question_queue.QuestionQueueStore` -- the third of Part C's 3 artifacts.

    Reads `store.list_questions()` (the actual persisted queue), never a
    hand-built list: the questions shown here are the same records
    `build_t4_question_queue_entry()` and
    `route_unfilled_fields_to_question_queue()` wrote, so the artifact
    cannot drift from the queue it claims to present. `context_prefix`
    filters to one manifest's own questions when several subsystems share a
    queue."""
    open_qs = [q for q in question_store.list_questions() if q.get("status") in ("OPEN", "ASSUMED")]
    if context_prefix:
        open_qs = [q for q in open_qs if str(q.get("context_path", "")).startswith(context_prefix)]
    lines = ["# Connectivity question queue", ""]
    if not open_qs:
        lines.append("(no open questions)")
        return "\n".join(lines) + "\n"
    open_qs.sort(key=lambda q: (-int(q.get("tier") or 0), str(q.get("owner")), str(q.get("id"))))
    lines += ["| id | tier | blocking | owner | context | question | status |",
              "|---|---|---|---|---|---|---|"]
    for q in open_qs:
        lines.append("| {id} | T{tier} | {blocking} | {owner} | {ctx} | {question} | {status} |".format(
            id=q.get("id"), tier=q.get("tier"), blocking=q.get("blocking"),
            owner=q.get("owner"), ctx=q.get("context_path"),
            question=str(q.get("question", "")).replace("|", "\\|"), status=q.get("status")))
    return "\n".join(lines) + "\n"


def emit_connectivity_artifacts(out_dir, rows: list, *,
                                metadata: Optional[dict] = None,
                                exemptions: Optional[list] = None,
                                lock_store: Optional["RowLockStore"] = None,
                                question_store=None,
                                instance_tree: Optional["DutInstanceNode"] = None,
                                row_id_fn: Optional[Callable[[Any], str]] = None,
                                context_prefix: Optional[str] = None,
                                amba_interfaces: Optional[list] = None) -> dict:
    """Write ALL THREE of Part C's final presentation artifacts in one call,
    from one matrix, into `out_dir`: the connectivity matrix (JSON manifest
    + human-readable table), the hierarchy diagram marking bind points and
    VIP mount locations, and the question queue.

    This entry point exists because the three renderers were each real but
    individually callable only -- nothing in the harness emitted the set, so
    "the 3 artifacts" was a property of the code, not of any output a human
    ever received. `write_connectivity_manifest()`'s own guards (role
    provenance, self-check identity) run first, so a partial artifact set is
    never left behind by a matrix that would have failed the manifest write.

    Pass `amba_interfaces` (a `build_amba_fabric_inventory()` result) to also
    write AMBA-6's per-protocol interface count table, cross-checked against
    this same matrix so the two port counts cannot disagree. It is optional
    because Part C's three artifacts are protocol-agnostic; without it the key
    `amba_interface_counts` is present in the result with value None, which is
    "no AMBA inventory was supplied", never "this fabric has no AMBA ports".

    Returns `{artifact_key: Path}` plus `"manifest"` (the manifest dict) and
    `"pending_reconfirmations"` (the review worklist, empty when every row is
    confirmed and unchanged)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = write_connectivity_manifest(
        out / ARTIFACT_FILENAMES["matrix_manifest"], rows,
        metadata=metadata, exemptions=exemptions,
        lock_store=lock_store, row_id_fn=row_id_fn)

    table_path = out / ARTIFACT_FILENAMES["matrix_table"]
    table_path.write_text("# Connectivity matrix\n\n```\n"
                          + render_matrix_table(rows) + "\n```\n", encoding="utf-8")

    diagram_path = out / ARTIFACT_FILENAMES["hierarchy_diagram"]
    diagram_path.write_text("# Connectivity hierarchy (bind points + VIP mount locations)\n\n"
                            "```mermaid\n"
                            + render_hierarchy_diagram(rows, instance_tree=instance_tree,
                                                       lock_store=lock_store, row_id_fn=row_id_fn)
                            + "\n```\n", encoding="utf-8")

    questions_path = out / ARTIFACT_FILENAMES["question_queue"]
    if question_store is None:
        questions_path.write_text(
            "# Connectivity question queue\n\n"
            "(no question-queue store supplied to emit_connectivity_artifacts(); "
            "this is NOT an assertion that no questions exist)\n", encoding="utf-8")
    else:
        questions_path.write_text(
            render_question_queue_artifact(question_store, context_prefix=context_prefix),
            encoding="utf-8")

    amba_path = None
    amba_table = None
    if amba_interfaces is not None:
        amba_table = build_protocol_interface_count_table(amba_interfaces)
        cross_check_amba_table_against_matrix(amba_table, rows)
        amba_path = out / ARTIFACT_FILENAMES["amba_interface_counts"]
        amba_path.write_text(
            "# AMBA-6: interface count before endpoint tracing\n\n"
            + render_protocol_interface_count_table(amba_table)
            + "\nDiscovery only -- no bind statement is planned, emitted or implied by "
              "this artifact (AMBA-30/AMBA-31).\n",
            encoding="utf-8")

    _rid = row_id_fn or (lambda r: r.row_id() if hasattr(r, "row_id") else
                         f"{r.get('dut_instance')}::{r.get('interface')}")
    pending = lock_store.pending_reconfirmations(rows, _rid) if lock_store is not None else []

    return {
        "matrix_manifest": out / ARTIFACT_FILENAMES["matrix_manifest"],
        "matrix_table": table_path,
        "hierarchy_diagram": diagram_path,
        "question_queue": questions_path,
        "amba_interface_counts": amba_path,
        "amba_interface_count_table": amba_table,
        "manifest": manifest,
        "pending_reconfirmations": pending,
    }


# ===========================================================================
# 3 machine gates
# ===========================================================================

class GateStatus(str, Enum):
    """Extended 2026-09-03 (mandatory-gate-checkpoint workstream, Gap #2) to
    add NOT_YET_RUN/PENDING alongside the original PASS/FAIL/NOT_AVAILABLE --
    this is the SAME enum every gate result already used, extended rather
    than shadowed by a parallel status type, per the confirmed gap's own
    requirement to extend the existing report schema. Four semantically
    DISTINCT meanings, never conflated with one another by any function in
    this module:

    - PASS / FAIL: a gate actually ran its real check against real evidence
      and produced a verdict.
    - NOT_AVAILABLE: an ENVIRONMENT/TOOLING gap -- the gate's real logic is
      ready but the tool/data source it needs (slang/vcs on PATH, a live
      simv trace) does not exist in this environment. This is a capability
      gap that installing a tool fixes; it does not change on its own as the
      build progresses.
    - PENDING: the gate was invoked, but a real WORKFLOW PREREQUISITE this
      specific build has not yet reached does not exist yet (the textbook
      case: Gate 3 cannot PASS or FAIL until at least one pattern actually
      completes -- e.g. the TCA-hang situation, where no pattern has reached
      a terminal PASS/FAIL yet). This is a TRANSIENT state expected to
      resolve to PASS/FAIL as the build progresses, never to be reported or
      read as a FAIL, and never to be silently indistinguishable from "not
      applicable" -- see `evaluate_transaction_activity_status()` below.
    - NOT_YET_RUN: the gate has never even been INVOKED in this build/report
      at all -- distinct from PENDING (which means "invoked, waiting on a
      real prerequisite") and distinct from NOT_AVAILABLE (which means
      "invoked, found a real tooling gap"). This is the default a build
      report must show for Gate 1/2/3 before the mandatory checkpoint (first
      successful compile/elaboration, CLAUDE.md's Bind-Location Rules /
      `.claude/agents/IP_UVM_DV_Gen.md` Step 9) has been reached -- see
      `bind_verification_status_block()`/`assert_bind_gates_checkpoint()`
      below, which exist specifically so a build report can never simply
      OMIT gate status and have that omission be indistinguishable from a
      genuine NOT_YET_RUN/PENDING/FAILED state.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    PENDING = "PENDING"
    NOT_YET_RUN = "NOT_YET_RUN"


@dataclass
class GateResult:
    gate: str
    status: GateStatus
    detail: dict


# ---- Gate 1: elaboration check --------------------------------------------

def detect_elaboration_tool(which_fn: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """slang preferred (static, license-free, fast) over vcs (real license,
    real compile) when both are present -- confirmed in this environment:
    neither is on PATH (2026-09-03, `which slang` / `which vcs`)."""
    if which_fn("slang"):
        return "slang"
    if which_fn("vcs"):
        return "vcs"
    return None


def run_gate1_elaboration_check(
    filelist_paths: list, top_module: str,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    run_fn: Callable[..., Any] = subprocess.run,
) -> GateResult:
    """Cheapest gate: catches a bind path that flatly does not exist,
    before Gate 2/3 spend any more effort. Real subprocess wrapper around
    whichever of `slang`/`vcs` is actually installed; `which_fn`/`run_fn`
    are injectable so this real logic can be exercised with a synthetic
    fake tool in tests without needing a real license or binary (the same
    dependency-injection pattern this module uses for Gate 2/3's
    synthetic-fixture tests)."""
    tool = detect_elaboration_tool(which_fn)
    if tool is None:
        return GateResult(
            gate="gate1_elaboration", status=GateStatus.NOT_AVAILABLE,
            detail={
                "reason": "neither slang nor vcs is on PATH in this environment (confirmed 2026-09-03).",
                "instructions": (
                    "Install slang (https://github.com/MikePopoloski/slang) and run "
                    "`slang --ast-json -f <filelist> <top_module> -o /dev/null` (nonzero "
                    "exit == elaboration error), OR run `vcs -elab_only -f <filelist> "
                    f"-top {top_module}` on a licensed VCS install."
                ),
            },
        )
    if tool == "slang":
        argv = ["slang", "--ast-json", "-o", "-", "-f", *[str(p) for p in filelist_paths], "--top", top_module]
    else:
        argv = ["vcs", "-elab_only", "-f", *[str(p) for p in filelist_paths], "-top", top_module]
    proc = run_fn(argv, capture_output=True, text=True, timeout=300)
    status = GateStatus.PASS if proc.returncode == 0 else GateStatus.FAIL
    return GateResult(
        gate="gate1_elaboration", status=status,
        detail={"tool": tool, "argv": argv, "returncode": proc.returncode,
                "stderr": (proc.stderr or "")[-4000:]},
    )


# ---- Gate 2: static zero-time connectivity ---------------------------------

@dataclass
class SignalTrace:
    """A synthetic or real zero-time signal-trace fixture: `samples` maps a
    signal name -> an ordered list of `(time, value)` pairs. `value` is a
    string ("0"/"1"/"x"/"z" or a wider hex string containing those chars for
    a bus)."""
    samples: dict


def evaluate_zero_time_connectivity(
    trace: SignalTrace, clock_signal: str, reset_signal: str,
    required_nonx_signals: list, reset_active_low: bool = True,
) -> GateResult:
    """Real Gate-2 LOGIC: at the claimed bind point, confirm (a) the clock
    genuinely toggles somewhere in the trace, (b) reset genuinely deasserts
    at some point, and (c) every signal in `required_nonx_signals` is non-X/
    non-Z at time zero specifically. A silent/dead interface is flagged
    FAIL here, before any real transaction runs. Operates purely on the
    `SignalTrace` data contract -- no live simv is read here (see module
    docstring); `run_gate2_against_live_simv()` below is the honest
    NOT_AVAILABLE integration point for actually producing a live trace."""
    problems = []
    clk_values = {v for _, v in trace.samples.get(clock_signal, [])}
    clk_toggles = len({v for v in clk_values if v in ("0", "1")}) >= 2
    if not clk_toggles:
        problems.append(f"clock {clock_signal!r} does not toggle in the supplied trace")

    rst_samples = trace.samples.get(reset_signal, [])
    asserted, deasserted = ("0", "1") if reset_active_low else ("1", "0")
    rst_deasserts = any(v == deasserted for _, v in rst_samples) and any(v == asserted for _, v in rst_samples)
    if not rst_deasserts:
        problems.append(f"reset {reset_signal!r} never transitions asserted->deasserted in the supplied trace")

    nonx_problems = []
    for sig in required_nonx_signals:
        sig_samples = trace.samples.get(sig, [])
        t0_values = [v for t, v in sig_samples if t == 0]
        if not t0_values:
            nonx_problems.append(f"{sig!r} has no sample at time 0")
            continue
        if any(ch in ("x", "X", "z", "Z") for v in t0_values for ch in v):
            nonx_problems.append(f"{sig!r} is X/Z at time 0: {t0_values[0]!r}")
    problems.extend(nonx_problems)

    status = GateStatus.FAIL if problems else GateStatus.PASS
    return GateResult(
        gate="gate2_zero_time_connectivity", status=status,
        detail={"clock_toggles": clk_toggles, "reset_deasserts": rst_deasserts,
                "nonx_at_t0_problems": nonx_problems, "problems": problems},
    )


def run_gate2_against_live_simv(*args, **kwargs) -> GateResult:
    """Honest NOT_AVAILABLE integration point: no live simv exists in this
    repo to dump a real zero-time signal trace from. Real capture recipe:
    dump the relevant signals to FSDB/VCD for the first few time steps
    (e.g. `$dumpvars` scoped to just the bind-point signals, per this
    project's own Waveform Dump User Gate -- minimum sufficient scope, not
    full-chip), convert to a `SignalTrace` (time, value) sample list per
    signal, and call `evaluate_zero_time_connectivity()` with it -- the
    real, tested logic above. Never fabricate a trace to make this pass."""
    return GateResult(
        gate="gate2_zero_time_connectivity", status=GateStatus.NOT_AVAILABLE,
        detail={"reason": "no live simv in this repo to capture a real zero-time signal trace from.",
                "instructions": ("Dump the bind-point clock/reset/required signals for the first few "
                                  "time steps and convert to a SignalTrace, then call "
                                  "evaluate_zero_time_connectivity() directly.")},
    )


# ---- Gate 3: transaction activity ------------------------------------------

def evaluate_transaction_activity(monitor_transaction_counts: dict) -> GateResult:
    """Real Gate-3 LOGIC: confirms every VIP monitor actually received >= 1
    real transaction. `monitor_transaction_counts` maps a VIP monitor
    instance path -> an observed transaction count (from a real or
    synthetic-fixture source). Explicitly the only method that catches a
    path that's syntactically legal (passed Gate 1) and structurally wired
    (passed Gate 2) but connected to the WRONG instance -- a monitor on the
    wrong bus segment toggles clock/reset fine but never sees a real
    transaction addressed to it."""
    silent = {mon: cnt for mon, cnt in monitor_transaction_counts.items() if cnt < 1}
    status = GateStatus.FAIL if silent else GateStatus.PASS
    return GateResult(
        gate="gate3_transaction_activity", status=status,
        detail={"silent_monitors": silent, "monitor_count": len(monitor_transaction_counts)},
    )


def run_gate3_against_live_simv(*args, **kwargs) -> GateResult:
    """Honest NOT_AVAILABLE integration point, same treatment as Gate 2:
    real recipe is a minimal directed test whose UVM monitors' own
    `analysis_port` write counts are tallied into a
    `monitor_transaction_counts` dict and passed to
    `evaluate_transaction_activity()`.

    Part C's "standing 'just connectivity-check' recipe re-run on every RTL
    update" is no longer only a recommendation in this docstring: it is
    implemented as `dv_harness/connectivity_check.py` and the root
    justfile's `connectivity-check` / `connectivity-check-status` recipes
    (2026-09-04). That runner drives `run_machine_gates()` and records the
    RTL content fingerprint each verdict was produced against, so a later
    `--check-only` run fails when the RTL moved but the gates were not
    re-run. Supplying real counts here is still the project's own job --
    this function fabricates none."""
    return GateResult(
        gate="gate3_transaction_activity", status=GateStatus.NOT_AVAILABLE,
        detail={"reason": "no live simv/directed test run exists in this repo to source real monitor transaction counts from.",
                "instructions": ("Run a minimal directed test per interface, tally each VIP monitor's "
                                  "analysis_port write count, and call evaluate_transaction_activity() "
                                  "with that dict. Recommended as a standing recipe re-run on every RTL "
                                  "update, not a one-time check.")},
    )


def evaluate_transaction_activity_status(
    pattern_completed: bool, monitor_transaction_counts: Optional[dict] = None,
) -> GateResult:
    """Gate-3 status resolver (2026-09-03, Gap #2 -- mandatory-gate-
    checkpoint workstream) that makes the PENDING state explicit instead of
    the caller having to infer it from an absent/empty counts dict.
    `pattern_completed` is REAL EVIDENCE the caller must supply (a sim.log
    terminal PASS/FAIL marker, an LSF job-terminal reconcile record -- see
    CLAUDE.md's `_write_job_tier_memory_on_terminal_reconcile()` reference)
    -- this function never infers it from `monitor_transaction_counts` being
    None/empty, because that alone is ambiguous (it could mean "no pattern
    has even started" just as easily as "a pattern ran but wrote nothing to
    any monitor's analysis_port", which is a real FAIL, not a PENDING).

    - `pattern_completed=False` -> PENDING. Gate 3 cannot logically PASS or
      FAIL yet: there is no completed pattern to have sourced real monitor
      transaction counts from. This is the exact TCA-hang situation this
      workstream exists to make trackable -- a build stuck with no pattern
      yet reaching a terminal PASS/FAIL must report Gate 3 as PENDING, never
      silently as FAIL (nothing has actually failed a check) and never
      simply omitted from a report (indistinguishable from "not checked").
    - `pattern_completed=True` and `monitor_transaction_counts` supplied ->
      delegates to `evaluate_transaction_activity()` for the real verdict.
    - `pattern_completed=True` but `monitor_transaction_counts` is None ->
      NOT_AVAILABLE (a pattern finished, but no tooling/log path exists here
      to source per-monitor transaction counts from -- a genuine tooling
      gap, not a transient workflow-prerequisite wait)."""
    if not pattern_completed:
        return GateResult(
            gate="gate3_transaction_activity", status=GateStatus.PENDING,
            detail={
                "reason": ("no pattern has completed yet in this build -- Gate 3 cannot "
                           "PASS or FAIL until a real pattern reaches a terminal PASS/FAIL "
                           "and its VIP monitors' analysis_port write counts can be tallied."),
                "prerequisite": "a completed (terminal PASS or FAIL) pattern run",
            },
        )
    if monitor_transaction_counts is not None:
        return evaluate_transaction_activity(monitor_transaction_counts)
    return run_gate3_against_live_simv()


# ---- Pipeline (mandatory, non-skippable) -----------------------------------

@dataclass
class GateReport:
    gate1: GateResult
    gate2: GateResult
    gate3: GateResult

    def ready_for_human_review(self) -> bool:
        """A connectivity plan is ready to present to a human ONLY if no
        gate reported FAIL. NOT_AVAILABLE is allowed through (it is not a
        silently-assumed PASS -- callers must still see and report it
        prominently; see `blocking_not_available()` below) but a real FAIL
        blocks presentation outright."""
        return GateStatus.FAIL not in (self.gate1.status, self.gate2.status, self.gate3.status)

    def not_available_gates(self) -> list:
        return [g.gate for g in (self.gate1, self.gate2, self.gate3) if g.status == GateStatus.NOT_AVAILABLE]

    def pending_gates(self) -> list:
        """Gates genuinely invoked but blocked on a real workflow
        prerequisite (typically Gate 3 before any pattern has completed) --
        kept separate from `not_available_gates()` since PENDING and
        NOT_AVAILABLE are distinct GateStatus meanings (see GateStatus'
        own docstring): a PENDING gate is expected to resolve to PASS/FAIL
        as the build progresses; a NOT_AVAILABLE one will not, until the
        missing tool/environment capability is actually installed."""
        return [g.gate for g in (self.gate1, self.gate2, self.gate3) if g.status == GateStatus.PENDING]


def run_machine_gates(
    filelist_paths: list, top_module: str, signal_trace: Optional[SignalTrace],
    clock_signal: str = "clk", reset_signal: str = "rst_n",
    required_nonx_signals: Optional[list] = None,
    monitor_transaction_counts: Optional[dict] = None,
    pattern_completed: Optional[bool] = None,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    run_fn: Callable[..., Any] = subprocess.run,
) -> GateReport:
    """The single mandatory pipeline entry point -- a caller cannot invoke
    only 1 or 2 of the 3 gates through this function; all three always run,
    in order, and the aggregate `GateReport` is what must be consulted
    before presenting a plan for human confirmation (`ready_for_human_review()`).
    The three underlying `run_gate*`/`evaluate_*` functions remain
    separately importable/invokable for unit testing and for a caller that
    needs one gate's raw result mid-pipeline -- but THIS function is the
    one a real connectivity workflow is expected to call.

    `pattern_completed` (2026-09-03, Gap #2): when explicitly supplied (True
    or False, based on real evidence -- see
    `evaluate_transaction_activity_status()`'s own docstring), Gate 3 is
    resolved through that PENDING-aware function instead of the older
    NOT_AVAILABLE-only `run_gate3_against_live_simv()` fallback, so a build
    with no pattern completed yet reports Gate 3 as PENDING rather than
    conflating it with a tooling gap. Left as `None` (the default), Gate 3
    falls back to the original behavior unchanged, for backward
    compatibility with any existing caller that has not yet been updated to
    supply this real evidence."""
    gate1 = run_gate1_elaboration_check(filelist_paths, top_module, which_fn=which_fn, run_fn=run_fn)
    if signal_trace is not None:
        gate2 = evaluate_zero_time_connectivity(
            signal_trace, clock_signal, reset_signal, required_nonx_signals or [])
    else:
        gate2 = run_gate2_against_live_simv()
    if pattern_completed is not None:
        gate3 = evaluate_transaction_activity_status(pattern_completed, monitor_transaction_counts)
    elif monitor_transaction_counts is not None:
        gate3 = evaluate_transaction_activity(monitor_transaction_counts)
    else:
        gate3 = run_gate3_against_live_simv()
    return GateReport(gate1=gate1, gate2=gate2, gate3=gate3)


# ---- Mandatory build-status checkpoint (2026-09-03, Gap #2) ---------------

class BindGateCheckpointError(ConnectivityError):
    """Raised by `assert_bind_gates_checkpoint()` when a build reports its
    first successful compile/elaboration but Gates 1/2 were never actually
    invoked (still NOT_YET_RUN, or the status block is missing outright) --
    the mandatory checkpoint required by CLAUDE.md's Bind-Location Rules and
    `.claude/agents/IP_UVM_DV_Gen.md` Step 9 from that point in a build
    forward. Also raised when Gate 3's status is missing from the block
    entirely -- Gate 3 is allowed to be PENDING at this checkpoint (a
    pattern legitimately may not have completed yet), but it must never be
    silently absent, which is indistinguishable from "not checked"."""


#: The 3 status-block keys every build-status report must carry from the
#: first-successful-compile checkpoint onward. Kept as one shared tuple
#: (not re-typed at each call site) so `bind_verification_status_block()`,
#: `assert_bind_gates_checkpoint()`, and
#: `dv_harness/uvm_generator/bind_verification_lint.py`'s report scanner all
#: agree on the exact same 3 keys.
BIND_VERIFICATION_STATUS_KEYS = (
    "gate1_elaboration", "gate2_zero_time_connectivity", "gate3_transaction_activity",
)


def bind_verification_status_block(gate_report: Optional[GateReport]) -> dict:
    """The canonical status block a build-status report must embed from the
    first-successful-compile checkpoint onward (CLAUDE.md's Bind-Location
    Rules / `IP_UVM_DV_Gen.md` Step 9). `gate_report=None` means no gate has
    ever been invoked in this build yet -- every key then explicitly reports
    NOT_YET_RUN rather than the block simply being empty/omitted, so a
    reviewer (human or `assert_bind_gates_checkpoint()`/the standalone lint
    script) can always tell "never run" apart from a report that just left
    the section out."""
    if gate_report is None:
        return {key: GateStatus.NOT_YET_RUN.value for key in BIND_VERIFICATION_STATUS_KEYS}
    return {
        "gate1_elaboration": gate_report.gate1.status.value,
        "gate2_zero_time_connectivity": gate_report.gate2.status.value,
        "gate3_transaction_activity": gate_report.gate3.status.value,
    }


def render_bind_verification_status_markdown(gate_report: Optional[GateReport]) -> str:
    """Renders `bind_verification_status_block()` as the exact
    `## Bind Verification Status` section every IP_UVM_DV_Gen build-status
    report must paste in verbatim from the first-successful-compile
    checkpoint onward -- both a human reviewer and
    `dv_harness/uvm_generator/bind_verification_lint.py`'s regex scanner key
    off this literal `Gate 1 (...): <STATUS>` line shape, so a hand-written
    status report following this exact rendering stays lint-clean."""
    block = bind_verification_status_block(gate_report)
    labels = {
        "gate1_elaboration": "Gate 1 (elaboration)",
        "gate2_zero_time_connectivity": "Gate 2 (static zero-time connectivity)",
        "gate3_transaction_activity": "Gate 3 (transaction activity)",
    }
    lines = ["## Bind Verification Status", ""]
    for key in BIND_VERIFICATION_STATUS_KEYS:
        lines.append(f"- {labels[key]}: {block[key]}")
    return "\n".join(lines)


def assert_bind_gates_checkpoint(first_compile_succeeded: bool, gate_report: Optional[GateReport]) -> None:
    """The mandatory checkpoint itself (2026-09-03, Gap #2 -- closes the
    confirmed finding that the 3-gate standard was never applied to the live
    usb31_dev_uvm build because nothing retroactively flagged in-flight work
    against new verification infrastructure). Once
    `first_compile_succeeded` is True, Gates 1 and 2 MUST have actually been
    invoked -- ANY real status (PASS, FAIL, or NOT_AVAILABLE) satisfies this;
    only NOT_YET_RUN (or `gate_report` being None outright) is a violation,
    because that is the one status that means "nobody ran this gate at all".
    Gate 3 is explicitly NOT required to hold a terminal PASS/FAIL here --
    PENDING is an accepted, expected state at this checkpoint (per
    `evaluate_transaction_activity_status()`, a pattern may legitimately not
    have completed yet) -- but `gate_report` must still exist so Gate 3's
    status is at minimum explicitly surfaced, never silently absent.

    Raises `BindGateCheckpointError` -- this is a real exception a caller
    cannot silently ignore the way a bool return could be, matching this
    module's own established convention (`ConnectivitySelfCheckError`,
    `BindTierError`) of hard-failing a mandatory rule rather than degrading
    it to a warning."""
    if not first_compile_succeeded:
        return
    if gate_report is None:
        raise BindGateCheckpointError(
            "GATES_NEVER_INVOKED_AT_FIRST_COMPILE_CHECKPOINT",
            {"first_compile_succeeded": True, "gate_report": None},
        )
    never_run = [g.gate for g in (gate_report.gate1, gate_report.gate2) if g.status == GateStatus.NOT_YET_RUN]
    if never_run:
        raise BindGateCheckpointError(
            "GATE_1_OR_2_NOT_YET_RUN_AT_FIRST_COMPILE_CHECKPOINT",
            {"never_run_gates": never_run},
        )


# ===========================================================================
# Per-row confirmation / locking mechanism
# ===========================================================================

class RowLockConflictError(ConnectivityError):
    """A locked (already human-confirmed) row was asked to be re-confirmed
    with DIFFERENT content, without the caller having acknowledged the exact
    prior confirmation it supersedes.

    Before 2026-09-04 this could not happen because it was not checked:
    `confirm_row()` unconditionally overwrote `self._locks[row_id]`, so a
    second call carrying a different `bind_target` or a downgraded `tier`
    on an already-confirmed row succeeded silently -- the lock recorded a
    confirmation that no human had ever seen the new content of. `.detail`
    carries the real field-level `diff` (see `diff_row_fields()`) plus the
    `expected_supersedes_hash` a caller must pass back to proceed, so the
    error itself is the diff artifact a reviewer reads."""


#: Confirmation-state values reported by `RowLockStore.confirmation_status()`
#: and written into each manifest row's `confirmation` block. Three DISTINCT
#: states, never collapsed into a bool: an unconfirmed row and a row that was
#: confirmed and has since changed are both "not currently trustworthy", but
#: only the second one has a prior human confirmation to diff against.
CONFIRMATION_UNCONFIRMED = "UNCONFIRMED"
CONFIRMATION_CONFIRMED = "CONFIRMED"
CONFIRMATION_CHANGED_SINCE_CONFIRMATION = "CHANGED_SINCE_CONFIRMATION"


def diff_row_fields(old_content: Optional[dict], new_content: dict) -> list:
    """Field-level old-vs-new change list between two row contents -- the
    actual DIFF a human reviewer reads before re-confirming, as opposed to a
    bare changed/unchanged flag.

    Returns one entry per differing key, in sorted key order:
    `{"field", "change", "old", "new"}` where `change` is one of
    `ADDED` / `REMOVED` / `CHANGED`. `old_content=None` (a never-confirmed
    row) yields one `ADDED` entry per field, which is what a first-time
    review is: every field is new information."""
    old = dict(old_content or {})
    new = dict(new_content or {})
    changes = []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            changes.append({"field": key, "change": "ADDED", "old": None, "new": new[key]})
        elif key not in new:
            changes.append({"field": key, "change": "REMOVED", "old": old[key], "new": None})
        elif old[key] != new[key]:
            changes.append({"field": key, "change": "CHANGED", "old": old[key], "new": new[key]})
    return changes


def render_row_diff(row_id: str, diff: list) -> str:
    """Human-readable rendering of one `diff_row_fields()` result -- the text
    a reviewer is shown when a locked row's content moved under them."""
    if not diff:
        return f"{row_id}: (no field changes)"
    lines = [f"{row_id}:"]
    for d in diff:
        lines.append(f"  {d['change']:<8} {d['field']}: {d['old']!r} -> {d['new']!r}")
    return "\n".join(lines)


class RowLockStore:
    """JSON-file-backed lock store for per-row (interface row or
    scoreboard-plan-entry row) human confirmation. A confirmed row is
    LOCKED: `diff_rows_needing_reconfirmation()` will not re-surface it
    unless its content actually changed since the last confirmation --
    keeping confirmation cost from scaling linearly with project size on
    every regeneration, per Part C.

    LOCKED here means enforced, not merely labelled (2026-09-04): once a row
    is confirmed, `confirm_row()` refuses any attempt to write different
    content over it unless the caller passes back the exact
    `supersedes_hash` of the confirmation it is replacing -- i.e. unless it
    has actually looked at `row_diff()`. `is_locked()` was previously a
    passive query nothing in the module consulted; it is now the guard
    `confirm_row()` itself runs.

    Every confirmation record carries WHO confirmed it and on WHAT evidence
    (`confirmed_by` / `evidence`, both required, non-empty) -- an anonymous
    confirmation is exactly what a per-row human-sign-off mechanism must not
    be able to record."""

    def __init__(self, path):
        self.path = Path(path)
        self._locks: dict[str, dict] = {}
        if self.path.exists():
            self._locks = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._locks, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def confirm_row(self, row_id: str, row_content: dict, *,
                    confirmed_by: str, evidence: Any,
                    supersedes_hash: Optional[str] = None) -> dict:
        """Lock one row as human-confirmed, recording who confirmed it and on
        what evidence. Returns the persisted confirmation record.

        Four hard refusals, every one a raised `ConnectivityError` subclass
        rather than a warning or a silently-skipped write:

        1. `confirmed_by` empty/blank/non-string -- an unattributed
           confirmation is not a confirmation. The manifest's whole purpose
           is answering "who signed off on this bind target"; a row whose
           answer is "nobody recorded" is worse than an unconfirmed row,
           because it LOOKS reviewed.
        2. `evidence` empty -- the basis (RTL path + line, a topology dump, a
           designer's answer id) is what makes the confirmation auditable
           later. `confirmed_by` alone records only that someone clicked.
        3. Content still containing the literal `REQUIRED_HUMAN_INPUT`
           sentinel. Confirming such a row would mark a scoreboard plan row
           with an unfilled ordering/legal-drop as reviewed-and-locked, after
           which `diff_rows_needing_reconfirmation()` would stop re-surfacing
           it and the unanswered field would never be seen again. Fill the
           field -- directly, or via `apply_answered_questions()` once a human
           has answered the queue entry
           `route_unfilled_fields_to_question_queue()` raised -- and confirm
           then.
        4. The row is already locked and the new content DIFFERS, without
           `supersedes_hash` matching the currently-locked hash
           (`RowLockConflictError`, carrying the field-level diff). This is
           the explicit diff+reconfirm flow: read `row_diff(row_id, content)`,
           show it to the human, and only then re-confirm passing
           `supersedes_hash=store.locked_hash(row_id)`.

        Re-confirming a locked row with IDENTICAL content is a permitted
        no-op-shaped refresh (a second reviewer countersigning the same
        content) -- it never needs `supersedes_hash`, because nothing changed
        for a human to have missed."""
        if not isinstance(confirmed_by, str) or not confirmed_by.strip():
            raise ConnectivityError("ROW_CONFIRMATION_REQUIRES_CONFIRMED_BY",
                                     {"row_id": row_id, "confirmed_by": confirmed_by})
        if evidence is None or (isinstance(evidence, (str, list, tuple, dict)) and len(evidence) == 0) \
                or (isinstance(evidence, str) and not evidence.strip()):
            raise ConnectivityError("ROW_CONFIRMATION_REQUIRES_EVIDENCE",
                                     {"row_id": row_id, "confirmed_by": confirmed_by,
                                      "evidence": evidence})
        unfilled = find_required_human_input_paths(row_content)
        if unfilled:
            raise ConnectivityError(
                "CANNOT_CONFIRM_ROW_WITH_UNFILLED_REQUIRED_HUMAN_INPUT",
                {"row_id": row_id, "unfilled_paths": unfilled},
            )

        new_hash = _content_hash(row_content)
        prior = self._locks.get(row_id)
        if prior is not None and prior.get("content_hash") != new_hash:
            if supersedes_hash != prior.get("content_hash"):
                raise RowLockConflictError(
                    "LOCKED_ROW_CHANGED_REQUIRES_EXPLICIT_RECONFIRM",
                    {
                        "row_id": row_id,
                        "locked_hash": prior.get("content_hash"),
                        "new_hash": new_hash,
                        "expected_supersedes_hash": prior.get("content_hash"),
                        "previously_confirmed_by": prior.get("confirmed_by"),
                        "previously_confirmed_date": prior.get("confirmed_date"),
                        "diff": diff_row_fields(prior.get("content"), row_content),
                        "hint": ("read RowLockStore.row_diff(row_id, new_content), show it to the "
                                 "confirming human, then call confirm_row(..., supersedes_hash=<locked_hash>)"),
                    },
                )

        record = {
            "content_hash": new_hash,
            "content": row_content,
            "confirmed_by": confirmed_by.strip(),
            "confirmed_date": _utcnow_iso(),
            "evidence": evidence,
            "supersedes_hash": prior.get("content_hash") if prior else None,
        }
        # `confirmed_at` retained as an alias of `confirmed_date` so lock files
        # written before 2026-09-04 and readers of either key stay valid.
        record["confirmed_at"] = record["confirmed_date"]
        self._locks[row_id] = record
        self.save()
        return record

    def is_locked(self, row_id: str) -> bool:
        return row_id in self._locks

    def confirmation(self, row_id: str) -> Optional[dict]:
        """The full persisted confirmation record for one row, or None."""
        entry = self._locks.get(row_id)
        return dict(entry) if entry else None

    def locked_hash(self, row_id: str) -> Optional[str]:
        entry = self._locks.get(row_id)
        return entry["content_hash"] if entry else None

    def locked_content(self, row_id: str) -> Optional[dict]:
        entry = self._locks.get(row_id)
        return entry.get("content") if entry else None

    def row_diff(self, row_id: str, new_content: dict) -> list:
        """Field-level diff of `new_content` against what was last confirmed
        for `row_id` -- the artifact a reviewer must see before the
        `supersedes_hash` re-confirmation path is legitimate to use."""
        return diff_row_fields(self.locked_content(row_id), new_content)

    def confirmation_status(self, row_id: str, row_content: dict) -> str:
        """One of `CONFIRMATION_UNCONFIRMED` / `CONFIRMATION_CONFIRMED` /
        `CONFIRMATION_CHANGED_SINCE_CONFIRMATION` for one row's CURRENT
        content -- what `write_connectivity_manifest()` stamps onto each row."""
        locked = self.locked_hash(row_id)
        if locked is None:
            return CONFIRMATION_UNCONFIRMED
        if locked == _content_hash(row_content):
            return CONFIRMATION_CONFIRMED
        return CONFIRMATION_CHANGED_SINCE_CONFIRMATION

    def diff_rows_needing_reconfirmation(self, current_rows: list, row_id_fn: Callable[[Any], str]) -> list:
        """Returns the subset of `current_rows` that need (re)confirmation:
        never-yet-confirmed rows, or rows whose content hash no longer
        matches what was last confirmed. An unchanged, already-confirmed
        row is NOT returned -- this is what keeps a no-op regeneration a
        true no-op for the human reviewer."""
        needing = []
        for row in current_rows:
            row_id = row_id_fn(row)
            content = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            current_hash = _content_hash(content)
            locked_hash = self.locked_hash(row_id)
            if locked_hash is None or locked_hash != current_hash:
                needing.append(row)
        return needing

    def pending_reconfirmations(self, current_rows: list, row_id_fn: Callable[[Any], str]) -> list:
        """`diff_rows_needing_reconfirmation()` plus, for each returned row,
        the actual field-level diff and the `supersedes_hash` the re-confirm
        call will need. This is the review worklist: the earlier function
        answers only WHICH rows moved, this one answers WHAT moved in each,
        which is what a human actually needs in order to re-confirm."""
        out = []
        for row in self.diff_rows_needing_reconfirmation(current_rows, row_id_fn):
            row_id = row_id_fn(row)
            content = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            locked = self.locked_hash(row_id)
            out.append({
                "row_id": row_id,
                "status": (CONFIRMATION_UNCONFIRMED if locked is None
                           else CONFIRMATION_CHANGED_SINCE_CONFIRMATION),
                "supersedes_hash": locked,
                "current_hash": _content_hash(content),
                "diff": self.row_diff(row_id, content),
                "row": content,
            })
        return out


# ===========================================================================
# Checker / scoreboard planning-table generator
# ===========================================================================

def generate_protocol_check_entry(
    interface_row_id: str, vip_type: str,
    builtin_checks: list, disabled_checks: dict,
) -> dict:
    """Protocol-check plan entry: MUST reuse the VIP's own built-in checks.
    The agent's job here is ONLY to list which built-ins are DISABLED and
    why -- that disabled-list is itself the actual review focus, per Part C
    (not the enabled list). `disabled_checks` maps a check name (must be a
    member of `builtin_checks`) -> a non-empty reason string; any disabled
    check missing a reason is a hard error, never silently omitted from the
    report."""
    for name, reason in disabled_checks.items():
        if name not in builtin_checks:
            raise ConnectivityError("DISABLED_CHECK_NOT_IN_BUILTIN_LIST",
                                     {"interface_row_id": interface_row_id, "check": name})
        if not reason:
            raise ConnectivityError("DISABLED_CHECK_MISSING_REASON",
                                     {"interface_row_id": interface_row_id, "check": name})
    enabled = [c for c in builtin_checks if c not in disabled_checks]
    return {
        "kind": "protocol_check",
        "interface_row_id": interface_row_id,
        "vip_type": vip_type,
        "enabled_builtin_checks": enabled,
        "disabled_builtin_checks": [{"check": c, "reason": r} for c, r in disabled_checks.items()],
    }


#: The scoreboard planning table's required fields, in table-column order.
#: Every one of these resolves to `REQUIRED_HUMAN_INPUT` when the caller
#: supplies nothing real -- there is no field left with a computed default.
#: `ordering` and `ordering_tolerance_depth` are deliberately two SEPARATE
#: columns: "out-of-order" without a stated reorder-window depth does not
#: tell a scoreboard implementer how deep to buffer before declaring a
#: mismatch, and folding the depth into the same free-text string means it
#: is only captured when a human happens to write it there.
SCOREBOARD_PLAN_FIELDS = (
    "endpoint_pairs",
    "matching_key",
    "ordering",
    "ordering_tolerance_depth",
    "transformation_rules",
    "legal_drop_conditions",
    "reset_flush_behavior",
    "orphan_unmatched_threshold",
    "orphan_unmatched_timeout",
)


def _validated_endpoint_pairs(scoreboard_id: str, endpoint_pairs: Optional[list]):
    """Normalize/validate the comparison endpoints. Part C asks for a
    source/sink PORT plus its HIERARCHY PATH, so a bare port name with no
    path ("wdata") is rejected here rather than accepted and later compared
    against the wrong instance in a multi-instance SoC -- exactly the
    `Bind-Location Rules` rule-1 failure mode, one level up.

    Accepts either a 2-sequence `(source, sink)` or a
    `{"source": ..., "sink": ...}` dict per pair. An empty/omitted list is
    NOT an error: it resolves to `REQUIRED_HUMAN_INPUT` like every other
    unfilled field, so it routes to the question queue instead of silently
    describing a scoreboard with nothing to compare."""
    if not endpoint_pairs:
        return REQUIRED_HUMAN_INPUT
    for pair in endpoint_pairs:
        if isinstance(pair, dict):
            endpoints = [pair.get("source"), pair.get("sink")]
        elif isinstance(pair, (list, tuple)) and len(pair) == 2:
            endpoints = list(pair)
        else:
            raise ConnectivityError(
                "ENDPOINT_PAIR_MALFORMED",
                {"scoreboard_id": scoreboard_id, "pair": pair,
                 "expected": "a (source, sink) 2-sequence or a {'source':..., 'sink':...} dict"},
            )
        for endpoint in endpoints:
            if not isinstance(endpoint, str) or not endpoint.strip():
                raise ConnectivityError(
                    "ENDPOINT_PAIR_MALFORMED",
                    {"scoreboard_id": scoreboard_id, "pair": pair, "endpoint": endpoint},
                )
            if "." not in endpoint:
                raise ConnectivityError(
                    "ENDPOINT_NOT_A_HIERARCHY_PATH",
                    {"scoreboard_id": scoreboard_id, "endpoint": endpoint,
                     "expected": "a full instance hierarchy path (e.g. chip.core.usb0.axi_if), "
                                 "not a bare port or module name"},
                )
    return endpoint_pairs


def generate_scoreboard_entry(
    scoreboard_id: str, endpoint_pairs: list, matching_key: str,
    transformation_rules: Optional[list] = None,
    reset_flush_behavior: Optional[str] = None,
    orphan_threshold: Optional[int] = None,
    orphan_timeout: Optional[str] = None,
    ordering: Optional[str] = None,
    ordering_tolerance_depth: Optional[Any] = None,
    legal_drop_conditions: Optional[str] = None,
) -> dict:
    """Data-integrity (scoreboard) plan entry, one row of the planning
    table. `endpoint_pairs` and `matching_key` stay REQUIRED positional
    parameters -- a caller must consciously address them, never omit them by
    accident -- but supplying an empty value for either is no longer
    silently accepted: like every other field here it resolves to
    `REQUIRED_HUMAN_INPUT`, so `unfilled_plan_fields()` sees it and
    `route_unfilled_fields_to_question_queue()` turns it into a real,
    persisted, blocking question.

    This function NEVER computes a default for ANY of the nine
    `SCOREBOARD_PLAN_FIELDS`. The only way a field becomes a real value is a
    caller passing one in explicitly -- ultimately a human, either directly
    or via `apply_answered_questions()` reading back a persisted
    `question_queue` human answer.

    One deliberate distinction, on `transformation_rules` only:
    `None`/omitted means "nobody has said" -> `REQUIRED_HUMAN_INPUT`, while
    an explicitly-passed `[]` means "a human looked and confirmed this path
    performs no transformation" -> kept as `[]`. Those are different claims
    and the table must not conflate them."""
    return {
        "kind": "data_integrity_scoreboard",
        "scoreboard_id": scoreboard_id,
        "endpoint_pairs": _validated_endpoint_pairs(scoreboard_id, endpoint_pairs),
        "matching_key": matching_key if (matching_key or "").strip() else REQUIRED_HUMAN_INPUT,
        "ordering": ordering if ordering is not None else REQUIRED_HUMAN_INPUT,
        "ordering_tolerance_depth": (ordering_tolerance_depth if ordering_tolerance_depth is not None
                                     else REQUIRED_HUMAN_INPUT),
        "transformation_rules": transformation_rules if transformation_rules is not None else REQUIRED_HUMAN_INPUT,
        "legal_drop_conditions": legal_drop_conditions if legal_drop_conditions is not None else REQUIRED_HUMAN_INPUT,
        "reset_flush_behavior": reset_flush_behavior or REQUIRED_HUMAN_INPUT,
        "orphan_unmatched_threshold": orphan_threshold if orphan_threshold is not None else REQUIRED_HUMAN_INPUT,
        "orphan_unmatched_timeout": orphan_timeout if orphan_timeout is not None else REQUIRED_HUMAN_INPUT,
    }


def generate_system_level_entry(
    entry_id: str, kind: str, cross_interface_paths: list, description: str,
) -> dict:
    """System-level plan entry: cross-interface-path scoreboards,
    performance checks, DECERR/error-response checks. `kind` is a free
    label (e.g. "cross_path_scoreboard", "performance_check",
    "error_response_check") kept as caller-supplied evidence, not an enum
    this module invents on its own."""
    return {
        "kind": "system_level",
        "entry_id": entry_id,
        "system_level_kind": kind,
        "cross_interface_paths": cross_interface_paths,
        "description": description,
    }


def build_checker_scoreboard_plan(
    protocol_entries: list, scoreboard_entries: list, system_entries: list,
    *, question_store=None, now=None,
) -> dict:
    """Assemble the 3-category planning table (protocol checks / data-integrity
    scoreboards / system-level checks).

    `unfilled_fields` is ALWAYS computed, with or without a store, so the plan
    artifact itself carries the list of scoreboard fields still holding
    `REQUIRED_HUMAN_INPUT` -- a reader of the JSON never has to grep for the
    sentinel to find out whether the table is actually complete.

    Pass `question_store` (a `question_queue.QuestionQueueStore` or a project
    root path) to make Part C's "an empty field automatically becomes a
    question-queue entry" literally true: every unfilled field on every
    scoreboard entry is routed through `route_unfilled_fields_to_question_queue()`
    into real, persisted, schema-validated questions, and their Q-IDs are
    recorded on the plan as `open_questions`."""
    plan = {
        "generated_at": _utcnow_iso(),
        "protocol_checks": protocol_entries,
        "data_integrity_scoreboards": scoreboard_entries,
        "system_level_checks": system_entries,
        "unfilled_fields": {e["scoreboard_id"]: unfilled_plan_fields(e)
                            for e in scoreboard_entries
                            if unfilled_plan_fields(e)},
    }
    if question_store is not None:
        asked = []
        for entry in scoreboard_entries:
            asked.extend(route_unfilled_fields_to_question_queue(question_store, entry, now=now))
        plan["open_questions"] = [{"id": q["id"], "question_key": q["question_key"],
                                   "tier": q["tier"], "blocking": q["blocking"],
                                   "owner": q["owner"], "context_path": q["context_path"],
                                   "status": q["status"]}
                                  for q in asked]
    return plan


def scoreboard_entry_row_id(entry: dict) -> str:
    return f"scoreboard::{entry['scoreboard_id']}"


# ===========================================================================
# "An empty field automatically becomes a question-queue entry" (Part C)
#
# Before 2026-09-04 the REQUIRED_HUMAN_INPUT sentinel was only ever a string
# sitting in a returned dict: nothing scanned a plan entry for it, nothing
# turned it into a persisted question, and `RowLockStore.confirm_row()` would
# happily lock a scoreboard row whose ordering/legal-drop was still literally
# the word REQUIRED_HUMAN_INPUT. The three functions below close that, reusing
# the SAME `question_queue.QuestionQueueStore` the T4 bind path already routes
# through (`build_t4_question_queue_entry()`), never a parallel mechanism.
# ===========================================================================

def unfilled_plan_fields(entry: dict) -> list:
    """The `SCOREBOARD_PLAN_FIELDS` of one scoreboard entry still holding the
    `REQUIRED_HUMAN_INPUT` sentinel, in table-column order."""
    return [f for f in SCOREBOARD_PLAN_FIELDS if entry.get(f) == REQUIRED_HUMAN_INPUT]


def find_required_human_input_paths(obj: Any, _prefix: str = "") -> list:
    """Every location inside an arbitrary nested dict/list that still holds
    the sentinel, as dotted paths. Used by `RowLockStore.confirm_row()` to
    block confirming a row that was never actually filled in -- deliberately
    generic (not scoreboard-specific) so it also catches, say, a connectivity
    row whose `vip_type` is still unresolved."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(find_required_human_input_paths(v, f"{_prefix}{k}."))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found.extend(find_required_human_input_paths(v, f"{_prefix}{i}."))
    elif obj == REQUIRED_HUMAN_INPUT:
        found.append(_prefix.rstrip("."))
    return found


#: One pre-researched question per scoreboard planning field. `domain` drives
#: `question_queue.route_owner()`, so routing here is a real claim about WHO
#: actually knows the answer, not a single catch-all bucket: the DUT's own
#: reordering/drop/flush/transform behavior is a `designer` question, the
#: transaction field that ties a request to its response is a VIP/protocol
#: question, and where the scoreboard sits plus how long it waits before
#: declaring an orphan are DV-env policy.
#:
#: Every entry sets `affects_pass_fail_verdict`, which is why all nine
#: classify as Tier 3 / blocking rather than being auto-assumed. That is not
#: a hardcoded tier -- it is DERIVED, and it is honest: each of these fields
#: decides whether the scoreboard reports a mismatch at all. Guess `ordering`
#: as in-order on an out-of-order DUT and it reports mismatches that are not
#: real; guess `legal_drop_conditions` too permissively and it stays silent on
#: dropped payloads. Both are verdict-changing, i.e. exactly the silent
#: false-PASS class `question_queue.is_cannot_assume()` exists to stop.
SCOREBOARD_FIELD_QUESTIONS: dict = {
    "endpoint_pairs": {
        "domain": "env",
        "question": ("Which two hierarchy paths does this scoreboard compare -- what is the "
                     "source endpoint and what is the sink endpoint?"),
        "options": [
            {"label": "DUT ingress interface -> DUT egress interface (data passes through the DUT)",
             "rationale": "The common data-integrity shape: payload in one port, out another, DUT in between."},
            {"label": "VIP-driven stimulus port -> DUT internal observation point (bind/probe)",
             "rationale": "Used when the egress is not an external port and must be observed via a bind."},
            {"label": "Two DUT egress interfaces (a fan-out/replication path)",
             "rationale": "Applies when one ingress is replicated to several sinks and each copy must match."},
        ],
        "recommendation": "DUT ingress interface -> DUT egress interface (data passes through the DUT)",
        "assumption_if_unanswered": ("None -- a scoreboard with no stated endpoints has nothing to compare "
                                     "and would pass vacuously on every test."),
    },
    "matching_key": {
        "domain": "vip",
        "question": ("Which transaction field ties a source-side item to its sink-side counterpart "
                     "for this scoreboard?"),
        "options": [
            {"label": "A protocol transaction/tag ID carried end to end",
             "rationale": "Preferred when the protocol guarantees the tag survives the DUT unchanged."},
            {"label": "Address (plus a per-address sequence counter for repeats)",
             "rationale": "Used when no tag survives but the address is preserved; needs the counter to disambiguate rewrites."},
            {"label": "Payload content hash",
             "rationale": "Last resort when neither tag nor address survives; cannot disambiguate legitimately identical payloads."},
        ],
        "recommendation": "A protocol transaction/tag ID carried end to end",
        "assumption_if_unanswered": ("None -- without a matching key the scoreboard cannot pair items "
                                     "and would either match everything or nothing."),
    },
    "ordering": {
        "domain": "dut",
        "question": "Does this path deliver items to the sink strictly in order, or may the DUT reorder them?",
        "options": [
            {"label": "Strictly in-order",
             "rationale": "A single non-reordering datapath; any out-of-order arrival is a real bug the scoreboard must flag."},
            {"label": "Out-of-order permitted within a bounded reorder window",
             "rationale": "Multi-channel/pipelined DUTs reorder legally up to a depth; needs ordering_tolerance_depth."},
            {"label": "Out-of-order permitted with no bound (fully unordered set comparison)",
             "rationale": "Only correct when the protocol genuinely places no ordering guarantee on this path."},
        ],
        "recommendation": "Strictly in-order",
        "assumption_if_unanswered": ("None -- guessing in-order on a reordering DUT produces false FAILs, "
                                     "and guessing unordered on an in-order DUT hides real ordering bugs."),
    },
    "ordering_tolerance_depth": {
        "domain": "dut",
        "question": ("If reordering is legal on this path, how deep is the reorder window the scoreboard "
                     "must tolerate before declaring a mismatch?"),
        "options": [
            {"label": "0 -- no tolerance, ordering is strict",
             "rationale": "The consistent answer when `ordering` is strictly in-order."},
            {"label": "A finite depth set by a real DUT structure (outstanding-transaction limit, "
                      "queue/FIFO depth, number of parallel channels)",
             "rationale": "The reorder window is bounded by whatever DUT structure creates it; cite that structure."},
            {"label": "Unbounded -- compare as an unordered set, no window",
             "rationale": "Only when ordering is genuinely unconstrained; the scoreboard then cannot detect ordering bugs at all."},
        ],
        "recommendation": ("A finite depth set by a real DUT structure (outstanding-transaction limit, "
                           "queue/FIFO depth, number of parallel channels)"),
        "assumption_if_unanswered": ("None -- an unstated window makes 'out-of-order' unimplementable: the "
                                     "scoreboard cannot know how long to hold an unmatched item."),
    },
    "transformation_rules": {
        "domain": "dut",
        "question": ("What transformation does the payload undergo between source and sink -- width "
                     "conversion, packetization/segmentation, or byte-enable/strobe remapping?"),
        "options": [
            {"label": "None -- payload is bit-identical end to end",
             "rationale": "Valid only if the two endpoints have identical data width and framing; confirm, do not assume."},
            {"label": "Width conversion (upsize/downsize) with a stated byte order",
             "rationale": "Any width mismatch between the two interfaces forces this; the byte order is the part that gets it wrong."},
            {"label": "Packetization/segmentation (one source item becomes N sink items, or vice versa)",
             "rationale": "Applies wherever a burst/stream is re-framed; the scoreboard must reassemble before comparing."},
        ],
        "recommendation": "None -- payload is bit-identical end to end",
        "assumption_if_unanswered": ("None -- defaulting to 'no transform' is the specific silent false-PASS "
                                     "this field exists to prevent: the scoreboard would compare two "
                                     "differently-shaped payloads and report whatever the comparison happened to do."),
    },
    "legal_drop_conditions": {
        "domain": "dut",
        "question": "Under what conditions may this path legally drop or refuse an item without it being a bug?",
        "options": [
            {"label": "Never -- every source item must appear at the sink",
             "rationale": "Lossless paths; any missing item is a real failure the scoreboard must flag."},
            {"label": "Backpressure only defers, never drops (items are held, not lost)",
             "rationale": "Credit/ready-valid flow control; the scoreboard must widen its timeout, not permit loss."},
            {"label": "Drops are legal under a stated condition (error-response, overflow, filtered address range)",
             "rationale": "Requires naming the exact condition, so the scoreboard permits only that drop and no other."},
        ],
        "recommendation": "Never -- every source item must appear at the sink",
        "assumption_if_unanswered": ("None -- a too-permissive drop rule makes the scoreboard silently "
                                     "tolerate lost payloads, which is a false PASS."),
    },
    "reset_flush_behavior": {
        "domain": "dut",
        "question": "What happens to in-flight items, on both sides of this scoreboard, when reset asserts?",
        "options": [
            {"label": "Both sides flush -- the scoreboard clears all pending items on reset",
             "rationale": "Standard for a synchronous reset that clears the whole datapath."},
            {"label": "In-flight items survive reset and must still be matched afterwards",
             "rationale": "Applies where a buffer/queue is not reset, or reset is scoped to only part of the path."},
            {"label": "Asymmetric -- one side flushes and the other does not (state the sides)",
             "rationale": "Common across a reset-domain boundary; the asymmetry is what produces orphans after every reset."},
        ],
        "recommendation": "Both sides flush -- the scoreboard clears all pending items on reset",
        "assumption_if_unanswered": ("None -- getting this wrong produces either a phantom orphan storm after "
                                     "every reset, or a scoreboard that silently discards real mismatches."),
    },
    "orphan_unmatched_threshold": {
        "domain": "env",
        "question": "How many unmatched (orphan) items may be outstanding before this scoreboard reports an error?",
        "options": [
            {"label": "0 -- any item unmatched at end-of-test is an error",
             "rationale": "The strictest and usually correct end-of-test check for a lossless path."},
            {"label": "A finite non-zero allowance tied to real pipeline depth",
             "rationale": "Only for genuinely in-flight items at end-of-test; the number must cite the structure that justifies it."},
            {"label": "Report as a warning only, never fail the test",
             "rationale": "Appropriate only for a deliberately lossy/best-effort path; otherwise it disables the check."},
        ],
        "recommendation": "0 -- any item unmatched at end-of-test is an error",
        "assumption_if_unanswered": ("None -- a guessed non-zero threshold silently absorbs real lost "
                                     "transactions up to that count."),
    },
    "orphan_unmatched_timeout": {
        "domain": "env",
        "question": ("How long does the scoreboard wait for an item's counterpart before declaring it an "
                     "orphan, and when is that detection performed?"),
        "options": [
            {"label": "End-of-test sweep only -- no per-item timeout during the run",
             "rationale": "Simplest; catches everything eventually but reports the failure far from its cause."},
            {"label": "A per-item timeout in clock cycles, checked continuously during the run",
             "rationale": "Reports near the cause and catches hangs; the cycle count must come from real DUT latency, not a round number."},
            {"label": "Both -- a per-item timeout during the run plus an end-of-test sweep",
             "rationale": "Catches both slow-path hangs and quietly-lost items; the usual choice when latency is known."},
        ],
        "recommendation": "Both -- a per-item timeout during the run plus an end-of-test sweep",
        "assumption_if_unanswered": ("None -- with no detection timing stated, an item that never arrives may "
                                     "never be reported at all, which is a silent false PASS."),
    },
}

#: The risk context every scoreboard-planning question carries, mirroring
#: `T4_QUESTION_CONTEXT`'s role for T4 bind questions. See
#: `SCOREBOARD_FIELD_QUESTIONS` for why `affects_pass_fail_verdict` is a real
#: derived fact here rather than a hardcoded escalation.
SCOREBOARD_QUESTION_CONTEXT: dict = {"affects_pass_fail_verdict": True}


def scoreboard_field_context_path(scoreboard_id: str, field_name: str) -> str:
    """The stable evidence path one scoreboard field's question is anchored
    to. It is also what `question_queue.make_question_key()` hashes, so the
    SAME unfilled field on the SAME scoreboard always mints the SAME Q-ID
    however many times the plan is regenerated -- that is what keeps the
    queue's repeat-question-rate metric at zero across regenerations."""
    return f"checker_scoreboard_plan/data_integrity_scoreboards/{scoreboard_id}/{field_name}"


def _resolve_question_store(store):
    from . import question_queue
    if isinstance(store, (str, Path)):
        return question_queue.QuestionQueueStore(Path(store))
    return store


def route_unfilled_fields_to_question_queue(store, entry: dict, *, now=None) -> list:
    """Turn every `REQUIRED_HUMAN_INPUT` field of one scoreboard entry into a
    real, persisted question in the SAME queue the T4 bind path uses.

    This is Part C's "an empty field automatically becomes a question-queue
    entry", as executable code rather than a sentinel nobody reads. Each
    question carries the field's own pre-researched 2-3 options, its
    recommendation, and a domain that routes it to whoever actually knows the
    answer (`question_queue.route_owner()`).

    Returns the persisted question records, in table-column order. A record
    normally comes back Tier 3 / OPEN / blocking; it comes back Tier 1 /
    SELF_RESOLVED when a HUMAN has already answered that exact question_key
    before -- the queue's own "once a human answers, never ask again"
    guarantee, which is why regenerating a plan does not re-ask anything."""
    store = _resolve_question_store(store)
    scoreboard_id = entry["scoreboard_id"]
    asked = []
    for field_name in unfilled_plan_fields(entry):
        spec = SCOREBOARD_FIELD_QUESTIONS[field_name]
        asked.append(store.add_question(
            domain=spec["domain"],
            question=spec["question"],
            context_path=scoreboard_field_context_path(scoreboard_id, field_name),
            options=spec["options"],
            recommendation=spec["recommendation"],
            assumption_if_unanswered=spec["assumption_if_unanswered"],
            context=dict(SCOREBOARD_QUESTION_CONTEXT),
            now=now,
        ))
    return asked


def apply_answered_questions(store, entry: dict) -> dict:
    """Fill a scoreboard entry's unfilled fields from HUMAN answers already
    persisted in the question queue's decisions store, returning a new entry.

    This is the read-back half of the loop: `route_unfilled_fields_to_question_queue()`
    asks, a human answers via `QuestionQueueStore.answer_question()` (which
    persists to `decisions.json`/`decisions.md`), and this reads that answer
    back into the planning table so the row can finally be confirmed.

    Only a decision whose current source is `question_queue.HUMAN_DECISION_SOURCE`
    fills a field. A Tier-2 auto-assumption the harness minted for itself
    NEVER does -- that is the same gate `classify_tier()` applies, deliberately
    reused so the harness cannot fill its own mandatory-human-review field with
    its own earlier guess. Answers are stored as the human's literal answer
    string; this function does not coerce them into numbers or re-interpret
    them."""
    from . import question_queue
    store = _resolve_question_store(store)
    filled = dict(entry)
    for field_name in unfilled_plan_fields(entry):
        spec = SCOREBOARD_FIELD_QUESTIONS[field_name]
        key = question_queue.make_question_key(
            spec["domain"], spec["question"],
            scoreboard_field_context_path(entry["scoreboard_id"], field_name))
        decision = store.find_decision(key)
        current = (decision or {}).get("current") or {}
        if current.get("source") == question_queue.HUMAN_DECISION_SOURCE and current.get("answer"):
            filled[field_name] = current["answer"]
    return filled


# ===========================================================================
# T4 -> question queue. `dv_harness/question_queue.py` (Part B) now exists in
# this repo, so this is a real delegation into its QuestionQueueStore, not a
# hand-built dict shaped against Part B's documented schema. The Part-B
# reconciliation flag this section used to carry is therefore closed: the
# Q-ID, the owner routing, the tier classification and the `blocking` flag
# all come from that module's own code, and the entry this returns is a
# persisted, `question_queue.validate_question()`-clean record.
# ===========================================================================

#: The honest default risk context for a T4 bind question. T4 means the bind
#: target was undecidable from ALL FOUR real inputs (DUT instance tree,
#: interface fingerprints, existing binds, VIP topology/config_db) -- and a
#: guessed bind target is exactly the "syntactically legal, structurally
#: wired, WRONG instance" case Gate 3 exists to catch, i.e. one that produces
#: a silent false PASS. So `affects_pass_fail_verdict` is genuinely true for
#: this question class, which is what makes the resulting Tier-3/blocking
#: classification DERIVED from real risk rather than hardcoded. A caller may
#: override any field via `context=` -- doing so is that caller asserting a
#: different fact honestly, the same contract every other evidence dict in
#: this module carries.
T4_QUESTION_CONTEXT: dict = {"affects_pass_fail_verdict": True}


def build_t4_question_queue_entry(
    store, *, domain: str, question: str, context_path: str,
    options: list, recommendation: str, assumption_if_unanswered: str,
    context: Optional[dict] = None, question_key: Optional[str] = None,
    now=None,
) -> dict:
    """Ask one T4 (undecidable-from-any-input) bind/topology question through
    the REAL question queue -- every T4 `BindTierResult` in this module's own
    connectivity classification is expected to route here.

    `store` is a `question_queue.QuestionQueueStore`, or a project-root path
    to build one from. The returned record is that store's own persisted,
    schema-validated question: its `id` is DERIVED by
    `question_queue.make_question_id()` from the question key (a caller
    cannot supply one, which is what keeps the repeat-question-rate=0
    id-derivation guarantee intact), its `owner` comes from
    `question_queue.route_owner()`, and its `tier`/`blocking` come from
    `question_queue.classify_tier()` against `T4_QUESTION_CONTEXT` merged
    with any caller-supplied `context`.

    `options` must be a real pre-researched 2-3 item list, never open-ended
    -- enforced here as a hard length check, not just documentation. Plain
    strings are accepted and normalized to the queue's `{"label": ...}`
    option shape; `recommendation` must be one of those labels (the queue's
    own cross-field rule, checked here first so a caller gets this module's
    own error type instead of a schema traceback)."""
    from . import question_queue  # local import: keeps this module importable
                                  # without pulling in the queue's own deps

    if isinstance(store, (str, Path)):
        store = question_queue.QuestionQueueStore(Path(store))
    try:
        question_queue.route_owner(domain)
    except ValueError:
        raise ConnectivityError("UNKNOWN_QUESTION_DOMAIN", {"domain": domain}) from None
    if not (2 <= len(options) <= 3):
        raise ConnectivityError("OPTIONS_MUST_BE_PRE_RESEARCHED_2_TO_3",
                                 {"context_path": context_path, "options": options})
    normalized = question_queue.normalize_options(options)
    labels = [o["label"] for o in normalized]
    if recommendation not in labels:
        raise ConnectivityError("RECOMMENDATION_MUST_BE_ONE_OF_OPTIONS",
                                 {"recommendation": recommendation, "options": labels})

    merged_context = dict(T4_QUESTION_CONTEXT)
    merged_context.update(context or {})
    return store.add_question(
        domain=domain, question=question, context_path=context_path,
        options=normalized, recommendation=recommendation,
        assumption_if_unanswered=assumption_if_unanswered,
        question_key=question_key, context=merged_context, now=now,
    )
