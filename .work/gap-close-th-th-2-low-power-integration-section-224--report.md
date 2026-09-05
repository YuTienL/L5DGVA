# TH-2 — Low-Power Integration (spec section 224)

**Status: DONE (bounded scope, exactly as the task authorised)**

**Test summary:** `dv_harness_tests/test_power_intent.py` — 42 passed.

---

## 1. Gap re-verified independently before building

Not restated from the audit. Run in `D:/DV/Task/DV_Agent_Harness_L5/v50/`:

```
grep -rn "upf|power_domain|set_isolation|set_retention|power_intent" --include=*.py dv_harness/ tools/
```

returned only unrelated matches — the word "upfront" in `cli.py:939`,
`exemptions.py:265`, `reference_pattern_audit.py:6`, plus a single
`"power_domains":[]` literal in `tools/dut_architecture/build_architecture_model.py:33`.
A repo-wide `grep -ril` over `.py/.md/.json` found the term only in prose
(agent markdown, memory records, `.work/` reports) and in
`.dv-harness/dut-architecture/architecture_model.schema.json`'s
`"power_domains": []`, which declared the field with **no item shape at all**.

`tools/verification_flow/reset_clock_power_sequence_gate.py` and
`reset_power_cdc_corner_gate.py` were re-read: both are self-attested
evidence-block checks over reset/CDC JSON fields. Neither reads a power-intent
file. **Confirmed NEVER_BUILT.**

Closest existing real mechanism, and the one extended rather than duplicated:
the `power_domains` field of the architecture model, hardcoded `[]` since
`build_architecture_model.py` was written because nothing in the repo could
produce a power domain.

## 2. What was built

### `dv_harness/power_intent.py` (new)

A real IEEE-1801 UPF parser, structured power-intent model, and a
self-consistency analysis of that intent.

**Tcl-subset tokenizer** — `#` comments at command position, `;` command
separation, backslash-newline continuation, nested `{}` (literal, no
substitution — the real Tcl rule), `"..."` quoting with escapes, and
`set` / `$var` / `${var}` substitution. Every word carries its real source
line, so every model object and every finding cites a real `file:line`.

**Modelled commands** (the bounded subset, each mapping cleanly onto a flat
option/value shape, together carrying the power topology):
`upf_version`, `set_design_top`, `set_scope`, `set`, `create_power_domain`,
`create_supply_port`, `create_supply_net`, `create_supply_set`,
`connect_supply_net`, `set_domain_supply_net`, `create_power_switch`,
`set_isolation`, `set_isolation_control`, `set_retention`,
`set_retention_control`.

UPF-1.0 style (a separate `*_control` command) and UPF-2.x style (control
options folded into the strategy command) merge into **one** strategy record,
so "does this strategy have a control signal" has one answer, not two.

**Structured model**: `PowerIntent` with `domains`, `supply_ports`,
`supply_nets`, `supply_sets`, `switches`, `isolation`, `retention`,
`variables`, `unsupported_commands`, `issues`, plus derived
`switchable_domains()` (a domain is switchable when a switch declares
`-domain PD`, **or** a switch output supply port feeds the net PD uses as its
primary power net) and a full `to_dict()`.

**`analyze_power_intent()`** — every rule decidable from the UPF's own text:

