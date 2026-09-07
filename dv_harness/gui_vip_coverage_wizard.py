"""dv_harness/gui_vip_coverage_wizard.py -- GUI-XX: Interactive VIP-Based
Environment Creation to 100%-Coverage Wizard.

A standalone `ThreadingHTTPServer` (own process, `python -m
dv_harness.gui_vip_coverage_wizard --project-root <dir> --port <n>`),
following the EXACT precedent `gui_intake_wizard.py` and
`gui_intake_control_plane.py` already established: never imports
`dashboard.py`/`engine.py`/`gates.py`/`cli.py`, reuses only
`dashboard_auth.presented_token()` + `secrets.compare_digest()` for the
Authorization/`?token=` header parsing (never `dashboard_auth.
issue_session_token()`, which is `dashboard.py`'s own token, minted for its
own session file), and mints its OWN session token via the same
`storage._atomic_replace()` atomic-write-then-`secrets.compare_digest()`
pattern `gui_intake_control_plane.py` already established.

Walks a user through 11 REAL, grounded steps -- DUT/RTL discovery, VIP
discovery, bind-tier/PHY-boundary readiness, the VIP Learning Gate, UVM
generation readiness, VIP/UVM generation, single-test proof, coverage-hole
identification, ranked coverage-closure actions, functional coverage
signoff, and a terminal overall-maturity review -- each grounded in a REAL,
already-computed producer this project already ships:
`intake_state.py` (steps 1/2/3/5), `vip_learning_gate.py` (step 4),
`golden_flow_readiness.py` (steps 6/7), `coverage_analysis.py` (step 8),
`coverage_closure_action_utility.py` (step 9),
`functional_coverage_signoff.py` (step 10), `subsystem_maturity_gate.py`
(step 11). Every "confirm one fact" answer goes through the ONE sanctioned
question/decision mechanism this project already has --
`question_queue.QuestionQueueStore.add_question()` /
`answer_question()` -- never a second, wizard-local answer store.

The one "100% complete" signal this wizard emits, `overall_ready` on
`GET /api/state`, is EXACTLY Step 10's real
`functional_coverage_signoff_ready` boolean (or `null` when Step 10's own
required inputs were never available) -- this module computes NO
completion percentage of its own, and averages nothing.

Disclosed boundaries (never silently papered over): no live simulator; no
arbitration of an `active_driver_conflict` (Step 5's own blocking category
is reported, but this wizard cannot answer it via question_queue -- that is
a human/architecture decision, not a question with 2-3 candidate answers);
no waiver lifecycle (stays `waiver_store.py`'s own job); no VIP/RTL/pattern
CONTENT generation of any kind (No Golden-Reference Content Mining); no
fabricated completion percentage; and deliberately NO `STAGE_GATES` entry
of its own -- this is a REACHED capability (a real, standalone server a
user runs), never a WIRED engine stage.

A second, real, disclosed boundary: Step 3's own readiness
(`intake_state.py`'s `dut_boundary`/`critical_bind` category fold, driven
by this wizard's own `question_queue`-answered `bind:<target>` fields) is a
DIFFERENT real mechanism from `connectivity.enforce_bind_tier_policy()`'s
own, stricter Tier-3 requirement that a bind entry's own
`human_confirmation` sub-dict (`{source, confirmed_by, basis}`) be
populated directly. Answering a bind question through THIS wizard makes
`intake_state.py`'s OWN readiness view (and therefore this wizard's own
Step 3/Step 5) report the field resolved -- it does NOT, on its own,
populate a bind entry's `human_confirmation` sub-dict, so
`vip_learning_gate.py`'s own `check_bind_tier` sub-check (Step 4) can
genuinely still report BLOCKING even after Step 3 reads clean. This
divergence is real, and is disclosed here rather than silently unified
(unifying it would mean editing `intake_state.py` or `connectivity.py`,
both explicitly out of this module's file-safety scope).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from . import storage
from . import dashboard_auth
from . import intake_state
from . import question_queue
from . import vip_learning_gate
from . import golden_flow_readiness
from . import coverage_analysis
from . import coverage_closure_action_utility
from . import functional_coverage_signoff
from . import subsystem_maturity_gate
from . import env_manifest
from . import phy_boundary

try:  # pragma: no cover - real module built by concurrent batch work; optional
    from . import architecture_choice_ranking
except Exception:  # pragma: no cover
    architecture_choice_ranking = None


# ===========================================================================
# Errors
# ===========================================================================

class GuiVipCoverageWizardError(ValueError):
    """A user-facing refusal -- carries a machine-checkable `.reason` plus a
    real, specific `.detail` (never a bare generic message)."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ===========================================================================
# Step declarations
# ===========================================================================

KIND_FIELDS = "fields"
KIND_BIND = "bind"
KIND_COMPOSITE_READOUT = "composite_readout"
KIND_READINESS = "readiness"
KIND_GOLDEN_FLOW_ROW = "golden_flow_row"
KIND_COVERAGE_HOLES = "coverage_holes"
KIND_CLOSURE_RANKING = "closure_ranking"
KIND_COVERAGE_SIGNOFF = "coverage_signoff"
KIND_MATURITY_REVIEW = "maturity_review"


