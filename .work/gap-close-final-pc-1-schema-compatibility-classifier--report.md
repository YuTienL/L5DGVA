# PC-1 — Schema-compatibility classifier

**Status: DONE**
**Tests: `dv_harness_tests/test_schema_compat.py` — 161 passed, 9 skipped** (skips are
`format` names this `jsonschema` build does not assert: `date-time`, `uri`, `hostname`, …).
Neighbouring suites re-run clean: `test_env_manifest_fact_sources.py` +
`test_requirement_contract.py` (291 passed total), and 5 CLI suites (45 passed).

Commit: `04990de feat(schema): JSON Schema backward-compatibility classifier (PC-1)`

---

## 1. Gap independently re-verified (it was real)

- `grep -rn "schema_compat\|SchemaCompat\|BACKWARD_COMPATIBLE"` across the repo →
  **no module, no schema, no test**. No `dv_harness/schema_compat.py`.
- The only `backward_compatibility` in the tree is
  `dv_harness/system_command_plan.py:638 assess_backward_compatibility()` +
  `system_command_plan.schema.json`. That asks *"does this existing `command.txt`
  still run after the routing change"* — a different artifact and a different
  question. **Left completely untouched**; extending it would have been the
  parallel-mechanism mistake in reverse.
- Prior art confirmed as the shape to follow, not duplicate: `env_manifest.py:87`
  `SCHEMA_VERSION = "1.1"`, the module docstring's "SCHEMA VERSION" note, and
  CLAUDE.md:1414 *"Schema 1.1 is a breaking bump and deliberately so"*. That was a
  human reading a diff. This module makes the same judgment mechanically.

## 2. What was built

`dv_harness/schema_compat.py` (new) + CLI verb + `python -m` entry.

**Direction, stated once:** new schema is BACKWARD_COMPATIBLE iff every document
valid under the old schema is still valid under the new one — the direction the
env_manifest precedent cares about, and falsifiable by a single document.

Two mechanisms keep it from being the diff heuristic PC-1 warns about:

1. **Every keyword is either modelled or reported.** `modelled_keywords()` names the
   rules that actually exist. Anything else in schema position whose value changed →
   `UNMODELED_KEYWORD_CHANGED` / UNKNOWN. `pattern`, `format`, `multipleOf`, `oneOf`,
   `not`, `if`/`then`, `patternProperties`, `propertyNames`, `contains` are
   UNKNOWN-on-change **on purpose** — regex/branch containment is not decided here and
   is not faked. UNKNOWN has its own exit code (3) so it can never read as a PASS.
2. **Every BREAKING verdict carries a witness that real `jsonschema` validated.**
   The static rule proposes; `Draft202012Validator` disposes. A finding is `PROVEN`
   only when a document this module built genuinely passes the OLD validator and
   genuinely fails the NEW one. Where it cannot reach the change site, the finding is
   **kept** and marked `NOT_CONSTRUCTED` (fail-closed, same direction as
   `change_impact.py`).

Document construction is three real layers, not a template:
- `_synthesize()` — walks the schema's own keywords.
- `_sample_matching()` — emits a string in a regex's language by walking the AST
  **Python's own `re._parser`** returns, verified against the real `re` engine. All 11
  patterns in this repo's schemas are covered (`^Q-(VIP|DUT|ENV)-[0-9A-F]{8}$` →
  `Q-VIP-00000000`, etc.).
- `_repair()` — fixes the draft against the **real validator's own errors**, which is
  how constraints that only apply conditionally get satisfied without a constraint
  solver (`question.schema.json` pins `owner` per `domain` through an `allOf` of
  `if`/`then`; `research_evidence_card.schema.json` requires non-empty
  `supporting_evidence` only for a FACT). Fail-closed: an unrepairable draft raises
  rather than being returned.

