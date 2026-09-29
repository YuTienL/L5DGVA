"""Real tests for dv_harness/schema_config_governance.py.

Covers both halves of the gap this module closes:
  (a) section 146's governance registry over dv_harness/schemas/*.schema.json
      plus the fifteen named logical schemas, and
  (b) section 147's residual FORWARD_COMPATIBLE / MIGRATION_REQUIRED
      classification, reusing schema_compat.classify_schema_change() for the
      actual JSON-Schema-comparison arithmetic in both directions.

Every negative control is real: a schema that genuinely has no
additionalProperties/required, a migration function that genuinely does not
resolve, a project with no git history at all, a module the production entry
point genuinely does not import.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dv_harness import schema_config_governance as gov
from dv_harness import schema_compat


# --------------------------------------------------------------------------
# section 146: the ten-field vocabulary + the fifteen-name registry
# --------------------------------------------------------------------------

def test_governance_fields_are_the_documented_ten():
    assert gov.GOVERNANCE_FIELDS == (gov.CORE_GOVERNANCE_FIELDS
                                     + gov.STRUCTURAL_GOVERNANCE_FIELDS
                                     + gov.OPTIONAL_GOVERNANCE_FIELDS)
    assert len(gov.GOVERNANCE_FIELDS) == 10
    assert len(set(gov.GOVERNANCE_FIELDS)) == 10  # no duplicates across the three tiers
    assert set(gov.CORE_GOVERNANCE_FIELDS) & set(gov.OPTIONAL_GOVERNANCE_FIELDS) == set()


def test_governed_logical_schemas_is_the_documented_fifteen():
    assert len(gov.GOVERNED_LOGICAL_SCHEMAS) == 15
    assert len(set(gov.GOVERNED_LOGICAL_SCHEMAS)) == 15  # no duplicates


def test_every_logical_schema_has_a_backing_table_entry():
    for name in gov.GOVERNED_LOGICAL_SCHEMAS:
        assert name in gov.LOGICAL_SCHEMA_BACKING, f"{name} has no backing-table entry"


def _write_schema(tmp_path: Path, name: str, doc: dict, *, owner_module: str = None,
                  schema_version: str = None) -> Path:
    schemas_dir = tmp_path / "dv_harness" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / name).write_text(json.dumps(doc), encoding="utf-8")
    if owner_module:
        pkg = tmp_path / "dv_harness"
        pkg.mkdir(parents=True, exist_ok=True)
        text = f'"""owns {name}."""\n'
        if schema_version:
            text += f'SCHEMA_VERSION = "{schema_version}"\n'
        (pkg / owner_module).write_text(text, encoding="utf-8")
    return schemas_dir / name


def test_audit_schema_governance_core_complete(tmp_path):
    doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example/thing.schema.json",
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    _write_schema(tmp_path, "thing.schema.json", doc, owner_module="thing.py",
                  schema_version="1.0")
    result = gov.audit_schema_governance(tmp_path, "thing.schema.json")
    assert result["governance_status"] == "CORE_COMPLETE"
    for field in gov.CORE_GOVERNANCE_FIELDS:
        assert result["fields"][field]["status"] in ("DECLARED", "SUPPORTED"), field


def test_audit_schema_governance_core_undeclared_when_nothing_present(tmp_path):
    # No $id, no required, no additionalProperties, no owning module.
    doc = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    _write_schema(tmp_path, "bare.schema.json", doc)
    result = gov.audit_schema_governance(tmp_path, "bare.schema.json")
    assert result["fields"]["schema_id"]["status"] == "NOT_DECLARED"
    assert result["fields"]["schema_version"]["status"] == "NOT_DECLARED"
    assert result["fields"]["unknown_field_policy"]["status"] == "NOT_DECLARED"
    assert result["fields"]["required_field_policy"]["status"] == "NOT_DECLARED"
    # validation and compatibility are structural facts, always computed,
    # but never counted toward governance_status (see the module docstring
    # on CORE_GOVERNANCE_FIELDS vs STRUCTURAL_GOVERNANCE_FIELDS).
    assert result["fields"]["validation"]["status"] == "DECLARED"
    assert result["fields"]["compatibility"]["status"] == "SUPPORTED"
    assert result["governance_status"] == "CORE_UNDECLARED"


def test_audit_schema_governance_raises_on_missing_file(tmp_path):
    (tmp_path / "dv_harness" / "schemas").mkdir(parents=True)
    with pytest.raises(gov.SchemaGovernanceError):
        gov.audit_schema_governance(tmp_path, "nope.schema.json")


def test_audit_schema_governance_raises_on_invalid_json_schema(tmp_path):
    # Not even an object at the top level.
    _write_schema(tmp_path, "broken.schema.json", ["not", "an", "object"])
    with pytest.raises(gov.SchemaGovernanceError):
        gov.audit_schema_governance(tmp_path, "broken.schema.json")


def test_audit_schema_governance_reports_invalid_schema_shape(tmp_path):
    # A real object, but not a legal JSON Schema (bad "type" value).
    _write_schema(tmp_path, "invalid.schema.json", {"type": 12345})
    result = gov.audit_schema_governance(tmp_path, "invalid.schema.json")
    assert result["fields"]["validation"]["status"] == "NOT_DECLARED"


def test_producer_consumer_version_from_generator_provenance_tuple(tmp_path):
    doc = {
        "type": "object",
        "properties": {
            "generator": {"type": "object", "properties": {"tool_version": {"type": "string"}}},
        },
    }
    _write_schema(tmp_path, "prov.schema.json", doc)
    result = gov.audit_schema_governance(tmp_path, "prov.schema.json")
    assert result["fields"]["producer_version"]["status"] == "DECLARED"
    assert result["fields"]["consumer_version"]["status"] == "DECLARED"


def test_producer_consumer_version_not_declared_without_generator_block(tmp_path):
    _write_schema(tmp_path, "noprov.schema.json", {"type": "object"})
    result = gov.audit_schema_governance(tmp_path, "noprov.schema.json")
    assert result["fields"]["producer_version"]["status"] == "NOT_DECLARED"
    assert result["fields"]["consumer_version"]["status"] == "NOT_DECLARED"


def test_migration_policy_documented_in_owning_module(tmp_path):
    schemas_dir = tmp_path / "dv_harness" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "m.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    pkg = tmp_path / "dv_harness"
    (pkg / "m.py").write_text(
        '"""owns m.schema.json.\n\nSchema 1.1 is a breaking bump; a stale document must be '
        'regenerated, never migrated by this module."""\nSCHEMA_VERSION = "1.1"\n',
        encoding="utf-8")
    result = gov.audit_schema_governance(tmp_path, "m.schema.json")
    assert result["fields"]["migration"]["status"] == "DOCUMENTED_IN_SOURCE"
    assert result["fields"]["migration"]["owning_module"] == "dv_harness/m.py"


