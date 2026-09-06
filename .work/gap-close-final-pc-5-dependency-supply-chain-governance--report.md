# PC-5 — Dependency / Supply-Chain Governance — CLOSE-PASS REPORT

**Verdict: DONE**

**Test summary:** `dv_harness_tests/test_dependency_supply_chain.py` — **65 passed**; blast-radius
re-run across the touched files' real consumers — **~699 tests passed, 9 skipped, 0 failed**
(see "Test evidence" for the exact batches and one honest caveat about suite runtime).

---

## 1. Independent re-verification that the gap was real

Re-verified with my own searches before writing anything, per the close-pass rule that
audits can go stale:

```
grep -rn "supply_chain|dependency_audit|SBOM|pinned.version|vulnerability" -i  (whole tree)
```

The ONLY hits anywhere were inside `.work/workflow_scripts/loop_engineering_vi_pc_gap_close.js`
— i.e. the close-pass prompt describing this very gap. Nothing executable. Confirmed further:

- no module in `dv_harness/` or `tools/` read `pyproject.toml` or `requirements-harness.txt`
  as a dependency declaration;
- nothing anywhere compared a declared dependency against what is really installed;
- nothing anywhere asked whether a dependency version was pinned;
- `dv_harness/` had no module whose name or content concerned third-party components.

The gap was **total**, exactly as the audit said.

I also checked the environment's real advisory tooling rather than assuming: `pip_audit` and
`safety` are both absent (`importlib.util.find_spec` → False), and there is no offline OSV
database anywhere in the tree. That fact is what makes the vulnerability check honestly
NOT_AVAILABLE rather than fabricated-clean.

## 2. What I built

### `dv_harness/dependency_supply_chain.py` (new, ~700 lines)

**Inventory — this project's REAL declarations, from real files on disk:**

| source | what is read |
|---|---|
| `pyproject.toml` | `[build-system].requires`, `[project].dependencies`, every `[project.optional-dependencies]` group — each component carries the field it was declared in, so a build requirement and a runtime dependency stay distinguishable |
| every root `requirements*.txt` | one component per requirement line; a pip directive (`-r`, `--index-url`, …) is RECORDED as `DIRECTIVE_NOT_FOLLOWED` rather than silently dropped |
| installed DesignWare VIP | **`env_manifest.build_vip_release()` / `scan_designware_home()`**, reused verbatim |

**Reuse, not parallel mechanisms** (the project's hardest rule here):

- The VIP half is `env_manifest.build_vip_release()` — the existing real `$DESIGNWARE_HOME`
  filesystem scan — carried through with its three honestly distinct NOT_AVAILABLE reasons
  intact. There is **no second VIP scanner** and no VIP version is read from a document.
  This is held as a **property, not a claim**: a test patches
  `env_manifest.build_vip_release` and asserts the inventory changes — a hand-rolled walk
  would not respond to that.
- File integrity records go through **`env_manifest.file_ref()`** — the module's existing
  private `_file_ref` exposed as a public alias (the same "made public for this" pattern
  `uvm_structural_lint.config_db_call_sites()` set), **not copied**. Same property test.
- Version arithmetic is **`packaging`'s** `SpecifierSet`/`Version` (PyPA's PEP 440 reference
  implementation). Hand-rolling version comparison is how a supply-chain check silently
  accepts a version it should have refused.

**Three checks, each honest about what it is:**

1. **`PINNED_VERSION`** — real, runs everywhere. Only `==`/`===` without a wildcard is
   `PINNED_EXACT` (the only form naming ONE artifact); `==1.2.*` and `~=1.2.3` are
   `BOUNDED_RANGE`, `>=4.0` is `LOWER_BOUND_ONLY`, a bare name is `UNCONSTRAINED`. Severity
   HIGH/MEDIUM/LOW by how much room the declaration leaves. A VIP package whose install tree
   names no version directory is `VIP_PACKAGE_VERSION_UNKNOWN`.
2. **`DECLARED_VS_INSTALLED`** — real. Resolved against the REAL running interpreter through
   `importlib.metadata` (metadata read, not an import, so a package with an import-time side
   effect is never executed). Declared-but-not-installed and installed-outside-declared-range
   are both findings.
3. **`VULNERABILITY_ADVISORY`** — **`NOT_AVAILABLE` here, and it says so.** `pip-audit`/`safety`
   are probed BY NAME at run time; the OSV/PyPI APIs are network services a LOCAL_ANALYSIS run
   must not contact, and are never called. A project that HAS a real offline advisory database
   declares it (`.dv-harness/supply_chain/policy.json` or `--advisory-db`) and the check really
   runs — matching each component's **really installed** version (never the declared range: an
   advisory is about an artifact in use), reporting the database's own source, ISO as-of date
   and sha256, refusing a database that cannot state its own provenance, and reporting a
   database older than the policy ceiling (default 30 days) as its own finding.

