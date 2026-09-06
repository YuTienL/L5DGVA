# SPEC-7 — Per-artifact generation provenance tuple (spec section 210)

**Status: DONE**

**Test summary:** 103 passed (38 new provenance tests + the 65 pre-existing
`test_env_manifest.py` / `test_env_manifest_fact_sources.py` tests), plus 229 passed across the
MCP + env-manifest suites, 202 passed across blackboard/doc-extract/generation-readiness/
requirement-contract, and 161 passed + 9 skipped in `test_schema_compat.py` — all green.

Commit: `cdd125a` on branch `gap-close/env-manifest-fact-sources`.

---

## 1. Independent re-verification (before building)

The audit's PARTIALLY_WIRED finding was confirmed by my own greps, not taken on trust:

- `grep -n "schema_version\|tool_version\|provenance\|generated_by\|agent" dv_harness/env_manifest.py`
  → `SCHEMA_VERSION = "1.1"` (line 87), `"generator": {"tool": ..., "version": SCHEMA_VERSION}`
  (line 1099), and the only `tool_version` in the file (line 711) is **pypdf's** version inside
  `vip_config.user_guide_refs[].extraction` — not the harness's. So `generator.version` was the
  only version-shaped field and it is the SCHEMA version: "which harness build produced this" was
  answerable only by misreading it.
- The real schema (`dv_harness/schemas/env_manifest.schema.json`) had
  `generator.required == ["tool","version"]` with `additionalProperties: false` — no room for an
  agent, an input or a SHA, i.e. the absence was structural, not merely unpopulated.
- No agent/skill identifier, no input reference, no `repository_sha`/`git_sha` anywhere in the
  module or the schema.
- `grep -rn "git_sha\|git rev-parse" dv_harness/git_governance.py` → only push/merge
  branch-protection; **no per-artifact SHA-stamping function**, exactly as the audit said.
- The existing git-SHA reader to reuse: `dv_harness/change_impact.py:167 resolve_sha(root, rev)`
  (a real `git rev-parse --verify <rev>^{commit}`), already used by `benchmark_dataset.py:755`
  for `harness_git_sha`. **Reused, not reimplemented.**
- SPEC-3 has landed (`dv_harness/requirement_contract.py`, `CONTRACT_FIELDS` includes
  `requirement_id`, plus `downstream_consumable()`), so the input reference uses the requirement
  contract form rather than the path-only fallback the task allowed.
- Agent self-identification convention confirmed by reading real profiles: the YAML front-matter
  `name:` of `.claude/agents/*.md` (e.g. `audit-change-governance-agent`, `research-architect`)
  and `.claude/skills/**/SKILL.md` (e.g. `git-push-gate`).

## 2. What was built

All four answers went into the **existing `generator` block** — never a parallel provenance record
beside it (`dv_harness/env_manifest.py`, schema bumped 1.1 → 1.2):

| tuple element | field | how it is obtained |
|---|---|---|
| schema version | `schema_version` / `generator.version` | unchanged |
| tool version | `generator.tool_version` | real `dv_harness.__version__` (15.0.0), deliberately distinct from `version` |
| agent/skill | `generator.agent` | caller-declared identifier, **checked** against the real `.claude` profiles by `known_generation_identifiers()` |
| input | `generator.input_ir` | SPEC-3 requirement contract by `requirement_id`, really located + validated + run through `requirement_contract.downstream_consumable()`; or a real file as path+sha256+bytes |
| git SHA | `generator.repository_sha` | the EXISTING `change_impact.resolve_sha()` |

New public API in `env_manifest.py`: `known_generation_identifiers()`,
`build_generation_agent()`, `build_input_ir()`, `build_repository_sha()`,
`build_generator_block()`, `tool_version()`, `generation_provenance()`, `provenance_gaps()`,
`assert_generation_provenance_complete()`, plus `GenerationProvenanceIncompleteError` and
`InputIrDeclarationError`. `generate_env_manifest()` / `generate_and_write()` take
`generated_by`, `project_root`, `profile_root`, `input_requirements_path`,
`input_requirement_id`, `input_file_path`, `require_provenance`.

CLI (`dv-harness env-manifest generate`): `--generated-by`, `--input-requirements`,
`--input-requirement-id`, `--input-file`, `--project-root`, `--require-provenance`.

Honesty properties that carry the weight:

- **Nothing is fabricated or defaulted.** Undeclared agent / input / project root each record
  `NOT_DECLARED` naming the flag that would answer them. A declared identifier matching no real
  profile is `DECLARED` + `resolution: NOT_FOUND` — *recorded, never accepted as verified*. A
  deployed copy with no `.claude` tree reports `PROFILE_TREE_NOT_AVAILABLE`, deliberately distinct
  from `NOT_FOUND` ("nobody could check" ≠ "we checked and it is fake"). An unresolvable HEAD is
  `NOT_AVAILABLE` with its reason, never a SHA.
- **The generator's identity cannot be rerouted by a caller.** `repository_sha.harness` is always
  read from `HARNESS_REPOSITORY_ROOT` (derived from `__file__`), never from a caller-supplied path.
