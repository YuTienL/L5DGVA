"""Tests for the asset-processing table's 4 KEY JUDGMENTS as ENFORCED CODE
rather than as prose that an agent is trusted to have read.

Each judgment already had real supporting material before this file existed.
What each one lacked was a caller -- the recurring failure mode this repo has
hit repeatedly (`connectivity.assert_t3_never_auto_accepted()` naming a
"downstream consumer" that did not exist; `connectivity.py` being imported by
nothing but itself). These tests assert the WIRING, not the primitives:

  J1  PHY model decides the bind location, not RTL naming.
      `phy_boundary.assert_bind_location_allowed()` existed and was tested,
      but `bind_mechanism_generator.validate_bind_entries()` -- the only path
      that actually writes a `bind` into a .sv file -- never called it. The
      tier gate cannot substitute: a serial-lane bind target can be a clean
      T1 structural match, so tier and layer are independent properties.

  J3  The reference Makefile/command.txt is the highest authority.
      "A knob an agent believes is missing goes to the question queue" was in
      run_profile.py's docstring, run_profile.schema.json's description, the
      generated justfile's banner and RUN_PROFILE.md -- and in zero lines of
      code. Nothing in dv_harness/uvm_generator/ referenced question_queue at
      all, and nothing checked a profile's params against the real source.

J2 (register-file division of labour) and J4 (VIP source handling) are
covered by `test_asset_processing_artifacts.py`, which owns init_seq.py /
sys_regmap.py / vip_symbol_index.py; this file does not duplicate them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dv_harness import phy_boundary
from dv_harness.uvm_generator import run_profile_to_justfile as rp2j
from dv_harness.uvm_generator.bind_mechanism_generator import (
    BindTopologyError,
    assert_phy_boundary_decided_first,
    emit_bind_sv,
    validate_bind_entries,
)
from dv_harness.uvm_generator.makefile_to_run_profile import extract_run_profile
from dv_harness.uvm_generator.run_profile import (
    RunProfileValidationError,
    assert_params_traceable_to_source,
    assert_source_unchanged,
    save_run_profile,
    sha256_of_file,
    untraceable_params,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_MAKEFILE = (REPO_ROOT / "dv_harness" / "uvm_generator" / "templates"
                      / "sim_scripts" / "Makefile")


# ===========================================================================
# Judgment 1: the PHY model decides the mount LAYER, before any path is chosen
# ===========================================================================

def _mod(name, ports):
    return {"name": name, "ports": [
        {"name": n, "direction": d, "data_type": t} for n, d, t in ports]}


PARALLEL_PAIR = [
    _mod("phy", [("pclk", "input", "logic"), ("pipe_txdata", "input", "logic [31:0]"),
                 ("pipe_rxdata", "output", "logic [31:0]"), ("txp", "output", "logic")]),
    _mod("ctrl", [("pclk", "input", "logic"), ("pipe_txdata", "output", "logic [31:0]"),
                  ("pipe_rxdata", "input", "logic [31:0]")]),
]
SERIAL_PAIR = [
    _mod("aphy", [("refclk", "input", "logic"), ("serial_txp", "output", "logic"),
                  ("serial_rxn", "input", "logic")]),
    _mod("actrl", [("refclk", "input", "logic"), ("serial_txp", "input", "logic"),
                   ("serial_rxn", "output", "logic")]),
]
MIXED_PAIR = [
    _mod("mphy", [("lane_txp", "output", "logic"), ("sym_data", "output", "logic [15:0]")]),
    _mod("mctrl", [("lane_txp", "input", "logic"), ("sym_data", "input", "logic [15:0]")]),
]


@pytest.fixture
def parallel_doc():
    return phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "ctrl")


@pytest.fixture
def serial_doc():
    return phy_boundary.extract_phy_boundary(SERIAL_PAIR, "aphy", "actrl")


@pytest.fixture
def mixed_doc():
    return phy_boundary.extract_phy_boundary(MIXED_PAIR, "mphy", "mctrl")


# A structurally impeccable bind entry: full instance path (Rule 1), a real
# reason (evidence check), and the highest confidence tier there is. Nothing
# about it is wrong EXCEPT the layer it sits at -- which is the entire point.
def _t1_entry(target="chip.core.usb0.u_serdes", ports=("serial_txp", "serial_rxn"), **extra):
    entry = {
        "target_instance": target,
        "ports": list(ports),
        "reason": "serial lane pair declared here per RTL port table",
        "tier": "T1_ALREADY_DECIDED",
    }
    entry.update(extra)
    return entry


def test_a_serial_boundary_bind_is_refused_even_though_its_tier_is_t1(serial_doc):
    """The judgment in one test. This entry passes every other gate in the
    generator: it has evidence, it uses a full instance path, and it is T1 --
    the tier that needs no human confirmation. Only the PHY boundary knows it
    would produce a monitor that decodes nothing."""
    entries = [_t1_entry()]

    # Without the boundary document the tier gate happily accepts it, which
    # is precisely the hole: naming/structure alone cannot see the problem.
    assert validate_bind_entries(entries) == entries

    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="NOT_BINDABLE"):
        validate_bind_entries(entries, phy_boundary_doc=serial_doc)


def test_nothing_is_emitted_when_the_boundary_refuses(serial_doc):
    with pytest.raises(phy_boundary.PhyBoundaryValidationError):
        emit_bind_sv([_t1_entry()], phy_boundary_doc=serial_doc)


def test_a_parallel_boundary_bind_is_emitted(parallel_doc):
    entry = _t1_entry(target="chip.core.usb0.u_ctrl", ports=("pipe_rxdata", "pipe_txdata"))
    text = emit_bind_sv([entry], phy_boundary_doc=parallel_doc)
    assert "bind chip.core.usb0.u_ctrl" in text


def test_the_layer_gate_runs_before_the_tier_gate(serial_doc):
    """Ordering is the rule, so it is asserted directly. An entry that is
    BOTH at a refused layer AND an unconfirmed T3 must report the layer
    problem: fixing the tier (getting a human to confirm the target) would
    leave a silent monitor in place, so surfacing the tier first would send
    the reader to the wrong repair."""
    entry = _t1_entry()
    entry["tier"] = "T3_NAMING_HEURISTIC"  # would raise BindTierError on its own
    with pytest.raises(phy_boundary.PhyBoundaryValidationError):
        validate_bind_entries([entry], phy_boundary_doc=serial_doc)


def test_binding_the_serial_lane_of_a_mixed_boundary_is_refused(mixed_doc):
    """A MIXED boundary's document says bindable: true, so the layer check
    alone passes it. The per-entry declared signals are what catch someone
    binding its serial lanes anyway."""
    assert mixed_doc["bind_decision"]["bindable"] is True
    good = _t1_entry(target="chip.mctrl", ports=("sym_data",),
                     phy_boundary_signals=["sym_data"])
    assert validate_bind_entries([good], phy_boundary_doc=mixed_doc) == [good]

    bad = _t1_entry(target="chip.mctrl", ports=("lane_txp",),
                    phy_boundary_signals=["lane_txp"])
    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="SIGNAL_NOT_SANCTIONED"):
        validate_bind_entries([bad], phy_boundary_doc=mixed_doc)


def test_an_undecidable_boundary_is_refused_rather_than_guessed():
    """Between SERIAL_MAX_WIDTH and PARALLEL_MIN_WIDTH the boundary kind is
    UNDECIDABLE. That must refuse, not fall back to the more permissive of
    the two readings."""
    pair = [
        _mod("uphy", [("nibble", "output", "logic [3:0]")]),
        _mod("uctrl", [("nibble", "input", "logic [3:0]")]),
    ]
    doc = phy_boundary.extract_phy_boundary(pair, "uphy", "uctrl")
    assert doc["bind_decision"]["bindable"] is False
    with pytest.raises(phy_boundary.PhyBoundaryValidationError):
        validate_bind_entries([_t1_entry(ports=("nibble",))], phy_boundary_doc=doc)


def test_absent_boundary_doc_is_permitted_by_default_but_refused_under_require():
    """The disclosed residual, pinned so it cannot drift silently in either
    direction: an IP-level DUT with no PHY sub-block still generates, and the
    strict contract is one flag away."""
    entries = [_t1_entry()]
    assert validate_bind_entries(entries, phy_boundary_doc=None) == entries
    with pytest.raises(BindTopologyError) as exc:
        validate_bind_entries(entries, phy_boundary_doc=None, require_phy_boundary=True)
    assert exc.value.reason == "PHY_BOUNDARY_NOT_DECIDED"


def test_a_not_available_boundary_never_authorises_a_bind():
    """A NOT_AVAILABLE extraction (unknown module, no shared ports) must not
    read as permission. `None` means "no PHY in scope"; NOT_AVAILABLE means
    "there is a PHY question here and it was not answered"."""
    doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "no_such_module")
    assert doc["status"] == "NOT_AVAILABLE"
    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="NOT_EXTRACTED"):
        assert_phy_boundary_decided_first([_t1_entry()], doc)


def test_generate_bind_mechanism_tool_writes_no_file_when_the_layer_refuses(tmp_path):
    """End-to-end through the REAL emission tool, because "no .sv file was
    written" is the property that actually matters and it is a property of
    the tool, not of the generator function."""
    import subprocess
    import sys

    topo = tmp_path / "topology.json"
    phy_json = tmp_path / "phy_boundary.json"
    phy_boundary.save_phy_boundary(
        phy_boundary.extract_phy_boundary(SERIAL_PAIR, "aphy", "actrl"), phy_json)
    topo.write_text(json.dumps({
        "protocol": "usb", "bind_entries": [_t1_entry()],
        "macro_redirects": {}, "top_scope_decls": [],
    }), encoding="utf-8")
    out = tmp_path / "out"

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "generate_bind_mechanism.py"),
         "--topology", str(topo), "--out", str(out), "--phy-boundary", str(phy_json)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))

    assert proc.returncode != 0, proc.stdout
    assert "NOT_BINDABLE" in proc.stderr
    assert not (out / "usb_uvm_bind_inst.sv").exists()


def test_claude_md_states_the_ordering_rule_as_rule_5():
    """The judgment is an instruction to an agent as much as it is a code
    path, so the instruction's presence is a real assertion. Pinned on the
    ordering language specifically, not on the word "PHY" -- the section
    mentioned PHY-adjacent material before and still did not state the rule."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    section = text.split("## Bind-Location Rules")[1].split("\n## ")[0]
    assert "Five hard project rules" in section
    assert re.search(r"5\.\s+\*\*The PHY model decides the mount LAYER first", section)
    assert "assert_phy_boundary_decided_first" in section
    # The failure signature is the load-bearing part: Gate 1 and Gate 2 pass.
    assert "Gate 3" in section and "silent monitor" in section


