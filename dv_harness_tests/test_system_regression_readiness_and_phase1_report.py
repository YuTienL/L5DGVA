"""SYS-33..SYS-39: the system regression PLAN, the Knowledge Center composition
record, subsystem version pinning, the subsystem-git change-impact producer, the
system readiness derivation, SYS-38's twenty-two-item Phase-1 report and SYS-39's
stop condition.

FIXTURES. Every subsystem, address map, clock/reset fact, command.txt and
release_sha below is INVENTED for this file and describes no real DUT -- this
harness repo legitimately has no multi-subsystem project of its own. The
per-subsystem SYS-6 blocks, the SYS-15 registry entries and the command.txt
bodies are IMPORTED from `test_system_topology_analysis` and
`test_subsystem_architecture_and_command_contract` rather than retyped, for the
reason those suites give: three fixture shapes describing three different
imaginary DUTs is how a suite stops meaning anything, and a hand-typed copy
drifts silently from the shape the real builders produce.

WHAT THE HARD CASES ARE. A selection/dedup/conflict mechanism proved only on a
happy path is not proved at all, so this suite deliberately carries:

  * a subsystem that is registered and PASS-evidenced beside one that is
    neither, so SYS-33's "known-good" really excludes something and records why;
  * a real SYS-22 blocking collision and a real SYS-23 deduplication candidate,
    so the command selection is a selection rather than a copy of the IR;
  * an unresolved DRIVER_CONFLICT registry entry (two subsystems claiming one
    active clock/reset agent), which must make SYS-37 BLOCKED and must NOT be
    reported as READY -- SYS-37's own closing sentence;
  * a REAL git repository per subsystem, with a real commit moving files after
    the pinned release_sha, so SYS-36's diff is a real `git diff` and not a
    fixture dict; beside a subsystem with NO registered release_sha, which must
    come back undecidable and must force the full plan to be retained;
  * the REAL `system_level_change_impact_gate.py` subprocess run against the
    produced payload -- and against a deliberately broken one, so the gate's
    PASS is evidence rather than a subprocess that would pass anything.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import knowledge_center as kc
from dv_harness import subsystem_discovery as sd
from dv_harness import system_command_plan as scp
from dv_harness import system_phase1_report as spr
from dv_harness import system_readiness as sr
from dv_harness import system_regression_plan as srp
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
from dv_harness import system_scheduling_plan as ssp
from dv_harness import system_topology_analysis as sta
from dv_harness_tests.test_subsystem_discovery import (  # reused, never retyped
    _registry_entry,
    _write_candidate_sources,
    _write_env_tree,
    _write_registry,
)
from dv_harness_tests.test_system_topology_analysis import (  # reused, never retyped
    _analysis,
    _clock_reset_agent_entry,
    _plans,
    _registry,
)

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "system_level_change_impact_gate.py"


# ---------------------------------------------------------------------------
# Fixture assembly
# ---------------------------------------------------------------------------

def _selection_row(subsystem, *, readiness=sd.READY, pass_evidence=sd.PRESENT,
                   regression_evidence=sd.PRESENT, build=sd.PRESENT,
                   tests=sd.PRESENT, environment_path="", existence=sd.EXISTS_READY,
                   registered=True, kc_status="KC_NOT_CHECKED"):
    """One `require_explicit_selection()['selected_rows']` row, carrying the
    SYS-4 factor blocks SYS-33/SYS-37 read. Only the factors those two consume
    are varied; the rest are filled PRESENT so a test that moves one factor is
    moving exactly one thing."""
    factors = {factor: {"status": sd.PRESENT, "evidence": "synthetic fixture",
                        "matched": []}
               for factor in sd.READINESS_FACTORS}
    factors["pass_evidence"] = {"status": pass_evidence,
                                "evidence": f"synthetic pass_evidence={pass_evidence}",
                                "matched": ["logs/sim.log"]}
    factors["regression_evidence"] = {"status": regression_evidence,
                                      "evidence": "synthetic regression evidence",
                                      "matched": ["regression.list"]}
    factors["build"] = {"status": build, "evidence": "synthetic build", "matched": []}
    factors["tests"] = {"status": tests, "evidence": "synthetic tests",
                        "matched": ["test/foo_test.sv"]}
    return {
        "subsystem": subsystem,
        "environment_path": environment_path,
        "knowledge_center_status": kc_status,
        "readiness": readiness,
        "protocol": subsystem.split("_")[0],
        "version_sha": "",
        "existence_class": existence,
        "existence_reasons": [],
        "next_action": "-",
        "registered": registered,
        "readiness_factors": factors,
        "readiness_detail": {"readiness": readiness, "evidence": "synthetic"},
        "knowledge_center": {"found": False},
    }


def _selection(rows, *, admissible=True, refusal=""):
    return {
        "discovery": {"candidates": rows, "conflicts": []},
        "environment_mode_decision": {"mode": "SYSTEM_LEVEL_MODE"},
        "selected_subsystems": [r["subsystem"] for r in rows],
        "selected_rows": rows,
        "not_ready": [r for r in rows if r["existence_class"] != sd.EXISTS_READY],
        "blocking_conflicts": [],
        "selection_admissible": admissible,
        "refusal_reason": refusal,
    }


def _registry_entries(*, usb_sha="usb56789", pcie_sha="pcie1234", eth_sha="eth00000"):
    entries = [_registry_entry("PCIE_SS", sha=pcie_sha),
               _registry_entry("USB_SS", sha=usb_sha)]
    if eth_sha is not None:
        entries.append(_registry_entry("ETH_SS", sha=eth_sha))
    return entries


def _full_stack(tmp_path, *, registry_entries=None, driver_conflict=False):
    """One real SYS-5..30 stack over the imported synthetic fixtures, plus the
    SYS-33..37 layer this suite is about. Everything below SYS-33 is produced
    by the REAL builders -- a regression plan over a hand-typed IR would prove
    nothing about the selection it performs."""
    analysis = _analysis()
    integration_plan, command_plan, scheduling_plan, _sel = _plans(tmp_path)
    if driver_conflict:
        entry = _clock_reset_agent_entry()
        integration_plan = {
            "system_resource_registry": {
                **_registry([entry]),
                "summary": {
                    "entry_count": 1, "member_resource_count": 2,
                    "collapsed_resource_count": 1, "shared_entry_count": 1,
                    "entries_by_reuse_decision": {d: (1 if d == srr.BLOCKED else 0)
                                                  for d in srr.SYS17_DECISIONS},
                    "entries_by_conflict_status": {
                        c: (1 if c == srr.CONFLICT_DRIVER else 0)
                        for c in srr.CONFLICT_STATUSES},
                },
            },
            "vip_agent_deduplication_matrix": {
                "rows": [], "summary": {"row_count": 0, "blocked": 1,
                                        "by_decision": {}}},
        }
    topology = sta.build_system_topology_analysis(
        analysis, integration_plan, command_plan, scheduling_plan)
    rows = [_selection_row(sid) for sid in ("PCIE_SS", "USB_SS", "ETH_SS")]
    selection = _selection(rows)
    entries = (_registry_entries() if registry_entries is None else registry_entries)
    plan = srp.build_system_regression_plan(
        selection, integration_plan, command_plan, scheduling_plan, topology,
        registry_entries=entries)
    return {"analysis": analysis, "selection": selection,
            "integration_plan": integration_plan, "command_plan": command_plan,
            "scheduling_plan": scheduling_plan, "topology_analysis": topology,
            "registry_entries": entries, "regression_plan": plan}


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def _git_subsystem_repo(base: Path, *, second_commit=True) -> str:
    """A REAL git repository for one subsystem environment. Returns the FIRST
    commit's sha, which is what the registry pins as `release_sha` -- so
    SYS-36's diff is a real `git diff <release_sha>..HEAD` over real commits."""
    _write_env_tree(base)
    _git(base, "init", "-q")
    _git(base, "config", "user.email", "fixture@example.invalid")
    _git(base, "config", "user.name", "fixture")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "release")
    first = _git(base, "rev-parse", "HEAD").stdout.strip()
    if second_commit:
        (base / "rtl" / "dut_core.sv").write_text("// synthetic RTL, changed\n",
                                                  encoding="utf-8")
        _git(base, "add", "-A")
        _git(base, "commit", "-q", "-m", "post-release RTL change")
    return first


