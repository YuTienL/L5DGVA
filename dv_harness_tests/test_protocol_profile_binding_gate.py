import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "protocol_profile_binding_gate.py"
REGISTRY = ROOT / ".dv-harness" / "builder" / "protocol_builder_registry.json"


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--binding", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_usb_profile_and_vip_lookup_both_consulted_passes():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-profile", "USB/usb-vip-lookup"]},
    ]})
    assert rc == 0 and out["status"] == "PASS"


def test_usb_missing_profile_skill_fails():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-vip-lookup"]},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "PROFILE_SKILL_NOT_CONSULTED"
    assert out["protocol"] == "usb"
    assert "USB/usb-profile" in out["missing"]


def test_usb_missing_vip_lookup_skill_fails():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-profile"]},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert "USB/usb-vip-lookup" in out["missing"]


def test_protocol_with_null_profile_skill_requires_no_consultation():
    rc, out = _run({"protocols": [
        {"protocol": "emmc", "profile_skills_consulted": []},
    ]})
    assert rc == 0 and out["status"] == "PASS"


def test_unknown_protocol_key_fails():
    rc, out = _run({"protocols": [
        {"protocol": "not-a-real-protocol", "profile_skills_consulted": []},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "UNKNOWN_PROTOCOL"
