"""dv_harness/intake_plain_summary.py -- plain-language, one-shot-confirmation
summary over intake_baseline.py's own capture_intake_baseline()/
freeze_intake_baseline() records.

WHAT THIS CLOSES
------------------
intake_baseline.py captures the twelve pre-generation intake facts into
structured JSON (see that module's own docstring), but renders nothing a
human can read in one pass to confirm or correct before the baseline locks
in. This module is exactly that renderer -- "here is everything I now
believe about your project -- confirm or correct" -- and reads ONLY the
real baseline record's own fields. It captures no fact of its own, calls no
other producer, and never fabricates a value for a field the baseline
itself reports NOT_AVAILABLE: an unresolved fact is rendered as an open item
requiring the human's attention, never silently defaulted or omitted.

REUSE, NOT REINVENT
--------------------
The twelve field names, their canonical order, the CAPTURED/NOT_AVAILABLE
vocabulary, and which of the four real captors produced a given field are
all read directly off intake_baseline.py's own public `INTAKE_FIELDS` /
`FIELD_CAPTORS` tables -- this module never re-declares the field list and
never re-implements a captor. Shape classification is done by the identity
(`__name__`) of the real captor function `FIELD_CAPTORS` already points at,
never a second, independently-maintained field->shape table that could
silently drift out of sync with intake_baseline.py's own captor set.

WHAT THIS DOES NOT DO
------------------------
It never captures, freezes, evaluates, or invalidates a baseline -- it only
renders one a caller already produced (via `capture_intake_baseline()` or
`freeze_intake_baseline()`). It never approves anything and holds no stage
gate; there is deliberately no `STAGE_GATES` entry. "Confirm or correct"
means what it says: this text is meant to be shown to a human, who then
either confirms the baseline is right or corrects the underlying facts and
re-captures -- this module performs neither action itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import intake_baseline as ib


class IntakeSummaryError(ValueError):
    """The supplied record does not look like a real capture_intake_baseline()
    or freeze_intake_baseline() result -- refused rather than rendered with
    a guessed shape."""


#: Human-readable label per real intake field. Presentation only -- the
#: underlying fact set and its meaning are entirely intake_baseline.py's.
FIELD_LABELS: Dict[str, str] = {
    "dut_top_boundary": "DUT top module / boundary",
    "dut_sha": "DUT source SHA",
    "tb_sha": "Testbench source SHA",
    "source_file_hashes": "Source file hashes",
    "vip_declaration": "VIP declaration",
    "bind_topology_hash": "Bind topology hash",
    "reference_uvm_hash": "Reference-UVM hash",
    "de_command_txt_hash": "DE command.txt hash",
    "known_test_list": "Known test list",
    "unresolved_critical_unknowns_count": "Unresolved critical unknowns",
    "unresolved_conflicts_count": "Unresolved conflicts",
    "recorded_user_decisions_count": "Recorded user decisions",
}

#: Presentational grouping only -- membership is asserted below to be an
#: exact partition of the real `ib.INTAKE_FIELDS`, so a future field added
#: to intake_baseline.py without a matching entry here fails at import
#: rather than silently being dropped from the rendered summary.
FIELD_CATEGORIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("DUT / TB identity", ("dut_top_boundary", "dut_sha", "tb_sha")),
    ("Source & environment", ("source_file_hashes", "vip_declaration",
                              "bind_topology_hash", "reference_uvm_hash",
                              "de_command_txt_hash")),
    ("Test surface", ("known_test_list",)),
    ("Outstanding items", ("unresolved_critical_unknowns_count",
                           "unresolved_conflicts_count",
                           "recorded_user_decisions_count")),
)


def _assert_categories_cover_intake_fields() -> None:
    declared = set(ib.INTAKE_FIELDS)
    grouped = set()
    for _label, names in FIELD_CATEGORIES:
        for name in names:
            if name in grouped:
                raise AssertionError(
                    f"intake_plain_summary FIELD_CATEGORIES lists {name!r} "
                    "more than once")
            grouped.add(name)
    missing = sorted(declared - grouped)
    extra = sorted(grouped - declared)
    if missing or extra:
        raise AssertionError(
            "intake_plain_summary FIELD_CATEGORIES drifted from "
            f"intake_baseline.INTAKE_FIELDS: missing {missing}; extra {extra}")


_assert_categories_cover_intake_fields()


#: Maps a real captor's own __name__ (as referenced in ib.FIELD_CAPTORS) to
#: the shape this renderer uses to describe a CAPTURED value. Never a second
#: definition of which field uses which captor -- only a label for it.
_SHAPE_BY_CAPTOR_NAME: Dict[str, str] = {
    "_capture_declared_fact": "declared_fact",
    "_capture_hash_or_files_field": "hash_or_files",
    "_capture_list_field": "list",
    "_capture_count_field": "count",
}

_NOT_AVAILABLE_REASON_PHRASES: Dict[str, str] = {
    "NO_FACT_SUPPLIED": "no value was supplied for this fact",
    "EMPTY_FACT_SUPPLIED": "an empty value was supplied",
    "EMPTY_FILE_MAP_SUPPLIED": "an empty file map was supplied",
    "UNSUPPORTED_FACT_SHAPE": "the supplied value's type is not supported for this fact",
    "NO_COUNT_SUPPLIED": "no count was supplied",
    "INVALID_COUNT_VALUE": "the supplied count value is invalid (must be a real, non-negative integer)",
}


def _field_shape(field_name: str) -> str:
    captor = ib.FIELD_CAPTORS.get(field_name)
    if captor is None:
        return "unknown"
    return _SHAPE_BY_CAPTOR_NAME.get(getattr(captor, "__name__", ""), "unknown")


def _short_repr(value: Any, limit: int = 160) -> str:
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        else:
            text = str(value)
    except (TypeError, ValueError):
        text = str(value)
    text = text.strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "... (truncated for display)"
    return text


def _describe_captured_value(shape: str, detail: Optional[Dict[str, Any]]) -> str:
    """A plain-language description of a CAPTURED field's own real value --
    read only from the field record's own `detail`, never invented. When
    intake_baseline.py's own size cap already dropped the inline value, that
    absence is reported honestly rather than papered over."""
    detail = detail or {}
    if shape == "declared_fact":
        if "value" in detail:
            return _short_repr(detail["value"])
        if detail.get("value_truncated"):
            n = detail.get("value_length_chars")
            return (f"a large value ({n} characters) -- too large to show "
                     "inline; the digest below still identifies it exactly")
        return "a value was captured (no inline detail retained)"
    if shape == "hash_or_files":
        if "file_count" in detail:
            n = detail["file_count"]
            if detail.get("files_truncated"):
                return (f"{n} file(s) hashed and combined into one digest "
                        "(the file list itself is too large to show inline)")
            return f"{n} file(s) hashed and combined into one digest"
        supplied_as = detail.get("supplied_as")
        if supplied_as == "precomputed_hash":
            return "an already-computed hash was accepted as-is"
        if supplied_as == "raw_content_string":
            return "a single piece of raw content was hashed"
        return "a value was captured (no inline detail retained)"
    if shape == "list":
        n = detail.get("count")
        if n is None:
            return "a list was captured (no inline detail retained)"
        if detail.get("tests_truncated"):
            return f"{n} test name(s) recorded (list too large to show inline)"
        return f"{n} test name(s) recorded"
    if shape == "count":
        if "value" in detail:
            return f"{detail['value']}"
        return "a count was captured (no inline detail retained)"
    return "a value was captured"


def _describe_not_available_reason(reason: Optional[str]) -> str:
    if not reason:
        return "no reason was recorded"
    return _NOT_AVAILABLE_REASON_PHRASES.get(reason, reason)


def _resolve_baseline_and_freeze_meta(
        record: Any) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Accepts either a raw `capture_intake_baseline()` result, or a
    `freeze_intake_baseline()` result (whose own `baseline` key wraps the
    identical shape). Refuses -- never guesses -- anything else."""
    if not isinstance(record, dict):
        raise IntakeSummaryError(
            "record must be a dict produced by capture_intake_baseline() "
            "or freeze_intake_baseline()")
    inner = record.get("baseline")
    if isinstance(inner, dict) and "fields" in inner:
        freeze_meta = {
            "freeze_id": record.get("freeze_id"),
            "frozen_by": record.get("frozen_by"),
            "frozen_at": record.get("frozen_at"),
            "note": record.get("note") or "",
        }
        return inner, freeze_meta
    if "fields" in record:
        return record, None
    raise IntakeSummaryError(
        "record does not look like a capture_intake_baseline() or "
        "freeze_intake_baseline() result -- no 'fields' found")


