"""Tests for dv_harness.source_authority -- the 9-level conflict authority
order as executable code, and the mismatch -> question-queue escalation built
on it (2026-09-04 gap close).

The two findings these tests exist to keep closed, both from a real audit:

  * The order was documentation prose only. A grep for its distinctive terms
    ("register file (DUT", "controller doc", "VIP example", ...) found zero
    hits outside docs/RUN_PROFILE.md -- no constant, no resolver, nothing
    that applied it. `test_doc_and_code_orders_are_in_sync` plus
    `test_doc_code_drift_is_detected` are what stop moving it into code from
    simply creating a SECOND place for it to be wrong.

  * Nothing that detected a doc/RTL (or host/DUT) mismatch escalated it to a
    question-queue entry carrying both sides' evidence paths. The two real
    detectors in the tree -- reference_pattern_audit's symmetry check and
    address_map_verifier's 3-source check -- both terminated at report text
    (one of them, address_map_verifier, by explicit "never gating" design).
    The `*_escalates_*` tests below assert against the REAL persisted
    question record, never a return value the store never saw.

Nothing here is a mock: every escalation test drives a real
`question_queue.QuestionQueueStore` on tmp_path and reads the question back
out of it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import question_queue, reference_pattern_audit
from dv_harness import source_authority as sa
from dv_harness.uvm_generator import address_map_verifier as amv

REPO_ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# The order itself
# ===========================================================================

def test_order_is_nine_consecutive_levels_highest_first():
    assert [s.rank for s in sa.AUTHORITY_ORDER] == list(range(1, 10))
    assert sa.AUTHORITY_ORDER[0].id == "simulation_result"
    assert sa.AUTHORITY_ORDER[-1].id == "vip_document"
    assert len({s.id for s in sa.AUTHORITY_ORDER}) == 9


def test_doc_and_code_orders_are_in_sync():
    """The real docs/RUN_PROFILE.md paragraph is PARSED and compared against
    AUTHORITY_ORDER -- not eyeballed."""
    result = sa.assert_doc_matches_code()
    assert result["status"] == "IN_SYNC"
    assert result["levels"] == 9
    assert sa.parse_documented_order() == [s.doc_phrase for s in sa.AUTHORITY_ORDER]


def test_doc_code_drift_is_detected():
    """Swap two levels in the doc text and the check must fail, naming the
    first differing level. Without this the sync test could pass forever on a
    parser that silently returns whatever it likes."""
    text = sa.DOC_PATH.read_text(encoding="utf-8")
    drifted = text.replace("8) VIP example, 9) VIP document.",
                           "8) VIP document, 9) VIP example.")
    assert drifted != text, "fixture precondition: the doc paragraph changed shape"
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.assert_doc_matches_code(drifted)
    assert exc.value.reason == "AUTHORITY_ORDER_DOC_CODE_DRIFT"
    assert exc.value.detail["first_difference"] == 8


def test_missing_paragraph_is_refused_not_silently_empty():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.parse_documented_order("# a doc with no authority paragraph at all\n\ntext\n")
    assert exc.value.reason == "AUTHORITY_ORDER_PARAGRAPH_NOT_FOUND"


def test_is_not_the_evidence_source_priority_gate_order():
    """Both lists are 9 items long, which has already caused one
    mis-identification. They answer different questions (conflict resolution
    vs. discovery search order) and must stay distinct mechanisms."""
    gate = REPO_ROOT / "tools" / "verification_flow" / "evidence_source_priority_gate.py"
    gate_text = gate.read_text(encoding="utf-8")
    assert "ASK_USER" in gate_text
    for s in sa.AUTHORITY_ORDER:
        assert s.id.upper() not in gate_text


def test_aliases_resolve_to_canonical_ids():
    assert sa.normalize_source("decoder") == "dut_rtl"
    assert sa.normalize_source("sim.log") == "simulation_result"
    assert sa.normalize_source("command.txt") == "reference_command_txt"
    assert sa.normalize_source("VIP Document") == "vip_document"
    # the doc's own phrase is always accepted
    assert sa.normalize_source("existing testbench binds") == "existing_testbench_bind"


def test_unknown_source_is_refused_not_ranked_last():
    """The dangerous silent default: an unknown source ranked last LOSES every
    conflict it takes part in, quietly."""
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.authority_rank("somebody's slack message")
    assert exc.value.reason == "UNKNOWN_AUTHORITY_SOURCE"


def test_register_file_dut_outranks_global():
    """The '(DUT then Global)' clause the prose left implicit."""
    assert sa.outranks("register_file", "register_file",
                       a_qualifier="dut", b_qualifier="global")
    assert not sa.outranks("register_file", "register_file",
                           a_qualifier="global", b_qualifier="dut")
    assert sa.sort_key("register_file", "dut") < sa.sort_key("register_file", "global")


def test_unknown_register_file_qualifier_is_refused():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.SourceClaim("register_file", "x", "regs.json:1", qualifier="chip_top")
    assert exc.value.reason == "UNKNOWN_REGISTER_FILE_QUALIFIER"


# ===========================================================================
# Claims and conflict resolution
# ===========================================================================

def test_claim_without_evidence_path_is_unconstructable():
    """The guarantee "the escalation carries both evidence paths" is enforced
    at claim construction, not at the far end where it is already too late."""
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "")
    assert exc.value.reason == "CLAIM_MUST_CITE_EVIDENCE_PATH"


def test_resolve_conflict_higher_authority_wins():
    conflict = sa.resolve_conflict([
        sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
    ])
    assert conflict["verdict"] == sa.VERDICT_RESOLVED
    assert conflict["winner"]["source"] == "dut_rtl"
    assert conflict["losers"][0]["source"] == "controller_doc"
    assert conflict["authority_gap"] == -3
    assert "DUT RTL (tier 3) outranks controller doc/programming guide (tier 6)" in conflict["rule"]
    assert conflict["evidence_paths"] == {
        "dut_rtl": ["rtl/decoder.sv:118"],
        "controller_doc": ["Doc/regs.md:88"],
    }


def test_resolve_conflict_reports_no_conflict_when_sources_agree():
    conflict = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_0000", "Doc/regs.md:88"),
    ])
    assert conflict["verdict"] == sa.VERDICT_NO_CONFLICT
    assert conflict["winner"] is None


def test_same_authority_disagreement_is_undecidable_not_arbitrarily_won():
    conflict = sa.resolve_conflict([
        sa.SourceClaim("reference_pattern_file", "offset 0020 is programmed", "p.txt:42"),
        sa.SourceClaim("command.txt", "offset 0020 is never programmed", "p.txt (absent)"),
    ])
    assert conflict["verdict"] == sa.VERDICT_UNDECIDABLE
    assert conflict["winner"] is None
    assert len(conflict["tied"]) == 2
    assert "cannot break a tie inside one level" in conflict["rule"]


def test_single_claim_is_not_a_conflict():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.resolve_conflict([sa.SourceClaim("dut_rtl", "x", "a.sv:1")])
    assert exc.value.reason == "CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS"


# ===========================================================================
# Escalation into the real question queue
# ===========================================================================

def _conflict():
    return sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
    ])


def test_escalate_conflict_persists_a_blocking_tier3_question(tmp_path):
    rec = sa.escalate_conflict(tmp_path, _conflict(), domain="dut",
                               subject="tca register base address")
    store = question_queue.QuestionQueueStore(tmp_path)
    persisted = store.get_question(rec["id"])
    assert persisted is not None, "the question must be on disk, not just returned"
    assert persisted["tier"] == question_queue.TIER3_CANNOT_ASSUME
    assert persisted["blocking"] is True
    assert persisted["status"] == "OPEN"
    assert persisted["owner"] == "designer"          # route_owner('dut'), not hand-typed
    assert "affects_spec_intent" in persisted["tier_reason"]


def test_escalated_question_carries_both_sides_evidence_paths(tmp_path):
    """The literal requirement: a question-queue entry carrying BOTH sides'
    evidence paths. Asserted against the PERSISTED record."""
    rec = sa.escalate_conflict(tmp_path, _conflict(), domain="dut",
                               subject="tca register base address")
    persisted = question_queue.QuestionQueueStore(tmp_path).get_question(rec["id"])
    blob = json.dumps(persisted)
    assert "rtl/decoder.sv:118" in blob
    assert "Doc/regs.md:88" in blob
    # one option per side, each carrying THAT side's path as its rationale
    rationales = [o["rationale"] for o in persisted["options"]]
    assert "evidence: rtl/decoder.sv:118" in rationales
    assert "evidence: Doc/regs.md:88" in rationales
    # and inline in the question text, so a digest that renders only
    # `question` still shows both
    assert "rtl/decoder.sv:118" in persisted["question"]
    assert "Doc/regs.md:88" in persisted["question"]


def test_recommendation_is_the_authority_order_winner(tmp_path):
    rec = sa.escalate_conflict(tmp_path, _conflict(), domain="dut", subject="base address")
    assert rec["recommendation"].startswith("Trust the DUT RTL (tier 3)")
    assert rec["recommendation"] in [o["label"] for o in rec["options"]]


def test_a_question_missing_an_evidence_path_can_never_be_persisted():
    """The pre-persist structural guard, exercised directly: a hand-built
    question text/options pair that drops one side is refused."""
    conflict = _conflict()
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.assert_both_evidence_paths_present(
            "the doc and the rtl disagree",
            [{"label": "Trust the RTL", "rationale": "evidence: rtl/decoder.sv:118"},
             {"label": "Trust the doc", "rationale": "no idea where this came from"}],
            conflict)
    assert exc.value.reason == "CONFLICT_QUESTION_MISSING_EVIDENCE_PATH"
    assert exc.value.detail["missing_evidence_paths"] == ["Doc/regs.md:88"]


def test_no_conflict_asks_nothing(tmp_path):
    agree = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_0000", "Doc/regs.md:88"),
    ])
    assert sa.escalate_conflict(tmp_path, agree, domain="dut", subject="base") is None
    assert question_queue.QuestionQueueStore(tmp_path).list_questions() == []


def test_re_escalating_the_same_conflict_does_not_grow_the_queue(tmp_path):
    """Re-running a detector over unchanged sources must not grow the queue.

    Regression guard for a real defect found by running the wired audit twice
    over the actual reference/bfm_patterns/ corpus: `add_question()` appends
    unconditionally, so the queue went 12 -> 24 questions with duplicate ids.
    Same id was never enough; the RECORD COUNT is the assertion that matters."""
    store = question_queue.QuestionQueueStore(tmp_path)
    a = sa.escalate_conflict(tmp_path, _conflict(), domain="dut", subject="base address")
    b = sa.escalate_conflict(tmp_path, _conflict(), domain="dut", subject="base address")
    assert a["id"] == b["id"]
    assert a["question_key"] == b["question_key"]
    assert len(store.list_questions()) == 1


def test_re_escalation_returns_the_answered_record_not_a_fresh_open_copy(tmp_path):
    """Once a human answers, a re-detected mismatch must surface THAT answer,
    never a new OPEN record that hides it."""
    store = question_queue.QuestionQueueStore(tmp_path)
    first = sa.escalate_conflict(tmp_path, _conflict(), domain="dut", subject="base address")
    store.answer_question(first["id"], answer="the doc is stale; RTL is right",
                          basis="designer confirmed 2026-09-04", decided_by="designer")
    again = sa.escalate_conflict(tmp_path, _conflict(), domain="dut", subject="base address")
    assert again["status"] == "ANSWERED"
    assert again["answer"] == "the doc is stale; RTL is right"
    assert len(store.list_questions()) == 1


def test_more_than_three_sides_is_refused_not_truncated(tmp_path):
    """Truncating to the schema's 3-option limit would drop a source's
    evidence path with it."""
    conflict = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "a", "rtl.sv:1"),
        sa.SourceClaim("controller_doc", "b", "doc.md:2"),
        sa.SourceClaim("ip_user_guide", "c", "ug.pdf:3"),
        sa.SourceClaim("vip_document", "d", "vip.md:4"),
    ])
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.escalate_conflict(tmp_path, conflict, domain="dut", subject="base")
    assert exc.value.reason == "CONFLICT_SIDES_MUST_BE_2_TO_3"


# ===========================================================================
# Wire 1: reference_pattern_audit host/DUT asymmetry -> question queue
# ===========================================================================

_ASYMMETRIC_PATTERN = """\
// synthetic fixture -- never real project content
initial begin
  `HOSTWRITE4B(32'hAA00_0004, 32'hFFFF); //enable_evt
  `CPUWRITE4B (32'hBB00_0004, 32'hFFFF); //enable_evt
  `HOSTWRITE4B(32'hAA00_0008, 32'h11  ); //mode_sel
  `CPUWRITE4B (32'hBB00_0008, 32'h11  ); //mode_sel
  `HOSTWRITE4B(32'hAA00_0020, 32'h2600); //synth_switch_en=1
  $finish;
end
"""


@pytest.fixture()
def asymmetric_dir(tmp_path: Path) -> Path:
    d = tmp_path / "patterns"
    d.mkdir()
    (d / "synth_asym.txt").write_text(_ASYMMETRIC_PATTERN, encoding="utf-8")
    return d


def test_audit_without_a_store_files_nothing(asymmetric_dir, tmp_path):
    """Report-only callers keep the pure, side-effect-free read they had."""
    result = reference_pattern_audit.audit_directory(asymmetric_dir)
    assert result["summary"]["verdict"] == "ASYMMETRY_FOUND"
    assert "escalated_questions" not in result
    assert not (tmp_path / ".dv-harness" / "question_queue" / "questions.json").exists()


def test_audit_escalates_each_asymmetry_with_both_evidence_paths(asymmetric_dir, tmp_path):
    root = tmp_path / "proj"
    result = reference_pattern_audit.audit_directory(asymmetric_dir, question_store=root)
    assert result["findings"], "fixture precondition: the synthetic pattern is asymmetric"
    assert len(result["escalated_questions"]) == len(result["findings"])

    store = question_queue.QuestionQueueStore(root)
    qs = store.list_questions()
    assert len(qs) == len(result["findings"])
    q = qs[0]
    assert q["tier"] == question_queue.TIER3_CANNOT_ASSUME and q["blocking"] is True
    assert q["owner"] == "designer"
    # side 1: the written-side citation, with a real file:line
    assert "synth_asym.txt:7" in q["question"]
    assert "HOSTWRITE4B" in q["question"]
    # side 2: the ABSENCE, cited well enough to be checkable
    assert "no DUT-side write to base BB00 offset 0020" in q["question"]


def test_asymmetry_is_reported_as_undecidable_same_authority(asymmetric_dir):
    """Both halves of a host/DUT asymmetry come from the same tier-2 source,
    so the order genuinely cannot decide it -- which is exactly why the
    escalation is mandatory rather than advisory."""
    result = reference_pattern_audit.audit_directory(asymmetric_dir)
    conflict = reference_pattern_audit.asymmetry_conflict(result["findings"][0])
    assert conflict["verdict"] == sa.VERDICT_UNDECIDABLE
    assert {c["rank"] for c in conflict["claims"]} == {2}


def test_audit_report_text_names_the_escalated_questions(asymmetric_dir, tmp_path):
    result = reference_pattern_audit.audit_directory(asymmetric_dir, question_store=tmp_path / "p")
    text = reference_pattern_audit.format_report(result)
    assert "Escalated to the question queue" in text
    for qid in result["escalated_questions"]:
        assert qid in text


def test_clean_audit_escalates_nothing(tmp_path):
    d = tmp_path / "clean"
    d.mkdir()
    (d / "sym.txt").write_text(
        "`HOSTWRITE4B(32'hAA00_0004, 32'h1); //a\n"
        "`CPUWRITE4B (32'hBB00_0004, 32'h1); //a\n"
        "`HOSTWRITE4B(32'hAA00_0008, 32'h2); //b\n"
        "`CPUWRITE4B (32'hBB00_0008, 32'h2); //b\n", encoding="utf-8")
    result = reference_pattern_audit.audit_directory(d, question_store=tmp_path / "p")
    assert result["summary"]["verdict"] == "CLEAN"
    assert result["escalated_questions"] == []
    assert question_queue.QuestionQueueStore(tmp_path / "p").list_questions() == []


