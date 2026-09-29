"""Phase 11 (Regression Integration) + Phase 12 (Large Artifact Policy) +
Phase 19 (Security) gap-closure tests, 2026-09-04.

Every test here asserts REAL behavior of the real write path -- what actually
lands on disk in `.dv-harness/memory/**/<memory_id>.json`, what a real
`bjobs`-driven reconcile writes, and what the real periodic snapshot renders --
not that a module imports or a helper returns a shape.

The three gaps these close, as found by the audit that preceded them:
  * Phase 19: `memory_security.py`'s detector was wired ONLY into the Markdown
    vault mirror. The durable JSON store (`memory.MemoryStore.add()`, the
    system of record, and the ONLY store WORKING_MEMORY ever reaches) never
    called it.
  * Phase 12: no write-time size/content gate existed anywhere -- the "never
    embed a raw log/FSDB" rule held by writer discipline plus a post-hoc scan
    that only ever walked the Markdown vault tree.
  * Phase 11: `confidence` on every Job Memory record was the literal string
    "UNKNOWN", and `failure_signature`/`prior_related_knowledge` were surfaced
    by no per-job view anywhere.
"""

import json
import socket
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness import lsf_client, memory_security, regression_reporter
from dv_harness.knowledge_center import RESULT_MARKER
from dv_harness.memory import CornerCaseLibrary, MemoryStore, OrganizationalMemoryStore
from dv_harness.memory_artifact_policy import (
    EmbeddedArtifactError,
    MAX_RECORD_FIELD_CHARS,
    MAX_RECORD_FIELD_LINES,
    build_evidence_reference,
    enforce_record_artifact_policy,
)
from dv_harness.memory_router import route_and_store
from dv_harness_tests.organizational_promotion_fixture import admitted_organizational_record

VC_PASSWORD_LINE = "run it with VCPW=Sup3rSecret!pw on vchost-a"
SSH_KEY_BLOCK = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEAxLEAKEDKEYMATERIALxLEAKEDKEYMATERIALxLEAKED\n"
    "-----END RSA PRIVATE KEY-----"
)


def _record_on_disk(root: Path, level: str, memory_id: str) -> dict:
    """Read the record straight off disk, not through MemoryStore.get() --
    the point of these tests is what was PERSISTED, so a bug that redacted
    only the returned copy would still fail here."""
    return json.loads((root / ".dv-harness" / "memory" / level / f"{memory_id}.json")
                      .read_text(encoding="utf-8"))


KC_CFG = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                "vchost": "vchost-b", "vchop": "host-c"}}


