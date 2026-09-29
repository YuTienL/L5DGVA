"""Tests for dv_harness/protocol_capability.py -- the honest per-protocol
generation-capability claim (2026-09-04 multi-protocol-scope gap closure).

The gap these guard was never "the underlying function does not work". It was
that .dv-harness/qualification/protocol_capability_registry.json asserted
`REAL_CODE_GENERATOR_AVAILABLE` for 11 protocols when only 5 have a
protocol-specific module, and that claim reached real production surfaces
(dashboard.py's Protocols card, tools/universal_protocol/protocol_status.py's
output). So these tests are about the WIRING: that the shipped registry is
checked against the shipped code, that the two real consumers carry the split
claim, and that a re-overstated registry is refused rather than reported.
"""
from __future__ import annotations

import copy
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from dv_harness import protocol_capability as pc

ROOT = Path(__file__).resolve().parents[1]


# --- the shipped registry, checked against the shipped code -----------------

def test_shipped_registry_matches_the_code_that_actually_exists():
    """The whole point: this repo's real registry must not claim more than this
    repo's real modules support. Fails loudly the moment either side moves."""
    pc.assert_registry_matches_code(ROOT)


def test_every_declared_protocol_model_module_really_imports():
    for cap in pc.PROTOCOL_CAPABILITIES:
        if cap.model is None:
            continue
        assert pc.module_is_importable(cap.model.module), \
            f"{cap.protocol} declares {cap.model.module} which does not import"
        assert (ROOT / cap.model.tool).exists(), \
            f"{cap.protocol} declares tool {cap.model.tool} which does not exist"


def test_generic_skeleton_generator_is_real():
    assert pc.module_is_importable(pc.GENERIC_SKELETON_GENERATOR)


def test_the_four_unmodelled_protocols_report_generic_skeleton_only():
    """Ethernet/eDP/UCIe have no protocol-specific module anywhere in
    dv_harness/, and SD_SDIO's only model is the protocol-agnostic CMDQ tag
    lifecycle. The first three must therefore say GENERIC_SKELETON_ONLY --
    this is the exact claim the old registry got wrong."""
    for name in ("Ethernet", "eDP_DisplayPort", "UCIe"):
        cap = pc.capability_for(name)
        assert cap is not None and cap.model is None
        assert pc.derive_status(cap) == pc.STATUS_GENERIC_SKELETON_ONLY


def test_usb_is_the_only_dut_proven_protocol():
    proven = [c.protocol for c in pc.PROTOCOL_CAPABILITIES
              if pc.derive_status(c) == pc.STATUS_DUT_PROVEN]
    assert proven == ["USB_2_3x"]


def test_dut_proven_requires_evidence_that_exists_on_disk():
    """DUT_PROVEN is the strongest claim in the vocabulary, so it is earned by
    real files, not by a label. Point it at a path that is not there and the
    status drops."""
    cap = pc.capability_for("USB_2_3x")
    assert pc.derive_status(cap) == pc.STATUS_DUT_PROVEN
    fabricated = pc.ProtocolCapability(
        protocol="USB_2_3x", model=None,
        dut_proof=("examples/generated_usb_real_evidence_v999/environment_manifest.json",),
    )
    assert pc.derive_status(fabricated) == pc.STATUS_GENERIC_SKELETON_ONLY


def test_partial_models_all_name_what_they_do_not_model():
    """A PROTOCOL_MODEL_PARTIAL status is only honest if the partial-ness is
    readable without opening the module."""
    for cap in pc.PROTOCOL_CAPABILITIES:
        if pc.derive_status(cap) != pc.STATUS_PROTOCOL_MODEL_PARTIAL:
            continue
        assert cap.model is not None and cap.model.does_not_model, cap.protocol
        assert cap.model.models, cap.protocol


def test_amba_partial_names_ace_lite_and_axi_stream_as_unmodelled():
    """Both return zero hits in amba_fabric_generator.py, and AXI-Stream has no
    address channel at all -- structurally out of reach of an address-decode
    fabric model. The registry must say so."""
    cap = pc.capability_for("AMBA4_MULTI_MASTER_MULTI_SLAVE")
    assert "ace_lite_coherency" in cap.model.does_not_model
    assert "axi_stream" in cap.model.does_not_model