| severity | codes |
|---|---|
| ERROR | `ISOLATION_DOMAIN_UNDECLARED`, `RETENTION_DOMAIN_UNDECLARED`, `SWITCH_DOMAIN_UNDECLARED`, `SUPPLY_NET_UNDECLARED`, `SUPPLY_PORT_DOMAIN_UNDECLARED`, `SUPPLY_NET_DOMAIN_UNDECLARED`, `ISOLATION_WITHOUT_CONTROL_SIGNAL`, `ISOLATION_WITHOUT_SUPPLY`, `ISOLATION_WITHOUT_DOMAIN`, `RETENTION_WITHOUT_SAVE_RESTORE`, `RETENTION_CONTROL_INCOMPLETE`, `RETENTION_WITHOUT_SUPPLY`, `RETENTION_WITHOUT_DOMAIN`, `SWITCH_WITHOUT_CONTROL_PORT`, **`SWITCHABLE_DOMAIN_WITHOUT_ISOLATION`**, `DUPLICATE_*`, `*_CONTROL_WITHOUT_STRATEGY`, `MALFORMED_UPF_COMMAND`, `UPF_FILE_UNREADABLE/UNPARSEABLE` |
| WARNING | `DOMAIN_WITHOUT_PRIMARY_SUPPLY`, `DOMAIN_WITHOUT_ELEMENTS`, `ISOLATION_WITHOUT_CLAMP_VALUE`, `ISOLATION_CONTROL_WITHOUT_SENSE`, `SWITCH_WITHOUT_ON_STATE`, `UNRESOLVED_UPF_VARIABLE` |
| INFO | `SWITCHABLE_DOMAIN_WITHOUT_RETENTION`, `UNMODELLED_UPF_COMMAND` |

`SWITCHABLE_DOMAIN_WITHOUT_ISOLATION` is the rule carrying real low-power
meaning: a domain a switch can power down whose outputs nothing clamps would
float into always-on logic. `SWITCHABLE_DOMAIN_WITHOUT_RETENTION` is INFO, not
an error — losing state across a power-down is a legitimate design choice.

An empty model is **`NOT_AVAILABLE`, never PASS** — section 224's explicit
UNSUPPORTED/UNKNOWN outcome.

### Integration into existing real mechanisms (no parallel mechanism built)

- `tools/dut_architecture/build_architecture_model.py` — new `--upf` (repeatable)
  populates the previously-always-empty `power_domains` from
  `power_domains_for_architecture_model()` (name, scope, elements,
  primary power/ground nets, `switchable`, its isolation/retention strategy
  names, `source: "UPF"`, and a real `<upf file>:<line>` evidence string), and
  appends a `UPF_POWER_INTENT` evidence row. **Without `--upf` the field stays
  `[]` and `unknowns` gains "no power intent supplied (--upf): power_domains
  UNSUPPORTED/UNKNOWN"** — an absent power intent must not read as a design
  that simply has no power domains.
- `.dv-harness/dut-architecture/architecture_model.schema.json` — the
  `power_domains` item shape is now documented instead of being an untyped `[]`.
- `dv_harness/cli.py` — `dv-harness power-intent --upf <f> [--json]
  [--fail-on-error]`, sharing one implementation (`power_intent.execute_verb`)
  with `python -m dv_harness.power_intent`, the same convention `uvm-lint` and
  `verification-strategy` use. Exit 0 PASS / 1 FAIL-with-`--fail-on-error` /
  **2 NOT_AVAILABLE unconditionally** (with or without `--fail-on-error`).
- `CLAUDE.md` — new "Power Intent / Low-Power Evidence (2026-09-06)" section
  stating the mechanism, where it runs, and its four bounded limits.

### Test fixture

`dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf` — a clean,
realistic two-domain design (always-on `PD_TOP`; switchable, isolated,
retained `PD_PERIPH` with a real power switch). Its own header states in full
that it is a test fixture, that no `synthetic_lp_soc` RTL exists in this
repository, that this project owns no low-power DUT, and that it must never be
cited as evidence about any real design.

## 3. Tests — `dv_harness_tests/test_power_intent.py`, 42 passed

Same discipline as `test_uvm_structural_lint.py`:

1. **Tokenizer** against the syntax real UPF actually uses: comments, `;`
   separation, backslash continuation (asserting the continued command is ONE
   command whose line number is where it *started*), nested braces, quoting,
   unbalanced-brace refusal, and the Tcl brace rule — `$V` substitutes in a bare
   word and stays literal inside `{}` (getting that backwards would silently
   invent signal names that are not in the design). Unresolved `$var` is
   reported, not silently kept.
