# GAP-V2-002 Remediation — Implementation Report

`CAP-M6-GAPV2002-001`. Executed under `DEC-GAP-V2-002 = OPTION_B` (approved):
`tools/generate_protocol_uvm_environment.py` reclassified
`INTERNAL_GENERATION_PRIMITIVE`; all 11 `.claude/skills/PROTOCOL_BUILDERS/
*/SKILL.md` converge on the Canonical governed lifecycle, preserving their
existing protocol-specific discovery expertise while promoting the real,
derived generic fields (`protocol`, `role`) into machine-readable
Canonical `FieldControl`s.

```
GENERATE_PROTOCOL_TOOL_ROLE = INTERNAL_GENERATION_PRIMITIVE

START_HEAD = 3b70feb627848061942238503827fae366490d33
END_HEAD   = 4f0b5b24ca2d10b99c0a8def5381b379436f4d9b
```

## Field derivation (not assumed)

Full derivation: `GAP_V2_002_FIELD_CONTROL_DERIVATION.md`. Investigated at
minimum, per the dispatch's own instruction: `protocol`, `verification_
level`, `role`, `mode`, `topology`, `phy_boundary`.

```
protocol           EXISTING_CANONICAL_FIELD          (CAP-M6-C1-001)
role               NEW_GENERIC_CANONICAL_FIELD        (this task)
mode               PROTOCOL_SPECIFIC_EXTENSION        (not governed here)
topology           PROTOCOL_SPECIFIC_EXTENSION        (not governed here)
phy_boundary       EXISTING_CANONICAL_FIELD, but consumed by a different
                    tool (bind_mechanism_generator.py) -- not this one
verification_level EXISTING_CANONICAL_FIELD (lifecycle._FACT_KEYS), but
                    deliberately NOT built into a FieldControl this task
                    (CAP-M5M6-VLEVEL-001's own separate scope)
```

Real evidence for `role`: `dv_harness/uvm_generator/generator.py:431`
(`m.get('role', 'UNKNOWN')`, actually consumed, reused unchanged by
`ProtocolEnvGenerator`), present under some name in all 11 skills' own
"Discover Before Generate" list.

## Fix / integrate

- `dv_harness/generation_field_controls.py`: added `ROLE_FIELD_ID`,
  `role_field_control()`, `declared_role_value()`,
  `role_evidence_producers()` -- same shape as the existing `protocol`
  functions, zero new field-value types, reusing `FieldControl`/
  `EvidenceProducer`/`Candidate`/`SourceKind`/`Confidence` from
  `intake_field_resolution.py` verbatim (unchanged, again).
- `dv_harness/lifecycle.py`: added `"role"` to `_FACT_KEYS` (one line,
  same convention as the existing `"protocols"` entry).
- `dv_harness/engine.py`: `start_lifecycle()` gained a `role: Optional[str]
  = None` parameter; the generation field-controls block generalized from
  a single hardcoded `protocol` branch to a `field_id -> (declared,
  producers)` map covering both `protocol` and `role`, added to the
  resolution loop only when `generation_request is not None` (unchanged
  opt-in discipline from `CAP-M6-C1-001`); both fields persist to
  lifecycle facts once resolved; the generation-dispatch tail resolves
  `effective_role` the same way it already resolved `effective_protocol`
  (including the RESUME-call fallback to a prior lifecycle fact), and
  substitutes both into `request["protocol"]`/`request["role"]` before
  calling `create_environment()`. The CREATE-branch fact assembly also
  gained `if role is not None: facts["role"] = role`, mirroring
  `protocols`' own existing (pre-existing, not new) direct-declare
  persistence path -- found missing during this task's own test-first
  pass (a directly-declared `role` with no `generation_request` was
  silently dropped before this fix).
- Exception handling enriched: every one of `create_environment()`'s own
  10 real exception classes follows one repo-wide `(reason, detail)`
  convention (confirmed by direct read of all 10 class definitions) --
  `start_lifecycle()`'s except block now surfaces `exc.reason`/
  `exc.detail` generically into `AgentResult.raw["status"]`/`["detail"]`,
  so the CLI/dashboard JSON envelope carries the same information the
  standalone script's own JSON output always did.
- `dv_harness/cli.py`: `start` gained `--dut-role` (named to avoid
  colliding with the pre-existing `--role`, the human's own UX
  job-function flag -- a real naming conflict found and resolved during
  implementation, not assumed absent) and now prints a structured JSON
  envelope (status/environment_mode/generated_files/out/
  environment_mode_decision/protocol_model/structural_lint, or
  status/detail on failure) for `--generate` calls, matching the legacy
  script's own stdout contract field-for-field; the UX status banner is
  suppressed for `--generate` calls so the JSON stays the only thing on
  stdout, parseable without a prefix-skip.
- `dv_harness/dashboard.py`: `_start_background_run()` and `/api/start`'s
  JSON body both gained the same additive `role` field, mirroring
  `protocols`.
- `tools/generate_protocol_uvm_environment.py`: own header rewritten to
  state `INTERNAL_GENERATION_PRIMITIVE` and the two real reasons it
  remains reachable (the 2 subprocess-level regression tests; genuinely
  lifecycle-free low-level/CI use). Its own generation LOGIC (every line
  below the header) is completely unmodified -- confirmed unchanged by
  `test_protocol_env_generator.py`/`test_system_level_soc_composition_
  wiring.py` both still passing byte-for-byte.
- `CLAUDE.md`: corrected the now-stale "the one official CREATE
  ENVIRONMENT entry point... the script all ten
  `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invoke" claim (also fixed
  a stale count -- eleven skills exist, not ten) and added a GAP-V2-002
  status paragraph naming the new governed entry point.
