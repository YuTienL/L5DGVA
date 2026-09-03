"""dv_harness/uvm_generator/bind_verification_lint.py -- standalone,
build-tree-agnostic lint for the Gate 1/2/3 bind-verification-status
requirement (2026-09-03, Gap #2 closure -- mandatory-gate-checkpoint
workstream).

WHY THIS EXISTS AS A STANDALONE SCRIPT RATHER THAN AN ENGINE-WIRED GATE:
`.claude/agents/IP_UVM_DV_Gen.md` is agent-followed prose an LLM agent reads
and acts on -- confirmed by inspection (2026-09-03) that no code in
`dv_harness/` (`engine.py`, `graph.py`, `gates.py`) parses or mechanically
drives its documented Steps; every existing reference to it elsewhere in
this codebase (`address_map_verifier.py`, `vplan_writer/writer.py`, the
`sim_scripts/` templates) cites it only as a source-of-truth doc, never
invokes it as code. There is therefore no single engine call site this
requirement could be wired into as an automatic STAGE_GATES-style gate the
way `dv_harness/gates.py` gates a VPLAN stage. What CAN be checked
mechanically is the one real, durable ARTIFACT this agent's own documented
convention already produces: a build-status report (see
`IP_UVM_DV_Gen.md`'s "say so in the first status report" convention, line
~88). This script is that mechanical check -- run it against any build
tree's own status-report file (markdown or JSON) and it flags a report that
omits Gate 1/2/3 bind-verification status, exactly the way a human reviewer
or a CI step would, without requiring the report to have been produced by
any particular code path.

Pairs with `dv_harness/connectivity.py`'s
`bind_verification_status_block()`/`render_bind_verification_status_markdown()`
(the canonical status block/section a compliant report renders) and
`assert_bind_gates_checkpoint()` (the code-level checkpoint assertion a
future engine-driven build path can call directly, once one exists, instead
of going through this text-scanning fallback).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from dv_harness.connectivity import BIND_VERIFICATION_STATUS_KEYS, GateStatus

#: Recognized GateStatus values -- kept sourced from the real enum (never
#: re-typed as a separate literal list) so a future GateStatus addition is
#: picked up here automatically with no edit needed.
VALID_STATUS_VALUES = {s.value for s in GateStatus}

#: Matches this module's own `render_bind_verification_status_markdown()`
#: line shape: "- Gate 1 (elaboration): PASS" / "Gate 2 ...: NOT_AVAILABLE" /
#: "Gate 3 (transaction activity): PENDING". Deliberately tolerant of the
#: free-text parenthetical (the human-readable gate name varies) and of a
#: leading "- " bullet or its absence, anchoring only on "Gate <n>" and the
#: colon-then-status-token shape a hand-written report is expected to keep.
_MARKDOWN_GATE_RE = {
    "gate1_elaboration": re.compile(r"Gate\s*1\b[^:\n]*:\s*([A-Z_]+)"),
    "gate2_zero_time_connectivity": re.compile(r"Gate\s*2\b[^:\n]*:\s*([A-Z_]+)"),
    "gate3_transaction_activity": re.compile(r"Gate\s*3\b[^:\n]*:\s*([A-Z_]+)"),
}


def extract_status_block_from_markdown(text: str) -> dict:
    """Pulls whichever of the 3 gate-status lines are actually present out
    of free-form markdown report text. A key simply does not appear in the
    returned dict when its line is absent -- the caller (`lint_status_report_text`
    below) is what turns "absent" into a reported problem, this function
    only reports what it found."""
    block = {}
    for key, pattern in _MARKDOWN_GATE_RE.items():
        m = pattern.search(text)
        if m:
            block[key] = m.group(1).upper()
    return block


def extract_status_block_from_json(text: str) -> dict:
    """Accepts either a flat `{"gate1_elaboration": "...", ...}` dict (the
    exact shape `bind_verification_status_block()` returns) or that same
    dict nested one level under a `"bind_verification_status"` key (the
    shape a larger build-status JSON report is expected to embed it as)."""
    data = json.loads(text)
    if isinstance(data, dict) and "bind_verification_status" in data:
        data = data["bind_verification_status"]
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return {k: v for k, v in data.items() if k in BIND_VERIFICATION_STATUS_KEYS}


def lint_status_report_text(text: str, is_json: bool = False) -> list:
    """Returns a list of human-readable problem strings; an empty list means
    the report is clean. Never raises on a malformed report -- a report so
    broken it cannot even be scanned is itself reported as a single problem
    string, not an uncaught exception, since this tool's whole job is to
    surface problems to a human/CI reviewer, not to crash whatever pipeline
    invokes it."""
    try:
        block = extract_status_block_from_json(text) if is_json else extract_status_block_from_markdown(text)
    except (json.JSONDecodeError, ValueError) as exc:
        fmt = "JSON" if is_json else "markdown"
        return [f"could not parse report as {fmt}: {exc}"]

    problems = []
    for key in BIND_VERIFICATION_STATUS_KEYS:
        label = key.replace("_", " ")
        if key not in block or not block[key]:
            problems.append(
                f"{label} status missing from this report (required from the first-successful-compile "
                f"checkpoint onward -- CLAUDE.md's Bind-Location Rules / IP_UVM_DV_Gen.md Step 9)"
            )
        elif block[key] not in VALID_STATUS_VALUES:
            problems.append(
                f"{label} status {block[key]!r} is not a recognized GateStatus value "
                f"({sorted(VALID_STATUS_VALUES)})"
            )
    return problems


def lint_status_report_file(path) -> list:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    is_json = p.suffix.lower() == ".json"
    return lint_status_report_text(text, is_json=is_json)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Flag a build-status report artifact (markdown or JSON) that is missing "
            "Gate 1/2/3 bind-verification status -- CLAUDE.md's Bind-Location Rules / "
            "IP_UVM_DV_Gen.md Step 9 mandatory checkpoint."
        ),
    )
    parser.add_argument("report_path", help="Path to a build-status report (.md or .json)")
    args = parser.parse_args(argv)
    problems = lint_status_report_file(args.report_path)
    if problems:
        print(f"BIND-VERIFICATION-STATUS LINT: {len(problems)} problem(s) in {args.report_path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"BIND-VERIFICATION-STATUS LINT: clean -- {args.report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
