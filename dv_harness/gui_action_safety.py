"""dv_harness/gui_action_safety.py -- GUI Action Safety Framework (2026-09-06)

Every mutating dashboard endpoint is a CONSEQUENTIAL action -- GUI-19/PC-6
(`dashboard_auth.py`, on disk as the real "dashboard authorization matrix"
this project's own test suite names it, `test_dashboard_authorization_matrix
.py`) already gate every one of them behind a session token and a per-action
VIEWER/OPERATOR/APPROVER role. What did not exist anywhere in this repo,
confirmed by direct search before writing a line of this, was a per-action
SAFETY DECLARATION: which of the twenty-one real dispatched actions belongs
to which class of consequence, what real project state each one touches,
whether it can be undone at all, and -- when it can -- what the undo
concretely is. `dashboard_auth.py` answers "who may do this"; this module
answers "what does doing this actually mean".

Reuse over reinvent, on every axis this framework declares:

  - **Required permission** is never a second VIEWER/OPERATOR/APPROVER table.
    Every declaration's `required_role` is computed by calling
    `dashboard_auth.required_role()` itself at MODULE IMPORT time, for each
    of the 24 real actions -- so this module can never silently drift from
    the real authorization matrix; if that table's role for an action
    changes, this module's declaration changes with it on the next import,
    automatically, with no second edit.
  - **Rollback plan** reuses `capability_evolution.shadow_rollback_manifest(
    )`'s own PATTERN, not its code (that function restores git-tracked FILES
    from an experiment's untouched baseline arm -- a different domain from a
    JSON sub-key inside `.dv-harness/control.json`). The pattern kept:
    (1) a rollback record is built from REAL recorded evidence, never
    authored prose; (2) each entry names a `restore_action`; (3) the record
    always carries `applied: False`; (4) producing the manifest is the
    mechanism -- APPLYING it is a separate, human act this module never
    performs (there is no write/apply function anywhere in this file, held
    by `assert_module_only_reads()` below). The real evidence source for the
    13 `/api/control` commands is `gui_audit_log.py`'s own already-real,
    already-tested structured audit record (`who`/`when`/`before`/`after`/
    `evidence`/`approval`/`result`) -- this module never captures a second
    before/after snapshot of its own; it reads the one `gui_audit_log.py`
    already writes.
  - **Category coverage** is checked against dashboard.py's REAL dispatch
    the same way `dashboard_auth.assert_endpoints_mapped()`/
    `assert_control_commands_mapped()` already do -- this module calls those
    two functions directly (never re-parsing `dashboard.py`'s source a
    second time) and then checks its OWN 24-action table covers exactly the
    same real action set those two functions just proved `dashboard_auth.py`
    covers.

The 11 categories are not copied from a document unavailable in this
checkout -- no file anywhere in this repository names an external "11
consequential-action categories" list, confirmed by a repo-wide search
before this module was written. They are instead a closed, EVIDENCE-DERIVED
grouping of the real 24 actions `dashboard_auth.py`'s own two dispatch
tables (`ENDPOINT_REQUIRED_ROLE`, `CONTROL_COMMAND_REQUIRED_ROLE`) already
enumerate, following that same module's own stated grouping rationale (e.g.
its docstring's own "writes a real human DECISION into this project's audit
trail" split for APPROVE/COSIGN/CORRECT/RESEARCH_*). `assert_
category_coverage_is_total()` (run at import) proves every category is used
by at least one real action and no action falls outside the 11.

Evidence Truth Rule, applied to every field this module reports:
  - `scope` cites the REAL file/state each action mutates (verified against
    `control_plane.py`/`commands.py`/`dashboard.py`/`session_snapshot.py`/
    `waiver_store.py`/`signoff_export.py` source, not assumed from a name).
  - `reversible`/`rollback_plan_kind` are FALSE/`NOT_REVERSIBLE` unless a
    real, exposed reversal mechanism exists for that action specifically --
    not merely somewhere in the codebase. `waiver_store.revoke_waiver()`
    exists and is real, but is not wired to any dashboard POST endpoint
    today; the WAIVER_AUTHORING declaration says so in its own `note` rather
    than claiming a GUI-level reversibility that does not exist.
  - `build_rollback_plan()` never fabricates a restore for an action with no
    real captured evidence: a reversible action with no matching
    `gui_audit_log` record reports `NO_RECORD_FOUND`, and a reversible
    action this module has no evidence-capture route for at all (the 8
    non-`/api/control` endpoints -- `gui_audit_log.py` wraps `/api/control`
    only) reports `NO_EVIDENCE_CAPTURE_FOR_THIS_ACTION`, never a guessed
    "before" value.

FLAG_SUSPICIOUS and this module's 11 categories (2026-09-07): a real, new,
CLI-reachable verb now exists -- `ControlPlane.flag_suspicious()`
(`control_plane.py`) / `commands.cmd_flag_suspicious()` -- letting a reviewer
mark one specific already-produced gate result or evidence citation as
suspicious/needing re-verification, distinct from CORRECT (a whole-stage
reset, category CAT_DECISION_APPROVAL below) and from COSIGN (opt-in
agreement, scoped only to `gates.JUDGMENT_FIELDS`, also
CAT_DECISION_APPROVAL). It deliberately gets NO 12th entry in
ACTION_CATEGORIES: every category here answers "which class of consequence
does one of the 24 REAL dashboard-dispatched `/api/control` commands belong
to" (`assert_category_coverage_is_total()` requires each of the 11 to be
used by at least one such REAL declaration, checked at import), and
FLAG_SUSPICIOUS is not one -- `dashboard.py`'s `_dispatch_control()` has no
`cmd == "FLAG_SUSPICIOUS"` branch, so `dashboard_auth.
dispatched_control_commands()` would never see it and a declaration for it
here would fail `assert_coverage_matches_real_dispatch()`'s drift guard the
moment that function is called. This is disclosed rather than silently
absent: FLAG_SUSPICIOUS is a REACHED capability (real, callable from CLI/GUI
code via `commands.cmd_flag_suspicious()`), not yet a WIRED dashboard action
-- the same REACHED-vs-WIRED distinction several other modules in this
project draw for a mechanism with a real implementation and no dashboard
dispatch branch yet. Wiring a dashboard `POST /api/control` command for it
(and the matching 12th declaration this module would then need) is future
work in `dashboard.py`, out of this module's own file scope.

SIGNOFF BUNDLE SECOND REVIEW (2026-09-07, item id
"no-second-reviewer-mechanism-at-signoff-scope"): the same REACHED-vs-WIRED
shape as FLAG_SUSPICIOUS above, one paragraph earlier the same day.
`control_plane.ControlPlane.add_bundle_review()`/`get_bundle_reviews()`/
`has_independent_bundle_review()`/`assert_bundle_second_review_satisfied()`
are real, additive, tested methods closing a real gap: `approvals[stage]`
held exactly ONE reviewer record per stage (overwritten on every fresh
`approve()` call), and `question_queue.QuestionQueueStore.
add_decision_cosign()` co-signs one already-recorded Tier-3 intake DECISION,
not a whole signoff evidence bundle -- neither covered a second human
independently reviewing the WHOLE bundle before it is approved.
`signoff_export.bundle_second_review_status()` is the matching PURE
function (a `reviews` list the caller already fetched, exactly this
module's own "touches no approval machinery" pattern -- see
`freeze_acceptance_status()`). None of this gets a 22nd declaration here:
`dashboard.py` has no `POST /api/control` branch for recording a bundle
review (no `ADD_BUNDLE_REVIEW`-shaped `cmd` anywhere in
`_dispatch_control()`), so a declaration for it would fail
`assert_coverage_matches_real_dispatch()`'s drift guard the moment that
function runs, the identical reason FLAG_SUSPICIOUS gets none. This is a
REACHED capability (real, callable from Python/CLI code), not yet a WIRED
dashboard action -- wiring a `POST /api/control` command for it (and the
matching 22nd declaration this module would then need) is future work in
`dashboard.py`/`commands.py`, out of this module's own file scope. The
existing `/api/signoff-export` declaration's own `note` below names both
mechanisms together, since a human reviewing a just-produced bundle is the
natural moment to either file a clarifying question about one evidence
item or record their own independent review of the whole bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import dashboard_auth

# ---- The 11 consequential-action categories --------------------------------

CAT_HARNESS_LIFECYCLE = "HARNESS_LIFECYCLE"
CAT_RUN_CONTROL = "RUN_CONTROL"
CAT_TAKEOVER_CONTROL = "TAKEOVER_CONTROL"
CAT_STAGE_REDIRECT = "STAGE_REDIRECT"
CAT_CONSTRAINT_MANAGEMENT = "CONSTRAINT_MANAGEMENT"
CAT_DECISION_APPROVAL = "DECISION_APPROVAL"
CAT_RESEARCH_GOVERNANCE = "RESEARCH_GOVERNANCE"
CAT_POLICY_CONFIGURATION = "POLICY_CONFIGURATION"
CAT_WAIVER_AUTHORING = "WAIVER_AUTHORING"
CAT_SIGNOFF_EXPORT = "SIGNOFF_EXPORT"
CAT_SESSION_AND_FILE_STATE = "SESSION_AND_FILE_STATE"

#: Ordered so a rendered table reads roughly lifecycle -> steering ->
#: governance -> artifacts, but order carries no other meaning.
ACTION_CATEGORIES = (
    CAT_HARNESS_LIFECYCLE, CAT_RUN_CONTROL, CAT_TAKEOVER_CONTROL,
    CAT_STAGE_REDIRECT, CAT_CONSTRAINT_MANAGEMENT, CAT_DECISION_APPROVAL,
    CAT_RESEARCH_GOVERNANCE, CAT_POLICY_CONFIGURATION, CAT_WAIVER_AUTHORING,
    CAT_SIGNOFF_EXPORT, CAT_SESSION_AND_FILE_STATE,
)
if len(ACTION_CATEGORIES) != 11:  # pragma: no cover - self-check
    raise AssertionError(f"ACTION_CATEGORIES must carry exactly 11 entries, got {len(ACTION_CATEGORIES)}")

# ---- Impact vocabulary ------------------------------------------------------

IMPACT_STATE_MUTATION_REVERSIBLE = "STATE_MUTATION_REVERSIBLE"
IMPACT_GOVERNANCE_RECORD = "GOVERNANCE_RECORD_NOT_REVERSIBLE"
IMPACT_PROJECT_CONFIG_WRITE = "PROJECT_CONFIG_WRITE"
IMPACT_FILE_ARTIFACT_WRITE = "FILE_ARTIFACT_WRITE"
IMPACT_EXTERNAL_PROCESS_LAUNCH = "EXTERNAL_PROCESS_LAUNCH"

IMPACT_VALUES = (
    IMPACT_STATE_MUTATION_REVERSIBLE, IMPACT_GOVERNANCE_RECORD,
    IMPACT_PROJECT_CONFIG_WRITE, IMPACT_FILE_ARTIFACT_WRITE,
    IMPACT_EXTERNAL_PROCESS_LAUNCH,
)

# ---- Rollback-plan-kind vocabulary (the declared SHAPE; see build_rollback_plan()) --

ROLLBACK_KIND_SCOPE_RESTORE = "SCOPE_RESTORE"
ROLLBACK_KIND_FILE_ARTIFACT_DELETE = "FILE_ARTIFACT_DELETE"
ROLLBACK_KIND_NOT_REVERSIBLE = "NOT_REVERSIBLE"

ROLLBACK_KINDS = (
    ROLLBACK_KIND_SCOPE_RESTORE, ROLLBACK_KIND_FILE_ARTIFACT_DELETE,
    ROLLBACK_KIND_NOT_REVERSIBLE,
)

#: Which rollback_plan_kind values are legal for a reversible=True /
#: reversible=False declaration -- checked by validate_declaration(), never
#: left to be independently consistent by convention alone.
_ROLLBACK_KINDS_FOR_REVERSIBLE = frozenset({ROLLBACK_KIND_SCOPE_RESTORE, ROLLBACK_KIND_FILE_ARTIFACT_DELETE})
_ROLLBACK_KINDS_FOR_IRREVERSIBLE = frozenset({ROLLBACK_KIND_NOT_REVERSIBLE})

# ---- Rollback-report status vocabulary (build_rollback_plan()'s own outcome) --

RB_STATUS_BUILT = "ROLLBACK_PLAN_BUILT"
RB_STATUS_NOT_REVERSIBLE = "NOT_REVERSIBLE"
RB_STATUS_NO_EVIDENCE_ROUTE = "NO_EVIDENCE_CAPTURE_FOR_THIS_ACTION"
RB_STATUS_NO_RECORD_FOUND = "NO_RECORD_FOUND"
RB_STATUS_DISPATCH_FAILED = "DISPATCH_FAILED_NOTHING_TO_ROLL_BACK"

RB_STATUSES = (
    RB_STATUS_BUILT, RB_STATUS_NOT_REVERSIBLE, RB_STATUS_NO_EVIDENCE_ROUTE,
    RB_STATUS_NO_RECORD_FOUND, RB_STATUS_DISPATCH_FAILED,
)


class GuiActionSafetyError(Exception):
    """A declaration failed its own internal-consistency check, or a caller
    asked about an action_id this module has no declaration for."""


class GuiActionSafetyDriftError(GuiActionSafetyError):
    """`assert_coverage_matches_real_dispatch()`'s own refusal: this
    module's 24-action table no longer matches dashboard.py's real dispatch
    that `dashboard_auth.py` itself just proved it covers."""


# ---- The declaration record --------------------------------------------------

@dataclass(frozen=True)
class GUIActionDeclaration:
    action_id: str          # dashboard_auth.required_role()'s own action label
    category: str
    scope: str               # the real file/sub-state this action mutates
    impact: str
    required_role: str       # VIEWER / OPERATOR / APPROVER, computed, never hand-typed
    reversible: bool
    rollback_plan_kind: str
    note: str = ""            # optional disclosed caveat (see module docstring)


def _declare(*, path: str, control_command: Optional[str], category: str,
             scope: str, impact: str, reversible: bool, rollback_plan_kind: str,
             note: str = "") -> GUIActionDeclaration:
    """The one constructor. Computes `required_role`/`action_id` by calling
    the REAL `dashboard_auth.required_role()` rather than accepting either
    as a caller-supplied value -- a declaration can never assert a
    permission dashboard_auth.py itself would not also compute."""
    role, action_id = dashboard_auth.required_role(path, control_command)
    decl = GUIActionDeclaration(
        action_id=action_id, category=category, scope=scope, impact=impact,
        required_role=role, reversible=reversible,
        rollback_plan_kind=rollback_plan_kind, note=note,
    )
    violations = validate_declaration(decl)
    if violations:
        raise GuiActionSafetyError(
            f"{action_id}: internally inconsistent declaration: {'; '.join(violations)}")
    return decl


def validate_declaration(decl: GUIActionDeclaration) -> List[str]:
    """Every internal-consistency rule this framework holds a declaration
    to. Returns the (possibly empty) list of violations rather than raising,
    so a caller can collect every defect across the whole table in one pass
    (`validate_all_declarations()`) instead of stopping at the first."""
    violations: List[str] = []
    if decl.category not in ACTION_CATEGORIES:
        violations.append(f"category {decl.category!r} is not one of the 11 declared categories")
    if decl.impact not in IMPACT_VALUES:
        violations.append(f"impact {decl.impact!r} is not a recognized impact value")
    if decl.rollback_plan_kind not in ROLLBACK_KINDS:
        violations.append(f"rollback_plan_kind {decl.rollback_plan_kind!r} is not recognized")
    if decl.required_role not in dashboard_auth.ROLES:
        violations.append(f"required_role {decl.required_role!r} is not one of dashboard_auth.ROLES")
    if not decl.scope or not decl.scope.strip():
        violations.append("scope must be a real, non-empty citation of the mutated state")
    if decl.reversible and decl.rollback_plan_kind not in _ROLLBACK_KINDS_FOR_REVERSIBLE:
        violations.append(
            f"reversible=True requires rollback_plan_kind in {sorted(_ROLLBACK_KINDS_FOR_REVERSIBLE)}, "
            f"got {decl.rollback_plan_kind!r}")
    if not decl.reversible and decl.rollback_plan_kind not in _ROLLBACK_KINDS_FOR_IRREVERSIBLE:
        violations.append(
            f"reversible=False requires rollback_plan_kind == {ROLLBACK_KIND_NOT_REVERSIBLE!r}, "
            f"got {decl.rollback_plan_kind!r}")
    # Re-cross-check the stored role against a FRESH call, in case a caller
    # constructed a GUIActionDeclaration by hand rather than through
    # _declare() -- the permission field must never merely have been correct
    # ONCE at construction time.
    is_control = decl.action_id.startswith(f"POST {dashboard_auth.CONTROL_ENDPOINT} ")
    if is_control:
        cmd = decl.action_id[len(f"POST {dashboard_auth.CONTROL_ENDPOINT} "):]
        expected_role, _ = dashboard_auth.required_role(dashboard_auth.CONTROL_ENDPOINT, cmd)
    else:
        endpoint = decl.action_id[len("POST "):] if decl.action_id.startswith("POST ") else decl.action_id
        expected_role, _ = dashboard_auth.required_role(endpoint)
    if decl.required_role != expected_role:
        violations.append(
            f"required_role {decl.required_role!r} disagrees with dashboard_auth.required_role() "
            f"({expected_role!r}) for this action -- stale declaration")
    return violations


def validate_all_declarations() -> Dict[str, List[str]]:
    """Every declared action's violations, keyed by action_id -- entries with
    an empty list are clean. Never raises; a caller decides what to do with
    a non-empty result."""
    return {decl.action_id: validate_declaration(decl) for decl in GUI_ACTION_DECLARATIONS.values()}


# ---- The 24 real declarations -----------------------------------------------
# Every `path`/`control_command` pair here is a real branch in
# dashboard.py's do_POST()/_dispatch_control() (verified by direct reading,
# 2026-09-06). `assert_coverage_matches_real_dispatch()` re-checks this
# against dashboard.py's own source at call time.

_DECLARATIONS: Tuple[GUIActionDeclaration, ...] = (
    _declare(
        path="/api/setup", control_command=None,
        category=CAT_HARNESS_LIFECYCLE,
        scope=".dv-harness/project_meta.json (db_path, working_path, configured_at) "
              "-- see dashboard._save_project_meta()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
        note="Reversible by re-POSTing the prior db_path/working_path; no gui_audit_log "
             "coverage exists for this endpoint, so build_rollback_plan() cannot cite a "
             "real captured 'before' value for it (NO_EVIDENCE_CAPTURE_FOR_THIS_ACTION).",
    ),
    _declare(
        path="/api/start", control_command=None,
        category=CAT_HARNESS_LIFECYCLE,
        scope="spawns a background DVHarness worker thread "
              "(dashboard._start_background_run()) that writes .dv-harness/state.json "
              "and .dv-harness/events.jsonl as run_stage()/loop() progresses",
        impact=IMPACT_EXTERNAL_PROCESS_LAUNCH,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
        note="There is no 'unstart'. PAUSE is a real, separate action that can steer an "
             "already-started run, but it is not a rollback of START.",
    ),
    _declare(
        path="/api/control", control_command="PAUSE",
        category=CAT_RUN_CONTROL,
        scope=".dv-harness/control.json (paused, paused_reason, paused_at) -- "
              "ControlPlane.pause()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="RESUME",
        category=CAT_RUN_CONTROL,
        scope=".dv-harness/control.json (paused, paused_reason, paused_at) -- "
              "ControlPlane.resume()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="TAKEOVER",
        category=CAT_TAKEOVER_CONTROL,
        scope=".dv-harness/control.json (takeover) -- ControlPlane.takeover()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="RELEASE_TAKEOVER",
        category=CAT_TAKEOVER_CONTROL,
        scope=".dv-harness/control.json (takeover) -- ControlPlane.release_takeover()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="REDIRECT",
        category=CAT_STAGE_REDIRECT,
        scope=".dv-harness/state.json (current_stage) -- commands.cmd_redirect()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
        note="Restoring current_stage undoes the RECORDED field, not any side effect a "
             "stage's own entry logic may already have produced after the redirect ran.",
    ),
    _declare(
        path="/api/control", control_command="APPROVE",
        category=CAT_DECISION_APPROVAL,
        scope=".dv-harness/control.json (approvals.<stage>) -- ControlPlane.approve(); "
              "writes a real human DECISION into the project's audit trail",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="CORRECT",
        category=CAT_DECISION_APPROVAL,
        scope=".dv-harness/control.json (corrections.<stage>), plus .dv-harness/state.json "
              "(attempts) when reset_attempts=true -- ControlPlane.set_correction()",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="CONSTRAINT_ADD",
        category=CAT_CONSTRAINT_MANAGEMENT,
        scope=".dv-harness/control.json (constraints) -- ControlPlane.add_constraint()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="CONSTRAINT_REMOVE",
        category=CAT_CONSTRAINT_MANAGEMENT,
        scope=".dv-harness/control.json (constraints) -- ControlPlane.remove_constraint()",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
    ),
    _declare(
        path="/api/control", control_command="COSIGN",
        category=CAT_DECISION_APPROVAL,
        scope=".dv-harness/control.json (cosigns.<stage>.<field_path>) -- "
              "ControlPlane.add_cosign(); writes a real human DECISION",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="RESEARCH_APPROVE",
        category=CAT_RESEARCH_GOVERNANCE,
        scope=".dv-harness/control.json (approvals.RESEARCH_CAPABILITY_EVOLUTION) -- "
              "commands.cmd_research_approve()",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="RESEARCH_REJECT",
        category=CAT_RESEARCH_GOVERNANCE,
        scope="the capability-evolution candidate's own current_status "
              "(capability_evolution.read_candidate()/transition()) -- "
              "commands.cmd_research_reject()",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="RESEARCH_HOLD",
        category=CAT_RESEARCH_GOVERNANCE,
        scope=".dv-harness/control.json (approvals.RESEARCH_CAPABILITY_EVOLUTION) -- "
              "commands.cmd_research_hold()",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    # question_queue.py dashboard wiring: QUESTION_ANSWER/QUESTION_REVOKE both
    # write a real human DECISION into question_queue.py's own decisions.json
    # audit trail -- the same "records a decision other mechanisms then rely
    # on" rationale as APPROVE/COSIGN/CORRECT/RESEARCH_* above, per
    # dashboard_auth.py's own CONTROL_COMMAND_REQUIRED_ROLE comment.
    _declare(
        path="/api/control", control_command="QUESTION_ANSWER",
        category=CAT_DECISION_APPROVAL,
        scope=".dv-harness/question_queue/decisions.json (one entry's `current`) -- "
              "QuestionQueueStore.answer_question(); writes a real human DECISION "
              "(classify_tier()'s own HUMAN_DECISION_SOURCE) other mechanisms then rely on",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    _declare(
        path="/api/control", control_command="QUESTION_REVOKE",
        category=CAT_DECISION_APPROVAL,
        scope=".dv-harness/question_queue/decisions.json (one entry's `current`) -- "
              "QuestionQueueStore.revoke_decision(); withdraws a previously recorded "
              "human/Tier-2 decision",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
    ),
    # question_queue.request_clarification() (2026-09-07): a human signals "I
    # don't understand this question" and gets back a reworded rendering
    # grounded entirely in evidence the persisted record already carries --
    # NEVER a second question filing mechanism, never a new Q-ID, never a
    # change to tier/status/blocking. Deliberately NOT CAT_DECISION_APPROVAL:
    # per dashboard_auth.py's own comment, this is lower-risk than
    # QUESTION_ANSWER/QUESTION_REVOKE and writes no decision at all -- only a
    # best-effort append to a sibling audit file.
    _declare(
        path="/api/control", control_command="QUESTION_REQUEST_CLARIFICATION",
        category=CAT_RUN_CONTROL,
        scope=".dv-harness/question_queue/clarifications.json (one appended record) -- "
              "question_queue.request_clarification(); NEVER writes to questions.json/"
              "decisions.json and never changes tier/status/blocking",
        impact=IMPACT_FILE_ARTIFACT_WRITE,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
        note="A real, best-effort append to a sibling audit file, never a governance "
             "decision -- deliberately NOT CAT_DECISION_APPROVAL. No real un-append "
             "mechanism exists in this codebase for one clarification record.",
    ),
    _declare(
        path="/api/config", control_command=None,
        category=CAT_POLICY_CONFIGURATION,
        scope=".dv-harness/config.json (policy.require_dv_review_cosign) -- "
              "dashboard._handle_config()",
        impact=IMPACT_PROJECT_CONFIG_WRITE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
        note="No gui_audit_log coverage exists for this endpoint (it wraps /api/control "
             "only); build_rollback_plan() reports NO_EVIDENCE_CAPTURE_FOR_THIS_ACTION.",
    ),
    _declare(
        path="/api/session/save", control_command=None,
        category=CAT_SESSION_AND_FILE_STATE,
        scope=".dv-harness/sessions/<name>/ (session_snapshot.save_session())",
        impact=IMPACT_FILE_ARTIFACT_WRITE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_FILE_ARTIFACT_DELETE,
        note="Rollback is deleting the produced snapshot directory -- this module never "
             "performs that deletion; it only names the real produced path when supplied.",
    ),
    _declare(
        path="/api/session/restore", control_command=None,
        category=CAT_SESSION_AND_FILE_STATE,
        scope="the run-state layer (state.json/control.json/... per "
              "session_snapshot.RESTORE_FILES; events.jsonl is deliberately excluded) "
              "copied back from .dv-harness/sessions/<name>/",
        impact=IMPACT_STATE_MUTATION_REVERSIBLE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_SCOPE_RESTORE,
        note="Reversible only when session_snapshot.restore_session()'s own automatic "
             "pre-restore backup was taken (no_backup was not set) -- via re-invoking "
             "session/restore against that backup snapshot's own name.",
    ),
    _declare(
        path="/api/upload", control_command=None,
        category=CAT_SESSION_AND_FILE_STATE,
        scope=".dv-harness/uploads/<category>/<saved_filename> (dashboard._upload_root())",
        impact=IMPACT_FILE_ARTIFACT_WRITE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_FILE_ARTIFACT_DELETE,
        note="Rollback is deleting the uploaded file -- this module never performs that "
             "deletion; it only names the real produced path when supplied.",
    ),
    _declare(
        path="/api/signoff-export", control_command=None,
        category=CAT_SIGNOFF_EXPORT,
        scope="<out_dir> (default .dv-harness/signoff-export/<timestamp>/) -- "
              "signoff_export.collect_signoff_bundle()",
        impact=IMPACT_FILE_ARTIFACT_WRITE,
        reversible=True, rollback_plan_kind=ROLLBACK_KIND_FILE_ARTIFACT_DELETE,
        note="Rollback is deleting the produced bundle directory -- this module never "
             "performs that deletion; it only names the real produced path when supplied. "
             "A human reviewing this bundle's own manifest/freeze-invalidation output may "
             "file a NEW clarifying question tied to one specific evidence item via "
             "signoff_export.file_bundle_artifact_question()/file_freeze_finding_question() "
             "(question_queue.file_signoff_evidence_question(), 2026-09-07) -- a separate, "
             "real question-queue write this dashboard action does not itself perform, and "
             "not yet reachable from any dashboard POST endpoint today. A SECOND human may "
             "also record their own independent review of the whole bundle via "
             "control_plane.ControlPlane.add_bundle_review()/signoff_export."
             "bundle_second_review_status() (2026-09-07) -- likewise a real mechanism this "
             "dashboard action does not itself invoke and no dashboard POST endpoint "
             "reaches today; see this module's own docstring, 'SIGNOFF BUNDLE SECOND "
             "REVIEW'.",
    ),
    _declare(
        path="/api/waiver", control_command=None,
        category=CAT_WAIVER_AUTHORING,
        scope=".dv-harness/waivers/waivers.json (one appended/updated record) -- "
              "waiver_store.append_waiver()",
        impact=IMPACT_GOVERNANCE_RECORD,
        reversible=False, rollback_plan_kind=ROLLBACK_KIND_NOT_REVERSIBLE,
        note="waiver_store.revoke_waiver() is a real, separate reversal mechanism "
             "(requires a named human + reason), but it is NOT wired to any dashboard "
             "POST endpoint today -- reported as not reversible through THIS GUI action, "
             "never claimed reversible on the strength of a module-level function this "
             "action cannot reach.",
    ),
)

GUI_ACTION_DECLARATIONS: Dict[str, GUIActionDeclaration] = {d.action_id: d for d in _DECLARATIONS}

if len(GUI_ACTION_DECLARATIONS) != len(_DECLARATIONS):  # pragma: no cover - self-check
    raise AssertionError("duplicate action_id among GUI_ACTION_DECLARATIONS")


def assert_category_coverage_is_total() -> None:
    """Every one of the 11 categories is used by at least one real
    declaration, and every declaration's category is one of the 11 -- run at
    import so an unused or a stray category fails immediately."""
    used = {d.category for d in _DECLARATIONS}
    unused = set(ACTION_CATEGORIES) - used
    if unused:
        raise AssertionError(f"ACTION_CATEGORIES declared but never used: {sorted(unused)}")
    stray = used - set(ACTION_CATEGORIES)
    if stray:
        raise AssertionError(f"declarations use a category outside the 11: {sorted(stray)}")


assert_category_coverage_is_total()


def declared_actions() -> List[str]:
    return sorted(GUI_ACTION_DECLARATIONS)


def get_declaration(action_id: str) -> GUIActionDeclaration:
    try:
        return GUI_ACTION_DECLARATIONS[action_id]
    except KeyError:
        raise GuiActionSafetyError(
            f"no GUI action safety declaration for {action_id!r}; known actions: "
            f"{declared_actions()}") from None


def required_permission(action_id: str) -> str:
    """VIEWER / OPERATOR / APPROVER for `action_id`, read from the
    declaration -- itself computed from dashboard_auth.required_role(), so
    this is never a second, independently-maintained answer."""
    return get_declaration(action_id).required_role


# ---- Coverage drift guard ----------------------------------------------------

def assert_coverage_matches_real_dispatch() -> None:
    """dashboard_auth.py's own two drift guards prove ITS tables still cover
    dashboard.py's real do_POST()/_dispatch_control() dispatch (never
    re-parsed a second time here). This function then proves THIS module's
    24-action table covers exactly the same real action set -- no more, no
    fewer -- so a POST endpoint or control command added to dashboard.py
    later is caught here too, not only in dashboard_auth.py."""
    dashboard_auth.assert_endpoints_mapped()
    dashboard_auth.assert_control_commands_mapped()

    # /api/control itself is not a declared action HERE -- it is represented
    # at the finer grain of its 16 real sub-commands instead (each its own
    # GUIActionDeclaration), so it is excluded from the bare-endpoint diff
    # below and covered separately by the control-command diff.
    real_endpoints = set(dashboard_auth.dispatched_post_endpoints()) - {dashboard_auth.CONTROL_ENDPOINT}
    real_commands = set(dashboard_auth.dispatched_control_commands())

    declared_endpoints = set()
    declared_control_commands = set()
    prefix = f"POST {dashboard_auth.CONTROL_ENDPOINT} "
    for action_id in GUI_ACTION_DECLARATIONS:
        if action_id.startswith(prefix):
            declared_control_commands.add(action_id[len(prefix):])
        elif action_id.startswith("POST "):
            declared_endpoints.add(action_id[len("POST "):])

    missing_endpoints = real_endpoints - declared_endpoints
    stale_endpoints = declared_endpoints - real_endpoints
    missing_commands = real_commands - declared_control_commands
    stale_commands = declared_control_commands - real_commands
    if missing_endpoints or stale_endpoints or missing_commands or stale_commands:
        raise GuiActionSafetyDriftError(
            "GUI_ACTION_DECLARATIONS drifted from dashboard.py's real POST dispatch: "
            f"missing_endpoints={sorted(missing_endpoints)} "
            f"stale_endpoints={sorted(stale_endpoints)} "
            f"missing_control_commands={sorted(missing_commands)} "
            f"stale_control_commands={sorted(stale_commands)}")


# ---- Rollback plan builder ----------------------------------------------------

def _control_action_command(action_id: str) -> Optional[str]:
    prefix = f"POST {dashboard_auth.CONTROL_ENDPOINT} "
    if action_id.startswith(prefix):
        return action_id[len(prefix):]
    return None


def build_rollback_plan(root: Path, action_id: str, *,
                         gui_audit_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The concrete restore set for one dispatched GUI action -- reusing
    `capability_evolution.shadow_rollback_manifest()`'s own PATTERN (see
    module docstring): every entry names a `restore_action`, the record
    always carries `applied: False`, and the whole record is built from REAL
    recorded evidence or is honestly refused, never authored prose.

    Reads only. It writes nothing, restores nothing, and touches no project
    file -- see `assert_module_only_reads()`; producing the plan is the
    mechanism, applying it is a separate, human act outside this module's
    scope entirely (there is no apply function here to call).
    """
    decl = get_declaration(action_id)
    plan: Dict[str, Any] = {
        "action_id": action_id, "category": decl.category,
        "rollback_plan_kind": decl.rollback_plan_kind, "applied": False,
    }

    if not decl.reversible:
        plan["status"] = RB_STATUS_NOT_REVERSIBLE
        plan["reason"] = decl.note or f"{action_id} writes a real human decision or has no undo path"
        plan["entries"] = []
        plan["source_record"] = None
        return plan

    command = _control_action_command(action_id)
    if command is None:
        # No real before/after capture route exists for a non-/api/control
        # endpoint today -- gui_audit_log.py wraps /api/control only.
        # Reported honestly rather than approximated from the CURRENT file
        # content (which is not evidence of what the action itself changed).
        plan["status"] = RB_STATUS_NO_EVIDENCE_ROUTE
        plan["reason"] = (decl.note
                           or "no gui_audit_log (or equivalent) capture exists for this action")
        plan["entries"] = []
        plan["source_record"] = None
        return plan

    record = gui_audit_record
    if record is None:
        from . import gui_audit_log
        records = gui_audit_log.read_gui_audit_log(Path(root), action=command, limit=1)
        record = records[-1] if records else None

    if record is None:
        plan["status"] = RB_STATUS_NO_RECORD_FOUND
        plan["reason"] = f"no recorded gui_audit_log entry for control command {command!r}"
        plan["entries"] = []
        plan["source_record"] = None
        return plan

    plan["source_record"] = {
        "who": record.get("who"), "when": record.get("when"), "action": record.get("action"),
    }

    result = record.get("result") or {}
    if result.get("status") != "OK":
        plan["status"] = RB_STATUS_DISPATCH_FAILED
        plan["reason"] = "the recorded dispatch itself failed; no real mutation to restore"
        plan["entries"] = []
        return plan

    before = record.get("before")
    after = record.get("after")
    entries: List[Dict[str, Any]] = []
    before_map = before if isinstance(before, dict) else {}
    after_map = after if isinstance(after, dict) else {}
    keys = sorted(set(before_map) | set(after_map))
    for key in keys:
        if key == "_scope_status":
            continue
        before_val = before_map.get(key)
        after_val = after_map.get(key)
        entries.append({
            "scope_key": key,
            "restore_action": "NO_CHANGE" if before_val == after_val else "RESTORE_VALUE",
            "before_value": before_val,
            "after_value": after_val,
        })
    plan["status"] = RB_STATUS_BUILT
    plan["entries"] = entries
    return plan