class _FakeKnowledgeCenterRelay:
    """A real local relay server standing in for the Linux-server Knowledge
    Center broker, so the assertions below are about the payload that
    genuinely went ONTO THE WIRE -- not about what a mocked
    `KnowledgeCenterClient.add()` was handed.

    That distinction is the whole point for Phase 19: the audited gap was
    that a raw record reached `KnowledgeCenterClient.add()` and from there
    the shared, cross-user broker. Asserting on the serialized `put` payload
    the transport actually uploaded is the only assertion that proves the
    record crossing the machine boundary is the redacted one.

    Same transport-level pattern already used by
    test_memory_tier_completion.py and test_knowledge_center.py -- reused
    rather than re-invented so all three exercise one transport.
    """

    def __init__(self, monkeypatch, localappdata: Path):
        monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
        remote_dir = str(Path(__file__).resolve().parents[1] / "tools" / "remote")
        if remote_dir not in sys.path:
            sys.path.insert(0, remote_dir)
        self.received = []
        self._sock = None
        self._thread = None

    def start(self, responses):
        from remote_relay import info_path

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(len(responses))
        port = self._sock.getsockname()[1]

        def _serve():
            for resp in responses:
                conn, _ = self._sock.accept()
                buf = b""
                while b"\n" not in buf:
                    buf += conn.recv(65536)
                req = json.loads(buf.decode("utf-8"))
                if req.get("op") == "put":
                    try:
                        req["_local_content"] = Path(req["local"]).read_text(encoding="utf-8")
                    except OSError:
                        req["_local_content"] = None
                self.received.append(req)
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                conn.close()

        self._thread = threading.Thread(target=_serve)
        self._thread.start()

        p = info_path("vchost-b", "host-c")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"host": "127.0.0.1", "port": port, "token": "tok",
                                  "pid": 1, "started": "2026-09-01T00:00:00"}), encoding="utf-8")
        return self

    def stop(self):
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._sock is not None:
            self._sock.close()

    @property
    def pushed_record(self) -> dict:
        """The `record` block of the add payload the transport uploaded."""
        put = next(r for r in self.received if r.get("op") == "put")
        return json.loads(put["_local_content"])["record"]

    @staticmethod
    def ok_add_responses(memory_id: str = "KC-1"):
        return [
            {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
            {"ok": True, "exit_code": 0,
             "stdout": f'{RESULT_MARKER}{{"memory_id": "{memory_id}"}}\n', "error": ""},  # run
        ]


def organizational_record(root, **extra):
    """A methodology record that really reaches the ORGANIZATIONAL_MEMORY
    branch. Since 2026-09-04 that branch is gated
    (memory_router.organizational_admission_gate), so a record without real
    promotion provenance is demoted to Working Memory and never touches the
    shared broker at all -- which would silently turn every guard assertion
    below into a test of the WORKING_MEMORY path instead."""
    return admitted_organizational_record(
        root, kind="methodology", protocol="USB3",
        title="Reconcile every LSF job's sim.log epilogue before calling a batch clean",
        **extra)


class TestPhase19OrganizationalMemoryIsGuardedBeforeTheSharedPush:
    """The audited Phase 19 gap (2026-09-04): ORGANIZATIONAL_MEMORY -- the
    ONE tier whose only backing store is the shared, cross-user Knowledge
    Center on the Linux server -- bypassed both write-time guards.
    `route_and_store()`'s ORGANIZATIONAL_MEMORY branch called
    `OrganizationalMemoryStore.add()`, which forwarded the caller's record
    verbatim to `KnowledgeCenterClient.add()`; nothing on that path called
    `redact_record()` or `enforce_record_artifact_policy()`. So the most
    exposed destination in the system was the least protected one, and at the
    time it was reachable by any caller: `route_memory()` sent any
    methodology/best_practice/cross_project_lesson record with
    `verified: True` straight there. That second half was closed separately on
    2026-09-04 by `organizational_admission_gate()` (which is why every test
    below now builds its record through `organizational_record()`); the guard
    these tests cover still has to hold for every record that DOES clear it.
    """

    def test_a_secret_never_reaches_the_shared_broker_over_the_wire(self, tmp_path, monkeypatch):
        relay = _FakeKnowledgeCenterRelay(monkeypatch, tmp_path / "localappdata")
        relay.start(_FakeKnowledgeCenterRelay.ok_add_responses())
        try:
            result = route_and_store(
                tmp_path,
                organizational_record(tmp_path, lesson=VC_PASSWORD_LINE,
                                      evidence={"how": SSH_KEY_BLOCK}),
                cfg=KC_CFG)
        finally:
            relay.stop()

        assert result["destination"] == "ORGANIZATIONAL_MEMORY"
        pushed = relay.pushed_record
        # The payload that crossed the machine boundary carries neither
        # secret, at either nesting depth.
        serialized = json.dumps(pushed)
        assert "Sup3rSecret!pw" not in serialized
        assert "LEAKEDKEYMATERIAL" not in serialized
        assert "***REDACTED-VC_PASSWORD***" in pushed["lesson"]
        assert "***REDACTED-SSH_PRIVATE_KEY***" in pushed["evidence"]["how"]
        # ...and says so, rather than silently mutating the record.
        assert pushed["secrets_redacted"] is True
        assert set(pushed["secrets_redacted_types"]) == {"vc_password", "ssh_private_key"}

    def test_a_giant_log_is_truncated_with_disclosure_before_the_shared_push(
            self, tmp_path, monkeypatch):
        """CLAUDE.md: never store giant logs in a memory record. Enforced on
        this path too now, not only on the local JSON tiers."""
        blob = "\n".join(f"UVM_INFO sim.log line {i}" for i in range(MAX_RECORD_FIELD_LINES * 3))
        blob += "\nUVM_FATAL = 1, UVM_ERROR = 12"

        relay = _FakeKnowledgeCenterRelay(monkeypatch, tmp_path / "localappdata")
        relay.start(_FakeKnowledgeCenterRelay.ok_add_responses())
        try:
            route_and_store(tmp_path, organizational_record(tmp_path, lesson=blob), cfg=KC_CFG)
        finally:
            relay.stop()

        pushed = relay.pushed_record
        assert len(pushed["lesson"].splitlines()) < MAX_RECORD_FIELD_LINES
        assert len(pushed["lesson"]) <= MAX_RECORD_FIELD_CHARS
        assert "lines removed by the Phase 12 large-artifact policy" in pushed["lesson"]
        # the sim.log epilogue (the tail) survives -- head-only truncation
        # would throw away the PASS/FAIL verdict
        assert "UVM_FATAL = 1, UVM_ERROR = 12" in pushed["lesson"]
        assert pushed["large_artifact_truncated"]

    def test_embedded_waveform_content_hard_rejects_and_nothing_is_pushed(self, tmp_path):
        """A HARD REJECT, not a repair: the push must never happen at all,
        so no transport contact is made and no partial record lands on the
        shared server."""
        vcd = "$enddefinitions $end\n#0\n$dumpvars\n1!\n0\"\n"
        with patch("dv_harness.knowledge_center.KnowledgeCenterClient.add") as kc_add:
            with pytest.raises(EmbeddedArtifactError):
                route_and_store(tmp_path, organizational_record(tmp_path, lesson=vcd), cfg=KC_CFG)
        kc_add.assert_not_called()

    def test_the_store_guards_even_when_called_directly_not_through_the_router(self, tmp_path):
        """`OrganizationalMemoryStore.add()` is the chokepoint, so a caller
        that constructs the store itself (as cli.py/dashboard.py-style call
        sites do for every other KnowledgeCenterClient consumer) is covered
        too -- the guard is not a router-branch-only patch."""
        with patch("dv_harness.knowledge_center.KnowledgeCenterClient.add",
                    return_value={"ok": True, "memory_id": "KC-9"}) as kc_add:
            OrganizationalMemoryStore(tmp_path, cfg=KC_CFG).add(
                organizational_record(tmp_path, lesson=VC_PASSWORD_LINE))
        _category, _protocol, forwarded = kc_add.call_args[0]
        assert "Sup3rSecret!pw" not in json.dumps(forwarded)
        assert forwarded["secrets_redacted_types"] == ["vc_password"]
        # protocol routing still comes off the record, unchanged by guarding
        assert _protocol == "USB3"

    def test_the_vault_mirror_carries_the_same_guarded_content_that_was_pushed(
            self, tmp_path, monkeypatch):
        """Every other vault-write-through destination mirrors the guarded
        record `MemoryStore.add()` returns. This one had no local store to
        return one, so before the fix its Markdown note was rendered from the
        RAW record -- a giant log truncated out of the shared push would have
        survived in full inside the vault note."""
        blob = "\n".join(f"UVM_INFO sim.log line {i}" for i in range(MAX_RECORD_FIELD_LINES * 3))
        cfg = {**KC_CFG, "memory": {"vault_root": str(tmp_path / "vault"), "git_enabled": False}}

        relay = _FakeKnowledgeCenterRelay(monkeypatch, tmp_path / "localappdata")
        relay.start(_FakeKnowledgeCenterRelay.ok_add_responses())
        try:
            with patch("dv_harness.memory_router._maybe_write_vault_note") as vault_note:
                vault_note.return_value = {"ok": True}
                route_and_store(tmp_path, organizational_record(tmp_path, lesson=blob), cfg=cfg)
        finally:
            relay.stop()

        mirrored = vault_note.call_args[0][3]
        assert mirrored["lesson"] == relay.pushed_record["lesson"]
        assert mirrored["large_artifact_truncated"]

    def test_guarding_an_already_guarded_record_changes_nothing(self, tmp_path):
        """The router rebinds `record` to the guarded form and the store
        guards again -- this must be a no-op, never a double-redaction that
        wraps `***REDACTED-VC_PASSWORD***` inside another marker."""
        from dv_harness.memory import _guard_record_before_write

        once = _guard_record_before_write(organizational_record(tmp_path, lesson=VC_PASSWORD_LINE))
        twice = _guard_record_before_write(dict(once))
        assert twice == once
        assert once["lesson"].count("***REDACTED-") == 1


class TestPhase19SecretRedactionAtTheJsonStore:
    def test_secret_in_a_working_memory_field_is_redacted_on_disk(self, tmp_path):
        """WORKING_MEMORY is the tier with NO vault mirror at all
        (memory_router._VAULT_WRITE_THROUGH_DESTINATIONS excludes it), so
        before this gate a react-loop hypothesis carrying a password was
        written verbatim and scanned by nothing, ever."""
        store = MemoryStore(tmp_path)
        mem = store.add("working", {
            "memory_id": "WM-1", "kind": "react_reasoning_step",
            "hypothesis": VC_PASSWORD_LINE,
        })

        on_disk = _record_on_disk(tmp_path, "working", "WM-1")
        assert "Sup3rSecret!pw" not in json.dumps(on_disk)
        assert "***REDACTED-VC_PASSWORD***" in on_disk["hypothesis"]
        assert on_disk["hypothesis"].startswith("run it with VCPW=")  # key name kept legible
        assert on_disk["secrets_redacted"] is True
        assert on_disk["secrets_redacted_types"] == ["vc_password"]
        assert mem["hypothesis"] == on_disk["hypothesis"]  # returned copy matches disk

    def test_secret_nested_in_a_list_of_dicts_is_redacted(self, tmp_path):
        """A job record's `prior_related_knowledge` is a LIST of related-case
        dicts -- a top-level-only scan would miss every one of them."""
        MemoryStore(tmp_path).add("job", {
            "memory_id": "JOB-NESTED", "kind": "job_failure",
            "prior_related_knowledge": [
                {"note_id": "N1", "frontmatter": {"summary": VC_PASSWORD_LINE}},
            ],
        })
        on_disk = _record_on_disk(tmp_path, "job", "JOB-NESTED")
        assert "Sup3rSecret!pw" not in json.dumps(on_disk)
        assert ("***REDACTED-VC_PASSWORD***"
                in on_disk["prior_related_knowledge"][0]["frontmatter"]["summary"])

    def test_ssh_private_key_block_is_redacted_whole(self, tmp_path):
        MemoryStore(tmp_path).add("engineering", {
            "memory_id": "ENG-KEY", "root_cause": f"login broke:\n{SSH_KEY_BLOCK}",
        })
        on_disk = _record_on_disk(tmp_path, "engineering", "ENG-KEY")
        assert "LEAKEDKEYMATERIAL" not in json.dumps(on_disk)
        assert "BEGIN RSA PRIVATE KEY" not in json.dumps(on_disk)
        assert "***REDACTED-SSH_PRIVATE_KEY***" in on_disk["root_cause"]

    def test_memory_id_is_never_mangled_by_redaction(self, tmp_path):
        """A license-key-SHAPED id (grouped hex blocks) matches a real
        detector pattern; rewriting it would break the upsert key every index
        row, vault note id and second poll depends on."""
        looks_like_a_license_key = "ABCD-1234-EF56-7890"
        MemoryStore(tmp_path).add("job", {"memory_id": looks_like_a_license_key})
        assert MemoryStore(tmp_path).get(looks_like_a_license_key) is not None

    def test_redaction_is_idempotent_across_repeated_upserts(self, tmp_path):
        """mark_used()/deprecate()/a second reconcile poll all re-add() the
        same record; an already-redacted marker must never be re-wrapped."""
        store = MemoryStore(tmp_path)
        store.add("job", {"memory_id": "JOB-IDEM", "note": VC_PASSWORD_LINE})
        first = _record_on_disk(tmp_path, "job", "JOB-IDEM")["note"]
        store.mark_used("JOB-IDEM")
        store.mark_used("JOB-IDEM")
        assert _record_on_disk(tmp_path, "job", "JOB-IDEM")["note"] == first
        assert first.count("REDACTED") == 1

    def test_clean_record_is_untouched_and_unstamped(self, tmp_path):
        MemoryStore(tmp_path).add("project", {
            "memory_id": "PRJ-CLEAN", "title": "USB LFPS handshake topology",
            "root_cause": "polling.LFPS burst count below spec minimum",
        })
        on_disk = _record_on_disk(tmp_path, "project", "PRJ-CLEAN")
        assert on_disk["root_cause"] == "polling.LFPS burst count below spec minimum"
        assert "secrets_redacted" not in on_disk
        assert "large_artifact_truncated" not in on_disk

    def test_corner_case_library_add_is_guarded_too(self, tmp_path):
        """CCL records bypass MemoryStore entirely AND are pushed to the
        shared cross-user Knowledge Center, so an unguarded add() there is a
        cross-user leak path."""
        lib = CornerCaseLibrary(tmp_path)
        rec = lib.add({
            "ccl_id": "CCL-SEC", "corner_id": "usb_reset_race",
            "category": "reset_power", "risk_tier": "P1",
            "description": VC_PASSWORD_LINE,
        })
        assert "Sup3rSecret!pw" not in json.dumps(rec)
        on_disk = json.loads((tmp_path / ".dv-harness" / "memory" / "corner_case_library"
                              / "CCL-SEC.json").read_text(encoding="utf-8"))
        assert "***REDACTED-VC_PASSWORD***" in on_disk["description"]

    def test_redact_record_reports_a_dotted_field_path(self):
        _out, findings = memory_security.redact_record(
            {"evidence": {"cases": [{"detail": VC_PASSWORD_LINE}]}})
        assert [f["field"] for f in findings] == ["evidence.cases[0].detail"]
        assert "Sup3rSecret!pw" not in json.dumps(findings)  # the finding is not itself a leak


class TestPhase12WriteTimeLargeArtifactGate:
    def test_embedded_binary_content_is_hard_rejected(self, tmp_path):
        with pytest.raises(EmbeddedArtifactError):
            MemoryStore(tmp_path).add("job", {"memory_id": "JOB-BIN",
                                               "evidence": "fsdb bytes: \x00\x01\x02"})
        assert not (tmp_path / ".dv-harness" / "memory" / "job" / "JOB-BIN.json").exists()

    def test_embedded_vcd_dump_is_hard_rejected(self, tmp_path):
        vcd = "$enddefinitions $end\n#0\n$dumpvars\n0!\n1\"\n#10\n1!\n"
        with pytest.raises(EmbeddedArtifactError):
            MemoryStore(tmp_path).add("job", {"memory_id": "JOB-VCD", "evidence": vcd})

    def test_pasted_sim_log_body_is_truncated_and_stamped(self, tmp_path):
        """A raw sim.log body is legitimate CONTENT in the wrong PLACE: it is
        bounded and recorded, not silently dropped and not silently kept."""
        body = ("\n".join(f"UVM_INFO line {i}" for i in range(5000))
                + "\nUVM_FATAL = 1, UVM_ERROR = 5, UVM_WARNING = 0\nVERDICT: FAILED\n")
        assert len(body) > MAX_RECORD_FIELD_CHARS
        MemoryStore(tmp_path).add("job", {"memory_id": "JOB-LOG", "evidence": body})

        on_disk = _record_on_disk(tmp_path, "job", "JOB-LOG")
        stored = on_disk["evidence"]
        assert len(stored) < len(body)
        assert len(stored.splitlines()) <= MAX_RECORD_FIELD_LINES + 4
        assert "large-artifact policy" in stored
        assert stored.startswith("UVM_INFO line 0")
        # the UVM epilogue lives at the END of a sim.log -- a head-only
        # truncation would throw away the single most useful line
        assert "VERDICT: FAILED" in stored
        assert on_disk["large_artifact_truncated"][0]["field"] == "evidence"
        assert on_disk["large_artifact_truncated"][0]["original_chars"] == len(body)

    def test_a_long_path_reference_is_never_truncated(self, tmp_path):
        """The policy must not fire on the thing it is telling writers to do
        instead -- citing a path."""
        long_path = "/proj/" + "deep_dir/" * 200 + "sim.log"
        assert len(long_path) < MAX_RECORD_FIELD_CHARS
        MemoryStore(tmp_path).add("job", {"memory_id": "JOB-PATH", "sim_log": long_path})
        on_disk = _record_on_disk(tmp_path, "job", "JOB-PATH")
        assert on_disk["sim_log"] == long_path
        assert "large_artifact_truncated" not in on_disk

    def test_secrets_are_redacted_before_truncation_not_after(self, tmp_path):
        """Ordering matters for real: truncating first can split a multi-line
        PEM block so its BEGIN/END-anchored pattern no longer matches, leaving
        real key material in the surviving text."""
        filler = "\n".join(f"UVM_INFO line {i}" for i in range(5000))
        MemoryStore(tmp_path).add("job", {
            "memory_id": "JOB-BOTH", "evidence": f"{SSH_KEY_BLOCK}\n{filler}"})
        on_disk = _record_on_disk(tmp_path, "job", "JOB-BOTH")
        assert "LEAKEDKEYMATERIAL" not in json.dumps(on_disk)
        assert on_disk["secrets_redacted"] is True
        assert on_disk["large_artifact_truncated"]

    def test_enforce_record_artifact_policy_leaves_a_normal_record_value_equal(self):
        record = {"memory_id": "M1", "root_cause": "clock domain crossing",
                   "evidence": {"sim_log": "/proj/run/sim.log"}, "counts": [1, 2, 3]}
        out, report = enforce_record_artifact_policy(record)
        assert out == record
        assert report == {"truncated_fields": []}


class TestPhase12EvidenceReferenceBlock:
    def test_paths_and_ids_only_absent_keys_omitted(self):
        assert build_evidence_reference(sim_log="/proj/run/sim.log", lsf_job=123) == {
            "sim_log": "/proj/run/sim.log", "lsf_job": 123}

    def test_a_log_body_handed_in_place_of_a_path_is_rejected(self):
        with pytest.raises(EmbeddedArtifactError):
            build_evidence_reference(sim_log="UVM_ERROR: bad\nUVM_FATAL: worse\n")

    def test_an_oversized_reference_is_rejected(self):
        with pytest.raises(EmbeddedArtifactError):
            build_evidence_reference(fsdb="x" * 5000)


def _job(root: Path, jid: int, **fields) -> Path:
    state = lsf_client.JobState(job_id=jid, **fields)
    lsf_client.save_job_state(root, state)
    return root / ".dv-harness" / "lsf" / "jobs" / f"{jid}.json"


def _write_sim_log(root: Path, name: str, *, uvm_fatal: int, uvm_error: int, verdict: str) -> Path:
    log = root / name
    log.write_text(
        "".join(f"UVM_ERROR: mismatch {i}\n" for i in range(uvm_error))
        + "FINAL CHECK @ 1000 ns\n"
        + f"UVM_FATAL = {uvm_fatal}, UVM_ERROR = {uvm_error}, UVM_WARNING = 0\n"
        + f"VERDICT: {verdict}\n",
        encoding="utf-8")
    return log


def _reconcile_terminal(root: Path, jid: int):
    """The FIRST real writer: bjobs-only reconcile, before any sim.log
    epilogue has been parsed. bjobs is mocked at the subprocess-wrapper
    boundary only -- everything downstream of it is the production path."""
    with patch("dv_harness.lsf_client._run_bjobs",
               return_value={"RECORDS": [{"JOBID": str(jid), "STAT": "EXIT"}]}):
        lsf_client.reconcile_batch(root, [jid])


def _full_reconciliation_cycle(root: Path, jid: int):
    """The SECOND real writer: `run_reconciliation_cycle()`, which parses the
    job's real sim.log epilogue, sets a determinate sim_status from it, and
    re-upserts the same Job-tier memory record with that better evidence.
    This is the only production path that ever produces a job record backed by
    all three independent evidence sources."""
    with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
               return_value=[{"job_id": jid, "stat": "EXIT", "job_name": "usb_lfps"}]), \
         patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
               return_value={"RECORDS": [{"JOBID": str(jid), "STAT": "EXIT"}]}):
        return regression_reporter.run_reconciliation_cycle(root, "vcuser1", root / "uvm")


