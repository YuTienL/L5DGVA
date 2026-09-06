"""Tests for dv_harness.file_candidate_ranker.

Every git-log-bearing test drives a REAL throwaway git repository (built via
real `git` subprocess invocations in this file, never a mock), with real
commits touching different candidate files -- so the ranker's git-derived
evidence is checked against commits that really happened, not against a
stand-in. Negative controls give the NOT_AVAILABLE paths detection power:
an ambiguous/unverifiable input must read as NOT_AVAILABLE, never a
confident guess.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import file_candidate_ranker as fcr

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}: {result.stderr}"
    )
    return result


@pytest.fixture()
def real_repo(tmp_path: Path) -> Path:
    """A real throwaway git repository with real commits touching three
    different candidate files, standing in for the
    usb_reg.xlsx / usb_reg_v2.xlsx / usb_reg_final.xlsx ambiguity this
    module exists to help a human resolve."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    # usb_reg.xlsx: three real commits -- long, well-established history.
    old = repo / "usb_reg.xlsx"
    old.write_text("v1 content\n", encoding="utf-8")
    _git(repo, "add", "usb_reg.xlsx")
    _git(repo, "commit", "-m", "add usb_reg.xlsx")
    old.write_text("v1 content, revised\n", encoding="utf-8")
    _git(repo, "add", "usb_reg.xlsx")
    _git(repo, "commit", "-m", "fix a field in usb_reg.xlsx")
    old.write_text("v1 content, revised again\n", encoding="utf-8")
    _git(repo, "add", "usb_reg.xlsx")
    _git(repo, "commit", "-m", "another real revision to usb_reg.xlsx")

    # usb_reg_v2.xlsx: one real commit -- touched once, long ago.
    v2 = repo / "usb_reg_v2.xlsx"
    v2.write_text("v2 content\n", encoding="utf-8")
    _git(repo, "add", "usb_reg_v2.xlsx")
    _git(repo, "commit", "-m", "add usb_reg_v2.xlsx (experimental)")

    # usb_reg_final.xlsx: exists on disk but was NEVER committed -- the
    # "no history for this path" real-zero case this module reports
    # NOT_AVAILABLE for (see module docstring).
    final = repo / "usb_reg_final.xlsx"
    final.write_text("final content, never committed\n", encoding="utf-8")

    # A Makefile that references two of the three candidates, plus a
    # sibling build script referencing a third -- real build-script text.
    makefile = repo / "Makefile"
    makefile.write_text(
        "REGMAP := usb_reg_v2.xlsx\nall:\n\techo building with $(REGMAP)\n",
        encoding="utf-8",
    )
    build_sh = repo / "build.sh"
    build_sh.write_text(
        "#!/bin/sh\n# canonical register map: usb_reg.xlsx\ncat usb_reg.xlsx\n",
        encoding="utf-8",
    )
    return repo


# ---------------------------------------------------------------------------
# git log evidence
# ---------------------------------------------------------------------------


def test_git_log_evidence_real_multi_commit_file(real_repo: Path) -> None:
    evidence = fcr.gather_git_log_evidence(real_repo, real_repo / "usb_reg.xlsx")
    assert evidence.status == fcr.AVAILABLE
    assert evidence.commit_count == 3
    assert evidence.last_commit_sha
    assert evidence.last_commit_date is not None
    assert "revision" in (evidence.last_commit_subject or "")


def test_git_log_evidence_real_single_commit_file(real_repo: Path) -> None:
    evidence = fcr.gather_git_log_evidence(real_repo, real_repo / "usb_reg_v2.xlsx")
    assert evidence.status == fcr.AVAILABLE
    assert evidence.commit_count == 1


