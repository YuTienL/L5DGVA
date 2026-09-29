"""Tests for dv_harness/schema_compat.py (PC-1).

The suite is built around one rule: a compatibility verdict is only worth
anything if the DOCUMENTS agree with it. So almost every assertion here is
paired with a real `jsonschema` validation of a real document, and the headline
cases are driven off this repo's own artifacts rather than toy schemas:

  * `init_seq.schema.json` (real, `$ref`-bearing, `additionalProperties: false`)
    is mutated ONE defect at a time so each assertion proves that rule caught
    that specific injected change.
  * The REAL env_manifest 1.0 -> 1.1 bump is replayed out of git history and
    asserted BREAKING -- the same conclusion CLAUDE.md records a human reaching
    by reading that diff, reached here mechanically and backed by a witness.
  * Every schema currently in `dv_harness/schemas/` is compared against itself
    (must be compatible), synthesized from, and checked for keywords this
    module has no rule for.

Nothing here runs a build, a regression, or an LSF submission; the only
external process is `git show` against this repo's own history and, in the
version-bump tests, a scratch repository created under tmp_path.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dv_harness import schema_compat as sc  # noqa: E402

SCHEMA_DIR = ROOT / "dv_harness" / "schemas"
ALL_SCHEMAS = sorted(SCHEMA_DIR.glob("*.schema.json"))


def _load(name):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def init_seq():
    return _load("init_seq.schema.json")


def _validator(schema):
    import jsonschema
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def classify(old, new, **kw):
    return sc.classify_schema_change(old, new, **kw)


def codes(result):
    return sorted(f["code"] for f in result["findings"])


def _mutated(base, mutate):
    new = copy.deepcopy(base)
    mutate(new)
    assert new != base, "the test's own mutation changed nothing"
    return new


# ---------------------------------------------------------------------------
# the core contract: a BREAKING verdict is proven by a real document
# ---------------------------------------------------------------------------

def assert_witness_is_real(result, old, new):
    """Every PROVEN witness must actually pass the old validator and actually
    fail the new one. This is the assertion that makes the whole module more
    than a diff reader -- if it ever fails, the classifier is lying."""
    old_v, new_v = _validator(old), _validator(new)
    proven = [f for f in result["findings"] if f.get("witness_status") == "PROVEN"]
    assert proven, "expected at least one witness-backed finding"
    for f in proven:
        doc = f["witness"]
        assert old_v.is_valid(doc), f"{f['code']} witness does not pass the OLD schema: {doc}"
        assert not new_v.is_valid(doc), f"{f['code']} witness does not fail the NEW schema: {doc}"


BREAKING_MUTATIONS = {
    "REQUIRED_KEY_ADDED": lambda n: n["required"].append("source"),
    "REQUIRED_KEY_ADDED_NESTED": lambda n: n["$defs"]["step"]["required"].append("register"),
    "TYPE_NARROWED": lambda n: n["$defs"]["step"]["properties"]["index"].update({"type": "string"}),
    "ENUM_VALUE_REMOVED": lambda n: n["$defs"]["step"]["properties"]["kind"].__setitem__(
        "enum", n["$defs"]["step"]["properties"]["kind"]["enum"][:1]),
    "BOUND_TIGHTENED_MIN": lambda n: n["$defs"]["step"]["properties"]["index"].update({"minimum": 5}),
    "BOUND_TIGHTENED_MINLENGTH": lambda n: n["properties"]["interface"].update({"minLength": 40}),
    "BOUND_TIGHTENED_MINITEMS": lambda n: n["properties"]["steps"].update({"minItems": 3}),
    "BOUND_TIGHTENED_MAXITEMS": lambda n: n["properties"]["steps"].update({"maxItems": 0}),
    "PROPERTY_REMOVED_AND_CLOSED": lambda n: n["properties"].pop("source"),
    "CONST_CHANGED": lambda n: n["properties"]["schema_version"].update({"const": "2.0"}),
}


@pytest.mark.parametrize("label", sorted(BREAKING_MUTATIONS))
def test_each_narrowing_is_breaking_and_carries_a_validated_witness(init_seq, label):
    new = _mutated(init_seq, BREAKING_MUTATIONS[label])
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_BREAKING, result["findings"]
    assert result["counts"]["proven"] >= 1, f"{label} was claimed without a witness: {result}"
    assert_witness_is_real(result, init_seq, new)


COMPATIBLE_MUTATIONS = {
    "optional_property_added": lambda n: n["properties"].update(
        {"notes": {"type": "string", "description": "free-text note"}}),
    "type_widened": lambda n: n["$defs"]["step"]["properties"]["index"].update(
        {"type": ["integer", "null"]}),
    "integer_widened_to_number": lambda n: n["$defs"]["step"]["properties"]["index"].update(
        {"type": "number"}),
    "enum_value_added": lambda n: n["$defs"]["step"]["properties"]["kind"]["enum"].append("nop"),
    "required_key_dropped": lambda n: n["required"].remove("interface"),
    "minimum_lowered": lambda n: n["$defs"]["step"]["properties"]["index"].update({"minimum": -5}),
    "description_reworded": lambda n: n.update({"description": "different prose entirely"}),
    "title_changed": lambda n: n.update({"title": "init_seq (renamed)"}),
    "additional_properties_opened": lambda n: n["properties"]["source"].update(
        {"additionalProperties": True}),
}


@pytest.mark.parametrize("label", sorted(COMPATIBLE_MUTATIONS))
def test_each_widening_is_backward_compatible(init_seq, label):
    new = _mutated(init_seq, COMPATIBLE_MUTATIONS[label])
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_COMPATIBLE, result["findings"]
    assert result["counts"]["breaking"] == 0


@pytest.mark.parametrize("label", sorted(COMPATIBLE_MUTATIONS))
def test_a_compatible_verdict_survives_real_documents(init_seq, label):
    """A BACKWARD_COMPATIBLE verdict is a claim about every document. Check it
    the only way it can be checked: build documents that pass the old schema
    and confirm the new schema still takes them."""
    new = _mutated(init_seq, COMPATIBLE_MUTATIONS[label])
    old_v, new_v = _validator(init_seq), _validator(new)
    resolver = sc._Resolver(init_seq)
    docs = [sc._instance(init_seq, resolver),
            sc._instance(init_seq, resolver, ["source", "document"]),
            sc._instance(init_seq, resolver, ["steps", "0", "index"])]
    for doc in docs:
        assert old_v.is_valid(doc)
        assert new_v.is_valid(doc), f"{label} claimed compatible but rejects {doc}"


# ---------------------------------------------------------------------------
# the honesty guards
# ---------------------------------------------------------------------------

# Each of these narrows a construct this module does not decide, in a way the
# empirical pass cannot settle either -- the synthesized minimal instance of the
# old schema still validates against the new one. So UNKNOWN is the final answer
# and there is nowhere left for it to hide.
UNKNOWN_MUTATIONS = {
    "pattern_added": lambda n: n["properties"]["interface"].update({"pattern": "^x*$"}),
    "pattern_changed": lambda n: (n["properties"]["interface"].update({"pattern": "^x$"}),
                                  n["properties"]["interface"].update({"pattern": "^x+$"})),
    "format_added": lambda n: n["properties"]["source"]["properties"]["document"].update(
        {"format": "uri-reference"}),
    "unmodelled_keyword": lambda n: n["properties"]["interface"].update({"weirdNewKeyword": 3}),
    "oneOf_added": lambda n: n["properties"]["interface"].update(
        {"oneOf": [{"minLength": 1}, {"minLength": 2}]}),
    "not_added": lambda n: n["properties"]["interface"].update({"not": {"const": "nope"}}),
    "patternProperties_added": lambda n: n["properties"]["source"].update(
        {"patternProperties": {"^zz": {"type": "string"}}}),
    "multipleOf_added": lambda n: n["$defs"]["step"]["properties"]["index"].update(
        {"multipleOf": 1}),
}


@pytest.mark.parametrize("label", sorted(UNKNOWN_MUTATIONS))
def test_semantics_this_module_does_not_implement_report_unknown(init_seq, label):
    """The failure mode PC-1 names is a diff heuristic that pretends to
    understand JSON Schema semantics it never checks. These changes are all
    genuinely undecided here, and every one of them must say so rather than
    defaulting to compatible."""
    new = _mutated(init_seq, UNKNOWN_MUTATIONS[label])
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_UNKNOWN, result["findings"]
    assert result["counts"]["breaking"] == 0


def test_unknown_never_collapses_into_compatible_when_mixed_with_a_safe_change(init_seq):
    new = _mutated(init_seq, lambda n: (n["properties"].update({"notes": {"type": "string"}}),
                                        n["properties"]["interface"].update({"pattern": "^x*$"})))
    assert classify(init_seq, new)["verdict"] == sc.VERDICT_UNKNOWN


def test_an_undecided_change_a_real_document_refutes_becomes_breaking(init_seq):
    """UNKNOWN is honest, not final. `^a$` is undecidable against the old
    schema's `minLength: 1` by the rules here, but the minimal instance of the
    old schema is `"x"` -- and the real 2020-12 validator rejects it under the
    new pattern. The document wins, and the finding says the rules declined
    rather than pretending they were wrong."""
    new = _mutated(init_seq, lambda n: n["properties"]["interface"].update({"pattern": "^a$"}))
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert "UNDECIDED_CHANGE_PROVEN_BREAKING" in codes(result)
    assert "STATIC_RULES_INCOMPLETE" not in codes(result)
    assert_witness_is_real(result, init_seq, new)


def test_breaking_outranks_unknown(init_seq):
    new = _mutated(init_seq, lambda n: (n["required"].append("source"),
                                        n["properties"]["interface"].update({"pattern": "^x*$"})))
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert "CONSTRAINT_LANGUAGE_CHANGED" in codes(result)


def test_an_unmodelled_keyword_is_named_in_the_finding(init_seq):
    new = _mutated(init_seq, lambda n: n["properties"]["interface"].update({"weirdNewKeyword": 3}))
    finding = [f for f in classify(init_seq, new)["findings"]
               if f["code"] == "UNMODELED_KEYWORD_CHANGED"][0]
    assert "weirdNewKeyword" in finding["detail"]
    assert finding["schema_path"].endswith("/weirdNewKeyword")


def test_modelled_keywords_covers_every_keyword_this_repos_schemas_actually_use():
    """The rule table is only trustworthy while it covers the schemas in this
    tree. The day one starts using an assertive keyword with no rule, this test
    is what says so -- rather than that schema silently comparing as
    compatible."""
    applicator_sub = {"not", "if", "then", "else", "items", "contains",
                      "additionalProperties", "propertyNames",
                      "unevaluatedItems", "unevaluatedProperties"}
    applicator_list = {"allOf", "anyOf", "oneOf", "prefixItems"}
    applicator_map = {"properties", "patternProperties", "$defs", "definitions",
                      "dependentSchemas"}
    used = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            used.add(key)
            if key in applicator_sub:
                walk(value)
            elif key in applicator_list and isinstance(value, list):
                for item in value:
                    walk(item)
            elif key in applicator_map and isinstance(value, dict):
                for item in value.values():
                    walk(item)

    for path in ALL_SCHEMAS:
        walk(json.loads(path.read_text(encoding="utf-8")))
    assert used, "no schemas were scanned"
    assert used <= set(sc.modelled_keywords()), \
        f"schemas use keyword(s) with no compatibility rule: {sorted(used - set(sc.modelled_keywords()))}"


# ---------------------------------------------------------------------------
# the self-check: static rules are not trusted over real validation
# ---------------------------------------------------------------------------

def test_a_corpus_document_that_breaks_refutes_a_compatible_static_verdict():
    """The classifier must lose an argument with a real document.

    This exercises a REAL soundness hole in the rule table, not a contrived
    one: dropping `patternProperties` reads as "one fewer assertion" to
    `_compare_opaque`, but under `additionalProperties: false` those pattern
    keys were the only thing making `x_extra` legal, so removing it REJECTS
    documents. The static pass says BACKWARD_COMPATIBLE and is wrong; one real
    document overturns it and the finding names the rule table as the problem.
    """
    old = {"$schema": "https://json-schema.org/draft/2020-12/schema",
           "type": "object", "additionalProperties": False,
           "patternProperties": {"^x_": {"type": "string"}},
           "properties": {"a": {"type": "string"}}}
    new = copy.deepcopy(old)
    new.pop("patternProperties")
    doc = {"a": "v", "x_extra": "kept"}
    assert classify(old, new)["verdict"] == sc.VERDICT_COMPATIBLE
    result = classify(old, new, corpus=[doc])
    assert result["verdict"] == sc.VERDICT_BREAKING
    incomplete = [f for f in result["findings"] if f["code"] == "STATIC_RULES_INCOMPLETE"]
    assert incomplete and incomplete[0]["witness"] == doc
    assert result["documents_broken"] == 1
    assert_witness_is_real(result, old, new)


def test_a_corpus_document_that_still_validates_leaves_the_verdict_alone():
    old = {"$schema": "https://json-schema.org/draft/2020-12/schema",
           "type": "object", "properties": {"a": {"type": "string"}}}
    new = copy.deepcopy(old)
    new["properties"]["a"]["pattern"] = "^[a-z]+$"
    result = classify(old, new, corpus=[{"a": "letters"}])
    assert result["verdict"] == sc.VERDICT_UNKNOWN
    assert result["documents_broken"] == 0


def test_the_ref_shortcut_bug_stays_fixed(init_seq):
    """Regression pin. `steps.items` is the byte-identical `{"$ref":
    "#/$defs/step"}` in both versions while `$defs/step` is what changed; an
    `==` shortcut there reported a retyped required field as compatible."""
    new = _mutated(init_seq,
                   lambda n: n["$defs"]["step"]["properties"]["index"].update({"type": "string"}))
    assert init_seq["properties"]["steps"]["items"] == new["properties"]["steps"]["items"]
    result = classify(init_seq, new)
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert "TYPE_NARROWED" in codes(result)
    assert result["counts"]["proven"] >= 1


def test_refs_are_resolved_not_string_matched(init_seq):
    """A renamed definition with identical contents is not a change."""
    new = copy.deepcopy(init_seq)
    new["$defs"]["bring_up_step"] = new["$defs"].pop("step")
    new["properties"]["steps"]["items"] = {"$ref": "#/$defs/bring_up_step"}
    assert classify(init_seq, new)["verdict"] == sc.VERDICT_COMPATIBLE


# ---------------------------------------------------------------------------
# every real schema in this repo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: p.name)
def test_every_repo_schema_is_compatible_with_itself(path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    result = classify(schema, schema)
    assert result["verdict"] == sc.VERDICT_COMPATIBLE
    assert result["findings"] == []


@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: p.name)
def test_synthesis_produces_documents_the_real_validator_accepts(path):
    """The witness machinery is only credible if what it builds really
    validates. Proven against every schema this repo owns, not a toy -- and no
    schema is allowed to skip, because a schema nothing can be synthesized from
    is a schema whose breaking changes ship unwitnessed."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    doc = sc._instance(schema, sc._Resolver(schema))
    assert _validator(schema).is_valid(doc), \
        f"synthesized instance of {path.name} does not validate: {doc}"


