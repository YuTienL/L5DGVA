"""Machine-checkable anti-drift rule for CAP-M6-INTPRIME-001 (Integration
Prime Directive adoption) and CAP-M6-INTPRIME-V2-001 (V2 supersession).

Narrow things this reconciliation committed to keeping checkable without
building a new governance subsystem:

1. Prime Directive discoverability cannot silently disappear -- CLAUDE.md's
   compact ALWAYS_ON pointer, the governance_registry.json entry, and the
   real detailed document it points to must all keep existing together.
2. V2 supersession must stay unambiguous -- exactly one ACTIVE
   TASK_SCOPED entry for the detailed directive at any time, V1 retained
   as EVIDENCE_ON_DEMAND (never deleted, never a second active entry).
3. The capability-maturity policy's own anti-inflation invariants
   (`FOUNDATION != OPERATIONAL`, etc., and the `OPERATIONAL` rung's stricter
   "production call path" definition) cannot be silently stripped out of
   the reconciled policy document -- the concrete guard against a future
   report claiming OPERATIONAL merely from IMPLEMENTED/TESTED.
4. (V2) A current-scope gap can never be recorded with disposition
   `DOCUMENT_ONLY` -- V2's own explicit rule ("`DOCUMENT_ONLY` is invalid
   for a current-scope correctness defect") enforced against the real gap
   register, not merely stated in prose.

Deliberately reuses `dv_harness/governance_registry.py`'s own
`check_reachability()` rather than inventing a second reachability
mechanism.
"""
from __future__ import annotations

import csv
from pathlib import Path

from dv_harness import governance_registry as gr

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
M6_PREFLIGHT = ROOT / ".work" / "phase3-dual-repo-consolidation" / "M6_PREFLIGHT"
POLICY_DOC = M6_PREFLIGHT / "L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md"
GAP_REGISTER = M6_PREFLIGHT / "L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv"


def test_governance_registry_carries_exactly_one_active_prime_directive_entry():
    entries = gr.load_registry(ROOT)
    matches = [e for e in entries if e["id"] == "L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2"]
    assert len(matches) == 1, "V2 Prime Directive registry entry missing or duplicated"
    entry = matches[0]
    assert entry["load_policy"] == "TASK_SCOPED"
    assert entry["summary_path"] == "docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md"
    # No stale, still-TASK_SCOPED V1 entry left behind under its old id --
    # exactly one active detailed-directive entry at a time.
    stale = [e for e in entries if e["id"] == "L5DGVA_INTEGRATION_PRIME_DIRECTIVE"]
    assert stale == [], "V1's original TASK_SCOPED entry id must not still exist"


def test_governance_registry_retains_v1_as_historical_evidence_not_deleted_not_active():
    entries = gr.load_registry(ROOT)
    matches = [e for e in entries if e["id"] == "L5DGVA_INTEGRATION_PRIME_DIRECTIVE_HISTORICAL"]
    assert len(matches) == 1, "V1 historical registry entry missing or duplicated"
    entry = matches[0]
    assert entry["load_policy"] == "EVIDENCE_ON_DEMAND"
    assert entry["summary_path"] == "docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md"
    # V1's own file must still be a real, reachable file -- superseded, not deleted.
    assert (ROOT / "docs" / "architecture" / "L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md").is_file()


def test_the_registered_path_is_still_a_real_reachable_file():
    result = gr.check_reachability(ROOT)
    assert result.broken == [], result.broken


def test_claude_md_keeps_a_compact_always_on_pointer_to_v2_never_the_full_text():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "## Integration Prime Directive V2" in text
    assert "docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md" in text
    assert "SUPERSEDED_HISTORICAL" in text
    # Discoverability without duplication: CLAUDE.md must not carry the
    # directive's own full Golden Operational Workflow stage list verbatim.
    assert "-> ClarificationService when unresolved" not in text


def test_capability_maturity_policy_still_distinguishes_operational_from_implemented_tested():
    text = POLICY_DOC.read_text(encoding="utf-8")
    for invariant in (
        "FOUNDATION != OPERATIONAL",
        "IMPLEMENTED != WIRED",
        "TESTED != CONSUMED",
        "MODULE_EXISTS != RUNTIME_USED",
    ):
        assert invariant in text, "anti-inflation invariant silently removed: %s" % invariant
    assert "production call path" in text


def test_no_current_scope_gap_is_ever_recorded_as_document_only():
    """V2's own explicit rule: DOCUMENT_ONLY is invalid for a current-scope
    correctness defect. Enforced against the real register, not prose."""
    assert GAP_REGISTER.is_file(), "current-scope gap register must exist once V2 is adopted"
    with GAP_REGISTER.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "gap register exists but is empty"
    document_only = [r["GAP_ID"] for r in rows if r.get("DISPOSITION") == "DOCUMENT_ONLY"]
    assert document_only == [], "DOCUMENT_ONLY is an invalid disposition under V2: %s" % document_only
    valid_dispositions = {
        "FIX_NOW_CURRENT_SCOPE", "FIX_NOW_CORRECTNESS_BLOCKER", "FIX_NOW_CAPABILITY_LOSS",
        "FIX_NOW_SAFETY_SECURITY", "REGISTER_AND_DEFER_WITH_OWNER", "SUPERSEDED_WITH_EVIDENCE",
        "NOT_APPLICABLE_WITH_EVIDENCE", "HUMAN_DECISION_REQUIRED",
    }
    bad = [r["GAP_ID"] for r in rows if r.get("DISPOSITION") not in valid_dispositions]
    assert bad == [], "gap(s) with an unrecognized disposition: %s" % bad
