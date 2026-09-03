"""dv_harness_tests/test_mcp_claude_md_index.py -- proves the CLAUDE.md MCP
index (the `## MCP Query Interface: the 5 Verbs (index)` section) is real,
correct, and cannot silently drift from the code it indexes.

Three layers of proof, because "the docs say 5 verbs" is worth nothing on
its own:

  1. NON-DRIFT (the real file): `assert_index_matches_code()` runs against
     the REAL repo CLAUDE.md and the REAL verbs/schemas/query shapes. This
     is the assertion that fails the day someone adds a 6th verb, renames a
     required parameter, or moves the evidence DB.

  2. THE CHECKER ACTUALLY CHECKS: every drift class is exercised by MUTATING
     a copy of the real section and asserting the checker reports that exact
     problem. Without this a checker that returned `[]` unconditionally
     would pass layer 1 forever.

  3. THE INDEX'S CLAIMS ARE TRUE END-TO-END: every verb the index advertises
     is really callable through a real `ReadOnlyMcpContext` over a real
     on-disk manifest, with exactly the required arguments the index shows
     (and omitting a documented-required argument really fails). An index
     that routed an agent to a verb that does not work would pass layers 1
     and 2 and still be useless.
"""
from __future__ import annotations

import json

import pytest

from dv_harness.mcp import claude_md_index as idx
from dv_harness.mcp import regression_queries, schema, verbs
from dv_harness.mcp.errors import McpValidationError
from dv_harness.mcp.runtime import ReadOnlyMcpContext
from dv_harness_tests.mcp_manifest_fixture import build_fixture_manifest


@pytest.fixture(scope="module")
def real_doc_text() -> str:
    return idx.DOC_PATH.read_text(encoding="utf-8")


# ---- layer 1: the real CLAUDE.md matches the real code ----------------------

def test_real_claude_md_has_the_index_section(real_doc_text):
    section = idx.extract_section(real_doc_text)
    assert section.splitlines()[0].startswith(idx.INDEX_HEADING)
    # An index must be an INDEX: it points at the schemas rather than
    # inlining them, so it stays cheap to keep always-resident.
    assert "dv_harness/mcp/schema.py" in section


def test_real_claude_md_index_matches_code(real_doc_text):
    """The load-bearing non-drift assertion."""
    idx.assert_index_matches_code(real_doc_text)
    assert idx.check_index(real_doc_text) == []


def test_index_rows_are_exactly_the_five_verbs(real_doc_text):
    parsed = idx.parse_index(real_doc_text)
    assert set(parsed["verbs"]) == set(verbs.VERBS)
    assert len(parsed["verbs"]) == 5


def test_index_required_args_match_the_real_param_schemas(real_doc_text):
    parsed = idx.parse_index(real_doc_text)
    for verb, documented in parsed["verbs"].items():
        real = schema.PARAM_SCHEMAS[verb].get("required", [])
        assert sorted(documented) == sorted(real), verb
    # The two verbs that really do require an argument are exactly these.
    assert {v for v, a in parsed["verbs"].items() if a} == {"get_dut_port", "query_regression"}


def test_index_query_shapes_match_the_real_fixed_shapes(real_doc_text):
    parsed = idx.parse_index(real_doc_text)
    assert sorted(parsed["query_shapes"]) == sorted(regression_queries.QUERY_SHAPES)


def test_index_fact_sources_are_the_two_real_code_owned_paths(real_doc_text):
    parsed = idx.parse_index(real_doc_text)
    assert sorted(set(parsed["fact_source_paths"])) == sorted(idx.fact_source_paths())
    assert len(idx.fact_source_paths()) == 2
    # Both derived from code, not retyped in this test.
    assert idx.manifest_rel_path().endswith("env.manifest.json")
    assert idx.evidence_db_rel_path().endswith("evidence.duckdb")