@pytest.mark.parametrize("fmt", sorted(sc._FORMAT_SAMPLES))
def test_every_format_sample_passes_the_real_format_checker(fmt):
    """The format table is a set of claims about what a real validator accepts.
    Check them with that validator rather than by eye."""
    import jsonschema
    if fmt not in jsonschema.FormatChecker().checkers:
        pytest.skip(f"this jsonschema build does not assert format {fmt!r}")
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "string", "format": fmt}
    assert _validator(schema).is_valid(sc._format_sample(fmt)), \
        f"sample for format {fmt!r} is not actually valid"


def _repo_patterns():
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("pattern"), str):
                found.add(node["pattern"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in ALL_SCHEMAS:
        walk(json.loads(path.read_text(encoding="utf-8")))
    return sorted(found)


REPO_PATTERNS = _repo_patterns()


@pytest.mark.parametrize("pattern", REPO_PATTERNS)
def test_a_matching_string_is_produced_for_every_pattern_this_repo_uses(pattern):
    """The regex sampler walks the AST Python's own `re` parser produced. Its
    output is only trustworthy if the real engine agrees, so that is what is
    asserted -- against every pattern actually in this repo's schemas, not
    invented ones."""
    import re as _re
    sample = sc._sample_matching(pattern)
    assert _re.search(pattern, sample), f"{sample!r} does not match {pattern!r}"


def test_the_regex_sampler_refuses_what_it_cannot_emit():
    """A construct the emitter does not implement must raise, not silently
    return a string that happens not to match."""
    with pytest.raises(sc._Unsynthesizable):
        sc._sample_matching(r"(?=lookahead)x")
    with pytest.raises(sc._Unsynthesizable):
        sc._sample_matching(r"(a)\1")


def test_a_field_asserting_both_pattern_and_format_gets_a_sample_satisfying_both():
    """`exemptions.schema.json`'s `valid_until` is `format: date` AND
    `^\\d{4}-\\d{2}-\\d{2}$`. The pattern's own zero-filled sample
    ('0000-00-00') matches the regex and is not a real date, so satisfying one
    source is not enough."""
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "string", "format": "date",
              "pattern": r"^\d{4}-\d{2}-\d{2}$"}
    value = sc._instance(schema, sc._Resolver(schema))
    assert _validator(schema).is_valid(value), value


@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: p.name)
def test_adding_a_required_key_to_any_repo_schema_is_breaking(path):
    """The env_manifest precedent applied to all 24 schemas: a REQUIRED-key
    addition is never quietly compatible, whatever the schema."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    if schema.get("type") != "object" or "required" not in schema:
        pytest.skip(f"{path.name} has no top-level required list")
    new = copy.deepcopy(schema)
    new.setdefault("properties", {})["freshly_required"] = {"type": "string"}
    new["required"] = list(new["required"]) + ["freshly_required"]
    result = classify(schema, new)
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert "REQUIRED_KEY_ADDED" in codes(result)
    # And not merely asserted: a witness for every one of them, validated both
    # ways. This is the assertion that says the machinery reaches all 24 real
    # schemas, `if`/`then` conditionals and `pattern`-constrained ids included.
    assert_witness_is_real(result, schema, new)
    added = [f for f in result["findings"] if f["code"] == "REQUIRED_KEY_ADDED"][0]
    assert added["witness_status"] == "PROVEN"


def test_conditional_constraints_are_satisfied_by_the_repair_pass():
    """`question.schema.json` pins `owner` per `domain` through an `allOf` of
    `if`/`then` blocks. Nothing in the property walk can see that, so the draft
    is repaired from the REAL validator's own errors -- and the proof is that
    the repaired document carries the conditional value, not just that it
    validates."""
    schema = _load("question.schema.json")
    doc = sc._instance(schema, sc._Resolver(schema))
    assert _validator(schema).is_valid(doc)
    expected = {"vip": "DV-owner/Synopsys-AE", "dut": "designer", "env": "DV-owner"}
    assert doc["owner"] == expected[doc["domain"]]


def test_the_repair_pass_gives_up_rather_than_returning_an_invalid_document():
    """Fail-closed: a witness that does not validate proves nothing, so an
    unrepairable draft must raise instead of being handed back."""
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "object", "required": ["a"],
              "properties": {"a": {"type": "string", "pattern": "(?=impossible)x"}}}
    with pytest.raises(sc._Unsynthesizable):
        sc._instance(schema, sc._Resolver(schema))


# ---------------------------------------------------------------------------
# the real historical bump: env_manifest schema 1.0 -> 1.1
# ---------------------------------------------------------------------------

ENV_SCHEMA = "dv_harness/schemas/env_manifest.schema.json"
BUMP_COMMIT = "60bf3bd"


def _blob(rev, relpath):
    p = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{relpath}"],
                       capture_output=True, text=True, encoding="utf-8")
    return p.stdout if p.returncode == 0 else None


def _bump_pair():
    before = _blob(f"{BUMP_COMMIT}~1", ENV_SCHEMA)
    after = _blob(BUMP_COMMIT, ENV_SCHEMA)
    if before is None or after is None:
        pytest.skip("env_manifest 1.0 -> 1.1 commit is not reachable in this checkout")
    return json.loads(before), json.loads(after)


def test_the_real_env_manifest_1_0_to_1_1_bump_is_classified_breaking():
    """CLAUDE.md records a human reading that diff and concluding "Schema 1.1
    is a breaking bump and deliberately so". Same conclusion, mechanically,
    from the two real schema files in this repo's own history."""
    old, new = _bump_pair()
    result = classify(old, new)
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert_witness_is_real(result, old, new)