def _entry_ids(plan, category):
    return [e["entry_id"] for e in plan["entries"] if e["category"] == category]


# ============================================================================
# Vocabulary held to the requirements' own sentences
# ============================================================================

def test_sys33_categories_match_the_requirements_own_sentence_one_to_one():
    """SYS-33: "Build from known-good subsystem tests, selected command
    sequences, cross-subsystem scenarios, shared-resource contention,
    boot/config, interrupt, DMA, stress/concurrency." Eight sources, in that
    order."""
    assert srp.SYS33_CATEGORIES == (
        "KNOWN_GOOD_SUBSYSTEM_TESTS", "SELECTED_COMMAND_SEQUENCES",
        "CROSS_SUBSYSTEM_SCENARIOS", "SHARED_RESOURCE_CONTENTION",
        "BOOT_CONFIG", "INTERRUPT", "DMA", "STRESS_CONCURRENCY")


def test_sys37_inputs_match_the_requirements_own_sentence_and_there_are_ten():
    """SYS-37 names TEN inputs, not nine: "subsystem readiness, shared-resource
    conflicts, command compatibility, scoreboard compatibility, address map,
    clock/reset, VIP dedup resolution, build integration, scenario
    availability, regression evidence"."""
    assert sr.SYS37_INPUTS == (
        "subsystem_readiness", "shared_resource_conflicts", "command_compatibility",
        "scoreboard_compatibility", "address_map", "clock_reset",
        "vip_dedup_resolution", "build_integration", "scenario_availability",
        "regression_evidence")
    assert len(sr.SYS37_INPUTS) == 10


def test_sys37_reuses_sys4s_four_readiness_words_rather_than_minting_new_ones():
    """READY/PARTIAL/BLOCKED/UNKNOWN mean the same thing one level up. A second
    four-string vocabulary for the same question is the duplication this
    project has repeatedly caught as a real defect."""
    assert sr.SYSTEM_READINESS_CLASSES is sd.READINESS_CLASSES
    assert (sr.READY, sr.PARTIAL, sr.BLOCKED, sr.UNKNOWN) == (
        sd.READY, sd.PARTIAL, sd.BLOCKED, sd.UNKNOWN)


def test_sys38_sections_are_the_twenty_two_items_in_the_requirements_order():
    assert [n for n, _ in spr.SYS38_SECTIONS] == list(range(1, 23))
    assert [t for _, t in spr.SYS38_SECTIONS] == [
        "USER SELECTED SUBSYSTEMS", "SUBSYSTEM EXISTENCE CHECK",
        "KNOWLEDGE CENTER STATUS", "SUBSYSTEM READINESS MATRIX",
        "PER-SUBSYSTEM ARCHITECTURE ANALYSIS", "PER-SUBSYSTEM command.txt ANALYSIS",
        "SUBSYSTEM COMMAND CONTRACTS", "VIP / AGENT RESOURCE INVENTORY",
        "DUPLICATE RESOURCE ANALYSIS", "ACTIVE DRIVER CONFLICTS",
        "SHARED RESOURCE PROPOSAL", "SYSTEM_RESOURCE_REGISTRY",
        "SUBSYSTEM INTEGRATION MATRIX", "VIP / AGENT DEDUPLICATION MATRIX",
        "ADDRESS MAP INTEGRATION", "CLOCK / RESET INTEGRATION",
        "SCOREBOARD INTEGRATION PLAN", "SYSTEM command.txt SYNTHESIS PLAN",
        "SYSTEM ARCHITECTURE", "OPEN QUESTIONS", "SYSTEM READINESS",
        "USER REVIEW GATE"]


def test_sys39_stop_lines_are_the_requirements_ten_lines_verbatim():
    assert spr.SYS39_STOP_LINES == (
        "SYSTEM-LEVEL INTEGRATION DISCOVERY COMPLETE",
        "SELECTED SUBSYSTEM EXISTENCE CHECK COMPLETE",
        "KNOWLEDGE CENTER CHECK COMPLETE",
        "SUBSYSTEM ARCHITECTURE ANALYSIS COMPLETE",
        "SUBSYSTEM command.txt ANALYSIS COMPLETE",
        "VIP / AGENT DEDUPLICATION COMPLETE",
        "SYSTEM command.txt PLAN COMPLETE",
        "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED",
        "AWAITING USER APPROVAL",
        "STOP.")
    spr.assert_stop_condition_exact(spr.render_stop_condition())


def test_a_paraphrase_of_the_stop_condition_is_refused():
    """SYS-39 says "report exactly". A near-miss must fail, or the check has no
    detection power at all."""
    paraphrase = spr.render_stop_condition().replace("STOP.", "STOP")
    with pytest.raises(spr.SystemPhase1ReportError) as excinfo:
        spr.assert_stop_condition_exact(paraphrase)
    assert excinfo.value.reason == "SYS39_STOP_CONDITION_NOT_EXACT"


def test_no_second_git_diff_or_address_parser_is_defined_in_the_new_modules():
    """REUSE-FIRST, checked rather than asserted in a comment. `change_impact`
    owns the one `git diff` in this repo and `amba_fabric_generator.parse_addr`
    the one address parser; a second copy in these modules is exactly the
    defect this project has caught before."""
    for module in (srp, sr, spr):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not re.search(r"subprocess\.(run|Popen|check_output)", source), module
        assert '"diff"' not in source and "'diff'" not in source, module
        assert not re.search(r"int\(\s*[^)]*,\s*(0|16)\s*\)", source), module


# ============================================================================
# SYS-33 -- SYSTEM REGRESSION plan
# ============================================================================

def test_sys33_every_mandated_category_is_present_even_when_empty(tmp_path):
    """A category silently missing from a plan is indistinguishable from a
    category with nothing in it, and only one of those is a finding."""
    plan = _full_stack(tmp_path)["regression_plan"]
    assert list(plan["by_category"]) == list(srp.SYS33_CATEGORIES)
    for category in srp.SYS33_CATEGORIES:
        block = plan["by_category"][category]
        if block["count"] == 0:
            assert block["empty_reason"], category
        else:
            assert not block["empty_reason"], category


