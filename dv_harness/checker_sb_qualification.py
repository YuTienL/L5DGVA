"""dv_harness/checker_sb_qualification.py -- Checker / Scoreboard Qualification (2026-09-06).

ULTIMATE_PRODUCTION_COMPLETE.md section 158 asks for a qualification record/gate over a
checker or scoreboard's OWN trustworthiness track record: has it ever caught a real injected
defect, has it ever produced a false PASS. Re-verified by direct search before writing a
line of this module (`grep -rn "false_pass\\|checker_qualification\\|scoreboard_qualification"
-i dv_harness/*.py`): nothing in this repo answers this question today.

DISTINCT FROM `verification_architecture.py`'s `CheckerIR`/`ScoreboardIR`, on purpose --
those two IRs record where a checker/scoreboard is PLACED (bind target, mount side relative to
a bridge, comparability of its endpoints) and how CONFIDENT that placement inference is. They
carry no notion of the component's own historical TRACK RECORD: whether it has ever actually
demonstrated it can catch a defect, or whether it has ever been proven to pass when it should
not have. This module never imports `verification_architecture.py` and never derives placement
of any kind; a component here is identified purely by a caller-declared `component_id` (which
MAY, but need not, match a `CheckerIR.interface_row_id` or `ScoreboardIR.scoreboard_id` a
caller already has -- this module does not care).

DISTINCT FROM `golden_scenario.py`'s per-TEST capsule, also on purpose. A golden capsule
records that one (test, seed, config) combination was verified PASS against a commit --
`validate_capsule()` REFUSES any capsule whose `expected_result` is not itself a PASS verdict
(`PASS_VERDICTS`), so that store structurally cannot hold the FAIL-verdict evidence a real
defect-detection trial needs. This module's evidence is the opposite shape: a trial where a
known defect was deliberately present, and the checker/scoreboard's own recorded verdict for
that trial is what decides whether it DETECTED the defect (a real FAIL) or produced a FALSE
PASS (a real PASS despite the defect) -- `golden_scenario.py`'s schema cannot express either
outcome and this module does not extend or import it.

THE HONEST BOUNDARY THIS MODULE RESPECTS (read from `subsystem_maturity_gate.py`'s own
`false_pass_count_zero` condition before writing anything here, per this task's own
instruction). That condition is, and remains, `NOT_MEASURABLE` in this repository: its own
search note records that neither `golden_scenario.py` nor `requirement_contract.py` (the two
modules its own spec named as the likeliest home for an existing false-PASS signal), nor any
other real producer in this codebase, EVER persisted a false-PASS COUNT over a qualification
set before this module existed. This module is that missing producer -- but building it does
NOT retroactively make `subsystem_maturity_gate.py`'s condition measurable: that module is not
edited here (a deliberate, disclosed choice -- see "Disclosed residual" below), and its
`false_pass_count_zero` condition still, honestly, reports `NOT_MEASURABLE` until a future
change wires the two together. What changes is that a checker/scoreboard's own qualification
history now has somewhere real to be recorded and queried, for the first time.

WHAT THIS MODULE CANNOT DO, STATED UP FRONT. It cannot inject a fault into a DUT/TB itself --
this harness owns no RTL, no live simulator and no formal tool (the same boundary
`mutation_testing.py`'s own docstring states for its own, unrelated, Python-test-suite-scoped
mutation engine: DUT/RTL-level fault injection "needs a real RTL target and a simulator this
repository does not contain"). It cannot verify that a caller's claimed injected defect was
real, or that a cited verdict is accurate -- exactly the same limit `user_answer_validator.py`
and `vip_api_card.py` already draw for a citation's TRUTH versus its mere PRESENCE. What it CAN
do, and does, is refuse to accept a qualification claim with no real citation at all, and
derive an honest, worst-wins qualification verdict from whatever trials a caller supplies.

THE ONE HARD RULE THIS MODULE ENFORCES (worst-wins, never averaged, per this project's
Worst-Wins Composite Gates convention): a SINGLE confirmed false PASS disqualifies a
checker/scoreboard's whole qualification record, no matter how many real defect-detection
trials it also passed. A checker that mostly works and once silently missed a real defect is
not "mostly trustworthy" -- it is untrustworthy, because the entire value of a checker is that
a human can stop looking once it says PASS.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import models

# --- vocabulary --------------------------------------------------------------

#: The two kinds of verification component this module qualifies. A generated UVM environment
#: may carry many of each; this module tracks ONE named component's own history at a time.
COMPONENT_KINDS: Tuple[str, ...] = ("CHECKER", "SCOREBOARD")

#: Verdict-string interpretation, deliberately the SAME two small sets `golden_scenario.py`
#: already uses for the identical real-world spelling variance (`vip_distill.py`'s epilogue
#: writes "PASSED"/"FAILED"; `lsf_client.JobState.sim_status` writes "PASS"/"FAIL"). Restated
#: here rather than imported, because this module's PASS set means something different from
#: `golden_scenario.PASS_VERDICTS`: there, a PASS is what a capsule REQUIRES; here, a PASS on a
#: trial where a defect was deliberately present is exactly the FALSE-PASS finding this module
#: exists to catch.
PASS_VERDICTS = frozenset({"PASS", "PASSED"})
FAIL_VERDICTS = frozenset({"FAIL", "FAILED"})

#: One real trial's outcome, derived from its own recorded verdict -- never asserted directly
#: by a caller (there is no `outcome=` constructor argument; see `QualificationTrial.outcome`).
OUTCOME_DETECTED = "DETECTED"
OUTCOME_FALSE_PASS = "FALSE_PASS"
OUTCOME_INDETERMINATE = "INDETERMINATE"
TRIAL_OUTCOMES: Tuple[str, ...] = (OUTCOME_DETECTED, OUTCOME_FALSE_PASS, OUTCOME_INDETERMINATE)

#: One component's own qualification verdict, worst-wins over its whole recorded trial history.
STATUS_QUALIFIED = "QUALIFIED"
STATUS_PARTIALLY_QUALIFIED = "PARTIALLY_QUALIFIED"
STATUS_DISQUALIFIED = "DISQUALIFIED_FALSE_PASS_CONFIRMED"
STATUS_NO_TRIALS = "NO_TRIALS_RECORDED"
STATUS_INCONCLUSIVE = "EVIDENCE_INCONCLUSIVE"
QUALIFICATION_STATUSES: Tuple[str, ...] = (
    STATUS_QUALIFIED, STATUS_PARTIALLY_QUALIFIED, STATUS_DISQUALIFIED,
    STATUS_NO_TRIALS, STATUS_INCONCLUSIVE,
)

#: A project-wide gate verdict over several components' own qualification records.
GATE_QUALIFIED = "QUALIFIED"
GATE_NOT_QUALIFIED = "NOT_QUALIFIED"
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (GATE_QUALIFIED, GATE_NOT_QUALIFIED, GATE_INCOMPLETE_EVIDENCE)

#: How many INDEPENDENT confirmed-detection trials a component needs before its qualification
#: reads QUALIFIED rather than merely PARTIALLY_QUALIFIED. Two, for the same reason this
#: project's other "has this really been shown twice, not once" bars are two --
#: `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS`, `capability_evolution.
#: REPEAT_FAILURE_MIN_OCCURRENCES`, `capability_evolution.STABILITY_WINDOW_MIN_RUNS` -- a single
#: successful detection could be luck or an unusually obvious defect; two independent trials is
#: this codebase's own established floor for "not a fluke."
MIN_CONFIRMED_DETECTIONS = 2


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabularies must share no token with `dv_harness.models.Status` --
    the same guard several sibling domain-vocabulary modules in this project already run
    against themselves. A checker/scoreboard being `QUALIFIED` is not a stage reaching
    `Status.PASS`, and conflating the two would let this module's verdict be misread as a
    graph-routing signal."""
    status_values = {s.value for s in models.Status}
    for vocab_name, vocab in (
        ("TRIAL_OUTCOMES", TRIAL_OUTCOMES),
        ("QUALIFICATION_STATUSES", QUALIFICATION_STATUSES),
        ("GATE_VERDICTS", GATE_VERDICTS),
    ):
        collision = status_values & set(vocab)
        if collision:
            raise AssertionError(
                f"{vocab_name} collides with dv_harness.models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


class CheckerSbQualificationError(Exception):
    """Base for every refusal in this module."""


# --- one trial ---------------------------------------------------------------


@dataclass
class QualificationTrial:
    """One real trial: a known defect was deliberately made present (or claimed present) for
    ONE named checker/scoreboard component, and that component's own recorded verdict for the
    trial is what decides whether it caught the defect or produced a false PASS.

    Every field this module needs to CLASSIFY a trial is mandatory and citation-gated --
    the same "an uncited claim is refused outright" discipline `security_policy_ir.AccessRule`
    and `arbitration_policy_ir.ControllingMechanism` already apply to their own domains,
    independently re-applied here. This module cannot verify a citation is TRUE, only that one
    was actually supplied; see the module docstring's stated boundary.

    `component_verdict` is OPTIONAL -- a trial may be filed before its own verdict is known
    (e.g. the defect was injected and the run is still pending), in which case the trial's
    `outcome` is honestly `INDETERMINATE` rather than a guessed one. When `component_verdict`
    IS supplied, `verdict_evidence` (a citation for THAT specific claim -- a real
    `evidence_db.normalized_evidence` `evidence_id`, a sim.log reference, a waveform offset, or
    a named human confirmation) is then equally mandatory: a verdict claim with no citation is
    exactly the unsupported claim this module refuses everywhere else.
    """
    trial_id: str
    component_id: str
    component_kind: str
    defect_id: str
    injection_description: str
    injection_evidence: str
    component_verdict: Optional[str] = None
    verdict_evidence: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("trial_id", "component_id", "defect_id", "injection_description",
                     "injection_evidence"):
            if not str(getattr(self, name) or "").strip():
                raise CheckerSbQualificationError(
                    f"QualificationTrial: {name!r} is required and must be non-empty "
                    f"(trial_id={self.trial_id!r})")
        if self.component_kind not in COMPONENT_KINDS:
            raise CheckerSbQualificationError(
                f"QualificationTrial {self.trial_id!r}: component_kind={self.component_kind!r} "
                f"is not one of {COMPONENT_KINDS}")
        if self.component_verdict is not None and not str(self.verdict_evidence or "").strip():
            raise CheckerSbQualificationError(
                f"QualificationTrial {self.trial_id!r}: a component_verdict "
                f"({self.component_verdict!r}) was declared with no verdict_evidence citation -- "
                f"an uncited verdict claim is refused, per the Evidence Truth Rule")

    @property
    def outcome(self) -> str:
        """Derived, never asserted directly by a caller. A missing or unrecognized verdict is
        honestly `INDETERMINATE` -- it is never guessed toward DETECTED or FALSE_PASS."""
        if self.component_verdict is None:
            return OUTCOME_INDETERMINATE
        verdict = str(self.component_verdict).strip().upper()
        if verdict in FAIL_VERDICTS:
            return OUTCOME_DETECTED
        if verdict in PASS_VERDICTS:
            return OUTCOME_FALSE_PASS
        return OUTCOME_INDETERMINATE

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "component_id": self.component_id,
            "component_kind": self.component_kind,
            "defect_id": self.defect_id,
            "injection_description": self.injection_description,
            "injection_evidence": self.injection_evidence,
            "component_verdict": self.component_verdict,
            "verdict_evidence": self.verdict_evidence,
            "notes": self.notes,
            "outcome": self.outcome,
        }


