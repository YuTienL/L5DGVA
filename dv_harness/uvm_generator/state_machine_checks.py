"""dv_harness/uvm_generator/state_machine_checks.py -- the STATE_MACHINE_CHECKS
DSL (checker-sva-generator task, see .work/checker-sva-generator-design-report.md).

GAP CLOSED: `tools/observability/generate_observability_plan.py`'s ASSERTION
branch emitted a literal `1'b1; // TODO: replace with evidence-backed
temporal property` inside every `property`/`assert property` block, for
every target, unconditionally -- zero generation mechanics. This module
generalizes the one REAL, working, protocol-specific state-machine-legality
generator already in this package (`pcie_ltssm_generator.py`'s
`LTSSM_TRANSITIONS` + `validate_transition` + its generated
`ltssm_transition_legal` SV case-statement function, hardcoded to PCIe's own
11 states) into a manifest-driven DSL usable by ANY protocol, for the 3
idioms the design pass judged fully decidable from a finite, currently-
enumerable legal-value/state set plus a legality relation checkable with
only current+immediately-previous-cycle values (Q1 of the 3-question
decision procedure -- see the OBSERVABILITY planner SKILL.md files):

  - "valid_transition_table": generalizes pcie_ltssm_generator's own
    LTSSM_TRANSITIONS -> ltssm_transition_legal shape to any manifest-
    supplied state/transition table (PCIe LTSSM legality, a register
    field's fixed legal-encoding set expressed as a self-transition-only
    table, etc).
  - "mutual_exclusion": generalizes canfd_arbitration_generator.py's
    single-winner-arbitration FACT (confirmed real, no $onehot/$onehot0
    idiom emitted anywhere yet -- grep-confirmed by the design pass) into
    a standard $onehot/$onehot0 property.
  - "legal_value_set": the degenerate transition idiom needing no
    cross-cycle history at all -- a signal's value must always lie in a
    finite legal set.

Same house-DSL conventions as generator.py's own SCOREBOARD_CHECKS/
TRANSACTION_SCOREBOARDS extensions (mirrored deliberately, per this task's
own scope -- see generator.py's `scoreboard()` docstring for the precedent
this follows): a typed `StateMachineCheckError(ValueError)` with a short
SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict; every
non-structural fact requires a non-empty "evidence" string; validation never
guesses or silently falls back to a plausible-looking default for a
malformed/missing required field.

Imported by BOTH `generator.py` (manifest-driven env generation --
`UVMEnvironmentGenerator.assertions()`) and
`tools/observability/generate_observability_plan.py` (plan-driven path) --
one shared validate+emit implementation, per the design's explicit
"one shared emission function" requirement, so the two call sites can never
independently drift on what a given `state_machine_checks` entry compiles
to.

Clock/reset are NOT modeled as new per-entry fields here -- callers resolve
`clk`/`rst` themselves (generator.py reuses its own existing
`m.get('clocks')`/`m.get('resets')` manifest fields, exactly as `tb_top()`
already does; generate_observability_plan.py's plan-driven path does the
same against the plan's own top-level "clocks"/"resets" keys) and pass the
resolved signal names into `emit_check(entry, clk, rst)`.

assertion_id / gate-pointing contract: every compiled assert label is
`<sv_id(assertion_name)>_a`, so `assertion_id == sv_id(assertion_name)` is
always the assert label with its trailing "_a" stripped -- the stable
identifier the already-wired, unmodified
`assertion_vacuity_gate.py`/`assertion_vacuity_and_reachability_gate.py`
(STAGE_GATES["COVERAGE_CLOSURE"]) need to point at a real, DSL-generated
assertion.

RULINGS made closing gaps the design report left underspecified (documented
here, and in .work/checker-sva-generator-implementation-report.md):

  1. `state_signal`'s case-statement parameter TYPE for "valid_transition_table"
     is not modeled by the design's field list (only "state_signal",
     "states", "transitions" are listed) even though its own compiled-code
     sketch shows a `<state_type>` placeholder in the function signature.
     RULING: add an OPTIONAL "state_type" field (default: "logic [31:0]",
     a deliberately generic default consistent with this package's other
     generic-type defaults -- generator.py's `_emit_scoreboard_check`
     defaults an un-decorated field read to plain `int`, and its
     register_decode path defaults to a generic `bit [N:0]` slice type; no
     protocol-general enum type exists to infer from here either). A
     manifest targeting a real protocol with an already-declared SV enum
     type (e.g. a generated `<name>_ltssm_pkg::ltssm_state_e`) sets
     "state_type" to that real type name instead.
  2. The design's `on_violation.message_template` default
     ("%s: illegal value/transition observed", one %s) does not match the
     2-argument $sformatf call the design's own valid_transition_table
     compiled-code sketch shows ($past(state_signal), state_signal)).
     RULING: keep the design's literal default text verbatim (it is
     explicitly a cross-idiom generic default, not per-idiom-tuned) and
     accept that IEEE 1800 $sformatf/$display silently ignore excess
     positional arguments beyond the number of consumed format specifiers
     (not a compile error, not a runtime error) -- exactly the same
     accepted-tradeoff shape generator.py's own scoreboard() docstring
     already documents for its message_template argument-count contract.
     A manifest author who wants the extra values rendered supplies their
     own "message_template" with matching specifiers.
  3. mutual_exclusion/legal_value_set's exact $sformatf argument list is
     not fully spelled out by the design (only valid_transition_table's is
     shown verbatim). RULING: mutual_exclusion passes the single
     concatenated signal-group expression (`{sig1,sig2,...}`) as the sole
     arg; legal_value_set passes the single `value_signal` expression as
     the sole arg -- both are "the runtime-observed value that violated
     the property", the same role $past(state_signal)/state_signal play
     for valid_transition_table.
"""
from __future__ import annotations