def test_sys33_every_planned_entry_cites_a_real_source_row(tmp_path):
    plan = _full_stack(tmp_path)["regression_plan"]
    assert plan["entries"], "the fixture stack must derive at least one entry"
    for entry in plan["entries"]:
        assert entry["basis"].strip(), entry
        assert entry["source_artifact"] and entry["source_id"], entry
        assert entry["execution_status"] == srp.PLANNED_NOT_EXECUTED
        assert entry["selection_class"] in {
            "TARGETED", "DEPENDENCY", "SAFETY", "MANDATORY_SIGNOFF"}


def test_sys33_known_good_excludes_a_subsystem_with_no_qualified_pass_evidence(tmp_path):
    """The hard case for "known-good": one subsystem registered and
    PASS-evidenced, one registered but with ABSENT pass evidence, one not
    registered at all. Two must be excluded, each naming its own failing
    half."""
    stack = _full_stack(tmp_path)
    rows = [
        _selection_row("PCIE_SS"),
        _selection_row("USB_SS", pass_evidence=sd.ABSENT),
        _selection_row("ETH_SS", registered=False),
    ]
    selection = _selection(rows)
    plan = srp.build_system_regression_plan(
        selection, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"],
        registry_entries=[_registry_entry("PCIE_SS", sha="pcie1234"),
                          _registry_entry("USB_SS", sha="usb56789")])

    known_good = [e for e in plan["entries"]
                  if e["category"] == srp.CAT_KNOWN_GOOD_SUBSYSTEM_TESTS]
    assert [e["participating_subsystems"] for e in known_good] == [["PCIE_SS"]]

    excluded = {row["source_id"]: row for row in plan["excluded"]
                if row["category"] == srp.CAT_KNOWN_GOOD_SUBSYSTEM_TESTS}
    assert set(excluded) == {"USB_SS", "ETH_SS"}
    assert excluded["USB_SS"]["reason"] == srp.EXCL_NOT_KNOWN_GOOD
    assert "pass_evidence" in excluded["USB_SS"]["detail"]
    # ETH_SS has no registry entry at all, so its qualification_state is None.
    assert "qualification_state" in excluded["ETH_SS"]["detail"]


def test_sys33_command_selection_excludes_dedup_candidates_and_blocking_collisions(tmp_path):
    """"Selected command sequences", not "all command sequences". The
    exclusions are read off SYS-22's and SYS-23's own verdicts, so this test
    asserts against those layers rather than against a hardcoded list."""
    stack = _full_stack(tmp_path)
    plan = stack["regression_plan"]
    ir_ids = {e["system_command_id"]
              for e in stack["command_plan"]["system_command_ir"]["entries"]}
    planned = {e["source_id"] for e in plan["entries"]
               if e["category"] == srp.CAT_SELECTED_COMMAND_SEQUENCES}
    excluded = {row["source_id"] for row in plan["excluded"]
                if row["category"] == srp.CAT_SELECTED_COMMAND_SEQUENCES}

    assert planned | excluded == ir_ids, "every IR entry is planned or excluded"
    assert not planned & excluded
    assert excluded, "the fixture stack must exercise at least one real exclusion"
    for row in plan["excluded"]:
        if row["category"] != srp.CAT_SELECTED_COMMAND_SEQUENCES:
            continue
        assert row["reason"] in (srp.EXCL_DEDUP_CANDIDATE, srp.EXCL_BLOCKING_COLLISION)
        assert row["detail"].strip()

    blocked = {cid for c in stack["command_plan"]["command_collisions"]["collisions"]
               if c.get("blocks_integration") for cid in c["commands"]}
    assert not (planned & blocked), "a blocking collision's command is never planned"


def test_sys33_concatenation_check_reports_the_universe_it_selected_from(tmp_path):
    plan = _full_stack(tmp_path)["regression_plan"]
    check = plan["concatenation_check"]
    assert check["verdict"] in (srp.SELECTION_EVIDENCED, srp.FULL_UNIVERSE_SELECTED,
                                srp.EMPTY_UNIVERSE)
    assert check["universe"] == sum(check["universe_sources"].values())
    assert check["selected"] <= check["universe"]
    # The fixture stack really does exclude something, so this is a selection.
    assert check["verdict"] == srp.SELECTION_EVIDENCED
    assert check["excluded"] > 0


def test_sys33_blind_concatenation_is_refused_when_nothing_says_why(tmp_path):
    """SYS-33's only prohibition, as a check with real detection power: a plan
    that took its whole universe AND cites no basis is refused; taking the whole
    universe WITH a basis on every entry is not."""
    plan = _full_stack(tmp_path)["regression_plan"]
    blind = json.loads(json.dumps(plan))
    blind["concatenation_check"]["verdict"] = srp.FULL_UNIVERSE_SELECTED
    for entry in blind["entries"]:
        entry["basis"] = ""
    with pytest.raises(srp.SystemRegressionPlanError) as excinfo:
        srp.assert_not_blind_concatenation(blind)
    assert excinfo.value.reason == "BLIND_CONCATENATION_DETECTED"
    assert excinfo.value.detail["entries_without_basis"]

    evidenced = json.loads(json.dumps(plan))
    evidenced["concatenation_check"]["verdict"] = srp.FULL_UNIVERSE_SELECTED
    srp.assert_not_blind_concatenation(evidenced)  # every entry still cites a basis


def test_sys33_plan_refuses_to_claim_anything_was_executed(tmp_path):
    plan = _full_stack(tmp_path)["regression_plan"]
    assert plan["summary"]["tests_executed"] == 0
    assert plan["summary"]["jobs_submitted"] == 0
    srp.assert_nothing_executed(plan)

    ran = json.loads(json.dumps(plan))
    ran["entries"][0]["execution_status"] = "PASS"
    with pytest.raises(srp.SystemRegressionPlanError) as excinfo:
        srp.assert_nothing_executed(ran)
    assert excinfo.value.reason == "REGRESSION_ENTRY_EXECUTED"

    submitted = json.loads(json.dumps(plan))
    submitted["jobs_submitted"] = ["lsf-12345"]
    with pytest.raises(srp.SystemRegressionPlanError) as excinfo:
        srp.assert_nothing_executed(submitted)
    assert excinfo.value.reason == "REGRESSION_EXECUTION_ATTEMPTED"


def test_sys33_stress_concurrency_only_uses_pairs_sys25_called_parallel_safe(tmp_path):
    """Every other SYS-25 relationship says the two commands must be ordered,
    serialized or are undecided; a stress test built on an undecided pair would
    be measuring the harness's own uncertainty."""
    stack = _full_stack(tmp_path)
    safe = {(p["command_a"], p["command_b"])
            for p in stack["scheduling_plan"]["parallelism_model"]["pairs"]
            if p["relationship"] == ssp.REL_PARALLEL_SAFE}
    planned = {tuple(e["source_id"].split("|")) for e in stack["regression_plan"]["entries"]
               if e["category"] == srp.CAT_STRESS_CONCURRENCY}
    assert planned == safe


# ============================================================================
# SYS-35 -- SUBSYSTEM VERSION PINNING
# ============================================================================

def test_sys35_pin_is_idempotent_for_an_unchanged_set_and_new_for_a_moved_sha():
    rows = [_selection_row("PCIE_SS"), _selection_row("USB_SS")]
    selection = _selection(rows)
    first = sr.build_composition_version_pin(selection, _registry_entries(eth_sha=None))
    again = sr.build_composition_version_pin(selection, _registry_entries(eth_sha=None))
    assert first["composition_id"] == again["composition_id"]

    moved = sr.build_composition_version_pin(
        selection, _registry_entries(usb_sha="usb99999", eth_sha=None))
    assert moved["composition_id"] != first["composition_id"]
    assert moved["subsystem_versions"]["USB_SS"] == "usb99999"


