# PC-4 — Mutation Testing / Bug Injection — CLOSE-PASS REPORT

**Status: DONE**

**Commit:** `53e2654` — PC-4: mutation testing of this repo's own Python test suite (4 files, 1061 insertions, 0 deletions)

**Test summary:** `dv_harness_tests/test_mutation_testing.py` 21 passed; combined with
`test_qualification.py` + `test_stats_snapshot.py` (the two real modules the harness is
pointed at) 45 passed in 39.86s; all 11 `test_cli_*.py` files 84 passed / 5 failed,
all 5 in `test_cli_pueue.py` and **confirmed pre-existing** by re-running them against the
unmodified `cli.py` from HEAD, where they fail identically.

---

## 1. Gap independently re-verified as real

Run before writing any code, from `D:/DV/Task/DV_Agent_Harness_L5/v50/`:

```
grep -ril "mutation_test\|mutation testing\|bug_inject\|mutant" \
  --include="*.py" --include="*.md" --include="*.toml" --include="*.cfg" .
```

→ **zero hits repo-wide.** NEVER_BUILT confirmed.

Every `mutation` occurrence in `CLAUDE.md` belongs to
`capability_evolution.run_controlled_experiment()`, which is a per-candidate **treatment-arm
edit authored by whoever runs the experiment** — a different concept entirely (it changes code
to see if the change helps; it does not inject a fault to test whether a test would catch it).
Nothing was extended into it, and nothing duplicates it.

Closest existing mechanisms surveyed and deliberately **not** extended, with reasons:

| Existing mechanism | Why not this |
|---|---|
| `capability_evolution.run_controlled_experiment()` | Two-arm A/B of a *candidate improvement*; no fault injection, no kill/survive notion, and its mutation is authored, not generated. |
| `self_audit.py` (23 gates) | Meta-consistency of the repo's registries; asks nothing about test sensitivity. |
| `change_blast_radius.py` | The other real `ast` user in the tree — measures how far a change *reaches*, not whether tests would *catch* one. |
| `uvm_structural_lint.py` / `power_intent.py` test suites | Already use "mutate a clean fixture one defect at a time" as a *testing technique*; none of them is a reusable harness, and none targets `dv_harness/` Python. |

## 2. SCOPE — stated explicitly, as required

This is **testing-infrastructure-on-this-repo's-own-Python-code**. It injects AST-level faults
into a `dv_harness/*.py` module and re-runs that module's real `dv_harness_tests/test_*.py`
file to measure whether those tests detect the fault.

It is **NOT DUT/RTL-level fault injection** — no stuck-at, bit-flip or gate-level fault
campaign against a design under test. That needs a real RTL target and a simulator this
repository does not contain, and nothing produced here may ever be cited as evidence about a
DUT. The subject is this harness's own test suite; the verdict is about that suite's
sensitivity and nothing else. This is stated in the module docstring, in the CLI help, in the
test-file docstring, in the CLAUDE.md section, and as a `scope` key on every emitted JSON
report.

## 3. What was built

### `dv_harness/mutation_testing.py` (new, 556 lines)

**Four standard AST operators**, each a single-token change:

- `COMPARISON_SWAP` — `<`↔`<=`, `>`↔`>=`, `==`↔`!=`, `is`↔`is not`, `in`↔`not in`.
  Boundary-*shifting* rather than inverting: an inverted comparison breaks so loudly that any
  test kills it and the mutant teaches nothing.
- `BOUNDARY_SHIFT` — off-by-one on an int literal (`n` → `n+1`).
- `BOOL_OP_SWAP` — `and`↔`or`.
- `BOOL_CONST_FLIP` — `True`↔`False` (checked *before* the int branch, since `bool` subclasses
  `int`).

Mutants are produced by `ast.unparse` of the whole tree with exactly one site changed, so a
mutant is always syntactically valid. `-1` (which the AST stores as `UnaryOp(USub, Constant(1))`)
is labelled the way the **source** spells it — `-1 -> -2`, not `1 -> 2` — so a report is
reviewable against the file.

**The working tree is never written to, and that is structural.** mutmut/cosmic-ray overwrite
the source file and restore in a `finally`; a crash mid-run would leave a deliberately-broken
`dv_harness/*.py` in a tree whose main/master pushes are governed by real gates. Instead each
mutant runs in a **subprocess carrying a `sys.meta_path` finder** that serves the mutated
source for exactly one module name, from a temp file, before pytest is imported. The real file
is opened read-only.

**Safety — reuse, not a parallel pin.** `assert_safe_target()` refuses any module outside
`dv_harness/` and any test file outside `dv_harness_tests/`. The tests therefore really run
under that suite's `conftest.py`, whose existing session-wide `ENV_TRANSPORT_OVERRIDE = "off"`
pin applies to every mutant run. That pin is **reused, not re-implemented** — a second copy
would be exactly the parallel mechanism the Methodology Consolidation Rule forbids. Combined,
no mutant run can reach a real build, regression or LSF submission.

**Baseline first, always.** The run starts by executing the **unmutated** source through the
**same** import hook — proving both that the tests are green and that the hook is transparent.
A failing baseline yields `BASELINE_FAILED`, leaves every mutant `NOT_RUN`, and produces **no
score** rather than a number computed off a red suite. `TIMEOUT` gets its own bucket and is
deliberately **not** folded into `killed` (a hang is not the tests detecting the fault).

### `dv_harness/cli.py` (3 pure-insertion hunks, all mine — verified by `git diff`)