def test_git_log_evidence_no_history_for_this_path_is_not_available(
    real_repo: Path,
) -> None:
    """Negative control: a file that exists on disk, in a real repo with
    real commits, but was never itself committed -- reports NOT_AVAILABLE
    (per this module's own documented, deliberate reading of "no history"),
    never a confident zero presented as comparable to a real AVAILABLE
    signal, and the real commit_count=0 is still carried on the record."""
    evidence = fcr.gather_git_log_evidence(
        real_repo, real_repo / "usb_reg_final.xlsx"
    )
    assert evidence.status == fcr.NOT_AVAILABLE
    assert evidence.commit_count == 0
    assert "no commits" in (evidence.reason or "").lower()


def test_git_log_evidence_no_repo_root_supplied() -> None:
    evidence = fcr.gather_git_log_evidence(None, Path("usb_reg.xlsx"))
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "no repository root" in (evidence.reason or "").lower()


def test_git_log_evidence_not_a_git_repo(tmp_path: Path) -> None:
    """Negative control: a real directory that is simply not a git
    repository at all."""
    not_a_repo = tmp_path / "plain_dir"
    not_a_repo.mkdir()
    candidate = not_a_repo / "usb_reg.xlsx"
    candidate.write_text("x", encoding="utf-8")
    evidence = fcr.gather_git_log_evidence(not_a_repo, candidate)
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "not a git repository" in (evidence.reason or "").lower()


def test_git_log_evidence_repo_root_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    evidence = fcr.gather_git_log_evidence(missing, missing / "usb_reg.xlsx")
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "does not exist" in (evidence.reason or "").lower()


def test_git_log_evidence_candidate_outside_repo_root(
    real_repo: Path, tmp_path: Path
) -> None:
    """Negative control: candidate path is not inside the given repository
    root at all -- must be refused rather than silently treated as
    zero-history."""
    outside = tmp_path / "outside" / "usb_reg.xlsx"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    evidence = fcr.gather_git_log_evidence(real_repo, outside)
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "not inside" in (evidence.reason or "").lower()


# ---------------------------------------------------------------------------
# build-script reference evidence
# ---------------------------------------------------------------------------


def test_build_script_evidence_real_reference_found(real_repo: Path) -> None:
    evidence = fcr.gather_build_script_evidence(
        real_repo, real_repo / "usb_reg_v2.xlsx"
    )
    assert evidence.status == fcr.AVAILABLE
    assert evidence.reference_count == 1
    assert evidence.build_scripts_scanned == 2
    assert evidence.referencing_files
    assert evidence.referencing_files[0]["file"] in ("Makefile",)


def test_build_script_evidence_real_zero_references_is_available_not_unavailable(
    real_repo: Path,
) -> None:
    """A real, checked zero (build scripts exist, none mention this
    candidate) must be AVAILABLE with reference_count=0, never
    NOT_AVAILABLE -- collapsing the two would conflate absence with zero."""
    evidence = fcr.gather_build_script_evidence(
        real_repo, real_repo / "usb_reg_final.xlsx"
    )
    assert evidence.status == fcr.AVAILABLE
    assert evidence.reference_count == 0
    assert evidence.referencing_files == []


def test_build_script_evidence_no_project_root_supplied() -> None:
    evidence = fcr.gather_build_script_evidence(None, Path("usb_reg.xlsx"))
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "no project root" in (evidence.reason or "").lower()


def test_build_script_evidence_no_build_scripts_found(tmp_path: Path) -> None:
    """Negative control: a real project root with no build scripts/Makefiles
    of any kind under it -- distinct from "checked and found zero"."""
    empty_project = tmp_path / "no_build_scripts"
    empty_project.mkdir()
    (empty_project / "notes.txt").write_text("usb_reg.xlsx", encoding="utf-8")
    evidence = fcr.gather_build_script_evidence(
        empty_project, empty_project / "usb_reg.xlsx"
    )
    assert evidence.status == fcr.NOT_AVAILABLE
    assert evidence.build_scripts_scanned == 0
    assert "no build scripts" in (evidence.reason or "").lower()