def test_semantic_models_alias_keys_resolve():
    """The semantic-models files spell two protocols differently from the
    registry (USB / AMBA4_MMxMS). Both must resolve, or those files silently
    keep an unchecked capability claim."""
    assert pc.capability_for("USB") is pc.capability_for("USB_2_3x")
    assert pc.capability_for("AMBA4_MMxMS") is pc.capability_for("AMBA4_MULTI_MASTER_MULTI_SLAVE")


def test_no_legacy_capability_claim_survives_anywhere_under_dv_harness():
    assert pc.find_legacy_capability_claims(ROOT) == []


# --- drift guard: a re-overstated registry must be refused ------------------

def _project_with_registry(mutate) -> Path:
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / pc.REGISTRY_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / pc.REGISTRY_RELPATH).read_text(encoding="utf-8"))
    mutate(data)
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # No tools/ or examples/ are copied in on purpose: `root` selects WHICH
    # registry to check, while tool and dut_proof paths are harness assets
    # resolved against pc.HARNESS_ROOT. A temp project with neither directory
    # must still validate cleanly apart from the mutation under test -- that
    # is what makes this module usable from a downstream project.
    return tmp


def _problems_for(mutate) -> list:
    tmp = _project_with_registry(mutate)
    try:
        with pytest.raises(pc.ProtocolCapabilityDriftError) as exc:
            pc.assert_registry_matches_code(tmp)
        return exc.value.problems
    finally:
        shutil.rmtree(tmp)


def test_negative_control_unmutated_copy_of_the_registry_validates_clean():
    """Without this, every drift test below could be passing because the temp
    project is broken in some unrelated way rather than because the mutation
    was caught."""
    tmp = _project_with_registry(lambda d: None)
    try:
        pc.assert_registry_matches_code(tmp)
    finally:
        shutil.rmtree(tmp)


def test_reintroducing_generation_capability_is_refused():
    problems = _problems_for(
        lambda d: d["protocols"]["Ethernet"].update(
            {pc.LEGACY_CAPABILITY_KEY: pc.LEGACY_CAPABILITY_VALUE})
    )
    assert any(pc.LEGACY_CAPABILITY_KEY in p and "Ethernet" in p for p in problems)


def test_reintroducing_the_blanket_status_is_refused():
    problems = _problems_for(
        lambda d: d["protocols"]["UCIe"].update({"status": pc.LEGACY_STATUS_VALUE})
    )
    assert any(pc.LEGACY_STATUS_VALUE in p and "UCIe" in p for p in problems)


def test_claiming_a_protocol_model_that_does_not_exist_is_refused():
    """The exact original defect, re-staged: Ethernet claiming a real generator."""
    problems = _problems_for(
        lambda d: d["protocols"]["Ethernet"].update({
            "protocol_model_generator": "dv_harness.uvm_generator.ethernet_mac_generator",
            "capability_status": pc.STATUS_PROTOCOL_MODEL_PARTIAL,
        })
    )
    assert any("protocol_model_generator" in p and "Ethernet" in p for p in problems)
    assert any("capability_status" in p and "Ethernet" in p for p in problems)


def test_upgrading_a_status_beyond_what_the_code_earns_is_refused():
    problems = _problems_for(
        lambda d: d["protocols"]["PCIe"].update({"capability_status": pc.STATUS_DUT_PROVEN})
    )
    assert any("capability_status" in p and "PCIe" in p for p in problems)


def test_a_protocol_dropped_from_the_registry_is_refused():
    problems = _problems_for(lambda d: d["protocols"].pop("CAN_FD"))
    assert any("CAN_FD" in p and "absent from the registry" in p for p in problems)


def test_an_unknown_protocol_in_the_registry_is_refused():
    problems = _problems_for(
        lambda d: d["protocols"].update({"Thunderbolt": {"capability_status": "DUT_PROVEN"}})
    )
    assert any("Thunderbolt" in p for p in problems)


def test_new_interface_framework_cannot_reclaim_the_blanket_status():
    problems = _problems_for(
        lambda d: d["new_interface_framework"].update({"status": pc.LEGACY_STATUS_VALUE})
    )
    assert any("new_interface_framework" in p for p in problems)


