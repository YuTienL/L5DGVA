# vPlan 4th validation rule: constraint-items-exist-in-SV-source (2026-09-01)

## Summary

Implemented the previously-flagged-but-not-yet-implemented 4th vPlan
validation rule from `.claude/agents/IP_UVM_DV_Gen.md`'s "The vPlan" section
(added 2026-09-01): "every `constraint items` entry names a constraint that
actually exists in the written SV source." This closes the gap explicitly
noted as out-of-scope in `.work/vplan-doc-and-wiring-fix-report.md`'s "Open
follow-ups" section from earlier this same session.

Note on doc location: the task pointed at
`.claude/reference/IP_UVM_DV_Gen.md`, but that 787-line file's own "The
vPlan" section only ever described the 3 mandatory rules and carries no
2026-09-01 dated note. The actual 4th-rule text (verified verbatim) lives in
`.claude/agents/IP_UVM_DV_Gen.md` (2548 lines) at its own "The vPlan"
section, dated 2026-09-01 exactly as the task described. Treated the task's
path as referring to that real doc location rather than stall on the
mismatch.

## What was built

`dv_harness/vplan_writer/writer.py`:
- New typed error `ConstraintNotInSVSourceError` (reason
  `CONSTRAINT_NOT_IN_SV_SOURCE`, detail `{req_id, constraint_name,
  constraint_declaration_sources}`), following the exact `.reason`/`.detail`
  convention of the other three evidence errors.
- `VPlanEvidenceContext` gained an optional 4th ground-truth set,
  `sv_constraint_names: Optional[FrozenSet[str]] = None`, plus a
  `constraint_declaration_sources: Tuple[str, ...] = ()` provenance field --
  both additive fields with defaults, so any existing constructed
  `VPlanEvidenceContext` (e.g. hand-built in a test) keeps working unchanged.
- `build_evidence_context()` gained three new optional kwargs:
  `constraint_declaration_sources`, `constraint_declaration_regex` (default
  ``r'\bconstraint\s+(?P<constraint>[A-Za-z0-9_]+)\b'``), and
  `known_constraint_names` -- mirroring `task_declaration_sources`/
  `task_declaration_regex`/`known_task_names`'s scan-vs-bypass shape exactly.
  Neither supplied -> `sv_constraint_names` stays `None`. Either supplied but
  the scan/bypass yields an empty set -> `EvidenceSourceEmptyError`
  (`which="sv_constraint_names"`), same fail-closed discipline as the three
  mandatory sets.
- `_validate_item_evidence()` now checks, only when
  `evidence.sv_constraint_names is not None`, that every entry in an item's
  `constraint_items` is in that set; raises `ConstraintNotInSVSourceError`
  on the first mismatch.
- Updated `validate_items()`'s ordering docstring and the module header
  docstring accordingly; fixed the stale "3 REQUIRED validation rules"
  wording in the header docstring.

`dv_harness/vplan_writer/__init__.py`: exports `ConstraintNotInSVSourceError`.

`dv_harness/cli.py` (`vplan-export` subcommand): added
`--constraint-declaration-source` (repeatable), `--constraint-declaration-regex`,
and `--known-constraint-name` (repeatable) flags, wired straight into
`build_evidence_context()`; added `ConstraintNotInSVSourceError` to the
caught-and-reported typed-error tuple. Verified via `--help` that the new
flags render correctly and via a live CLI run in the new tests.

