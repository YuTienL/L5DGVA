"""Real tests for dv_harness/contextual_source_precedence.py -- the additive
per-fact-type override layer on top of source_authority.py's fixed 9-level
AUTHORITY_ORDER, plus its additive integration into design_source_inventory.py.
"""
import pytest

from dv_harness import contextual_source_precedence as csp
from dv_harness import source_authority as sa
from dv_harness import design_source_inventory as dsi


# ---------------------------------------------------------------------------
# FactTypeOverride construction: the Evidence Truth Rule enforced at the
# override's own construction boundary.
# ---------------------------------------------------------------------------

def test_override_refuses_construction_with_no_evidence():
    """NEGATIVE CONTROL: the module refuses to fabricate a precedence claim
    when no evidence citation is supplied -- the same discipline every other
    caller-declared-fact module in this project already applies."""
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(
            fact_type="bogus",
            order=tuple(s.id for s in sa.AUTHORITY_ORDER),
            evidence="",
        )
    assert exc.value.reason == "OVERRIDE_MUST_CITE_EVIDENCE"


def test_override_refuses_construction_with_blank_evidence():
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(
            fact_type="bogus",
            order=tuple(s.id for s in sa.AUTHORITY_ORDER),
            evidence="   ",
        )
    assert exc.value.reason == "OVERRIDE_MUST_CITE_EVIDENCE"


def test_override_refuses_empty_fact_type():
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(
            fact_type="  ",
            order=tuple(s.id for s in sa.AUTHORITY_ORDER),
            evidence="cited",
        )
    assert exc.value.reason == "FACT_TYPE_MUST_BE_STATED"


def test_override_refuses_a_subset_missing_one_source():
    base_ids = [s.id for s in sa.AUTHORITY_ORDER]
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(
            fact_type="bogus", order=tuple(base_ids[:-1]), evidence="cited",
        )
    assert exc.value.reason == "OVERRIDE_MUST_BE_A_PERMUTATION_OF_AUTHORITY_ORDER"


def test_override_refuses_a_duplicated_source():
    base_ids = [s.id for s in sa.AUTHORITY_ORDER]
    dup = tuple(base_ids[:-1]) + (base_ids[0],)
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(fact_type="bogus", order=dup, evidence="cited")
    assert exc.value.reason == "OVERRIDE_MUST_BE_A_PERMUTATION_OF_AUTHORITY_ORDER"


def test_override_refuses_an_invented_source_id():
    base_ids = [s.id for s in sa.AUTHORITY_ORDER]
    bogus_order = tuple(base_ids[:-1]) + ("made_up_source",)
    with pytest.raises(csp.ContextualSourcePrecedenceError) as exc:
        csp.FactTypeOverride(fact_type="bogus", order=bogus_order, evidence="cited")
    assert exc.value.reason == "OVERRIDE_NAMES_UNKNOWN_SOURCE"


def test_override_accepts_a_real_permutation_with_real_evidence():
    base_ids = [s.id for s in sa.AUTHORITY_ORDER]
    reordered = tuple(reversed(base_ids))
    o = csp.FactTypeOverride(fact_type="demo", order=reordered, evidence="real citation")
    assert o.fact_type == "demo"
    assert set(o.order) == set(base_ids)
    assert o.rank_of[reordered[0]] == 1
    assert o.rank_of[reordered[-1]] == 9


def test_override_normalizes_aliases_in_order():
    """The `order` tuple may be given via any registered alias, not only the
    canonical id -- normalised the same way source_authority.normalize_source
    already normalises everything else."""
    base_ids = [s.id for s in sa.AUTHORITY_ORDER]
    # replace one canonical id with a real alias for the same source
    aliased = ["sim_log" if x == "simulation_result" else x for x in base_ids]
    o = csp.FactTypeOverride(fact_type="demo2", order=tuple(aliased), evidence="cited")
    assert o.order[0] == "simulation_result"


# ---------------------------------------------------------------------------
# The shipped, real "timing" override table entry.
# ---------------------------------------------------------------------------

def test_shipped_timing_override_is_a_valid_permutation():
    assert "timing" in csp.known_fact_types()
    override = csp.FACT_TYPE_OVERRIDES["timing"]
    assert set(override.order) == {s.id for s in sa.AUTHORITY_ORDER}
    assert override.evidence.strip()


