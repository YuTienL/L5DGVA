"""dv_harness/gui_intake_wizard.py -- GUI-01 INTERACTIVE INTAKE WIZARD: a real
backend endpoint sequence (GET the current step, POST an answer, POST
advance) plus a minimal server-rendered HTML wizard UI wired to it, entirely
grounded in `dv_harness/intake_state.py`'s real per-field `IntakeFieldRecord`
data and `dv_harness/question_queue.py`'s sanctioned ask/answer mechanism --
never a fabricated flow.

THE GAP THIS CLOSES
--------------------
`dashboard.py`'s only intake-facing surface is a flat "Intake Uploads" card:
five file-upload buttons with no guided sequence, no per-field grounding, and
no notion of "what does the harness still need to know before it can
generate" (GUI-01's own `ULTIMATE_COMPLETE_GUI.md` wording). A repo-wide
grep for `intake_wizard`/`INTAKE_STEP`/`/api/intake` in `dashboard.py` before
this module was written matched nothing. Section 59's expected flow --
`NEW/OPEN PROJECT -> Verification Level -> Spec -> RTL -> command.txt ->
Existing UVM Environment -> VIP -> vPlan -> Protocol -> Execution
Environment -> Evidence Discovery -> Missing Information -> Readiness ->
User Review` -- names fourteen steps, transcribed verbatim below as
`TASK_ORDERED_STEP_TITLES` and checked against `WIZARD_STEPS` at import time
(`_assert_steps_match_task_order()`), the same "compare against the
specification's own list" discipline `golden_flow_readiness.py`'s
`SECTION_47_ROW_LABELS` already applies to its own twenty rows.

REUSE, NOT REINVENTION
------------------------
This module authors NO per-field resolution logic of its own. Every step's
"what do we actually know" content is a direct, unmodified read of
`intake_state.build_intake_state()`'s real `IntakeFieldRecord` list -- the
same env.manifest.json-layer / connectivity bind-tier / question_queue
decision-overlay joining that module already performs, called here and
nowhere re-derived. Confirming an answer never invents a second "the human
said X" store: it goes through `question_queue.QuestionQueueStore.
add_question()` (Tier-3, `context={"affects_spec_intent": True}` -- an
intake decision genuinely affects what gets generated) followed by
`answer_question()`, the exact two-call sequence `intake_state.py`'s own
module docstring already prescribes for a caller ("`already_resolved()` is a
do-not-ask lookup a caller consults BEFORE calling ... `add_question()`").
The answer then reaches every subsequent read of intake state through
`intake_state.py`'s own real decision overlay (`_apply_decision_overlay()`),
not through anything this module writes to a per-field store of its own --
this module's only own persisted state is the wizard's OWN navigational
position (`WizardSession`: which of the fourteen steps is currently
displayed), which `intake_state.py` has no notion of and could not honestly
carry.

Field ownership/domain routing is likewise reversed out of the REAL routing
table rather than re-derived: every `IntakeFieldRecord.owner` this project
produces was itself assigned via `question_queue.route_owner("dut"/"vip"/
"env")`, so `_OWNER_TO_DOMAIN` is exactly `question_queue.
DOMAIN_OWNER_ROUTING` inverted -- there is no second category-to-domain
table anywhere in this file.

GROUNDING PER STEP, AND WHY SOME STEPS ARE HONESTLY UNGROUNDED
------------------------------------------------------------------
`intake_state.py` tracks a fixed, real set of fields: `dut_rtl`,
`dut_registers`, `dut_address_map`, `dut_clock_reset`, `vip_release`,
`vip_user_guide_refs`, `component_hierarchy`, `config_db_trace`,
`testplan_correspondence`, `bind:<target>` (one per real bind entry),
`dut_boundary`, `active_driver_conflict:<resource>` (one per real
conflict), `build_env`, `known_pass_tests`. Section 59's fourteen GUI steps
do not correspond 1:1 to that set -- four of them (`NEW / OPEN PROJECT`,
`Verification Level`, `Spec`, `command.txt`, `Protocol` -- five, not four;
counted below) name a concern `intake_state.py` genuinely tracks NO field
for at all. Per the Evidence Truth Rule, this module never invents a field
to fill that gap: `WizardStepDef.kind == KIND_UNMODELED` steps report
`grounded: false` with a real, stated reason instead, and render as a plain
navigational placeholder in the HTML (Prev/Next only, no fabricated
content, no answer form). The remaining nine steps each name an explicit,
real subset of `intake_state.py`'s own field names and/or categories
(`WIZARD_STEPS` below) -- `RTL` shows `dut_rtl`/`dut_registers`/
`dut_address_map`/`dut_clock_reset` plus the `dut_boundary` category;
`Existing UVM Environment` shows `component_hierarchy`/`config_db_trace`;
`VIP` shows `vip_user_guide_refs` plus the `vip_resolution` category (i.e.
`vip_release`); `vPlan` shows `testplan_correspondence`; `Execution
Environment` shows `build_env` plus the `critical_bind` category (every
real `bind:<target>` field, however many exist). `known_pass_test` and
`active_driver_conflict` -- the two remaining categories `evaluate_
uvm_generation_ready()` also folds -- have no single earlier step that
names them in section 59's own wording, so they surface honestly at
`Evidence Discovery` (literally EVERY real field, unfiltered) and `Missing
Information` (every field NOT already resolved and NOT declared
`NOT_APPLICABLE`) rather than being force-fitted under an unrelated earlier
step name. `Readiness` is `intake_state.evaluate_uvm_generation_ready()`
rendered directly -- the real refusal gate, never re-implemented. `User
Review` is a read-only summary of the same real state for a human's final
look before leaving the wizard.

WHAT THIS MODULE DOES NOT DO
------------------------------
It files no golden-reference-mined content, generates no VIP/RTL/protocol
text, and authors no fact `intake_state.py` did not already compute or a
real human did not just supply through the real question-queue answer path.
It runs no build/regression/LSF job, invokes no stage gate, and writes no
approval/governance record -- there is deliberately no `STAGE_GATES` entry
for this module. It is a standalone server: `dashboard.py` was, at the time
this was built, itself under heavy, very-recent concurrent edit pressure in
this same multi-agent batch (its own file mtime a few minutes old at build
time) -- the identical "large file under heavy edit pressure" situation
this batch's own house rules single out `cli.py`/`gates.py` for, applied
here to `dashboard.py` for the same reason. Rather than risk a collision
editing it, this module ships its own minimal `ThreadingHTTPServer` (the
same `http.server` primitives `dashboard.py` itself already uses) on its
own port, runnable via `python -m dv_harness.gui_intake_wizard`. Mounting
this wizard's three endpoints into `dashboard.py`'s own server process (or
adding a "Intake Wizard" nav link there) is a disclosed residual for a pass
that can safely touch that file.

P1-3 (2026-09-07, additive-only, deferred item): `render_wizard_html()` now
also renders `web_layout.render_nav()` / `web_layout.render_status_bar_partial()`
-- imported, never re-implemented -- immediately inside `<body>`, before this
wizard's own existing crumbs/step markup, so this standalone server gains the
same status-bar/nav STRUCTURE `dashboard.py`'s real Global Status Bar already
uses (see `web_layout.py`'s own module docstring for why the two share element
ids/classes). This is markup only: the status-bar partial is `web_layout.py`'s
own documented "STATIC shell, no live data, no `<script>` block" contract, and
nothing here wires it to a real `/api/status` poll or to this wizard's own
POST-based `/advance` navigation -- doing either would be exactly the
page-shell rewrite this item's own revision note says is out of scope. Every
existing route, endpoint, and rendering behavior of this server is unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import env_manifest
from . import intake_state
from . import question_queue
from . import web_layout
from .storage import _atomic_replace

SCHEMA_VERSION = "1.0"


class GuiIntakeWizardError(ValueError):
    """Raised for a malformed request or a refused action (an unrouted step,
    an already-resolved field, an unknown field/step). Carries `reason` (a
    short machine-checkable token) and `detail`, the same convention
    `IntakeContractError`/`GoldenFlowReadinessError` already use."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Section 1: the fourteen GUI-01 steps (section 59), transcribed verbatim