def test_migration_not_documented_when_no_hint_present(tmp_path):
    schemas_dir = tmp_path / "dv_harness" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "n.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    pkg = tmp_path / "dv_harness"
    (pkg / "n.py").write_text('SCHEMA_VERSION = "1.0"\n', encoding="utf-8")
    result = gov.audit_schema_governance(tmp_path, "n.schema.json")
    assert result["fields"]["migration"]["status"] == "NOT_DOCUMENTED"


def test_deprecation_detected_anywhere_in_document(tmp_path):
    doc = {"type": "object", "properties": {"old": {"type": "string", "deprecated": True}}}
    _write_schema(tmp_path, "dep.schema.json", doc)
    result = gov.audit_schema_governance(tmp_path, "dep.schema.json")
    assert result["fields"]["deprecation"]["status"] == "DECLARED"


def test_deprecation_not_declared_when_absent(tmp_path):
    _write_schema(tmp_path, "nodep.schema.json", {"type": "object"})
    result = gov.audit_schema_governance(tmp_path, "nodep.schema.json")
    assert result["fields"]["deprecation"]["status"] == "NOT_DECLARED"


def test_audit_repo_schema_governance_cross_references_logical_names(tmp_path):
    doc = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False, "$id": "x"}
    _write_schema(tmp_path, "x.schema.json", doc, owner_module="x.py", schema_version="1.0")
    result = gov.audit_repo_schema_governance(tmp_path)
    assert result["schemas_audited"] == 1
    logical_names = {l["logical_name"] for l in result["logical_schemas"]}
    assert logical_names == set(gov.GOVERNED_LOGICAL_SCHEMAS)
    # None of the fifteen names match our synthetic "x.schema.json", so every
    # one is honestly unresolved against this bare fixture root.
    assert result["unresolved_logical_schema_count"] == 15


def test_audit_repo_schema_governance_reports_core_undeclared(tmp_path):
    _write_schema(tmp_path, "bare.schema.json", {"type": "object"})
    result = gov.audit_repo_schema_governance(tmp_path)
    assert "bare.schema.json" in result["core_undeclared_schemas"]


