"""Proves mechanism #14 (Subsystem -> System-Level/SoC verification
generation) is wired into the REAL paths, through the REAL entry points --
which is precisely what was never proven before (2026-09-04 re-audit).

Two entry points, two halves of this file:

A. `DVHarness.run_stage("SYSTEM_LEVEL")` -- the real engine loop. The
   pre-existing regression test for the composer
   (test_engine_gates_and_routing.py::
   test_engine_composes_soc_environment_on_system_level_pass) called the
   PRIVATE `_compose_soc_environment_files()` directly and said so, because
   "driving a genuine end-to-end SYSTEM_LEVEL PASS would require
   constructing valid payloads for every real SYSTEM_LEVEL gate unrelated to
   this feature". So the chain gate evidence -> gates.py verdict -> PASS
   branch -> compose_soc_environment -> blackboard -> event log had never
   been executed end to end by anything, and this project's own
   .dv-harness/events.jsonl has zero SOC_ENVIRONMENT_COMPOSED records. This
   file constructs those payloads (all 14, from prompts.py's own documented
   SYSTEM_LEVEL evidence shapes) and drives the real thing.

B. `create_environment()` -- the CREATE ENVIRONMENT entry point
   tools/generate_protocol_uvm_environment.py and every
   .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md invoke. Before 2026-09-04 it
   called ProtocolEnvGenerator unconditionally, so
   resolve_environment_mode()'s SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE decision
   reached the prompt and nothing else.

Nothing here mocks a gate, a gate verdict, or the registry: the gate scripts
are the real ones copied onto the temp project, and the registry is written
by the real engine.py writer, not hand-authored onto disk.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dv_harness.models import Status

ROOT = Path(__file__).resolve().parents[1]

# The two subsystems every fixture below composes. Same six fields
# tools/real_env/system_level_validator.py's REQUIRED list demands and
# subsystem_environment_registration_gate.py validates before a real entry is
# ever persisted.
_USB = {"name": "USB", "environment_manifest": "generated/usb/environment_manifest.json",
        "release_sha": "sha-usb-1", "qualification_state": "PRODUCTION_QUALIFIED",
        "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
_PCIE = {"name": "PCIE", "environment_manifest": "generated/pcie/environment_manifest.json",
         "release_sha": "sha-pcie-1", "qualification_state": "REGRESSION_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}

# Every gate script gates.STAGE_GATES["SYSTEM_LEVEL"] registers, plus the
# cross-directory system_level_validator. Copied onto the temp project root
# because gates.run_gate() resolves each script as `root / TOOLS_DIR /
# script_name` -- these are the real scripts, not stubs.
_GATE_SCRIPTS = [
    "verification_flow/system_level_subsystem_verdict_gate.py",
    "verification_flow/system_level_traceability_gate.py",
    "verification_flow/system_level_subsystem_set_completeness_gate.py",
    "verification_flow/cross_domain_evidence_bundle_gate.py",
    "verification_flow/cross_protocol_scenario_gate.py",
    "verification_flow/system_level_change_impact_gate.py",
    "verification_flow/system_level_composition_gate.py",
    "verification_flow/system_level_cross_domain_gate.py",
    "verification_flow/system_level_deadlock_livelock_gate.py",
    "verification_flow/system_level_dependency_graph_gate.py",
    "verification_flow/system_level_release_evidence_consistency_gate.py",
    "verification_flow/system_level_release_pinning_gate.py",
    "verification_flow/system_level_resource_contention_gate.py",
    "real_env/system_level_validator.py",
]


def _fresh_project():
    """A DVHarness rooted at a fresh temp dir with the real shipped graph and
    the real SYSTEM_LEVEL gate scripts in place."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    for rel in _GATE_SCRIPTS:
        dest = tmp / "tools" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "tools" / rel, dest)
    return tmp, DVHarness(tmp)


def _register_subsystems(h, entries):
    """Seeds the REAL runtime subsystem registry through the REAL production
    writer -- engine.py's _persist_subsystem_registry_entry(), the only thing
    that ever writes that file, called with the SIGNOFF stage whose
    STAGE_GATES really do include subsystem_environment_registration_gate.
    Deliberately not a hand-written JSON file: the point of these tests is
    that the composition's inputs came from the harness's own registration
    path, exactly as system_level_validator's --registered cross-check
    assumes.

    The SIGNOFF status is set to PASS first because that is the writer's
    real precondition: it persists only for a SIGNOFF that actually closed,
    never for one still held at WAIT_USER awaiting `dv-harness approve
    SIGNOFF` (see engine._persist_subsystem_registry_entry's HUMAN-APPROVAL
    HARD-STOP note). Seeding through the production writer means inheriting
    its production precondition too."""
    h.state.stages["SIGNOFF"]["status"] = Status.PASS.value
    for entry in entries:
        h._persist_subsystem_registry_entry(
            "SIGNOFF", {"subsystem_environment_registration_gate": dict(entry)})