#: The real DE-provided pattern corpus, outside this repo. Same read-only
#: integration convention (and same skip-not-fail rule) as
#: test_reference_pattern_audit.py's own real-corpus tier.
_REAL_PATTERN_DIR = Path("D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns")


@pytest.mark.skipif(not _REAL_PATTERN_DIR.is_dir(),
                    reason=f"real reference pattern corpus not present at {_REAL_PATTERN_DIR}")
def test_real_usb_p2_switch_en_asymmetry_becomes_a_real_question(tmp_path):
    """The bug that cost 3 debugging rounds, escalated instead of reported.

    Also the idempotence check that actually caught the duplicate-append
    defect: the synthetic fixture has one finding, so a doubled queue and a
    correct one differ by a single record there. Twelve findings over the
    real corpus made 12 -> 24 impossible to miss."""
    root = tmp_path / "proj"
    result = reference_pattern_audit.audit_directory(_REAL_PATTERN_DIR, question_store=root)
    assert result["summary"]["verdict"] == "ASYMMETRY_FOUND"
    store = question_queue.QuestionQueueStore(root)
    first_count = len(store.list_questions())
    assert first_count == result["summary"]["findings_count"] > 0

    p2 = [q for q in store.list_questions() if "usb_p2_switch_en" in q["question"]]
    assert p2, "the known real TCA asymmetry must reach the queue"
    q = p2[0]
    assert q["tier"] == question_queue.TIER3_CANNOT_ASSUME and q["blocking"] is True
    assert "HOSTWRITE4B" in q["question"] and "161A" in q["question"]   # written side
    assert "NEVER programmed DUT-side" in q["question"]                  # absent side

    reference_pattern_audit.audit_directory(_REAL_PATTERN_DIR, question_store=root)
    reference_pattern_audit.audit_directory(_REAL_PATTERN_DIR, question_store=root)
    assert len(store.list_questions()) == first_count


