"""dv_harness/exemptions.py -- structured, machine-checkable record of every
check/gate/assertion/coverage-bin that is DELIBERATELY disabled or relaxed
for a specific, cited reason (e.g. "this check is off because of an IP
restriction").

Why this module exists (user's own spec, 2026-09-03): that kind of knowledge
-- "we turned this off on purpose, and here is why" -- is worthless if it
only lives in a code comment or gets passed down by word of mouth. An agent
re-reading the code later has no way to tell a deliberate, still-valid
exemption from stale dead code, so it either re-litigates the same question
every time or "helpfully" deletes/re-enables the check and silently
regresses whatever the exemption was protecting against. A structured
exemptions.yaml (id / check_id / reason / basis_document / owner /
valid_until) fixes the first half of that problem.

The second half -- a temporary workaround quietly becoming a permanent,
never-revisited fact -- is what makes `valid_until` the load-bearing field
here (see exemptions.schema.json: it is REQUIRED and must be a
syntactically- and calendar-valid date -- there is no way to omit it or to
represent "no expiry" as a value). That said, the schema does NOT enforce
any maximum horizon: nothing today stops an operator from choosing a
far-future `valid_until` (e.g. "9999-12-31") as a de-facto permanent
exemption. check_expiry() and build_review_queue() below are the real,
callable functions that turn an expired `valid_until` into a concrete list
of entries a human needs to look at again, rather than a date nobody ever
checks -- but a deliberately far-future date will simply never reach that
list.

Review-queue integration point -- READ THIS BEFORE WIRING A CONSUMER:
`dv_harness/question_queue.py` now exists in this repo (a sibling,
concurrently-developed 3-tier ask-a-human workstream), but as of this
writing it does NOT consume this module's review-queue output --
`grep -n "review_queue|exemption" dv_harness/question_queue.py` returns no
matches. This module does not depend on question_queue.py and does not
invent its integration. What this module DOES provide is a standalone,
well-documented output: build_review_queue() returns a plain list of
{"exemption_id", "check_id", "expired_since", "days_expired", "reason",
"owner", "basis_document", "valid_until"} dicts, and write_review_queue()
persists that list as JSON to a known path
(`.dv-harness/exemptions/review_queue.json` by default, see
default_review_queue_path()). THIS is the integration point
`dv_harness/question_queue.py` (or any other consumer) should read from --
a JSON file at a stable path with a documented, tested shape -- so that
wiring the still-unconsumed integration up is "read this file", not "go
figure out where exemption data lives".

Storage format: a single YAML file (default
`.dv-harness/exemptions/exemptions.yaml` under a project root, see
default_exemptions_path()) shaped as
    schema_version: "1.0"
    exemptions:
      - id: EXEMPT-0001
        check_id: ...
        reason: ...
        basis_document: ...
        owner: ...
        valid_until: "2026-12-31"
validated against exemptions.schema.json (dv_harness/schemas/
exemptions.schema.json) via jsonschema Draft 2020-12, the exact discipline
dv_harness/uvm_generator/run_profile.py already uses for run_profile.json --
same fail-closed contract: invalid data raises rather than silently writing.

Distinct from dv_harness/waiver_store.py: a waiver there is a human-approved
sign-off on one specific gate/coverage-item instance with evidence attached
(consumed by the six gate scripts under tools/verification_flow/, no
expiry). An exemption here is "this check itself is deliberately off/relaxed
for this project, and here is the citable reason" -- a different, expiry-
driven concern. The two are not merged; a project may use either or both.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "exemptions.schema.json"
SCHEMA_VERSION = "1.0"

REQUIRED_FIELDS = ("id", "check_id", "reason", "basis_document", "owner", "valid_until")


class ExemptionValidationError(ValueError):
    """An exemptions document (or an entry about to be written into one)
    fails schema validation. Raised instead of returning False/None so a
    caller cannot accidentally persist or trust an invalid document -- same
    fail-closed discipline as run_profile.py's RunProfileValidationError."""


# --- paths -------------------------------------------------------------

def default_exemptions_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "exemptions" / "exemptions.yaml"


def default_review_queue_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "exemptions" / "review_queue.json"


# --- schema validation ---------------------------------------------------