# ===========================================================================

TASK_ORDERED_STEP_TITLES: Tuple[str, ...] = (
    "NEW / OPEN PROJECT", "Verification Level", "Spec", "RTL", "command.txt",
    "Existing UVM Environment", "VIP", "vPlan", "Protocol",
    "Execution Environment", "Evidence Discovery", "Missing Information",
    "Readiness", "User Review",
)

KIND_UNMODELED = "UNMODELED"    #: no intake_state.py field backs this step
KIND_FIELDS = "FIELDS"          #: an explicit, named subset of real fields
KIND_ALL_FIELDS = "ALL_FIELDS"  #: every real field, unfiltered
KIND_GAPS = "GAPS"              #: every real field not already resolved
KIND_READINESS = "READINESS"    #: evaluate_uvm_generation_ready() rendered
KIND_REVIEW = "REVIEW"          #: read-only final summary


@dataclass(frozen=True)
class WizardStepDef:
    step_id: str
    title: str
    kind: str
    field_names: Tuple[str, ...] = ()
    categories: Tuple[str, ...] = ()


WIZARD_STEPS: Tuple[WizardStepDef, ...] = (
    WizardStepDef("new_open_project", "NEW / OPEN PROJECT", KIND_UNMODELED),
    WizardStepDef("verification_level", "Verification Level", KIND_UNMODELED),
    WizardStepDef("spec", "Spec", KIND_UNMODELED),
    WizardStepDef(
        "rtl", "RTL", KIND_FIELDS,
        field_names=("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset"),
        categories=("dut_boundary",),
    ),
    WizardStepDef("command_txt", "command.txt", KIND_UNMODELED),
    WizardStepDef(
        "existing_uvm_environment", "Existing UVM Environment", KIND_FIELDS,
        field_names=("component_hierarchy", "config_db_trace"),
    ),
    WizardStepDef(
        "vip", "VIP", KIND_FIELDS,
        field_names=("vip_user_guide_refs",), categories=("vip_resolution",),
    ),
    WizardStepDef("vplan", "vPlan", KIND_FIELDS, field_names=("testplan_correspondence",)),
    WizardStepDef("protocol", "Protocol", KIND_UNMODELED),
    WizardStepDef(
        "execution_environment", "Execution Environment", KIND_FIELDS,
        field_names=("build_env",), categories=("critical_bind",),
    ),
    WizardStepDef("evidence_discovery", "Evidence Discovery", KIND_ALL_FIELDS),
    WizardStepDef("missing_information", "Missing Information", KIND_GAPS),
    WizardStepDef("readiness", "Readiness", KIND_READINESS),
    WizardStepDef("user_review", "User Review", KIND_REVIEW),
)