class TestPhase11JobMemoryConfidenceAndColumns:
    def test_confidence_is_computed_from_real_evidence_not_left_unknown(self, tmp_path):
        log = _write_sim_log(tmp_path, "sim_900.log", uvm_fatal=1, uvm_error=5, verdict="FAILED")
        _job(tmp_path, 900, pattern="usb_lfps", sim_log=str(log))
        _full_reconciliation_cycle(tmp_path, 900)

        rec = MemoryStore(tmp_path).get(lsf_client.job_tier_memory_id(900))
        assert rec["kind"] == "job_failure"
        assert rec["confidence"] == "HIGH"        # 3 independent sources + verified refs
        assert rec["confidence"] != "UNKNOWN"
        basis = rec["confidence_basis"]
        assert basis["inputs"] == {
            "independent_sources_count": 3, "evidence_refs_verified": True,
            "counter_evidence_count": 0, "multi_agent_consensus_count": 0}
        assert basis["score"] == 8

    def test_thin_evidence_scores_low_rather_than_claiming_confidence(self, tmp_path):
        """A job LSF says finished, with no log path, no verdict and no
        markers, must not score the same as a fully-evidenced failure."""
        _job(tmp_path, 901, pattern="usb_lfps")
        _reconcile_terminal(tmp_path, 901)
        rec = MemoryStore(tmp_path).get(lsf_client.job_tier_memory_id(901))
        assert rec["confidence"] == "LOW"
        assert rec["confidence_basis"]["inputs"]["independent_sources_count"] == 1
        assert rec["confidence_basis"]["inputs"]["evidence_refs_verified"] is False

    def test_a_cited_sim_log_that_does_not_exist_is_not_counted_as_verified(self, tmp_path):
        _job(tmp_path, 902, pattern="usb_lfps", sim_log=str(tmp_path / "swept_away.log"),
             uvm_fatal_count=1)
        _reconcile_terminal(tmp_path, 902)
        rec = MemoryStore(tmp_path).get(lsf_client.job_tier_memory_id(902))
        assert rec["confidence_basis"]["inputs"]["evidence_refs_verified"] is False

    def test_a_pass_verdict_contradicted_by_a_fatal_marker_caps_confidence(self, tmp_path):
        """CLAUDE.md's "LSF DONE is not equal to DV PASS" hazard in reverse:
        a real epilogue declaring VERDICT: PASSED while also declaring
        UVM_FATAL = 1 is genuine counter-evidence, and score_confidence()'s
        own safety floor must cap the level below HIGH."""
        log = _write_sim_log(tmp_path, "sim_903.log", uvm_fatal=1, uvm_error=0, verdict="PASSED")
        _job(tmp_path, 903, pattern="usb_lfps", sim_log=str(log))
        _full_reconciliation_cycle(tmp_path, 903)

        rec = MemoryStore(tmp_path).get(lsf_client.job_tier_memory_id(903))
        assert rec["dv_result"] == "PASS" and rec["uvm_fatal_count"] == 1
        assert rec["confidence_basis"]["inputs"]["counter_evidence_count"] == 1
        # Same three evidence sources as the fully-consistent FAILED job above
        # (which scores 8 -> HIGH); the counter-evidence penalty alone takes
        # this one to 5 -> MEDIUM.
        assert rec["confidence_basis"]["score"] == 5
        assert rec["confidence"] == "MEDIUM"

    def test_evidence_reference_block_is_written_with_paths_only(self, tmp_path):
        log = _write_sim_log(tmp_path, "sim_904.log", uvm_fatal=1, uvm_error=0, verdict="FAILED")
        _job(tmp_path, 904, pattern="usb_lfps", sim_log=str(log), run_dir=str(tmp_path),
             fsdb_path="/proj/run/usb_lfps.fsdb")
        _full_reconciliation_cycle(tmp_path, 904)

        rec = MemoryStore(tmp_path).get(lsf_client.job_tier_memory_id(904))
        assert rec["evidence"] == {
            "sim_log": str(log), "fsdb": "/proj/run/usb_lfps.fsdb",
            "lsf_job": 904, "run_dir": str(tmp_path)}
        # no coverage producer exists in this repo -- the key is OMITTED, never
        # written as a null that would look like coverage was captured
        assert "coverage" not in rec["evidence"]

    def test_snapshot_table_carries_signature_confidence_and_prior_columns(self, tmp_path):
        log = _write_sim_log(tmp_path, "sim_905.log", uvm_fatal=1, uvm_error=5, verdict="FAILED")
        _job(tmp_path, 905, pattern="usb_lfps", sim_log=str(log))
        _full_reconciliation_cycle(tmp_path, 905)
        # a real prior-knowledge hit, written onto the same record the way a
        # real vault search would
        store = MemoryStore(tmp_path)
        rec = store.get(lsf_client.job_tier_memory_id(905))
        rec["prior_related_knowledge"] = [{"note_id": "N1"}, {"note_id": "N2"}]
        store.add("job", rec)

        rows = regression_reporter.attach_job_memory_columns(
            tmp_path, [lsf_client.to_snapshot_row(lsf_client.load_job_state(tmp_path, 905),
                                                   agent_action="monitoring")])
        assert rows[0]["failure_signature"] == "EXIT/FATAL=1/ERR=5"
        assert rows[0]["confidence"] == "HIGH"
        assert rows[0]["prior_related_knowledge_count"] == 2

        snapshot = regression_reporter.render_snapshot(rows)
        header = next(line for line in snapshot.splitlines() if line.startswith("Job "))
        for column in ("Confidence", "Failure Signature", "Prior"):
            assert column in header
        job_line = next(line for line in snapshot.splitlines() if line.startswith("905"))
        assert "EXIT/FATAL=1/ERR=5" in job_line
        assert "HIGH" in job_line
        assert job_line.split()[-2] == "2"  # Prior column, just before the action column

    def test_a_job_with_no_memory_record_renders_dashes_not_a_fabricated_level(self, tmp_path):
        _job(tmp_path, 906, pattern="usb_lfps")
        rows = regression_reporter.attach_job_memory_columns(
            tmp_path, [lsf_client.to_snapshot_row(lsf_client.load_job_state(tmp_path, 906),
                                                   agent_action="monitoring")])
        assert "confidence" not in rows[0]
        job_line = next(line for line in regression_reporter.render_snapshot(rows).splitlines()
                        if line.startswith("906"))
        # Confidence / Failure Signature / Prior all render '-' ("not
        # computed"), never an invented level.
        assert job_line.split()[-4:] == ["-", "-", "-", "monitoring"]

    def test_to_snapshot_row_without_job_memory_keeps_its_original_shape(self, tmp_path):
        _job(tmp_path, 907, pattern="usb_lfps")
        row = lsf_client.to_snapshot_row(lsf_client.load_job_state(tmp_path, 907),
                                          agent_action="monitoring")
        assert set(row) == {"job_id", "pattern", "lsf_status", "dv_analysis_status",
                             "uvm_error_count", "uvm_fatal_count", "agent_action", "note"}

    def test_format_failure_signature_omits_absent_and_zero_fields(self):
        assert lsf_client.format_failure_signature(None) is None
        assert lsf_client.format_failure_signature(
            {"lsf_status": "DONE", "uvm_fatal_count": 0, "uvm_error_count": 0,
             "assertion_failure": True}) == "DONE/assert"