# ---- Structural guard: this module reads, it never writes ------------------

_FORBIDDEN_WRITE_TOKENS = (
    "write_text(", "write_bytes(", ".dump(", "os.replace(", "_atomic_replace(",
    "unlink(", "rmtree(", "os.remove(",
)


def assert_module_only_reads(source_path: Optional[Path] = None) -> None:
    """A literal substring check over `source_path`'s text (this module's
    own source by default; a test may point it at a synthetic file to prove
    the check has real detection power): no token that would write, delete,
    or replace a file may appear anywhere in it. This is the structural half
    of "producing a rollback manifest is the mechanism, applying it is a
    separate human act" -- not merely a docstring claim."""
    path = Path(source_path) if source_path is not None else Path(__file__)
    src = path.read_text(encoding="utf-8")
    # Exclude this module's own declaration of the forbidden list (which
    # necessarily quotes every token as a string literal) from the scan --
    # the check is about real USE elsewhere in the file, never the mention.
    # A synthetic test file carrying no such declaration is scanned whole.
    marker = "_FORBIDDEN_WRITE_TOKENS = ("
    if marker in src:
        start = src.index(marker)
        end = src.index(")", start) + 1
        haystack = src[:start] + src[end:]
    else:
        haystack = src
    hits = [tok for tok in _FORBIDDEN_WRITE_TOKENS if tok in haystack]
    if hits:
        raise AssertionError(
            f"{path.name} must never write/delete a file; found forbidden token(s): {hits}")