_STEP_BY_ID: Dict[str, WizardStepDef] = {s.step_id: s for s in WIZARD_STEPS}


def _assert_steps_match_task_order() -> None:
    declared = tuple(s.title for s in WIZARD_STEPS)
    if declared != TASK_ORDERED_STEP_TITLES:
        raise GuiIntakeWizardError("STEP_ORDER_CHANGED", {
            "declared": list(declared), "task_specified": list(TASK_ORDERED_STEP_TITLES)})
    ids = [s.step_id for s in WIZARD_STEPS]
    if len(set(ids)) != len(ids):
        raise GuiIntakeWizardError("DUPLICATE_STEP_ID", {"ids": ids})


_assert_steps_match_task_order()


# ===========================================================================
# Section 2: grounding -- intake_state.py's real per-field records, joined
# with question_queue.py's real ask/answer store, never re-derived
# ===========================================================================

#: Reversed straight out of the real routing table -- question_queue.py's
#: own `route_owner()` is what assigned every record's `.owner` in the first
#: place, so this is the one honest way back from "who owns this field" to
#: "which domain a NEW question about it must be filed under".
_OWNER_TO_DOMAIN: Dict[str, str] = {
    owner: domain for domain, owner in question_queue.DOMAIN_OWNER_ROUTING.items()
}

#: Statuses `intake_state.py` itself folds as "resolved" for `already_resolved()`.
_RESOLVED_STATUSES = intake_state.RESOLVED_STATUSES
_NOT_APPLICABLE = intake_state.IntakeFieldStatus.NOT_APPLICABLE.value

INTAKE_INPUTS_FILENAME = "intake_inputs.json"
SESSION_FILENAME = "session.json"


def _wizard_dir(root) -> Path:
    return Path(root) / ".dv-harness" / "gui_intake_wizard"


def _is_gap(record: "intake_state.IntakeFieldRecord") -> bool:
    return record.status not in _RESOLVED_STATUSES and record.status != _NOT_APPLICABLE


def _domain_for_record(record: "intake_state.IntakeFieldRecord") -> Optional[str]:
    """The question_queue domain a NEW question about `record` must be filed
    under, or `None` when `record.owner` is not one of the three real
    routed owner strings -- which, under `intake_state.py`'s own real
    resolution rules, only happens once a field is already resolved by a
    named human confirmation (a T3 bind's `confirmed_by`), i.e. a case
    `answer_field()` already refuses one check earlier via
    `already_resolved()`. Kept as an explicit, honestly-reported refusal
    rather than an unguarded KeyError."""
    return _OWNER_TO_DOMAIN.get(record.owner)


def _context_path_for_field(field_name: str) -> str:
    return f"gui_intake_wizard:{field_name}"


def _question_text_for_field(field_name: str) -> str:
    return f"Confirm the real value for intake field '{field_name}'."


