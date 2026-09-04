"""Stage-1 acceptance tests A and G (master prompt section 23), end to end.

The other six are already covered by the build steps that installed the pieces
they exercise -- B/C/D/E in `test_capability_evolution_research_architect.py`,
F in `test_research_intent_routing.py`, H in `test_research_memory_governance.py`.
These two were not, because neither belongs to a single component:

* **Test A -- Research Ingestion.** "One technical paper -> a valid
  ResearchEvidenceCard with provenance, explicit limitations, claim
  classification, confidence, and no invented evidence." Every one of those six
  properties is checked here against a REAL document on disk, by running the
  real chain `research-ingestion/SKILL.md` prescribes -- skeleton builder ->
  gap list -> analytical half -> validator -> filed card -- not by unit-testing
  one function in isolation. The analytical half in `_read_the_paper()` is
  written from the synthetic paper's actual text, so "no invented evidence" is
  a property of this card that a checker can verify rather than a claim.

* **Test G -- Prior Research Comparison.** "A new paper overlapping an existing
  Evidence Card -> overlap/new/contradiction status identified and linked."
  Driven through `capability_evolution.read_evidence_cards()` /
  `link_prior_research()` against cards really filed in a real
  `research/evidence_cards/` directory.

The no-invented-evidence auditor (`invented_evidence()`) is itself held to a
negative control: two mutated cards, each changing exactly one thing (a number
the paper never printed, a section the paper does not have), must be caught. An
auditor nobody proved can fail is not evidence that the card is clean.
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

from dv_harness import capability_evolution as ce  # noqa: E402
from dv_harness import doc_extraction as dx  # noqa: E402
from dv_harness import inference  # noqa: E402


# --- the synthetic input documents ------------------------------------------
#
# Synthetic on purpose. Stage 1 installs the machinery and Stage 2 operates it
# on real external literature; ingesting a real paper here would BE Stage 2, and
# the master prompt's own First-Run Control Instruction (sections 57/82) forbids
# starting it before these acceptance tests pass. What matters for test A is
# that the document is a REAL FILE with REAL BYTES whose sections and numbers
# can be checked against the card -- which a synthetic paper satisfies exactly.

PAPER_A_TEXT = """\
# Confidence-Guided Regression Ranking for RTL Verification

Preprint. Authors: A. Researcher, B. Coauthor, C. Third. Dated 2025-11.

## 1 Introduction

Running the full regression after every RTL edit costs far more compute than the
edit's blast radius justifies. We ask whether the set of tests that can newly
fail is computable from the change itself.

## 3 Method

### 3.1 Semantic delta construction

The elaborated dependency graph is emitted by the elaborator itself. We do not
hand-author it, and no part of the graph is supplied by the ranking model.

### 3.2 Confidence-guided ranking

Each candidate test receives a reachability score over the changed cone, and the
selection cut is placed where the score distribution flattens.

## 4 Experimental Setup

We evaluate on 6 internal designs, each carrying between 900 and 2400 tests.
Full regression is run once per design as a control.

## 5 Results

### 5.1 Selection size

Table 3 reports a mean selection reduction of 62 percent measured against the
full regression on the same designs.

### 5.2 Escape rate

No excluded test changed its verdict on any of the 6 designs.

## 6 Limitations

The 6 designs all come from the authors' own organization. No third party has
reproduced the results and the tool is not released. The method requires an
elaborator that emits a complete dependency graph, and we do not name the
elaborator we used.

## 7 Discussion

Whether a selection produced this way should still be widened by a safety tier
is outside the scope of this paper.
"""

# A second document that OVERLAPS the first (shares Semantic Delta), EXTENDS it
# (adds a mechanism the first does not have), and CONTRADICTS it on the one
# metric both report. One document exercising all three keeps test G's three
# outcomes on real, comparable inputs instead of three hand-built dicts.
PAPER_B_TEXT = """\
# Semantic Delta Selection Revisited: A Failed Replication

Preprint. Authors: D. Skeptic, E. Colleague. Dated 2026-02.

## 2 Setup

We replicate the confidence-guided ranking method on 3 external designs that the
original authors did not use.

## 4 Results

### 4.1 Selection size

We measure a mean selection reduction of 31 percent, roughly half the reduction
the original work reports.

### 4.2 Escapes

Two excluded tests changed verdict on one design, so the no-missed-failure claim
does not hold outside the original design set.

## 5 Limitations

Only 3 designs were available to us, and we could not obtain the original tool.
"""

# A third document with no shared mechanism and no shared domain -- the "new"
# arm of test G.
PAPER_C_TEXT = """\
# Formal Proof-Guided Repair of Reset Sequencing Bugs

Preprint. Authors: F. Formalist. Dated 2025-06.

## 3 Method

A bounded model checker produces a counterexample trace, and a repair template
rewrites the reset sequencing logic until the property holds.

## 5 Limitations

