"""Tests for dv_harness/vip_learning_gate.py -- the VIP Learning Gate, the
single pre-generation checkpoint over four already-real signals:
vip_api_card.py, phy_boundary.py, connectivity.py bind-tier resolution, and
env_manifest.py's vip_config layer.

Discipline, the same one test_power_intent.py / test_vip_api_card.py use:
  1. Each of the four sub-checks is proven CLEAN over a real clean input,
     built through the REAL producing module (a real vip_symbol_index over a
     small real synthetic VIP source, a real generated env.manifest.json, a
     real phy_boundary.json this repo's own generator already produced, real
     bind entries run through the real tier classifier).
  2. Every BLOCKING/WARNING/NOT_AVAILABLE/NOT_APPLICABLE path is then driven
     by a real input that mutates or omits exactly one thing, so each
     assertion proves that ONE sub-check reacted to that ONE condition
     without the others being disturbed.
  3. The composite verdict is checked against combinations of the four, so
     "BLOCKED if any sub-check is BLOCKING, PASS with a carried warning
     otherwise, NOT_AVAILABLE only when nothing could be evaluated at all" is
     proven rather than assumed.
  4. Both real CLI entry points (`python -m dv_harness.vip_learning_gate`)
     exit codes are driven as real subprocesses.

Nothing here re-implements any of the four modules' own judgment -- every
fixture below is built by calling the REAL function
(`vip_symbol_index.build_symbol_index`, `vip_api_card.validate_vip_api_usage`
indirectly through the gate, `phy_boundary.extract_phy_boundary`,
`connectivity.enforce_bind_tier_policy` indirectly, `env_manifest.
generate_env_manifest`), never a hand-typed report dict standing in for one.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import connectivity
from dv_harness import env_manifest
from dv_harness import phy_boundary
from dv_harness import question_queue
from dv_harness import vip_api_card as vac
from dv_harness import vip_learning_gate as vlg
from dv_harness import vip_symbol_index as vsi

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PHY_BOUNDARY_PARALLEL = (REPO_ROOT / "examples" / "asset_processing" / "generated"
                              / "phy_boundary.json")
REAL_PHY_BOUNDARY_SERIAL = (REPO_ROOT / "examples" / "asset_processing" / "generated"
                            / "phy_boundary_serial.json")


# ---------------------------------------------------------------------------
# shared real inputs
# ---------------------------------------------------------------------------

_VIP_SRC = textwrap.dedent("""
    class svt_demo_cfg extends uvm_object;
      virtual function void apply_preset(int level);
      endfunction
      virtual function void set_defaults();
      endfunction
    endclass

    class svt_part_ext extends svt_part_hidden_base;
      virtual function void known_call();
      endfunction
    endclass
    """)

_CLEAN_SEQ = textwrap.dedent("""
    class demo_env_vseq extends uvm_sequence;
      virtual task body();
        svt_demo_cfg cfg;
        cfg = new();
        cfg.apply_preset(2);
        cfg.set_defaults();
      endtask
    endclass
    """)


@pytest.fixture(scope="module")
def demo_index(tmp_path_factory):
    """A REAL vip_symbol_index built by the real indexer over a small real
    synthetic VIP source (never a hand-written index dict)."""
    root = tmp_path_factory.mktemp("vip_src")
    (root / "svt_demo_pkg.sv").write_text(_VIP_SRC, encoding="utf-8")
    return vsi.build_symbol_index([root], "demo", relative_to=root)


def _write_generated_dir(tmp_path, text, name="demo_env_vseq.sv"):
    d = tmp_path / "env"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d


@pytest.fixture()
def clean_env_dir(tmp_path):
    return _write_generated_dir(tmp_path, _CLEAN_SEQ)


@pytest.fixture()
def blocked_env_dir(tmp_path):
    """One fabricated method name -- `apply_preset` -> `apply_prezet` -- the
    same single-defect mutation `test_vip_api_card.py` uses for its own
    headline BLOCKED case."""
    mutated = _CLEAN_SEQ.replace("cfg.apply_preset(2);", "cfg.apply_prezet(2);")
    assert mutated != _CLEAN_SEQ
    return _write_generated_dir(tmp_path, mutated, "blocked_env_vseq.sv")


@pytest.fixture()
def unprovable_env_dir(tmp_path):
    """A call through `svt_part_ext`, whose base is neither indexed nor a
    uvm_ base-library class -- an OPEN inheritance chain, section 187's
    UNKNOWN, never BLOCKED."""
    text = textwrap.dedent("""
        class demo_env_open_vseq extends uvm_sequence;
          virtual task body();
            svt_part_ext handle;
            handle = new();
            handle.unknown_call();
          endtask
        endclass
        """)
    return _write_generated_dir(tmp_path, text, "unprovable_env_vseq.sv")


def _phy_boundary_undecidable_doc():
    """Built by calling the REAL `phy_boundary.extract_phy_boundary()` over
    two synthetic modules sharing only a clock port -- no payload signal at
    all, so the real classifier reports UNDECIDABLE. No verible/slang binary
    is needed: `extract_phy_boundary()` consumes an already-parsed module
    list, it does not parse RTL itself."""
    phy_module = {"name": "phy_x", "ports": [
        {"name": "clk", "data_type": "logic", "direction": "input"}]}
    ctrl_module = {"name": "ctrl_x", "ports": [
        {"name": "clk", "data_type": "logic", "direction": "input"}]}
    doc = phy_boundary.extract_phy_boundary([phy_module, ctrl_module], "phy_x", "ctrl_x")
    assert doc["classification"]["kind"] == "UNDECIDABLE"
    return doc


T1_T2_BIND_ENTRIES = [
    {"target_instance": "chip.core.usb0", "tier": "T1_ALREADY_DECIDED", "reason": "existing bind"},
    {"target_instance": "chip.core.usb1", "tier": "T2_STRUCTURAL_MATCH", "reason": "fingerprint match"},
]
T4_BIND_ENTRIES = [
    {"target_instance": "chip.core.mystery", "tier": "T4_UNDECIDABLE", "reason": "no evidence at all"},
]
T3_UNCONFIRMED_BIND_ENTRIES = [
    {"target_instance": "chip.core.guess", "tier": "T3_NAMING_HEURISTIC", "reason": "name looks right"},
]
T3_CONFIRMED_BIND_ENTRIES = [
    {"target_instance": "chip.core.guess", "tier": "T3_NAMING_HEURISTIC", "reason": "name looks right",
     "human_confirmation": {"source": question_queue.HUMAN_DECISION_SOURCE,
                            "confirmed_by": "j.reviewer", "basis": "manually checked RTL hierarchy"}},
]


def _vip_config_dump(path, instance_path="tb.usb_agent", vip_type="svt_usb_agent"):
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "vip_instances": [{"instance_path": instance_path, "vip_type": vip_type, "config_fields": {}}],
    }), encoding="utf-8")
    return path


@pytest.fixture()
def captured_env_manifest_path(tmp_path):
    dump = _vip_config_dump(tmp_path / "vip_config_dump.json")
    manifest = env_manifest.generate_env_manifest(vip_config_dump_path=dump)
    assert manifest["vip_config"]["status"] == "CAPTURED"
    out = tmp_path / "env.manifest.captured.json"
    env_manifest.save_env_manifest(manifest, out)
    return out


@pytest.fixture()
def not_available_env_manifest_path(tmp_path):
    manifest = env_manifest.generate_env_manifest()
    assert manifest["vip_config"]["status"] == "NOT_AVAILABLE"
    out = tmp_path / "env.manifest.not_available.json"
    env_manifest.save_env_manifest(manifest, out)
    return out


# ---------------------------------------------------------------------------
# 1. check_vip_api_card
# ---------------------------------------------------------------------------

def test_vip_api_card_clean_is_clean(demo_index, clean_env_dir):
    result = vlg.check_vip_api_card(sources=[clean_env_dir], index=demo_index)
    assert result.status == vlg.CLEAN
    assert result.detail["counts"][vac.BLOCKED] == 0


def test_vip_api_card_fabricated_method_blocks(demo_index, blocked_env_dir):
    result = vlg.check_vip_api_card(sources=[blocked_env_dir], index=demo_index)
    assert result.status == vlg.BLOCKING
    assert "svt_demo_cfg.apply_prezet" in result.reason
    assert "svt_demo_cfg.apply_prezet" in result.detail["blocked_citations"]


def test_vip_api_card_open_chain_is_a_warning_not_a_block(demo_index, unprovable_env_dir):
    """Section 187's UNKNOWN: not a pass, and -- per this gate's own task --
    not a block either."""
    result = vlg.check_vip_api_card(sources=[unprovable_env_dir], index=demo_index)
    assert result.status == vlg.WARNING
    assert "svt_part_ext.unknown_call" in result.detail["unprovable_citations"]


def test_vip_api_card_nothing_supplied_is_not_applicable():
    result = vlg.check_vip_api_card()
    assert result.status == vlg.NOT_APPLICABLE


def test_vip_api_card_sources_without_index_is_not_available(clean_env_dir):
    result = vlg.check_vip_api_card(sources=[clean_env_dir])
    assert result.status == vlg.NOT_AVAILABLE


def test_vip_api_card_missing_index_file_is_not_available(clean_env_dir, tmp_path):
    result = vlg.check_vip_api_card(sources=[clean_env_dir],
                                    index_path=tmp_path / "no_such_index.json")
    assert result.status == vlg.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# 2. check_phy_boundary
# ---------------------------------------------------------------------------

def test_phy_boundary_real_parallel_doc_is_clean():
    doc = json.loads(REAL_PHY_BOUNDARY_PARALLEL.read_text(encoding="utf-8"))
    result = vlg.check_phy_boundary(doc=doc)
    assert result.status == vlg.CLEAN
    assert result.detail["mount_layer"] == "controller_phy_parallel_boundary"


def test_phy_boundary_real_serial_only_doc_blocks():
    """A real doc this repo's own generator produced: SERIAL-only, not
    bindable. A protocol monitor bound there decodes nothing (Gate 3 silent
    monitor), so this checkpoint must stop it before generation."""
    doc = json.loads(REAL_PHY_BOUNDARY_SERIAL.read_text(encoding="utf-8"))
    result = vlg.check_phy_boundary(doc=doc)
    assert result.status == vlg.BLOCKING
    assert result.detail["classification_kind"] == "SERIAL"
    assert "PHY_BOUNDARY_NOT_BINDABLE" in result.reason


def test_phy_boundary_undecidable_blocks():
    doc = _phy_boundary_undecidable_doc()
    result = vlg.check_phy_boundary(doc=doc)
    assert result.status == vlg.BLOCKING
    assert result.detail["classification_kind"] == "UNDECIDABLE"


def test_phy_boundary_not_available_doc_is_not_available():
    """A doc whose own status is NOT_AVAILABLE (the boundary could not be
    extracted at all) is honestly NOT_AVAILABLE here too -- never read as a
    clean pass, and never conflated with a real UNDECIDABLE decision."""
    doc = phy_boundary.extract_phy_boundary([], "phy_x", "ctrl_x")
    assert doc["status"] == "NOT_AVAILABLE"
    result = vlg.check_phy_boundary(doc=doc)
    assert result.status == vlg.NOT_AVAILABLE


def test_phy_boundary_nothing_supplied_is_not_applicable():
    """No PHY sub-block in scope for this build is a legitimate answer, per
    phy_boundary.py's own disclosed residual."""
    result = vlg.check_phy_boundary()
    assert result.status == vlg.NOT_APPLICABLE


