"""dv_harness/l5dgva_v5_ss84_phase_entry_protocol_schema.py -- L5DGVA V5
section 84 "Mandatory Phase Entry Protocol": the 14-step schema + a real,
static structural check over `dv_harness/gates.py`'s own `STAGE_GATES` dict --
never a live-dispatch claim.

MIGRATED (M5 Capability Pool Closure, CAP-POOL-008, from Parent). Real,
tested Parent capability (9/9 tests, independently re-run in Parent's own
tree before trusting), unblocked because its one real dependency
(`dv_harness/gates.py`'s `STAGE_GATES` dict) is already present in
canonical. ADAPTED, not blind-copied: `stage_gates_phase_name_coverage()`
reads whatever `STAGE_GATES` dict is really registered in the repo it
runs in, and canonical's own registry is smaller than Parent's (4 fewer
gate entries registered as of this migration -- confirmed by direct
diff). The "HONEST FINDING" paragraph below and the coverage-count test
are RE-DERIVED against canonical's own real `gates.py`, not copied from
Parent's citation -- see the updated finding below.

SCOPE DECISION (carried from Parent, not re-litigated). This module does
not attempt to prove the section's own COMPOSITE requirement
(`MandatoryPhaseEntryProtocol_PASS` / `PhaseTriggeredRecallCoverage_PASS`)
true -- that can only be proven by actually running the 14-step sequence
at a real phase boundary and recording what was retrieved, live-runtime
evidence a static-code task cannot fabricate. It closes a narrower,
genuinely different question: does section 84's own text name a SCHEMA
(the 14 ordered steps, the 15 named material phases) and a STRUCTURAL
CHECK (do those 15 phase names have any real, already-registered
`STAGE_GATES` counterpart in this codebase's own `gates.py` source,
checked by real string comparison, not a live phase boundary) that IS
extractable today with zero live dispatch. It does.

PRIMARY SOURCE, quoted verbatim (Parent's own citation,
`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v5.md:1406-1423`
-- that document corpus is Parent-only, not present in canonical; the
quote itself is carried here as the schema's own citation, the corpus
migration question itself is separately tracked, unresolved, in
`M4_M3_DEFERRED_CLOSURE.md`):

    ## 84. Mandatory Phase Entry Protocol

    Before every material phase: 1. identify phase/scope/profile; 2.
    assemble required context; 3. retrieve applicable KC; 4. retrieve
    reference methods; 5. retrieve DE executable intent; 6. retrieve
    OpenSpec effective values; 7. retrieve existing-environment manifests;
    8. retrieve design/connectivity evidence; 9. evaluate applicability; 10.
    create/update PhaseUnderstandingManifest; 11. create/update execution
    plan; 12. check Understanding <-> Plan consistency; 13. run phase gate;
    14. execute only after PASS.

    Apply at intake, discovery, architecture, vPlan,
    VIP/bind/bridge/checker/scoreboard/assertion/coverage generation, build,
    elaboration, smoke, regression, debug, coverage closure, signoff,
    System-Level composition, change impact and external-resolution resume.

    Required: `MandatoryPhaseEntryProtocol_PASS = true`
    `PhaseTriggeredRecallCoverage_PASS = true`

REUSE CHECK (re-confirmed this migration). `grep -rln
"MandatoryPhaseEntryProtocol\\|PhaseTriggeredRecallCoverage"
dv_harness/ dv_harness_tests/` returned zero hits in canonical before this
migration -- nothing in this codebase names either required flag today.
`gates.py`'s own `STAGE_GATES` dict (the real, already-existing per-stage
gate registry) is reused as-is, read-only, never edited or duplicated.

WHAT THIS MODULE ACTUALLY DOES.
  1. `PHASE_ENTRY_STEPS` -- the 14 named steps, verbatim, in order, as data.
  2. `MATERIAL_PHASES` -- the 15 named phases section 84 applies at,
     verbatim, as data.
  3. `PhaseEntryRecord` / `evaluate_mandatory_phase_entry_protocol()` -- a
     pure structural-completeness check over CALLER-SUPPLIED per-step
     evidence (exactly the `PhaseUnderstandingManifest`-style posture: this
     function cannot itself go retrieve KC/reference methods/OpenSpec
     values live; it can only tell a caller who already did so, and cites
     an `evidence_ref` for each step, whether all 14 are honestly present).
     Called with no evidence it reports every one of the 14 steps missing --
     it does not default to PASS.
  4. `stage_gates_phase_name_coverage()` -- the one part of this module that
     needs NO caller-supplied evidence at all: it reads the real
     `dv_harness.gates.STAGE_GATES` dict's own key names (never a
     hand-copied second list) and does a normalized substring match against
     each of the 15 `MATERIAL_PHASES` names. This is a real static fact
     about THIS codebase's current stage registry, re-derivable by anyone
     re-running it.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.
  * It does not claim `MandatoryPhaseEntryProtocol_PASS` or
    `PhaseTriggeredRecallCoverage_PASS` is true anywhere in this codebase --
    both stay honestly unreachable without a real phase boundary actually
    firing the 14-step sequence and a real audit trail proving it did.
  * It does not wire itself into `engine.py`'s `run_stage()` or any other
    live dispatch path. No phase entry in this codebase currently calls
    this module. That wiring is left open, same as in Parent.
  * `stage_gates_phase_name_coverage()`'s NOT_MATCHED verdicts are not
    "these phases are unsupported" -- only "no `STAGE_GATES` key's own text
    names this phase directly"; a phase may still be handled inside a
    differently-named stage's gate list. Disclosed as a naming-coverage
    fact, not a capability verdict.

HONEST FINDING (a real run against CANONICAL's actual `gates.py`, RE-
DERIVED for this migration, not copied from Parent's own citation --
canonical's `STAGE_GATES` registers 4 fewer gate entries than Parent's as
of this migration: `vplan_scope_ownership_stage_gate`,
`canonical_reference_integration_baseline_gate`,
`uvm_dut_top_integration_pregeneration_gate`,
`de_facing_uvm_leakage_gate` -- none of the 4 changes this module's own
result: re-run directly against canonical's real `gates.STAGE_GATES`,
the finding is IDENTICAL to Parent's own citation. Of the 15 named
material phases, 12 have at least one real `STAGE_GATES` key whose name
textually contains one of the phase's own normalized word-tokens
(`intake`->`INTAKE`; `discovery`->`DISCOVERY`/`ARCH_DISCOVERY`;
`architecture`->`VERIFICATION_ARCHITECTURE`; `vPlan`->`VPLAN`;
`build`->`BUILD`/`BUILD_DEBUG`;
`regression`->`REGRESSION`/`REGRESSION_MONITOR`/`REGRESSION_SELECT`;
`debug`->`BUILD_DEBUG`; `coverage closure`->`COVERAGE_CLOSURE`/
`REQUIREMENT_CLOSURE`; `signoff`->`SIGNOFF`;
`System-Level composition`->`SYSTEM_LEVEL`;
`change impact`->`CHANGE_IMPACT`); and, honestly disclosed as a crude
byproduct of the same plain-substring rule rather than a real semantic
match, `VIP/bind/bridge/checker/scoreboard/assertion/coverage generation`
also matches `COVERAGE_CLOSURE` solely via its own `coverage` word-token
-- this module does not upgrade that to a stronger claim than "one word
of this phase's name is a substring of that stage key". Exactly 3 phases
have NO `STAGE_GATES` key matching any of their word-tokens at all:
`elaboration`, `smoke`, `external-resolution resume` -- a real, disclosed
naming-coverage gap, not a claim this module resolves. See
`dv_harness_tests/test_l5dgva_v5_ss84_phase_entry_protocol_schema.py` for
the fixture proving this finding as a regression.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import gates as _gates

#: The 14 named steps, verbatim order, from section 84's own numbered list.
PHASE_ENTRY_STEPS: Tuple[Tuple[int, str], ...] = (
    (1, "identify phase/scope/profile"),
    (2, "assemble required context"),
    (3, "retrieve applicable KC"),
    (4, "retrieve reference methods"),
    (5, "retrieve DE executable intent"),
    (6, "retrieve OpenSpec effective values"),
    (7, "retrieve existing-environment manifests"),
    (8, "retrieve design/connectivity evidence"),
    (9, "evaluate applicability"),
    (10, "create/update PhaseUnderstandingManifest"),
    (11, "create/update execution plan"),
    (12, "check Understanding <-> Plan consistency"),
    (13, "run phase gate"),
    (14, "execute only after PASS"),
)

#: The 15 named material phases section 84 applies at, verbatim order.
MATERIAL_PHASES: Tuple[str, ...] = (
    "intake",
    "discovery",
    "architecture",
    "vPlan",
    "VIP/bind/bridge/checker/scoreboard/assertion/coverage generation",
    "build",
    "elaboration",
    "smoke",
    "regression",
    "debug",
    "coverage closure",
    "signoff",
    "System-Level composition",
    "change impact",
    "external-resolution resume",
)


@dataclass(frozen=True)
class PhaseEntryStepEvidence:
    """One of the 14 steps, with whatever the caller supplied for it."""
    step_id: int
    description: str
    satisfied: bool = False
    evidence_ref: Optional[str] = None


@dataclass(frozen=True)
class PhaseEntryRecord:
    phase: str
    steps: Tuple[PhaseEntryStepEvidence, ...]


@dataclass(frozen=True)
class MandatoryPhaseEntryVerdict:
    phase: str
    pass_: bool
    missing_step_ids: Tuple[int, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "MandatoryPhaseEntryProtocol_PASS": self.pass_,
            "missing_step_ids": list(self.missing_step_ids),
            "reason": self.reason,
        }


def build_phase_entry_record(
    phase: str,
    evidence: Optional[Dict[int, str]] = None,
) -> PhaseEntryRecord:
    """Build a `PhaseEntryRecord` for `phase` from caller-supplied per-step
    evidence (`{step_id: evidence_ref}`). A step with no entry, or an empty
    `evidence_ref`, is recorded `satisfied=False` -- this function never
    infers or assumes a step happened."""
    evidence = evidence or {}
    steps = tuple(
        PhaseEntryStepEvidence(
            step_id=step_id,
            description=description,
            satisfied=bool(evidence.get(step_id)),
            evidence_ref=evidence.get(step_id) or None,
        )
        for step_id, description in PHASE_ENTRY_STEPS
    )
    return PhaseEntryRecord(phase=phase, steps=steps)


def evaluate_mandatory_phase_entry_protocol(
    record: PhaseEntryRecord,
) -> MandatoryPhaseEntryVerdict:
    """PASS only if all 14 steps are `satisfied` with a real, non-empty
    `evidence_ref`. Called with an empty/default record this reports all 14
    steps missing -- it never defaults toward PASS."""
    missing = tuple(s.step_id for s in record.steps if not s.satisfied)
    if missing:
        return MandatoryPhaseEntryVerdict(
            phase=record.phase,
            pass_=False,
            missing_step_ids=missing,
            reason=(
                f"MandatoryPhaseEntryProtocol_PASS is honestly False for phase "
                f"'{record.phase}': step(s) {list(missing)} of 14 have no "
                f"evidence_ref on this record."
            ),
        )
    return MandatoryPhaseEntryVerdict(
        phase=record.phase,
        pass_=True,
        missing_step_ids=(),
        reason="All 14 phase-entry steps carry a non-empty evidence_ref.",
    )


#: Result of the one part of this module that needs no caller-supplied
#: evidence: a real name-coverage scan of `gates.STAGE_GATES`.
MATCHED = "MATCHED"
NOT_MATCHED = "NOT_MATCHED"


@dataclass(frozen=True)
class PhaseStageNameCoverage:
    phase: str
    status: str
    matched_stage_keys: Tuple[str, ...] = ()


def _normalize(text: str) -> str:
    """Lowercase, alnum-only token -- e.g. `"System-Level composition"` ->
    `"systemlevelcomposition"`, `"VIP/bind/bridge/checker/scoreboard/
    assertion/coverage generation"` -> a single long alnum run. Used only to
    do a plain substring test against `STAGE_GATES` keys, never a semantic
    guess about which stage "really" handles a phase."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


