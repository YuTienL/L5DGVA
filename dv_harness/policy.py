from __future__ import annotations
from pathlib import Path
from .models import Stage, Status, HarnessState
from .graph import GraphDefinition

ORDER = [s.value for s in Stage]

_GRAPH_CONDITION = {
    Status.PASS.value: "PASS",
    Status.CLOSED.value: "PASS",
    Status.FAIL.value: "FAIL",
    Status.BLOCKED.value: "BLOCKED",
    Status.WAIT_USER.value: "BLOCKED",
}


def _load_graph_def(root: Path) -> GraphDefinition | None:
    p = Path(root) / ".dv-harness" / "graph" / "main_graph.json"
    if not p.exists():
        return None
    try:
        return GraphDefinition.load(p)
    except Exception:
        return None


def graph_next(current: str, status: str, root: Path) -> str | None:
    """Route via .dv-harness/graph/main_graph.json edges -- CLAUDE.md's
    first core rule is 'Graph is the global workflow authority', but the
    engine previously only ever advanced stages in a fixed linear ORDER
    and never consulted this file. Returns None (caller falls back to
    ORDER) if there is no graph, or no edge matches. Passes through
    synthetic join nodes (e.g. ANALYSIS_JOIN) that exist in the graph but
    have no corresponding Stage, since the linear engine has no parallel
    join semantics of its own.

    CONSOLIDATED (2026-08-28, 12-claim re-audit): previously re-parsed
    main_graph.json's raw "edges" list independently of graph.py's
    GraphDefinition/Edge model -- two separate implementations of the same
    edge-traversal, only one of which (this one) was ever actually called.
    Now the single edge-matching primitive is GraphDefinition.next_for();
    this function is just the Status-vocabulary-to-condition mapping plus
    the join-node passthrough loop on top of it. engine.py's advance() is
    the caller for PASS/FAIL; loop()'s BLOCKED/WAIT_USER short-circuit
    deliberately does NOT call this (see engine.py's loop() docstring note
    on BLOCKED edges) -- a stage marked BLOCKED/WAIT_USER means "stop and
    wait for a human" (Human Override principle), not "auto-route
    somewhere"; can_signoff() below is the one place that does provide an
    explicit redirect for specific, known-recoverable blocked conditions
    (SHA drift, open findings) -- not a general BLOCKED-edge lookup.
    """
    gd = _load_graph_def(root)
    if gd is None:
        return None
    node, condition = current, _GRAPH_CONDITION.get(status, "PASS")
    for _ in range(len(ORDER) + 5):
        target = gd.next_for(node, condition)
        if target is None:
            return None
        if target in ORDER:
            return target
        node, condition = target, "PASS"
    return None


def next_stage(current: str) -> str | None:
    try:
        i = ORDER.index(current)
    except ValueError:
        return ORDER[0]
    return ORDER[i+1] if i+1 < len(ORDER) else None

# Blackboard topic engine.DVHarness._score_root_cause_confidence() writes on
# every gate-verified RE_AUDIT/RCA_JOIN PASS, holding the composed
# QualifiedConclusion (dv_harness/qualified_conclusion.py): the stage's own
# hard-gate verdict AND inference.score_confidence()'s INDEPENDENTLY
# recomputed confidence, together, as one is_qualified boolean.
QUALIFIED_CONCLUSION_TOPIC = "qualified_conclusion"


def read_qualified_conclusion(blackboard) -> dict | None:
    """The composed QualifiedConclusion record, or None when none was ever
    written (or the topic holds a shape this cannot read). `blackboard` is a
    dv_harness.blackboard.Blackboard; Blackboard.read() wraps every value as
    {"value": ..., "source": ..., ...}, which is unwrapped here so callers
    never re-implement that unwrapping."""
    if blackboard is None:
        return None
    try:
        record = blackboard.read(QUALIFIED_CONCLUSION_TOPIC)
    except Exception:
        return None
    value = record.get("value") if isinstance(record, dict) else None
    return value if isinstance(value, dict) else None


