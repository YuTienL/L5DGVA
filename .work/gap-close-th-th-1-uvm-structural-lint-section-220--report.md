# TH-1 — UVM Structural Lint (spec section 220)

**Status: DONE**
**Tests: 32 new (`dv_harness_tests/test_uvm_structural_lint.py`) all pass; 167 tests of the neighbouring verible / env-manifest / protocol-generator / SoC-composition suites re-run and still pass.**
**Commit: `0b2a216` on branch `gap-close/env-manifest-fact-sources` (no push; PR-only governance untouched).**

## 1. Gap independently re-verified before building

Not taken from the audit. Re-checked with my own greps:

- `grep -rn "uvm_component_utils|uvm_object_utils" --include=*.py dv_harness/ tools/` returned **only generator EMIT sites** (`uvm_generator/generator.py`, `amba_fabric_generator.py`, `tools/observability/generate_observability_plan.py`). Nothing reads a generated `.sv` back.
- `dv_harness/verible_parser.py` extraction is `kModuleDeclaration` / `kPortDeclaration` / `kInstantiationBase` shaped — RTL only, confirmed by reading the file.
- `dv_harness/uvm_generator/bind_verification_lint.py` lints elaboration/simulation **report text**, not UVM source.

So the gap was real and total: a generated environment's first structural feedback was a VCS compile — exactly the expensive path section 220 exists to run in front of.

## 2. What was built

`dv_harness/uvm_structural_lint.py` (new, ~530 lines).

**Parser reuse, not a second parser.** It calls the real `verible_parser.run_export_json()` and that module's tree-walk helpers. Those helpers were private (`_walk`, `_find_all_nonoverlapping`, …); rather than importing privates or duplicating a walker (Methodology Consolidation Rule), I added **public aliases** at the bottom of `verible_parser.py` — one implementation, now a named contract. Verified live against this machine's verible (`v0.0-4150-gfe58e708`) that class-based UVM produces every node the checks need: `kClassDeclaration`/`kClassHeader`/`kExtendsList`, `kClassItems`, `kMacroCall(MacroCallId + kMacroArgList)`, `kFunctionDeclaration`/`kFunctionHeader`, `kTaskDeclaration`, member `kDataDeclaration`, and `kFunctionCall(kReferenceCallBase = callee kReference + kParenGroup)`. **Every call site's boundary comes from verible's tree**; only the already-isolated callee identifier path (`uvm_config_db#(T)::set`, `phase.raise_objection`, `env.mon.ap.connect`) is matched as a string. No regex over raw file text.

**Five checks** — the subset a parse can *decide* without elaboration:

| Rule family | ERROR cases |
|---|---|
| `FACTORY_REGISTRATION_{MISSING,WRONG_KIND,NAME_MISMATCH}` | missing macro; object macro on a component; macro naming a different type |
| `PHASE_METHOD_{WRONG_KIND,RETURN_TYPE_NOT_VOID,ARG_COUNT,ARG_TYPE}` | `function void run_phase`; `task connect_phase`; non-void phase function; wrong/absent `uvm_phase` argument |
| `CONFIG_DB_{GET_WITHOUT_SET,SET_WITHOUT_GET,KEY_NOT_STATICALLY_RESOLVABLE}` | none — WARNING/INFO only, see §4 |
| `TLM_PORT_NEVER_CONNECTED` / `TLM_EXPORT_NEVER_CONNECTED` | a declared `uvm_*_port` member `.connect()` is never called on (export/imp: WARNING) |
| `OBJECTION_{RAISE_DROP_IMBALANCE,RAISE_DROP_SPLIT_ACROSS_METHODS,NEVER_RAISED_IN_TEST_RUN_PHASE}` | per-method imbalance where the class totals also fail to balance |

**Where it runs (real wiring, not a standalone module).**
- `dv_harness/uvm_generator/create_environment.py` — the one real CREATE ENVIRONMENT entry point — now lints what it just generated in **both** SUBSYSTEM_MODE and SYSTEM_LEVEL_MODE, returns the report as `result["structural_lint"]`, and writes `<out_dir>/uvm_structural_lint.json`.
- Non-blocking by default; a manifest may set `"strict_structural_lint": true` to make ERROR findings raise `StructuralLintFailedError`, surfaced by `tools/generate_protocol_uvm_environment.py` as **exit 5** (its existing exit-2/3/4 refusals unchanged).
- New CLI verb: `dv-harness uvm-lint --env-dir <dir> | --file <f> [--json] [--fail-on-error] [--verible-bin ...]`.
- `CLAUDE.md` documents the mechanism and its limits (new "UVM Structural Lint (2026-09-06)" section).

## 3. Evidence it actually works

**Against real generator output** — all 13 `examples/generated_*` environments this project's own generator produced report **status PASS, 0 ERROR findings**. A lint that fires on genuine generator output would be unusable regardless of how many synthetic defects it catches, so this is as load-bearing as the mutation tests.

**Against injected defects** — the test file asserts a clean synthetic environment has *zero* findings first, then mutates that same source **one defect at a time**, so each assertion proves the lint caught that specific injected defect:

