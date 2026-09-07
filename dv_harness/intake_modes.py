"""dv_harness/intake_modes.py -- a declared intake rigor MODE (FAST / STANDARD /
STRICT / SIGNOFF) that changes WHICH `intake_state.py` fields/categories are
mandatory before generation may proceed.

THE GAP THIS CLOSES
--------------------
`intake_state.py`'s own `evaluate_uvm_generation_ready()` already refuses
generation while any of `BLOCKING_CATEGORIES` -- a single FIXED tuple of six
categories -- is unresolved. That is the right rule for one point in a
project's lifecycle, but it is the ONLY rule this codebase had: the same six
categories are demanded whether an engineer wants a five-second sanity check
before a quick local iteration, or a human is about to sign off a project for
good. Section 17 asks for a declared MODE that widens or narrows the required
set instead of one permanently-fixed set. A repo-wide grep for
`IntakeMode`/`intake_mode`/`INTAKE_MODE` before writing this module matched
nothing executable anywhere in `dv_harness/`.

REUSE OVER REINVENT -- what this module imports and why
---------------------------------------------------------
This module invents no new readiness engine. It reuses TWO already-real
mechanisms exactly as they stand:

  - `intake_state.py`'s own `IntakeState.category_status()` (worst-wins fold
    per category) and its per-field `IntakeFieldRecord.status` -- read
    verbatim, never re-derived. `intake_state.BLOCKING_CATEGORIES` (the six
    categories that fixed rule already names) is reused directly as the
    `STANDARD` mode's own required set, rather than retyped, so `STANDARD`
    mode is provably identical in scope to that pre-existing fixed rule.
  - `verification_intake_contract.py`'s `evaluate_intake_readiness()` --
    THE `INTAKE_READY` conjunction this task instructs be reused, called
    unmodified. This module's only job is to build that function's
    caller-supplied `conditions` list DIFFERENTLY per declared mode; the
    worst-wins, no-averaging, "empty input is never vacuously ready"
    discipline all still live in that one function, not duplicated here.

Neither `intake_state.py` nor `verification_intake_contract.py` is edited.
Both are on the "several very similar-sounding capabilities already exist"
list this task's own instructions warned to check first -- and both check
out as genuinely reusable rather than needing a parallel rewrite: this
module is the missing PARAMETERIZATION layer between them, nothing more.

THE FOUR MODES, AND WHAT EACH ONE ACTUALLY WIDENS
----------------------------------------------------
Two independent axes decide a mode's rigor, and both increase monotonically
FAST -> STANDARD -> STRICT -> SIGNOFF (checked at import time by
`assert_modes_monotonically_increasing()`, the same "assert the declared
table is internally consistent" discipline this codebase's other
mode/tier tables already apply to themselves):

  1. WHICH CATEGORIES are required at all (`required_categories`).
     FAST requires only `dut_boundary` and `build_env` -- can a monitor even
     mount, and does the environment build -- a five-second sanity check
     before a quick local iteration, never a generation-readiness claim.
     STANDARD is `intake_state.BLOCKING_CATEGORIES` verbatim: DUT boundary,
     VIP unresolved, active-driver conflict, critical bind, build env,
     known-PASS test -- the existing fixed rule, unchanged, reachable here
     under an explicit name instead of being the only option. STRICT and
     SIGNOFF both require STANDARD's six PLUS `general` -- the seventh and
     last category `build_intake_state()` ever populates (DUT RTL/registers/
     address-map/clock-reset, VIP user-guide refs, component hierarchy,
     config_db trace, testplan correspondence) -- so between them STRICT and
     SIGNOFF cover every category this project's real intake ever produces.

  2. WHAT GRANULARITY a required category is checked AT
     (`require_all_fields`). FAST/STANDARD/STRICT all check a category by
     its existing worst-wins `category_status()` roll-up -- one condition
     per required category, exactly the shape `evaluate_uvm_generation_ready()`
     already checks. SIGNOFF is the one mode that switches axis: instead of
     one condition per category, it builds one condition PER RECORDED FIELD
     across the WHOLE `IntakeState` (every category, not only the required
     six-or-seven), so a human doing final sign-off review sees the exact
     FIELD blocking readiness rather than only the category name it belongs
     to. Because a category's worst-wins status can only be MET when every
     one of its own fields is already resolved-or-`NOT_APPLICABLE`, SIGNOFF's
     readiness BOOLEAN never disagrees with STRICT's over the same
     `IntakeState` -- the two differ in diagnostic granularity, not in what
     counts as ready, and a test proves exactly that equivalence.

STATUS MAPPING: `IntakeFieldStatus` (8 values) -> `CONDITION_STATUSES` (4)
-----------------------------------------------------------------------------
`verification_intake_contract.evaluate_intake_readiness()` speaks a smaller,
four-value vocabulary (`MET` / `UNMET` / `UNKNOWN` / `NOT_APPLICABLE`) than
`intake_state.py`'s eight-value one. The mapping below is a considered,
documented reduction, never an arbitrary one:

  - `AUTO_RESOLVED`, `USER_CONFIRMED`  -> `MET`           (a real resolution
    exists, machine- or human-sourced -- `intake_state.RESOLVED_STATUSES`
    verbatim).
  - `NOT_APPLICABLE`                    -> `NOT_APPLICABLE` (a caller
    explicitly declared this field out of scope -- never inferred).
  - `BLOCKED`, `CONTRADICTED`           -> `UNMET`         (real evidence was
    consulted and it says this field CANNOT proceed, or two real sources
    actively disagree -- both are "checked, and it failed", the same meaning
    `evaluate_intake_readiness()`'s own `UNMET` already carries).
  - `MISSING`, `UNKNOWN`, `PARTIAL`     -> `UNKNOWN`       (no evidence at
    all, evidence that could not be resolved, or only some sub-evidence
    resolved -- all three are "we do not yet know", the same meaning
    `evaluate_intake_readiness()`'s own `UNKNOWN` already carries).

`UNMET` and `UNKNOWN` both block a mode's readiness identically (per
`evaluate_intake_readiness()`'s own documented rule -- "this failed" and "we
do not know" must both stop a human from being told the project is ready),
so this mapping changes no readiness BOOLEAN versus a coarser one; it exists
so a rendered report never claims a genuinely unresolved (`MISSING`) field
was "checked and failed" (`UNMET`) when nobody has looked at it yet.

WHAT THIS MODULE DOES NOT DO
------------------------------
It builds conditions and reads `IntakeState`; it runs no gate script, writes
no state/blackboard/approval record, files no question, and holds no stage
gate of its own -- exactly the same boundary `intake_state.py`'s own
`evaluate_uvm_generation_ready()` already draws, one mode-selection layer
higher. `cli.py`/`gates.py` are untouched (both are large files under heavy
concurrent edit in this batch, per this task's own guidance to prefer a
standalone `python -m dv_harness.<module>` front door instead); the ad hoc
CLI here is `python -m dv_harness.intake_modes`.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field as _dc_field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import intake_state
from . import verification_intake_contract as vic

SCHEMA_VERSION = "1.0"


class IntakeModeError(ValueError):
    """Raised for an unrecognized mode name or an internally-inconsistent
    mode table, the same `reason`/`detail` convention `IntakeContractError`
    and `IntakeFieldRecord`'s own validation already use in this codebase."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---- mode vocabulary -------------------------------------------------------