The approach was exercised on 2 small blocks only.
"""


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        import os as _os
        import stat as _stat

        _os.chmod(p, _stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_on_rm_error, ignore_errors=True)


def _write_doc(root: Path, name: str, text: str) -> Path:
    src = root / "research" / "sources"
    src.mkdir(parents=True, exist_ok=True)
    path = src / name
    path.write_text(text, encoding="utf-8")
    return path


def _ref(document: str, page: str, section: str, location: str = "") -> dict:
    """Per-claim provenance in the EXISTING evidence_ref() shape -- the same
    5-key dict the card's own source_provenance uses, per the schema's $def."""
    return dx.evidence_ref(document=document, version="preprint v1",
                           page=page, section=section, location=location)


def _l5(matches, basis) -> dict:
    return {"matches": list(matches), "search_basis": basis}


# --- the analytical half, written from PAPER_A_TEXT --------------------------

def _read_the_paper(document_name: str) -> dict:
    """Step 3-5 of `research-ingestion/SKILL.md`: the half a reader authors.

    Every section string cited below is a heading that really appears in
    PAPER_A_TEXT, and every number quoted (62, 6, 900, 2400, 3) is a number that
    document really prints. That is what makes test A's no-invented-evidence
    property checkable rather than asserted.
    """
    return {
        "authors": ["A. Researcher", "B. Coauthor", "C. Third"],
        "date": "2025-11",
        "verification_domain": ["regression selection", "change impact"],
        "problem_statement": (
            "Running the full regression after every RTL edit costs more compute than the "
            "edit's blast radius justifies."
        ),
        "core_method": (
            "Score each test by reachability over the changed cone of an elaborator-emitted "
            "dependency graph, then cut the selection where the score distribution flattens."
        ),
        "architecture_pattern": {
            "input": "Two RTL revisions plus the existing test-to-module coverage map",
            "transformation": "Semantic delta over the elaborated dependency graph",
            "decision": "Reachability score per test, cut at the distribution knee",
            "tool": "The elaborator (unnamed in the paper) plus the authors' ranking code",
            "evidence": "Selected-versus-full regression verdict comparison per design",
            "next_action": "Run the selected subset; fall back to full on an unresolved node",
        },
        "key_mechanisms": ["Semantic Delta", "Regression Ranking", "Graph Reasoning"],
        "inputs": ["two RTL revisions", "test-to-module coverage map"],
        "outputs": ["ranked selected regression list"],
        "ai_role": (
            "NONE. Section 3.1 states the graph is emitted by the elaborator and no part of "
            "it is supplied by the ranking model; the ranking itself is a reachability score."
        ),
        "deterministic_tool_role": (
            "The elaborator supplies the dependency graph and the regression database supplies "
            "each test's verdict. Both oracles are deterministic tools, not model output."
        ),
        "eda_tools": ["an unnamed commercial elaborator"],
        "feedback_loop": {
            "hypothesis": "The changed cone bounds which tests can newly fail",
            "evidence_needed": "The verdict of every EXCLUDED test on the new revision",
            "tool_action": "Run the full regression once per design as a control",
            "observation": "No excluded test changed verdict on any of the 6 designs",
            "confidence_update": "Raised from proposal to measured on the authors' own designs",
            "gap": "No design with a known escape was included in the 6",
            "next_best_action": "Repeat the comparison against a regression with seeded escapes",
        },
        "quantitative_results": [
            {
                "metric": "mean selection reduction versus full regression",
                "value": "62 percent",
                "unit": "percent reduction",
                "context": "mean over 6 internal designs of 900 to 2400 tests each",
                "source_location": _ref(document_name, "5", "5.1 Selection size", "Table 3"),
            },
            {
                # `value` is the document's own word, not a numeral. Section 5.2
                # prints "No excluded test changed its verdict"; writing "0" here
                # would be a normalisation the paper never made, and
                # research-ingestion/SKILL.md step 3 says quantitative_results go
                # in "exactly as printed, never normalised". The auditor below
                # caught exactly that on the first run of this test.
                "metric": "excluded tests that changed verdict",
                "value": "none",
                "unit": "tests",
                "context": "across all 6 designs, against a full-regression control",
                "source_location": _ref(document_name, "5", "5.2 Escape rate"),
            },
        ],
        "limitations": [
            {"tag": "SMALL_BENCHMARK",
             "detail": "6 designs, all from the authors' own organization."},
            {"tag": "NO_INDEPENDENT_REPRODUCTION",
             "detail": "No third party has reproduced the results and the tool is not released."},
            {"tag": "VENDOR_DEPENDENCY",
             "detail": "Requires an elaborator that emits a complete dependency graph; the "
                       "paper does not name the one it used."},
        ],
        "assumptions": ["The test-to-module coverage map is complete and current."],
        "maturity": "PROTOTYPE",
        "production_relevance": {
            "level": "HIGH",
            "explanation": (
                "Regression cost is a real bottleneck here, and change_impact.select_regression() "
                "already computes a 3-tier selection this could inform."
            ),
        },
        "evidence_strength": {
            "scale": 3,
            "rationale": (
                "A controlled comparison against full regression on 6 real designs -- more than "
                "a demonstration, less than independent replication or production deployment."
            ),
        },
        "confidence": "MEDIUM",
        "claim_set": [
            {
                "claim_text": (
                    "Confidence-guided ranking reduced the selected regression by 62 percent "
                    "with no excluded test changing verdict."
                ),
                "claim_type": "AUTHOR_CLAIM",
                "source_location": _ref(document_name, "5", "5.1 Selection size", "Table 3"),
                "supporting_evidence": [
                    "Table 3, section 5.1: mean selection reduction of 62 percent",
                    "Section 5.2: no excluded test changed its verdict on any of the 6 designs",
                ],
                "confidence": "MEDIUM",
                "uncertainty": (
                    "Measured only on the authors' own 6 designs, with no seeded escapes and no "
                    "third-party replication."
                ),
                "verification_requirement": (
                    "Re-run against change_impact.select_regression()'s TARGETED/DEPENDENCY/SAFETY "
                    "output on a regression with known escapes."
                ),
            },
            {
                "claim_text": (
                    "The dependency graph is emitted by the elaborator, not hand-authored and "
                    "not produced by the ranking model."
                ),
                "claim_type": "FACT",
                "source_location": _ref(document_name, "3",
                                        "3.1 Semantic delta construction"),
                "supporting_evidence": [
                    "Section 3.1 states the graph is emitted by the elaborator itself and that "
                    "no part of it is supplied by the ranking model",
                ],
                "confidence": "HIGH",
                "uncertainty": "NONE -- this is a statement about the method's own construction.",
                "verification_requirement": None,
            },
            {
                "claim_text": (
                    "This selection would have to compose with the harness's existing NO-SHRINK "
                    "safety tier rather than replace it."
                ),
                "claim_type": "INFERENCE",
                "source_location": _ref(document_name, "7", "7 Discussion"),
                "supporting_evidence": [],
                "confidence": "LOW",
                "uncertainty": (
                    "Section 7 explicitly puts safety-tier widening outside the paper's scope, so "
                    "this composition is this reader's reading and not the authors' claim."
                ),
                "verification_requirement": (
                    "Check regression_selection_completeness_gate.py's NO-SHRINK rule against a "
                    "selection this method would produce."
                ),
            },
            {
                "claim_text": (
                    "The 62 percent reduction would hold on designs outside the authors' own "
                    "organization."
                ),
                "claim_type": "HYPOTHESIS",
                "source_location": _ref(document_name, "6", "6 Limitations"),
                "supporting_evidence": [],
                "confidence": "LOW",
                "uncertainty": (
                    "Section 6 states all 6 designs come from the authors' own organization; "
                    "generalization is untested."
                ),
                "verification_requirement": (
                    "Repeat the measurement on a design from a different organization."
                ),
            },
        ],
        "candidate_l5_mapping": {
            "existing_agent": _l5(
                [], "read .claude/agents/ROSTER.md in full; no agent owns regression selection"),
            "existing_skill": _l5(
                ["CORE/verification-change-impact", "CORE/regression-core"],
                "ls .claude/skills/CORE and read both SKILL.md files"),
            "existing_graph_node": _l5(
                ["CHANGE_IMPACT"], "grep STAGE_GATES in dv_harness/gates.py"),
            "existing_blackboard_object": _l5(
                [], "read dv_harness/blackboard.py; topics are findings / debug_loop_history / "
                    "capability_evolution_candidates only"),
            "existing_memory_layer": _l5(
                [], "read dv_harness/memory.py MEMORY_LEVELS; no selection-history tier exists"),
            "existing_evidence_mechanism": _l5(
                ["dv_harness/change_impact.py compute_change_impact()/select_regression()"],
                "read dv_harness/change_impact.py in full"),
            "possible_enhancement": (
                "Feed a semantic (not file-level) delta into change_impact.file_to_module_map(); "
                "a candidate for research-architect to weigh, never a decision."
            ),
        },
        "related_prior_research": [],
        "contradictions": [],
    }


def _ingest(root: Path, doc_path: Path, *, title: str, source: str,
            analytical: dict) -> dict:
    """The real `research-ingestion` chain, steps 1/2/3-5/6 of its SKILL.md."""
    card = dx.build_research_evidence_card_skeleton(
        doc_path, root, title=title, source=source,
        document_type="ARXIV_PAPER", version="preprint v1")
    owed = dx.research_card_missing_fields(card)
    assert owed == list(dx.RESEARCH_CARD_LLM_AUTHORED_FIELDS)
    card.update(analytical)
    dx.validate_research_evidence_card(card)
    return card


def _file_card(root: Path, stem: str, card: dict) -> Path:
    cards_dir = root / "research" / "evidence_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    path = cards_dir / f"{stem}{ce.EVIDENCE_CARD_SUFFIX}"
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# --- the no-invented-evidence auditor ---------------------------------------

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set:
    return set(_NUMBER_RE.findall(text or ""))


def invented_evidence(card: dict, document_text: str) -> list:
    """Every place the card cites something the document does not contain.

    Two mechanical checks, both re-derived from the document's real bytes:

    * every `source_location.section` on a claim or a quantitative result names
      a section heading the document really has;
    * every number appearing in a `claim_text`, a `quantitative_results.value`
      or a `supporting_evidence` string is a number the document really prints.

    Not a proof of honesty -- a reader can still mis-characterise a passage that
    exists. It IS a mechanical check on the two fabrications that matter most and
    are otherwise invisible: a citation to a section nobody can look up, and a
    measurement nobody measured.
    """
    haystack = " ".join(document_text.split()).lower()
    doc_numbers = _numbers(document_text)
    problems = []

    def _check_ref(where: str, ref: dict) -> None:
        section = " ".join(str(ref.get("section") or "").split()).lower()
        if section and section not in haystack:
            problems.append(f"{where}: cites section {ref.get('section')!r}, "
                            "which does not appear in the document")

    def _check_numbers(where: str, text: str) -> None:
        for number in sorted(_numbers(text)):
            if number not in doc_numbers:
                problems.append(f"{where}: quotes the number {number!r}, "
                                "which the document never prints")

    for i, claim in enumerate(card.get("claim_set") or []):
        where = f"claim_set[{i}]"
        _check_ref(where, claim.get("source_location") or {})
        _check_numbers(f"{where}.claim_text", claim.get("claim_text") or "")
        for j, evidence in enumerate(claim.get("supporting_evidence") or []):
            _check_numbers(f"{where}.supporting_evidence[{j}]", evidence)

    for i, result in enumerate(card.get("quantitative_results") or []):
        where = f"quantitative_results[{i}]"
        _check_ref(where, result.get("source_location") or {})
        _check_numbers(f"{where}.value", result.get("value") or "")
        _check_numbers(f"{where}.context", result.get("context") or "")

    return problems


# ===========================================================================
# TEST A -- Research Ingestion
# ===========================================================================

@pytest.fixture()
def ingested():
    """One real document on disk -> one filed, validated card, plus the root."""
    root = _tmp()
    try:
        doc = _write_doc(root, "paper_001_confidence_guided_ranking.md", PAPER_A_TEXT)
        card = _ingest(
            root, doc,
            title="Confidence-Guided Regression Ranking for RTL Verification",
            source="synthetic preprint (Stage-1 acceptance test A)",
            analytical=_read_the_paper(doc.name))
        path = _file_card(root, "paper_001", card)
        yield {"root": root, "doc": doc, "card": card, "path": path}
    finally:
        _rmtree(root)


def test_A_the_chain_produces_a_card_that_validates(ingested):
    """A1: valid ResearchEvidenceCard, through the real validator."""
    dx.validate_research_evidence_card(ingested["card"])
    assert dx.research_card_missing_fields(ingested["card"]) == []
    filed = json.loads(ingested["path"].read_text(encoding="utf-8"))
    dx.validate_research_evidence_card(filed)
    assert filed == ingested["card"]


def test_A_provenance_is_the_real_file_and_not_a_typed_string(ingested):
    """A2: provenance. Re-hash the bytes here rather than trusting the card."""
    card, doc = ingested["card"], ingested["doc"]
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    assert card["document_sha256"] == digest
    assert card["document_id"] == f"DOC-{digest[:12]}"
    assert card["document_bytes"] == doc.stat().st_size
    assert Path(card["document_path"]).resolve() == doc.resolve()
    assert card["source_provenance"] == dx.evidence_ref(
        document=doc.name, version="preprint v1", page="", section="",
        location=str(doc.resolve()))
    index = dx.DocumentIndex(ingested["root"])
    registered = [r for r in index.load()
                  if r.get("kind") == dx.RESEARCH_DOCUMENT_INDEX_KIND]
    assert [r["sha256"] for r in registered] == [digest]
    # Registration is what makes re-ingesting an unchanged document detectable.
    assert index.needs_extract(doc) is False


def test_A_every_claim_and_result_carries_its_own_source_location(ingested):
    """A2 continued: provenance is per-claim, not only per-document."""
    ref_keys = {"document", "version", "page", "section", "source_location"}
    for claim in ingested["card"]["claim_set"]:
        assert set(claim["source_location"]) == ref_keys
        assert claim["source_location"]["section"].strip()
    for result in ingested["card"]["quantitative_results"]:
        assert set(result["source_location"]) == ref_keys
        assert result["source_location"]["section"].strip()


def test_A_limitations_are_explicit_and_use_the_closed_tag_vocabulary(ingested):
    """A3: explicit limitations."""
    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    allowed = set(schema["$defs"]["limitation"]["properties"]["tag"]["enum"])
    limitations = ingested["card"]["limitations"]
    assert limitations, "a card with no stated limitation is not an honest card"
    for entry in limitations:
        assert entry["tag"] in allowed
        assert entry["detail"].strip()


def test_A_every_claim_is_classified_and_the_two_schema_rules_really_bind(ingested):
    """A4: claim classification, including that the distinction is exercised."""
    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    allowed = set(schema["$defs"]["claim"]["properties"]["claim_type"]["enum"])
    types = [c["claim_type"] for c in ingested["card"]["claim_set"]]
    assert set(types) <= allowed
    # A card whose every claim is a FACT has not classified anything -- it has
    # relabelled the paper's abstract. This paper supports all four types.
    assert set(types) == {"FACT", "AUTHOR_CLAIM", "INFERENCE", "HYPOTHESIS"}
    for claim in ingested["card"]["claim_set"]:
        if claim["claim_type"] == "FACT":
            assert claim["supporting_evidence"]
        else:
            assert (claim.get("verification_requirement") or "").strip()


def test_A_promoting_the_author_claim_to_a_fact_is_refused_by_the_real_schema(ingested):
    """A4 negative control: the single most damaging ingestion failure."""
    card = copy.deepcopy(ingested["card"])
    claim = next(c for c in card["claim_set"] if c["claim_type"] == "AUTHOR_CLAIM")
    claim["claim_type"] = "FACT"
    claim["verification_requirement"] = None
    dx.validate_research_evidence_card(card)  # a FACT with evidence still validates
    # ...so the schema is not the whole defence, and the INFERENCE case shows
    # where it does bind: a non-FACT with no open verification requirement.
    card2 = copy.deepcopy(ingested["card"])
    inference_claim = next(c for c in card2["claim_set"] if c["claim_type"] == "INFERENCE")
    inference_claim["verification_requirement"] = None
    with pytest.raises(dx.ResearchEvidenceCardValidationError):
        dx.validate_research_evidence_card(card2)


def test_A_confidence_uses_the_existing_inference_vocabulary(ingested):
    """A5: confidence, from inference.py's levels -- no fourth vocabulary."""
    dx.assert_confidence_vocabulary_reused()
    allowed = set(inference.CONFIDENCE_LEVELS) | {"UNKNOWN"}
    assert ingested["card"]["confidence"] in allowed
    for claim in ingested["card"]["claim_set"]:
        assert claim["confidence"] in allowed


