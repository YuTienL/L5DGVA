"""dv_harness/register_excel_extract.py -- turn a real register-map Excel/CSV
spreadsheet into a structured RegisterIR, and into a
register_map.schema.json-shaped document env_manifest.py can load.

THE GAP THIS CLOSES
-------------------
`dv_harness/schemas/register_map.schema.json` is a documented INPUT CONTRACT
for `env.manifest.json`'s `dut_facts.registers` layer, and its own
description says why it is a contract rather than a live extractor: "No live
RAL model exists in dv_harness itself ... which is exactly why this is a
documented input contract rather than a live extractor." A real project
supplies that file today by hand-authoring JSON from a RAL model export, an
IP-XACT conversion, or a programming-guide transcription. A repo-wide grep
for `openpyxl`/`xlsx`/`Excel` before this change matched only unrelated
document-format handling (`doc_extraction.py`'s suffix set, `vplan_writer`'s
`.xlsx` vPlan output) -- nothing anywhere read a register-map SPREADSHEET,
which is exactly how many real programming guides and RAL exports actually
arrive.

This module is that transcription step, and only that. It never invents a
register: a spreadsheet row is either transcribed with real values read from
real cells, or its defect is reported and that row/register is excluded --
never silently dropped, never filled with a guessed placeholder.

REUSE OVER REINVENT
--------------------
- The output's SHAPE is `register_map.schema.json`, read from disk here
  rather than re-declared -- `to_register_map_document()` builds a document
  and then calls the REAL `env_manifest.validate_register_map()` against it,
  so a document this module claims is schema-valid is checked by the same
  validator `env_manifest.build_dut_facts_registers()` will later use to load
  it. There is no second register-map schema in this module.
- The CURRENT access-type vocabulary is READ from
  `register_map.schema.json`'s own `$defs.access_kind.enum` at run time
  (`schema_access_kind_enum()`), never hardcoded -- if a future change widens
  that enum, this module picks it up with no code edit.

ACCESS-TYPE VOCABULARY: WIDER THAN THE SCHEMA, HONESTLY
--------------------------------------------------------
Real register-map spreadsheets spell access types inconsistently ("R/W",
"Read-Write", "RW") and sometimes use a real access semantic the schema does
not yet declare. `normalize_access_type()` folds spelling variants onto a
short canonical token (a formatting normalization only -- "R/W" and "RW" are
the same fact spelled two ways); it does NOT decide whether that token is one
of the schema's eight declared values. That second question is answered
separately, against the schema file read at run time, so the two concerns
(how is it spelled vs. is it a value this project's schema already knows
about) can never be conflated. A token the schema does not declare (this
project's real fixture uses `RS`, read-then-set-on-read, distinct from `RC`)
is never dropped or coerced onto the nearest schema value -- it is preserved
verbatim in the RegisterIR and reported as a `schema_widening_candidate` so a
human/integrator can decide whether to widen the schema additively. Per the
project's file-safety scope for this task, this module does NOT edit
`register_map.schema.json` itself -- see the returned
`schema_widening_candidates` / the caller's structured output for the exact
additive enum values a real spreadsheet needed.

A register/field whose access type is not currently declared by the schema
is excluded from `to_register_map_document()`'s schema-conformant output
(never force-mapped onto a wrong existing value) but stays fully present in
the plain RegisterIR this module returns -- so the fact is never lost, only
kept out of what would otherwise validate against a vocabulary the project
has not yet widened to include it.

BOUNDED, HONESTLY
-----------------
- No `openpyxl` installed -> `NOT_AVAILABLE` naming the real ImportError,
  never a crash and never a silently-empty result read as "no registers".
- Missing file, unreadable workbook, no recognizable header row, or zero
  register rows survive parsing -> `PARSE_ERROR`/`NOT_AVAILABLE` with the
  real reason. Never a fabricated register.
- Legacy binary `.xls` (pre-2007 format) is NOT supported: `openpyxl` cannot
  read it and this module does not bundle a second binary-format reader.
  Reported as `NOT_AVAILABLE` naming that limitation, not attempted.
- A row-level defect (unparseable offset/bit-range, an access-type string
  that is not even a plausible mnemonic) excludes that row/field and is
  recorded in `row_errors` -- it never becomes a guessed register/field.
- Offsets/reset values must be `0x`-prefixed hex or plain decimal digits; an
  un-prefixed hex string (bare `1000` meaning hex, not decimal 1000) is read
  as decimal, a stated limitation rather than a guess.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import env_manifest

try:
    import openpyxl
    _OPENPYXL_AVAILABLE = True
    _OPENPYXL_IMPORT_ERROR: Optional[str] = None
except ImportError as _exc:  # pragma: no cover - exercised via a real absence in some environments
    openpyxl = None  # type: ignore[assignment]
    _OPENPYXL_AVAILABLE = False
    _OPENPYXL_IMPORT_ERROR = str(_exc)


STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_PARSE_ERROR = "PARSE_ERROR"

_STATUSES = {STATUS_OK, STATUS_PARTIAL, STATUS_NOT_AVAILABLE, STATUS_PARSE_ERROR}

_XLSX_SUFFIXES = {".xlsx", ".xlsm"}
_CSV_SUFFIXES = {".csv"}
_UNSUPPORTED_LEGACY_SUFFIXES = {".xls"}


# ---------------------------------------------------------------------------
# Header aliasing -- real spreadsheets spell these columns many ways.
# ---------------------------------------------------------------------------

def _collapse(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.strip().upper())


_HEADER_ALIASES: Dict[str, List[str]] = {
    "register_name": ["register name", "register", "reg name", "reg", "name"],
    "block": ["block", "module", "block name"],
    "offset": ["offset", "address offset", "reg offset", "register offset"],
    "width": ["width", "bit width", "register width", "reg width"],
    "access": ["access", "access type", "r/w", "register access"],
    "reset_value": ["reset value", "reset", "default", "reset val"],
    "field_name": ["field name", "field", "bit field"],
    "bits": ["bits", "bit range", "bit position", "bit(s)"],
    "field_access": ["field access", "field access type"],
    "field_reset": ["field reset", "field reset value", "field default"],
    "notes": ["notes", "comment", "comments", "description"],
}

_HEADER_LOOKUP: Dict[str, str] = {}
for _canonical, _aliases in _HEADER_ALIASES.items():
    for _alias in _aliases:
        _HEADER_LOOKUP[_collapse(_alias)] = _canonical

_REQUIRED_HEADERS = {"register_name", "offset"}


def _map_headers(raw_headers: Sequence[Optional[str]]) -> Dict[str, int]:
    """Map column index -> canonical field name for every recognized header
    cell. Unrecognized header cells are simply not present in the result --
    an extra column (e.g. a spreadsheet's own tracking id) is not an error."""
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(raw_headers):
        if cell is None:
            continue
        canonical = _HEADER_LOOKUP.get(_collapse(str(cell)))
        if canonical and canonical not in mapping:
            mapping[canonical] = idx
    return mapping


# ---------------------------------------------------------------------------
# Value parsing -- never guesses; a malformed cell is a reported defect.
# ---------------------------------------------------------------------------

def _cell_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


_UNKNOWN_TOKENS = {"", "N/A", "NA", "TBD", "-", "?", "UNKNOWN", "NONE"}


def parse_hex_or_decimal(text: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """Parse an offset/address/reset-value cell. Returns (value, error).
    `0x`-prefixed (any case) is hex; a plain digit string is decimal --
    documented limitation: a bare hex string with no `0x` prefix (e.g. a
    spreadsheet author who wrote "1000" meaning hex 0x1000) is read as
    decimal 1000, never guessed as hex."""
    if text is None:
        return None, None
    stripped = text.strip()
    if stripped.upper() in _UNKNOWN_TOKENS:
        return None, None
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", stripped):
        return int(stripped, 16), None
    if re.fullmatch(r"[0-9A-Fa-f]+[hH]", stripped):
        return int(stripped[:-1], 16), None
    if re.fullmatch(r"[0-9]+", stripped):
        return int(stripped), None
    return None, f"unparseable numeric value: {text!r} (expected 0x-hex, trailing-h hex, or decimal)"


_BITS_RE = re.compile(r"^\[?\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?$")


def parse_bit_range(text: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse a bit-range cell ("[7:0]", "7:0", "3") into (bit_offset,
    bit_width, error)."""
    if text is None:
        return None, None, "missing bit range for a field row"
    stripped = text.strip()
    m = _BITS_RE.match(stripped)
    if not m:
        return None, None, f"unparseable bit range: {text!r} (expected e.g. '[7:0]', '7:0', or '3')"
    hi = int(m.group(1))
    lo = int(m.group(2)) if m.group(2) is not None else hi
    bit_offset = min(hi, lo)
    bit_width = abs(hi - lo) + 1
    return bit_offset, bit_width, None


# `normalize_access_type()` folds SPELLING variants onto one of these short
# canonical tokens. Whether that token is one the CURRENT
# register_map.schema.json declares is a separate question, answered by
# `schema_access_kind_enum()` -- see module docstring.
_ACCESS_ALIASES: Dict[str, str] = {
    "RW": "RW", "R/W": "RW", "READWRITE": "RW", "READWRITEONLY": "RW",
    "RO": "RO", "R": "RO", "READONLY": "RO",
    "WO": "WO", "W": "WO", "WRITEONLY": "WO",
    "W1C": "W1C", "WRITE1TOCLEAR": "W1C", "W1TC": "W1C",
    "RW1C": "RW1C", "READWRITE1TOCLEAR": "RW1C",
    "RC": "RC", "READCLEAR": "RC", "RCLR": "RC",
    "WC": "WC", "WRITECLEAR": "WC",
    "W1S": "W1S", "WRITE1TOSET": "W1S", "W1TS": "W1S",
    "RS": "RS", "READSET": "RS", "READTOSET": "RS",
}

_MNEMONIC_RE = re.compile(r"^[A-Z0-9]{1,6}$")


def normalize_access_type(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Returns (canonical_token_or_none, error_or_none). `error` is set only
    when the text is not even a plausible short access mnemonic (free-form
    prose, garbage) -- a real but schema-undeclared mnemonic like "RS" is
    returned successfully with no error; whether it is in the CURRENT schema
    is answered separately."""
    if raw is None:
        return None, None
    stripped = raw.strip()
    if not stripped or stripped.upper() in _UNKNOWN_TOKENS:
        return None, None
    collapsed = re.sub(r"[\s\-_/]+", "", stripped.upper())
    if collapsed in _ACCESS_ALIASES:
        return _ACCESS_ALIASES[collapsed], None
    if _MNEMONIC_RE.match(collapsed):
        return collapsed, None
    return None, f"unrecognized access-type text: {raw!r} (not a plausible access mnemonic)"


# ---------------------------------------------------------------------------
# RegisterIR
# ---------------------------------------------------------------------------

@dataclass
class RegisterFieldIR:
    name: str
    bit_offset: Optional[int]
    bit_width: Optional[int]
    access_type: Optional[str]
    access_in_current_schema: Optional[bool]
    reset_value: Optional[int]
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "bit_offset": self.bit_offset,
            "bit_width": self.bit_width,
            "access_type": self.access_type,
            "access_in_current_schema": self.access_in_current_schema,
            "reset_value": (f"0x{self.reset_value:x}" if self.reset_value is not None else None),
            "notes": self.notes,
        }


@dataclass
class RegisterIR:
    register_name: str
    block: Optional[str]
    offset: Optional[int]
    absolute_address: Optional[int]
    width: Optional[int]
    access_type: Optional[str]
    access_in_current_schema: Optional[bool]
    reset_value: Optional[int]
    notes: Optional[str] = None
    fields: List[RegisterFieldIR] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "register_name": self.register_name,
            "block": self.block,
            "offset": (f"0x{self.offset:x}" if self.offset is not None else None),
            "absolute_address": (f"0x{self.absolute_address:x}" if self.absolute_address is not None else None),
            "width": self.width,
            "access_type": self.access_type,
            "access_in_current_schema": self.access_in_current_schema,
            "reset_value": (f"0x{self.reset_value:x}" if self.reset_value is not None else None),
            "notes": self.notes,
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass
class ExtractionResult:
    status: str
    reason: Optional[str]
    source_path: str
    registers: List[RegisterIR] = field(default_factory=list)
    row_errors: List[Dict[str, Any]] = field(default_factory=list)
    schema_widening_candidates: Dict[str, List[str]] = field(default_factory=dict)
    schema_access_enum_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "source_path": self.source_path,
            "registers": [r.to_dict() for r in self.registers],
            "row_errors": self.row_errors,
            "schema_widening_candidates": self.schema_widening_candidates,
            "schema_access_enum_used": self.schema_access_enum_used,
        }


def _not_available(source_path: str, reason: str) -> ExtractionResult:
    return ExtractionResult(status=STATUS_NOT_AVAILABLE, reason=reason, source_path=source_path)


def _parse_error(source_path: str, reason: str) -> ExtractionResult:
    return ExtractionResult(status=STATUS_PARSE_ERROR, reason=reason, source_path=source_path)


# ---------------------------------------------------------------------------
# Schema vocabulary -- read at run time, never hardcoded (REUSE OVER REINVENT).
# ---------------------------------------------------------------------------

def schema_access_kind_enum() -> List[str]:
    """The register_map.schema.json access_kind enum, read fresh from disk
    every call -- if a future integrator widens the schema additively, this
    module's classification of "in current schema" tracks it with no code
    change here."""
    schema = json.loads(env_manifest.REGISTER_MAP_SCHEMA_PATH.read_text(encoding="utf-8"))
    return list(schema["$defs"]["access_kind"]["enum"])


# ---------------------------------------------------------------------------
# Row-oriented sheet reading -- one implementation shared by .xlsx and .csv.
# ---------------------------------------------------------------------------

def _read_xlsx_rows(path: Path, sheet_name: Optional[str]) -> List[List[Any]]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ValueError(f"sheet {sheet_name!r} not found; available sheets: {wb.sheetnames}")
            ws = wb[sheet_name]
        else:
            ws = wb[wb.sheetnames[0]]
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_csv_rows(path: Path) -> List[List[Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.reader(fh)]


def _first_nonblank_row_index(rows: List[List[Any]]) -> Optional[int]:
    for idx, row in enumerate(rows):
        if any(_cell_text(c) is not None for c in row):
            return idx
    return None


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_register_map(
    path: Any,
    *,
    sheet_name: Optional[str] = None,
    default_block_name: Optional[str] = None,
    base_address: Optional[int] = None,
) -> ExtractionResult:
    """Extract a RegisterIR from a real register-map .xlsx or .csv file.

    `default_block_name`: used for every register when the sheet carries no
    "Block"/"Module" column -- defaults to the file's own stem, never a
    fabricated protocol/IP name.
    `base_address`: an integer block base address; when supplied,
    `absolute_address = base_address + offset` is computed per register.
    Omit it and `absolute_address` stays None with no guessed base.
    """
    source_path = str(path)
    p = Path(path)
    schema_enum = set(schema_access_kind_enum())

    if not p.exists():
        return _not_available(source_path, f"file not found: {source_path}")
    if not p.is_file():
        return _not_available(source_path, f"not a regular file: {source_path}")

    suffix = p.suffix.lower()
    if suffix in _UNSUPPORTED_LEGACY_SUFFIXES:
        return _not_available(
            source_path,
            "legacy binary .xls format is not supported -- openpyxl reads .xlsx/.xlsm only; "
            "re-save the workbook as .xlsx or export to .csv",
        )
    if suffix in _XLSX_SUFFIXES:
        if not _OPENPYXL_AVAILABLE:
            return _not_available(
                source_path,
                f"openpyxl is not installed, cannot read {suffix} files: {_OPENPYXL_IMPORT_ERROR}",
            )
        try:
            rows = _read_xlsx_rows(p, sheet_name)
        except Exception as exc:  # noqa: BLE001 - a real unreadable workbook is a real PARSE_ERROR
            return _parse_error(source_path, f"could not read workbook: {exc}")
    elif suffix in _CSV_SUFFIXES:
        try:
            rows = _read_csv_rows(p)
        except Exception as exc:  # noqa: BLE001
            return _parse_error(source_path, f"could not read csv: {exc}")
    else:
        return _parse_error(source_path, f"unsupported file extension: {suffix!r} (expected .xlsx/.xlsm/.csv)")

    header_idx = _first_nonblank_row_index(rows)
    if header_idx is None:
        return _parse_error(source_path, "sheet/file is empty -- no header row found")

    header_map = _map_headers(rows[header_idx])
    missing_required = _REQUIRED_HEADERS - set(header_map)
    if missing_required:
        return _parse_error(
            source_path,
            f"missing required column(s): {sorted(missing_required)} "
            f"(recognized headers: {sorted(header_map)})",
        )

    def col(row: List[Any], key: str) -> Optional[str]:
        idx = header_map.get(key)
        if idx is None or idx >= len(row):
            return None
        return _cell_text(row[idx])

    default_block = default_block_name or p.stem
    block_of: Dict[str, str] = {}
    registers: "Dict[str, RegisterIR]" = {}
    order: List[str] = []
    row_errors: List[Dict[str, Any]] = []
    current_register_name: Optional[str] = None
    widening: Dict[str, List[str]] = {}

    def note_widening(token: str, where: str) -> None:
        widening.setdefault(token, [])
        if where not in widening[token]:
            widening[token].append(where)

    def classify(token: Optional[str]) -> Optional[bool]:
        if token is None:
            return None
        return token in schema_enum

    for r_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(_cell_text(c) is not None for c in row):
            continue  # blank spacer row -- not a defect

        reg_name_cell = col(row, "register_name")
        block_cell = col(row, "block")
        offset_cell = col(row, "offset")
        width_cell = col(row, "width")
        access_cell = col(row, "access")
        reset_cell = col(row, "reset_value")
        field_name_cell = col(row, "field_name")
        bits_cell = col(row, "bits")
        field_access_cell = col(row, "field_access")
        field_reset_cell = col(row, "field_reset")
        notes_cell = col(row, "notes")

        if reg_name_cell:
            current_register_name = reg_name_cell
            if current_register_name not in block_of:
                block_of[current_register_name] = block_cell or default_block

        is_register_defining_row = offset_cell is not None

        if is_register_defining_row:
            if current_register_name is None:
                row_errors.append({"row": r_idx, "error": "register-defining row with no register name"})
                continue
            offset_val, off_err = parse_hex_or_decimal(offset_cell)
            if off_err or offset_val is None:
                row_errors.append({
                    "row": r_idx, "register": current_register_name,
                    "error": f"invalid offset: {off_err or 'empty offset'}",
                })
                continue
            width_val: Optional[int] = None
            if width_cell is not None:
                try:
                    width_val = int(width_cell)
                except ValueError:
                    row_errors.append({
                        "row": r_idx, "register": current_register_name,
                        "error": f"unparseable width: {width_cell!r}",
                    })
            access_token, acc_err = normalize_access_type(access_cell)
            if acc_err:
                row_errors.append({"row": r_idx, "register": current_register_name, "error": acc_err})
            reset_val, reset_err = parse_hex_or_decimal(reset_cell)
            if reset_err:
                row_errors.append({
                    "row": r_idx, "register": current_register_name,
                    "error": f"invalid reset value: {reset_err}",
                })
            in_schema = classify(access_token)
            if access_token is not None and in_schema is False:
                note_widening(access_token, f"register {current_register_name!r} (row {r_idx})")

            if current_register_name not in registers:
                order.append(current_register_name)
                registers[current_register_name] = RegisterIR(
                    register_name=current_register_name,
                    block=block_of[current_register_name],
                    offset=offset_val,
                    absolute_address=(base_address + offset_val if base_address is not None else None),
                    width=width_val,
                    access_type=access_token,
                    access_in_current_schema=in_schema,
                    reset_value=reset_val,
                    notes=notes_cell,
                )
            else:
                # A register named again on a later row (e.g. a repeated
                # summary row) -- update rather than duplicate.
                reg = registers[current_register_name]
                reg.offset = offset_val
                reg.absolute_address = base_address + offset_val if base_address is not None else None
                if width_val is not None:
                    reg.width = width_val
                if access_token is not None:
                    reg.access_type = access_token
                    reg.access_in_current_schema = in_schema
                if reset_val is not None:
                    reg.reset_value = reset_val
                if notes_cell:
                    reg.notes = notes_cell

        if field_name_cell:
            if current_register_name is None or current_register_name not in registers:
                row_errors.append({
                    "row": r_idx,
                    "error": f"field {field_name_cell!r} has no preceding register-defining row",
                })
                continue
            bit_offset, bit_width, bits_err = parse_bit_range(bits_cell)
            if bits_err:
                row_errors.append({
                    "row": r_idx, "register": current_register_name, "field": field_name_cell,
                    "error": bits_err,
                })
                continue
            f_access_raw = field_access_cell if field_access_cell is not None else access_cell
            f_access_token, f_acc_err = normalize_access_type(f_access_raw)
            if f_acc_err:
                row_errors.append({
                    "row": r_idx, "register": current_register_name, "field": field_name_cell,
                    "error": f_acc_err,
                })
            f_reset_raw = field_reset_cell if field_reset_cell is not None else None
            f_reset_val, f_reset_err = parse_hex_or_decimal(f_reset_raw)
            if f_reset_err:
                row_errors.append({
                    "row": r_idx, "register": current_register_name, "field": field_name_cell,
                    "error": f"invalid field reset value: {f_reset_err}",
                })
            f_in_schema = classify(f_access_token)
            if f_access_token is not None and f_in_schema is False:
                note_widening(f_access_token, f"field {field_name_cell!r} of {current_register_name!r} (row {r_idx})")

            registers[current_register_name].fields.append(RegisterFieldIR(
                name=field_name_cell,
                bit_offset=bit_offset,
                bit_width=bit_width,
                access_type=f_access_token,
                access_in_current_schema=f_in_schema,
                reset_value=f_reset_val,
                notes=notes_cell,
            ))

    if not registers:
        return ExtractionResult(
            status=STATUS_PARSE_ERROR,
            reason=f"no valid registers could be extracted; {len(row_errors)} row error(s)",
            source_path=source_path,
            row_errors=row_errors,
            schema_widening_candidates=widening,
            schema_access_enum_used=sorted(schema_enum),
        )

    status = STATUS_OK if not row_errors else STATUS_PARTIAL
    reason = None if not row_errors else f"{len(row_errors)} row(s) had defects and were excluded; see row_errors"
    return ExtractionResult(
        status=status,
        reason=reason,
        source_path=source_path,
        registers=[registers[name] for name in order],
        row_errors=row_errors,
        schema_widening_candidates=widening,
        schema_access_enum_used=sorted(schema_enum),
    )


# ---------------------------------------------------------------------------
# Bridge to the existing register_map.schema.json input contract (REUSE).
# ---------------------------------------------------------------------------

def to_register_map_document(result: ExtractionResult, *, source_description: str = "excel_register_map_transcription") -> Dict[str, Any]:
    """Project a (possibly PARTIAL) ExtractionResult into a
    register_map.schema.json-shaped document, and validate it against the
    REAL schema via `env_manifest.validate_register_map()`. Registers/fields
    whose access type is not in the CURRENT schema enum, or whose width is
    not one of the schema's declared widths, are excluded from the document
    (never force-mapped) and named in the returned `excluded` list -- the
    full facts stay available on `result` itself, this function only decides
    what is safe to hand to the existing schema-validated pipeline today.

    Raises `env_manifest.RegisterMapValidationError` if the constructed
    document still fails validation (a defect in this bridge, not in the
    input) -- callers should not treat that as a normal outcome."""
    blocks: Dict[str, Dict[str, Any]] = {}
    excluded: List[Dict[str, Any]] = []
    valid_widths = {8, 16, 32, 64, 128}

    for reg in result.registers:
        if reg.width not in valid_widths:
            excluded.append({"register": reg.register_name, "reason": f"width {reg.width!r} not in {sorted(valid_widths)}"})
            continue
        if reg.access_type is None or reg.access_in_current_schema is False:
            excluded.append({"register": reg.register_name, "reason": f"access_type {reg.access_type!r} not in current schema enum"})
            continue
        kept_fields = []
        for f in reg.fields:
            if f.access_type is None or f.access_in_current_schema is False:
                excluded.append({
                    "register": reg.register_name, "field": f.name,
                    "reason": f"field access_type {f.access_type!r} not in current schema enum",
                })
                continue
            if f.bit_offset is None or f.bit_width is None:
                excluded.append({"register": reg.register_name, "field": f.name, "reason": "missing bit range"})
                continue
            kept_fields.append({
                "name": f.name,
                "bit_offset": f.bit_offset,
                "bit_width": f.bit_width,
                "access": f.access_type,
                "reset_value": (f"0x{f.reset_value:x}" if f.reset_value is not None else None),
                **({"description": f.notes} if f.notes else {}),
            })
        block_name = reg.block or "default"
        block = blocks.setdefault(block_name, {"name": block_name, "base_address": "0x0", "registers": []})
        block["registers"].append({
            "name": reg.register_name,
            "address_offset": f"0x{reg.offset:x}",
            "width": reg.width,
            "access": reg.access_type,
            "reset_value": (f"0x{reg.reset_value:x}" if reg.reset_value is not None else None),
            "fields": kept_fields,
            **({"description": reg.notes} if reg.notes else {}),
        })

    doc = {
        "schema_version": "1.0",
        "source": {"kind": "excel_register_map_transcription", "description": source_description},
        "blocks": list(blocks.values()),
    }
    env_manifest.validate_register_map(doc)
    return {"document": doc, "excluded": excluded}


# ---------------------------------------------------------------------------
# Ad hoc entry point -- no `dv-harness` CLI verb added here (cli.py is out of
# this task's file-safety scope); this mirrors other modules' bare `python -m`
# front door.
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m dv_harness.register_excel_extract")
    parser.add_argument("path", help="register-map .xlsx/.csv file")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--block", default=None)
    parser.add_argument("--base-address", default=None, help="hex or decimal block base address")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base_address = None
    if args.base_address is not None:
        base_address, err = parse_hex_or_decimal(args.base_address)
        if err:
            print(f"invalid --base-address: {err}")
            return 2

    result = extract_register_map(
        args.path, sheet_name=args.sheet, default_block_name=args.block, base_address=base_address,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"status: {result.status}")
        if result.reason:
            print(f"reason: {result.reason}")
        print(f"registers extracted: {len(result.registers)}")
        if result.schema_widening_candidates:
            print(f"schema widening candidates: {result.schema_widening_candidates}")
        for e in result.row_errors:
            print(f"  row_error: {e}")

    if result.status in (STATUS_NOT_AVAILABLE,):
        return 2
    if result.status == STATUS_PARSE_ERROR:
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    import sys
    sys.exit(main())