def test_shipped_timing_override_moves_controller_doc_above_dut_rtl():
    """The task's own worked example, made checkable: for the 'timing' fact
    type, controller_doc (the datasheet/programming-guide stand-in) outranks
    dut_rtl (the RTL comment)."""
    rank_doc, used_doc = csp.contextual_rank("controller_doc", "timing")
    rank_rtl, used_rtl = csp.contextual_rank("dut_rtl", "timing")
    assert used_doc == used_rtl == "PER_FACT_TYPE_OVERRIDE"
    assert rank_doc < rank_rtl  # lower number = higher authority = wins


def test_base_order_has_the_opposite_relationship_for_functional_facts():
    """Confirms the reversal is real: under the UNMODIFIED base order (no
    fact_type at all, i.e. the 'functional' case), dut_rtl outranks
    controller_doc -- the exact opposite of the timing case above."""
    assert sa.authority_rank("dut_rtl") < sa.authority_rank("controller_doc")


# ---------------------------------------------------------------------------
# contextual_rank / contextual_sort_key: unknown fact_type -> base order.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fact_type", [None, "", "functional", "some_unregistered_kind"])
def test_contextual_rank_falls_back_to_base_order_when_no_override_declared(fact_type):
    for src in ("simulation_result", "dut_rtl", "controller_doc", "vip_document"):
        rank, used = csp.contextual_rank(src, fact_type)
        assert used == "BASE_AUTHORITY_ORDER"
        assert rank == sa.authority_rank(src)


def test_contextual_rank_raises_on_unknown_source_never_fabricates():
    """NEGATIVE CONTROL: an unrecognised source name is never silently
    ranked, whether or not a fact_type override is in play."""
    with pytest.raises(sa.SourceAuthorityError) as exc:
        csp.contextual_rank("totally_made_up_source", "timing")
    assert exc.value.reason == "UNKNOWN_AUTHORITY_SOURCE"

    with pytest.raises(sa.SourceAuthorityError):
        csp.contextual_rank("totally_made_up_source", None)


def test_contextual_sort_key_reuses_register_file_suborder_tie_break():
    """The DUT-then-Global tie-break inside tier 'register_file' is decided
    identically whether or not a fact-type override applies, because it is
    reused from source_authority.sort_key(), never re-derived."""
    dut_key = csp.contextual_sort_key("register_file", None, qualifier="dut")
    global_key = csp.contextual_sort_key("register_file", None, qualifier="global")
    assert dut_key < global_key

    dut_key_timing = csp.contextual_sort_key("register_file", "timing", qualifier="dut")
    global_key_timing = csp.contextual_sort_key("register_file", "timing", qualifier="global")
    assert dut_key_timing < global_key_timing
    # rank component is identical in both cases (register_file isn't reordered
    # by the timing override); only the subrank differs by qualifier.
    assert dut_key_timing[0] == global_key_timing[0]


def test_contextual_sort_key_raises_on_bad_qualifier():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        csp.contextual_sort_key("register_file", "timing", qualifier="not_a_real_qualifier")
    assert exc.value.reason == "UNKNOWN_REGISTER_FILE_QUALIFIER"


# ---------------------------------------------------------------------------
# resolve_conflict_for_fact_type: agreement with source_authority.resolve_
# conflict() when no override applies, and genuine reversal when one does.
# ---------------------------------------------------------------------------

def _claim(source, claim, path, qualifier=None):
    return sa.SourceClaim(source=source, claim=claim, evidence_path=path, qualifier=qualifier)


def test_no_override_reduces_to_exactly_source_authority_resolve_conflict():
    """Proves 'never replace source_authority.py's own order': for a fact
    type with no declared override (here 'functional', the task's own
    unchanged worked example), this module's verdict must be byte-identical
    to calling source_authority.resolve_conflict() directly on the same
    claims."""
    claims = [
        _claim("dut_rtl", "mode bit is active-high", "rtl/foo.v:12"),
        _claim("controller_doc", "mode bit is active-low", "doc/foo.md:5"),
    ]
    base_result = sa.resolve_conflict(claims)
    contextual_result = csp.resolve_conflict_for_fact_type(claims, "functional")

    assert contextual_result["verdict"] == base_result["verdict"] == sa.VERDICT_RESOLVED
    assert contextual_result["winner"]["source"] == base_result["winner"]["source"] == "dut_rtl"
    assert contextual_result["winner"]["rank"] == base_result["winner"]["rank"]
    assert contextual_result["winner"]["contextual_rank"] == base_result["winner"]["rank"]
    assert contextual_result["evidence_paths"] == base_result["evidence_paths"]
    assert contextual_result["authority_order_used"] == "BASE_AUTHORITY_ORDER"