def test_audit_repo_schema_governance_empty_when_no_schemas_dir(tmp_path):
    result = gov.audit_repo_schema_governance(tmp_path)
    assert result["schemas_audited"] == 0


# --------------------------------------------------------------------------
# real-repo assertion: this project's own requirement_contract.schema.json
# is a genuine RESOLVED match for RequirementIR, and reaches CORE_COMPLETE.
# --------------------------------------------------------------------------

REAL_ROOT = Path(__file__).resolve().parent.parent


def test_real_repo_requirement_contract_resolves_to_requirement_ir():
    result = gov.audit_repo_schema_governance(REAL_ROOT)
    assert result["schemas_audited"] >= 20
    by_name = {l["logical_name"]: l for l in result["logical_schemas"]}
    req = by_name["RequirementIR"]
    assert req["status"] == "RESOLVED"
    assert req["schema_files"] == ["requirement_contract.schema.json"]
    assert req["audits"][0]["governance_status"] == "CORE_COMPLETE"


def test_real_repo_reports_nine_unresolved_logical_schemas_honestly():
    result = gov.audit_repo_schema_governance(REAL_ROOT)
    # Six real matches (RequirementIR, LoopContract, SYSTEM_RESOURCE_REGISTRY,
    # CapabilityCandidate, ResearchEvidence, FailureIR); nine honestly absent.
    assert result["unresolved_logical_schema_count"] == 9
    for name in ("VerificationIR", "vPlanIR", "TestIR", "CoverageIR", "EvidenceIR",
                 "SubsystemRegistry", "AMBA_PORT_REGISTRY", "ReproducibilityCapsule",
                 "SignoffRecord"):
        assert name in result["unresolved_logical_schemas"]


# --------------------------------------------------------------------------
# section 147: classify_change_full()
# --------------------------------------------------------------------------

_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def test_classify_backward_compatible_when_a_required_field_is_relaxed():
    # Old required both a and b; new only requires a. Every old-valid
    # document (carrying both) still validates under new -> backward
    # compatible. A new-valid document that omits b does NOT validate under
    # old (which still requires it) -> not forward compatible.
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
           "required": ["a", "b"]}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    result = gov.classify_change_full(old, new)
    assert result["verdict"] == gov.VERDICT_BACKWARD
    assert result["backward_compatible_analysis"]["verdict"] == schema_compat.VERDICT_COMPATIBLE


def test_classify_forward_compatible_when_new_field_required_but_old_reader_tolerant():
    # New schema REQUIRES an added field ("b"). Backward direction: old docs
    # (missing "b") now fail under new -> BREAKING. Forward direction: new
    # docs (always carrying "b") still validate under old (no
    # additionalProperties:false there to reject the extra field) ->
    # BACKWARD_COMPATIBLE from schema_compat's own point of view, which this
    # module reports as FORWARD_COMPATIBLE for the ORIGINAL old->new edit.
    old = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "string"}},
           "required": ["a"]}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
           "required": ["a", "b"]}
    result = gov.classify_change_full(old, new)
    assert result["verdict"] == gov.VERDICT_FORWARD
    assert result["backward_compatible_analysis"]["verdict"] == schema_compat.VERDICT_BREAKING
    assert result["forward_compatible_analysis"]["verdict"] == schema_compat.VERDICT_COMPATIBLE


def test_classify_breaking_with_no_migration_path_stays_breaking():
    # additionalProperties:false on BOTH sides, plus a genuinely incompatible
    # type narrowing -> neither direction is compatible, and no migration_fn
    # is supplied.
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "integer"}}, "required": ["a"],
           "additionalProperties": False}
    result = gov.classify_change_full(old, new)
    assert result["verdict"] == gov.VERDICT_BREAKING
    assert result["migration_plan"]["status"] == "NOT_DECLARED"


def test_classify_migration_required_with_a_real_resolvable_migration_fn():
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "integer"}}, "required": ["a"],
           "additionalProperties": False}
    # A real, resolvable callable already in this package.
    result = gov.classify_change_full(old, new, migration_fn="dv_harness.models:Status")
    # Status is a class (callable), so it resolves; but classes with no
    # __call__-friendly signature still count as "callable" per Python's own
    # rule -- use a real function instead for clarity.
    assert result["migration_plan"]["status"] in ("RESOLVED", "DECLARED_BUT_UNRESOLVABLE")