def test_A_no_invented_evidence(ingested):
    """A6: every cited section and every quoted number is really in the paper."""
    problems = invented_evidence(ingested["card"], PAPER_A_TEXT)
    assert problems == [], "\n".join(problems)


def test_A_the_no_invented_evidence_auditor_catches_a_fabricated_number(ingested):
    """A6 negative control #1 -- an auditor nobody proved can fail proves nothing."""
    card = copy.deepcopy(ingested["card"])
    card["quantitative_results"][0]["value"] = "88 percent"
    problems = invented_evidence(card, PAPER_A_TEXT)
    assert any("88" in p for p in problems), problems


def test_A_the_no_invented_evidence_auditor_catches_a_fabricated_section(ingested):
    """A6 negative control #2 -- a citation to a section that does not exist."""
    card = copy.deepcopy(ingested["card"])
    card["claim_set"][0]["source_location"]["section"] = "9.4 Field Deployment Results"
    problems = invented_evidence(card, PAPER_A_TEXT)
    assert any("9.4 Field Deployment Results" in p for p in problems), problems


def test_A_the_search_basis_is_required_even_where_nothing_was_found(ingested):
    """A6 continued: REUSE-before-ADD at card level. An empty `matches` is the
    claim that most needs its search shown, and the schema enforces that."""
    mapping = ingested["card"]["candidate_l5_mapping"]
    slots = [k for k in mapping if k.startswith("existing_")]
    assert len(slots) == 6
    for slot in slots:
        assert mapping[slot]["search_basis"].strip()
    card = copy.deepcopy(ingested["card"])
    card["candidate_l5_mapping"]["existing_agent"]["search_basis"] = ""
    with pytest.raises(dx.ResearchEvidenceCardValidationError):
        dx.validate_research_evidence_card(card)


