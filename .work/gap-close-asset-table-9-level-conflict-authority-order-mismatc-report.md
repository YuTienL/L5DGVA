# Gap close — 9-level conflict authority order + mismatch → question-queue escalation

Scope: exactly the two requirements handed to this pass. Audit only for the
READY parts, real code for the PARTIAL/BLOCKED parts. 2026-09-04.

**Verdict: DONE.**

| Requirement | Audit verdict in | Verdict out |
|---|---|---|
| 9-level conflict authority order | PARTIAL (prose only, no code, no applier) | **READY** |
| Mismatch → question-queue escalation, both evidence paths | BLOCKED (no wire between real detectors and the real queue) | **READY** |

Test summary: `419 passed` over the 10 directly-affected suites
(`test_source_authority.py` 35 new + `test_reference_pattern_audit.py`,
`test_address_map_verifier.py`, `test_question_queue.py`,
`test_cli_question_queue.py`, `test_connectivity.py`, `test_run_profile.py`,
`test_run_profile_to_justfile.py`, `test_four_key_judgments_enforcement.py`,
`test_asset_processing_artifacts.py`), plus the full `dv_harness_tests` suite.

---

## 1. Re-confirmation of the audit's cited evidence (all of it held)

- `docs/RUN_PROFILE.md:26-32` — the 9-level paragraph is there, verbatim as
  quoted. Confirmed by reading it, and now by machine
  (`parse_documented_order()` returns exactly those 9 phrases).
- `tools/verification_flow/evidence_source_priority_gate.py` — 9 lines total,
  `ORDER = ['EXISTING_PROJECT_FILES' ... 'ASK_USER']`. Confirmed a genuinely
  different list answering a different question.
- `dv_harness/reference_pattern_audit.py` — `find_symmetry_asymmetries()` →
  `AsymmetryFinding` → `audit_directory()` → JSON/`format_report()`; the only
  real call site was `dv_harness/cli.py`'s `reference-audit` branch. No path
  to `question_queue`. Confirmed.
- `dv_harness/uvm_generator/address_map_verifier.py` — `doc_status`
  AGREES/DISAGREES/NOT_AVAILABLE recorded as a generated-Verilog comment,
  `"a document disagreement does not block committal"`. Zero `question_queue`
  references. Confirmed.
- `dv_harness/connectivity.py:2698` `build_t4_question_queue_entry()` — the
  one real, existing escalation path, for bind/topology T4 only. Confirmed,
  and deliberately reused as the pattern (not duplicated) below.
- `dv_harness/schemas/question.schema.json` — one correction to the audit's
  framing worth recording: the schema is `additionalProperties: false` and
  has **no `context` field**, so `add_question(context=...)` feeds tier
  classification but is never persisted. "Carrying both evidence paths"
  therefore had to be built out of fields that *are* persisted (`question`,
  `options[].rationale`, `context_path`), which is what the new code does.

## 2. What was built

### `dv_harness/source_authority.py` (new, 470 lines)

The order as executable code, not prose:

- `AUTHORITY_ORDER` — 9 `AuthoritySource` records, rank 1 (highest) … 9, each
  carrying the doc's exact phrase, a description, and the aliases real call
  sites already use (`decoder` → `dut_rtl`, `sim.log` → `simulation_result`,
  `command.txt` → `reference_command_txt`, …).
- `REGISTER_FILE_SUBORDER = ("dut", "global")` — the `(DUT then Global)`
  clause tier 4 carries, made a real comparison (`sort_key()` returns
  `(rank, subrank)`) instead of a parenthetical a reader had to remember.
- `normalize_source()` / `authority_rank()` / `outranks()` — an unknown
  source **raises** (`UNKNOWN_AUTHORITY_SOURCE`) rather than defaulting to
  last, because the natural silent default makes an unknown source lose every
  conflict it takes part in, quietly.
- `SourceClaim` — source + claim + **mandatory non-empty `evidence_path`**.
  A claim without a citation is unconstructable; that is how "the escalation
  carries both evidence paths" is guaranteed at the near end rather than
  checked at the far end where it is already too late.
- `resolve_conflict()` → `NO_CONFLICT` / `RESOLVED` (winner, losers,
  `authority_gap`, and the exact ordering sentence applied) /
  `UNDECIDABLE_SAME_AUTHORITY` (two claims at the same tier disagree — the
  order cannot break that tie and does not pretend to). Fewer than 2 claims
  raises: "resolving" one claim is just believing the only thing you read.
