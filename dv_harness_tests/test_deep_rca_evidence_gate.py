"""Tests for tools/verification_flow/deep_rca_evidence_gate.py's independent
evidence_path hash recompute (2026-09-02, RE_AUDIT evidence-gate audit
follow-up: the gate previously only checked that an agent-submitted
evidence_hash/checked pair was a non-empty string -- nothing independently
recomputed a hash of the real current sim.log/RTL/waveform file on disk, so
an agent could cite a stale (recalled-from-memory) or fabricated hash and
still PASS. See the gate script's own module comment for the full
rationale)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "deep_rca_evidence_gate.py"

REQUIRED_SOURCES = [
    "SIM_LOG", "TRACE", "RTL", "TESTBENCH", "COMMAND", "SCOREBOARD",
    "PHY_MODEL", "STANDARD_SPEC", "VIP_EXAMPLE", "VIP_SOURCE", "VIP_DOCUMENT",
]


def _run_gate(root: Path, rca: dict):
    rca_path = root / "rca.json"
    rca_path.write_text(json.dumps(rca), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--rca", str(rca_path), "--root", str(root)],
        capture_output=True, text=True, timeout=30,
    )
    out = json.loads((r.stdout or "").strip() or "{}")
    return r.returncode, out


def _base_rca(evidence_sources):
    return {
        "evidence_sources": evidence_sources,
        "first_bad_event": {"time_ns": 1000},
        "causal_chain": [{"e": "a"}, {"e": "b"}],
        "confidence": "HIGH",
    }


def _legacy_sources(overrides=None):
    """One entry per required source, all satisfying the ORIGINAL
    non-empty-evidence_hash check with no evidence_path -- `overrides` maps
    a source name to a dict of extra/replaced fields (e.g. evidence_path)."""
    sources = [{"source": s, "checked": True, "evidence_hash": f"h_{s}"} for s in REQUIRED_SOURCES]
    if overrides:
        by_source = {s["source"]: s for s in sources}
        for name, patch in overrides.items():
            by_source[name].update(patch)
    return sources


def test_pass_legacy_non_empty_hash_backward_compat():
    # No evidence_path anywhere -- must still PASS exactly like before this
    # change, proving old callers that never adopted evidence_path keep
    # working (the weaker/legacy fallback path).
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate(tmp, _base_rca(_legacy_sources()))
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_pass_when_evidence_path_hash_matches_real_current_file():
    tmp = Path(tempfile.mkdtemp())
    try:
        sim_log = tmp / "sim.log"
        sim_log.write_text("UVM_ERROR ... FIFO_EMPTY at t=1000ns\n", encoding="utf-8")
        real_hash = hashlib.sha256(sim_log.read_bytes()).hexdigest()
        sources = _legacy_sources({
            "SIM_LOG": {"evidence_path": "sim.log", "evidence_hash": real_hash},
        })
        rc, out = _run_gate(tmp, _base_rca(sources))
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_fail_evidence_hash_stale_or_fabricated_on_mismatch():
    # The real file's CURRENT content hashes to something other than what
    # the agent claimed -- e.g. the file changed since the agent looked at
    # it, or the hash was never really computed from it at all.
    tmp = Path(tempfile.mkdtemp())
    try:
        sim_log = tmp / "sim.log"
        sim_log.write_text("UVM_ERROR ... FIFO_EMPTY at t=1000ns\n", encoding="utf-8")
        sources = _legacy_sources({
            "SIM_LOG": {"evidence_path": "sim.log", "evidence_hash": "deadbeef" * 8},
        })
        rc, out = _run_gate(tmp, _base_rca(sources))
        assert rc != 0
        assert out["reason"] == "EVIDENCE_HASH_STALE_OR_FABRICATED"
        assert out["source"] == "SIM_LOG"
        assert out["claimed_hash"] == "deadbeef" * 8
        assert out["actual_hash"] == hashlib.sha256(sim_log.read_bytes()).hexdigest()
    finally:
        shutil.rmtree(tmp)


def test_fail_evidence_path_not_found():
    tmp = Path(tempfile.mkdtemp())
    try:
        sources = _legacy_sources({
            "RTL": {"evidence_path": "rtl/does_not_exist.sv", "evidence_hash": "abc123"},
        })
        rc, out = _run_gate(tmp, _base_rca(sources))
        assert rc != 0
        assert out["reason"] == "EVIDENCE_PATH_NOT_FOUND"
        assert out["source"] == "RTL"
    finally:
        shutil.rmtree(tmp)


def test_still_fails_deep_rca_evidence_incomplete_with_evidence_path_present():
    # evidence_path hash checking must not weaken the pre-existing
    # completeness requirement -- dropping one required source is still
    # DEEP_RCA_EVIDENCE_INCOMPLETE even though the remaining sources use
    # real evidence_path/hash pairs.
    tmp = Path(tempfile.mkdtemp())
    try:
        sim_log = tmp / "sim.log"
        sim_log.write_text("content\n", encoding="utf-8")
        real_hash = hashlib.sha256(sim_log.read_bytes()).hexdigest()
        sources = _legacy_sources({
            "SIM_LOG": {"evidence_path": "sim.log", "evidence_hash": real_hash},
        })
        sources = [s for s in sources if s["source"] != "RTL"]
        rc, out = _run_gate(tmp, _base_rca(sources))
        assert rc != 0
        assert out["reason"] == "DEEP_RCA_EVIDENCE_INCOMPLETE"
        assert "RTL" in out["missing"]
    finally:
        shutil.rmtree(tmp)