def trial_from_dict(data: dict) -> QualificationTrial:
    """Build one `QualificationTrial` from a plain dict (the shape a JSON trial file, or a
    caller's own record, already carries). Raises `CheckerSbQualificationError` on anything the
    dataclass constructor itself would reject, plus an unrecognized key."""
    if not isinstance(data, dict):
        raise CheckerSbQualificationError(f"a trial record must be a dict, got {type(data).__name__}")
    known = {"trial_id", "component_id", "component_kind", "defect_id", "injection_description",
             "injection_evidence", "component_verdict", "verdict_evidence", "notes"}
    unknown = set(data.keys()) - known
    if unknown:
        raise CheckerSbQualificationError(f"unrecognized trial field(s): {sorted(unknown)}")
    try:
        return QualificationTrial(
            trial_id=data.get("trial_id"),
            component_id=data.get("component_id"),
            component_kind=data.get("component_kind"),
            defect_id=data.get("defect_id"),
            injection_description=data.get("injection_description"),
            injection_evidence=data.get("injection_evidence"),
            component_verdict=data.get("component_verdict"),
            verdict_evidence=data.get("verdict_evidence"),
            notes=data.get("notes") or "",
        )
    except TypeError as exc:
        raise CheckerSbQualificationError(f"malformed trial record: {exc}") from exc


