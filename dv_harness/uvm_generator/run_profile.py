"""run_profile.json: the machine-readable IR of a generated UVM environment's
single authoritative execution surface (its Makefile, or an SoC-level
reference command.txt).

This module owns load/save/validate only. Extraction from a real Makefile
lives in makefile_to_run_profile.py; justfile generation from a profile
lives in run_profile_to_justfile.py. Keeping these three separate mirrors
the asset-processing distinction this schema exists to enforce: the
authoritative source, the normalized IR, and a generated execution surface
are three different things and must not be edited into each other.

Design rule this whole module exists to serve (per CLAUDE.md's "No
Golden-Reference Content Mining" and the project's broader "reference
command.txt/whole-chip-script is the sole execution authority" principle):
an agent must never compose a vcs/simv command line, or invent a plusarg,
from documentation or a paraphrase. It may only use params/targets present
in a run_profile.json that was itself mechanically extracted from a real
source file. A knob believed missing goes to a question queue -- it is
never silently added here by an agent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "run_profile.schema.json"
SCHEMA_VERSION = "1.0"


class RunProfileValidationError(ValueError):
    """A run_profile.json (or a dict about to become one) fails schema validation.

    Raised instead of returning False/None so a caller cannot accidentally
    proceed with an invalid profile -- the same fail-closed discipline as
    the engine's other evidence gates.
    """


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_run_profile(profile: dict) -> None:
    """Validate `profile` against run_profile.schema.json. Raises
    RunProfileValidationError on any violation; returns None on success.
    """
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise RunProfileValidationError(
            "jsonschema package is not installed; cannot validate run_profile.json. "
            "Install it rather than skipping validation."
        ) from exc

    validator_cls = jsonschema.Draft202012Validator
    schema = _load_schema()
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(profile), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise RunProfileValidationError(
            "run_profile.json failed schema validation:\n" + "\n".join(lines)
        )


def load_run_profile(path: Path) -> dict:
    """Load and validate a run_profile.json from disk. Raises
    RunProfileValidationError if the file is not schema-valid -- a caller
    (justfile generator, agent-facing query) must never consume an
    unvalidated profile.
    """
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_run_profile(profile)
    return profile


def save_run_profile(profile: dict, path: Path) -> None:
    """Validate then write `profile` to `path` as pretty-printed JSON."""
    validate_run_profile(profile)
    Path(path).write_text(json.dumps(profile, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_param(profile: dict, name: str) -> dict | None:
    """Look up one param by name across compile_time_params + runtime_params.
    Returns None if not present -- the caller (a justfile recipe's
    validator, or an agent-facing query) must treat that as "this knob does
    not exist in the authoritative source", never fall back to a guess.
    """
    for bucket in ("compile_time_params", "runtime_params"):
        for p in profile.get(bucket, []):
            if p["name"] == name:
                return p
    return None


def check_constraints(profile: dict, values: dict[str, str]) -> list[str]:
    """Check `values` (param name -> proposed string value) against every
    enum_membership constraint in the profile whose params are all present
    in `values`. Returns a list of violation messages (empty = all satisfied
    constraints that could be checked passed). Constraints referencing a
    param not present in `values` are skipped, not treated as violations --
    this function is a pre-flight guard for the params a caller is actually
    about to change, not a full-profile validator.

    Only enum_membership is checked here; mutual_requirement/forbidden_combination/
    retired constraints are surfaced as-is via list_constraints_for() for a
    human/agent to reason about, since their semantics vary too much to
    evaluate generically without re-implementing the source Makefile's own
    Make-language logic.
    """
    violations: list[str] = []
    for c in profile.get("constraints", []):
        if c["kind"] != "enum_membership":
            continue
        if not all(p in values for p in c["params"]):
            continue
        for p in c["params"]:
            param_def = find_param(profile, p)
            if param_def and param_def.get("type") == "enum":
                if values[p] not in param_def.get("enum", []):
                    violations.append(f"{p}={values[p]!r}: {c['message']}")
    return violations


def new_empty_profile(source_kind: str, source_path: str, target_ip: str, ip_prefix: str) -> dict:
    """Construct the minimal skeleton of a valid run_profile.json. Used by
    extractors as their starting point -- never hand-authored for a real
    environment, since every field must trace back to real source evidence.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"kind": source_kind, "path": source_path},
        "target": {"target_ip": target_ip, "ip_prefix": ip_prefix},
        "required_paths": [],
        "compile_time_params": [],
        "runtime_params": [],
        "defines": [],
        "compile_flags": {},
        "lsf": {},
        "pattern_registry": {},
        "constraints": [],
        "targets": [],
    }
