"""dv_harness/init_seq.py -- loader/validator for init_seq.yaml (the
asset-processing table's row-10 artifact) AND the Gate-2 precondition
evaluator that rows 8 and 10 both feed.

Row 10 is "IP programming guide -> init_seq.yaml: register write order and
wait conditions -> directed test, connectivity check". Both named consumers
are implemented here:

  * connectivity check -- `evaluate_gate2_preconditions()` and
    `evaluate_zero_time_connectivity_gated()`.
  * directed test -- `directed_test_steps()`.

THE GAP THIS CLOSES. `connectivity.evaluate_zero_time_connectivity()` checks
three things: the clock toggles, reset deasserts, and the required signals
are non-X at time 0. It has no register-enable precondition of any kind, so
all three of its failure modes are ambiguous:

    a clock that never toggles because the CRU clock-enable bit was never
    written looks EXACTLY like a clock that never toggles because the bind is
    mounted on the wrong instance.

The first is a stimulus/bring-up defect, the second is a connectivity defect,
and they have completely different fixes. Reporting the first as a Gate-2
connectivity FAIL sends a debugger to re-examine a bind that was correct all
along. This module supplies the missing precondition so the two are
distinguishable, by joining sys_regmap.json's mode-determining bits (which
bits must hold which values for this interface to be clocked, out of reset
and muxed to the pins) with init_seq.yaml's documented write ORDER.

It deliberately does NOT modify connectivity.py: it imports that module's own
real `GateStatus`/`GateResult` and calls its real
`evaluate_zero_time_connectivity()`, so there is one Gate-2 implementation in
this repo and this is a precondition layer over it, not a competing second
gate.

HONESTY CONTRACT, matching env_manifest.py's. Precondition evaluation needs
real OBSERVED register values (read back from a live run, or from a real
register-access trace). With none supplied the result is NOT_AVAILABLE with
the real capture recipe -- never a fabricated "preconditions met" that would
make a Gate-2 FAIL look explained.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import sys_regmap as _sys_regmap
from .connectivity import GateResult, GateStatus, evaluate_zero_time_connectivity

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "init_seq.schema.json"

# Which step kinds require which fields. Enforced by validate_init_seq()
# beyond what JSON Schema expresses, because the requirement is conditional
# on `kind` -- a wait_condition with no timeout_us is a hang, and a write
# with no value is meaningless, but neither is expressible as a flat
# `required` list in the schema without an if/then chain that would be far
# harder for a human to read than this table.
_REQUIRED_BY_KIND = {
    "write": ("block", "register", "value"),
    "read_check": ("block", "register", "value"),
    "wait_us": ("wait_us",),
    "wait_condition": ("block", "register", "value", "timeout_us"),
}


class InitSeqValidationError(ValueError):
    """An init_seq document fails validation -- schema, step ordering, or a
    kind-specific required field. Raised rather than returning False so a
    caller cannot run a directed test or a precondition check against a
    sequence whose order was never actually verified."""


def validate_init_seq(doc: dict) -> None:
    """Validate `doc` against init_seq.schema.json, then enforce the two
    constraints JSON Schema cannot express cleanly: contiguous ascending
    step indices, and the kind-conditional required fields in
    _REQUIRED_BY_KIND.

    The index check exists because array order IS the required write order
    for this artifact. If a step is deleted while editing and the remaining
    `index` values are left as 0,1,3, that is a real signal that a
    programming-guide step was dropped -- silently renumbering it would hide
    a missing bring-up write, which is precisely the class of defect this
    file exists to prevent."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise InitSeqValidationError(
            "jsonschema package is not installed; cannot validate against "
            "init_seq.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise InitSeqValidationError("init_seq.schema.json validation failed:\n" + "\n".join(lines))

    steps = doc.get("steps", [])
    expected = list(range(len(steps)))
    actual = [s["index"] for s in steps]
    if actual != expected:
        raise InitSeqValidationError(
            f"init_seq step indices must be contiguous and ascending from 0; got {actual}, "
            f"expected {expected}. A gap usually means a programming-guide step was deleted -- "
            "fix the sequence rather than renumbering around the gap."
        )
    for step in steps:
        for field in _REQUIRED_BY_KIND[step["kind"]]:
            if step.get(field) is None:
                raise InitSeqValidationError(
                    f"init_seq step {step['index']} of kind {step['kind']!r} requires "
                    f"{field!r}, which is missing or null"
                )