def can_signoff(state: HarnessState, cfg: dict, blackboard=None) -> tuple[bool, str, str | None]:
    """Third element is a redirect_stage: None means the caller should just
    BLOCK and wait for a human; a Stage name means this failure is
    auto-recoverable by routing back there (per the graph condition
    "if server_sha_match == false -> SERVER_SYNC" -- a SHA drift is not a
    human decision, it's a resync).

    `blackboard` (2026-09-04, mechanism-#9 gap closure) is optional so every
    existing caller/test keeps working unchanged; engine.loop() -- the one
    production caller -- passes its real Blackboard, which is what makes the
    qualified-conclusion check below fire on the real path."""
    policy = cfg["policy"]
    if policy.get("require_exact_server_sha", True):
        if state.git_sha and state.server_sha and state.git_sha != state.server_sha:
            return False, "Git SHA 與 Server SHA 不一致", Stage.SERVER_SYNC.value
    if policy.get("require_all_actionable_findings_closed", True) and state.findings_open > 0:
        return False, f"仍有 {state.findings_open} 個 open findings", Stage.IMPLEMENT.value
    if policy.get("require_second_pass_audit", True):
        rs = state.stages.get(Stage.RE_AUDIT.value, {})
        if rs.get("status") not in (Status.PASS.value, Status.CLOSED.value):
            return False, "Second-pass audit 尚未完成", None
    # GAP FIX (2026-09-04, "Hypothesis+Evidence+Result+Gate = Conclusion"
    # re-audit): require_second_pass_audit above only asks whether RE_AUDIT
    # reached stage PASS -- it never asks what that stage CONCLUDED. Those
    # are genuinely different facts, and the difference is reachable, not
    # theoretical: root_cause_evidence_gate only mandates non-empty
    # counter_evidence at its own HIGH/CONFIRMED tier, so a MEDIUM-confidence
    # finding with one supporting citation and two unrefuted counter-evidence
    # entries passes all 11 RE_AUDIT gates while score_confidence() recomputes
    # to LOW (2*1 + 2 - 3*2 = -2), i.e. build_qualified_conclusion() returns
    # is_qualified=False. Before this check, that run closed into SIGNOFF
    # exactly like a fully qualified one: the QualifiedConclusion was written
    # to the Blackboard on the real RE_AUDIT PASS path and then read by
    # nothing except dashboard.py's display.
    #
    # Deliberately scoped to the DANGEROUS case only -- a record that EXISTS
    # and says is_qualified is False -- mirroring how CLAUDE.md's Bind-Location
    # Rules scope enforce_bind_tier_policy()'s `require_tier` residual. A
    # project with NO record at all is not blocked here: absence is already
    # covered by require_second_pass_audit above (no RE_AUDIT PASS, no
    # record), and blocking on absence would turn every pre-existing project
    # whose RE_AUDIT status was set by any route other than a
    # root_cause_evidence_gate-bearing PASS into an unclosable one. That
    # residual is disclosed, not hidden.
    #
    # redirect_stage is None (BLOCK and wait for a human), matching
    # require_second_pass_audit's own None rather than the SHA-drift/open-
    # findings redirects: a conclusion that did not qualify needs better
    # evidence, which is a human/agent judgment, not a mechanical resync.
    if policy.get("require_qualified_conclusion", True):
        qc = read_qualified_conclusion(blackboard)
        if isinstance(qc, dict) and qc.get("is_qualified") is False:
            level = ((qc.get("inference_confidence") or {}).get("level")
                     if isinstance(qc.get("inference_confidence"), dict) else None)
            return False, (
                "Qualified Conclusion 未成立 "
                f"(gate_verdict={qc.get('gate_verdict')}, "
                f"recomputed_confidence={level}) -- "
                "RE_AUDIT 的 root cause 結論未達可信門檻，不得進入 SIGNOFF"
            ), None
    return True, "", None