# --- one component's qualification record ------------------------------------


@dataclass
class ComponentQualificationRecord:
    component_id: str
    component_kind: str
    trial_count: int
    detected_count: int
    false_pass_count: int
    indeterminate_count: int
    confirmed_detections: List[str]
    confirmed_false_passes: List[str]
    indeterminate_trials: List[str]
    status: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "component_kind": self.component_kind,
            "trial_count": self.trial_count,
            "detected_count": self.detected_count,
            "false_pass_count": self.false_pass_count,
            "indeterminate_count": self.indeterminate_count,
            "confirmed_detections": self.confirmed_detections,
            "confirmed_false_passes": self.confirmed_false_passes,
            "indeterminate_trials": self.indeterminate_trials,
            "status": self.status,
            "reason": self.reason,
        }


def evaluate_component_qualification(
    trials: Sequence[QualificationTrial], *,
    min_confirmed_detections: int = MIN_CONFIRMED_DETECTIONS,
) -> ComponentQualificationRecord:
    """Fold one component's whole real trial history into one qualification record.

    Worst-wins, never averaged: a single confirmed false PASS disqualifies the component
    regardless of how many trials it separately detected. Only once zero false passes exist
    does the detection COUNT matter at all, and even then a component with real trials on file
    but zero confirmed detections and zero confirmed false passes (every trial INDETERMINATE)
    is reported `EVIDENCE_INCONCLUSIVE` rather than either extreme -- distinct from
    `NO_TRIALS_RECORDED` (nothing was ever tried at all), because "we tried and could not tell"
    and "we never tried" are different operator problems with different remedies.

    Every trial must name the SAME component -- a caller mixing two components' trials into
    one call is a usage error, refused rather than silently pooled.
    """
    trials = list(trials)
    if not trials:
        raise CheckerSbQualificationError(
            "evaluate_component_qualification: at least one QualificationTrial is required "
            "(pass an empty list's component identity explicitly via "
            "no_trials_recorded() instead)")
    component_id = trials[0].component_id
    component_kind = trials[0].component_kind
    for t in trials:
        if t.component_id != component_id or t.component_kind != component_kind:
            raise CheckerSbQualificationError(
                f"evaluate_component_qualification: trial {t.trial_id!r} names "
                f"({t.component_id!r}, {t.component_kind!r}), which disagrees with this "
                f"batch's own ({component_id!r}, {component_kind!r}) -- trials for more than "
                f"one component must be evaluated separately, never pooled")

    detected = [t.trial_id for t in trials if t.outcome == OUTCOME_DETECTED]
    false_pass = [t.trial_id for t in trials if t.outcome == OUTCOME_FALSE_PASS]
    indeterminate = [t.trial_id for t in trials if t.outcome == OUTCOME_INDETERMINATE]

    if false_pass:
        status = STATUS_DISQUALIFIED
        reason = (
            f"{len(false_pass)} confirmed false-PASS trial(s) on record "
            f"({', '.join(sorted(false_pass))}) -- disqualified regardless of "
            f"{len(detected)} separate confirmed detection(s); one confirmed false PASS "
            f"outranks any number of clean detections")
    elif len(detected) >= min_confirmed_detections:
        status = STATUS_QUALIFIED
        reason = (
            f"{len(detected)} confirmed defect-detection trial(s) on record with zero "
            f"confirmed false passes, meeting the {min_confirmed_detections}-trial floor")
    elif detected:
        status = STATUS_PARTIALLY_QUALIFIED
        reason = (
            f"{len(detected)} confirmed defect-detection trial(s) on record with zero "
            f"confirmed false passes, below the {min_confirmed_detections}-trial floor for "
            f"full qualification")
    elif indeterminate:
        status = STATUS_INCONCLUSIVE
        reason = (
            f"{len(indeterminate)} trial(s) recorded but every one is INDETERMINATE (no "
            f"resolvable component_verdict) -- this component's own catch/false-pass history "
            f"remains unproven either way")
    else:  # pragma: no cover -- every trial is one of the three outcomes above
        status = STATUS_INCONCLUSIVE
        reason = "no trial resolved to a determinable outcome"

    return ComponentQualificationRecord(
        component_id=component_id, component_kind=component_kind,
        trial_count=len(trials), detected_count=len(detected), false_pass_count=len(false_pass),
        indeterminate_count=len(indeterminate), confirmed_detections=sorted(detected),
        confirmed_false_passes=sorted(false_pass), indeterminate_trials=sorted(indeterminate),
        status=status, reason=reason)