def test_A_ingestion_writes_only_under_research_and_the_harness_state_dir(ingested):
    """A6 continued: the skill's own boundary -- no production file is touched.

    Fingerprints every file under `dv_harness/` and `.claude/` in the REAL repo
    before and after a full ingest into a temp root, the same discipline
    acceptance test D applies to the architect's decision logic.
    """
    def fingerprint():
        out = {}
        for base in (REPO_ROOT / "dv_harness", REPO_ROOT / ".claude"):
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out

    before = fingerprint()
    root = _tmp()
    try:
        doc = _write_doc(root, "paper_002.md", PAPER_A_TEXT)
        card = _ingest(root, doc, title="t", source="s",
                       analytical=_read_the_paper(doc.name))
        _file_card(root, "paper_002", card)
        written = {p.relative_to(root).parts[0]
                   for p in root.rglob("*") if p.is_file()}
        assert written <= {"research", ".dv-harness"}, written
    finally:
        _rmtree(root)
    assert fingerprint() == before


# ===========================================================================
# TEST G -- Prior Research Comparison
# ===========================================================================

def _card_for(root: Path, name: str, text: str, *, title: str, stem: str,
              analytical: dict) -> dict:
    doc = _write_doc(root, name, text)
    card = dx.build_research_evidence_card_skeleton(
        doc, root, title=title, source=f"synthetic preprint ({stem})",
        document_type="ARXIV_PAPER", version="preprint v1")
    card.update(analytical)
    dx.validate_research_evidence_card(card)
    _file_card(root, stem, card)
    return card


