"""Tests for dv_harness/sw_fw_usage_model.py -- documented SW/FW usage-
sequence facts (phase/action/register per numbered procedure step, each
with a real document+line citation) extracted from a REAL, offline-distilled
programming guide, shaped directly into `programming_sequence_ir.py`'s own
phase/action vocabulary and, for the fully-classified subset, composed into
a real `programming_sequence_ir.ProgrammingSequenceIR` document.

The synthetic programming-guide fixture below states in its own text that
it is a test fixture and describes no real vendor IP -- consistent with the
"No Golden-Reference Content Mining" rule: nothing here is mined from, or
compared against, a real vendor's programming guide.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import programming_sequence_ir as psir
from dv_harness import sw_fw_usage_model as sfm
from dv_harness import vip_user_guide_distill as ugd

FIXTURE_TEXT = """1.0 Overview

This is a synthetic programming guide test fixture. It is not real
protocol content and describes no real vendor IP.

3.1 Device Initialization Procedure

1. Initialize the device by asserting POR_RESET for 10 us.
2. Configure the CTRL_REG register to set the operating mode.
3. Enable the DMA_CTRL.START bit.
4. Wait for the STATUS.READY bit to be set.
5. Read back the DMA_CTRL register to verify DATA_COUNT reached zero.
6. Proceed to the next section of the manual for further options.

3.2 Reset Sequence

1. Toggle the RSTN pin per the timing diagram shown in Figure 2.
2. Hold RSTN low for at least 100 microseconds before releasing.

3.3 Ambiguous Examples

1. Reset the device and then configure the interrupt mask register.
2. Write the CFG_REG value and read back the STATUS register to confirm.

4.0 Miscellaneous Notes

See Table 3 for a list of supported clock frequencies.
"""

NO_SEQUENCES_TEXT = """1.0 Overview

This synthetic fixture intentionally contains no numbered procedure list
anywhere in its text, only running prose paragraphs.

2.0 Miscellaneous

Some paragraph that is not a numbered step of anything at all.
"""

STEP_PREFIX_TEXT = """5.0 Bring-Up