def test_sys35_an_unpinned_subsystem_is_recorded_not_omitted():
    """A snapshot silently missing a subsystem would restore a DIFFERENT
    composition than the one it claims."""
    rows = [_selection_row("PCIE_SS"), _selection_row("USB_SS")]
    entries = [_registry_entry("PCIE_SS", sha="pcie1234"),
               dict(_registry_entry("USB_SS"), release_sha="")]
    pin = sr.build_composition_version_pin(_selection(rows), entries)

    assert pin["subsystems"] == ["PCIE_SS", "USB_SS"]
    assert pin["subsystem_versions"]["USB_SS"] == sr.UNPINNED
    assert pin["unpinned_subsystems"] == ["USB_SS"]
    assert pin["restorable"] is False
    assert "cannot restore" in pin["restore_note"]


def test_sys35_pin_file_is_append_only_unlike_the_registry_it_sits_beside(tmp_path):
    """The whole difference from `_persist_subsystem_registry_entry()`, which
    replaces a subsystem's row by NAME. A file whose rows are overwritten in
    place cannot be the record of what composition X was built from."""
    rows = [_selection_row("PCIE_SS"), _selection_row("USB_SS")]
    selection = _selection(rows)
    first = sr.build_composition_version_pin(selection, _registry_entries(eth_sha=None))
    moved = sr.build_composition_version_pin(
        selection, _registry_entries(usb_sha="usb99999", eth_sha=None))

    sr.write_composition_pin(tmp_path, first)
    sr.write_composition_pin(tmp_path, moved)
    stored = sr.read_composition_pins(tmp_path)["compositions"]
    assert {c["composition_id"] for c in stored} == {first["composition_id"],
                                                     moved["composition_id"]}

    # Re-writing the SAME composition id replaces that one entry only.
    sr.write_composition_pin(tmp_path, first)
    stored = sr.read_composition_pins(tmp_path)["compositions"]
    assert len(stored) == 2

    # It never touches the real registration authority.
    assert not (tmp_path / ".dv-harness" / "soc-composer"
                / "subsystem_environment_registry.json").exists()


def test_sys35_missing_pin_file_degrades_to_empty_not_to_a_guess(tmp_path):
    assert sr.read_composition_pins(tmp_path)["compositions"] == []
    sr.pin_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    sr.pin_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert sr.read_composition_pins(tmp_path)["compositions"] == []


# ============================================================================
# SYS-36 -- CHANGE IMPACT (real git)
# ============================================================================

def test_sys36_diffs_each_subsystem_against_its_own_registered_release_sha(tmp_path):
    """A REAL `git diff` per subsystem tree, against that subsystem's OWN
    release sha -- not one repo-wide base, which is the thing
    `change_impact.compute_change_impact()` structurally cannot do."""
    pcie = tmp_path / "generated" / "pcie_uvm_env"
    usb = tmp_path / "generated" / "usb_uvm_env"
    pcie_sha = _git_subsystem_repo(pcie, second_commit=True)
    usb_sha = _git_subsystem_repo(usb, second_commit=False)

    stack = _full_stack(tmp_path)
    rows = [_selection_row("PCIE_SS", environment_path=str(pcie)),
            _selection_row("USB_SS", environment_path=str(usb))]
    entries = [_registry_entry("PCIE_SS", sha=pcie_sha),
               _registry_entry("USB_SS", sha=usb_sha)]
    impact = srp.compute_subsystem_change_impact(
        tmp_path, _selection(rows), stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)

    by_id = {d["subsystem"]: d for d in impact["subsystem_diffs"]}
    assert by_id["PCIE_SS"]["status"] == srp.DIFF_REAL
    assert by_id["PCIE_SS"]["changed"] is True
    assert "rtl/dut_core.sv" in by_id["PCIE_SS"]["files"]
    assert by_id["PCIE_SS"]["risk_counts"]  # classify_risk() really ran
    assert by_id["USB_SS"]["status"] == srp.DIFF_REAL
    assert by_id["USB_SS"]["changed"] is False
    assert impact["changed_subsystems"] == ["PCIE_SS"]
    assert impact["undecidable_subsystems"] == []
    assert impact["selective_regression"]["verdict"] == srp.SELECTIVE_SUPPORTED


def test_sys36_a_subsystem_with_no_release_sha_is_undecidable_not_unchanged(tmp_path):
    """The false-clean this whole layer exists to prevent: "we could not diff"
    must never read as "nothing changed"."""
    pcie = tmp_path / "generated" / "pcie_uvm_env"
    pcie_sha = _git_subsystem_repo(pcie)
    stack = _full_stack(tmp_path)
    rows = [_selection_row("PCIE_SS", environment_path=str(pcie)),
            _selection_row("USB_SS", environment_path=str(tmp_path / "nowhere"))]
    entries = [_registry_entry("PCIE_SS", sha=pcie_sha),
               dict(_registry_entry("USB_SS"), release_sha="")]
    impact = srp.compute_subsystem_change_impact(
        tmp_path, _selection(rows), stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)

    by_id = {d["subsystem"]: d for d in impact["subsystem_diffs"]}
    assert by_id["USB_SS"]["status"] == srp.DIFF_NO_BASE_SHA
    assert by_id["USB_SS"]["changed"] is False
    assert impact["undecidable_subsystems"] == ["USB_SS"]
    assert impact["selective_regression"]["verdict"] == srp.SELECTIVE_UNSUPPORTED

    plan = stack["regression_plan"]
    targeted = srp.select_targeted_system_regression(plan, impact)
    assert targeted["mode"] == srp.SELECTIVE_UNSUPPORTED
    assert targeted["retained_entry_ids"] == [e["entry_id"] for e in plan["entries"]]
    assert targeted["dropped_entry_ids"] == []


def test_sys36_selective_regression_keeps_mandatory_entries_and_drops_only_untouched(tmp_path):
    """SYS-36 permits narrowing; `regression_tiers`' MANDATORY_SIGNOFF class
    and an entry with no known scope are still retained -- expand, never
    shrink."""
    pcie = tmp_path / "generated" / "pcie_uvm_env"
    usb = tmp_path / "generated" / "usb_uvm_env"
    eth = tmp_path / "generated" / "eth_uvm_env"
    shas = {"PCIE_SS": _git_subsystem_repo(pcie, second_commit=True),
            "USB_SS": _git_subsystem_repo(usb, second_commit=False),
            "ETH_SS": _git_subsystem_repo(eth, second_commit=False)}
    paths = {"PCIE_SS": pcie, "USB_SS": usb, "ETH_SS": eth}

    stack = _full_stack(tmp_path)
    rows = [_selection_row(sid, environment_path=str(paths[sid])) for sid in shas]
    entries = [_registry_entry(sid, sha=sha) for sid, sha in shas.items()]
    selection = _selection(rows)
    plan = srp.build_system_regression_plan(
        selection, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)
    impact = srp.compute_subsystem_change_impact(
        tmp_path, selection, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)
    assert impact["changed_subsystems"] == ["PCIE_SS"]

    targeted = srp.select_targeted_system_regression(plan, impact)
    assert targeted["mode"] == srp.SELECTIVE_SUPPORTED
    assert targeted["dropped_entry_ids"], "a selective run must really drop something"
    by_id = {e["entry_id"]: e for e in plan["entries"]}
    for entry_id in targeted["dropped_entry_ids"]:
        entry = by_id[entry_id]
        assert entry["selection_class"] != "MANDATORY_SIGNOFF"
        assert entry["participating_subsystems"]
        assert "PCIE_SS" not in entry["participating_subsystems"]
    for entry_id in targeted["retained_entry_ids"]:
        entry = by_id[entry_id]
        assert (entry["selection_class"] == "MANDATORY_SIGNOFF"
                or not entry["participating_subsystems"]
                or "PCIE_SS" in entry["participating_subsystems"])