def test_phy_boundary_missing_path_is_not_available(tmp_path):
    result = vlg.check_phy_boundary(doc_path=tmp_path / "no_such_boundary.json")
    assert result.status == vlg.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# 3. check_bind_tier
# ---------------------------------------------------------------------------

def test_bind_tier_t1_t2_entries_are_clean():
    result = vlg.check_bind_tier(bind_entries=T1_T2_BIND_ENTRIES)
    assert result.status == vlg.CLEAN
    assert len(result.detail["decisions"]) == 2


def test_bind_tier_t4_entry_blocks():
    result = vlg.check_bind_tier(bind_entries=T4_BIND_ENTRIES)
    assert result.status == vlg.BLOCKING
    assert result.reason == "T4_BIND_MUST_GO_TO_QUESTION_QUEUE"


def test_bind_tier_unconfirmed_t3_entry_blocks():
    result = vlg.check_bind_tier(bind_entries=T3_UNCONFIRMED_BIND_ENTRIES)
    assert result.status == vlg.BLOCKING
    assert result.reason == "T3_BIND_REQUIRES_HUMAN_CONFIRMATION"


def test_bind_tier_confirmed_t3_entry_is_clean():
    """The SAME T3 candidate as the unconfirmed case, differing only by a
    real human_confirmation carrying the sanctioned
    question_queue.HUMAN_DECISION_SOURCE -- proves the gate reacts to the
    confirmation, not to the target name."""
    result = vlg.check_bind_tier(bind_entries=T3_CONFIRMED_BIND_ENTRIES)
    assert result.status == vlg.CLEAN