2. **Clean fixture** extracts a fully-asserted model — domain elements, supply
   ports/nets, `connect_supply_net` attachment, switch ports, the merged
   isolation strategy with `$ISO_CTRL` substituted to `pmu_iso_en` and BOTH its
   source sites recorded, retention save/restore signal+sense pairs,
   `switchable_domains() == ["PD_PERIPH"]` — and reports **zero** findings.
   A separate test opens the fixture and asserts each object's recorded line
   number really is that command's line.
3. **One mutation per analysis rule** (19 tests), each replacing exactly one
   substring of the clean fixture and asserting the target was unique first, so
   a fixture edit cannot silently turn a mutation test into a passing no-op.
   The zero-finding baseline is what makes "this rule caught this specific
   injected defect" a valid inference. Includes the negative cases that matter:
   a warning-only defect stays PASS, `-update` on a duplicate domain merges
   rather than errors, an unmodelled command is INFO and does not fail.
3b. **The two derived paths a fixture mutation cannot reach**: switchability
   derived through the SUPPLY NET rather than `-domain` (a switch that drives
   the net a domain uses as its primary power net makes that domain
   switchable — tracking only `-domain` would miss the whole net-driven
   form), and a UPF-2.x supply SET satisfying the isolation/retention
   always-on-supply requirement, with an undeclared supply set still caught.
4. **UNSUPPORTED/UNKNOWN**: sources with no power constructs → `NOT_AVAILABLE`
   with zero findings; a missing file is reported, not crashed; multiple files
   accumulate into one model with a control command in file B attaching to a
   strategy declared in file A.
5. **Real integration through real entry points**: the actual
   `build_architecture_model.py` subprocess with and without `--upf` (asserting
   the pre-existing clock/reset fields are untouched), and the actual
   `python -m dv_harness power-intent` CLI subprocess for PASS, `--json`,
   `--fail-on-error` exit 1, and NOT_AVAILABLE exit 2 both with and without
   `--fail-on-error`.

Nothing was run against a production build, regression, or LSF. Every test
touches only local synthetic fixtures and `tmp_path`.

## 4. Built vs. DEFERRED — stated explicitly

**Deferred, deliberately, and NOT half-built:**

- **No stage gate.** Section 224's behavioural list (power state, reset
  interaction, clock gating, wake-up, traffic during power transitions,
  interrupt wake, low-power entry/exit) is **not** implemented. Verifying any
  of it needs a real low-power DUT and a power-aware simulator; this project
  has neither. A gate that "checks" power intent against nothing would be
  exactly the fabricated low-power verification flow section 224 forbids, so
  none was written. Nothing in `dv_harness/gates.py` or `STAGE_GATES` was
  touched.
- **Nothing is cross-checked against RTL, a netlist, or a simulation.** The
  analysis is UPF-vs-UPF only, and both the module docstring and the CLI's own
  rendered output say so on every run.
- **Tcl subset, not an interpreter**: `[...]` command substitution,
  `if`/`foreach`/`proc`, `expr`, and `source`/`load_upf` inclusion are not
  executed.
- **Power-state tables** (`add_power_state`, `create_pst`, `add_pst_state`) are
  recorded as unmodelled rather than modelled — their supply-expression
  mini-language does not fit the flat option/value shape the modelled commands
  share, and modelling them badly would be worse than reporting them honestly.
  Every unmodelled command is surfaced with its file and line as an INFO
  finding saying it was NOT analysed; nothing is silently dropped.

**Governance:** no human-approval gate was weakened, added to, or bypassed. No
production build, regression, or LSF submission was triggered. Shared files
(`dv_harness/cli.py`, concurrently modified by another close-pass) were staged
with the hand-scoped patch technique, never a broad `git add`.

## 5. Files

- `dv_harness/power_intent.py` (new)
- `dv_harness_tests/test_power_intent.py` (new)
- `dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf` (new)
- `tools/dut_architecture/build_architecture_model.py` (modified)
- `.dv-harness/dut-architecture/architecture_model.schema.json` (modified)
- `dv_harness/cli.py` (modified — `power-intent` verb only)
- `CLAUDE.md` (modified — new section)
