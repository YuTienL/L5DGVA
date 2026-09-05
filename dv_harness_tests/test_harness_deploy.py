"""Tests for dv_harness/harness_deploy.py -- the harness-to-remote-Agent-path
deployment mechanism.

Every test here runs against a real filesystem (tmp_path) or against this
repo's own real checkout. NOT ONE of them can reach the network: the two
remote-side sources are a local directory and a local transcript file, and the
only code path that would invoke `remote_exec.py` is exercised through an
injected `run_fn`. That is a property of the module's design (execute defaults
to False), asserted explicitly by
`test_apply_via_remote_exec_does_not_execute_by_default`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import harness_deploy as hd  # noqa: E402


# ---- Fixtures ---------------------------------------------------------------

@pytest.fixture
def manifest():
    return hd.DeployManifest(
        include=["dv_harness/**/*.py", ".claude/agents/**/*.md", "CLAUDE.md"],
        exclude=["**/__pycache__/**", "**/*.pyc"],
        never_sync=["replay.ps1", "**/.env", "**/*.pem"],
        remote_deployment_root="/home/svcacct/AI/Agent",
        manifest_version="1.0",
    )


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def fake_project(tmp_path, manifest):
    """A miniature harness checkout matching `manifest`'s include globs."""
    src = tmp_path / "pc"
    _write(src, "CLAUDE.md", "# harness rules\n")
    _write(src, "dv_harness/engine.py", "ENGINE = 1\n")
    _write(src, "dv_harness/gates.py", "GATES = 1\n")
    _write(src, ".claude/agents/debug-agent.md", "# debug agent\n")
    _write(src, "dv_harness/__pycache__/engine.cpython-311.pyc", "junk")
    return src


# ---- The shipped manifest is real and honest --------------------------------

def test_shipped_manifest_loads_and_declares_the_real_deployment_path():
    m = hd.load_manifest()
    assert m.remote_deployment_root == "/home/svcacct/AI/Agent"
    assert m.include, "the shipped manifest must declare what the harness is"


def test_shipped_manifest_covers_the_four_things_policy_names():
    """USAGE_MULTI_USER_SAFETY.md's policy is about the harness ENGINE plus its
    skills/agents. A manifest that silently dropped one of them would sync a
    half-harness that imports but misbehaves."""
    m = hd.load_manifest()
    joined = " ".join(m.include)
    for required in ("dv_harness/", ".claude/skills/", ".claude/agents/", "CLAUDE.md"):
        assert required in joined, f"shipped manifest never mentions {required}"


def test_shipped_manifest_excludes_per_project_runtime_state():
    """`.dv-harness/` is one user's run state (state.json, events.jsonl,
    memory, evidence DB). USAGE_MULTI_USER_SAFETY.md's 'never share a
    --project-root' rule means pushing it over the shared tree would clobber
    every other user's state."""
    m = hd.load_manifest()
    assert any(pat.startswith(".dv-harness") for pat in m.exclude)


def test_shipped_manifest_never_syncs_the_real_local_credential_script():
    """replay.ps1 is real, present in this checkout's root, and gitignored
    (.gitignore:11) -- CLAUDE.md's Remote Linux Execution amendment describes
    it as the never-committed script that supplies VCPW. The destination is a
    SHARED multi-user path."""
    m = hd.load_manifest()
    assert hd._matches_any("replay.ps1", m.never_sync)
    assert hd._matches_any("replay.csh", m.never_sync)


def test_shipped_manifest_resolves_against_this_real_repo():
    """Not a synthetic check: the shipped globs must actually match this
    checkout, and must not trip the never_sync refusal on the real tree."""
    m = hd.load_manifest()
    files = hd.collect_local_files(ROOT, m)
    assert len(files) > 100
    assert "CLAUDE.md" in files
    assert any(f.startswith("dv_harness/") for f in files)
    assert any(f.startswith(".claude/agents/") for f in files)
    assert not any(f.startswith(".dv-harness/") for f in files)
    assert not any("__pycache__" in f for f in files)


# ---- Manifest loading refusals ---------------------------------------------

def test_load_manifest_missing_file_refuses(tmp_path):
    with pytest.raises(hd.ManifestError) as exc:
        hd.load_manifest(tmp_path / "nope.json")
    assert exc.value.reason == "HARNESS_DEPLOY_MANIFEST_NOT_FOUND"