def load_init_seq(path) -> dict:
    """Load and validate an init_seq document from a real .yaml (or .json)
    file. YAML is parsed with `yaml.safe_load` -- never `yaml.load` -- so a
    hand-edited sequence file can never execute arbitrary Python during a
    load that happens on every connectivity check."""
    text = Path(path).read_text(encoding="utf-8")
    if str(path).lower().endswith((".yaml", ".yml")):
        import yaml
        doc = yaml.safe_load(text)
    else:
        doc = json.loads(text)
    validate_init_seq(doc)
    return doc


# ---------------------------------------------------------------------------
# consumer 1 (row 10, "directed test")
# ---------------------------------------------------------------------------

def directed_test_steps(doc: dict, sys_regmap_doc: Optional[dict] = None) -> list:
    """Flatten the sequence into concrete directed-test steps, resolving each
    register reference to a real absolute address through sys_regmap.json
    when one is supplied.

    Address resolution is deliberately by NAME through the register map
    rather than by a hand-typed address in the init_seq file itself (the
    schema has no address field at all). A bring-up sequence that hardcodes
    addresses silently rots the moment the address map moves; resolving
    through the map means a renamed or removed register is a hard error here
    instead of a write to a stale address at run time."""
    lookup = {}
    if sys_regmap_doc is not None:
        for block in sys_regmap_doc.get("blocks", []):
            for reg in block.get("registers", []):
                lookup[(block["name"], reg["name"])] = (
                    hex(_sys_regmap.absolute_address(block, reg)),
                    {f["name"]: f for f in (reg.get("fields") or [])},
                )
    out = []
    for step in doc.get("steps", []):
        entry = {
            "index": step["index"],
            "kind": step["kind"],
            "description": step.get("description"),
            "block": step.get("block"),
            "register": step.get("register"),
            "field": step.get("field"),
            "value": step.get("value"),
            "wait_us": step.get("wait_us"),
            "timeout_us": step.get("timeout_us"),
            "absolute_address": None,
            "bit_offset": None,
            "bit_width": None,
        }
        key = (step.get("block"), step.get("register"))
        if sys_regmap_doc is not None and step.get("block") and step.get("register"):
            if key not in lookup:
                raise InitSeqValidationError(
                    f"init_seq step {step['index']} references {key} which does not exist in the "
                    "supplied sys_regmap -- a bring-up step pointing at a register the system "
                    "register map does not define is a real error, not something to skip"
                )
            addr, fields = lookup[key]
            entry["absolute_address"] = addr
            fname = step.get("field")
            if fname:
                if fname not in fields:
                    raise InitSeqValidationError(
                        f"init_seq step {step['index']} references field {fname!r} of "
                        f"{key}, which that register does not define"
                    )
                entry["bit_offset"] = fields[fname]["bit_offset"]
                entry["bit_width"] = fields[fname]["bit_width"]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# consumer 2 (rows 8+10, "connectivity check") -- the Gate-2 precondition
# ---------------------------------------------------------------------------

def _extract_field_value(observed_word: str, bit_offset: int, bit_width: int) -> str:
    """Pull one field's value out of an observed whole-register value, so a
    caller supplies real register reads (what a run can actually produce)
    rather than pre-sliced field values (which would push the slicing work,
    and the chance of getting it wrong, onto every caller)."""
    word = int(observed_word, 16)
    mask = (1 << bit_width) - 1
    return hex((word >> bit_offset) & mask)