def _system_level_evidence(subsystems, soc_name="demo_soc"):
    """One agent reply carrying a valid evidence block for all 14 real
    SYSTEM_LEVEL gates. Every payload shape is transcribed from
    dv_harness/prompts.py's own STAGE_INSTRUCTIONS[SYSTEM_LEVEL] examples --
    the same instructions a real agent is given -- not invented here."""
    names = [s["name"] for s in subsystems]
    a, b = names[0], names[1]
    blocks = {
        "system_level_subsystem_verdict_gate": {
            "system_verdict": "PASS",
            "subsystems": [{"name": n, "verdict": "PASS", "isolated": False,
                            "approved_waiver_id": None} for n in names],
        },
        "system_level_traceability_gate": {
            "selected_subsystems": names,
            "system_requirement_ids": ["SR1"],
            "scenarios": [{"scenario_id": "SC1", "participating_subsystems": names,
                           "system_requirement_ids": ["SR1"], "mechanism_ids": ["M1"],
                           "coverage_ids": ["CV1"]}],
        },
        # The multi-flag gate: its ONE fence body is a dict of sub-payloads
        # keyed by EvidenceFlag key ("registry"). engine.py's
        # _compose_soc_environment_files() reuses that same dict as the
        # composition manifest, so soc_name rides along in it.
        "system_level_validator": {
            "registry": {"soc_name": soc_name, "subsystems": subsystems},
        },
        "system_level_subsystem_set_completeness_gate": {
            "required_subsystems": names,
            "selected_subsystems": names,
            "subsystem_waivers": [],
            "subsystem_scenario_participation": [
                {"scenario_id": "SC1", "participating_subsystems": names}],
        },
        "cross_protocol_scenario_gate": {
            "scenarios": [{"scenario_id": "SC1", "protocols": names,
                           "requirement_ids": ["SR1"], "mechanism_ids": ["M1"],
                           "coverage_ids": ["CV1"], "evidence": ["ev1"],
                           "interaction_point": "shared APB register window"}],
        },
        "cross_domain_evidence_bundle_gate": {
            "scenarios": [{"scenario_id": "SC1", "domains": ["SHARED_RESOURCE", "INTERRUPT"],
                           "contention_evidence": "ev-contention",
                           "interrupt_evidence": "ev-irq",
                           "evidence_bundle_hash": "bundle-h1",
                           "subsystem_release_snapshot_hash": "snap-h1"}],
        },
        "system_level_cross_domain_gate": {
            "scenarios": [{"scenario_id": "SC1", "domains": ["SHARED_RESOURCE", "RESET"],
                           "contention_policy": "round-robin on the shared APB bus",
                           "recovery_or_reinit_check": "post-reset re-enumeration checked",
                           "evidence": "ev-cross-domain"}],
        },
        "system_level_composition_gate": {
            "selected_subsystems": subsystems,
            "system_level_scenarios": [
                {"scenario_id": "SC1", "participating_subsystems": names}],
        },
        "system_level_release_pinning_gate": {
            "selected_subsystems": [
                {"name": s["name"], "release_sha": s["release_sha"],
                 "environment_manifest_hash": f"mh-{s['name']}",
                 "qualification_evidence_hash": f"qh-{s['name']}"} for s in subsystems],
            "composition_hash": "comp-h1",
        },
        "system_level_release_evidence_consistency_gate": {
            "subsystems": [
                {"subsystem": s["name"], "release_sha": s["release_sha"],
                 "manifest_hash": f"mh-{s['name']}",
                 "qualification_evidence_hash": f"qh-{s['name']}"} for s in subsystems],
            "scenarios": [{"scenario_id": "SC1", "participating_subsystems": names,
                           "release_snapshot": {s["name"]: s["release_sha"] for s in subsystems},
                           "evidence_bundle_hash": "bundle-h1"}],
        },
        "system_level_change_impact_gate": {
            "changed_subsystems": [a],
            "selected_subsystems": names,
            "system_scenarios": [{"scenario_id": "SC1", "participating_subsystems": names}],
            "rerun_scenarios": ["SC1"],
        },
        "system_level_dependency_graph_gate": {
            "subsystems": names,
            "dependencies": [{"from": a, "to": b}],
        },
        # evidence_provenance (2026-09-06, TH-9): these two gates assert
        # dynamic system BEHAVIOUR (deadlock/livelock freedom, contention
        # arbitration) from numbers written here by hand, so
        # gates.run_gate() now requires each to declare who produced them.
        # AGENT_SELF_ATTESTED is the honest value for a hand-written fixture
        # and is exactly what a real agent typing these numbers must declare.
        "system_level_deadlock_livelock_gate": {
            "evidence_provenance": "AGENT_SELF_ATTESTED",
            "deadlock_detected": False, "livelock_detected": False,
            "forward_progress_assertions": ["fp_assert_apb_grant"],
            "stress_scenario_evidence": ["stress-run-1"],
        },
        "system_level_resource_contention_gate": {
            "evidence_provenance": "AGENT_SELF_ATTESTED",
            "shared_resources": ["APB_BUS"],
            "scenarios": [{"scenario_id": "SC1", "resources": ["APB_BUS"],
                           "arbitration_or_contention_policy": "round-robin",
                           "contention_testcase_ids": ["tc_contend_1"]}],
        },
    }
    return "".join(
        f"```dv-harness-evidence:{gid}\n{json.dumps(payload)}\n```\n"
        for gid, payload in blocks.items())


