from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generator_py_header_does_not_claim_fully_orphaned():
    text = (ROOT / "dv_harness" / "uvm_generator" / "generator.py").read_text(encoding="utf-8")
    header = text[:800]
    assert "NOT invoked by any executing code path" not in header
    assert "deprecated" in header.lower()
    assert "ProtocolEnvGenerator" in header


def test_protocol_env_generator_py_does_not_call_generator_py_orphaned():
    text = (ROOT / "dv_harness" / "uvm_generator" / "protocol_env_generator.py").read_text(encoding="utf-8")
    header = text[:1200]
    assert "orphaned/unwired" not in header
