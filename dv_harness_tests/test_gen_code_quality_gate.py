"""Tests for dv_harness/gen_code_quality_gate.py -- the composite
Generated-Code Quality Gate (spec section 221) that folds
`uvm_structural_lint.py`'s real findings and `vip_api_card.py`'s real
BLOCKED-citation findings worst-wins into one PASS/FAIL/INCOMPLETE_EVIDENCE
verdict.

Discipline, matching this project's own house style for a module that reuses
two existing checks:

  1. A clean baseline -- the SAME fixture `test_vip_api_card.py` already uses
     (`fixtures/vip_api/demo_env_seq.sv` against the real synthetic VIP source
     `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv`) -- lints
     clean AND resolves fully PROVEN, so it doubles as a clean input to BOTH
     underlying checks and gives the composite gate a real PASS.
  2. Each rule is then driven by MUTATING that clean baseline one defect at a
     time: a real structural-lint ERROR finding, a real BLOCKED VIP API
     citation, and both at once (worst-wins).
  3. A real UNPROVABLE case (an open inheritance chain, zero BLOCKED) proves
     the gate reports INCOMPLETE_EVIDENCE rather than FAIL or PASS.
  4. A negative control proves this module never re-derives either check:
     with both real underlying functions monkeypatched to raise, supplying
     already-computed reports directly still folds correctly and neither
     function is ever called.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import gen_code_quality_gate as gcq
from dv_harness import uvm_structural_lint as usl
from dv_harness import vip_api_card as vac
from dv_harness import vip_symbol_index as vsi

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"
CLEAN_FIXTURE = Path(__file__).parent / "fixtures" / "vip_api" / "demo_env_seq.sv"

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None, reason="verible-verilog-syntax not on PATH")


@pytest.fixture(scope="module")
def demo_index():
    """The REAL vip_symbol_index over the REAL synthetic VIP source -- the
    same fixture test_vip_api_card.py's own tests build."""
    return vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)


@pytest.fixture(scope="module")
def clean_source():
    return CLEAN_FIXTURE.read_text(encoding="utf-8")


def _env_dir(tmp_path, text: str, name: str = "generated_env.sv") -> Path:
    d = tmp_path / "env"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d


def _evaluate(tmp_path, text, index):
    """Run the real gate over a generated source: real structural lint AND
    real VIP API validation, both against the identical source text."""
    d = _env_dir(tmp_path, text)
    return gcq.evaluate_gen_code_quality_gate(
        env_dir=d, vip_sources=[d], vip_index=index, vip_relative_to=d)


def _mutate(clean_source, old, new):
    assert old in clean_source, f"mutation anchor not found in fixture: {old!r}"
    return clean_source.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. the clean baseline -- both real conditions MET
# ---------------------------------------------------------------------------

@requires_verible
def test_both_conditions_met_reports_pass(tmp_path, demo_index, clean_source):
    report = _evaluate(tmp_path, clean_source, demo_index)
    assert report.status == gcq.GATE_PASS, gcq.format_report(report)
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert lint_cond.status == gcq.COND_MET
    assert vip_cond.status == gcq.COND_MET
    assert report.structural_lint_status == "PASS"
    assert report.vip_api_status == vac.PROVEN


@requires_verible
def test_pass_report_renders_a_readable_table(tmp_path, demo_index, clean_source):
    report = _evaluate(tmp_path, clean_source, demo_index)
    text = gcq.format_report(report)
    assert "PASS" in text
    assert gcq.CONDITION_STRUCTURAL_LINT in text
    assert gcq.CONDITION_VIP_API in text


# ---------------------------------------------------------------------------
# 2. a real structural-lint ERROR finding fails the gate
# ---------------------------------------------------------------------------

@requires_verible
def test_structural_lint_error_finding_fails_the_gate(tmp_path, demo_index, clean_source):
    mutated = _mutate(
        clean_source,
        "  `uvm_object_utils(demo_env_base_vseq)\n", "")
    report = _evaluate(tmp_path, mutated, demo_index)
    assert report.status == gcq.GATE_FAIL, gcq.format_report(report)
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert lint_cond.status == gcq.COND_UNMET
    assert lint_cond.detail["error_count"] >= 1
    assert any(f["rule"] == "FACTORY_REGISTRATION_MISSING" for f in lint_cond.detail["findings"])
    # The unrelated check stays clean -- this is a REAL, isolated finding,
    # not a mutation that happens to break everything at once.
    assert vip_cond.status == gcq.COND_MET
    assert report.structural_lint_status == "FAIL"
    assert report.vip_api_status == vac.PROVEN


# ---------------------------------------------------------------------------
# 3. a real BLOCKED VIP API citation fails the gate
# ---------------------------------------------------------------------------

