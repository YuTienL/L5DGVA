"""Tests for dv_harness.intake_source_priority -- the 10-step INTAKE
DISCOVERY ladder (which source to consult FIRST for a fact not yet known),
kept provably distinct from two pre-existing lists it is easy to confuse it
with: `source_authority.AUTHORITY_ORDER` (a CONFLICT-resolution order for
facts already read from two disagreeing sources) and
`tools/verification_flow/evidence_source_priority_gate.py`'s own 9-item
`ORDER` (a different, narrower DISCOVERY order for one gate's evidence-trace
shape).

Nothing here is a mock: the cross-check tests read the real
`source_authority.AUTHORITY_ORDER` and the real gate script's real source
text off disk, never a hand-typed copy of either.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import intake_source_priority as isp
from dv_harness import source_authority as sa

REPO_ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# The order itself
# ===========================================================================

def test_order_is_ten_consecutive_steps_check_first_to_last():
    assert [s.rank for s in isp.INTAKE_SOURCE_ORDER] == list(range(1, 11))
    assert len({s.id for s in isp.INTAKE_SOURCE_ORDER}) == 10
    assert isp.INTAKE_SOURCE_ORDER[0].id == "repo_files_on_disk"
    assert isp.INTAKE_SOURCE_ORDER[-1].id == "ask_user"


def test_order_matches_the_task_specified_ten_steps_in_order():
    assert [s.id for s in isp.INTAKE_SOURCE_ORDER] == [
        "repo_files_on_disk",
        "existing_uvm_environment",
        "build_scripts_makefile",
        "rtl_phy_source",
        "register_files",
        "specs_datasheets",
        "vip_examples",
        "regression_lists",
        "git_history",
        "ask_user",
    ]


def test_normalize_intake_source_resolves_aliases_case_and_punctuation():
    assert isp.normalize_intake_source("RTL/PHY source") == "rtl_phy_source"
    assert isp.normalize_intake_source("makefile") == "build_scripts_makefile"
    assert isp.normalize_intake_source("Ask-The-User") == "ask_user"
    assert isp.normalize_intake_source("git_log") == "git_history"


def test_normalize_intake_source_refuses_unknown_name_rather_than_guessing():
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.normalize_intake_source("simulation_result")  # a source_authority id
    assert exc.value.reason == "UNKNOWN_INTAKE_SOURCE"
    assert "known_ids" in exc.value.detail


def test_intake_rank_orders_check_first_lowest():
    assert isp.intake_rank("repo_files_on_disk") < isp.intake_rank("rtl_phy_source")
    assert isp.intake_rank("rtl_phy_source") < isp.intake_rank("ask_user")


# ===========================================================================
# next_sources_to_check(): the lookup this module exists to provide
# ===========================================================================

def test_next_sources_orders_available_sources_by_discovery_priority():
    rows = isp.next_sources_to_check(
        "does this project already model interrupt X",
        ["git_history", "repo_files_on_disk", "rtl_phy_source", "ask_user"],
    )
    assert [r["id"] for r in rows] == [
        "repo_files_on_disk", "rtl_phy_source", "git_history", "ask_user",
    ]
    # fact_name is carried through on every row for the caller's own evidence
    # trail, and does not change the ranking.
    assert all(r["fact_name"] == "does this project already model interrupt X" for r in rows)


def test_next_sources_never_reorders_ask_user_ahead_of_an_offered_source():
    """Ask-the-user must never come before a higher-priority source that was
    actually declared available -- the exact 'ASKED_USER_TOO_EARLY' failure
    mode the pre-existing evidence_source_priority_gate.py guards against for
    its own 9-item order."""
    rows = isp.next_sources_to_check("register default value", ["ask_user", "register_files"])
    assert [r["id"] for r in rows] == ["register_files", "ask_user"]


def test_next_sources_same_available_set_same_order_regardless_of_fact():
    """The ladder is a table of SOURCE KINDS, not a per-fact heuristic: two
    different facts with the same available sources get the identical
    ordering."""
    available = ["specs_datasheets", "vip_examples", "build_scripts_makefile"]
    rows_a = isp.next_sources_to_check("fact A", available)
    rows_b = isp.next_sources_to_check("fact B", available)
    assert [r["id"] for r in rows_a] == [r["id"] for r in rows_b]


def test_first_source_to_check_convenience():
    row = isp.first_source_to_check("clock gating default", ["specs_datasheets", "rtl_phy_source"])
    assert row["id"] == "rtl_phy_source"


# --- negative controls -----------------------------------------------------

def test_next_sources_refuses_empty_fact_name():
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.next_sources_to_check("   ", ["repo_files_on_disk"])
    assert exc.value.reason == "FACT_NAME_MUST_BE_STATED"


def test_next_sources_refuses_empty_availability_rather_than_defaulting_to_ask_user():
    """An empty availability list must be a refusal, never a silent
    'ask the user' -- the caller has not stated a real intake situation."""
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.next_sources_to_check("fact", [])
    assert exc.value.reason == "NO_AVAILABLE_SOURCES_DECLARED"


def test_next_sources_refuses_unknown_available_source_rather_than_dropping_it():
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.next_sources_to_check("fact", ["repo_files_on_disk", "totally_made_up_source"])
    assert exc.value.reason == "UNKNOWN_INTAKE_SOURCE"


def test_next_sources_deduplicates_an_available_source_named_twice():
    rows = isp.next_sources_to_check("fact", ["rtl", "rtl_phy_source", "rtl_source"])
    assert [r["id"] for r in rows] == ["rtl_phy_source"]


# ===========================================================================
# The required cross-check: never confused with the two pre-existing lists
# ===========================================================================

def test_intake_ladder_is_a_different_length_from_authority_order():
    """source_authority.py's own docstring records that its 9-item conflict
    order and the pre-existing 9-item discovery gate order have ALREADY been
    mis-identified once purely on matching length. This ladder is 10 items,
    which structurally rules out repeating that exact coincidence."""
    assert len(isp.INTAKE_SOURCE_ORDER) != len(sa.AUTHORITY_ORDER)
    assert len(isp.INTAKE_SOURCE_ORDER) == 10
    assert len(sa.AUTHORITY_ORDER) == 9


def test_intake_ladder_canonical_ids_never_resolve_in_authority_order():
    """No canonical id of this table may resolve through
    source_authority.normalize_source() -- otherwise a caller holding an id
    from THIS table could hand it to the OTHER module and get a confident
    (wrong) answer instead of an UNKNOWN_AUTHORITY_SOURCE refusal.

    Deliberately does NOT assert zero alias overlap: both tables legitimately
    discuss some of the same real artifacts (RTL, register files, VIP
    examples), so an ordinary synonym like "rtl" or "makefile" appearing in
    both tables' own `aliases` is expected and is not the dangerous case --
    see `assert_distinct_from_known_discovery_and_conflict_orders`'s own
    docstring for why canonical-id cross-resolution is the property that
    actually matters.
    """
    for level in isp.INTAKE_SOURCE_ORDER:
        with pytest.raises(sa.SourceAuthorityError):
            sa.normalize_source(level.id)


def test_authority_order_canonical_ids_never_resolve_in_intake_ladder():
    for level in sa.AUTHORITY_ORDER:
        with pytest.raises(isp.IntakeSourcePriorityError):
            isp.normalize_intake_source(level.id)


def test_intake_ladder_phrases_are_disjoint_from_authority_order_phrases():
    intake_phrases = {s.phrase.lower() for s in isp.INTAKE_SOURCE_ORDER}
    authority_phrases = {s.doc_phrase.lower() for s in sa.AUTHORITY_ORDER}
    assert not (intake_phrases & authority_phrases)


def test_assert_distinct_passes_against_the_real_repo_state():
    result = isp.assert_distinct_from_known_discovery_and_conflict_orders()
    assert result["status"] == "DISTINCT"
    assert result["intake_levels"] == 10
    assert result["authority_order_levels"] == 9
    assert result["evidence_source_priority_gate_order_levels"] == 9


def test_assert_distinct_reads_the_real_gate_script_order_not_a_hand_copy():
    """The comparison target is the REAL evidence_source_priority_gate.py
    ORDER constant, parsed off disk -- not a value re-typed in this test
    suite or in the module under test."""
    real_text = isp.EVIDENCE_SOURCE_PRIORITY_GATE_PATH.read_text(encoding="utf-8")
    parsed = isp.parse_evidence_source_priority_gate_order(real_text)
    assert parsed == [
        "EXISTING_PROJECT_FILES", "RTL_PARAMETERS_DEFINES", "EXISTING_UVM_VIP_CONFIG",
        "EXISTING_TESTS_SEQUENCES", "DESIGN_DOCS", "VPLAN_TEST_TABLE",
        "BUILD_REGRESSION_SCRIPTS", "GIT_HISTORY_COMMENTS", "ASK_USER",
    ]
    # And it disagrees with this module's own ten phrases, word for word.
    assert parsed != [s.phrase for s in isp.INTAKE_SOURCE_ORDER]


# --- negative controls: the cross-check must actually be able to fail -----

def test_cross_check_trips_if_the_gate_order_were_ever_ten_items_long():
    """Mutate only the comparison TEXT (never the real file) to prove the
    length guard against the gate script's order has real detection power,
    not just a hardcoded '10 != 9' that would pass regardless of content."""
    fabricated_ten_item_order = (
        "ORDER=['A','B','C','D','E','F','G','H','I','J']"
    )
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.assert_distinct_from_known_discovery_and_conflict_orders(
            gate_order_text=fabricated_ten_item_order)
    assert exc.value.reason == (
        "INTAKE_LADDER_LENGTH_CONFUSABLE_WITH_EVIDENCE_SOURCE_PRIORITY_GATE_ORDER"
    )


def test_cross_check_trips_if_the_gate_order_were_ever_identical_content():
    """A fabricated 10-item ORDER whose phrases are byte-identical to this
    module's own ten phrases must be caught by the CONTENT check, proving
    that check is not vacuous once the length check alone cannot apply."""
    ten_identical_phrases = ",".join(f"'{s.phrase}'" for s in isp.INTAKE_SOURCE_ORDER)
    fabricated_text = f"ORDER=[{ten_identical_phrases}]"
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.assert_distinct_from_known_discovery_and_conflict_orders(
            gate_order_text=fabricated_text)
    assert exc.value.reason == "INTAKE_LADDER_IDENTICAL_TO_EVIDENCE_SOURCE_PRIORITY_GATE_ORDER"


def test_parse_gate_order_refuses_text_with_no_order_constant():
    with pytest.raises(isp.IntakeSourcePriorityError) as exc:
        isp.parse_evidence_source_priority_gate_order("no order constant in here at all")
    assert exc.value.reason == "EVIDENCE_SOURCE_PRIORITY_GATE_ORDER_NOT_FOUND"


def test_importing_the_gate_script_module_would_be_unsafe_so_this_module_never_does():
    """Documents (and locks in) WHY parse_evidence_source_priority_gate_order
    reads the file's text instead of importing it: the gate script calls
    argparse.parse_args() at module level with no __main__ guard, so an
    import outside its own CLI invocation raises/exits immediately."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import tools.verification_flow.evidence_source_priority_gate"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode != 0


