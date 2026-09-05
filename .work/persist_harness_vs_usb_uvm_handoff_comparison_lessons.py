"""Persists the 2026-09-03 "why does the Harness-built usb31_dev_uvm environment
have problems USB_UVM_Handoff didn't" deep comparative analysis's real lessons
into Engineering Memory, via memory_router.route_and_store().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORDS = [
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "Reference BFM patterns (reference/bfm_patterns/*.txt) were consulted reactively, bug by "
            "bug, never with an upfront systematic line-by-line coverage audit -- and this directly "
            "cost 3 debugging rounds finding a real host/DUT write asymmetry (usb_p2_switch_en written "
            "on the host TCA only, never the DUT TCA) that a systematic pass would have surfaced on day one"
        ),
        "scope": "process",
        "symptoms": [
            "usb31_dev_uvm/CLAUDE.md's 31-entry trap catalogue cites reference/bfm_patterns/*.txt dozens "
            "of times, but every citation is pulled only while chasing a specific already-known bug -- "
            "zero entries describe an upfront full-coverage conversion/audit pass",
            "The TCA NC->USB investigation only discovered on its third round that USB2_bulkin.txt:79 "
            "writes usb_p2_switch_en to the HOST TCA register (0x161A_0020) but the DUT TCA "
            "(0x1272_0020) is never written in any HS pattern -- a structural, mechanically-detectable "
            "asymmetry between the two TCA endpoints' register writes",
        ],
        "root_cause": (
            "No tool or required process step exists in the Harness that mechanically extracts every "
            "register write / task call from the full set of reference pattern files and cross-checks "
            "for structural asymmetries (e.g. a register written on one endpoint/instance but not its "
            "counterpart) before bring-up work begins. Reference-pattern knowledge is only acquired "
            "on-demand, driven by whatever bug is currently being chased -- which finds the SAME class "
            "of fact only after it has already caused a real symptom, never before."
        ),
        "fix": (
            "Not yet fixed at the time of this record -- multi-agent implementation work to build a "
            "systematic reference-pattern coverage audit tool is being launched immediately following "
            "this analysis (see follow-up records/commits for the real implementation)."
        ),
        "verification": {
            "single_sim": "N/A -- process/methodology finding",
            "regression": "N/A",
            "reaudit": "Independently investigated via a dedicated fork tasked specifically with finding "
                        "evidence for or against a systematic line-by-line conversion claim; found none, "
                        "confirmed only reactive citation via grep across the full trap catalogue.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: 'the reference pattern was used, and cited with file:line evidence "
            "when a bug came up' is NOT the same claim as 'the reference pattern was systematically "
            "audited for coverage/symmetry before bring-up began', and the Harness's own reporting "
            "discipline (requiring file:line citations) can make the former look like the latter unless "
            "explicitly distinguished. A structural asymmetry (same logical operation applied to two "
            "peer endpoints, but the reference only performs it on one) is exactly the class of fact a "
            "mechanical extraction+diff tool catches for free, that reactive citation only catches after "
            "a real hang/failure forces the question."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, deep comparative analysis (fork a1745a6171cc312a9) "
            "answering the user's direct credibility questions about the usb31_dev_uvm build vs. "
            "USB_UVM_Handoff."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "VIP bind-location correctness was asserted via real RTL-citation reasoning (T1/T2-tier per "
            "the Harness's own confidence system) but was NEVER actually run through the Harness's own "
            "3-machine-gate verification standard (elaboration / static connectivity / transaction "
            "activity) -- because that tooling (dv_harness/connectivity.py) did not exist for most of "
            "this build's life, and once it existed nobody retroactively applied it"
        ),
        "scope": "process",
        "symptoms": [
            "usb31_dev_uvm's own CLAUDE.md (31-entry trap catalogue, extensive bind-architecture "
            "documentation) has zero references to connectivity.py or 'Gate 1/2/3' -- this build's bind "
            "decisions were made and documented entirely before that verification tooling existed",
            "Gate 3 (transaction activity -- 'the only method that catches a path that's syntactically "
            "legal but wired to the wrong instance') requires a live simv to deliver >=1 real "
            "transaction to a VIP monitor; this build has never gotten past initial link bring-up "
            "(the TCA NC->USB hang), so Gate 3 is structurally impossible to have passed yet",
        ],
        "root_cause": (
            "The 3-gate connectivity verification standard was built as new Harness infrastructure "
            "mid-session, by a concurrently-running workflow, with no mechanism to retroactively flag "
            "or re-verify already-in-progress builds against the new standard once it landed. A new "
            "verification capability landing in the Harness does not automatically get applied to work "
            "already underway."
        ),
        "fix": (
            "Not yet fixed at the time of this record -- multi-agent implementation work to (a) make "
            "the 3 gates a mandatory, checked step in the IP_UVM_DV_Gen build workflow going forward, "
            "and (b) formally track Gate 3's current PENDING (not FAILED, not PASSED) status for this "
            "build until a pattern actually completes, is being launched immediately following this "
            "analysis."
        ),
        "verification": {
            "single_sim": "N/A -- process/methodology finding",
            "regression": "N/A",
            "reaudit": "Independently investigated via a dedicated fork, which confirmed via direct grep "
                       "of usb31_dev_uvm/CLAUDE.md that zero mentions of connectivity.py/Gate 1/2/3 exist, "
                       "and confirmed via the build's own status reports that no pattern has ever "
                       "completed (TCA hang blocks all HS patterns to date).",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: 'the bind target is justified by a real RTL citation' and 'the bind "
            "is verified correct' are different claims, and the Harness's own T1-T4 confidence-tier "
            "system already encodes this distinction (T1/T2 = high confidence from real evidence, but "
            "still not the same as a live Gate-3 transaction-activity pass) -- yet without an explicit, "
            "mandatory checkpoint requiring Gate 3 status to be reported (PASSED/FAILED/PENDING, never "
            "silently omitted) for every bind claim, a well-reasoned T1/T2 justification can be mistaken "
            "for a completed verification. New verification infrastructure landing in the Harness needs "
            "an explicit retroactive-applicability check against in-flight work, not just future work."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, deep comparative analysis (fork a1745a6171cc312a9)."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "A mature, polished reference environment's clean appearance is evidence that extensive "
            "past debugging already happened and was cleaned up -- NOT evidence that a comparable build "
            "effort needs less debugging; USB_UVM_Handoff contains 670 real-incident citations across "
            "73% of its files with no surviving trap-catalogue-equivalent, meaning its own messy build "
            "history was real but is now invisible"
        ),
        "scope": "process",
        "symptoms": [
            "User compared the actively-in-progress, fully-visible usb31_dev_uvm build (31-entry trap "
            "catalogue, every wrong turn documented) against the finished USB_UVM_Handoff reference and "
            "asked why the former has so many more visible problems",
            "Grep of USB_UVM_Handoff for real-incident language ('trap N', 'Job NNNN', 'measured', "
            "'previously found/caused/cost') found 670 occurrences across 136 of ~186 files (73% of the "
            "tree) -- e.g. the already-known 'Job 98669' hang, 'trap 50/95' -- but no CLAUDE.md/dut-"
            "request.md-equivalent document survives inside it; every incident is fossilized as an "
            "inline code comment with the discovery PROCESS itself discarded",
        ],
        "root_cause": (
            "This is a structural, not a process, finding: a finished reference environment's visible "
            "artifact is, by definition, the post-cleanup state. Comparing a build's visible "
            "in-progress messiness against a different build's already-cleaned final state is not an "
            "apples-to-apples efficiency comparison unless the reference's own historical build cost is "
            "also accounted for."
        ),
        "fix": (
            "N/A -- this is an analytical/communication finding, not a code defect. The actionable "
            "consequence is: when reporting build progress or efficiency comparisons to a stakeholder, "
            "explicitly distinguish 'this build is less mature than that reference' from 'this build's "
            "PROCESS is less efficient than whatever produced that reference' -- the two are easy to "
            "conflate and the second claim requires evidence the first does not."
        ),
        "verification": {
            "single_sim": "N/A",
            "regression": "N/A",
            "reaudit": "Independently investigated via a dedicated fork's direct grep of USB_UVM_Handoff's "
                       "own file tree for incident-language, not assumed.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: this is itself the argument FOR the Harness's own trap-catalogue/"
            "dut-request.md documentation discipline -- USB_UVM_Handoff's 670 fossilized incident-"
            "comments prove exactly the kind of knowledge a structured, surviving trap catalogue "
            "preserves in reusable form, that inline-comment-only documentation loses (the comment "
            "survives, but the reasoning process, the false starts, and the reusable methodology do "
            "not). When asked 'why does the new build look messier', the honest answer includes 'because "
            "you can see its real debugging process, which the reference also had and discarded' -- not "
            "as an excuse, but as a genuinely relevant fact about what is and isn't a fair comparison."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, deep comparative analysis (fork a1745a6171cc312a9)."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "A blind register write (writing a literal constant to a multi-field register without "
            "reading its reset value / full bit-field definition first) is a generalizable, mechanically-"
            "detectable defect CLASS -- this session hit it once (TCA_CTRLSYNCMODE bit 10 write as "
            "0x00000400, clobbering 4 unexamined bits including one, auto_safe_state, that was genuinely "
            "live) and it produced a WRONG root-cause conclusion that took several further rounds to "
            "reverse"
        ),
        "scope": "engine",
        "symptoms": [
            "A register write intended to set one bit (usb_p2_switch_en, bit 10) used the literal value "
            "0x00000400 instead of a read-modify-write, silently clearing bits 8/9/13/16 at their "
            "non-zero reset defaults (real reset value 0x00012300) without ever having read what those "
            "bits do",
            "Because the write appeared to have 'no effect' on the target symptom, the fix was wrongly "
            "concluded ineffective and retracted -- when in fact one of the clobbered bits (bit 16, "
            "auto_safe_state) was genuinely live and its corruption could have masked the real effect, "
            "meaning the 'no effect' observation was not sound evidence either way",
        ],
        "root_cause": (
            "No check (static or process-level) in the Harness currently flags a literal-constant "
            "register write against a register whose reset value is non-zero or whose declared bit-"
            "field count exceeds the number of bits the write's own stated intent names."
        ),
        "fix": (
            "Not yet fixed at the time of this record -- multi-agent implementation work to add a "
            "generalized 'register write safety' static check (flagging literal writes to multi-field "
            "registers without RMW, when a reset-value/bit-field source is available to check against) "
            "is being launched immediately following this analysis."
        ),
        "verification": {
            "single_sim": "N/A -- the underlying TCA investigation itself is real and separately tracked",
            "regression": "N/A",
            "reaudit": "The clobbered-bit finding was independently confirmed by a fresh investigation "
                       "agent that traced all 4 affected bits to real RTL consumption sites and the real "
                       "PHY databook (dwc_usbc31sspphy_tsmc12ffcns databook section 14.1.7, pp.945-947), "
                       "confirming bit 16 (auto_safe_state) is genuinely live and was genuinely corrupted "
                       "by the blind write.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: 'the write landed (readback confirms the bus works) and the symptom "
            "didn't change' is NOT sound evidence that the targeted bit is ineffective, whenever the "
            "write was a blind literal-value write to a register with other live fields -- the symptom "
            "could be unchanged because the fix genuinely didn't work, OR because a side effect from the "
            "same write masked it. These two cases are indistinguishable without knowing the register's "
            "full reset value and bit-field semantics BEFORE writing, which is exactly what a "
            "register-write-safety check should enforce as a precondition, not something to reconstruct "
            "afterward when a conclusion turns out wrong."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, TCA NC->USB investigation (multiple rounds of the "
            "IP_UVM_DV_Gen build agent) + deep comparative analysis (fork a1745a6171cc312a9)."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "A long-running background build/investigation agent's session transcript can become "
            "permanently unresumable mid-investigation (confirmed real this session: 'No transcript "
            "found for agent ID' on a SendMessage attempt) with no formal Harness convention requiring "
            "such an agent to maintain a structured, continuously-updated resume-state file that a fresh "
            "agent could use to pick up cold"
        ),
        "scope": "engine",
        "symptoms": [
            "The IP_UVM_DV_Gen build agent investigating the TCA NC->USB hang became unresumable via "
            "SendMessage after having accumulated many hours and a 31-entry trap catalogue's worth of "
            "investigation context; a fresh agent had to be launched and re-briefed entirely from "
            "on-disk artifacts (CLAUDE.md, dut-request.md, in-code retraction comments) rather than "
            "simply continuing the conversation",
        ],
        "root_cause": (
            "No formal requirement exists for a long-running build/investigation agent to maintain a "
            "structured resume-state file (current hypothesis, evidence gathered so far, next planned "
            "step, decisions pending user confirmation) as a first-class, continuously-updated "
            "deliverable -- this build happened to survive the loss reasonably well because its own "
            "documentation discipline (CLAUDE.md trap catalogue, dut-request.md, in-code retraction "
            "comments) was already thorough, but that thoroughness was a side effect of general good "
            "practice, not a guaranteed, checked convention."
        ),
        "fix": (
            "Not yet fixed at the time of this record -- multi-agent implementation work to formalize a "
            "required 'long-running agent checkpoint' convention (a defined-schema resume-state file, "
            "required to exist and be current for any agent expected to run more than N rounds) is being "
            "launched immediately following this analysis."
        ),
        "verification": {
            "single_sim": "N/A -- infrastructure/process finding",
            "regression": "N/A",
            "reaudit": "N/A -- directly observed and confirmed via the actual failed SendMessage attempt "
                       "in this session, not inferred.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: this build's recovery worked because its documentation discipline was "
            "already good, by habit rather than by a checked requirement -- a less disciplined build "
            "agent losing its session would have no formal fallback at all. This is the same category "
            "of harness-reliability gap the session's own earlier 'checkpoint/rollback/degradation' work "
            "addressed for DVHarness's own stage-loop engine (dv_harness/session_snapshot.py, "
            "auto-checkpoint at stage transitions) -- but that mechanism is specific to DVHarness's own "
            "run_stage()/loop(), and does NOT cover a separately-dispatched, long-running background "
            "build/investigation agent's own accumulated context, which is a distinct persistence gap "
            "that needs its own, separate convention."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, USB build agent session loss (SendMessage failure "
            "on agent a970eda03b300ab8f) + deep comparative analysis (fork a1745a6171cc312a9)."
        ),
    },
]


def main() -> int:
    for record in RECORDS:
        result = route_and_store(ROOT, record)
        print(f"[{record['title'][:70]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