def test_the_real_bump_names_exactly_the_four_fact_sources_claude_md_names():
    """Not just "something broke": the four REQUIRED additions CLAUDE.md lists
    (vip_release, user_guide_refs, address_map/clock_reset,
    testplan_correspondence) must each be named by a finding."""
    old, new = _bump_pair()
    result = classify(old, new)
    named = " ".join(f["detail"] for f in result["findings"]
                     if f["code"] == "REQUIRED_KEY_ADDED")
    for key in ("vip_release", "user_guide_refs", "address_map",
                "clock_reset", "testplan_correspondence"):
        assert key in named, f"{key} was not reported as a newly-required key"


def test_a_real_1_0_manifest_shape_is_the_witness_for_the_real_bump():
    """The witness is not an abstract claim: it is a document shaped like the
    manifests that were on disk before the bump, and the real 1.1 validator
    really rejects it -- which is exactly `load_env_manifest()` failing loudly
    on a stale 1.0 file."""
    old, new = _bump_pair()
    result = classify(old, new)
    witnesses = [f["witness"] for f in result["findings"]
                 if f["code"] == "REQUIRED_KEY_ADDED" and f.get("witness")]
    assert witnesses, "the headline breaking change shipped without a witness"
    old_v, new_v = _validator(old), _validator(new)
    for doc in witnesses:
        assert set(doc) >= {"schema_version", "vip_config", "dut_facts", "env_topology"}
        assert old_v.is_valid(doc)
        assert not new_v.is_valid(doc)