def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_exemptions_document(doc: dict) -> None:
    """Validate `doc` (the whole {"schema_version", "exemptions": [...]}
    document) against exemptions.schema.json. Raises
    ExemptionValidationError on any violation; returns None on success.

    BUG FIX (2026-09-03, independent review repro: `valid_until:
    "2026-02-30"`): the schema declares `"format": "date"` on `valid_until`,
    but a bare `Draft202012Validator(schema)` treats `format` as an
    annotation only -- it does NOT actually check it unless a
    `format_checker` is attached. Without one, a calendar-invalid date like
    "2026-02-30" satisfies the `pattern` regex (it looks like a date) and
    passes validation, gets written to disk by add_exemption(), and then
    crashes date.fromisoformat() inside is_expired()/build_review_queue()
    with an unhandled ValueError the first time anyone runs `dv-harness
    exemptions check`. Attaching jsonschema's own `FormatChecker()` (built
    in, no extra dependency) makes `format: date` a real, enforced
    constraint -- it rejects "2026-02-30" the same way it already rejects
    "not-a-date", so add_exemption() now refuses the write up front instead
    of persisting a document that is unreadable ever after."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise ExemptionValidationError(
            "jsonschema package is not installed; cannot validate exemptions.yaml. "
            "Install it rather than skipping validation."
        ) from exc

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise ExemptionValidationError(
            "exemptions document failed schema validation:\n" + "\n".join(lines)
        )


# --- load / save ----------------------------------------------------------

def _empty_document() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "exemptions": []}


def load_exemptions_document(path: Path) -> Dict[str, Any]:
    """Load and validate the exemptions.yaml document at `path`. A missing
    file is not an error -- it is treated as an empty, valid document (a
    project that has never recorded an exemption yet), matching
    waiver_store.read_waivers()'s "no file yet" behavior. A present-but-
    invalid file raises ExemptionValidationError; callers must never
    silently fall back to an empty document in that case."""
    path = Path(path)
    if not path.is_file():
        return _empty_document()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ExemptionValidationError(f"{path}: top-level YAML content must be a mapping, got {type(raw).__name__}")
    validate_exemptions_document(raw)
    return raw


def save_exemptions_document(path: Path, doc: Dict[str, Any]) -> None:
    """Validate `doc`, then write it to `path` as YAML. Validation happens
    BEFORE the write so a caller can never persist a schema-invalid
    exemptions.yaml -- an agent reading it back later must be able to trust
    it unconditionally."""
    validate_exemptions_document(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def list_exemptions(path: Path) -> List[Dict[str, Any]]:
    """Return every entry (active and retired) in the document at `path`."""
    return list(load_exemptions_document(path).get("exemptions", []))


# --- adding an entry --------------------------------------------------

def _next_auto_id(entries: List[Dict[str, Any]]) -> str:
    """EXEMPT-0001, EXEMPT-0002, ... -- only used when the caller does not
    supply --id explicitly. Scans existing EXEMPT-<n> ids for the current
    max rather than counting entries, so a retired/removed entry never
    causes an id to be reused."""
    max_n = 0
    for e in entries:
        eid = str(e.get("id", ""))
        if eid.startswith("EXEMPT-"):
            suffix = eid[len("EXEMPT-"):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"EXEMPT-{max_n + 1:04d}"


def add_exemption(path: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Append one new exemption entry to the document at `path`, creating
    the file (and its parent directory) if it does not exist yet.

    `entry` must already contain check_id/reason/basis_document/owner/
    valid_until (id and created_at are filled in here when omitted). The
    full resulting document is schema-validated before the write, so a
    missing/malformed field (most importantly a missing or malformed
    valid_until -- the schema has no "no expiry" escape hatch) raises
    ExemptionValidationError rather than silently writing a bad record.
    Returns the entry actually written (with id/created_at filled in).
    """
    entry = dict(entry)
    doc = load_exemptions_document(path)
    entries = doc.setdefault("exemptions", [])

    if not entry.get("id"):
        entry["id"] = _next_auto_id(entries)
    if any(str(e.get("id")) == str(entry["id"]) for e in entries):
        raise ExemptionValidationError(f"an exemption with id {entry['id']!r} already exists in {path}")
    entry.setdefault("created_at", date.today().isoformat())
    entry.setdefault("status", "active")

    entries.append(entry)
    save_exemptions_document(path, doc)
    return entry


# --- expiry / review queue ----------------------------------------------

