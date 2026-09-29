#!/usr/bin/env python3
"""command_generation_gate.py -- the New-Command Creation Gate: STANDALONE,
refusing (BLOCKED) the creation of a brand-new DE command.txt/scenario
command unless three independent, evidence-grounded conditions all hold.

Standalone -- not registered in `dv_harness/gates.py`'s `STAGE_GATES` (see
this task's returned `gates_py_entry_snippet` for the integrator). Same file
shape as `assertion_generation_gate.py` / `scoreboard_generation_gate.py`:
a real `dv-harness-evidence:command_generation_gate` payload, one PASS/BLOCKED/
FAIL verdict, no state written.

WHY A NEW COMMAND NEEDS A GATE AT ALL
--------------------------------------
`.claude/skills/CORE/command-inventory/SKILL.md` already treats existing
command.txt content as a reusable capability baseline, and the Engineering
Discipline Rules ("command.txt change-impact check") already require every
change to be checked against the inventory. What was missing was a REFUSAL
point BEFORE a new command is authored at all -- an agent free to always
write a new command.txt has no incentive to ever reuse one, and a new
command assigned to the wrong branch-ownership tier (a VIP-driven scenario
written into `branch_a*`, say) reproduces exactly the drift
`branch_ownership_resolver.py`'s own header names as a confirmed real
incident class.

THIS GATE IMPORTS TWO REAL, JUST-BUILT MODULES RATHER THAN RE-DERIVING
EITHER JUDGMENT
------------------------------------------------------------------------
`dv_harness.existing_command_reuse_score.evaluate_reuse()` is the real
four-dimension reuse ranking (semantic-name match, argument-shape
compatibility, branch-ownership compatibility, real `evidence_db.py`
regression history) already built to answer "can an existing command
already do this". `dv_harness.branch_ownership_resolver.validate_branch_
assignment()` is the real classifier for whether a branch label (`block`/
`branch_a*`/`branch_fw`/`branch_b*`) is the correct tier for a declared
operation's nature, already grounded in `.claude/skills/CORE/
pattern-architecture/SKILL.md` and `.claude/skills/CORE/branch-mapper/
SKILL.md`. This gate calls both and never re-implements a shred of either
judgment -- REUSE OVER REINVENT applies to this gate's own construction, not
only to the command it is judging.

THREE CONDITIONS, ALL REQUIRED
-------------------------------
(a) `existing_command_reuse_score.evaluate_reuse()` must report
    `NO_REUSE_CANDIDATE` for the proposed command's own declared need
    (name/description/keywords/arguments/branch_layer) against the caller-
    supplied `existing_commands` inventory. Anything else --
    `REUSE_CANDIDATES_FOUND` -- means a real reusable command exists and
    must not be duplicated; this gate BLOCKS naming the top candidate that
    reuse-score itself found, and invents no ranking of its own.
(b) `branch_ownership_resolver.validate_branch_assignment()` must report
    `VALID` for the proposed command's declared `branch_layer` against its
    declared `operation_kind` (+ `per_port`/`driven_by`/`arbitration_policy`).
    `INVALID` (wrong tier, or non-canonical naming) and `AMBIGUOUS`
    (the operation's nature could not be resolved from what was declared)
    both BLOCK -- an unresolved ownership question is not a lesser finding
    than a wrong one; it is the same finding this gate cannot pass past.
(c) The task must be IMPLEMENTABLE given the evidence actually supplied --
    checked here, not by either imported module (neither one asks this
    question). A non-empty, non-placeholder `implementation_plan`, at least
    one non-placeholder `source_citations` entry, and a `grounding_basis`
    drawn from the primary-source vocabulary the Engineering Discipline
    Rules already name for THIS command's own resolved ownership tier
    (VIP examples/user manual/source/class reference for a VIP-owned
    command; DUT RTL/PHY documents/programming guide/register
    documentation for a DUT/FW/GLOBAL-owned one) -- directly operationalizing
    "branch-B / VIP pattern changes: query VIP examples... FIRST" and
    "branch-A / branch_fw changes: query DUT RTL source... FIRST" rather
    than inventing a fourth vocabulary. A grounding basis for the WRONG tier
    (VIP-sourced grounding cited for a branch_a*-owned command, or vice
    versa) is treated the same as no grounding at all: citing the wrong
    kind of primary source is not weaker evidence, it is evidence about a
    different command.

WHAT THIS GATE DOES NOT DO
---------------------------
It does not write a command.txt, does not pick a reuse candidate for the
caller, does not decide which branch label to use, and does not run a
build/regression/LSF job. It also does not verify that the cited source
citations are TRUE -- per the Evidence Truth Rule, this gate can check that
real-looking evidence was cited and is internally consistent with the
declared ownership tier, never that a citation such as "VIP user guide
section 4.2" actually says what the agent claims. Fabricating a VIP
API/class/sequence, RTL content, or command.txt semantics not grounded in
real evidence remains this project's #1 defect risk and is not something a
shape check over agent-typed text can prove or disprove; this gate narrows
where an agent is ALLOWED to skip citing evidence at all, it does not
verify the citations themselves.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# Same idiom as waiver_revalidation_gate.py / rtl_write_scope_guard_gate.py:
# prefer the real dv_harness package location run_gate() already knows and
# passes via env; the parents[2] guess only holds in this repo's own
# dogfooding layout where tools/verification_flow/ and dv_harness/ are
# siblings under the same root.
_pkg_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
sys.path.insert(0, str(pathlib.Path(_pkg_root) if _pkg_root
                       else pathlib.Path(__file__).resolve().parents[2]))

try:
    from dv_harness import existing_command_reuse_score as _reuse_score
    from dv_harness import branch_ownership_resolver as _branch_owner
    _DEPENDENCIES_AVAILABLE = True
    _DEPENDENCY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - broken/partial deployment
    _reuse_score = None
    _branch_owner = None
    _DEPENDENCIES_AVAILABLE = False
    _DEPENDENCY_IMPORT_ERROR = repr(exc)


def project_root():
    # run_gate() supplies the real project root, and also runs every gate
    # with cwd=<project root>; cwd is the fallback for a direct invocation.
    return pathlib.Path(os.environ.get("DV_HARNESS_PROJECT_ROOT") or os.getcwd())


# --- primary-source grounding vocabulary -------------------------------------
#
# Directly transcribed from CLAUDE.md's "Engineering Discipline Rules"
# (2026-08-29) bullets this gate's own docstring quotes -- not a new
# vocabulary invented for this gate. VIP-owned (branch_b*) commands must be
# grounded in VIP-side primary sources; DUT/FW/GLOBAL-owned (branch_a*/
# branch_fw/block) commands must be grounded in DUT-side primary sources.
VIP_GROUNDING_BASES = frozenset({
    "VIP_EXAMPLE", "VIP_SOURCE", "VIP_USER_GUIDE", "VIP_CLASS_REFERENCE",
})
DUT_GROUNDING_BASES = frozenset({
    "DUT_RTL", "PHY_DOCUMENT", "PROGRAMMING_GUIDE", "REGISTER_DOCUMENTATION",
})
ALL_GROUNDING_BASES = VIP_GROUNDING_BASES | DUT_GROUNDING_BASES

#: Which grounding vocabulary a resolved ownership tier requires. Populated
#: after `branch_ownership_resolver` import succeeds so this module never
#: hardcodes that resolver's own OWNER_* string constants a second time.
_TIER_GROUNDING = {}
if _branch_owner is not None:
    _TIER_GROUNDING = {
        _branch_owner.OWNER_VIP: VIP_GROUNDING_BASES,
        _branch_owner.OWNER_DUT: DUT_GROUNDING_BASES,
        _branch_owner.OWNER_FW: DUT_GROUNDING_BASES,
        _branch_owner.OWNER_GLOBAL: DUT_GROUNDING_BASES,
    }

#: Values that read as "nothing was really said here" -- the same class of
#: placeholder text `requirement_contract.py`'s own STATUS_OVERCLAIMED rule
#: refuses to accept as a completed field, applied locally so this module
#: does not import that (out-of-scope) module for one constant.
_PLACEHOLDER_TEXT = frozenset({"", "tbd", "n/a", "na", "unknown", "?", "none", "null"})


def _is_placeholder(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _PLACEHOLDER_TEXT


def _clean_strings(values) -> list:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(v).strip() for v in values if not _is_placeholder(v)]


# --- (a) reuse check ----------------------------------------------------------


def _need_from_proposed_command(proposed: dict) -> dict:
    """Builds the `need` dict `existing_command_reuse_score.evaluate_reuse()`
    expects, straight out of the proposed command's own declared fields --
    never inventing a description/keyword that field did not carry."""
    need = {}
    for key in ("description", "summary", "operation", "intent", "title"):
        if proposed.get(key):
            need[key] = proposed[key]
    if proposed.get("command_name") and "title" not in need:
        need["name"] = proposed["command_name"]
    if proposed.get("keywords"):
        need["keywords"] = proposed["keywords"]
    arguments = proposed.get("arguments")
    if arguments is None:
        arguments = proposed.get("PARAMETERS")
    if arguments is not None:
        need["arguments"] = arguments
    if proposed.get("branch_layer"):
        need["branch_layer"] = proposed["branch_layer"]
    return need


def _evaluate_reuse(proposed: dict, existing_commands, *, root, db_path) -> dict:
    need = _need_from_proposed_command(proposed)
    try:
        report = _reuse_score.evaluate_reuse(
            need, existing_commands or [], root=root, db_path=db_path)
    except _reuse_score.NeedValidationError as exc:
        return {"passed": False, "reason": "MALFORMED_REUSE_NEED", "detail": str(exc)}
    if report["status"] == _reuse_score.NO_REUSE_CANDIDATE:
        return {"passed": True, "report_status": report["status"], "reason": report.get("reason")}
    return {
        "passed": False,
        "report_status": report["status"],
        "top_candidate": report.get("top_candidate"),
        "reason": (
            "a real reusable command was found by existing_command_reuse_score "
            "and must not be duplicated by a new command.txt"
        ),
    }


# --- (b) branch-ownership check ----------------------------------------------


def _evaluate_branch_ownership(proposed: dict, ownership: dict) -> dict:
    branch_label = proposed.get("branch_layer")
    result = _branch_owner.validate_branch_assignment(
        branch_label,
        ownership.get("operation_kind"),
        per_port=ownership.get("per_port"),
        driven_by=ownership.get("driven_by"),
        arbitration_policy=ownership.get("arbitration_policy"),
    )
    passed = result.verdict == _branch_owner.VALID
    return {"passed": passed, "validation": result.to_dict()}


# --- (c) task-implementability check -----------------------------------------


def _evaluate_implementability(task_evidence: dict, resolved_tier) -> dict:
    if not isinstance(task_evidence, dict):
        return {"passed": False, "reason": "TASK_EVIDENCE_NOT_A_DICT"}

    plan = task_evidence.get("implementation_plan")
    if _is_placeholder(plan):
        return {"passed": False, "reason": "NO_IMPLEMENTATION_PLAN",
                "detail": "implementation_plan is missing, empty, or a placeholder value"}

    citations = _clean_strings(task_evidence.get("source_citations"))
    if not citations:
        return {"passed": False, "reason": "NO_SOURCE_CITATIONS",
                "detail": "source_citations carries no real (non-placeholder) evidence citation"}

    grounding_basis = task_evidence.get("grounding_basis")
    if grounding_basis not in ALL_GROUNDING_BASES:
        return {"passed": False, "reason": "GROUNDING_BASIS_NOT_RECOGNIZED",
                "detail": f"grounding_basis must be one of {sorted(ALL_GROUNDING_BASES)}, "
                          f"got {grounding_basis!r}"}

    if resolved_tier is not None:
        required = _TIER_GROUNDING.get(resolved_tier)
        if required is not None and grounding_basis not in required:
            return {"passed": False, "reason": "GROUNDING_BASIS_WRONG_TIER",
                    "detail": (
                        f"operation resolved to ownership tier {resolved_tier!r}, which the "
                        f"Engineering Discipline Rules require grounding from {sorted(required)}; "
                        f"{grounding_basis!r} is grounding for a different tier's primary sources"
                    )}

    return {"passed": True, "grounding_basis": grounding_basis,
            "source_citations": citations, "implementation_plan": plan}


# --- top-level evaluation ------------------------------------------------------


def evaluate(payload: dict, *, root=None, db_path=None) -> dict:
    if not _DEPENDENCIES_AVAILABLE:
        return {"status": "FAIL", "reason": "DEPENDENCY_UNAVAILABLE",
                "detail": f"could not import existing_command_reuse_score / "
                          f"branch_ownership_resolver: {_DEPENDENCY_IMPORT_ERROR}"}

    if not isinstance(payload, dict):
        return {"status": "FAIL", "reason": "MALFORMED_PAYLOAD",
                "detail": "evidence block is not a JSON object"}

    proposed = payload.get("proposed_command")
    existing_commands = payload.get("existing_commands")
    ownership = payload.get("ownership")
    task_evidence = payload.get("task_evidence")

    if not isinstance(proposed, dict) or not proposed:
        return {"status": "FAIL", "reason": "MISSING_PROPOSED_COMMAND",
                "detail": "proposed_command must be a non-empty object"}
    if existing_commands is not None and not isinstance(existing_commands, list):
        return {"status": "FAIL", "reason": "MALFORMED_EXISTING_COMMANDS",
                "detail": "existing_commands must be a list when supplied"}
    if not isinstance(ownership, dict) or not ownership:
        return {"status": "FAIL", "reason": "MISSING_OWNERSHIP_DECLARATION",
                "detail": "ownership must be a non-empty object "
                          "(operation_kind, per_port, driven_by, arbitration_policy)"}

    reuse_check = _evaluate_reuse(proposed, existing_commands, root=root, db_path=db_path)
    if reuse_check.get("reason") == "MALFORMED_REUSE_NEED":
        return {"status": "FAIL", "reason": "MALFORMED_REUSE_NEED",
                "detail": reuse_check.get("detail"), "reuse_check": reuse_check}
    if not reuse_check["passed"]:
        return {"status": "BLOCKED", "reason": "REUSABLE_COMMAND_EXISTS",
                "detail": reuse_check.get("reason"), "reuse_check": reuse_check}

    ownership_check = _evaluate_branch_ownership(proposed, ownership)
    if not ownership_check["passed"]:
        return {"status": "BLOCKED", "reason": "BRANCH_OWNERSHIP_NOT_VALID",
                "detail": ownership_check["validation"].get("reason"),
                "ownership_check": ownership_check}

    resolved_tier = ownership_check["validation"].get("assigned_tier")
    implementability_check = _evaluate_implementability(task_evidence, resolved_tier)
    if not implementability_check["passed"]:
        return {"status": "BLOCKED", "reason": "TASK_NOT_IMPLEMENTABLE",
                "detail": implementability_check.get("reason"),
                "implementability_check": implementability_check}

    return {
        "status": "PASS",
        "reuse_check": reuse_check,
        "ownership_check": ownership_check,
        "implementability_check": implementability_check,
    }


_EXIT_CODES = {
    "PASS": 0,
    "FAIL:DEPENDENCY_UNAVAILABLE": 2,
    "FAIL:MALFORMED_PAYLOAD": 3,
    "FAIL:MISSING_PROPOSED_COMMAND": 3,
    "FAIL:MALFORMED_EXISTING_COMMANDS": 3,
    "FAIL:MISSING_OWNERSHIP_DECLARATION": 3,
    "FAIL:MALFORMED_REUSE_NEED": 3,
    "BLOCKED:REUSABLE_COMMAND_EXISTS": 4,
    "BLOCKED:BRANCH_OWNERSHIP_NOT_VALID": 5,
    "BLOCKED:TASK_NOT_IMPLEMENTABLE": 6,
}


def _exit_code(result: dict) -> int:
    key = f"{result['status']}:{result.get('reason')}"
    return _EXIT_CODES.get(key, 1 if result["status"] != "PASS" else 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="New-Command Creation Gate: refuses (BLOCKED) a new DE command.txt "
                    "unless no real reusable command exists, its declared branch ownership "
                    "is VALID, and the task is implementable given real cited evidence.")
    ap.add_argument("--command-request", required=True,
                    help="JSON file: the dv-harness-evidence:command_generation_gate payload "
                         "(proposed_command / existing_commands / ownership / task_evidence).")
    ap.add_argument("--root", default=None,
                    help="Project root override (for the read-only evidence_db reuse-history "
                         "lookup); defaults to DV_HARNESS_PROJECT_ROOT / cwd.")
    ap.add_argument("--db", default=None, help="Evidence database path override.")
    args = ap.parse_args(argv)

    payload = json.loads(pathlib.Path(args.command_request).read_text(encoding="utf-8"))
    root = args.root or str(project_root())
    result = evaluate(payload, root=root, db_path=args.db)
    print(json.dumps(result, indent=2, sort_keys=True))
    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