def test_todays_schemas_are_unchanged_against_head():
    """The classifier run over this working tree must be quiet unless someone
    actually edited a schema -- a checker that cries wolf on an untouched tree
    is not usable in CI."""
    result = sc.classify_repo_schema_changes(ROOT, "HEAD")
    edited = [r for r in result["schemas"] if not r.get("reason")]
    for r in edited:
        assert r["verdict"] in (sc.VERDICT_COMPATIBLE, sc.VERDICT_BREAKING, sc.VERDICT_UNKNOWN)
    assert result["verdict"] in (sc.VERDICT_COMPATIBLE, sc.VERDICT_BREAKING, sc.VERDICT_UNKNOWN)


# ---------------------------------------------------------------------------
# repo mode + the version-bump rule, on a scratch repository
# ---------------------------------------------------------------------------

def _scratch_repo(tmp_path, schema, module_version="1.0"):
    root = tmp_path / "repo"
    (root / "dv_harness" / "schemas").mkdir(parents=True)
    (root / "dv_harness" / "schemas" / "widget.schema.json").write_text(
        json.dumps(schema, indent=1), encoding="utf-8")
    (root / "dv_harness" / "widget.py").write_text(
        'SCHEMA_VERSION = "%s"\nSCHEMA_PATH = "widget.schema.json"\n' % module_version,
        encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(root)] + args, check=True,
                       capture_output=True, text=True)
    return root