- `parse_documented_order()` / `assert_doc_matches_code()` — the markdown
  paragraph is **parsed** and compared level-for-level against the code.
  Without this, moving the order into code would only have created a second
  place for it to be wrong. Drift is a test failure in both directions
  (`test_doc_code_drift_is_detected` swaps levels 8/9 in the doc text and
  asserts `first_difference == 8`).
- `escalate_conflict()` — the wire. Files a Tier-3 question through the real
  `question_queue.QuestionQueueStore.add_question()`, reusing its machinery
  wholesale (derived Q-ID, `route_owner()`, `classify_tier()`); nothing is
  re-implemented. `CONFLICT_QUESTION_CONTEXT = {"affects_spec_intent": True}`
  mirrors `connectivity.T4_QUESTION_CONTEXT`'s pattern: a fixed, honest
  context dict, not a hardcoded tier.
  - **The two options ARE the two sides**, and each option's `rationale` is
    that side's evidence path. Both paths are also inlined into the question
    text, so a digest rendering only `question` still shows both.
  - `assert_both_evidence_paths_present()` runs **before** the record is
    handed to the store, so a conflict question naming a disagreement without
    citing where both halves live cannot reach the queue at all.
  - More than 3 sides is refused, never truncated to the schema's 3-option
    limit — truncating would drop a source's evidence path with it.
  - **Idempotent on `question_key`.** `QuestionQueueStore.add_question()`
    appends unconditionally: two asks of the same key mint the same Q-ID but
    produce two records. Fine for the hand-called escalations it was written
    for, wrong for a detector wired into a rerunnable audit. Found for real,
    not by inspection — running the wired audit twice over the actual
    `reference/bfm_patterns/` corpus took the queue from 12 questions to 24,
    all duplicate ids. `escalate_conflict()` now returns the EXISTING record
    instead, so a re-detected mismatch surfaces its current status (still
    OPEN, or since ANSWERED in place) rather than a fresh OPEN copy that
    hides the answer.

### Wire 1 — `dv_harness/reference_pattern_audit.py`

`asymmetry_conflict()` + `escalate_asymmetries()`, and
`audit_directory(..., question_store=)`.

Both halves of a host/DUT write asymmetry come from the **same** tier-2
source (the reference pattern file), so `resolve_conflict()` returns
`UNDECIDABLE_SAME_AUTHORITY` every time — which is the honest answer and
exactly why escalating is mandatory rather than advisory: no amount of
re-reading the pattern settles whether the missing DUT-side write is a real
bug or intended for that speed/mode. The absence side is cited **as an
absence** (`"synth_asym.txt (whole file): no DUT-side write to base BB00
offset 0020"`), which is what makes an absence checkable by whoever receives
it. `domain="dut"` → owner `designer` via the queue's own routing table.

`question_store` is opt-in so the existing report-only callers keep a pure,
side-effect-free read (`test_audit_without_a_store_files_nothing`).

### Wire 2 — `dv_harness/uvm_generator/address_map_verifier.py`

`doc_disagreement_conflict()` + `escalate_doc_disagreements()`, and
`verify_address_map(..., question_store=)`.

**The module's "never gating" contract is preserved exactly.** The decoder
(tier 3) still wins over the register document (tier 6) mechanically, the
returned verified entries are byte-identical with or without a store, and the
`` `define `` is still emitted with its loud `// ** DOC DISAGREEMENT (not
blocking …` comment — asserted directly by
`test_escalation_does_not_make_committal_blocking`. What was missing is a
different question, which the doc-status comment asked nobody:

- *"Which base address do I use?"* — decided mechanically by the authority
  order. Never blocks. This module already answered it correctly.
- *"Which of these two artifacts is stale/wrong?"* — not decidable by the
  authority order, and left entirely unasked. A stale register document
  silently outlived every generation run because the only record of the
  disagreement was a `//` comment in generated Verilog a reader had to
  already be looking at.

Disclosed judgment, made explicit in the code rather than buried:
`DOC_AUTHORITY_SOURCE = "controller_doc"` (tier 6) rather than
`register_file` (tier 4), because this module's own contract calls it "a
register document, read LAST, as corroboration only" — a human-written
programming document, not a machine-readable register description. It is
overridable (`doc_source=`), and **cannot change the outcome either way**,
since the decoder is tier 3 and outranks both candidates.

### CLI (`dv_harness/cli.py`)