# ===========================================================================
# Wire 2: address_map_verifier doc disagreement -> question queue
# ===========================================================================

_DECODER = [{"instance": "tca", "base": "0x1272_0000",
             "evidence": "rtl/usb_decoder.sv:118 (address comparator)"}]
_HIST = [{"base": "0x1272_0000", "access_count": 12, "source": "reference/bfm_patterns/USB2_bulkin.txt"}]
_DOC_DISAGREES = [{"instance": "tca", "base": "0x1272_8000", "doc_ref": "Doc/USB31_prog_guide.md:412"}]
_DOC_AGREES = [{"instance": "tca", "base": "0x1272_0000", "doc_ref": "Doc/USB31_prog_guide.md:412"}]


def test_doc_disagreement_escalates_with_both_evidence_paths(tmp_path):
    verified = amv.verify_address_map(_DECODER, _HIST, _DOC_DISAGREES, question_store=tmp_path)
    assert verified[0]["doc_status"] == "DISAGREES"
    qs = question_queue.QuestionQueueStore(tmp_path).list_questions()
    assert len(qs) == 1
    blob = json.dumps(qs[0])
    assert "rtl/usb_decoder.sv:118 (address comparator)" in blob   # side 1: the decoder
    assert "Doc/USB31_prog_guide.md:412" in blob                    # side 2: the doc
    assert qs[0]["tier"] == question_queue.TIER3_CANNOT_ASSUME