def test_index_server_invocation_names_a_real_module_and_real_flags(real_doc_text):
    parsed = idx.parse_index(real_doc_text)
    assert parsed["server_module"] == idx.SERVER_MODULE
    module_file = idx.REPO_ROOT / (idx.SERVER_MODULE.replace(".", "/") + ".py")
    assert module_file.is_file()
    real_flags = idx._real_server_flags()
    for flag in idx.SERVER_FLAGS:
        assert flag in parsed["server_flags"]
        assert flag in real_flags


def test_index_routes_the_protocol_question_instead_of_inlining_a_list(real_doc_text):
    """CLAUDE.md must not carry a hardcoded protocol list -- that is a
    manifest fact, and inlining it is the "details, not index" bloat the
    file's own contract forbids."""
    parsed = idx.parse_index(real_doc_text)
    assert parsed["protocol_routing_verb"] == idx.PROTOCOL_ROUTING_VERB == "get_vip_config"


# ---- layer 2: the checker really catches each drift class -------------------

def _mutate(text: str, old: str, new: str) -> str:
    assert old in text, f"fixture text no longer contains {old!r}"
    return text.replace(old, new, 1)


def test_missing_section_is_reported_not_silently_passed():
    with pytest.raises(idx.ClaudeMdIndexError) as e:
        idx.assert_index_matches_code("# Some other file\n\n## Unrelated\n\ntext\n")
    assert e.value.reason == "INDEX_SECTION_MISSING"


def test_a_sixth_verb_in_code_with_no_index_row_is_caught(real_doc_text, monkeypatch):
    monkeypatch.setitem(verbs.VERBS, "get_something_new", lambda *a, **k: {})
    problems = idx.check_index(real_doc_text)
    assert any("get_something_new" in p and "no row" in p for p in problems)


def test_an_index_row_for_a_nonexistent_verb_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "| `get_topology` |", "| `get_teleport` |")
    problems = idx.check_index(mutated)
    assert any("get_teleport" in p and "not in verbs.VERBS" in p for p in problems)
    assert any("get_topology" in p and "no row" in p for p in problems)


def test_a_wrong_required_arg_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "verible-parsed, with the source sha256 | `module_name` |",
                      "verible-parsed, with the source sha256 | `module` |")
    problems = idx.check_index(mutated)
    assert any(p.startswith("verb 'get_dut_port'") for p in problems), problems


def test_a_dropped_required_arg_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "verible-parsed, with the source sha256 | `module_name` |",
                      "verible-parsed, with the source sha256 | *(none)* |")
    problems = idx.check_index(mutated)
    assert any("get_dut_port" in p and "module_name" in p for p in problems), problems


def test_a_stale_query_shape_list_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "`by_date_range` |", "`by_moon_phase` |")
    problems = idx.check_index(mutated)
    assert any("query_regression" in p and "QUERY_SHAPES" in p for p in problems), problems


def test_a_wrong_fact_source_path_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "- `.dv-harness/evidence/evidence.duckdb`",
                      "- `.dv-harness/evidence.sqlite`")
    problems = idx.check_index(mutated)
    assert any("read-only fact sources" in p for p in problems), problems


def test_a_third_fact_source_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "- `.dv-harness/evidence/evidence.duckdb`",
                      "- `.dv-harness/secrets/keys.json` — extra\n- `.dv-harness/evidence/evidence.duckdb`")
    problems = idx.check_index(mutated)
    assert any("read-only fact sources" in p for p in problems), problems


def test_a_wrong_server_module_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "python -m dv_harness.mcp.server --manifest",
                      "python -m dv_harness.mcp.old_server --manifest")
    problems = idx.check_index(mutated)
    assert any("names module" in p for p in problems), problems


def test_an_invented_server_flag_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "--evidence-db .dv-harness/evidence/evidence.duckdb",
                      "--evidence-db .dv-harness/evidence/evidence.duckdb --allow-write")
    problems = idx.check_index(mutated)
    assert any("--allow-write" in p and "does not define" in p for p in problems), problems


