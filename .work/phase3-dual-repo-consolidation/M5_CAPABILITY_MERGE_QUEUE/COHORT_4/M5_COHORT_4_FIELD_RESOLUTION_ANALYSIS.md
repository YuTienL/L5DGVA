# CAP-ATL-007 — intake_field_resolution.py — Field Resolution Analysis

## Operationality in Parent (real, verified, not assumed)

`IMPLEMENTED=YES`, `WIRED=YES`, `CONSUMED=YES`, `TESTED=YES`,
`OPERATIONAL=YES` in Parent. Real, scoped caller sweep found **9 real
Parent production modules** importing/consuming
`intake_field_resolution.py`: `intake_contract.py`, `intake_discovery.py`,
`intake_interfaces.py`, `intake_loader.py`, `intake_package.py`,
`intake_resume.py`, `intake_schema.py`, `intake_validation.py`,
`intake_workbook.py` — plus **10 test files**. Its own 24 tests
independently re-run in Parent's own tree: **24/24 pass**.

This is a genuinely mature, load-bearing Parent capability — **not** an
orphaned module like `task_boundary_conformance.py` was (before its own
correction this Cohort). It is deeply embedded in Parent's own separate
intake pipeline family (`intake_schema.py`/`intake_workbook.py`/
`intake_loader.py`/`intake_package.py`/`intake_resume.py`/
`intake_discovery.py`/`intake_contract.py`/`intake_interfaces.py`/
`intake_clarification.py`), none of which exist in canonical, and all of
which are **out of this Cohort's registered scope** ("Cohort 4 is limited
to the registered contract capabilities associated with
`task_boundary_conformance.py` and `intake_field_resolution.py` plus
strictly necessary Canonical contract/schema dependencies... Do not expand
into unrelated Parent governance modules").

## The scoping decision this makes necessary

Migrating the WHOLE Parent module verbatim (imports intact) would either
(a) silently pull the 9-module Parent pipeline family in as a transitive
dependency — a real scope violation — or (b) leave the migrated module
with broken imports. Neither is acceptable. The resolution: migrate the
CONTRACT/ALGORITHM content (the 8-attribute OpenSpec model, the
`SourceKind`/`Origin`/`ValidationState`/`ConfirmationState`/`Confidence`
enums, `Candidate`/`EffectiveValue` dataclasses, the no-precedence
evidence-based `_decide()` resolution algorithm, the question-gate logic)
as an ADAPTED canonical module with only the two dependencies that
genuinely are canonical-general-purpose and already exist:
`dv_harness/source_authority.py` and `dv_harness/question_queue.py` — both
independently verified compatible (see Compatibility notes below), not
assumed.

## Real established semantics (from code, callers and tests — not inferred from field names)

| OpenSpec attribute | Real semantics (verified from `intake_field_resolution.py` + its 24 tests) |
|---|---|
| `DeclaredValue` (`SourceKind.DECLARED`) | A user-typed value, always `Confidence.HIGH`, `source="user_workbook"`. **Not automatically the winner** — it is one `Candidate` among others, arbitrated the same way as any other, UNLESS passed via the separate `human_answer=` parameter (a distinct, always-wins short-circuit — `test_a_declared_value_has_no_authority_rank_so_it_can_only_be_resolved_by_a_human` proves a bare `DECLARED` candidate loses to authority-ranked evidence and stays `CONTRADICTED`, while `test_a_human_answer_resolves_a_contradiction_and_keeps_every_candidate` proves the separate `human_answer=` path always wins) |
| `AutoDiscoveredValue` (`SourceKind.AUTO_DISCOVERED`) | A value found by an `EvidenceProducer` on the evidence ladder; `Origin` defaults to `AUTO_DISCOVERED` too (unless the producer explicitly asserts a different origin) |
| `DerivedValue` (`SourceKind.DERIVED`) | A value computed from other evidence (e.g. `DATA_W*8`); same arbitration treatment as `AUTO_DISCOVERED`, distinguished only for the `to_openspec_record()` view |
| `EffectiveValue` | The single resolved value (or `None`), produced by `_decide()`. Carries `state`/`confidence`/`confirmation_state`/`evidence_refs`/`candidates`/`resolution_method`/`attempts`/`conflict` — the full audit trail, never just the bare value |
| `Confidence` | `UNKNOWN`/`LOW`/`MEDIUM`/`HIGH`, ranked. **Never breaks a tie among disagreeing candidates** — `test_confidence_alone_never_selects_a_winner_among_conflicting_values` proves a HIGH-confidence candidate does not beat a MEDIUM-confidence one when they disagree; confidence only gates `min_confidence` eligibility |
| `ValidationState` | `NOT_VALIDATED`/`VALID`/`INVALID`/`CONTRADICTED` — a TECHNICAL-validity axis (schema/rule/evidence check). `CONTRADICTED` is an OUTPUT of `_decide()`, never an input (`_reset_contradiction()` proves replayed recorded candidates start from their technical validity again, not their last verdict) |
| `ConfirmationState` | `NOT_CONFIRMED`/`CONFIRMED_BY_EVIDENCE`/`CONFIRMED_BY_USER`/`CONFLICT` — an ORIGIN/AUTHORITY axis, orthogonal to `ValidationState`. A value can be `CONFIRMED_BY_USER` (declared) yet still be technically `CONTRADICTED` if it disagrees with other evidence — proven directly by the `Candidate.confirmation_state` property's own docstring and by `test_a_declared_value_has_no_authority_rank_so_it_can_only_be_resolved_by_a_human` |
| `EvidenceRefs` | A de-duplicated union (`_union()`) of every SUPPORTING candidate's evidence refs; the `human_answer` path prepends the literal `"human_answer"` marker |

