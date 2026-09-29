"""Persists the 2026-09-02 USB_UVM_Handoff distillation audit into
Engineering Memory, via memory_router.route_and_store() (auto-loads cfg,
pushes to the shared Knowledge Center automatically).

User-directed audit: verify whether USB_UVM_Handoff's file structure,
verification environment, command.txt content architecture, VIP examples
integration, and Makefile content have genuinely been distilled into
DV Agent Harness L5's permanent assets (code + skills), not just left as a
reference tree someone might informally consult. Three records: what's
confirmed already-consolidated (for discoverability), what's a genuine gap
(command.txt/pattern content architecture), and what's a partial gap
(Makefile/sim-scripts).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD_CONFIRMED = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "USB_UVM_Handoff distillation audit (2026-09-02): file structure, verification-environment composition, and VIP-examples grounding ARE real, code-level Harness assets -- confirmed and documented here for discoverability",
    "scope": "engine",
    "symptoms": [
        "User asked directly: was USB_UVM_Handoff's file structure/verification-environment/VIP-examples-integration ever actually distilled into DV Agent Harness L5, or just informally referenced ad hoc during builds?",
        "The current live USB build (IP_UVM_DV_Gen agent, 2026-09-02) reported it never listed dv_harness/uvm_generator/ and hand-authored everything independently -- raising doubt about whether any of this consolidated knowledge actually exists or gets used",
    ],
    "root_cause": "N/A -- this is a confirmation record, not a bug record.",
    "fix": (
        "Audited dv_harness/uvm_generator/*.py directly. CONFIRMED real, dated, line-cited evidence baked into the actual "
        "generation code (not just comments referencing the idea): generator.py has 20+ real citations of USB_UVM_Handoff's "
        "usb_top_env.sv (connect_phase, port counting, scoreboard wiring, e.g. lines 85/178/182/371-377/407-414/472/506/531) "
        "and usb_virtual_sequencer.sv (line 36) informing real generation functions -- port-count derivation, multi-component "
        "composition, scoreboard connection patterns. protocol_env_generator.py documents the real (non-flat) tb/ tree shape "
        "(tb/agents, tb/env, tb/seq, tb/patterns/common). soc_environment_composer.py explicitly enforces the CLAUDE.md rule "
        "that content must be sourced from VIP examples/manual/source, not invented. dv_harness/uvm_generator/templates/"
        "sim_scripts/ was confirmed to be a real, byte-identical-origin copy of USB_UVM_Handoff/sim/scripts/, now chip-"
        "configured for THIS exact project (waves.tcl hardcodes sysn063/u_lan063/u_ss_vout; Makefile has TOPMOD:=sysn063, "
        "PORTS?=0|1|both) -- confirmed by the build agent's own reconciliation report the same day. There is also a real, "
        "mechanically-enforced anti-mining gate (dv_harness/prompts.py's protocol_isolation_gate): any evidence citation "
        "whose resolved path contains 'USB_UVM_Handoff' during real stage evaluation FAILs closed (REFERENCE_TREE_CITATION_"
        "FORBIDDEN) -- the No-Golden-Reference-Content-Mining rule is enforced in code, not just documented in CLAUDE.md."
    ),
    "verification": {
        "single_sim": "N/A (documentation/knowledge-consolidation audit, not a simulation fix)",
        "regression": "N/A",
        "reaudit": "Confirmed via direct source read of dv_harness/uvm_generator/*.py and dv_harness/prompts.py, 2026-09-02.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "IMPORTANT CAVEAT, found the same day: this consolidated code asset existing and being CORRECT does not mean it gets "
        "USED. The current live USB build never called any of it -- see the companion record on the IP_UVM_DV_Gen agent's "
        "own admission ('I never listed the directory'). Consolidating knowledge into dv_harness/uvm_generator/ is necessary "
        "but not sufficient; the agent/skill dispatching a real build must actually be told to survey that directory first. "
        "CLAUDE.md:135 already names a sibling file in the same directory (regression_list_manager.py) but that alone was "
        "not enough for the dispatched agent to notice the rest of the directory -- a future dispatch prompt for this kind "
        "of work should explicitly instruct 'list dv_harness/uvm_generator/ and dv_harness/uvm_generator/templates/ before "
        "hand-authoring anything', not just cite one file."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-02, USB_UVM_Handoff distillation audit directed by the user.",
}

RECORD_GAP_COMMAND_TXT = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "command.txt/pattern content architecture (block/branch_a/branch_fw/branch_b task composition, arbitration and ordering traps) was NEVER distilled beyond a thin 23-line generic skill -- captured here with real evidence, closing part of the gap",
    "scope": "engine",
    "symptoms": [
        "grep across dv_harness/uvm_generator/*.py for 'command.txt'/'command_txt': ZERO hits -- the actual generator code has no encoded knowledge of how to construct a pattern file's content, only command_semantic_expectation_parser.py (a VERIFICATION-side parser under tools/verification_flow/, used to check an existing pattern against the DUT's real command.txt during VERIFY, not to author a new one)",
        ".claude/skills/CORE/command-generator/SKILL.md is only 23 lines, entirely generic (vPlan-gap-driven command_mapping.csv maintenance), with zero citations of USB_UVM_Handoff, zero mention of the real block/branch_a/branch_fw/branch_b task-composition pattern",
    ],
    "root_cause": (
        "The real, rich architectural knowledge lives only in USB_UVM_Handoff's own pattern .txt files and their own "
        "in-repo README.md/soc_run.svh -- e.g. uvm/tb/patterns/enumeration/usb20_enumeration.txt's real content demonstrates: "
        "`include soc_int.svh (blocking, SoC-level, once) -> `include soc_run.svh (branch_a0/branch_a1: ss_vout_init_flow "
        "then each port's controller bring-up, launched into the background, non-blocking) -> `USB_FORK_FW_SERVICE (branch_fw: "
        "per-port firmware service, never returns, raises usb_fw_port_running[p]) -> fork/join (NOT join_any -- explicitly "
        "documented as unsafe once firmware is its own branch, with a real job number and timestamp showing a false-positive-"
        "reading early exit) of branch_b0/branch_b1 (per-port USB traffic macros: USB_WAIT_CTRL_READY -> USB_STAGE_LINKUP -> "
        "USB_ENUMERATE -> USB_TRAFFIC_CTRL) -> FINAL_CHECK. Named traps embedded in the pattern comments: trap 51 (APB_* VIP "
        "sequences and `CPUWRITE hold different locks on the SAME sequencer -- UVM arbitration can interleave them and "
        "silently overwrite a USB register write; 'NO SoC REGISTER CONTENT MAY BE ADDED TO A HOST SCRIPT'), trap 98 (LINKUP "
        "must precede ENUMERATE -- enumeration cannot start before DSTS.CONNECTSPD reports the port's built speed). None of "
        "this was ever pulled out into a reusable, general Harness asset -- every future pattern author has to re-discover "
        "it by reading USB_UVM_Handoff's raw files directly, which is exactly the kind of one-off tribal knowledge the "
        "Methodology Consolidation Rule exists to prevent."
    ),
    "fix": (
        "Not yet fixed in code/skill -- this record captures the real architecture as Knowledge Center content per the "
        "user's explicit instruction, as a first step. Recommended real fix (not yet built): either (a) expand "
        "command-generator/SKILL.md substantially with this real block/branch_a/branch_fw/branch_b pattern, the fork/join-"
        "not-join_any rule, and the trap catalogue, generalized beyond USB-specific macro names to the protocol-agnostic "
        "shape, or (b) add real generation logic to dv_harness/uvm_generator/ (a pattern_content_generator.py sibling to "
        "pattern_registry_generator.py) that can emit a real branch_a/branch_fw/branch_b skeleton from a protocol profile, "
        "the way generator.py already does for env composition."
    ),
    "verification": {
        "single_sim": "N/A (knowledge-consolidation gap, not a simulation fix)",
        "regression": "N/A",
        "reaudit": "Confirmed via direct grep of dv_harness/uvm_generator/*.py (0 hits) and direct read of both command-generator/SKILL.md (23 lines, generic) and USB_UVM_Handoff/uvm/tb/patterns/enumeration/usb20_enumeration.txt (114 lines, real architecture), 2026-09-02.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON: a skill file existing with a plausible-sounding name (command-generator) is not evidence "
        "that the real architectural knowledge behind a class of artifact has actually been captured -- this one was 23 "
        "generic lines while the real, hard-won knowledge (fork/join semantics, arbitration locks, ordering traps) sat "
        "entirely in the reference project's own files, never pulled out. When auditing 'has X been consolidated', check "
        "the actual CONTENT/DEPTH of the skill or code that claims to cover it, not just whether a plausibly-named file "
        "exists."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-02, USB_UVM_Handoff distillation audit directed by the user.",
}

RECORD_GAP_MAKEFILE = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "Makefile/sim-scripts consolidation from USB_UVM_Handoff is real but incomplete -- 5 files never migrated, and mature real capabilities in the already-consolidated template (regression.list, TEST=, -W, lsf_regress.sh, incremental build, coverage/UNR) went unused by the same-day live USB build because nothing pointed the dispatched agent at them",
    "scope": "engine",
    "symptoms": [
        "dv_harness/uvm_generator/templates/sim_scripts/ (Makefile, check/*, gen_pattern_pool.py, lsf_run.sh, lsf_regress.sh, lsf_wait.sh, waves.tcl, ip_run.sh) is a real, byte-identical-origin, now chip-specific-configured copy of USB_UVM_Handoff/sim/scripts/ -- but 5 files present in the original (analyze_sim.sh, apb_timing_report.sh, dpdm_report.sh, irq_report.sh, check/gen_scaledown.py) were never carried over, with no documented rationale anywhere in the codebase",
        "The same-day live USB VIP build (IP_UVM_DV_Gen agent) hand-built its own sim/scripts/Makefile independently, never consulting the already-consolidated, already-chip-configured template -- and its own honest reconciliation report catalogued the real capability gap this caused: no TEST=/+UVM_TESTNAME= test-selection knob at all, full rebuild every time instead of incremental stamp-file builds, no coverage/UNR, no regression.list verdict bookkeeping, and a fire-and-forget bsub instead of the template's real 753-line lsf_regress.sh (concurrency groups, -W timeout, stall detection, stale-log guard)",
    ],
    "root_cause": (
        "Two independent, compounding gaps. (1) The migration itself is incomplete -- 5 files with no callers found within "
        "the original scripts directory itself (so their omission didn't break anything internally) but with unverified "
        "importance to a real user-facing workflow (waveform/timing/power-domain/IRQ analysis reports), silently dropped "
        "with zero record of the decision. (2) Even the PART that IS consolidated (Makefile, LSF scripts) went completely "
        "unused by a same-day real build task, because CLAUDE.md pointed the dispatched agent at exactly one sibling file "
        "(regression_list_manager.py) rather than the directory as a whole -- see the companion confirmed-consolidation "
        "record for the full analysis of that miss."
    ),
    "fix": (
        "Not yet fixed -- this record captures the concrete gap list per the user's explicit instruction. Two real, "
        "separately-scoped follow-ups: (a) migrate the 5 missing scripts into dv_harness/uvm_generator/templates/sim_scripts/ "
        "(or explicitly document per-file why each is out of scope, if that turns out to be the right call after inspecting "
        "them), and (b) retrofit the live USB build's sim/scripts/Makefile to adopt the template's regression.list/TEST=/-W/"
        "lsf_regress.sh mechanics rather than its own thinner reimplementation -- the build agent's own report already "
        "recommended this as next-step work."
    ),
    "verification": {
        "single_sim": "N/A (knowledge-consolidation gap, not a simulation fix)",
        "regression": "N/A",
        "reaudit": "Confirmed via find/diff comparison of dv_harness/uvm_generator/templates/sim_scripts/ against USB_UVM_Handoff/sim/scripts/, plus the live build agent's own same-day reconciliation report, 2026-09-02.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON: a partial migration (most files moved, a few silently dropped with no record) is nearly as "
        "dangerous as no migration -- a future reader sees the template directory, reasonably assumes it is the complete, "
        "current source of truth, and has no way to know 5 real files are missing without an explicit diff against the "
        "origin. Any 'consolidate X into the Harness' task should end with an explicit, recorded file-count/diff check "
        "against the source, not just 'copied the important-looking files over'."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-02, USB_UVM_Handoff distillation audit directed by the user.",
}


def main() -> int:
    for record in (RECORD_CONFIRMED, RECORD_GAP_COMMAND_TXT, RECORD_GAP_MAKEFILE):
        result = route_and_store(ROOT, record)
        print(f"[{record['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