def test_no_override_also_agrees_on_undecidable_verdict():
    claims = [
        _claim("dut_rtl", "claim A", "rtl/a.v:1"),
        _claim("dut_rtl", "claim B (disagrees)", "rtl/b.v:2"),
    ]
    base_result = sa.resolve_conflict(claims)
    contextual_result = csp.resolve_conflict_for_fact_type(claims, "unregistered_fact_type")
    assert base_result["verdict"] == contextual_result["verdict"] == sa.VERDICT_UNDECIDABLE
    assert base_result["winner"] is None and contextual_result["winner"] is None


def test_no_override_agrees_on_no_conflict_verdict():
    claims = [
        _claim("dut_rtl", "same claim text", "rtl/a.v:1"),
        _claim("controller_doc", "same claim text", "doc/b.md:2"),
    ]
    base_result = sa.resolve_conflict(claims)
    contextual_result = csp.resolve_conflict_for_fact_type(claims, None)
    assert base_result["verdict"] == contextual_result["verdict"] == sa.VERDICT_NO_CONFLICT
    assert contextual_result["winner"] is None


def test_timing_fact_type_reverses_the_winner_versus_base_order():
    """The core positive proof: the SAME two disagreeing claims resolve to a
    DIFFERENT winner depending on fact_type -- dut_rtl wins under the base
    (functional) order, controller_doc wins under the 'timing' override."""
    claims = [
        _claim("dut_rtl", "clock runs at 100MHz", "rtl/clk.v:9"),
        _claim("controller_doc", "clock runs at 125MHz", "doc/timing.md:44"),
    ]
    base_result = sa.resolve_conflict(claims)
    assert base_result["verdict"] == sa.VERDICT_RESOLVED
    assert base_result["winner"]["source"] == "dut_rtl"

    timing_result = csp.resolve_conflict_for_fact_type(claims, "timing")
    assert timing_result["verdict"] == sa.VERDICT_RESOLVED
    assert timing_result["winner"]["source"] == "controller_doc"
    assert timing_result["authority_order_used"] == "PER_FACT_TYPE_OVERRIDE"
    # evidence for BOTH sides is still carried, exactly as source_authority's
    # own escalation contract requires -- reversing the winner never drops
    # the loser's evidence.
    assert "rtl/clk.v:9" in timing_result["evidence_paths"]["dut_rtl"]
    assert "doc/timing.md:44" in timing_result["evidence_paths"]["controller_doc"]


def test_resolve_conflict_for_fact_type_refuses_fewer_than_two_claims():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        csp.resolve_conflict_for_fact_type([_claim("dut_rtl", "x", "rtl/a.v:1")], "timing")
    assert exc.value.reason == "CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS"


def test_resolve_conflict_for_fact_type_refuses_non_sourceclaim_members():
    with pytest.raises(sa.SourceAuthorityError) as exc:
        csp.resolve_conflict_for_fact_type([{"not": "a claim"}, {"also": "not"}], "timing")
    assert exc.value.reason == "CLAIMS_MUST_BE_SOURCECLAIM"


def test_undecidable_same_authority_still_honest_under_a_declared_override():
    """Two claims from the SAME source (so they sit at the identical
    contextual rank no matter the fact_type) that disagree must still be
    UNDECIDABLE under 'timing' too -- the override reorders TIERS, it never
    invents a tie-break inside one."""
    claims = [
        _claim("controller_doc", "budget is 10ns", "doc/a.md:1"),
        _claim("controller_doc", "budget is 12ns", "doc/b.md:2"),
    ]
    result = csp.resolve_conflict_for_fact_type(claims, "timing")
    assert result["verdict"] == sa.VERDICT_UNDECIDABLE
    assert result["winner"] is None
    assert len(result["tied"]) == 2


# ---------------------------------------------------------------------------
# describe / format
# ---------------------------------------------------------------------------

def test_describe_fact_type_overrides_shape():
    rows = csp.describe_fact_type_overrides()
    assert any(r["fact_type"] == "timing" for r in rows)
    timing_row = next(r for r in rows if r["fact_type"] == "timing")
    assert len(timing_row["order"]) == 9
    assert len(timing_row["order_doc_phrases"]) == 9
    assert timing_row["evidence"].strip()


def test_format_fact_type_overrides_is_real_text():
    text = csp.format_fact_type_overrides()
    assert "timing" in text
    assert "controller doc" in text.lower()