def _load_intake_inputs(root) -> Dict[str, Any]:
    """The wizard's own small, honestly-optional input file, naming the SAME
    keyword arguments `intake_state.build_intake_state()` itself accepts:
    `env_manifest` (an inline dict -- the same partial/hand-shaped form
    `dv_harness_tests/test_intake_state.py`'s own fixtures already treat as
    legitimate input, e.g. `{"dut_facts": {"registers": ...}}`) or
    `env_manifest_path`, plus `bind_entries`/`dut_boundary`/
    `active_driver_conflicts`/`build_env_gate`/`known_pass_tests`. This
    module invents none of these facts -- it only assembles whatever a
    caller (a human, an upstream discovery step) already placed here.
    Absent entirely, every argument stays unset -- the same "a caller with
    only... nothing else still gets a real, honest IntakeState" resilience
    `build_intake_state()` already documents for itself."""
    path = _wizard_dir(root) / INTAKE_INPUTS_FILENAME
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": f"{INTAKE_INPUTS_FILENAME} could not be read: {type(exc).__name__}: {exc}"}
    if not isinstance(doc, dict):
        return {"_load_error": f"{INTAKE_INPUTS_FILENAME} is not a JSON object"}
    return doc


def _load_env_manifest_for(root, inputs: Dict[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    """`(env_manifest_dict_or_None, note)`. An inline `env_manifest` in
    `intake_inputs.json` wins; else an explicit `env_manifest_path`; else
    the project's real on-disk `env.manifest.json` via
    `env_manifest.default_manifest_path()` -- reused, never a second
    hardcoded path convention. A present-but-invalid/unreadable file is
    reported as a `note` rather than silently read as absent."""
    inline = inputs.get("env_manifest")
    if isinstance(inline, dict):
        return inline, None
    candidate = inputs.get("env_manifest_path")
    if not candidate:
        default = env_manifest.default_manifest_path(root)
        candidate = str(default) if default is not None else None
    if not candidate:
        return None, None
    try:
        return env_manifest.load_env_manifest(candidate), None
    except FileNotFoundError:
        return None, None
    except Exception as exc:
        return None, f"{candidate} could not be loaded: {type(exc).__name__}: {exc}"


def _intake_state_kwargs(root) -> Tuple[Dict[str, Any], Optional[str]]:
    inputs = _load_intake_inputs(root)
    manifest, note = _load_env_manifest_for(root, inputs)
    kwargs: Dict[str, Any] = {
        "env_manifest": manifest,
        "bind_entries": inputs.get("bind_entries"),
        "dut_boundary": inputs.get("dut_boundary"),
        "active_driver_conflicts": inputs.get("active_driver_conflicts"),
        "build_env_gate": inputs.get("build_env_gate"),
        "known_pass_tests": inputs.get("known_pass_tests"),
    }
    return kwargs, (inputs.get("_load_error") or note)


def build_grounded_intake_state(root) -> Tuple[
        "intake_state.IntakeState", Dict[str, str], "question_queue.QuestionQueueStore", Optional[str]]:
    """The one real grounding call every GET/POST in this module goes
    through: `(intake_state, field_question_keys, question_store, note)`.

    Built in two passes over the exact same real inputs, because a field's
    real `question_key` needs its real `owner` (to route the domain) and
    its real `field` name (for `bind:*`/`active_driver_conflict:*` entries,
    whose count is not known until `intake_state.py` has already resolved
    them) -- both only exist after a first, un-overlaid
    `build_intake_state()` call. The SECOND call re-runs
    `build_intake_state()` with a real `question_queue.QuestionQueueStore`
    and that derived `field_question_keys` map, so any human answer already
    on file reaches this state through `intake_state.py`'s own real
    decision overlay -- never a second resolution path."""
    root = Path(root)
    kwargs, note = _intake_state_kwargs(root)
    raw_state = intake_state.build_intake_state(**kwargs)
    field_question_keys: Dict[str, str] = {}
    for r in raw_state.records:
        domain = _domain_for_record(r)
        if domain is None:
            continue
        field_question_keys[r.field] = question_queue.make_question_key(
            domain, _question_text_for_field(r.field), _context_path_for_field(r.field))
    store = question_queue.QuestionQueueStore(root)
    final_state = intake_state.build_intake_state(
        question_store=store, field_question_keys=field_question_keys, **kwargs)
    return final_state, field_question_keys, store, note


# ===========================================================================
# Section 3: wizard navigation state (this module's own -- never a claim
# about intake_state.py's own data)
# ===========================================================================

@dataclass
class WizardSession:
    current_step_index: int = 0

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "current_step_index": self.current_step_index}


def load_session(root) -> WizardSession:
    path = _wizard_dir(root) / SESSION_FILENAME
    if not path.exists():
        return WizardSession()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        idx = int(doc.get("current_step_index", 0))
    except Exception:
        return WizardSession()
    idx = max(0, min(idx, len(WIZARD_STEPS) - 1))
    return WizardSession(current_step_index=idx)


def save_session(root, session: WizardSession) -> None:
    d = _wizard_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="session.", suffix=".json", dir=str(d))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        _atomic_replace(tmp, d / SESSION_FILENAME)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ===========================================================================