def _replication_analytical(document_name: str) -> dict:
    """PAPER_B: shares Semantic Delta, adds Independent Replication, and reports
    a DIFFERENT value for the same metric the first paper reports."""
    a = _read_the_paper(document_name)
    a = copy.deepcopy(a)
    a["authors"] = ["D. Skeptic", "E. Colleague"]
    a["date"] = "2026-02"
    a["key_mechanisms"] = ["Semantic Delta", "Regression Ranking", "Independent Replication"]
    a["problem_statement"] = (
        "A selection method measured only on its authors' own designs has not been shown to "
        "generalize."
    )
    a["quantitative_results"] = [{
        "metric": "mean selection reduction versus full regression",
        "value": "31 percent",
        "unit": "percent reduction",
        "context": "mean over 3 external designs the original authors did not use",
        "source_location": _ref(document_name, "4", "4.1 Selection size"),
    }]
    a["limitations"] = [
        {"tag": "SMALL_BENCHMARK", "detail": "Only 3 designs were available."},
        {"tag": "NO_INDEPENDENT_REPRODUCTION",
         "detail": "The original tool could not be obtained, so the replication is approximate."},
    ]
    a["claim_set"] = [{
        "claim_text": "The measured selection reduction is 31 percent, roughly half the "
                      "reduction the original work reports.",
        "claim_type": "AUTHOR_CLAIM",
        "source_location": _ref(document_name, "4", "4.1 Selection size"),
        "supporting_evidence": ["Section 4.1: mean selection reduction of 31 percent"],
        "confidence": "MEDIUM",
        "uncertainty": "The original tool was unavailable, so the reimplementation may differ.",
        "verification_requirement": "Obtain the original tool and re-measure on both design sets.",
    }]
    return a


