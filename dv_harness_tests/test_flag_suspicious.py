"""FLAG_SUSPICIOUS -- a real, third verb for a reviewer to mark ONE specific
already-produced gate result or evidence citation as suspicious/needing
re-verification (2026-09-07 gap closure, item id
"no-flag-suspicious-gate-result-verb").

Before this, the only two nearby mechanisms answered a different question:
CORRECT (`control_plane.ControlPlane.set_correction()`) resets a whole
STAGE, and COSIGN (`add_cosign()`) is opt-in AGREEMENT with a pending
`gates.JUDGMENT_FIELDS` value. Neither lets a reviewer express DOUBT about
one specific already-produced result without discarding the rest of the
stage's work, and COSIGN cannot target anything outside JUDGMENT_FIELDS at
all.

Every test here drives the REAL machinery: `ControlPlane.flag_suspicious()`/
`resolve_suspicious_flag()` persisted to a real `control.json` on disk,
`commands.cmd_flag_suspicious()`/`cmd_resolve_suspicious_flag()` through a
real `StateStore` (so the real event is really appended to
`events.jsonl`), and `evidence_provenance.summarize_evidence_blocks()`/
`control_plane.describe_stage()` -- the SAME shared read path the dashboard
and the CLI's explain/evidence/checklist verbs already go through -- to
prove a flag against one of `PROVENANCE_REQUIRED_GATES`' own results is
really surfaced there. Negative controls (missing required fields, an
unresolved flag, a RESOLVED flag no longer counting as OPEN, a flag against
a target this module's narrower convention does not recognise) are what
give the positive assertions detection power.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import control_plane as cpmod
from dv_harness import commands
from dv_harness import evidence_provenance as ep
from dv_harness.control_plane import ControlPlane, describe_stage
from dv_harness.storage import StateStore

ROOT = Path(__file__).resolve().parents[1]

VERIFY_GATE = "per_port_queue_starvation_gate"


def _clean_verify_payload() -> dict:
    """A payload the real per_port_queue_starvation_gate script passes on the
    merits, carrying no provenance field -- lifted verbatim from
    test_evidence_provenance.py's own _clean_payload() for this one gate, so
    this test's positive path is never accidentally riding on a shape
    failure."""
    return {
        "ports": [{"port_id": "p0", "independent_queue": True,
                   "max_wait_cycles": 100, "observed_wait_cycles": 10,
                   "forward_progress_evidence": "sim.log:441"}],
    }


def _blocks_text(blocks: dict) -> str:
    return "".join(f"```dv-harness-evidence:{gid}\n{json.dumps(p)}\n```\n"
                    for gid, p in blocks.items())


def _project(tmp_path: Path) -> Path:
    """A minimal project root carrying the real gate scripts, so
    describe_stage()'s real evaluate_stage_evidence_with_completion() call
    resolves `root / tools/verification_flow / <script>` for real -- the same
    pattern test_evidence_provenance.py's own _project() uses."""
    import shutil
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    shutil.copytree(ROOT / "tools" / "verification_flow",
                    root / "tools" / "verification_flow",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".dv-harness").mkdir()
    return root


class _FakeHarness:
    """The minimal `h` shape commands.py's cmd_* functions need: a real root
    and a real StateStore for h.store.event() -- no full DVHarness/engine
    construction required for a control-plane-only verb."""

    def __init__(self, root: Path):
        self.root = root
        self.store = StateStore(root)


# ---------------------------------------------------------------------------
# ControlPlane.flag_suspicious() / resolve_suspicious_flag() -- the store
# ---------------------------------------------------------------------------

def test_flag_suspicious_persists_a_real_open_record(tmp_path):
    cp = ControlPlane(tmp_path)
    entry = cp.flag_suspicious("VERIFY", "gate:per_port_queue_starvation_gate",
                                "the observed_wait_cycles looks copy-pasted from a sibling port",
                                flagged_by="reviewer_a", severity="HIGH")
    assert entry["status"] == cpmod.SUSPICION_STATUS_OPEN
    assert entry["severity"] == "HIGH"
    assert entry["flagged_by"] == "reviewer_a"
    assert entry["resolved_by"] is None and entry["resolved_at"] is None

    # Really persisted to disk, not just returned.
    on_disk = json.loads((tmp_path / ".dv-harness" / "control.json").read_text(encoding="utf-8"))
    stored = on_disk["suspicious_flags"]["VERIFY"]["gate:per_port_queue_starvation_gate"]
    assert stored == entry

    fetched = cp.get_suspicious_flag("VERIFY", "gate:per_port_queue_starvation_gate")
    assert fetched == entry