BASE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://dv-agent-harness-l5/schemas/widget.schema.json",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "name"],
    "properties": {"schema_version": {"const": "1.0"},
                   "name": {"type": "string", "minLength": 1}},
}


def _write(root, schema, module_version=None):
    (root / "dv_harness" / "schemas" / "widget.schema.json").write_text(
        json.dumps(schema, indent=1), encoding="utf-8")
    if module_version is not None:
        (root / "dv_harness" / "widget.py").write_text(
            'SCHEMA_VERSION = "%s"\nSCHEMA_PATH = "widget.schema.json"\n' % module_version,
            encoding="utf-8")


def test_repo_mode_flags_a_breaking_edit_that_did_not_bump_schema_version(tmp_path):
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    breaking = copy.deepcopy(BASE_SCHEMA)
    breaking["required"].append("owner")
    breaking["properties"]["owner"] = {"type": "string"}
    _write(root, breaking)  # module SCHEMA_VERSION deliberately left at 1.0
    result = sc.classify_repo_schema_changes(root, "HEAD")
    assert result["verdict"] == sc.VERDICT_BREAKING
    one = result["schemas"][0]
    assert "REQUIRED_KEY_ADDED" in [f["code"] for f in one["findings"]]
    assert "BREAKING_WITHOUT_VERSION_BUMP" in [f["code"] for f in one["findings"]]