**The load-bearing honesty rule:** `NOT_FULLY_CHECKED` outranks `POLICY_CLEAN` — the same rule
`platform_health.py` applies ranking UNKNOWN above HEALTHY. A fully-pinned, fully-installed
project with no advisory source reports `NOT_FULLY_CHECKED` and exits **2**, never a clean
security result. A component with no installed version is reported per-component as
*unmatchable*, so an inventory of uninstalled declarations can never read as a scanned one.

### Wiring

- `dv-harness supply-chain inventory|check|advisory-status` (`dv_harness/cli.py`, parser + dispatch)
- `python -m dv_harness.dependency_supply_chain` — one shared `execute_verb()`, the same
  convention `power-intent`/`golden-scenario`/`config-variants` use.
- Exit 0 `POLICY_CLEAN`, 1 a real policy finding, 2 a check that could not run / nothing to
  inventory.

### `dv_harness/env_manifest.py`

One addition only: the public `file_ref = _file_ref` alias with a comment stating why it was
exposed. No behaviour change; all three env_manifest test modules still pass.

### `CLAUDE.md`

One new section, "Dependency / Supply-Chain Governance (2026-09-06, PC-5)", following the
established shape: the negative grep that proved the gap, what is reused rather than rebuilt,
the three checks with the NOT_AVAILABLE one stated plainly, the bounded/disclosed list, this
repo's own real computed answer, and what the tests hold it to.

## 3. This repository's own real, computed answer

Not claimed — produced by the real command:

```
$ dv-harness supply-chain check
dependency supply chain: D:\DV\Task\DV_Agent_Harness_L5\v50  [POLICY_FINDINGS]
  components inventoried: 4
  PINNED_VERSION           CHECKED  (4 finding(s))
  DECLARED_VS_INSTALLED    CHECKED  (2 finding(s))
  VULNERABILITY_ADVISORY   NOT_AVAILABLE
    HIGH   UNPINNED_DEPENDENCY claude-code-sdk   (no version constraint at all)
    MEDIUM UNPINNED_DEPENDENCY setuptools        (>=68, lower bound only)
    MEDIUM UNPINNED_DEPENDENCY jsonschema        (>=4.0, lower bound only)
    LOW    UNPINNED_DEPENDENCY mcp               (>=2.1.1,<3, bounded range)
    MEDIUM DECLARED_DEPENDENCY_NOT_INSTALLED setuptools
    MEDIUM DECLARED_DEPENDENCY_NOT_INSTALLED claude-code-sdk
  NOT FULLY CHECKED: VULNERABILITY_ADVISORY -- this report is not a clean security result
```

Nothing in this repo is exact-pinned today, two declared dependencies are not installed for
this interpreter, there is no VIP install tree, and **no security scan ran**. That is a real
finding set a human can act on, and it exits 1.

## 4. Preserved boundaries (verified, not asserted)

- **No human-approval gate touched.** A test tokenizes this module's own source (comments and
  strings stripped) and asserts `ControlPlane`, `can_signoff`, `assert_human_approval`,
  `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`, `bsub`, `run_stage` and
  `subprocess` appear in **no executable code**.
- **No production build / regression / LSF submission.** The module submits nothing and shells
  out to nothing; every test runs against synthetic/local fixtures only.
- **Reads only.** A byte-level `sha256` snapshot of a whole project root is asserted unchanged
  across two full reports plus both other verbs; a bare project root is asserted to gain no
  files at all (no `StateStore`/`MemoryStore` is minted).
- **No stage gate**, deliberately: a gate that passed because no advisory database was present
  would be worse than none.
- **No verdict-vocabulary collision:** `assert_no_verification_verdict_vocabulary()` runs at
  import and is proven to really trip on an injected `PASS`.

## 5. Test evidence

`dv_harness_tests/test_dependency_supply_chain.py` — **65 tests**. The fixture is a REAL project
root whose every declaration is exact-pinned to a version `importlib.metadata` reports RIGHT NOW
(read at test time, never hardcoded, so the suite tests the module rather than the developer's
environment). Every rule is driven by MUTATING that one clean project ONE defect at a time.

Negative controls that give it detection power:

- the identical clean project **without** an advisory database is `NOT_FULLY_CHECKED`, not
  `POLICY_CLEAN` — the headline pair, and the whole point of the module;