- `dv-harness authority order [--json]` — the 9 levels.
- `dv-harness authority check-doc` — doc/code sync, exit 1 on drift.
- `dv-harness authority resolve <claims.json|-> [--json] [--escalate
  --subject … --domain …]` — apply the order; exit 0 on NO_CONFLICT, 1
  otherwise.
- `dv-harness reference-audit … --escalate` — the audit's findings into the
  real queue under `--project-root`.

Real callers, not a primitive with none — the specific failure mode commit
`becc1d7` was itself closing two days ago.

### Docs

- `docs/RUN_PROFILE.md` — new paragraph after the order stating that the
  prose is now parsed and held to the code, naming `resolve_conflict()` /
  `escalate_conflict()`, and stating explicitly that this is **not**
  `evidence_source_priority_gate.py`'s `ORDER` (both are 9 items long, which
  has already caused one mis-identification: a discovery order vs. a conflict
  order).
- `CLAUDE.md` — new `## Source Authority Order: 9 Levels, Enforced
  (2026-09-04)` section: the 9 levels, what is now machine-enforced, the
  not-the-other-9-item-list warning, and both wires including the explicit
  "this does not make committal blocking" note for the address-map path.

## 3. Tests

`dv_harness_tests/test_source_authority.py` — 35 tests, no mocks anywhere;
every escalation test drives a real `QuestionQueueStore` on `tmp_path` and
reads the question back **off disk**.

The ones that would actually catch a regression that matters:

- `test_doc_and_code_orders_are_in_sync` + `test_doc_code_drift_is_detected`
  — the pair. The first alone would pass forever on a parser that returns
  whatever it likes.
- `test_is_not_the_evidence_source_priority_gate_order` — a real guard
  against the two 9-item lists being merged by a future reader.
- `test_escalated_question_carries_both_sides_evidence_paths` — the literal
  requirement, asserted against the persisted record (options' rationales,
  and inline in the question text).
- `test_a_question_missing_an_evidence_path_can_never_be_persisted` — the
  pre-persist guard exercised directly.
- `test_escalation_does_not_make_committal_blocking` — the address-map
  module's own non-gating contract, byte-for-byte.
- `test_re_escalating_the_same_conflict_does_not_grow_the_queue` and
  `test_re_escalation_returns_the_answered_record_not_a_fresh_open_copy` —
  idempotence; what makes wiring escalation into `audit_directory()` itself
  safe instead of a thing a human has to remember to run exactly once. The
  first version of this test asserted only that the two asks shared a Q-ID,
  which they did while the queue silently doubled.
- `test_real_usb_p2_switch_en_asymmetry_becomes_a_real_question` — the real
  DE corpus at `D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns/`
  (read-only; skipped, not failed, where absent). 12 findings → 12 Tier-3
  blocking questions owned by `designer`; the known `usb_p2_switch_en` one
  cites `USB2_bulkin.txt:79 \`HOSTWRITE4B(32'h161A_0020) //
  usb_p2_switch_en=1, ss_hdshk_req=0` on the written side and "NEVER
  programmed DUT-side (base 1272)" on the absent side. Three consecutive
  runs leave the queue at 12. This is the test that exposed the
  duplicate-append defect above — the synthetic fixture has one finding, so
  a doubled queue and a correct one differ there by a single record.
- `test_claim_without_evidence_path_is_unconstructable`,
  `test_unknown_source_is_refused_not_ranked_last`,
  `test_more_than_three_sides_is_refused_not_truncated` — the three silent
  defaults that would have hollowed the mechanism out.
- 3 CLI tests via real subprocess (`authority check-doc`, `authority order
  --json`, `reference-audit --escalate` filing real questions and keeping its
  exit-1-on-asymmetry contract).

## 4. Honest residuals

- **Escalation is opt-in at both wires** (`question_store=None` by default).
  Deliberate: `audit_directory()` and `verify_address_map()` have existing
  pure-read callers, and silently giving them a filesystem side effect would
  be a worse change than the gap. The CLI passes a store on `--escalate`; a
  generator pipeline that wants it must pass one too.
- **`resolve_conflict()` is not automatically applied by every consumer of a
  fact.** It is now real, tested, CLI-exposed, and called by both mismatch
  detectors — but a stage that reads a doc and an RTL file and forms its own
  opinion is still free not to route through it. Making every fact read go
  through a conflict resolver is a separate, much larger effort
  (it is the shape of the MCP-first routing work), not this one.
- The reference-pattern escalation's `domain="dut"` is fixed. A host-side-only
  asymmetry is still a DUT-programming question in this project's own idiom,
  but a project where the host block has its own owner would want that
  routable.