from .generator import sv_id

_VALID_KINDS = frozenset({"valid_transition_table", "mutual_exclusion", "legal_value_set"})
_VALID_SEVERITIES = frozenset({"UVM_ERROR", "UVM_WARNING", "UVM_INFO"})
_DEFAULT_MESSAGE_TEMPLATE = "%s: illegal value/transition observed"


class StateMachineCheckError(ValueError):
    """Same typed-error convention as generator.py's
    MalformedScoreboardCheckError/MalformedTransactionScoreboardError: a
    short SCREAMING_SNAKE_CASE `reason` code plus a concrete `detail` dict
    -- a state_machine_checks entry is never silently compiled from a
    guessed/incomplete/malformed manifest entry."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _severity_macro(severity: str) -> str:
    return "`uvm_%s" % severity[len("UVM_"):].lower()


def _validate_common(entry: dict) -> tuple[str, str, str, dict]:
    """Validates the 3 fields every state_machine_checks entry requires
    (assertion_name, kind, evidence) plus the optional on_violation block.
    Returns (assertion_name, kind, evidence, on_violation) where
    on_violation is always a well-formed
    {"severity": <valid UVM severity>, "message_template": <non-empty str>}
    dict (defaults filled in when the whole key, or one of its two
    sub-fields, is absent)."""
    if not isinstance(entry, dict):
        raise StateMachineCheckError("MISSING_ASSERTION_NAME", {"entry": entry})

    assertion_name = entry.get("assertion_name")
    if not assertion_name or not str(assertion_name).strip():
        raise StateMachineCheckError("MISSING_ASSERTION_NAME", {"entry": entry})

    kind = entry.get("kind")
    if kind not in _VALID_KINDS:
        raise StateMachineCheckError("INVALID_STATE_MACHINE_CHECK_KIND", {
            "assertion_name": assertion_name, "kind": kind, "valid_kinds": sorted(_VALID_KINDS),
        })

    evidence = entry.get("evidence")
    if not evidence or not str(evidence).strip():
        raise StateMachineCheckError("MISSING_STATE_MACHINE_CHECK_EVIDENCE", {
            "assertion_name": assertion_name,
        })

    on_violation = dict(entry.get("on_violation") or {})
    severity = on_violation.get("severity", "UVM_ERROR")
    if severity not in _VALID_SEVERITIES:
        raise StateMachineCheckError("INVALID_VIOLATION_SEVERITY", {
            "assertion_name": assertion_name, "severity": severity,
            "valid_severities": sorted(_VALID_SEVERITIES),
        })
    message_template = on_violation.get("message_template") or _DEFAULT_MESSAGE_TEMPLATE
    on_violation = {"severity": severity, "message_template": message_template}

    return str(assertion_name), kind, str(evidence), on_violation


def _emit_valid_transition_table(entry: dict, name: str, on_violation: dict, clk: str, rst: str) -> str:
    state_signal = entry.get("state_signal")
    if not state_signal or not str(state_signal).strip():
        raise StateMachineCheckError("MISSING_STATE_SIGNAL", {"assertion_name": name})

    states = entry.get("states")
    if (not isinstance(states, list) or not states
            or not all(isinstance(s, str) and s.strip() for s in states)
            or len(states) != len(set(states))):
        raise StateMachineCheckError("INVALID_STATES_LIST", {
            "assertion_name": name, "states": states,
        })

    # RULING: the design's field list requires "transitions" but names no
    # reason code for "transitions itself is missing/not-a-dict" (only
    # UNKNOWN_TRANSITION_SOURCE_STATE/UNKNOWN_TRANSITION_TARGET_STATE cover
    # a malformed individual entry within it) -- INVALID_TRANSITIONS_MAP
    # added here, same SCREAMING_SNAKE_CASE convention, for that one gap.
    transitions = entry.get("transitions")
    if not isinstance(transitions, dict) or not transitions:
        raise StateMachineCheckError("INVALID_TRANSITIONS_MAP", {
            "assertion_name": name, "transitions": transitions,
        })
    state_set = set(states)
    for src, targets in transitions.items():
        if src not in state_set:
            raise StateMachineCheckError("UNKNOWN_TRANSITION_SOURCE_STATE", {
                "assertion_name": name, "source_state": src, "known_states": list(states),
            })
        if not isinstance(targets, list):
            raise StateMachineCheckError("UNKNOWN_TRANSITION_TARGET_STATE", {
                "assertion_name": name, "source_state": src, "targets": targets,
            })
        for tgt in targets:
            if tgt not in state_set:
                raise StateMachineCheckError("UNKNOWN_TRANSITION_TARGET_STATE", {
                    "assertion_name": name, "source_state": src, "target_state": tgt,
                    "known_states": list(states),
                })

    state_type = entry.get("state_type", "logic [31:0]")  # RULING #1, see module docstring
    fn_name = "%s_transition_legal" % name

    case_lines = []
    for st in states:  # manifest order preserved -- never re-sorted
        targets = transitions.get(st, [])
        targets_text = ", ".join(targets)
        case_lines.append("    %s: return (to_state inside {%s});" % (st, targets_text))
    case_text = "\n".join(case_lines)

    severity_macro = _severity_macro(on_violation["severity"])
    name_upper = sv_id(name).upper()

    return """function automatic bit %s(%s from_state, %s to_state);
  case (from_state)
