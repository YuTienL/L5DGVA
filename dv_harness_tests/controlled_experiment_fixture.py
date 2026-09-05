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

# The single-gate, non-execution-layer stage the experiment measures.
FIXTURE_STAGE = "COMMAND_PATTERN"
FIXTURE_GATE_ID = "command_migration_integrity_gate"

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
        return AgentResult(
            ok=True,
            text=("Command migration manifest read; submitting integrity evidence.\n"
                  f"```dv-harness-evidence:{FIXTURE_GATE_ID}\n{body}\n```\n"),
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
