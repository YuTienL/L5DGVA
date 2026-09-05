"""dv_harness/change_blast_radius.py -- change-budget / blast-radius gate
(2026-09-06).

GAP THIS CLOSES. `git_governance.py` gates on ONE fact: the DESTINATION
BRANCH. It blocks an agent pushing to main/master and allows everything
else, "keyed on the destination branch and on nothing else". That is the
right rule for *where* a change lands and says nothing about *how far the
change reaches*: a one-line docstring fix on a feature branch and a
47-file rewrite of `models.py` + `gates.py` + the git hooks themselves are
indistinguishable to it. Nothing in this repo estimated a change's reach
from real signals -- the only pre-existing `blast_radius` in the tree is
`question_queue.py`'s HAND-DECLARED string field (the asker types
"single_regression" / "unbounded" itself; `classify_tier()` believes it).
A self-reported label is not a measurement.

This module is the measurement. It computes reach from three real signals
and never from an attestation:

  1. FILES TOUCHED -- a real `git diff --name-only`, via
     `change_impact.changed_files()`. Reused, not re-implemented: that
     function already owns this repo's degrade-never-raise git contract and
     its REAL_DIFF / NO_GIT / UNKNOWN_BASE / DIFF_FAILED status vocabulary,
     and a second copy of the same subprocess plumbing is exactly the
     parallel mechanism CLAUDE.md's Methodology Consolidation Rule forbids.

  2. SHARED-ACROSS-SUBSYSTEMS REACH -- the transitive IMPORTER closure of
     each changed `dv_harness/*.py` module, from a real `ast` parse of the
     package's own import statements. This is "this project's own module
     dependency structure" read off the source, not a curated list of
     "important files" someone has to remember to update. `models.py`
     scores 88 because 88 modules really can reach it; `autonomy_levels.py`
     scores 0 because nothing imports it. Neither number is typed in
     anywhere.

  3. GOVERNANCE/POLICY SELF-MODIFICATION -- does the change touch a file
     that IS a gate? Derived from `autonomy_levels.LEVEL_C_ENFORCEMENT`'s
     `cites` table plus the live hook scripts, NOT hand-listed. That table
     already names the real modules enforcing each LEVEL C example and
     already has `assert_level_c_citations_resolve()` failing a test the
     moment a citation goes stale, so deriving from it means this gate's
     notion of "a policy file" cannot silently drift from the repo's own
     notion of "what enforces policy".

WHAT IT DOES WITH THAT. Above a threshold the change is not blocked
forever -- it requires ADDITIONAL REAL CONFIRMATION, recorded through the
approval mechanism this repo already has: `ControlPlane.approve()` under
the approval-only stage key `CHANGE_BLAST_RADIUS` (registered in
`commands.APPROVAL_ONLY_STAGES`, the extension point that exists precisely
for "real code-owned approval points that are not graph stages"). No new
approval store, no new CLI verb for the human side -- the existing
`dv-harness approve` is the command.

The approval is PINNED to the assessed change: it counts only if its note
carries this assessment's `digest`, a sha256 over the exact sorted set of
changed files and the tier. Add a file, drop a file, or grow the change and
the digest moves and the old approval stops applying. That is what keeps
this from degrading into a one-time blanket bypass -- the same
exact-value-match reasoning `ControlPlane.add_cosign()` already uses ("a
value that later changes at the same location is NOT covered by a stale
cosign").

STRICTLY ADDITIVE TO THE EXISTING GATE. cli.py runs the branch gate FIRST
and unchanged; a protected-branch block still blocks with git_governance's
own decision and message. This check only ever runs on a change the branch
gate ALREADY ALLOWED, and can only turn an allow into a block, never a
block into an allow. Deleting this module restores the previous behavior
exactly.

FAIL-OPEN ON OUR OWN IGNORANCE, FAIL-CLOSED ON A REAL MEASUREMENT. If the
diff cannot be computed (no git, unresolvable base, a brand-new branch with
no merge-base), the verdict is NOT_ASSESSABLE and the push is allowed with
that stated plainly -- an environment problem must not masquerade as a
policy finding. A tier that was really measured and really exceeds the
threshold blocks.

HUMAN PUSHES ARE NOT GATED, same rule and same reason as
`git_governance.evaluate_pre_push()`: this is a guard against an agent
making a sweeping change unattended, not a local branch-protection
reimplementation. `detect_ai_agent_markers()` is imported from
git_governance rather than re-derived, so the two gates can never disagree
about what an agent environment is.
"""
from __future__ import annotations

