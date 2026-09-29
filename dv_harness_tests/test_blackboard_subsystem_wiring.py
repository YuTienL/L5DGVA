"""Connection tests for the three Blackboard edges that had no live call
site in code before 2026-09-04:

    env.manifest.json (vip_config / dut_facts / env_topology) -> Blackboard
    question queue decisions (answered / assumed / revoked)   -> Blackboard
    connectivity 3-gate standard (Gate 1 / 2 / 3 statuses)    -> Blackboard

The Blackboard mechanism itself was never the gap -- `Blackboard.write()`
and engine.py's `_write_blackboard_from_evidence()` were already firing on
the real `run_stage()` PASS branch, with real stage-sourced entries on disk
under `.dv-harness/blackboard/`. What a 2026-09-04 audit found was that
three whole subsystems built after that mechanism never joined it: a
repo-wide grep for "blackboard" hit ZERO lines in `env_manifest.py`,
`question_queue.py`, `connectivity.py` and `connectivity_check.py`, and no
node in the real `.dv-harness/graph/main_graph.json` declared any topic
those subsystems could have written. Each persisted only to its own private
store, so a graph stage -- whose one structured view of current truth is
the `blackboard_read` snapshot engine.py serializes into its prompt -- could
not see any of it. That contradicts CLAUDE.md's own "Blackboard stores
current verification truth" rule.

So these tests deliberately do NOT re-test any subsystem's internals (those
have their own suites: test_env_manifest.py, test_question_queue.py,
test_connectivity_check.py). Every test here drives a REAL production entry
point end to end -- `dv_harness.cli.main()` for `dv-harness env-manifest
generate` and `dv-harness question-queue ...`, `connectivity_check.main()`
for `just connectivity-check` -- and then asserts a real
`.dv-harness/blackboard/<topic>.json` file exists on disk carrying a real
`source`. A test that still passed after the wiring line was deleted would
prove nothing about the edge, which is exactly the failure mode the
pre-2026-09-04 per-subsystem unit tests had.

The last group closes the loop back to the graph: a topic nothing ever
READS is only half an edge, so those tests assert against the REAL
`.dv-harness/graph/main_graph.json` this harness runs on (not a fixture)
that each new topic is declared in some node's `blackboard_read`, and that
`Blackboard.snapshot()` over that real node's declaration -- the exact call
engine.py makes -- returns the written value.
"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap

import pytest

import dv_harness.cli as cli_mod
from dv_harness import connectivity_check as cc
from dv_harness import env_manifest, question_queue
from dv_harness.blackboard import Blackboard
from dv_harness.graph import GraphDefinition

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
REAL_GRAPH_PATH = REPO_ROOT / ".dv-harness" / "graph" / "main_graph.json"

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

RTL_FIXTURE = textwrap.dedent("""\
    module lfps_detect #(parameter int WIDTH = 8) (
      input  logic             clk,
      input  logic             rst_n,
      input  logic [WIDTH-1:0] rx_data,
      output logic             lfps_seen
    );
      logic [WIDTH-1:0] shift_reg;
    endmodule
    """)


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _topic_file(root, topic):
    return root / ".dv-harness" / "blackboard" / f"{topic}.json"


def _read_topic(root, topic):
    """Reads the raw persisted entry (topic/value/source/confidence), NOT
    Blackboard.read()'s unwrapping -- the `source` field is half of what is
    being proved here."""
    return json.loads(_topic_file(root, topic).read_text(encoding="utf-8"))


# ===========================================================================
# env.manifest.json -> Blackboard
# ===========================================================================

def test_cli_env_manifest_generate_writes_the_env_manifest_topic(monkeypatch, tmp_path, capsys):
    """THE edge. Before this wiring `env-manifest generate` wrote its
    manifest file and nothing else; `.dv-harness/blackboard/env_manifest.json`
    could not exist because no code anywhere named that topic."""
    out_manifest = tmp_path / "env.manifest.json"
    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest)], capsys)
    assert rc == 0
    assert out_manifest.exists()

    entry = _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)
    assert entry["topic"] == "env_manifest"
    # A real, attributable source -- the same evidence standard the already-
    # firing stage-sourced topics (INTAKE/ENV_CHECK/DISCOVERY) are held to.
    assert entry["source"] == "env-manifest"
    assert entry["value"]["manifest_path"] == str(out_manifest)


def test_env_manifest_topic_keeps_not_available_honest(monkeypatch, tmp_path, capsys):
    """A generation run with no VIP dump / no topology dump must surface
    NOT_AVAILABLE plus the real reason -- never an empty list that reads to a
    consuming stage like "captured, and the environment has no VIP"."""
    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(tmp_path / "env.manifest.json")], capsys)
    assert rc == 0

    value = _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)["value"]
    assert value["vip_config"]["status"] == "NOT_AVAILABLE"
    assert "VIP_CONFIG_DUMP_PATH" in value["vip_config"]["reason"]
    assert value["vip_config"]["instance_count"] == 0
    assert value["dut_facts"]["rtl"]["status"] == "NOT_AVAILABLE"
    assert value["env_topology"]["component_hierarchy"]["status"] == "NOT_AVAILABLE"
    assert value["env_topology"]["config_db_trace"]["status"] == "NOT_AVAILABLE"


def test_env_manifest_topic_carries_real_vip_instances(monkeypatch, tmp_path, capsys):
    """A real VIP config dump reaches a consuming stage through the topic --
    instance paths and types, from the real parse, not a restated status."""
    dump = tmp_path / "vip_config_dump.json"
    dump.write_text(json.dumps({"schema_version": "1.0", "vip_instances": [
        {"instance_path": "tb_top.usb_vip1", "vip_type": "svt_usb_agent",
         "config_fields": {"speed": "SS"}},
        {"instance_path": "tb_top.usb_vip0", "vip_type": "svt_usb_agent",
         "config_fields": {}},
    ]}), encoding="utf-8")

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(tmp_path / "env.manifest.json"),
        "--vip-config-dump", str(dump)], capsys)
    assert rc == 0

    vip = _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)["value"]["vip_config"]
    assert vip["status"] == "CAPTURED"
    assert vip["instance_count"] == 2
    # Sorted by instance_path, exactly as the manifest layer sorts them.
    assert [i["instance_path"] for i in vip["instances"]] == ["tb_top.usb_vip0", "tb_top.usb_vip1"]
    assert vip["instances"][1]["config_field_count"] == 1


@requires_verible
def test_env_manifest_topic_agrees_with_the_manifest_and_omits_parse_trees(
        monkeypatch, tmp_path, capsys):
    """Cross-checked against the manifest the SAME run wrote (not against a
    hand-written expectation), and asserted prompt-sized: the topic is
    serialized into every reading stage's prompt, so the full per-port /
    per-signal verible parse must NOT be inlined."""
    rtl = tmp_path / "lfps_detect.sv"
    rtl.write_text(RTL_FIXTURE, encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
    assert rc == 0

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    manifest_module = manifest["dut_facts"]["rtl"]["files"][0]["modules"][0]
    topic_rtl = _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)["value"]["dut_facts"]["rtl"]

    assert topic_rtl["status"] == "PARSED"
    assert topic_rtl["file_count"] == 1
    assert topic_rtl["files"][0]["file_path"] == str(rtl)
    assert topic_rtl["files"][0]["source_sha256"] == \
        manifest["dut_facts"]["rtl"]["files"][0]["source_sha256"]
    assert topic_rtl["files"][0]["modules"] == [manifest_module["name"]] == ["lfps_detect"]

    # The manifest really did carry the full parse; the topic really did not.
    assert manifest_module["ports"]
    blob = json.dumps(topic_rtl)
    assert "rx_data" not in blob and "lfps_seen" not in blob


def test_env_manifest_topic_is_refreshed_not_left_stale(monkeypatch, tmp_path, capsys):
    """Re-generation must overwrite the topic. A stale snapshot of a previous
    environment is worse than none: a stage would read it as current truth."""
    dump = tmp_path / "vip_config_dump.json"
    dump.write_text(json.dumps({"schema_version": "1.0", "vip_instances": [
        {"instance_path": "tb_top.vip0", "vip_type": "svt_usb_agent", "config_fields": {}}]}),
        encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    assert _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest),
        "--vip-config-dump", str(dump)], capsys)[0] == 0
    assert _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)["value"]["vip_config"]["instance_count"] == 1

    dump.write_text(json.dumps({"schema_version": "1.0", "vip_instances": [
        {"instance_path": "tb_top.vip0", "vip_type": "svt_usb_agent", "config_fields": {}},
        {"instance_path": "tb_top.vip1", "vip_type": "svt_usb_agent", "config_fields": {}}]}),
        encoding="utf-8")
    assert _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest),
        "--vip-config-dump", str(dump)], capsys)[0] == 0
    assert _read_topic(tmp_path, env_manifest.BLACKBOARD_TOPIC)["value"]["vip_config"]["instance_count"] == 2


# ===========================================================================
# question queue decisions -> Blackboard
# ===========================================================================

def _add_question(monkeypatch, tmp_path, capsys, *, extra=None, question="Which PHY layer?"):
    args = ["question-queue", "add", "--domain", "dut", "--question", question,
            "--context-path", "rtl/usb_phy.sv", "--recommendation", "Option A",
            "--assumption-if-unanswered", "Option A",
            "--option", "Option A", "--option", "Option B"]
    if extra:
        args += extra
    return _run_cli(monkeypatch, tmp_path, args, capsys)


def test_cli_question_queue_answer_writes_the_decisions_topic(monkeypatch, tmp_path, capsys):
    """THE edge for a Tier-3 CANNOT_ASSUME question a human actually
    answered. That answer IS current-run truth the moment it is given;
    before this wiring it lived only in the queue's own private
    decisions.json, invisible to every graph stage."""
    rc, out = _add_question(monkeypatch, tmp_path, capsys, extra=["--affects-pass-fail-verdict"])
    assert rc == 0
    record = json.loads(out)
    assert record["tier"] == 3 and record["status"] == "OPEN"
    # Nothing is decided yet, so there is nothing to publish yet.
    assert not _topic_file(tmp_path, question_queue.BLACKBOARD_TOPIC).exists()

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "question-queue", "answer", record["id"],
        "--answer", "Option B", "--basis", "designer confirmed against RTL",
        "--decided-by", "dv-owner"], capsys)
    assert rc == 0

    entry = _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)
    assert entry["topic"] == "open_questions_decisions"
    assert entry["source"] == "question_queue"
    value = entry["value"]
    assert value["decision_count"] == 1
    assert value["human_answered_count"] == 1
    assert value["tier2_assumed_count"] == 0
    decision = value["decisions"][record["question_key"]]
    assert decision["answer"] == "Option B"
    assert decision["basis"] == "designer confirmed against RTL"
    assert decision["decided_by"] == "dv-owner"
    assert decision["source"] == question_queue.HUMAN_DECISION_SOURCE


def test_decisions_topic_keeps_tier2_assumption_distinguishable(monkeypatch, tmp_path, capsys):
    """A Tier-2 auto-assumption is a machine guess, not an answer. It must
    reach the topic (a stage needs to know an assumption is in force) but
    must stay distinguishable from a human answer -- collapsing the two is
    precisely what the 3-tier protocol exists to prevent."""
    rc, out = _add_question(monkeypatch, tmp_path, capsys)
    assert rc == 0
    record = json.loads(out)
    assert record["tier"] == 2

    value = _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)["value"]
    assert value["decision_count"] == 1
    assert value["human_answered_count"] == 0
    assert value["tier2_assumed_count"] == 1
    decision = value["decisions"][record["question_key"]]
    assert decision["source"] == "tier2_auto_assumption"
    assert decision["source"] != question_queue.HUMAN_DECISION_SOURCE
    assert decision["ever_tier2_assumed"] is True


def test_cli_question_queue_revoke_removes_the_decision_from_the_topic(
        monkeypatch, tmp_path, capsys):
    """A revoked decision must disappear from the topic, exactly as it
    disappears from find_decision(). A stage that kept acting on a decision
    a human withdrew is the worst possible failure of this mirror."""
    rc, out = _add_question(monkeypatch, tmp_path, capsys)
    assert rc == 0
    record = json.loads(out)
    assert _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)["value"]["decision_count"] == 1

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "question-queue", "revoke", record["question_key"],
        "--reason", "assumption contradicted by RTL", "--revoked-by", "dv-owner"], capsys)
    assert rc == 0

    value = _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)["value"]
    assert value["decision_count"] == 0
    assert value["decisions"] == {}
    assert value["revoked_count"] == 1


def test_decisions_topic_agrees_with_decisions_json(monkeypatch, tmp_path, capsys):
    """The mirror and the store it mirrors are asserted against each other,
    not each against a hand-written expectation -- the cross-check a
    per-side unit test structurally cannot make."""
    for i in range(3):
        rc, out = _add_question(monkeypatch, tmp_path, capsys, question=f"Q{i}?")
        assert rc == 0

    store = question_queue.QuestionQueueStore(tmp_path)
    on_disk = json.loads(store.decisions_path.read_text(encoding="utf-8"))["decisions"]
    value = _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)["value"]

    assert set(value["decisions"]) == set(on_disk)
    assert value["decision_count"] == len(on_disk)
    for key, mirrored in value["decisions"].items():
        assert mirrored["answer"] == on_disk[key]["current"]["answer"]
        assert mirrored["source"] == on_disk[key]["current"]["source"]


def test_store_constructed_without_an_injected_blackboard_still_mirrors(tmp_path):
    """The mirror is ON by default, not opt-in. This class is constructed all
    over the codebase (cli.py, connectivity.py x2, coverage_analysis.py,
    source_authority.py, run_profile_to_justfile.py, and growing) and only
    cli.py injects a board; a mirror all the others had to remember to switch
    on would be the same "built but never wired" gap this file exists to
    close. Exercised through the plain `QuestionQueueStore(root)` they use."""
    store = question_queue.QuestionQueueStore(tmp_path)
    assert store.blackboard is None  # nothing injected
    store.add_question(domain="env", question="q?", context_path="p",
                       options=[{"label": "A"}, {"label": "B"}],
                       recommendation="A", assumption_if_unanswered="A")
    assert store.decisions_path.exists()

    value = _read_topic(tmp_path, question_queue.BLACKBOARD_TOPIC)["value"]
    assert value["decision_count"] == 1
    assert value["tier2_assumed_count"] == 1


def test_constructing_a_store_creates_no_directories(tmp_path):
    """The default board is built lazily, at the first decision write. Merely
    constructing a store (which several callers do just to read
    find_decision()) must not create `.dv-harness/blackboard/`."""
    question_queue.QuestionQueueStore(tmp_path)
    assert not (tmp_path / ".dv-harness" / "blackboard").exists()


# ===========================================================================
# connectivity 3-gate standard -> Blackboard
# ===========================================================================

def _make_connectivity_project(tmp_path, **cfg_overrides):
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "dut.sv").write_text("module dut(input clk); endmodule\n", encoding="utf-8")
    cfg = {"rtl_sources": ["rtl/**/*.sv"], "filelists": [], "top_module": "tb_top"}
    cfg.update(cfg_overrides)
    p = root / cc.DEFAULT_CONFIG_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def test_connectivity_check_run_writes_the_gates_topic(tmp_path, capsys):
    """THE edge, through the real `just connectivity-check` entry point.
    Before this wiring the 3 gate statuses reached only a state file and a
    markdown report -- both artifacts a human opens, neither reachable from
    a graph stage."""
    root = _make_connectivity_project(
        tmp_path, monitor_transaction_counts={"env.usb_agent.monitor": 42},
        pattern_completed=True)
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    capsys.readouterr()

    entry = _read_topic(root, cc.BLACKBOARD_TOPIC)
    assert entry["topic"] == "connectivity_gates"
    assert entry["source"] == "connectivity-check"
    value = entry["value"]
    assert set(value["gates"]) == {"gate1_elaboration", "gate2_zero_time_connectivity",
                                   "gate3_transaction_activity"}
    assert value["gates"]["gate3_transaction_activity"]["status"] == "PASS"
    assert value["ready_for_human_review"] is True

    # The verdicts travel with the RTL they were produced against, so a
    # reader can tell whether they still describe the current RTL.
    state = json.loads((root / cc.DEFAULT_STATE_RELPATH).read_text(encoding="utf-8"))
    assert value["rtl_fingerprint"] == state["rtl_fingerprint"]
    assert value["rtl_file_count"] == 1


def test_gates_topic_never_collapses_not_available_or_pending_into_a_boolean(tmp_path, capsys):
    """NOT_AVAILABLE ("no slang/vcs on PATH") and PENDING ("no pattern has
    completed yet") must survive into the topic as themselves. Flattening
    either into FAIL -- or into a pass/fail bool -- is the exact conflation
    GateStatus's five states exist to prevent."""
    root = _make_connectivity_project(tmp_path, pattern_completed=False)
    cc.main(["--project-root", str(root)])
    capsys.readouterr()

    value = _read_topic(root, cc.BLACKBOARD_TOPIC)["value"]
    statuses = {g: v["status"] for g, v in value["gates"].items()}
    assert statuses["gate3_transaction_activity"] == "PENDING"
    assert "FAIL" not in statuses.values()
    assert "gate3_transaction_activity" in value["pending_gates"]
    # Every reported status is a real GateStatus value, never a bool.
    valid = {s.value for s in cc.GateStatus}
    assert set(statuses.values()) <= valid
    assert value["gates"]["gate3_transaction_activity"]["detail"]


def test_check_only_does_not_refresh_the_gates_topic(tmp_path, capsys):
    """`--check-only` runs NO gate -- it only compares fingerprints. If it
    refreshed the topic, stale verdicts would look freshly produced against
    RTL they were never run on."""
    root = _make_connectivity_project(tmp_path, pattern_completed=True,
                                      monitor_transaction_counts={"env.mon": 1})
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    before = _topic_file(root, cc.BLACKBOARD_TOPIC).read_text(encoding="utf-8")

    (root / "rtl" / "dut.sv").write_text("module dut(input clk, input rst_n); endmodule\n",
                                         encoding="utf-8")
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_STALE
    capsys.readouterr()

    after = _topic_file(root, cc.BLACKBOARD_TOPIC).read_text(encoding="utf-8")
    assert after == before
    # And the topic still honestly reports the OLD fingerprint, so a reader
    # comparing it against current RTL can see the verdicts are stale.
    assert json.loads(after)["value"]["rtl_fingerprint"] != \
        cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])["fingerprint"]