def parse_as_of(value: Optional[str]) -> date:
    """Parse a CLI-supplied --as-of value; None/'' means "today"."""
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_valid_until(entry: Dict[str, Any]) -> Optional[date]:
    """Parse one entry's `valid_until` into a real calendar date, or raise a
    clear ExemptionValidationError naming the offending entry and value.

    BUG FIX (2026-09-03): add_exemption()'s upfront schema validation (see
    validate_exemptions_document()'s own docstring) now rejects a
    calendar-invalid `valid_until` like "2026-02-30" before it is ever
    written. But this module must also stay safe against a file that was
    hand-edited on disk *after* being written, or a legacy file predating
    this fix -- is_expired()/build_review_queue() both call
    date.fromisoformat() on this value, and an unhandled ValueError there
    would crash `dv-harness exemptions check` with a raw traceback instead
    of a clean, actionable error. Centralizing the parse here means both
    call sites fail the same clean way."""
    valid_until = entry.get("valid_until")
    if not valid_until:
        return None
    try:
        return date.fromisoformat(valid_until)
    except (TypeError, ValueError) as exc:
        raise ExemptionValidationError(
            f"exemption {entry.get('id', '<unknown id>')!r} has an invalid valid_until "
            f"{valid_until!r} that is not a real, parseable calendar date ({exc}). This "
            f"exemptions.yaml file was likely hand-edited outside add_exemption(); fix or "
            f"retire this entry directly in the file before re-running this check."
        ) from exc


def is_expired(entry: Dict[str, Any], as_of: date) -> bool:
    """An entry is expired once `as_of` is strictly after its valid_until
    day -- valid_until is the last day the exemption is still in force. A
    'retired' entry is never reported as expired: it has already been
    explicitly closed out by a human, not silently allowed to lapse.

    Raises ExemptionValidationError (via _parse_valid_until()) rather than
    an unhandled ValueError if `valid_until` is present but not a real
    calendar date -- see _parse_valid_until()'s docstring."""
    if entry.get("status") == "retired":
        return False
    parsed = _parse_valid_until(entry)
    if parsed is None:
        # Schema-valid documents can never reach this (valid_until is
        # required), but a hand-edited/legacy file might; treat as expired
        # rather than silently trusting an exemption with no expiry at all.
        return True
    return parsed < as_of


def find_expired(entries: List[Dict[str, Any]], as_of: Optional[date] = None) -> List[Dict[str, Any]]:
    as_of = as_of or date.today()
    return [e for e in entries if is_expired(e, as_of)]


def find_active(entries: List[Dict[str, Any]], as_of: Optional[date] = None) -> List[Dict[str, Any]]:
    as_of = as_of or date.today()
    return [e for e in entries if not is_expired(e, as_of) and e.get("status") != "retired"]


def check_expiry(path: Path, as_of: Optional[date] = None) -> Dict[str, Any]:
    """Real, callable expiry check: given the exemptions file at `path` and
    (optionally) a current date, return which entries are expired vs. still
    active as of that date. This is the function backing both the `check`
    and `expire-report` CLI subcommands -- see cli.py's `exemptions` group.
    """
    as_of = as_of or date.today()
    entries = list_exemptions(path)
    expired = find_expired(entries, as_of)
    active = find_active(entries, as_of)
    retired = [e for e in entries if e.get("status") == "retired"]
    return {
        "as_of": as_of.isoformat(),
        "path": str(path),
        "total": len(entries),
        "active_count": len(active),
        "expired_count": len(expired),
        "retired_count": len(retired),
        "expired": expired,
        "active": active,
    }


def build_review_queue(path: Path, as_of: Optional[date] = None) -> List[Dict[str, Any]]:
    """Build the review-queue record list for every currently-expired entry
    in the exemptions file at `path`. This is the standalone, documented
    hand-off shape described in this module's own docstring above -- a
    future question-queue system reads FROM this shape (or from the JSON
    file write_review_queue() produces), it is never produced BY that
    system. Each record is independently meaningful (no cross-references
    into the exemptions file required to act on it)."""
    as_of = as_of or date.today()
    expired = find_expired(list_exemptions(path), as_of)
    queue: List[Dict[str, Any]] = []
    for e in expired:
        valid_until = e.get("valid_until")
        # _parse_valid_until() re-validates rather than trusting that
        # find_expired()'s own is_expired() pass already parsed this value
        # cleanly -- cheap, and keeps this function safe to call directly
        # against a hand-edited entries list, not only through check_expiry().
        parsed = _parse_valid_until(e)
        days_expired = (as_of - parsed).days if parsed is not None else None
        queue.append({
            "exemption_id": e.get("id"),
            "check_id": e.get("check_id"),
            "reason": e.get("reason"),
            "owner": e.get("owner"),
            "basis_document": e.get("basis_document"),
            "valid_until": valid_until,
            "expired_since": valid_until,
            "days_expired": days_expired,
            "as_of": as_of.isoformat(),
        })
    return queue


def write_review_queue(queue: List[Dict[str, Any]], out_path: Path) -> Path:
    """Persist `queue` (from build_review_queue()) as JSON to `out_path`,
    creating parent directories as needed. Always writes, even when `queue`
    is empty -- an empty review_queue.json is itself a meaningful, current
    fact ("nothing is expired as of the last check"), not the absence of a
    file a consumer would have to special-case."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                                     "entries": queue}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return out_path
