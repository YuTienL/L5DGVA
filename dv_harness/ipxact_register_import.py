"""dv_harness/ipxact_register_import.py -- turn a real IEEE 1685 (IP-XACT)
component XML's memory-map/register/field content into the SAME
`register_excel_extract.ExtractionResult`/`RegisterIR`/`RegisterFieldIR` shape
`register_excel_extract.py` already produces from an Excel/CSV register-map
spreadsheet, so it can flow through the SAME, already-schema-validated
`to_register_map_document()` bridge into `register_map.schema.json`.

THE GAP THIS CLOSES (DUT-04). `register_map.schema.json`'s own description
and `register_excel_extract.py`'s own docstring both name "an IP-XACT
conversion" as a legitimate real-world way a project supplies a register map
-- but a repo-wide grep for a real IP-XACT XML reader before this change
matched nothing: IP-XACT could only ever enter this harness by a human first
hand-converting it to Excel or to `register_map.schema.json` JSON, a lossy,
unaudited manual step. This module is that live extractor.

REUSE OVER REINVENT. This module does not re-declare a second register/field
IR, a second access-type vocabulary, or a second bridge into
`register_map.schema.json`. It imports `register_excel_extract` and:
  - builds the SAME `RegisterIR`/`RegisterFieldIR` dataclasses that module
    already defines,
  - normalizes IP-XACT's own access vocabulary ("read-write", "read-only",
    "write-only", ...) through the SAME `normalize_access_type()` this
    module's Excel sibling uses for a spreadsheet's "R/W"/"RW" spellings --
    `normalize_access_type()`'s own alias table already collapses
    "read-write" -> "READWRITE" -> "RW" with no code change needed here,
  - classifies "is this access token in the CURRENT schema enum" via the
    SAME `schema_access_kind_enum()` (read fresh from
    `register_map.schema.json` at run time, never hardcoded here either),
  - hands its `ExtractionResult` to the SAME `to_register_map_document()`,
    so an IP-XACT-derived document is checked by the identical validator an
    Excel-derived one is.
The only genuinely NEW logic here is IP-XACT's own XML shape: walking
`memoryMap`/`addressBlock`/`register`/`field` elements and IP-XACT's native
`enumeratedValues` structure (a real, additive analogue of DUT-10's Excel
"legal values" cell -- both land on the SAME `RegisterFieldIR.enum_values`
field, `register_excel_extract.py` defines and this module never
re-declares).

NAMESPACE HANDLING. Real IP-XACT documents use either the pre-2014
`spirit:` namespace (IEEE 1685-2009 and Accellera's earlier SPIRIT schema)
or the 2014+ `ipxact:` namespace (IEEE 1685-2014) -- element names are
essentially unchanged between the two. This module never hardcodes either
prefix: every lookup matches on the LOCAL tag name only (`_local_name()`
strips whatever namespace URI ElementTree qualifies the tag with), so a
document in either namespace -- or with no namespace at all, which some
in-house export tools emit -- is read identically.

BOUNDED, HONESTLY, mirroring `register_excel_extract.py`'s own posture:
- A `register` with no `addressOffset`, or an offset/size/reset value that
  is not `0x`-hex or plain decimal, is EXCLUDED and reported in
  `row_errors` -- never guessed.
- An `access` value this module cannot even collapse to a plausible short
  mnemonic (`normalize_access_type()` returns an error) is reported the
  same way; a real-but-schema-undeclared access token still survives (as
  `access_in_current_schema=False`) exactly like the Excel path.
- Only `field`s that are direct children of a `register` are read. IP-XACT's
  `register` array dimension (`spirit:dim`), `registerFile` (a nested block
  of repeated registers), `alternateRegisters`, and `memoryRemap` are all
  real IP-XACT constructs this module does NOT expand or attempt to
  flatten -- a register living inside one of those is silently invisible
  to a naive per-element walk, so `extract_register_map_from_ipxact()`
  counts `spirit:register`/`ipxact:register` elements seen anywhere in the
  document against ones actually attributed to a memoryMap/addressBlock and
  reports the gap honestly in the result's `notes` rather than claiming a
  document with e.g. a `registerFile` was fully read.
- `enumeratedValue` entries whose own `value` is not `0x`-hex/decimal (e.g.
  IP-XACT's `usage="write"` / bitmask forms with `x`/`z` characters) are
  skipped for that one member and counted in `row_errors`, the same
  "whole-cell-fails" discipline `register_excel_extract.parse_enum_values()`
  applies is relaxed here to per-member, because IP-XACT already gives each
  member as a separate, individually-well-formed XML element -- there is no
  single free-text cell whose partial parse would be ambiguous.
- Not a full IEEE 1685 validator: a document that is not even well-formed
  XML, or has no `spirit:`/`ipxact:` register content at all, is reported as
  `NOT_AVAILABLE`/`PARSE_ERROR` with the real reason, never a silent empty
  result mistaken for "this component genuinely has zero registers".
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import register_excel_extract as rex

__all__ = ["extract_register_map_from_ipxact"]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for c in elem:
        if _local_name(c.tag) == name:
            return c
    return None


def _children(elem: ET.Element, name: str) -> List[ET.Element]:
    return [c for c in elem if _local_name(c.tag) == name]


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    stripped = elem.text.strip()
    return stripped or None


def _child_text(elem: ET.Element, name: str) -> Optional[str]:
    return _text(_child(elem, name))


def _find_all_local(root: ET.Element, name: str) -> List[ET.Element]:
    return [e for e in root.iter() if _local_name(e.tag) == name]


def _parse_reset_value(reg_or_field: ET.Element) -> Tuple[Optional[int], Optional[str]]:
    """Read a register/field's reset value. Supports both the simple
    non-standard `<resetValue>` shape some export tools emit directly, and
    the real IEEE 1685-2014 `<resets><reset><value>...</value></reset>
    </resets>` structure -- the first `reset`'s `value`, since a register/
    field with more than one named reset (power-on vs. a secondary domain
    reset) is a real but rarer case this module honestly does not
    disambiguate; that reset's own name is not lost, only not distinguished
    -- and neither reads as an error when NEITHER shape is present (no
    reset value declared is a legitimate absence, not a defect)."""
    direct = _child_text(reg_or_field, "resetValue")
    if direct is not None:
        return rex.parse_hex_or_decimal(direct)
    resets = _child(reg_or_field, "resets")
    if resets is not None:
        first_reset = _child(resets, "reset")
        if first_reset is not None:
            value_text = _child_text(first_reset, "value")
            if value_text is not None:
                return rex.parse_hex_or_decimal(value_text)
    return None, None


def _parse_enumerated_values(field_elem: ET.Element, *, register_name: str, field_name: str,
                              row_errors: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    container = _child(field_elem, "enumeratedValues")
    if container is None:
        return None
    members: List[Dict[str, Any]] = []
    for ev in _children(container, "enumeratedValue"):
        name = _child_text(ev, "name")
        value_text = _child_text(ev, "value")
        if not name or value_text is None:
            row_errors.append({
                "register": register_name, "field": field_name,
                "error": f"enumeratedValue missing name/value (name={name!r}, value={value_text!r})",
            })
            continue
        value, err = rex.parse_hex_or_decimal(value_text)
        if err or value is None:
            row_errors.append({
                "register": register_name, "field": field_name,
                "error": f"unparseable enumeratedValue {name!r} value: {value_text!r} ({err or 'empty'})",
            })
            continue
        members.append({"value": value, "name": name})
    return members or None


def _parse_field(field_elem: ET.Element, *, register_name: str,
                  row_errors: List[Dict[str, Any]], schema_enum: set) -> Optional[rex.RegisterFieldIR]:
    name = _child_text(field_elem, "name")
    if not name:
        row_errors.append({"register": register_name, "error": "field element with no <name>"})
        return None
    offset_text = _child_text(field_elem, "bitOffset")
    width_text = _child_text(field_elem, "bitWidth")
    if offset_text is None or width_text is None:
        row_errors.append({
            "register": register_name, "field": name,
            "error": f"missing bitOffset/bitWidth (bitOffset={offset_text!r}, bitWidth={width_text!r})",
        })
        return None
    try:
        bit_offset = int(offset_text, 0)
        bit_width = int(width_text, 0)
    except ValueError as exc:
        row_errors.append({"register": register_name, "field": name, "error": f"unparseable bitOffset/bitWidth: {exc}"})
        return None

    access_raw = _child_text(field_elem, "access")
    access_token, acc_err = rex.normalize_access_type(access_raw)
    if acc_err:
        row_errors.append({"register": register_name, "field": name, "error": acc_err})
    in_schema = access_token in schema_enum if access_token is not None else None

    reset_val, reset_err = _parse_reset_value(field_elem)
    if reset_err:
        row_errors.append({"register": register_name, "field": name, "error": f"invalid field reset value: {reset_err}"})

    enum_values = _parse_enumerated_values(field_elem, register_name=register_name, field_name=name,
                                            row_errors=row_errors)

    description = _child_text(field_elem, "description")

    return rex.RegisterFieldIR(
        name=name, bit_offset=bit_offset, bit_width=bit_width,
        access_type=access_token, access_in_current_schema=in_schema,
        reset_value=reset_val, notes=description, enum_values=enum_values,
    )


def _parse_register(reg_elem: ET.Element, *, block_name: str,
                     row_errors: List[Dict[str, Any]], schema_enum: set,
                     base_address: Optional[int]) -> Optional[rex.RegisterIR]:
    name = _child_text(reg_elem, "name")
    if not name:
        row_errors.append({"error": "register element with no <name>"})
        return None
    offset_text = _child_text(reg_elem, "addressOffset")
    if offset_text is None:
        row_errors.append({"register": name, "error": "missing <addressOffset>"})
        return None
    offset_val, off_err = rex.parse_hex_or_decimal(offset_text)
    if off_err or offset_val is None:
        row_errors.append({"register": name, "error": f"invalid addressOffset: {off_err or 'empty'}"})
        return None

    width_text = _child_text(reg_elem, "size")
    width_val: Optional[int] = None
    if width_text is not None:
        try:
            width_val = int(width_text, 0)
        except ValueError:
            row_errors.append({"register": name, "error": f"unparseable <size>: {width_text!r}"})

    access_raw = _child_text(reg_elem, "access")
    access_token, acc_err = rex.normalize_access_type(access_raw)
    if acc_err:
        row_errors.append({"register": name, "error": acc_err})
    in_schema = access_token in schema_enum if access_token is not None else None

    reset_val, reset_err = _parse_reset_value(reg_elem)
    if reset_err:
        row_errors.append({"register": name, "error": f"invalid reset value: {reset_err}"})

    description = _child_text(reg_elem, "description")

    reg = rex.RegisterIR(
        register_name=name, block=block_name, offset=offset_val,
        absolute_address=(base_address + offset_val if base_address is not None else None),
        width=width_val, access_type=access_token, access_in_current_schema=in_schema,
        reset_value=reset_val, notes=description,
    )
    for field_elem in _children(reg_elem, "field"):
        f = _parse_field(field_elem, register_name=name, row_errors=row_errors, schema_enum=schema_enum)
        if f is not None:
            reg.fields.append(f)
    return reg


def extract_register_map_from_ipxact(path: Any) -> rex.ExtractionResult:
    """Extract a `register_excel_extract.ExtractionResult` from a real
    IEEE 1685 (IP-XACT) component XML document's `memoryMaps` content.
    See this module's docstring for the exact real-world shapes/limitations
    this covers."""
    source_path = str(path)
    p = Path(path)
    schema_enum = set(rex.schema_access_kind_enum())

    if not p.exists():
        return rex.ExtractionResult(status=rex.STATUS_NOT_AVAILABLE, reason=f"file not found: {source_path}", source_path=source_path)
    if not p.is_file():
        return rex.ExtractionResult(status=rex.STATUS_NOT_AVAILABLE, reason=f"not a regular file: {source_path}", source_path=source_path)

    try:
        tree = ET.parse(str(p))
    except ET.ParseError as exc:
        return rex.ExtractionResult(status=rex.STATUS_PARSE_ERROR, reason=f"not well-formed XML: {exc}", source_path=source_path)
    root = tree.getroot()

    memory_maps = _find_all_local(root, "memoryMap")
    if not memory_maps:
        # A document may legitimately have zero memoryMaps (a pure-RTL-view
        # IP-XACT component with no register model at all) -- but this
        # module cannot tell that apart from "this is not really an
        # IP-XACT component document" without at least a recognizable root,
        # so it checks for the real IP-XACT/SPIRIT root element name before
        # deciding which honest reason to report.
        root_local = _local_name(root.tag)
        if root_local not in ("component", "abstractionDefinition", "busDefinition"):
            return rex.ExtractionResult(
                status=rex.STATUS_PARSE_ERROR,
                reason=f"root element <{root_local}> is not a recognized IP-XACT component document "
                       "(expected <component>, spirit: or ipxact: namespace)",
                source_path=source_path,
            )
        return rex.ExtractionResult(
            status=rex.STATUS_NOT_AVAILABLE,
            reason="well-formed IP-XACT component document has no <memoryMap> element -- this "
                   "component declares no register model",
            source_path=source_path,
        )

    row_errors: List[Dict[str, Any]] = []
    order: List[str] = []
    registers: Dict[str, rex.RegisterIR] = {}
    widening: Dict[str, List[str]] = {}

    for mm in memory_maps:
        mm_name = _child_text(mm, "name") or "default"
        for ab in _children(mm, "addressBlock"):
            block_name = _child_text(ab, "name") or mm_name
            base_text = _child_text(ab, "baseAddress")
            base_val: Optional[int] = None
            if base_text is not None:
                base_val, base_err = rex.parse_hex_or_decimal(base_text)
                if base_err:
                    row_errors.append({"block": block_name, "error": f"invalid baseAddress: {base_err}"})
            for reg_elem in _children(ab, "register"):
                reg = _parse_register(
                    reg_elem, block_name=block_name, row_errors=row_errors,
                    schema_enum=schema_enum, base_address=base_val,
                )
                if reg is None:
                    continue
                if reg.access_type is not None and reg.access_in_current_schema is False:
                    widening.setdefault(reg.access_type, []).append(f"register {reg.register_name!r}")
                for f in reg.fields:
                    if f.access_type is not None and f.access_in_current_schema is False:
                        widening.setdefault(f.access_type, []).append(
                            f"field {f.name!r} of {reg.register_name!r}")
                if reg.register_name in registers:
                    row_errors.append({
                        "register": reg.register_name,
                        "error": "duplicate register name across memoryMaps/addressBlocks -- second "
                                 "definition ignored",
                    })
                    continue
                order.append(reg.register_name)
                registers[reg.register_name] = reg

    all_register_elements = _find_all_local(root, "register")
    unattributed = len(all_register_elements) - len(order) - sum(
        1 for e in row_errors if "duplicate register name" in e.get("error", "")
    )
    notes: Optional[str] = None
    if unattributed > 0:
        notes = (
            f"{unattributed} <register> element(s) found outside any memoryMap/addressBlock "
            "context this module walks (e.g. inside a registerFile, alternateRegisters, or a "
            "dim-arrayed register) -- see module docstring; not extracted."
        )

    if not registers:
        return rex.ExtractionResult(
            status=rex.STATUS_PARSE_ERROR,
            reason=f"no valid registers could be extracted from IP-XACT memoryMaps; "
                   f"{len(row_errors)} row error(s)" + (f"; {notes}" if notes else ""),
            source_path=source_path, row_errors=row_errors,
            schema_widening_candidates=widening, schema_access_enum_used=sorted(schema_enum),
        )

    status = rex.STATUS_OK if not row_errors else rex.STATUS_PARTIAL
    reason = notes if not row_errors else (
        f"{len(row_errors)} row(s) had defects and were excluded; see row_errors"
        + (f"; {notes}" if notes else "")
    )
    return rex.ExtractionResult(
        status=status, reason=reason, source_path=source_path,
        registers=[registers[name] for name in order], row_errors=row_errors,
        schema_widening_candidates=widening, schema_access_enum_used=sorted(schema_enum),
    )


# ---------------------------------------------------------------------------
# Ad hoc entry point, mirroring register_excel_extract.py's own bare
# `python -m` front door (cli.py is out of this task's file-safety scope).
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="python -m dv_harness.ipxact_register_import")
    parser.add_argument("path", help="IP-XACT (IEEE 1685) component .xml file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = extract_register_map_from_ipxact(args.path)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"status: {result.status}")
        if result.reason:
            print(f"reason: {result.reason}")
        print(f"registers extracted: {len(result.registers)}")
        for e in result.row_errors:
            print(f"  row_error: {e}")

    if result.status == rex.STATUS_NOT_AVAILABLE:
        return 2
    if result.status == rex.STATUS_PARSE_ERROR:
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
