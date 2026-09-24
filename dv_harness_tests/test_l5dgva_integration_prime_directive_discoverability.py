"""Machine-checkable anti-drift rule for CAP-M6-INTPRIME-001 (Integration
Prime Directive adoption).

Two, and only two, narrow things this reconciliation committed to keeping
checkable without building a new governance subsystem:

1. Prime Directive discoverability cannot silently disappear -- CLAUDE.md's
   compact ALWAYS_ON pointer, the governance_registry.json entry, and the
   real detailed document it points to must all keep existing together.
2. The capability-maturity policy's own anti-inflation invariants
   (`FOUNDATION != OPERATIONAL`, etc., and the `OPERATIONAL` rung's stricter
   "production call path" definition) cannot be silently stripped out of
   the reconciled policy document -- the concrete guard against a future
   report claiming OPERATIONAL merely from IMPLEMENTED/TESTED.

Deliberately reuses `dv_harness/governance_registry.py`'s own
`check_reachability()` rather than inventing a second reachability
mechanism.
"""
from __future__ import annotations

from pathlib import Path

from dv_harness import governance_registry as gr

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
POLICY_DOC = (
    ROOT
    / ".work"
    / "phase3-dual-repo-consolidation"
    / "M6_PREFLIGHT"
    / "L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md"
)


def test_governance_registry_carries_the_prime_directive_entry():
    entries = gr.load_registry(ROOT)
    matches = [e for e in entries if e["id"] == "L5DGVA_INTEGRATION_PRIME_DIRECTIVE"]
    assert len(matches) == 1, "Prime Directive registry entry missing or duplicated"
    entry = matches[0]
    assert entry["load_policy"] == "TASK_SCOPED"
    assert entry["summary_path"] == "docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md"


def test_the_registered_path_is_still_a_real_reachable_file():
    result = gr.check_reachability(ROOT)
    assert result.broken == [], result.broken


def test_claude_md_keeps_a_compact_always_on_pointer_never_the_full_text():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "## Integration Prime Directive" in text
    assert "docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md" in text
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