def test_build_script_evidence_project_root_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    evidence = fcr.gather_build_script_evidence(missing, missing / "usb_reg.xlsx")
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "does not exist" in (evidence.reason or "").lower()


# ---------------------------------------------------------------------------
# mtime evidence
# ---------------------------------------------------------------------------


def test_mtime_evidence_real_file(real_repo: Path) -> None:
    evidence = fcr.gather_mtime_evidence(real_repo / "usb_reg.xlsx")
    assert evidence.status == fcr.AVAILABLE
    assert evidence.mtime_epoch is not None
    assert evidence.mtime_iso is not None
    assert evidence.size_bytes is not None and evidence.size_bytes > 0


def test_mtime_evidence_missing_file(tmp_path: Path) -> None:
    """Negative control: the candidate simply is not on disk."""
    evidence = fcr.gather_mtime_evidence(tmp_path / "nonexistent.xlsx")
    assert evidence.status == fcr.NOT_AVAILABLE
    assert "not found" in (evidence.reason or "").lower()


def test_mtime_evidence_directory_is_not_a_file(tmp_path: Path) -> None:
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    evidence = fcr.gather_mtime_evidence(a_dir)
    assert evidence.status == fcr.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# analyze_candidate + rank_file_candidates: full assembly, never picks a
# winner, and the ranking is stable/deterministic and evidence-explainable.
# ---------------------------------------------------------------------------


def test_analyze_candidate_assembles_all_three_signals(real_repo: Path) -> None:
    evidence = fcr.analyze_candidate(
        real_repo / "usb_reg.xlsx", repo_root=real_repo, project_root=real_repo
    )
    assert evidence.exists_on_disk is True
    assert evidence.git_log.status == fcr.AVAILABLE
    assert evidence.build_script_references.status == fcr.AVAILABLE
    assert evidence.mtime.status == fcr.AVAILABLE
    assert evidence.available_signal_count() == 3


def test_rank_file_candidates_returns_every_candidate_never_a_winner(
    real_repo: Path,
) -> None:
    candidates = [
        real_repo / "usb_reg.xlsx",
        real_repo / "usb_reg_v2.xlsx",
        real_repo / "usb_reg_final.xlsx",
    ]
    report = fcr.rank_file_candidates(
        candidates, repo_root=real_repo, project_root=real_repo
    )
    # Every candidate must appear -- this module never drops or "resolves"
    # the ambiguity by omission.
    assert len(report.candidates) == 3
    assert {c.path for c in report.candidates} == {str(p) for p in candidates}
    assert report.caller_must_decide is True
    # No field key anywhere names a single winner/recommendation (the
    # disclosure text itself legitimately uses the word "winner" to explain
    # that this module does not pick one, which is why this checks field
    # KEYS rather than doing a substring scan over the whole payload).
    result_dict = report.to_dict()

    def _collect_keys(obj):
        keys = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.add(str(k).lower())
                keys |= _collect_keys(v)
        elif isinstance(obj, list):
            for item in obj:
                keys |= _collect_keys(item)
        return keys

    all_keys = _collect_keys(result_dict)
    for forbidden in ("winner", "recommended", "recommendation", "best_candidate", "answer"):
        assert forbidden not in all_keys


def test_rank_file_candidates_orders_by_real_evidence(real_repo: Path) -> None:
    """usb_reg.xlsx has the most real commits and the most recent commit
    date; usb_reg_v2.xlsx has one older commit plus a build-script
    reference; usb_reg_final.xlsx has neither. This asserts the
    informational display order actually reflects that real evidence,
    while every candidate's full evidence remains attached regardless of
    its position."""
    candidates = [
        real_repo / "usb_reg_final.xlsx",  # deliberately listed first
        real_repo / "usb_reg_v2.xlsx",
        real_repo / "usb_reg.xlsx",
    ]
    report = fcr.rank_file_candidates(
        candidates, repo_root=real_repo, project_root=real_repo
    )
    ordered_names = [Path(c.path).name for c in report.candidates]
    assert ordered_names[0] == "usb_reg.xlsx"
    assert ordered_names.index("usb_reg_v2.xlsx") < ordered_names.index(
        "usb_reg_final.xlsx"
    )
    ranks = [c.display_rank for c in report.candidates]
    assert ranks == [1, 2, 3]