def test_sys36_affected_artifacts_are_joined_from_the_real_sys15_21_26_30_layers(tmp_path):
    pcie = tmp_path / "generated" / "pcie_uvm_env"
    pcie_sha = _git_subsystem_repo(pcie)
    stack = _full_stack(tmp_path)
    rows = [_selection_row("PCIE_SS", environment_path=str(pcie))]
    entries = [_registry_entry("PCIE_SS", sha=pcie_sha)]
    impact = srp.compute_subsystem_change_impact(
        tmp_path, _selection(rows), stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)

    ir_pcie = {e["system_command_id"]
               for e in stack["command_plan"]["system_command_ir"]["entries"]
               if e["source_subsystem"] == "PCIE_SS"}
    assert {c["system_command_id"] for c in impact["affected_system_commands"]} == ir_pcie
    model = stack["topology_analysis"]["system_scenario_model"]["scenarios"]
    expected = sorted(s["scenario_id"] for s in model
                      if "PCIE_SS" in s["participating_subsystems"])
    assert impact["affected_system_scenarios"] == expected


@pytest.mark.skipif(not GATE.exists(), reason="change-impact gate script not present")
def test_sys36_payload_passes_the_real_gate_and_a_broken_one_fails_it(tmp_path):
    """The gate is attestation-only by construction, so its PASS is only
    evidence if a WRONG payload really fails. Both halves are run as real
    subprocesses against the shipped script."""
    pcie = tmp_path / "generated" / "pcie_uvm_env"
    usb = tmp_path / "generated" / "usb_uvm_env"
    shas = {"PCIE_SS": _git_subsystem_repo(pcie, second_commit=True),
            "USB_SS": _git_subsystem_repo(usb, second_commit=False)}
    paths = {"PCIE_SS": pcie, "USB_SS": usb}
    stack = _full_stack(tmp_path)
    rows = [_selection_row(sid, environment_path=str(paths[sid])) for sid in shas]
    entries = [_registry_entry(sid, sha=sha) for sid, sha in shas.items()]
    impact = srp.compute_subsystem_change_impact(
        tmp_path, _selection(rows), stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], registry_entries=entries)
    payload = srp.build_change_impact_gate_input(impact)
    assert payload["changed_subsystems"] == ["PCIE_SS"]
    assert payload["rerun_scenarios"], "the fixture must produce impacted scenarios"

    good = tmp_path / "impact_good.json"
    good.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run([sys.executable, str(GATE), "--impact", str(good)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == "PASS"

    broken = dict(payload, rerun_scenarios=[])
    bad = tmp_path / "impact_bad.json"
    bad.write_text(json.dumps(broken), encoding="utf-8")
    result = subprocess.run([sys.executable, str(GATE), "--impact", str(bad)],
                            capture_output=True, text=True)
    assert result.returncode == 3
    assert json.loads(result.stdout.strip().splitlines()[-1])["reason"] == \
        "MISSING_IMPACTED_RERUN_SCENARIOS"


# ============================================================================
# SYS-37 -- SYSTEM ENVIRONMENT READINESS
# ============================================================================

def _derive(stack, **kwargs):
    return sr.derive_system_readiness(
        stack["selection"], stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"],
        version_pin=kwargs.pop("version_pin", None),
        regression_plan=kwargs.pop("regression_plan", stack["regression_plan"]))


def test_sys37_derivation_covers_all_ten_inputs_in_order(tmp_path):
    readiness = _derive(_full_stack(tmp_path))
    assert [i["input"] for i in readiness["inputs"]] == list(sr.SYS37_INPUTS)
    for row in readiness["inputs"]:
        assert row["status"] in sr.INPUT_STATUSES
        assert row["evidence"].strip()
    assert readiness["system_readiness"] in sr.SYSTEM_READINESS_CLASSES


def test_sys37_unresolved_active_driver_conflict_blocks_and_prevents_ready(tmp_path):
    """SYS-37's own closing sentence, as a check. The conflicting entry is the
    imported CONFLICT_DRIVER clock/reset agent -- two subsystems claiming one
    active driver, which SYS-42's golden rule forbids."""
    stack = _full_stack(tmp_path, driver_conflict=True)
    readiness = _derive(stack)

    dedup = next(i for i in readiness["inputs"]
                 if i["input"] == sr.IN_VIP_DEDUP_RESOLUTION)
    assert dedup["status"] == sr.INPUT_BLOCKED
    assert dedup["conflicting_resources"] == ["SYSRES-CLKRST-0001"]
    assert readiness["system_readiness"] == sr.BLOCKED
    assert readiness["system_readiness"] != sr.READY
    assert readiness["active_driver_conflict"]["unresolved"] is True
    assert readiness["active_driver_conflict"]["prevents_ready"] is True

    # The control. The imported topology fixture deliberately carries OTHER
    # real conflicts (an address overlap, two clock/reset disagreements, three
    # blocking command collisions), so the same stack without the driver
    # conflict is still BLOCKED -- by different inputs. What must change is the
    # VIP-dedup input and the active-driver record, and asserting only that is
    # what gives this test detection power for the thing it is about.
    clean = _derive(_full_stack(tmp_path))
    clean_dedup = next(i for i in clean["inputs"]
                       if i["input"] == sr.IN_VIP_DEDUP_RESOLUTION)
    assert clean_dedup["status"] != sr.INPUT_BLOCKED
    assert clean["active_driver_conflict"]["unresolved"] is False
    assert clean["active_driver_conflict"]["prevents_ready"] is False
    assert clean["active_driver_conflict"]["conflicting_resources"] == []


def _clean_documents():
    """Minimal but real-SHAPED SYS-15..30 documents in which all ten SYS-37
    inputs are CLEAR. Every key below is one the real builders emit (see the
    `build_*` functions those modules own); this exists so READY is proved
    REACHABLE -- a derivation that could never return its best value would be
    indistinguishable from one that is simply broken."""
    rows = [_selection_row("PCIE_SS"), _selection_row("USB_SS")]
    pin = sr.build_composition_version_pin(
        _selection(rows), _registry_entries(eth_sha=None))
    integration_plan = {
        "system_resource_registry": {
            "entries": [], "subsystems": ["PCIE_SS", "USB_SS"],
            "summary": {
                "entry_count": 2,
                "entries_by_reuse_decision": {d: (2 if d == srr.REUSE_SHARED else 0)
                                              for d in srr.SYS17_DECISIONS},
                "entries_by_conflict_status": {c: (2 if c == srr.CONFLICT_NONE else 0)
                                               for c in srr.CONFLICT_STATUSES},
            }},
        "vip_agent_deduplication_matrix": {"rows": [], "summary": {"row_count": 0,
                                                                   "blocked": 0}},
    }
    command_plan = {"summary": {"collisions": 0, "blocking_collisions": 0,
                                "subsystem_modes_preserved": True}}
    scheduling_plan = {
        "shared_resource_scheduling": {
            "entries": [],
            "summary": {"row_count": 1,
                        "by_disposition": {d: (1 if d == ssp.SCHED_KEEP_SUBSYSTEM_LOCAL
                                               else 0) for d in ssp.SYS24_DISPOSITIONS}}},
        "global_serialization_check": {"verdict": ssp.NO_GLOBAL_SERIALIZATION},
        "scoreboard_integration": {
            "subsystems": [], "system_correlation_layer": {},
            "summary": {"scoreboards_reused": 2, "scoreboards_modified": 0,
                        "scoreboards_replaced": 0,
                        "topology_descriptor_parts_missing": 0,
                        "topology_descriptor_parts_available": 3}},
    }
    topology = {
        "address_map_reconciliation": {
            "per_subsystem": {}, "overlaps": [],
            "summary": {"region_count": 4, "overlapping_pairs": 1, "conflicts": 0,
                        "subsystems_with_self_overlap": [],
                        "by_verdict": {c: 0 for c in sta.SYS28_OVERLAP_CLASSES}}},
        "clock_reset_comparison": {"clock_comparisons": [], "reset_comparisons": [],
                                    "summary": {"conflicts": 0}},
        "clock_reset_compatibility_input": {"computed_value": "PASS",
                                             "reason": "no disagreement"},
        "system_scenario_model": {"scenarios": [],
                                   "summary": {"scenario_count": 2,
                                               "cross_subsystem_scenarios": 2,
                                               "scenario_bodies_generated": 0}},
    }
    regression_plan = {"summary": {"entry_count": 5},
                       "concatenation_check": {"verdict": srp.SELECTION_EVIDENCED}}
    return (_selection(rows), integration_plan, command_plan, scheduling_plan,
            topology, pin, regression_plan)


def test_sys37_ready_is_reachable_and_one_concern_drops_it_to_partial():
    selection, integration, command, scheduling, topology, pin, plan = _clean_documents()
    readiness = sr.derive_system_readiness(
        selection, integration, command, scheduling, topology,
        version_pin=pin, regression_plan=plan)
    assert readiness["system_readiness"] == sr.READY
    assert readiness["summary"]["inputs_clear"] == 10

    # One CONCERN is enough: not-yet-clean never rounds up.
    topology["system_scenario_model"]["summary"]["cross_subsystem_scenarios"] = 0
    partial = sr.derive_system_readiness(
        selection, integration, command, scheduling, topology,
        version_pin=pin, regression_plan=plan)
    assert partial["system_readiness"] == sr.PARTIAL

    # And one BLOCKED outranks nine clear inputs.
    topology["system_scenario_model"]["summary"]["cross_subsystem_scenarios"] = 2
    command["summary"]["blocking_collisions"] = 1
    blocked = sr.derive_system_readiness(
        selection, integration, command, scheduling, topology,
        version_pin=pin, regression_plan=plan)
    assert blocked["system_readiness"] == sr.BLOCKED


def test_sys37_all_unknown_inputs_report_unknown_never_partial():
    """A composition nobody could examine must not be reported with the same
    word as one examined and found lacking."""
    readiness = sr.derive_system_readiness({}, {}, {}, {}, {})
    assert readiness["system_readiness"] == sr.UNKNOWN
    assert readiness["summary"]["inputs_unknown"] == 10


def test_sys37_ready_requires_every_input_clear_and_never_rounds_up(tmp_path):
    stack = _full_stack(tmp_path)
    readiness = _derive(stack)
    clear = [i["input"] for i in readiness["inputs"] if i["status"] == sr.INPUT_CLEAR]
    if readiness["system_readiness"] == sr.READY:
        assert len(clear) == len(sr.SYS37_INPUTS)
    else:
        assert len(clear) < len(sr.SYS37_INPUTS)
        assert readiness["system_readiness"] in (sr.PARTIAL, sr.BLOCKED)


def test_sys37_verdict_authorizes_nothing(tmp_path):
    readiness = _derive(_full_stack(tmp_path))
    assert "NOTHING" in readiness["authorizes"]
    assert "SYS-40" in readiness["authorizes"]


# ============================================================================
# SYS-34 -- KNOWLEDGE CENTER UPDATE
# ============================================================================

class _RecordingKnowledgeCenter(kc.KnowledgeCenterClient):
    """The REAL client with only its transport replaced. Subclassing rather
    than hand-rolling a stub is what makes `record_system_composition()`'s own
    refusal logic the thing under test instead of a re-typed copy of it."""

    def __init__(self):
        super().__init__({}, project_root=None)
        self.added = []

    def add(self, category, protocol, record):
        self.added.append({"category": category, "protocol": protocol,
                           "record": record})
        return {"ok": True, "memory_id": "KC-FIXTURE-0001"}


def test_sys34_record_carries_the_requirements_own_field_list(tmp_path):
    stack = _full_stack(tmp_path)
    pin = sr.build_composition_version_pin(stack["selection"], stack["registry_entries"])
    readiness = _derive(stack, version_pin=pin)
    record = sr.build_system_composition_record(
        pin, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], readiness,
        regression_plan=stack["regression_plan"])

    for field in kc.SYSTEM_COMPOSITION_FIELDS:
        assert field in record, field
    assert record["COMPOSITION_ID"] == pin["composition_id"]
    assert record["SUBSYSTEM_VERSIONS"] == pin["subsystem_versions"]
    assert record["SYSTEM_READINESS"] == readiness["system_readiness"]
    assert record["SYSTEM_COMMAND_TXT"]["command_txt_written"] == 0
    assert record["REGRESSION_EVIDENCE"]["system_regression_executed"] == 0
    assert record["KNOWN_LIMITATIONS"], "a Phase-1 record must state its limits"


def test_sys34_uses_the_existing_knowledge_center_not_a_parallel_store():
    """SYS-34: "No parallel knowledge store." The composition record goes
    through the SAME add/search verbs, the same broker and the same lifecycle
    as SYS-3's subsystem records and SYOSCB-3's component records."""
    client = _RecordingKnowledgeCenter()
    published = client.record_system_composition({
        "COMPOSITION_ID": "SYSCOMP-DEADBEEF", "SYSTEM_COMPOSITION": ["PCIE_SS", "USB_SS"],
        "PHASE": kc.PHASE_2_INTEGRATED})
    assert published["ok"] is True
    assert client.added[0]["category"] == kc.SYSTEM_COMPOSITION_CATEGORY
    assert client.added[0]["record"]["kind"] == kc.SYSTEM_COMPOSITION_RECORD_KIND
    assert set(kc.SYSTEM_COMPOSITION_FIELDS) <= set(client.added[0]["record"])


def test_sys34_refuses_to_publish_a_phase_1_plan(tmp_path):
    """SYS-34's first four words are "After successful integration", and this
    shard is read across projects and users. A Phase-1 plan published there
    would later read as "this composition was built and passed"."""
    stack = _full_stack(tmp_path)
    pin = sr.build_composition_version_pin(stack["selection"], stack["registry_entries"])
    record = sr.build_system_composition_record(
        pin, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], _derive(stack, version_pin=pin))
    assert record["PHASE"] == kc.PHASE_1_PLAN

    client = _RecordingKnowledgeCenter()
    result = sr.publish_system_composition_record(client, record)
    assert result["ok"] is False
    assert result["error"] == "PHASE_NOT_PUBLISHABLE"
    assert client.added == [], "nothing may reach the shared store at Phase 1"

    # A record with no id is refused too -- nobody could look it up.
    assert client.record_system_composition({"PHASE": kc.PHASE_2_INTEGRATED})["error"] \
        == "COMPOSITION_ID_REQUIRED"