class IntakeMode(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    STRICT = "STRICT"
    SIGNOFF = "SIGNOFF"


#: Declared rigor order, least to most strict -- checked, not merely implied,
#: by `assert_modes_monotonically_increasing()` below.
MODE_ORDER: Tuple[IntakeMode, ...] = (
    IntakeMode.FAST, IntakeMode.STANDARD, IntakeMode.STRICT, IntakeMode.SIGNOFF,
)

#: The one category `build_intake_state()` populates that
#: `intake_state.BLOCKING_CATEGORIES` never names -- see module docstring.
_GENERAL_CATEGORY = "general"


@dataclass(frozen=True)
class IntakeModeSpec:
    """One mode's own required-condition declaration: which categories are
    mandatory, and at what granularity (category roll-up, or every field)."""
    mode: IntakeMode
    required_categories: Tuple[str, ...]
    require_all_fields: bool
    description: str


MODE_SPECS: Dict[IntakeMode, IntakeModeSpec] = {
    IntakeMode.FAST: IntakeModeSpec(
        mode=IntakeMode.FAST,
        required_categories=("dut_boundary", "build_env"),
        require_all_fields=False,
        description=(
            "Minimal pre-iteration sanity check: can a monitor mount at all, "
            "and does the environment build. Not a generation-readiness claim."
        ),
    ),
    IntakeMode.STANDARD: IntakeModeSpec(
        mode=IntakeMode.STANDARD,
        required_categories=tuple(intake_state.BLOCKING_CATEGORIES),
        require_all_fields=False,
        description=(
            "The existing evaluate_uvm_generation_ready() rule, reachable "
            "under an explicit mode name: the six BLOCKING_CATEGORIES."
        ),
    ),
    IntakeMode.STRICT: IntakeModeSpec(
        mode=IntakeMode.STRICT,
        required_categories=tuple(intake_state.BLOCKING_CATEGORIES) + (_GENERAL_CATEGORY,),
        require_all_fields=False,
        description=(
            "STANDARD's six categories plus 'general' (DUT RTL/registers/"
            "address-map/clock-reset, VIP user-guide refs, component "
            "hierarchy, config_db trace, testplan correspondence) -- every "
            "category build_intake_state() ever populates, checked by "
            "category-level worst-wins roll-up."
        ),
    ),
    IntakeMode.SIGNOFF: IntakeModeSpec(
        mode=IntakeMode.SIGNOFF,
        required_categories=tuple(intake_state.BLOCKING_CATEGORIES) + (_GENERAL_CATEGORY,),
        require_all_fields=True,
        description=(
            "Same category coverage as STRICT, but checked per FIELD rather "
            "than per category roll-up, so a human doing final sign-off "
            "review sees exactly which field is blocking readiness."
        ),
    ),
}


def _assert_categories_known(mode: IntakeMode, categories: Sequence[str]) -> None:
    known = set(intake_state.BLOCKING_CATEGORIES) | {_GENERAL_CATEGORY}
    unknown = [c for c in categories if c not in known]
    if unknown:
        raise IntakeModeError("MODE_REQUIRES_UNKNOWN_CATEGORY", {
            "mode": mode.value, "unknown_categories": unknown,
            "known_categories": sorted(known)})


def assert_modes_monotonically_increasing() -> None:
    """Import-time guard: each mode in `MODE_ORDER` requires a category set
    that is a real SUPERSET of the previous mode's -- FAST's required
    categories are a subset of STANDARD's, which are a subset of STRICT's,
    which equal SIGNOFF's (SIGNOFF widens granularity, not category scope).
    A future edit that narrows a later mode's required set, or references a
    category `intake_state.py` does not actually produce, fails this at
    import rather than silently shipping a mode that is not actually
    stricter than the one before it."""
    prev_categories: set = set()
    for mode in MODE_ORDER:
        spec = MODE_SPECS[mode]
        _assert_categories_known(mode, spec.required_categories)
        current = set(spec.required_categories)
        if not prev_categories.issubset(current):
            raise IntakeModeError("MODE_ORDER_NOT_MONOTONIC", {
                "mode": mode.value,
                "missing_from_this_mode": sorted(prev_categories - current),
                "hint": "every category required by an earlier (less strict) "
                        "mode must still be required by every later mode",
            })
        prev_categories = current
    # SIGNOFF must be at least as strict as STRICT on the granularity axis
    # too: field-level checking is a real widening only when it checks every
    # field, never a narrower field subset than STRICT's category coverage
    # already implies.
    if not MODE_SPECS[IntakeMode.SIGNOFF].require_all_fields:
        raise IntakeModeError("SIGNOFF_MUST_REQUIRE_ALL_FIELDS", {})


assert_modes_monotonically_increasing()


def resolve_mode(mode: "IntakeMode | str") -> IntakeMode:
    """Normalizes a mode name or `IntakeMode` member. Raises `IntakeModeError`
    naming the real known modes on an unrecognized string, rather than
    silently falling back to any particular mode."""
    if isinstance(mode, IntakeMode):
        return mode
    try:
        return IntakeMode(str(mode).strip().upper())
    except ValueError:
        raise IntakeModeError("UNKNOWN_INTAKE_MODE", {
            "mode": mode, "known_modes": [m.value for m in MODE_ORDER]})


def mode_spec(mode: "IntakeMode | str") -> IntakeModeSpec:
    return MODE_SPECS[resolve_mode(mode)]


# ---- status vocabulary bridge: IntakeFieldStatus -> CONDITION_STATUSES ----

#: See module docstring's "STATUS MAPPING" section for the reasoning behind
#: every one of these eight entries.
_FIELD_STATUS_TO_CONDITION_STATUS: Dict[str, str] = {
    intake_state.IntakeFieldStatus.AUTO_RESOLVED.value: "MET",
    intake_state.IntakeFieldStatus.USER_CONFIRMED.value: "MET",
    intake_state.IntakeFieldStatus.NOT_APPLICABLE.value: "NOT_APPLICABLE",
    intake_state.IntakeFieldStatus.BLOCKED.value: "UNMET",
    intake_state.IntakeFieldStatus.CONTRADICTED.value: "UNMET",
    intake_state.IntakeFieldStatus.MISSING.value: "UNKNOWN",
    intake_state.IntakeFieldStatus.UNKNOWN.value: "UNKNOWN",
    intake_state.IntakeFieldStatus.PARTIAL.value: "UNKNOWN",
}


def _assert_status_mapping_total() -> None:
    known = {s.value for s in intake_state.IntakeFieldStatus}
    mapped = set(_FIELD_STATUS_TO_CONDITION_STATUS)
    if known != mapped:
        raise IntakeModeError("STATUS_MAPPING_INCOMPLETE", {
            "missing": sorted(known - mapped), "unexpected": sorted(mapped - known)})
    bad_targets = sorted(
        v for v in _FIELD_STATUS_TO_CONDITION_STATUS.values()
        if v not in vic.CONDITION_STATUSES
    )
    if bad_targets:
        raise IntakeModeError("STATUS_MAPPING_TARGETS_UNKNOWN_CONDITION_STATUS", {
            "bad_targets": bad_targets, "known_condition_statuses": sorted(vic.CONDITION_STATUSES)})


_assert_status_mapping_total()


def condition_status_for_field_status(status: str) -> str:
    """Maps one real `intake_state.IntakeFieldStatus` value onto
    `verification_intake_contract.CONDITION_STATUSES`. Raises rather than
    guessing on an unrecognized input -- the same fail-closed discipline
    `IntakeFieldRecord.__post_init__` already applies to the status it
    accepts in the first place."""
    try:
        return _FIELD_STATUS_TO_CONDITION_STATUS[status]
    except KeyError:
        raise IntakeModeError("UNKNOWN_INTAKE_FIELD_STATUS", {
            "status": status, "known_statuses": sorted(_FIELD_STATUS_TO_CONDITION_STATUS)})


# ---- building mode-specific conditions for INTAKE_READY --------------------

def build_mode_conditions(
    state: intake_state.IntakeState, mode: "IntakeMode | str",
) -> List[Dict[str, Any]]:
    """The parameterization this module exists to provide:
    `verification_intake_contract.evaluate_intake_readiness()`'s own
    `conditions` argument, built DIFFERENTLY per declared mode from ONE real
    `IntakeState` -- never a second copy of that state, never a re-derived
    fact.

    Category-granularity modes (FAST/STANDARD/STRICT) emit one condition per
    `mode_spec(mode).required_categories` entry, named `category:<name>`,
    from `IntakeState.category_status()` -- the SAME worst-wins roll-up
    `evaluate_uvm_generation_ready()` already uses for its own fixed rule.

    SIGNOFF emits one condition per RECORDED FIELD across the whole state
    (every category, not only the required six-or-seven), named
    `field:<name>`, from that field's own `IntakeFieldRecord.status` --
    never the category it belongs to. An `IntakeState` carrying zero records
    at all yields an empty list either way; `evaluate_intake_readiness()`
    itself turns that into an honest `NOT_AVAILABLE` (never a vacuous
    `READY`), so this function does not special-case it."""
    spec = mode_spec(mode)
    conditions: List[Dict[str, Any]] = []
    if spec.require_all_fields:
        for record in state.records:
            conditions.append({
                "name": f"field:{record.field}",
                "status": condition_status_for_field_status(record.status),
                "reason": (
                    f"[{record.category}] {record.reason}" if record.reason
                    else f"[{record.category}] no reason recorded"
                ),
            })
    else:
        for category in spec.required_categories:
            cat_status = state.category_status(category)
            conditions.append({
                "name": f"category:{category}",
                "status": condition_status_for_field_status(cat_status),
                "reason": f"worst-wins status for category {category!r}: {cat_status}",
            })
    return conditions


@dataclass
class ModeReadinessResult:
    """One mode's evaluation of one `IntakeState`: the mode itself, the
    granularity it checked at, and the real `IntakeReadinessResult`
    `verification_intake_contract.evaluate_intake_readiness()` produced --
    never re-interpreted here, carried through verbatim."""
    mode: str
    granularity: str  # "category" or "field"
    required_categories: List[str]
    readiness: vic.IntakeReadinessResult

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "granularity": self.granularity,
            "required_categories": self.required_categories,
            "readiness": self.readiness.to_dict(),
        }


