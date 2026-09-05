export const meta = {
  name: 'close-comparative-analysis-gaps',
  description: 'Turn the Harness-vs-USB_UVM_Handoff comparative analysis findings into permanent Harness capabilities, verified to prevent recurrence',
  phases: [
    { title: 'Build', detail: '4 parallel workstreams closing 4 confirmed gaps' },
    { title: 'Review', detail: 'independent verification each gap is actually closed, not just documented' },
  ],
}

const CONTEXT = `
## Background: what this workflow exists to fix

A user directly questioned why the Harness-built D:\\DV\\Task\\USB\\usb31_dev_uvm environment
hit problems (unresolved TCA hang, self-inflicted regressions, a wrong root-cause
conclusion from a blind register write, a lost agent session) that the reference
D:\\DV\\Task\\DV_Agent_Harness_L5\\USB_UVM_Handoff apparently didn't. A deep, evidence-based
investigation (this session, 2026-09-03) confirmed 4 real, distinct process/capability
gaps -- not DUT complexity, not excuses. Per this project's own CLAUDE.md Methodology
Consolidation Rule ("Once a real deficiency/weakness/gap is confirmed by evidence... it
must be closed by launching multi-agent implementation work on all currently-known
confirmed gaps together"), this workflow closes all 4 together, and per the user's own
explicit instruction each fix must be VERIFIED to prevent recurrence (real test / fault
injection proving the fix works), not merely documented.

This session currently has other concurrent workstreams that may still have uncommitted
work in dv_harness/config.py, dv_harness/cli.py, dv_harness/engine.py, CLAUDE.md. Before
editing any shared file, run 'git status --short' and 'git diff <file>' to see what is
already there. Before committing, run 'git diff --cached <file>' and confirm it shows
ONLY your own intended change -- if not, unstage and use a hand-built 'git apply --cached'
patch scoped to your own hunk (this technique has been used successfully many times today
in this repo -- search git log for "Fix real preflight-gate regression" or "Fix
governance-review findings" for worked examples).

The live USB build at D:\\DV\\Task\\USB\\usb31_dev_uvm is ALSO being actively worked by a
separate, currently-running investigation agent (chasing the TCA hang root cause). Do NOT
run any build/simulation command against that tree, and do NOT modify any file under
D:\\DV\\Task\\USB\\usb31_dev_uvm\\uvm\\tb\\ while that investigation may still be in progress --
read-only access to that tree (for citing real examples, running static/text analysis) is
fine and encouraged; live builds/runs and file edits there are not your job in this
workflow.
`

phase('Build')

const referenceAudit = agent(`${CONTEXT}

## Your task: build a systematic reference-pattern coverage audit tool (Gap #1)

Confirmed finding: reference/bfm_patterns/*.txt files (the DE-provided originals) were only ever consulted reactively, bug by bug -- never with an upfront systematic pass. This cost 3 real debugging rounds finding that usb_p2_switch_en is written on the host TCA register but never the DUT TCA in any HS pattern -- a mechanically-detectable host/DUT write asymmetry that a systematic audit would have caught on day one.

Concrete requirements:
1. New tool, e.g. dv_harness/reference_pattern_audit.py: given a directory of reference BFM pattern files (*.txt, the reference/bfm_patterns/ convention already established in usb31_dev_uvm/CLAUDE.md), mechanically extract every register-write-style task call (\`CPUWRITE*B\`/\`HOSTWRITE*B\`/similar macro-invocation patterns -- read a couple of real reference/bfm_patterns/*.txt files under D:\\DV\\Task\\USB\\usb31_dev_uvm\\reference\\bfm_patterns\\ READ-ONLY first to ground the real syntax, do not guess it) into a structured record: {file, line, macro, address_or_register, value, host_or_dut_context}.
2. Build a real symmetry/coverage check on top of that extraction: for any register name/address that appears in a "paired endpoint" context (this project's own convention already distinguishes host-side vs DUT-side addresses for the same logical register, e.g. TCA appearing at both a host offset and a DUT offset -- design a detector for this pattern generically, e.g. same register-offset suffix appearing under two different base addresses, or grep for an explicit HOST/DUT naming convention in the real files you read), flag any case where one side writes a register/field the other side never touches. This is exactly the class of fact that would have caught the real usb_p2_switch_en asymmetry -- verify your tool actually catches it by running it against the real reference/bfm_patterns/ directory (read-only) and confirming it flags the known real asymmetry (USB2_bulkin.txt / USB2_bulkout.txt-style files writing TCA_CTRLSYNCMODE's usb_p2_switch_en on the host offset 0x161A_0020 but never on the DUT offset 0x1272_0020 in any HS-speed pattern) -- if you can't reproduce that specific finding, your detector logic needs rethinking, don't just ship a version that misses the known case.
3. Wire this as a REQUIRED step in .claude/agents/IP_UVM_DV_Gen.md's own documented workflow (read that file first) -- add an explicit early step: "before writing any bring-up pattern, run the reference-pattern coverage audit and review its findings" -- not an optional/suggested step, a required one with the same weight as this file's other required steps.
4. New CLI subcommand: dv-harness reference-audit <dir> (read cli.py's existing subcommand conventions first, match the style).
5. Real tests: the extraction logic against a small synthetic fixture (never real project content) proving the macro-call parsing works, AND a real test that runs the tool against the actual reference/bfm_patterns/ directory (read-only, this is a real integration test against real content, not a synthetic fixture -- this project's own established pattern for run_profile.py's extractor tests did exactly this against a real template Makefile) and asserts the known asymmetry is actually flagged in the output.

Write a report to .work/gap-close-reference-audit-report.md. Run your tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED with a one-line test summary, and explicitly confirm/deny whether your tool reproduces the known real finding.`, {label: 'build:reference-audit-tool', phase: 'Build'})

