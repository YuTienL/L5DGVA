# SYS-1..SYS-4 gap close: subsystem discovery-and-present + EXISTS_* + readiness gate

**Verdict: DONE.**
**Commit:** `982b918` on `gap-close/env-manifest-fact-sources` (no push, no PR — per the
gh/PR-Only Governance Policy nothing was merged or pushed to a protected branch).
**Tests:** 38 new tests in `dv_harness_tests/test_subsystem_discovery.py` all pass
(`28.23s`); the 84 tests of the six related pre-existing modules
(`test_environment_mode_router`, `test_knowledge_center`,
`test_system_level_soc_composition_wiring`, `test_environment_mode_selection_gate`,
`test_protocol_and_environment_mode_engine_wiring`, `test_qualification`) still pass
(`169.01s`, 0 failures).

---

## 1. The audit finding, re-verified before building

Re-verified independently rather than taken on trust:

| Claim | Re-verified |
|---|---|
| `resolve_environment_mode()` refuses an empty request with `MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION` | Yes — `dv_harness/environment_mode_router.py:126-143` (pre-change line numbers) |
| Nothing computes a candidate list before selection | Yes — no discovery/listing function existed on-path |
| No `EXISTS_READY|EXISTS_PARTIAL|EXISTS_BLOCKED|EXISTS_UNKNOWN` anywhere in real code | Yes — only prose in the orchestration script |
| Neither `environment_mode_router.py`, `create_environment.py`, `subsystem_environment_registration_gate.py` nor `system_level_validator.py` references `knowledge_center` | Yes — confirmed by direct read of all four |
| `qualification_state` is a single collapsed maturity value, not a 13-factor derivation | Yes — `dv_harness/qualification.py:46-50` documents it as a deliberate narrow subset |
| This repo's real `subsystem_environment_registry.json` does not exist on disk | Yes — only `_template.json` (`{"subsystems": []}`) is present |

Running the new CLI against this repo confirms the honest empty state is preserved:
`0 registered`, `NOT_CONFIGURED`, `_(no candidate subsystem environments discovered)_`,
`refusal: NO_EXPLICIT_SELECTION`. Nothing was fabricated into this project's real audit
trail to make a mechanism look like it had fired.

---

## 2. What was built

### `dv_harness/subsystem_discovery.py` (new, 970 lines)

A new module rather than an extension, because every function reads **many** subsystems'
evidence at once and has no single-subsystem home — `environment_mode_router` reacts to a
selection already made, the two gate scripts judge one claimed payload, and
`dashboard.py`'s `_subsystem_registry()` structurally cannot show an unregistered
candidate. It **imports and composes** the real primitives, never copies them:

- `environment_mode_router.read_registered_subsystem_entries()` / `registry_path()` —
  the only registry reader used; `engine.py`'s `_persist_subsystem_registry_entry()`
  remains the only writer and nothing here mutates it.
- `qualification.SYSTEM_LEVEL_STATES` — reused by identity (a test asserts `is`), so no
  second qualification vocabulary is introduced.
- `environment_mode_router.resolve_environment_mode()` — `require_explicit_selection()`
  calls it rather than re-deriving the mode decision.

| Requirement | Function | Notes |
|---|---|---|
| SYS-1 | `discover_subsystem_candidates()`, `render_discovery_table()`, `require_explicit_selection()` | All six mandated columns, from three real sources (registry, declared candidates, the requested set) |
| SYS-2 | `classify_subsystem_existence()`, `classify_registry_claim()` | The five-way enum; the second is the registry-evidence-only variant the gate script can honestly compute |
| SYS-3 | `knowledge_center_subsystem_check()` | Contradictions + staleness against repository evidence |
| SYS-4 | `probe_environment_artifacts()`, `readiness_factors_from_evidence()`, `derive_subsystem_readiness()` | 13 factors, each independently probed |

**SYS-1 — the six columns.** `SUBSYSTEM / ENVIRONMENT PATH / KNOWLEDGE CENTER STATUS /
READINESS / PROTOCOL / VERSION-SHA`, versus the 2 of 6 the dashboard rendered. Candidates
are the union of the real registry, the project's declared
`.dv-harness/soc-composer/subsystem_candidate_sources.json`, and any name in the request
that neither knows about (so a request for a nonexistent subsystem gets a `NOT_FOUND` row
rather than silence). When no candidate-sources file is declared, the registry entry's own
`environment_manifest` parent directory supplies the path — the registry alone is
sufficient, and the absent file reports `NOT_CONFIGURED`, never an invented candidate.