def test_escalation_does_not_make_committal_blocking(tmp_path):
    """address_map_verifier's own "a document disagreement does not block
    committal" contract is preserved exactly: same return value, and the
    `define is still emitted."""
    quiet = amv.verify_address_map(_DECODER, _HIST, _DOC_DISAGREES)
    loud = amv.verify_address_map(_DECODER, _HIST, _DOC_DISAGREES, question_store=tmp_path)
    assert quiet == loud
    emitted = amv.emit_verified_base_addr_defines(loud, "usb31")
    assert "`define USB31_TCA_BASE_ADDR 32'h12720000" in emitted
    assert "DOC DISAGREEMENT (not blocking" in emitted


def test_agreeing_doc_escalates_nothing(tmp_path):
    amv.verify_address_map(_DECODER, _HIST, _DOC_AGREES, question_store=tmp_path)
    assert question_queue.QuestionQueueStore(tmp_path).list_questions() == []


def test_missing_doc_escalates_nothing(tmp_path):
    amv.verify_address_map(_DECODER, _HIST, None, question_store=tmp_path)
    assert question_queue.QuestionQueueStore(tmp_path).list_questions() == []


def test_doc_disagreement_conflict_resolves_in_the_decoders_favour():
    verified = amv.verify_address_map(_DECODER, _HIST, _DOC_DISAGREES)
    conflict = amv.doc_disagreement_conflict(verified[0])
    assert conflict["verdict"] == sa.VERDICT_RESOLVED
    assert conflict["winner"]["source"] == "dut_rtl"
    assert conflict["winner"]["rank"] < conflict["losers"][0]["rank"]


