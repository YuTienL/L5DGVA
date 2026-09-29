"""Two 2026-09-04 Blackboard gaps, both proven on the REAL path.

`test_blackboard_subsystem_wiring.py` already proves each subsystem's own
sync function writes its topic when its CLI/runner entry point is invoked.
Neither of the gaps below is about that, and neither is covered there:

A. **`Blackboard.write()` was not atomic.** It was a plain
   `p.write_text(json.dumps(...))` -- truncate, then write -- while
   `blackboard.py` imported `tempfile` and never used it. That matters
   because concurrency here is real, not hypothetical: `engine.
   _advance_with_fanout()` runs parallel_group branches through a genuine
   `ThreadPoolExecutor` in ONE process and every branch's `run_stage()`
   touches topics from its own thread, and `dashboard.py` polls topic files
   straight off disk from an HTTP thread. The engine's fan-out ownership
   claim (`AgentTaskStore.acquire()`) only stops two BRANCHES claiming the
   same WRITE topic; it says nothing about the file operation. None of
   `engine.py`'s ~17 `self.blackboard.read/write(...)` call sites wraps the
   call in a try/except, so a torn read would have surfaced as an uncaught
   `JSONDecodeError` out of `run_stage()`.

   The tests below are three-way so the positive results have power: the
   SAME concurrent harness run against a deliberately non-atomic writer
   really does observe torn reads (so the harness can detect the defect),
   run against the real writer observes none (write atomicity, proven
   independently of any reader retry), and the real `read()` survives the
   non-atomic writer (reader resilience, proven independently of the write).

B. **Nothing on the autonomous path ever PRODUCED the three
   subsystem-written topics.** `engine.py` had zero references to
   `env_manifest` / `question_queue` / `connectivity_check`; no node prompt
   instructed an agent to run either command; CI ran only
   `connectivity-check --check-only`, which by contract refreshes nothing.
   Seven real graph nodes declare one of the three in `blackboard_read`, so
   a fully autonomous INTAKE->SIGNOFF run could finish with all three
   permanently absent. Every test in Part B drives the REAL
   `DVHarness.run_stage()` against the REAL shipped `main_graph.json` and
   asserts the topic file appears on disk without any CLI command being
   run -- which is precisely what `test_blackboard_subsystem_wiring.py`
   cannot show, because every test there invokes the CLI/runner itself.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dv_harness import connectivity_check as cc
from dv_harness import env_manifest
from dv_harness.blackboard import Blackboard
from dv_harness.engine import SUBSYSTEM_TOPIC_REFRESHERS, DVHarness
from dv_harness.graph import GraphDefinition

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH_PATH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

SUBSYSTEM_TOPICS = {"env_manifest", "open_questions_decisions", "connectivity_gates"}


# ===========================================================================
# Part A -- atomic write / resilient read under real concurrency
# ===========================================================================

# Big enough that a truncate-then-write leaves a genuinely wide window for a
# reader to land in, the same way a real env_manifest/connectivity_gates
# summary is far larger than one filesystem block.
_BIG_VALUE = {"payload": ["x" * 512 for _ in range(100)]}


class _NonAtomicBlackboard(Blackboard):
    """The pre-fix write path, with its truncate/write window widened to a
    deterministic 5ms so the control test cannot be flaky. Exists ONLY to
    show the harness below can detect a torn write at all."""

    def write(self, t, value, source="", confidence="HIGH"):
        payload = {"topic": t, "value": value, "source": source, "confidence": confidence}
        p = self._path(t)
        blob = json.dumps(payload, ensure_ascii=False, indent=2)
        with p.open("w", encoding="utf-8") as f:
            f.write(blob[: len(blob) // 2])
            f.flush()
            time.sleep(0.005)
            f.write(blob[len(blob) // 2:])
        return payload


def _hammer(bb, topic, *, reader, writers=3, readers=3, reader_iterations=150,
             reader_sleep=0.004, writer_sleep=0.002):
    """Mirrors engine._advance_with_fanout()'s real shape: several branch
    threads in ONE process, in ONE ThreadPoolExecutor, touching the
    blackboard concurrently. Returns the exceptions the readers saw.

    Termination is driven by the READERS (a fixed iteration count) and the
    writers loop until that finishes, so reads and writes genuinely overlap
    for the whole run. `done` is set from the readers' `finally`, so a writer
    that raises can never leave the pool waiting on a reader that never stops
    -- the failure surfaces as that writer's exception, not as a hung test.

    Both sides sleep between operations ON PURPOSE. A zero-backoff reader
    spin is not a model of anything real (nothing in this harness reads a
    topic in a tight loop) and it changes what is being measured in two
    ways this suite must avoid: on Windows, continuously-open readers can
    exhaust `storage._atomic_replace()`'s own retry budget so the WRITER
    raises -- a pre-existing property of that shared utility, which
    state.json's writer has too, not anything this file's fix introduced --
    and against a non-atomic writer the union of write windows covers
    essentially all wall-clock time, so the topic file is never valid at any
    instant and no reader retry policy could possibly succeed."""
    done = threading.Event()
    start = threading.Barrier(writers + readers)
    errors = []

    def write_loop(worker):
        start.wait()
        i = 0
        while not done.is_set():
            bb.write(topic, dict(_BIG_VALUE, round=i, worker=worker), source="fanout")
            i += 1
            time.sleep(writer_sleep)

    def read_loop():
        start.wait()
        try:
            for _ in range(reader_iterations):
                try:
                    reader()
                except Exception as exc:  # recorded, never swallowed silently
                    errors.append(exc)
                time.sleep(reader_sleep)
        finally:
            done.set()

    with ThreadPoolExecutor(max_workers=writers + readers) as ex:
        futures = [ex.submit(write_loop, w) for w in range(writers)]
        futures += [ex.submit(read_loop) for _ in range(readers)]
        for f in futures:
            f.result()
    return errors


# ONE writer at a cadence that leaves real gaps between writes, read by two
# threads often enough to land inside one. Every Part A concurrency test uses
# these SAME numbers on purpose: the three results (raw read tears against a
# non-atomic writer / does not tear against the real one / the retrying
# read() survives the non-atomic one) are then measured under identical
# conditions and differ only in the one variable each names.
_LOAD = dict(writers=1, readers=2, reader_iterations=120,
              reader_sleep=0.002, writer_sleep=0.02)


def _raw_read(path: Path):
    """A reader with NO retry -- dashboard.py's `_read_json_file` retries a
    PermissionError but not a torn parse, and any external tool reading a
    topic file gets exactly this. Used so Part A can attribute a result to
    the WRITE path alone."""
    return json.loads(path.read_text(encoding="utf-8"))


class TestBlackboardWriteIsAtomic:

    def test_control_a_nonatomic_writer_really_does_tear_under_this_harness(self, tmp_path):
        """Detection power. Without this, "no torn reads" below would be
        indistinguishable from "the test never looked hard enough"."""
        bb = _NonAtomicBlackboard(tmp_path)
        path = bb._path("torn")
        errors = _hammer(bb, "torn", reader=lambda: _raw_read(path), **_LOAD)
        assert any(isinstance(e, json.JSONDecodeError) for e in errors), (
            "the control writer produced no torn read -- this harness cannot detect "
            "the defect it is meant to prove fixed", [type(e).__name__ for e in errors])

    def test_real_write_is_never_observed_half_written(self, tmp_path):
        """The fix itself: concurrent unretried readers see only complete
        payloads, so no reader ANYWHERE (dashboard, external tool, or one of
        engine.py's 17 unguarded read call sites) can observe a torn topic.

        A bare PermissionError is deliberately tolerated here and asserted
        against separately below: on Windows a reader's CreateFile can lose
        the race with the writer's `os.replace()` itself (the window
        storage._atomic_replace() and dashboard._read_json_file() both
        already document and retry). That is a lock race, not a torn file --
        the retrying reader in TestBlackboardReadIsResilient is what covers
        it, and `_raw_read` deliberately has no retry so this test can
        attribute its result to the WRITE path alone."""
        bb = Blackboard(tmp_path)
        path = bb._path("verification_state")
        bb.write("verification_state", {"seed": True}, source="seed")

        seen = []

        def reader():
            doc = _raw_read(path)
            seen.append(doc)
            assert doc["topic"] == "verification_state"
            assert doc["confidence"] == "HIGH"
            assert doc["value"]["payload"] if "payload" in doc["value"] else True

        errors = _hammer(bb, "verification_state", reader=reader, **_LOAD)
        torn = [e for e in errors if isinstance(e, (json.JSONDecodeError, UnicodeDecodeError))]
        assert torn == [], torn
        assert all(isinstance(e, PermissionError) for e in errors), \
            [type(e).__name__ for e in errors]
        assert seen, "readers never actually read anything"

    def test_write_leaves_no_temp_files_behind(self, tmp_path):
        """The temp file is unlinked (or renamed away) on every path -- a
        blackboard directory silting up with `<topic>.XXXX.json` would make
        the topic store unreadable to anything that lists it."""
        bb = Blackboard(tmp_path)
        for i in range(5):
            bb.write("findings", {"i": i}, source="t")
        names = sorted(p.name for p in bb.root.iterdir())
        assert names == ["findings.json"], names

    def test_a_failed_write_leaves_the_previous_value_intact(self, tmp_path):
        """Atomic means all-or-nothing, not just untorn: a write that dies
        mid-serialization must not destroy the last known truth. A
        truncate-then-write would have left an empty or partial file here."""
        bb = Blackboard(tmp_path)
        bb.write("qualified_conclusion", {"is_qualified": True}, source="RE_AUDIT")

        class _Unserializable:
            pass

        with pytest.raises(TypeError):
            bb.write("qualified_conclusion", {"bad": _Unserializable()}, source="RE_AUDIT")

        assert bb.read("qualified_conclusion")["value"] == {"is_qualified": True}
        assert sorted(p.name for p in bb.root.iterdir()) == ["qualified_conclusion.json"]


class TestBlackboardReadIsResilient:

    def test_read_survives_the_nonatomic_writer_the_control_test_defeats(self, tmp_path):
        """Reader resilience, isolated from the write fix: against the SAME
        writer that made `_raw_read` fail above, `Blackboard.read()`'s retry
        loop returns real payloads and raises nothing."""
        bb = _NonAtomicBlackboard(tmp_path)
        seen = []

        def reader():
            doc = bb.read("connectivity_gates")
            if doc is not None:
                seen.append(doc)
                assert doc["source"] == "fanout"

        errors = _hammer(bb, "connectivity_gates", reader=reader, **_LOAD)
        assert errors == [], [repr(e) for e in errors]
        assert seen

    def test_read_returns_default_for_a_topic_that_was_never_written(self, tmp_path):
        assert Blackboard(tmp_path).read("never_written") is None
        assert Blackboard(tmp_path).read("never_written", default={}) == {}

    def test_read_still_raises_on_a_permanently_corrupt_topic(self, tmp_path):
        """The retry budget must not turn corruption into a silent "no
        record". Reporting an unreadable topic as absent would present
        "no verification truth recorded" as a fact -- the one thing the
        Blackboard must never fabricate."""
        bb = Blackboard(tmp_path)
        bb._path("findings").write_text('{"topic": "findings", "val', encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            bb.read("findings")

    def test_snapshot_reads_through_the_same_resilient_path(self, tmp_path):
        """`snapshot()` is what engine.py actually calls for a node's
        `blackboard_read` -- it must inherit read()'s behavior, not bypass it."""
        bb = Blackboard(tmp_path)
        bb.write("project", {"mode": "SUBSYSTEM_MODE"}, source="INTAKE")
        snap = bb.snapshot(["project", "absent"])
        assert snap["project"]["value"] == {"mode": "SUBSYSTEM_MODE"}
        assert snap["absent"] is None