def test_rank_file_candidates_ties_preserve_input_order(tmp_path: Path) -> None:
    """Negative control: with no repo_root/project_root supplied at all,
    every signal is NOT_AVAILABLE for every candidate, so all sort weights
    tie. Ties must preserve the caller's own input order, never an
    arbitrary re-ordering."""
    a = tmp_path / "a.xlsx"
    b = tmp_path / "b.xlsx"
    c = tmp_path / "c.xlsx"
    for p in (a, b, c):
        p.write_text("x", encoding="utf-8")
    report = fcr.rank_file_candidates([a, b, c])
    assert [Path(cand.path).name for cand in report.candidates] == [
        "a.xlsx",
        "b.xlsx",
        "c.xlsx",
    ]
    for cand in report.candidates:
        # mtime is real and available even with no repo/project root.
        assert cand.evidence.mtime.status == fcr.AVAILABLE
        assert cand.evidence.git_log.status == fcr.NOT_AVAILABLE
        assert cand.evidence.build_script_references.status == fcr.NOT_AVAILABLE


def test_display_order_reason_cites_real_evidence(real_repo: Path) -> None:
    report = fcr.rank_file_candidates(
        [real_repo / "usb_reg.xlsx"], repo_root=real_repo, project_root=real_repo
    )
    reason = report.candidates[0].display_order_reason
    assert "3 git commit" in reason
    assert "mtime" in reason


# ---------------------------------------------------------------------------
# execute_verb / CLI, real subprocesses.
# ---------------------------------------------------------------------------


def test_execute_verb_rank_exit_0_when_every_candidate_has_evidence(
    real_repo: Path,
) -> None:
    exit_code, result = fcr.execute_verb(
        "rank",
        candidates=[str(real_repo / "usb_reg.xlsx")],
        repo_root=str(real_repo),
        project_root=str(real_repo),
    )
    assert exit_code == 0
    assert result["candidates"][0]["available_signal_count"] == 3


def test_execute_verb_rank_exit_1_when_a_candidate_has_no_evidence_at_all(
    tmp_path: Path,
) -> None:
    """A candidate path that does not exist on disk, with no repo_root and
    no project_root supplied, has ALL THREE signals NOT_AVAILABLE -- a real,
    disclosed finding (exit 1), never silently reported as exit 0."""
    exit_code, result = fcr.execute_verb(
        "rank", candidates=[str(tmp_path / "ghost.xlsx")]
    )
    assert exit_code == 1
    assert result["candidates"][0]["available_signal_count"] == 0


def test_execute_verb_rank_exit_2_no_candidates() -> None:
    exit_code, result = fcr.execute_verb("rank", candidates=[])
    assert exit_code == 2


def test_execute_verb_unrecognized_verb() -> None:
    exit_code, _result = fcr.execute_verb("bogus", candidates=["x"])
    assert exit_code == 2


def test_cli_real_subprocess_exit_0(real_repo: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dv_harness.file_candidate_ranker",
            "rank",
            str(real_repo / "usb_reg.xlsx"),
            "--repo-root",
            str(real_repo),
            "--project-root",
            str(real_repo),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["candidates"][0]["available_signal_count"] == 3


def test_cli_real_subprocess_usage_error_exit_2() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.file_candidate_ranker", "rank"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Vocabulary discipline.
# ---------------------------------------------------------------------------


def test_status_vocabulary_disjoint_from_models_status() -> None:
    fcr.assert_no_verification_verdict_vocabulary()
