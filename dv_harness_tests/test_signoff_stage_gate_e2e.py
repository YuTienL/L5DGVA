"""End-to-end proof that the SIGNOFF stage gate battery can actually be
satisfied by a REAL engine.run_stage() transition -- and that the signoff
export bundle is gate-aware about it.

Why this file exists (2026-09-04 re-audit of mechanism #8, Qualification /
Signoff Engine). The audit found the SIGNOFF stage gate had never once been
satisfied anywhere in this repo:

  - every real `.dv-harness/state.json` showed SIGNOFF as NOT_STARTED (or
    carried no `stages` map at all),
  - `grep -c '"SIGNOFF"' <every events.jsonl>` returned 0 everywhere,
  - `.dv-harness/soc-composer/subsystem_environment_registry.json` -- written
    ONLY by engine._persist_subsystem_registry_entry() on a real SIGNOFF PASS
    -- did not exist,
  - `grep -rn 'run_stage(\\s*"SIGNOFF"' dv_harness_tests/*.py` returned zero
    matches, and test_engine_gates_and_routing.py's own
    test_engine_persists_subsystem_registry_entry_on_signoff_pass says so in
    its comment: it calls the private persistence method directly "rather
    than driving a full run_stage() SIGNOFF PASS, which would require
    constructing valid payloads for all 9 real SIGNOFF gates".

That is exactly what this file does. Every payload below was validated
against the real gate script under tools/verification_flow/, and the gates
run for real (subprocess, via gates.run_gate) -- nothing here is mocked
except the LLM adapter, which stands in for the agent that would author the
evidence blocks.

The second half proves the wiring the same audit found missing in the other
direction: signoff_export.collect_signoff_bundle() never looked at the
SIGNOFF stage gate at all, so a bundle produced for a project that never ran
a single SIGNOFF gate was indistinguishable from one produced after a real
signoff.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from dv_harness import signoff_export
from dv_harness.control_plane import ControlPlane
from dv_harness.engine import DVHarness
from dv_harness.gates import STAGE_GATES
from dv_harness.models import Status
from dv_harness.adapters.base import AgentResult

ROOT = Path(__file__).resolve().parents[1]

RUN_ID = "RUN-SIGNOFF-E2E-1"
RELEASE_HASH = "rel-hash-1"
PROMOTION_CHAIN_HASH = "promo-chain-1"
EVIDENCE_BUNDLE_HASH = "evbundle-1"
MANIFEST_HASH = "manifest-hash-1"
ATTESTATION_SIGNATURE = "sig-1"

# signoff_snapshot_immutability_gate.py recomputes this exact digest itself
# over exactly these five fields -- a hardcoded literal here would be a
# fabricated value the gate would reject, so it is derived the same way.
_SNAPSHOT_MATERIAL = {
    "release_hash": RELEASE_HASH,
    "promotion_chain_hash": PROMOTION_CHAIN_HASH,
    "evidence_bundle_hash": EVIDENCE_BUNDLE_HASH,
    "manifest_hash": MANIFEST_HASH,
    "attestation_signature": ATTESTATION_SIGNATURE,
}
SNAPSHOT_HASH = hashlib.sha256(
    json.dumps(_SNAPSHOT_MATERIAL, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()

# signoff_bundle_completeness_gate.py's REQUIRED_CLASSES, verbatim.
_BUNDLE_EVIDENCE_CLASSES = [
    "SPEC_TRACE", "BUILD", "TEST", "ASSERTION", "SCOREBOARD",
    "COVERAGE", "REGRESSION", "RCA_FIX", "ENV_FINGERPRINT",
]

SUBSYSTEM_ENTRY = {
    "name": "USB3_DEVICE",
    "environment_manifest": "generated/usb3_device/environment_manifest.json",
    "release_sha": RELEASE_HASH,
    "qualification_state": "PRODUCTION_QUALIFIED",
    "interface_compatibility": "PASS",
    "clock_reset_compatibility": "PASS",
}


def _fence(gate_id: str, payload: dict) -> str:
    return f"```dv-harness-evidence:{gate_id}\n{json.dumps(payload)}\n```\n"


def signoff_evidence_text(bundle_dir: Path, bundle_hash: str) -> str:
    """The full 9-gate SIGNOFF evidence an agent would have to author.

    `bundle_dir`/`bundle_hash` must come from a REAL
    signoff_export.collect_signoff_bundle() run: signoff_bundle_completeness_gate
    reads that directory's real manifest.json off disk and recomputes
    signoff_export.compute_bundle_hash() over it, rejecting any claimed hash
    that does not match. There is no way to satisfy that gate with an
    invented value.
    """
    return (
        _fence("false_pass_resistance_gate", {
            "positive_test_pass": True,
            "negative_test_detects_fault": True,
            "checker_detects_injected_fault": True,
            "semantic_log_match": True,
            "oracle_independent": True,
            "proof_bundle_hash": "false-pass-proof-1",
        })
        + _fence("signoff_bundle_completeness_gate", {
            "final_verdict": "PASS",
            "bundle_hash": bundle_hash,
            "bundle_dir": str(bundle_dir),
            "evidence": [{"class": c, "hash": f"h-{c.lower()}"} for c in _BUNDLE_EVIDENCE_CLASSES],
        })
        + _fence("evidence_bundle_run_consistency_gate", {
            "run_id": RUN_ID,
            "bundle_hash": EVIDENCE_BUNDLE_HASH,
            "evidence": [
                {"evidence_id": f"EV-{c}", "run_id": RUN_ID, "hash": f"h-{c.lower()}"}
                for c in _BUNDLE_EVIDENCE_CLASSES
            ],
        })
        + _fence("evidence_freshness_gate", {
            "current": {"rtl_hash": "rtl-1", "build_hash": "build-1", "spec_revision": "spec-1"},
            "items": [{
                "evidence_id": "EV-SPEC_TRACE", "rtl_hash": "rtl-1", "build_hash": "build-1",
                "spec_revision": "spec-1", "evidence_hash": "h-spec_trace",
            }],
        })
        + _fence("release_attestation_gate", {
            "release_id": "REL-1", "release_hash": RELEASE_HASH,
            "promotion_chain_hash": PROMOTION_CHAIN_HASH,
            "evidence_bundle_hash": EVIDENCE_BUNDLE_HASH,
            "attested_by": "dv-lead", "attested_at": "2026-09-04T00:00:00Z",
            "attestation_signature": ATTESTATION_SIGNATURE,
        })
        + _fence("signoff_snapshot_immutability_gate", dict(
            _SNAPSHOT_MATERIAL, snapshot_hash=SNAPSHOT_HASH,
            post_signoff_mutation_detected=False))
        + _fence("signoff_trace_crosscheck_gate", {
            "snapshot_hash": SNAPSHOT_HASH,
            "trace_chain_hash": "trace-1",
            "coverage_state_hash": "cov-1",
            "result_bundle_hash": "result-1",
            "rca_bundle_hash": "rca-1",
            "evidence_bundle_hash": EVIDENCE_BUNDLE_HASH,
            "snapshot_references": {
                "trace_chain_hash": "trace-1",
                "coverage_state_hash": "cov-1",
                "result_bundle_hash": "result-1",
                "rca_bundle_hash": "rca-1",
                "evidence_bundle_hash": EVIDENCE_BUNDLE_HASH,
            },
            "active_failure_count": 0,
        })
        + _fence("verification_verdict_consistency_gate", {
            "final_verdict": "PASS", "simulation_status": "PASS",
            "semantic_status": "TRUE_PASS", "checker_status": "PASS",
            "active_failure_ids": [], "signoff_credit_allowed": True,
        })
        + _fence("subsystem_environment_registration_gate", SUBSYSTEM_ENTRY)
    )


class _PassAdapter:
    def __init__(self, text: str):
        self.text = text

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        return AgentResult(ok=True, text=self.text, raw={}, session_id=None)


def _signoff_project():
    """A project root a real SIGNOFF run_stage() can execute in: its own copy
    of tools/ (gates.run_gate resolves `root/tools/verification_flow/<script>`,
    and self_audit.run_self_audit -- which the signoff bundle always runs --
    resolves gate scripts the same way) and the real shipped graph."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    shutil.copy(ROOT / ".dv-harness" / "graph" / "main_graph.json",
                tmp / ".dv-harness" / "graph" / "main_graph.json")
    return tmp