# Section 4: per-step view assembly -- pure functions over a real IntakeState
# ===========================================================================

def _record_to_dict(r: "intake_state.IntakeFieldRecord") -> dict:
    d = r.to_dict()
    d["already_resolved"] = r.status in _RESOLVED_STATUSES
    d["is_gap"] = _is_gap(r)
    return d


def _fields_for_step(step: WizardStepDef, state: "intake_state.IntakeState"
                      ) -> List["intake_state.IntakeFieldRecord"]:
    out: List["intake_state.IntakeFieldRecord"] = []
    for r in state.records:
        if r.field in step.field_names or r.category in step.categories:
            out.append(r)
    return out


def build_step_view(step: WizardStepDef, state: "intake_state.IntakeState",
                     readiness: "Optional[intake_state.UvmGenerationReadiness]" = None) -> dict:
    """The honest, grounded content for ONE step. `KIND_UNMODELED` reports
    `grounded: False` with a real reason and never a fabricated field list;
    every other kind is a direct read of `state`'s real records (or the
    real `evaluate_uvm_generation_ready()` result for `KIND_READINESS`/
    `KIND_REVIEW`) -- this function computes no new intake fact."""
    if step.kind == KIND_UNMODELED:
        return {
            "grounded": False, "kind": step.kind, "fields": [],
            "reason": (
                "intake_state.py tracks no per-field record for this step; it is a "
                "navigational placeholder only, never a fabricated fact."
            ),
        }
    if step.kind == KIND_FIELDS:
        fields = _fields_for_step(step, state)
        return {"grounded": True, "kind": step.kind, "fields": [_record_to_dict(r) for r in fields]}
    if step.kind == KIND_ALL_FIELDS:
        return {
            "grounded": True, "kind": step.kind,
            "fields": [_record_to_dict(r) for r in state.records],
            "generated_at": state.generated_at,
        }
    if step.kind == KIND_GAPS:
        gaps = [r for r in state.records if _is_gap(r)]
        return {"grounded": True, "kind": step.kind, "fields": [_record_to_dict(r) for r in gaps]}
    if step.kind == KIND_READINESS:
        readiness = readiness or intake_state.evaluate_uvm_generation_ready(state)
        return {
            "grounded": True, "kind": step.kind, "fields": [],
            "ready": readiness.ready, "blocking": readiness.blocking,
            "blocking_categories": sorted(readiness.blocking), "checked_at": readiness.checked_at,
        }
    if step.kind == KIND_REVIEW:
        readiness = readiness or intake_state.evaluate_uvm_generation_ready(state)
        gap_count = len([r for r in state.records if _is_gap(r)])
        return {
            "grounded": True, "kind": step.kind, "fields": [],
            "ready": readiness.ready, "blocking_categories": sorted(readiness.blocking),
            "field_count": len(state.records), "gap_count": gap_count,
            "generated_at": state.generated_at,
        }
    raise GuiIntakeWizardError("UNKNOWN_STEP_KIND", {"kind": step.kind})  # pragma: no cover


# ===========================================================================
# Section 5: the real backend endpoint sequence -- GET the current step,
# POST an answer, POST advance
# ===========================================================================

def get_state_view(root) -> dict:
    """GET the current step: the full grounded view for whichever of the
    fourteen steps this project's wizard session currently sits on."""
    root = Path(root)
    state, _field_question_keys, _store, note = build_grounded_intake_state(root)
    session = load_session(root)
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    step = WIZARD_STEPS[session.current_step_index]
    view = build_step_view(step, state, readiness=readiness)
    return {
        "schema_version": SCHEMA_VERSION,
        "step": {
            "id": step.step_id, "title": step.title,
            "index": session.current_step_index, "total": len(WIZARD_STEPS),
        },
        "steps": [
            {"id": s.step_id, "title": s.title, "grounded": s.kind != KIND_UNMODELED}
            for s in WIZARD_STEPS
        ],
        "view": view,
        "overall_ready": readiness.ready,
        "note": note,
    }


def _find_open_or_assumed_question(store: "question_queue.QuestionQueueStore",
                                    question_key: str) -> Optional[dict]:
    candidates = [
        q for q in store.list_questions()
        if q.get("question_key") == question_key and q.get("status") in ("OPEN", "ASSUMED")
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda q: q.get("created_at") or "")[-1]


