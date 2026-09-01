#!/usr/bin/env python3
# NEW (2026-09-01, vplan-doc-and-wiring-fix): closes the gap this session's
# audit confirmed -- STAGE_GATES["VPLAN"] previously wired ONLY
# spec_coverage_audit.py, which checks a structurally different, incompatible
# JSON schema (a `requirements[]` list with VERIFIED/WAIVED/NOT_APPLICABLE
# status) and never calls dv_harness/vplan_writer's real validate_items().
# So even when an agent correctly ran `dv-harness vplan-export` (the real,
# CLI-exposed, openpyxl-based vPlan writer -- see dv_harness/vplan_writer/
# writer.py and dv_harness/cli.py's `vplan-export` subcommand), the automatic
# engine-driven gate pipeline never exercised the "3 REQUIRED validation
# rules" .claude/agents/IP_UVM_DV_Gen.md's "The vPlan" section describes
# (every pattern name has a matching file, every task name is a real
# declaration, every pattern is in the run-time dispatcher).
#
# This gate closes that gap by calling the REAL vplan_writer.build_evidence_
# context()/validate_items() functions directly (same import-and-call pattern
# as tools/verification_flow/pattern_registry_completeness_gate.py) against
# real evidence on disk (pattern_dir glob, dispatcher_file text scan,
# task_declaration_sources glob+scan) -- not just JSON self-consistency, the
# same real-filesystem evidence discipline `dv-harness vplan-export` itself
# uses. It intentionally reuses vplan_writer's OWN VPlanItem field set and
# build_evidence_context()'s own kwarg names for this script's JSON payload
# shape (items/pattern_dir/pattern_glob/dispatcher_file/
# dispatcher_pattern_regex/task_declaration_sources/task_declaration_regex/
# known_check_names) -- these are not invented here, they mirror the already-
# established dv_harness.vplan_writer.build_evidence_context() signature and
# dv_harness/cli.py's `vplan-export` argparse flags exactly, so this gate adds
# no new schema/data-contract beyond what those two already define.
import argparse
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from dv_harness.vplan_writer import (  # noqa: E402
    build_evidence_context,
    validate_items,
    EvidenceSourceEmptyError,
    VPlanSchemaError,
    UnresolvedPatternFileError,
    UnknownTaskDeclarationError,
    PatternNotInDispatcherError,
    UnknownCheckerNameError,
)

_TYPED_ERRORS = (
    EvidenceSourceEmptyError, VPlanSchemaError, UnresolvedPatternFileError,
    UnknownTaskDeclarationError, PatternNotInDispatcherError, UnknownCheckerNameError,
)

# Only these two are required with no default in build_evidence_context()'s
# own signature -- every other evidence-context kwarg below is optional and,
# if absent from the payload, is simply not passed so build_evidence_context's
# own default applies (never re-hardcoded here, to avoid the two defaults
# drifting apart).
_REQUIRED_TOP_LEVEL = ("items", "pattern_dir", "dispatcher_file")

_OPTIONAL_EVIDENCE_KWARGS = (
    "pattern_glob", "dispatcher_pattern_regex", "task_declaration_regex",
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validates a vPlan item list against real pattern-dir/dispatcher-file/"
                     "task-declaration-source evidence by calling the real "
                     "dv_harness.vplan_writer.validate_items() -- the same function "
                     "`dv-harness vplan-export` itself calls before writing the .xlsx."
    )
    ap.add_argument("--vplan-validation", required=True,
                     help="Path to a JSON file: {items: [...VPlanItem dicts...], pattern_dir, "
                          "dispatcher_file, and any optional build_evidence_context kwargs}.")
    args = ap.parse_args()

    payload = json.loads(pathlib.Path(args.vplan_validation).read_text(encoding="utf-8"))

    missing = [k for k in _REQUIRED_TOP_LEVEL if not payload.get(k)]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_REQUIRED_FIELD", "missing": missing}))
        return 2

    items = payload["items"]
    if not isinstance(items, list):
        print(json.dumps({"status": "FAIL", "reason": "ITEMS_NOT_A_LIST", "value": items}))
        return 2

    evidence_kwargs = {
        "pattern_dir": payload["pattern_dir"],
        "dispatcher_file": payload["dispatcher_file"],
        "task_declaration_sources": payload.get("task_declaration_sources"),
    }
    for key in _OPTIONAL_EVIDENCE_KWARGS:
        if key in payload:
            evidence_kwargs[key] = payload[key]

    known_check_names = frozenset(payload["known_check_names"]) if payload.get("known_check_names") else None

    try:
        evidence = build_evidence_context(**evidence_kwargs)
        validate_items(items, evidence, known_check_names=known_check_names)
    except _TYPED_ERRORS as e:
        print(json.dumps({"status": "FAIL", "reason": e.reason, "detail": e.detail}))
        return 3

    print(json.dumps({"status": "PASS", "item_count": len(items)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
