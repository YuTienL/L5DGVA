# SYS-5..SYS-8 gap close: per-subsystem architecture analysis + command.txt grammar + SubsystemCommandContract

**Verdict: DONE.**
**Scope:** SYS-5, SYS-6, SYS-7, SYS-8 of the FIRST-CLASS DOMAIN EXTENSION — SYSTEM-LEVEL
VERIFICATION INTEGRATION WORKFLOW (master prompt lines 4274–4519). Discovery/analysis/
planning/reporting only, per the document's own SYS-39 stop condition.
**Tests:** 53 new tests in
`dv_harness_tests/test_subsystem_architecture_and_command_contract.py`, all pass; the seven
related suites together (`test_reference_pattern_audit`, `test_source_authority`,
`test_subsystem_discovery`, `test_env_manifest_fact_sources`, `test_environment_mode_router`,
`test_system_level_soc_composition_wiring`, plus the new file) run **193 passed** (192 before the SYS-6 requirement drift guard was added).

---

## 1. The audit's findings, re-verified before building

Re-derived independently rather than taken on trust:

| Claim | Re-verified |
|---|---|
| `SubsystemCommandContract` / `command_contract` appear nowhere in real code or schema | Yes — repo-wide grep over `*.py`/`*.json`/`*.md`, excluding this task's own orchestrator prompt text, returns **zero** hits |
| `reference_pattern_audit.py` discards READ-verb calls and parses no control flow | Yes — `_MACRO_CALL_RE` requires two hex literals (so `CPUREAD4B(addr, i)` never matches at all), and the extractor is strictly line-at-a-time |
| `command_inventory.csv` has 10 identity/mapping columns and no dependency/ordering column | Yes — header confirmed; 24 real USB entries present |
| `.dv-workflow/command_inventory.csv` really fired (not a stub) | Yes — CMD-001..CMD-024 cite real `D:/DV/Task/USB/patterns/*.txt` with populated HANDLER/VIP_SEQUENCE |
| No per-subsystem SYS-6 report assembler anywhere | Yes — `env_manifest.py`, `run_profile.py` and `hierarchy.json` each stand alone with nothing joining them |
| The real command.txt grammar | Read directly: `D:/DV/Task/USB/command.txt` (90 lines) and `D:/DV/Task/USB/patterns/*.txt` (23 files) — the eight idioms listed in the new code's own header comment, plus the confirmed absence of any loop or fork/join in that corpus |

The audit's SYS-6 gap list was also confirmed: **interrupts, DMA, firmware interaction, memory
model, virtual interfaces** had no field, schema or code anywhere, and `component_hierarchy`
carried only a generic `type_name` with nothing classifying a component BY ROLE.

---

## 2. What was built

### 2a. `dv_harness/reference_pattern_audit.py` — extended, not duplicated (SYS-7)

The task's own instruction was to extend this module, and it is the right home: the SYS-7
grammar layer reads the SAME file class with the SAME macro-name shape. What changed:

- **`_MACRO_NAME_FRAGMENT`** — the macro-name shape is now written ONCE and both layers are
  built from it (`_MACRO_CALL_RE` for the pre-existing write-symmetry audit,
  `_REGISTER_MACRO_NAME_RE` for the new classifier). `_MACRO_CALL_RE.pattern` is byte-identical
  to before; a test asserts both layers agree, and another asserts the write-symmetry
  extractor still returns exactly what it did.
- **`extract_command_statements()`** — a full statement classifier over 26 kinds, string- and
  comment-aware, accumulating physical lines until bracket depth returns to 0. The real
  corpus's four-line `` `SMEMMODEL.FILLMEM("...", 4, 40'h2000_1000, 'd32); `` is ONE call with
  four arguments here, where the line-at-a-time layer sees four fragments.