## Precedence / conflict semantics (instruction item 3 — explicit)

`_decide()`'s real algorithm, in order:
1. A `human_answer=` argument, if given, always wins (`HUMAN_CONFIRMED`, `Confidence.HIGH`, `CONFIRMED_BY_USER`) — the only true "precedence" in the whole model, and it is a human override, not a source-kind rule.
2. No eligible candidate -> `UNRESOLVED`, value `None`.
3. Exactly one distinct value among eligible candidates -> `SINGLE_SOURCE` (or `CONSENSUS` if ≥2 distinct sources agree).
4. ≥2 distinct values (a real conflict) -> try the 9-level `source_authority` order, but ONLY when every side has an evidence-backed, authority-ranked candidate (`_try_authority()`); a `DECLARED` candidate has no `authority` field set by default, so it can never win this step — confirmed by `test_a_declared_value_has_no_authority_rank_so_it_can_only_be_resolved_by_a_human`.
5. If authority resolution also fails (no ranked evidence on some side, or a tie) -> `CONTRADICTED`, value `None`, every candidate preserved with a `_mark_contradicted()` note explaining why.

**No SourceKind (DECLARED vs. AUTO_DISCOVERED vs. DERIVED) is ever given
precedence over another by name.** This is the single most important,
easy-to-get-wrong fact about this model — confirmed directly from code
(`_decide()` never branches on `c.kind`, only on `c.validation`/
`c.confidence`/`c.authority`/`groups`) and from tests (`test_two_distinct_
agreeing_sources_are_a_consensus`, `test_authorised_evidence_resolves_a_
conflict_by_source_authority_and_says_so`).

## Confidence != ValidationState != ConfirmationState (instruction item 4 — explicit preservation check)

All three verified as genuinely orthogonal axes, preserved unchanged in
the canonical adaptation:
- `Confidence` gates ELIGIBILITY (`min_confidence` threshold) only — never picks a winner among eligible candidates.
- `ValidationState` is a TECHNICAL-correctness axis, decided by a `validator` callback (schema/rule check), independent of who asserted the value.
- `ConfirmationState` is an ORIGIN/AUTHORITY axis, decided by who supplied the winning value and how (evidence consensus, source-authority arbitration, or a real human answer) — completely independent of whether that value later turns out `VALID`/`INVALID`/`CONTRADICTED`.

`test_a_declared_value_has_no_authority_rank_so_it_can_only_be_resolved_
by_a_human` is the sharpest proof of the three-way separation: a
`CONFIRMED_BY_USER`-capable candidate (a bare `DECLARED` value) still
ends up `CONTRADICTED` (a `ValidationState`-family outcome) with `value
is None`, because `ConfirmationState`'s "who asserted it" has no bearing
on `ValidationState`'s "is it technically resolvable against competing
evidence."

## AUTO_DISCOVERY_FIRST / MINIMAL_STRUCTURED_CLARIFICATION preservation (instruction item 5)