# ===========================================================================
# Part B -- the three subsystem topics on the REAL automatic engine path
# ===========================================================================

class _StubAdapter:
    """Returns a fixed AgentResult. The topic refresh happens BEFORE the
    adapter call, so these tests never need a stage to PASS -- which is the
    point: an autonomous run must produce these topics on the way IN to a
    stage, not as a reward for finishing one."""

    def __init__(self):
        self.calls = 0

    def run(self, **kwargs):
        from dv_harness.adapters.base import AgentResult
        self.calls += 1
        return AgentResult(ok=True, text="stub", raw={}, session_id=None)


def _fresh_project():
    """A DVHarness on a fresh temp project carrying the REAL shipped graph,
    so `blackboard_read` declarations are production's own."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    h = DVHarness(tmp)
    h.cfg["degradation"]["probe_resources"] = False
    h.adapter = _StubAdapter()
    return tmp, h


def _topic_entry(root: Path, topic: str):
    p = root / ".dv-harness" / "blackboard" / f"{topic}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _refresh_events(root: Path):
    p = root / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("event") == "BLACKBOARD_TOPIC_REFRESH"]


def _actions(root: Path, topic: str):
    return [r["action"] for ev in _refresh_events(root) for r in ev["topics"]
            if r["topic"] == topic]


def _write_connectivity_config(root: Path, **overrides):
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "rtl" / "dut.sv").write_text("module dut(input clk); endmodule\n", encoding="utf-8")
    cfg = {"rtl_sources": ["rtl/**/*.sv"], "filelists": [], "top_module": "tb_top",
           "monitor_transaction_counts": {"env.usb_agent.monitor": 7},
           "pattern_completed": True}
    cfg.update(overrides)
    p = root / cc.DEFAULT_CONFIG_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class TestRealGraphCoverage:

    def test_every_subsystem_topic_the_real_graph_reads_has_a_producer(self):
        """The coverage claim, checked against the shipped graph rather than
        asserted. A future node declaring one of these topics with no
        producer registered fails here instead of silently reading nothing."""
        graph = GraphDefinition.load(REAL_GRAPH_PATH)
        declared = {t for n in graph.nodes.values()
                    for t in (n.blackboard_read or []) if t in SUBSYSTEM_TOPICS}
        assert declared == SUBSYSTEM_TOPICS, declared
        assert declared <= set(SUBSYSTEM_TOPIC_REFRESHERS), (
            declared - set(SUBSYSTEM_TOPIC_REFRESHERS))

    def test_no_subsystem_topic_is_written_by_any_node_pass_branch(self):
        """Why these three need a producer at all: unlike every other topic,
        no graph node declares them in `blackboard_write`, so
        `_write_blackboard_from_evidence()` can never produce them."""
        graph = GraphDefinition.load(REAL_GRAPH_PATH)
        written = {t for n in graph.nodes.values() for t in (n.blackboard_write or [])}
        assert not (SUBSYSTEM_TOPICS & written), SUBSYSTEM_TOPICS & written


class TestRunStageProducesDeclaredTopics:

    def test_run_stage_produces_the_decisions_topic_with_no_cli_invoked(self):
        """IMPLEMENT declares `open_questions_decisions`. Before this wiring
        the topic existed only if a human had already answered a question
        through the CLI in this project; an empty decision set is itself real
        citable truth ("nothing has been answered yet"), not "no record"."""
        tmp, h = _fresh_project()
        try:
            assert _topic_entry(tmp, "open_questions_decisions") is None
            h.run_stage("goal", stage="IMPLEMENT")

            entry = _topic_entry(tmp, "open_questions_decisions")
            assert entry is not None, "run_stage did not produce the topic it declares it reads"
            assert entry["source"] == "question_queue"
            assert entry["value"]["decision_count"] == 0
            assert _actions(tmp, "open_questions_decisions") == ["MIRRORED_FROM_STORE"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_stage_syncs_an_existing_env_manifest_with_no_cli_invoked(self):
        """ARCH_DISCOVERY declares `env_manifest`. The manifest is produced
        by `dv-harness env-manifest generate`; the engine mirrors the one on
        disk, which is the half an autonomous run could never reach."""
        tmp, h = _fresh_project()
        try:
            manifest_path = tmp / ".dv-harness" / "env.manifest.json"
            env_manifest.generate_and_write(manifest_path)
            assert _topic_entry(tmp, "env_manifest") is None

            h.run_stage("goal", stage="ARCH_DISCOVERY")

            entry = _topic_entry(tmp, "env_manifest")
            assert entry is not None
            assert entry["source"] == "env-manifest"
            # The honesty contract survives the mirror: a NOT_AVAILABLE layer
            # stays NOT_AVAILABLE rather than becoming an empty list.
            assert entry["value"]["vip_config"]["status"] == "NOT_AVAILABLE"
            assert _actions(tmp, "env_manifest") == ["SYNCED_FROM_MANIFEST"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_stage_runs_the_real_connectivity_gates_when_configured(self):
        """VERIFY declares `connectivity_gates`. This is the missing
        "`just connectivity-check` (not `--check-only`) on the real automated
        flow" step: the engine runs the REAL 3-gate recipe, which is the only
        producer of this topic."""
        tmp, h = _fresh_project()
        try:
            _write_connectivity_config(tmp)
            h.run_stage("goal", stage="VERIFY")

            entry = _topic_entry(tmp, "connectivity_gates")
            assert entry is not None
            assert entry["source"] == "connectivity-check"
            assert set(entry["value"]["gates"]) == {
                "gate1_elaboration", "gate2_zero_time_connectivity",
                "gate3_transaction_activity"}
            # A REAL gate run, not a mirror: the runner's own state file and
            # report exist and agree with the topic's fingerprint.
            state = json.loads((tmp / cc.DEFAULT_STATE_RELPATH).read_text(encoding="utf-8"))
            assert entry["value"]["rtl_fingerprint"] == state["rtl_fingerprint"]
            assert (tmp / cc.DEFAULT_REPORT_RELPATH).is_file()
            assert _actions(tmp, "connectivity_gates") == ["GATES_RUN"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_topics_reach_the_stage_prompt_snapshot(self):
        """The consumption half, on the same run: the refreshed topic is in
        the `blackboard.snapshot(node.blackboard_read)` engine.py serializes
        into the stage prompt -- not merely on disk after the fact."""
        tmp, h = _fresh_project()
        try:
            env_manifest.generate_and_write(tmp / ".dv-harness" / "env.manifest.json")
            h.run_stage("goal", stage="IMPLEMENT")

            node = h.graph.nodes["IMPLEMENT"]
            snap = h.blackboard.snapshot(node.blackboard_read)
            assert snap["env_manifest"]["source"] == "env-manifest"
            assert snap["open_questions_decisions"]["source"] == "question_queue"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRefreshIsScopedAndHonest:

    def test_a_node_declaring_none_of_them_produces_none_of_them(self):
        """Driven by the node's own `blackboard_read`, never a hardcoded
        stage list: INTAKE declares none of the three, so it pays for none."""
        tmp, h = _fresh_project()
        try:
            _write_connectivity_config(tmp)
            env_manifest.generate_and_write(tmp / ".dv-harness" / "env.manifest.json")
            h.run_stage("goal", stage="INTAKE")

            for topic in SUBSYSTEM_TOPICS:
                assert _topic_entry(tmp, topic) is None, topic
            assert _refresh_events(tmp) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_unproducible_topic_is_recorded_honestly_never_fabricated(self):
        """No manifest generated and no connectivity config: the topics stay
        ABSENT (nothing is invented) and the real reason plus the real
        producing command land in the audit trail, so "was this topic ever
        produced on this run, and if not why" is answerable from events."""
        tmp, h = _fresh_project()
        try:
            h.run_stage("goal", stage="ARCH_DISCOVERY")
            h.run_stage("goal", stage="BUILD_DEBUG")

            assert _topic_entry(tmp, "env_manifest") is None
            assert _topic_entry(tmp, "connectivity_gates") is None
            reports = [r for ev in _refresh_events(tmp) for r in ev["topics"]]
            manifest_report = next(r for r in reports if r["topic"] == "env_manifest")
            assert manifest_report["action"] == "MANIFEST_NOT_GENERATED"
            assert "env-manifest generate" in manifest_report["produces_it"]
            conn_report = next(r for r in reports if r["topic"] == "connectivity_gates")
            assert conn_report["action"] == "NOT_CONFIGURED"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_broken_producer_never_fails_the_stage(self):
        """Best-effort, like the three sync functions' own writes: a
        schema-invalid manifest on disk is reported and NOT mirrored, and the
        stage still runs (the adapter is still reached)."""
        tmp, h = _fresh_project()
        try:
            (tmp / ".dv-harness" / "env.manifest.json").write_text(
                '{"schema_version": "1.0"}', encoding="utf-8")
            h.run_stage("goal", stage="ARCH_DISCOVERY")

            assert _topic_entry(tmp, "env_manifest") is None, \
                "an invalid manifest must not be mirrored as if it were current truth"
            assert _actions(tmp, "env_manifest") == ["MANIFEST_INVALID"]
            assert h.adapter.calls >= 1, "a failed refresh must not stop the stage"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestConnectivityGatesUseTheExistingStalenessTrigger:

    def test_unchanged_rtl_does_not_pay_for_a_second_gate_run(self):
        tmp, h = _fresh_project()
        try:
            _write_connectivity_config(tmp)
            h.run_stage("goal", stage="VERIFY")
            h.run_stage("goal", stage="VERIFY")
            assert _actions(tmp, "connectivity_gates") == ["GATES_RUN", "UP_TO_DATE"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_changed_rtl_re_runs_the_gates_on_the_next_stage(self):
        """The standing "re-run on every RTL update" recipe, now firing on
        the autonomous path instead of only from a human's `just` invocation.
        Content-hash based, so this is a real content change, not a touch."""
        tmp, h = _fresh_project()
        try:
            _write_connectivity_config(tmp)
            h.run_stage("goal", stage="VERIFY")
            (tmp / "rtl" / "dut.sv").write_text(
                "module dut(input clk, input rst_n); endmodule\n", encoding="utf-8")
            h.run_stage("goal", stage="VERIFY")

            assert _actions(tmp, "connectivity_gates") == ["GATES_RUN", "GATES_RUN"]
            reasons = [r["reason"] for ev in _refresh_events(tmp) for r in ev["topics"]
                       if r["topic"] == "connectivity_gates"]
            assert reasons == ["NEVER_RUN", "RTL_CHANGED"], reasons
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