const mandatoryGates = agent(`${CONTEXT}

## Your task: make the 3-gate bind-connectivity verification MANDATORY and trackable (Gap #2)

Confirmed finding: dv_harness/connectivity.py's 3-gate standard (elaboration / static zero-time connectivity / transaction activity -- read that file in full first, it's real and already built) has never been applied to the live usb31_dev_uvm build, because it was built mid-session by a different concurrent effort and nothing retroactively flags in-flight work against new verification infrastructure. Also, Gate 3 (transaction activity) cannot pass until a pattern actually completes -- which hasn't happened yet for this build (TCA hang) -- and this PENDING state needs to be trackable and explicit, never silently indistinguishable from "not checked" or "failed".

Concrete requirements:
1. Read dv_harness/connectivity.py's real gate functions (run_gate1_elaboration_check, run_gate2_..., run_gate3_...) and its BindTierResult/report shape in full.
2. Add an explicit gate-status enum/field if one doesn't already exist that distinguishes NOT_YET_RUN / PENDING (a prerequisite, like a completed pattern, doesn't exist yet) / PASSED / FAILED -- never conflating PENDING with FAILED or with "not applicable". Check connectivity.py's existing report schema first; extend it rather than building a parallel one if a suitable field already exists.
3. Update .claude/agents/IP_UVM_DV_Gen.md's documented workflow to make running gates 1 and 2 a REQUIRED checkpoint immediately after first successful compile/elaboration (not optional, not "when convenient"), and require Gate 3's status to be explicitly reported (even if PENDING) in every build-status report the agent produces from that point forward, so a build report can never simply omit bind-verification status.
4. Also update CLAUDE.md's own "Bind-Location Rules (2026-09-03)" section (read it first) to note explicitly that the 3 gates are a REQUIRED workflow checkpoint for IP_UVM_DV_Gen builds, not merely available tooling -- currently that section describes the gates as existing capability without mandating their use in the build workflow itself.
5. Do NOT run any live build/gate check against the actual usb31_dev_uvm tree (a separate agent owns that live tree right now -- see the shared CONTEXT note above). Instead, prove your mandatory-checkpoint wiring works using a synthetic/test project structure: write a test that simulates an IP_UVM_DV_Gen-style build reaching "first successful compile" and asserts gate 1/2 are required to have been invoked (or their PENDING/FAILED status explicitly surfaced) before the workflow is considered allowed to proceed to the next documented step -- if IP_UVM_DV_Gen.md's workflow isn't mechanically enforced by code (it may just be agent-followed documentation, check this first), then the verification is: confirm the document itself unambiguously states the requirement, and add a real, standalone lint/check script (e.g. dv_harness/uvm_generator or a new small script) that CAN be run against any build tree's own status/report artifacts to flag "Gate 3 status missing from this report" -- design whichever mechanism actually fits how IP_UVM_DV_Gen currently operates (check first, don't assume a mechanically-enforced gate exists if it's actually agent-followed prose).

Write a report to .work/gap-close-mandatory-gates-report.md, explicitly stating whether the enforcement mechanism you built is a mechanical code check or a strengthened/clarified documentation requirement (and why that's the right choice given how IP_UVM_DV_Gen actually operates). Run your tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED with a one-line test summary.`, {label: 'build:mandatory-gates', phase: 'Build'})

