"""The Three Autonomy Levels (Research-Capability Evolution master prompt
section 61), and what really enforces LEVEL C in this repo today.

This module is documentation that a test can FAIL. Section 61 separates
capability evolution into three governance levels, and the third one -- the
human-governed boundary -- names nine example actions. The obvious way to
record that is a markdown file, and the obvious failure mode of a markdown file
is that it describes enforcement which has since been renamed, narrowed, or
deleted, while continuing to read as reassuring. So the enforcement claims here
are `cites` tuples naming real importable symbols, and
`assert_level_c_citations_resolve()` turns a stale claim into a test failure.

  LEVEL A -- RESEARCH AUTONOMY. Fully automatable. Ingest information, extract
    claims, collect and classify evidence, compare prior research, inspect
    current L5, identify gaps, generate hypotheses, recommend KEEP/ENHANCE/ADD/
    EXPERIMENT/REJECT, propose benchmarks, update temporary/job-level research
    state, create architecture proposals, detect contradictions.
    MUST NOT MODIFY PRODUCTION BEHAVIOR. `capability_evolution.py` is entirely
    Level A work, which is why its "writes nothing outside <root>/.dv-harness/"
    property is a governance statement and not an implementation detail.

  LEVEL B -- EXPERIMENT AUTONOMY. May be automated within existing repository
    governance: isolated experiment plans, an experiment/feature branch, bounded
    experimental changes, static checks, build, controlled simulation, targeted
    regression, coverage, before/after comparison, benchmark metrics, experiment
    evidence, a PROMOTE/REVISE/REJECT recommendation. Two constraints, and the
    second is the one that gets forgotten:
      (1) experiment changes stay ISOLATED and REVERSIBLE;
      (2) execution obeys the EXISTING security, resource, license,
          remote-execution and repository policies, and NEVER bypasses an
          existing human-approval requirement for an action current L5 policy
          already classifies as consequential.
    Level B is permission to automate work inside the fence. It is never
    permission to move the fence.

  LEVEL C -- PRODUCTION PROMOTION. Always human-governed. Section 61's closing
    line is the operative one: "Never automatically promote experimental
    capability into production merely because a benchmark passed." The nine
    named examples and their real enforcement are LEVEL_C_EXAMPLES /
    LEVEL_C_ENFORCEMENT below. In `capability_evolution.py` this boundary is
    `assert_no_production_write_authorized()` / `assert_human_approval()`.

WHAT "NONE" MEANS BELOW, stated once so the table reads as neither more alarming
nor more reassuring than it is: every item is covered at the LAST mile by the
generic PR gate (row 1), because `git_governance.py` keys on the destination
branch and nothing else -- it does not care what the change was. "NONE" means
there is no ITEM-SPECIFIC enforcement in front of that: nothing refuses the edit
at the point it is made, nothing marks the touched artifact as consequential,
and a human reviewing the resulting PR is the only thing between the change and
production. Those items (LEVEL_C_UNENFORCED) are FLAGGED, not closed. Building
new production-safety enforcement was deliberately not attempted in the same
pass that discovered the gap: a safety mechanism authored by the pass that
decided it was needed has had no independent review, which is the failure mode
this governance model exists to prevent. They want a separate, dedicated effort.

This module deliberately holds no state, imports nothing from the harness at
module scope, and has no authority of its own -- it is an index of OTHER
modules' enforcement, so that reading it can never be mistaken for enforcing
anything.
"""
from __future__ import annotations

# Section 61's nine examples, verbatim and in order.
LEVEL_C_EXAMPLES = (
    "merging to main",
    "changing default production workflow",
    "changing signoff policy",
    "changing verification oracle semantics",
    "changing regression selection policy used for signoff",
    "changing shared schemas with production impact",
    "changing organizational verification policy",
    "enabling new autonomous destructive actions",
    "changing remote execution/security policy",
)