def test_gates_topic_not_written_when_write_is_false(tmp_path):
    """A dry evaluation (`write=False`) must leave no trace, the blackboard
    included -- otherwise a probe would publish verdicts nothing recorded."""
    root = _make_connectivity_project(tmp_path, pattern_completed=True)
    cfg = cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH)
    result = cc.run_connectivity_check(root, cfg, write=False)
    assert result.gate_report is not None
    assert not _topic_file(root, cc.BLACKBOARD_TOPIC).exists()


# ===========================================================================
# The other half of the edge: the REAL graph declares readers for each topic
# ===========================================================================

NEW_TOPICS = {
    env_manifest.BLACKBOARD_TOPIC: "env_manifest",
    question_queue.BLACKBOARD_TOPIC: "open_questions_decisions",
    cc.BLACKBOARD_TOPIC: "connectivity_gates",
}


@pytest.mark.parametrize("topic", sorted(NEW_TOPICS))
def test_real_graph_declares_a_reader_for_each_new_topic(topic):
    """A topic nothing ever reads is half an edge. Asserted against the REAL
    `.dv-harness/graph/main_graph.json` this harness runs on -- a fixture
    graph would pass while the shipped one stayed unwired, which is the
    whole class of gap this file exists to close."""
    graph = GraphDefinition.load(REAL_GRAPH_PATH)
    readers = sorted(n.id for n in graph.nodes.values() if topic in n.blackboard_read)
    assert readers, f"no node in the real graph declares blackboard_read of {topic!r}"