**Self-check in the other direction.** Every classification also validates real
documents (a minimal instance of the old schema, plus any `--corpus` files) against
both schemas. A document that passes old and fails new overrides the static answer:
- after a COMPATIBLE verdict → `STATIC_RULES_INCOMPLETE` (a bug report against this
  module's own rule table, forcing BREAKING);
- after an UNKNOWN verdict → `UNDECIDED_CHANGE_PROVEN_BREAKING` (the rules declined;
  a document settled it).

**Repo mode + the env_manifest rule.** `classify_repo_schema_changes(root, base_rev)`
runs over `dv_harness/schemas/*.schema.json` between a git revision and the working
tree, and enforces the precedent: a BREAKING **or UNDECIDED** schema edit must bump the
owning module's `SCHEMA_VERSION` → `BREAKING_WITHOUT_VERSION_BUMP`. The owning module
is discovered by **reading the source** (`owning_modules_for_schema()`), not from a
hardcoded table, so a new schema/module pair is covered the day it lands.

CLI: `dv-harness schema-compat [--old F --new F | --base REV] [--corpus …] [--json]`.
Exit codes 0 compatible / 1 breaking / 2 NOT_AVAILABLE / 3 UNKNOWN.

## 3. Evidence it actually works

The headline is the repo's **own real history**, not a toy:

```
$ python -m dv_harness schema-compat --base 60bf3bd~1
schema-compat: BREAKING (16 schema(s) changed since 60bf3bd~1)
  dv_harness/schemas/env_manifest.schema.json: BREAKING
    [BREAKING] REQUIRED_KEY_ADDED at #/properties/dut_facts (PROVEN):
        key(s) ['address_map', 'clock_reset'] are now REQUIRED …
    [BREAKING] REQUIRED_KEY_ADDED at #/properties/env_topology (PROVEN):
        key(s) ['testplan_correspondence'] …
    [BREAKING] CONST_CHANGED at #/properties/schema_version (PROVEN): const '1.0' -> '1.1'
    [BREAKING] REQUIRED_KEY_ADDED at #/properties/vip_config (PROVEN):
        key(s) ['user_guide_refs', 'vip_release'] …
```

All four findings PROVEN, and they name exactly the four fact sources CLAUDE.md lists.
No `BREAKING_WITHOUT_VERSION_BUMP` — because `env_manifest.py` *did* bump 1.0 → 1.1.

Tests, all against real material:
- The real 1.0→1.1 bump replayed from git: asserted BREAKING, asserted to name all
  four fact sources, and its witness asserted to be a stale-1.0-shaped manifest the
  real 1.1 validator rejects (i.e. `load_env_manifest()` failing loudly, as designed).
- 10 breaking + 9 compatible + 8 undecided mutations of **real** `init_seq.schema.json`,
  one defect at a time; every breaking one must carry a witness that really passes old
  and really fails new (`assert_witness_is_real`).
- All 24 repo schemas: compatible with themselves; yield a validating instance;
  and adding a required key to each is BREAKING **with a PROVEN witness** (no skips).
- Repo mode on a scratch git repo: unbumped-breaking flagged, bumped-breaking accepted,
  undecided-edit also requires a bump, compatible edit silent, new file "nothing to
  break", deleted schema BREAKING.
- Two regression pins for bugs found and fixed during the build (below).

## 4. Real bugs the build surfaced (and the self-check caught)

- **`$ref` short-circuit.** `steps.items` is the byte-identical `{"$ref":
  "#/$defs/step"}` in both versions while `$defs/step` is what changed; an `==`
  shortcut reported a **retyped required field as BACKWARD_COMPATIBLE**. Found by the
  empirical layer firing `STATIC_RULES_INCOMPLETE` on my own rules. Fixed by making
  sameness resolve refs in both documents (`_Comparison._same` / `_refs_agree`), pinned
  by `test_the_ref_shortcut_bug_stays_fixed`.
- Witness mutations that produced documents which never validated against the old
  schema (so findings shipped `NOT_CONSTRUCTED`); reworked into
  materialize/resize/set-absent ops. All previously-unproven cases now PROVEN.

## 5. Deliberately not closed, stated rather than implied

- **A known soundness hole is left open and pinned as a test.** Dropping
  `patternProperties` reads as "one fewer assertion" statically, but under
  `additionalProperties: false` it *rejects* documents. Closing it properly means
  reasoning about a regex's key-space — the same regex containment this module refuses
  to fake — so it stays open, documented in the module docstring, and
  `test_a_corpus_document_that_breaks_refutes_a_compatible_static_verdict` uses it as
  the live demonstration that the empirical layer catches what the rules miss. No repo
  schema uses `patternProperties` today.
- Not wired into `engine.py` / any gate. It is a CLI verb and a library. Turning
  `BREAKING_WITHOUT_VERSION_BUMP` into a blocking gate is a policy decision, and
  three concurrent close-passes were editing shared files this session.
- It classifies; it does not migrate documents, edit schemas, or decide whether a
  breaking change is *allowed* — env_manifest's bump was breaking and correct.

## 6. Safety

- No human-approval gate touched, read, or referenced. No `HumanApprovalRequiredError`,
  `ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`, `policy.can_signoff()`
  or PR-governance code path is in this change.
- No build / regression / LSF submission. The only subprocesses are `git show` /
  `git diff` against this repo's own history (read-only) and scratch `git init` repos
  under `tmp_path`.
- `golden_flow_readiness.py` not touched.
- `cli.py` was shared with a concurrent `generation-readiness` pass: committed with the
  hand-scoped patch technique (`git diff > patch`, trimmed to my 2 of 4 hunks,
  `git apply --cached --check` then `--cached`). Verified after commit that the other
  pass's 2 hunks remain intact and unstaged.

## 7. Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\schema_compat.py` (new, 1533 lines)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_schema_compat.py` (new, 728 lines)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\cli.py` (+37: `schema-compat` parser + dispatch)