@requires_verible
def test_vip_api_blocked_citation_fails_the_gate(tmp_path, demo_index, clean_source):
    mutated = _mutate(clean_source, "cfg.apply_preset(2);", "cfg.reconfigur(2);")
    report = _evaluate(tmp_path, mutated, demo_index)
    assert report.status == gcq.GATE_FAIL, gcq.format_report(report)
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert vip_cond.status == gcq.COND_UNMET
    assert vip_cond.detail["blocked_count"] >= 1
    assert any(c["citation"] == "svt_demo_cfg.reconfigur" for c in vip_cond.detail["blocked_cards"])
    # The unrelated check stays clean.
    assert lint_cond.status == gcq.COND_MET
    assert report.structural_lint_status == "PASS"
    assert report.vip_api_status == vac.BLOCKED


# ---------------------------------------------------------------------------
# 4. worst-wins: both real defects at once still fold to one FAIL
# ---------------------------------------------------------------------------

@requires_verible
def test_worst_wins_both_unmet_conditions_still_one_fail(tmp_path, demo_index, clean_source):
    mutated = _mutate(
        clean_source, "  `uvm_object_utils(demo_env_base_vseq)\n", "")
    mutated = _mutate(mutated, "cfg.apply_preset(2);", "cfg.reconfigur(2);")
    report = _evaluate(tmp_path, mutated, demo_index)
    assert report.status == gcq.GATE_FAIL, gcq.format_report(report)
    unmet = [c.name for c in report.conditions if c.status == gcq.COND_UNMET]
    assert set(unmet) == {gcq.CONDITION_STRUCTURAL_LINT, gcq.CONDITION_VIP_API}
    assert gcq.CONDITION_STRUCTURAL_LINT in report.reason
    assert gcq.CONDITION_VIP_API in report.reason


# ---------------------------------------------------------------------------
# 5. an honest UNPROVABLE citation -> INCOMPLETE_EVIDENCE, never FAIL/PASS
# ---------------------------------------------------------------------------

_OPEN_CHAIN_VIP_SRC = textwrap.dedent("""\
    package quality_demo_vip_pkg;
      class quality_demo_cfg extends quality_demo_external_base;
        virtual function void known_method();
        endfunction
      endclass

      class quality_demo_helper extends uvm_object;
        virtual function void do_something();
        endfunction
      endclass
    endpackage
    """)

_OPEN_CHAIN_GENERATED_SRC = textwrap.dedent("""\
    class quality_gate_open_chain_vseq extends uvm_sequence #(uvm_sequence_item);
      `uvm_object_utils(quality_gate_open_chain_vseq)

      function new(string name = "quality_gate_open_chain_vseq");
        super.new(name);
      endfunction

      virtual task body();
        quality_demo_cfg h;
        h = new();
        h.unknown_method();
      endtask
    endclass
    """)


@requires_verible
def test_unprovable_vip_citation_reports_incomplete_evidence(tmp_path):
    vip_dir = tmp_path / "vip_src"
    vip_dir.mkdir()
    (vip_dir / "quality_demo_vip_pkg.sv").write_text(_OPEN_CHAIN_VIP_SRC, encoding="utf-8")
    index = vsi.build_symbol_index([vip_dir], "demo_open_chain", relative_to=vip_dir)

    env_dir = _env_dir(tmp_path, _OPEN_CHAIN_GENERATED_SRC, name="open_chain_env.sv")
    report = gcq.evaluate_gen_code_quality_gate(
        env_dir=env_dir, vip_sources=[env_dir], vip_index=index, vip_relative_to=env_dir)

    assert report.vip_api_status == vac.UNPROVABLE
    assert report.status == gcq.GATE_INCOMPLETE_EVIDENCE, gcq.format_report(report)
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert vip_cond.status == gcq.COND_UNKNOWN
    assert vip_cond.detail["unprovable_count"] >= 1
    # The structural lint side is real and clean -- this is genuinely an
    # UNKNOWN pulling the verdict down from PASS, not a second real defect.
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    assert lint_cond.status == gcq.COND_MET


# ---------------------------------------------------------------------------
# 6. a generated environment with no VIP API citations at all: NOT_APPLICABLE
#    never blocks PASS
# ---------------------------------------------------------------------------

_NO_VIP_CALLS_SRC = textwrap.dedent("""\
    class quality_gate_no_vip_item extends uvm_sequence_item;
      `uvm_object_utils(quality_gate_no_vip_item)
      function new(string name = "quality_gate_no_vip_item");
        super.new(name);
      endfunction
    endclass
    """)


