"""Persists two 2026-09-03 lessons from the live USB VIP build into Engineering
Memory, via memory_router.route_and_store() (auto-loads cfg, pushes to the
shared Knowledge Center automatically).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD_RENAME = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "A global file/macro rename (usb31_ -> usb_, to match a reference naming convention) silently corrupted 13 real DUT-owned hierarchical paths -- caught by luck, not by the static checker, because hierarchy references only resolve at elaboration",
    "scope": "engine",
    "symptoms": [
        "During the live USB VIP build (2026-09-03), a controller-directed rename (align this environment's file/macro naming with USB_UVM_Handoff's convention: usb31_<role> -> usb_<role>) was performed as a search-and-replace",
        "The static checker (usb_static_check.py, 0 errors/19 files) reported clean both before and after -- the corruption was invisible to it",
        "13 real DUT-owned hierarchical paths were corrupted: e.g. u_udc_usb31_top.u_udc_usb31_phy... (real, correct) became u_udc_usb_top.u_udc_usb_phy... (fabricated, does not exist in the DUT)",
    ],
    "root_cause": (
        "A blanket 'usb31_' -> 'usb_' string replacement does not distinguish between the namespace the renaming agent "
        "OWNS (its own file names, macro names, class names -- e.g. usb31_reg_arb.sv, `USB31_PORT_TCA_DEVICE_MODE) and "
        "namespaces it does NOT own that happen to share the same substring (the DUT's own real RTL instance names, e.g. "
        "u_udc_usb31_top, which literally contains 'usb31' as part of the DUT vendor's own module/instance naming, not "
        "this environment's naming). Hierarchical path references (`sysn063.u_lan063.u_udc_usb31_top....`) are plain "
        "strings to any text-based rename tool and to SystemVerilog's own lexer -- they are only checked against the real "
        "design hierarchy at ELABORATION time, not at parse/lint time, so a static checker that only validates syntax "
        "(balanced braces, macro self-containment, include order, etc.) cannot catch a corrupted hierarchical path at all. "
        "This would have shipped a build that fails only once a real elaboration is attempted, with an error pointing at "
        "the wrong-looking symptom (an unresolvable hierarchical reference) rather than the actual cause (an over-broad "
        "rename)."
    ),
    "fix": (
        "Caught only incidentally (the implementer happened to read the affected file while investigating an unrelated "
        "hang). Fixed the 13 corrupted paths, then built a real, negative-tested guard: a new static-check category "
        "harvests the real DUT path component vocabulary from the UNTOUCHED original reference files "
        "(reference/bfm_patterns/*.txt -- files never edited by this environment, so their content is authoritative DUT "
        "vocabulary by construction) and flags any occurrence of a digit-stripped/renamed variant of those components "
        "elsewhere in the tree. Negative-tested by deliberately re-injecting the exact same corruption, confirming the "
        "new check fires, then restoring and confirming clean again -- verifying the guard actually catches the failure "
        "mode it was built for, not just plausible-sounding coverage."
    ),
    "verification": {
        "single_sim": "N/A (build-process/tooling defect, not a simulation fix)",
        "regression": "Static check clean (0 errors/19 files) after the fix, with the new guard category added (now 13 static-check categories total). Guard's own detection verified via deliberate re-injection of the original bug.",
        "reaudit": "Self-caught and self-fixed by the same agent within the same work session, 2026-09-03.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON (catalogued in this project's own build as trap T-27): a rename is only safe over a "
        "namespace you actually own. Before any global search-and-replace rename (aligning naming with a reference "
        "convention, migrating a prefix, etc.), explicitly identify what namespace boundary the tool operates within -- "
        "own files/macros/classes vs. any external, unowned vocabulary (DUT RTL instance names, vendor IP names, third-"
        "party VIP class names) that might share a matching substring by coincidence. A syntax-only static checker cannot "
        "protect against this class of bug because the corruption is only meaningful relative to a REAL external "
        "structure (the DUT's actual hierarchy) that the checker has no model of -- the only reliable guard is comparing "
        "against an untouched, authoritative source of that external vocabulary (here: reference files never edited by "
        "the tool doing the rename), plus negative-testing the guard against the exact original bug before trusting it."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-03, live USB VIP build (IP_UVM_DV_Gen agent), self-caught and self-fixed.",
}

RECORD_SELFREPORT = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "A dispatched sub-agent read the completed reference environment's own docs during a root-cause investigation and produced 'already implemented in the mature tree' recommendations -- exactly the No-Golden-Reference-Content-Mining violation the standing rule forbids, self-caught and self-reported by the dispatching agent",
    "scope": "engine",
    "symptoms": [
        "During the live USB VIP build's TCA-hang root-cause investigation, a sub-agent dispatched by the build agent read D:\\DV\\Task\\USB\\uvm\\docs\\ssphy-bringup.md and usb_stages.svh -- files belonging to the completed, mature reference environment (the exact reference tree this project's own CLAUDE.md names as usable ONLY for structural conformance checking, never as a content source)",
        "That sub-agent's recommendations were framed as 'already implemented in the mature uvm tree' -- i.e. content mined from the golden reference and proposed for direct reuse, not independently re-derived from primary sources (DUT RTL, PHY databook)",
    ],
    "root_cause": (
        "The dispatching agent's own prompt to its sub-agent did not explicitly fence off the reference-environment tree "
        "as off-limits for that specific investigation -- the No-Golden-Reference-Content-Mining rule was known and "
        "generally followed elsewhere in the same session's work (e.g. the ATTACH_LAYER/DUT_ROLE/bind-location decisions "
        "were all sourced from DUT RTL/VIP evidence, not the reference tree), but a dispatch prompt for a specific "
        "sub-investigation did not carry that constraint forward explicitly, and the sub-agent -- lacking that context -- "
        "took the path of least resistance (a working reference implementation exists, read it) rather than re-deriving "
        "the sequencing logic from the DUT RTL/PHY databook independently."
    ),
    "fix": (
        "The dispatching agent caught this itself (not the user, not an external review) by recognizing the sub-agent's "
        "own framing ('already implemented in the mature tree') as a red flag matching the standing rule's exact "
        "prohibition. Split the sub-agent's result: kept everything genuinely DUT-RTL-sourced, quarantined (discarded, "
        "not merged) everything sourced from the reference environment's own docs. Explicitly stated intent to re-derive "
        "any genuinely-needed sequencing guidance from the databook and RTL directly if it turns out to matter, rather "
        "than falling back to the quarantined content."
    ),
    "verification": {
        "single_sim": "N/A (process/rule-compliance defect, not a simulation fix)",
        "regression": "N/A",
        "reaudit": "Self-caught and self-corrected within the same investigation, 2026-09-03 -- no external verification was needed to catch it, which is itself the noteworthy part.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON: knowing a rule generally applies to a session's work is not the same as that rule being "
        "carried forward into every sub-dispatch within that work. When an agent (or a controlling session) delegates a "
        "sub-investigation to another agent, any standing constraint that matters for THAT specific sub-task (here: "
        "'never read the golden-reference tree for content, only for structural comparison after the fact') must be "
        "restated explicitly in the sub-dispatch's own prompt -- it cannot be assumed to survive by osmosis from the "
        "parent context. This mirrors a related lesson from earlier the same session (MEM-7F2DCD9E83): citing one "
        "instruction/file and expecting a dispatched agent to independently infer the full scope of a standing rule is "
        "not reliable; the specific constraint needs to be spelled out at each dispatch boundary where it could "
        "plausibly be missed. The positive half of this lesson is equally worth keeping: the SELF-catching of this "
        "violation, purely from recognizing the sub-agent's own suspicious framing, worked -- this is a real example of "
        "the independent-verification/self-skepticism discipline this session has repeatedly reinforced actually paying "
        "off in practice, not just in theory."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-03, live USB VIP build (IP_UVM_DV_Gen agent), self-caught and self-reported.",
}


def main() -> int:
    for record in (RECORD_RENAME, RECORD_SELFREPORT):
        result = route_and_store(ROOT, record)
        print(f"[{record['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