def no_trials_recorded(component_id: str, component_kind: str) -> ComponentQualificationRecord:
    """The honest zero-evidence record for a named component nobody has ever run a
    qualification trial against -- the Evidence Truth Rule's negative control: absent evidence
    must produce `NO_TRIALS_RECORDED`, never a silently defaulted `QUALIFIED` (this component
    has simply never been tested) or `DISQUALIFIED` (nobody proved it does anything wrong
    either)."""
    if component_kind not in COMPONENT_KINDS:
        raise CheckerSbQualificationError(
            f"no_trials_recorded: component_kind={component_kind!r} is not one of "
            f"{COMPONENT_KINDS}")
    if not str(component_id or "").strip():
        raise CheckerSbQualificationError("no_trials_recorded: component_id is required")
    return ComponentQualificationRecord(
        component_id=component_id, component_kind=component_kind,
        trial_count=0, detected_count=0, false_pass_count=0, indeterminate_count=0,
        confirmed_detections=[], confirmed_false_passes=[], indeterminate_trials=[],
        status=STATUS_NO_TRIALS,
        reason="no qualification trial has ever been recorded for this component")


# --- a project-wide gate over several components -----------------------------


def evaluate_qualification_gate(
    records: Sequence[ComponentQualificationRecord], *,
    required_components: Optional[Sequence[Tuple[str, str]]] = None,
) -> dict:
    """Worst-wins fold across several components' own qualification records into ONE gate
    verdict, matching this project's Worst-Wins Composite Gates convention: a single
    `DISQUALIFIED_FALSE_PASS_CONFIRMED` component makes the whole gate `NOT_QUALIFIED`
    regardless of how many other components are clean. Only once none is disqualified does an
    incomplete/inconclusive/partial component make the gate `INCOMPLETE_EVIDENCE` rather than
    either extreme; the gate is `QUALIFIED` only when every named component is itself
    `QUALIFIED`.

    `required_components`, when supplied, is a list of `(component_id, component_kind)` pairs
    that MUST appear among `records` -- a required component missing from `records` entirely is
    folded in as its own honest `NO_TRIALS_RECORDED` record rather than silently ignored, so a
    caller cannot manufacture a clean gate by simply never mentioning an unqualified component.
    """
    by_key: Dict[Tuple[str, str], ComponentQualificationRecord] = {}
    for r in records:
        key = (r.component_id, r.component_kind)
        if key in by_key:
            raise CheckerSbQualificationError(
                f"evaluate_qualification_gate: component {key!r} appears more than once in "
                f"`records` -- evaluate one record per component")
        by_key[key] = r

    if required_components:
        for comp_id, comp_kind in required_components:
            key = (comp_id, comp_kind)
            if key not in by_key:
                by_key[key] = no_trials_recorded(comp_id, comp_kind)

    if not by_key:
        return {
            "verdict": GATE_INCOMPLETE_EVIDENCE,
            "components": [],
            "disqualified": [],
            "incomplete": [],
            "reason": "no component qualification records were supplied",
        }

    disqualified = sorted(k for k, r in by_key.items() if r.status == STATUS_DISQUALIFIED)
    incomplete = sorted(
        k for k, r in by_key.items()
        if r.status in (STATUS_NO_TRIALS, STATUS_INCONCLUSIVE, STATUS_PARTIALLY_QUALIFIED))

    if disqualified:
        verdict = GATE_NOT_QUALIFIED
        reason = f"{len(disqualified)} component(s) carry a confirmed false PASS: {disqualified}"
    elif incomplete:
        verdict = GATE_INCOMPLETE_EVIDENCE
        reason = (f"{len(incomplete)} component(s) are not yet fully qualified "
                  f"(no trials, inconclusive evidence, or below the confirmed-detection floor): "
                  f"{incomplete}")
    else:
        verdict = GATE_QUALIFIED
        reason = f"all {len(by_key)} component(s) are QUALIFIED"

    return {
        "verdict": verdict,
        "components": [
            {"component_id": k[0], "component_kind": k[1], **by_key[k].to_dict()}
            for k in sorted(by_key)
        ],
        "disqualified": [{"component_id": k[0], "component_kind": k[1]} for k in disqualified],
        "incomplete": [{"component_id": k[0], "component_kind": k[1]} for k in incomplete],
        "reason": reason,
    }