const registerSafety = agent(`${CONTEXT}

## Your task: build a generalized register-write-safety static check (Gap #3)

Confirmed finding: a blind literal-value register write (TCA_CTRLSYNCMODE written as the literal 0x00000400 instead of read-modify-write) silently clobbered 4 unexamined bits at their non-zero reset defaults, and produced a WRONG "fix is ineffective" root-cause conclusion that took several further debugging rounds to reverse, because "the write landed but the symptom didn't change" is not sound evidence when other live bits were corrupted by the same write.

Concrete requirements:
1. Read D:\\DV\\Task\\USB\\usb31_dev_uvm\\sim\\scripts\\usb_static_check.py in full (READ-ONLY -- this is the live build's own static checker; you are not editing this file, you are using it as a real reference for this project's established per-category static-check convention before building a NEW, GENERIC version). It has 15 categories; read a couple of existing category implementations (e.g. category 13 mentioned in this session's history, the DUT-path-corruption guard) to understand the real code style/pattern this checker uses.
2. Build a NEW, generic (protocol-agnostic, not USB-specific) static check -- following the same genericization convention already established this session for dv_harness/uvm_generator/templates/sim_scripts/* (TARGET_IP/IP_PREFIX-style parameterization, read a couple of those files for the convention) -- that flags: a register-write macro call (CPUWRITE4B/CPUWRITE2B/CPUWRITE1B/HOSTWRITE4B or similar, generalize the macro-name pattern rather than hardcoding USB's exact macro names) using a bare literal hex/decimal constant as the value argument, where (a) no read-modify-write pattern (a preceding CPUREAD* into the same variable, then a bitwise-OR/AND-NOT combining that variable with a literal before the write) is present for that same register, AND (b) a register-width/bit-field reference table is available to cross-check against (design this as an optional input -- if no such table is supplied, the check should still flag "literal write with no RMW, register semantics unknown -- verify manually" rather than silently passing). This directly targets the exact defect class this session hit.
3. Add this as a new template file in dv_harness/uvm_generator/templates/sim_scripts/check/ (matching the existing check/*.py convention already established there from the earlier USB_UVM_Handoff distillation work this session -- read what's already in that directory first) -- e.g. reg_write_safety.py, with the same --help/docstring conventions already established for that directory's other scripts.
4. Real test: a synthetic fixture (small, never real project content) containing both a real RMW pattern (should NOT be flagged) and a blind literal write to a multi-field register (SHOULD be flagged), proving the detector actually distinguishes the two. Also write a test replicating the REAL historical bug as a fixture (a CPUWRITE4B of a literal 0x00000400-style value with a known nonzero-reset-value register comment nearby) and confirm your check flags it -- this is the "prove it would have caught the real bug" verification the user explicitly asked for.
5. Do NOT run this check against the live usb31_dev_uvm tree yet (a separate agent owns that tree right now) -- note in your report that a follow-up run against that tree, once the TCA investigation concludes, is a recommended next step, but is out of scope for you to do now.

Write a report to .work/gap-close-register-write-safety-report.md. Run your tests yourself and confirm pass before reporting DONE, including explicit confirmation the historical-bug-shaped fixture is caught. Report DONE/BLOCKED with a one-line test summary.`, {label: 'build:register-write-safety', phase: 'Build'})

const agentCheckpoint = agent(`${CONTEXT}

## Your task: formalize a long-running build/investigation agent checkpoint convention (Gap #4)

Confirmed finding: the IP_UVM_DV_Gen build agent investigating the TCA NC->USB hang became permanently unresumable mid-investigation this session (a real 'No transcript found for agent ID' failure on SendMessage) after accumulating many hours of context. It happened to recover reasonably well because its own documentation habits (CLAUDE.md trap catalogue, dut-request.md, in-code retraction comments) were already thorough -- but that was a side effect of general good practice, not a checked, required convention. A less disciplined agent losing its session would have no formal fallback.

Note: this is a DIFFERENT gap from what this session's earlier "harness reliability" workflow already built (dv_harness/session_snapshot.py auto-checkpoint at DVHarness's own run_stage()/loop() stage transitions, and dv_harness/degradation.py). That mechanism covers the ENGINE's own stage loop. It does NOT cover a separately-dispatched, long-running background build/investigation Agent-tool subagent's own accumulated context (like the IP_UVM_DV_Gen agent that was lost) -- read dv_harness/session_snapshot.py briefly to confirm this scope boundary before building something that duplicates it.

Concrete requirements:
1. New skill, e.g. .claude/skills/CORE/agent-checkpoint-discipline/SKILL.md (check the existing .claude/skills/CORE/ directory structure and a couple of real SKILL.md files there first for the real format/style convention -- e.g. .claude/skills/CORE/pattern-architecture/SKILL.md if it exists, or any other real example) -- defining a REQUIRED convention: any agent expected to run more than a small number of rounds (a build/investigation agent, not a quick one-shot task) must maintain a structured, continuously-updated resume-state artifact with a defined schema: current hypothesis/status, evidence gathered so far (with citations), next planned step, decisions pending user/coordinator confirmation, files touched this session. Specify a concrete file location convention (e.g. a STATUS.md or RESUME.md at a predictable path within the build tree the agent is working in) and a concrete update cadence (after every round that changes the investigation's state, not just at the end).
2. This convention should explicitly reference the REAL, ALREADY-WORKING example from this exact session as a worked illustration: usb31_dev_uvm/CLAUDE.md's trap catalogue + docs/dut-request.md together already functioned as a de facto version of this (that's literally how the fresh agent was successfully re-briefed after the session loss) -- codify what made that recovery work as the formal required pattern, rather than inventing an unrelated new format.
3. Update .claude/agents/IP_UVM_DV_Gen.md (read it first) to reference this new skill and require it.
4. This is fundamentally a documentation/convention deliverable (a skill is prose guidance, not executable code) -- but per the user's explicit instruction that fixes must be "verified to confirm the problem won't recur," add a concrete, checkable verification method: a real, standalone script (e.g. dv_harness/agent_checkpoint_check.py or similar) that, given a build-tree path, checks whether a resume-state artifact matching the defined schema exists and looks reasonably current (e.g. checks for required sections, checks the file's mtime isn't stale relative to other recently-modified files in the tree) -- and a real test proving this checker correctly distinguishes "a tree with a real, current resume-state artifact" from "a tree without one" using synthetic fixtures.
5. Do NOT create or modify any file under D:\\DV\\Task\\USB\\usb31_dev_uvm -- that tree is owned by a separate, currently-running agent. Your deliverable lives entirely in the v50 Harness repo (skills, docs, the new checker script and its tests). If you want to demonstrate the checker against a real example, use usb31_dev_uvm as a READ-ONLY test subject (confirm your checker reports it as "has a resume-state artifact" given its real CLAUDE.md+dut-request.md, without writing anything to that tree).

Write a report to .work/gap-close-agent-checkpoint-report.md. Run your tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED with a one-line test summary.`, {label: 'build:agent-checkpoint', phase: 'Build'})