%s
    default: return 1'b0;
  endcase
endfunction
property %s_p;
  @(posedge %s) disable iff (!%s)
    $changed(%s) |-> %s($past(%s), %s);
endproperty
%s_a: assert property (%s_p)
  else %s("%s_ILLEGAL_TRANSITION", $sformatf(%s, $past(%s), %s));
""" % (
        fn_name, state_type, state_type,
        case_text,
        name, clk, rst, state_signal, fn_name, state_signal, state_signal,
        name, name, severity_macro, name_upper, _json_str(on_violation["message_template"]),
        state_signal, state_signal,
    )


def _emit_mutual_exclusion(entry: dict, name: str, on_violation: dict, clk: str, rst: str) -> str:
    signals = entry.get("signals")
    if not isinstance(signals, list) or len(signals) < 2:
        raise StateMachineCheckError("INVALID_MUTEX_SIGNAL_LIST", {
            "assertion_name": name, "signals": signals,
        })

    mode = entry.get("mode")
    if mode not in ("exactly_one", "at_most_one"):
        raise StateMachineCheckError("INVALID_MUTEX_MODE", {
            "assertion_name": name, "mode": mode, "valid_modes": ["exactly_one", "at_most_one"],
        })
    onehot_fn = "$onehot" if mode == "exactly_one" else "$onehot0"

    guard = entry.get("guard") or "1'b1"
    signal_concat = "{%s}" % ", ".join(signals)

    severity_macro = _severity_macro(on_violation["severity"])
    name_upper = sv_id(name).upper()

    return """property %s_p;
  @(posedge %s) disable iff (!%s) (%s) |-> %s(%s);
