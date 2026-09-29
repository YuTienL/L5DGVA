#!/usr/bin/env python3
"""de_local_sim_env_intake_gate.py -- INTAKE-stage evidence gate for a
pre-existing DE-local simulation environment (the local Design-Engineer
compile script, run script, filelist and environment-setup script a project
may already have BEFORE the harness gets involved).

GAP THIS CLOSES (2026-09-01, de-local-sim-env-intake design pass): an audit
found this intake had ZERO schema or code backing anywhere in the codebase --
DE_BASELINE_REPRODUCTION's own de_baseline_reproduction_gate.py validates
HASHES of a de_local_sim_path/build recipe (that a baseline was *reproduced*
identically) but never that the four underlying DE-local artifacts
(compile/run/filelist/env-setup scripts) are real files that were actually
confirmed to exist/work in the first place. This script is that missing
intake-time check.

Evidence schema (documented in dv_harness/prompts.py's INTAKE stage
instructions): a "de_local_sim_env_intake" object with exactly four fields --
compile_script_path, run_script_path, filelist_path, env_setup_script_path --
each an object {"path": "<real file path>", "evidence": "<how it was
confirmed to exist/work>"}, mirroring the "evidence" per-item note convention
already used across this repo's other evidence schemas (e.g.
experience_knowledge_gate.py, protocol_builder_registry_conformance_gate.py)
and the mandatory non-empty "evidence" string field convention from
dv_harness/uvm_generator/generator.py's house DSL style.

RULING: OPTIONAL/non-blocking by design -- a project genuinely may have no
pre-existing DE-local environment, and this gate must never force one on it.
dv_harness/gates.py's evidence engine (_evaluate_stage_evidence_core) treats
a gate whose fenced ```dv-harness-evidence:<gate_id>``` block is entirely
missing from the agent's reply as an unconditional per-gate failure ("no
evidence block supplied") -- there is no existing per-gate "skip this one if
absent" switch, and adding one would be a much larger, cross-cutting change
to every stage's gate list rather than a minimal, additive fix scoped to
this gap. So prompts.py instructs the agent to ALWAYS emit this fenced
block, using an EMPTY JSON object ("{}") when no DE-local environment
exists. This script is what makes that concession genuinely safe: a payload
that is not a dict, or carries none of the four fields, is treated as
"the evidence block is entirely absent" in the schema sense and PASSes as a
no-op (DE_LOCAL_SIM_ENV: NOT_APPLICABLE) with zero field enforcement. The
moment ANY of the four fields is populated, the block counts as "present"
and every one of the four fields is required and checked for real, on-disk
existence and non-emptiness -- partial evidence is never accepted as if the
whole block were absent.
"""
import argparse, json, pathlib, sys

REQUIRED_FIELDS = ("compile_script_path", "run_script_path", "filelist_path", "env_setup_script_path")

# One exit code per FAIL *kind* (not per field) -- same convention as
# server_sync_identity_gate.py's distinct exit codes per distinct reason.
_EXIT_CODE_BY_KIND = {
    "FIELD_MISSING": 2,
    "PATH_MISSING": 3,
    "EVIDENCE_MISSING": 4,
    "PATH_NOT_FOUND": 5,
    "PATH_NOT_A_FILE": 6,
    "PATH_FILE_EMPTY": 7,
}


def _check_field(field: str, entry):
    """Returns None if `entry` is a valid {"path", "evidence"} object whose
    path is a real, non-empty file on disk; otherwise a (kind, detail) pair
    identifying exactly which check failed, for a typed per-field reason."""
    if not isinstance(entry, dict):
        return "FIELD_MISSING", {}
    path = entry.get("path")
    if not path or not isinstance(path, str) or not path.strip():
        return "PATH_MISSING", {}
    evidence = entry.get("evidence")
    if not evidence or not isinstance(evidence, str) or not evidence.strip():
        return "EVIDENCE_MISSING", {"path": path}
    p = pathlib.Path(path)
    try:
        exists = p.is_file()
    except OSError:
        exists = False
    if not exists:
        if p.exists():
            return "PATH_NOT_A_FILE", {"path": path}
        return "PATH_NOT_FOUND", {"path": path}
    try:
        size = p.stat().st_size
    except OSError:
        return "PATH_NOT_FOUND", {"path": path}
    if size == 0:
        return "PATH_FILE_EMPTY", {"path": path}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.intake).read_text(encoding="utf-8"))

    if not isinstance(d, dict) or not any(d.get(f) for f in REQUIRED_FIELDS):
        # No-op PASS: evidence block carries none of the four fields --
        # this project has no pre-existing DE-local simulation environment
        # to intake, and that is a legitimate, unenforced state.
        print(json.dumps({"status": "PASS", "de_local_sim_env": "NOT_APPLICABLE"}))
        return 0

    for field in REQUIRED_FIELDS:
        result = _check_field(field, d.get(field))
        if result is not None:
            kind, detail = result
            payload = {"status": "FAIL", "reason": f"{field.upper()}_{kind}", "field": field}
            payload.update(detail)
            print(json.dumps(payload))
            return _EXIT_CODE_BY_KIND[kind]

    print(json.dumps({"status": "PASS", "de_local_sim_env": "CONFIRMED",
                       "fields_confirmed": list(REQUIRED_FIELDS)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