def _drive_signoff(tmp: Path, approve: bool = True) -> DVHarness:
    """Drive ONE real run_stage("SIGNOFF") whose 9 gates all pass.

    `approve=False` is the same run with no `dv-harness approve SIGNOFF` on
    record -- the case run_stage() holds at WAIT_USER. Everything else
    (evidence, gates, subprocesses) is identical, which is what makes the
    pair of tests below a controlled comparison of the human-approval
    hard-stop alone.
    """
    h = DVHarness(tmp)
    # The bundle the SIGNOFF gate battery itself consumes: produced BEFORE
    # the stage passes, which is why collect_signoff_bundle cannot require a
    # SIGNOFF PASS by default (see signoff_export's module docstring).
    pre = signoff_export.collect_signoff_bundle(tmp, tmp / "signoff_gate_input")
    assert pre["status"] == "OK"
    assert pre["bundle_kind"] == "PRE_SIGNOFF_GATE_INPUT"

    h.set_stage("SIGNOFF")
    # SIGNOFF is one of the stages run_stage() holds at WAIT_USER without a
    # real human approval on record, regardless of gate verdict.
    if approve:
        ControlPlane(tmp).approve("SIGNOFF", note="e2e signoff", reviewer_id="dv-lead")
    h.adapter = _PassAdapter(signoff_evidence_text(Path(pre["out_dir"]), pre["bundle_hash"]))
    h.run_stage("sign off the USB3 device subsystem environment")
    return h