endproperty
%s_a: assert property (%s_p)
  else %s("%s_MUTEX_VIOLATION", $sformatf(%s, %s));
""" % (
        name, clk, rst, guard, onehot_fn, signal_concat,
        name, name, severity_macro, name_upper, _json_str(on_violation["message_template"]),
        signal_concat,
    )


def _emit_legal_value_set(entry: dict, name: str, on_violation: dict, clk: str, rst: str) -> str:
    value_signal = entry.get("value_signal")
    if not value_signal or not str(value_signal).strip():
        raise StateMachineCheckError("MISSING_VALUE_SIGNAL", {"assertion_name": name})

    legal_values = entry.get("legal_values")
    if not isinstance(legal_values, list) or not legal_values:
        raise StateMachineCheckError("INVALID_LEGAL_VALUES_LIST", {
            "assertion_name": name, "legal_values": legal_values,
        })

    guard = entry.get("guard") or "1'b1"
    values_text = ", ".join(str(v) for v in legal_values)

    severity_macro = _severity_macro(on_violation["severity"])
    name_upper = sv_id(name).upper()

    return """property %s_p;
  @(posedge %s) disable iff (!%s) (%s) |-> (%s inside {%s});
endproperty
%s_a: assert property (%s_p)
  else %s("%s_ILLEGAL_VALUE", $sformatf(%s, %s));
""" % (
        name, clk, rst, guard, value_signal, values_text,
        name, name, severity_macro, name_upper, _json_str(on_violation["message_template"]),
        value_signal,
    )


def _json_str(s: str) -> str:
    """Renders a Python string as a double-quoted SV string literal
    (mirrors generator.py's own `json.dumps(message_template)` usage in
    _emit_scoreboard_check/_emit_transaction_scoreboard -- json's string
    escaping is a correct, already-proven-in-this-package superset of SV
    string-literal escaping for the plain ASCII text this DSL's
    message_template fields carry)."""
    import json
    return json.dumps(s)


def emit_check(entry: dict, clk: str = "clk", rst: str = "rst_n") -> str:
    """Validates one state_machine_checks manifest entry in full, then
    compiles it into real SystemVerilog (a `property`/`assert property`
    block, plus a generated `function automatic bit ..._transition_legal`
    for "valid_transition_table"). Raises StateMachineCheckError -- never
    silently skips, guesses, or partially compiles -- on the first
    malformed/missing piece found (dispatch to the per-kind validator only
    happens after the 3 common fields are themselves well-formed).

    `clk`/`rst` are plain SV signal-name strings resolved by the CALLER
    (see this module's own docstring for why no new per-entry clock/reset
    field is introduced here)."""
    assertion_name, kind, _evidence, on_violation = _validate_common(entry)
    name = sv_id(assertion_name)

    if kind == "valid_transition_table":
        return _emit_valid_transition_table(entry, name, on_violation, clk, rst)
    if kind == "mutual_exclusion":
        return _emit_mutual_exclusion(entry, name, on_violation, clk, rst)
    return _emit_legal_value_set(entry, name, on_violation, clk, rst)