**SYS-2 — the five-way enum, all five reachable.** One test builds a single synthetic
project that produces all five classes at once and asserts set equality with
`EXISTENCE_CLASSES`. `EXISTS_UNKNOWN`, which the audit correctly said had no code analog,
now has two real ones: an environment tree that cannot be opened, and a claimed
`release_sha` that disagrees with the registry — "it exists, but this evidence cannot tell
you which version you have" is neither a PASS nor a FAIL, and guessing either way would be
the fabrication SYS-2 forbids. `NOT_FOUND` carries SYS-2's own next action
(`SCOPE_CORRECTION_OR_SEPARATE_SUBSYSTEM_CREATION_WORKFLOW`, "forbids inventing").

**SYS-3 — through the existing client, not beside it.** `knowledge_center.py` gained
`SUBSYSTEM_RECORD_FIELDS` (the requirement's own 21 fields),
`normalize_subsystem_record()`, and two typed methods on the existing
`KnowledgeCenterClient` — `subsystem_record()` (routes through the existing `search` verb
on one fixed category) and `record_subsystem()` (through `add`). No new transport, no new
broker command, no second store. Matching is exact case-insensitive `SUBSYSTEM_ID`
equality, not a substring hit — a free-text search for `USB` returns `USB3_DEVICE`, and a
test asserts that is not accepted as this subsystem's record. Contradictions resolve by
fixed precedence (repository wins, KC value recorded as `overridden_value`), and the five
statuses stay distinct: `KC_NOT_CHECKED` / `KC_NOT_CONFIGURED` / `KC_UNAVAILABLE` /
`KC_RECORD_ABSENT` / `KC_RECORD_FOUND` — "the KC has nothing" and "the KC could not be
reached" are different facts.

**SYS-4 — 13 factors, derived not attested.** Each factor is probed from repository
artifacts; three are additionally **blocked** by the registry's own recorded verdicts
(`interface_compatibility != PASS`, `clock_reset_compatibility != PASS`,
`qualification_state` outside `SYSTEM_LEVEL_STATES`), so a recorded verdict outranks a
complete-looking file tree. Precedence is a documented total function: any blocker →
`BLOCKED`; nothing evidenced at all → `UNKNOWN`; all 13 present → `READY`; otherwise
`PARTIAL`. A single unevaluated factor therefore never rounds up to `READY`.

**Probe honesty.** Name-based matching is real repository evidence but is not proof of
content, so every `PRESENT` carries the actual matched paths, an unreadable root reports
`UNKNOWN` (never `ABSENT`), a truncated walk reports `UNKNOWN` for what it did not reach,
and a project may declare exact per-artifact paths that bypass the conventions entirely.

### Additive wiring (three files, no behaviour change when unused)

- **`environment_mode_router.py`** — optional `candidate_subsystems` input; both branches
  now report `candidate_subsystems` and `unselected_candidates`. This lets the existing
  refusal name what the user may choose from, and makes a deliberately unselected
  candidate visible instead of silently dropped ("the Harness must NOT assume that all
  available subsystems should be integrated"). Omitting the field reproduces the previous
  behaviour exactly — asserted by a test.
- **`tools/real_env/system_level_validator.py`** — `--classify` adds a `classification`
  key to the emitted JSON and changes no verdict, no exit code and no check. A test runs
  the real script as a subprocess with and without the flag and asserts the payload is
  byte-identical once the added key is stripped, so the `STAGE_GATES["SYSTEM_LEVEL"]`
  wiring is provably unaffected. The import is lazy and guarded — the default path never
  imports `dv_harness` at all, and an import failure degrades to
  `CLASSIFICATION_UNAVAILABLE`, never a fabricated class.
- **`dv_harness/cli.py`** — `dv-harness subsystem-discovery [--select ...]
  [--knowledge-center] [--json]`. Exit 0 for a pure listing, exit 2 when a selection is
  made that is not admissible. `--knowledge-center` is off by default because it is a real
  remote call.

---

## 3. The hard constraint, and how it is held

No System-Level UVM source, no System `command.txt`, no System Virtual Sequencer and no
command routing/adapter is generated anywhere in this change. Two tests enforce it rather
than a comment claiming it:

- `test_module_generates_no_system_level_artifacts` snapshots the whole project tree before
  a full discovery + selection run and asserts it is byte-for-byte identical afterwards —
  the module does not even mutate the registry it reads.
- `test_soc_composer_cross_subsystem_stubs_are_still_unimplemented` asserts
  `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` / `system_coverage()` still
  raise `NotImplementedError`. They were not touched.

Every report ends with the explicit `SYSTEM-LEVEL IMPLEMENTATION NOT STARTED` phase
boundary naming SYS-40 and its separate human approval.

---

## 4. Tests (38, on synthetic fixtures with real conflicting cases)

All fixtures are synthetic and built in `tmp_path`: a fake registry, fake environment
trees, a fake declared-candidate file, a fake Knowledge Center client with the real
client's method surface. No network call, no real registry touched.

Not a happy path only — the conflicting/ambiguous cases carry the coverage:

- **Two candidates resolving to one environment tree** (`PCIE` and `PCIE_GEN5`). Both rows
  are individually `EXISTS_READY`, so a per-row check alone would have waved it through;
  the conflict is detected at the candidate-set level, blocks the *selection* with
  `CANDIDATE_SET_CONFLICT`, and is reported for the user to disambiguate — never
  auto-merged. This is SYS-10's duplicate-resource problem arriving one step early.
- **A recorded `clock_reset_compatibility: FAIL`** against an environment where every
  artifact is on disk — a file-presence view would have said `READY`; the recorded verdict
  wins and lands `EXISTS_BLOCKED` / `BLOCKED`.
- **A KC record whose `GIT_SHA` and `READINESS` contradict the repository** — the
  repository value wins, the KC value is recorded as `overridden_value`, the record is
  flagged stale, and the report renders both.
- **A `release_sha` mismatch** between claim and registry → `EXISTS_UNKNOWN` through the
  real gate script.
- **An environment on disk that was never registered** → `EXISTS_PARTIAL`, not `READY`.
- **A registry entry missing a required field** → `EXISTS_PARTIAL` naming the field.
- Plus: all five existence classes reachable in one project; all four readiness values
  reachable; one blocker outranking 12 healthy factors; a single `UNKNOWN` factor not
  rounding up; declared artifact paths beating the name conventions; unreadable tree →
  `UNKNOWN` not `ABSENT`; the four non-found KC statuses staying distinct.

**Drift guard.** `REGISTRY_REQUIRED_FIELDS` is a third statement of a contract also stated
in `subsystem_environment_registration_gate.py` and `system_level_validator.py`, which stay
standalone stdlib-only subprocesses and cannot import it. A test AST-parses both scripts
and asserts all three agree — the same pattern `source_authority.assert_doc_matches_code()`
already uses, rather than a risky refactor of two live gate scripts.

---

## 5. Resulting verdicts

| Req | Before | After |
|---|---|---|
| SYS-1 | PARTIALLY_WIRED (refusal only; 2 of 6 columns) | **WIRED_AND_FIRING** — `discover_subsystem_candidates()` + `render_discovery_table()` + `require_explicit_selection()`, all six columns, reachable via `dv-harness subsystem-discovery` |
| SYS-2 | PARTIALLY_WIRED (binary PASS/FAIL; no enum) | **WIRED_AND_FIRING** — five-way enum, all five reachable, also surfaced by the real gate under `--classify` |
| SYS-3 | DORMANT for this purpose | **WIRED_AND_FIRING** — typed accessors on the existing client, 21 fields, contradictions + staleness reported |
| SYS-4 | PARTIALLY_WIRED; derivation NEVER_BUILT | **WIRED_AND_FIRING** — 13-factor `READY/PARTIAL/BLOCKED/UNKNOWN` derivation from probed evidence plus recorded registry verdicts |

## 6. Disclosed limits

1. **The artifact probe is name-based** unless a project declares exact paths. That is real
   repository evidence and is what SYS-2 asks for, but a name match is not proof of
   content. Mitigated by citing matched paths, by the declared-path override, and by
   `UNKNOWN` (not `ABSENT`) for anything unexaminable — not eliminated.
2. **This repo has no multi-subsystem project of its own**, so its own discovery run is
   honestly empty. The mechanism is proven against synthetic fixtures, not against a real
   registered subsystem set — same standing limitation `CLAUDE.md` already discloses for
   mechanism #14, and deliberately not papered over by writing fabricated registry entries
   into this project's real audit trail.
3. **SYS-3's write half (`record_subsystem()`) has no production caller yet.** It exists so
   the read half has a matching shape on the same shard; nothing in the engine publishes
   subsystem records to the shared KC today. REACHED, not WIRED.
4. **`--classify` is opt-in**, so `STAGE_GATES["SYSTEM_LEVEL"]` does not yet request the
   classification. That is deliberate for this step: turning it on changes what a live gate
   emits, and this step's contract was to add the capability without altering any existing
   verdict path.
5. **SYS-5 onward is untouched** — per-subsystem workflow analysis, architecture analysis,
   `command.txt` analysis, resource inventory, dedup, and the integration/dedup matrices are
   later steps of this same sequence.