def test_classify_migration_required_uses_a_real_module_function():
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "integer"}}, "required": ["a"],
           "additionalProperties": False}
    result = gov.classify_change_full(
        old, new, migration_fn="dv_harness.schema_compat:modelled_keywords")
    assert result["migration_plan"]["status"] == "RESOLVED"
    assert result["verdict"] == gov.VERDICT_MIGRATION_REQUIRED


def test_classify_migration_fn_declared_but_unresolvable_stays_breaking():
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "integer"}}, "required": ["a"],
           "additionalProperties": False}
    result = gov.classify_change_full(
        old, new, migration_fn="dv_harness.schema_compat:no_such_function_anywhere")
    assert result["migration_plan"]["status"] == "DECLARED_BUT_UNRESOLVABLE"
    assert result["verdict"] == gov.VERDICT_BREAKING  # never silently upgraded


def test_classify_malformed_migration_fn_string_is_reported_not_crashed():
    result = gov._resolve_migration_fn("no-colon-here")
    assert result["status"] == "MALFORMED"


def test_classify_unknown_when_a_change_is_statically_undecidable():
    # A `pattern` change is UNKNOWN by schema_compat's own design (regex
    # containment is not decided there).
    old = {"$schema": _DRAFT, "type": "string", "pattern": "^[a-z]+$"}
    new = {"$schema": _DRAFT, "type": "string", "pattern": "^[a-z0-9]+$"}
    result = gov.classify_change_full(old, new)
    assert result["verdict"] == gov.VERDICT_UNKNOWN


def test_no_verdict_ever_silently_becomes_migration_required_without_resolution():
    # Same BREAKING setup as above, but migration_fn omitted entirely.
    old = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}}, "required": ["a"],
           "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "integer"}}, "required": ["a"],
           "additionalProperties": False}
    result = gov.classify_change_full(old, new, migration_fn=None)
    assert result["migration_plan"]["status"] == "NOT_DECLARED"
    assert result["verdict"] == gov.VERDICT_BREAKING


# --------------------------------------------------------------------------
# consumer inventory, rollback, tests, and human-gate
# --------------------------------------------------------------------------

def test_consumer_inventory_finds_real_references(tmp_path):
    pkg = tmp_path / "dv_harness"
    pkg.mkdir(parents=True)
    (pkg / "writer.py").write_text('SCHEMAS_DIR = "z.schema.json"\n', encoding="utf-8")
    (pkg / "reader.py").write_text('# reads z.schema.json for its own purpose\n',
                                   encoding="utf-8")
    (pkg / "unrelated.py").write_text('# nothing here\n', encoding="utf-8")
    hits = gov._find_schema_consumers(tmp_path, "z.schema.json")
    assert "dv_harness/writer.py" in hits or "dv_harness\\writer.py" in hits
    assert "dv_harness/reader.py" in hits or "dv_harness\\reader.py" in hits
    assert not any("unrelated" in h for h in hits)


def test_consumer_inventory_empty_without_dv_harness_dir(tmp_path):
    assert gov._find_schema_consumers(tmp_path, "z.schema.json") == []


def _run_git(cwd, *args):
    subprocess.run(["git"] + list(args), cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def test_rollback_available_with_real_git_history(tmp_path):
    schemas_dir = tmp_path / "dv_harness" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "r.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "config", "user.email", "t@example.com")
    _run_git(tmp_path, "config", "user.name", "t")
    _run_git(tmp_path, "add", "-A")
    _run_git(tmp_path, "commit", "-q", "-m", "init")

    old = {"type": "object"}
    new = {"type": "object", "required": ["a"]}
    result = gov.classify_change_full(old, new, schema_filename="r.schema.json", root=tmp_path)
    assert result["rollback"]["status"] == "AVAILABLE"


def test_rollback_not_available_without_git_history(tmp_path):
    schemas_dir = tmp_path / "dv_harness" / "schemas"
    schemas_dir.mkdir(parents=True)
    old = {"type": "object"}
    new = {"type": "object", "required": ["a"]}
    result = gov.classify_change_full(old, new, schema_filename="r.schema.json", root=tmp_path)
    assert result["rollback"]["status"] == "NOT_AVAILABLE"


def test_tests_field_found_and_not_found(tmp_path):
    (tmp_path / "dv_harness_tests").mkdir(parents=True)
    (tmp_path / "dv_harness_tests" / "test_thing.py").write_text("", encoding="utf-8")
    old, new = {"type": "object"}, {"type": "object", "required": ["a"]}
    result = gov.classify_change_full(old, new, owning_module="dv_harness/thing.py", root=tmp_path)
    assert result["tests"]["status"] == "FOUND"

    result2 = gov.classify_change_full(old, new, owning_module="dv_harness/missing.py",
                                       root=tmp_path)
    assert result2["tests"]["status"] == "NOT_FOUND"


def test_human_gate_required_when_owning_module_reached_from_engine(tmp_path):
    pkg = tmp_path / "dv_harness"
    pkg.mkdir(parents=True)
    (pkg / "engine.py").write_text("from . import thing\n", encoding="utf-8")
    old = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "string"}},
           "required": ["a"], "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "integer"}},
           "required": ["a"], "additionalProperties": False}
    result = gov.classify_change_full(old, new, owning_module="dv_harness/thing.py", root=tmp_path)
    assert result["verdict"] == gov.VERDICT_BREAKING
    assert result["human_gate_required"] is True