- **`classify_command_roles()`** — SYS-7's PRODUCER / CONSUMER / PARSER / DISPATCHER / TARGET
  VIP-SEQUENCE, each derived from the file's own evidence, each with an explicit UNRESOLVED
  state. The parser of a command.txt is whatever defines its macros, which the file does not
  contain: it reports UNRESOLVED and names the macros, and RESOLVES only when the caller
  supplies real macro-definition sources. The producer is UNRESOLVED unless declared. Naming a
  guessed parser would be worse than saying it is unresolved.
- **`classify_wait()`** — SYS-7's "interrupt waits" as a name-token classification that says so:
  the matched token is the evidence, and a wait matching nothing is `SIGNAL_LEVEL_WAIT` rather
  than a guess in either direction.
- **`build_ordering_constraints()`** — six SEMANTIC relations
  (`ADDRESS_READ_AFTER_WRITE` / `ADDRESS_WRITE_AFTER_WRITE` / `WAIT_GATED` / `DELAY_GATED` /
  `INITIALIZATION_PRECEDES` / `FORCE_ACTIVE_DURING`). Implicit program order is never emitted:
  every statement follows the one before it, so an edge saying so carries no information and
  would bury the ones that do. A real 245-statement pattern yields 105 edges, not ~30 000.
- **`analyze_command_file()`** — every one of SYS-7's named aspects gets an explicit verdict,
  including the ones the real corpus does not exercise. `loops_and_repetition`,
  `concurrency` and `error_handling` report `NOT_FOUND` **with the search that was performed**,
  because an aspect nobody mentions is indistinguishable from an aspect nobody looked for.
- `python -m dv_harness.reference_pattern_audit <dir> --commands` runs it standalone.

Everything is read-only. SYS-7's own closing rule is "Do not modify command.txt during
discovery"; this module has never had a write path, and a test snapshots the file bytes across
a full analysis + contract build.

### 2b. `dv_harness/subsystem_command_contract.py` + its JSON schema (SYS-8) — new

A new module, because `parallel_safe` is meaningless inside one file (a command.txt is
sequential by construction) and only becomes a real question across subsystems. Both existing
analogs were checked first and neither is the right home: `command_inventory.csv` is identity +
handler mapping with no dependency/ordering/concurrency column (it is READ here as a declared
overlay via `load_command_inventory_overlay()`, never rewritten), and
`reference_pattern_audit` is strictly per-file.

- **`SubsystemCommandContract`** carries SYS-8's own 20 field names, verbatim and in its own
  order, plus one documented extra (`parallel_safety_reason`). `SYS8_FIELDS`, the dataclass and
  `dv_harness/schemas/subsystem_command_contract.schema.json`'s `required` list are held to
  each other by two tests, so the requirement, the code and the schema cannot drift apart in
  any direction.
- **Resource ids are a flat prefixed namespace** — `REGISTER_BLOCK:` / `BFM:` / `MODEL:` /
  `MEMORY_MODEL:` / `HIERARCHY:` — so SYS-9's inventory and SYS-10's dedup can compare two
  subsystems by string equality instead of by class name, which is SYS-10's own rule ("Do not
  decide duplicates by class names alone"). Every resource carries an access mode, the basis
  that made it visible, and a `file:line` citation.
- **`resolve_cross_subsystem_concurrency()`** decides `shared_resource_dependency` /
  `parallel_safe` / `serialization_required` over the whole set. A set holding ONE subsystem
  reports `UNKNOWN` with the reason, never `PARALLEL_SAFE` — there is no second subsystem to
  be concurrent with, and defaulting to safe would be a claim nothing supports.
