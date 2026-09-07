"""Golden Subsystem Benchmark / KPI / Critical False-Architecture-Claim Metrics.

Master-prompt sections 299-301 (VIP_SCOREBOARD_CHECKER_ASSERTION.md) and 326-328
(SUBSYSTEM_DESIGN_INTELLIGENCE.md -- the same shape, aimed at design extraction
instead of verification architecture) both ask the same question: grade a real
extractor's placement/architecture CLAIMS about a subsystem against a
hand-curated GOLDEN ground truth, as a versioned benchmark with a KPI, and --
the critical property -- surface every case where the extractor was
CONFIDENTLY WRONG (a "false-positive architecture claim") as its own distinct,
never-averaged-away signal, because a confident wrong claim about where a
checker/scoreboard/assertion sits, or what a module's FSM/instance tree looks
like, is far more dangerous than an honest "I don't know".

WHAT THIS GRADES. Two real producers, never re-implemented here:
  * `dv_harness/verification_architecture.py` -- `assemble_verification_architecture()`'s
    own `vip_selection`/`vip_bind`/`checker`/`scoreboard`/`assertion` IR lists.
  * `dv_harness/design_architecture_ir.py` -- `build_architecture_ir()`'s own
    `instance_tree`, per-module `fsm_extraction.candidates`, and
    `duplicate_modules`.
This module reads whichever of those two real, ALREADY-PRODUCED documents a
caller supplies (it never runs a simulator, a build, verible, or either
producer itself -- Evidence Truth Rule: a "claim" graded here is always
something the real extractor actually said, never something this module
infers on the extractor's behalf) and compares named FIELDS on named RECORDS
against a curated `expected_value`.

REUSE, STATED PRECISELY. `dv_harness/benchmark_dataset.py` (spec section 226)
already built exactly the versioned-corpus + train/test-leakage MECHANISM this
task is told to reuse "as the vehicle rather than inventing a second benchmark
harness". What this module takes from it, literally imported and unmodified:
the generic `_sha256_text`/`_safe_id`/`_now` helpers, and -- because they are
genuinely generic concepts, not stage-mutation-specific -- its
`DIFFICULTIES`/`QUALIFICATIONS` case-metadata vocabularies and its
`INTEGRITY_*`/`LEAKAGE_*` result vocabularies, so a case here and a case there
report integrity/leakage in the exact same words.

What this module does NOT force through `benchmark_dataset.py`'s own
`register_dataset_version()`/`validate_case()`/`run_benchmark_eval()`, and
why: that schema's execution-shaped fields are hard-bound to a DIFFERENT
question. `expected_result` must be one of `capability_evolution.
BENCHMARK_OUTCOMES` -- `IMPROVED`/`UNCHANGED`/`DEGRADED`/`INCONCLUSIVE`, a
before/after CANDIDATE-EXPERIMENT vocabulary that does not mean, and must
never be bent to mean, "this architecture claim was correct". `mutation` must
be a non-empty declarative content-diff a shadow run applies to a treatment
arm -- meaningless for grading a claim against ground truth, and populating it
with an inert placeholder just to satisfy validation would itself be exactly
the kind of fabricated-shape workaround the Evidence Truth Rule exists to
catch. `benchmark_dataset.py`'s own docstring says as much already: "Cases
that need a different execution shape (a pure prompt/response agent eval, a
generated-file diff) are NOT supported." Grading a real IR's claims against
curated ground truth is such a shape. So this module carries its OWN small
versioned registry and its OWN append-only tuning ledger -- structurally a
direct port of `benchmark_dataset.py`'s three version-registration refusal
rules (same-version-different-content refused, back-dated-version refused,
no-op bump refused) and its question-digest-keyed leakage design -- sized to a
case whose real content is a `subsystem_id` + `extraction_kind` + a list of
GOLDEN CLAIM SPECS, not a fixture/stage/mutation triple.

CLAIM GRADING. One `GoldenClaimSpec` names: which IR list (`ir_kind`) to look
in, a `match` dict identifying exactly one record in it, a `field` on that
record, the ground-truth `expected_value`, and two curator-declared,
closed-per-claim value sets drawn from the REAL producer's own documented
vocabulary (never invented here): `positive_values` (the field's "confident,
affirmative claim" values -- e.g. `["RESOLVED"]`, or `[True]`) and
`abstention_values` (the field's "the extractor honestly declined to answer"
values -- e.g. `["UNKNOWN", "PARTIAL", "NOT_AVAILABLE"]`, or `[None]`).
`grade_claim()` then classifies, per CLAIM_OUTCOMES:
  * actual == expected                              -> CLAIM_MATCH
  * actual in abstention_values                      -> CLAIM_HONEST_ABSTENTION
    (a coverage gap, never scored as a wrong claim -- an honest "don't know"
    must never be punished the same as a confident wrong answer)
  * actual in positive_values (and wrong)            -> CLAIM_FALSE_POSITIVE
    (THE critical case: the extractor confidently asserted an architecture
    fact -- a checker is mounted, a scoreboard is comparable, an assertion's
    clock domain matches, an FSM resolved cleanly, an instance resolved to a
    named module -- and it was wrong)
  * actual is some other, non-abstaining wrong value -> CLAIM_FALSE_NEGATIVE
  * the ground-truth target record does not exist    -> CLAIM_TARGET_MISSING
  * the match/field spec cannot be resolved at all    -> CLAIM_PATH_ERROR
    (a corpus defect -- never silently treated as a match)

KPI. `summarize_claims()` reports, over every graded claim, always -- never
omitted for being zero, per the Evidence Truth Rule --
`claim_accuracy`, and the headline `false_positive_architecture_claim_rate`
(both over the GRADEABLE claims: MATCH+FALSE_POSITIVE+FALSE_NEGATIVE, so an
abstention-heavy corpus cannot dilute the rate that matters), plus
`honest_abstention_rate` and `target_missing_rate` as coverage signals. Denominator
zero reports `kpi_status: "NOT_AVAILABLE"`, never a fabricated 0.0.

WORST-WINS, PER THE HOUSE RULE. `claim_verdict()`/the run's overall `status`
never average: a single held-out `CLAIM_FALSE_POSITIVE` anywhere makes the
whole verdict `FALSE_POSITIVE_DETECTED`, full stop, regardless of how many
other claims matched cleanly -- exactly `dv_harness.system_closure_aggregator`'s
and every other composite gate in this repo's own strict-worst-wins rule,
applied here to "does this extractor ever make a confidently wrong
architecture claim on a golden subsystem".

VOCABULARY. `assert_no_verification_verdict_vocabulary()` checks this
module's `CLAIM_OUTCOMES`/`GS_RUN_STATUSES`/`CASE_NOT_EXECUTED` share no token
with `dv_harness.models.Status`, the same discipline `capability_evolution`
and `benchmark_dataset` already hold themselves to.

BOUNDED, stated rather than implied closed:
  * This module never runs a simulator, build, regression, LSF job, verible,
    or either real extractor -- a caller always supplies the real, already-
    produced `assemble_verification_architecture()` / `build_architecture_ir()`
    document. Grading is pure comparison.
  * A claim's `match` spec must resolve to EXACTLY one record; an ambiguous
    match is a corpus defect (CLAIM_PATH_ERROR), never resolved by picking
    "the first one".
  * `positive_values`/`abstention_values` are curator-declared per claim, not
    derived from the real module's status vocabulary by this module -- a
    curator who mis-declares them mis-grades their own case; this module does
    not second-guess a claim's own declared value sets.
  * There is deliberately no stage gate and no change to `dv_harness/gates.py`
    or `dv_harness/cli.py`, matching `golden_scenario.py`/`power_intent.py`'s
    own precedent -- the front door is
    `python -m dv_harness.golden_subsystem_benchmark`.
  * There is no `eval` verb that dispatches a live agent (unlike
    `benchmark_dataset.py`, which deliberately omits one for that reason) --
    THIS module's `eval` verb is pure JSON-to-JSON comparison against a
    caller-supplied `--extracted-docs-file`, never a subprocess dispatch, so
    exposing it on the CLI carries none of `benchmark_dataset.py`'s risk.
"""
from __future__ import annotations