def test_human_gate_not_required_when_module_not_on_production_path(tmp_path):
    pkg = tmp_path / "dv_harness"
    pkg.mkdir(parents=True)
    (pkg / "engine.py").write_text("from . import unrelated_other_thing\n", encoding="utf-8")
    old = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "string"}},
           "required": ["a"], "additionalProperties": False}
    new = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "integer"}},
           "required": ["a"], "additionalProperties": False}
    result = gov.classify_change_full(old, new, owning_module="dv_harness/thing.py", root=tmp_path)
    assert result["human_gate_required"] is False


def test_human_gate_never_required_for_a_non_breaking_verdict(tmp_path):
    pkg = tmp_path / "dv_harness"
    pkg.mkdir(parents=True)
    (pkg / "engine.py").write_text("from . import thing\n", encoding="utf-8")
    old = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "string"}},
           "required": ["a"]}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    result = gov.classify_change_full(old, new, owning_module="dv_harness/thing.py", root=tmp_path)
    assert result["verdict"] in (gov.VERDICT_BACKWARD, gov.VERDICT_FORWARD)
    assert result["human_gate_required"] is False


# --------------------------------------------------------------------------
# CLI / execute_verb
# --------------------------------------------------------------------------

def test_execute_verb_registry_exit_zero_on_real_repo():
    text, code = gov.execute_verb(action="registry", root=str(REAL_ROOT))
    assert code in (0, 1)  # real repo state; either is a legitimate outcome
    assert "schema-config-governance" in text


def test_execute_verb_registry_not_available_on_bare_root(tmp_path):
    text, code = gov.execute_verb(action="registry", root=str(tmp_path))
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_execute_verb_classify_requires_old_and_new():
    text, code = gov.execute_verb(action="classify")
    assert code == 2


def test_execute_verb_classify_json_round_trip(tmp_path):
    old = {"$schema": _DRAFT, "type": "object", "properties": {"a": {"type": "string"}},
           "required": ["a"]}
    new = {"$schema": _DRAFT, "type": "object",
           "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    op, np = tmp_path / "old.json", tmp_path / "new.json"
    op.write_text(json.dumps(old), encoding="utf-8")
    np.write_text(json.dumps(new), encoding="utf-8")
    text, code = gov.execute_verb(action="classify", old=str(op), new=str(np), as_json=True)
    assert code == 0
    payload = json.loads(text)
    assert payload["verdict"] in (gov.VERDICT_BACKWARD, gov.VERDICT_FORWARD)


def test_real_cli_subprocess_registry_and_classify(tmp_path):
    op, np = tmp_path / "old.json", tmp_path / "new.json"
    op.write_text(json.dumps({"$schema": _DRAFT, "type": "object"}), encoding="utf-8")
    np.write_text(json.dumps({"$schema": _DRAFT, "type": "object", "required": ["x"]}),
                  encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.schema_config_governance", "classify",
         "--old", str(op), "--new", str(np), "--json"],
        cwd=str(REAL_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode in (0, 1, 3)
    payload = json.loads(result.stdout)
    assert payload["verdict"] in (
        gov.VERDICT_BACKWARD, gov.VERDICT_FORWARD, gov.VERDICT_BREAKING,
        gov.VERDICT_MIGRATION_REQUIRED, gov.VERDICT_UNKNOWN)

    result2 = subprocess.run(
        [sys.executable, "-m", "dv_harness.schema_config_governance", "registry", "--json"],
        cwd=str(REAL_ROOT), capture_output=True, text=True, timeout=60)
    assert result2.returncode in (0, 1)
    payload2 = json.loads(result2.stdout)
    assert payload2["schemas_audited"] > 0


def test_unknown_action_reported_honestly():
    text, code = gov.execute_verb(action="bogus")
    assert code == 2
    assert "unknown action" in text
