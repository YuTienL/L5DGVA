# TH-5 -- Configuration Variant Explosion Control (spec section 232)

**Status: DONE**

**Test summary:** `python -m pytest dv_harness_tests/test_config_variant_coverage.py -q` ->
**30 passed**; neighbouring/shared-surface suites `test_golden_scenario.py`,
`test_power_intent.py`, `test_requirement_contract.py` and the whole `-k "cli or command"`
selection all pass (the only failures in that selection are the 6 pre-existing
`pueue`/`pueued`-daemon-unavailable ones, confirmed identical with my `cli.py` change
stashed out).

**Commit:** `5f42bf4  feat(config): pairwise/t-way configuration variant selection (spec 232, TH-5)`

---

## 1. Gap re-verified independently (not taken from the audit)

- `grep -rn "pairwise\|n-wise\|covering_array\|CoveringArray\|cross_product\|combinatorial"
  --include=*.py .` matched only unrelated mechanisms:
  `system_topology_analysis._pairwise_overlap()` (do two ADDRESS REGIONS intersect),
  `system_command_plan`'s pairwise ESCALATION QUESTION split, `source_authority`'s pairwise
  CONFLICT questions, and prose in test comments. No covering array anywhere.
- `dv_harness/change_impact.py` and `dv_harness/regression_tiers.py` were read in full at the
  header/API level: both select WHICH TESTS out of an enumerated pattern universe
  (`full_pattern_universe()`, the `TARGETED/DEPENDENCY/SAFETY/MANDATORY_SIGNOFF` classes,
  driven by a real `git diff` and `.dv-harness/requirements.csv`). Neither has any notion of a
  configuration dimension, a legal-value set, or a combination. Confirmed NEVER_BUILT.
- Spec section 232 read at `CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md:7732`.

## 2. What was built

**`dv_harness/config_variant_coverage.py` (new, 1026 lines)**

- `ConfigSpace` / `ConfigDimension` / `Constraint` / `CriticalCombination` -- a declared config
  space: named dimensions with legal values, `forbid` clauses (partial assignments that may
  never appear), and declared critical combinations (possibly only partially pinned).
  Every structural contradiction raises `ConfigSpaceError` naming the offending declaration.
- `generate_covering_array(space, strength=2)` -- **IPOG (In-Parameter-Order-General)**,
  cited in code and in the emitted artifact: *Lei, Kacker, Kuhn, Okun, Lawrence, "IPOG: A
  General Strategy for T-Way Software Testing", IEEE ECBS 2007* -- the strength-t
  generalisation of Tai & Lei's IPO (2002) and the algorithm behind NIST ACTS.
  **Why this one, not a heuristic:** deterministic (no random restarts, so a plan is diffable
  and reviewable), generalises to any t >= 2 with one implementation (t=3 needs no second
  mechanism), and its horizontal/vertical-extension structure accepts SEEDED rows -- exactly
  what section 232's "critical configurations must not be removed merely to reduce compute"
  needs.
- Constraint handling is sound rather than optimistic: validity checked at every assignment;
  forbidden interactions excluded from the target set **and reported**; a final REPAIR pass
  re-verifies independently and, for each remaining miss, runs a real exhaustive backtracking
  search -- only a pair that search **proves** has no legal full configuration is reported as
  `UNREACHABLE_UNDER_CONSTRAINTS`.
- `verify_coverage()` is a separate first-principles recomputation (re-enumerate targets,
  rescan rows), so it can check a hand-written list, and `build_plan()` runs it as part of
  producing a plan -- a plan artifact cannot claim coverage the verifier did not confirm. It
  also reports illegal rows, incomplete rows and undeclared values.
- `critical_combination_status()` checks section 232's own rule against the emitted plan
  rather than trusting the generator; `build_plan()` raises if any critical went missing.
- Artifact: `.dv-harness/regression/config_variant_plan.json` (atomic write, same convention
  as `change_impact._atomic_write_json`).

**`dv_harness/cli.py`** -- `dv-harness config-variants plan|verify --space <file>
[--strength N] [--combinations F] [--out F] [--json]`, sharing one `execute_verb()` with
`python -m dv_harness.config_variant_coverage` (the `power-intent`/`golden-scenario`
convention). Exit 0 full coverage, 1 real coverage finding, 2 broken declaration/usage.
Pure addition, two hunks, no existing line changed.