def test_flag_suspicious_default_severity_is_medium(tmp_path):
    cp = ControlPlane(tmp_path)
    entry = cp.flag_suspicious("VERIFY", "evidence:sim.log:441", "reason",
                                flagged_by="reviewer_a")
    assert entry["severity"] == "MEDIUM"


@pytest.mark.parametrize("kwargs,missing", [
    ({"target": "", "reason": "r", "flagged_by": "u"}, "target"),
    ({"target": "  ", "reason": "r", "flagged_by": "u"}, "target"),
    ({"target": "t", "reason": "", "flagged_by": "u"}, "reason"),
    ({"target": "t", "reason": "r", "flagged_by": ""}, "flagged_by"),
    ({"target": "t", "reason": "r", "flagged_by": None}, "flagged_by"),
])
def test_flag_suspicious_refuses_missing_required_fields(tmp_path, kwargs, missing):
    """Negative control: unlike a bare bookkeeping note, a suspicion flag
    with no target/reason/flagged_by is refused outright -- an unattributed,
    uncited doubt is not a real flag."""
    cp = ControlPlane(tmp_path)
    with pytest.raises(ValueError, match=missing):
        cp.flag_suspicious("VERIFY", **kwargs)


def test_flag_suspicious_refuses_an_unrecognized_severity(tmp_path):
    cp = ControlPlane(tmp_path)
    with pytest.raises(ValueError, match="severity"):
        cp.flag_suspicious("VERIFY", "gate:x", "reason", flagged_by="u",
                            severity="SUPER_URGENT")


def test_list_suspicious_flags_scoping_and_open_only_filter(tmp_path):
    cp = ControlPlane(tmp_path)
    cp.flag_suspicious("VERIFY", "gate:a", "r1", flagged_by="u1")
    cp.flag_suspicious("VERIFY", "gate:b", "r2", flagged_by="u1")
    cp.flag_suspicious("SIGNOFF", "gate:c", "r3", flagged_by="u2")
    cp.resolve_suspicious_flag("VERIFY", "gate:a", "checked, was correct after all")

    # Scoped to one stage, unfiltered: both flags still present.
    verify_all = cp.list_suspicious_flags("VERIFY")
    assert set(verify_all) == {"gate:a", "gate:b"}

    # Scoped to one stage, open_only: the resolved one drops out.
    verify_open = cp.list_suspicious_flags("VERIFY", open_only=True)
    assert set(verify_open) == {"gate:b"}

    # Unscoped, open_only: SIGNOFF's still-open flag survives, VERIFY's
    # resolved one does not, and a stage with only resolved flags reports an
    # empty dict rather than disappearing entirely.
    everything_open = cp.list_suspicious_flags(open_only=True)
    assert everything_open["VERIFY"] == {"gate:b": everything_open["VERIFY"]["gate:b"]}
    assert set(everything_open["SIGNOFF"]) == {"gate:c"}


def test_resolve_suspicious_flag_never_deletes_the_record(tmp_path):
    cp = ControlPlane(tmp_path)
    cp.flag_suspicious("VERIFY", "gate:a", "doubt this", flagged_by="reviewer_a")
    resolved = cp.resolve_suspicious_flag("VERIFY", "gate:a",
                                            "re-ran the check by hand, result stands",
                                            resolved_by="reviewer_b")
    assert resolved["status"] == cpmod.SUSPICION_STATUS_RESOLVED
    assert resolved["resolved_by"] == "reviewer_b"
    assert resolved["resolution_note"] == "re-ran the check by hand, result stands"
    # Still on file, not deleted.
    assert cp.get_suspicious_flag("VERIFY", "gate:a") == resolved


def test_resolve_suspicious_flag_requires_a_resolution_note(tmp_path):
    cp = ControlPlane(tmp_path)
    cp.flag_suspicious("VERIFY", "gate:a", "doubt this", flagged_by="reviewer_a")
    with pytest.raises(ValueError, match="resolution_note"):
        cp.resolve_suspicious_flag("VERIFY", "gate:a", "")


def test_resolve_suspicious_flag_refuses_a_target_never_flagged(tmp_path):
    cp = ControlPlane(tmp_path)
    with pytest.raises(ValueError, match="no suspicion flag on file"):
        cp.resolve_suspicious_flag("VERIFY", "gate:never-flagged", "note")


# ---------------------------------------------------------------------------
# Distinctness from CORRECT and COSIGN
# ---------------------------------------------------------------------------

def test_flag_suspicious_never_touches_corrections_or_cosigns(tmp_path):
    """A suspicion flag is neither a stage reset nor an agreement -- it must
    never appear as, or be confused with, a correction or a cosign record on
    the same control.json."""
    cp = ControlPlane(tmp_path)
    cp.flag_suspicious("VERIFY", "gate:per_port_queue_starvation_gate",
                        "doubt this", flagged_by="reviewer_a")
    data = cp.load()
    assert data.get("corrections", {}) == {}
    assert data.get("cosigns", {}) == {}
    assert cp.get_active_correction("VERIFY") is None
    assert cp.get_cosign("VERIFY", "gate:per_port_queue_starvation_gate") is None