- **`detect_contract_conflicts()`** reports three CROSS-SUBSYSTEM conflict types:
  `DUPLICATE_ACTIVE_DRIVER` (SYS-10/12's "PCIe and USB both contain a CPU AXI Master" shape,
  resolution = SYS-12's own "stop automatic integration until ownership is resolved"),
  `SHARED_RESOURCE_CONTENTION`, and `ADDRESS_WRITE_COLLISION`. Read/read sharing is **not** a
  conflict, and contention inside one subsystem is **not** a conflict — a detector that reports
  either trains its users to ignore it.
- **`clock_domain` resolves in two steps, each able to fail honestly**: addresses are located in
  the project's real address map, then mapped through a declared region→clock mapping. A
  `soc_arch_map` address_map entry carries no clock of its own, so without a declared mapping
  it reports `UNRESOLVED` and NAMES the regions it did locate — which is the input SYS-29's
  cross-subsystem clock-domain comparison will consume.

### 2c. `dv_harness/subsystem_architecture_analysis.py` (SYS-5 + SYS-6) — new

A new module for the same structural reason: both requirements operate on MANY subsystems at
once. `env_manifest.py` stays the sole writer of ONE environment's manifest; `run_profile.py`
stays the IR of ONE Makefile; neither knows what a subsystem is, and SYS-5's isolation rule is
a property OF a set. This module **imports and composes** them and re-derives nothing:

| SYS-6 evidence | Source, reused not copied |
|---|---|
| DUT hierarchy, VIPs, register model, address map, clock/reset, RTL | `env_manifest.load_env_manifest()` |
| build/run/regression/waveform/fsdbreport flows | `run_profile.load_run_profile()` — real `compile_time_params`/`runtime_params`/`targets` |
| command.txt grammar, interrupt waits, DMA, firmware evidence | `reference_pattern_audit` (SYS-7) |
| contracts + cross-subsystem conflicts | `subsystem_command_contract` (SYS-8) |
| candidate rows, and one definition of what a command.txt is named | `subsystem_discovery` (SYS-1..4) — `discover_command_files()` reuses its `ARTIFACT_GLOBS["command_txt"]` and bounded walk |

**The six fields the audit found missing are now derived**, each from real artifacts with a
cited basis:

- **semantic component roles** — `classify_component_roles()` assigns
  agent/sequencer/virtual_sequencer/driver/monitor/scoreboard/reference_model/predictor/
  coverage_collector/assertions_checker/config_object/env, most-specific-token-first (so a
  virtual sequencer is not swallowed by "sequencer"). It is a NAME-TOKEN classifier and says so
  on every row: the matched token and the field it matched in are the basis, a component
  matching nothing is `UNCLASSIFIED` rather than assigned a plausible role, and a project may
  declare exact assignments which beat the tokens entirely.
- **active/passive** — copied from the dump's real `get_is_active()`, three-valued
  (`UVM_ACTIVE`/`UVM_PASSIVE`/`NOT_APPLICABLE`); never inferred from a name, and
  `NOT_APPLICABLE` is not folded into "passive".
- **interrupts** and **DMA** — two independent axes each, reported separately: RTL port-name
  matches from the verible parse, and command.txt evidence from SYS-7.
- **firmware interaction** — command.txt model/VIP task calls + memory backdoor loads +
  firmware-named components.
- **memory model** — command.txt model instances + hierarchy components + address-map regions,
  explicitly distinct from the register model.
- **virtual interfaces** — a token match over the `config_db_trace` message body (whose internal
  format `env_manifest.py` deliberately keeps opaque), reported as such.

**Three field statuses, not two.** `DERIVED` / `NOT_AVAILABLE` / `NOT_APPLICABLE`. "Nobody
looked" and "we looked and there are none" are opposite findings; `NOT_AVAILABLE` names the
real command that would produce the missing artifact.

**SYS-5's isolation rule is enforced, not asserted.** Each analysis records every path it
actually opened; `assert_no_cross_contamination()` compares those reads against the OTHER
selected subsystems' environment roots and **raises** rather than warns — a contaminated
analysis cannot be repaired after the fact. `synthesize_subsystem_analyses()` re-runs that check
and additionally refuses while any analysis is not `COMPLETE`, so a caller cannot reach the
synthesis with a hand-assembled list that skipped `run_per_subsystem_analyses()`. Parallelism is
safe for a structural reason: an analysis is a pure read over its own declared input list and
`artifacts_modified: False` is a property of a function with no write path.

### 2d. Wiring

`dv-harness subsystem-analysis --select A --select B [--command-inventory CSV] [--json]`.
Exit 0 only when the selection is admissible AND no cross-subsystem conflict stands — SYS-12's
"stop automatic integration of that resource" must not read as a clean run to a CI step. When
the selection is refused, the SYS-1 discovery report is printed FIRST, so an empty analysis
reads as "nothing was selected" and never as "these subsystems are clean". SYS-1's
explicit-selection refusal is not bypassed: the front door goes through
`subsystem_discovery.require_explicit_selection()`.

---

## 3. The hard constraint, and how it is held

No System-Level UVM source, no System command.txt, no System Virtual Sequencer and no command
routing/adapter is generated anywhere in this change. Four tests enforce it:

- `test_the_whole_flow_writes_nothing_into_the_analyzed_environments` — byte-for-byte snapshot
  of the whole project tree before and after a full two-subsystem analysis + synthesis + report.
- `test_no_system_level_uvm_source_or_system_command_txt_is_produced` — the rendered report
  contains no `class `/`endclass`/`` `uvm_component_utils ``/`module `/`endmodule`/`uvm_sequence #`,
  and no `*_vseqr.sv` or `system_command.txt` exists on disk.
- `test_sys7_analysis_never_modifies_the_command_txt` — command.txt bytes unchanged across
  analysis and contract building.
- `test_soc_composer_cross_subsystem_stubs_are_still_unimplemented` — `cross_subsystem_scenarios()`
  / `end_to_end_scoreboard()` / `system_coverage()` still raise `NotImplementedError`. They were
  not touched.

Both the contract-set document and the analysis report carry the SYS-39 phase boundary naming
SYS-40 and its separate human approval, and the JSON schema makes `command_txt_modified` a
`const false` — a document claiming otherwise is not a valid document of that schema.

---

## 4. Tests (53, on synthetic fixtures with real conflicting cases)

Every fixture is synthetic and built in `tmp_path`: fake command.txt files written in the real
macro grammar (describing no real DUT), fake environment trees, a fake registry, a fake topology
dump, a fake SoC architecture map. No real project's command.txt is opened by any test.

The conflicting/ambiguous cases carry the coverage:

- **Two subsystems both actively driving one CPU-side BFM** — both invoke `` `CPUWRITE4B ``, so
  both drive `BFM:DUT_SIDE`. Reported as `DUPLICATE_ACTIVE_DRIVER` with
  `STOP_AUTOMATIC_INTEGRATION_UNTIL_OWNERSHIP_RESOLVED`, and the affected contracts are marked
  `NOT_PARALLEL_SAFE` / `serialization_required` with the contending subsystem named.
- **Two subsystems writing the exact same address literal** — `ADDRESS_WRITE_COLLISION`. An
  address written by only one of them is correctly not a collision.
- **Two subsystems only READING one block** — zero conflicts, `READ_ONLY_SHARING`,
  `PARALLEL_SAFE`. The negative case that gives the positive ones meaning.
- **A subsystem contending only with itself** across two of its own command.txt files — not a
  conflict.
- **A single-subsystem set** — every `parallel_safe` is `UNKNOWN` with
  `SINGLE_SUBSYSTEM_CONTRACT_SET` as the reason, and zero conflicts by construction.
- **A contaminated analysis** — one subsystem's `read_paths` containing a path under another's
  environment root raises `CrossContaminationError`, and the synthesis cannot be reached around it.
- **An incomplete analysis** — the synthesis refuses.
- Plus: a drift guard holding `SYS6_FIELDS` to the requirement's own 24-item list one-to-one;
  the drift guard on the shared macro-name fragment; the pre-existing write-symmetry
  layer proved unchanged; the four-line `FILLMEM` call as one statement; a `//` inside a string
  literal not treated as a comment and a comma inside one not splitting an argument; dotted text
  inside `$display("...Command.")` not becoming a CONSUMER; interrupt vs. level wait with the
  deciding token cited; semantic edges bounded well below pairwise program order; a force with
  no matching release saying so; parser UNRESOLVED then RESOLVED when definitions are supplied;
  loops/fork-join/`$error` classified when present and honestly NOT_FOUND when absent; the
  three clock-domain resolution outcomes; the declared command_inventory overlay applied and
  the CSV proved unmodified; `NOT_AVAILABLE` vs `NOT_APPLICABLE` staying distinct; and three
  real-subprocess CLI tests covering the conflict exit code, the refusal path, and a clean
  single-subsystem run.

---

## 5. Resulting verdicts

| Req | Before | After |
|---|---|---|
| SYS-5 | NEVER_BUILT | **WIRED_AND_FIRING** — `run_per_subsystem_analyses()` opens one independent, parallel-safe analysis per selected subsystem; `assert_no_cross_contamination()` enforces isolation as an exception; `synthesize_subsystem_analyses()` refuses to synthesize early. Reachable via `dv-harness subsystem-analysis`. |
| SYS-6 | PARTIALLY_WIRED | **WIRED_AND_FIRING** — all 24 mandated fields get a verdict from real artifacts; the six the audit found missing (interrupts, DMA, firmware, memory model, virtual interfaces, semantic component roles) are derived with a cited basis; one assembler joins env.manifest.json + run_profile.json + hierarchy.json + the SYS-7 analysis. |
| SYS-7 | PARTIALLY_WIRED | **WIRED_AND_FIRING** — full statement grammar, PRODUCER/CONSUMER/PARSER/DISPATCHER/TARGET-VIP-SEQUENCE roles, six semantic ordering relations, and an explicit verdict for every named aspect including waits, interrupt waits, delays, reset handling, DMA, loops, concurrency, error handling, expected responses and termination. Read-only. |
| SYS-8 | NEVER_BUILT | **WIRED_AND_FIRING** — `SubsystemCommandContract` with SYS-8's own 20 fields, a real JSON schema held to it by test, and the cross-subsystem conflict detection that feeds SYS-19..25. |

---

## 6. Disclosed limits

1. **Role, interrupt, DMA, reset, memory-model and firmware classification is NAME-TOKEN
   based.** That is real evidence — it is what the captured artifacts contain — but it is not
   proof. Mitigated by citing the matched token and the field it matched in on every row, by
   `UNCLASSIFIED` rather than a plausible guess, and by a declared-override path; not
   eliminated. `is_active` is the exception and is never name-derived.
2. **`HIERARCHY:GMODEL` and `MODEL:GMODEL` can both appear for one physical model** — they are
   two different access paths (a backdoor assign through the macro root vs. a task call), and
   both are reported. Deciding that two resource ids denote ONE physical resource is SYS-11's
   relationship classification, which is a later step of this sequence and deliberately not
   pre-empted here.
3. **`command_category` does not split a register write into config-vs-traffic.** SYS-7 names
   "init/config/traffic commands", but nothing in a command.txt states which a given write is;
   it is `REGISTER_ACCESS`, and a declared classification may override. Guessing would be
   fabricated evidence.
4. **`clock_domain` needs a declared region→clock mapping** to resolve past UNRESOLVED, because
   a `soc_arch_map` address_map entry carries no clock reference of its own. This is reported
   with the located regions rather than defaulted.
5. **This repo has no multi-subsystem project of its own**, so `dv-harness subsystem-analysis`
   here is honestly empty (0 registered, `NOT_CONFIGURED`, `NO_EXPLICIT_SELECTION`, exit 2) —
   the same standing limitation CLAUDE.md already discloses for mechanism #14, deliberately not
   papered over with fabricated registry entries. The SYS-7 layer WAS exercised against the real
   USB corpus read-only during development (23 pattern files + `command.txt`, zero UNCLASSIFIED
   statements, real interrupt waits and ordering edges recovered), but no test depends on that
   tree.
6. **SYS-9 onward is untouched** — resource inventory, duplicate VIP/agent detection across
   subsystems, relationship classification, the shared-resource registry and the two mandatory
   matrices are later steps of this same sequence. `detect_contract_conflicts()` produces the
   command-derived half of SYS-10's input; it is not SYS-10.
