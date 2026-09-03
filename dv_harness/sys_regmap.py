"""dv_harness/sys_regmap.py -- loader, validator and mode-determining-bit
classifier for sys_regmap.json, the asset-processing table's row-8 artifact:
"Global register file -> sys_regmap.json: clock/reset/mux/pinmux control bits
-> mode-determining bits".

Why a separate file from register_map.schema.json (the question this module
exists to answer): register_map.schema.json describes the DUT's own
functional registers and its `blocks` array is flat and undifferentiated --
there is no field on it that can express "this block is the clock-enable /
pinmux / PHY-select block". So there was no way to identify a mode-determining
bit at all, which is why row 8 was BLOCKED at the artifact level and why
connectivity.py's Gate 2 had no register-enable precondition of any kind.
sys_regmap.schema.json adds exactly the two fields that were missing -- a
block-level `kind` and a field-level `control_kind` -- and this module turns
them into the real precondition set that `dv_harness/init_seq.py` then
evaluates a Gate-2 result against.

Same input-contract discipline as register_map.schema.json: the content is
transcribed from a real chip-level programming guide or exported from a real
system RAL model. This module never invents a control bit, and never guesses
which interface a bit governs -- an undocumented `required_value` stays null
and an unscoped bit is treated as governing EVERY interface, because assuming
a mode-determining bit is irrelevant is the unsafe direction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "sys_regmap.schema.json"

# Every control_kind except this one is mode-determining -- see the schema's
# own description of the field. Written as "everything but" rather than as an
# allow-list so that adding a new control_kind to the schema defaults to
# SAFE (treated as mode-determining) instead of being silently ignored.
NOT_MODE_DETERMINING = "not_mode_determining"


class SysRegmapValidationError(ValueError):
    """A sys_regmap document fails sys_regmap.schema.json validation. Raised
    rather than returning None/False, matching env_manifest.py's
    RegisterMapValidationError fail-closed discipline: dut-mode preconditions
    must never be computed from content that did not actually validate."""


def validate_sys_regmap(doc: dict) -> None:
    """Validate `doc` against sys_regmap.schema.json. Raises
    SysRegmapValidationError on any violation."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise SysRegmapValidationError(
            "jsonschema package is not installed; cannot validate against "
            "sys_regmap.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise SysRegmapValidationError("sys_regmap.schema.json validation failed:\n" + "\n".join(lines))


def load_sys_regmap(path) -> dict:
    """Load and validate a sys_regmap.json from disk."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_sys_regmap(doc)
    return doc


def absolute_address(block: dict, register: dict) -> int:
    """Real absolute address of a system-control register, computed from the
    block base plus the register offset -- the same computation mcp/verbs.py
    already performs for the DUT register map, deliberately identical so the
    two maps behave the same way for a consumer."""
    return int(block["base_address"], 16) + int(register["address_offset"], 16)


def iter_mode_determining_bits(doc: dict, interface: Optional[str] = None):
    """Yield one record per mode-determining bit in `doc`, optionally
    filtered to those governing `interface`.

    Scoping rule (deliberate, and the safe direction): a bit whose
    `governs_interfaces` list is empty or absent is treated as governing
    EVERY interface. A real programming guide often states a global
    clock-enable without enumerating every downstream consumer; dropping such
    a bit from an interface's precondition set would silently produce a
    Gate-2 PASS/FAIL computed against an incomplete precondition set, which
    is exactly the failure this artifact exists to prevent."""
    for block in doc.get("blocks", []):
        for register in block.get("registers", []):
            for field in register.get("fields", []) or []:
                kind = field.get("control_kind")
                if kind == NOT_MODE_DETERMINING:
                    continue
                governs = field.get("governs_interfaces") or []
                scoped_to_all = not governs
                if interface is not None and not scoped_to_all and interface not in governs:
                    continue
                yield {
                    "block": block["name"],
                    "block_kind": block["kind"],
                    "register": register["name"],
                    "field": field["name"],
                    "control_kind": kind,
                    "absolute_address": hex(absolute_address(block, register)),
                    "bit_offset": field["bit_offset"],
                    "bit_width": field["bit_width"],
                    "required_value": field.get("required_value"),
                    "governs_interfaces": list(governs),
                    "applies_to_all_interfaces": scoped_to_all,
                }


def mode_determining_bits(doc: dict, interface: Optional[str] = None) -> list:
    """List form of `iter_mode_determining_bits()`, sorted by
    (absolute_address, bit_offset) for a stable, diffable order."""
    bits = list(iter_mode_determining_bits(doc, interface=interface))
    bits.sort(key=lambda b: (int(b["absolute_address"], 16), b["bit_offset"]))
    return bits


def required_preconditions(doc: dict, interface: str) -> list:
    """The subset of `interface`'s mode-determining bits that carry a
    documented `required_value` -- i.e. the bits a Gate-2 precondition check
    can actually VERIFY rather than merely list.

    A mode-determining bit with a null required_value is intentionally NOT
    returned here: the programming guide did not document what it must be, so
    checking it would mean inventing the expected value. Those bits are still
    reported by `mode_determining_bits()` so they stay visible to a human
    reviewer instead of disappearing."""
    return [b for b in mode_determining_bits(doc, interface=interface)
            if b.get("required_value") is not None]


def unverifiable_bits(doc: dict, interface: str) -> list:
    """The complement of `required_preconditions()`: mode-determining bits
    with no documented required value. Surfaced explicitly so a Gate-2
    precondition result can state honestly how much of the mode it could not
    verify, rather than implying full coverage."""
    return [b for b in mode_determining_bits(doc, interface=interface)
            if b.get("required_value") is None]