`resolve_field()` always runs every registered `EvidenceProducer` (evidence
ladder order) regardless of whether a `declared` value was supplied — the
declared value becomes just one more `Candidate`, never a short-circuit
that skips discovery. `unresolved_blank()` explicitly marks
`discovery_ran=False`, and `evaluate_question_gate()` REFUSES to ask about
any field where `discovery_ran` is `False` (`QuestionDecision(False, None,
("DISCOVERY_NOT_ATTEMPTED",))`), proven by
`test_a_blank_that_never_went_through_discovery_may_not_reach_the_
question_queue`. This is the literal, code-level implementation of
`AUTO_DISCOVERY_FIRST`. `MINIMAL_STRUCTURED_CLARIFICATION` is preserved by
`MAX_QUESTION_OPTIONS = 3` (`file_clarification()` REFUSES — raises,
rather than truncating — a conflict with more than 3 sides, proven by
`test_a_conflict_with_more_than_three_sides_is_refused_rather_than_
truncated`) and by `evaluate_question_gate()`'s own narrow set of
ask-worthy conditions (contradicted / unresolved / confirmation-required-
but-not-confirmed only — never a blanket "ask about everything").

## Canonical reconciliation (instruction item 7 — Parent is evidence, not authority)

Canonical already has its OWN, real, wired intake-field model
(`intake_state.IntakeFieldRecord`/`IntakeFieldStatus`, independently
verified this Cohort by direct read, not merely cited from a prior
document):

```python
class IntakeFieldStatus(str, Enum):
    AUTO_RESOLVED = "AUTO_RESOLVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"

@dataclass
class IntakeFieldRecord:
    field: str; category: str; value: Any; source: str; confidence: str
    status: str; last_validated: Optional[str] = None; owner: Optional[str] = None
    reason: str = ""
```

This is a **single flat record with ONE combined status enum** that folds
discovery-method + technical-validity + human-confirmation into one axis
(e.g. `USER_CONFIRMED` conflates "who confirmed it" with "is it correct").
`confidence` is separately confirmed **semantically equivalent** to
Parent's `Confidence` enum — both draw from the same value set
(`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`; canonical's via
`inference.CONFIDENCE_LEVELS` + `"UNKNOWN"`, independently verified by
direct read of `intake_state.py`'s own `CONFIDENCE_VOCAB` definition).

**Canonical authority wins where it already establishes something
stronger.** One case where it genuinely does: `intake_audit_provenance.py`'s
`established_by_status` taxonomy (`HUMAN`/`TIER2_ASSUMPTION`/
`SYSTEM_COMPUTED`/`UNVERIFIABLE`/`NOT_ESTABLISHED`, independently verified
by direct read) is a real, more complete evidence-provenance model than
anything Parent's `intake_field_resolution.py` itself defines — Parent's
own module reuses `question_queue`'s decision-chain the same way canonical
already does, but canonical's OWN provenance taxonomy is not superseded or
touched by this migration.

**This Cohort does NOT reconcile the two models into one.** Per explicit
instruction: "Cohort 4 only establishes the semantic foundation that M6
will use... Do not implement M6 ClarificationService." The new canonical
`intake_field_resolution.py` is delivered as a parallel, richer,
FOUNDATION-status model — genuinely available for M6 to adopt, extend, or
reconcile against `intake_state.py` when `ClarificationService` is
actually built — not wired into `intake_state.py`'s existing call sites by
this Cohort.

## Compatibility of the two canonical dependencies this migration reuses (verified, not assumed)

- **`source_authority.py`**: `authority_rank()`, `SourceClaim` (fields
  `source`/`claim`/`evidence_path`/`qualifier`/`detail`, matching exactly
  what `_try_authority()` constructs), `resolve_conflict()` (returns a
  dict with `"verdict"` in `{NO_CONFLICT, RESOLVED,
  UNDECIDABLE_SAME_AUTHORITY}` and `"winner"` as a `.to_dict()`-shaped
  dict carrying a `"claim"` key) — all read directly from canonical
  source, byte-for-byte compatible with what the migrated
  `_try_authority()` calls.
- **`question_queue.py`**: `make_question_id(domain, question_key)`,
  `QuestionQueueStore.add_question(domain=..., question=..., context_path=...,
  options=..., recommendation=..., assumption_if_unanswered=...,
  question_key=..., context=...)`, `.get_question(question_id)` — all
  present with signatures matching exactly what `file_clarification()`
  calls (canonical's `add_question()` accepts additional optional
  keyword arguments Parent's version may not have, but none required by
  this module).
