import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "protocol_isolation_gate.py"


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--edit", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_no_evidence_refs_at_all_is_a_pass():
    rc, out = _run({"branch": "block"})
    assert rc == 0 and out["status"] == "PASS"


def test_vip_evidence_ref_into_forbidden_tree_fails(tmp_path):
    forbidden_dir = tmp_path / "USB_UVM_Handoff" / "seq"
    forbidden_dir.mkdir(parents=True)
    forbidden_file = forbidden_dir / "usb_seq.sv"
    forbidden_file.write_text("class usb_seq;\nendclass\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(forbidden_file), "quote": "class usb_seq"}],
    })
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"
    assert out["forbidden_tree"] == "USB_UVM_Handoff"


def test_dut_evidence_ref_into_forbidden_tree_fails(tmp_path):
    forbidden_dir = tmp_path / "USB_UVM_Handoff" / "rtl"
    forbidden_dir.mkdir(parents=True)
    forbidden_file = forbidden_dir / "usb_ctrl.v"
    forbidden_file.write_text("module usb_ctrl;\nendmodule\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_a0",
        "dut_rtl_evidence_refs": [{"path": str(forbidden_file), "quote": "module usb_ctrl"}],
    })
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"


def test_evidence_ref_into_real_vip_manual_passes(tmp_path):
    real_dir = tmp_path / "vip_manual"
    real_dir.mkdir()
    real_file = real_dir / "usb_vip_manual.md"
    real_file.write_text("class usb_seq;\nendclass\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(real_file), "quote": "class usb_seq"}],
    })
    assert rc == 0 and out["status"] == "PASS"


def test_substring_match_in_unrelated_filename_does_not_false_positive(tmp_path):
    # A filename that merely CONTAINS "USB_UVM_Handoff" as a substring, but
    # is not actually a path segment under that directory, must not trip
    # the forbidden-tree check -- it must match whole path segments only.
    real_dir = tmp_path / "notes"
    real_dir.mkdir()
    real_file = real_dir / "my_USB_UVM_Handoff_summary.md"
    real_file.write_text("summary text\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(real_file), "quote": "summary text"}],
    })
    assert rc == 0 and out["status"] == "PASS"
