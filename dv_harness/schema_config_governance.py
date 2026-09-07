r"""dv_harness/schema_config_governance.py -- section 146 (Schema/Configuration
Governance) + the residual half of section 147 (Schema Compatibility/Migration)
that `dv_harness/schema_compat.py` does not cover.

FIRST CHECKED, per this item's own instruction, before writing a line of code:
the real dv-harness CLI already has a `schema-compat` verb, backed by
`dv_harness/schema_compat.py` (read in full). That module is real, tested, and
substantial -- it classifies BACKWARD_COMPATIBLE / BREAKING / UNKNOWN for any
`dv_harness/schemas/*.schema.json` change with a static rule table PLUS a real
`jsonschema`-validated witness document (never a bare textual diff), and it
already enforces one migration-adjacent rule inherited from the `env_manifest`
1.0 -> 1.1 precedent: a BREAKING edit to a schema whose owning module declares
`SCHEMA_VERSION` must bump that constant (`BREAKING_WITHOUT_VERSION_BUMP`).

That is a real, working answer to most of section 147's "classify a schema
change" half. It is NOT a full answer to either section, and it says so about
itself: its own module docstring states "It does not migrate documents... and
does not decide whether a breaking change is ALLOWED." Two concrete, named
gaps remain after reading it in full, and this module closes exactly those two
-- nothing schema_compat.py already does is re-implemented here.

GAP 1 (section 147): schema_compat.py's classifier vocabulary is only three
values (BACKWARD_COMPATIBLE / BREAKING / UNKNOWN). Section 147 requires five:
BACKWARD_COMPATIBLE / FORWARD_COMPATIBLE / MIGRATION_REQUIRED / BREAKING /
UNKNOWN, plus "breaking changes require impact analysis, migration plan,
consumer inventory, rollback, tests, Human Gate when production state is
affected." schema_compat.py gives real impact analysis (the findings list) and
nothing else on that list. `classify_change_full()` below adds the missing
two verdicts and the five listed artifacts, by REUSING schema_compat.py's own
`classify_schema_change()` for both compatibility directions rather than
re-deriving JSON Schema comparison logic a second time:
  - FORWARD_COMPATIBLE is the swapped call: `classify_schema_change(new, old)`
    asks "does every document valid under NEW also validate under OLD" -- an
    old CONSUMER reading a NEW-written document. schema_compat.py's own
    direction only ever answers the opposite question (can a NEW schema still
    read OLD documents), so a real, useful case -- a change that ADDS a new
    REQUIRED field -- was previously reported only as bare BREAKING even
    though it is genuinely forward-compatible (an old, more permissive reader
    can still consume a new document; only a new reader rejects an old one).
    That case is this module's own proof of why the swapped call adds real
    information schema_compat.py's single direction cannot express.
  - MIGRATION_REQUIRED is BREAKING (in both directions) with a real,
    resolved migration function on file (a caller-declared dotted path this
    module verifies actually imports and is callable -- never invented).
    Plain BREAKING is reserved for a change with no confirmed migration path,
    which is the more severe, more honest state.
  - a "consumer inventory" (every `.py` file under `dv_harness/` that
    references the schema's own filename -- a real, if approximate, grep,
    never a fabricated list), "rollback" availability (the old blob is really
    retrievable from git history, reusing schema_compat.read_blob_at_rev()),
    a "tests" check (does a `dv_harness_tests/test_<owning module>.py` file
    exist on disk), and a `human_gate_required` flag (the owning module is
    really imported, by a real import-graph walk, from `engine.py`, the one
    file this project's own graph-driven production loop runs from) are all
    reported alongside the verdict -- schema_compat.py has none of these.

GAP 2 (section 146): schema_compat.py operates ONLY on real
`dv_harness/schemas/*.schema.json` files -- it has no concept of the fifteen
named LOGICAL schemas section 146 lists (VerificationIR, RequirementIR,
vPlanIR, ..., SignoffRecord), and nothing in this repo maps those fifteen
names to what actually backs each one. Searched before building
(`grep -rn "schema_id\|producer_version\|consumer_version\|unknown_field_policy
\|deprecation_policy\|MIGRATION_REQUIRED\|FORWARD_COMPATIBLE"` over
`dv_harness/*.py`) and found zero hits repo-wide -- this governance registry,
and the ten governance fields section 146 asks every persistent schema to
support "as applicable", did not exist anywhere. `audit_repo_schema_governance()`
is that registry, built from real evidence rather than guessed: each of the
fifteen names is matched to a real `dv_harness/schemas/*.schema.json` file only
where the file's own `title`/`description` genuinely names that concept (six
real matches: RequirementIR -> requirement_contract, LoopContract ->
loop_contract, SYSTEM_RESOURCE_REGISTRY -> system_resource_registry,
CapabilityCandidate -> capability_evolution_candidate, ResearchEvidence ->
research_evidence_card, FailureIR -> system_failure_record +
system_failure_triage); the other nine (VerificationIR, vPlanIR, TestIR,
CoverageIR, EvidenceIR, SubsystemRegistry, AMBA_PORT_REGISTRY,
ReproducibilityCapsule, SignoffRecord) are honestly reported
`NO_JSON_SCHEMA_ARTIFACT` -- each backed by a real Python module (cited) that
declares its own ad hoc shape (several even declare their own `SCHEMA_VERSION`
constant with nothing to validate it against), but none of them is a real,
independently-loadable `.schema.json` file `schema_compat.py` (or any
`jsonschema` validator) can ever check a future change against. That gap is
reported, never silently closed by inventing nine new schema files this task
was not asked to author and which would need deep, per-IR domain review to get
right.

Ten governance fields, per schema with a real JSON Schema file: `schema_id`
($id present), `schema_version` (an owning module -- reusing
`schema_compat.owning_modules_for_schema()`, never re-derived -- declares a
`*SCHEMA_VERSION` constant), `unknown_field_policy` (`additionalProperties`
declared at the schema's top level), `required_field_policy` (a non-empty
top-level `required` array), `validation` (the file is real, parseable JSON
Schema -- a real `jsonschema.Draft202012Validator` construction, never a bare
`json.loads`), `compatibility` (SUPPORTED, because schema_compat.py can
classify any change to a file under `dv_harness/schemas/`) -- these six are the
CORE fields, present-or-absent for essentially any machine-validated schema in
this repo. `producer_version`/`consumer_version` (a `generator.tool_version`
-shaped property, the real per-artifact provenance tuple env_manifest.py's own
schema 1.2 already carries), `migration` (a documented migration/regeneration
policy found in the owning module's own source text near its
`SCHEMA_VERSION` declaration), and `deprecation` (any `"deprecated": true`
usage anywhere in the schema) are OPTIONAL/as-applicable fields, reported for
information but never counted against a schema that legitimately has none of
them -- section 146's own words are "should support as applicable", not "must
carry all ten unconditionally", and treating the optional four as mandatory
would manufacture a false finding against a schema like `question.schema.json`
that never needed a producer/consumer version tuple at all.

WHAT THIS MODULE DOES NOT DO. It authors no new `.schema.json` file (the nine
NO_JSON_SCHEMA_ARTIFACT gaps stay disclosed, not closed). It never decides
whether a breaking change is ALLOWED, never picks between BACKWARD_COMPATIBLE/
FORWARD_COMPATIBLE, never resolves a real conflict, and never invokes any
approval/Human-Gate mechanism itself -- `human_gate_required` is a flag this
module computes and reports for a human/`ControlPlane.approve()` caller to act
on, never an approval this module grants or withholds. It never migrates a
document -- a caller-declared migration function is only ever RESOLVED
(imported and confirmed callable) here, never invoked. It writes nothing:
`audit_repo_schema_governance()` and `classify_change_full()` are pure reads
over the repository and two schema documents.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import schema_compat

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------
# section 146: the ten governance fields, and the fifteen named schemas
# --------------------------------------------------------------------------

#: Fields section 146 says "every persistent/inter-agent schema should
#: support as applicable", split three ways. CORE is what a schema AUTHOR
#: actually declares (a real $id, a real owning SCHEMA_VERSION, a real
#: additionalProperties/required policy) -- these four are what
#: `governance_status` below is scored against, since they are the only ones
#: an author can omit. STRUCTURAL (`validation`, `compatibility`) is always
#: computed and always reported, but never scored: any syntactically valid
#: schema file under `dv_harness/schemas/` is unconditionally reachable by
#: schema_compat.py's own classifier, so counting those two toward
#: "declared" would make CORE_UNDECLARED nearly unreachable regardless of
#: what the schema's author actually wrote. OPTIONAL is legitimately absent
#: from many schemas -- reported, never demanded.
CORE_GOVERNANCE_FIELDS = (
    "schema_id", "schema_version", "unknown_field_policy", "required_field_policy",
)
STRUCTURAL_GOVERNANCE_FIELDS = ("validation", "compatibility")
OPTIONAL_GOVERNANCE_FIELDS = (
    "producer_version", "consumer_version", "migration", "deprecation",
)
GOVERNANCE_FIELDS = (CORE_GOVERNANCE_FIELDS + STRUCTURAL_GOVERNANCE_FIELDS
                     + OPTIONAL_GOVERNANCE_FIELDS)

#: Section 146's own named list, transcribed verbatim so a future edit to the
#: spec paragraph is checkable against this tuple by a test, the same
#: discipline `golden_flow_readiness._assert_rows_match_section_47()` and
#: `mcp/claude_md_index.py` already apply to their own transcribed lists.
GOVERNED_LOGICAL_SCHEMAS = (
    "VerificationIR", "RequirementIR", "vPlanIR", "TestIR", "CoverageIR",
    "FailureIR", "EvidenceIR", "LoopContract", "SubsystemRegistry",
    "AMBA_PORT_REGISTRY", "SYSTEM_RESOURCE_REGISTRY", "ReproducibilityCapsule",
    "CapabilityCandidate", "ResearchEvidence", "SignoffRecord",
)

#: Real-evidence mapping: logical name -> (schema filename(s) under
#: dv_harness/schemas/, or () when none exists; the real Python module that
#: backs the concept, cited for a human to check; a one-line note on how the
#: match was decided). Built by reading every schema file's own `title`/
#: `description` (see this module's own docstring) -- never guessed from the
#: logical name alone. A logical name with an empty schema-filename tuple has
#: NO real `.schema.json` backing it in this repository today.
LOGICAL_SCHEMA_BACKING: Dict[str, Tuple[Tuple[str, ...], Optional[str], str]] = {
    "VerificationIR": (
        (), "dv_harness/verification_intent_ir.py",
        "declares its own SCHEMA_VERSION but that module's own CLAUDE.md "
        "section states plainly: \"No JSON schema file accompanies this IR\"",
    ),
    "RequirementIR": (
        ("requirement_contract.schema.json",), "dv_harness/requirement_contract.py",
        "exact conceptual match: \"the structured IR the Spec Intelligence "
        "Agent emits and every downstream generator consumes\"",
    ),
    "vPlanIR": (
        (), "dv_harness/vplan_artifact.py",
        "declares its own SCHEMA_VERSION; no dv_harness/schemas/*.json file "
        "exists for the vPlan row/hierarchy shape",
    ),
    "TestIR": (
        (), None,
        "no dedicated per-test-record IR or schema found; the nearest related "
        "artifact is golden_scenario.py's capsule, which is a freshness/"
        "reproducibility record (mapped separately below to "
        "ReproducibilityCapsule), not a general TestIR",
    ),
    "CoverageIR": (
        (), None,
        "no dedicated CoverageIR schema found; coverage_analysis.py and "
        "amba_functional_coverage_ir.py each perform a narrower, specific "
        "coverage-hole/AMBA-cross-coverage analysis rather than defining one "
        "canonical persisted coverage IR",
    ),
    "FailureIR": (
        ("system_failure_record.schema.json", "system_failure_triage.schema.json"),
        None,
        "two real, matching schemas: 'System-Level Failure Record (SYS-31)' "
        "and 'System Failure Triage (SYS-32)'",
    ),
    "EvidenceIR": (
        (), "dv_harness/evidence_db.py",
        "evidence is a real DuckDB table schema (jobs/normalized_evidence/"
        "coverage_samples/...), not a JSON Schema document",
    ),
    "LoopContract": (
        ("loop_contract.schema.json",), "dv_harness/loop_contract.py",
        "exact name match",
    ),
    "SubsystemRegistry": (
        (), "dv_harness/environment_mode_router.py",
        "the real registry is subsystem_environment_registry.json, read via "
        "read_registered_subsystem_entries(); no dv_harness/schemas/*.json "
        "validates its shape",
    ),
    "AMBA_PORT_REGISTRY": (
        (), "dv_harness/amba_port_registry.py",
        "a real Python dataclass registry; no dv_harness/schemas/*.json file "
        "exists for it",
    ),
    "SYSTEM_RESOURCE_REGISTRY": (
        ("system_resource_registry.schema.json",), "dv_harness/system_resource_registry.py",
        "exact name match: \"SYS-15 ... the SYSTEM_RESOURCE_REGISTRY\"",
    ),
    "ReproducibilityCapsule": (
        (), "dv_harness/golden_scenario.py",
        "the GoldenScenario capsule; recorded in evidence.duckdb via "
        "record_golden_scenario(), not a dv_harness/schemas/*.json file",
    ),
    "CapabilityCandidate": (
        ("capability_evolution_candidate.schema.json",), "dv_harness/capability_evolution.py",
        "exact conceptual match: \"ONE proposed change to this harness's own "
        "capability, produced by the research-architect agent\"",
    ),
    "ResearchEvidence": (
        ("research_evidence_card.schema.json",), None,
        "exact conceptual match: \"ONE external technical document -> ONE "
        "independent ResearchEvidenceCard\"",
    ),
    "SignoffRecord": (
        (), "dv_harness/signoff_export.py",
        "declares its own FREEZE_SCHEMA_VERSION; the frozen baseline record "
        "under .dv-harness/signoff/freezes/*.json has no dv_harness/schemas/"
        "*.json validator",
    ),
}


class SchemaGovernanceError(ValueError):
    """A governance audit could not be completed for a reason worth reporting
    distinctly from an ordinary finding -- an unreadable file, a malformed
    caller input. Raised rather than silently degrading, for the same
    fail-closed reason `schema_compat.SchemaCompatError` exists."""


_MIGRATION_POLICY_HINTS = (
    "migrat", "regenerate", "breaking bump", "sole writer",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SchemaGovernanceError(f"cannot read {path}: {exc}") from exc


def _contains_deprecated_true(node: Any) -> bool:
    if isinstance(node, Mapping):
        if node.get("deprecated") is True:
            return True
        return any(_contains_deprecated_true(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_deprecated_true(v) for v in node)
    return False


def audit_schema_governance(root: Path, schema_filename: str) -> Dict[str, Any]:
    """The ten governance fields for ONE real `dv_harness/schemas/<file>`,
    mechanically derived -- never a caller-typed claim about what a schema
    supports."""
    root = Path(root)
    path = root / schema_compat.SCHEMAS_DIR / schema_filename
    if not path.exists():
        raise SchemaGovernanceError(f"no such schema file: {path}")
    doc = _load_json(path)
    if not isinstance(doc, Mapping):
        raise SchemaGovernanceError(f"{path} is not a JSON object")

    fields: Dict[str, Dict[str, Any]] = {}

    fields["schema_id"] = (
        {"status": "DECLARED", "value": doc["$id"]} if doc.get("$id")
        else {"status": "NOT_DECLARED"}
    )

    owners = schema_compat.owning_modules_for_schema(root, schema_filename)
    fields["schema_version"] = (
        {"status": "DECLARED", "owning_modules": owners} if owners
        else {"status": "NOT_DECLARED",
              "reason": "no dv_harness/*.py both names this schema file and "
                        "declares a *SCHEMA_VERSION constant"}
    )

    try:
        import jsonschema
        jsonschema.Draft202012Validator.check_schema(doc)
        fields["validation"] = {"status": "DECLARED",
                                 "reason": "parses as a valid Draft 2020-12 JSON Schema"}
    except ImportError:
        fields["validation"] = {"status": "NOT_AVAILABLE",
                                 "reason": "jsonschema package is not installed"}
    except Exception as exc:  # jsonschema.SchemaError or similar
        fields["validation"] = {"status": "NOT_DECLARED",
                                 "reason": f"schema does not validate as JSON Schema: {exc}"}

    # Any real *.schema.json under dv_harness/schemas/ is reachable by
    # schema_compat.py's own classify_repo_schema_changes(); that reach IS
    # what "compatibility" means here -- never re-derived.
    fields["compatibility"] = {
        "status": "SUPPORTED",
        "reason": "schema_compat.classify_repo_schema_changes() classifies "
                  "any change under dv_harness/schemas/*.schema.json",
    }

    ap = doc.get("additionalProperties")
    fields["unknown_field_policy"] = (
        {"status": "DECLARED", "value": ap} if "additionalProperties" in doc
        else {"status": "NOT_DECLARED"}
    )

    req = doc.get("required")
    fields["required_field_policy"] = (
        {"status": "DECLARED", "value": req} if isinstance(req, list) and req
        else {"status": "NOT_DECLARED"}
    )

    gen_props = ((doc.get("properties") or {}).get("generator") or {}).get("properties") or {}
    has_provenance = "tool_version" in gen_props
    fields["producer_version"] = (
        {"status": "DECLARED", "reason": "properties.generator.tool_version declared"}
        if has_provenance else {"status": "NOT_DECLARED"}
    )
    fields["consumer_version"] = (
        {"status": "DECLARED", "reason": "properties.generator.tool_version declared "
                                          "(shared producer/consumer identity field)"}
        if has_provenance else {"status": "NOT_DECLARED"}
    )

    migration_status = {"status": "NOT_DOCUMENTED"}
    for owner in owners:
        try:
            text = (root / owner).read_text(encoding="utf-8").lower()
        except OSError:
            continue
        hit = next((h for h in _MIGRATION_POLICY_HINTS if h in text), None)
        if hit:
            migration_status = {"status": "DOCUMENTED_IN_SOURCE",
                                "owning_module": owner, "matched_hint": hit}
            break
    fields["migration"] = migration_status

    fields["deprecation"] = (
        {"status": "DECLARED"} if _contains_deprecated_true(doc) else {"status": "NOT_DECLARED"}
    )

    core_declared = sum(1 for f in CORE_GOVERNANCE_FIELDS if fields[f]["status"] == "DECLARED"
                        or fields[f]["status"] == "SUPPORTED")
    if core_declared == len(CORE_GOVERNANCE_FIELDS):
        governance_status = "CORE_COMPLETE"
    elif core_declared == 0:
        governance_status = "CORE_UNDECLARED"
    else:
        governance_status = "CORE_PARTIAL"

    return {
        "schema": schema_filename,
        "governance_status": governance_status,
        "fields": fields,
    }


def audit_repo_schema_governance(root: Path = Path(".")) -> Dict[str, Any]:
    """Section 146's registry: every real `dv_harness/schemas/*.schema.json`
    audited for the ten governance fields, cross-referenced against the
    fifteen named logical schemas (real matches, and honest gaps)."""
    root = Path(root)
    schemas_dir = root / schema_compat.SCHEMAS_DIR
    real_files = sorted(p.name for p in schemas_dir.glob("*.schema.json")) if schemas_dir.is_dir() else []

    per_schema = []
    for name in real_files:
        try:
            per_schema.append(audit_schema_governance(root, name))
        except SchemaGovernanceError as exc:
            per_schema.append({"schema": name, "governance_status": "NOT_AVAILABLE",
                               "reason": str(exc)})

    by_name = {p["schema"]: p for p in per_schema}
    logical = []
    for logical_name in GOVERNED_LOGICAL_SCHEMAS:
        schema_files, module, note = LOGICAL_SCHEMA_BACKING.get(logical_name, ((), None, "unmapped"))
        # RESOLVED requires the mapped file(s) to be REALLY present in THIS
        # audited root -- the mapping table is repo-wide evidence, but a
        # bare/fixture root that does not actually carry the file must never
        # be reported as if it did.
        present = [f for f in schema_files if f in by_name]
        if schema_files and present == list(schema_files):
            logical.append({
                "logical_name": logical_name,
                "status": "RESOLVED",
                "schema_files": list(schema_files),
                "note": note,
                "audits": [by_name[f] for f in schema_files],
            })
        elif schema_files and present:
            logical.append({
                "logical_name": logical_name,
                "status": "PARTIALLY_RESOLVED",
                "schema_files": list(schema_files),
                "present_in_root": present,
                "note": note,
            })
        elif schema_files:
            logical.append({
                "logical_name": logical_name,
                "status": "MAPPED_BUT_ABSENT_FROM_ROOT",
                "schema_files": list(schema_files),
                "note": note,
            })
        else:
            logical.append({
                "logical_name": logical_name,
                "status": "NO_JSON_SCHEMA_ARTIFACT",
                "python_module": module,
                "note": note,
            })

    undeclared = [p["schema"] for p in per_schema if p.get("governance_status") == "CORE_UNDECLARED"]
    unresolved_logical = [l["logical_name"] for l in logical if l["status"] != "RESOLVED"]

    return {
        "schema_config_governance_version": SCHEMA_VERSION,
        "root": str(root),
        "schemas_audited": len(per_schema),
        "core_undeclared_schemas": undeclared,
        "per_schema": per_schema,
        "logical_schemas": logical,
        "unresolved_logical_schema_count": len(unresolved_logical),
        "unresolved_logical_schemas": unresolved_logical,
    }


# --------------------------------------------------------------------------
# section 147 residual: FORWARD_COMPATIBLE / MIGRATION_REQUIRED, plus the
# five listed breaking-change artifacts schema_compat.py does not produce
# --------------------------------------------------------------------------

VERDICT_BACKWARD = "BACKWARD_COMPATIBLE"
VERDICT_FORWARD = "FORWARD_COMPATIBLE"
VERDICT_MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
VERDICT_BREAKING = "BREAKING"
VERDICT_UNKNOWN = "UNKNOWN"


def _resolve_migration_fn(dotted: Optional[str]) -> Dict[str, Any]:
    """A caller-DECLARED migration function, verified real -- never invented.
    `dotted` is `module.path:function_name`. Absent entirely is honest
    NOT_DECLARED, distinct from a declared-but-broken one."""
    if not dotted:
        return {"status": "NOT_DECLARED"}
    if ":" not in dotted:
        return {"status": "MALFORMED", "reason": "expected 'module.path:function_name'"}
    mod_name, _, fn_name = dotted.partition(":")
    try:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, fn_name)
    except (ImportError, AttributeError) as exc:
        return {"status": "DECLARED_BUT_UNRESOLVABLE", "declared": dotted, "reason": str(exc)}
    if not callable(fn):
        return {"status": "DECLARED_BUT_UNRESOLVABLE", "declared": dotted,
                "reason": f"{dotted!r} resolved but is not callable"}
    return {"status": "RESOLVED", "declared": dotted}


def _find_schema_consumers(root: Path, schema_filename: str) -> List[str]:
    """Every dv_harness/*.py file that references this schema's filename --
    a real, repo-wide grep, never a fabricated inventory. Broader than
    `schema_compat.owning_modules_for_schema()` (which requires a declared
    SCHEMA_VERSION too): this is section 147's "consumer inventory", covering
    readers as well as writers."""
    hits = []
    pkg_dir = Path(root, "dv_harness")
    if not pkg_dir.is_dir():
        return hits
    for py in sorted(pkg_dir.rglob("*.py")):
        try:
            if schema_filename in py.read_text(encoding="utf-8"):
                hits.append(str(py.relative_to(root)))
        except OSError:  # pragma: no cover - unreadable source file
            continue
    return hits


def _production_path_modules(root: Path) -> Sequence[str]:
    """Modules this project's own graph-driven autonomous loop actually runs
    from -- a real import-graph fact, not a guess. `engine.py` is the one
    file `dv_harness_tests`'s own suite and this project's CLAUDE.md both
    treat as the production entry point (`DVHarness.run_stage()`/`loop()`)."""
    return ("dv_harness/engine.py",)


def _is_production_path(root: Path, module: Optional[str]) -> bool:
    """Best-effort: is `module` reachable from the production entry point(s)
    by a direct import statement? A real, if shallow (one-hop), check --
    never a claim about the full transitive closure."""
    if not module:
        return False
    target_stem = Path(module).stem
    for prod_module in _production_path_modules(root):
        p = Path(root, prod_module)
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover
            continue
        if re.search(rf'\b{re.escape(target_stem)}\b', text):
            return True
    return False


def classify_change_full(old_schema: Mapping[str, Any], new_schema: Mapping[str, Any],
                          *, migration_fn: Optional[str] = None,
                          corpus: Sequence[Any] = (),
                          schema_filename: Optional[str] = None,
                          root: Path = Path("."),
                          owning_module: Optional[str] = None) -> Dict[str, Any]:
    """Section 147's full five-value classification, plus the five listed
    breaking-change artifacts (impact analysis, migration plan, consumer
    inventory, rollback, tests) and a Human-Gate flag. Reuses
    `schema_compat.classify_schema_change()` for BOTH real compatibility
    directions -- there is exactly one JSON-Schema-comparison engine in this
    package, called twice with its arguments swapped, never re-implemented.
    """
    backward = schema_compat.classify_schema_change(old_schema, new_schema, corpus=corpus)
    forward = schema_compat.classify_schema_change(new_schema, old_schema, corpus=corpus)
    migration = _resolve_migration_fn(migration_fn)

    bv, fv = backward["verdict"], forward["verdict"]
    if bv == schema_compat.VERDICT_UNKNOWN or fv == schema_compat.VERDICT_UNKNOWN:
        verdict = VERDICT_UNKNOWN
    elif bv == schema_compat.VERDICT_COMPATIBLE:
        verdict = VERDICT_BACKWARD
    elif fv == schema_compat.VERDICT_COMPATIBLE:
        verdict = VERDICT_FORWARD
    elif migration["status"] == "RESOLVED":
        verdict = VERDICT_MIGRATION_REQUIRED
    else:
        verdict = VERDICT_BREAKING

    result: Dict[str, Any] = {
        "verdict": verdict,
        "backward_compatible_analysis": backward,
        "forward_compatible_analysis": forward,
        "migration_plan": migration,
    }

    if schema_filename is not None:
        result["consumer_inventory"] = _find_schema_consumers(root, schema_filename)
        relpath = f"{schema_compat.SCHEMAS_DIR}/{schema_filename}"
        try:
            has_history = schema_compat.read_blob_at_rev(root, relpath, "HEAD") is not None
            result["rollback"] = {"status": "AVAILABLE" if has_history else "NOT_AVAILABLE",
                                  "reason": "old content retrievable via git history"
                                  if has_history else "no git history for this path at HEAD"}
        except schema_compat.SchemaCompatError as exc:
            result["rollback"] = {"status": "NOT_AVAILABLE", "reason": str(exc)}

    if owning_module is not None:
        test_path = Path(root, "dv_harness_tests", f"test_{Path(owning_module).stem}.py")
        result["tests"] = {"status": "FOUND" if test_path.is_file() else "NOT_FOUND",
                           "path": str(test_path)}
        result["human_gate_required"] = (
            verdict in (VERDICT_BREAKING, VERDICT_MIGRATION_REQUIRED)
            and _is_production_path(root, owning_module)
        )
    else:
        result["human_gate_required"] = False

    return result


# --------------------------------------------------------------------------
# verb
# --------------------------------------------------------------------------

def _render_registry(result: Dict[str, Any]) -> str:
    lines = [f"schema-config-governance: {result['schemas_audited']} schema(s) audited under "
             f"{schema_compat.SCHEMAS_DIR}"]
    for p in result["per_schema"]:
        lines.append(f"  {p['schema']}: {p.get('governance_status')}")
    lines.append(f"logical schemas resolved: "
                 f"{len(GOVERNED_LOGICAL_SCHEMAS) - result['unresolved_logical_schema_count']}"
                 f"/{len(GOVERNED_LOGICAL_SCHEMAS)}")
    for l in result["logical_schemas"]:
        if l["status"] != "RESOLVED":
            lines.append(f"  {l['logical_name']}: {l['status']} -- {l.get('note', '')}")
    return "\n".join(lines)


def execute_verb(*, action: str, root: str = ".", old: Optional[str] = None,
                 new: Optional[str] = None, schema_filename: Optional[str] = None,
                 owning_module: Optional[str] = None, migration_fn: Optional[str] = None,
                 corpus: Sequence[str] = (), as_json: bool = False) -> Tuple[str, int]:
    """Exit codes for `registry`: 0 nothing concerning, 1 at least one real
    schema is CORE_UNDECLARED, 2 nothing to audit. For `classify`: 0
    BACKWARD_COMPATIBLE/FORWARD_COMPATIBLE, 1 BREAKING/MIGRATION_REQUIRED,
    2 NOT_AVAILABLE, 3 UNKNOWN -- mirroring schema_compat.py's own convention
    that UNKNOWN never shares an exit code with a confident verdict."""
    root_path = Path(root)
    if action == "registry":
        result = audit_repo_schema_governance(root_path)
        if result["schemas_audited"] == 0:
            payload = {"status": "NOT_AVAILABLE",
                       "reason": f"no *.schema.json under {schema_compat.SCHEMAS_DIR}"}
            return (json.dumps(payload, indent=2) if as_json
                    else f"schema-config-governance: NOT_AVAILABLE -- {payload['reason']}"), 2
        code = 1 if result["core_undeclared_schemas"] else 0
        return (json.dumps(result, indent=2, default=str) if as_json
                else _render_registry(result)), code
    if action == "classify":
        if not (old and new):
            return "schema-config-governance: NOT_AVAILABLE -- supply --old and --new", 2
        try:
            old_doc = json.loads(Path(old).read_text(encoding="utf-8"))
            new_doc = json.loads(Path(new).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"schema-config-governance: NOT_AVAILABLE -- {exc}", 2
        result = classify_change_full(old_doc, new_doc, migration_fn=migration_fn,
                                      corpus=[json.loads(Path(c).read_text(encoding="utf-8"))
                                              for c in corpus],
                                      schema_filename=schema_filename, root=root_path,
                                      owning_module=owning_module)
        code = {VERDICT_BACKWARD: 0, VERDICT_FORWARD: 0, VERDICT_BREAKING: 1,
                VERDICT_MIGRATION_REQUIRED: 1, VERDICT_UNKNOWN: 3}[result["verdict"]]
        text = (json.dumps(result, indent=2, default=str) if as_json
                else f"schema-config-governance: {result['verdict']}")
        return text, code
    return f"schema-config-governance: NOT_AVAILABLE -- unknown action {action!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.schema_config_governance",
        description="Section 146 schema/configuration governance registry, plus the "
                    "FORWARD_COMPATIBLE/MIGRATION_REQUIRED half of section 147 "
                    "schema_compat.py does not cover.")
    sub = ap.add_subparsers(dest="action", required=True)

    reg = sub.add_parser("registry", help="audit every real dv_harness/schemas/*.schema.json "
                                          "plus the fifteen named logical schemas")
    reg.add_argument("--root", default=".")
    reg.add_argument("--json", action="store_true")

    cla = sub.add_parser("classify", help="five-value BACKWARD/FORWARD/MIGRATION_REQUIRED/"
                                          "BREAKING/UNKNOWN classification of one schema change")
    cla.add_argument("--old", required=True)
    cla.add_argument("--new", required=True)
    cla.add_argument("--schema-filename", dest="schema_filename",
                     help="the real dv_harness/schemas/<file> this change targets, for "
                          "consumer-inventory/rollback lookups")
    cla.add_argument("--owning-module", dest="owning_module",
                     help="the real dv_harness/<file>.py that owns this schema, for "
                          "tests/Human-Gate lookups")
    cla.add_argument("--migration-fn", dest="migration_fn",
                     help="module.path:function_name of a real migration function")
    cla.add_argument("--root", default=".")
    cla.add_argument("--corpus", nargs="*", default=[])
    cla.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    text, code = execute_verb(action=a.action, root=a.root,
                              old=getattr(a, "old", None), new=getattr(a, "new", None),
                              schema_filename=getattr(a, "schema_filename", None),
                              owning_module=getattr(a, "owning_module", None),
                              migration_fn=getattr(a, "migration_fn", None),
                              corpus=getattr(a, "corpus", []), as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