def test_sys34_normalizer_is_case_insensitive_and_present_and_null():
    record = kc.normalize_system_composition_record(
        {"composition_id": "SYSCOMP-1", "SYSTEM_READINESS": "PARTIAL",
         "memory_id": "KC-1", "status": "ACTIVE"})
    assert record["COMPOSITION_ID"] == "SYSCOMP-1"
    assert record["SYSTEM_READINESS"] == "PARTIAL"
    assert record["KNOWN_LIMITATIONS"] is None  # present-and-null, never a KeyError
    assert record["_kc"]["memory_id"] == "KC-1"


def test_sys34_publish_without_a_client_is_an_honest_result_not_a_crash():
    result = sr.publish_system_composition_record(None, {"COMPOSITION_ID": "X"})
    assert result["ok"] is False
    assert result["error"] == "NO_KNOWLEDGE_CENTER_CLIENT"


# ============================================================================
# SYS-38 -- the twenty-two-item Phase-1 report
# ============================================================================

def _report(tmp_path, **overrides):
    stack = _full_stack(tmp_path)
    pin = sr.build_composition_version_pin(stack["selection"], stack["registry_entries"])
    readiness = _derive(stack, version_pin=pin)
    record = sr.build_system_composition_record(
        pin, stack["integration_plan"], stack["command_plan"],
        stack["scheduling_plan"], stack["topology_analysis"], readiness,
        regression_plan=stack["regression_plan"])
    kwargs = dict(
        selection=stack["selection"], synthesis=None,
        resource_analysis=None,
        integration_plan=stack["integration_plan"],
        command_plan=stack["command_plan"],
        scheduling_plan=stack["scheduling_plan"],
        topology_analysis=stack["topology_analysis"],
        regression_plan=stack["regression_plan"],
        version_pin=pin, readiness=readiness, knowledge_center_record=record)
    kwargs.update(overrides)
    return stack, spr.build_system_phase1_report(**kwargs)