# ===========================================================================
# Judgment 3: the reference source is the highest authority
# ===========================================================================

@pytest.fixture
def real_profile():
    return extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")


def test_every_param_of_the_real_extractor_traces_to_the_real_makefile(real_profile):
    """The check must be satisfied by the profile the real extractor produces
    from the real template Makefile. A traceability rule that the sanctioned
    extractor itself fails is a rule that gets switched off."""
    source_text = _TEMPLATE_MAKEFILE.read_text(encoding="utf-8")
    assert untraceable_params(real_profile, source_text) == []
    assert_params_traceable_to_source(real_profile, source_text)


def test_a_hand_added_knob_is_refused(real_profile):
    """The actual attack this closes: an agent adds the knob it wishes
    existed to run_profile.json and regenerates the justfile around it. The
    generated justfile's own 'DO NOT hand-edit' banner never applied to the
    profile, which is the file worth editing."""
    real_profile["runtime_params"].append(
        {"name": "SKIP_SCOREBOARD_CHECKS", "type": "bool01", "default": "0"})
    source_text = _TEMPLATE_MAKEFILE.read_text(encoding="utf-8")
    assert untraceable_params(real_profile, source_text) == ["SKIP_SCOREBOARD_CHECKS"]
    with pytest.raises(RunProfileValidationError, match="PARAM_NOT_TRACEABLE_TO_SOURCE") as exc:
        assert_params_traceable_to_source(real_profile, source_text)
    # The refusal must name the route, or it just teaches people to delete
    # the check.
    assert "question-queue item" in str(exc.value)