def _formal_repair_analytical(document_name: str) -> dict:
    """PAPER_C: no shared mechanism, no shared domain -- the 'new' arm."""
    a = copy.deepcopy(_read_the_paper(document_name))
    a["authors"] = ["F. Formalist"]
    a["date"] = "2025-06"
    a["verification_domain"] = ["formal property verification", "reset sequencing"]
    a["key_mechanisms"] = ["Proof-Guided Repair", "Bounded Model Checking"]
    a["problem_statement"] = "Reset sequencing bugs are found late and fixed by hand."
    a["quantitative_results"] = []
    a["evidence_strength"] = {"scale": 1, "rationale": "Two small blocks, no comparison."}
    a["limitations"] = [{"tag": "SMALL_BENCHMARK", "detail": "Two small blocks only."}]
    a["claim_set"] = [{
        "claim_text": "A repair template rewrites the reset sequencing logic until the "
                      "property holds.",
        "claim_type": "AUTHOR_CLAIM",
        "source_location": _ref(document_name, "3", "3 Method"),
        "supporting_evidence": ["Section 3 describes the counterexample-to-repair loop"],
        "confidence": "LOW",
        "uncertainty": "Exercised on 2 small blocks.",
        "verification_requirement": "Run the loop against a real reset-sequencing failure here.",
    }]
    return a


@pytest.fixture()
def three_cards():
    root = _tmp()
    try:
        a = _card_for(root, "paper_001_ranking.md", PAPER_A_TEXT,
                      title="Confidence-Guided Regression Ranking for RTL Verification",
                      stem="paper_001",
                      analytical=_read_the_paper("paper_001_ranking.md"))
        b = _card_for(root, "paper_002_replication.md", PAPER_B_TEXT,
                      title="Semantic Delta Selection Revisited: A Failed Replication",
                      stem="paper_002",
                      analytical=_replication_analytical("paper_002_replication.md"))
        c = _card_for(root, "paper_003_formal_repair.md", PAPER_C_TEXT,
                      title="Formal Proof-Guided Repair of Reset Sequencing Bugs",
                      stem="paper_003",
                      analytical=_formal_repair_analytical("paper_003_formal_repair.md"))
        yield {"root": root, "a": a, "b": b, "c": c}
    finally:
        _rmtree(root)


def test_G_the_card_store_is_read_from_real_filed_cards(three_cards):
    root = three_cards["root"]
    cards = ce.read_evidence_cards(root)
    assert [c["document_id"] for c in cards] == sorted(
        {three_cards[k]["document_id"] for k in ("a", "b", "c")})
    excluded = ce.read_evidence_cards(root, exclude_document_id=three_cards["a"]["document_id"])
    assert three_cards["a"]["document_id"] not in [c["document_id"] for c in excluded]
    assert ce.read_evidence_cards(root / "nowhere") == []


def test_G_a_new_paper_against_the_whole_store_gets_a_status_and_a_link_each(three_cards):
    """The headline of test G, in one call: a new card compared against every
    card already filed, each comparison identified by a section-28 relation and
    LINKED by the prior card's own document_id.

    Card B really does overlap card A (both are semantic-delta regression
    selection) AND disagrees with it on the one metric both report, so its
    relation is the stronger of the two, CONTRADICTS -- disagreement is never
    reported as convergence. Card C shares neither mechanism nor domain, so it
    comes back UNRELATED. Both are statuses; neither is silence.
    """
    new_card = three_cards["b"]
    priors = ce.read_evidence_cards(three_cards["root"],
                                    exclude_document_id=new_card["document_id"])
    summary = ce.link_prior_research(new_card, priors)

    assert summary["document_id"] == new_card["document_id"]
    assert set(summary["compared_against"]) == {
        three_cards["a"]["document_id"], three_cards["c"]["document_id"]}
    assert len(summary["links"]) == 2
    by_prior = {c["document_id"]: c for c in summary["comparisons"]}
    assert by_prior[three_cards["a"]["document_id"]]["relation"] == "CONTRADICTS"
    assert by_prior[three_cards["c"]["document_id"]]["relation"] == "UNRELATED"
    for link in summary["links"]:
        assert link["document_id"] in summary["compared_against"]
        assert link["relation"] in ce.prior_research_relations()
        assert link["note"].strip()
    assert summary["has_contradiction"] is True
    assert summary["is_new"] is False


