# USB Pre-Flight Blocking Gaps Closure — Design Spec

## Context

A multi-agent wiring audit (2026-08-31, workflow `full-harness-wiring-audit`,
609 claims assessed across 315 skills / 16 agents / 45 dv_harness modules /
205 tools files, 299 flagged, 290 confirmed real gaps after adversarial
re-verification) found 4 BLOCKING gaps standing directly in the way of the
harness's first real USB VIP-based UVM environment generation run:

- **B1**: No code-level barrier prevents an agent from citing content out of
  `USB_UVM_Handoff` (the reference environment) as if it were a primary
  source. CLAUDE.md's "No Golden-Reference Content Mining" rule is
  prompt-only — no gate enforces it.
- **B2**: The USB-specific skill chain (`usb-profile`, `usb-vip-lookup`,
  `usb-environment-builder`) is not wired into the automated engine graph
  (`main_graph.json`). Other protocols have the same profile/builder gap.
- **B3**: Three alternate USB "environment generation" skills
  (`usb-real-env-generator`, `usb-complete-env-generator`,
  `usb-production-builder`) are confirmed dead duplicates of
  `usb-environment-builder`, still sitting in live (non-`_deprecated`)
  directories where an agent could wander into them by mistake.
- **B4**: The persistent-relay remote execution scripts
  (`remote_hop.py`/`remote_relay.py`/`remote_exec.py`/`source_identity.py`)
  that CLAUDE.md and two SKILL.md files describe as implemented actually
  live outside the `v50` repo (`D:\DV\Task\DV_Agent_Harness_L5\`), are
  invisible to any gate, and BUILD/VERIFY stage evidence for
  compile/simulate claims is currently self-attested JSON with no
  independent proof a real remote execution occurred.

This spec closes all 4 gaps together, since they were all discovered in one
audit pass and are needed together before the first real USB generation
attempt. Full audit findings (all 290, not just these 4) are preserved in
this session's conversation history; only the 4 BLOCKING items are in scope
here — the ~65 IMPORTANT and ~213 MINOR findings are out of scope for this
plan (mostly dead/unwired skills for other protocols and SoC-composition
features irrelevant to a single-IP USB run).

## Global Constraints

- Every new/modified gate follows the existing `STAGE_GATES` contract in
  `dv_harness/gates.py`: `(gate_id, script_path_relative_to_tools_verification_flow,
  cli_flag_or_EvidenceFlag_tuple)`. Scripts print one JSON line
  (`{"status": "PASS"|"FAIL", ...}`) to stdout and exit 0 for PASS,
  non-zero for FAIL — never raise an uncaught exception for an ordinary
  fail case.
- Every new gate that verifies an agent-supplied file reference must
  independently check the file on the real filesystem — never trust a
  self-attested boolean, matching `manual_lookup_before_edit_gate.py`'s
  existing `_verify_evidence_refs()` pattern.
- No wildcard destructive commands; no hidden server access.
- Files relocated into `v50` (B4) must be synced to `industrial` and
  `PACKAGE` per the Methodology Consolidation Rule, using the explicit-file-
  list + real-content-diff-verification method already established in this
  project's session history (never a self-reported "synced" claim).
- `git mv` (not delete+recreate) for any file relocation, to preserve
  history.
- All 4 fixes must land with real regression tests exercising the actual
  production entrypoint (`run_stage()` / the gate script's own `main()` via
  subprocess), not just a unit test of an internal helper in isolation —
  per this project's own recurring "real-but-unwired" lesson.

## B3: Archive 3 dead USB skills (mechanical)

**Files to move** (matching the precedent set by
`docs/superpowers/plans/2026-08-31-protocol-generalization-gap-closing.md`'s
Task 1, which archived 21 similar dead duplicates):

- `git mv .claude/skills/REAL_ENV_GENERATION/usb-real-env-generator .claude/skills/_deprecated/REAL_ENV_GENERATION/usb-real-env-generator`
- `git mv .claude/skills/REAL_PROJECT_GENERATION/usb-complete-env-generator .claude/skills/_deprecated/REAL_PROJECT_GENERATION/usb-complete-env-generator`
- `git mv .claude/skills/UNIVERSAL_PROTOCOL/usb-production-builder .claude/skills/_deprecated/UNIVERSAL_PROTOCOL/usb-production-builder`

Each moved `SKILL.md` gets the same NOTICE header pattern already used by
the other 21 archived duplicates (see any file under
`.claude/skills/_deprecated/REAL_ENV_GENERATION/` for the existing wording
to copy): states it duplicates `usb-environment-builder`, is not referenced
by the registry, and was archived on this date.

No new code is needed: `dv_harness/skill_resolver.py`'s existing
`'_deprecated' not in p.relative_to(root).parts` filter (already covering
the prior 21) will automatically exclude these 3 once moved.
`dv_harness/signoff_export.py`'s and `dv_harness/stats_snapshot.py`'s
existing `_deprecated` exclusions cover them too.

**Test**: extend `dv_harness_tests/test_skill_resolver.py`'s existing
`test_deprecated_skills_are_excluded_from_index` to also assert these 3
new paths are excluded (parametrize, don't duplicate the test body).

## B1: `protocol_isolation_gate.py`

**New file**: `tools/verification_flow/protocol_isolation_gate.py`

**Registered in `dv_harness/gates.py`'s `STAGE_GATES["IMPLEMENT"]`**, added
after `manual_lookup_before_edit_gate` (same evidence-ref shape, so it can
reuse the same fenced evidence block an agent already produces for that
gate — this is a new gate id with its own script, not a modification of
`manual_lookup_before_edit_gate.py` itself, so the two gates can evolve
independently and a failure here is distinguishable from a
missing-evidence failure there):

```python
("protocol_isolation_gate", "protocol_isolation_gate.py", "--edit"),
```

**CLI contract** (`--edit <path-to-json>`): reads the SAME evidence JSON
shape `manual_lookup_before_edit_gate.py` already consumes (a dict whose
values are lists of `{"path": ..., "quote": ...}` refs under keys like
`vip_examples_evidence_refs`, `dut_rtl_evidence_refs`, etc. — read the
current `manual_lookup_before_edit_gate.py` for the exact key names before
implementing, since the plan-writing step must copy them verbatim, not
guess).

**Denylist**: a module-level tuple of reference-tree path fragments that
must never appear as a resolved evidence-ref path:

```python
FORBIDDEN_REFERENCE_TREES = ("USB_UVM_Handoff",)
```

(a tuple, not a single string, so future protocols' reference environments
can be added without restructuring the check).

**Logic**: for every `{"path": ..., "quote": ...}` ref found in any list
value of the evidence dict, resolve `path` to an absolute path
(`pathlib.Path(ref["path"]).resolve()`) and check whether any element of
`FORBIDDEN_REFERENCE_TREES` appears as a path component (use
`.parts`, not a substring match on the string form, so a coincidental
substring match like a file named `my_USB_UVM_Handoff_notes.md` in an
unrelated directory doesn't false-positive — check that the forbidden name
is a whole path segment). On the first match, print
`{"status": "FAIL", "reason": "REFERENCE_TREE_CITATION_FORBIDDEN", "path": ..., "forbidden_tree": ...}`
and exit 2. If no evidence refs are present at all, this gate does not
apply (`PASS` — absence-of-content is `manual_lookup_before_edit_gate`'s
concern, not this one's) — this gate only ever produces a FAIL when a
forbidden citation is actually found, never when evidence is merely
missing.

**Test**: `dv_harness_tests/test_protocol_isolation_gate.py` — a fixture
with a fake `USB_UVM_Handoff` directory and a fake real VIP-manual
directory; assert FAIL when an evidence ref resolves into the fake
`USB_UVM_Handoff` tree, PASS when it resolves into the fake VIP-manual
tree or when the tree name only appears as a substring of an unrelated
filename (not a full path segment). Also add an `IMPLEMENT`-stage
`run_stage()` integration test (in
`dv_harness_tests/test_engine_gates_and_routing.py`, following that file's
existing pattern for other IMPLEMENT gates) proving a real forbidden
citation blocks the stage end-to-end, not just the standalone script.

## B2: Generalized profile/vip-lookup binding

**Registry schema change**: `.dv-harness/builder/protocol_builder_registry.json`'s
`protocols` dict currently has, per protocol, `display_name`, `skill`
(the builder skill), `discover`, `build`. Add two new fields to every
protocol entry:

- `profile_skill` (string, required for every protocol) — the real skill
  directory name for that protocol's profile skill. Before implementing,
  enumerate the real files (`Glob '.claude/skills/**/​*-profile/SKILL.md'`
  plus USB's non-conforming pair) and fill this in per-protocol from what
  actually exists — do not assume a naming convention, several protocols
  break it (e.g. MIPI CSI-2's real skill directory is `csi2-profile`, not
  `mipi-csi-profile`; confirm every mapping against the real directory
  listing at implementation time, not against this spec's own paraphrase
  of it).
- `vip_lookup_skill` (string, optional, `null` where absent) — currently
  only USB has one (`usb-vip-lookup`); every other protocol entry gets
  `null` explicitly (present-but-null, not simply omitted, so a consumer
  can distinguish "checked, none exists" from "field never added").

**`protocol-router`'s SKILL.md** (`.claude/skills/CORE/protocol-router/SKILL.md`):
add an instruction that after detecting the protocol, the agent must read
`protocol_builder_registry.json`, resolve `profile_skill` (and
`vip_lookup_skill` if non-null) for the detected protocol, and actually
invoke/read those skills before proceeding — recording which skills were
consulted in the DISCOVERY/PROTOCOL_CAPABILITY stage evidence block under a
new key `profile_skills_consulted: [<skill-name>, ...]`.

**New gate**: `tools/verification_flow/protocol_profile_binding_gate.py`,
registered in `STAGE_GATES["PROTOCOL_CAPABILITY"]` (alongside the existing
`protocol_generator_binding_gate` etc.):

```python
("protocol_profile_binding_gate", "protocol_profile_binding_gate.py", "--binding"),
```

**Logic**: reads the same evidence shape `protocol_generator_binding_gate.py`
already consumes (a `protocols` list of per-protocol dicts) plus the new
`profile_skills_consulted` list; for each named protocol, loads
`protocol_builder_registry.json` (real file, not agent-supplied) to get
that protocol's real `profile_skill`/`vip_lookup_skill`, and FAILs
(`reason: "PROFILE_SKILL_NOT_CONSULTED"`) if the registry's `profile_skill`
(or `vip_lookup_skill`, when non-null) is missing from
`profile_skills_consulted`. This is a harness-supplied cross-check (the
registry lookup), not a self-attested claim — matching this project's
`ContextFlag` pattern of never trusting an agent for a truth the harness
can look up directly.

**Test**: `dv_harness_tests/test_protocol_profile_binding_gate.py` —
assert PASS when `profile_skills_consulted` includes the real registry
value for a given protocol, FAIL when it's missing, and a case exercising
`vip_lookup_skill: null` (must not require consultation of a skill that
doesn't exist).

## B4: Relocate remote execution scripts + provenance gate

**File relocation** (`git mv` is not usable across the two separate repos
— these files currently live in a directory with no shared git history
with `v50` — so this is a plain copy, followed by deleting the old copies
only after the new location is verified working, per Global Constraints'
content-diff-verification requirement):

- `D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py` → `v50/tools/remote/remote_hop.py`
- `D:\DV\Task\DV_Agent_Harness_L5\remote_relay.py` → `v50/tools/remote/remote_relay.py`
- `D:\DV\Task\DV_Agent_Harness_L5\remote_exec.py` → `v50/tools/remote/remote_exec.py`
- `D:\DV\Task\DV_Agent_Harness_L5\source_identity.py` → `v50/tools/remote/source_identity.py`
- `D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_relay.py` → `v50/dv_harness_tests/test_remote_relay.py`
- `D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_exec.py` → `v50/dv_harness_tests/test_remote_exec.py`
- `D:\DV\Task\DV_Agent_Harness_L5\tests\test_source_identity.py` → `v50/dv_harness_tests/test_source_identity.py`

Internal imports in the relocated scripts (`from remote_hop import Session, _setup_reminder`)
and in the relocated tests (`sys.path.insert(0, str(ROOT))` where `ROOT` is
computed as `Path(__file__).resolve().parents[1]`) must be checked against
the new relative location (`tools/remote/` is now 2 levels under repo
root instead of at repo root) and corrected so the existing 43 tests still
pass unchanged in behavior. Do not change `remote_relay.py`'s 4-layer
credential-boundary logic itself (`running_inside_ai_agent()`,
`is_credential_inspection_command()`, the loopback bind assertion) — only
its location and import paths.

After the new location's full test suite passes, delete the old top-level
copies (both `D:\DV\Task\DV_Agent_Harness_L5\*.py` originals and the
`PACKAGE/` mirrors of them, since `PACKAGE/remote_*.py` currently mirror
the OLD location and must instead mirror the new one at
`PACKAGE/tools/remote/`) — do not leave two live copies of the same
credential-boundary-critical script; a stale duplicate is a real security
liability (an agent or human could accidentally invoke the un-updated old
copy).

**New gate**: `tools/verification_flow/remote_execution_provenance_gate.py`,
registered in both `STAGE_GATES["BUILD"]` and `STAGE_GATES["VERIFY"]`:

```python
("remote_execution_provenance_gate", "remote_execution_provenance_gate.py", "--provenance"),
```

**CLI contract** (`--provenance <path-to-json>`): evidence dict with
`transcript_path` (a real file path — the captured stdout of a real
`remote_exec.py` invocation) and `claimed_exit_code` (int).

**Logic**: reads `transcript_path` off the real filesystem (FAIL
`TRANSCRIPT_FILE_NOT_FOUND` if missing/unreadable). Parses the file's
content for `remote_exec.py`'s actual structured output markers — read the
real current `remote_exec.py` (in its new `v50/tools/remote/` location)
for its exact print format before implementing this parser, since the
exact field names/format must be copied verbatim, not guessed. At minimum
this gate must verify: (a) a `REMOTE_HOST=` line is present and non-empty,
(b) an `EXIT_CODE=` line is present and parses as an integer, (c) that
parsed exit code equals `claimed_exit_code` (FAIL
`EXIT_CODE_MISMATCH` otherwise — this is the check that makes the
evidence non-self-attested: an agent cannot claim success while the real
transcript shows a non-zero exit), (d) a `STATUS=` line is present. If all
present and consistent, PASS.

**Test**: `dv_harness_tests/test_remote_execution_provenance_gate.py` —
fixture transcript files: one with a real-shaped PASS block, one with a
mismatched exit code, one with a missing marker line, one with a
nonexistent path. Plus a `run_stage()` integration test for both BUILD and
VERIFY proving a mismatched-exit-code transcript blocks the stage.

**Documentation correction**: `CLAUDE.md`'s "Remote Linux Execution
(Persistent Relay)" section and
`.claude/skills/CORE/remote-linux-execution-bridge/SKILL.md`'s "Persistent
Relay" section currently describe these 4 files as already implemented
"at the project root next to `remote_hop.py`" (i.e. the `v50` project
root) — correct the stated location to `tools/remote/` and add one line
noting `remote_execution_provenance_gate.py` now independently verifies a
transcript rather than trusting self-attested BUILD/VERIFY evidence.

## Testing Strategy Summary

Every one of the 4 gaps gets: (1) a standalone script/unit test exercising
the new/modified file directly, and (2) a `run_stage()`-level integration
test proving the real production entrypoint enforces it end-to-end — per
this project's own repeated "real-but-unwired" lesson, a unit test alone
is not sufficient evidence of wiring. The full `dv_harness_tests/` suite
must pass (currently 1043 tests) after all 4 gaps are closed, plus the
new tests this spec adds.

## Out of Scope

- The other 65 IMPORTANT and ~213 MINOR findings from the same audit pass
  (dead skills for other protocols, SoC-composition features, corner-case
  taxonomy wiring, etc.) — not blocking for a single-IP USB run, tracked
  only in this session's conversation history for now.
- Building a real evidence producer for `environment_mode_selection`
  (already ruled out of scope in the prior plan's Ruling 5 for the same
  reason: new-feature-sized design work, not a bounded fix).
- Any change to `remote_relay.py`'s own 4-layer credential-boundary
  mechanism — this spec only relocates and re-wires around it.