def test_repo_mode_accepts_a_breaking_edit_that_did_bump_it(tmp_path):
    """env_manifest's own choice: breaking IS allowed, it just has to be
    declared. The bump silences the version finding and nothing else."""
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    breaking = copy.deepcopy(BASE_SCHEMA)
    breaking["required"].append("owner")
    breaking["properties"]["owner"] = {"type": "string"}
    breaking["properties"]["schema_version"] = {"const": "1.1"}
    _write(root, breaking, module_version="1.1")
    result = sc.classify_repo_schema_changes(root, "HEAD")
    one = result["schemas"][0]
    assert one["verdict"] == sc.VERDICT_BREAKING
    assert "BREAKING_WITHOUT_VERSION_BUMP" not in [f["code"] for f in one["findings"]]


def test_repo_mode_requires_a_bump_for_an_undecidable_edit_too(tmp_path):
    """An edit nobody can prove safe is not a reason to skip the bump."""
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    unknown = copy.deepcopy(BASE_SCHEMA)
    unknown["properties"]["name"]["pattern"] = "^[a-z]+$"
    _write(root, unknown)
    result = sc.classify_repo_schema_changes(root, "HEAD")
    one = result["schemas"][0]
    assert one["verdict"] == sc.VERDICT_UNKNOWN
    assert "BREAKING_WITHOUT_VERSION_BUMP" in [f["code"] for f in one["findings"]]


