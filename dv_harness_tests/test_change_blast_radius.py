"""Tests for the change-budget / blast-radius gate (dv_harness/change_blast_radius.py).

Three layers, matching what the gate actually has to be true about:

  1. THE SIGNALS ARE MEASURED, NOT DECLARED. The import graph is parsed out of
     this repo's real source and must reproduce edges that really exist; the
     governance-file set must be DERIVED from autonomy_levels.LEVEL_C_ENFORCEMENT
     (proven by mutating that table and watching the set follow) rather than
     hand-listed. This is the whole difference between this gate and
     question_queue.py's pre-existing self-reported `blast_radius` string.

  2. THE DECISION RULES. Tier thresholds, the digest pin (a grown change stops
     being covered by the approval that reviewed the smaller one), human pushes
     ungated, and fail-open when no real diff can be computed.

  3. END-TO-END THROUGH GIT ITSELF, reusing test_git_hooks_e2e.py's proven
     throwaway-repo + real-hooks + local-bare-remote harness: a real `git push`
     of a governance-file change from an agent environment must be ABORTED BY
     GIT, must land nothing on the remote, and must then SUCCEED once a real
     `dv-harness approve CHANGE_BLAST_RADIUS` pinned to that digest exists.

  4. THE EXISTING BRANCH GATE IS UNWEAKENED. The last class re-asserts, through
     the real CLI, that a protected-branch agent push still blocks with
     git_governance's own message even when the blast radius is CONTAINED -- the
     new check is additive and cannot turn a block into an allow.

No production build, regression or LSF submission is involved anywhere: every
git operation runs in a pytest tmp_path throwaway repo against a local bare
remote.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = ROOT / "tools" / "git-hooks"
sys.path.insert(0, str(ROOT))

from dv_harness import change_blast_radius as cbr  # noqa: E402
from dv_harness.git_governance import AI_AGENT_ENV_MARKERS  # noqa: E402

GIT = shutil.which("git")

AGENT_ENV = {"CLAUDECODE": "1"}
HUMAN_ENV: dict = {}


# ---------------------------------------------------------------------------
# 1. the signals are measured off real source, not declared
# ---------------------------------------------------------------------------
class TestImportGraphIsRealSource:

    def test_graph_reproduces_edges_that_really_exist_in_this_repo(self):
        graph = cbr.build_import_graph(ROOT / "dv_harness")
        # Real edges, each verifiable by reading the named file's imports.
        assert "capability_evolution" in graph["commands"], (
            "commands.py really does `from .capability_evolution import "
            "HUMAN_APPROVAL_STAGE`; the AST walk missed it")
        assert "change_impact" in graph["change_blast_radius"]
        assert "git_governance" in graph["change_blast_radius"]
        # ...and does not invent edges to modules that are not imported.
        assert "engine" not in graph["change_blast_radius"]

    def test_reach_orders_modules_the_way_the_real_dependency_structure_does(self):
        graph = cbr.build_import_graph(ROOT / "dv_harness")
        reverse = cbr.reverse_edges(graph)
        models_reach = len(cbr.importer_closure(["models"], reverse))
        # cli.py is a real leaf: it imports most of the package and (apart from
        # __main__) nothing imports it, so a change to it reaches almost
        # nothing -- the exact inverse of models.py, which most of the package
        # can reach. A gate that could not tell these two apart would be
        # scoring nothing real. Asserted as an ORDERING with generous slack
        # rather than exact counts, because both numbers legitimately move
        # whenever the package gains or loses an import.
        leaf_reach = len(cbr.importer_closure(["cli"], reverse))
        assert models_reach > 50, models_reach
        assert leaf_reach <= 3, leaf_reach
        assert models_reach > leaf_reach * 10

    def test_a_module_is_inside_its_own_blast_radius(self):
        reverse = cbr.reverse_edges(cbr.build_import_graph(ROOT / "dv_harness"))
        assert "models" in cbr.importer_closure(["models"], reverse)

    def test_import_cycles_do_not_hang_the_closure(self, tmp_path):
        pkg = tmp_path / "dv_harness"
        pkg.mkdir()
        (pkg / "a.py").write_text("from .b import x\n", encoding="utf-8")
        (pkg / "b.py").write_text("from .a import y\n", encoding="utf-8")
        reverse = cbr.reverse_edges(cbr.build_import_graph(pkg))
        assert cbr.importer_closure(["a"], reverse) == {"a", "b"}

    def test_unparseable_file_contributes_no_edges_instead_of_raising(self, tmp_path):
        pkg = tmp_path / "dv_harness"
        pkg.mkdir()
        (pkg / "broken.py").write_text("def (((\n", encoding="utf-8")
        (pkg / "ok.py").write_text("from .broken import z\n", encoding="utf-8")
        graph = cbr.build_import_graph(pkg)          # must not raise
        assert graph["broken"] == set()
        assert graph["ok"] == {"broken"}


class TestGovernanceSetIsDerivedNotHandListed:

    def test_it_follows_the_level_c_enforcement_table(self, monkeypatch):
        """Mutate the repo's own enforcement table and the gate's notion of
        'a policy file' must move with it. This is what proves derivation:
        a hardcoded list would be unaffected by this monkeypatch."""
        from dv_harness import autonomy_levels

        assert "dv_harness/git_governance.py" in cbr.governance_files()
        monkeypatch.setattr(autonomy_levels, "LEVEL_C_ENFORCEMENT", {
            "a fabricated example": {"status": "ENFORCED", "mechanism": "",
                                      "cites": (("dv_harness.fabricated_guard", "X"),)},
        })
        derived = cbr.governance_files()
        assert "dv_harness/fabricated_guard.py" in derived
        assert "dv_harness/git_governance.py" not in derived

    def test_the_live_hook_scripts_are_governance_by_path(self):
        gov = cbr.governance_files()
        assert cbr.is_governance_file("tools/git-hooks/pre-push", gov)
        assert cbr.is_governance_file("tools/git-hooks/pre-merge-commit", gov)

    def test_the_gate_and_its_source_table_are_themselves_governance_files(self):
        """A change that edits the gate, or edits the table the gate reads its
        governance set out of, is exactly the change that most needs review."""
        gov = cbr.governance_files()
        assert cbr.is_governance_file("dv_harness/change_blast_radius.py", gov)
        assert cbr.is_governance_file("dv_harness/autonomy_levels.py", gov)

    def test_an_ordinary_source_file_is_not_governance(self):
        gov = cbr.governance_files()
        assert not cbr.is_governance_file("dv_harness/dashboard.py", gov)
        assert not cbr.is_governance_file("docs/readme.md", gov)


# ---------------------------------------------------------------------------
# 2. the decision rules
# ---------------------------------------------------------------------------
class TestTierClassification:

    def test_small_leaf_change_is_contained(self):
        a = cbr.assess_changed_files(ROOT, ["docs/notes.md", "dv_harness_tests/test_x.py"])
        assert a.tier == cbr.TIER_CONTAINED
        assert a.tier not in cbr.TIERS_REQUIRING_CONFIRMATION

    def test_high_reach_module_change_is_wide(self):
        a = cbr.assess_changed_files(ROOT, ["dv_harness/models.py"])
        assert a.tier == cbr.TIER_WIDE
        assert a.reach >= cbr.WIDE_REACH_THRESHOLD
        assert any("import reach" in r for r in a.reasons)

    def test_many_files_is_wide_even_with_zero_import_reach(self):
        files = [f"docs/page_{i}.md" for i in range(cbr.WIDE_FILE_COUNT_THRESHOLD)]
        a = cbr.assess_changed_files(ROOT, files)
        assert a.tier == cbr.TIER_WIDE
        assert a.reach == 0
        assert any("files changed" in r for r in a.reasons)

    def test_governance_file_outranks_size(self):
        """One line in a gate file is the top tier -- size cannot argue it down."""
        a = cbr.assess_changed_files(ROOT, ["tools/git-hooks/pre-push"])
        assert a.tier == cbr.TIER_GOVERNANCE
        assert a.file_count == 1
        assert a.governance_files_touched == ["tools/git-hooks/pre-push"]

    def test_no_real_diff_is_not_assessable_and_scores_nothing(self):
        a = cbr.assess_changed_files(ROOT, ["dv_harness/models.py"], diff_status="NO_GIT")
        assert a.tier == cbr.TIER_NOT_ASSESSABLE
        assert a.file_count == 0 and a.digest == ""


class TestDigestPinning:

    def test_same_file_set_in_any_order_is_the_same_digest(self):
        a = cbr.assess_changed_files(ROOT, ["dv_harness/models.py", "docs/a.md"])
        b = cbr.assess_changed_files(ROOT, ["docs/a.md", "dv_harness/models.py"])
        assert a.digest == b.digest != ""

    def test_growing_the_change_moves_the_digest(self):
        """The property the whole confirmation mechanism rests on: an approval
        for a smaller change cannot cover a larger one."""
        a = cbr.assess_changed_files(ROOT, ["dv_harness/models.py"])
        b = cbr.assess_changed_files(ROOT, ["dv_harness/models.py", "dv_harness/gates.py"])
        assert a.digest != b.digest


class TestDecideRules:

    def _wide(self):
        return cbr.assess_changed_files(ROOT, ["dv_harness/models.py"])

    def test_human_push_of_a_wide_change_is_never_blocked(self, tmp_path):
        d = cbr.decide(tmp_path, "pre-push", self._wide(), HUMAN_ENV)
        assert d.allowed is True
        assert d.tier == cbr.TIER_WIDE
        assert "no AI-agent environment marker" in d.reason

    def test_agent_push_of_a_contained_change_is_allowed(self, tmp_path):
        a = cbr.assess_changed_files(ROOT, ["docs/notes.md"])
        d = cbr.decide(tmp_path, "pre-push", a, AGENT_ENV)
        assert d.allowed is True and d.tier == cbr.TIER_CONTAINED

    def test_agent_push_of_a_wide_change_is_blocked_without_confirmation(self, tmp_path):
        d = cbr.decide(tmp_path, "pre-push", self._wide(), AGENT_ENV)
        assert d.allowed is False
        assert "BLOCKED" in d.reason
        assert d.confirmation["state"] == "ABSENT"
        # the block must hand over the real, runnable confirmation command
        assert "dv-harness approve CHANGE_BLAST_RADIUS" in d.reason
        assert self._wide().digest in d.reason

    def test_a_pinned_approval_unblocks_that_exact_change(self, tmp_path):
        from dv_harness.control_plane import ControlPlane

        a = self._wide()
        ControlPlane(tmp_path).approve(
            cbr.BLAST_RADIUS_APPROVAL_STAGE,
            note=f"blast-radius {a.digest}: reviewed the models.py change",
            reviewer_id="reviewer@example.invalid")
        d = cbr.decide(tmp_path, "pre-push", a, AGENT_ENV)
        assert d.allowed is True
        assert d.confirmation["state"] == "PINNED_MATCH"
        assert "reviewer@example.invalid" in d.reason

    def test_an_approval_for_a_different_change_does_not_carry_over(self, tmp_path):
        """The anti-blanket-bypass property, end to end: approve the small
        change, then grow it, and the gate must block again as STALE_DIGEST."""
        from dv_harness.control_plane import ControlPlane

        small = cbr.assess_changed_files(ROOT, ["dv_harness/models.py"])
        ControlPlane(tmp_path).approve(
            cbr.BLAST_RADIUS_APPROVAL_STAGE, note=f"blast-radius {small.digest}: ok",
            reviewer_id="reviewer@example.invalid")
        assert cbr.decide(tmp_path, "pre-push", small, AGENT_ENV).allowed is True

        grown = cbr.assess_changed_files(
            ROOT, ["dv_harness/models.py", "tools/git-hooks/pre-push"])
        d = cbr.decide(tmp_path, "pre-push", grown, AGENT_ENV)
        assert d.allowed is False
        assert d.confirmation["state"] == "STALE_DIGEST"
        assert "DIFFERENT" in d.reason

    def test_unmeasurable_change_fails_open_and_says_so(self, tmp_path):
        a = cbr.assess_changed_files(ROOT, [], diff_status="NEW_BRANCH_NO_MERGE_BASE")
        d = cbr.decide(tmp_path, "pre-push", a, AGENT_ENV)
        assert d.allowed is True
        assert d.tier == cbr.TIER_NOT_ASSESSABLE
        assert "NEW_BRANCH_NO_MERGE_BASE" in d.reason


class TestApprovalStageIsOperableByTheRealApproveCommand:
    """capability_evolution.py's own gate was once un-operable because
    `dv-harness approve` rejected its stage key before ControlPlane ever saw
    it (see commands.APPROVAL_ONLY_STAGES' comment). Same mistake, checked."""

    def test_the_stage_is_registered_as_an_approval_only_stage(self):
        from dv_harness import commands
        assert cbr.BLAST_RADIUS_APPROVAL_STAGE in commands.APPROVAL_ONLY_STAGES
        assert cbr.BLAST_RADIUS_APPROVAL_STAGE in commands.approval_stage_choices()

    def test_it_is_not_a_graph_stage(self):
        from dv_harness.models import Stage
        assert cbr.BLAST_RADIUS_APPROVAL_STAGE not in {s.value for s in Stage}

    def test_the_command_the_block_message_prints_is_the_registered_one(self):
        cmd = cbr.confirmation_command("deadbeefdeadbeef")
        from dv_harness import commands
        stage = cmd.split()[2]
        assert stage in commands.approval_stage_choices()
        assert "deadbeefdeadbeef" in cmd


# ---------------------------------------------------------------------------
# 3 + 4. end-to-end through real git, and the existing branch gate unweakened
# ---------------------------------------------------------------------------
pytestmark_e2e = pytest.mark.skipif(
    GIT is None or not (HOOKS_DIR / "pre-push").exists(),
    reason="needs a real git executable and the tools/git-hooks scripts",
)


def _base_env(agent: bool):
    """Same construction test_git_hooks_e2e.py established: markers stripped
    (this runner is itself an agent environment), PYTHONPATH so the hook's
    `python -m dv_harness.cli` resolves the package from the throwaway repo,
    and the documented self-test bypass so these tests stay scoped to the
    governance/blast-radius gates."""
    env = dict(os.environ)
    for marker in AI_AGENT_ENV_MARKERS:
        env.pop(marker, None)
    if agent:
        env["CLAUDECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    env.pop("GIT_DIR", None)
    env["DV_HARNESS_SKIP_SELF_TEST"] = "1"
    return env


def _git(work, *args, env=None, check=True):
    r = subprocess.run([GIT, *args], cwd=str(work), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace",
                       env=env if env is not None else _base_env(agent=False))
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _remote_refs(remote):
    r = subprocess.run([GIT, "--git-dir", str(remote), "for-each-ref", "--format=%(refname)"],
                       capture_output=True, text=True, timeout=60, check=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _events(work, name):
    trail = Path(work) / ".dv-harness" / "events.jsonl"
    if not trail.exists():
        return []
    out = []
    for line in trail.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == name:
            out.append(ev)
    return out


@pytest.fixture()
def repo(tmp_path):
    """Throwaway work repo with THIS repo's real hooks installed, pushing at a
    throwaway LOCAL BARE remote -- never a network remote, never this repo."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run([GIT, "init", "--bare", "-q", str(remote)], check=True, timeout=60)
    subprocess.run([GIT, "init", "-q", "-b", "master", str(work)], check=True, timeout=60)
    _git(work, "config", "user.email", "e2e@example.invalid")
    _git(work, "config", "user.name", "e2e")
    _git(work, "config", "core.hooksPath", str(HOOKS_DIR))
    (work / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(remote))
    # Publish master so a later feature-branch push has a real remote-side
    # base, and so the branch gate is not what stops these tests.
    _git(work, "push", "-q", "origin", "master", env=_base_env(agent=False))
    return work, remote


def _commit_governance_change(work, env):
    """A one-file change to a GOVERNANCE file, on a feature branch the
    PR-only branch gate happily allows -- so anything that blocks the push
    can only be the blast-radius gate."""
    _git(work, "checkout", "-q", "-b", "feat/blast-radius-e2e", env=env)
    target = Path(work) / "dv_harness"
    target.mkdir(parents=True, exist_ok=True)
    (target / "git_governance.py").write_text("# edited by the e2e test\n", encoding="utf-8")
    _git(work, "add", "dv_harness/git_governance.py", env=env)
    _git(work, "commit", "-qm", "touch a governance file", env=env)


@pytestmark_e2e
class TestRealGitPushIsGatedOnBlastRadius:

    def test_agent_push_of_a_governance_change_is_aborted_by_git(self, repo):
        work, remote = repo
        env = _base_env(agent=True)
        _commit_governance_change(work, env)

        r = _git(work, "push", "origin", "feat/blast-radius-e2e", env=env, check=False)

        assert r.returncode != 0, f"push was NOT blocked:\n{r.stdout}\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "GOVERNANCE" in combined
        assert "dv-harness approve CHANGE_BLAST_RADIUS" in combined
        # nothing landed: the feature branch does not exist on the remote
        assert "refs/heads/feat/blast-radius-e2e" not in _remote_refs(remote)

    def test_the_blocked_push_leaves_a_real_audit_event(self, repo):
        work, remote = repo
        env = _base_env(agent=True)
        _commit_governance_change(work, env)
        before = len(_events(work, "BLAST_RADIUS_DECISION"))
        _git(work, "push", "origin", "feat/blast-radius-e2e", env=env, check=False)

        evs = _events(work, "BLAST_RADIUS_DECISION")[before:]
        assert len(evs) == 1, f"expected one new blast-radius event, got {evs}"
        ev = evs[0]
        assert ev["allowed"] is False
        assert ev["tier"] == "GOVERNANCE"
        assert ev["governance_files_touched"] == ["dv_harness/git_governance.py"]
        assert "CLAUDECODE" in ev["detected_markers"]

    def test_a_real_pinned_approval_lets_the_same_push_through(self, repo):
        """The full loop: blocked -> a human records the real approval with the
        printed digest -> the identical `git push` now succeeds and the ref
        really lands on the remote."""
        work, remote = repo
        env = _base_env(agent=True)
        _commit_governance_change(work, env)

        blocked = _git(work, "push", "origin", "feat/blast-radius-e2e", env=env, check=False)
        assert blocked.returncode != 0
        digest = json.loads(
            subprocess.run([sys.executable, "-m", "dv_harness.cli", "--project-root", str(work),
                            "blast-radius", "--base", "master", "--head", "HEAD"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace",
                           env=_base_env(agent=False), check=True).stdout)["digest"]
        assert digest

        approve = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(work),
             "approve", cbr.BLAST_RADIUS_APPROVAL_STAGE,
             "--note", f"blast-radius {digest}: reviewed, one gate file, intentional",
             "--reviewer-id", "reviewer@example.invalid"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=_base_env(agent=False))
        assert approve.returncode == 0, approve.stderr

        r = _git(work, "push", "origin", "feat/blast-radius-e2e", env=env, check=False)
        assert r.returncode == 0, f"approved push was still blocked:\n{r.stdout}\n{r.stderr}"
        assert "refs/heads/feat/blast-radius-e2e" in _remote_refs(remote)

    def test_agent_push_of_a_small_ordinary_change_is_not_gated(self, repo):
        """The gate must not become a tax on every push: a one-file, low-reach,
        non-governance change from an agent must go straight through."""
        work, remote = repo
        env = _base_env(agent=True)
        _git(work, "checkout", "-q", "-b", "feat/tiny", env=env)
        (Path(work) / "notes.md").write_text("a note\n", encoding="utf-8")
        _git(work, "add", "notes.md", env=env)
        _git(work, "commit", "-qm", "tiny doc change", env=env)

        r = _git(work, "push", "origin", "feat/tiny", env=env, check=False)

        assert r.returncode == 0, f"a tiny change was wrongly blocked:\n{r.stdout}\n{r.stderr}"
        assert "refs/heads/feat/tiny" in _remote_refs(remote)

    def test_publishing_a_branch_to_an_empty_remote_is_not_scored_as_zero_files(self, repo):
        """Regression, found by these tests: a first push of `master` to a
        remote that lacks it has no remote-side base, and merge-base(master,
        master) is master -- so the naive range was head..head and the gate
        reported a truthful-looking 'CONTAINED, 0 files changed' for a push
        whose real content is the entire branch. A fabricated measurement is
        worse than no measurement; this must be NOT_ASSESSABLE."""
        work, remote = repo
        fresh_remote = Path(work).parent / "remote2.git"
        subprocess.run([GIT, "init", "--bare", "-q", str(fresh_remote)], check=True, timeout=60)
        _git(work, "remote", "add", "origin2", str(fresh_remote))
        env = _base_env(agent=False)
        before = len(_events(work, "BLAST_RADIUS_DECISION"))

        r = _git(work, "push", "origin2", "master", env=env, check=False)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

        new = _events(work, "BLAST_RADIUS_DECISION")[before:]
        assert new == [], (
            "an unmeasurable new-branch push was scored and logged as a real "
            f"tier: {new}")

    def test_human_push_of_a_governance_change_is_not_gated(self, repo):
        work, remote = repo
        human = _base_env(agent=False)
        _commit_governance_change(work, human)

        r = _git(work, "push", "origin", "feat/blast-radius-e2e", env=human, check=False)

        assert r.returncode == 0, f"human push was wrongly blocked:\n{r.stdout}\n{r.stderr}"
        assert "refs/heads/feat/blast-radius-e2e" in _remote_refs(remote)


@pytestmark_e2e
class TestExistingBranchGateIsUnweakened:
    """The new check is ADDITIVE. These assert the old behavior is byte-for-byte
    intact on the path the new code now sits in."""

    def test_protected_branch_block_still_wins_and_still_says_what_it_said(self, repo):
        work, remote = repo
        env = _base_env(agent=True)
        # A CONTAINED change -- the blast-radius gate would allow it. The
        # branch gate must still block the push to master, with ITS message.
        (Path(work) / "notes.md").write_text("a note\n", encoding="utf-8")
        _git(work, "add", "notes.md", env=env)
        _git(work, "commit", "-qm", "tiny change on master", env=env)
        before_br = len(_events(work, "BLAST_RADIUS_DECISION"))
        before_gg = len(_events(work, "GIT_GUARD_DECISION"))

        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "protected branch 'master'" in combined
        assert "gh pr create" in combined
        # ...and the blast-radius gate never even ran for THIS push: a
        # branch-gate block is final, and exits before the second gate.
        assert len(_events(work, "BLAST_RADIUS_DECISION")) == before_br
        assert len(_events(work, "GIT_GUARD_DECISION")) == before_gg + 1

    def test_a_blast_radius_approval_cannot_unlock_a_protected_branch_push(self, repo):
        """The confirmation this gate introduces must not become a way around
        the human-review-only rule for main/master."""
        work, remote = repo
        env = _base_env(agent=True)
        (Path(work) / "notes.md").write_text("a note\n", encoding="utf-8")
        _git(work, "add", "notes.md", env=env)
        _git(work, "commit", "-qm", "tiny change on master", env=env)
        subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(work),
             "approve", cbr.BLAST_RADIUS_APPROVAL_STAGE,
             "--note", "blast-radius approved for everything", "--reviewer-id", "x"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=_base_env(agent=False), check=True)

        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode != 0, "a blast-radius approval unlocked a protected-branch push"
        assert "protected branch 'master'" in (r.stdout + r.stderr)
        assert _remote_refs(remote) == ["refs/heads/master"]  # only the fixture's own push