- an advisory whose affected range **contains** the really-installed version fires, while the
  same advisory whose range stops **at** it does not (proves the matcher isn't just
  name-matching);
- an advisory for another ecosystem never matches a Python component;
- a stale database is a finding, a one-day-old one is not;
- an **empty but well-provenanced** database is usable (a real feed carrying nothing is still a
  real check);
- `==2.1.*` is proven **not** to read as an exact pin;
- patching `env_manifest.build_vip_release` / `env_manifest.file_ref` really changes the output
  (reuse held as a property);
- an unexplained exemption and a misspelled policy key are both refused;
- both entry points run as real subprocesses with exit codes 0/1/2 asserted, and the CLI and
  module are proven to produce identical JSON.

**One real bug was found by these tests and fixed:** `load_advisory_database()` originally used
`if not doc.get(required)`, which refused an advisory database with an **empty** advisory list —
a legitimate real feed carrying nothing currently affecting this ecosystem. Refusing it would
have pushed such a project back to permanent `NOT_FULLY_CHECKED`. Presence and non-emptiness are
now separate checks, with a dedicated regression test.

### Blast-radius re-run

The three touched tracked files have a precise blast radius — `env_manifest.py` (one public
alias), `cli.py` (one additive subparser + dispatch branch), `CLAUDE.md` (one appended section,
which matters because CLAUDE.md is a Tier-2 always-resident, size-capped artifact and is parsed
by the MCP index check). Every consumer of those was re-run:

| batch | result |
|---|---|
| `test_dependency_supply_chain.py` | **65 passed** |
| `test_env_manifest.py`, `test_env_manifest_fact_sources.py`, `test_env_manifest_generation_provenance.py`, `test_mcp_claude_md_index.py`, `test_mcp_env_manifest_integration.py`, `test_cli_preflight.py`, `test_source_authority.py`, + new suite | **241 passed** |
| `test_context_budget.py` (the resident-pack size cap over the now-longer CLAUDE.md) | **83 passed** |
| `test_cli_blackboard.py`, `test_cli_question_queue.py`, `test_cli_cross_project.py`, `test_cli_memory_commands.py`, `test_justfile.py` | **72 passed** |
| `test_config_variant_coverage.py`, `test_golden_scenario.py`, `test_schema_compat.py`, `test_vip_api_card.py` (the nearest-neighbour `execute_verb` CLI verbs) | **238 passed, 9 skipped** |

**Honest caveat:** I first attempted a single run over all 83 modules that mention `CLAUDE.md` or
import `dv_harness.cli`. That run was **killed by the tool harness's background-task lifetime
limit after ~50 minutes**, not by any test failure — this suite is extremely subprocess-heavy
(real `git push` hook e2e, real dashboards over HTTP, real gate-script subprocesses). I therefore
re-ran the genuinely affected consumers in the bounded batches above rather than reporting a
result I had not actually seen. A full-repo `pytest` run was not completed in this pass.

## 6. Scope: built vs. deliberately deferred

**Built:** the inventory (3 real sources), the pinned-version check, the declared-vs-installed
check, the advisory check's real machinery plus its honest NOT_AVAILABLE, the optional
policy-as-data file, both entry points, the CLAUDE.md section, 65 tests.

**Deliberately NOT built, and stated in both the module docstring and CLAUDE.md rather than
implied closed:**

- **Not an SBOM.** The inventory is what this project DECLARES plus what is really installed for
  those declarations — not a transitive dependency graph. Resolving one needs a resolver run
  against a package index, which is a network act. Every report carries that disclosure.
- **No bundled advisory feed.** Vendoring a snapshot of OSV into this repo would be a large,
  immediately-stale artifact and would need a network fetch to produce. The module supports a
  real declared offline database and reports NOT_AVAILABLE without one.
- **No stage gate and no engine wiring.** REACHED, not WIRED — no `run_stage()`/`advance()` call
  site invokes it, no graph node declares it, it is not on the dashboard. Same disclosed shape
  as `cross_project_mining.py`, `verification_strategy.py` and `resource_orchestrator.py`.
- **Non-Python, non-VIP ecosystems** (system packages, EDA tool installs beyond the VIP scan)
  have no declaration artifact in this project to read, so none is invented.

## 7. Files changed

- `dv_harness/dependency_supply_chain.py` — **new**
- `dv_harness_tests/test_dependency_supply_chain.py` — **new**
- `dv_harness/cli.py` — `supply-chain` parser + dispatch branch (hand-scoped; file was clean
  at HEAD before the change)
- `dv_harness/env_manifest.py` — public `file_ref` alias (one addition, no behaviour change)
- `CLAUDE.md` — one new section appended