def test_traceability_matches_whole_tokens_only(real_profile):
    """A substring match would accept an invented knob whose name happens to
    live inside a real one -- the false negative that makes the check
    worthless. Asserted against a param the real Makefile really does define,
    so this cannot pass by the source simply not containing the prefix."""
    source_text = _TEMPLATE_MAKEFILE.read_text(encoding="utf-8")
    real_name = real_profile["runtime_params"][0]["name"]
    real_profile["runtime_params"].append(
        {"name": real_name + "_OVERRIDE", "type": "string"})
    assert untraceable_params(real_profile, source_text) == [real_name + "_OVERRIDE"]


def test_a_stale_profile_is_refused(tmp_path, real_profile):
    makefile = tmp_path / "Makefile"
    makefile.write_text(_TEMPLATE_MAKEFILE.read_text(encoding="utf-8"), encoding="utf-8")
    real_profile["source"]["content_sha256"] = sha256_of_file(makefile)
    assert_source_unchanged(real_profile, makefile)  # matches: no raise

    makefile.write_text(makefile.read_text(encoding="utf-8") + "\nNEW_KNOB ?= 1\n",
                        encoding="utf-8")
    with pytest.raises(RunProfileValidationError, match="SOURCE_CHANGED_SINCE_EXTRACTION"):
        assert_source_unchanged(real_profile, makefile)