def test_load_manifest_unparseable_refuses(tmp_path):
    p = _write(tmp_path, "m.json", "{not json")
    with pytest.raises(hd.ManifestError) as exc:
        hd.load_manifest(p)
    assert exc.value.reason == "HARNESS_DEPLOY_MANIFEST_UNPARSEABLE"


def test_load_manifest_without_include_refuses(tmp_path):
    """An empty include set would make every sync report 'already in sync'
    forever -- a silently vacuous green, which is worse than an error."""
    p = _write(tmp_path, "m.json", json.dumps({"include": []}))
    with pytest.raises(hd.ManifestError) as exc:
        hd.load_manifest(p)
    assert exc.value.reason == "HARNESS_DEPLOY_MANIFEST_HAS_NO_INCLUDE"


# ---- Collection + the never_sync deny list ---------------------------------

def test_collect_local_files_is_sorted_and_excludes_pycache(fake_project, manifest):
    files = hd.collect_local_files(fake_project, manifest)
    assert files == sorted(files)
    assert files == [".claude/agents/debug-agent.md", "CLAUDE.md",
                     "dv_harness/engine.py", "dv_harness/gates.py"]


def test_never_sync_raises_rather_than_silently_skipping(tmp_path, manifest):
    """Safety property 2. A credential quietly dropped teaches the operator
    nothing; the include glob stays wrong and the next file it picks up may
    not be on the deny list."""
    src = tmp_path / "pc"
    _write(src, "dv_harness/engine.py", "ENGINE = 1\n")
    _write(src, "dv_harness/secrets.pem", "-----BEGIN PRIVATE KEY-----\n")
    # A broad include glob is the realistic way a credential gets swept in --
    # never_sync only has anything to refuse once an include reaches the file.
    manifest.include = ["dv_harness/**/*"]
    with pytest.raises(hd.SecretPathRefusedError) as exc:
        hd.collect_local_files(src, manifest)
    assert exc.value.reason == "NEVER_SYNC_PATH_MATCHED"
    assert "dv_harness/secrets.pem" in exc.value.detail["paths"]


def test_never_sync_matches_by_basename_anywhere_in_the_tree(tmp_path, manifest):
    """A deny list anchored only to the repo root would miss the same file one
    directory down, which is exactly where a copied credential ends up."""
    src = tmp_path / "pc"
    _write(src, "dv_harness/sub/.env", "VCPW=hunter2\n")
    manifest.include = ["dv_harness/**/*", "dv_harness/**/.env"]
    with pytest.raises(hd.SecretPathRefusedError):
        hd.collect_local_files(src, manifest)


# ---- Diff / plan ------------------------------------------------------------