const [referenceAuditResult, mandatoryGatesResult, registerSafetyResult, agentCheckpointResult] = await parallel([
  () => referenceAudit, () => mandatoryGates, () => registerSafety, () => agentCheckpoint,
])

phase('Review')

const review = await agent(`Independently review this 4-workstream effort closing the gaps found by today's "why does the Harness-built USB environment have problems the reference didn't" comparative analysis, for DV Agent Harness L5. Read all 4 reports in full first:

D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\gap-close-reference-audit-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\gap-close-mandatory-gates-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\gap-close-register-write-safety-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\gap-close-agent-checkpoint-report.md

Raw returned results (cross-reference against the report files):

### reference-audit-tool
${referenceAuditResult}

### mandatory-gates
${mandatoryGatesResult}

### register-write-safety
${registerSafetyResult}

### agent-checkpoint
${agentCheckpointResult}

Verify by running real commands yourself -- never by trusting any report's prose. The user's explicit bar for this work is "functional reinforcement that CONFIRMS the problem won't happen again," not documentation alone. For each workstream, check:

1. **reference-audit-tool**: actually run the new dv-harness reference-audit tool yourself against the real D:\\DV\\Task\\USB\\usb31_dev_uvm\\reference\\bfm_patterns\\ directory (read-only) and confirm it genuinely flags the known real usb_p2_switch_en host/DUT asymmetry. If it doesn't reproduce that finding, this workstream has not actually closed the gap regardless of what its report claims.
2. **mandatory-gates**: read the actual updated IP_UVM_DV_Gen.md and CLAUDE.md text yourself -- is the requirement genuinely unambiguous (a build agent could not reasonably read it and conclude the gates are optional), or is it soft/hedged language? If a mechanical checker was built, run it against a synthetic case yourself and confirm it actually catches a missing-gate-status report.
3. **register-write-safety**: run the new check yourself against its own historical-bug-shaped fixture and confirm it flags it; also run it against a real, clean RMW example and confirm it does NOT false-positive.
4. **agent-checkpoint**: run the new checker script yourself against the real (read-only) usb31_dev_uvm tree and confirm it correctly recognizes CLAUDE.md+dut-request.md as a real resume-state artifact; also run it against an empty/synthetic tree with no such artifact and confirm it correctly flags the absence.
5. Confirm none of the 4 workstreams touched or ran anything against D:\\DV\\Task\\USB\\usb31_dev_uvm\\uvm\\tb\\ (the live build's own source tree) -- read-only citation is fine, any write or build/run command is not.
6. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
7. Check git hygiene: confirm no whole-file git add swept in unrelated uncommitted changes from other concurrent workstreams still in this crowded working tree.

Report a clear verdict (APPROVED / NEEDS_FIX) with concrete, evidence-cited findings per workstream. Be explicit about which gaps are genuinely closed (mechanically verified) vs. only documented/hoped-to-help.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { referenceAuditResult, mandatoryGatesResult, registerSafetyResult, agentCheckpointResult, review }