def answer_field(root, field_name: Optional[str], answer: Optional[str],
                  basis: Optional[str] = None, decided_by: Optional[str] = None) -> dict:
    """POST an answer for one real intake_state.py field.

    Reuses `question_queue.QuestionQueueStore.add_question()` (Tier-3,
    `context={"affects_spec_intent": True}` -- a real, honest fact: which
    intake fields the harness proceeds on genuinely affects what it will go
    on to generate) followed by `answer_question()` -- the exact sanctioned
    ask/answer sequence, never a second per-field answer store of this
    module's own. `intake_state.already_resolved()` is consulted FIRST, so a
    field the do-not-ask rule already covers is refused rather than
    re-answered -- the "GUI must not ask the user to re-enter something
    already discoverable" rule (section 59) enforced at the write boundary,
    not merely by the UI not offering a form."""
    root = Path(root)
    if not field_name or not str(field_name).strip():
        raise GuiIntakeWizardError("EMPTY_FIELD_NAME", {})
    field_name = str(field_name).strip()
    if answer is None or not str(answer).strip():
        raise GuiIntakeWizardError("EMPTY_ANSWER", {"field": field_name})
    answer = str(answer).strip()

    state, field_question_keys, store, _note = build_grounded_intake_state(root)
    record = state.get(field_name)
    if record is None:
        raise GuiIntakeWizardError("UNKNOWN_FIELD", {
            "field": field_name, "known_fields": sorted(r.field for r in state.records)})
    if intake_state.already_resolved(state, field_name):
        raise GuiIntakeWizardError("FIELD_ALREADY_RESOLVED", {
            "field": field_name, "status": record.status,
            "hint": "this field is already resolved; the do-not-ask rule refuses a re-ask",
        })
    domain = _domain_for_record(record)
    if domain is None:
        raise GuiIntakeWizardError("FIELD_NOT_ROUTABLE", {"field": field_name, "owner": record.owner})

    question_key = field_question_keys.get(field_name) or question_queue.make_question_key(
        domain, _question_text_for_field(field_name), _context_path_for_field(field_name))
    existing = _find_open_or_assumed_question(store, question_key)
    if existing is None:
        # question.schema.json requires 2-3 PRE-RESEARCHED options (never an
        # open-ended free-text question) -- satisfied honestly here, not
        # worked around, because the wizard already HAS the human's real
        # typed value by the time this question is filed (the POST body
        # carries both in one step): the first option IS that real value,
        # never a placeholder the human has to invent from scratch, and the
        # second is the one other legitimate real outcome this exact ask can
        # honestly have -- the human declines to confirm it after all.
        existing = store.add_question(
            domain=domain, question=_question_text_for_field(field_name),
            context_path=_context_path_for_field(field_name),
            options=[answer, "UNCONFIRMED (left unanswered by the human)"], recommendation=answer,
            assumption_if_unanswered=(
                f"Field '{field_name}' left unconfirmed pending a real human GUI "
                f"intake-wizard answer."
            ),
            question_key=question_key,
            context={"affects_spec_intent": True, "gui_intake_wizard_field": field_name},
        )
    basis_text = str(basis).strip() if basis else ""
    if not basis_text:
        basis_text = "Confirmed via the GUI intake wizard."
    decided_by_text = str(decided_by).strip() if decided_by else "gui_intake_wizard"
    return store.answer_question(
        existing["id"], answer=answer, basis=basis_text, decided_by=decided_by_text)


def advance_step(root, *, direction: Optional[str] = None, step_id: Optional[str] = None) -> dict:
    """POST advance: move the wizard's own navigational position (never
    intake_state.py's data) either `direction="next"`/`"back"` (clamped to
    the fourteen real steps) or directly to a named `step_id`. Returns the
    same shape `get_state_view()` returns, for the step now current."""
    root = Path(root)
    session = load_session(root)
    if step_id is not None:
        if step_id not in _STEP_BY_ID:
            raise GuiIntakeWizardError("UNKNOWN_STEP", {
                "step_id": step_id, "known_steps": list(_STEP_BY_ID)})
        session.current_step_index = list(_STEP_BY_ID).index(step_id)
    elif direction == "next":
        session.current_step_index = min(session.current_step_index + 1, len(WIZARD_STEPS) - 1)
    elif direction == "back":
        session.current_step_index = max(session.current_step_index - 1, 0)
    else:
        raise GuiIntakeWizardError("UNKNOWN_DIRECTION", {
            "direction": direction, "known_directions": ["next", "back"],
            "hint": "pass step_id= for a direct goto",
        })
    save_session(root, session)
    return get_state_view(root)


# ===========================================================================
# Section 6: minimal server-rendered HTML -- no client-side JS required; a
# classic form-POST-then-redirect wizard, matching "minimal" literally
# ===========================================================================