def test_plan_pushes_only_new_and_changed_never_the_whole_tree(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    _write(target, "CLAUDE.md", "# harness rules\n")          # identical
    _write(target, "dv_harness/engine.py", "ENGINE = 0\n")     # different
    # dv_harness/gates.py and the agent md are absent -> local_only

    plan, ctx = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan.push == [".claude/agents/debug-agent.md",
                         "dv_harness/engine.py", "dv_harness/gates.py"]
    assert plan.different == ["dv_harness/engine.py"]
    assert plan.unchanged == ["CLAUDE.md"]
    assert plan.remote_only == []
    assert plan.in_sync is False
    assert ctx["remote_source"].startswith("target_root:")


def test_plan_surfaces_remote_only_as_a_human_decision_and_never_deletes(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    for rel in [".claude/agents/debug-agent.md", "CLAUDE.md",
                "dv_harness/engine.py", "dv_harness/gates.py"]:
        _write(target, rel, (fake_project / rel).read_text(encoding="utf-8"))
    _write(target, "dv_harness/server_hotfix.py", "HOTFIX = 1\n")

    plan, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan.push == []
    assert plan.remote_only == ["dv_harness/server_hotfix.py"]
    assert plan.in_sync is False
    assert hd.plan_exit_code(plan) == hd.EXIT_REMOTE_ONLY_NEEDS_DECISION

    hd.apply_to_local_target(fake_project, target, plan)
    assert (target / "dv_harness/server_hotfix.py").exists(), \
        "a server-only file must survive an apply -- deletion is a human decision"


def test_plan_reports_in_sync_when_trees_match(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    for rel in hd.collect_local_files(fake_project, manifest):
        _write(target, rel, (fake_project / rel).read_text(encoding="utf-8"))
    plan, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan.in_sync is True
    assert plan.push == []
    assert plan.local_source_id == plan.remote_source_id
    assert hd.plan_exit_code(plan) == hd.EXIT_OK


def test_source_id_differs_when_one_byte_differs(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    for rel in hd.collect_local_files(fake_project, manifest):
        _write(target, rel, (fake_project / rel).read_text(encoding="utf-8"))
    (target / "CLAUDE.md").write_text("# harness rules!\n", encoding="utf-8")
    plan, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan.local_source_id != plan.remote_source_id


def test_assume_remote_empty_is_a_first_deployment(fake_project, manifest):
    plan, ctx = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    assert plan.push == hd.collect_local_files(fake_project, manifest)
    assert ctx["remote_source"] == "assumed_remote_empty"


def test_remote_side_must_be_unambiguous(fake_project, manifest, tmp_path):
    """Zero sources or two sources are both refusals: a missing transcript path
    must never silently degrade into 'the server has nothing' and push
    everything."""
    with pytest.raises(hd.RemoteManifestError) as exc:
        hd.run_plan(fake_project, manifest=manifest)
    assert exc.value.reason == "REMOTE_SIDE_NOT_UNAMBIGUOUSLY_SPECIFIED"

    with pytest.raises(hd.RemoteManifestError):
        hd.run_plan(fake_project, manifest=manifest, target_root=tmp_path,
                    assume_remote_empty=True)


def test_absent_target_root_refuses_and_is_never_auto_created(fake_project, manifest, tmp_path):
    """A typo'd --target-root must not silently become 'the target has
    nothing' and push the entire harness to the wrong place."""
    absent = tmp_path / "typoed-path"
    with pytest.raises(hd.RemoteManifestError) as exc:
        hd.run_plan(fake_project, manifest=manifest, target_root=absent)
    assert exc.value.reason == "TARGET_ROOT_NOT_A_DIRECTORY"
    assert not absent.exists()


# ---- CRLF vs LF: the real core.autocrlf hazard ------------------------------

def test_a_crlf_vs_lf_only_difference_is_not_drift(tmp_path, manifest):
    """THE decisive case for real use. This repo's core.autocrlf is true, so the
    Windows working copy holds CRLF while a git-cloned /home/svcacct/AI/Agent
    holds LF. Without this classification every text file lands in `different`
    on every plan, forever -- ~950 files of permanent phantom drift."""
    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/engine.py").write_bytes(b"import os\r\nENGINE = 1\r\n")
    target = tmp_path / "server"
    (target / "dv_harness").mkdir(parents=True)
    (target / "dv_harness/engine.py").write_bytes(b"import os\nENGINE = 1\n")

    manifest.include = ["dv_harness/**/*.py"]
    plan, ctx = hd.run_plan(src, manifest=manifest, target_root=target)
    assert plan.push == [], "a CRLF/LF-only difference must not be pushed"
    assert plan.line_ending_only == ["dv_harness/engine.py"]
    assert plan.unchanged == ["dv_harness/engine.py"]
    assert plan.in_sync is True
    assert ctx["line_ending_tolerant"] is True


def test_strict_line_endings_reports_the_raw_byte_diff(tmp_path, manifest):
    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\r\n")
    target = tmp_path / "server"
    (target / "dv_harness").mkdir(parents=True)
    (target / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\n")

    manifest.include = ["dv_harness/**/*.py"]
    plan, ctx = hd.run_plan(src, manifest=manifest, target_root=target,
                            strict_line_endings=True)
    assert plan.push == ["dv_harness/engine.py"]
    assert plan.line_ending_only == []
    assert ctx["line_ending_tolerant"] is False


def test_a_real_content_change_is_still_drift_even_across_line_endings(tmp_path, manifest):
    """The classification must not swallow a genuine edit that also happens to
    cross a line-ending boundary -- that would silently refuse to deploy a real
    change, the most expensive failure this tool could have."""
    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/engine.py").write_bytes(b"ENGINE = 2\r\n")
    target = tmp_path / "server"
    (target / "dv_harness").mkdir(parents=True)
    (target / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\n")

    manifest.include = ["dv_harness/**/*.py"]
    plan, _ = hd.run_plan(src, manifest=manifest, target_root=target)
    assert plan.push == ["dv_harness/engine.py"]
    assert plan.line_ending_only == []


def test_binary_files_are_never_line_ending_normalized(tmp_path, manifest):
    """A NUL byte means the 0x0d 0x0a pair is data, not a line ending. Treating
    a differing binary as 'line endings only' would skip a real change."""
    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/blob.bin").write_bytes(b"\x00\x01\r\n\x02")
    target = tmp_path / "server"
    (target / "dv_harness").mkdir(parents=True)
    (target / "dv_harness/blob.bin").write_bytes(b"\x00\x01\n\x02")

    manifest.include = ["dv_harness/**/*.bin"]
    plan, _ = hd.run_plan(src, manifest=manifest, target_root=target)
    assert plan.push == ["dv_harness/blob.bin"]
    assert plan.line_ending_only == []


def test_line_ending_classification_needs_no_remote_content(tmp_path, manifest):
    """It compares the remote MD5 (all a transcript carries) against both
    renderings of the local bytes -- so it works on the transcript path, which
    is the one that matters against the real server."""
    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\r\n")
    import hashlib
    lf_md5 = hashlib.md5(b"ENGINE = 1\n").hexdigest()
    t = _write(tmp_path, "md5.txt", _transcript({"dv_harness/engine.py": lf_md5}))

    manifest.include = ["dv_harness/**/*.py"]
    plan, _ = hd.run_plan(src, manifest=manifest, remote_md5sum_transcript=t)
    assert plan.push == []
    assert plan.line_ending_only == ["dv_harness/engine.py"]


# ---- Remote transcript path (the real captured-stdout convention) -----------

def _transcript(files_md5: dict, *, exit_code: int = 0) -> str:
    body = "\n".join(f"{md5}  {path}" for path, md5 in files_md5.items())
    status = "PASS" if exit_code == 0 else "FAIL"
    return f"REMOTE_HOST=host-b\nEXIT_CODE={exit_code}\nSTATUS={status}\n{body}\n"


def test_plan_from_a_real_remote_md5sum_transcript(tmp_path, fake_project, manifest):
    local = hd.compute_local_manifest(fake_project, hd.collect_local_files(fake_project, manifest))
    remote = dict(local)
    remote["dv_harness/engine.py"] = "0" * 32          # drifted on the server
    del remote["dv_harness/gates.py"]                   # never deployed
    t = _write(tmp_path, "md5.txt", _transcript(remote))

    plan, ctx = hd.run_plan(fake_project, manifest=manifest, remote_md5sum_transcript=t)
    assert plan.push == ["dv_harness/engine.py", "dv_harness/gates.py"]
    assert ctx["remote_source"].startswith("transcript:")


def test_transcript_without_real_markers_refuses(tmp_path, fake_project, manifest):
    """A hand-written md5 list cannot stand in for a real remote_exec.py
    invocation -- the same rule server_sync_identity_gate.py enforces."""
    t = _write(tmp_path, "md5.txt", "d41d8cd98f00b204e9800998ecf8427e  CLAUDE.md\n")
    with pytest.raises(hd.RemoteManifestError) as exc:
        hd.run_plan(fake_project, manifest=manifest, remote_md5sum_transcript=t)
    assert exc.value.reason.startswith("REMOTE_TRANSCRIPT_MISSING_MARKERS")


def test_transcript_with_nonzero_remote_exit_refuses(tmp_path, fake_project, manifest):
    """A failed remote md5sum yields a short manifest that reads as 'the
    server is missing everything', which would push the whole tree."""
    t = _write(tmp_path, "md5.txt", _transcript({"CLAUDE.md": "0" * 32}, exit_code=1))
    with pytest.raises(hd.RemoteManifestError) as exc:
        hd.run_plan(fake_project, manifest=manifest, remote_md5sum_transcript=t)
    assert exc.value.reason == "REMOTE_MD5SUM_NONZERO_EXIT"


def test_transcript_file_not_found_refuses(tmp_path, fake_project, manifest):
    with pytest.raises(hd.RemoteManifestError) as exc:
        hd.run_plan(fake_project, manifest=manifest,
                    remote_md5sum_transcript=tmp_path / "never_captured.txt")
    assert exc.value.reason == "REMOTE_TRANSCRIPT_FILE_NOT_FOUND"


def test_remote_md5sum_command_uses_remote_exec_and_relative_paths():
    cmd = hd.remote_md5sum_command(["CLAUDE.md", "dv_harness/engine.py"], "/home/svcacct/AI/Agent")
    assert "tools/remote/remote_exec.py" in cmd
    assert "remote_relay.py" not in cmd, "the credentialed leg must never be named in an agent-run command"
    assert "--cwd /home/svcacct/AI/Agent" in cmd
    assert "md5sum CLAUDE.md dv_harness/engine.py" in cmd


# ---- Apply: local target ----------------------------------------------------

def test_apply_to_local_target_really_copies_the_push_set(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    result = hd.apply_to_local_target(fake_project, target, plan)
    assert result["status"] == "APPLIED"
    assert result["copied_count"] == len(plan.push)
    for rel in plan.push:
        assert (target / rel).read_text(encoding="utf-8") == \
               (fake_project / rel).read_text(encoding="utf-8")


def test_apply_event_records_why_a_push_set_was_small(tmp_path):
    """"993 local files, 0 pushed" must not read as a no-op in the audit trail
    -- the line-ending-only count is what explains it."""
    from dv_harness.storage import StateStore

    src = tmp_path / "pc"
    (src / "dv_harness").mkdir(parents=True)
    (src / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\r\n")
    target = tmp_path / "server"
    (target / "dv_harness").mkdir(parents=True)
    (target / "dv_harness/engine.py").write_bytes(b"ENGINE = 1\n")
    m = _write(tmp_path, "m.json", json.dumps(
        {"manifest_version": "t", "remote_deployment_root": "/x",
         "include": ["dv_harness/**/*.py"]}))

    store = StateStore(src)
    code, payload = hd.execute_verb(src, "apply", manifest_path=m,
                                    target_root=target, store=store)
    assert code == hd.EXIT_OK
    assert payload["copied_count"] == 0
    event = [json.loads(l) for l in store.events_file.read_text(encoding="utf-8").splitlines()
             if l.strip()][0]
    assert event["event"] == hd.EVENT_NAME
    assert event["pushed_count"] == 0
    assert event["line_ending_only_count"] == 1
    assert event["line_ending_tolerant"] is True


def test_apply_then_replan_reports_in_sync(tmp_path, fake_project, manifest):
    """End-to-end round trip: the diff engine must agree that the apply it
    just performed actually closed the gap."""
    target = tmp_path / "server"
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    hd.apply_to_local_target(fake_project, target, plan)
    plan2, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan2.in_sync is True
    assert plan2.push == []


def test_apply_is_incremental_on_a_second_run(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    hd.apply_to_local_target(fake_project, target, plan)
    (fake_project / "dv_harness/gates.py").write_text("GATES = 2\n", encoding="utf-8")
    plan2, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    assert plan2.push == ["dv_harness/gates.py"], "only the changed file may be re-sent"


# ---- Apply: remote_exec transport ------------------------------------------

def test_apply_via_remote_exec_does_not_execute_by_default(tmp_path, fake_project, manifest):
    """The structural reason a LOCAL_ANALYSIS workflow can build and test this
    file without ever reaching the live server."""
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    result = hd.apply_via_remote_exec(
        fake_project, plan, "/home/svcacct/AI/Agent",
        tarball_path=tmp_path / "pkg.tgz")
    assert result["status"] == "PREPARED"
    assert result["executed"] is False
    assert "why_not_executed" in result
    assert result["commands"], "the exact command sequence must still be produced"


def test_transport_commands_use_remote_exec_never_remote_relay(tmp_path, fake_project, manifest):
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    result = hd.apply_via_remote_exec(fake_project, plan, "/home/svcacct/AI/Agent",
                                       tarball_path=tmp_path / "pkg.tgz")
    joined = "\n".join(result["commands"])
    assert "remote_relay.py" not in joined, "CLAUDE.md: the credentialed leg is never agent-invoked"
    assert joined.count("tools/remote/remote_exec.py") == 3
    assert "--put" in joined and "tar xzf" in joined
    assert "VCPW" not in joined and "password" not in joined.lower()


def test_apply_via_remote_exec_runs_the_sequence_through_an_injected_runner(tmp_path, fake_project, manifest):
    """The execute=True path is real code, so it is tested -- with an injected
    runner, so no relay is involved and no network call is made."""
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    seen = []

    def fake_run(cmd):
        seen.append(cmd)
        return 0, "REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n"

    result = hd.apply_via_remote_exec(fake_project, plan, "/home/svcacct/AI/Agent",
                                       execute=True, run_fn=fake_run,
                                       tarball_path=tmp_path / "pkg.tgz")
    assert result["status"] == "APPLIED"
    assert result["executed"] is True
    assert len(seen) == 3 and seen == result["commands"]


def test_apply_via_remote_exec_stops_at_the_first_failing_command(tmp_path, fake_project, manifest):
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    calls = []

    def failing_run(cmd):
        calls.append(cmd)
        return (0, "ok") if len(calls) == 1 else (1, "ERROR=MD5_MISMATCH")

    result = hd.apply_via_remote_exec(fake_project, plan, "/home/svcacct/AI/Agent",
                                       execute=True, run_fn=failing_run,
                                       tarball_path=tmp_path / "pkg.tgz")
    assert result["status"] == "TRANSPORT_FAILED"
    assert len(calls) == 2, "a failed --put must not be followed by an untar of a bad tarball"
    assert result["failed_command"] == result["commands"][1]


def test_apply_via_remote_exec_with_nothing_to_push_builds_no_tarball(tmp_path, fake_project, manifest):
    target = tmp_path / "server"
    for rel in hd.collect_local_files(fake_project, manifest):
        _write(target, rel, (fake_project / rel).read_text(encoding="utf-8"))
    plan, _ = hd.run_plan(fake_project, manifest=manifest, target_root=target)
    result = hd.apply_via_remote_exec(fake_project, plan, "/home/svcacct/AI/Agent",
                                       tarball_path=tmp_path / "pkg.tgz")
    assert result["status"] == "NOTHING_TO_PUSH"
    assert not (tmp_path / "pkg.tgz").exists()


# ---- Tarball ----------------------------------------------------------------

def test_tarball_contains_exactly_the_push_set_at_relative_paths(tmp_path, fake_project, manifest):
    import tarfile

    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    out = tmp_path / "pkg.tgz"
    info = hd.build_tarball(fake_project, plan.push, out)
    assert info["file_count"] == len(plan.push)
    with tarfile.open(out) as tf:
        names = sorted(tf.getnames())
    assert names == sorted(plan.push), \
        "members must carry project-root-relative paths so `tar xzf -C <root>` lands them correctly"


def test_tarball_is_deterministic_for_identical_content(tmp_path, fake_project, manifest):
    """Metadata is normalized so the bytes depend on the content being
    shipped, not on which machine packed it."""
    plan, _ = hd.run_plan(fake_project, manifest=manifest, assume_remote_empty=True)
    a, b = tmp_path / "a.tgz", tmp_path / "b.tgz"
    hd.build_tarball(fake_project, plan.push, a)
    hd.build_tarball(fake_project, plan.push, b)
    assert a.read_bytes() == b.read_bytes()


# ---- Audit trail ------------------------------------------------------------

def test_record_event_writes_one_harness_deploy_sync_line(tmp_path):
    from dv_harness.storage import StateStore

    store = StateStore(tmp_path)
    hd.record_event(tmp_path, {"verb": "apply", "status": "APPLIED",
                                "pushed_count": 2, "pushed": ["a.py", "b.py"]},
                    store=store)
    lines = [json.loads(l) for l in store.events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    events = [e for e in lines if e.get("event") == hd.EVENT_NAME]
    assert len(events) == 1
    assert events[0]["status"] == "APPLIED"
    assert events[0]["pushed"] == ["a.py", "b.py"]
    assert events[0]["ts"]


def test_record_event_caps_a_huge_path_list_but_keeps_the_true_total(tmp_path):
    """A first deployment pushes the whole harness (~1000 files here). Inlining
    every path would append ~100KB to a single events.jsonl line that
    `dv-harness audit` and the dashboard both read back."""
    from dv_harness.storage import StateStore

    store = StateStore(tmp_path)
    paths = [f"dv_harness/mod_{i}.py" for i in range(400)]
    hd.record_event(tmp_path, {"status": "APPLIED", "pushed_count": 400, "pushed": paths},
                    store=store)
    event = [json.loads(l) for l in store.events_file.read_text(encoding="utf-8").splitlines()][0]
    assert len(event["pushed"]) == hd.EVENT_PATH_LIST_CAP
    assert event["pushed_truncated"] is True
    assert event["pushed_total"] == 400
    assert event["pushed_count"] == 400, "the real count must survive truncation"


def test_record_event_does_not_mutate_the_callers_payload(tmp_path):
    from dv_harness.storage import StateStore

    paths = [f"f{i}.py" for i in range(400)]
    payload = {"status": "APPLIED", "pushed": paths}
    hd.record_event(tmp_path, payload, store=StateStore(tmp_path))
    assert len(payload["pushed"]) == 400
    assert "pushed_truncated" not in payload


def test_record_event_is_best_effort_and_never_raises(tmp_path):
    """Mirrors engine.py's `_promote_*`/`_record_*` convention: an audit-write
    failure must never turn an already-completed sync into a crash."""
    class Exploding:
        def event(self, _):
            raise OSError("disk full")

    event = hd.record_event(tmp_path, {"status": "APPLIED"}, store=Exploding())
    assert event["_recorded"] is False
    assert "disk full" in event["_record_error"]


# ---- The real CLI front door ------------------------------------------------

def _run_cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "dv_harness.cli", *args],
                          cwd=str(cwd), capture_output=True, text=True)


def test_cli_registers_the_harness_deploy_verb():
    proc = _run_cli("--help")
    assert proc.returncode == 0
    assert "harness-deploy" in proc.stdout


def test_cli_plan_against_a_synthetic_target_reports_drift(tmp_path):
    """The real CLI, the real shipped manifest, this real checkout -- against
    an empty synthetic target directory, so no network call is possible."""
    target = tmp_path / "server"
    target.mkdir()
    proc = _run_cli("harness-deploy", "plan", "--target-root", str(target))
    assert proc.returncode == hd.EXIT_DRIFT, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "PLANNED"
    assert payload["in_sync"] is False
    assert payload["push_count"] > 100
    assert payload["remote_only"] == []
    assert "CLAUDE.md" in payload["push"]


def test_cli_apply_to_a_synthetic_target_then_plan_is_clean(tmp_path):
    target = tmp_path / "server"
    target.mkdir()
    apply_proc = _run_cli("harness-deploy", "apply", "--target-root", str(target))
    assert apply_proc.returncode == hd.EXIT_OK, apply_proc.stdout + apply_proc.stderr
    applied = json.loads(apply_proc.stdout)
    assert applied["status"] == "APPLIED"
    assert applied["copied_count"] > 100

    plan_proc = _run_cli("harness-deploy", "plan", "--target-root", str(target))
    payload = json.loads(plan_proc.stdout)
    assert payload["in_sync"] is True, payload
    assert plan_proc.returncode == hd.EXIT_OK


def test_cli_manifest_prints_the_remote_md5sum_command():
    proc = _run_cli("harness-deploy", "manifest", "--print-md5sum-command")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["remote_deployment_root"] == "/home/svcacct/AI/Agent"
    assert payload["file_count"] > 100
    assert len(payload["local_source_id"]) == 64
    assert payload["remote_md5sum_command"].startswith("python tools/remote/remote_exec.py --cwd ")


def test_both_front_doors_share_one_implementation(tmp_path):
    """`dv-harness harness-deploy` and `python -m dv_harness.harness_deploy`
    must agree exactly -- they call one `execute_verb()`. Two handlers
    orchestrating the same behavior is the parallel-mechanism defect this
    project forbids, and this test is what would catch them drifting."""
    target = tmp_path / "server"
    target.mkdir()
    via_cli = _run_cli("harness-deploy", "plan", "--target-root", str(target))
    via_module = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_deploy", "plan", "--target-root", str(target)],
        cwd=str(ROOT), capture_output=True, text=True)
    assert via_cli.returncode == via_module.returncode
    a, b = json.loads(via_cli.stdout), json.loads(via_module.stdout)
    assert a["push"] == b["push"]
    assert a["local_source_id"] == b["local_source_id"]
    assert a["remote_only"] == b["remote_only"]


def test_cli_refuses_an_unspecified_remote_side(tmp_path):
    proc = _run_cli("harness-deploy", "plan")
    assert proc.returncode == hd.EXIT_ERROR
    payload = json.loads(proc.stdout)
    assert payload["reason"] == "REMOTE_SIDE_NOT_UNAMBIGUOUSLY_SPECIFIED"