def test_bind_tier_nothing_supplied_is_not_applicable():
    result = vlg.check_bind_tier()
    assert result.status == vlg.NOT_APPLICABLE


def test_bind_tier_empty_list_is_not_applicable():
    result = vlg.check_bind_tier(bind_entries=[])
    assert result.status == vlg.NOT_APPLICABLE


def test_bind_tier_entries_from_a_real_file(tmp_path):
    p = tmp_path / "bind_entries.json"
    p.write_text(json.dumps(T1_T2_BIND_ENTRIES), encoding="utf-8")
    result = vlg.check_bind_tier(bind_entries_path=p)
    assert result.status == vlg.CLEAN


# ---------------------------------------------------------------------------
# 4. check_vip_config_layer
# ---------------------------------------------------------------------------

def test_vip_config_layer_captured_is_clean(captured_env_manifest_path):
    result = vlg.check_vip_config_layer(manifest_path=captured_env_manifest_path)
    assert result.status == vlg.CLEAN


def test_vip_config_layer_not_available_blocks(not_available_env_manifest_path):
    result = vlg.check_vip_config_layer(manifest_path=not_available_env_manifest_path)
    assert result.status == vlg.BLOCKING
    assert result.reason  # the manifest's own real reason string, carried verbatim


def test_vip_config_layer_nothing_supplied_is_not_available():
    result = vlg.check_vip_config_layer()
    assert result.status == vlg.NOT_AVAILABLE