Step 1: Write the ENABLE_REG register to power on the block.
Step 2: Wait for the READY.DONE bit to assert before continuing.
"""


@pytest.fixture()
def distilled_guide(tmp_path):
    src = tmp_path / "synthetic_programming_guide.txt"
    src.write_text(FIXTURE_TEXT, encoding="utf-8")
    out_dir = tmp_path / "distilled"
    return ugd.distill_user_guide(src, out_dir, title="Synthetic Programming Guide",
                                  doc_kind="programming_guide")


# ===========================================================================
# absent programming guide -> NOT_AVAILABLE, never a guess
# ===========================================================================

def test_no_document_supplied_is_not_available():
    doc = sfm.extract_sw_fw_usage_model()
    assert doc["status"] == "NOT_AVAILABLE"
    assert doc["source"] is None
    assert doc["sequences"] == []
    assert doc["sequence_count"] == 0
    assert "no programming guide document was supplied" in doc["reason"]


def test_disclosure_is_always_present_and_states_not_verified():
    doc = sfm.extract_sw_fw_usage_model()
    assert "NOT VERIFIED" in doc["disclosure"]
    assert "programming_sequence_ir.validate_step_ordering" in doc["disclosure"]


def test_missing_reference_record_path_reports_not_available(tmp_path):
    doc = sfm.extract_sw_fw_usage_model(reference_record_path=tmp_path / "nope.reference.json")
    assert doc["status"] == "NOT_AVAILABLE"
    assert "could not load" in doc["reason"]


def test_malformed_reference_record_dict_is_rejected():
    doc = sfm.extract_sw_fw_usage_model(reference_record={"schema_version": "1.0"})
    assert doc["status"] == "NOT_AVAILABLE"
    assert "missing" in doc["reason"]


def test_missing_fulltext_file_on_disk_reports_not_available(distilled_guide):
    Path(distilled_guide["full_text_extract"]["path"]).unlink()
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    assert doc["status"] == "NOT_AVAILABLE"
    assert "missing on disk" in doc["reason"]


def test_step_phase_and_action_vocabulary_are_programming_sequence_irs_own():
    doc = sfm.extract_sw_fw_usage_model()
    assert doc["step_phase_vocabulary"] == list(psir.CANONICAL_PHASES)
    assert doc["step_action_vocabulary"] == list(psir.STEP_ACTIONS)


# ===========================================================================
# classification -- literal keyword evidence only, never a guess
# ===========================================================================

def test_classify_phase_positive_examples():
    assert sfm.classify_phase("Initialize the device by asserting POR_RESET for 10 us.") == {
        "phase": psir.PHASE_INIT, "status": sfm.STATUS_CLASSIFIED,
        "evidence": ["Initialize"], "matched_phases": [psir.PHASE_INIT]}
    r = sfm.classify_phase("Wait for the STATUS.READY bit to be set.")
    assert r["phase"] == psir.PHASE_WAIT
    assert r["status"] == sfm.STATUS_CLASSIFIED


def test_classify_phase_neutral_text_is_unclassified_never_guessed():
    r = sfm.classify_phase("Proceed to the next section of the manual for further options.")
    assert r["status"] == sfm.STATUS_UNCLASSIFIED
    assert r["phase"] is None
    assert r["evidence"] == []


def test_classify_phase_two_distinct_phases_is_ambiguous_never_resolved():
    r = sfm.classify_phase("Reset the device and then configure the interrupt mask register.")
    assert r["status"] == sfm.STATUS_AMBIGUOUS
    assert r["phase"] is None
    assert set(r["matched_phases"]) == {psir.PHASE_RESET, psir.PHASE_CONFIGURE}


def test_classify_action_positive_examples():
    assert sfm.classify_action("Wait for the STATUS.READY bit to be set.") == {
        "action": psir.ACTION_WAIT, "status": sfm.STATUS_CLASSIFIED, "evidence": ["Wait for"]}
    w = sfm.classify_action("Configure the CTRL_REG register to set the operating mode.")
    assert w["action"] == psir.ACTION_WRITE
    assert w["status"] == sfm.STATUS_CLASSIFIED
    r = sfm.classify_action("Read back the DMA_CTRL register to verify DATA_COUNT reached zero.")
    assert r["action"] == psir.ACTION_READ
    assert r["status"] == sfm.STATUS_CLASSIFIED


def test_classify_action_wait_wins_over_write_and_read():
    # A step whose text ALSO mentions write/read-shaped words is still WAIT
    # when it contains real wait phrasing -- matching programming_sequence_
    # ir.py's own "wait = pure delay/poll-until-condition" semantics.
    r = sfm.classify_action("Wait for the write operation to complete before reading status.")
    assert r["action"] == psir.ACTION_WAIT
    assert r["status"] == sfm.STATUS_CLASSIFIED


def test_classify_action_write_and_read_with_no_wait_is_ambiguous_never_resolved():
    r = sfm.classify_action("Write the CFG_REG value and read back the STATUS register to confirm.")
    assert r["status"] == sfm.STATUS_AMBIGUOUS
    assert r["action"] is None
    assert r["evidence"] == ["Write", "read"]


def test_classify_action_neutral_text_is_unclassified():
    r = sfm.classify_action("Toggle the RSTN pin per the timing diagram shown in Figure 2.")
    assert r["status"] == sfm.STATUS_UNCLASSIFIED
    assert r["action"] is None


def test_extract_register_dotted_form_resolves_register_and_field():
    r = sfm.extract_register("Wait for the STATUS.READY bit to be set.")
    assert r == {"register": "STATUS", "field": "READY",
                 "status": sfm.REGISTER_STATUS_RESOLVED_WITH_FIELD, "evidence": "STATUS.READY"}


def test_extract_register_bare_token_resolves_register_only():
    r = sfm.extract_register("Configure the CTRL_REG register to set the operating mode.")
    assert r["register"] == "CTRL_REG"
    assert r["field"] is None
    assert r["status"] == sfm.REGISTER_STATUS_RESOLVED


def test_extract_register_no_register_shaped_token_is_unresolved_never_fabricated():
    r = sfm.extract_register("Reset the device and then configure the interrupt mask register.")
    assert r == {"register": None, "field": None,
                 "status": sfm.REGISTER_STATUS_UNRESOLVED, "evidence": None}


def test_extract_register_bare_allcaps_with_no_underscore_is_unresolved():
    # RSTN has no underscore-separated segment -- deliberately below this
    # module's narrow register-shape bar, never guessed as a register name.
    r = sfm.extract_register("Toggle the RSTN pin per the timing diagram shown in Figure 2.")
    assert r["status"] == sfm.REGISTER_STATUS_UNRESOLVED


def test_classify_phase_with_heading_fallback_only_applies_on_unclassified_step_text():
    # Step text carries no phase keyword of its own -> the enclosing
    # heading's own real classification supplies a distinct, tagged
    # fallback.
    r = sfm.classify_phase_with_heading_fallback(
        "Toggle the RSTN pin per the timing diagram shown in Figure 2.", "3.2 Reset Sequence")
    assert r["phase"] == psir.PHASE_RESET
    assert r["status"] == sfm.STATUS_CLASSIFIED_FROM_HEADING
    assert r["evidence_source"] == "heading"


def test_classify_phase_with_heading_fallback_never_overrides_a_real_ambiguity():
    # The step's OWN text is genuinely ambiguous (two distinct phases) --
    # a clean heading classification must never quietly resolve that.
    r = sfm.classify_phase_with_heading_fallback(
        "Reset the device and then configure the interrupt mask register.",
        "3.1 Device Initialization Procedure")
    assert r["status"] == sfm.STATUS_AMBIGUOUS
    assert r["phase"] is None


def test_classify_phase_with_heading_fallback_no_heading_stays_unclassified():
    r = sfm.classify_phase_with_heading_fallback(
        "Toggle the RSTN pin per the timing diagram shown in Figure 2.", None)
    assert r["status"] == sfm.STATUS_UNCLASSIFIED
    assert r["evidence_source"] is None


# ===========================================================================
# structural scan -- real consecutively-numbered candidate sequences only
# ===========================================================================

def test_scan_usage_sequences_groups_consecutive_numbered_items():
    text = "1. Step one.\n2. Step two.\n3. Step three.\n"
    groups = sfm.scan_usage_sequences(text, document_label="doc", fulltext_path="doc.txt")
    assert len(groups) == 1
    assert [i["number"] for i in groups[0]["items"]] == [1, 2, 3]
    assert groups[0]["items"][0]["citation"] == {
        "document": "doc", "fulltext_path": "doc.txt", "line": 1}


def test_scan_usage_sequences_numbering_restart_starts_a_new_sequence():
    text = (
        "1. Step one.\n2. Step two.\n3. Step three.\n\n"
        "Some unrelated paragraph breaks the list.\n\n"
        "1. Restarted item one.\n2. Restarted item two.\n"
    )
    groups = sfm.scan_usage_sequences(text, document_label="doc", fulltext_path="doc.txt")
    assert len(groups) == 2
    assert [i["number"] for i in groups[0]["items"]] == [1, 2, 3]
    assert [i["number"] for i in groups[1]["items"]] == [1, 2]


def test_scan_usage_sequences_single_item_never_counts_as_a_sequence():
    text = "1. Only one step here.\n\nUnrelated text below.\n"
    groups = sfm.scan_usage_sequences(text, document_label="doc", fulltext_path="doc.txt")
    assert groups == []


def test_scan_usage_sequences_no_numbered_lists_reports_none():
    text = "No numbered lists anywhere in this document at all.\n"
    groups = sfm.scan_usage_sequences(text, document_label="doc", fulltext_path="doc.txt")
    assert groups == []


def test_scan_usage_sequences_recognizes_step_n_prefix_form():
    groups = sfm.scan_usage_sequences(
        STEP_PREFIX_TEXT, document_label="doc", fulltext_path="doc.txt")
    assert len(groups) == 1
    assert [i["number"] for i in groups[0]["items"]] == [1, 2]
    assert groups[0]["heading"] == "5.0 Bring-Up"


# ===========================================================================
# full extraction over a real distilled programming guide
# ===========================================================================

def test_extraction_over_real_document_reports_three_candidate_sequences(distilled_guide):
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    assert doc["status"] == "EXTRACTED"
    assert doc["sequence_count"] == 3
    assert doc["source"]["doc_kind"] == "programming_guide"
    assert doc["source"]["fulltext_sha256_verified"] is True
    names = [s["name"] for s in doc["sequences"]]
    assert names == [
        "3.1 Device Initialization Procedure", "3.2 Reset Sequence", "3.3 Ambiguous Examples"]


def test_extraction_first_sequence_steps_classify_as_expected(distilled_guide):
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    seq1 = doc["sequences"][0]
    assert seq1["step_count"] == 6
    expected = [
        (sfm.STATUS_CLASSIFIED, psir.PHASE_INIT, sfm.STATUS_CLASSIFIED, psir.ACTION_WRITE,
         sfm.REGISTER_STATUS_RESOLVED, "POR_RESET"),
        (sfm.STATUS_CLASSIFIED, psir.PHASE_CONFIGURE, sfm.STATUS_CLASSIFIED, psir.ACTION_WRITE,
         sfm.REGISTER_STATUS_RESOLVED, "CTRL_REG"),
        (sfm.STATUS_CLASSIFIED, psir.PHASE_ENABLE, sfm.STATUS_CLASSIFIED, psir.ACTION_WRITE,
         sfm.REGISTER_STATUS_RESOLVED_WITH_FIELD, "DMA_CTRL"),
        (sfm.STATUS_CLASSIFIED, psir.PHASE_WAIT, sfm.STATUS_CLASSIFIED, psir.ACTION_WAIT,
         sfm.REGISTER_STATUS_RESOLVED_WITH_FIELD, "STATUS"),
        (sfm.STATUS_CLASSIFIED, psir.PHASE_VERIFY, sfm.STATUS_CLASSIFIED, psir.ACTION_READ,
         sfm.REGISTER_STATUS_RESOLVED, "DMA_CTRL"),
        (sfm.STATUS_CLASSIFIED_FROM_HEADING, psir.PHASE_INIT, sfm.STATUS_UNCLASSIFIED, None,
         sfm.REGISTER_STATUS_UNRESOLVED, None),
    ]
    for step, exp in zip(seq1["steps"], expected):
        assert (step["phase_status"], step["phase"], step["action_status"], step["action"],
                step["register_status"], step["register"]) == exp
        # every step carries a real, checkable citation
        assert step["citation"]["document"] == "Synthetic Programming Guide"
        assert isinstance(step["citation"]["line"], int)


def test_extraction_ambiguous_sequence_never_silently_resolved(distilled_guide):
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    seq3 = doc["sequences"][2]
    assert seq3["name"] == "3.3 Ambiguous Examples"
    assert seq3["steps"][0]["phase_status"] == sfm.STATUS_AMBIGUOUS
    assert seq3["steps"][0]["phase"] is None
    assert seq3["steps"][1]["action_status"] == sfm.STATUS_AMBIGUOUS
    assert seq3["steps"][1]["action"] is None


def test_min_sequence_length_can_be_widened_to_exclude_a_short_sequence(distilled_guide):
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide, min_sequence_length=3)
    # both the 2-step reset sequence and the 2-step ambiguous-examples
    # sequence drop out; only the 6-step init sequence survives.
    assert doc["sequence_count"] == 1
    assert doc["sequences"][0]["name"] == "3.1 Device Initialization Procedure"


def test_zero_sequences_found_is_honestly_reported(tmp_path):
    src = tmp_path / "no_seq.txt"
    src.write_text(NO_SEQUENCES_TEXT, encoding="utf-8")
    out_dir = tmp_path / "distilled_none"
    record = ugd.distill_user_guide(src, out_dir, title="No Sequences Doc", doc_kind="programming_guide")
    doc = sfm.extract_sw_fw_usage_model(reference_record=record)
    assert doc["status"] == "EXTRACTED"
    assert doc["sequence_count"] == 0
    assert doc["sequences"] == []


# ===========================================================================
# composition into programming_sequence_ir.py's own real shape -- the
# actual reuse claim, proven by a real round trip through that module's own
# constructor and validator.
# ===========================================================================

def test_to_programming_sequence_document_includes_only_fully_resolved_steps(distilled_guide):
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    doc, excluded = sfm.to_programming_sequence_document(seq1, name="init_seq")
    assert doc["name"] == "init_seq"
    assert [s["index"] for s in doc["steps"]] == [0, 1, 2, 3, 4]
    assert len(excluded) == 1
    assert excluded[0]["position"] == 6
    assert excluded[0]["reason"] == sfm.EXCLUDE_ACTION_NOT_RESOLVED


def test_to_programming_sequence_document_never_carries_a_register_on_a_wait_step(distilled_guide):
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    doc, _ = sfm.to_programming_sequence_document(seq1)
    wait_steps = [s for s in doc["steps"] if s["action"] == psir.ACTION_WAIT]
    assert len(wait_steps) == 1
    assert wait_steps[0]["register"] is None
    # register_status DID resolve (STATUS.READY) -- confirming the register
    # is dropped by design for a wait action, not because it was unresolved.
    real_step = seq1.steps[3]
    assert real_step.action == psir.ACTION_WAIT
    assert real_step.register_status == sfm.REGISTER_STATUS_RESOLVED_WITH_FIELD


def test_to_programming_sequence_document_never_fabricates_a_value():
    result = sfm.build_sw_fw_usage_sequences(reference_record=None)
    assert result.status == "NOT_AVAILABLE"
    # A sequence with zero steps still composes to a legal (empty) document
    # rather than raising -- programming_sequence_ir_from_dict() itself
    # treats zero steps as NOT_APPLICABLE, never a crash.
    empty_seq = sfm.SwFwUsageSequenceFact(sequence_id="SEQ_EMPTY", name="Empty", name_citation=None)
    doc, excluded = sfm.to_programming_sequence_document(empty_seq)
    assert doc["steps"] == []
    assert excluded == []


def test_build_candidate_programming_sequence_ir_is_a_real_programming_sequence_ir(distilled_guide):
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    ir, excluded = sfm.build_candidate_programming_sequence_ir(seq1, name="init_seq")
    assert isinstance(ir, psir.ProgrammingSequenceIR)
    assert ir.name == "init_seq"
    assert len(ir.steps) == 5
    assert len(excluded) == 1
    # every value carried through unchanged by the real constructor
    assert [s.phase for s in ir.steps] == [
        psir.PHASE_INIT, psir.PHASE_CONFIGURE, psir.PHASE_ENABLE, psir.PHASE_WAIT, psir.PHASE_VERIFY]
    assert [s.action for s in ir.steps] == [
        psir.ACTION_WRITE, psir.ACTION_WRITE, psir.ACTION_WRITE, psir.ACTION_WAIT, psir.ACTION_READ]


def test_candidate_ir_validates_order_valid_against_real_register_facts(distilled_guide):
    # The headline integration proof: this module's real extraction output,
    # unmodified, composes into a document programming_sequence_ir.py's own
    # real validate_step_ordering() accepts and passes.
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    ir, _ = sfm.build_candidate_programming_sequence_ir(seq1, name="init_seq")
    facts = psir.register_facts_from_dicts([
        {"name": "POR_RESET", "access_type": "RW"},
        {"name": "CTRL_REG", "access_type": "RW", "depends_on": ["POR_RESET"]},
        {"name": "DMA_CTRL", "access_type": "RW", "depends_on": ["CTRL_REG"]},
    ])
    report = psir.validate_step_ordering(ir, facts)
    assert report["status"] == psir.STATUS_ORDER_VALID
    assert report["findings"] == []


def test_candidate_ir_with_no_register_facts_reports_not_available(distilled_guide):
    # This module produces the candidate; it never runs the ordering check
    # itself, and validate_step_ordering() is unchanged: no register facts
    # is honestly NOT_AVAILABLE, never an assumed-clean pass.
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    ir, _ = sfm.build_candidate_programming_sequence_ir(seq1)
    report = psir.validate_step_ordering(ir, None)
    assert report["status"] == psir.STATUS_NOT_AVAILABLE


def test_candidate_ir_detects_a_real_dependency_violation(distilled_guide):
    # A negative control proving the composed document really is checked,
    # not merely accepted: declaring CTRL_REG dependent on a register that
    # is never written earlier in this sequence produces a real finding.
    result = sfm.build_sw_fw_usage_sequences(reference_record=distilled_guide)
    seq1 = result.sequences[0]
    ir, _ = sfm.build_candidate_programming_sequence_ir(seq1)
    facts = psir.register_facts_from_dicts([
        {"name": "POR_RESET", "access_type": "RW"},
        {"name": "CTRL_REG", "access_type": "RW", "depends_on": ["MODE_LOCK"]},
        {"name": "DMA_CTRL", "access_type": "RW"},
        {"name": "MODE_LOCK", "access_type": "RW"},
    ])
    report = psir.validate_step_ordering(ir, facts)
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_DEPENDENCY_NOT_YET_SATISFIED in codes


# ===========================================================================
# save/load
# ===========================================================================

def test_save_and_load_round_trip(distilled_guide, tmp_path):
    doc = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    out_path = tmp_path / "sw_fw_usage_model.json"
    sfm.save_sw_fw_usage_model(doc, out_path)
    loaded = sfm.load_sw_fw_usage_model(out_path)
    assert loaded == doc


def test_save_is_deterministic_byte_for_byte(distilled_guide, tmp_path):
    doc1 = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    doc2 = sfm.extract_sw_fw_usage_model(reference_record=distilled_guide)
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    sfm.save_sw_fw_usage_model(doc1, p1)
    sfm.save_sw_fw_usage_model(doc2, p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_load_rejects_a_document_that_is_not_a_sw_fw_usage_model(tmp_path):
    p = tmp_path / "not_ours.json"
    p.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ValueError):
        sfm.load_sw_fw_usage_model(p)


# ===========================================================================
# ad hoc entry point
# ===========================================================================

def test_execute_verb_requires_reference_record():
    text, code = sfm.execute_verb("extract")
    assert code == 2
    assert "requires --reference-record" in text


def test_execute_verb_unknown_verb():
    text, code = sfm.execute_verb("bogus")
    assert code == 2
    assert "unknown" in text


def test_execute_verb_extract_exit_codes(distilled_guide, tmp_path):
    ref_path = distilled_guide["full_text_extract"]["path"]
    ref_json = Path(ref_path).with_name(Path(ref_path).stem.replace(".fulltext", "") + ".reference.json")
    assert ref_json.exists()

    text, code = sfm.execute_verb("extract", reference_record_path=str(ref_json), as_json=True)
    assert code == 0
    assert '"status": "EXTRACTED"' in text

    missing = tmp_path / "does_not_exist.reference.json"
    text2, code2 = sfm.execute_verb("extract", reference_record_path=str(missing))
    assert code2 == 2
    assert "NOT_AVAILABLE" in text2


def test_execute_verb_extract_zero_sequences_exit_code(tmp_path):
    src = tmp_path / "no_seq.txt"
    src.write_text(NO_SEQUENCES_TEXT, encoding="utf-8")
    out_dir = tmp_path / "distilled_none"
    record = ugd.distill_user_guide(src, out_dir, title="No Sequences Doc", doc_kind="programming_guide")
    ref_json = Path(record["full_text_extract"]["path"]).with_name("no_seq.reference.json")
    text, code = sfm.execute_verb("extract", reference_record_path=str(ref_json))
    assert code == 1
    assert "sequences found: 0" in text


def test_real_cli_subprocess_end_to_end(distilled_guide):
    ref_path = distilled_guide["full_text_extract"]["path"]
    ref_json = Path(ref_path).with_name("synthetic_programming_guide.reference.json")
    assert ref_json.exists()

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.sw_fw_usage_model", "extract",
         "--reference-record", str(ref_json), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"status": "EXTRACTED"' in result.stdout
    assert '"sequence_count": 3' in result.stdout