def test_an_unrecorded_hash_is_not_reported_as_a_match(tmp_path, real_profile):
    """Absence of a recorded hash is not evidence of a match -- but neither
    may it invent one. It stays silent, which is why param traceability is a
    separate, independent check rather than something gated behind the hash."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("wholly unrelated content\n", encoding="utf-8")
    real_profile["source"].pop("content_sha256", None)
    assert assert_source_unchanged(real_profile, makefile) is None


def test_generate_and_write_refuses_a_profile_with_an_invented_knob(tmp_path, real_profile):
    """Wiring, not just the primitive: generation is where the invented knob
    would become an execution surface, so that is where it must fail."""
    (tmp_path / "Makefile").write_text(_TEMPLATE_MAKEFILE.read_text(encoding="utf-8"),
                                       encoding="utf-8")
    real_profile["source"]["path"] = "Makefile"
    real_profile["source"].pop("content_sha256", None)
    real_profile["runtime_params"].append(
        {"name": "SKIP_SCOREBOARD_CHECKS", "type": "bool01", "default": "0"})
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(real_profile, profile_path)

    with pytest.raises(RunProfileValidationError, match="PARAM_NOT_TRACEABLE_TO_SOURCE"):
        rp2j.generate_and_write(profile_path, tmp_path / "justfile")
    assert not (tmp_path / "justfile").exists()


def test_verification_reports_not_available_rather_than_guessing(tmp_path, real_profile):
    """A profile inspected away from its environment is the common case. It
    must report NOT_AVAILABLE, never a bare pass that reads as VERIFIED."""
    real_profile["source"]["path"] = "Makefile"  # not present in tmp_path
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(real_profile, profile_path)
    result = rp2j.verify_source_authority(real_profile, profile_path)
    assert result["status"] == "NOT_AVAILABLE"
    # ...and generation still proceeds, so the check is not a false-positive
    # source that gets routed around.
    rp2j.generate_and_write(profile_path, tmp_path / "justfile")
    assert (tmp_path / "justfile").is_file()


def test_verify_source_cli_exit_codes(tmp_path, real_profile):
    (tmp_path / "Makefile").write_text(_TEMPLATE_MAKEFILE.read_text(encoding="utf-8"),
                                       encoding="utf-8")
    real_profile["source"]["path"] = "Makefile"
    real_profile["source"].pop("content_sha256", None)
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(real_profile, profile_path)
    assert rp2j.main(["verify-source", str(profile_path)]) == 0

    real_profile["runtime_params"].append({"name": "INVENTED_KNOB", "type": "string"})
    save_run_profile(real_profile, profile_path)
    assert rp2j.main(["verify-source", str(profile_path)]) == 1


# --- the question-queue route, as a real persisted record -------------------

def test_assert_option_modeled_accepts_a_real_param_and_refuses_an_invented_one(real_profile):
    real_name = real_profile["runtime_params"][0]["name"]
    assert rp2j.assert_option_modeled(real_profile, "sim", real_name)["name"] == real_name
    with pytest.raises(rp2j.UnmodeledOptionError, match="UNMODELED_OPTION"):
        rp2j.assert_option_modeled(real_profile, "sim", "SKIP_SCOREBOARD_CHECKS")


def test_a_missing_option_becomes_a_real_persisted_question(tmp_path, real_profile):
    """The prose said "question-queue item" for as long as this generator has
    existed. This asserts a record actually lands in the SAME queue
    connectivity's T4 binds use -- schema-valid, owner-routed, id-derived."""
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    rec = rp2j.build_missing_option_question_queue_entry(
        store, profile=real_profile, target="sim", option="SKIP_SCOREBOARD_CHECKS",
        options=["add a SKIP_SCOREBOARD_CHECKS make variable to the Makefile",
                 "express it through the existing UVM_VERBOSITY/test selection"],
        recommendation="express it through the existing UVM_VERBOSITY/test selection",
        assumption_if_unanswered="no knob is added; scoreboard checks stay on",
    )
    question_queue.validate_question(rec)
    assert rec["owner"] == question_queue.route_owner("env")
    assert rec["context_path"] == "run_profile/targets/sim/params/SKIP_SCOREBOARD_CHECKS"
    # affects_pass_fail_verdict -> CANNOT_ASSUME, the same escalation an
    # undecidable bind gets. A silently-added execution knob can produce a
    # PASS that verified something other than what was asked for.
    assert rec["tier"] == question_queue.TIER3_CANNOT_ASSUME


