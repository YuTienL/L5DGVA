# Gap-close report — asset-processing table, the 4 key judgments

Scope: PHY-decides-bind · register-file division of labour · command.txt
authority · VIP-source symbol-indexing.
Working directory: `D:\DV\Task\DV_Agent_Harness_L5\v50`. Branch `master`.

## Result: **DONE** (2 gaps closed for real) + 1 **NEEDS_SEPARATE_EFFORT**

One-line test summary: **26 new tests in
`dv_harness_tests/test_four_key_judgments_enforcement.py`, all passing;
418 passing across the coupled suites** (four_key_judgments, bind_mechanism_generator,
run_profile, run_profile_to_justfile, makefile_to_run_profile,
asset_processing_artifacts, connectivity, cli_question_queue, context_budget).

---

## The audit finding was materially stale — verified, not assumed

Commit `fd04774` ("feat(assets): build the 7 missing asset-processing artifact
types + real consumers") landed at 02:33 on 2026-09-04, after the audit that
produced my input finding was gathered. It created `dv_harness/phy_boundary.py`
(511 lines), `sys_regmap.py`, `init_seq.py`, `vip_symbol_index.py`,
`design_intent.py`, five JSON Schemas, `.claudeignore`, and
`examples/asset_processing/`. So several verdicts I was handed were already
wrong by the time I read them. Re-verified state below.

What that commit did **not** do — and what this pass closes — is give the new
modules a **caller**. That is this repo's own most frequently repeated failure
mode (`connectivity.assert_t3_never_auto_accepted()` naming a "downstream
consumer" that did not exist; `connectivity.py` imported by nothing but
itself), and both remaining gaps were exactly it.

---

## Judgment 1 — PHY model decides bind location, not RTL naming

**Audit said BLOCKED. Re-verified: PARTIAL. Now: DONE.**

Already real (re-confirmed, not taken on trust):
- `dv_harness/phy_boundary.py:308` `decide_bind_location()`, `:481`
  `assert_bind_location_allowed()` — derives SERIAL/PARALLEL/MIXED/UNDECIDABLE
  from the real verible-parsed port table and refuses a non-bindable mount
  layer. Worked examples at `examples/asset_processing/generated/phy_boundary.json`
  and `phy_boundary_serial.json`.

The real remaining gap:
- `grep -rn "assert_bind_location_allowed"` across the repo returned **only
  its own definition and its own unit tests**. The only code path that
  actually writes a `bind` into a `.sv` file —
  `tools/generate_bind_mechanism.py` → `bind_mechanism_generator.emit_bind_sv()`
  → `validate_bind_entries()` (`bind_mechanism_generator.py:33` at HEAD) — ran
  the evidence check and `connectivity.enforce_bind_tier_policy()` and nothing
  else. A serial-lane bind was fully emittable.
- The tier gate cannot substitute, and this is the load-bearing point: a
  serial-lane target can be a clean **T1** structural match. Layer-correctness
  and path-correctness are independent properties, so they need independent
  gates. Test `test_a_serial_boundary_bind_is_refused_even_though_its_tier_is_t1`
  asserts exactly this — the same entry passes `validate_bind_entries()` with
  no boundary document and is refused with one.
- CLAUDE.md's `## Bind-Location Rules` still said "Four hard project rules",
  none of which stated the ordering.

Built:
- `bind_mechanism_generator.assert_phy_boundary_decided_first()`, run **before**
  the tier gate inside `validate_bind_entries()` — the ordering is itself the
  rule, so it is asserted directly
  (`test_the_layer_gate_runs_before_the_tier_gate`: an entry that is both at a
  refused layer and an unconfirmed T3 reports the layer problem, because
  getting a human to confirm the target would leave a silent monitor in place).
- `emit_bind_sv(..., phy_boundary_doc=, require_phy_boundary=)`;
  `tools/generate_bind_mechanism.py --phy-boundary / --require-phy-boundary`.
  End-to-end test drives the real tool as a subprocess and asserts **no `.sv`
  file is written**.
- Per-entry `phy_boundary_signals` catches the MIXED case a layer check alone
  passes (that document says `bindable: true`).
- A NOT_AVAILABLE extraction is refused, distinctly from `None`: `None` means
  "no PHY in scope", NOT_AVAILABLE means "there is a PHY question here and it
  was not answered".
- **CLAUDE.md Bind-Location Rule 5**, written as the ordering rule with the
  Gate-1-PASS/Gate-2-PASS/Gate-3-silent-monitor failure signature, the
  confirmed 2026-08-31 USB3-PIPE4 drift it comes from, and the honest
  `require_phy_boundary=False` residual. The section's own summary sentences
  ("These four rules are enforced by review", "unlike the four location rules
  above") were corrected rather than left contradicting the new rule.

**Disclosed residual**: `require_phy_boundary` defaults False, mirroring
`require_tier`. An IP-level DUT with no PHY sub-block genuinely has no boundary
to decide. Rule 5 is hard-enforced whenever a boundary is in scope and known,
not universally. Pinned by
`test_absent_boundary_doc_is_permitted_by_default_but_refused_under_require`
so it cannot drift silently in either direction.

## Judgment 2 — the two register files' division of labour

**Audit said BLOCKED. Re-verified: READY. No action taken.**

The audit's evidence is superseded. `dv_harness/init_seq.py:315`
`evaluate_zero_time_connectivity_gated()` runs the **real, unmodified** Gate 2
(`init_seq.py:49` imports `evaluate_zero_time_connectivity`, `GateResult`,
`GateStatus` from `connectivity.py` — one Gate 2, not a second one) alongside
`evaluate_gate2_preconditions()`, and returns an explicit `interpretation`:
`PRECONDITION_NOT_MET` when Gate 2 fails **and** the mode bits were never
written, `CONNECTIVITY_FAILURE` only when every verifiable mode bit is correct,
`INDETERMINATE` when the bits were not captured. That is precisely the
conflation the judgment warns about, undone. `sys_regmap.json` and
`init_seq.yaml` both exist with schemas and worked examples
(`examples/asset_processing/inputs/`), covered by
`dv_harness_tests/test_asset_processing_artifacts.py`.

## Judgment 3 — reference command.txt is the highest authority

**Audit said PARTIAL. Now: DONE for the bounded parts; the command.txt
extractor is NEEDS_SEPARATE_EFFORT.**

### (b) new-option → question-queue routing — **closed**

Confirmed the audit's finding still held: `grep question_queue
dv_harness/uvm_generator/` returned zero hits. The instruction lived in
`run_profile.py`'s docstring, `run_profile.schema.json`'s own `description`,
the generated justfile's banner and `docs/RUN_PROFILE.md` — and in no code.

Built in `run_profile_to_justfile.py`:
- `assert_option_modeled()` → `UnmodeledOptionError` (a subclass of
  `RunProfileValidationError`, so existing fail-closed handling catches it too).
- `build_missing_option_question_queue_entry()` — asks through the **same**
  `question_queue.QuestionQueueStore` that `connectivity.build_t4_question_queue_entry()`
  uses; one queue for this harness, not a second parallel one. Owner-routed via
  `route_owner("env")`, id-derived (regeneration does not mint a duplicate —
  `test_the_same_missing_option_asked_twice_mints_the_same_id`), and carrying
  `affects_pass_fail_verdict: True`, which classifies it Tier 3 CANNOT_ASSUME.
  That escalation is reasoned, not copied: a silently-added execution knob does
  not produce a visibly broken run, it produces a PASS that verified something
  other than what was intended. Open-ended option lists, a recommendation
  outside the options, and an already-modeled option are all refused.

### the profile itself, not the justfile — **closed** (the real hole)

The generated justfile already carried a "DO NOT hand-edit" banner and is
regenerated anyway. The file actually worth editing to smuggle in a knob is
`run_profile.json`, and it had **no** check: nothing distinguished a param the
extractor derived from the real source from one an agent typed in.

Built in `run_profile.py`:
- `untraceable_params()` / `assert_params_traceable_to_source()` — re-reads the
  real Makefile/command.txt and refuses any param name absent from it as a
  whole token. Deliberately a name-token check and nothing cleverer: parsing
  Make conditionals or SystemVerilog task bodies well enough to prove a param's
  *semantics* would be a second extractor, and a wrong one either rejects real
  params (which gets the check switched off) or accepts invented ones. A name
  absent from the authoritative source cannot have come from it, and that one
  claim is checkable with certainty. Whole-token matching is pinned by a test
  (`SPEED` must not be "found" inside `HIGH_SPEED_MODE`).
- `assert_source_unchanged()` — content-hash staleness. Silent when no hash was
  recorded: absence of a recorded hash is not evidence of a match, and
  inventing one would be the same sin this module refuses everywhere else.
- `run_profile_to_justfile.verify_source_authority()` runs both **before**
  `generate_and_write()` emits anything, plus a `verify-source` CLI subcommand
  (exit 0 VERIFIED / 1 violation / 3 NOT_AVAILABLE). A profile inspected away
  from its environment reports NOT_AVAILABLE and still generates — refusing
  there would be the false positive that gets the check routed around.
- Verified the check is satisfied by the profile the **real** extractor
  produces from the **real** template Makefile
  (`test_every_param_of_the_real_extractor_traces_to_the_real_makefile`): a
  traceability rule the sanctioned extractor itself fails is a rule that gets
  deleted.

### (a) `human_raw_override` — **closed as far as a justfile can close it**

Was restricted by a comment and nothing else, so at the point of invocation it
was indistinguishable from a modeled recipe. It now takes an `ack` parameter
ahead of the target and refuses anything but `HUMAN_OVERRIDE_ACK_TOKEN`
(`I-AM-A-HUMAN-BYPASSING-RUN-PROFILE`), with a refusal message naming the
question queue. Driven through the **real `just` binary** in a test (a
string-matched shell condition is not evidence that it fires), asserting both
that a wrong token is refused before `make` is reached and that the right token
passes through.

**Honest residual, stated in the code, the doc and the test**: an agent can
type that token. What is closed is a silent, deniable bypass — the token
appears verbatim in shell history and CI logs as an attributable claim. A
deliberate bypass cannot be closed from inside a justfile.

### (a) caveat 2 — the `command_txt` extractor: **NEEDS_SEPARATE_EFFORT**

`docs/RUN_PROFILE.md`'s own scope note is still accurate: the SoC-level
SystemVerilog-task `command.txt` format has no extractor, and building one
requires a real command.txt to write it against — none exists in this repo, and
guessing the format from the Makefile extractor is precisely what the
"No Golden-Reference Content Mining" rule forbids. Two things did improve
without it: the doc now states plainly that a `command_txt`-sourced profile is
**authored, not extracted**, and notes that
`assert_params_traceable_to_source()` reads whatever file `source.path` names,
so an authored profile is still checked against its real source even though
nothing yet derives it from one.

## Judgment 4 — VIP source handling must be careful

**Audit said BLOCKED/PARTIAL. Re-verified: READY. No action taken.**

- `.claudeignore` **exists** (70 lines, repo root). Extension-qualified
  patterns (`**/vip/**/*.sv`, `**/svt_*/**/*.sv`, `**/designware/**/*.sv`)
  rather than bare directory patterns, deliberately, so it cannot hide
  `.dv-harness/vault/03_Verification/VIP/`'s real markdown notes. Carve-outs
  for `Examples/` and `.f` filelists match `context_budget.policy.json`'s own
  allow-globs. `DESIGNWARE_HOME`/`VIP_HOME` are env-var-rooted external paths
  and are not expressible as gitignore-style globs; `**/designware/**` and
  `**/svt_*/**` are the structural equivalent and are what actually matches.
- `dv_harness/vip_symbol_index.py` is a real generated index, protocol-agnostic
  (`build_symbol_index(roots, protocol)` takes the protocol from the caller and
  never infers it from a directory name), with
  `assert_no_bodies_retained()` (`:255`) making "declarations and `file:line`
  only, never bodies" a **checkable invariant** — which is what makes indexing
  a tier-1-denied tree legitimate. It renders the tier-3
  `docs/vip_ref/<protocol>.md`. Worked output at
  `examples/asset_processing/generated/vip_symbol_index.json` and `vip_ref/`.

## Verification

- New: `dv_harness_tests/test_four_key_judgments_enforcement.py` — 26 tests,
  **26 passed**, zero skipped (the `just`-binary test really ran; `just` is
  installed here).
- Coupled suites: **418 passed** — `test_four_key_judgments_enforcement.py`,
  `test_bind_mechanism_generator.py`, `test_run_profile_to_justfile.py`,
  `test_run_profile.py`, `test_makefile_to_run_profile.py`,
  `test_asset_processing_artifacts.py`, `test_connectivity.py`,
  `test_cli_question_queue.py`, `test_context_budget.py`.
- One pre-existing test updated, not weakened:
  `test_generate_justfile_has_human_override_escape_hatch` now asserts the
  `ack`-parameter form and the token's presence.

### A concurrent-workflow hang, isolated and excluded

`dv_harness_tests/test_engine_gates_and_routing.py::test_run_stage_appends_real_coverage_history_sample_on_coverage_closure_pass`
**hangs in the current working tree**. It is not mine, and this was proven
rather than asserted:

1. `git archive HEAD` into a scratch export → the test **passes in 42.6s**.
2. Applied **only my diff** onto that export → the test **passes in 48.2s**.
3. `git status` shows `dv_harness/engine.py` and `dv_harness/coverage_analysis.py`
   are currently modified by another in-flight workflow; my diff touches
   neither, and the hanging test imports nothing I changed.

The full-suite run was therefore also executed inside the isolated HEAD+my-diff
export, so the result reflects my change rather than other workflows'
uncommitted state. That hang belongs to whichever workflow owns `engine.py`
right now and is flagged here rather than silently absorbed.

## Files changed

- `dv_harness/uvm_generator/bind_mechanism_generator.py` — mount-layer gate
  before the tier gate.
- `tools/generate_bind_mechanism.py` — `--phy-boundary` / `--require-phy-boundary`.
- `dv_harness/uvm_generator/run_profile.py` — source-authority verification.
- `dv_harness/uvm_generator/run_profile_to_justfile.py` — question-queue route,
  `verify_source_authority()`, `verify-source` CLI, `human_raw_override` ack.
- `CLAUDE.md` — Bind-Location Rule 5 (+ the two summary sentences it made stale).
- `docs/RUN_PROFILE.md` — items 6 and 7, the `human_raw_override` change, the
  `command_txt` scope limit, the Tests section.
- `dv_harness_tests/test_four_key_judgments_enforcement.py` — new, 26 tests.
- `dv_harness_tests/test_run_profile_to_justfile.py` — one assertion updated.

Concurrency discipline: every file was checked with `git status`/`git diff`
before editing (all six were clean — the concurrent edits are in `engine.py`,
`memory*.py`, `react*.py`, `cli.py`, `coverage_analysis.py`, none of which this
pass touches), and the commit is hand-scoped to exactly these paths, never a
broad `git add`.