def test_flag_suspicious_accepts_a_target_cosign_could_never_reach(tmp_path):
    """COSIGN is scoped only to gates.JUDGMENT_FIELDS locations (a
    "<gate_id>/<loc>" field path). FLAG_SUSPICIOUS accepts ANY citation
    string a reviewer chooses -- here, a bare evidence artifact path with no
    gate_id/loc shape at all."""
    cp = ControlPlane(tmp_path)
    entry = cp.flag_suspicious("VERIFY", "evidence:sim.log:441",
                                "this line does not match the FSDB timestamp",
                                flagged_by="reviewer_a")
    assert entry["target"] == "evidence:sim.log:441"


def test_flag_suspicious_does_not_reset_stage_attempts(tmp_path):
    """Negative control against CORRECT: cmd_correct() resets ss["attempts"]
    when reset_attempts=True and always calls replan_stage(); flag_suspicious
    must do neither -- it never even touches state.json."""
    root = _project(tmp_path)
    state_path = root / ".dv-harness" / "state.json"
    state_before = {"current_stage": "VERIFY",
                    "stages": {"VERIFY": {"status": "PARTIAL", "attempts": 3,
                                          "blocking_reason": "", "last_message": ""}}}
    state_path.write_text(json.dumps(state_before), encoding="utf-8")

    h = _FakeHarness(root)
    commands.cmd_flag_suspicious(h, "VERIFY", "gate:per_port_queue_starvation_gate",
                                   "doubt this", flagged_by="reviewer_a")

    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after == state_before


# ---------------------------------------------------------------------------
# commands.cmd_flag_suspicious() / cmd_resolve_suspicious_flag() -- the verb
# ---------------------------------------------------------------------------

def test_cmd_flag_suspicious_writes_a_real_audit_event(tmp_path):
    root = _project(tmp_path)
    h = _FakeHarness(root)
    result = commands.cmd_flag_suspicious(h, "VERIFY", "gate:per_port_queue_starvation_gate",
                                            "smells copy-pasted", flagged_by="reviewer_a",
                                            severity="HIGH")
    assert result["stage"] == "VERIFY"
    assert result["status"] == cpmod.SUSPICION_STATUS_OPEN

    events_path = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ev = next(e for e in lines if e.get("cmd") == "flag-suspicious")
    assert ev["stage"] == "VERIFY"
    assert ev["target"] == "gate:per_port_queue_starvation_gate"
    assert ev["severity"] == "HIGH"
    assert ev["flagged_by"] == "reviewer_a"


def test_cmd_resolve_suspicious_flag_writes_a_real_audit_event(tmp_path):
    root = _project(tmp_path)
    h = _FakeHarness(root)
    commands.cmd_flag_suspicious(h, "VERIFY", "gate:x", "doubt", flagged_by="reviewer_a")
    result = commands.cmd_resolve_suspicious_flag(h, "VERIFY", "gate:x",
                                                     "confirmed correct", resolved_by="reviewer_b")
    assert result["status"] == cpmod.SUSPICION_STATUS_RESOLVED

    events_path = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ev = next(e for e in lines if e.get("cmd") == "resolve-suspicious-flag")
    assert ev["target"] == "gate:x"
    assert ev["resolved_by"] == "reviewer_b"


def test_cmd_flag_suspicious_rejects_an_unknown_stage(tmp_path):
    root = _project(tmp_path)
    h = _FakeHarness(root)
    with pytest.raises(ValueError, match="Unknown stage"):
        commands.cmd_flag_suspicious(h, "NOT_A_REAL_STAGE", "gate:x", "reason",
                                       flagged_by="reviewer_a")


# ---------------------------------------------------------------------------
# evidence_provenance.py: a flag against a PROVENANCE_REQUIRED_GATES result
# is surfaced next to that gate's own self-attested/independently-derived
# caveat, not silently invisible.
# ---------------------------------------------------------------------------