def evaluate_intake_readiness_for_mode(
    state: intake_state.IntakeState,
    mode: "IntakeMode | str",
    *,
    now: Optional[str] = None,
) -> ModeReadinessResult:
    """The one function this module exists to provide: `INTAKE_READY` for
    `state`, gated by `mode`'s own required-condition set, computed by
    calling `verification_intake_contract.evaluate_intake_readiness()`
    unmodified over `build_mode_conditions(state, mode)`."""
    resolved = resolve_mode(mode)
    spec = MODE_SPECS[resolved]
    conditions = build_mode_conditions(state, resolved)
    readiness = vic.evaluate_intake_readiness(conditions, now=now)
    granularity = "field" if spec.require_all_fields else "category"
    return ModeReadinessResult(
        mode=resolved.value, granularity=granularity,
        required_categories=list(spec.required_categories), readiness=readiness,
    )


# ---- loading a persisted IntakeState (IntakeState.to_dict()-shaped) --------

def load_intake_state(doc: dict) -> intake_state.IntakeState:
    """Reconstructs an `IntakeState` from a document in exactly the shape
    `IntakeState.to_dict()` already emits (`{"fields": [...]}`) -- the
    round-trip a caller needs to persist a real `build_intake_state()`
    result and later evaluate it against a mode without rebuilding the
    original env-manifest/bind/question-queue inputs. Raises on a malformed
    document rather than silently constructing a partial state."""
    if not isinstance(doc, dict) or not isinstance(doc.get("fields"), list):
        raise IntakeModeError("MALFORMED_INTAKE_STATE_DOCUMENT", {
            "hint": "expected an IntakeState.to_dict()-shaped document with "
                    "a 'fields' list"})
    records = []
    for i, raw in enumerate(doc["fields"]):
        if not isinstance(raw, dict):
            raise IntakeModeError("MALFORMED_INTAKE_FIELD_RECORD", {"index": i, "record": raw})
        try:
            records.append(intake_state.IntakeFieldRecord(
                field=raw["field"], category=raw["category"], value=raw.get("value"),
                source=raw.get("source", ""), confidence=raw.get("confidence", "UNKNOWN"),
                status=raw["status"], last_validated=raw.get("last_validated"),
                owner=raw.get("owner"), reason=raw.get("reason", ""),
            ))
        except KeyError as e:
            raise IntakeModeError("INTAKE_FIELD_RECORD_MISSING_KEY", {
                "index": i, "missing_key": str(e)})
    return intake_state.IntakeState(records, generated_at=doc.get("generated_at"))