def test_the_same_missing_option_asked_twice_mints_the_same_id(tmp_path, real_profile):
    """The queue's repeat-question-rate=0 property. Regeneration must not
    manufacture a new question each time."""
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    kwargs = dict(
        profile=real_profile, target="sim", option="SKIP_SCOREBOARD_CHECKS",
        options=["add it to the Makefile", "use existing test selection"],
        recommendation="use existing test selection",
        assumption_if_unanswered="no knob is added",
    )
    first = rp2j.build_missing_option_question_queue_entry(store, **kwargs)
    second = rp2j.build_missing_option_question_queue_entry(store, **kwargs)
    assert first["id"] == second["id"]


def test_an_already_modeled_option_is_not_askable(tmp_path, real_profile):
    """Asking the queue about a knob that already exists wastes the one
    resource the queue is rationing: a human's attention."""
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    real_name = real_profile["runtime_params"][0]["name"]
    with pytest.raises(RunProfileValidationError, match="OPTION_ALREADY_MODELED"):
        rp2j.build_missing_option_question_queue_entry(
            store, profile=real_profile, target="sim", option=real_name,
            options=["a", "b"], recommendation="a", assumption_if_unanswered="x")


def test_an_open_ended_question_is_refused(tmp_path, real_profile):
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    with pytest.raises(RunProfileValidationError, match="OPTIONS_MUST_BE_PRE_RESEARCHED"):
        rp2j.build_missing_option_question_queue_entry(
            store, profile=real_profile, target="sim", option="SKIP_SCOREBOARD_CHECKS",
            options=["just one"], recommendation="just one", assumption_if_unanswered="x")


def test_a_recommendation_outside_the_options_is_refused(tmp_path, real_profile):
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    with pytest.raises(RunProfileValidationError, match="RECOMMENDATION_MUST_BE_ONE_OF_OPTIONS"):
        rp2j.build_missing_option_question_queue_entry(
            store, profile=real_profile, target="sim", option="SKIP_SCOREBOARD_CHECKS",
            options=["a", "b"], recommendation="c", assumption_if_unanswered="x")


# --- the human escape hatch -------------------------------------------------

def test_human_raw_override_requires_an_explicit_acknowledgment(real_profile):
    text = rp2j.generate_justfile(real_profile)
    assert "human_raw_override ack target *args:" in text
    assert rp2j.HUMAN_OVERRIDE_ACK_TOKEN in text
    # The refusal message must name the sanctioned alternative.
    assert "question queue" in text


@pytest.mark.skipif(__import__("shutil").which("just") is None,
                    reason="the `just` binary is not installed in this environment")
def test_human_raw_override_really_refuses_a_wrong_token(tmp_path, real_profile):
    """Run the real `just` binary against the real generated recipe -- the
    guard is a shell condition, and a string-matched shell condition is not
    evidence that it fires."""
    import subprocess

    (tmp_path / "Makefile").write_text("noop:\n\t@echo ran\n", encoding="utf-8")
    real_profile["source"]["path"] = "Makefile"
    real_profile["source"].pop("content_sha256", None)
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(real_profile, profile_path)
    rp2j.generate_and_write(profile_path, tmp_path / "justfile", verify_source=False)

    refused = subprocess.run(["just", "human_raw_override", "whatever", "noop"],
                             cwd=tmp_path, capture_output=True, text=True)
    assert refused.returncode != 0
    assert rp2j.HUMAN_OVERRIDE_ACK_TOKEN in refused.stderr
    assert "make" not in refused.stdout  # the guard ran BEFORE make, not after

    # The token must also let a human THROUGH -- a guard that refuses
    # everything is not a guard, it is a removed feature. `make` is not
    # installed in this environment (confirmed: the recipe reports
    # "make: command not found"), so the passing evidence is that execution
    # reached the make line at all, with the guard's own message absent.
    allowed = subprocess.run(
        ["just", "human_raw_override", rp2j.HUMAN_OVERRIDE_ACK_TOKEN, "noop"],
        cwd=tmp_path, capture_output=True, text=True)
    assert rp2j.HUMAN_OVERRIDE_ACK_TOKEN not in allowed.stderr
    assert allowed.returncode == 0 or "make" in allowed.stderr, allowed.stderr