`dv-harness mutation-test [--module ...] [--test ...] [--operator ...] [--max-mutants N]
[--lines A:B] [--list] [--min-score F] [--timeout N]`. `--module` omitted runs every pair in
`DEFAULT_TARGETS`. `--max-mutants` reports the remainder `NOT_RUN` rather than dropping them,
so a partial run can never read as a full one.

### `dv_harness_tests/test_mutation_testing.py` (new, 21 tests)

### `CLAUDE.md` — one append-only section (`## Mutation Testing of This Repo's Own Test Suite`)

## 4. Real measured results on this repo

Both are genuine runs against real modules and their real existing test files:

| Target module | Test file | Generated | Killed | Survived | Score | Wall clock |
|---|---|---|---|---|---|---|
| `dv_harness/qualification.py` | `test_qualification.py` | 3 | 3 | 0 | **1.00** | 13.2s |
| `dv_harness/stats_snapshot.py` | `test_stats_snapshot.py` | 12 | 4 | 8 | **0.333** | 75.1s |

The **contrast is the point** — the harness produces different, defensible answers for two real
modules rather than a uniform number.

`stats_snapshot.py`'s 8 survivors, reviewed:

- **Real findings** (a human can act on these): `_iron_rule_count`'s and `_graph_counts`'s
  missing-file `return 0` / `return 0, 0` branches are never exercised (3 mutants);
  `_is_real_agent_profile`'s `OSError` branch is never exercised (1 mutant);
  `text.find("\n---", 3)`'s start offset is never probed (2 mutants).
- **Provably EQUIVALENT** (undetectable by construction, not a missing test): `-1 -> -2` on
  `if end == -1` — `str.find` returns −1 or a non-negative index and can never return −2.

`SURVIVED` is reported as a finding, never as proof of a missing test. Equivalent-mutant
detection is undecidable in general and is deliberately not attempted.

## 5. Tests prove the mechanism, not that a function returns a value

The **core end-to-end test** runs the one real line `stats_snapshot.py` spells `if end == -1`
and asserts its two mutants come back **differently**:

- `==` → `!=` **KILLED** — inverts the sentinel, so frontmatter parsing breaks for every real
  agent profile and `test_agent_count_matches_real_glob` fails.
- `-1` → `-2` **SURVIVED** — provably equivalent, so no test can ever detect it.

That asymmetry is the control: **if the import hook were not installing the mutant, both would
survive; if it were breaking the module, both would be killed.** Only a real, working mutation
run separates them.

The other 20 carry the same shape:

- The working tree's **bytes AND mtime** asserted unchanged across a real run.
- A forced baseline failure asserted to score nothing, run no mutant, and mark all `NOT_RUN`.
- Both safety refusals driven (module outside `dv_harness/`, test outside `dv_harness_tests/`),
  plus the non-existent-module and unregistered-target refusals.
- Every mutant asserted to `compile()` and to differ from the original; all sources distinct.
- Re-generation asserted **byte-identical** — a missed undo would silently produce compound
  mutants, whose kill would say nothing about which fault was caught.
- `max_mutants` asserted to leave the remainder visibly `NOT_RUN` on a second real module.
- All four operators asserted to fire; the negative-literal label asserted.
- The `TIMEOUT` bucket driven directly.
- `DEFAULT_TARGETS` drift guard (every pair resolves to a real module and real test file).
- Both CLI paths driven as **real subprocesses**, including a real non-zero exit under
  `--min-score` and the multi-module/`--test` refusal.

## 6. Constraints honoured

- **No human-approval gate touched.** `HumanApprovalRequiredError`,
  `ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`, `policy.can_signoff()` and the
  PR-only main/master governance are untouched and **unreferenced** — `mutation_testing.py`
  imports none of them. There is deliberately no stage gate and no default threshold: mutation
  score is a **measurement**, not a gate; `--min-score` is opt-in.
- **No real production build / regression / LSF submission.** Structurally impossible per the
  `assert_safe_target()` + reused-conftest-pin argument above. Every run in this pass was
  against `dv_harness/qualification.py` and `dv_harness/stats_snapshot.py` — pure local modules.
- **`golden_flow_readiness.py` not touched.**
- **Hand-scoped commit.** `git diff` verified `cli.py` carries exactly 3 hunks and `CLAUDE.md`
  exactly 1, all **pure insertions, zero deletions**, all mine (both files were unmodified when
  this pass started). Only the four files below were staged; the eight files other passes had
  dirty were left alone.

## 7. Built vs. deferred

**Built (complete):** the operators, the generator, the isolated runner, the baseline gate, the
safety guards, the report/JSON shape, the CLI verb, the two real registered targets, 21 tests,
the CLAUDE.md section.

**Deferred, deliberately and stated in the module + CLAUDE.md:**

- **Equivalent-mutant detection** — undecidable in general; survivors are reported with operator
  and line for human review.
- **A wider operator set** — four, not the dozen a mature tool ships. Each added operator
  multiplies wall clock by its mutant count.
- **A large default target set** — one mutant costs one full pytest process, so `DEFAULT_TARGETS`
  is deliberately two fast, self-contained pairs. An unbounded default would be a multi-hour job
  nobody runs.
- **Parallel mutant execution** — sequential and bounded; simpler and honest.
- **Engine wiring** — REACHED (a real CLI caller exists), not WIRED: no `run_stage()`/`advance()`
  call site invokes it and no graph node declares it. Deliberate: mutation testing is a
  developer/CI act on the harness's own code, not a step on a DUT verification run.

## 8. Files

- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/mutation_testing.py` *(new)*
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_mutation_testing.py` *(new)*
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/cli.py` *(3 insertion hunks)*
- `D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md` *(1 append-only section)*