# status: ENFORCED  -- a real mechanism refuses the action itself
#         PARTIAL   -- a real mechanism covers a named PART; residual stated
#         NONE      -- no item-specific enforcement; generic PR gate only
#
# `cites` names real, importable module attributes so the citation can be
# CHECKED rather than believed -- see assert_level_c_citations_resolve(), which
# is what keeps this table from quietly going stale the way a prose list would.
LEVEL_C_ENFORCEMENT = {
    "merging to main": {
        "status": "ENFORCED",
        "mechanism": (
            "git_governance.evaluate_pre_push() / evaluate_pre_merge_commit() BLOCK any "
            "push or merge onto PROTECTED_BRANCHES ('main','master') from an AI-agent "
            "environment, keyed on the destination branch alone -- so it holds for a "
            "capability-evolution change exactly as it does for any other. Live in this "
            "repo (core.hooksPath = tools/git-hooks) and driven end-to-end against a real "
            "git push/merge by dv_harness_tests/test_git_hooks_e2e.py."
        ),
        "cites": (
            ("dv_harness.git_governance", "PROTECTED_BRANCHES"),
            ("dv_harness.git_governance", "evaluate_pre_push"),
            ("dv_harness.git_governance", "evaluate_pre_merge_commit"),
        ),
        "residual": (
            "Server-side branch protection -- the authoritative layer -- is still not in "
            "force (origin is empty), so the local hook is the only gate today. Disclosed "
            "in CLAUDE.md's gh CLI + PR-Only Governance Policy, not introduced here."
        ),
    },
    "changing default production workflow": {
        "status": "NONE",
        "mechanism": (
            "The default production workflow IS .dv-harness/graph/main_graph.json plus "
            "gates.STAGE_GATES. No code guards either against edit. The nearest real "
            "mechanism is self_tuning.PROTECTED_REMOVALS, and it is narrower than this "
            "item in both directions: it covers gate MEMBERSHIP only (not node/edge "
            "topology), only for four named IMPLEMENT/RE_AUDIT gates plus every "
            "PROMOTION_READINESS and SIGNOFF gate, and only along the self-tuning "
            "override path. self_tuning.propose_add_override() has no protected list at "
            "all, and propose_remove_override() will remove a gate from any OTHER stage."
        ),
        "cites": (
            ("dv_harness.self_tuning", "PROTECTED_REMOVALS"),
            ("dv_harness.self_tuning", "ELEVATED_SCRUTINY_GATES"),
        ),
        "residual": (
            "OPEN GAP. A direct edit to main_graph.json or to STAGE_GATES is refused by "
            "nothing at the point it is made."
        ),
    },
    "changing signoff policy": {
        "status": "PARTIAL",
        "mechanism": (
            "self_tuning.PROTECTED_REMOVALS is computed from the REAL "
            "STAGE_GATES['PROMOTION_READINESS'] and ['SIGNOFF'] lists (self_tuning."
            "_compute_protected_removals()), so every gate on either stage is "
            "un-removable: propose_remove_override() returns False and "
            "tools/verification_flow/self_tuning_proposal_gate.py refuses the proposal. "
            "Separately, policy.can_signoff() is a real hard stop engine.loop() consults "
            "BEFORE dispatching SIGNOFF."
        ),
        "cites": (
            ("dv_harness.self_tuning", "PROTECTED_REMOVALS"),
            ("dv_harness.policy", "can_signoff"),
        ),
        "residual": (
            "Covers gate MEMBERSHIP along the self-tuning path only. Editing a SIGNOFF "
            "gate script's own PASS/FAIL source under tools/verification_flow/, or "
            "editing policy.can_signoff() itself, is not covered -- that is the "
            "'verification oracle semantics' row below, and it is a NONE."
        ),
    },
    "changing verification oracle semantics": {
        "status": "NONE",
        "mechanism": (
            "The oracle is the PASS/FAIL logic inside tools/verification_flow/*.py and "
            "gates.py's verdict mapping. No protected list, no checksum, no gate covers "
            "the CONTENT of any gate script. PROTECTED_REMOVALS protects a gate's "
            "membership in a stage; it says nothing about what that gate decides once "
            "it runs, so a gate can keep its protected slot while its verdict logic is "
            "rewritten underneath it."
        ),
        "cites": (),
        "residual": (
            "OPEN GAP, and the highest-consequence one in this table: this is the "
            "mechanism by which a false PASS becomes possible."
        ),
    },
    "changing regression selection policy used for signoff": {
        "status": "NONE",
        "mechanism": (
            "change_impact.select_regression() and regression_tiers.py carry no protected-"
            "parameter entry and no gate. self_tuning.PROTECTED_PARAMETERS does contain "
            "two regression entries -- ('regression_submission_policy_gate', "
            "'wave_default_off') and (..., 'require_prior_failure_ref') -- but those "
            "govern how a regression is SUBMITTED (waveform default, prior-failure "
            "reference), not which tests are SELECTED as sufficient for signoff. Adjacent "
            "policy, different question."
        ),
        "cites": (("dv_harness.self_tuning", "PROTECTED_PARAMETERS"),),
        "residual": (
            "OPEN GAP. Narrowing the selection that feeds signoff is refused by nothing."
        ),
    },
    "changing shared schemas with production impact": {
        "status": "NONE",
        "mechanism": (
            "dv_harness/schemas/*.json are loaded and validated against, never guarded "
            "against edit. A loosened `required` list or a widened enum weakens every "
            "consumer at once and no mechanism notices."
        ),
        "cites": (),
        "residual": "OPEN GAP.",
    },
    "changing organizational verification policy": {
        "status": "PARTIAL",
        "mechanism": (
            "memory_router.promote_to_organizational() / organizational_admission_gate() "
            "are real code enforcing WHO may write organizational knowledge: the "
            "provenance is re-read off the durable store and ORGANIZATIONAL_MIN_"
            "CONFIRMATIONS independent confirmations are required. Since 2026-09-04 "
            "research-origin content additionally faces research_organizational_admission"
            "_reasons(), which is an AUTHORITY check (section 72: a Research Agent alone "
            "must not promote policy into Organizational Memory)."
        ),
        "cites": (
            ("dv_harness.memory_router", "promote_to_organizational"),
            ("dv_harness.memory_router", "organizational_admission_gate"),
            ("dv_harness.memory_router", "ORGANIZATIONAL_MIN_CONFIRMATIONS"),
        ),
        "residual": (
            "Enforces the policy; does not guard the policy. Lowering "
            "ORGANIZATIONAL_MIN_CONFIRMATIONS from 2 to 1 is an ordinary source edit."
        ),
    },
    "enabling new autonomous destructive actions": {
        "status": "PARTIAL",
        "mechanism": (
            ".claude/settings.json registers a real PreToolUse hook, "
            ".claude/hooks/block-destructive.ps1, on the Bash|PowerShell matcher, and "
            "context_budget's guard hook denies tier-1 reads on "
            "Read|Grep|Bash|PowerShell|NotebookRead. Both are live, not aspirational."
        ),
        "cites": (("dv_harness.context_budget", "POLICY_PATH"),),
        "residual": (
            "The hooks constrain actions; nothing constrains editing the hooks or "
            "settings.json that registers them. Both guards also fail OPEN when Python "
            "is unavailable -- disclosed in CLAUDE.md's Context Budget section, not new."
        ),
    },
    "changing remote execution/security policy": {
        "status": "NONE",
        "mechanism": (
            "The SSH/Remote Transport Connection Intake gate, the remote_relay.py "
            "invocation prohibition and its 2026-09-03 single-user amendment are all "
            "CLAUDE.md prose -- protocol an agent is trusted to follow, with no code "
            "refusing a violation. context_budget.policy.json is schema-validated on "
            "load, which checks that a policy is well-formed, never that it was not "
            "weakened."
        ),
        "cites": (),
        "residual": (
            "OPEN GAP. Editing the credential/remote-execution rules is an ordinary "
            "document edit."
        ),
    },
}