def test_vip_config_layer_missing_manifest_path_is_not_available(tmp_path):
    result = vlg.check_vip_config_layer(manifest_path=tmp_path / "no_such_manifest.json")
    assert result.status == vlg.NOT_AVAILABLE


def test_vip_config_layer_malformed_manifest_is_not_available(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    result = vlg.check_vip_config_layer(manifest_path=p)
    assert result.status == vlg.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# 5. composite: run_pre_generation_checkpoint()
# ---------------------------------------------------------------------------

def test_composite_passes_when_everything_supplied_is_clean(demo_index, clean_env_dir,
                                                             captured_env_manifest_path):
    report = vlg.run_pre_generation_checkpoint(
        vip_sources=[clean_env_dir], vip_index=demo_index,
        env_manifest_path=captured_env_manifest_path,
    )
    assert report.verdict == vlg.PASS
    assert report.blocking_checks == []
    assert report.get(vlg.CHECK_VIP_API_CARD).status == vlg.CLEAN
    assert report.get(vlg.CHECK_PHY_BOUNDARY).status == vlg.NOT_APPLICABLE
    assert report.get(vlg.CHECK_BIND_TIER).status == vlg.NOT_APPLICABLE
    assert report.get(vlg.CHECK_VIP_CONFIG_LAYER).status == vlg.CLEAN


def test_composite_blocks_naming_only_the_offending_check(demo_index, clean_env_dir,
                                                          captured_env_manifest_path):
    """A T4 bind entry is the ONLY thing wrong here; the other three real
    signals are clean/not-applicable, and the composite must name exactly
    the one offending sub-check."""
    report = vlg.run_pre_generation_checkpoint(
        vip_sources=[clean_env_dir], vip_index=demo_index,
        bind_entries=T4_BIND_ENTRIES,
        env_manifest_path=captured_env_manifest_path,
    )
    assert report.verdict == vlg.BLOCKED
    assert report.blocking_checks == [vlg.CHECK_BIND_TIER]
    assert report.get(vlg.CHECK_VIP_API_CARD).status == vlg.CLEAN


def test_composite_blocks_on_vip_api_card_alone(demo_index, blocked_env_dir):
    report = vlg.run_pre_generation_checkpoint(vip_sources=[blocked_env_dir], vip_index=demo_index)
    assert report.verdict == vlg.BLOCKED
    assert report.blocking_checks == [vlg.CHECK_VIP_API_CARD]


def test_composite_blocks_on_phy_boundary_alone():
    doc = json.loads(REAL_PHY_BOUNDARY_SERIAL.read_text(encoding="utf-8"))
    report = vlg.run_pre_generation_checkpoint(phy_boundary_doc=doc)
    assert report.verdict == vlg.BLOCKED
    assert report.blocking_checks == [vlg.CHECK_PHY_BOUNDARY]


def test_composite_blocks_on_vip_config_layer_alone(not_available_env_manifest_path):
    report = vlg.run_pre_generation_checkpoint(env_manifest_path=not_available_env_manifest_path)
    assert report.verdict == vlg.BLOCKED
    assert report.blocking_checks == [vlg.CHECK_VIP_CONFIG_LAYER]


def test_composite_multiple_blocking_checks_are_all_named(not_available_env_manifest_path):
    report = vlg.run_pre_generation_checkpoint(
        bind_entries=T4_BIND_ENTRIES,
        env_manifest_path=not_available_env_manifest_path,
    )
    assert report.verdict == vlg.BLOCKED
    assert set(report.blocking_checks) == {vlg.CHECK_BIND_TIER, vlg.CHECK_VIP_CONFIG_LAYER}


def test_composite_warning_is_carried_but_never_blocks(demo_index, unprovable_env_dir,
                                                       captured_env_manifest_path):
    report = vlg.run_pre_generation_checkpoint(
        vip_sources=[unprovable_env_dir], vip_index=demo_index,
        env_manifest_path=captured_env_manifest_path,
    )
    assert report.verdict == vlg.PASS
    assert report.warning_checks == [vlg.CHECK_VIP_API_CARD]
    assert report.blocking_checks == []


def test_composite_nothing_supplied_is_not_available():
    """No sub-check had any real evidence to evaluate: this must be a
    distinct, honest NOT_AVAILABLE -- never a fabricated PASS and never a
    fabricated BLOCKED."""
    report = vlg.run_pre_generation_checkpoint()
    assert report.verdict == vlg.GATE_NOT_AVAILABLE
    assert report.blocking_checks == []
    statuses = {c.name: c.status for c in report.sub_checks}
    assert statuses[vlg.CHECK_VIP_API_CARD] == vlg.NOT_APPLICABLE
    assert statuses[vlg.CHECK_PHY_BOUNDARY] == vlg.NOT_APPLICABLE
    assert statuses[vlg.CHECK_BIND_TIER] == vlg.NOT_APPLICABLE
    assert statuses[vlg.CHECK_VIP_CONFIG_LAYER] == vlg.NOT_AVAILABLE


def test_report_round_trips_through_json():
    report = vlg.run_pre_generation_checkpoint()
    blob = json.dumps(report.to_dict())
    restored = json.loads(blob)
    assert restored["verdict"] == vlg.GATE_NOT_AVAILABLE
    assert len(restored["sub_checks"]) == 4


# ---------------------------------------------------------------------------
# 6. real CLI subprocess: python -m dv_harness.vip_learning_gate
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_learning_gate", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def test_cli_exits_2_when_nothing_supplied():
    result = _run_cli()
    assert result.returncode == 2, result.stdout + result.stderr
    assert "NOT_AVAILABLE" in result.stdout


def test_cli_exits_1_when_vip_config_layer_is_not_available(not_available_env_manifest_path):
    result = _run_cli("--env-manifest", str(not_available_env_manifest_path))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BLOCKED" in result.stdout
    assert vlg.CHECK_VIP_CONFIG_LAYER in result.stdout


def test_cli_exits_0_when_clean(captured_env_manifest_path):
    result = _run_cli("--env-manifest", str(captured_env_manifest_path),
                      "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == vlg.PASS


def test_cli_exits_1_on_real_serial_phy_boundary():
    result = _run_cli("--phy-boundary", str(REAL_PHY_BOUNDARY_SERIAL))
    assert result.returncode == 1, result.stdout + result.stderr
    assert vlg.CHECK_PHY_BOUNDARY in result.stdout


def test_cli_exits_1_on_t4_bind_entries(tmp_path):
    p = tmp_path / "bind_entries.json"
    p.write_text(json.dumps(T4_BIND_ENTRIES), encoding="utf-8")
    result = _run_cli("--bind-entries", str(p))
    assert result.returncode == 1, result.stdout + result.stderr