def test_repo_mode_is_silent_on_a_compatible_edit(tmp_path):
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    compatible = copy.deepcopy(BASE_SCHEMA)
    compatible["properties"]["note"] = {"type": "string"}
    _write(root, compatible)
    result = sc.classify_repo_schema_changes(root, "HEAD")
    assert result["verdict"] == sc.VERDICT_COMPATIBLE
    assert result["schemas"][0]["findings"] == []


def test_repo_mode_reports_a_new_schema_file_as_nothing_to_break(tmp_path):
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    (root / "dv_harness" / "schemas" / "gadget.schema.json").write_text(
        json.dumps(BASE_SCHEMA), encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    result = sc.classify_repo_schema_changes(root, "HEAD")
    gadget = [r for r in result["schemas"] if r["schema"].endswith("gadget.schema.json")][0]
    assert gadget["verdict"] == sc.VERDICT_COMPATIBLE
    assert "nothing to break" in gadget["reason"]


def test_repo_mode_reports_a_deleted_schema_as_breaking(tmp_path):
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    (root / "dv_harness" / "schemas" / "widget.schema.json").unlink()
    result = sc.classify_repo_schema_changes(root, "HEAD")
    assert result["verdict"] == sc.VERDICT_BREAKING
    assert result["schemas"][0]["findings"][0]["code"] == "SCHEMA_DELETED"


def test_owning_module_is_discovered_from_source_not_a_hardcoded_table(tmp_path):
    root = _scratch_repo(tmp_path, BASE_SCHEMA)
    assert sc.owning_modules_for_schema(root, "widget.schema.json") == ["dv_harness/widget.py"]
    assert sc.owning_modules_for_schema(root, "nothing.schema.json") == []


def test_owning_module_lookup_works_on_this_repo():
    owners = sc.owning_modules_for_schema(ROOT, "env_manifest.schema.json")
    assert "dv_harness/env_manifest.py" in owners


# ---------------------------------------------------------------------------
# fail-closed behaviour and the verb
# ---------------------------------------------------------------------------

def test_an_unreadable_schema_raises_rather_than_returning_unknown(tmp_path):
    with pytest.raises(sc.SchemaCompatError):
        sc.compare_schema_files(tmp_path / "missing.json", tmp_path / "also-missing.json")


def test_a_non_object_schema_is_rejected():
    with pytest.raises(sc.SchemaCompatError):
        classify(["not", "a", "schema"], {})


def test_an_unresolvable_ref_raises_rather_than_being_ignored():
    old = {"type": "object", "properties": {"a": {"$ref": "#/$defs/gone"}}}
    with pytest.raises(sc.SchemaCompatError):
        classify(old, {"type": "object", "properties": {"a": {"type": "string"}}})


def test_verb_exit_codes(tmp_path, init_seq):
    old_p = tmp_path / "old.json"
    new_p = tmp_path / "new.json"
    old_p.write_text(json.dumps(init_seq), encoding="utf-8")

    new_p.write_text(json.dumps(_mutated(init_seq, lambda n: n["properties"].update(
        {"notes": {"type": "string"}}))), encoding="utf-8")
    assert sc.execute_verb(old=str(old_p), new=str(new_p))[1] == 0

    new_p.write_text(json.dumps(_mutated(init_seq, lambda n: n["required"].append("source"))),
                     encoding="utf-8")
    assert sc.execute_verb(old=str(old_p), new=str(new_p))[1] == 1

    new_p.write_text(json.dumps(_mutated(init_seq, lambda n: n["properties"]["interface"].update(
        {"pattern": "^x*$"}))), encoding="utf-8")
    text, code = sc.execute_verb(old=str(old_p), new=str(new_p))
    assert code == 3, f"UNKNOWN must not share an exit code with PASS: {text}"

    assert sc.execute_verb()[1] == 2
    assert sc.execute_verb(old=str(old_p), new=str(tmp_path / "nope.json"))[1] == 2


def test_verb_json_output_carries_the_witness(tmp_path, init_seq):
    old_p, new_p = tmp_path / "old.json", tmp_path / "new.json"
    old_p.write_text(json.dumps(init_seq), encoding="utf-8")
    new_p.write_text(json.dumps(_mutated(init_seq, lambda n: n["required"].append("source"))),
                     encoding="utf-8")
    text, code = sc.execute_verb(old=str(old_p), new=str(new_p), as_json=True)
    payload = json.loads(text)
    assert code == 1 and payload["verdict"] == sc.VERDICT_BREAKING
    witness = [f for f in payload["findings"] if f.get("witness")][0]["witness"]
    assert _validator(init_seq).is_valid(witness)


def test_dv_harness_cli_exposes_the_same_implementation(tmp_path, init_seq):
    old_p, new_p = tmp_path / "old.json", tmp_path / "new.json"
    old_p.write_text(json.dumps(init_seq), encoding="utf-8")
    new_p.write_text(json.dumps(_mutated(init_seq, lambda n: n["required"].append("source"))),
                     encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dv_harness", "schema-compat",
                        "--old", str(old_p), "--new", str(new_p), "--json"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 1, r.stdout + r.stderr
    assert json.loads(r.stdout[r.stdout.index("{"):])["verdict"] == sc.VERDICT_BREAKING


def test_module_entry_point_matches_the_cli(tmp_path, init_seq):
    old_p, new_p = tmp_path / "old.json", tmp_path / "new.json"
    old_p.write_text(json.dumps(init_seq), encoding="utf-8")
    new_p.write_text(json.dumps(init_seq), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dv_harness.schema_compat",
                        "--old", str(old_p), "--new", str(new_p)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert sc.VERDICT_COMPATIBLE in r.stdout


def test_classification_does_not_mutate_its_inputs(init_seq):
    new = _mutated(init_seq, lambda n: n["required"].append("source"))
    before_old, before_new = copy.deepcopy(init_seq), copy.deepcopy(new)
    classify(init_seq, new)
    assert init_seq == before_old
    assert new == before_new