def evaluate_gate2_preconditions(
    sys_regmap_doc: dict, interface: str,
    observed_register_values: Optional[dict] = None,
    init_seq_doc: Optional[dict] = None,
) -> GateResult:
    """Evaluate whether `interface`'s mode-determining bits actually hold the
    values the programming guide requires.

    `observed_register_values` maps an absolute address hex string ->
    the observed whole-register value hex string, as read back from a real
    run. With none supplied the result is NOT_AVAILABLE carrying the real
    capture recipe -- this function never assumes preconditions were met.

    Returns a `GateResult` using connectivity.py's own `GateStatus` enum, so
    a precondition result slots into the existing gate-report machinery
    (`render_bind_verification_status_markdown()` and friends) with no
    parallel status vocabulary:
      * PASS -- every verifiable required bit holds its required value.
      * FAIL -- at least one does not: the interface is genuinely not in the
        mode the programming guide requires.
      * NOT_AVAILABLE -- no observed values supplied (tooling/capture gap).
      * PENDING -- there are mode-determining bits for this interface but
        NONE carries a documented required value, so there is nothing to
        verify yet. Deliberately not PASS: "we checked nothing" must never
        be reported with the same status as "we checked everything and it
        was fine", per GateStatus's own four-distinct-meanings contract.
    """
    required = _sys_regmap.required_preconditions(sys_regmap_doc, interface)
    unverifiable = _sys_regmap.unverifiable_bits(sys_regmap_doc, interface)
    base_detail = {
        "interface": interface,
        "required_bit_count": len(required),
        "unverifiable_bit_count": len(unverifiable),
        "unverifiable_bits": [f"{b['block']}.{b['register']}.{b['field']}" for b in unverifiable],
        "init_seq_step_count": len((init_seq_doc or {}).get("steps", [])) if init_seq_doc else None,
    }

    if observed_register_values is None:
        return GateResult(
            gate="gate2_preconditions_mode_bits", status=GateStatus.NOT_AVAILABLE,
            detail={**base_detail,
                    "reason": "no observed register values supplied -- cannot verify mode-determining bits",
                    "instructions": (
                        "Read back each address listed in required_bits after running the init "
                        "sequence (a real register-access trace, a UVM RAL mirror dump, or a "
                        "backdoor peek), and pass {absolute_address_hex: observed_word_hex} as "
                        "observed_register_values. Never fabricate these values to make the gate pass."),
                    "required_bits": [
                        {"name": f"{b['block']}.{b['register']}.{b['field']}",
                         "absolute_address": b["absolute_address"],
                         "required_value": b["required_value"]} for b in required]},
        )

    if not required:
        return GateResult(
            gate="gate2_preconditions_mode_bits", status=GateStatus.PENDING,
            detail={**base_detail,
                    "reason": (
                        f"interface {interface!r} has {len(unverifiable)} mode-determining bit(s) but none "
                        "carries a documented required_value, so nothing can be verified yet. Transcribe "
                        "the required values from the programming guide into sys_regmap.json to make this "
                        "checkable; reported PENDING rather than PASS because nothing was actually checked.")
                    if unverifiable else (
                        f"no mode-determining bits are declared for interface {interface!r} in the supplied "
                        "sys_regmap -- either this interface genuinely has none, or the system register map "
                        "does not yet cover it. Reported PENDING rather than PASS because those two cases "
                        "are not distinguishable from this file alone."),
                    },
        )

    violations, unread = [], []
    for bit in required:
        observed_word = observed_register_values.get(bit["absolute_address"])
        if observed_word is None:
            unread.append({"name": f"{bit['block']}.{bit['register']}.{bit['field']}",
                           "absolute_address": bit["absolute_address"]})
            continue
        actual = _extract_field_value(observed_word, bit["bit_offset"], bit["bit_width"])
        if int(actual, 16) != int(bit["required_value"], 16):
            violations.append({
                "name": f"{bit['block']}.{bit['register']}.{bit['field']}",
                "control_kind": bit["control_kind"],
                "absolute_address": bit["absolute_address"],
                "required_value": bit["required_value"],
                "observed_value": actual,
                "observed_register_word": observed_word,
            })

    if unread:
        return GateResult(
            gate="gate2_preconditions_mode_bits", status=GateStatus.NOT_AVAILABLE,
            detail={**base_detail, "violations": violations, "unread_bits": unread,
                    "reason": (f"{len(unread)} required mode-determining bit(s) have no observed value "
                               "in observed_register_values; the precondition set is incomplete so no "
                               "PASS/FAIL verdict is claimed")},
        )

    status = GateStatus.FAIL if violations else GateStatus.PASS
    return GateResult(
        gate="gate2_preconditions_mode_bits", status=status,
        detail={**base_detail, "violations": violations,
                "verified_bits": [f"{b['block']}.{b['register']}.{b['field']}" for b in required]},
    )