import json
import sys
import platform
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .benchmark_dataset import (  # generic, non-stage-mutation-specific reuse only
    _sha256_text, _safe_id, _now,
    DIFFICULTIES, QUALIFICATIONS,
    INTEGRITY_OK, INTEGRITY_DRIFT, INTEGRITY_UNREADABLE, INTEGRITY_STATUSES,
    LEAKAGE_CLEAN, LEAKAGE_PARTIAL, LEAKAGE_FULL, LEAKAGE_STATUSES,
)

SCHEMA_VERSION = "1.0"
DATASETS_SUBDIR = "golden_subsystem_benchmarks"
VERSIONS_SUBDIR = "versions"
EVAL_RUNS_SUBDIR = "eval_runs"
TUNING_LEDGER_NAME = "tuning_ledger.jsonl"

GS_EVAL_PRODUCER = "golden_subsystem_benchmark.run_golden_subsystem_eval"
CASE_RUN_KIND = "golden_subsystem_case"

# ---------------------------------------------------------------------------
# Extraction kinds (which of the two real producers a case grades)

EK_VERIFICATION_ARCHITECTURE = "VERIFICATION_ARCHITECTURE"
EK_DESIGN_ARCHITECTURE = "DESIGN_ARCHITECTURE"
EXTRACTION_KINDS: tuple = (EK_VERIFICATION_ARCHITECTURE, EK_DESIGN_ARCHITECTURE)

#: `dv_harness/verification_architecture.py`'s own top-level IR list keys
#: (`assemble_verification_architecture()`'s return dict).
VERIFICATION_ARCHITECTURE_IR_KINDS: tuple = (
    "vip_selection", "vip_bind", "checker", "scoreboard", "assertion",
)
#: `dv_harness/design_architecture_ir.py`'s own three fact families.
DESIGN_ARCHITECTURE_IR_KINDS: tuple = (
    "instance_node", "module_fsm_candidate", "duplicate_module",
)
IR_KINDS_BY_EXTRACTION_KIND: dict = {
    EK_VERIFICATION_ARCHITECTURE: VERIFICATION_ARCHITECTURE_IR_KINDS,
    EK_DESIGN_ARCHITECTURE: DESIGN_ARCHITECTURE_IR_KINDS,
}

# ---------------------------------------------------------------------------
# Vocabularies -- never `dv_harness.models.Status` members (checked below)

CLAIM_MATCH = "CLAIM_MATCH"
CLAIM_FALSE_POSITIVE = "CLAIM_FALSE_POSITIVE"
CLAIM_FALSE_NEGATIVE = "CLAIM_FALSE_NEGATIVE"
CLAIM_HONEST_ABSTENTION = "CLAIM_HONEST_ABSTENTION"
CLAIM_TARGET_MISSING = "CLAIM_TARGET_MISSING"
CLAIM_PATH_ERROR = "CLAIM_PATH_ERROR"
CLAIM_OUTCOMES: tuple = (
    CLAIM_MATCH, CLAIM_FALSE_POSITIVE, CLAIM_FALSE_NEGATIVE,
    CLAIM_HONEST_ABSTENTION, CLAIM_TARGET_MISSING, CLAIM_PATH_ERROR,
)

#: One case's overall verdict when the extracted doc for it was never
#: supplied at all -- distinct from any claim outcome, since no claim was
#: even attempted.
CASE_NOT_EXECUTED = "CASE_NOT_EXECUTED"

GS_RUN_CLEAN = "CLEAN"
GS_RUN_FALSE_POSITIVE_DETECTED = "FALSE_POSITIVE_DETECTED"
GS_RUN_FALSE_NEGATIVE_ONLY = "FALSE_NEGATIVE_ONLY"
GS_RUN_INADMISSIBLE = "INADMISSIBLE"
GS_RUN_NOT_AVAILABLE = "NOT_AVAILABLE"
GS_RUN_STATUSES: tuple = (
    GS_RUN_CLEAN, GS_RUN_FALSE_POSITIVE_DETECTED, GS_RUN_FALSE_NEGATIVE_ONLY,
    GS_RUN_INADMISSIBLE, GS_RUN_NOT_AVAILABLE,
)

DATASET_REQUIRED_FIELDS = (
    "dataset_id", "version", "description", "owner", "source", "provenance", "cases",
)

#: Every field a case is stored with -- folded into `case_record_digest()`,
#: so editing ANY of them (including a curator note) is editing the corpus
#: and requires a version bump.
CASE_METADATA_FIELDS = (
    "case_id", "subsystem_id", "extraction_kind", "owner", "source", "provenance",
    "known_ambiguity", "difficulty", "qualification",
)
CASE_EXECUTION_FIELDS = ("fixture_ref", "claims")
CASE_CONTENT_FIELDS = CASE_METADATA_FIELDS + CASE_EXECUTION_FIELDS

#: The subset that is the QUESTION the case asks -- which real subsystem
#: fixture, which extraction kind, and exactly what it claims-checks.
#: Leakage is keyed on these only, the same discipline
#: `benchmark_dataset.CASE_SUBSTANCE_FIELDS` documents: renaming or
#: re-owning a case must not launder tuning history, while changing what it
#: actually grades makes it a genuinely different case.
CASE_SUBSTANCE_FIELDS = ("extraction_kind", "fixture_ref", "claims")

