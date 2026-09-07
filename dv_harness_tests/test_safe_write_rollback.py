"""Real tests for dv_harness/safe_write_rollback.py -- Safe Write / Rollback
Contract (section 154).

Every test drives the real module functions against a real temp directory
tree (no mocks of the module under test, and no mocked filesystem) -- files
are really written, really backed up, really restored or really deleted on
disk, and every assertion re-reads real bytes off disk afterward rather than
trusting a returned dict.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness import safe_write_rollback as swr


# --- safe_write(): the write itself --------------------------------------------


def test_safe_write_creates_file_and_manifest(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "module m; endmodule\n",
                             actor="agent-1", reason="generate DUT wrapper")
    target = tmp_path / "gen" / "out.sv"
    assert target.is_file()
    assert target.read_text() == "module m; endmodule\n"
    assert record["pre_existed"] is False
    assert record["pre_backup_path"] is None
    assert record["path"] == "gen/out.sv"
    assert record["rollback_applied"] is False

    loaded = swr.read_manifest(tmp_path, record["write_id"])
    assert loaded == record


def test_safe_write_of_existing_file_captures_real_backup(tmp_path):
    target = tmp_path / "cfg" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"v": 1}')

    record = swr.safe_write(tmp_path, "cfg/settings.json", '{"v": 2}',
                             actor="agent-1", reason="bump config version")
    assert record["pre_existed"] is True
    backup = tmp_path / record["pre_backup_path"]
    assert backup.is_file()
    assert backup.read_text() == '{"v": 1}'
    assert target.read_text() == '{"v": 2}'


def test_safe_write_requires_real_attribution(tmp_path):
    with pytest.raises(swr.SafeWriteError):
        swr.safe_write(tmp_path, "a.txt", "x", actor="", reason="r")
    with pytest.raises(swr.SafeWriteError):
        swr.safe_write(tmp_path, "a.txt", "x", actor="agent", reason="   ")


def test_safe_write_refuses_path_escape(tmp_path):
    with pytest.raises(swr.SafeWriteError):
        swr.safe_write(tmp_path, "../outside.txt", "x", actor="agent", reason="r")
    with pytest.raises(swr.SafeWriteError):
        swr.safe_write(tmp_path, "/etc/passwd", "x", actor="agent", reason="r")
    # Nothing should exist outside tmp_path.
    assert not (tmp_path.parent / "outside.txt").exists()


def test_safe_write_refuses_write_id_collision(tmp_path):
    swr.safe_write(tmp_path, "a.txt", "1", actor="agent", reason="r", write_id="SW-fixed")
    with pytest.raises(swr.SafeWriteError):
        swr.safe_write(tmp_path, "b.txt", "2", actor="agent", reason="r", write_id="SW-fixed")


# --- plan_rollback(): read-only, checkable -------------------------------------


def test_plan_rollback_available_for_fresh_write(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="r")
    plan = swr.plan_rollback(tmp_path, record["write_id"])
    assert plan["status"] == swr.STATUS_AVAILABLE
    assert plan["action"] == "delete"  # did not exist before -> undo is delete
    # Read-only: file must be untouched by planning.
    assert (tmp_path / "gen" / "out.sv").read_text() == "content"


def test_plan_rollback_restore_content_action_for_overwrite(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text("old")
    record = swr.safe_write(tmp_path, "cfg.json", "new", actor="a", reason="r")
    plan = swr.plan_rollback(tmp_path, record["write_id"])
    assert plan["status"] == swr.STATUS_AVAILABLE
    assert plan["action"] == "restore_content"


def test_plan_rollback_not_found_for_unknown_write_id(tmp_path):
    # NEGATIVE CONTROL: no evidence on disk -> an honest, distinctly-named
    # NOT_FOUND status, never a fabricated AVAILABLE/UNKNOWN default.
    plan = swr.plan_rollback(tmp_path, "SW-never-existed")
    assert plan["status"] == swr.STATUS_NOT_FOUND


def test_plan_rollback_detects_drift(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="r")
    # Something else (not this module) touches the file afterward.
    (tmp_path / "gen" / "out.sv").write_text("someone else's edit")
    plan = swr.plan_rollback(tmp_path, record["write_id"])
    assert plan["status"] == swr.STATUS_DRIFT_DETECTED


def test_plan_rollback_detects_corrupted_backup(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text("old")
    record = swr.safe_write(tmp_path, "cfg.json", "new", actor="a", reason="r")
    backup = tmp_path / record["pre_backup_path"]
    backup.write_text("tampered")
    plan = swr.plan_rollback(tmp_path, record["write_id"])
    assert plan["status"] == swr.STATUS_BACKUP_CORRUPTED


def test_plan_rollback_detects_manifest_tampering(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="r")
    manifest_path = tmp_path / ".dv-harness" / "safe_write" / "manifests" / f"{record['write_id']}.json"
    import json
    data = json.loads(manifest_path.read_text())
    data["post_digest"] = "0" * 64  # forge the pinned field without recomputing the digest
    manifest_path.write_text(json.dumps(data))
    plan = swr.plan_rollback(tmp_path, record["write_id"])
    assert plan["status"] == swr.STATUS_MANIFEST_TAMPERED


# --- apply_rollback(): the real undo -------------------------------------------


def test_apply_rollback_restores_prior_content(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text("old")
    record = swr.safe_write(tmp_path, "cfg.json", "new", actor="a", reason="update")
    assert target.read_text() == "new"

    result = swr.apply_rollback(tmp_path, record["write_id"], actor="human-1", reason="undo bad config")
    assert target.read_text() == "old"
    assert result["rollback_applied"] is True
    assert result["rollback_actor"] == "human-1"

    # Manifest on disk reflects the rollback too.
    reloaded = swr.read_manifest(tmp_path, record["write_id"])
    assert reloaded["rollback_applied"] is True


def test_apply_rollback_deletes_file_that_did_not_exist_before(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="generate")
    target = tmp_path / "gen" / "out.sv"
    assert target.is_file()

    swr.apply_rollback(tmp_path, record["write_id"], actor="human-1", reason="undo generation")
    assert not target.exists()


def test_apply_rollback_refuses_when_not_found(tmp_path):
    # NEGATIVE CONTROL: no manifest -> refuses, never a silent no-op success.
    with pytest.raises(swr.RollbackRefusedError):
        swr.apply_rollback(tmp_path, "SW-never-existed", actor="human", reason="r")


def test_apply_rollback_refuses_on_drift_and_does_not_touch_the_file(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="r")
    target = tmp_path / "gen" / "out.sv"
    target.write_text("someone else's edit")

    with pytest.raises(swr.RollbackRefusedError):
        swr.apply_rollback(tmp_path, record["write_id"], actor="human", reason="r")
    # NEGATIVE CONTROL: the refusal must be real -- the drifted content must
    # survive untouched, never silently clobbered by a "best effort" restore.
    assert target.read_text() == "someone else's edit"


def test_apply_rollback_refuses_double_apply(tmp_path):
    record = swr.safe_write(tmp_path, "gen/out.sv", "content", actor="a", reason="r")
    swr.apply_rollback(tmp_path, record["write_id"], actor="human", reason="undo")
    with pytest.raises(swr.RollbackRefusedError):
        swr.apply_rollback(tmp_path, record["write_id"], actor="human", reason="undo again")


def test_apply_rollback_requires_real_attribution(tmp_path):
    record = swr.safe_write(tmp_path, "a.txt", "x", actor="a", reason="r")
    with pytest.raises(swr.SafeWriteError):
        swr.apply_rollback(tmp_path, record["write_id"], actor="", reason="r")


def test_two_writes_to_same_path_roll_back_independently(tmp_path):
    """A second safe_write() on the same path must undo to what the FIRST
    write produced, not to the pre-first-write state -- each write_id owns
    its own undo step, like a real per-commit rollback chain."""
    target = tmp_path / "cfg.json"
    target.write_text("v0")
    r1 = swr.safe_write(tmp_path, "cfg.json", "v1", actor="a", reason="first edit")
    r2 = swr.safe_write(tmp_path, "cfg.json", "v2", actor="a", reason="second edit")
    assert target.read_text() == "v2"

    swr.apply_rollback(tmp_path, r2["write_id"], actor="human", reason="undo second")
    assert target.read_text() == "v1"

    swr.apply_rollback(tmp_path, r1["write_id"], actor="human", reason="undo first")
    assert target.read_text() == "v0"


# --- batches: worst-wins composite gate ----------------------------------------


def test_safe_write_batch_tracks_multiple_files_as_one_contract(tmp_path):
    batch = swr.safe_write_batch(
        tmp_path,
        {"cfg/a.json": '{"a": 1}', "cfg/b.json": '{"b": 1}'},
        actor="agent-1", reason="multi-file config change",
    )
    assert len(batch["write_ids"]) == 2
    assert (tmp_path / "cfg" / "a.json").read_text() == '{"a": 1}'
    assert (tmp_path / "cfg" / "b.json").read_text() == '{"b": 1}'


def test_batch_plan_available_when_all_entries_clean(tmp_path):
    batch = swr.safe_write_batch(tmp_path, {"a.txt": "1", "b.txt": "2"},
                                  actor="agent", reason="r")
    plan = swr.plan_rollback_batch(tmp_path, batch["batch_id"])
    assert plan["status"] == swr.STATUS_AVAILABLE
    assert len(plan["entries"]) == 2


def test_batch_plan_worst_wins_one_drifted_file_blocks_whole_batch(tmp_path):
    batch = swr.safe_write_batch(tmp_path, {"a.txt": "1", "b.txt": "2"},
                                  actor="agent", reason="r")
    # Drift only ONE of the two files.
    (tmp_path / "b.txt").write_text("drifted")
    plan = swr.plan_rollback_batch(tmp_path, batch["batch_id"])
    # Worst-wins: one bad entry fails the WHOLE batch verdict, regardless of
    # the other clean entry.
    assert plan["status"] == swr.STATUS_DRIFT_DETECTED


def test_batch_apply_refuses_entirely_if_any_entry_unsafe_nothing_partially_applied(tmp_path):
    batch = swr.safe_write_batch(tmp_path, {"a.txt": "1", "b.txt": "2"},
                                  actor="agent", reason="r")
    (tmp_path / "b.txt").write_text("drifted")

    with pytest.raises(swr.RollbackRefusedError):
        swr.apply_rollback_batch(tmp_path, batch["batch_id"], actor="human", reason="undo")

    # NEGATIVE CONTROL: worst-wins means NEITHER file was touched -- not even
    # the clean one -- because a config change must revert atomically or not
    # at all.
    assert (tmp_path / "a.txt").read_text() == "1"
    assert (tmp_path / "b.txt").read_text() == "drifted"


def test_batch_apply_restores_all_entries_when_clean(tmp_path):
    (tmp_path / "a.txt").write_text("old-a")
    batch = swr.safe_write_batch(tmp_path, {"a.txt": "new-a", "b.txt": "new-b"},
                                  actor="agent", reason="r")
    result = swr.apply_rollback_batch(tmp_path, batch["batch_id"], actor="human", reason="undo")
    assert result["rollback_applied"] is True
    assert (tmp_path / "a.txt").read_text() == "old-a"
    assert not (tmp_path / "b.txt").exists()  # b.txt did not exist before the batch write


def test_batch_plan_not_found_for_unknown_batch_id(tmp_path):
    plan = swr.plan_rollback_batch(tmp_path, "SWB-never-existed")
    assert plan["status"] == swr.STATUS_NOT_FOUND


def test_batch_plan_partially_rolled_back_is_distinct_from_available(tmp_path):
    batch = swr.safe_write_batch(tmp_path, {"a.txt": "1", "b.txt": "2"},
                                  actor="agent", reason="r")
    wids = batch["write_ids"]
    # Roll back only one of the two entries directly (bypassing the batch verb).
    swr.apply_rollback(tmp_path, wids[0], actor="human", reason="partial undo")
    plan = swr.plan_rollback_batch(tmp_path, batch["batch_id"])
    assert plan["status"] == swr.STATUS_PARTIALLY_ROLLED_BACK


# --- listing --------------------------------------------------------------------


def test_list_writes_and_batches(tmp_path):
    assert swr.list_writes(tmp_path) == []
    assert swr.list_batches(tmp_path) == []
    r = swr.safe_write(tmp_path, "a.txt", "1", actor="a", reason="r")
    b = swr.safe_write_batch(tmp_path, {"c.txt": "1"}, actor="a", reason="r")
    assert r["write_id"] in swr.list_writes(tmp_path)
    assert b["batch_id"] in swr.list_batches(tmp_path)


# --- vocabulary hygiene -----------------------------------------------------


def test_status_vocabulary_disjoint_from_models_status():
    from dv_harness.models import Status
    verdict_tokens = {m.value for m in Status}
    ours = {
        swr.STATUS_AVAILABLE, swr.STATUS_ALREADY_ROLLED_BACK, swr.STATUS_DRIFT_DETECTED,
        swr.STATUS_BACKUP_CORRUPTED, swr.STATUS_MANIFEST_TAMPERED, swr.STATUS_NOT_FOUND,
        swr.STATUS_PARTIALLY_ROLLED_BACK,
    }
    assert not (ours & verdict_tokens)


# --- CLI front door --------------------------------------------------------------


def test_cli_write_plan_apply_round_trip(tmp_path, capsys):
    content_file = tmp_path / "src_content.txt"
    content_file.write_text("hello world")

    rc = swr.execute_verb(["--root", str(tmp_path), "write",
                            "--path", "gen/out.txt", "--content-file", str(content_file),
                            "--actor", "agent-1", "--reason", "generate"])
    assert rc == 0
    out = capsys.readouterr().out
    import json
    record = json.loads(out)
    assert (tmp_path / "gen" / "out.txt").read_text() == "hello world"

    rc = swr.execute_verb(["--root", str(tmp_path), "plan", "--write-id", record["write_id"]])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == swr.STATUS_AVAILABLE

    rc = swr.execute_verb(["--root", str(tmp_path), "apply", "--write-id", record["write_id"],
                            "--actor", "human-1", "--reason", "undo"])
    assert rc == 0
    assert not (tmp_path / "gen" / "out.txt").exists()


def test_cli_apply_refuses_and_returns_nonzero_when_unknown(tmp_path, capsys):
    rc = swr.execute_verb(["--root", str(tmp_path), "apply", "--write-id", "SW-nope",
                            "--actor", "human", "--reason", "r"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out