`tools/vplan/vplan_writer_validation_gate.py`: this **did** need updating.
Added `ConstraintNotInSVSourceError` to the imported/caught typed-error
tuple, added `constraint_declaration_regex` to the optional-kwargs list, and
added `constraint_declaration_sources`/`known_constraint_names` passthrough
in the evidence-kwargs dict built from the JSON payload -- same
uninvented-schema discipline as the rest of the file (these are
`build_evidence_context()`'s own kwarg names, nothing new coined here).
Updated the file's header comment with a dated `UPDATED (2026-09-01,
vplan-4th-rule-implementation)` note explaining the change, matching the
file's existing `NEW (...)` convention.

Documentation kept in sync: `.claude/agents/IP_UVM_DV_Gen.md` (new dated
`BUG FIX` note, corrected the stale "3 REQUIRED validation rules above" cross-
reference to "3 mandatory validation rules", added the new CLI flags to the
concrete invocation block) and `.claude/skills/CORE/ip-uvm-dv-gen/SKILL.md`
(new dated `BUG FIX` note, corrected its own stale "3 REQUIRED"/"3 rules"
wording). `dv_harness/prompts.py`'s `STAGE_INSTRUCTIONS[Stage.VPLAN.value]`
evidence-block example was extended with the optional
`constraint_declaration_sources` field and a short note that it is optional
and additive, so an agent following the prompt knows the new field exists
without being forced to supply it.

## Ruling (also recorded in the commit message and in both doc files)

**RULING: the 4th rule is implemented as an OPTIONAL, evidence-gated check
(evidence.sv_constraint_names defaults to `None`, meaning "not requested,
skip"), mirroring the existing `known_check_names`/`UnknownCheckerNameError`
precedent already in this module -- not as an unconditionally mandatory
check like the other three.**

Why: the doc text lists it alongside the 3 mandatory rules with no
"optional" qualifier, and a maximally faithful reading would make it always
enforced. But CLAUDE.md's engineering discipline explicitly requires
"additive/backward-compatible changes that produce byte-identical output
when a new key/field is absent," and every existing caller of this module
(the `dv-harness vplan-export` CLI's existing invocations, every existing
`STAGE_GATES['VPLAN']` JSON payload shape, every existing test fixture in
`test_vplan_writer.py` and `test_vplan_writer_validation_gate.py`, and
`test_engine_gates_and_routing.py`'s `VPLAN` fixture) supplies zero SV
constraint-declaration evidence today. Making the check unconditional would
turn every one of those into an immediate, unrequested
`EvidenceSourceEmptyError`/`ConstraintNotInSVSourceError` failure the moment
this change landed -- a real regression, not a byte-identical extension.
The module already has a precedent for exactly this shape of problem
(`known_check_names`), so extending that same shape to the 4th rule is the
minimal, most consistent way to add real teeth to the check without breaking
every existing caller. When a caller *does* supply the evidence (new tests
and the new CLI flags exercise this), the check is fully strict and
fail-closed, identical in spirit to the three mandatory rules.

A secondary, smaller ruling: the constraint evidence is built by **scanning
real SV source text** for `constraint <name>` declarations (mirroring how
`declared_tasks` scans for `task automatic <name>`/`class <name> extends`),
not by accepting an externally-supplied manifest as the only option --
because the doc explicitly says "the written SV source," which is a
source-code-truth claim, not a manifest-truth claim (unlike
`known_check_names`, which is explicitly described as typically coming from
a `scoreboard_rules[]` manifest). `known_constraint_names` is offered too,
purely as a bypass-scanning convenience for callers that already have the
name set in hand (test fixtures, non-file-based sources), exactly paralleling
`known_task_names`'s existing role for `declared_tasks`.

## Tests

Added to `dv_harness_tests/test_vplan_writer.py`:
- `_make_fake_env_with_constraints()` fixture helper: real SV file declaring
  `constraint c_bulk_len`/`constraint c_isoc_payload` (the exact names
  `_realistic_items()` already uses), reusing the existing fake-environment
  convention.
- `TestConstraintNotInSVSourceRule` (7 tests): skipped when no evidence
  supplied; passes on a real declared constraint; raises the typed error on
  an unknown constraint; `write_vplan_workbook` refuses (no file written) on
  mismatch; `write_vplan_workbook` succeeds end-to-end with real constraint
  evidence; `known_constraint_names` bypasses scanning (both its pass and
  fail paths); `constraint_declaration_sources` yielding zero constraints
  raises `EvidenceSourceEmptyError` (`which="sv_constraint_names"`).
- 2 new CLI tests in `TestCliVplanExport`: `--constraint-declaration-source`
  passes with a real constraint; reports `ConstraintNotInSVSourceError` (and
  writes no file) on an unknown one.

Added to `dv_harness_tests/test_vplan_writer_validation_gate.py`:
- `_add_constraint_declarations()` fixture helper.
- 4 new tests: PASS with real constraint evidence supplied; FAIL
  (`CONSTRAINT_NOT_IN_SV_SOURCE`, exit 3) on an unknown constraint;
  rule skipped (PASS) when the payload supplies no constraint evidence at
  all, even for an obviously-fake constraint name; `known_constraint_names`
  passthrough in the JSON payload bypasses scanning.

## Test results

```
python -m pytest dv_harness_tests/test_vplan_writer.py \
  dv_harness_tests/test_vplan_writer_validation_gate.py -q
........................................                                 [100%]
40 passed in 32.12s

python -m pytest dv_harness_tests/test_engine_gates_and_routing.py \
  dv_harness_tests/test_hard_gate_script_smoke.py -q
........................................................................ [ 19%]
........................................................................ [ 39%]
........................................................................ [ 59%]
........................................................................ [ 79%]
........................................................................ [ 99%]
...                                                                      [100%]
363 passed in 304.40s (0:05:04)
```

All 403 tests across the four directly-relevant suites pass; zero
regressions in `test_engine_gates_and_routing.py`'s existing VPLAN gate
fixture or `test_hard_gate_script_smoke.py` (both untouched by this change,
confirming the new evidence fields really are additive/optional). No
pre-existing bug was found during this pass (unlike the prior
`vplan-doc-and-wiring-fix` session, which had one).

## Files changed

- `dv_harness/vplan_writer/writer.py`
- `dv_harness/vplan_writer/__init__.py`
- `dv_harness/cli.py`
- `tools/vplan/vplan_writer_validation_gate.py`
- `dv_harness/prompts.py`
- `.claude/agents/IP_UVM_DV_Gen.md`
- `.claude/skills/CORE/ip-uvm-dv-gen/SKILL.md`
- `dv_harness_tests/test_vplan_writer.py`
- `dv_harness_tests/test_vplan_writer_validation_gate.py`

`.dv-harness/events.jsonl` also shows as modified (append-only event log
touched incidentally by running the CLI/tests) -- left uncommitted, same
convention as the prior `vplan-doc-and-wiring-fix` pass.

`dv_harness/gates.py` needed **no** change: `STAGE_GATES['VPLAN']` already
wires `tools/vplan/vplan_writer_validation_gate.py` by script path and
`--vplan-validation` flag name only; the gate's JSON payload schema is
internal to the script and grew additively (new optional keys), so the
wiring itself is untouched.

## Residual gaps / concerns

None blocking. One documentation-only follow-up worth flagging for
awareness (not introduced by this pass, and not a code gap): the 4th rule's
"real SV source" scan uses the same lightweight regex-text-scan discipline
as the existing `declared_tasks` scan (not a real SystemVerilog parser), so
a constraint declared inside a disabled ``ifdef`` block or a commented-out
region would still be treated as "existing" -- this is an accepted,
pre-existing limitation of the whole evidence-by-citation approach in this
module (identical limitation already exists for `dispatcher_patterns`/
`declared_tasks`), not something unique to this new rule, and matches the
module's own stated design ("regex text scan... not a full SV parser").