def test_drift_error_reports_every_problem_at_once_not_just_the_first():
    def mutate(d):
        d["protocols"]["Ethernet"]["capability_status"] = pc.STATUS_DUT_PROVEN
        d["protocols"]["UCIe"]["capability_status"] = pc.STATUS_DUT_PROVEN
    problems = _problems_for(mutate)
    assert any("Ethernet" in p for p in problems)
    assert any("UCIe" in p for p in problems)


def test_sync_is_idempotent_and_repairs_an_overstated_registry():
    tmp = _project_with_registry(
        lambda d: d["protocols"]["Ethernet"].update({
            pc.LEGACY_CAPABILITY_KEY: pc.LEGACY_CAPABILITY_VALUE,
            "status": pc.LEGACY_STATUS_VALUE,
            "capability_status": pc.STATUS_DUT_PROVEN,
        })
    )
    try:
        changed = pc.sync_registry(tmp)
        assert "Ethernet" in changed
        pc.assert_registry_matches_code(tmp)  # repaired
        assert pc.sync_registry(tmp) == []    # idempotent
        entry = json.loads((tmp / pc.REGISTRY_RELPATH).read_text(encoding="utf-8"))["protocols"]["Ethernet"]
        assert pc.LEGACY_CAPABILITY_KEY not in entry
        assert entry["capability_status"] == pc.STATUS_GENERIC_SKELETON_ONLY
    finally:
        shutil.rmtree(tmp)


def test_sync_leaves_fields_owned_by_other_mechanisms_alone():
    """qualification_status/builder_profile/qualification_suite belong to the
    qualification ladder and the builder platform, not to this module."""
    tmp = _project_with_registry(lambda d: None)
    try:
        before = json.loads((tmp / pc.REGISTRY_RELPATH).read_text(encoding="utf-8"))
        pc.sync_registry(tmp)
        after = json.loads((tmp / pc.REGISTRY_RELPATH).read_text(encoding="utf-8"))
        for name, entry in before["protocols"].items():
            for key in ("qualification_status", "builder_profile", "qualification_suite",
                        "qualification_note"):
                if key in entry:
                    assert after["protocols"][name][key] == entry[key], f"{name}.{key} was rewritten"
    finally:
        shutil.rmtree(tmp)


# --- consumer 1: tools/universal_protocol/protocol_status.py ---------------

def _run_protocol_status(cwd=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "universal_protocol" / "protocol_status.py")],
        capture_output=True, text=True, timeout=60, cwd=str(cwd or ROOT),
    )


def test_protocol_status_prints_both_columns_for_the_real_registry():
    r = _run_protocol_status()
    assert r.returncode == 0, r.stderr
    out = r.stdout
    # The split claim, not one collapsed column.
    assert "CAPABILITY" in out and "QUALIFICATION" in out
    assert "PROTOCOL MODEL GENERATOR" in out
    # Ethernet must be visibly skeleton-only, PCIe visibly modelled-but-partial.
    eth = next(line for line in out.splitlines() if line.startswith("Ethernet"))
    assert pc.STATUS_GENERIC_SKELETON_ONLY in eth and "NONE" in eth
    pcie = next(line for line in out.splitlines() if line.startswith("PCIe"))
    assert pc.STATUS_PROTOCOL_MODEL_PARTIAL in pcie
    assert "pcie_ltssm_generator" in pcie
    assert pc.LEGACY_STATUS_VALUE not in out
    assert pc.LEGACY_CAPABILITY_VALUE not in out


def test_protocol_status_refuses_to_report_an_overstated_registry():
    """The wiring that matters: the status command cannot print a readiness
    the code does not back. Previously it printed whatever the file said."""
    tmp = _project_with_registry(
        lambda d: d["protocols"]["Ethernet"].update({
            "capability_status": pc.STATUS_DUT_PROVEN,
            "protocol_model_generator": "dv_harness.uvm_generator.ethernet_mac_generator",
        })
    )
    try:
        # protocol_status.py resolves its root from its own location, so drive
        # the same refusal through the module CLI against the temp project --
        # the identical assert_registry_matches_code() call the tool makes.
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.protocol_capability", "--check", "--root", str(tmp)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
        assert r.returncode == 2
        assert "Ethernet" in r.stderr
    finally:
        shutil.rmtree(tmp)