def test_every_detail_document_the_index_cites_really_exists(real_doc_text):
    """"Details on demand" is only a real contract if the pointers resolve."""
    cited = idx.cited_detail_paths(real_doc_text)
    assert cited, "the index must point somewhere for detail"
    for rel in cited:
        assert (idx.REPO_ROOT / rel).exists(), rel
    # The two that carry this interface's actual detail.
    assert "dv_harness/mcp/schema.py" in cited
    assert ".work/mcp-server-report.md" in cited


def test_a_dead_detail_citation_is_caught(real_doc_text):
    mutated = _mutate(real_doc_text, "`.work/mcp-server-report.md`",
                      "`.work/mcp-server-report-that-was-deleted.md`")
    problems = idx.check_index(mutated)
    assert any("dead citation" in p for p in problems), problems


def test_inlining_a_protocol_list_instead_of_routing_is_caught(real_doc_text):
    mutated = _mutate(
        real_doc_text,
        "file — call `get_vip_config` with no arguments and read the `vip_type` of each captured instance.",
        "file. Protocols: usb, pcie, ethernet, mipi, canfd, amba.")
    problems = idx.check_index(mutated)
    assert any("must ROUTE" in p for p in problems), problems


# ---- layer 3: the index's routing claims are true end-to-end ---------------

@pytest.fixture()
def real_context(tmp_path):
    """A real ReadOnlyMcpContext over a real on-disk manifest file -- not a
    mock and not an in-memory dict."""
    manifest_path = tmp_path / "env.manifest.json"
    manifest_path.write_text(json.dumps(build_fixture_manifest()), encoding="utf-8")
    return ReadOnlyMcpContext(manifest_path, tmp_path / "evidence" / "evidence.duckdb")


def test_every_indexed_verb_is_really_callable(real_doc_text, real_context):
    """Each verb the index advertises answers, through the real runtime,
    when called with exactly the arguments the index says are required."""
    parsed = idx.parse_index(real_doc_text)
    minimal_args = {
        "get_dut_port": {"module_name": "usb3_ctrl"},
        "query_regression": {"query_shape": "latest"},
    }
    for verb in parsed["verbs"]:
        params = minimal_args.get(verb, {})
        result = real_context.call(verb, params)
        assert result["verb"] == verb
        # Every key that verb's real RESULT schema calls required must be
        # present -- derived from the schema, not retyped, so this stays
        # true when a result envelope changes. (get_topology deliberately
        # carries two sub-layer statuses instead of one `status`; asserting
        # a hardcoded "status" here would be wrong for it.)
        for key in schema.RESULT_SCHEMAS[verb]["required"]:
            assert key in result, (verb, key)


def test_omitting_a_documented_required_arg_really_fails(real_doc_text, real_context):
    """The index's "required args" column is load-bearing, not decorative:
    calling without them raises rather than quietly returning something."""
    parsed = idx.parse_index(real_doc_text)
    for verb, required in parsed["verbs"].items():
        if not required:
            continue
        with pytest.raises(McpValidationError):
            real_context.call(verb, {})


def test_get_vip_config_with_no_args_really_answers_the_protocol_question(real_context):
    """The index routes "which protocols exist" here; prove that route
    actually returns the per-instance vip_type an agent is told to read."""
    result = real_context.call("get_vip_config", {})
    assert result["status"] == "CAPTURED"
    assert result["match_count"] == len(result["instances"]) >= 1
    vip_types = [i["vip_type"] for i in result["instances"]]
    assert all(isinstance(v, str) and v for v in vip_types)
    assert "usb3_vip_config" in vip_types


def test_a_verb_outside_the_index_is_refused(real_context):
    """The index's "there are exactly 5, no free-text fallback" rule, proved
    against the real runtime rather than asserted in prose."""
    from dv_harness.mcp.errors import McpUnknownVerbError

    with pytest.raises(McpUnknownVerbError):
        real_context.call("read_file", {"path": "CLAUDE.md"})


def test_module_main_exits_zero_on_the_real_repo(capsys):
    assert idx.main([]) == 0
    assert "OK" in capsys.readouterr().out
