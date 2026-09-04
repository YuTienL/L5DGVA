"""dv_harness/git_governance.py -- gh CLI + PR-only merge/push governance gate.

L5 requirement (2026-09-03 user spec, "gh CLI + PR-only policy" workstream):
an agent may branch / commit / open a PR, but must never merge or push
directly into a protected branch (main/master) -- human review via PR is
the only path onto those branches ("這應列入 L5 governance...禁止直接merge
main/master，Human review 才是最後 gate"). This module is the real,
callable enforcement point behind that policy.

DETECTION (Layer 2, defense-in-depth): reuses the exact AI-agent-environment
marker set tools/remote/remote_relay.py's own Layer 2 guard already
established for an analogous problem -- a privileged/irreversible operation
an agent must never perform itself (see that module's "Defense in depth"
note and its 2026-08-31 incident history). Reused directly via import
(AI_AGENT_ENV_MARKERS below), not copy-pasted, so the two guards can never
silently drift apart.

Deliberately no override variable here (unlike remote_relay.py's
DV_HARNESS_RELAY_AUTORECONNECT_OK): there is no sanctioned automated flow
under which an agent should ever push/merge directly into main/master, so
this gate is unconditional whenever an agent marker is present and the
destination is protected. A human running the identical git command from
their own interactive terminal (no agent marker in their environment) is
never blocked by this module -- this is a targeted guard against
agent-initiated direct writes to a protected branch, not a general local
branch-protection reimplementation. The real, PRIMARY gate once a GitHub
remote exists is server-side branch protection requiring PR review (see
CLAUDE.md's "gh CLI + PR-Only Governance Policy" section) -- this module is
defense-in-depth for the pre-remote/no-branch-protection-yet case, and for
any Claude Code session running git locally with no server-side gate at all.

TWO REAL CALL SITES (git hooks, see tools/git-hooks/):
- pre-push: git invokes the hook with proposed refspecs on stdin, one line
  per "<local ref> <local sha1> <remote ref> <remote sha1>" (githooks(5)).
  evaluate_pre_push() parses that text directly -- never shells out to git
  itself -- so it stays unit-testable against captured real stdin shapes.
- pre-merge-commit: git invokes this hook with no stdin payload and skips
  it entirely on a fast-forward merge (githooks(5)); the hook SCRIPT
  resolves the current branch (`git rev-parse --abbrev-ref HEAD` -- the
  branch the merge commit is about to land on) and passes it via --branch.
  evaluate_pre_merge_commit() takes that string directly.

Both hook scripts call `dv-harness git-guard --check <hook-name> [--branch
<b>]` (dv_harness/cli.py), which prints the JSON decision and exits 0
(allowed) or 1 (blocked) -- the exit code is what actually blocks git, per
githooks(5): a non-zero exit from pre-push/pre-merge-commit aborts the
operation before it takes effect.
"""
from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional


def _remote_relay_module():
    """Dynamically imports tools/remote/remote_relay.py to reuse its real
    AI_AGENT_ENV_MARKERS constant as the single source of truth for "what
    counts as an AI-agent environment marker" -- tools/remote/ has no
    __init__.py, the same not-a-package precedent dv_harness/preflight.py's
    own _remote_exec_module() and dv_harness/knowledge_center.py's private
    copy already establish for this exact directory."""
    remote_dir = str(Path(__file__).resolve().parents[1] / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    import remote_relay  # type: ignore
    return remote_relay


AI_AGENT_ENV_MARKERS = _remote_relay_module().AI_AGENT_ENV_MARKERS

# This project's real git-safety baseline: "master" is included alongside
# "main" precisely because that is this repo's own real current branch
# name, not a guess at a future convention. (State note, re-checked
# 2026-09-04: an `origin` GitHub remote now exists but is still empty, so
# no server-side branch protection can exist on it yet -- this local gate
# is currently the only thing standing between an agent and a direct
# `git push origin master`. See CLAUDE.md's gh CLI + PR-Only Governance
# Policy section for the dated, authoritative state.)
# AUTONOMY LEVEL C (Research-Capability Evolution master prompt section 61):
# this constant, and the two evaluate_* functions below, are the REAL enforcement
# behind section 61's first named example, "merging to main". The gate keys on
# the destination branch and on nothing else -- not on which feature, agent or
# workflow produced the commit -- so a capability-evolution change proposed by
# research-architect is blocked here on exactly the same terms as any other
# agent-authored push. Indexed, with the other eight LEVEL C examples and what
# does or does not enforce each, in dv_harness/autonomy_levels.py.
PROTECTED_BRANCHES = ("main", "master")

_REF_HEADS_RE = re.compile(r"^refs/heads/(.+)$")


def detect_ai_agent_markers(env: Mapping[str, str]) -> List[str]:
    """Every AI_AGENT_ENV_MARKERS name actually present with a non-empty
    value in `env`, in declared order. Empty list means an ordinary human
    interactive environment. Deliberately no override variable consulted
    here (see module docstring) -- this list alone decides Layer 2 for
    this gate."""
    return [m for m in AI_AGENT_ENV_MARKERS if env.get(m)]


def branch_from_ref(ref: str) -> Optional[str]:
    """'refs/heads/main' -> 'main'; anything not under refs/heads/ (a tag,
    refs/for/..., a raw sha for a delete) -> None, since only a real branch
    ref can be a "protected branch" in the sense this gate cares about."""
    m = _REF_HEADS_RE.match(ref.strip())
    return m.group(1) if m else None


def is_protected_branch(branch: Optional[str], protected=PROTECTED_BRANCHES) -> bool:
    return branch in protected


@dataclass
class RefspecCheck:
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str
    branch: Optional[str]
    protected: bool


@dataclass
class GuardDecision:
    hook: str  # "pre-push" | "pre-merge-commit"
    allowed: bool
    reason: str
    branch: Optional[str] = None
    detected_markers: List[str] = field(default_factory=list)
    refspecs: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_pre_push_refspecs(stdin_text: str) -> List[RefspecCheck]:
    """Parses real git pre-push hook stdin: one '<local ref> <local sha1>
    <remote ref> <remote sha1>' line per ref being pushed (githooks(5)). A
    line that does not split into exactly 4 fields is skipped rather than
    raising -- a hook must never crash git with a traceback on unexpected
    input; it should just not treat that line as a protected-branch hit."""
    out: List[RefspecCheck] = []
    for line in stdin_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        branch = branch_from_ref(remote_ref)
        out.append(RefspecCheck(local_ref, local_sha, remote_ref, remote_sha,
                                 branch, is_protected_branch(branch)))
    return out


def evaluate_pre_push(stdin_text: str, env: Mapping[str, str]) -> GuardDecision:
    """BLOCKED only when BOTH hold: at least one pushed ref targets a
    protected branch, AND the calling environment carries an AI-agent
    marker. Any other combination is allowed (a human pushing to main, or
    an agent pushing to an ordinary feature branch -- branch/commit/PR is
    exactly what the policy permits an agent to do)."""
    refspecs = parse_pre_push_refspecs(stdin_text)
    protected_hits = [r for r in refspecs if r.protected]
    markers = detect_ai_agent_markers(env)
    refspec_dicts = [asdict(r) for r in refspecs]

    if not protected_hits:
        return GuardDecision("pre-push", True,
                              "no protected branch (main/master) among the pushed refs",
                              refspecs=refspec_dicts)
    if not markers:
        return GuardDecision(
            "pre-push", True,
            "protected branch push detected, but no AI-agent environment marker present "
            "-- human-initiated push is not blocked by this gate",
            branch=protected_hits[0].branch, refspecs=refspec_dicts)
    return GuardDecision(
        "pre-push", False,
        f"BLOCKED: AI-agent environment (markers: {markers}) attempted a direct push to "
        f"protected branch '{protected_hits[0].branch}'. Open a PR instead (gh pr create) -- "
        f"merging main/master requires human review, per CLAUDE.md's gh CLI + PR-Only "
        f"Governance Policy.",
        branch=protected_hits[0].branch, detected_markers=markers, refspecs=refspec_dicts,
    )


def evaluate_pre_merge_commit(current_branch: Optional[str], env: Mapping[str, str]) -> GuardDecision:
    """Same two-condition rule as evaluate_pre_push, for a local `git
    merge` about to create a non-fast-forward merge commit ON the current
    branch (git's own pre-merge-commit hook is skipped for a fast-forward
    merge -- see githooks(5) -- so this only ever fires for a real merge
    commit, exactly the operation the policy is about)."""
    markers = detect_ai_agent_markers(env)
    protected = is_protected_branch(current_branch)
    if not protected:
        return GuardDecision("pre-merge-commit", True,
                              f"current branch '{current_branch}' is not protected",
                              branch=current_branch)
    if not markers:
        return GuardDecision(
            "pre-merge-commit", True,
            "protected branch merge detected, but no AI-agent environment marker present "
            "-- human-initiated merge is not blocked by this gate",
            branch=current_branch)
    return GuardDecision(
        "pre-merge-commit", False,
        f"BLOCKED: AI-agent environment (markers: {markers}) attempted a direct merge into "
        f"protected branch '{current_branch}'. Open a PR instead (gh pr create) -- "
        f"merging main/master requires human review, per CLAUDE.md's gh CLI + PR-Only "
        f"Governance Policy.",
        branch=current_branch, detected_markers=markers,
    )