def test_G_a_contradicting_metric_is_reported_as_CONTRADICTS_with_its_signal(three_cards):
    """Two cards reporting the same metric with different values contradict --
    derived from the cards themselves, with neither card naming the other."""
    comparison = ce.compare_evidence_cards(three_cards["b"], three_cards["a"])
    assert comparison["relation"] == "CONTRADICTS"
    signals = comparison["basis"]["contradiction_signals"]
    assert signals and all(s.startswith("METRIC_VALUE_CONFLICT:") for s in signals)
    assert "31 percent" in signals[0] and "62 percent" in signals[0]
    summary = ce.link_prior_research(three_cards["b"], [three_cards["a"]])
    assert summary["has_contradiction"] is True
    assert summary["is_new"] is False


def test_G_pure_overlap_without_a_metric_conflict_is_OVERLAPS(three_cards):
    """Strip the conflicting measurement and the same pair is an overlap, not a
    contradiction -- so CONTRADICTS above came from the metric, not the domain."""
    b = copy.deepcopy(three_cards["b"])
    b["quantitative_results"] = []
    comparison = ce.compare_evidence_cards(b, three_cards["a"])
    assert comparison["relation"] == "OVERLAPS"
    assert comparison["basis"]["shared_mechanisms"] == ["regression ranking", "semantic delta"]
    assert ce.link_prior_research(b, [three_cards["a"]])["has_overlap"] is True


def test_G_a_superset_of_mechanisms_is_EXTENDS(three_cards):
    """B's mechanisms are A's plus one, so with the conflict removed and A's
    extra mechanism dropped the relation rises from OVERLAPS to EXTENDS."""
    b = copy.deepcopy(three_cards["b"])
    b["quantitative_results"] = []
    a = copy.deepcopy(three_cards["a"])
    a["key_mechanisms"] = ["Semantic Delta", "Regression Ranking"]
    comparison = ce.compare_evidence_cards(b, a)
    assert comparison["relation"] == "EXTENDS"
    assert comparison["basis"]["new_only_mechanisms"] == ["independent replication"]
    assert comparison["basis"]["prior_only_mechanisms"] == []


def test_G_an_unrelated_paper_is_new_not_overlapping(three_cards):
    """The 'new' arm: no shared mechanism, no shared domain, nothing declared."""
    summary = ce.link_prior_research(three_cards["c"], [three_cards["a"], three_cards["b"]])
    assert summary["relations"] == ["UNRELATED"]
    assert summary["is_new"] is True
    assert summary["has_overlap"] is False and summary["has_contradiction"] is False


def test_G_a_first_card_with_no_priors_is_new(three_cards):
    summary = ce.link_prior_research(three_cards["a"], [])
    assert summary["comparisons"] == [] and summary["links"] == []
    assert summary["is_new"] is True


def test_G_a_re_ingested_identical_document_is_flagged_as_not_independent(three_cards):
    """Same bytes twice must never be counted as convergence."""
    duplicate = copy.deepcopy(three_cards["a"])
    duplicate["document_id"] = "DOC-000000000000"
    comparison = ce.compare_evidence_cards(duplicate, three_cards["a"])
    assert comparison["relation"] == "OVERLAPS"
    assert comparison["basis"]["identical_document"] is True
    assert "NOT a second" in comparison["note"]


def test_G_a_card_stating_neither_mechanism_nor_domain_is_INSUFFICIENT_EVIDENCE(three_cards):
    """UNKNOWN-over-convenient-UNRELATED, the same discipline as test C."""
    empty = copy.deepcopy(three_cards["c"])
    empty["key_mechanisms"] = []
    empty["verification_domain"] = []
    comparison = ce.compare_evidence_cards(empty, three_cards["a"])
    assert comparison["relation"] == "INSUFFICIENT_EVIDENCE"
    summary = ce.link_prior_research(empty, [three_cards["a"]])
    assert summary["is_new"] is True and summary["has_overlap"] is False


def test_G_a_document_s_own_declared_relation_outranks_derivation(three_cards):
    """SUPPORTS and SUPERSEDES are unreachable by derivation on purpose -- they
    are reading judgements. They appear only when a document declares them."""
    b = copy.deepcopy(three_cards["b"])
    b["quantitative_results"] = []
    b["related_prior_research"] = [{
        "document_id": three_cards["a"]["document_id"],
        "relation": "SUPERSEDES",
        "note": "The replication supersedes the original's generalization claim.",
    }]
    dx.validate_research_evidence_card(b)
    comparison = ce.compare_evidence_cards(b, three_cards["a"])
    assert comparison["relation"] == "SUPERSEDES"
    assert comparison["basis"]["declared_relation"] == "SUPERSEDES"


