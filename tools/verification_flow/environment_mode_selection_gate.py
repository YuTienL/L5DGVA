#!/usr/bin/env python3
# environment_mode_selection_gate (PROJECT_MODEL) -- added 2026-09-01
# (route-skill-resolver-dynamic-implementation task): closes the exact gap
# dv_harness/dashboard.py's _environment_mode_selected() docstring documents
# as its own "HONEST STATUS" (2026-08-31, poster-gap-closing-round2 finding
# C2): "no stage anywhere in this engine currently EMITS an
# environment_mode_selection block -- there is no STAGE_GATES entry
# requiring it, no prompts.py instruction telling any agent to produce it,
# and no engine writer generates it." PROJECT_MODEL is the stage this task's
# RULING picks for it: PROJECT_MODEL already establishes
# verification_boundary/topology (project_model_topology_completeness_gate,
# also in this stage's STAGE_GATES), the natural point to also decide
# SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE per CLAUDE.md's "Before CREATE
# ENVIRONMENT, select: SUBSYSTEM_MODE / SYSTEM_LEVEL_MODE" -- one stage
# earlier than PROTOCOL_CAPABILITY's per-protocol discovery.
#
# RULING (see .work/route-skill-resolver-dynamic-implementation-report.md
# for the full write-up): this gate independently RE-DERIVES the mode from
# requested_subsystems + the real registry (same "derive independently, then
# compare against the agent's declared value" discipline
# tools/real_env/execution_mode_validator.py already uses for
# PURE_LOCAL_READ_ANALYSIS vs REMOTE_EXECUTION_REQUIRED) rather than
# importing dv_harness.environment_mode_router directly. dv_harness's own
# in-process engine.py call (never subprocessed) is what actually exercises
# environment_mode_router.resolve_environment_mode() for real, with its own
# dedicated unit tests; a subprocess gate script that imported it via a
# parents[-N] sys.path trick (the convention a few older gates use, e.g.
# qualification_matrix_consistency_gate.py) would silently break the moment
# it's copied standalone into a temp test-fixture project that doesn't also
# carry a full dv_harness/ package copy alongside it -- self-contained is
# the more robust contract for a gate script than for engine.py.
#
# Deliberately single-flag (--state only), not a ContextFlag-carrying
# multi-flag gate: dashboard.py's _environment_mode_selected() reads
# payload.get("environment_mode") directly off the SAME
# `environment_mode_selection` evidence block with no sub-key nesting, so
# the agent-supplied JSON here must stay flat. The real subsystem registry
# is instead read directly, relative to THIS SCRIPT's own working directory
# -- gates.run_gate() always subprocess.run()s every gate script with
# cwd=str(root) (harness-controlled, never agent-attested), the exact same
# trust boundary a ContextFlag would give it, without needing one.
import argparse, json, pathlib, sys

VALID_MODES = {"SUBSYSTEM_MODE", "SYSTEM_LEVEL_MODE"}
REGISTRY_RELATIVE_PATH = pathlib.Path(".dv-harness") / "soc-composer" / "subsystem_environment_registry.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.state).read_text())

    declared_mode = d.get("environment_mode")
    if declared_mode not in VALID_MODES:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_ENVIRONMENT_MODE",
                           "declared_mode": declared_mode, "allowed": sorted(VALID_MODES)}))
        return 2

    requested = [str(s).strip().lower() for s in (d.get("requested_subsystems") or []) if str(s).strip()]
    if not requested:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_REQUESTED_SUBSYSTEMS"}))
        return 3

    # Real registered-subsystem names -- read relative to this process's own
    # cwd (== the real project root; see module header) rather than from any
    # agent-attested path, so an agent cannot spoof "already registered" to
    # skip a genuine SUBSYSTEM_MODE build. Missing/unreadable file == empty
    # registry, the same defensive default
    # environment_mode_router.read_registered_subsystem_names() uses.
    try:
        registry = json.loads(REGISTRY_RELATIVE_PATH.read_text(encoding="utf-8")) if REGISTRY_RELATIVE_PATH.exists() else {}
    except (OSError, ValueError):
        registry = {}
    registered = {str(s.get("name", "")).strip().lower()
                  for s in (registry.get("subsystems") or []) if isinstance(s, dict) and s.get("name")}

    # CLAUDE.md "Environment Generation Mode" / environment_mode_policy.json:
    # a single requested subsystem is a SUBSYSTEM_MODE build; two or more is
    # a SYSTEM_LEVEL_MODE composition. Same rule
    # dv_harness/environment_mode_router.py's resolve_environment_mode()
    # applies, re-derived here independently rather than imported (see
    # module header RULING above).
    derived_mode = "SUBSYSTEM_MODE" if len(requested) < 2 else "SYSTEM_LEVEL_MODE"

    if declared_mode != derived_mode:
        print(json.dumps({"status": "CONFLICT", "declared_mode": declared_mode,
                           "derived_mode": derived_mode, "requested_subsystems": requested}))
        return 4

    missing = sorted(s for s in requested if s not in registered)
    # CLAUDE.md: "If a required subsystem is missing in SYSTEM_LEVEL_MODE,
    # build it through SUBSYSTEM_MODE then return to composition" -- a
    # SYSTEM_LEVEL_MODE declaration with a real gap against the registry
    # must acknowledge that escalation, not silently proceed as if every
    # requested subsystem were already reusable.
    if derived_mode == "SYSTEM_LEVEL_MODE" and missing and not d.get("needs_subsystem_mode_first"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_SUBSYSTEM_MODE_ESCALATION_NOT_DECLARED",
                           "missing_subsystems": missing}))
        return 5

    print(json.dumps({"status": "PASS", "environment_mode": derived_mode, "missing_subsystems": missing}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