def open_field_names(record: Any) -> List[str]:
    """The real, canonical-order field names that are NOT CAPTURED (or
    malformed) in this record -- the do-not-silently-omit list a caller
    can act on without re-parsing the rendered text."""
    baseline, _freeze_meta = _resolve_baseline_and_freeze_meta(record)
    fields = baseline.get("fields") or {}
    out: List[str] = []
    for name in ib.INTAKE_FIELDS:
        f = fields.get(name)
        if not isinstance(f, dict) or f.get("status") != ib.CAPTURED:
            out.append(name)
    return out


def render_intake_plain_summary(record: Any) -> str:
    """Render a plain-language "here is everything I now believe about
    your project -- confirm or correct" summary from a real
    capture_intake_baseline()/freeze_intake_baseline() record. Every line
    is derived from that record's own fields; a field this record could not
    capture is rendered as an honest open item, never silently defaulted."""
    baseline, freeze_meta = _resolve_baseline_and_freeze_meta(record)
    fields = baseline.get("fields") or {}

    lines: List[str] = []
    lines.append("Here is everything I now believe about your project. Please confirm")
    lines.append("or correct each item below before this intake baseline is treated as settled.")
    lines.append("")

    captured = 0
    not_available = 0
    open_items: List[str] = []

    for category_label, field_names in FIELD_CATEGORIES:
        lines.append(f"{category_label}:")
        for name in field_names:
            f = fields.get(name)
            label = FIELD_LABELS.get(name, name)
            if not isinstance(f, dict):
                lines.append(f"  - {label}: NO DATA RECORDED FOR THIS FIELD (malformed record)")
                open_items.append(label)
                continue
            status = f.get("status")
            if status == ib.CAPTURED:
                captured += 1
                shape = _field_shape(name)
                desc = _describe_captured_value(shape, f.get("detail"))
                digest = f.get("digest")
                digest_note = f" [digest {digest[:16]}...]" if digest else ""
                lines.append(f"  - {label}: {desc}{digest_note}")
            elif status == ib.NOT_AVAILABLE:
                not_available += 1
                reason = _describe_not_available_reason(f.get("reason"))
                lines.append(f"  - {label}: NOT CAPTURED -- {reason}")
                open_items.append(label)
            else:
                lines.append(f"  - {label}: UNRECOGNIZED STATUS {status!r} (malformed record)")
                open_items.append(label)
        lines.append("")

    lines.append(f"Summary: {captured} of {len(ib.INTAKE_FIELDS)} facts captured, "
                 f"{not_available} not available.")

    if open_items:
        lines.append("")
        lines.append("Open items needing your confirmation or correction:")
        for item in open_items:
            lines.append(f"  - {item}")
    else:
        lines.append("")
        lines.append("No open items -- every fact was captured. Please still confirm "
                     "each value above is correct before it locks in.")

    lines.append("")
    if freeze_meta is not None:
        note_part = f" Note: {freeze_meta['note']}" if freeze_meta.get("note") else ""
        lines.append(
            f"This baseline was FROZEN as {freeze_meta.get('freeze_id')} by "
            f"{freeze_meta.get('frozen_by')} at {freeze_meta.get('frozen_at')}.{note_part}")
    else:
        lines.append(
            "This baseline has NOT been frozen yet -- nothing has locked in. "
            "Confirm or correct the facts above, then freeze.")

    return "\n".join(lines)