def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


_CSS = (
    "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#1a1a1a}"
    ".crumbs{font-size:12px;color:#666;margin-bottom:8px}"
    ".note{background:#fff8e1;border:1px solid #e0c46c;padding:6px 10px;margin:8px 0;font-size:13px}"
    ".unmodeled{background:#eef;border:1px solid #99c;padding:10px;margin:12px 0}"
    ".error{background:#fee;border:1px solid #c66;padding:10px;margin:12px 0;color:#900}"
    "table.fields{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}"
    "table.fields th,table.fields td{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}"
    "table.fields th{background:#f2f2f2}"
    "form.inline{display:inline;margin:0}"
    "input[type=text]{width:110px;margin-right:2px}"
    "button{cursor:pointer}"
    "</style>"
)


def _answer_form_html(field_name: str) -> str:
    return (
        f'<form class="inline" method="POST" action="/answer">'
        f'<input type="hidden" name="field" value="{_esc(field_name)}">'
        f'<input type="text" name="answer" placeholder="answer">'
        f'<input type="text" name="basis" placeholder="basis (optional)">'
        f'<input type="text" name="decided_by" placeholder="your name">'
        f'<button type="submit">Confirm</button></form>'
    )


def render_wizard_html(doc: dict) -> str:
    step = doc["step"]
    view = doc["view"]
    # P1-3 (additive, deferred item): a shared status-bar/nav partial from
    # `web_layout.py`, inserted at a fixed point (immediately inside `<body>`,
    # before this wizard's own existing crumbs/step markup) -- structure only,
    # never a rewrite of this server's own already-working page shell. The nav
    # entries are this wizard's own real fourteen steps (`doc["steps"]`, the
    # same list the crumbs trail below already renders from), so the partial
    # never invents a route this page does not already have.
    layout_partial = (
        web_layout.render_nav([(s["id"], s["title"]) for s in doc["steps"]], active=step["id"])
        + web_layout.render_status_bar_partial()
    )
    crumbs = " &rarr; ".join(
        (f'<b>{_esc(s["title"])}</b>' if s["id"] == step["id"] else _esc(s["title"]))
        for s in doc["steps"]
    )
    parts: List[str] = [
        '<div class="crumbs">' + crumbs + "</div>",
        f'<h2>Step {step["index"] + 1} / {step["total"]}: {_esc(step["title"])}</h2>',
    ]
    if doc.get("note"):
        parts.append(f'<div class="note">{_esc(doc["note"])}</div>')
    if not view.get("grounded"):
        parts.append(f'<div class="unmodeled">{_esc(view.get("reason", ""))}</div>')
    elif view["kind"] == KIND_READINESS:
        parts.append(f'<p>UVM_GENERATION_READY: <b>{view["ready"]}</b></p>')
        if view["blocking_categories"]:
            parts.append(
                "<p>Blocking categories:</p><ul>"
                + "".join(f"<li>{_esc(c)}</li>" for c in view["blocking_categories"])
                + "</ul>"
            )
    elif view["kind"] == KIND_REVIEW:
        parts.append(
            f'<p>Fields tracked: {view["field_count"]} &middot; '
            f'Gaps remaining: {view["gap_count"]} &middot; '
            f'UVM_GENERATION_READY: <b>{view["ready"]}</b></p>'
        )
    if view.get("fields"):
        rows = ['<table class="fields"><tr><th>Field</th><th>Category</th><th>Status</th>'
                "<th>Confidence</th><th>Value</th><th>Reason</th><th>Owner</th><th>Answer</th></tr>"]
        for f in view["fields"]:
            answer_cell = "(already resolved)" if f["already_resolved"] else _answer_form_html(f["field"])
            rows.append(
                "<tr>"
                f'<td>{_esc(f["field"])}</td><td>{_esc(f["category"])}</td>'
                f'<td>{_esc(f["status"])}</td><td>{_esc(f["confidence"])}</td>'
                f'<td>{_esc(f["value"])}</td><td>{_esc(f["reason"])}</td>'
                f'<td>{_esc(f["owner"])}</td><td>{answer_cell}</td>'
                "</tr>"
            )
        rows.append("</table>")
        parts.append("".join(rows))
    parts.append(
        '<form class="inline" method="POST" action="/advance">'
        '<input type="hidden" name="direction" value="back">'
        "<button>&larr; Back</button></form> "
        '<form class="inline" method="POST" action="/advance">'
        '<input type="hidden" name="direction" value="next">'
        "<button>Next &rarr;</button></form>"
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>GUI-01 Interactive Intake Wizard</title>" + _CSS + "</head><body>"
        + layout_partial + "".join(parts) + "</body></html>"
    )