```
factory_missing            -> ERROR FACTORY_REGISTRATION_MISSING (demo_monitor)
object_utils_missing       -> ERROR FACTORY_REGISTRATION_MISSING (demo_item)
object macro on component  -> ERROR FACTORY_REGISTRATION_WRONG_KIND
macro names another type   -> ERROR FACTORY_REGISTRATION_NAME_MISMATCH
function void run_phase    -> ERROR PHASE_METHOD_WRONG_KIND
task connect_phase         -> ERROR PHASE_METHOD_WRONG_KIND
function bit build_phase   -> ERROR PHASE_METHOD_RETURN_TYPE_NOT_VOID
connect_phase(int phase)   -> ERROR PHASE_METHOD_ARG_TYPE
connect_phase()            -> ERROR PHASE_METHOD_ARG_COUNT
delete the .connect() call -> ERROR TLM_PORT_NEVER_CONNECTED + WARNING TLM_EXPORT_NEVER_CONNECTED
delete drop_objection      -> ERROR OBJECTION_RAISE_DROP_IMBALANCE
delete the config_db set   -> WARNING CONFIG_DB_GET_WITHOUT_SET
delete the config_db get   -> WARNING CONFIG_DB_SET_WITHOUT_GET
```

Plus real negative/robustness cases: an out-of-scope VIP base is recorded UNCLASSIFIED and **not** flagged; a method-local TLM handle is not mistaken for a class member; a similarly-named port does not count as connected; a raise/drop pair split across `pre_main_phase`/`post_main_phase` is WARNING not ERROR; a renamed-on-both-sides config_db key stays clean; missing verible → `NOT_AVAILABLE`, never PASS; empty dir → `NOT_AVAILABLE`; malformed `.sv` → ERROR, non-standalone `.svh` → WARNING; the real `create_environment()` end-to-end writes the report with real per-file SHA-256s; `strict_structural_lint` really refuses; and the CLI verb's exit codes with and without `--fail-on-error`.

## 4. Scoped down / deliberately NOT built — stated honestly

- **Section 220 lists twelve concerns; five are implemented.** Not implemented: analysis-port semantics beyond connection, sequencer/driver linkage, virtual-interface binding, package/import dependencies, duplicate definitions, duplicate active drivers, illegal hierarchy assumptions. Several need elaboration-time truth a parse does not have (resolved parameters, evaluated generate/`` `ifdef `` conditions, the VIP's own class definitions).
- **Both config_db findings are WARNING, never ERROR** — an unmatched key is an absence this analysis cannot *prove*: the missing half may live in VIP code, a project's own top test, or behind a run-time-built key. This was changed after a real observation, not theorised: at ERROR it fired on the real `usb_base_vseq`'s legitimate `device_address`/`configuration_value` optional overrides. ERROR is reserved for defects provable from the analysed sources alone.
- **Not added to `STAGE_GATES`.** A new mandatory IMPLEMENT-stage gate would require every existing caller to supply a new evidence block and would fail every stage run that does not — a large blast radius for no added enforcement, since the check already runs at the real generation call site. The mechanism is wired into real code, not left standalone.
- Generate/`` `ifdef `` conditions are not evaluated; parameters are not resolved; a class whose base chain leaves the analysed set is UNCLASSIFIED and skipped.

## 5. Governance / safety

- No human-approval gate touched or weakened. No new gate registered. `focused_wave_debug_window_gate`, the question-queue path, `git-guard` and the PR-only policy are untouched.
- **Nothing was built, run, simulated, or submitted.** Everything ran against local fixtures: the in-repo `examples/generated_*` directories, synthetic UVM strings in the test file, and real `create_environment()` calls into `tempfile.mkdtemp()`. No VCS, no LSF, no remote transport.
- Commit is on the existing feature branch `gap-close/env-manifest-fact-sources`, **not** pushed and **not** on `main`/`master`.

## 6. Shared-file concurrency handling

A concurrently-running close-pass modified `dv_harness/cli.py` (a `verification-strategy` verb) and `dv_harness/uvm_generator/create_environment.py` (`compose_soc_environment(..., root)`) while I worked. Both were staged with the **hand-scoped patch technique**: `git diff --unified=2 <file> > patch`, programmatic hunk-level trim to my hunks only, `git apply --cached --check` then `--cached`. Verified afterwards that no foreign line is in the staged diff, and that the **staged-only** tree imports and passes all 32 tests (checked with `git stash push --keep-index`, then popped — the other pass's working-tree changes are intact and unstaged). `CLAUDE.md`, `verible_parser.py` and `tools/generate_protocol_uvm_environment.py` contained only my changes and were staged whole.

## Files

- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/uvm_structural_lint.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_uvm_structural_lint.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/verible_parser.py` (public aliases for its tree-walk helpers)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/uvm_generator/create_environment.py` (`_run_structural_lint`, `StructuralLintFailedError`, both mode branches)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/cli.py` (`uvm-lint` verb)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/tools/generate_protocol_uvm_environment.py` (report + exit 5)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md` (mechanism + stated limits)