#: A phase whose own name is a slash-joined multi-word list needs its
#: individual words checked too (a single long fused token like
#: "vipbindbridgecheckerscoreboardassertioncoveragegeneration" will never be
#: a substring of any short `STAGE_GATES` key even if one word alone would
#: be) -- split on non-alnum before normalizing each piece, still a plain
#: substring test, never a curated phase->stage mapping.
def _normalized_tokens(text: str) -> Tuple[str, ...]:
    return tuple(_normalize(piece) for piece in re.split(r"[^A-Za-z0-9]+", text) if piece)


def stage_gates_phase_name_coverage() -> Dict[str, PhaseStageNameCoverage]:
    """For each of the 15 `MATERIAL_PHASES`, check whether any real
    `dv_harness.gates.STAGE_GATES` key contains one of that phase's own
    normalized word-tokens as a substring (case-insensitive, alnum-only on
    both sides). Reads `gates.STAGE_GATES` directly -- never a second,
    hand-maintained copy of its key list -- so this cannot silently drift
    from the real stage registry."""
    stage_keys = tuple(_gates.STAGE_GATES.keys())
    normalized_keys = {key: _normalize(key) for key in stage_keys}
    result: Dict[str, PhaseStageNameCoverage] = {}
    for phase in MATERIAL_PHASES:
        tokens = _normalized_tokens(phase)
        matches = tuple(
            key
            for key in stage_keys
            for token in tokens
            if token and token in normalized_keys[key]
        )
        # de-duplicate, preserve STAGE_GATES declaration order
        seen: List[str] = []
        for key in stage_keys:
            if key in matches and key not in seen:
                seen.append(key)
        if seen:
            result[phase] = PhaseStageNameCoverage(
                phase=phase, status=MATCHED, matched_stage_keys=tuple(seen)
            )
        else:
            result[phase] = PhaseStageNameCoverage(phase=phase, status=NOT_MATCHED)
    return result
