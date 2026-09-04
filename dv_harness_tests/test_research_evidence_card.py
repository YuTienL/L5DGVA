"""Tests for the ResearchEvidenceCard contract and its mechanical builder.

Two halves, matching the two halves of the card itself:

1. `dv_harness/schemas/research_evidence_card.schema.json` really REJECTS the
   things the master prompt (sections 8/9) says must never pass -- a missing
   required field, an invented claim_type, a FACT with no supporting evidence,
   a non-FACT with no open verification requirement, and an "L5 has nothing
   like this" recorded without saying where anyone looked. A schema whose
   constraints are only described in its own `description` strings is prose
   with extra syntax, so each rule gets a case that fails without it.

2. `doc_extraction.build_research_evidence_card_skeleton()` produces a REAL
   skeleton for a REAL file on disk: the sha256 is the hash of the actual
   bytes (re-computed here with plain hashlib, not read back from the same
   function under test), `document_id` is derived from it, `source_provenance`
   is byte-identical to what the pre-existing `evidence_ref()` returns for the
   same inputs, and the document really lands in the real `DocumentIndex`.

Plus the seam between them: a skeleton is deliberately INVALID, its gap list is
exactly the LLM-authored field set, and filling exactly that set makes it valid.
That is the contract that keeps a half-filled card from looking finished.

The skill file is held to the code it teaches, same discipline as
test_memory_review_skill.py and source_authority.assert_doc_matches_code():
every symbol `research-ingestion/SKILL.md` cites by name must really exist.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dv_harness import doc_extraction as dx  # noqa: E402
from dv_harness import inference  # noqa: E402

SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "research-ingestion" / "SKILL.md"
RESEARCH_DIR = REPO_ROOT / "research"

# The nine sections every mechanics-bearing skill in this tree carries, taken
# from real siblings rather than from a style guide.
SIBLING_SKILLS = [
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-link" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-retrieval" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-consolidation" / "SKILL.md",
]
_SECTION_RE = re.compile(r"^\*\*([A-Za-z /]+)\*\*:", re.MULTILINE)

DOC_TEXT = (
    "# Semantic Change Impact Analysis for RTL Verification\n\n"
    "We reduce selected regression size by 62% with no missed failures.\n"
)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        import os as _os, stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_on_rm_error, ignore_errors=True)


def _write_doc(root: Path, name: str = "semantic_change_impact.md", text: str = DOC_TEXT) -> Path:
    src = root / "sources"
    src.mkdir(parents=True, exist_ok=True)
    p = src / name
    p.write_text(text, encoding="utf-8")
    return p


def _ref(page: str = "7", section: str = "5.2 Results", location: str = "Table 3") -> dict:
    return dx.evidence_ref(document="semantic_change_impact.md", version="rev 1.1",
                           page=page, section=section, location=location)


def _l5_match(matches=None, basis="grep -rn over dv_harness/ and .claude/skills/") -> dict:
    return {"matches": list(matches or []), "search_basis": basis}


def _analytical_half() -> dict:
    """A complete, honest ANALYTICAL half -- the part the skill authors by
    reading. Kept as one function so every rejection test below starts from a
    card that really validates, and therefore proves the ONE mutation it makes
    is what caused the failure."""
    return {
        "authors": ["A. Researcher", "B. Coauthor"],
        "date": "2025-11",
        "verification_domain": ["regression selection", "change impact"],
        "problem_statement": "Full regression after every RTL edit costs more compute than the edit's blast radius justifies.",
        "core_method": "Build a module-level dependency graph from the elaborated netlist, diff two revisions semantically rather than textually, and select only tests reaching a changed cone.",
        "architecture_pattern": {
            "input": "Two RTL revisions plus the existing test-to-module coverage map",
            "transformation": "Semantic diff over the elaborated dependency graph",
            "decision": "Rank tests by whether they reach a changed cone",
            "tool": "Commercial elaborator plus the authors' graph differ",
            "evidence": "Selected-vs-full regression pass/fail comparison",
            "next_action": "Run the selected subset; fall back to full on an unresolved node",
        },
        "key_mechanisms": ["Semantic Delta", "Graph Reasoning", "Regression Ranking"],
        "inputs": ["two RTL revisions", "test-to-module coverage map"],
        "outputs": ["ranked selected regression list", "unreachable-node report"],
        "ai_role": "NONE -- selection is graph reachability, no model is involved.",
        "deterministic_tool_role": "Elaborator supplies the dependency graph; the regression database supplies pass/fail. Both oracles are deterministic.",
        "eda_tools": ["a commercial elaborator (unnamed in the paper)"],
        "feedback_loop": {
            "hypothesis": "The changed cone bounds which tests can newly fail",
            "evidence_needed": "Pass/fail of the excluded tests on the new revision",
            "tool_action": "Run full regression once as a control",
            "observation": "No excluded test changed verdict across 4 designs",
            "confidence_update": "Raised from proposal to measured on the authors' own set",
            "gap": "No design with a known escape was included",
            "next_best_action": "Repeat against a regression with seeded escapes",
        },
        "quantitative_results": [{
            "metric": "selected regression size vs full",
            "value": "62%",
            "unit": "percent reduction",
            "context": "mean over 4 internal designs, 900-2400 tests each, against full regression",
            "source_location": _ref(),
        }],
        "limitations": [
            {"tag": "SMALL_BENCHMARK", "detail": "4 designs, all from the authors' own organization."},
            {"tag": "NO_INDEPENDENT_REPRODUCTION", "detail": "No third party has re-run the method; the tool is not released."},
            {"tag": "VENDOR_DEPENDENCY", "detail": "Requires an elaborator that emits a full dependency graph; the paper does not name it."},
        ],
        "assumptions": ["The test-to-module coverage map is complete and current."],
        "maturity": "PROTOTYPE",
        "production_relevance": {
            "level": "HIGH",
            "explanation": "Regression cost is a real bottleneck here, and this harness already computes a 3-tier selection in change_impact.py that this could inform.",
        },
        "evidence_strength": {
            "scale": 3,
            "rationale": "A controlled comparison against full regression on 4 real designs -- more than a demo, less than production deployment or independent replication.",
        },
        "confidence": "MEDIUM",
        "claim_set": [
            {
                "claim_text": "Semantic change impact reduced the selected regression by 62% with no missed failures.",
                "claim_type": "AUTHOR_CLAIM",
                "source_location": _ref(),
                "supporting_evidence": ["Table 3: 62% selection reduction over 4 designs"],
                "confidence": "MEDIUM",
                "uncertainty": "'No missed failures' is measured only on the authors' own 4-design set, with no seeded escapes.",
                "verification_requirement": "Re-run against change_impact.select_regression()'s TARGETED/DEPENDENCY/SAFETY output on a regression with known escapes.",
            },
            {
                "claim_text": "The elaborated dependency graph is derived by the tool, not hand-authored.",
                "claim_type": "FACT",
                "source_location": _ref(page="4", section="3.1 Graph construction", location="Figure 2"),
                "supporting_evidence": ["Figure 2 shows the elaborator invocation and its emitted graph format"],
                "confidence": "HIGH",
                "uncertainty": "NONE",
                "verification_requirement": None,
            },
            {
                "claim_text": "This method would compose with this harness's existing NO-SHRINK selection gate rather than replace it.",
                "claim_type": "INFERENCE",
                "source_location": _ref(page="9", section="6 Discussion", location=""),
                "supporting_evidence": [],
                "confidence": "LOW",
                "uncertainty": "The paper never discusses a safety-tier fallback, so composition is this reader's reading, not the authors'.",
                "verification_requirement": "Check regression_selection_completeness_gate.py's NO-SHRINK rule against a selection this method would produce.",
            },
        ],
        "candidate_l5_mapping": {
            "existing_agent": _l5_match([], "read .claude/agents/ROSTER.md in full; no agent owns regression selection"),
            "existing_skill": _l5_match(["CORE/verification-change-impact"], "ls .claude/skills/CORE plus read that SKILL.md"),
            "existing_graph_node": _l5_match(["REGRESSION_SELECT", "CHANGE_IMPACT"], "grep STAGE_GATES in dv_harness/gates.py"),
            "existing_blackboard_object": _l5_match([], "read dv_harness/blackboard.py; topics are findings/debug_loop_history only"),
            "existing_memory_layer": _l5_match([], "read dv_harness/memory.py MEMORY_LEVELS; no selection-history tier"),
            "existing_evidence_mechanism": _l5_match(
                ["dv_harness/change_impact.py compute_change_impact()/select_regression()"],
                "read dv_harness/change_impact.py in full"),
            "possible_enhancement": "Feed a semantic (not file-level) delta into change_impact.file_to_module_map(); candidate only, not a decision.",
        },
        "related_prior_research": [],
        "contradictions": [],
    }


def _valid_card(tmp: Path) -> dict:
    doc = _write_doc(tmp)
    card = dx.build_research_evidence_card_skeleton(
        doc, tmp, title="Semantic Change Impact Analysis for RTL Verification",
        source="arXiv:2501.00000", document_type="ARXIV_PAPER", version="rev 1.1")
    card.update(_analytical_half())
    return card


# --- 1. the schema is a real contract ---------------------------------------

def test_schema_itself_is_a_valid_draft_2020_12_schema():
    import jsonschema
    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_a_fully_filled_card_validates():
    """The baseline every rejection test below mutates from. Without this, a
    'schema rejects X' test proves only that something was wrong."""
    tmp = _tmp()
    try:
        dx.validate_research_evidence_card(_valid_card(tmp))
    finally:
        _rmtree(tmp)


@pytest.mark.parametrize("field", ["claim_set", "candidate_l5_mapping", "evidence_strength",
                                   "document_sha256", "maturity", "problem_statement"])
def test_schema_rejects_a_card_missing_a_required_field(field):
    tmp = _tmp()
    try:
        card = _valid_card(tmp)
        del card[field]
        with pytest.raises(dx.ResearchEvidenceCardValidationError) as exc:
            dx.validate_research_evidence_card(card)
        assert field in str(exc.value)
    finally:
        _rmtree(tmp)


def test_schema_rejects_an_invented_claim_type():
    """FACT/AUTHOR_CLAIM/INFERENCE/HYPOTHESIS is a closed enum (master prompt
    section 9) -- a fifth value would let a reader route around the whole
    classification discipline by naming a softer category."""
    tmp = _tmp()
    try:
        card = _valid_card(tmp)
        card["claim_set"][0]["claim_type"] = "OPINION"
        with pytest.raises(dx.ResearchEvidenceCardValidationError) as exc:
            dx.validate_research_evidence_card(card)
        assert "claim_set/0/claim_type" in str(exc.value)
    finally:
        _rmtree(tmp)


def test_schema_rejects_a_fact_carrying_no_supporting_evidence():
    """Half of 'Never silently convert AUTHOR_CLAIM into FACT': relabelling an
    unsupported claim as FACT must cost something."""
    tmp = _tmp()
    try:
        card = _valid_card(tmp)
        fact = next(c for c in card["claim_set"] if c["claim_type"] == "FACT")
        fact["supporting_evidence"] = []
        with pytest.raises(dx.ResearchEvidenceCardValidationError) as exc:
            dx.validate_research_evidence_card(card)
        assert "supporting_evidence" in str(exc.value)
    finally:
        _rmtree(tmp)


@pytest.mark.parametrize("claim_type", ["AUTHOR_CLAIM", "INFERENCE", "HYPOTHESIS"])
def test_schema_rejects_a_non_fact_claim_with_no_open_verification_requirement(claim_type):
    """The other half: everything that is not a FACT is by construction
    unresolved, so it must say what would resolve it."""
    tmp = _tmp()
    try:
        card = _valid_card(tmp)
        claim = card["claim_set"][0]
        claim["claim_type"] = claim_type
        claim["verification_requirement"] = None
        with pytest.raises(dx.ResearchEvidenceCardValidationError) as exc:
            dx.validate_research_evidence_card(card)
        assert "verification_requirement" in str(exc.value)
    finally:
        _rmtree(tmp)


def test_schema_rejects_an_empty_l5_match_with_no_stated_search():
    """'Do not assume absence' (master prompt section 8). An empty `matches` is
    the claim that most needs its search shown, so search_basis is required
    exactly when it is easiest to skip."""
    tmp = _tmp()
    try:
        card = _valid_card(tmp)
        card["candidate_l5_mapping"]["existing_agent"] = {"matches": [], "search_basis": ""}
        with pytest.raises(dx.ResearchEvidenceCardValidationError) as exc:
            dx.validate_research_evidence_card(card)
        assert "search_basis" in str(exc.value)
    finally:
        _rmtree(tmp)


def test_schema_rejects_an_unknown_limitation_tag_and_an_out_of_range_evidence_scale():
    tmp = _tmp()
    try:
        base = _valid_card(tmp)

        card = copy.deepcopy(base)
        card["limitations"][0]["tag"] = "SMALLISH_BENCHMARK"
        with pytest.raises(dx.ResearchEvidenceCardValidationError):
            dx.validate_research_evidence_card(card)

        card = copy.deepcopy(base)
        card["evidence_strength"]["scale"] = 6
        with pytest.raises(dx.ResearchEvidenceCardValidationError):
            dx.validate_research_evidence_card(card)
    finally:
        _rmtree(tmp)


def test_schema_suffix_enum_equals_the_module_s_own_allowlist():
    """The schema says document_suffix "must equal
    doc_extraction.RESEARCH_DOCUMENT_SUFFIXES". A description that says two
    lists are equal is worth nothing unless something compares them."""
    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["$defs"]["document_suffix"]["enum"]) == set(dx.RESEARCH_DOCUMENT_SUFFIXES)
    assert dx.RESEARCH_DOCUMENT_SUFFIXES < dx.SUPPORTED, \
        "research ingestion must be a strict narrowing of the module's existing allowlist"


def test_confidence_vocabulary_is_inference_dot_py_s_plus_unknown():
    """Master prompt section 10 forbids a parallel research inference engine.
    This repo already carries a real 3-vs-4-level confidence ambiguity; a third
    vocabulary here would compound it."""
    dx.assert_confidence_vocabulary_reused()
    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    enum = schema["$defs"]["confidence_level"]["enum"]
    assert [v for v in enum if v != "UNKNOWN"] == list(inference.CONFIDENCE_LEVELS)


# --- 2. the mechanical builder is real --------------------------------------

def test_skeleton_carries_the_real_sha256_and_a_document_id_derived_from_it():
    tmp = _tmp()
    try:
        doc = _write_doc(tmp)
        expected = hashlib.sha256(doc.read_bytes()).hexdigest()
        card = dx.build_research_evidence_card_skeleton(doc, tmp)
        assert card["document_sha256"] == expected
        assert card["document_id"] == f"DOC-{expected[:12]}"
        # Compared against the bytes really on disk, not against len(DOC_TEXT):
        # this repo runs on Windows, where write_text() translates newlines, so
        # the source string's length is not the file's size.
        assert card["document_bytes"] == doc.stat().st_size == len(doc.read_bytes())
        assert card["document_path"] == str(doc.resolve())
        assert card["document_suffix"] == ".md"
    finally:
        _rmtree(tmp)


def test_skeleton_source_provenance_is_exactly_evidence_ref_s_output():
    """The card reuses doc_extraction.evidence_ref()'s existing 5-key shape
    rather than a research-specific provenance dict -- asserted by calling that
    function directly and comparing, so a divergence is a test failure."""
    tmp = _tmp()
    try:
        doc = _write_doc(tmp)
        digest = hashlib.sha256(doc.read_bytes()).hexdigest()
        card = dx.build_research_evidence_card_skeleton(doc, tmp)
        assert card["source_provenance"] == dx.evidence_ref(
            document=doc.name, version=f"sha256:{digest}",
            page="", section="", location=str(doc.resolve()))
        assert set(card["source_provenance"]) == {
            "document", "version", "page", "section", "source_location"}
    finally:
        _rmtree(tmp)


def test_a_supplied_document_version_replaces_the_hash_fallback():
    tmp = _tmp()
    try:
        doc = _write_doc(tmp)
        card = dx.build_research_evidence_card_skeleton(doc, tmp, version="rev 1.1")
        assert card["source_provenance"]["version"] == "rev 1.1"
        # ...and the hash identity is still carried, on its own field.
        assert card["document_sha256"] == hashlib.sha256(doc.read_bytes()).hexdigest()
    finally:
        _rmtree(tmp)


def test_skeleton_registers_the_document_in_the_real_document_index():
    """The skeleton builder is DocumentIndex's first real caller. An unchanged
    document must be recognised as already indexed; an edited one must not."""
    tmp = _tmp()
    try:
        doc = _write_doc(tmp)
        idx = dx.DocumentIndex(tmp)
        assert idx.needs_extract(doc) is True

        card = dx.build_research_evidence_card_skeleton(doc, tmp, document_type="ARXIV_PAPER")
        assert dx.DocumentIndex(tmp).needs_extract(doc) is False

        row = next(r for r in dx.DocumentIndex(tmp).load() if r["path"] == str(doc.resolve()))
        assert row["kind"] == dx.RESEARCH_DOCUMENT_INDEX_KIND
        assert row["metadata"]["document_id"] == card["document_id"]
        assert row["metadata"]["document_type"] == "ARXIV_PAPER"

        doc.write_text(DOC_TEXT + "\nAn added paragraph changes the content hash.\n", encoding="utf-8")
        assert dx.DocumentIndex(tmp).needs_extract(doc) is True
        assert dx.build_research_evidence_card_skeleton(doc, tmp)["document_id"] != card["document_id"]
    finally:
        _rmtree(tmp)


def test_register_false_leaves_the_index_untouched():
    tmp = _tmp()
    try:
        doc = _write_doc(tmp)
        dx.build_research_evidence_card_skeleton(doc, tmp, register=False)
        assert dx.DocumentIndex(tmp).load() == []
    finally:
        _rmtree(tmp)


def test_builder_refuses_a_design_input_and_a_missing_file():
    """RESEARCH_DOCUMENT_SUFFIXES is narrower than SUPPORTED on purpose: an .sv
    file arriving here means the caller took the wrong ingestion path."""
    tmp = _tmp()
    try:
        rtl = _write_doc(tmp, name="usb_ctrl.sv", text="module usb_ctrl; endmodule\n")
        assert rtl.suffix in dx.SUPPORTED and rtl.suffix not in dx.RESEARCH_DOCUMENT_SUFFIXES
        with pytest.raises(dx.ResearchIngestionError) as exc:
            dx.build_research_evidence_card_skeleton(rtl, tmp)
        assert ".sv" in str(exc.value)

        with pytest.raises(dx.ResearchIngestionError):
            dx.build_research_evidence_card_skeleton(tmp / "sources" / "absent.pdf", tmp)
    finally:
        _rmtree(tmp)


# --- 3. the seam: a skeleton is honestly unfinished --------------------------

def test_a_skeleton_does_not_validate_and_names_what_is_owed():
    tmp = _tmp()
    try:
        card = dx.build_research_evidence_card_skeleton(_write_doc(tmp), tmp)
        with pytest.raises(dx.ResearchEvidenceCardValidationError):
            dx.validate_research_evidence_card(card)
        assert dx.research_card_missing_fields(card) == list(dx.RESEARCH_CARD_LLM_AUTHORED_FIELDS)
    finally:
        _rmtree(tmp)


def test_the_gap_is_computed_by_the_existing_inference_engine():
    """Master prompt section 10: reuse dv_harness.inference, do not build a
    research inference engine. Asserted by re-deriving the same answer from
    inference.identify_gap() directly."""
    tmp = _tmp()
    try:
        card = dx.build_research_evidence_card_skeleton(_write_doc(tmp), tmp)
        assert dx.research_card_missing_fields(card) == inference.identify_gap(
            dx.research_card_required_fields(), sorted(card.keys()))
    finally:
        _rmtree(tmp)


def test_the_two_field_halves_are_exactly_the_schema_s_required_list():
    """Mechanical + LLM-authored must partition `required` -- so adding a field
    to the schema without deciding which half owns it fails here rather than
    silently landing in neither worklist."""
    mech = set(dx.RESEARCH_CARD_MECHANICAL_FIELDS)
    llm = set(dx.RESEARCH_CARD_LLM_AUTHORED_FIELDS)
    assert not (mech & llm)
    assert mech | llm == set(dx.research_card_required_fields())
    assert len(dx.RESEARCH_CARD_MECHANICAL_FIELDS) == len(mech)
    assert len(dx.RESEARCH_CARD_LLM_AUTHORED_FIELDS) == len(llm)


def test_a_skeleton_plus_exactly_the_analytical_half_validates():
    """End to end: the builder's output and the schema really agree, and the
    skill's worklist is sufficient -- filling exactly the gap list, and nothing
    else, produces a valid card."""
    tmp = _tmp()
    try:
        card = dx.build_research_evidence_card_skeleton(
            _write_doc(tmp), tmp, document_type="ARXIV_PAPER", version="rev 1.1")
        analytical = _analytical_half()
        assert sorted(analytical) == sorted(dx.research_card_missing_fields(card))
        card.update(analytical)
        dx.validate_research_evidence_card(card)
        assert dx.research_card_missing_fields(card) == []
    finally:
        _rmtree(tmp)


def test_the_mechanical_half_is_never_left_to_the_llm():
    """Nothing an LLM authors may be one of the identity fields."""
    for field in ("document_id", "document_sha256", "document_path", "source_provenance"):
        assert field in dx.RESEARCH_CARD_MECHANICAL_FIELDS
        assert field not in dx.RESEARCH_CARD_LLM_AUTHORED_FIELDS


# --- 4. the skill and the store are held to the code ------------------------

def test_skill_file_exists_and_declares_its_own_name():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert re.search(r"^name: research-ingestion$", text, re.MULTILINE)


def test_skill_carries_the_same_mechanics_sections_as_its_siblings():
    mine = set(_SECTION_RE.findall(SKILL_PATH.read_text(encoding="utf-8")))
    for sibling in SIBLING_SKILLS:
        expected = set(_SECTION_RE.findall(sibling.read_text(encoding="utf-8")))
        assert expected <= mine, f"missing section(s) {sorted(expected - mine)} that {sibling.name} carries"


def test_skill_is_discoverable_under_the_name_it_declares():
    """SkillResolver indexes by the SKILL.md's parent directory name, so the
    directory name is the address other assets will bind."""
    from dv_harness.skill_resolver import SkillResolver
    resolved = SkillResolver(REPO_ROOT).resolve(["research-ingestion"])[0]
    assert resolved["found"] is True
    assert Path(resolved["path"]) == SKILL_PATH.relative_to(REPO_ROOT)


def test_every_code_symbol_the_skill_cites_actually_exists():
    text = SKILL_PATH.read_text(encoding="utf-8")
    for name in ("build_research_evidence_card_skeleton", "research_card_missing_fields",
                 "validate_research_evidence_card", "evidence_ref", "sha256_file",
                 "RESEARCH_DOCUMENT_SUFFIXES", "RESEARCH_CARD_LLM_AUTHORED_FIELDS",
                 "DocumentIndex"):
        assert name in text, f"SKILL.md stopped citing {name}"
        assert hasattr(dx, name), f"doc_extraction.{name} does not exist"
    assert "identify_gap" in text and hasattr(inference, "identify_gap")
    assert str(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.relative_to(REPO_ROOT)).replace("\\", "/") in text


def test_skill_states_all_four_responsibility_boundaries():
    """Master prompt section 6's four explicit non-responsibilities. A skill
    that teaches the happy path without the boundary is the failure mode this
    whole tree is guarding against."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    for phrase in ("deciding final L5 architecture", "cross-paper synthesis",
                   "modifying production code", "declaring verification PASS"):
        assert phrase in text


def test_the_card_store_exists_with_its_naming_convention_documented():
    store = RESEARCH_DIR / "evidence_cards"
    assert (RESEARCH_DIR / "README.md").is_file()
    readme = (store / "README.md").read_text(encoding="utf-8")
    for stem in ("paper_001", "standard_001", "vendor_report_001"):
        assert stem in readme, f"section-27 naming example {stem} is not documented"
    assert ".card.json" in readme
    # Stage boundary: Stage 1 installs the machinery, Stage 2 fills the store.
    assert [p for p in store.iterdir() if p.name != "README.md"] == []


def test_the_research_readme_points_at_files_that_really_exist():
    text = (RESEARCH_DIR / "README.md").read_text(encoding="utf-8")
    for rel in (".claude/skills/research-ingestion/SKILL.md",
                "dv_harness/schemas/research_evidence_card.schema.json",
                "dv_harness/doc_extraction.py",
                "dv_harness/inference.py",
                "dv_harness_tests/test_research_evidence_card.py"):
        assert rel in text, f"research/README.md stopped citing {rel}"
        assert (REPO_ROOT / rel).is_file(), f"research/README.md cites a missing {rel}"