def test_summarize_evidence_blocks_folds_in_an_open_flag():
    payload = dict(_clean_verify_payload(), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    blocks = {VERIFY_GATE: payload}
    flags = {ep.suspicion_target_for_gate(VERIFY_GATE): {
        "target": ep.suspicion_target_for_gate(VERIFY_GATE),
        "status": "OPEN", "reason": "doubtful", "severity": "HIGH",
    }}
    summary = ep.summarize_evidence_blocks(blocks, suspicious_flags=flags)
    entry = next(e for e in summary["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["flagged_suspicious"] is True
    assert entry["suspicion_flag"]["severity"] == "HIGH"
    assert summary["flagged_gate_ids"] == [VERIFY_GATE]
    assert summary["has_flagged_suspicious"] is True
    assert summary["suspicion_caveat"] == ep.SUSPICION_FLAG_CAVEAT


def test_summarize_evidence_blocks_with_no_flags_is_unchanged(tmp_path):
    """Negative control: omitting suspicious_flags (every pre-existing
    caller's call shape) leaves flagged_suspicious/has_flagged_suspicious
    honestly False and suspicion_caveat None -- no behaviour change for a
    caller that has not adopted this feature."""
    payload = dict(_clean_verify_payload(), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    summary = ep.summarize_evidence_blocks({VERIFY_GATE: payload})
    entry = next(e for e in summary["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["flagged_suspicious"] is False
    assert entry["suspicion_flag"] is None
    assert summary["has_flagged_suspicious"] is False
    assert summary["suspicion_caveat"] is None


def test_a_resolved_flag_no_longer_counts_as_flagged():
    """Negative control: only an OPEN flag caveats a claim -- a RESOLVED one
    (a human already re-checked and it stands) must not still read as
    suspicious."""
    payload = dict(_clean_verify_payload(), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    flags = {ep.suspicion_target_for_gate(VERIFY_GATE): {
        "target": ep.suspicion_target_for_gate(VERIFY_GATE),
        "status": "RESOLVED", "reason": "was fine", "severity": "LOW",
    }}
    summary = ep.summarize_evidence_blocks({VERIFY_GATE: payload}, suspicious_flags=flags)
    entry = next(e for e in summary["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["flagged_suspicious"] is False
    assert summary["has_flagged_suspicious"] is False


def test_a_flag_against_an_unrecognized_target_is_not_folded_in():
    """Negative control: this module's narrower convention only recognises
    "gate:<gate_id>" targets. A flag stored under a different target string
    (e.g. an evidence-citation path) is real and on file elsewhere
    (control_plane.describe_stage()'s own top-level suspicious_flags key
    still carries it), but it must not be silently matched to an unrelated
    gate's entry here."""
    payload = dict(_clean_verify_payload(), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    flags = {"evidence:sim.log:441": {"status": "OPEN", "reason": "x"}}
    summary = ep.summarize_evidence_blocks({VERIFY_GATE: payload}, suspicious_flags=flags)
    entry = next(e for e in summary["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["flagged_suspicious"] is False


# ---------------------------------------------------------------------------
# control_plane.describe_stage() -- the real shared read path
# ---------------------------------------------------------------------------

def _state_with_verify_evidence(root: Path) -> dict:
    payload = dict(_clean_verify_payload(), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    state = {
        "current_stage": "VERIFY",
        "stages": {"VERIFY": {"status": "PARTIAL", "attempts": 1,
                              "blocking_reason": "",
                              "last_message": _blocks_text({VERIFY_GATE: payload})}},
    }
    (root / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return state


def test_describe_stage_surfaces_an_open_flag_via_the_shared_read_path(tmp_path):
    root = _project(tmp_path)
    state = _state_with_verify_evidence(root)
    cp = ControlPlane(root)
    cp.flag_suspicious("VERIFY", ep.suspicion_target_for_gate(VERIFY_GATE),
                        "observed_wait_cycles looks fabricated", flagged_by="reviewer_a",
                        severity="CRITICAL")

    d = describe_stage(root, state, "VERIFY")

    # Folded into the provenance-specific view.
    prov = d["evidence_provenance"]
    assert prov["has_flagged_suspicious"] is True
    assert prov["flagged_gate_ids"] == [VERIFY_GATE]
    entry = next(e for e in prov["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["flagged_suspicious"] is True
    assert entry["suspicion_flag"]["severity"] == "CRITICAL"

    # Also present in the stage-wide top-level view (every flag on the
    # stage, regardless of whether it matches a PROVENANCE_REQUIRED_GATES
    # convention).
    assert ep.suspicion_target_for_gate(VERIFY_GATE) in d["suspicious_flags"]
    assert d["suspicious_flags"][ep.suspicion_target_for_gate(VERIFY_GATE)]["reason"] == \
        "observed_wait_cycles looks fabricated"


def test_describe_stage_with_no_flags_reports_none(tmp_path):
    """Negative control: a stage with no suspicion flags on file reports an
    empty top-level suspicious_flags dict and an unflagged provenance
    summary -- describe_stage() never fabricates a flag."""
    root = _project(tmp_path)
    state = _state_with_verify_evidence(root)
    d = describe_stage(root, state, "VERIFY")
    assert d["suspicious_flags"] == {}
    assert d["evidence_provenance"]["has_flagged_suspicious"] is False
    assert d["evidence_provenance"]["suspicion_caveat"] is None