- **The requirement citation is checked, not just named.** Citing `REQ-X` records that requirement's
  own five-value status and `downstream_consumable()`'s real verdict — whether a generator was
  *entitled* to build from it.
- **Provenance never fails generation by default**; `--require-provenance` is the strict opt-in,
  the same disclosed-default shape as `require_tier` / `require_phy_boundary`.
- The flattened tuple also reaches the `env_manifest` **Blackboard topic** as
  `generation_provenance`, so a reading stage sees who/what/which-commit without opening the file.

### The one contract this deliberately narrows, stated rather than hidden

`env.manifest.json`'s diffability rule ("regenerating from unchanged inputs is byte-identical, so a
real diff means a real underlying change, never clock noise") now admits one new source of diff: a
manifest regenerated after the **harness itself** moved commit differs in
`generator.repository_sha.harness`. That is a real underlying change — a different generator
produced the artifact, which is the fact section 210 exists to record — not clock noise. Unchanged
inputs *and* an unchanged harness commit still produce a byte-identical file, asserted by a test.
Both the module docstring, the schema description and CLAUDE.md now say this explicitly.

1.1 → 1.2 is a **breaking** bump (the keys are REQUIRED), for the same reason 1.0 → 1.1 was: a
stale manifest fails `load_env_manifest()` loudly rather than presenting an untraceable artifact as
a traceable one. `test_schema_compat.py` (the concurrent PC-1 pass's classifier, which enforces
exactly this "breaking edit ⇒ version bump" rule) passes against the change.

## 3. Preserved boundaries

- **No human-approval gate touched.** `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`,
  `ControlPlane.approve`, `policy.can_signoff` and SYS-39/40's stop are not referenced anywhere in
  this change; nothing here approves, arbitrates or authorizes anything.
- **No stage gate added.** This records and checks provenance; it decides no verdict.
- Nothing runs a build, a regression or an LSF submission. Every test uses synthetic fixtures, a
  throwaway local git repo, and this checkout's own real `.claude` profiles.

## 4. Tests (`dv_harness_tests/test_env_manifest_generation_provenance.py`, 38 tests)

Detection power comes from asserting against sources **outside** the code under test:

- the harness SHA vs. an **independent** `git rev-parse HEAD` the test runs itself;
- the project SHA vs. a **real throwaway git repo with a real commit** created by the test;
- `tool_version` vs. the real `dv_harness.__version__` (and asserted `!=` `version`);
- the agent identifier vs. the **real `.claude` profiles**, with `totally-invented-agent` as the
  negative control and a `PROFILE_TREE_NOT_AVAILABLE` control;
- the input digest vs. an independently computed `hashlib.sha256`;
- the contract cross-check driven through the **real** `requirement_contract` validator
  (`PARTIAL` ⇒ `downstream_consumable: False`; a record missing `checker` ⇒ `INVALID`).

Reuse is held as a **property**, not a docstring claim:
`test_repository_sha_is_read_through_the_existing_change_impact_resolver` monkeypatches
`change_impact.resolve_sha()` and asserts the manifest changes — a second hand-rolled
`git rev-parse` inside `env_manifest.py` would not respond to it.

Also covered: every provenance key is schema-REQUIRED (parametrised deletion), a 1.1-shaped
manifest is refused by `load_env_manifest()`, an invented `resolution` value is refused,
`--require-provenance` names every gap at once, byte-identical regeneration at the same commit,
the moved-commit diff being confined to exactly the SHA field, the Blackboard topic, and the real
CLI front door as a subprocess (exit 0 declared / exit 1 with `--require-provenance` undeclared /
exit 0 undeclared without it).

## 5. Concurrency discipline

`dv_harness/cli.py` and `CLAUDE.md` are shared with three concurrent passes. Both were staged with
the hand-scoped patch technique (`git diff > patch`, split by hunk, keep only my hunks,
`git apply --cached --check` then `--cached`); patches kept at `.work/patches/`. `dashboard.py` was
not touched. Verified after committing: the other passes' `cli.py` hunks remain uncommitted in the
working tree, and nothing was lost from `CLAUDE.md` (another pass staged the whole file between my
`apply --cached` and my `commit`, so its section rode along in my commit — content-preserving, and
confirmed present in HEAD).

## 6. Deferred (stated, not implied closed)

- **Scope is `env.manifest.json` only.** `create_environment()`'s own `environment_manifest.json`
  and the generated `.sv` files carry no provenance tuple yet. Extending the tuple to every
  generated artifact is a separate, larger pass.
- **Nothing produces contract-shaped requirement records in this repo yet** (SPEC-3's own disclosed
  residual), so the `input_ir` contract form is exercised by real synthetic contracts in tests and
  is dormant in production until a project supplies them — the same disclosure SPEC-3 makes.
- **No engine call site sets `generated_by`.** `engine._refresh_env_manifest_topic()` only MIRRORS
  an existing manifest and never generates one, so there is no autonomous-path generation call to
  attribute. The provenance flags are reached from the real CLI front door and from
  `doc_extraction_fanout`'s `generate_and_write(**kwargs)` pass-through; making a graph node
  declare its own identifier would need a generation call site that does not exist today.
- **`--require-provenance` defaults off**, deliberately, so an un-migrated project is never
  retroactively failed.