def test_never_mutates_source_authority_authority_order():
    """AUTHORITY_ORDER is a frozen tuple of frozen dataclasses; this asserts
    the object identity survives module import/use, i.e. this module never
    replaces source_authority.py's own order."""
    before = sa.AUTHORITY_ORDER
    csp.contextual_rank("dut_rtl", "timing")
    csp.resolve_conflict_for_fact_type(
        [_claim("dut_rtl", "x", "a:1"), _claim("controller_doc", "y", "b:1")], "timing")
    assert sa.AUTHORITY_ORDER is before


# ---------------------------------------------------------------------------
# design_source_inventory.py's additive integration.
# ---------------------------------------------------------------------------

def test_source_entry_without_fact_type_is_byte_identical_to_before():
    """Backward-compatibility proof: omitting fact_type (every pre-existing
    caller) yields the exact rank/id/doc_phrase/status/reason the module
    produced before the override layer existed, plus only a new
    authority_order_used=None key."""
    entry = dsi.SourceEntry(source_id="s1", type="rtl", authority_hint="dut_rtl")
    row = dsi.evaluate_source(entry)
    auth = row["authority"]
    assert auth["status"] == dsi.AUTHORITY_RESOLVED
    assert auth["rank"] == sa.authority_rank("dut_rtl") == 3
    assert auth["id"] == "dut_rtl"
    assert auth["doc_phrase"] == "DUT RTL"
    assert auth["authority_order_used"] is None
    assert auth["reason"] is None


def test_source_entry_default_fact_type_is_none():
    entry = dsi.SourceEntry(source_id="s1", type="rtl")
    assert entry.fact_type is None


def test_source_entry_with_unknown_fact_type_falls_back_to_base_order():
    entry = dsi.SourceEntry(source_id="s1", type="rtl", authority_hint="dut_rtl",
                             fact_type="functional")
    row = dsi.evaluate_source(entry)
    assert row["authority"]["rank"] == 3
    assert row["authority"]["authority_order_used"] == "BASE_AUTHORITY_ORDER"


def test_source_entry_with_timing_fact_type_reorders_rank():
    rtl_entry = dsi.SourceEntry(source_id="rtl1", type="rtl", authority_hint="dut_rtl",
                                 fact_type="timing")
    doc_entry = dsi.SourceEntry(source_id="doc1", type="doc", authority_hint="controller_doc",
                                 fact_type="timing")
    rtl_row = dsi.evaluate_source(rtl_entry)
    doc_row = dsi.evaluate_source(doc_entry)
    assert rtl_row["authority"]["authority_order_used"] == "PER_FACT_TYPE_OVERRIDE"
    assert doc_row["authority"]["authority_order_used"] == "PER_FACT_TYPE_OVERRIDE"
    # reversed vs base order: controller_doc now outranks dut_rtl
    assert doc_row["authority"]["rank"] < rtl_row["authority"]["rank"]


def test_source_entry_authority_not_applicable_still_carries_new_key():
    """NO_AUTHORITY_HINT_SUPPLIED and UNRESOLVED_AUTHORITY_HINT paths both
    still report authority_order_used explicitly as None, never omitted."""
    entry = dsi.SourceEntry(source_id="s1", type="rtl")  # no authority_hint at all
    row = dsi.evaluate_source(entry)
    assert row["authority"]["status"] == dsi.AUTHORITY_NOT_APPLICABLE
    assert row["authority"]["authority_order_used"] is None

    entry2 = dsi.SourceEntry(source_id="s2", type="rtl", authority_hint="not_a_real_source")
    row2 = dsi.evaluate_source(entry2)
    assert row2["authority"]["status"] == dsi.AUTHORITY_NOT_APPLICABLE
    assert row2["authority"]["authority_order_used"] is None
    assert "UNRESOLVED_AUTHORITY_HINT" in row2["authority"]["reason"]


def test_build_source_registry_batch_still_works_with_mixed_fact_types():
    entries = [
        dsi.SourceEntry(source_id="a", type="rtl", authority_hint="dut_rtl"),
        dsi.SourceEntry(source_id="b", type="doc", authority_hint="controller_doc",
                         fact_type="timing"),
        dsi.SourceEntry(source_id="c", type="rtl", authority_hint="dut_rtl",
                         fact_type="timing"),
    ]
    registry = dsi.build_source_registry(entries)
    assert registry["source_count"] == 3
    ranks = {r["source_id"]: r["authority"]["rank"] for r in registry["sources"]}
    # under the timing override, controller_doc (b) outranks dut_rtl (c)
    assert ranks["b"] < ranks["c"]