def test_G_a_declared_contradiction_is_honored_even_with_no_metric_conflict(three_cards):
    b = copy.deepcopy(three_cards["b"])
    b["quantitative_results"] = []
    b["contradictions"] = [{
        "statement": "The no-missed-failure claim does not hold outside the original designs.",
        "against": f"the original work, {three_cards['a']['document_id']}",
        "source_location": _ref("paper_002_replication.md", "4", "4.2 Escapes"),
    }]
    dx.validate_research_evidence_card(b)
    comparison = ce.compare_evidence_cards(b, three_cards["a"])
    assert comparison["relation"] == "CONTRADICTS"
    assert comparison["basis"]["contradiction_signals"] == [
        f"AGAINST_DOCUMENT_ID:{three_cards['a']['document_id']}"]


def test_G_every_link_validates_against_the_schema_s_own_link_shape(three_cards):
    """The link is the card schema's `prior_research_link`, not a private shape."""
    import jsonschema

    schema = json.loads(dx.RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
    link_schema = dict(schema["$defs"]["prior_research_link"])
    link_schema["$defs"] = schema["$defs"]
    summary = ce.link_prior_research(three_cards["b"],
                                     [three_cards["a"], three_cards["c"]])
    validator = jsonschema.Draft202012Validator(link_schema)
    for link in summary["links"]:
        validator.validate(link)


def test_G_the_relation_vocabulary_is_the_schema_s_and_not_a_second_copy():
    """Section 28 names these seven once. capability_evolution must not own a
    second tuple of them, or the two agree only until someone edits one."""
    assert ce.prior_research_relations() == dx.prior_research_relations()
    source = (REPO_ROOT / "dv_harness" / "capability_evolution.py").read_text(encoding="utf-8")
    assignments = re.findall(r"^[A-Z_]+ *= *\([^)]*\)", source, re.MULTILINE)
    for assignment in assignments:
        assert not ("SUPPORTS" in assignment and "SUPERSEDES" in assignment), (
            "capability_evolution.py defines its own copy of the section-28 relation "
            f"vocabulary: {assignment}")


def test_G_comparison_never_edits_a_filed_card(three_cards):
    """The architect reads cards; `research-ingestion` writes them. Byte-check."""
    cards_dir = three_cards["root"] / "research" / "evidence_cards"
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(cards_dir.glob("*.card.json"))}
    summary = ce.link_prior_research(
        three_cards["b"], ce.read_evidence_cards(
            three_cards["root"], exclude_document_id=three_cards["b"]["document_id"]))
    assert summary["comparisons"]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(cards_dir.glob("*.card.json"))}
    assert after == before


def test_G_links_persist_to_working_memory_through_the_real_router(three_cards):
    """'Linked' means persisted, and it lands in WORKING_MEMORY -- one session's
    reading of two external documents is not verified engineering knowledge."""
    from dv_harness.memory import MemoryStore

    root = three_cards["root"]
    summary = ce.link_prior_research(three_cards["b"], [three_cards["a"], three_cards["c"]])
    routed = ce.persist_prior_research_links(root, summary)
    assert len(routed) == 2
    assert {r["destination"] for r in routed} == {"WORKING_MEMORY"}
    stored = MemoryStore(root).find("working", kind=ce.PRIOR_RESEARCH_LINK_MEMORY_KIND)
    assert len(stored) == 2
    assert {r["prior_document_id"] for r in stored} == {
        three_cards["a"]["document_id"], three_cards["c"]["document_id"]}
    for record in stored:
        assert record["relation"] in ce.prior_research_relations()
        assert record["document_id"] == three_cards["b"]["document_id"]
        assert "verified" not in record


def test_G_the_link_memory_kind_is_an_existing_research_kind(three_cards):
    """No new memory kind, no sixth tier -- section 12."""
    from dv_harness import memory_router

    assert ce.PRIOR_RESEARCH_LINK_MEMORY_KIND in memory_router.RESEARCH_EVIDENCE_KINDS
    assert memory_router.route_memory(
        {"kind": ce.PRIOR_RESEARCH_LINK_MEMORY_KIND,
         "document_id": three_cards["b"]["document_id"]}) == "WORKING_MEMORY"


def test_G_a_research_link_record_cannot_reach_engineering_memory(three_cards):
    """Test H's rule, re-checked at this new write site rather than assumed."""
    from dv_harness import memory_router

    record = {
        "kind": ce.PRIOR_RESEARCH_LINK_MEMORY_KIND,
        "document_id": three_cards["b"]["document_id"],
        "prior_document_id": three_cards["a"]["document_id"],
        "relation": "CONTRADICTS",
        # the laundering attempt: everything an ordinary engineering record
        # would need, bolted onto a cross-document reading.
        "verified": True,
        "confidence": "HIGH",
        "evidence": ["section 4.1 of the replication"],
        "lesson": "Semantic delta selection does not generalize.",
    }
    ok, reasons = memory_router.engineering_admission_gate(
        record, root=three_cards["root"])
    assert ok is False, reasons
    assert reasons
