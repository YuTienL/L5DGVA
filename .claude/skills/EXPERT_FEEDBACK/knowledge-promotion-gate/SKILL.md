---
name: knowledge-promotion-gate
description: Promote learning only to correct Project/Protocol/Platform scope.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# knowledge-promotion-gate
Promote learning only to correct Project/Protocol/Platform scope.
Expert suggestion is a hypothesis until current evidence verifies it.

## Mechanics (2026-09-03, real wiring)

**Purpose**: an expert-feedback-sourced suggestion (from
`dv-expert-review-intake`/`dv-expert-impact-analyzer`) must clear the SAME
verification gate as any other candidate knowledge before it is trusted at
Project/Protocol/Platform scope -- expert authority is not itself evidence.

**Inputs**: an expert suggestion plus its scope claim (this specific
project, this protocol generically, or the whole platform/harness).

**Outputs**: a routed memory record at the scope-appropriate tier --
Project-scoped -> `PROJECT_MEMORY` (`project-memory` skill, `verified: true`
required); protocol/platform-generalizable -> `ENGINEERING_MEMORY` first,
then only `ORGANIZATIONAL_MEMORY` via
`memory_router.promote_to_organizational()` once independently reconfirmed
(see `organizational-memory` skill) -- never straight to Organizational on
a single expert's say-so, no matter how senior.

**Preconditions**: the suggestion must be validated against CURRENT
RTL/VIP/log/waveform/spec evidence for at least one real occurrence before
any record is written -- an unverified suggestion stays a hypothesis in
Working Memory / the expert-feedback closure loop, not a memory record.

**Execution Steps**:
1. `dv-expert-review-intake` captures the suggestion + claimed scope.
2. Verify it against current evidence for a concrete instance (not "this
   sounds right" -- an actual RTL/log/waveform check).
3. Route at the narrowest scope the evidence actually supports (a single
   project's quirk is PROJECT_MEMORY, not ENGINEERING_MEMORY; a
   protocol-general lesson still starts at ENGINEERING_MEMORY, never
   ORGANIZATIONAL_MEMORY directly).
4. `dv-expert-feedback-closure` records the outcome either way (adopted at
   scope X, or rejected/downgraded to hypothesis) -- a rejected suggestion
   is itself worth recording so it is not re-litigated from scratch next
   time.

**Fallback**: if scope is ambiguous (project-specific vs. protocol-general),
default to the NARROWER scope (Project, not Organizational) -- widening
later after independent reconfirmation is safe; over-widening immediately
is not.

**Evidence Requirements**: the same qualitative/quantitative/repeated-
confirmation gates as `engineering-memory`/`organizational-memory` --
expert seniority does not substitute for any of the three.

**Failure Conditions**: promoting an expert suggestion to Organizational
scope on first mention violates the "Never promote unverified hypotheses"
rule identically to any other unverified source.

**Example**: an expert flags "this VIP's reset sequencing needs an extra
delay on all AMBA-based DUTs." Verify it against THIS project's current
RTL/VIP first (-> PROJECT_MEMORY or ENGINEERING_MEMORY if root-caused and
verified here); only after a SECOND, independent project's build also
reconfirms it does it become eligible for
`promote_to_organizational(kind="methodology")`.