import ast
import hashlib
import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .change_impact import changed_files, resolve_sha, _git
from .git_governance import detect_ai_agent_markers, parse_pre_push_refspecs

# The approval-only stage key a human confirms an over-threshold change
# under. Registered in commands.APPROVAL_ONLY_STAGES so the EXISTING
# `dv-harness approve` accepts it; deliberately not a models.Stage member,
# because this is not a graph node and must never drive the engine loop.
BLAST_RADIUS_APPROVAL_STAGE = "CHANGE_BLAST_RADIUS"

# --- tiers ----------------------------------------------------------------
TIER_CONTAINED = "CONTAINED"      # measured, under every threshold
TIER_WIDE = "WIDE"                # measured, reach/size over threshold
TIER_GOVERNANCE = "GOVERNANCE"    # the change edits a gate/policy file itself
TIER_NOT_ASSESSABLE = "NOT_ASSESSABLE"  # no real diff to measure

# Tiers that require a pinned human confirmation before an agent may push.
TIERS_REQUIRING_CONFIRMATION = (TIER_WIDE, TIER_GOVERNANCE)

# THRESHOLDS, calibrated against this repo's REAL import graph as measured
# 2026-09-06 (134 modules under dv_harness/): per-module transitive importer
# reach has median 19, p75 28, p90 40, max 88 (models.py). 40 is that
# measured p90 -- a change whose union reach clears it can affect roughly a
# third of the package, which is the honest meaning of "shared across
# subsystems" here. Re-derive these from the graph, do not nudge them, if
# the package's shape changes materially.
WIDE_REACH_THRESHOLD = 40
# Independent of reach: a change this broad is wide even if every file is a
# leaf nothing imports (e.g. a sweep across 30 test fixtures).
WIDE_FILE_COUNT_THRESHOLD = 25

_PACKAGE_DIR_NAME = "dv_harness"


# --- signal 2: the real module dependency structure -----------------------


def _module_name_for_path(rel_path: str) -> Optional[str]:
    """'dv_harness/gates.py' -> 'gates'. Anything not a top-level module of
    the package -> None (a subpackage file, a test, an RTL source)."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) != 2 or parts[0] != _PACKAGE_DIR_NAME:
        return None
    if not parts[1].endswith(".py"):
        return None
    return parts[1][: -len(".py")]


def _imported_siblings(tree: ast.AST, known: Set[str]) -> Set[str]:
    """Every sibling module of the package this AST imports, by any of the
    four real spellings used in this codebase: `from .x import y`,
    `from . import x`, `from dv_harness.x import y`, `import dv_harness.x`.
    Only names in `known` are kept, so a stdlib or third-party import can
    never be mistaken for an intra-package edge."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module is None:
                # from . import gates, models
                out.update(a.name for a in node.names if a.name in known)
            elif node.level == 1 and node.module:
                head = node.module.split(".")[0]
                if head in known:
                    out.add(head)
            elif node.module and node.module.startswith(_PACKAGE_DIR_NAME + "."):
                head = node.module.split(".")[1]
                if head in known:
                    out.add(head)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_PACKAGE_DIR_NAME + "."):
                    head = alias.name.split(".")[1]
                    if head in known:
                        out.add(head)
    return out