def render_error_html(doc: dict, exc: GuiIntakeWizardError) -> str:
    html = render_wizard_html(doc)
    banner = f'<div class="error">{_esc(exc.reason)}: {_esc(json.dumps(exc.detail, default=str))}</div>'
    return html.replace("<body>", "<body>" + banner, 1)


# ===========================================================================
# Section 7: the standalone server -- dashboard.py's own ThreadingHTTPServer/
# BaseHTTPRequestHandler primitives, nested (not touching dashboard.py at
# all) so `project_root` is captured by closure exactly as dashboard.py's
# own `run_dashboard()` already does for its own Handler.
# ===========================================================================

def build_server(project_root, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Constructs (but does not start) the wizard's own ThreadingHTTPServer,
    bound to `project_root`. `port=0` lets the OS pick a free port -- read
    it back via `server.server_address[1]`, the same pattern this module's
    own tests use."""
    root = Path(project_root)

    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, payload: Any) -> None:
            self._send_bytes(code, json.dumps(payload, default=str).encode("utf-8"), "application/json")

        def _send_html(self, code: int, html: str) -> None:
            self._send_bytes(code, html.encode("utf-8"), "text/html; charset=utf-8")

        def _redirect_home(self) -> None:
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_form(self) -> Tuple[Dict[str, Any], bool]:
            """`(data, was_json)`. Accepts either a JSON body (the real API
            path) or a classic `application/x-www-form-urlencoded` POST (the
            server-rendered HTML forms above) -- one reader, two accepted
            shapes, matching `dashboard.py`'s own `POST /api/upload` vs.
            classic-form-tolerant convention."""
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype == "application/json":
                try:
                    return (json.loads(raw.decode("utf-8")) if raw else {}), True
                except Exception:
                    return {}, True
            parsed = parse_qs(raw.decode("utf-8"))
            return {k: v[0] for k, v in parsed.items()}, False

        def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming
            path = urlparse(self.path).path
            try:
                if path in ("/", ""):
                    doc = get_state_view(root)
                    self._send_html(200, render_wizard_html(doc))
                elif path == "/api/state":
                    self._send_json(200, get_state_view(root))
                else:
                    self._send_json(404, {"error": "NOT_FOUND", "path": path})
            except Exception as exc:  # pragma: no cover - defensive
                self._send_json(500, {"error": "INTERNAL_ERROR", "message": str(exc)})

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            data, was_json = self._read_form()
            try:
                if path in ("/answer", "/api/answer"):
                    result = answer_field(
                        root, data.get("field"), data.get("answer"),
                        data.get("basis"), data.get("decided_by"))
                    if was_json:
                        self._send_json(200, {"answered": result})
                    else:
                        self._redirect_home()
                elif path in ("/advance", "/api/advance"):
                    result = advance_step(
                        root, direction=data.get("direction"), step_id=data.get("step_id"))
                    if was_json:
                        self._send_json(200, result)
                    else:
                        self._redirect_home()
                else:
                    self._send_json(404, {"error": "NOT_FOUND", "path": path})
            except GuiIntakeWizardError as exc:
                if was_json:
                    self._send_json(400, {"error": exc.reason, "detail": exc.detail})
                else:
                    try:
                        doc = get_state_view(root)
                        self._send_html(400, render_error_html(doc, exc))
                    except Exception:  # pragma: no cover - defensive
                        self._send_json(400, {"error": exc.reason, "detail": exc.detail})
            except Exception as exc:  # pragma: no cover - defensive
                self._send_json(500, {"error": "INTERNAL_ERROR", "message": str(exc)})

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass  # keep test/CLI output quiet, mirroring dashboard.py's own Handler

    return ThreadingHTTPServer((host, port), Handler)


def run_server(project_root, host: str = "127.0.0.1", port: int = 8799) -> None:
    """Starts the wizard's own ThreadingHTTPServer and blocks
    (`serve_forever()`) -- the `python -m dv_harness.gui_intake_wizard`
    entry point."""
    build_server(project_root, host, port).serve_forever()


# ===========================================================================
# Ad hoc CLI front door
# ===========================================================================

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.gui_intake_wizard",
        description="GUI-01 Interactive Intake Wizard: a real backend endpoint sequence "
                    "(GET the current step, POST an answer, POST advance) plus a minimal "
                    "server-rendered HTML wizard UI, grounded entirely in intake_state.py's "
                    "real per-field records.",
    )
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args(argv)
    print(f"GUI-01 intake wizard serving http://{args.host}:{args.port}/ "
          f"for project root {args.project_root}")
    run_server(args.project_root, args.host, args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