@dataclass(frozen=True)
class WizardStepDef:
    step_id: str
    title: str
    kind: str
    fields: Tuple[str, ...] = ()
    categories: Tuple[str, ...] = ()
    row_id: Optional[str] = None


TASK_ORDERED_STEP_TITLES: Tuple[str, ...] = (
    "DUT/RTL Discovery",
    "VIP Discovery / Capability Readiness",
    "Bind-Tier / PHY-Boundary Readiness",
    "VIP Learning Gate",
    "UVM Generation Readiness",
    "VIP/UVM Generation",
    "Single-Test Proof",
    "Coverage-Hole Identification",
    "Ranked Coverage-Closure Actions",
    "Functional Coverage Signoff",
    "Overall Maturity Summary",
)

WIZARD_STEPS: Tuple[WizardStepDef, ...] = (
    WizardStepDef("dut_rtl_discovery", "DUT/RTL Discovery", KIND_FIELDS,
                  fields=("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset")),
    WizardStepDef("vip_discovery", "VIP Discovery / Capability Readiness", KIND_FIELDS,
                  categories=("vip_resolution",), fields=("vip_release", "vip_user_guide_refs")),
    WizardStepDef("bind_tier_phy_boundary", "Bind-Tier / PHY-Boundary Readiness", KIND_BIND,
                  categories=("dut_boundary", "critical_bind")),
    WizardStepDef("vip_learning_gate", "VIP Learning Gate", KIND_COMPOSITE_READOUT),
    WizardStepDef("uvm_generation_readiness", "UVM Generation Readiness", KIND_READINESS),
    WizardStepDef("vip_uvm_generation", "VIP/UVM Generation", KIND_GOLDEN_FLOW_ROW,
                  row_id="vip_uvm_generation"),
    WizardStepDef("single_test_proof", "Single-Test Proof", KIND_GOLDEN_FLOW_ROW,
                  row_id="single_test_proof"),
    WizardStepDef("coverage_hole_identification", "Coverage-Hole Identification", KIND_COVERAGE_HOLES),
    WizardStepDef("ranked_closure_actions", "Ranked Coverage-Closure Actions", KIND_CLOSURE_RANKING),
    WizardStepDef("functional_coverage_signoff", "Functional Coverage Signoff", KIND_COVERAGE_SIGNOFF),
    WizardStepDef("overall_maturity_summary", "Overall Maturity Summary", KIND_MATURITY_REVIEW),
)

_STEP_BY_ID: Dict[str, WizardStepDef] = {s.step_id: s for s in WIZARD_STEPS}


def _assert_steps_match_task_order() -> None:
    titles = tuple(s.title for s in WIZARD_STEPS)
    if titles != TASK_ORDERED_STEP_TITLES:
        raise AssertionError(
            "WIZARD_STEPS drifted from TASK_ORDERED_STEP_TITLES: "
            f"{titles!r} != {TASK_ORDERED_STEP_TITLES!r}"
        )
    if len(_STEP_BY_ID) != len(WIZARD_STEPS):
        raise AssertionError("WIZARD_STEPS contains a duplicate step_id")


_assert_steps_match_task_order()


# ===========================================================================
# Owner -> domain routing (reversed question_queue.DOMAIN_OWNER_ROUTING)
# ===========================================================================

_OWNER_TO_DOMAIN: Dict[str, str] = {
    owner: domain for domain, owner in question_queue.DOMAIN_OWNER_ROUTING.items()
}


# ===========================================================================
# Paths
# ===========================================================================

WIZARD_DIR_NAME = "gui_vip_coverage_wizard"
SESSION_FILENAME = "session.json"
INPUTS_FILENAME = "wizard_inputs.json"
AUTH_SESSION_FILENAME = "gui_vip_coverage_wizard_session.json"


def _wizard_dir(root: Path) -> Path:
    return Path(root) / ".dv-harness" / WIZARD_DIR_NAME


def _session_path(root: Path) -> Path:
    return _wizard_dir(root) / SESSION_FILENAME


def _inputs_path(root: Path) -> Path:
    return _wizard_dir(root) / INPUTS_FILENAME


def _auth_session_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / AUTH_SESSION_FILENAME


def _atomic_write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
            fh.write("\n")
        storage._atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ===========================================================================
# wizard_inputs.json -- honestly-optional named kwargs
# ===========================================================================