# ---- ad hoc front door -- no `dv-harness` CLI verb per this task's own scope
# (`cli.py`/`gates.py` are large files under heavy concurrent edit in this
# batch; `python -m` is the sanctioned fallback several sibling modules in
# this house style already use).
# ===========================================================================

def format_mode_readiness_report(result: ModeReadinessResult) -> str:
    r = result.readiness
    lines = [
        f"INTAKE_READY[{result.mode} / {result.granularity}]: {r.status} "
        f"(evaluated {r.evaluated_count} condition(s))",
    ]
    if r.blocking:
        lines.append("Blocking:")
        for c in r.blocking:
            reason = f" -- {c['reason']}" if c.get("reason") else ""
            lines.append(f"  - {c['name']}: {c['status']}{reason}")
    if r.clear:
        lines.append(f"Clear: {', '.join(c['name'] for c in r.clear)}")
    return "\n".join(lines)


def execute_verb(verb: str, *, mode: Optional[str] = None,
                  intake_state_path: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.intake_modes`.
    Returns (text, exit_code): 0 clean/ready, 1 not ready / a real finding,
    2 nothing to report or a usage error."""
    if verb == "modes":
        rows = [{"mode": m.value, "granularity": "field" if MODE_SPECS[m].require_all_fields else "category",
                  "required_categories": list(MODE_SPECS[m].required_categories),
                  "description": MODE_SPECS[m].description} for m in MODE_ORDER]
        text = json.dumps(rows, indent=2) if as_json else "\n".join(
            f"{r['mode']} ({r['granularity']}-level): {', '.join(r['required_categories'])}\n"
            f"    {r['description']}" for r in rows)
        return text, 0
    if verb == "conditions":
        if not mode:
            return "conditions requires --mode", 2
        try:
            spec = mode_spec(mode)
        except IntakeModeError as e:
            return f"{e.reason}: {json.dumps(e.detail)}", 2
        text = (json.dumps(dataclasses.asdict(spec), indent=2, default=lambda o: o.value if isinstance(o, IntakeMode) else o)
                if as_json else
                f"{spec.mode.value}: granularity={'field' if spec.require_all_fields else 'category'} "
                f"required_categories={list(spec.required_categories)}")
        return text, 0
    if verb == "evaluate":
        if not mode or not intake_state_path:
            return "evaluate requires --mode and --intake-state", 2
        try:
            with open(intake_state_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            state = load_intake_state(doc)
            result = evaluate_intake_readiness_for_mode(state, mode)
        except IntakeModeError as e:
            return f"{e.reason}: {json.dumps(e.detail)}", 2
        except (OSError, json.JSONDecodeError) as e:
            return f"CANNOT_READ_INTAKE_STATE: {e}", 2
        text = json.dumps(result.to_dict(), indent=2) if as_json else format_mode_readiness_report(result)
        code = {vic.READY: 0, vic.NOT_READY: 1, vic.NOT_AVAILABLE: 2}[result.readiness.status]
        return text, code
    return f"unknown verb: {verb!r} (expected modes|conditions|evaluate)", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.intake_modes",
        description="Intake rigor MODE (FAST/STANDARD/STRICT/SIGNOFF): "
                    "which intake_state.py fields/categories are mandatory, "
                    "evaluated through verification_intake_contract.py's own "
                    "INTAKE_READY conjunction.")
    ap.add_argument("verb", choices=("modes", "conditions", "evaluate"))
    ap.add_argument("--mode", help="For 'conditions'/'evaluate': FAST|STANDARD|STRICT|SIGNOFF.")
    ap.add_argument("--intake-state", dest="intake_state_path",
                    help="For 'evaluate': path to an IntakeState.to_dict()-shaped JSON document.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable form.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, mode=a.mode, intake_state_path=a.intake_state_path, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