def _drive_signoff_to_pass(tmp: Path) -> DVHarness:
    return _drive_signoff(tmp, approve=True)


def test_run_stage_signoff_passes_all_nine_real_gates_end_to_end():
    tmp = _signoff_project()
    try:
        h = _drive_signoff_to_pass(tmp)

        # 1. The stage really closed PASS -- the state every real state.json
        #    in this repo showed as NOT_STARTED before this test existed.
        assert h.state.stages["SIGNOFF"]["status"] == Status.PASS.value, \
            h.state.stages["SIGNOFF"].get("blocking_reason")
        on_disk = json.loads((tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert on_disk["stages"]["SIGNOFF"]["status"] == Status.PASS.value

        # 2. All 9 gates really are the ones that ran -- guards against this
        #    test silently going stale if STAGE_GATES["SIGNOFF"] grows a gate
        #    this evidence text does not answer.
        submitted = set(h.state.stages["SIGNOFF"]["last_evidence_blocks"])
        assert {gid for gid, _, _ in STAGE_GATES["SIGNOFF"]} <= submitted

        # 3. The subsystem registry file -- written ONLY on a real SIGNOFF
        #    PASS -- now exists, with this run's real entry in it.
        reg = json.loads((tmp / ".dv-harness" / "soc-composer"
                          / "subsystem_environment_registry.json").read_text(encoding="utf-8"))
        assert [s["name"] for s in reg["subsystems"]] == ["USB3_DEVICE"]
        assert reg["subsystems"][0]["qualification_state"] == "PRODUCTION_QUALIFIED"

        # 4. A real SIGNOFF record reached the audit trail.
        events = [json.loads(line) for line in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        signoff_events = [e for e in events if e.get("stage") == "SIGNOFF"]
        assert signoff_events
        assert any(e.get("event") == "SUBSYSTEM_ENVIRONMENT_REGISTERED" for e in signoff_events)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_gates_passing_without_human_approval_qualifies_nothing():
    """The human-approval hard-stop must govern the DURABLE qualification
    artifacts, not just the stage status (2026-09-04, mechanism #8 re-audit
    follow-up).

    run_stage() deliberately downgrades a fully gate-verified SIGNOFF to
    WAIT_USER when no `dv-harness approve SIGNOFF` is on record ("gates
    passing is not the same thing as a human sign-off", engine.py's own
    comment). But the whole `if verdict == "PASS":` side-effect block runs on
    GATE VERDICT ALONE, after that downgrade. _export_signoff_bundle()
    re-checks the recorded stage status for exactly this reason and
    documents why; its sibling _persist_subsystem_registry_entry() -- the
    ONLY writer of the runtime subsystem registry -- did not, so a subsystem
    was recorded PRODUCTION_QUALIFIED in the real registry while its signoff
    was still waiting on a human.

    That registry is not a log. environment_mode_router.
    read_registered_subsystem_entries() feeds it to
    soc_environment_composer.compose_soc_environment(), STAGE_GATES
    ["SYSTEM_LEVEL"]'s system_level_validator cross-checks agent claims
    against it via its --registered ContextFlag, and
    signoff_export.read_signoff_stage_status() reports its mere presence as
    "independent corroboration" of a real SIGNOFF PASS -- so an
    unapproved entry there is a false corroboration of the very approval it
    skipped.
    """
    tmp = _signoff_project()
    try:
        h = _drive_signoff(tmp, approve=False)

        # 1. The gates really did all pass -- this is the same evidence the
        #    approved run uses, so the ONLY difference is the missing human.
        submitted = set(h.state.stages["SIGNOFF"]["last_evidence_blocks"])
        assert {gid for gid, _, _ in STAGE_GATES["SIGNOFF"]} <= submitted

        # 2. ...and the stage still correctly refused to close.
        assert h.state.stages["SIGNOFF"]["status"] == Status.WAIT_USER.value
        assert "HUMAN_APPROVAL_REQUIRED" in h.state.stages["SIGNOFF"]["blocking_reason"]

        # 3. Nothing durable was qualified: no registry file at all.
        assert not (tmp / ".dv-harness" / "soc-composer"
                    / "subsystem_environment_registry.json").exists()
        # ...which is also what signoff_export reports about the project.
        status = signoff_export.read_signoff_stage_status(tmp)
        assert status["stage_status"] == Status.WAIT_USER.value
        assert status["gate_verified"] is False
        assert status["subsystem_registry_present"] is False
        # ...and no SYSTEM_LEVEL composition can be built from it.
        from dv_harness.environment_mode_router import read_registered_subsystem_entries
        assert read_registered_subsystem_entries(tmp) == []

        # 4. No bundle either (this half already held before the fix).
        assert not (tmp / ".dv-harness" / "signoff_bundle").exists()

        # 5. The audit trail must not claim a registration happened, and the
        #    blackboard must not carry one for a later stage to read.
        events = [json.loads(line) for line in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        assert not [e for e in events
                    if e.get("event") in ("SUBSYSTEM_ENVIRONMENT_REGISTERED",
                                          "SIGNOFF_BUNDLE_EXPORTED")]
        assert h.blackboard.read("subsystem_registry") is None

        # 6. The hold is not permanent: the same evidence, once a human
        #    really approves, does register. (Proves the guard blocks the
        #    unapproved case specifically, not the mechanism as a whole.)
        ControlPlane(tmp).approve("SIGNOFF", note="late approval", reviewer_id="dv-lead")
        h2 = DVHarness(tmp)
        h2.set_stage("SIGNOFF")
        pre = signoff_export.collect_signoff_bundle(tmp, tmp / "signoff_gate_input_2")
        h2.adapter = _PassAdapter(signoff_evidence_text(Path(pre["out_dir"]), pre["bundle_hash"]))
        h2.run_stage("sign off the USB3 device subsystem environment")
        assert h2.state.stages["SIGNOFF"]["status"] == Status.PASS.value, \
            h2.state.stages["SIGNOFF"].get("blocking_reason")
        reg = json.loads((tmp / ".dv-harness" / "soc-composer"
                          / "subsystem_environment_registry.json").read_text(encoding="utf-8"))
        assert [s["name"] for s in reg["subsystems"]] == ["USB3_DEVICE"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_pass_exports_a_gate_verified_bundle_on_the_real_path():
    """engine._export_signoff_bundle is the real production-path caller of
    signoff_export.collect_signoff_bundle(). Before it existed, the module's
    only callers were the `signoff-export` CLI and the dashboard button, both
    of which bypass STAGE_GATES["SIGNOFF"] entirely -- no bundle anywhere was
    ever the consequence of a gate-verified signoff."""
    tmp = _signoff_project()
    try:
        _drive_signoff_to_pass(tmp)

        bundle_dir = tmp / ".dv-harness" / "signoff_bundle"
        manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["bundle_kind"] == "SIGNOFF_GATE_VERIFIED"
        assert manifest["signoff_stage"]["gate_verified"] is True
        assert manifest["signoff_stage"]["stage_status"] == "PASS"
        # Independent corroboration recorded in the bundle itself: the file
        # only a real SIGNOFF PASS ever writes.
        assert manifest["signoff_stage"]["subsystem_registry_present"] is True
        assert manifest["signoff_stage"]["signoff_event_count"] > 0

        # The same fact is a real file inside the bundle, for a reader who
        # only ever opens the directory.
        stamped = json.loads((bundle_dir / "signoff_stage_status.json").read_text(encoding="utf-8"))
        assert stamped == manifest["signoff_stage"]

        events = [json.loads(line) for line in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        exported = [e for e in events if e.get("event") == "SIGNOFF_BUNDLE_EXPORTED"]
        assert exported and exported[-1]["bundle_kind"] == "SIGNOFF_GATE_VERIFIED"
        assert exported[-1]["out_dir"] == str(bundle_dir.resolve())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_require_signoff_pass_refuses_before_the_gate_and_allows_after():
    """The audit's named bypass condition, both halves: `signoff-export` run
    against a project whose SIGNOFF never started produced an OK-looking
    bundle. Under --require-signoff-pass that is now a refusal that writes
    nothing, and it stops being a refusal exactly when the real stage gate
    passes -- not one moment earlier."""
    tmp = _signoff_project()
    try:
        h = DVHarness(tmp)  # creates a real state.json: SIGNOFF NOT_STARTED
        assert h.state.stages["SIGNOFF"]["status"] == Status.NOT_STARTED.value

        refused_dir = tmp / "refused_out"
        refused = signoff_export.collect_signoff_bundle(
            tmp, refused_dir, require_signoff_pass=True)
        assert refused["status"] == "REFUSED"
        assert refused["reason"] == "SIGNOFF_STAGE_NOT_PASSED"
        assert refused["signoff_stage"]["stage_status"] == "NOT_STARTED"
        assert refused["signoff_stage"]["gate_verified"] is False
        # A refusal writes NOTHING -- not even an empty directory a later
        # reader could mistake for a partial bundle.
        assert not refused_dir.exists()

        _drive_signoff_to_pass(tmp)

        allowed_dir = tmp / "allowed_out"
        allowed = signoff_export.collect_signoff_bundle(
            tmp, allowed_dir, require_signoff_pass=True)
        assert allowed["status"] == "OK"
        assert allowed["bundle_kind"] == "SIGNOFF_GATE_VERIFIED"
        assert (allowed_dir / "manifest.json").is_file()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_signoff_stage_status_never_creates_state_and_reports_absence_honestly():
    """A project with no state.json at all must report NOT_RECORDED, kept
    distinct from a recorded NOT_STARTED -- and reading it must not mint a
    state.json as a side effect (which storage.StateStore.load() would)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        status = signoff_export.read_signoff_stage_status(tmp)
        assert status["state_file_present"] is False
        assert status["stage_status"] == signoff_export.SIGNOFF_STATUS_NOT_RECORDED
        assert status["gate_verified"] is False
        assert status["subsystem_registry_present"] is False
        assert status["signoff_event_count"] == 0
        assert status["required_signoff_gates"] == [gid for gid, _, _ in STAGE_GATES["SIGNOFF"]]
        assert not (tmp / ".dv-harness" / "state.json").exists()

        # A state.json with no `stages` map at all (a real shape found in
        # this repo at .work/_e2e_demo_usb3_lfps/) is also NOT_RECORDED, not
        # NOT_STARTED -- "never recorded" and "recorded as not started" are
        # different facts.
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        (tmp / ".dv-harness" / "state.json").write_text(
            json.dumps({"current_stage": "RE_AUDIT", "project": "demo",
                        "overall_status": "PASS"}), encoding="utf-8")
        stub = signoff_export.read_signoff_stage_status(tmp)
        assert stub["state_file_present"] is True
        assert stub["current_stage"] == "RE_AUDIT"
        assert stub["stage_status"] == signoff_export.SIGNOFF_STATUS_NOT_RECORDED
        assert stub["gate_verified"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