@requires_verible
def test_no_vip_api_citations_is_not_applicable_and_still_passes(tmp_path, demo_index):
    env_dir = _env_dir(tmp_path, _NO_VIP_CALLS_SRC, name="no_vip_env.sv")
    report = gcq.evaluate_gen_code_quality_gate(
        env_dir=env_dir, vip_sources=[env_dir], vip_index=demo_index, vip_relative_to=env_dir)
    assert report.vip_api_status == vac.NOT_AVAILABLE
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert vip_cond.status == gcq.COND_NOT_APPLICABLE
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    assert lint_cond.status == gcq.COND_MET
    assert report.status == gcq.GATE_PASS, gcq.format_report(report)


# ---------------------------------------------------------------------------
# 7. honest absence: nothing supplied at all -> INCOMPLETE_EVIDENCE, never PASS
#    (the negative control this project's house style mandates for every new
#    module: it must refuse to fabricate a clean answer when evidence is
#    absent)
# ---------------------------------------------------------------------------

def test_no_reports_and_nothing_to_produce_them_from_reports_incomplete_evidence():
    report = gcq.evaluate_gen_code_quality_gate()
    assert report.status == gcq.GATE_INCOMPLETE_EVIDENCE, gcq.format_report(report)
    lint_cond = report.condition(gcq.CONDITION_STRUCTURAL_LINT)
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert lint_cond.status == gcq.COND_UNKNOWN
    assert vip_cond.status == gcq.COND_UNKNOWN
    assert report.structural_lint_status is None
    assert report.vip_api_status is None


def test_vip_sources_without_an_index_never_fabricates_a_vip_report():
    """Supplying only `vip_sources` (no `vip_index`) must never silently
    trigger a VIP API check -- the condition stays honestly UNKNOWN."""
    report = gcq.evaluate_gen_code_quality_gate(vip_sources=["/does/not/matter"])
    vip_cond = report.condition(gcq.CONDITION_VIP_API)
    assert vip_cond.status == gcq.COND_UNKNOWN
    assert report.vip_api_status is None


# ---------------------------------------------------------------------------
# 8. never re-derives either check: with both real functions monkeypatched
#    to raise, supplying already-computed reports still folds correctly and
#    neither function is ever called
# ---------------------------------------------------------------------------