def test_sys38_all_twenty_two_sections_render_once_each_in_order(tmp_path):
    _stack, report = _report(tmp_path)
    text = spr.render_system_phase1_report(report)
    spr.assert_report_section_order(text)
    for number, title in spr.SYS38_SECTIONS:
        assert text.count(f"\n## {number}. {title}\n") == 1


def test_sys38_a_missing_input_renders_a_visible_note_and_is_never_omitted(tmp_path):
    """A reader told there are twenty-two sections uses that to notice one is
    missing -- so an unfillable section must SAY so, in place."""
    _stack, report = _report(tmp_path)
    assert 5 in report["summary"]["sections_not_supplied"]  # synthesis omitted above
    body = spr.section_body(report, 5)
    assert body.startswith("_NOT SUPPLIED._")
    assert "analyze_selected_subsystems" in body
    text = spr.render_system_phase1_report(report)
    assert "## 5. PER-SUBSYSTEM ARCHITECTURE ANALYSIS" in text


def test_sys38_out_of_order_missing_and_duplicated_headings_are_all_refused(tmp_path):
    _stack, report = _report(tmp_path)
    text = spr.render_system_phase1_report(report)

    dropped = text.replace("\n## 12. SYSTEM_RESOURCE_REGISTRY\n", "\n")
    with pytest.raises(spr.SystemPhase1ReportError) as excinfo:
        spr.assert_report_section_order(dropped)
    assert excinfo.value.reason == "SYS38_SECTION_MISSING"

    duplicated = text + "\n## 12. SYSTEM_RESOURCE_REGISTRY\n\nagain\n"
    with pytest.raises(spr.SystemPhase1ReportError) as excinfo:
        spr.assert_report_section_order(duplicated)
    assert excinfo.value.reason == "SYS38_SECTION_DUPLICATED"

    swapped = "\n".join([
        "## 2. SUBSYSTEM EXISTENCE CHECK", "", "b", "",
        "## 1. USER SELECTED SUBSYSTEMS", "", "a", "",
    ] + [line for number, title in spr.SYS38_SECTIONS[2:]
         for line in (f"## {number}. {title}", "", "x", "")])
    with pytest.raises(spr.SystemPhase1ReportError) as excinfo:
        spr.assert_report_section_order(swapped)
    assert excinfo.value.reason == "SYS38_SECTIONS_OUT_OF_ORDER"


def test_sys38_report_emits_no_bind_statement_and_no_compilable_systemverilog(tmp_path):
    _stack, report = _report(tmp_path)
    text = spr.render_system_phase1_report(report)  # runs both guards itself
    assert "System command.txt written: 0" in text
    assert "scenario bodies generated: 0" in text
    assert report["summary"]["implementation_started"] is False


def test_sys38_open_questions_collects_from_every_layer_and_files_nothing(tmp_path):
    """Section 20 COLLECTS; the layers that detect a conflict escalate it
    themselves, idempotently. A report that re-escalated on every render would
    grow the question queue every time somebody printed it."""
    stack = _full_stack(tmp_path, driver_conflict=True)
    pin = sr.build_composition_version_pin(
        stack["selection"],
        [_registry_entry("PCIE_SS", sha="pcie1234"),
         dict(_registry_entry("USB_SS"), release_sha="")])
    readiness = _derive(stack, version_pin=pin)
    questions = spr.collect_open_questions(
        selection=stack["selection"], resource_analysis=None,
        integration_plan=stack["integration_plan"],
        command_plan=stack["command_plan"],
        scheduling_plan=stack["scheduling_plan"],
        topology_analysis=stack["topology_analysis"],
        readiness=readiness, version_pin=pin)

    sources = {q["source"] for q in questions}
    assert "SYS-15 registry" in sources          # the DRIVER_CONFLICT entry
    assert "SYS-35 version pinning" in sources   # the unpinned subsystem
    assert "SYS-37 readiness input" in sources
    assert any(q["blocking"] for q in questions)
    # Blocking items sort first, so a reader meets them before the rest.
    blocking_flags = [q["blocking"] for q in questions]
    assert blocking_flags == sorted(blocking_flags, reverse=True)


def test_sys38_section_22_carries_sys39s_stop_verbatim_whatever_the_verdict(tmp_path):
    """The stop is about who decides, not about how the analysis came out."""
    for driver_conflict in (False, True):
        stack = _full_stack(tmp_path, driver_conflict=driver_conflict)
        readiness = _derive(stack)
        report = spr.build_system_phase1_report(
            selection=stack["selection"],
            integration_plan=stack["integration_plan"],
            command_plan=stack["command_plan"],
            scheduling_plan=stack["scheduling_plan"],
            topology_analysis=stack["topology_analysis"],
            readiness=readiness)
        text = spr.render_system_phase1_report(report)
        gate = spr.section_body(report, 22)
        spr.assert_stop_condition_exact(
            gate.split("```")[1] if "```" in gate else gate)
        assert spr.render_stop_condition() in text
        assert report["stop_condition"] == spr.render_stop_condition()