def test_fabricating_a_conflict_for_an_agreeing_entry_is_refused():
    verified = amv.verify_address_map(_DECODER, _HIST, _DOC_AGREES)
    with pytest.raises(amv.AddressMapVerificationError) as exc:
        amv.doc_disagreement_conflict(verified[0])
    assert exc.value.reason == "NOT_A_DOC_DISAGREEMENT"


# ===========================================================================
# CLI surface
# ===========================================================================

def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "dv_harness", *args],
                          cwd=str(cwd or REPO_ROOT), capture_output=True, text=True)


def test_cli_authority_check_doc_passes_against_the_real_doc():
    proc = _cli("authority", "check-doc")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "IN_SYNC"


def test_cli_authority_order_lists_nine_levels():
    proc = _cli("authority", "order", "--json")
    assert proc.returncode == 0, proc.stderr
    levels = json.loads(proc.stdout)
    assert [l["rank"] for l in levels] == list(range(1, 10))


def test_cli_reference_audit_escalate_files_real_questions(asymmetric_dir, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    proc = _cli("--project-root", str(root), "reference-audit", str(asymmetric_dir), "--escalate")
    assert proc.returncode == 1, proc.stderr          # asymmetry found -> exit 1, unchanged
    assert "Escalated to the question queue" in proc.stdout
    assert question_queue.QuestionQueueStore(root).list_questions()


# ===========================================================================
# Conflict-type taxonomy (2026-09-06 additive extension)
# ===========================================================================

def test_taxonomy_has_exactly_ten_values_and_is_closed():
    """The task-specified 10-value vocabulary, verbatim -- and every
    CONFLICT_TYPE_* constant's value must actually be one of the ten (the
    guard `assert_conflict_type_vocabulary_is_closed()` runs at import)."""
    assert len(sa.CONFLICT_TYPES) == 10
    assert set(sa.CONFLICT_TYPES) == {
        "DOC_DOC_CONFLICT", "DOC_RTL_CONFLICT", "REGISTER_RTL_CONFLICT",
        "GUIDE_REGISTER_CONFLICT", "PHY_SPEC_MODEL_CONFLICT", "VERSION_CONFLICT",
        "CONFIGURATION_CONFLICT", "COMMAND_TASK_CONFLICT", "VIP_DOC_SOURCE_CONFLICT",
        "UNKNOWN",
    }
    sa.assert_conflict_type_vocabulary_is_closed()  # must not raise


def test_every_authority_order_id_has_a_conflict_kind():
    """A future 10th AUTHORITY_ORDER level must not go unclassified here."""
    assert set(sa._AUTHORITY_ID_TO_KIND.keys()) == {s.id for s in sa.AUTHORITY_ORDER}


@pytest.mark.parametrize("a,b,expected", [
    ("controller_doc", "dut_rtl", "DOC_RTL_CONFLICT"),
    ("dut_rtl", "controller_doc", "DOC_RTL_CONFLICT"),           # order-independent
    ("register_file", "dut_rtl", "REGISTER_RTL_CONFLICT"),
    ("ip_user_guide", "register_file", "GUIDE_REGISTER_CONFLICT"),
    ("phy_model", "spec", "PHY_SPEC_MODEL_CONFLICT"),
    ("phy_boundary", "datasheet", "PHY_SPEC_MODEL_CONFLICT"),     # extra-kind aliases resolve too
    ("version", "version", "VERSION_CONFLICT"),
    ("tool_version", "vip_version", "VERSION_CONFLICT"),
    ("configuration", "configuration", "CONFIGURATION_CONFLICT"),
    ("config", "cfg", "CONFIGURATION_CONFLICT"),
    ("reference_command_txt", "reference_command_txt", "COMMAND_TASK_CONFLICT"),
    ("command.txt", "makefile", "COMMAND_TASK_CONFLICT"),         # AUTHORITY_ORDER aliases
    ("vip_document", "vip_example", "VIP_DOC_SOURCE_CONFLICT"),
    ("controller_doc", "controller_doc", "DOC_DOC_CONFLICT"),
    ("spec_doc", "programming_doc", "DOC_DOC_CONFLICT"),          # both alias to controller_doc
])
def test_classify_conflict_type_maps_named_pairs(a, b, expected):
    assert sa.classify_conflict_type(a, b) == expected


@pytest.mark.parametrize("a,b", [
    ("simulation_result", "controller_doc"),
    ("existing_testbench_bind", "dut_rtl"),
    ("simulation_result", "simulation_result"),
    ("vip_example", "controller_doc"),
])
def test_classify_conflict_type_unrelated_pairs_are_unknown_not_guessed(a, b):
    """A pair the table does not name must read UNKNOWN, never a plausible
    -looking but invented category."""
    assert sa.classify_conflict_type(a, b) == "UNKNOWN"


def test_classify_conflict_type_refuses_an_unrecognized_source():
    """Same discipline as `normalize_source()`: an unrecognized source must
    never be silently classified UNKNOWN, because that would hide a real
    typo behind the taxonomy's own honest 'no named shape fits' value."""
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.classify_conflict_type("somebody's slack message", "dut_rtl")
    assert exc.value.reason == "UNKNOWN_CONFLICT_SOURCE_KIND"


def test_classify_conflict_reads_a_real_resolve_conflict_record():
    """The literal task requirement: classify a REAL conflict record (from
    `resolve_conflict()`), not a hand-built stand-in."""
    conflict = sa.resolve_conflict([
        sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
    ])
    assert conflict["verdict"] == sa.VERDICT_RESOLVED  # fixture precondition
    assert sa.classify_conflict(conflict) == "DOC_RTL_CONFLICT"


def test_classify_conflict_classifies_no_conflict_records_too():
    """The taxonomy is about which two source TYPES were being compared, not
    about whether they agreed -- a NO_CONFLICT record still classifies."""
    conflict = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_0000", "Doc/regs.md:88"),
    ])
    assert conflict["verdict"] == sa.VERDICT_NO_CONFLICT  # fixture precondition
    assert sa.classify_conflict(conflict) == "DOC_RTL_CONFLICT"