def test_never_re_derives_either_check_when_reports_are_already_supplied(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("gen_code_quality_gate must not re-run this check")

    monkeypatch.setattr(usl, "lint_uvm_environment", _boom)
    monkeypatch.setattr(usl, "lint_uvm_sources", _boom)
    monkeypatch.setattr(vac, "validate_vip_api_usage", _boom)
    monkeypatch.setattr(vac, "load_index", _boom)

    lint_report = usl.UvmLintReport(status="PASS")
    vip_report = vac.VipApiValidationReport(status=vac.PROVEN, counts={vac.PROVEN: 3})

    report = gcq.evaluate_gen_code_quality_gate(
        lint_report=lint_report, vip_api_report=vip_report,
        # These would trigger a real run if the pre-supplied reports were
        # ignored -- passing them alongside proves they are NOT consulted.
        env_dir="/does/not/matter", vip_sources=["/does/not/matter"],
        vip_index={"schema_version": "1.0"})

    assert report.status == gcq.GATE_PASS
    assert report.structural_lint_status == "PASS"
    assert report.vip_api_status == vac.PROVEN


def test_never_re_derives_a_blocked_or_fail_verdict_either(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("gen_code_quality_gate must not re-run this check")

    monkeypatch.setattr(usl, "lint_uvm_environment", _boom)
    monkeypatch.setattr(vac, "validate_vip_api_usage", _boom)

    lint_report = usl.UvmLintReport(
        status="FAIL",
        findings=[usl.LintFinding(
            rule="FACTORY_REGISTRATION_MISSING", severity="ERROR",
            file_path="x.sv", line=1, subject="x", message="missing")])

    report = gcq.evaluate_gen_code_quality_gate(lint_report=lint_report, env_dir="/nope")
    assert report.status == gcq.GATE_FAIL
    assert report.condition(gcq.CONDITION_STRUCTURAL_LINT).status == gcq.COND_UNMET


# ---------------------------------------------------------------------------
# 9. classify_*_condition() and fold_conditions() as pure unit functions
# ---------------------------------------------------------------------------

def test_classify_structural_lint_condition_not_available_is_unknown():
    report = usl.UvmLintReport(status="NOT_AVAILABLE", reason="verible not found")
    cond = gcq.classify_structural_lint_condition(report)
    assert cond.status == gcq.COND_UNKNOWN
    assert "verible not found" in cond.reason


def test_classify_vip_api_condition_status_vocabulary_covers_every_real_value():
    assert gcq.classify_vip_api_condition(
        vac.VipApiValidationReport(status=vac.PROVEN, counts={vac.PROVEN: 1})
    ).status == gcq.COND_MET
    assert gcq.classify_vip_api_condition(
        vac.VipApiValidationReport(status=vac.BLOCKED, cards=[vac.VipApiCard(
            citation="x.y", kind="METHOD", vip_class="x", member="y",
            status=vac.BLOCKED, usage_file="f.sv", usage_line=1, usage_text="x.y();")])
    ).status == gcq.COND_UNMET
    assert gcq.classify_vip_api_condition(
        vac.VipApiValidationReport(status=vac.UNPROVABLE)
    ).status == gcq.COND_UNKNOWN
    assert gcq.classify_vip_api_condition(
        vac.VipApiValidationReport(status=vac.NOT_AVAILABLE,
                                   reason="NO_VIP_API_CITATIONS_FOUND")
    ).status == gcq.COND_NOT_APPLICABLE
    assert gcq.classify_vip_api_condition(
        vac.VipApiValidationReport(status=vac.NOT_AVAILABLE, reason="NO_SOURCE_FILES_TO_VALIDATE")
    ).status == gcq.COND_UNKNOWN


def test_fold_conditions_worst_wins_precedence():
    met = gcq._condition("a", gcq.COND_MET, "ok")
    unmet = gcq._condition("b", gcq.COND_UNMET, "bad")
    unknown = gcq._condition("c", gcq.COND_UNKNOWN, "?")
    not_applicable = gcq._condition("d", gcq.COND_NOT_APPLICABLE, "n/a")

    assert gcq.fold_conditions([met, not_applicable])[0] == gcq.GATE_PASS
    assert gcq.fold_conditions([met, unknown])[0] == gcq.GATE_INCOMPLETE_EVIDENCE
    assert gcq.fold_conditions([met, unmet])[0] == gcq.GATE_FAIL
    # UNMET outranks UNKNOWN too -- a single real defect fails the gate even
    # alongside an unresolved condition.
    assert gcq.fold_conditions([unmet, unknown])[0] == gcq.GATE_FAIL


def test_condition_status_vocabulary_is_rejected_when_unrecognized():
    with pytest.raises(gcq.GenCodeQualityGateError):
        gcq._condition("x", "NOT_A_REAL_STATUS", "bad")


def test_gate_incomplete_evidence_never_collides_with_models_status():
    from dv_harness.models import Status
    assert gcq.GATE_INCOMPLETE_EVIDENCE not in {m.value for m in Status}


# ---------------------------------------------------------------------------
# 10. python -m front door
# ---------------------------------------------------------------------------

@requires_verible
def test_cli_pass_exit_code(tmp_path, demo_index, clean_source):
    import json
    env_dir = _env_dir(tmp_path, clean_source)
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(demo_index), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate",
         "--env-dir", str(env_dir),
         "--vip-source", str(env_dir), "--vip-index", str(index_path)],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


@requires_verible
def test_cli_env_dir_only_reports_vip_condition_honestly_unknown(tmp_path, clean_source):
    """Omitting --vip-source/--vip-index must never silently read as
    NOT_APPLICABLE -- the VIP condition stays UNKNOWN (nothing was checked),
    which pulls the whole gate to INCOMPLETE_EVIDENCE rather than PASS."""
    env_dir = _env_dir(tmp_path, clean_source)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate",
         "--env-dir", str(env_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "INCOMPLETE_EVIDENCE" in result.stdout


@requires_verible
def test_cli_fail_exit_code_on_real_lint_error(tmp_path, clean_source):
    mutated = _mutate(clean_source, "  `uvm_object_utils(demo_env_base_vseq)\n", "")
    env_dir = _env_dir(tmp_path, mutated)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate",
         "--env-dir", str(env_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout


def test_cli_incomplete_evidence_exit_code_no_source_files(tmp_path):
    empty_dir = tmp_path / "empty_env"
    empty_dir.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate",
         "--env-dir", str(empty_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "INCOMPLETE_EVIDENCE" in result.stdout


def test_cli_json_output_round_trips(tmp_path, demo_index, clean_source):
    import json
    env_dir = _env_dir(tmp_path, clean_source)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate",
         "--env-dir", str(env_dir), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True)
    doc = json.loads(result.stdout)
    assert doc["status"] in (gcq.GATE_PASS, gcq.GATE_FAIL, gcq.GATE_INCOMPLETE_EVIDENCE)
    assert len(doc["conditions"]) == 2


def test_cli_usage_error_when_nothing_supplied():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.gen_code_quality_gate"],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