def test_sys38_section_bodies_come_from_the_owning_modules_not_a_second_computation(tmp_path):
    """The report must not hold a second opinion about anything it reports."""
    stack, report = _report(tmp_path)
    assert spr.section_body(report, 12) == srr.render_registry_table(
        stack["integration_plan"]["system_resource_registry"])
    assert spr.section_body(report, 15) == sta.render_address_overlap_table(
        stack["topology_analysis"]["address_map_reconciliation"])
    assert spr.section_body(report, 16) == sta.render_clock_reset_table(
        stack["topology_analysis"]["clock_reset_comparison"])


def test_sys38_section_not_present_raises_rather_than_returning_empty(tmp_path):
    _stack, report = _report(tmp_path)
    with pytest.raises(spr.SystemPhase1ReportError) as excinfo:
        spr.section_body(report, 23)
    assert excinfo.value.reason == "SYS38_SECTION_NOT_PRESENT"


# ============================================================================
# End to end, through the real front door on a real project tree
# ============================================================================

def _real_project(tmp_path):
    _write_env_tree(tmp_path / "generated" / "pcie_uvm_env")
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [_registry_entry("PCIE", sha="pcie1234"),
                               _registry_entry("USB", sha="usb56789")])
    _write_candidate_sources(tmp_path, [
        {"name": "PCIE", "protocol": "PCIE",
         "environment_path": "generated/pcie_uvm_env"},
        {"name": "USB", "protocol": "USB",
         "environment_path": "generated/usb_uvm_env"}])


def test_end_to_end_produces_all_twenty_two_sections_and_stops(tmp_path):
    """SYS-1 selection through SYS-39, through the real front door, on a real
    project tree -- nothing hand-assembled."""
    _real_project(tmp_path)
    result = spr.produce_phase1_report(tmp_path, ["PCIE", "USB"])

    assert result["selection"]["selection_admissible"] is True
    assert result["phase1_report"]["summary"]["sections_not_supplied"] == []
    assert result["phase1_report"]["summary"]["section_count"] == 22
    assert result["system_readiness"]["system_readiness"] in sr.SYSTEM_READINESS_CLASSES
    assert result["version_pin"]["subsystem_versions"] == {"PCIE": "pcie1234",
                                                           "USB": "usb56789"}
    assert result["knowledge_center_record"]["PHASE"] == kc.PHASE_1_PLAN
    assert result["stop_condition"] == spr.render_stop_condition()

    text = result["phase1_report_text"]
    spr.assert_report_section_order(text)
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in text
    assert "AWAITING USER APPROVAL" in text


def test_end_to_end_writes_nothing_into_the_project(tmp_path):
    """Phase 1 is analysis. The pin file and the KC record are both separate,
    explicit calls -- running the report must leave the tree alone."""
    _real_project(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    spr.produce_phase1_report(tmp_path, ["PCIE", "USB"])
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert not sr.pin_path(tmp_path).exists()


def _run_cli(tmp_path, *extra):
    """The same real-subprocess convention `test_system_topology_analysis`
    uses for its own verb, so the SYS-28..30 and SYS-33..39 CLI layers cannot
    drift into two shapes."""
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-phase1-report", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def test_the_cli_refuses_an_empty_selection_through_sys1(tmp_path):
    """SYS-1's explicit-selection refusal is not bypassed by adding a verb on
    top of the stack. An empty report must read as "nothing was selected",
    never as "this system is ready"."""
    _real_project(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 2, proc.stderr
    assert "NO_EXPLICIT_SELECTION" in proc.stdout
    assert "AWAITING USER APPROVAL" in proc.stdout


def test_the_cli_prints_all_twenty_two_sections_and_writes_nothing_by_default(tmp_path):
    """The real end-to-end path: a real subprocess through the whole
    SYS-1 -> SYS-39 stack, with both subsystem environments byte-identical
    afterwards. A Phase-1 pass that quietly wrote a System command.txt or
    touched a subsystem environment would be exactly the SYS-40 crossing
    SYS-39 forbids."""
    _real_project(tmp_path)
    # Scoped to the subsystem ENVIRONMENT trees, as the SYS-28..30 CLI test is:
    # the claim under test is SYS-14's ("preserve existing subsystem
    # environments") plus SYS-39's, not that a `DVHarness` construction writes
    # no state of its own -- it writes .dv-harness/agents/*.json on every verb,
    # and asserting otherwise would be testing the wrong thing.
    generated = tmp_path / "generated"
    before = {str(p.relative_to(generated)): p.read_bytes()
              for p in sorted(generated.rglob("*")) if p.is_file()}

    proc = _run_cli(tmp_path, "--select", "PCIE", "--select", "USB")
    assert proc.returncode in (0, 2), proc.stderr
    for number, title in spr.SYS38_SECTIONS:
        assert f"## {number}. {title}" in proc.stdout, (number, title)
    for line in spr.SYS39_STOP_LINES:
        assert line in proc.stdout, line
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout

    after = {str(p.relative_to(generated)): p.read_bytes()
             for p in sorted(generated.rglob("*")) if p.is_file()}
    assert after == before
    for forbidden in ("system_command.txt", "soc_command.txt", "system_scoreboard.sv",
                      "system_virtual_sequencer.sv", "system_address_decoder.sv",
                      "system_composition_pins.json"):
        assert not list(tmp_path.rglob(forbidden)), forbidden


def test_the_cli_writes_the_pin_only_when_explicitly_asked(tmp_path):
    _real_project(tmp_path)
    proc = _run_cli(tmp_path, "--select", "PCIE", "--select", "USB", "--write-pin")
    assert proc.returncode in (0, 2), proc.stderr
    assert sr.pin_path(tmp_path).exists()
    stored = sr.read_composition_pins(tmp_path)["compositions"]
    assert len(stored) == 1
    assert stored[0]["subsystem_versions"] == {"PCIE": "pcie1234", "USB": "usb56789"}
    # Still never the real registration authority.
    registry = json.loads((tmp_path / ".dv-harness" / "soc-composer"
                           / "subsystem_environment_registry.json").read_text())
    assert [e["name"] for e in registry["subsystems"]] == ["PCIE", "USB"]


def test_end_to_end_refuses_a_subsystem_the_user_did_not_select(tmp_path):
    """SYS-1's refusal is not bypassed by adding a verb on top of it."""
    _real_project(tmp_path)
    result = spr.produce_phase1_report(tmp_path, ["PCIE"])
    assert result["selection"]["selected_subsystems"] == ["PCIE"]
    assert result["version_pin"]["subsystems"] == ["PCIE"]
    assert "USB" not in result["version_pin"]["subsystem_versions"]
    # A one-subsystem composition has no cross-subsystem scenario to run, and
    # SYS-37 must say so rather than reporting a clean single-subsystem system.
    scenario_input = next(i for i in result["system_readiness"]["inputs"]
                          if i["input"] == sr.IN_SCENARIO_AVAILABILITY)
    assert scenario_input["status"] in (sr.INPUT_CONCERN, sr.INPUT_UNKNOWN)
    assert result["system_readiness"]["system_readiness"] != sr.READY
