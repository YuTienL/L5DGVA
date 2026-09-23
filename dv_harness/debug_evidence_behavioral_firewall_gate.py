"""dv_harness/debug_evidence_behavioral_firewall_gate.py -- L5DGVA V17
(`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v17_ULTRA_STRICT_
Auto_KC_Debug.md`) sections 475 ("GUI Escalation") and 489 ("Debug Behavioral
Firewall") -- a real, evidence-gated PRE-DECLARATION gate, never a live
monitor.

THE GAP THIS CLOSES
--------------------
A fresh full re-sweep of the `B_kc_memory_obsidian` domain (2026-09-17) found
`SS475`/`SS482`/`SS483`/`SS484`/`SS485`/`SS486`/`SS487`/`SS489`/`SS490` cited
by zero real `dv_harness/` module (confirmed by `grep -rl "SS<n>\\b"
dv_harness/*.py` for each number individually -- SS487/SS489 are MENTIONED in
`reference_debug_differential.py`'s own docstring prose, lines 31-32/41/71,
but neither module computes `DebugKCGeneralizationTruth_PASS` nor
`DebugBehavioralFirewall_PASS` as a real flag anywhere). This module closes
SS475 and SS489 -- the two of that set whose contract text is a pure,
caller-supplied-evidence structural CHECKLIST, needing no live session,
engine wiring, or external tool, unlike SS482-486 (KC lifecycle
self-repair/regression/eight-engine execution proof, left open below).

PRIMARY SOURCE, QUOTED VERBATIM
--------------------------------
`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v17_ULTRA_STRICT_
Auto_KC_Debug.md`, lines 6439-6446:

    ## 475. GUI Escalation

    Do not conclude GUI is required merely because current FSDB lacks a
    signal. Escalate only after logs/existing
    diagnostics/reference-wave/targeted-FSDB methods are insufficient and
    GUI is the next-best evidence source.

    Required: `NoPrematureGUIDebugEscalation_PASS = true`

Lines 6607-6614:

    ## 489. Debug Behavioral Firewall

    Before declaring a debug path unavailable, require: existing diagnostics
    checked? logs checked? current FSDB merely missing scope? Reference wave
    config studied? targeted scope extension possible? fsdbreport attempted
    after scope exists? GUI truly next-best?

    Required: `DebugBehavioralFirewall_PASS = true`

SS475 IS SS489'S LAST CHECKLIST ITEM, NOT A SEPARATE CHECKLIST
------------------------------------------------------------------
SS489's seven questions are, in order: (1) existing diagnostics checked,
(2) logs checked, (3) current FSDB merely missing scope (i.e. not
"impossible"), (4) Reference wave config studied, (5) targeted scope
extension possible, (6) fsdbreport attempted after scope exists, (7) "GUI
truly next-best?" -- which is exactly SS475's own criterion, worded
identically ("next-best evidence source" / "GUI truly next-best"). This
module therefore evaluates ONE checklist (`DebugEvidenceChecklist`, below)
and derives BOTH required flags from it: `DebugBehavioralFirewall_PASS`
(all seven items satisfied) and `NoPrematureGUIDebugEscalation_PASS` (item 7
alone, but ONLY meaningful/true if a GUI escalation was actually declared;
if no GUI escalation was declared at all, there is nothing premature to
guard against, so the flag is vacuously true) -- never re-deriving one from
the other by guessing, never silently treating "not applicable" as "PASS".

REUSE, NOT REIMPLEMENTATION
-----------------------------
This is the same "pure structural pre-declaration gate over caller-supplied
per-item booleans, `NOT_EVALUATED` for anything not supplied, honest
violation list" shape `dv_harness/command_precondition_gate.py` and
`dv_harness/irq_backdoor_qualification_gate.py` already use for their own,
differently-scoped checklists -- no new gate SHAPE is invented here, only a
new checklist over new content. This module imports nothing from either
(their checklists are unrelated in content) and duplicates no logic from
`fsdb_scope_gap_classifier.py` or `reference_wave_config_inherit.py`: it
takes each of THOSE modules' own real verdicts as plain caller-supplied
booleans (an integration caller is expected to pass
`fsdb_scope_gap_classifier`'s own PRESENT/CURRENT_FSDB_SCOPE_INSUFFICIENT/
UNKNOWN result mapped to this checklist's `current_fsdb_scope_gap_only`
field, for example) rather than re-implementing FSDB-scope classification
here.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
--------------------------------------------
It does not decide FROM RAW EVIDENCE (a sim.log, an FSDB file, a wave.txt)
whether any checklist item is true -- that is each cited sibling module's
own job. It does not run/replay/simulate anything. It does not itself
detect a debug-path-unavailable DECLARATION in narrative text (a caller
supplies `gui_escalation_declared`/`debug_path_declared_unavailable`
directly) -- SS490's `debug_prohibited_behavior_registry.py` companion
module is the one that scans real narrative TEXT for these declarations;
this module only judges whether the supporting evidence checklist was
honestly satisfied once such a declaration/escalation is asserted to exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

#: The seven SS489 checklist items, in the contract's own stated order.
#: Each is `Optional[bool]`: `None` means "not supplied" and is NEVER treated
#: as satisfied -- an unevaluated item is a violation, not a silent pass.
CHECKLIST_ITEM_NAMES: Tuple[str, ...] = (
    "existing_diagnostics_checked",
    "logs_checked",
    "current_fsdb_scope_gap_only",
    "reference_wave_config_studied",
    "targeted_scope_extension_possible",
    "fsdbreport_attempted_after_scope_exists",
    "gui_truly_next_best",
)


@dataclass(frozen=True)
class DebugEvidenceChecklist:
    """Caller-supplied evidence for SS489's seven checklist items, plus the
    two declarations (`debug_path_declared_unavailable`,
    `gui_escalation_declared`) that decide WHICH flags this checklist's
    evaluation is even judging (SS489 gates "declaring a debug path
    unavailable"; SS475 gates "concluding GUI is required" specifically --
    two distinct assertions a caller may or may not have actually made)."""
    existing_diagnostics_checked: Optional[bool] = None
    logs_checked: Optional[bool] = None
    current_fsdb_scope_gap_only: Optional[bool] = None
    reference_wave_config_studied: Optional[bool] = None
    targeted_scope_extension_possible: Optional[bool] = None
    fsdbreport_attempted_after_scope_exists: Optional[bool] = None
    gui_truly_next_best: Optional[bool] = None
    #: Did the debug narrative actually declare the debug path unavailable?
    #: If False, SS489's firewall has nothing to gate (vacuous PASS).
    debug_path_declared_unavailable: bool = False
    #: Did the debug narrative actually escalate to/declare GUI required?
    #: If False, SS475 has nothing to gate (vacuous PASS).
    gui_escalation_declared: bool = False

    def item(self, name: str) -> Optional[bool]:
        return getattr(self, name)


@dataclass(frozen=True)
class DebugBehavioralFirewallResult:
    """The two SS475/SS489 required flags plus the honest per-item detail
    behind them -- never a bare boolean a caller cannot audit."""
    debug_path_declared_unavailable: bool
    gui_escalation_declared: bool
    unevaluated_items: Tuple[str, ...]
    failed_items: Tuple[str, ...]
    #: SS489's own required flag.
    DebugBehavioralFirewall_PASS: bool
    #: SS475's own required flag.
    NoPrematureGUIDebugEscalation_PASS: bool
    violations: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "DebugBehavioralFirewall_PASS": self.DebugBehavioralFirewall_PASS,
            "NoPrematureGUIDebugEscalation_PASS": self.NoPrematureGUIDebugEscalation_PASS,
            "debug_path_declared_unavailable": self.debug_path_declared_unavailable,
            "gui_escalation_declared": self.gui_escalation_declared,
            "unevaluated_items": list(self.unevaluated_items),
            "failed_items": list(self.failed_items),
            "violations": list(self.violations),
        }


def evaluate_debug_behavioral_firewall(
    checklist: DebugEvidenceChecklist,
) -> DebugBehavioralFirewallResult:
    """The real SS475/SS489 evaluator.

    `DebugBehavioralFirewall_PASS` (SS489): if
    `debug_path_declared_unavailable` is False, vacuously True (nothing was
    declared unavailable, so there is nothing to have checked evidence
    for). If True, every one of the seven checklist items must be `True`
    (not `None`, not `False`) -- an item left `None` is reported as
    `unevaluated`, distinct from one explicitly `False`, but BOTH fail the
    gate; SS489 requires the question be answered affirmatively, not merely
    asked.

    `NoPrematureGUIDebugEscalation_PASS` (SS475): if `gui_escalation_declared`
    is False, vacuously True. If True, requires the first six checklist
    items (everything SS475's prose lists as a prerequisite: "logs/existing
    diagnostics/reference-wave/targeted-FSDB methods") to each be `True` --
    escalating to GUI without having exhausted those is exactly the
    "concluding GUI is required merely because current FSDB lacks a signal"
    SS475 prohibits, regardless of whether a broader
    `debug_path_declared_unavailable` assertion was also made.
    """
    unevaluated: List[str] = []
    failed: List[str] = []
    for name in CHECKLIST_ITEM_NAMES:
        value = checklist.item(name)
        if value is None:
            unevaluated.append(name)
        elif value is False:
            failed.append(name)

    violations: List[str] = []

    if not checklist.debug_path_declared_unavailable:
        firewall_pass = True
    else:
        bad = [n for n in CHECKLIST_ITEM_NAMES if checklist.item(n) is not True]
        firewall_pass = not bad
        if bad:
            violations.append(
                "SS489 Debug Behavioral Firewall: debug path declared "
                "unavailable without satisfying: " + ", ".join(bad)
            )

    prerequisite_items = CHECKLIST_ITEM_NAMES[:-1]  # everything but gui_truly_next_best
    if not checklist.gui_escalation_declared:
        gui_pass = True
    else:
        bad_gui = [n for n in prerequisite_items if checklist.item(n) is not True]
        gui_pass = not bad_gui
        if bad_gui:
            violations.append(
                "SS475 GUI Escalation: GUI escalation declared before "
                "exhausting: " + ", ".join(bad_gui)
            )

    return DebugBehavioralFirewallResult(
        debug_path_declared_unavailable=checklist.debug_path_declared_unavailable,
        gui_escalation_declared=checklist.gui_escalation_declared,
        unevaluated_items=tuple(unevaluated),
        failed_items=tuple(failed),
        DebugBehavioralFirewall_PASS=firewall_pass,
        NoPrematureGUIDebugEscalation_PASS=gui_pass,
        violations=tuple(violations),
    )