def test_classify_conflict_reads_an_undecidable_same_authority_record():
    conflict = sa.resolve_conflict([
        sa.SourceClaim("reference_pattern_file", "offset 0020 is programmed", "p.txt:42"),
        sa.SourceClaim("command.txt", "offset 0020 is never programmed", "p.txt (absent)"),
    ])
    assert conflict["verdict"] == sa.VERDICT_UNDECIDABLE  # fixture precondition
    assert sa.classify_conflict(conflict) == "COMMAND_TASK_CONFLICT"


def test_classify_conflict_accepts_ad_hoc_source_a_source_b_shape():
    """A disagreement between two kinds AUTHORITY_ORDER has no level for at
    all (a PHY model vs. a spec doc) can never reach `resolve_conflict()` --
    `SourceClaim` correctly refuses to rank either one -- but it is still a
    real, nameable conflict shape."""
    assert sa.classify_conflict({"source_a": "phy_model", "source_b": "spec"}) \
        == "PHY_SPEC_MODEL_CONFLICT"


def test_classify_conflict_accepts_ad_hoc_sources_list_shape():
    assert sa.classify_conflict({"sources": ["configuration", "configuration"]}) \
        == "CONFIGURATION_CONFLICT"


def test_classify_conflict_refuses_more_than_two_distinct_source_types():
    """A pairwise classification, mirroring escalate_conflict()'s own 2-3
    -sides boundary: a 3-plus-way disagreement does not reduce to one
    labelled pair without deciding which two sides the label is about."""
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.classify_conflict({"sources": ["dut_rtl", "controller_doc", "ip_user_guide"]})
    assert exc.value.reason == "CONFLICT_TYPE_NEEDS_ONE_OR_TWO_SOURCE_TYPES"


def test_classify_conflict_refuses_an_unrecognized_record_shape():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.classify_conflict({"nothing_this_function_understands": True})
    assert exc.value.reason == "CONFLICT_RECORD_SHAPE_NOT_RECOGNIZED"


def test_classify_conflict_refuses_a_record_with_no_claims_or_sources():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.classify_conflict({"claims": []})
    assert exc.value.reason == "CONFLICT_RECORD_SHAPE_NOT_RECOGNIZED"


def test_classify_conflict_refuses_a_non_dict_record():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        sa.classify_conflict(["not", "a", "dict"])
    assert exc.value.reason == "CONFLICT_RECORD_MUST_BE_A_DICT"
