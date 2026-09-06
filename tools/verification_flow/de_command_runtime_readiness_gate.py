#!/usr/bin/env python3
"""de_command_runtime_readiness_gate.py -- STAGE_GATES subprocess wrapper for
dv_harness.de_command_runtime_readiness_gate's composite DE_COMMAND_RUNTIME_READY
verdict.

The evidence block this script reads (one JSON file, via --runtime-readiness)
carries three sub-shapes, all owned by their real real modules -- this script
parses none of them itself:
  {
    "registry": { ... runtime_event_registry.registry_from_dict() shape ... },
    "commands": { "commands": [ ... ] }  (command_precondition_gate.commands_from_dict()
                                           shape -- a bare list is also accepted),
    "branch_grammar_results": [ ... ] or { ... } or omitted
  }

`commands` and `branch_grammar_results` are both optional: a pattern with no
declared commands yet, or no branch/grammar-side batch result yet (that
sibling batch may not have finished), still gets a real verdict over whatever
WAS supplied -- never a refusal to run.

Exit codes: 0 PASS, 1 BLOCKED (a real, named blocker), 2 DEPENDENCY_UNAVAILABLE
(the real dv_harness engine package could not be imported), 3 MALFORMED_PAYLOAD
/ MISSING_REGISTRY, 4 REGISTRY_DECLARATION_ERROR, 5 COMMAND_DECLARATION_ERROR,
6 BRANCH_GRAMMAR_DECLARATION_ERROR.
"""
import argparse
import json
import os
import pathlib
import sys

# Prefer the real dv_harness package location run_gate() already knows and
# passes via env (see dv_harness/gates.py); the parents[2] guess only holds in
# this repo's own dogfooding layout. Same idiom as waiver_revalidation_gate.py.
_pkg_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
sys.path.insert(0, str(pathlib.Path(_pkg_root) if _pkg_root else pathlib.Path(__file__).resolve().parents[2]))

_IMPORT_ERROR = None
try:
    from dv_harness import de_command_runtime_readiness_gate as _gate_mod
    from dv_harness.runtime_event_registry import EventRegistryError, registry_from_dict
    from dv_harness.command_precondition_gate import CommandPreconditionGateError, commands_from_dict
except Exception as e:  # pragma: no cover - broken/partial deployment
    _gate_mod = None
    _IMPORT_ERROR = str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-readiness", required=True)
    a = ap.parse_args()

    if _gate_mod is None:
        print(json.dumps({"status": "FAIL", "reason": "DEPENDENCY_UNAVAILABLE", "detail": _IMPORT_ERROR}))
        return 2

    try:
        payload = json.loads(pathlib.Path(a.runtime_readiness).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"status": "FAIL", "reason": "MALFORMED_PAYLOAD", "detail": str(e)}))
        return 3

    if not isinstance(payload, dict) or "registry" not in payload:
        print(json.dumps({
            "status": "FAIL", "reason": "MISSING_REGISTRY",
            "detail": "the evidence block must carry a 'registry' object "
                      "(runtime_event_registry.registry_from_dict shape)",
        }))
        return 3

    try:
        registry = registry_from_dict(payload["registry"])
    except EventRegistryError as e:
        print(json.dumps({"status": "FAIL", "reason": "REGISTRY_DECLARATION_ERROR", "detail": str(e)}))
        return 4

    commands_raw = payload.get("commands")
    commands = ()
    if commands_raw:
        if isinstance(commands_raw, list):
            commands_raw = {"commands": commands_raw}
        try:
            commands = commands_from_dict(commands_raw)
        except CommandPreconditionGateError as e:
            print(json.dumps({"status": "FAIL", "reason": "COMMAND_DECLARATION_ERROR", "detail": str(e)}))
            return 5

    branch_grammar_results = payload.get("branch_grammar_results")
    try:
        report = _gate_mod.evaluate_de_command_runtime_readiness(registry, commands, branch_grammar_results)
    except _gate_mod.DECommandRuntimeReadinessError as e:
        print(json.dumps({"status": "FAIL", "reason": "BRANCH_GRAMMAR_DECLARATION_ERROR", "detail": str(e)}))
        return 6

    detail = report.to_dict()
    detail["status"] = "PASS" if report.status == _gate_mod.DE_COMMAND_RUNTIME_PASS else "FAIL"
    print(json.dumps(detail))
    return 0 if report.status == _gate_mod.DE_COMMAND_RUNTIME_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