def render_qualification_markdown(gate_report: dict) -> str:
    """Reuse `connectivity.render_markdown_table()` -- this repo's one parameterized table
    renderer -- rather than a second hand-rolled table loop. Imported lazily so this module
    stays importable even without that dependency chain resolved."""
    from .connectivity import render_markdown_table

    columns = [
        ("component_id", "Component"),
        ("component_kind", "Kind"),
        ("status", "Status"),
        ("detected_count", "Detected"),
        ("false_pass_count", "False PASS"),
        ("indeterminate_count", "Indeterminate"),
        ("reason", "Reason"),
    ]
    rows = gate_report.get("components", [])
    table = render_markdown_table(columns, rows)
    return f"Checker/Scoreboard Qualification: **{gate_report.get('verdict')}**\n\n{table}"


# --- CLI ----------------------------------------------------------------------


def execute_verb(verb: str, *, trials_path: Optional[str] = None,
                 required: Optional[Sequence[str]] = None,
                 as_json: bool = False) -> int:
    """Shared implementation behind both the ad hoc CLI and any future `dv-harness` wiring.

    `trials_path` names a JSON file holding either a bare list of trial dicts, or
    `{"trials": [...]}`. Exit codes: 0 QUALIFIED, 1 NOT_QUALIFIED (a real confirmed false
    PASS), 2 INCOMPLETE_EVIDENCE or a usage error.
    """
    if verb != "evaluate":
        print(json.dumps({"error": f"unknown verb {verb!r}; only 'evaluate' is supported"}))
        return 2
    if not trials_path:
        print(json.dumps({"error": "--trials is required"}))
        return 2
    try:
        with open(trials_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"could not read trials file: {exc}"}))
        return 2

    raw_trials = data.get("trials") if isinstance(data, dict) else data
    if not isinstance(raw_trials, list):
        print(json.dumps({"error": "trials file must be a JSON list, or {'trials': [...]}"}))
        return 2

    try:
        trials = [trial_from_dict(t) for t in raw_trials]
    except CheckerSbQualificationError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    grouped: Dict[Tuple[str, str], List[QualificationTrial]] = {}
    for t in trials:
        grouped.setdefault((t.component_id, t.component_kind), []).append(t)

    try:
        records = [evaluate_component_qualification(v) for v in grouped.values()]
        required_components = None
        if required:
            required_components = []
            for item in required:
                comp_id, _, comp_kind = item.partition(":")
                required_components.append((comp_id, comp_kind or "CHECKER"))
        report = evaluate_qualification_gate(records, required_components=required_components)
    except CheckerSbQualificationError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(render_qualification_markdown(report))

    if report["verdict"] == GATE_QUALIFIED:
        return 0
    if report["verdict"] == GATE_NOT_QUALIFIED:
        return 1
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.checker_sb_qualification",
        description="Checker/Scoreboard Qualification: fold a set of real, cited "
                    "defect-detection/false-PASS trials into a worst-wins qualification "
                    "verdict per named checker/scoreboard component, and an overall gate "
                    "across all of them. Reads and reports only -- writes nothing, gates "
                    "nothing, authorizes nothing.")
    ap.add_argument("verb", choices=["evaluate"], help="Only 'evaluate' is supported today.")
    ap.add_argument("--trials", dest="trials_path", default=None,
                    help="JSON file: a bare list of trial records, or {'trials': [...]}.")
    ap.add_argument("--required", action="append", default=None,
                    help="A required 'component_id:component_kind' pair (repeatable). A "
                         "required component missing from --trials folds in as "
                         "NO_TRIALS_RECORDED rather than being silently omitted.")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="Emit the machine-readable gate report.")
    a = ap.parse_args(argv)
    return execute_verb(a.verb, trials_path=a.trials_path, required=a.required,
                       as_json=a.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