def test_real_graph_reader_nodes_are_the_stages_that_need_each_topic():
    """Pins WHICH stages read each topic, so a later graph edit cannot
    quietly drop a reader that matters (e.g. SIGNOFF losing sight of a
    FAILing bind gate) while the presence test above still passed."""
    graph = GraphDefinition.load(REAL_GRAPH_PATH)

    def readers(topic):
        return {n.id for n in graph.nodes.values() if topic in n.blackboard_read}

    # Real DUT/VIP/topology facts feed the stages that build the
    # architecture/verification-boundary model and the implementation.
    assert {"ARCH_DISCOVERY", "PROJECT_MODEL", "IMPLEMENT"} <= readers("env_manifest")
    # Bind/connectivity verdicts feed build-debug, verify and signoff.
    assert {"BUILD_DEBUG", "VERIFY", "SIGNOFF"} <= readers("connectivity_gates")
    # Answered/assumed questions feed the stages that would otherwise
    # re-derive (or re-ask) a decision a human already made.
    assert {"IMPLEMENT", "FAILURE_RECOVERY", "SIGNOFF"} <= readers("open_questions_decisions")


def test_engine_snapshot_call_surfaces_a_written_topic(monkeypatch, tmp_path, capsys):
    """The consumption path itself, exercised exactly as engine.py does it:
    `self.blackboard.snapshot(node.blackboard_read)` over a REAL graph node's
    declaration. This is what puts the value into a stage's prompt."""
    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(tmp_path / "env.manifest.json")], capsys)
    assert rc == 0

    node = GraphDefinition.load(REAL_GRAPH_PATH).nodes["ARCH_DISCOVERY"]
    snapshot = Blackboard(tmp_path).snapshot(node.blackboard_read)

    assert "env_manifest" in snapshot
    assert snapshot["env_manifest"] is not None
    assert snapshot["env_manifest"]["source"] == "env-manifest"
    assert snapshot["env_manifest"]["value"]["vip_config"]["status"] == "NOT_AVAILABLE"
    # An unwritten prior topic still reports as None rather than vanishing --
    # the snapshot is a complete answer to the node's declaration.
    assert snapshot["baseline"] is None