**`dv_harness_tests/fixtures/config_variants/synthetic_pcie_ep_space.json`** -- a fixture whose
own `description` states it is a test fixture and not any real DUT's configuration: 8
dimensions shaped like the ones section 232 names (gen_speed, lane_width, data_width,
clock_mode, feature_mode, compile_define, sku, vip_config), 3 constraints, 2 declared critical
combinations (one only partially pinned).

**`CLAUDE.md`** -- new section documenting the mechanism, the citation, and its stated limits
(appended at end; pure addition).

## 3. The real result on the real fixture

```
full cross product   : 6480          (3 x 5 x 3 x 3 x 4 x 3 x 2 x 2)
legal cross product  : 4662          (exactly enumerated under the 3 constraints)
selected             : 20 configuration(s)      reduction 0.99571
2-way interactions   : 267/267 covered, 0 uncovered, 0 unreachable, 3 excluded as forbidden
critical combinations: 2/2 present
```

20 is the information-theoretic floor for pairwise coverage of this space (product of the two
largest value counts, 5 lane widths x 4 feature modes), and the test asserts it as a **lower
bound** so a "smaller" answer would be caught as a bug rather than praised. At `--strength 3`
the same implementation emits 78 configurations covering all 1591 legal triples.

## 4. Why the tests are real proof

The central tests deliberately do **not** ask the module's own verifier whether it succeeded.
`_brute_force_uncovered_pairs()` / `_brute_force_uncovered_triples()` in the test file are
independent re-derivations written from scratch: they enumerate every legal interaction by
nested loops over the **fixture JSON** (with the constraint check also re-implemented from the
JSON) and rescan the emitted rows. The generator's bookkeeping, its `target_tuples()` helper
and its verifier are all bypassed.

Also proven: every emitted row is complete and legal; the verifier is non-vacuous (drop one row
and it names exactly the pairs the independent recount says went missing); a critical
combination survives pruning even when fully redundant; a critical combination that
contradicts a constraint, or that has no legal completion, is refused with a reason rather than
dropped; an individually-legal-but-uncompletable pair is reported `UNREACHABLE_UNDER_CONSTRAINTS`
and never counted as covered; illegal rows / undeclared values / incomplete rows are each
caught; generation is deterministic; the plan artifact round-trips and re-verifies on its own;
10 ternary dimensions (59049-point product) reduce to a low-double-digit covering set; and both
real CLI entry points run as real subprocesses with asserted exit codes.

## 5. Governance / safety

- No existing human-approval gate, governance boundary, or gate script was touched. This
  module deliberately has **no stage gate**: a gate that passed on a config plan nobody ran
  would be worse than none (same reasoning already recorded for `power-intent` and
  `golden-scenario`).
- Nothing runs, builds, submits, or approves. No LSF, no VCS, no remote transport, no
  production regression -- everything was exercised against the synthetic local fixture and
  `tmp_path`.
- Shared files: `dv_harness/cli.py` and `CLAUDE.md` were re-checked with `git status`/`git diff`
  before and after editing; both of my changes are pure additions in regions untouched by the
  concurrent pass (which had added `requirement-contract` to `cli.py`), and the commit staged
  exactly five paths -- `.dv-harness/events.jsonl` and the other passes' `.work/` reports were
  left unstaged.

## 6. Scoped down / deferred, honestly

Built as described, at full scope for the selector itself. Deliberately **not** built, and
disclosed in both the module docstring and CLAUDE.md:

1. **No composition with test selection.** Which tests run in each selected configuration stays
   `change_impact.select_regression()`'s answer; cross-multiplying the two is a cost decision
   this module does not own.
2. **The other section-232 selection methods are not mined.** Requirement-driven,
   historical-risk and change-impact combinations enter only as caller-declared
   `critical_combinations` carrying a real reason string. This module does not read
   requirements, failure history or a git diff to invent a "critical" combination -- a
   combination is critical because real evidence said so.
3. **Equivalence-class reduction is the author's act**, performed when a dimension's legal
   values are declared. "These two data widths are equivalent" is a protocol-behaviour claim
   needing primary evidence, so the selector does not make it.
4. **No stage gate and no engine wiring.** The plan is an input to a human's or a caller's
   regression decision, produced on demand.
5. `legal_cross_product_size` is exactly enumerated only up to `MAX_EXACT_ENUMERATION`
   (200,000); above that it reports `UNCOUNTED` with the real reason rather than a number
   nobody computed. Values must be JSON scalars; a structured value is refused, not
   stringified.