# --- front door -------------------------------------------------------------

def execute_verb(argv) -> int:
    """`python -m dv_harness.intake_plain_summary render --file <path.json>`.
    Exit 0: rendered, every fact captured. Exit 1: rendered, at least one
    open item remains. Exit 2: refused (missing/unreadable/malformed file)."""
    ap = argparse.ArgumentParser(
        prog="intake-plain-summary",
        description="Plain-language, one-shot-confirmation summary over a real "
                    "capture_intake_baseline()/freeze_intake_baseline() record.")
    ap.add_argument("verb", choices=["render"])
    ap.add_argument("--file", required=True,
                    help="path to a JSON file produced by capture_intake_baseline() "
                         "or freeze_intake_baseline()")
    args = ap.parse_args(list(argv))

    p = Path(args.file)
    if not p.is_file():
        print(json.dumps({"status": "REFUSED", "reason": f"FILE_NOT_FOUND: {p}"}, indent=2))
        return 2
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "REFUSED",
                          "reason": f"FILE_UNREADABLE: {type(exc).__name__}: {exc}"}, indent=2))
        return 2

    try:
        text = render_intake_plain_summary(record)
        items = open_field_names(record)
    except IntakeSummaryError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, indent=2))
        return 2

    print(text)
    return 1 if items else 0


def main(argv: Optional[Any] = None) -> int:
    import sys as _sys
    return execute_verb(list(_sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
