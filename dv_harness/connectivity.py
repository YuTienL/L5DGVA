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
# 4-tier confidence system (Part C)
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
PROTOCOL_FINGERPRINTS: dict[str, set[str]] = {
    "AXI": {"AWVALID", "AWREADY", "WLAST", "BRESP"},
    "AXI_LITE": {"AWVALID", "AWREADY", "WVALID", "BVALID"},
    "APB": {"PSEL", "PENABLE", "PWRITE", "PREADY"},
    "AHB": {"HTRANS", "HADDR", "HWRITE", "HREADY"},
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


def match_protocol_fingerprint(port_names: set[str], protocol: str) -> dict:
    """Structural T2 match check for one (module port-set, protocol) pair.
    `matched=True` only when the FULL required signature subset is present
    (a partial hit is reported as `matched=False` with `missing_signals`
    listed, never rounded up to a match)."""
    required = PROTOCOL_FINGERPRINTS.get(protocol.upper())
    if required is None:
        return {"matched": False, "protocol": protocol, "reason": "UNKNOWN_PROTOCOL_FINGERPRINT",
                "matched_signals": [], "missing_signals": sorted(required or [])}
    present = {sig for sig in required if any(sig in p for p in port_names)}
    missing = required - present
    return {
        "matched": not missing,
        "protocol": protocol.upper(),
        "matched_signals": sorted(present),
        "missing_signals": sorted(missing),
    }


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
# Connectivity matrix (required output artifact)
# ===========================================================================

MATRIX_COLUMNS = [
    "dut_instance", "interface", "direction", "role", "vip_type",
    "count", "active_passive", "bind_target", "tier",
]


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


def build_connectivity_matrix(rows: list) -> list[dict]:
    """Fixed-column JSON form of the required matrix. `rows` may be
    `ConnectivityRow` instances or already-plain dicts (accepted so a
    caller re-loading a persisted manifest can re-render without
    reconstructing dataclasses)."""
    out = []
    for r in rows:
        d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
        out.append({col: d.get(col) for col in MATRIX_COLUMNS})
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


def count_vip_instances_in_matrix(rows: list) -> int:
    """How many matrix rows actually carry a VIP instance -- the `vip_instance
    _count` term of the self-check identity, read off the real matrix rather
    than supplied by the caller as a separate (and therefore forgeable)
    number."""
    return sum(
        1 for r in build_connectivity_matrix(rows)
        if str(r.get("vip_type") or "").strip().upper() not in NO_VIP_MARKERS
    )


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
    bool/warning) exactly as that function does."""
    exemptions = list(exemptions or [])
    verified = len(build_connectivity_matrix(rows))
    vip = count_vip_instances_in_matrix(rows)
    verify_self_check_identity(verified, vip, exemptions)
    return {
        "verified_interface_count": verified,
        "vip_instance_count": vip,
        "exemption_count": len(exemptions),
        "exemptions": exemptions,
        "identity_holds": True,
    }


def write_connectivity_manifest(path, rows: list, metadata: Optional[dict] = None,
                                exemptions: Optional[list] = None) -> dict:
    """Persist the connectivity matrix. The self-check identity and role
    provenance are verified BEFORE anything is written, so a manifest file
    that exists on disk is one that reconciled -- a matrix with an
    unexplained no-VIP interface, or a hand-typed naming-derived role,
    raises instead of silently producing an authoritative-looking artifact."""
    assert_role_provenance(rows)
    self_check = verify_matrix_self_check_identity(rows, exemptions)
    manifest = {
        "generated_at": _utcnow_iso(),
        "metadata": metadata or {},
        "columns": MATRIX_COLUMNS,
        "rows": build_connectivity_matrix(rows),
        "self_check": self_check,
    }
    Path(path).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def render_hierarchy_diagram(rows: list) -> str:
    """Minimal mermaid-flowchart rendering of DUT instance -> bind target ->
    VIP type, one edge per matrix row, tier annotated on the edge label --
    the second of Part C's 3 final artifacts (matrix / hierarchy diagram /
    question queue). Deliberately simple (a topology overview, not a
    full schematic) -- the matrix itself remains the authoritative detail
    source."""
    matrix = build_connectivity_matrix(rows)
    lines = ["flowchart LR"]
    for i, r in enumerate(matrix):
        dut_node = f'D{i}["{r["dut_instance"]}<br/>{r["interface"]}"]'
        vip_node = f'V{i}["{r["vip_type"]}<br/>({r["active_passive"]})"]'
        lines.append(f"  {dut_node} -->|{r['tier']}: {r['bind_target']}| {vip_node}")
    return "\n".join(lines)


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

class RowLockStore:
    """JSON-file-backed lock store for per-row (interface row or
    scoreboard-plan-entry row) human confirmation. A confirmed row is
    LOCKED: `diff_rows_needing_reconfirmation()` will not re-surface it
    unless its content actually changed since the last confirmation --
    keeping confirmation cost from scaling linearly with project size on
    every regeneration, per Part C."""

    def __init__(self, path):
        self.path = Path(path)
        self._locks: dict[str, dict] = {}
        if self.path.exists():
            self._locks = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._locks, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def confirm_row(self, row_id: str, row_content: dict) -> None:
        """Lock one row as human-confirmed.

        Refuses (hard `ConnectivityError`, never a warning) to confirm a row
        that still contains the literal `REQUIRED_HUMAN_INPUT` sentinel
        anywhere in its content. Confirming such a row is the precise failure
        this whole mechanism exists to prevent: it would mark a scoreboard
        plan row with an unfilled ordering/legal-drop as reviewed-and-locked,
        after which `diff_rows_needing_reconfirmation()` would stop
        re-surfacing it and the unanswered field would never be seen again.
        Fill the field -- directly, or via `apply_answered_questions()` once a
        human has answered the queue entry `route_unfilled_fields_to_question_queue()`
        raised -- and confirm then."""
        unfilled = find_required_human_input_paths(row_content)
        if unfilled:
            raise ConnectivityError(
                "CANNOT_CONFIRM_ROW_WITH_UNFILLED_REQUIRED_HUMAN_INPUT",
                {"row_id": row_id, "unfilled_paths": unfilled},
            )
        self._locks[row_id] = {
            "content_hash": _content_hash(row_content),
            "content": row_content,
            "confirmed_at": _utcnow_iso(),
        }
        self.save()

    def is_locked(self, row_id: str) -> bool:
        return row_id in self._locks

    def locked_hash(self, row_id: str) -> Optional[str]:
        entry = self._locks.get(row_id)
        return entry["content_hash"] if entry else None

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
    normalized = [o if isinstance(o, dict) else {"label": str(o)} for o in options]
    labels = [o.get("label") for o in normalized]
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