def _load_wizard_inputs(root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """Returns (doc, note). `doc` is `{}` and `note` names the real defect
    for a missing/malformed file -- never raises, never silently guesses."""
    p = _inputs_path(root)
    if not p.exists():
        return {}, None
    try:
        raw = p.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"wizard_inputs.json unreadable/malformed: {exc}"
    if not isinstance(doc, dict):
        return {}, "wizard_inputs.json must be a JSON object"
    return doc, None


def _load_env_manifest_for(root: Path, inputs: Dict[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    doc = inputs.get("env_manifest")
    if isinstance(doc, dict):
        return doc, None
    path = inputs.get("env_manifest_path")
    if path:
        try:
            return env_manifest.load_env_manifest(path), None
        except Exception as exc:  # noqa: BLE001 - honest surface, never a crash
            return None, f"env_manifest_path unreadable/invalid: {exc}"
    default = env_manifest.default_manifest_path(root)
    if default is not None:
        try:
            return env_manifest.load_env_manifest(default), None
        except Exception as exc:  # noqa: BLE001
            return None, f"default env.manifest.json unreadable/invalid: {exc}"
    return None, "no env.manifest.json supplied or found on disk"


def _load_dut_boundary_for(inputs: Dict[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    if isinstance(inputs.get("dut_boundary"), dict):
        return inputs["dut_boundary"], None
    path = inputs.get("phy_boundary_path")
    if path:
        try:
            return phy_boundary.load_phy_boundary(path), None
        except Exception as exc:  # noqa: BLE001
            return None, f"phy_boundary_path unreadable/invalid: {exc}"
    return None, None


# ===========================================================================
# Two-pass grounded intake-state builder (mirrors gui_intake_wizard.py's own
# build_grounded_intake_state() pattern, independently re-derived here since
# that function is private to that module)
# ===========================================================================

def _context_path_for_field(field_name: str) -> str:
    return f"gui_vip_coverage_wizard/{field_name}"


def _question_text_for_field(field_name: str) -> str:
    return f"Please confirm the real value for intake field '{field_name}'."


def build_grounded_intake_state(root: Path) -> Tuple[
        intake_state.IntakeState, Dict[str, str], "question_queue.QuestionQueueStore", Optional[str]]:
    """Two-pass grounded `IntakeState`: first pass computes the raw field
    set to derive each field's real `question_key`; second pass re-runs
    `build_intake_state()` with a real `QuestionQueueStore` + those keys so
    any human answer already on file flows through `intake_state.py`'s own
    `_apply_decision_overlay()`. Returns (state, field_question_keys, store,
    note)."""
    inputs, inputs_note = _load_wizard_inputs(root)
    manifest, manifest_note = _load_env_manifest_for(root, inputs)
    dut_boundary, boundary_note = _load_dut_boundary_for(inputs)
    bind_entries = inputs.get("bind_entries") if isinstance(inputs.get("bind_entries"), list) else None
    active_driver_conflicts = (inputs.get("active_driver_conflicts")
                                if isinstance(inputs.get("active_driver_conflicts"), list) else None)

    raw_state = intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries, dut_boundary=dut_boundary,
        active_driver_conflicts=active_driver_conflicts,
    )
    field_question_keys: Dict[str, str] = {}
    for record in raw_state.records:
        domain = _OWNER_TO_DOMAIN.get(record.owner, "env")
        key = question_queue.make_question_key(
            domain, _question_text_for_field(record.field), _context_path_for_field(record.field),
        )
        field_question_keys[record.field] = key

    store = question_queue.QuestionQueueStore(root)
    final_state = intake_state.build_intake_state(
        env_manifest=manifest, question_store=store, field_question_keys=field_question_keys,
        bind_entries=bind_entries, dut_boundary=dut_boundary,
        active_driver_conflicts=active_driver_conflicts,
    )
    note = "; ".join(n for n in (inputs_note, manifest_note, boundary_note) if n) or None
    return final_state, field_question_keys, store, note


# ===========================================================================
# Session
# ===========================================================================

@dataclass
class WizardSession:
    current_step_index: int = 0

    def clamp(self) -> None:
        self.current_step_index = max(0, min(self.current_step_index, len(WIZARD_STEPS) - 1))

    def to_dict(self) -> dict:
        return {"current_step_index": self.current_step_index}

    @classmethod
    def from_dict(cls, doc: dict) -> "WizardSession":
        s = cls(current_step_index=int(doc.get("current_step_index", 0)))
        s.clamp()
        return s


def load_session(root: Path) -> WizardSession:
    p = _session_path(root)
    if not p.exists():
        return WizardSession()
    try:
        return WizardSession.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return WizardSession()


def save_session(root: Path, session: WizardSession) -> None:
    session.clamp()
    _atomic_write_json(_session_path(root), session.to_dict())


# ===========================================================================
# Per-step grounded view builders
# ===========================================================================

def _record_to_dict(state: intake_state.IntakeState, field_name: str) -> Optional[dict]:
    rec = state.get(field_name)
    return rec.to_dict() if rec is not None else None


def build_step_view(root: Path, step: WizardStepDef) -> dict:
    """Dispatches per KIND onto a real, already-computed producer. Never
    fabricates a status field a real producer does not expose."""
    if step.kind == KIND_FIELDS:
        state, _fqk, _store, note = build_grounded_intake_state(root)
        view: Dict[str, Any] = {"grounded": True, "note": note}
        if step.fields:
            view["fields"] = {f: _record_to_dict(state, f) for f in step.fields}
        if step.categories:
            view["categories"] = {c: {
                "status": state.category_status(c),
                "fields": [r.to_dict() for r in state.fields_in_category(c)],
            } for c in step.categories}
        return view

    if step.kind == KIND_BIND:
        state, _fqk, _store, note = build_grounded_intake_state(root)
        categories = {c: {
            "status": state.category_status(c),
            "fields": [r.to_dict() for r in state.fields_in_category(c)],
        } for c in step.categories}
        inputs, _ = _load_wizard_inputs(root)
        candidates = inputs.get("architecture_choice_candidates")
        ranking = None
        ranking_error = None
        if candidates and architecture_choice_ranking is not None:
            try:
                report = architecture_choice_ranking.rank_bind_location_candidates(candidates)
                ranking = report.to_dict()
            except Exception as exc:  # noqa: BLE001 - honest surface
                ranking_error = str(exc)
        return {
            "grounded": True, "note": note, "categories": categories,
            "architecture_choice_ranking": ranking,
            "architecture_choice_ranking_error": ranking_error,
            "multi_choice_available": ranking is not None
            and len(ranking.get("ranked", [])) >= 2,
        }

    if step.kind == KIND_COMPOSITE_READOUT:
        inputs, note = _load_wizard_inputs(root)
        try:
            report = vip_learning_gate.run_pre_generation_checkpoint(
                vip_sources=inputs.get("vip_sources"),
                vip_index=inputs.get("vip_index"),
                vip_index_path=inputs.get("vip_index_path"),
                vip_relative_to=inputs.get("vip_relative_to"),
                phy_boundary_doc=inputs.get("phy_boundary_doc") or inputs.get("dut_boundary"),
                phy_boundary_path=inputs.get("phy_boundary_path"),
                bind_entries=inputs.get("bind_entries"),
                bind_entries_path=inputs.get("bind_entries_path"),
                bind_require_tier=bool(inputs.get("bind_require_tier", False)),
                env_manifest_doc=inputs.get("env_manifest"),
                env_manifest_path=inputs.get("env_manifest_path"),
            )
            return {"grounded": True, "note": note, "report": report.to_dict()}
        except Exception as exc:  # noqa: BLE001 - honest surface
            return {"grounded": False, "note": note, "error": str(exc)}

    if step.kind == KIND_READINESS:
        state, _fqk, _store, note = build_grounded_intake_state(root)
        readiness = intake_state.evaluate_uvm_generation_ready(state)
        return {
            "grounded": True, "note": note, "readiness": readiness.to_dict(),
            "disclosure": (
                "An active_driver_conflict, when it is the sole blocker, requires human "
                "arbitration -- it is not a fact this wizard can resolve by asking a "
                "2-3-option question through question_queue."
            ),
        }

    if step.kind == KIND_GOLDEN_FLOW_ROW:
        try:
            matrix = golden_flow_readiness.derive_golden_flow_readiness(root)
            rows = [r for r in matrix.get("rows", []) if r.get("row_id") == step.row_id]
            row = rows[0] if rows else None
            return {"grounded": row is not None, "row": row,
                    "note": None if row is not None else f"row_id {step.row_id!r} not found"}
        except Exception as exc:  # noqa: BLE001
            return {"grounded": False, "row": None, "note": str(exc)}

    if step.kind == KIND_COVERAGE_HOLES:
        return _build_coverage_holes_view(root)

    if step.kind == KIND_CLOSURE_RANKING:
        return _build_closure_ranking_view(root)

    if step.kind == KIND_COVERAGE_SIGNOFF:
        inputs, note = _load_wizard_inputs(root)
        try:
            report = functional_coverage_signoff.analyze_functional_coverage_signoff(
                root, cfg=inputs.get("functional_coverage_signoff_cfg"))
            return {"grounded": True, "note": note, "report": report}
        except Exception as exc:  # noqa: BLE001
            return {"grounded": False, "note": note, "error": str(exc)}

    if step.kind == KIND_MATURITY_REVIEW:
        levels: Dict[str, Any] = {}
        inputs, _ = _load_wizard_inputs(root)
        gate_inputs = None
        try:
            gate_inputs = subsystem_maturity_gate.GateInputs(
                vip_api_cards_path=inputs.get("vip_api_cards_path"),
                vip_sources=inputs.get("vip_sources"),
                vip_index_path=inputs.get("vip_index_path"),
                bind_entries=inputs.get("bind_entries"),
                bind_topology_path=inputs.get("bind_topology_path"),
                evidence_db_path=inputs.get("evidence_db_path"),
                smoke_proof_report=inputs.get("smoke_proof_report"),
            )
        except Exception:  # noqa: BLE001
            gate_inputs = None
        for level in subsystem_maturity_gate.MATURITY_LEVELS:
            try:
                levels[level] = subsystem_maturity_gate.derive_maturity_gate(level, root, gate_inputs)
            except Exception as exc:  # noqa: BLE001
                levels[level] = {"level": level, "verdict": "ERROR", "error": str(exc)}
        return {"grounded": True, "note": None, "levels": levels}

    raise AssertionError(f"unhandled step kind: {step.kind}")  # pragma: no cover


def _coverage_summary_doc(root: Path, inputs: Dict[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    doc = inputs.get("coverage_summary")
    if isinstance(doc, dict):
        return doc, None
    path = inputs.get("coverage_summary_path")
    if not path:
        return None, "no coverage_summary or coverage_summary_path supplied in wizard_inputs.json"
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"coverage_summary_path unreadable/malformed: {exc}"


def _build_coverage_holes_view(root: Path) -> dict:
    inputs, inputs_note = _load_wizard_inputs(root)
    raw, note = _coverage_summary_doc(root, inputs)
    if raw is None:
        return {"grounded": False, "note": note or inputs_note, "holes": [], "escalations": []}
    try:
        parsed = coverage_analysis.parse_coverage_summary(raw)
    except coverage_analysis.CoverageAnalysisError as exc:
        return {"grounded": False, "note": f"malformed coverage summary: {exc}", "holes": [], "escalations": []}
    holes = coverage_analysis.identify_holes(parsed)
    translated = [{"coverage_id": h.get("name"), **h} for h in holes]
    _state, _fqk, store, _n = build_grounded_intake_state(root)
    escalations: List[dict] = []
    try:
        escalations = coverage_analysis.escalate_unreachable_holes(root, translated, store=store)
    except Exception as exc:  # noqa: BLE001 - honest surface, coverage-hole escalation is best-effort
        escalations = [{"error": str(exc)}]
    return {
        "grounded": True, "note": None,
        "coverage_summary_loaded": True,
        "holes": translated,
        "escalations": escalations,
    }


def _build_closure_ranking_view(root: Path) -> dict:
    inputs, note = _load_wizard_inputs(root)
    candidates = inputs.get("closure_action_candidates")
    if not candidates:
        holes_view = _build_coverage_holes_view(root)
        holes_remaining = len(holes_view.get("holes", [])) if holes_view.get("grounded") else None
        return {
            "grounded": False, "note": note,
            "ranking": None, "ranking_ever_run": False,
            "holes_remaining": holes_remaining,
        }
    try:
        ranking = coverage_closure_action_utility.rank_coverage_closure_actions(candidates)
        rd = ranking.to_dict()
    except coverage_closure_action_utility.CoverageClosureActionUtilityError as exc:
        return {"grounded": False, "note": f"invalid closure candidates: {exc}",
                "ranking": None, "ranking_ever_run": False, "holes_remaining": None}
    ranked = rd.get("ranked", [])
    multi_choice_available = False
    if len(ranked) >= 2:
        top_score = ranked[0].get("utility_score")
        overlapping = [r for r in ranked if r.get("utility_score") == top_score]
        multi_choice_available = len(overlapping) >= 2
    return {
        "grounded": True, "note": note, "ranking": rd, "ranking_ever_run": True,
        "multi_choice_available": multi_choice_available,
    }


# ===========================================================================
# get_state_view() -- GET /api/state backing function
# ===========================================================================

def get_state_view(root: Path) -> dict:
    root = Path(root)
    session = load_session(root)
    step = WIZARD_STEPS[session.current_step_index]
    steps_summary = [{"step_id": s.step_id, "title": s.title, "kind": s.kind} for s in WIZARD_STEPS]

    view = build_step_view(root, step)

    signoff_view = build_step_view(root, _STEP_BY_ID["functional_coverage_signoff"])
    overall_ready: Optional[bool] = None
    signoff_report = signoff_view.get("report") if isinstance(signoff_view, dict) else None
    if isinstance(signoff_report, dict) and signoff_report.get(
            "status") != functional_coverage_signoff.STATUS_NOT_AVAILABLE:
        overall_ready = bool(signoff_report.get("functional_coverage_signoff_ready"))

    return {
        "schema_version": 1,
        "step": {"step_id": step.step_id, "title": step.title, "kind": step.kind,
                  "index": session.current_step_index, "total": len(WIZARD_STEPS)},
        "steps": steps_summary,
        "view": view,
        "overall_ready": overall_ready,
    }


# ===========================================================================
# answer() -- POST /answer backing function
# ===========================================================================

def answer_field(root: Path, field_name: str, answer: str, *,
                  basis: Optional[str] = None, decided_by: Optional[str] = None) -> dict:
    root = Path(root)
    field_name = (field_name or "").strip()
    answer = (answer or "").strip()
    if not field_name:
        raise GuiVipCoverageWizardError("EMPTY_FIELD_NAME", "field is required")
    if not answer:
        raise GuiVipCoverageWizardError("EMPTY_ANSWER", "answer is required")

    state, field_question_keys, store, _note = build_grounded_intake_state(root)
    if intake_state.already_resolved(state, field_name):
        raise GuiVipCoverageWizardError(
            "ALREADY_RESOLVED", f"field {field_name!r} is already resolved; no question needed")
    record = state.get(field_name)
    if record is None:
        raise GuiVipCoverageWizardError("FIELD_NOT_FOUND", f"no such intake field: {field_name!r}")
    domain = _OWNER_TO_DOMAIN.get(record.owner)
    if domain is None:
        raise GuiVipCoverageWizardError(
            "FIELD_NOT_ROUTABLE", f"field {field_name!r} has no domain-routable owner ({record.owner!r})")

    question_key = field_question_keys.get(field_name) or question_queue.make_question_key(
        domain, _question_text_for_field(field_name), _context_path_for_field(field_name))
    filed = store.add_question(
        domain=domain, question=_question_text_for_field(field_name),
        context_path=_context_path_for_field(field_name),
        options=[answer, "UNCONFIRMED_NO_HUMAN_ANSWER_YET"],
        recommendation=answer,
        assumption_if_unanswered=(
            f"Field {field_name!r} remains unresolved and blocks UVM generation readiness "
            "until a human answers this question."),
        question_key=question_key,
    )
    resolved = store.answer_question(
        filed["id"], answer=answer,
        basis=basis or "human confirmed via GUI VIP Coverage Wizard",
        decided_by=decided_by or "gui_vip_coverage_wizard_user",
    )
    return {"field": field_name, "question": resolved}


def answer_question_directly(root: Path, question_id: str, answer: str, *,
                              basis: Optional[str] = None, decided_by: Optional[str] = None) -> dict:
    root = Path(root)
    question_id = (question_id or "").strip()
    answer = (answer or "").strip()
    if not question_id:
        raise GuiVipCoverageWizardError("EMPTY_QUESTION_ID", "question_id is required")
    if not answer:
        raise GuiVipCoverageWizardError("EMPTY_ANSWER", "answer is required")
    store = question_queue.QuestionQueueStore(root)
    try:
        resolved = store.answer_question(
            question_id, answer=answer,
            basis=basis or "human confirmed via GUI VIP Coverage Wizard",
            decided_by=decided_by or "gui_vip_coverage_wizard_user",
        )
    except KeyError as exc:
        raise GuiVipCoverageWizardError("QUESTION_NOT_FOUND", str(exc)) from exc
    return {"question": resolved}


# ===========================================================================
# advance_step() -- POST /advance backing function, with genuine per-step
# precondition refusal (distinct from gui_intake_wizard.advance_step()'s
# pure clamped navigation)
# ===========================================================================

def advance_precondition(root: Path, step: WizardStepDef) -> Tuple[bool, str]:
    """Returns (ok, reason). `reason` is empty when `ok` is True, and names
    the real unmet precondition otherwise."""
    view = build_step_view(root, step)

    if step.kind == KIND_FIELDS:
        for f in step.fields:
            rec = view.get("fields", {}).get(f)
            status = rec.get("status") if rec else intake_state.IntakeFieldStatus.MISSING.value
            if status not in intake_state.NON_BLOCKING_STATUSES:
                return False, f"field {f!r} is {status!r}, not yet resolved"
        for c in step.categories:
            status = view.get("categories", {}).get(c, {}).get("status")
            if status not in intake_state.NON_BLOCKING_STATUSES:
                return False, f"category {c!r} is {status!r}, not yet resolved"
        return True, ""

    if step.kind == KIND_BIND:
        for c in step.categories:
            status = view.get("categories", {}).get(c, {}).get("status")
            if status not in intake_state.NON_BLOCKING_STATUSES:
                return False, f"category {c!r} is {status!r}, not yet resolved"
        return True, ""

    if step.kind == KIND_COMPOSITE_READOUT:
        report = view.get("report")
        if report is None:
            return False, view.get("error") or "VIP Learning Gate report could not be computed"
        verdict = report.get("verdict")
        if verdict == vip_learning_gate.BLOCKED:
            blocking = report.get("blocking_checks", [])
            return False, f"VIP Learning Gate verdict is BLOCKED (blocking checks: {blocking!r})"
        return True, ""

    if step.kind == KIND_READINESS:
        readiness = view.get("readiness", {})
        if not readiness.get("ready"):
            return False, f"UVM generation is not ready (blocking: {list(readiness.get('blocking', {}))!r})"
        return True, ""

    if step.kind == KIND_GOLDEN_FLOW_ROW:
        row = view.get("row")
        if row is None:
            return False, view.get("note") or f"row {step.row_id!r} not found"
        if row.get("status") != golden_flow_readiness.READY:
            return False, f"row {step.row_id!r} status is {row.get('status')!r}, not READY"
        return True, ""

    if step.kind == KIND_COVERAGE_HOLES:
        if not view.get("coverage_summary_loaded"):
            return False, view.get("note") or "no coverage summary was successfully loaded"
        return True, ""

    if step.kind == KIND_CLOSURE_RANKING:
        holes_remaining = view.get("holes_remaining")
        if holes_remaining == 0:
            return True, ""
        if view.get("ranking_ever_run"):
            return True, ""
        return False, (view.get("note")
                        or "no coverage-closure ranking has been run yet and real holes remain")

    if step.kind == KIND_COVERAGE_SIGNOFF:
        report = view.get("report")
        if not isinstance(report, dict):
            return False, view.get("error") or "functional coverage signoff report unavailable"
        if report.get("status") == functional_coverage_signoff.STATUS_NOT_AVAILABLE:
            return False, f"functional coverage signoff status is {report.get('status')!r}"
        return True, ""

    if step.kind == KIND_MATURITY_REVIEW:
        return True, ""  # terminal step: no precondition

    raise AssertionError(f"unhandled step kind: {step.kind}")  # pragma: no cover


def _forward_gate_check(root: Path, from_index: int, to_index: int) -> Tuple[bool, str]:
    for i in range(from_index, to_index):
        step = WIZARD_STEPS[i]
        ok, reason = advance_precondition(root, step)
        if not ok:
            return False, f"cannot advance past step {i} ({step.step_id!r}): {reason}"
    return True, ""


def advance_step(root: Path, *, direction: Optional[str] = None,
                  step_id: Optional[str] = None) -> dict:
    root = Path(root)
    session = load_session(root)
    current = session.current_step_index

    if step_id is not None:
        if step_id not in _STEP_BY_ID:
            raise GuiVipCoverageWizardError("UNKNOWN_STEP_ID", f"no such step_id: {step_id!r}")
        target = next(i for i, s in enumerate(WIZARD_STEPS) if s.step_id == step_id)
    elif direction == "next":
        target = min(current + 1, len(WIZARD_STEPS) - 1)
    elif direction == "back":
        target = max(current - 1, 0)
    else:
        raise GuiVipCoverageWizardError(
            "MISSING_DIRECTION_OR_STEP_ID", "supply direction='next'/'back' or step_id=")

    if target > current:
        ok, reason = _forward_gate_check(root, current, target)
        if not ok:
            raise GuiVipCoverageWizardError("PRECONDITION_NOT_MET", reason)

    session.current_step_index = target
    session.clamp()
    save_session(root, session)
    return get_state_view(root)


# ===========================================================================
# Auth -- own session token, per gui_intake_control_plane.py's precedent
# ===========================================================================

def issue_session_token(project_root: Path, *, port: Optional[int] = None,
                         host: str = "127.0.0.1") -> Dict[str, Any]:
    token = secrets.token_urlsafe(32)
    record = {
        "token": token, "host": host, "port": port,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _auth_session_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        storage._atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return record


def read_session_token(project_root: Path) -> Optional[str]:
    path = _auth_session_path(project_root)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tok = doc.get("token")
    return tok if isinstance(tok, str) and tok else None


def _authorized(expected_token: Optional[str], headers: Any, path: str) -> bool:
    if not expected_token:
        return False
    presented = dashboard_auth.presented_token(headers, path)
    return bool(presented) and secrets.compare_digest(presented, expected_token)


# ===========================================================================
# HTML rendering
# ===========================================================================

_CSS = """
body { font-family: system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #1b1f24; }
header { background: #14213d; color: white; padding: 12px 20px; }
header h1 { margin: 0; font-size: 18px; }
.crumbs { padding: 10px 20px; font-size: 13px; color: #555; }
.crumbs span.current { font-weight: bold; color: #14213d; }
main { padding: 20px; max-width: 1000px; margin: 0 auto; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; }
th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; font-size: 13px; }
th { background: #eef1f6; }
.nav { margin-top: 20px; }
.nav button { padding: 8px 16px; margin-right: 8px; }
.note { color: #a94442; font-style: italic; }
.ok { color: #2e7d32; }
.overall { font-weight: bold; padding: 10px; margin-bottom: 10px; border-radius: 4px; }
.overall.ready { background: #e6f4ea; color: #2e7d32; }
.overall.notready { background: #fdecea; color: #a94442; }
.overall.unknown { background: #fff8e1; color: #8a6d00; }
form.answer { margin-top: 16px; padding: 12px; background: #fff; border: 1px solid #ddd; }
form.answer input[type=text] { width: 60%; padding: 6px; }
"""


def _esc(s: Any) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_dict_table(d: Dict[str, Any]) -> str:
    if not d:
        return "<p><em>(no data)</em></p>"
    rows = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, indent=2, default=str)
            rows.append(f"<tr><th>{_esc(k)}</th><td><pre>{_esc(v)}</pre></td></tr>")
        else:
            rows.append(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def _answer_form_html(step: WizardStepDef) -> str:
    if step.kind not in (KIND_FIELDS, KIND_BIND):
        return ""
    return (
        '<form class="answer" method="post" action="/answer">'
        '<label>Field name: <input type="text" name="field"></label><br><br>'
        '<label>Answer: <input type="text" name="answer"></label><br><br>'
        '<label>Basis (optional): <input type="text" name="basis"></label><br><br>'
        '<button type="submit">Confirm</button>'
        '</form>'
    )


def render_wizard_html(doc: dict) -> str:
    step = doc["step"]
    crumbs = " &raquo; ".join(
        f'<span class="current">{_esc(s["title"])}</span>' if s["step_id"] == step["step_id"]
        else _esc(s["title"])
        for s in doc["steps"]
    )
    overall = doc.get("overall_ready")
    overall_cls = "unknown" if overall is None else ("ready" if overall else "notready")
    overall_text = ("Step 10 has not yet resolved a signoff verdict" if overall is None
                     else ("READY" if overall else "NOT READY"))
    view = doc["view"]
    body_parts = [f'<div class="overall {overall_cls}">Functional Coverage Signoff Ready: {_esc(overall_text)}</div>']
    if view.get("note"):
        body_parts.append(f'<p class="note">Note: {_esc(view["note"])}</p>')
    body_parts.append(_render_dict_table({k: v for k, v in view.items() if k != "note"}))
    body_parts.append(_answer_form_html(_STEP_BY_ID[step["step_id"]]))
    body_parts.append(
        '<div class="nav">'
        '<form style="display:inline" method="post" action="/advance">'
        '<input type="hidden" name="direction" value="back">'
        '<button type="submit">&laquo; Prev</button></form> '
        '<form style="display:inline" method="post" action="/advance">'
        '<input type="hidden" name="direction" value="next">'
        '<button type="submit">Next &raquo;</button></form>'
        '</div>'
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>GUI VIP Coverage Wizard</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>GUI VIP Coverage Wizard</h1></header>"
        f"<div class='crumbs'>{crumbs}</div>"
        f"<main><h2>{_esc(step['title'])} (step {step['index'] + 1} of {step['total']})</h2>"
        f"{''.join(body_parts)}</main></body></html>"
    )


def render_error_html(doc: dict, exc: Exception) -> str:
    reason = getattr(exc, "reason", "ERROR")
    detail = getattr(exc, "detail", str(exc))
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>GUI VIP Coverage Wizard - Error</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>GUI VIP Coverage Wizard</h1></header>"
        f"<main><h2 class='note'>{_esc(reason)}</h2><p>{_esc(detail)}</p>"
        f"<p><a href='/'>&laquo; back</a></p></main></body></html>"
    )


# ===========================================================================
# Server
# ===========================================================================

def build_server(project_root: Path, host: str = "127.0.0.1", port: int = 0,
                  *, require_auth: bool = True) -> Tuple[ThreadingHTTPServer, Optional[str]]:
    root = Path(project_root).resolve()
    token_holder: Dict[str, Optional[str]] = {"token": None}

    class Handler(BaseHTTPRequestHandler):
        server_version = "GuiVipCoverageWizard/1.0"

        def log_message(self, fmt, *args):  # noqa: N802 - silent, matches gui_intake_wizard.py
            pass

        def _send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, status: int, doc: Any) -> None:
            self._send_bytes(status, "application/json", json.dumps(doc, default=str).encode("utf-8"))

        def _send_html(self, status: int, html: str) -> None:
            self._send_bytes(status, "text/html; charset=utf-8", html.encode("utf-8"))

        def _redirect_home(self) -> None:
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def _authorized(self) -> bool:
            if not require_auth:
                return True
            return _authorized(token_holder["token"], self.headers, self.path)

        def _read_form(self) -> Dict[str, str]:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype == "application/json":
                try:
                    doc = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    return {}
                return {k: str(v) for k, v in doc.items()} if isinstance(doc, dict) else {}
            qs = parse_qs(raw.decode("utf-8"))
            return {k: v[0] for k, v in qs.items() if v}

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                try:
                    doc = get_state_view(root)
                except Exception as exc:  # noqa: BLE001
                    self._send_html(200, render_error_html({}, exc))
                    return
                self._send_html(200, render_wizard_html(doc))
                return
            if path in ("/api/state",):
                try:
                    self._send_json(200, get_state_view(root))
                except Exception as exc:  # noqa: BLE001
                    self._send_json(500, {"reason": "STATE_ERROR", "detail": str(exc)})
                return
            self._send_json(404, {"reason": "NOT_FOUND", "detail": path})

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            is_json_client = path.startswith("/api/")
            base_path = path[len("/api"):] if is_json_client else path
            if base_path not in ("/answer", "/advance"):
                self._send_json(404, {"reason": "NOT_FOUND", "detail": path})
                return
            if not self._authorized():
                if is_json_client:
                    self._send_json(401, {"reason": "UNAUTHORIZED", "detail": "missing/invalid session token"})
                else:
                    self._send_html(401, render_error_html({}, GuiVipCoverageWizardError(
                        "UNAUTHORIZED", "missing/invalid session token")))
                return
            form = self._read_form()
            try:
                if base_path == "/answer":
                    if form.get("question_id"):
                        result = answer_question_directly(
                            root, form.get("question_id", ""), form.get("answer", ""),
                            basis=form.get("basis") or None, decided_by=form.get("decided_by") or None)
                    else:
                        result = answer_field(
                            root, form.get("field", ""), form.get("answer", ""),
                            basis=form.get("basis") or None, decided_by=form.get("decided_by") or None)
                    if is_json_client:
                        self._send_json(200, result)
                    else:
                        self._redirect_home()
                    return
                if base_path == "/advance":
                    result = advance_step(
                        root, direction=form.get("direction") or None,
                        step_id=form.get("step_id") or None)
                    if is_json_client:
                        self._send_json(200, result)
                    else:
                        self._redirect_home()
                    return
            except GuiVipCoverageWizardError as exc:
                if is_json_client:
                    self._send_json(400, {"reason": exc.reason, "detail": exc.detail})
                else:
                    self._send_html(400, render_error_html({}, exc))
                return
            except Exception as exc:  # noqa: BLE001
                if is_json_client:
                    self._send_json(500, {"reason": "SERVER_ERROR", "detail": str(exc)})
                else:
                    self._send_html(500, render_error_html({}, exc))
                return

    server = ThreadingHTTPServer((host, port), Handler)
    token = None
    if require_auth:
        record = issue_session_token(root, port=server.server_address[1], host=host)
        token_holder["token"] = record["token"]
        token = record["token"]
    return server, token


def run_server(project_root: Path, host: str = "127.0.0.1", port: int = 0,
                *, require_auth: bool = True) -> None:
    server, token = build_server(project_root, host=host, port=port, require_auth=require_auth)
    addr, real_port = server.server_address
    print(f"gui_vip_coverage_wizard listening on http://{addr}:{real_port}")
    if token:
        print(f"session token: {token}")
    try:
        server.serve_forever()
    finally:
        server.shutdown()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.gui_vip_coverage_wizard")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-auth", action="store_true", help="disable session-token gating (local debugging only)")
    args = parser.parse_args(argv)
    run_server(Path(args.project_root), host=args.host, port=args.port, require_auth=not args.no_auth)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