# ---- Rendering ----------------------------------------------------------------

def render_declarations_table() -> str:
    from .connectivity import render_markdown_table
    headers = ["Action", "Category", "Required Role", "Impact", "Reversible", "Rollback Kind"]
    rows = []
    for action_id in declared_actions():
        d = GUI_ACTION_DECLARATIONS[action_id]
        rows.append({
            "Action": d.action_id, "Category": d.category,
            "Required Role": d.required_role, "Impact": d.impact,
            "Reversible": "yes" if d.reversible else "no",
            "Rollback Kind": d.rollback_plan_kind,
        })
    return render_markdown_table(headers, rows)


# ---- CLI ----------------------------------------------------------------------

def execute_verb(argv) -> int:
    """`python -m dv_harness.gui_action_safety declarations|validate|rollback-plan`.
    No `dv-harness` CLI verb was added -- `cli.py` was under concurrent edit
    by other same-day work in this repo, the same disclosed choice several
    sibling standalone modules already make."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="python -m dv_harness.gui_action_safety")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("declarations")
    sub.add_parser("validate")
    sub.add_parser("coverage")
    rb = sub.add_parser("rollback-plan")
    rb.add_argument("action_id")
    rb.add_argument("--root", default=".")
    for p in (sub.choices["declarations"], sub.choices["validate"],
              sub.choices["coverage"], rb):
        p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "declarations":
        if args.json:
            print(_json.dumps(
                {a: GUI_ACTION_DECLARATIONS[a].__dict__ for a in declared_actions()},
                ensure_ascii=False, indent=2))
        else:
            print(render_declarations_table())
        return 0

    if args.verb == "validate":
        violations = validate_all_declarations()
        bad = {k: v for k, v in violations.items() if v}
        if args.json:
            print(_json.dumps(violations, ensure_ascii=False, indent=2))
        else:
            if not bad:
                print("All GUI action safety declarations are internally consistent.")
            for action_id, errs in bad.items():
                for e in errs:
                    print(f"{action_id}: {e}")
        return 1 if bad else 0

    if args.verb == "coverage":
        try:
            assert_coverage_matches_real_dispatch()
        except GuiActionSafetyDriftError as e:
            print(str(e))
            return 1
        print("GUI_ACTION_DECLARATIONS covers dashboard.py's real dispatch exactly.")
        return 0

    if args.verb == "rollback-plan":
        plan = build_rollback_plan(Path(args.root), args.action_id)
        if args.json:
            print(_json.dumps(plan, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"{args.action_id}: {plan['status']}")
            if plan.get("reason"):
                print(f"  reason: {plan['reason']}")
            for entry in plan.get("entries", []):
                print(f"  {entry['scope_key']}: {entry['restore_action']} "
                      f"(before={entry['before_value']!r} after={entry['after_value']!r})")
        return 0 if plan["status"] == RB_STATUS_BUILT else 1

    return 2  # pragma: no cover - argparse enforces `required=True`


def main() -> None:
    import sys
    sys.exit(execute_verb(sys.argv[1:]))


if __name__ == "__main__":
    main()
