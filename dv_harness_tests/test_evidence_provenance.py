"""TH-9 -- self-attested vs. independently-derived gate evidence.

Everything here runs the REAL machinery: the real
`gates.evaluate_stage_evidence()` over the REAL shipped `STAGE_GATES` entries,
running the REAL gate scripts under `tools/verification_flow/` as
subprocesses, and the REAL consumers (`control_plane.describe_stage()`, the
REAL dashboard HTTP server, `signoff_export.read_signoff_stage_status()`).
Nothing is mocked, and no test writes a gate result by hand -- a test that
asserted against a hand-written detail dict would prove the assertion, not the
wiring.

The negative controls are what give these tests detection power. For every
"provenance is required" assertion there is a paired assertion that the SAME
payload, gates and scripts reach a real PASS once the field is declared; for
every "the artifact must exist" assertion there is a paired one with the file
really on disk. Nothing here runs a build, a regression or an LSF submission,
and no human-approval gate is touched.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from dv_harness import evidence_provenance as ep
from dv_harness.gates import (
    STAGE_GATES,
    evaluate_stage_evidence,
    extract_evidence_blocks,
    run_gate,
)

ROOT = Path(__file__).resolve().parents[1]

# One gate per stage family in the enforced set, so the stage-level tests
# exercise both a VERIFY gate and a SYSTEM_LEVEL one.
VERIFY_GATE = "per_port_queue_starvation_gate"
SYSTEM_GATE = "system_level_deadlock_livelock_gate"


def _clean_payload(gate_id: str) -> dict:
    """A payload that the gate's OWN script passes on the merits, carrying no
    provenance field. Verified below (test_clean_payloads_pass_on_the_merits)
    against the real scripts, so every provenance assertion is isolated to the
    provenance field and never accidentally riding on a shape failure."""
    return {
        "per_port_queue_starvation_gate": {
            "ports": [{"port_id": "p0", "independent_queue": True,
                       "max_wait_cycles": 100, "observed_wait_cycles": 10,
                       "forward_progress_evidence": "sim.log:441"}],
        },
        "multi_port_fairness_qos_gate": {
            "ports": [{"port_id": "p0", "min_service_share_percent": 10,
                       "observed_service_share_percent": 40,
                       "qos_enabled": False}],
        },
        "interrupt_storm_latency_gate": {
            "sources": [{"source_id": "irq0", "max_ack_latency_cycles": 100,
                         "observed_max_ack_latency_cycles": 12,
                         "storm_rate": None, "lost_interrupts": 0}],
        },
        "scoreboard_transaction_liveness_gate": {
            "missing_expected_transactions": 0, "missing_actual_transactions": 0,
            "duplicate_transactions": 0, "max_transaction_latency": 100,
            "observed_max_transaction_latency": 20,
        },
        "system_level_deadlock_livelock_gate": {
            "deadlock_detected": False, "livelock_detected": False,
            "forward_progress_assertions": ["fp_assert_grant"],
            "stress_scenario_evidence": ["stress-run-1"],
        },
        "system_level_resource_contention_gate": {
            "shared_resources": [],
            "scenarios": [{"scenario_id": "SC1", "resources": []}],
        },
    }[gate_id]


def _gate_spec(gate_id: str):
    for entries in STAGE_GATES.values():
        for gid, script, flag in entries:
            if gid == gate_id:
                return script, flag
    raise AssertionError(f"{gate_id} is not registered in STAGE_GATES")


def _run(gate_id: str, payload: dict, root: Path = ROOT):
    script, flag = _gate_spec(gate_id)
    return run_gate(root, script, flag, payload)


def _project(tmp_path: Path) -> Path:
    """A minimal project root carrying the real gate scripts, so run_gate()
    resolves `root / tools/verification_flow / <script>` for real."""
    import shutil
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    shutil.copytree(ROOT / "tools" / "verification_flow",
                    root / "tools" / "verification_flow",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".dv-harness").mkdir()
    return root


# ---------------------------------------------------------------------------
# The enforced set is principled, and every entry really runs
# ---------------------------------------------------------------------------

def test_every_provenance_required_gate_is_a_registered_stage_gate():
    ep.assert_required_gates_are_registered()


def test_the_audit_named_gates_are_all_enforced():
    """The three gates the completeness audit called out by name must be in
    the enforced set -- this is the gap the module exists to close, so it is
    asserted rather than left to be read out of the table."""
    for gate_id in ("system_level_deadlock_livelock_gate",
                    "system_level_resource_contention_gate",
                    "per_port_queue_starvation_gate"):
        assert ep.gate_requires_provenance(gate_id)


def test_every_enforced_gate_declares_the_claim_it_makes():
    for gate_id, claim in ep.PROVENANCE_REQUIRED_GATES.items():
        assert isinstance(claim, str) and len(claim.strip()) > 10, gate_id


def test_an_unenforced_gate_is_completely_untouched():
    """A gate outside the set must reach its script with the payload it always
    got, and must carry no provenance annotation -- stamping one would present
    a field nobody supplied and nobody checked as if it had been decided."""
    payload = {"classification": "ENV_ISSUE"}
    assert ep.check_payload(ROOT, "unknown_failure_escalation_gate", payload) is None
    gr = _run("unknown_failure_escalation_gate", payload)
    assert gr.ok
    assert ep.PROVENANCE_FIELD not in gr.detail


@pytest.mark.parametrize("gate_id", sorted(ep.PROVENANCE_REQUIRED_GATES))
def test_clean_payloads_pass_on_the_merits(gate_id):
    """Positive control for every provenance test below: with the honest
    provenance declared, each clean payload really reaches a PASS through the
    real script. Without this, a 'FAIL' assertion elsewhere could be a shape
    failure wearing a provenance failure's name."""
    payload = dict(_clean_payload(gate_id))
    payload[ep.PROVENANCE_FIELD] = ep.AGENT_SELF_ATTESTED
    gr = _run(gate_id, payload)
    assert gr.ok, gr.detail