class _ReplyAdapter:
    def __init__(self, text):
        self.text = text

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        return AgentResult(ok=True, text=self.text, raw={}, session_id=None)


# --------------------------------------------------------------------------
# A. The real engine entry point: DVHarness.run_stage("SYSTEM_LEVEL")
# --------------------------------------------------------------------------

def test_real_run_stage_system_level_pass_composes_soc_environment():
    """The end-to-end firing that had never happened: a real
    run_stage("SYSTEM_LEVEL") through all 14 real gate scripts to a real
    PASS, which composes a real SoC environment on disk and emits a real
    SOC_ENVIRONMENT_COMPOSED event."""
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB, _PCIE])
        h.set_stage("SYSTEM_LEVEL")
        h.adapter = _ReplyAdapter(_system_level_evidence([_USB, _PCIE]))
        h.run_stage("compose the USB+PCIe system-level environment")

        assert h.state.stages["SYSTEM_LEVEL"]["status"] == Status.PASS.value, \
            h.state.stages["SYSTEM_LEVEL"]

        # Real generated content, at the real path.
        out_dir = tmp / "generated" / "soc_composition" / "demo_soc"
        tb = (out_dir / "soc_tb_top.sv").read_text(encoding="utf-8")
        assert "usb_env usb_env_inst;" in tb
        assert "pcie_env pcie_env_inst;" in tb
        vseqr = (out_dir / "soc_virtual_sequencer.sv").read_text(encoding="utf-8")
        assert "usb_virtual_sequencer usb_vseqr;" in vseqr
        assert "pcie_virtual_sequencer pcie_vseqr;" in vseqr
        composed = json.loads((out_dir / "soc_composition_manifest.json").read_text(encoding="utf-8"))
        assert composed["composed_subsystems"] == ["USB", "PCIE"]
        assert composed["composition_status"] == "SOC_TB_COMPOSED"

        # The real event log -- the exact record this project's own
        # events.jsonl has never contained.
        events = [json.loads(line) for line in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        composed_events = [e for e in events if e.get("event") == "SOC_ENVIRONMENT_COMPOSED"]
        assert len(composed_events) == 1
        assert composed_events[0]["soc_name"] == "demo_soc"
        assert composed_events[0]["stage"] == "SYSTEM_LEVEL"

        bb = h.blackboard.read("soc_composition")
        assert bb["value"]["soc_name"] == "demo_soc"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_run_stage_system_level_refuses_unregistered_subsystem():
    """The registry cross-check is live on the REAL path, not only in the
    gate script's own unit test: claiming a subsystem the harness never
    registered fails the stage and composes nothing. Same evidence as the
    passing test above except that only USB was ever registered."""
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB])
        h.set_stage("SYSTEM_LEVEL")
        h.adapter = _ReplyAdapter(_system_level_evidence([_USB, _PCIE]))
        h.run_stage("compose the USB+PCIe system-level environment")

        assert h.state.stages["SYSTEM_LEVEL"]["status"] != Status.PASS.value
        assert not (tmp / "generated" / "soc_composition").exists()
        events = [json.loads(line) for line in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        assert not [e for e in events if e.get("event") == "SOC_ENVIRONMENT_COMPOSED"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# B. The real CREATE ENVIRONMENT entry point
# --------------------------------------------------------------------------

def test_create_environment_routes_two_registered_subsystems_to_the_soc_composer():
    """A SYSTEM_LEVEL_MODE request reaches compose_soc_environment() because
    the router said so -- not because a caller hand-assembled a
    system_level_validator evidence block."""
    from dv_harness.uvm_generator.create_environment import create_environment
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB, _PCIE])
        result = create_environment(tmp, {
            "requested_subsystems": ["USB", "PCIE"], "soc_name": "demo_soc"})

        assert result["environment_mode"] == "SYSTEM_LEVEL_MODE"
        assert result["decision"]["resolved"] is True
        assert result["decision"]["needs_subsystem_mode_first"] is False
        assert result["composed_subsystems"] == ["USB", "PCIE"]

        # The SAME on-disk location engine.py's own composer path writes to.
        out_dir = tmp / "generated" / "soc_composition" / "demo_soc"
        assert Path(result["out_dir"]) == out_dir
        tb = (out_dir / "soc_tb_top.sv").read_text(encoding="utf-8")
        assert "usb_env usb_env_inst;" in tb and "pcie_env pcie_env_inst;" in tb
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_composes_from_the_real_registry_not_the_caller():
    """The composed content comes from what the harness REGISTERED, not from
    what the caller passed: the request names only subsystem names, and the
    release_sha/qualification_state that reach the generated evidence
    comments are the registered ones."""
    from dv_harness.uvm_generator.create_environment import create_environment
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB, _PCIE])
        create_environment(tmp, {"requested_subsystems": ["USB", "PCIE"],
                                 "soc_name": "demo_soc"})
        tb = (tmp / "generated" / "soc_composition" / "demo_soc" / "soc_tb_top.sv").read_text(
            encoding="utf-8")
        assert "release_sha=sha-usb-1" in tb
        assert "qualification_state=PRODUCTION_QUALIFIED" in tb
        assert "release_sha=sha-pcie-1" in tb
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_refuses_when_a_requested_subsystem_is_unregistered():
    """CLAUDE.md "Environment Generation Mode": a missing subsystem is built
    through SUBSYSTEM_MODE first, then composition resumes. The refusal names
    which one -- it never silently composes the registered subset, and never
    degrades to generating one subsystem environment for a two-subsystem
    request."""
    from dv_harness.uvm_generator.create_environment import (
        create_environment, SubsystemModeRequiredError)
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB])
        try:
            create_environment(tmp, {"requested_subsystems": ["USB", "PCIE"],
                                     "soc_name": "demo_soc"})
        except SubsystemModeRequiredError as exc:
            assert exc.detail["missing_subsystems"] == ["PCIE"]
            assert "SUBSYSTEM_MODE" in exc.detail["next_action"]
        else:
            raise AssertionError("composed despite an unregistered subsystem")
        assert not (tmp / "generated" / "soc_composition").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_keeps_single_protocol_manifests_on_the_subsystem_path():
    """Backwards compatibility, stated as a test: the manifest shape every
    .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md passes (a `protocol`, no
    `requested_subsystems`) still resolves SUBSYSTEM_MODE and still reaches
    ProtocolEnvGenerator.generate() with the same files produced. The new
    dispatch is a branch in FRONT of the old path, not a rewrite of it."""
    from dv_harness.uvm_generator.create_environment import create_environment
    from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator
    tmp, _h = _fresh_project()
    try:
        manifest = {"protocol": "usb", "smoke_tests": [{"name": "smoke"}]}
        via_dispatch = create_environment(tmp, dict(manifest), out_dir=tmp / "dispatch_out")
        direct = ProtocolEnvGenerator(tmp / "direct_out").generate(dict(manifest))

        assert via_dispatch["environment_mode"] == "SUBSYSTEM_MODE"
        assert via_dispatch["generated_files"] == direct
        assert (tmp / "dispatch_out" / "tb" / "top" / "tb_top.sv").read_text(encoding="utf-8") == \
               (tmp / "direct_out" / "tb" / "top" / "tb_top.sv").read_text(encoding="utf-8")
        assert not (tmp / "generated" / "soc_composition").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_builds_a_single_requested_subsystem():
    """One entry in `requested_subsystems` is a SUBSYSTEM_MODE build by
    definition (policy.json), and it reaches ProtocolEnvGenerator with that
    name as the protocol -- a request written in the composition vocabulary
    does not have to be rewritten into a `protocol` manifest to be buildable."""
    from dv_harness.uvm_generator.create_environment import create_environment
    tmp, _h = _fresh_project()
    try:
        result = create_environment(tmp, {"requested_subsystems": ["USB"]},
                                    out_dir=tmp / "usb_out")
        assert result["environment_mode"] == "SUBSYSTEM_MODE"
        assert (tmp / "usb_out" / "tb" / "env" / "usb_env.sv").exists()
        assert not (tmp / "generated" / "soc_composition").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_distinguishes_no_out_dir_from_no_mode():
    """"You did not say WHAT to build" and "you did not say WHERE to put it"
    are different failures with different fixes, and stay different types."""
    from dv_harness.uvm_generator.create_environment import (
        create_environment, MissingOutputDirectoryError, EnvironmentModeUnresolvedError)
    tmp, _h = _fresh_project()
    try:
        try:
            create_environment(tmp, {"protocol": "usb"})
        except MissingOutputDirectoryError as exc:
            assert exc.reason == "SUBSYSTEM_MODE_REQUIRES_OUT_DIR"
            assert exc.detail["decision"]["environment_mode"] == "SUBSYSTEM_MODE"
            assert not isinstance(exc, EnvironmentModeUnresolvedError)
        else:
            raise AssertionError("generated without an output directory")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_create_environment_refuses_an_unresolved_mode():
    """environment_mode_policy.json's mode_must_be_explicit_before_generation
    reaches the generator: a request naming nothing to build raises rather
    than defaulting to SUBSYSTEM_MODE."""
    from dv_harness.uvm_generator.create_environment import (
        create_environment, EnvironmentModeUnresolvedError)
    tmp, _h = _fresh_project()
    try:
        try:
            create_environment(tmp, {"soc_name": "demo_soc"}, out_dir=tmp / "out")
        except EnvironmentModeUnresolvedError as exc:
            assert exc.reason == "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION"
        else:
            raise AssertionError("generated without an explicit environment mode")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_generate_protocol_uvm_environment_tool_dispatches_by_mode():
    """The real shipped CLI entry point, run as a real subprocess -- the one
    tools/ script every PROTOCOL_BUILDERS skill documents. Both branches go
    through it."""
    tmp, h = _fresh_project()
    try:
        _register_subsystems(h, [_USB, _PCIE])

        soc_manifest = tmp / "soc_request.json"
        soc_manifest.write_text(json.dumps(
            {"requested_subsystems": ["USB", "PCIE"], "soc_name": "demo_soc"}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_protocol_uvm_environment.py"),
             "--manifest", str(soc_manifest), "--out", str(tmp / "soc_out"),
             "--root", str(tmp)],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "OK"
        assert out["environment_mode"] == "SYSTEM_LEVEL_MODE"
        assert "soc_tb_top.sv" in out["generated_files"]
        assert (tmp / "soc_out" / "soc_tb_top.sv").exists()

        sub_manifest = tmp / "usb_request.json"
        sub_manifest.write_text(json.dumps({"protocol": "usb"}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_protocol_uvm_environment.py"),
             "--manifest", str(sub_manifest), "--out", str(tmp / "usb_out"),
             "--root", str(tmp)],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["environment_mode"] == "SUBSYSTEM_MODE"
        assert (tmp / "usb_out" / "tb" / "top" / "tb_top.sv").exists()

        # A two-subsystem request with one unregistered subsystem refuses at
        # the CLI too, with a named exit code -- never a partial generation
        # reported as OK.
        bad_manifest = tmp / "bad_request.json"
        bad_manifest.write_text(json.dumps(
            {"requested_subsystems": ["USB", "ETHERNET"], "soc_name": "demo_soc"}),
            encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_protocol_uvm_environment.py"),
             "--manifest", str(bad_manifest), "--out", str(tmp / "bad_out"),
             "--root", str(tmp)],
            capture_output=True, text=True)
        assert proc.returncode == 2, proc.stdout
        out = json.loads(proc.stdout)
        assert out["status"] == "SUBSYSTEM_MODE_REQUIRED_FIRST"
        assert out["detail"]["missing_subsystems"] == ["ETHERNET"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