# The LEVEL C examples with NO item-specific enforcement today. Derived, never
# hand-listed, so it cannot disagree with the table above.
LEVEL_C_UNENFORCED = tuple(
    example for example in LEVEL_C_EXAMPLES
    if LEVEL_C_ENFORCEMENT[example]["status"] == "NONE"
)


def assert_level_c_citations_resolve() -> None:
    """Every `cites` entry in LEVEL_C_ENFORCEMENT must name a real, importable
    module attribute.

    This is what makes the table a CHECKED citation rather than a description of
    enforcement that may or may not still exist. A guard that is deleted or
    renamed turns its row from a claim into an ImportError/AttributeError at test
    time, which is the only way a table like this stays honest as the code around
    it moves. Rows with an empty `cites` are the NONE rows: there is nothing to
    cite, and that absence is the finding.
    """
    import importlib

    for example, entry in LEVEL_C_ENFORCEMENT.items():
        for module_name, attribute in entry["cites"]:
            module = importlib.import_module(module_name)
            if not hasattr(module, attribute):
                raise AssertionError(
                    f"LEVEL_C_ENFORCEMENT[{example!r}] cites {module_name}.{attribute}, "
                    "which no longer exists. The cited enforcement moved or was removed; "
                    "re-verify what really enforces this item before editing this table."
                )


def level_c_enforcement_report() -> str:
    """Human-readable rendering of LEVEL_C_ENFORCEMENT, unenforced items last."""
    lines = ["LEVEL C (production promotion) -- what really enforces each example today", ""]
    for example in LEVEL_C_EXAMPLES:
        entry = LEVEL_C_ENFORCEMENT[example]
        lines.append(f"[{entry['status']:8}] {example}")
        lines.append(f"           {entry['mechanism']}")
        if entry.get("residual"):
            lines.append(f"           residual: {entry['residual']}")
        lines.append("")
    lines.append("NO item-specific enforcement today (generic PR gate only):")
    for example in LEVEL_C_UNENFORCED:
        lines.append(f"  - {example}")
    return "\n".join(lines)