# ---------------------------------------------------------------------------
# Enforcement: a headline claim with no declared producer is REJECTED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gate_id", sorted(ep.PROVENANCE_REQUIRED_GATES))
def test_missing_provenance_is_rejected_on_every_enforced_gate(gate_id):
    gr = _run(gate_id, _clean_payload(gate_id))
    assert not gr.ok
    assert gr.detail["reason"] == ep.REASON_MISSING
    # The refusal has to be actionable: it names the field, the accepted
    # values, and the claim the gate would otherwise have made.
    assert gr.detail["required_field"] == ep.PROVENANCE_FIELD
    assert set(gr.detail["accepted_values"]) == set(ep.PROVENANCE_VALUES)
    assert gr.detail["gate_claim"] == ep.PROVENANCE_REQUIRED_GATES[gate_id]


def test_deadlock_freedom_cannot_be_claimed_without_saying_who_derived_it():
    """The headline case, stated as its own test: an agent asserting
    'no deadlock, no livelock' with forward-progress assertions and stress
    evidence listed -- everything the pre-2026-09-06 gate asked for -- is now
    REFUSED until it states who produced that conclusion, and is ACCEPTED the
    moment it honestly says the agent did."""
    payload = _clean_payload(SYSTEM_GATE)
    refused = _run(SYSTEM_GATE, payload)
    assert not refused.ok and refused.detail["reason"] == ep.REASON_MISSING

    honest = dict(payload, **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    accepted = _run(SYSTEM_GATE, honest)
    assert accepted.ok
    assert accepted.detail[ep.PROVENANCE_FIELD] == ep.AGENT_SELF_ATTESTED
    assert accepted.detail["evidence_provenance_independently_derived"] is False
    assert accepted.detail["evidence_provenance_caveat"] == ep.SELF_ATTESTED_CAVEAT


def test_an_unrecognised_provenance_value_is_rejected():
    payload = dict(_clean_payload(VERIFY_GATE),
                   **{ep.PROVENANCE_FIELD: "VERIFIED"})
    gr = _run(VERIFY_GATE, payload)
    assert not gr.ok
    assert gr.detail["reason"] == ep.REASON_INVALID
    assert gr.detail["declared"] == "VERIFIED"


def test_an_empty_provenance_string_is_missing_not_invalid():
    """Distinct operator problems keep distinct reasons: '' means nobody
    filled it in, not that they filled in something wrong."""
    payload = dict(_clean_payload(VERIFY_GATE), **{ep.PROVENANCE_FIELD: "   "})
    gr = _run(VERIFY_GATE, payload)
    assert not gr.ok and gr.detail["reason"] == ep.REASON_MISSING


def test_a_non_object_payload_is_refused_with_its_own_reason():
    gr = _run(VERIFY_GATE, ["not", "an", "object"])
    assert not gr.ok and gr.detail["reason"] == ep.REASON_PAYLOAD_NOT_OBJECT


# ---------------------------------------------------------------------------
# The asymmetry: honesty is free, an independence claim costs a real artifact
# ---------------------------------------------------------------------------

def test_claiming_tool_derived_without_a_derivation_block_is_refused():
    payload = dict(_clean_payload(SYSTEM_GATE),
                   **{ep.PROVENANCE_FIELD: ep.TOOL_DERIVED})
    gr = _run(SYSTEM_GATE, payload)
    assert not gr.ok and gr.detail["reason"] == ep.REASON_DERIVATION_MISSING


def test_claiming_tool_derived_against_a_file_that_does_not_exist_is_refused():
    payload = dict(
        _clean_payload(SYSTEM_GATE),
        **{
            ep.PROVENANCE_FIELD: ep.TOOL_DERIVED,
            ep.DERIVATION_FIELD: {"tool": "jasper",
                                  "artifact_path": "reports/no_such_proof.log"},
        },
    )
    gr = _run(SYSTEM_GATE, payload)
    assert not gr.ok
    assert gr.detail["reason"] == ep.REASON_ARTIFACT_NOT_FOUND
    assert gr.detail["artifact_path"] == "reports/no_such_proof.log"


def test_a_real_artifact_on_disk_makes_the_independence_claim_acceptable(tmp_path):
    """The paired positive control for the two refusals above: the SAME
    payload, the same gate, the same script -- the only difference is that the
    cited artifact really exists under the project root."""
    root = _project(tmp_path)
    (root / "reports").mkdir()
    (root / "reports" / "deadlock_proof.log").write_text(
        "synthetic fixture: stands in for a real formal-proof report\n",
        encoding="utf-8")

    payload = dict(
        _clean_payload(SYSTEM_GATE),
        **{
            ep.PROVENANCE_FIELD: ep.SIMULATION_DERIVED,
            ep.DERIVATION_FIELD: {"tool": "vcs",
                                  "artifact_path": "reports/deadlock_proof.log"},
        },
    )
    missing_first = _run(SYSTEM_GATE, dict(payload, **{
        ep.DERIVATION_FIELD: {"tool": "vcs", "artifact_path": "reports/absent.log"}}),
        root=root)
    assert not missing_first.ok

    gr = _run(SYSTEM_GATE, payload, root=root)
    assert gr.ok, gr.detail
    assert gr.detail["evidence_provenance_independently_derived"] is True
    assert gr.detail["evidence_provenance_caveat"] == ep.DERIVED_CAVEAT


def test_the_artifact_is_resolved_under_the_project_root_not_the_cwd(tmp_path):
    """Path resolution is a real property: a relative artifact_path must be
    read against the project being judged. Proven by placing the file under a
    DIFFERENT root and asserting the claim is still refused."""
    root = _project(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "proof.log").write_text("x", encoding="utf-8")
    payload = dict(
        _clean_payload(SYSTEM_GATE),
        **{ep.PROVENANCE_FIELD: ep.TOOL_DERIVED,
           ep.DERIVATION_FIELD: {"tool": "t", "artifact_path": "proof.log"}},
    )
    assert not _run(SYSTEM_GATE, payload, root=root).ok
    (root / "proof.log").write_text("x", encoding="utf-8")
    assert _run(SYSTEM_GATE, payload, root=root).ok


def test_declaring_the_honest_value_needs_nothing_else():
    """The asymmetry stated as its own assertion: AGENT_SELF_ATTESTED is
    always accepted with no derivation block, so an agent is never pushed
    toward a stronger claim just to get a stage moving."""
    for gate_id in sorted(ep.PROVENANCE_REQUIRED_GATES):
        payload = dict(_clean_payload(gate_id),
                       **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
        assert ep.check_payload(ROOT, gate_id, payload) is None, gate_id


# ---------------------------------------------------------------------------
# The provenance field does not change what the underlying script decides
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gate_id", sorted(ep.PROVENANCE_REQUIRED_GATES))
def test_the_new_field_does_not_alter_the_scripts_own_verdict(gate_id):
    """Each enforced script must reach the SAME verdict on a genuinely bad
    payload whether or not provenance is declared -- provenance is an
    additional requirement, never a replacement for the shape checks."""
    bad = {
        "per_port_queue_starvation_gate": {"ports": [{"port_id": "p0", "independent_queue": False}]},
        "multi_port_fairness_qos_gate": {"ports": [{"port_id": "p0"}]},
        "interrupt_storm_latency_gate": {"sources": [{"source_id": "irq0"}]},
        "scoreboard_transaction_liveness_gate": {"missing_expected_transactions": 3},
        "system_level_deadlock_livelock_gate": {"deadlock_detected": True},
        "system_level_resource_contention_gate": {
            "shared_resources": ["DDR"],
            "scenarios": [{"scenario_id": "SC1", "resources": ["DDR"]}],
        },
    }[gate_id]
    with_prov = dict(bad, **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})
    gr = _run(gate_id, with_prov)
    assert not gr.ok
    # It failed on the SCRIPT's own reason, not on provenance.
    assert gr.detail["reason"] not in (
        ep.REASON_MISSING, ep.REASON_INVALID, ep.REASON_DERIVATION_MISSING,
        ep.REASON_ARTIFACT_NOT_FOUND, ep.REASON_PAYLOAD_NOT_OBJECT,
    ), gr.detail


# ---------------------------------------------------------------------------
# Stage level: the real evaluate_stage_evidence() over the real shipped gates
# ---------------------------------------------------------------------------

def _blocks_text(blocks: dict) -> str:
    return "".join(f"```dv-harness-evidence:{gid}\n{json.dumps(p)}\n```\n"
                   for gid, p in blocks.items())


def test_stage_evaluation_fails_when_a_headline_claim_declares_no_provenance(tmp_path):
    """Driven through the REAL evaluate_stage_evidence() over the REAL
    STAGE_GATES['SYSTEM_LEVEL'] list, with the real scripts on disk."""
    root = _project(tmp_path)
    text = _blocks_text({SYSTEM_GATE: _clean_payload(SYSTEM_GATE)})
    verdict, reasons = evaluate_stage_evidence(root, "SYSTEM_LEVEL", text)
    assert verdict == "GATE_FAIL"
    assert any(ep.REASON_MISSING in r for r in reasons)

    honest = _blocks_text({SYSTEM_GATE: dict(
        _clean_payload(SYSTEM_GATE), **{ep.PROVENANCE_FIELD: ep.AGENT_SELF_ATTESTED})})
    verdict2, reasons2 = evaluate_stage_evidence(root, "SYSTEM_LEVEL", honest)
    # Other SYSTEM_LEVEL gates still have no evidence block, so the stage is
    # still not a PASS -- but this gate's provenance failure is GONE, which is
    # the property under test.
    assert not any(ep.REASON_MISSING in r for r in reasons2)
    assert verdict2 == "GATE_FAIL"


# ---------------------------------------------------------------------------
# Consumers render the caveat
# ---------------------------------------------------------------------------

def _state_with_verify_evidence(root: Path, provenance) -> None:
    payload = dict(_clean_payload(VERIFY_GATE))
    if provenance is not None:
        payload[ep.PROVENANCE_FIELD] = provenance
        if provenance in ep.INDEPENDENTLY_DERIVED:
            (root / "sim.log").write_text("synthetic fixture sim log\n", encoding="utf-8")
            payload[ep.DERIVATION_FIELD] = {"tool": "vcs", "artifact_path": "sim.log"}
    state = {
        "current_stage": "VERIFY",
        "stages": {"VERIFY": {"status": "PARTIAL", "attempts": 1,
                              "blocking_reason": "",
                              "last_message": _blocks_text({VERIFY_GATE: payload})}},
    }
    (root / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")


def test_describe_stage_carries_the_self_attested_caveat(tmp_path):
    from dv_harness.control_plane import describe_stage

    root = _project(tmp_path)
    _state_with_verify_evidence(root, ep.AGENT_SELF_ATTESTED)
    state = json.loads((root / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
    d = describe_stage(root, state, "VERIFY")
    prov = d["evidence_provenance"]
    assert prov["has_self_attested_claims"] is True
    assert prov["caveat"] == ep.SELF_ATTESTED_CAVEAT
    entry = next(e for e in prov["entries"] if e["gate_id"] == VERIFY_GATE)
    assert entry["independently_derived"] is False
    assert entry["claim"] == ep.PROVENANCE_REQUIRED_GATES[VERIFY_GATE]


def test_describe_stage_does_not_caveat_a_derived_claim(tmp_path):
    """Negative control for the test above -- the same stage, the same gate,
    the same read path, with a real artifact on disk."""
    from dv_harness.control_plane import describe_stage

    root = _project(tmp_path)
    _state_with_verify_evidence(root, ep.SIMULATION_DERIVED)
    state = json.loads((root / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
    prov = describe_stage(root, state, "VERIFY")["evidence_provenance"]
    assert prov["has_self_attested_claims"] is False
    assert prov["caveat"] is None


def test_dashboard_renders_the_caveat_over_real_http(tmp_path):
    """The REAL dashboard server, over REAL HTTP: GET /api/state must carry
    the caveat for the current stage, and the page the browser really loads
    must contain the renderer that shows it in red. Uses the same
    _start_dashboard/_wait_ready/_get harness every other dashboard card test
    uses, so this card is proven the way the others are."""
    from dv_harness_tests.test_dashboard_interactive import (
        _free_port, _get, _start_dashboard, _wait_ready,
    )

    port = _free_port()
    root = _project(tmp_path)
    (root / ".dv-harness" / "config.json").write_text(
        json.dumps({"dashboard": {"host": "127.0.0.1", "port": port},
                    "policy": {"require_stage_gate_evidence": False,
                               "max_stage_retries": 0}}),
        encoding="utf-8")
    _state_with_verify_evidence(root, ep.AGENT_SELF_ATTESTED)

    base = f"http://127.0.0.1:{port}"
    _start_dashboard(root)
    _wait_ready(base)

    code, body = _get(base, "/api/state")
    assert code == 200
    prov = body["current_stage_detail"]["evidence_provenance"]
    assert prov["has_self_attested_claims"] is True
    assert prov["caveat"] == ep.SELF_ATTESTED_CAVEAT
    assert any(e["gate_id"] == VERIFY_GATE for e in prov["entries"])

    with urllib.request.urlopen(base + "/", timeout=10) as resp:
        page = resp.read().decode("utf-8")
    assert "provenanceBlock" in page
    assert "Evidence provenance (headline behaviour claims)" in page
    # Rendered with the existing bold+red .err treatment, not as an
    # easily-skimmed grey note.
    assert 'class="err"' in page


def test_signoff_stage_status_names_every_self_attested_claim(tmp_path):
    from dv_harness.signoff_export import read_signoff_stage_status

    root = _project(tmp_path)
    _state_with_verify_evidence(root, ep.AGENT_SELF_ATTESTED)
    status = read_signoff_stage_status(root)
    prov = status["evidence_provenance"]
    assert prov["available"] is True
    assert prov["has_self_attested_claims"] is True
    assert prov["caveat"] == ep.SELF_ATTESTED_CAVEAT
    claim = next(c for c in prov["self_attested_claims"] if c["gate_id"] == VERIFY_GATE)
    assert claim["stage"] == "VERIFY"
    assert claim[ep.PROVENANCE_FIELD] == ep.AGENT_SELF_ATTESTED

    lines = ep.render_caveat_lines(prov)
    assert lines and lines[0] == ep.SELF_ATTESTED_CAVEAT
    assert any(VERIFY_GATE in line for line in lines)


def test_signoff_stage_status_does_not_create_state_for_a_bare_project(tmp_path):
    """Asking who attested a project's evidence must never bring that
    project's governance state into existence."""
    from dv_harness.signoff_export import read_signoff_stage_status

    root = tmp_path / "bare"
    root.mkdir()
    status = read_signoff_stage_status(root)
    assert status["evidence_provenance"]["available"] is False
    assert status["evidence_provenance"]["reason"] == "NO_STATE_FILE"
    assert not (root / ".dv-harness").exists()


def test_reading_provenance_writes_nothing(tmp_path):
    """Byte-level snapshot: summarizing provenance is a pure read."""
    root = _project(tmp_path)
    _state_with_verify_evidence(root, ep.AGENT_SELF_ATTESTED)
    before = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    ep.summarize_project_provenance(root)
    ep.summarize_project_provenance(root)
    after = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    assert before == after


# ---------------------------------------------------------------------------
# Vocabulary / boundary guarantees
# ---------------------------------------------------------------------------

def test_provenance_vocabulary_shares_no_token_with_stage_verdicts():
    """A provenance value must never be readable as a DV verdict -- the same
    rule capability_evolution.py applies to its own vocabularies."""
    from dv_harness.models import Status

    assert not (set(ep.PROVENANCE_VALUES) & {s.value for s in Status})


def test_an_undeclared_provenance_is_never_treated_as_derived():
    assert ep.caveat_for(None) == ep.SELF_ATTESTED_CAVEAT
    assert ep.is_independently_derived(None) is False
    assert ep.is_independently_derived("SOMETHING_ELSE") is False


def test_the_module_authorizes_nothing():
    """It reports; it never approves, never routes and never submits. Asserted
    against the module's own source, with control_plane.py as the negative
    control proving the check has detection power."""
    src = (ROOT / "dv_harness" / "evidence_provenance.py").read_text(encoding="utf-8")
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "bsub", "run_stage("):
        assert forbidden not in src, forbidden
    control = (ROOT / "dv_harness" / "control_plane.py").read_text(encoding="utf-8")
    assert "ControlPlane" in control


def test_summarize_reports_nothing_for_a_stage_with_no_headline_claims():
    summary = ep.summarize_evidence_blocks(extract_evidence_blocks(
        '```dv-harness-evidence:unknown_failure_escalation_gate\n'
        '{"classification": "ENV_ISSUE"}\n```\n'))
    assert summary["entries"] == []
    assert summary["has_self_attested_claims"] is False
    assert ep.render_caveat_lines(summary) == []