def test_module_check_passes_against_this_repo():
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.protocol_capability", "--check"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr


# --- consumer 2: the real dashboard HTTP surface ---------------------------

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _dashboard_project(port: int) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (tmp / ".dv-harness" / "config.json").write_text(json.dumps({
        "dashboard": {"host": "127.0.0.1", "port": port},
        "policy": {"require_stage_gate_evidence": False, "max_stage_retries": 0},
    }), encoding="utf-8")
    dest = tmp / pc.REGISTRY_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / pc.REGISTRY_RELPATH, dest)
    return tmp


def _serve(tmp: Path):
    from dv_harness import dashboard
    t = threading.Thread(target=dashboard.serve, args=(tmp,),
                         kwargs={"adapter_factory": None}, daemon=True)
    t.start()
    return t


def _wait(base: str, timeout: float = 15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/state", timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.05)
    raise AssertionError(f"dashboard never became ready: {last}")


def test_dashboard_api_state_carries_the_split_capability_claim():
    """dashboard.py's _protocol_registry() is a real production reader of this
    registry. Before this change it surfaced only qualification_status, which
    was BUILDER_AVAILABLE for all 11 -- indistinguishable readiness. The real
    HTTP surface must now carry capability_status and the module name."""
    port = _free_port()
    tmp = _dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _serve(tmp)
        state = _wait(base)
        registry = {p["name"]: p for p in state["protocol_registry"]}
        assert set(registry) == set(pc.known_protocols())
        assert registry["Ethernet"]["capability_status"] == pc.STATUS_GENERIC_SKELETON_ONLY
        assert registry["Ethernet"]["protocol_model_generator"] == "NONE"
        assert registry["PCIe"]["capability_status"] == pc.STATUS_PROTOCOL_MODEL_PARTIAL
        assert registry["PCIe"]["protocol_model_generator"].endswith("pcie_ltssm_generator")
        assert registry["USB_2_3x"]["capability_status"] == pc.STATUS_DUT_PROVEN
        # qualification_status is a different question and must be untouched.
        assert registry["Ethernet"]["qualification_status"] == "BUILDER_AVAILABLE"

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        # The tile really renders it, with real CSS behind the class.
        assert "capability_status" in html
        assert "cap-generic-only" in html
        style = html.split("<style>")[1].split("</style>")[0]
        assert ".cap-generic-only" in style and ".cap-dut-proven" in style
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the registry is not hand-maintained prose -----------------------------

def test_registry_note_points_at_its_generator():
    data = json.loads((ROOT / pc.REGISTRY_RELPATH).read_text(encoding="utf-8"))
    assert "dv_harness/protocol_capability.py" in data["note"]
    assert "--sync" in data["note"]


def test_semantic_model_files_carry_the_same_split_claim():
    d = ROOT / pc.SEMANTIC_MODELS_RELDIR
    files = sorted(d.glob("*.json"))
    assert files, "no semantic-model files found"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert pc.LEGACY_CAPABILITY_KEY not in data, path.name
        cap = pc.capability_for(str(data.get("protocol") or path.stem))
        assert cap is not None, path.name
        assert data["capability_status"] == pc.derive_status(cap), path.name
        expected = cap.model.module if cap.model else "NONE"
        assert data["protocol_model_generator"] == expected, path.name


def test_capability_status_vocabulary_is_disjoint_from_the_qualification_ladder():
    """Two vocabularies answering two different questions must not share a
    token, or a reader will conflate 'code exists' with 'proven'."""
    from dv_harness.qualification import CANONICAL_LADDER
    assert not set(pc.STATUS_VOCABULARY) & set(CANONICAL_LADDER)


def test_copy_of_the_registry_is_not_mutated_by_a_read():
    data = pc.load_registry(ROOT)
    snapshot = copy.deepcopy(data)
    pc.assert_registry_matches_code(ROOT)
    assert pc.load_registry(ROOT) == snapshot
