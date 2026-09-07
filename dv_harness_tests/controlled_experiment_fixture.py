"""The synthetic project fixture every controlled-experiment test runs against.

WHY A FIXTURE AND NOT THIS REPO. `capability_evolution.run_controlled_experiment()`
drives the REAL `DVHarness.run_stage()`. Pointing that at this repository would
run real stages against real project state, and pointing it at a build/regression
family stage would reach the farm. Everything here is deliberately the smallest
project that still makes the measurement REAL:

  * one real gate script, copied byte-for-byte out of this repo's own
    `tools/verification_flow/` -- so `gates.py` runs the real subprocess and the
    before/after numbers come from a real gate evaluation, not a stub;
  * the real shipped `main_graph.json`, so route/skill resolution and the node
    lookup behave exactly as they do in production;
  * `COMMAND_PATTERN`, chosen because it is a single-gate stage whose real graph
    node declares no execution-layer skill -- `run_controlled_experiment()`
    refuses those by default, and this fixture must never be the thing that
    quietly submits a build.

The stub adapter is the ONLY mocked thing, and it is mocked for one reason: the
real `ClaudeCLIAdapter` dispatches a `claude -p` subprocess. It reads a real file
out of the project root it is handed, which is what makes the two arms differ
for a real reason -- the mutation writes that file into the treatment copy only,
so the agent in the treatment arm has evidence to submit and the agent in the
baseline arm does not.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"
GATE_SCRIPT = ROOT / "tools" / "verification_flow" / "command_migration_integrity_gate.py"
# gates.run_gate() resolves a gate's script as `root / TOOLS_DIR / script_name`
# against the PROJECT ROOT it is handed (the arm workspace), never against this
# repo -- so command_generation_gate.py must be copied into the fixture project
# too, exactly like GATE_SCRIPT above, or every real invocation of it fails
# closed with GATE_TOOL_MISSING regardless of how correct its evidence payload
# is. It needs no other tool file copied alongside it: it imports
# existing_command_reuse_score/branch_ownership_resolver from the real
# dv_harness PACKAGE via DV_HARNESS_PACKAGE_ROOT (gates._gate_env()), not from
# a sibling file under tools/verification_flow/.
GATE_SCRIPT_2 = ROOT / "tools" / "verification_flow" / "command_generation_gate.py"

# The two-gate, non-execution-layer stage the experiment measures. Both gate ids
# below are exactly STAGE_GATES["COMMAND_PATTERN"] in dv_harness/gates.py -- the
# stub agent below must supply BOTH evidence blocks for the stage to PASS.
FIXTURE_STAGE = "COMMAND_PATTERN"
FIXTURE_GATE_ID = "command_migration_integrity_gate"
FIXTURE_GATE_ID_2 = "command_generation_gate"

# The file the stub agent looks for. The mutation writes it into the treatment
# arm; its absence in the baseline arm is what the baseline measures.
MIGRATION_FILE = "command_migration.json"

# A payload the REAL gate script accepts: matching source/destination hashes.
MIGRATION_PAYLOAD = {
    "commands": [
        {"command_id": "cmd_lfps_polling", "source_hash": "a1b2c3", "destination_hash": "a1b2c3"},
        {"command_id": "cmd_u1_entry", "source_hash": "d4e5f6", "destination_hash": "d4e5f6"},
    ]
}

# A payload the REAL command_generation_gate.py script accepts, traced through
# evaluate() and confirmed to PASS (see the investigation report this fixture's
# gap-close is based on): existing_commands=[] clears the reuse-score gate
# unconditionally (NO_EXISTING_COMMANDS_SUPPLIED); per_port=True with
# driven_by="DUT_BRINGUP_FLOW" on a "RAW_DUT_REGISTER_WRITE" resolves to tier
# DUT, which branch_layer="branch_a0" also resolves to -> VALID branch
# ownership; and task_evidence carries a non-placeholder implementation_plan,
# >=1 non-placeholder source_citations, and a grounding_basis
# ("PROGRAMMING_GUIDE") drawn from DUT_GROUNDING_BASES, the correct vocabulary
# for the resolved DUT tier. Kept on the SAME real LFPS-polling/U1-entry USB
# link-training migration this fixture already models, per a real DUT-side
# PHY calibration register write during bring-up.
COMMAND_GENERATION_PAYLOAD = {
    "proposed_command": {
        "command_name": "cmd_usb_phy_reg_write_port0",
        "branch_layer": "branch_a0",
        "description": "Write PHY calibration register during DUT bring-up on port 0",
        "arguments": ["ADDRESS", "VALUE"],
    },
    "existing_commands": [],
    "ownership": {
        "operation_kind": "RAW_DUT_REGISTER_WRITE",
        "per_port": True,
        "driven_by": "DUT_BRINGUP_FLOW",
    },
    "task_evidence": {
        "implementation_plan": (
            "Add a new branch_a0 task that issues a CPUWRITE1B to the PHY "
            "calibration register (offset 0x20) using the existing bridge task "
            "pattern, following the DUT bring-up sequence documented in the PHY "
            "programming guide section 4.2."
        ),
        "source_citations": [
            "PHY Programming Guide v2.1, Section 4.2 'Calibration Register Sequence'",
            "usb_phy_regmap.csv row 'PHY_CAL_CTRL'",
        ],
        "grounding_basis": "PROGRAMMING_GUIDE",
    },
}

# The SAME payload, deliberately BLOCKED (real, traced exit 6
# TASK_NOT_IMPLEMENTABLE/GROUNDING_BASIS_NOT_RECOGNIZED -- "unknown" is not a
# member of command_generation_gate.py's own ALL_GROUNDING_BASES). Used only
# when the migration manifest's own commands do NOT have matching source/
# destination hashes: an agent that noticed the same manifest is internally
# inconsistent has no sound primary-source grounding to cite for a NEW
# command either, so both gates fail together on the SAME real signal
# (`_migration_hashes_match()` below) instead of the second, unconditionally-
# valid gate silently overriding what the first one already found wrong. This
# is what keeps the benchmark-dataset "held-back harder case"
# (mismatched-hashes-expect-repair, command_pattern_evidence_v2.json) and the
# plain mismatched-hashes case discriminating exactly as they did before this
# stage grew a second required gate.
COMMAND_GENERATION_PAYLOAD_UNGROUNDED = {
    **COMMAND_GENERATION_PAYLOAD,
    "task_evidence": {
        **COMMAND_GENERATION_PAYLOAD["task_evidence"],
        "grounding_basis": "unknown",
    },
}


def _migration_hashes_match(manifest_json) -> bool:
    """Real correctness signal off the manifest's own content -- the SAME
    matching-source/destination-hash check the real command_migration_
    integrity_gate.py applies -- used to decide which command-generation
    payload to submit (see COMMAND_GENERATION_PAYLOAD_UNGROUNDED above)."""
    if not isinstance(manifest_json, dict):
        return False
    commands = manifest_json.get("commands")
    if not isinstance(commands, list) or not commands:
        return False
    return all(
        isinstance(c, dict) and c.get("source_hash") == c.get("destination_hash")
        for c in commands
    )


# The candidate's bounded change, in run_controlled_experiment()'s auditable
# declarative form: a relative path plus its content, verified to resolve inside
# the treatment workspace before anything is written.
MIGRATION_MUTATION = [{
    "path": MIGRATION_FILE,
    "content": json.dumps(MIGRATION_PAYLOAD, indent=2),
}]


def make_fixture_project(dest: Path) -> Path:
    """Materialize the synthetic project at `dest` and return it."""
    dest = Path(dest)
    (dest / "tools" / "verification_flow").mkdir(parents=True, exist_ok=True)
    shutil.copy(GATE_SCRIPT, dest / "tools" / "verification_flow" / GATE_SCRIPT.name)
    shutil.copy(GATE_SCRIPT_2, dest / "tools" / "verification_flow" / GATE_SCRIPT_2.name)
    (dest / ".dv-harness" / "graph").mkdir(parents=True, exist_ok=True)
    (dest / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


class MigrationEvidenceAdapter:
    """The stub agent. It submits the real gate's evidence block when, and only
    when, the migration manifest is present in the project root it is run in."""

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult

        manifest = Path(cwd) / MIGRATION_FILE
        if not manifest.exists():
            return AgentResult(
                ok=True,
                text=("No command migration manifest is present in this project, so no "
                      "migration integrity evidence can be produced."),
                raw={}, session_id=None)
        body = manifest.read_text(encoding="utf-8")
        try:
            manifest_json = json.loads(body)
        except ValueError:
            manifest_json = None
        command_generation_payload = (
            COMMAND_GENERATION_PAYLOAD if _migration_hashes_match(manifest_json)
            else COMMAND_GENERATION_PAYLOAD_UNGROUNDED)
        command_generation_body = json.dumps(command_generation_payload, indent=2)
        return AgentResult(
            ok=True,
            text=("Command migration manifest read; submitting integrity evidence.\n"
                  f"```dv-harness-evidence:{FIXTURE_GATE_ID}\n{body}\n```\n"
                  "Also submitting command-generation evidence for the new "
                  "DUT-side PHY calibration register write command.\n"
                  f"```dv-harness-evidence:{FIXTURE_GATE_ID_2}\n"
                  f"{command_generation_body}\n```\n"),
            raw={}, session_id=None)


def harness_factory(project_root):
    """`run_controlled_experiment(harness_factory=...)`'s injected seam: a REAL
    DVHarness rooted at the arm's own workspace, with only the agent adapter
    swapped so no subprocess is dispatched."""
    from dv_harness.engine import DVHarness

    harness = DVHarness(Path(project_root))
    harness.adapter = MigrationEvidenceAdapter()
    return harness


def run_demo_experiment(root: Path, candidate: dict, fixture: Path, **kwargs) -> dict:
    """The whole fixture experiment as one call, for tests that need a candidate
    to genuinely REACH BENCHMARKED rather than to study the experiment itself."""
    from dv_harness import capability_evolution as ce

    return ce.run_controlled_experiment(
        root, candidate,
        fixture_project=fixture,
        stages=[FIXTURE_STAGE],
        mutation=MIGRATION_MUTATION,
        harness_factory=harness_factory,
        **kwargs,
    )


def run_demo_replication(root: Path, candidate: dict, fixture: Path, **kwargs) -> dict:
    """One more REAL shadow run of the same experiment, for tests that need a
    candidate to genuinely satisfy section 134's stability window before
    BENCHMARKED -> PROMOTION_CANDIDATE will let it through.

    Deliberately the same fixture, arms, stages and mutation as
    run_demo_experiment(): a replication that measured something else would not
    replicate anything, and `stability_window_status()` refuses that case."""
    from dv_harness import capability_evolution as ce

    return ce.run_shadow_replication(
        root, candidate,
        fixture_project=fixture,
        stages=[FIXTURE_STAGE],
        mutation=MIGRATION_MUTATION,
        harness_factory=harness_factory,
        **kwargs,
    )


def benchmarked_with_stability_window(root: Path, candidate: dict, fixture: Path) -> dict:
    """A candidate at BENCHMARKED carrying a real, established stability window:
    the controlled experiment plus one real replication, both measured."""
    measured = run_demo_experiment(root, candidate, fixture)["candidate"]
    return run_demo_replication(root, measured, fixture)["candidate"]