CLAIM_REQUIRED_FIELDS = (
    "claim_id", "ir_kind", "match", "field", "expected_value",
    "positive_values", "abstention_values", "note",
)


class GoldenSubsystemBenchmarkError(ValueError):
    """Base class for every refusal this module makes."""


class GSValidationError(GoldenSubsystemBenchmarkError):
    """A dataset, case or claim that does not carry the required fields, or
    carries them in a shape the grader cannot resolve."""


class GSVersionConflictError(GoldenSubsystemBenchmarkError):
    """A version being re-registered with different content, back-dated
    behind the latest, or bumped without changing a single case."""


class GSNotFoundError(GoldenSubsystemBenchmarkError):
    """No such dataset, or no such version of it, on disk."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's vocabularies must share no token with
    `dv_harness.models.Status` -- the same rule, and the same reason, as
    `capability_evolution`/`benchmark_dataset`: a benchmark claim outcome
    must never be confusable with a real DV verification verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    for name, vocabulary in (
        ("CLAIM_OUTCOMES", CLAIM_OUTCOMES),
        ("GS_RUN_STATUSES", GS_RUN_STATUSES),
        ("CASE_NOT_EXECUTED", (CASE_NOT_EXECUTED,)),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise GSValidationError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)} -- "
                "a golden-subsystem claim outcome must never be confusable with a "
                "verification verdict"
            )


# ---------------------------------------------------------------------------
# Paths and digests (mirrors benchmark_dataset.py's own layout, one level
# under a separate subdirectory so the two corpora never collide)


def datasets_dir(root) -> Path:
    return Path(root) / ".dv-harness" / DATASETS_SUBDIR


def dataset_dir(root, dataset_id: str) -> Path:
    return datasets_dir(root) / _safe_id(dataset_id, "dataset_id")


def version_path(root, dataset_id: str, version: int) -> Path:
    return dataset_dir(root, dataset_id) / VERSIONS_SUBDIR / f"v{int(version)}.json"


def tuning_ledger_path(root, dataset_id: str) -> Path:
    return dataset_dir(root, dataset_id) / TUNING_LEDGER_NAME


def eval_runs_dir(root, dataset_id: str) -> Path:
    return dataset_dir(root, dataset_id) / EVAL_RUNS_SUBDIR


def case_record_digest(case: Dict[str, Any]) -> str:
    payload = {k: case.get(k) for k in CASE_CONTENT_FIELDS}
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def case_question_digest(case: Dict[str, Any]) -> str:
    payload = {k: case.get(k) for k in CASE_SUBSTANCE_FIELDS}
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def dataset_content_digest(cases: Sequence[Dict[str, Any]]) -> str:
    pairs = sorted((str(c.get("case_id")), case_record_digest(c)) for c in cases)
    return _sha256_text(json.dumps(pairs, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Validation


_JSON_SCALAR = (str, int, float, bool, type(None))


def validate_claim(claim: Any, *, index: int, extraction_kind: str) -> None:
    where = f"claims[{index}]"
    if not isinstance(claim, dict):
        raise GSValidationError(f"{where} must be an object, got {type(claim).__name__}")
    for field in CLAIM_REQUIRED_FIELDS:
        if field not in claim:
            raise GSValidationError(f"{where} is missing {field!r}")
    _safe_id(claim.get("claim_id"), f"{where}.claim_id")

    allowed_ir_kinds = IR_KINDS_BY_EXTRACTION_KIND.get(extraction_kind, ())
    if claim.get("ir_kind") not in allowed_ir_kinds:
        raise GSValidationError(
            f"{where}.ir_kind must be one of {allowed_ir_kinds} for extraction_kind "
            f"{extraction_kind!r}, got {claim.get('ir_kind')!r}"
        )

    module_name = claim.get("module_name")
    if claim["ir_kind"] == "module_fsm_candidate":
        if not isinstance(module_name, str) or not module_name.strip():
            raise GSValidationError(
                f"{where}.module_name is required and must be a non-empty string for "
                "ir_kind 'module_fsm_candidate' (it names which parsed module's "
                "fsm_extraction.candidates list to search)"
            )
    elif module_name is not None:
        raise GSValidationError(
            f"{where}.module_name must be omitted/None for ir_kind {claim['ir_kind']!r} "
            "(only 'module_fsm_candidate' claims are scoped to one module)"
        )

    match = claim.get("match")
    if not isinstance(match, dict) or not match:
        raise GSValidationError(f"{where}.match must be a non-empty object")
    for k, v in match.items():
        if not isinstance(k, str) or not k.strip():
            raise GSValidationError(f"{where}.match has a non-string/empty key {k!r}")
        if not isinstance(v, _JSON_SCALAR) and not isinstance(v, list):
            raise GSValidationError(
                f"{where}.match[{k!r}] must be a JSON scalar or list, got {type(v).__name__}"
            )

    if not isinstance(claim.get("field"), str) or not claim["field"].strip():
        raise GSValidationError(f"{where}.field must be a non-empty string")
    if not isinstance(claim.get("note"), str) or not claim["note"].strip():
        raise GSValidationError(
            f"{where}.note must be a non-empty string citing where this ground truth "
            "comes from -- an uncited golden claim cannot be reviewed"
        )
    for lst_field in ("positive_values", "abstention_values"):
        if not isinstance(claim.get(lst_field), list):
            raise GSValidationError(f"{where}.{lst_field} must be a list (may be empty)")


def validate_case(case: Any, *, index: int) -> None:
    where = f"cases[{index}]"
    if not isinstance(case, dict):
        raise GSValidationError(f"{where} must be an object, got {type(case).__name__}")
    for field in CASE_CONTENT_FIELDS:
        if field not in case:
            raise GSValidationError(f"{where} is missing {field!r}")
    _safe_id(case.get("case_id"), f"{where}.case_id")

    for field in ("subsystem_id", "owner", "source", "provenance", "fixture_ref"):
        if not str(case.get(field) or "").strip():
            raise GSValidationError(f"{where}.{field} must be a non-empty string")
    if not isinstance(case.get("known_ambiguity"), str):
        raise GSValidationError(
            f"{where}.known_ambiguity must be a string (empty means none declared)")
    if case.get("difficulty") not in DIFFICULTIES:
        raise GSValidationError(
            f"{where}.difficulty must be one of {DIFFICULTIES}, got {case.get('difficulty')!r}")
    if case.get("qualification") not in QUALIFICATIONS:
        raise GSValidationError(
            f"{where}.qualification must be one of {QUALIFICATIONS}, "
            f"got {case.get('qualification')!r}")
    if case.get("extraction_kind") not in EXTRACTION_KINDS:
        raise GSValidationError(
            f"{where}.extraction_kind must be one of {EXTRACTION_KINDS}, "
            f"got {case.get('extraction_kind')!r}")

    claims = case.get("claims")
    if not isinstance(claims, list) or not claims:
        raise GSValidationError(f"{where}.claims must be a non-empty list")
    seen = set()
    for j, claim in enumerate(claims):
        validate_claim(claim, index=j, extraction_kind=case["extraction_kind"])
        cid = claim["claim_id"]
        if cid in seen:
            raise GSValidationError(f"{where}: duplicate claim_id {cid!r} in the same case")
        seen.add(cid)


def validate_dataset(dataset: Any) -> None:
    if not isinstance(dataset, dict):
        raise GSValidationError(f"a dataset must be an object, got {type(dataset).__name__}")
    for field in DATASET_REQUIRED_FIELDS:
        if field not in dataset:
            raise GSValidationError(f"dataset is missing {field!r}")
    _safe_id(dataset.get("dataset_id"), "dataset_id")
    version = dataset.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise GSValidationError(f"dataset version must be an integer >= 1, got {version!r}")
    for field in ("description", "owner", "source", "provenance"):
        if not str(dataset.get(field) or "").strip():
            raise GSValidationError(f"dataset {field} must be a non-empty string")

    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise GSValidationError("a dataset version must carry at least one case")
    seen = set()
    for i, case in enumerate(cases):
        validate_case(case, index=i)
        cid = case["case_id"]
        if cid in seen:
            raise GSValidationError(f"duplicate case_id {cid!r} in the same dataset version")
        seen.add(cid)


# ---------------------------------------------------------------------------
# The versioned registry -- same three refusal rules as
# benchmark_dataset.register_dataset_version(), ported to this case shape.


def list_versions(root, dataset_id: str) -> List[int]:
    vdir = dataset_dir(root, dataset_id) / VERSIONS_SUBDIR
    if not vdir.is_dir():
        return []
    out = []
    for path in vdir.glob("v*.json"):
        try:
            out.append(int(path.stem[1:]))
        except ValueError:
            continue
    return sorted(out)


def latest_version(root, dataset_id: str) -> Optional[int]:
    versions = list_versions(root, dataset_id)
    return versions[-1] if versions else None


def list_datasets(root) -> List[str]:
    base = datasets_dir(root)
    if not base.is_dir():
        return []
    out = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        try:
            if list_versions(root, p.name):
                out.append(p.name)
        except GSValidationError:
            continue
    return sorted(out)


def load_dataset(root, dataset_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    if version is None:
        version = latest_version(root, dataset_id)
        if version is None:
            raise GSNotFoundError(
                f"no versions of golden-subsystem dataset {dataset_id!r} are registered "
                f"under {dataset_dir(root, dataset_id)}")
    path = version_path(root, dataset_id, version)
    if not path.is_file():
        raise GSNotFoundError(f"dataset {dataset_id!r} has no version {version} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def register_dataset_version(root, dataset: Dict[str, Any], *,
                             by: str = "golden-subsystem-benchmark") -> Dict[str, Any]:
    """Register ONE immutable dataset version, or refuse -- the exact three
    refusals `benchmark_dataset.register_dataset_version()` documents,
    ported here rather than re-derived: different content at an existing
    version number, a back-dated version, or a bump that changes no case."""
    validate_dataset(dataset)
    dataset_id = dataset["dataset_id"]
    version = int(dataset["version"])
    digest = dataset_content_digest(dataset["cases"])

    path = version_path(root, dataset_id, version)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        actual = dataset_content_digest(existing.get("cases") or [])
        if actual != existing.get("content_digest"):
            raise GSVersionConflictError(
                f"{dataset_id} v{version} on disk is {INTEGRITY_DRIFT}: its cases hash to "
                f"{actual[:12]} but the stored version records "
                f"{str(existing.get('content_digest'))[:12]}. Restore it, or register the "
                "edited corpus as a new version -- registering over it would bless the drift."
            )
        if existing.get("content_digest") == digest:
            return existing
        raise GSVersionConflictError(
            f"{dataset_id} v{version} is already registered with content digest "
            f"{str(existing.get('content_digest'))[:12]}, and the dataset offered hashes to "
            f"{digest[:12]}. A registered version is immutable: bump to "
            f"v{(latest_version(root, dataset_id) or version) + 1} instead of editing it."
        )

    previous = latest_version(root, dataset_id)
    if previous is not None:
        if version <= previous:
            raise GSVersionConflictError(
                f"{dataset_id} is already at v{previous}; a dataset version only moves "
                f"forward, and v{version} would back-date the corpus"
            )
        prior = load_dataset(root, dataset_id, previous)
        if prior.get("content_digest") == digest:
            raise GSVersionConflictError(
                f"{dataset_id} v{version} carries exactly the cases v{previous} already "
                "carries; a version bump that changes no case is not a new dataset version"
            )

    stored = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "version": version,
        "previous_version": previous,
        "registered_at": _now(),
        "registered_by": str(by),
        "description": dataset["description"],
        "owner": dataset["owner"],
        "source": dataset["source"],
        "provenance": dataset["provenance"],
        "notes": dataset.get("notes", ""),
        "content_digest": digest,
        "case_digests": {c["case_id"]: case_record_digest(c) for c in dataset["cases"]},
        "cases": dataset["cases"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    return stored


def verify_dataset_integrity(root, dataset_id: str,
                             version: Optional[int] = None) -> Dict[str, Any]:
    try:
        stored = load_dataset(root, dataset_id, version)
    except json.JSONDecodeError as exc:
        return {"dataset_id": dataset_id, "version": version,
                "status": INTEGRITY_UNREADABLE, "detail": f"not readable JSON ({exc})"}
    recomputed = dataset_content_digest(stored.get("cases") or [])
    stored_digest = stored.get("content_digest")
    if recomputed == stored_digest:
        return {"dataset_id": dataset_id, "version": stored.get("version"),
                "status": INTEGRITY_OK, "content_digest": stored_digest,
                "case_count": len(stored.get("cases") or []), "detail": None}
    drifted = sorted(
        cid for cid, d in (stored.get("case_digests") or {}).items()
        if d != next((case_record_digest(c) for c in (stored.get("cases") or [])
                      if c.get("case_id") == cid), None)
    )
    return {
        "dataset_id": dataset_id,
        "version": stored.get("version"),
        "status": INTEGRITY_DRIFT,
        "content_digest": stored_digest,
        "recomputed_digest": recomputed,
        "drifted_case_ids": drifted,
        "case_count": len(stored.get("cases") or []),
        "detail": (f"the stored cases hash to {recomputed[:12]} but the version records "
                   f"{str(stored_digest)[:12]}; a case was edited in place instead of "
                   "registering a new version"),
    }


def diff_dataset_versions(root, dataset_id: str, old_version: int,
                          new_version: int) -> Dict[str, Any]:
    old = load_dataset(root, dataset_id, old_version)
    new = load_dataset(root, dataset_id, new_version)
    old_cases = {c["case_id"]: case_record_digest(c) for c in old.get("cases") or []}
    new_cases = {c["case_id"]: case_record_digest(c) for c in new.get("cases") or []}
    added = sorted(set(new_cases) - set(old_cases))
    removed = sorted(set(old_cases) - set(new_cases))
    modified = sorted(cid for cid in set(old_cases) & set(new_cases)
                      if old_cases[cid] != new_cases[cid])
    return {
        "dataset_id": dataset_id,
        "old_version": old.get("version"),
        "new_version": new.get("version"),
        "old_content_digest": old.get("content_digest"),
        "new_content_digest": new.get("content_digest"),
        "bumped": old.get("content_digest") != new.get("content_digest"),
        "added_case_ids": added,
        "removed_case_ids": removed,
        "modified_case_ids": modified,
        "unchanged_case_ids": sorted(cid for cid in set(old_cases) & set(new_cases)
                                     if old_cases[cid] == new_cases[cid]),
    }


# ---------------------------------------------------------------------------
# Train/test leakage -- same question-digest-keyed, append-only ledger design
# as benchmark_dataset.record_tuning_use()/leakage_report(), ported here.


def record_tuning_use(root, dataset_id: str, case_id: str, *,
                      subject_id: str, subject_version: str, used_for: str,
                      version: Optional[int] = None,
                      by: str = "golden-subsystem-benchmark") -> Dict[str, Any]:
    stored = load_dataset(root, dataset_id, version)
    case = next((c for c in stored.get("cases") or [] if c.get("case_id") == case_id), None)
    if case is None:
        raise GSNotFoundError(
            f"dataset {dataset_id} v{stored.get('version')} has no case {case_id!r}")
    if not str(subject_id or "").strip() or not str(subject_version or "").strip():
        raise GSValidationError(
            "a tuning use must name the subject_id and subject_version it tuned")
    if not str(used_for or "").strip():
        raise GSValidationError("a tuning use must say what the case was used for")
    entry = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": stored.get("version"),
        "case_id": case_id,
        "case_question_digest": case_question_digest(case),
        "case_record_digest": case_record_digest(case),
        "subject_id": str(subject_id),
        "subject_version": str(subject_version),
        "used_for": str(used_for),
        "recorded_at": _now(),
        "recorded_by": str(by),
    }
    path = tuning_ledger_path(root, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def read_tuning_ledger(root, dataset_id: str) -> List[Dict[str, Any]]:
    path = tuning_ledger_path(root, dataset_id)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def leakage_report(root, dataset_id: str, *, subject_id: str, subject_version: str,
                   version: Optional[int] = None) -> Dict[str, Any]:
    stored = load_dataset(root, dataset_id, version)
    cases = stored.get("cases") or []
    ledger = read_tuning_ledger(root, dataset_id)

    exact, related = {}, {}
    for entry in ledger:
        if str(entry.get("subject_id")) != str(subject_id):
            continue
        digest = entry.get("case_question_digest")
        if str(entry.get("subject_version")) == str(subject_version):
            exact.setdefault(digest, []).append(entry)
        else:
            related.setdefault(digest, []).append(entry)

    leaked, related_ids, detail = [], [], []
    for case in cases:
        digest = case_question_digest(case)
        if digest in exact:
            leaked.append(case["case_id"])
            detail.append({"case_id": case["case_id"], "case_question_digest": digest,
                           "uses": exact[digest]})
        elif digest in related:
            related_ids.append(case["case_id"])

    total = len(cases)
    if not leaked:
        status = LEAKAGE_CLEAN
    elif len(leaked) >= total:
        status = LEAKAGE_FULL
    else:
        status = LEAKAGE_PARTIAL
    return {
        "dataset_id": dataset_id,
        "dataset_version": stored.get("version"),
        "subject_id": str(subject_id),
        "subject_version": str(subject_version),
        "case_count": total,
        "leaked_case_ids": sorted(leaked),
        "leaked_count": len(leaked),
        "held_out_count": total - len(leaked),
        "related_tuning_use_case_ids": sorted(related_ids),
        "status": status,
        "leaked_detail": detail,
    }


# ---------------------------------------------------------------------------
# Claim resolution + grading -- the part with no analog in benchmark_dataset.py


def _flatten_instance_tree(instance_tree: Optional[dict]) -> List[dict]:
    """Every node of `design_architecture_ir.build_instance_tree()`'s real
    forest, each carrying a new `path` (the instance-name chain from its own
    root), so a claim can disambiguate two instances that share a bare
    `instance_name` in different branches."""
    out: List[dict] = []

    def walk(node: dict, path: tuple) -> None:
        node_path = path + (node.get("instance_name"),)
        rec = dict(node)
        rec["path"] = list(node_path)
        out.append(rec)
        for child in node.get("children") or []:
            walk(child, node_path)

    for tree in ((instance_tree or {}).get("trees") or []):
        walk(tree, ())
    return out


def _resolve_records(doc: Any, extraction_kind: str, ir_kind: str,
                     module_name: Optional[str]) -> List[dict]:
    if not isinstance(doc, dict):
        raise GSValidationError(
            f"the extracted doc must be a dict (the real "
            f"{'assemble_verification_architecture()' if extraction_kind == EK_VERIFICATION_ARCHITECTURE else 'build_architecture_ir()'} "
            f"return shape), got {type(doc).__name__}"
        )
    if extraction_kind == EK_VERIFICATION_ARCHITECTURE:
        records = doc.get(ir_kind)
        if records is None:
            raise GSValidationError(f"extracted doc has no {ir_kind!r} list")
        if not isinstance(records, list):
            raise GSValidationError(f"extracted doc[{ir_kind!r}] must be a list")
        return records
    if extraction_kind == EK_DESIGN_ARCHITECTURE:
        if ir_kind == "duplicate_module":
            dups = doc.get("duplicate_modules")
            if not isinstance(dups, list):
                raise GSValidationError("extracted doc['duplicate_modules'] must be a list")
            return dups
        if ir_kind == "instance_node":
            return _flatten_instance_tree(doc.get("instance_tree"))
        if ir_kind == "module_fsm_candidate":
            modules = doc.get("modules")
            if not isinstance(modules, dict):
                raise GSValidationError("extracted doc['modules'] must be a dict")
            mod = modules.get(module_name)
            if mod is None:
                return []  # a real, honest fact: this module was not in the build at all
            fsm = mod.get("fsm_extraction") or {}
            candidates = fsm.get("candidates")
            if candidates is None:
                return []
            if not isinstance(candidates, list):
                raise GSValidationError(
                    f"extracted doc['modules'][{module_name!r}]['fsm_extraction']"
                    "['candidates'] must be a list")
            return candidates
    raise GSValidationError(f"unknown extraction_kind {extraction_kind!r}")


def grade_claim(extracted_doc: Any, extraction_kind: str, claim: Dict[str, Any]) -> Dict[str, Any]:
    """Grade ONE golden claim against ONE real, caller-supplied extracted
    doc. Never raises for a resolvable-but-wrong claim -- every failure mode
    is a distinct, reported CLAIM_OUTCOMES member."""
    base = {
        "claim_id": claim["claim_id"], "ir_kind": claim["ir_kind"],
        "module_name": claim.get("module_name"), "match": claim["match"],
        "field": claim["field"], "expected_value": claim["expected_value"],
    }
    try:
        records = _resolve_records(extracted_doc, extraction_kind, claim["ir_kind"],
                                   claim.get("module_name"))
    except GSValidationError as exc:
        return {**base, "outcome": CLAIM_PATH_ERROR, "actual_value": None, "detail": str(exc)}

    found = [r for r in records if isinstance(r, dict)
             and all(r.get(k) == v for k, v in claim["match"].items())]
    if not found:
        return {**base, "outcome": CLAIM_TARGET_MISSING, "actual_value": None,
                "detail": f"no {claim['ir_kind']} record matched {claim['match']}"}
    if len(found) > 1:
        return {**base, "outcome": CLAIM_PATH_ERROR, "actual_value": None,
                "detail": f"{len(found)} {claim['ir_kind']} records matched {claim['match']}; "
                          "a claim's match spec must identify exactly one record"}
    record = found[0]
    field = claim["field"]
    if field not in record:
        return {**base, "outcome": CLAIM_PATH_ERROR, "actual_value": None,
                "detail": f"field {field!r} is not present on the resolved {claim['ir_kind']} record"}

    actual = record[field]
    expected = claim["expected_value"]
    if actual == expected:
        outcome = CLAIM_MATCH
    elif actual in claim["abstention_values"]:
        outcome = CLAIM_HONEST_ABSTENTION
    elif actual in claim["positive_values"]:
        outcome = CLAIM_FALSE_POSITIVE
    else:
        outcome = CLAIM_FALSE_NEGATIVE
    return {**base, "outcome": outcome, "actual_value": actual, "detail": None}


def grade_case(extracted_doc: Any, case: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every claim of one case, graded against one real extracted doc."""
    return [grade_claim(extracted_doc, case["extraction_kind"], claim)
            for claim in case["claims"]]