def build_import_graph(package_dir: Path) -> Dict[str, Set[str]]:
    """`{module: {sibling modules it imports}}` from a real `ast` parse of
    every top-level .py in the package.

    A file that fails to parse contributes NO edges rather than raising --
    a gate must not crash git over a syntax error somewhere else in the
    tree -- but it is still a node, so a change to it is still measurable.
    """
    package_dir = Path(package_dir)
    known = {p.stem for p in package_dir.glob("*.py")}
    graph: Dict[str, Set[str]] = {m: set() for m in known}
    for path in sorted(package_dir.glob("*.py")):
        try:
            # Warnings suppressed deliberately: ast.parse re-emits every
            # SyntaxWarning in the parsed source (invalid escape sequences in
            # other modules' docstrings, in this tree's case). Those belong to
            # a linter, not to a git hook -- a gate that prints unrelated
            # warnings into the middle of someone's `git push` output teaches
            # them to stop reading it.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        graph[path.stem] = _imported_siblings(tree, known)
    return graph


def reverse_edges(graph: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """`{module: {modules that DIRECTLY import it}}` -- the direction reach
    actually travels when a module changes."""
    rev: Dict[str, Set[str]] = {m: set() for m in graph}
    for importer, imported in graph.items():
        for target in imported:
            rev.setdefault(target, set()).add(importer)
    return rev


def importer_closure(modules: Sequence[str], reverse: Dict[str, Set[str]]) -> Set[str]:
    """Every module transitively reachable from `modules` along importer
    edges, INCLUDING the changed modules themselves (a changed module is
    part of its own blast radius). Cycle-safe."""
    seen: Set[str] = set()
    stack = list(modules)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(reverse.get(current, ()))
    return seen


# --- signal 3: governance/policy files, DERIVED not hand-listed -----------

# Path prefixes that are governance by construction rather than by citation:
# the live hook scripts are the thing git actually executes, and no import
# graph or LEVEL C citation can see a shell script.
GOVERNANCE_PATH_PREFIXES = ("tools/git-hooks/",)


def governance_files(package_dir: Optional[Path] = None) -> Set[str]:
    """Repo-relative paths of the files that ARE gates.

    Derived from `autonomy_levels.LEVEL_C_ENFORCEMENT`'s `cites` -- the
    repo's own checked table of what really enforces each LEVEL C
    (production-promotion) example -- plus GOVERNANCE_PATH_PREFIXES for the
    non-Python hook scripts. Nothing here is a curated "important files"
    list: adding real enforcement to the LEVEL C table automatically brings
    that module under this gate, and deleting enforcement removes it (and
    trips that table's own `assert_level_c_citations_resolve()` first).
    """
    from . import autonomy_levels

    out: Set[str] = set()
    for entry in autonomy_levels.LEVEL_C_ENFORCEMENT.values():
        for module_name, _attribute in entry.get("cites", ()):
            if not module_name.startswith(_PACKAGE_DIR_NAME + "."):
                continue
            out.add(module_name.replace(".", "/") + ".py")
    # This module and the table it derives from are themselves gate files:
    # a change that edits the blast-radius gate, or edits the citation table
    # the gate reads its governance set out of, is exactly the change that
    # most needs a human to look at it.
    out.add(f"{_PACKAGE_DIR_NAME}/change_blast_radius.py")
    out.add(f"{_PACKAGE_DIR_NAME}/autonomy_levels.py")
    return out


def is_governance_file(rel_path: str, governance_set: Set[str]) -> bool:
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if normalized in governance_set:
        return True
    return any(normalized.startswith(prefix) for prefix in GOVERNANCE_PATH_PREFIXES)


# --- the assessment -------------------------------------------------------


@dataclass
class BlastRadiusAssessment:
    tier: str
    diff_status: str                 # change_impact.changed_files()'s own status
    base_sha: Optional[str]
    head_sha: Optional[str]
    file_count: int
    changed_files: List[str] = field(default_factory=list)
    changed_modules: List[str] = field(default_factory=list)
    reach_modules: List[str] = field(default_factory=list)
    reach: int = 0
    governance_files_touched: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    digest: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _digest(tier: str, files: Sequence[str]) -> str:
    """sha256 over the tier plus the exact sorted changed-file set.

    Deliberately NOT over the SHAs: a rebase or an amend that leaves the
    same files touched at the same tier keeps the same digest, so a human
    who reviewed "these 31 files, GOVERNANCE tier" does not have to
    re-confirm an identical change under a new sha. Touching one more file
    -- the thing that actually enlarges the radius -- does move it.
    """
    payload = json.dumps({"tier": tier, "files": sorted(files)},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def assess_changed_files(root: Path, files: Sequence[str], *, diff_status: str = "REAL_DIFF",
                         base_sha: Optional[str] = None,
                         head_sha: Optional[str] = None) -> BlastRadiusAssessment:
    """Score an already-computed changed-file list. Split out from the git
    plumbing so the scoring rules are testable against a synthetic file list
    with no repository involved at all."""
    normalized = sorted({str(f).replace("\\", "/") for f in files if str(f).strip()})
    if diff_status != "REAL_DIFF":
        return BlastRadiusAssessment(
            tier=TIER_NOT_ASSESSABLE, diff_status=diff_status, base_sha=base_sha,
            head_sha=head_sha, file_count=0,
            reasons=[f"no real diff to measure (status={diff_status}); "
                     "allowing, and saying so rather than inventing a tier"],
            digest="")

    package_dir = Path(root) / _PACKAGE_DIR_NAME
    graph = build_import_graph(package_dir) if package_dir.is_dir() else {}
    reverse = reverse_edges(graph)

    changed_modules = sorted({m for m in (_module_name_for_path(f) for f in normalized)
                              if m is not None and m in graph})
    reach_modules = sorted(importer_closure(changed_modules, reverse)) if changed_modules else []

    gov_set = governance_files(package_dir)
    gov_touched = sorted(f for f in normalized if is_governance_file(f, gov_set))

    reasons: List[str] = []
    tier = TIER_CONTAINED
    if gov_touched:
        tier = TIER_GOVERNANCE
        reasons.append(
            f"touches {len(gov_touched)} governance/policy file(s) that themselves enforce a "
            f"gate: {', '.join(gov_touched)}")
    if len(reach_modules) >= WIDE_REACH_THRESHOLD:
        if tier == TIER_CONTAINED:
            tier = TIER_WIDE
        reasons.append(
            f"import reach {len(reach_modules)} modules (>= {WIDE_REACH_THRESHOLD}) from "
            f"{len(changed_modules)} changed dv_harness module(s): "
            f"{', '.join(changed_modules)}")
    if len(normalized) >= WIDE_FILE_COUNT_THRESHOLD:
        if tier == TIER_CONTAINED:
            tier = TIER_WIDE
        reasons.append(f"{len(normalized)} files changed (>= {WIDE_FILE_COUNT_THRESHOLD})")
    if not reasons:
        reasons.append(
            f"{len(normalized)} file(s), import reach {len(reach_modules)} module(s), no "
            "governance/policy file touched -- under every threshold")

    return BlastRadiusAssessment(
        tier=tier, diff_status=diff_status, base_sha=base_sha, head_sha=head_sha,
        file_count=len(normalized), changed_files=normalized,
        changed_modules=changed_modules, reach_modules=reach_modules,
        reach=len(reach_modules), governance_files_touched=gov_touched,
        reasons=reasons, digest=_digest(tier, normalized))


_ZERO_SHA = "0" * 40


def _merge_base(root: Path, a: str, b: str) -> Optional[str]:
    """Real `git merge-base`, through change_impact's own git wrapper (its
    degrade-never-raise contract is the one this repo already relies on;
    a second subprocess wrapper here would be a duplicate)."""
    rc, out, _ = _git(Path(root), ["merge-base", a, b])
    return out.strip() if rc == 0 and out.strip() else None


def push_diff_range(root: Path, refspecs) -> Tuple[Optional[str], Optional[str], str]:
    """(base, head, status) for a pre-push, from git's own refspec lines.

    An existing remote branch gives an exact range: remote_sha..local_sha.
    A brand-new branch arrives with an all-zero remote sha (githooks(5)) and
    has no such range; the honest base is then the merge-base with the
    protected branch the work forked from. If neither resolves, the status
    says NEW_BRANCH_NO_MERGE_BASE and nothing is scored -- see the module
    docstring's fail-open-on-our-own-ignorance rule.

    A merge-base EQUAL to head is rejected rather than used (found by the
    end-to-end tests): pushing `master` itself to a remote that does not yet
    have it makes merge-base(master, master) == master, and the resulting
    empty `head..head` diff would be scored as a truthful "0 files changed,
    CONTAINED". That is a fabricated measurement of a push whose real content
    is the entire branch, and it is precisely the case the NOT_ASSESSABLE
    tier exists for. Same for a merge-base equal to head reached via any
    other protected branch that is an ancestor-free match.
    """
    from .git_governance import PROTECTED_BRANCHES

    pushed = [r for r in refspecs if r.local_sha and r.local_sha != _ZERO_SHA]
    if not pushed:
        return None, None, "NO_PUSHED_COMMITS"
    head = pushed[-1].local_sha
    existing = [r for r in pushed if r.remote_sha and r.remote_sha != _ZERO_SHA]
    if existing:
        return existing[-1].remote_sha, head, "REAL_DIFF"
    head_sha = resolve_sha(Path(root), head) or head
    for branch in PROTECTED_BRANCHES:
        if resolve_sha(Path(root), branch) is None:
            continue
        base = _merge_base(Path(root), head, branch)
        if base and base != head_sha:
            return base, head, "REAL_DIFF"
    return None, head, "NEW_BRANCH_NO_MERGE_BASE"


def assess_range(root: Path, base_rev: Optional[str], head_rev: Optional[str], *,
                 range_status: str = "REAL_DIFF") -> BlastRadiusAssessment:
    """Assess a real revision range, or report why it could not be."""
    if range_status != "REAL_DIFF" or not base_rev or not head_rev:
        return assess_changed_files(root, [], diff_status=range_status,
                                     base_sha=base_rev, head_sha=head_rev)
    diff = changed_files(Path(root), base_rev, head_rev)
    return assess_changed_files(root, diff["files"], diff_status=diff["status"],
                                 base_sha=diff.get("base_sha"), head_sha=diff.get("head_sha"))


# --- the pinned confirmation ---------------------------------------------


def confirmation_command(digest: str) -> str:
    """The exact, real command a human runs to confirm this assessment.
    Printed in the block message so the instruction is copy-pasteable
    instead of a description of an approval that has to be looked up."""
    return (f"dv-harness approve {BLAST_RADIUS_APPROVAL_STAGE} "
            f"--note 'blast-radius {digest}: <what you reviewed>' "
            f"--reviewer-id <you> --reviewer-confidence HIGH|MEDIUM|LOW")


def confirmation_status(root: Path, digest: str) -> Dict[str, object]:
    """Is there a real, PINNED human confirmation on disk for this exact
    assessment? Reads the same `.dv-harness/control.json` approvals every
    other human-approval check in this harness reads -- never a second store.

    An approval whose note does not carry `digest` is reported as PRESENT
    BUT STALE rather than silently ignored: "you approved a different
    version of this change" is a different, more useful fact than "no
    approval".
    """
    from .control_plane import ControlPlane

    approval = ControlPlane(Path(root)).get_approval(BLAST_RADIUS_APPROVAL_STAGE)
    if not approval:
        return {"confirmed": False, "state": "ABSENT", "approval": None}
    note = str(approval.get("note") or "")
    if digest and digest in note:
        return {"confirmed": True, "state": "PINNED_MATCH", "approval": approval}
    return {"confirmed": False, "state": "STALE_DIGEST", "approval": approval}


@dataclass
class BlastRadiusDecision:
    hook: str
    allowed: bool
    reason: str
    tier: str
    detected_markers: List[str] = field(default_factory=list)
    assessment: Optional[dict] = None
    confirmation: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


def decide(root: Path, hook: str, assessment: BlastRadiusAssessment,
           env: Mapping[str, str]) -> BlastRadiusDecision:
    """The gate proper. Blocks only when ALL of: a real measurement exists,
    its tier is over threshold, the caller is an AI-agent environment, and
    no pinned human confirmation is on disk."""
    markers = detect_ai_agent_markers(env)
    payload = assessment.to_dict()

    if assessment.tier == TIER_NOT_ASSESSABLE:
        return BlastRadiusDecision(hook, True, assessment.reasons[0], assessment.tier,
                                    detected_markers=markers, assessment=payload)
    if assessment.tier not in TIERS_REQUIRING_CONFIRMATION:
        return BlastRadiusDecision(
            hook, True,
            f"blast radius {assessment.tier}: {assessment.reasons[0]}",
            assessment.tier, detected_markers=markers, assessment=payload)
    if not markers:
        return BlastRadiusDecision(
            hook, True,
            f"blast radius {assessment.tier}, but no AI-agent environment marker present "
            "-- a human's own push is not gated on change size, same rule as the "
            "PR-only branch gate",
            assessment.tier, detected_markers=markers, assessment=payload)

    confirmation = confirmation_status(Path(root), assessment.digest)
    if confirmation["confirmed"]:
        approval = confirmation["approval"] or {}
        return BlastRadiusDecision(
            hook, True,
            f"blast radius {assessment.tier}, confirmed by {approval.get('reviewer_id')} "
            f"at {approval.get('approved_at')} for this exact change "
            f"(digest {assessment.digest})",
            assessment.tier, detected_markers=markers, assessment=payload,
            confirmation=confirmation)

    stale = ""
    if confirmation["state"] == "STALE_DIGEST":
        stale = ("A CHANGE_BLAST_RADIUS approval exists but was recorded for a DIFFERENT "
                 "change (its note does not carry this digest) -- the change has grown or "
                 "moved since it was reviewed, so it needs confirming again. ")
    return BlastRadiusDecision(
        hook, False,
        f"BLOCKED: AI-agent environment (markers: {markers}) is pushing a "
        f"{assessment.tier}-blast-radius change without human confirmation. "
        f"{'; '.join(assessment.reasons)}. {stale}"
        f"This does not replace the PR-only branch gate -- it is an additional check on how "
        f"far the change reaches. Split the change, or have a human review it and run: "
        f"{confirmation_command(assessment.digest)}",
        assessment.tier, detected_markers=markers, assessment=payload,
        confirmation=confirmation)


def evaluate_pre_push(root: Path, stdin_text: str, env: Mapping[str, str]) -> BlastRadiusDecision:
    """Blast-radius verdict for a real pre-push, from git's own refspec
    stdin. Parsed with git_governance.parse_pre_push_refspecs() -- the same
    parser the branch gate uses, so the two gates always see the identical
    push."""
    refspecs = parse_pre_push_refspecs(stdin_text)
    base, head, status = push_diff_range(Path(root), refspecs)
    return decide(Path(root), "pre-push", assess_range(Path(root), base, head,
                                                        range_status=status), env)


def evaluate_pre_merge_commit(root: Path, merge_head: Optional[str],
                              env: Mapping[str, str]) -> BlastRadiusDecision:
    """Blast-radius verdict for a local merge about to create a merge
    commit. git passes the hook nothing, so the hook script supplies
    MERGE_HEAD; the range assessed is merge-base(HEAD, MERGE_HEAD)..MERGE_HEAD
    -- the commits the merge would actually bring in, not the whole branch."""
    root = Path(root)
    if not merge_head:
        return decide(root, "pre-merge-commit",
                      assess_changed_files(root, [], diff_status="NO_MERGE_HEAD"), env)
    head = resolve_sha(root, merge_head)
    if head is None:
        return decide(root, "pre-merge-commit",
                      assess_changed_files(root, [], diff_status="UNKNOWN_MERGE_HEAD"), env)
    base = _merge_base(root, "HEAD", head)
    if base is None:
        return decide(root, "pre-merge-commit",
                      assess_changed_files(root, [], diff_status="NO_MERGE_BASE"), env)
    return decide(root, "pre-merge-commit", assess_range(root, base, head), env)