- All 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md`: "Generate /
  Integrate" section's own invocation line replaced with the governed
  `dv-harness start --goal "<goal>" --protocols <protocol> --dut-role
  <role> --generate --generate-out <dir> --generate-manifest <m.json>`
  call. Two skills needed a second, protocol-specific edit beyond the
  shared line (`pcie`'s own LTSSM-layering sentence, `amba4-soc`'s own
  fabric-layering sentence) -- both updated to reference the same governed
  invocation rather than the standalone script, found by reading each
  file in full rather than assuming the shared line was the only one.

## Architecture direction preserved (no inversion, no recursion)

```
User / Agent -> PROTOCOL_BUILDER -> Protocol-specific Discovery -> Evidence
  -> Canonical FieldControls -> start_lifecycle() -> Field Resolution
  -> Clarification / HumanGate when required -> EffectiveValues -> Dispatch
  -> generation primitive -> create_environment()
```

Confirmed, not assumed: `test_gap_v2_002_protocol_builder_convergence.py::
test_create_environment_real_caller_set_is_exactly_the_two_known_ones`
walks the real AST of every `.py` file in the repository and finds
exactly 2 real call sites for `create_environment(` -- `dv_harness/
engine.py` (the governed path) and `tools/generate_protocol_uvm_
environment.py` (the internal primitive, calling it for itself, never
calling back into `start_lifecycle()`). No protocol-specific Intake
engine, no protocol-specific Field Resolution engine, no second lifecycle
orchestrator, no lifecycle recursion.

## Caller classification (all 13 real callers)

| # | Caller | Classification |
|---|---|---|
| 1-11 | `.claude/skills/PROTOCOL_BUILDERS/{amba4-soc,canfd,edp,emmc,ethernet,mipi-csi,mipi-dsi,pcie,sd,ucie,usb}-environment-builder/SKILL.md` | `MIGRATE_TO_GOVERNED_LIFECYCLE` (done -- all 11 now invoke `dv-harness start --generate`) |
| 12 | `dv_harness_tests/test_protocol_env_generator.py` | `TEST_ONLY` (subprocess-level regression test of the internal primitive itself -- correctly unchanged) |
| 13 | `dv_harness_tests/test_system_level_soc_composition_wiring.py` | `TEST_ONLY` (same) |

`AUTHORIZED_LOW_LEVEL_CALLER` and `SUPERSEDED`: 0 callers in either
category -- no caller needed a scoped bypass declaration, and nothing was
retired.

```
UNKNOWN_RUNTIME_CALLERS = 0
UNCONTROLLED_BYPASSES = 0
```

## Correctness closure

```
ROOT_CAUSE_COMPLETE = YES
FIX_COMPLETE = YES
CALLERS_VALIDATED = YES  (all 13 traced and classified; AST-based
  regression test keeps this true going forward, not just at this
  task's own moment)
FIELD_CONTROLS_VALIDATED = YES  (derived from real evidence, not assumed
  -- see GAP_V2_002_FIELD_CONTROL_DERIVATION.md; 6-category classification
  applied to every field investigated, not only the 2 governed)
WIRING_VALIDATED = YES
PRODUCTION_DATAFLOW_VALIDATED = YES  (the CLI's own JSON-envelope test,
  test_cli_start_generate_prints_a_structured_json_envelope_matching_the_
  legacy_script, proves a migrated caller's own JSON-parsing behavior is
  preserved, not merely that start_lifecycle() was called)
HITL_VALIDATED = YES  (role's own QuestionOwner/HumanGate/answer-loop
  tested independently of protocol's, including the "only one field
  answered still blocks on the other" case)
EVIDENCE_VALIDATED = YES
E2E_VALIDATED = YES  (test_generation_dispatch_calls_create_environment_
  directly_never_recurses re-run with both fields declared)
REGRESSION_VALIDATED = YES  (see Regression section below)
```

`CAPABILITY_ISLAND = NO` for the protocol/role generation edge, now for
every one of the 13 real callers, not only CLI/dashboard.

## Regression

```
python -m pytest <47 dispatch-caller files> + 14 directly-touched-module
  files (the CAP-M6-C1-001/V2 population + test_gap_v2_002_protocol_
  builder_convergence.py, new) -v
=> 5 failed, 1524 passed, 11 skipped in 1135.25s (0:18:55)
```

All 5 failures byte-identical, by test ID, to the same 5 already-classified
`PRE_EXISTING` failures re-confirmed unchanged across every M6 regression
this session (`test_question_queue_digest_auto_trigger.py`,
`test_resource_cost_autonomy.py::test_3b_...`, and 3 in `test_waveform_
dump_scope_human_confirmation.py`) -- none of the 5 failing files touch
`generation_field_controls.py`, `lifecycle.py`, `engine.py`'s
`start_lifecycle()`, `cli.py`'s `start` command, `dashboard.py`, or any
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md`. `REGRESSION_CAUSED_BY_
REMEDIATION = 0`, `UNKNOWN_REGRESSION_FAILURES = 0`.

## Governance gates

```
dv_harness.constitution_gate.check_constitution_intact('.')
  => ConstitutionCheckResult(status='PASS', reasons=[])
```

All 5 frozen sources (Parent/v50/b7a/b7b/b8) re-verified unchanged
immediately before this report's own commit:

```
Parent (D:\DV\Task\DV_Agent_Harness_L5) = 3e9dd7360f584078ed8f4b04120c9844acabd97b  UNCHANGED
v50    (D:\DV\Task\DV_Agent_Harness_L5\v50)                                        = f3fd17326cf3654aca6fd83fad991a3f247e6682  UNCHANGED
b7a    (D:/wt/b7a) = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5  UNCHANGED
b7b    (D:/wt/b7b) = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b  UNCHANGED
b8     (D:/wt/b8)  = c9cdd06ce586d44f4c0cef00310c10f95ea59f93  UNCHANGED
```

## Recomputed metrics (post-remediation)

```
STRUCTURAL_CONNECTED_STAGES = 8    (unchanged)
PRODUCTION_CONNECTED_STAGES = 8    (unchanged count; same 8 stages now
  reachable from 13 real production/internal-primitive-test callers
  instead of 2)
CAPABILITY_ISLANDS (generation edge) = 0   (was 1 before this task)
CURRENT_SCOPE_GAPS_OPEN = 0   (GAP-V2-002 was the only OPEN current-scope
  gap after the V2 adoption task; now CLOSED. GAP-V2-003 is DEFERRED,
  future scope, correctly excluded from this count)
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 3   (unchanged -- this task
  touched no P0 capability row; {CAP-CE-018, CAP-M5M6-VLEVEL-001,
  CAP-M8-EXPLOOP-001})
```

## STOP

Per this dispatch's own explicit condition: `CURRENT_SCOPE_GAPS_OPEN = 0`
for the current pre-VLEVEL Golden Workflow scope, so
`NEXT_RECOMMENDED_GATE = CAP-M5M6-VLEVEL-001` is now reported. **This
report names the gate; it does not start it** -- `CAP-M5M6-VLEVEL-001`
remains not auto-started, per this dispatch's own explicit instruction.
Waiting for a separate, explicit dispatch to begin it.