# ---------------------------------------------------------------------------
# KPI aggregation -- always reported, worst-wins verdict


def summarize_claims(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {o: 0 for o in CLAIM_OUTCOMES}
    for r in results:
        counts[r["outcome"]] += 1
    total = len(results)
    gradeable = counts[CLAIM_MATCH] + counts[CLAIM_FALSE_POSITIVE] + counts[CLAIM_FALSE_NEGATIVE]

    def rate(n: int, d: int) -> Optional[float]:
        return round(n / d, 4) if d else None

    return {
        "total_claims": total,
        "counts": counts,
        "gradeable_claims": gradeable,
        # The headline critical metric (sections 299-301 / 326-328): a
        # confidently WRONG architecture claim, over the claims where the
        # extractor actually took a definite (non-abstaining) position.
        "false_positive_architecture_claim_rate": rate(counts[CLAIM_FALSE_POSITIVE], gradeable),
        "false_negative_architecture_claim_rate": rate(counts[CLAIM_FALSE_NEGATIVE], gradeable),
        "claim_accuracy": rate(counts[CLAIM_MATCH], gradeable),
        "honest_abstention_rate": rate(counts[CLAIM_HONEST_ABSTENTION], total),
        "target_missing_rate": rate(counts[CLAIM_TARGET_MISSING], total),
        "path_error_count": counts[CLAIM_PATH_ERROR],
        "kpi_status": "MEASURED" if gradeable else "NOT_AVAILABLE",
    }


def claim_verdict(results: Sequence[Dict[str, Any]]) -> str:
    """Strict WORST-WINS over one case's (or one run's) claims: a single
    FALSE_POSITIVE outranks any number of clean claims, per this project's
    composite-gate rule -- never averaged, never diluted by volume."""
    outcomes = {r["outcome"] for r in results}
    if CLAIM_FALSE_POSITIVE in outcomes:
        return GS_RUN_FALSE_POSITIVE_DETECTED
    if CLAIM_FALSE_NEGATIVE in outcomes:
        return GS_RUN_FALSE_NEGATIVE_ONLY
    if CLAIM_MATCH in outcomes or CLAIM_HONEST_ABSTENTION in outcomes:
        return GS_RUN_CLEAN
    return GS_RUN_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# The eval run -- pure comparison, no subprocess, no simulator/build/LSF job


def _environment(root: Path) -> Dict[str, Any]:
    from .change_impact import resolve_sha

    return {
        "harness_root": str(root),
        "harness_git_sha": resolve_sha(root, "HEAD"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }


def run_golden_subsystem_eval(root, dataset_id: str, *, subject: Dict[str, Any],
                              extracted_docs_by_case: Dict[str, Any],
                              version: Optional[int] = None,
                              run_id: Optional[str] = None,
                              by: str = "golden-subsystem-benchmark") -> Dict[str, Any]:
    """Grade EVERY case of one dataset version against one subject's real,
    already-produced extracted docs, and record it.

    `extracted_docs_by_case`: `{case_id: <real assemble_verification_architecture()
    or build_architecture_ir() return dict>}`. A case whose id is absent is
    recorded `CASE_NOT_EXECUTED` -- never silently skipped, never graded
    against a fabricated stand-in.

    The run's `status` is judged over the HELD-OUT cases only (never tuned on
    by this exact subject version) and is `INADMISSIBLE` when every case was
    leaked, mirroring `benchmark_dataset.run_benchmark_eval()`'s own section
    226 discipline. It never runs a simulator, build, regression or LSF job,
    and never invokes either real extractor -- pure comparison over
    caller-supplied documents.
    """
    root = Path(root).resolve()
    stored = load_dataset(root, dataset_id, version)
    dsv = int(stored["version"])
    cases = list(stored.get("cases") or [])

    subject_id = str((subject or {}).get("subject_id") or "").strip()
    subject_version = str((subject or {}).get("subject_version") or "").strip()
    if not subject_id or not subject_version:
        raise GSValidationError(
            "an eval must identify the subject_id and subject_version under evaluation")

    integrity = verify_dataset_integrity(root, dataset_id, dsv)
    if integrity["status"] != INTEGRITY_OK:
        raise GSVersionConflictError(
            f"{dataset_id} v{dsv} is {integrity['status']}: {integrity['detail']}; a result "
            "measured against a drifted corpus cites a version that no longer describes "
            "what was graded")

    leakage = leakage_report(root, dataset_id, subject_id=subject_id,
                             subject_version=subject_version, version=dsv)
    leaked = set(leakage["leaked_case_ids"])

    started_at = _now()
    run_id = run_id or "GSE-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
        _sha256_text(f"{dataset_id}|{dsv}|{subject_id}|{subject_version}|{started_at}")[:8])

    docs = extracted_docs_by_case or {}
    case_results: List[Dict[str, Any]] = []
    for case in cases:
        used_for_tuning = case["case_id"] in leaked
        common = {
            "case_id": case["case_id"],
            "case_record_digest": case_record_digest(case),
            "case_question_digest": case_question_digest(case),
            "subsystem_id": case["subsystem_id"],
            "extraction_kind": case["extraction_kind"],
            "difficulty": case.get("difficulty"),
            "qualification": case.get("qualification"),
            "known_ambiguity": case.get("known_ambiguity", ""),
            "used_for_tuning": used_for_tuning,
        }
        if case["case_id"] not in docs:
            case_results.append({
                **common, "executed": False, "claims": [], "claim_summary": None,
                "case_verdict": CASE_NOT_EXECUTED,
            })
            continue
        claim_results = grade_case(docs[case["case_id"]], case)
        case_results.append({
            **common, "executed": True, "claims": claim_results,
            "claim_summary": summarize_claims(claim_results),
            "case_verdict": claim_verdict(claim_results),
        })

    held = [c for c in case_results if not c["used_for_tuning"]]
    held_claims = [r for c in held for r in c["claims"]]
    all_claims = [r for c in case_results for r in c["claims"]]
    held_summary = summarize_claims(held_claims)
    overall_summary = summarize_claims(all_claims)

    if leakage["status"] == LEAKAGE_FULL:
        status = GS_RUN_INADMISSIBLE
    elif not any(c["executed"] for c in held):
        status = GS_RUN_NOT_AVAILABLE
    else:
        status = claim_verdict(held_claims)

    record = {
        "schema_version": SCHEMA_VERSION,
        "produced_by": GS_EVAL_PRODUCER,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "dataset_version": dsv,
        "dataset_content_digest": stored.get("content_digest"),
        "subject": {
            "subject_id": subject_id,
            "subject_version": subject_version,
            "subject_kind": str((subject or {}).get("subject_kind") or "UNDECLARED"),
            "notes": str((subject or {}).get("notes") or ""),
        },
        "environment": _environment(root),
        "started_at": started_at,
        "finished_at": _now(),
        "run_by": str(by),
        "cases": case_results,
        "summary": overall_summary,
        "held_out_summary": held_summary,
        "leakage": {k: v for k, v in leakage.items() if k != "leaked_detail"},
        "status": status,
    }
    path = eval_runs_dir(root, dataset_id) / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    record["record_path"] = str(path)
    return record


def read_eval_runs(root, dataset_id: str) -> List[Dict[str, Any]]:
    rdir = eval_runs_dir(root, dataset_id)
    if not rdir.is_dir():
        return []
    runs = []
    for path in sorted(rdir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        record["record_path"] = str(path)
        runs.append(record)
    return sorted(runs, key=lambda r: str(r.get("started_at") or ""))


def format_eval_report(record: Dict[str, Any]) -> str:
    s, hs, lk = record["summary"], record["held_out_summary"], record["leakage"]
    lines = [
        f"golden-subsystem eval {record['run_id']}: {record['status']}",
        f"  dataset       {record['dataset_id']} v{record['dataset_version']} "
        f"(digest {str(record.get('dataset_content_digest'))[:12]})",
        f"  subject       {record['subject']['subject_id']} "
        f"@{record['subject']['subject_version']} ({record['subject']['subject_kind']})",
        f"  all claims    {s['total_claims']} total, "
        f"false_positive_rate={s['false_positive_architecture_claim_rate']} "
        f"claim_accuracy={s['claim_accuracy']}",
        f"  held-out      {hs['total_claims']} claims, "
        f"false_positive_rate={hs['false_positive_architecture_claim_rate']} "
        f"(leakage {lk['status']}, {lk['leaked_count']} case(s) used for tuning)",
    ]
    for case in record["cases"]:
        flag = " [TUNED-ON]" if case.get("used_for_tuning") else ""
        cs = case.get("claim_summary") or {}
        lines.append(
            f"    {case['case_verdict']:<24} {case['case_id']}{flag}  "
            f"claims={cs.get('total_claims', 0)} fp={cs.get('counts', {}).get(CLAIM_FALSE_POSITIVE, 0)}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI


def execute_verb(verb: str, *, root, dataset_id: Optional[str] = None,
                 json_file: Optional[str] = None, version: Optional[int] = None,
                 old_version: Optional[int] = None, new_version: Optional[int] = None,
                 case_id: Optional[str] = None, subject_id: Optional[str] = None,
                 subject_version: Optional[str] = None, subject_kind: Optional[str] = None,
                 used_for: Optional[str] = None, extracted_docs_file: Optional[str] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation of `dv-harness golden-subsystem-benchmark` and
    `python -m dv_harness.golden_subsystem_benchmark`. (There is no
    `dv-harness` verb registered by this task -- see the module docstring's
    bounded-scope note; this is the standalone front door.) Returns
    (text, exit_code): 0 fine, 1 a real finding (content drift, leakage
    present, a run with a detected false-positive/false-negative claim or
    inadmissible), 2 nothing to report or a usage error."""
    root = Path(root)

    if verb == "register":
        if not json_file:
            return "golden-subsystem-benchmark register requires --json-file <dataset.json>", 2
        data = json.loads(Path(json_file).read_text(encoding="utf-8"))
        stored = register_dataset_version(root, data)
        text = (json.dumps(stored, indent=2, sort_keys=True) if as_json else
                f"registered {stored['dataset_id']} v{stored['version']} "
                f"({len(stored['cases'])} case(s), digest {stored['content_digest'][:12]}, "
                f"previous={stored['previous_version']})")
        return text, 0

    if verb == "list":
        datasets = list_datasets(root)
        if not datasets:
            return (json.dumps([]) if as_json else
                    f"NOT_AVAILABLE: no golden-subsystem benchmark datasets under "
                    f"{datasets_dir(root)}"), 2
        rows = []
        for did in datasets:
            versions = list_versions(root, did)
            latest = load_dataset(root, did, versions[-1])
            rows.append({"dataset_id": did, "versions": versions,
                         "latest_version": versions[-1],
                         "case_count": len(latest.get("cases") or []),
                         "content_digest": latest.get("content_digest"),
                         "owner": latest.get("owner")})
        if as_json:
            return json.dumps(rows, indent=2), 0
        lines = [f"{len(rows)} golden-subsystem dataset(s):"]
        for r in rows:
            lines.append(f"  {r['dataset_id']}  versions={r['versions']}  "
                         f"latest=v{r['latest_version']} ({r['case_count']} cases, "
                         f"digest {str(r['content_digest'])[:12]}, owner {r['owner']})")
        return "\n".join(lines), 0

    if not dataset_id:
        return f"golden-subsystem-benchmark {verb} requires --dataset-id", 2

    if verb == "verify":
        versions = ([version] if version is not None else list_versions(root, dataset_id))
        if not versions:
            return f"NOT_AVAILABLE: dataset {dataset_id!r} has no registered versions", 2
        reports = [verify_dataset_integrity(root, dataset_id, v) for v in versions]
        code = 1 if any(r["status"] != INTEGRITY_OK for r in reports) else 0
        if as_json:
            return json.dumps(reports, indent=2), code
        lines = [f"{dataset_id}: {len(reports)} version(s)"]
        for r in reports:
            lines.append(f"  v{r['version']}  {r['status']}  {r['case_count']} case(s)"
                         + (f"  {r['detail']}" if r.get("detail") else ""))
        return "\n".join(lines), code

    if verb == "diff":
        if old_version is None or new_version is None:
            return "golden-subsystem-benchmark diff requires --old-version and --new-version", 2
        report = diff_dataset_versions(root, dataset_id, old_version, new_version)
        if as_json:
            return json.dumps(report, indent=2), 0
        return ("\n".join([
            f"{dataset_id} v{report['old_version']} -> v{report['new_version']}: "
            f"{'BUMPED' if report['bumped'] else 'IDENTICAL_CONTENT'}",
            f"  added     {report['added_case_ids']}",
            f"  removed   {report['removed_case_ids']}",
            f"  modified  {report['modified_case_ids']}",
            f"  unchanged {len(report['unchanged_case_ids'])} case(s)",
        ]), 0)

    if verb == "record-tuning-use":
        if not (case_id and subject_id and subject_version and used_for):
            return ("golden-subsystem-benchmark record-tuning-use requires --case-id, "
                    "--subject-id, --subject-version and --used-for", 2)
        entry = record_tuning_use(root, dataset_id, case_id, subject_id=subject_id,
                                  subject_version=subject_version, used_for=used_for,
                                  version=version)
        return (json.dumps(entry, indent=2, sort_keys=True) if as_json else
                f"recorded tuning use: {entry['case_id']} "
                f"(question digest {entry['case_question_digest'][:12]}) "
                f"tuned {entry['subject_id']}@{entry['subject_version']}"), 0

    if verb == "leakage":
        if not (subject_id and subject_version):
            return "golden-subsystem-benchmark leakage requires --subject-id and --subject-version", 2
        report = leakage_report(root, dataset_id, subject_id=subject_id,
                                subject_version=subject_version, version=version)
        code = 0 if report["status"] == LEAKAGE_CLEAN else 1
        if as_json:
            return json.dumps(report, indent=2), code
        return ("\n".join([
            f"{dataset_id} v{report['dataset_version']} vs "
            f"{report['subject_id']}@{report['subject_version']}: {report['status']}",
            f"  cases       {report['case_count']}",
            f"  leaked      {report['leaked_count']} {report['leaked_case_ids']}",
            f"  held out    {report['held_out_count']}",
        ]), code)

    if verb == "eval":
        if not (subject_id and subject_version and extracted_docs_file):
            return ("golden-subsystem-benchmark eval requires --subject-id, --subject-version "
                    "and --extracted-docs-file <case_id -> extracted doc JSON>", 2)
        docs = json.loads(Path(extracted_docs_file).read_text(encoding="utf-8"))
        record = run_golden_subsystem_eval(
            root, dataset_id,
            subject={"subject_id": subject_id, "subject_version": subject_version,
                     "subject_kind": subject_kind},
            extracted_docs_by_case=docs, version=version)
        code = 0 if record["status"] == GS_RUN_CLEAN else 1
        return (json.dumps(record, indent=2, sort_keys=True) if as_json
                else format_eval_report(record)), code

    if verb == "runs":
        runs = read_eval_runs(root, dataset_id)
        if not runs:
            return f"NOT_AVAILABLE: no recorded eval runs for {dataset_id!r}", 2
        if as_json:
            return json.dumps(runs, indent=2), (
                1 if any(r.get("status") != GS_RUN_CLEAN for r in runs) else 0)
        lines = [f"{len(runs)} eval run(s) for {dataset_id}:"]
        for r in runs:
            lines.append(f"  {r.get('run_id')}  v{r.get('dataset_version')}  "
                         f"{r.get('subject', {}).get('subject_id')}"
                         f"@{r.get('subject', {}).get('subject_version')}  {r.get('status')}")
        return "\n".join(lines), (1 if any(r.get("status") != GS_RUN_CLEAN for r in runs) else 0)

    return f"unknown golden-subsystem-benchmark verb {verb!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.golden_subsystem_benchmark",
        description="Golden Subsystem Benchmark / KPI / Critical False-Architecture-Claim "
                    "Metrics (master prompt sections 299-301, 326-328): a versioned corpus of "
                    "hand-curated ground-truth architecture claims about real subsystems, "
                    "graded against dv_harness/verification_architecture.py and "
                    "dv_harness/design_architecture_ir.py's own real, already-produced output, "
                    "with a worst-wins false-positive-architecture-claim KPI.")
    ap.add_argument("verb", choices=("register", "list", "verify", "diff",
                                      "record-tuning-use", "leakage", "eval", "runs"))
    ap.add_argument("--root", default=".", help="Project root.")
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--json-file", default=None, help="register: the dataset version JSON file.")
    ap.add_argument("--version", type=int, default=None,
                    help="Operate on this dataset version (default: the latest).")
    ap.add_argument("--old-version", type=int, default=None, help="diff: the earlier version.")
    ap.add_argument("--new-version", type=int, default=None, help="diff: the later version.")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--subject-id", default=None, help="The extractor/agent version being graded.")
    ap.add_argument("--subject-version", default=None)
    ap.add_argument("--subject-kind", default=None)
    ap.add_argument("--used-for", default=None,
                    help="record-tuning-use: what the case was used to tune.")
    ap.add_argument("--extracted-docs-file", default=None,
                    help="eval: JSON file mapping case_id -> the real extracted "
                         "verification_architecture/design_architecture_ir doc for that case.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.verb, root=a.root, dataset_id=a.dataset_id, json_file=a.json_file,
            version=a.version, old_version=a.old_version, new_version=a.new_version,
            case_id=a.case_id, subject_id=a.subject_id, subject_version=a.subject_version,
            subject_kind=a.subject_kind, used_for=a.used_for,
            extracted_docs_file=a.extracted_docs_file, as_json=a.json)
    except GoldenSubsystemBenchmarkError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