def evaluate_zero_time_connectivity_gated(
    trace, clock_signal: str, reset_signal: str, required_nonx_signals: list,
    *, sys_regmap_doc: dict, interface: str,
    observed_register_values: Optional[dict] = None,
    init_seq_doc: Optional[dict] = None, reset_active_low: bool = True,
) -> dict:
    """Run the REAL Gate 2 (`connectivity.evaluate_zero_time_connectivity()`,
    unmodified) together with its mode-bit precondition, and return both plus
    an explicit interpretation.

    The `interpretation` field is the whole point of this function. When
    Gate 2 FAILs and the preconditions also FAIL, the honest reading is
    PRECONDITION_NOT_MET -- the interface was never clocked/released/muxed,
    so the Gate-2 failure is expected and says nothing about whether the bind
    is correct. Reporting that case as a connectivity failure sends a
    debugger to re-examine a bind that may be perfectly correct. Only a
    Gate-2 FAIL with preconditions PASSing is a genuine
    CONNECTIVITY_FAILURE.

    Returns a plain dict rather than a single GateResult because collapsing
    two independently-meaningful verdicts into one status is exactly the
    conflation this module exists to undo."""
    gate2 = evaluate_zero_time_connectivity(
        trace, clock_signal, reset_signal, required_nonx_signals,
        reset_active_low=reset_active_low,
    )
    pre = evaluate_gate2_preconditions(
        sys_regmap_doc, interface,
        observed_register_values=observed_register_values, init_seq_doc=init_seq_doc,
    )

    if gate2.status is GateStatus.PASS:
        interpretation = "CONNECTIVITY_OK"
        rationale = ("Gate 2 passed: clock toggles, reset deasserts, no X at t0. "
                     f"Precondition status was {pre.status.value}.")
    elif pre.status is GateStatus.FAIL:
        interpretation = "PRECONDITION_NOT_MET"
        rationale = (
            "Gate 2 failed AND the interface's mode-determining bits do not hold their required "
            "values, so the interface was never clocked/released/muxed in the first place. This "
            "is a bring-up/stimulus defect, NOT evidence that the bind is wrong -- fix the init "
            "sequence and re-run before touching the bind."
        )
    elif pre.status is GateStatus.PASS:
        interpretation = "CONNECTIVITY_FAILURE"
        rationale = (
            "Gate 2 failed while every verifiable mode-determining bit holds its required value, "
            "so the interface IS in the correct mode and the failure is genuinely a connectivity "
            "problem -- the bind target, its port connections, or the clock/reset source."
        )
    else:
        interpretation = "INDETERMINATE"
        rationale = (
            f"Gate 2 failed but precondition status is {pre.status.value}, so it cannot be "
            "determined whether the interface was ever in the required mode. Capture the "
            "mode-bit values (see the precondition result's instructions) before concluding "
            "anything about the bind."
        )

    return {
        "gate2": gate2, "preconditions": pre,
        "interpretation": interpretation, "rationale": rationale,
    }
