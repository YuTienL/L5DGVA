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

def can_signoff(state: HarnessState, cfg: dict) -> tuple[bool, str, str | None]:
    """Third element is a redirect_stage: None means the caller should just
    BLOCK and wait for a human; a Stage name means this failure is
    auto-recoverable by routing back there (per the graph condition
    "if server_sha_match == false -> SERVER_SYNC" -- a SHA drift is not a
    human decision, it's a resync)."""
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
    return True, "", None