# ===========================================================================
# Rendering / standalone front door
# ===========================================================================

def test_describe_order_is_json_serializable_and_matches_the_table():
    rows = isp.describe_order()
    assert len(rows) == 10
    assert [r["id"] for r in rows] == [s.id for s in isp.INTAKE_SOURCE_ORDER]


def test_format_order_names_the_module_and_lists_all_ten():
    text = isp.format_order()
    assert "dv_harness/intake_source_priority.py" in text
    for s in isp.INTAKE_SOURCE_ORDER:
        assert s.phrase in text


def test_cli_order_verb_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_source_priority", "order"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "repo files already on disk" in proc.stdout


def test_cli_self_check_verb_exits_zero_against_the_real_repo():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_source_priority", "self-check"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert '"status": "DISTINCT"' in proc.stdout


def test_cli_next_verb_exits_zero_with_a_non_ask_user_source_available():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_source_priority", "next",
         "--fact", "clock default", "--available", "rtl_phy_source,ask_user", "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert '"id": "rtl_phy_source"' in proc.stdout


def test_cli_next_verb_exits_one_when_ask_user_is_the_only_available_source():
    """Exit code 1 == a real finding: nothing but a human is available."""
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_source_priority", "next",
         "--fact", "clock default", "--available", "ask_user", "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 1


def test_cli_next_verb_exits_two_on_unknown_source():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_source_priority", "next",
         "--fact", "clock default", "--available", "not_a_real_source"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 2
