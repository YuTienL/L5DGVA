"""Agent/Skill benchmark dataset governance (master prompt section 226).

WHAT WAS MISSING. `capability_evolution.run_controlled_experiment()` measures ONE
candidate's ONE bounded change against ONE fixture: it is per-candidate
execution, and it answers "did this change help". Section 226 asks a different
question -- "how good is this agent/skill, measured against a VERSIONED corpus of
cases with known expected outcomes, and was it evaluated on the very examples it
was tuned on". Nothing in this repo held a corpus: grepping for
`benchmark_dataset`/`eval_corpus`/`dataset_version`/`leakage` (outside
`memory_security`'s unrelated secret-leakage detector) matched no executable
code. `benchmark_plan` is per-candidate free text and `benchmark_result` is one
candidate's one measurement; neither is a dataset, neither is versioned, and
neither can say whether a case was used for tuning.

WHAT THIS IS, AND WHAT IT REUSES. Three things, deliberately small:

  1. A VERSIONED, CONTENT-ADDRESSED REGISTRY. A dataset version is an immutable
     JSON file under `<root>/.dv-harness/benchmark_datasets/<id>/versions/vN.json`
     carrying a `content_digest` folded from every case's own content digest.
     Re-registering a version with different content is REFUSED (bump instead);
     bumping to a version whose cases are byte-identical to the previous one is
     also refused, because a bump that changes no case is not a new dataset.
     `verify_dataset_integrity()` recomputes the digest off disk, so editing a
     case in place without a bump is reported as CONTENT_DRIFT rather than
     silently accepted. `diff_dataset_versions()` names what a bump added,
     removed and modified.

  2. A RUNNER THAT IS NOT A SECOND RUNNER. Each case is executed by
     `capability_evolution`'s OWN isolated-fixture machinery --
     `_prepare_shadow_run()` (workspace containment, fixture validation) and
     `_execute_shadow_run()` (fingerprint the fixture, copy it twice, drive the
     REAL `DVHarness.run_stage()` in each arm, measure both through
     `control_plane.describe_stage()`, re-fingerprint, write the record). There
     is exactly one shadow-run implementation in this package and this module
     calls it rather than growing a parallel one. A case's `expected_result` is
     one of that module's own `BENCHMARK_OUTCOMES`, for the same reason.

     What this module does NOT reuse is the promotion state machine, on purpose.
     A benchmark eval makes no `transition()`, persists no candidate, and its
     records carry `produced_by = BENCHMARK_EVAL_PRODUCER`, which is NOT in
     `capability_evolution.SHADOW_RUN_PRODUCERS` -- so a dataset-case record can
     never be pinned into a stability window or satisfy
     `assert_benchmark_measured()`. Evaluating an agent is not evidence for
     promoting a capability change, and the two must not be able to be confused.
     Every human-approval gate in this repo is untouched by this module: it
     approves nothing, promotes nothing, and decides no verification verdict.

  3. TRAIN/TEST LEAKAGE TRACKING. `record_tuning_use()` appends to an
     append-only ledger the fact that a case was used to TUNE some subject
     version. Leakage is keyed on the case's QUESTION DIGEST -- what it sets up,
     what it runs and what result it expects -- and not on its id, its owner or
     its prose, and is matched across EVERY version of the dataset. So renaming a
     case does not launder its leakage, while changing what the case asks makes
     it a genuinely different case. An eval reports the full score AND the held-out score over
     the non-leaked cases, and a run where EVERY case was used for tuning is
     `INADMISSIBLE` -- section 226's "do not evaluate a capability only on
     examples used to tune it", as a status rather than a sentence.

VOCABULARY. This module's case and run statuses share no token with
`dv_harness.models.Status` (see `assert_no_verification_verdict_vocabulary()`,
the same rule `capability_evolution` enforces on its own four vocabularies): a
benchmark case that MATCHED its expected result is not a DV verification PASS,
and a log grep must not be able to confuse them.

BOUNDED, and stated rather than implied closed:
  * A case is executed as a two-arm shadow run over a fixture project, which is
    what the reused runner measures. Cases that need a different execution shape
    (a pure prompt/response agent eval, a generated-file diff) are NOT supported.
  * There is deliberately no `eval` CLI verb. An eval needs a `harness_factory`
    naming the subject under evaluation; defaulting it would dispatch REAL
    `claude -p` agent subprocesses per case from a typed command line. The
    registry/verify/diff/leakage verbs are CLI-exposed; running one is a Python
    call whose caller states the subject explicitly.
  * `qualification` and `difficulty` are declared metadata, checked only against
    their vocabularies. Nothing here judges whether a case is as hard as it says.
  * There is no stage gate. A gate passing on a benchmark nobody reviewed would
    be worse than none, exactly as `golden_scenario` and `power_intent` state.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import capability_evolution as ce

SCHEMA_VERSION = "1.0"
DATASETS_SUBDIR = "benchmark_datasets"
VERSIONS_SUBDIR = "versions"
EVAL_RUNS_SUBDIR = "eval_runs"
TUNING_LEDGER_NAME = "tuning_ledger.jsonl"

#: Who wrote a shadow-run record. Deliberately NOT a member of
#: `capability_evolution.SHADOW_RUN_PRODUCERS`, so a record produced while
#: benchmarking an agent can never be counted as evidence for promoting a
#: capability-evolution candidate.
BENCHMARK_EVAL_PRODUCER = "benchmark_dataset.run_benchmark_eval"

#: The run_kind stamped on each case's record, for the same reason.
CASE_RUN_KIND = "dataset_case"

#: One case's outcome. This is the module's pass/fail, in tokens that are NOT
#: `dv_harness.models.Status` members: MATCHED = the subject produced the
#: expected result, MISMATCHED = it produced a different one, ERRORED = the case
#: could not be measured at all (which is never counted as a match).
CASE_MATCHED = "MATCHED"
CASE_MISMATCHED = "MISMATCHED"
CASE_ERRORED = "ERRORED"
CASE_OUTCOMES = (CASE_MATCHED, CASE_MISMATCHED, CASE_ERRORED)

#: One eval run's status, over the HELD-OUT cases (see run_benchmark_eval).
RUN_MET = "MET"
RUN_NOT_MET = "NOT_MET"
RUN_INADMISSIBLE = "INADMISSIBLE"
RUN_NOT_AVAILABLE = "NOT_AVAILABLE"
RUN_STATUSES = (RUN_MET, RUN_NOT_MET, RUN_INADMISSIBLE, RUN_NOT_AVAILABLE)

#: Leakage over one (dataset version, subject version) pair.
LEAKAGE_CLEAN = "CLEAN"
LEAKAGE_PARTIAL = "PARTIAL_LEAKAGE"
LEAKAGE_FULL = "FULLY_LEAKED"
LEAKAGE_STATUSES = (LEAKAGE_CLEAN, LEAKAGE_PARTIAL, LEAKAGE_FULL)

#: Integrity of a stored dataset version.
INTEGRITY_OK = "INTACT"
INTEGRITY_DRIFT = "CONTENT_DRIFT"
INTEGRITY_UNREADABLE = "UNREADABLE"
INTEGRITY_STATUSES = (INTEGRITY_OK, INTEGRITY_DRIFT, INTEGRITY_UNREADABLE)

DIFFICULTIES = ("BASIC", "INTERMEDIATE", "ADVANCED", "EXPERT")

#: Where a case came from. Every value states its own trust level; there is no
#: unlabelled option, because "is this case real or synthetic" must never be
#: something a reader has to infer.
QUALIFICATIONS = (
    "SYNTHETIC_FIXTURE",
    "REAL_PROJECT_DERIVED",
    "VENDOR_EXAMPLE_DERIVED",
    "UNQUALIFIED_DRAFT",
)

#: Section 226's tracked fields, split into the ones that DEFINE the case (folded
#: into its content digest, so changing one makes it a different case that
#: carries no prior leakage) and the ones that describe its execution.
CASE_METADATA_FIELDS = (
    "case_id", "source", "protocol", "project_coverage", "difficulty",
    "expected_result", "known_ambiguity", "owner", "qualification", "provenance",
)
CASE_EXECUTION_FIELDS = ("fixture_ref", "stages", "mutation")
CASE_CONTENT_FIELDS = CASE_METADATA_FIELDS + CASE_EXECUTION_FIELDS

#: The subset that is the QUESTION the case asks -- what it sets up, what it
#: runs, and what result it expects. Leakage is keyed on these and on nothing
#: else, deliberately: renaming a case, changing its owner, or rewording its
#: declared ambiguity must not be able to launder the fact that a subject was
#: tuned on it, while changing what it asks genuinely makes it another case.
#: Dataset VERSION integrity, by contrast, is sensitive to every tracked field
#: (see case_record_digest) -- editing metadata is still editing the corpus.
CASE_SUBSTANCE_FIELDS = ("expected_result",) + CASE_EXECUTION_FIELDS

DATASET_REQUIRED_FIELDS = (
    "dataset_id", "version", "description", "owner", "source", "provenance", "cases",
)

_ID_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class BenchmarkDatasetError(ValueError):
    """Base class for every refusal this module makes."""


class DatasetValidationError(BenchmarkDatasetError):
    """A dataset or case that does not carry section 226's tracked fields, or
    carries them in a shape the runner cannot execute."""


class DatasetVersionConflictError(BenchmarkDatasetError):
    """A version being re-registered with different content, back-dated behind
    the latest, or bumped without changing a single case."""


class DatasetNotFoundError(BenchmarkDatasetError):
    """No such dataset, or no such version of it, on disk."""


class BenchmarkEvalIsolationError(BenchmarkDatasetError):
    """The eval could not be kept isolated -- a case's shadow run reported an
    isolation violation. Raised rather than recorded as a failed case: an
    isolation failure produces a measurement nobody should read, which is the
    same rule `capability_evolution.ExperimentIsolationError` already states."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's three vocabularies must share no token with
    `dv_harness.models.Status`.

    The same rule, and the same reason, as
    `capability_evolution.assert_no_verification_verdict_vocabulary()`: a
    benchmark score must never be something a reader, a log grep or a string
    comparison could take for a DV verification verdict. Checkable here rather
    than promised in a docstring, so it stays true after a later edit adds a
    status.
    """
    from .models import Status

    verdicts = {s.value for s in Status}
    for name, vocabulary in (
        ("CASE_OUTCOMES", CASE_OUTCOMES),
        ("RUN_STATUSES", RUN_STATUSES),
        ("LEAKAGE_STATUSES", LEAKAGE_STATUSES),
        ("INTEGRITY_STATUSES", INTEGRITY_STATUSES),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise DatasetValidationError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)} -- "
                "a benchmark result must never be confusable with a verification verdict"
            )


# ---------------------------------------------------------------------------
# Paths and digests


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_id(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not _ID_SAFE.match(text):
        raise DatasetValidationError(
            f"{what} {value!r} is not a safe identifier; it must match {_ID_SAFE.pattern} "
            "(it names a directory and a file on disk)"
        )
    return text


def datasets_dir(root) -> Path:
    """The one directory any benchmark dataset lives under."""
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
    """A case's STORED form: a digest over every section 226 tracked field.

    This is what dataset-version integrity is checked against, so editing any
    tracked field -- including metadata like `owner` or `known_ambiguity` -- is
    editing the corpus and requires a version bump. `tuning_uses` is deliberately
    not a case field at all; it lives in the append-only ledger, so recording one
    can never look like a case edit.
    """
    payload = {k: case.get(k) for k in CASE_CONTENT_FIELDS}
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def case_question_digest(case: Dict[str, Any]) -> str:
    """A case's IDENTITY for leakage: a digest over CASE_SUBSTANCE_FIELDS only.

    Deliberately blind to `case_id` and to every descriptive field, so a case
    renamed or re-owned still carries the tuning history it earned, and a case
    whose setup, stages or expected result changed carries none.
    """
    payload = {k: case.get(k) for k in CASE_SUBSTANCE_FIELDS}
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def dataset_content_digest(cases: Sequence[Dict[str, Any]]) -> str:
    """The version's identity: every case's record digest, folded in id order."""
    pairs = sorted((str(c.get("case_id")), case_record_digest(c)) for c in cases)
    return _sha256_text(json.dumps(pairs, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Validation


def validate_case(case: Any, *, index: int) -> None:
    where = f"cases[{index}]"
    if not isinstance(case, dict):
        raise DatasetValidationError(f"{where} must be an object, got {type(case).__name__}")
    for field in CASE_CONTENT_FIELDS:
        if field not in case:
            raise DatasetValidationError(
                f"{where} is missing {field!r}; section 226 requires every tracked field "
                f"on every case ({', '.join(CASE_CONTENT_FIELDS)})"
            )
    _safe_id(case.get("case_id"), f"{where}.case_id")

    for field in ("source", "protocol", "owner", "provenance"):
        if not str(case.get(field) or "").strip():
            raise DatasetValidationError(f"{where}.{field} must be a non-empty string")
    if not isinstance(case.get("known_ambiguity"), str):
        # Empty is a legitimate answer ("none declared"); missing or non-text is
        # not, because the field exists to make the ambiguity a stated one.
        raise DatasetValidationError(
            f"{where}.known_ambiguity must be a string (empty means none declared)")
    if case.get("difficulty") not in DIFFICULTIES:
        raise DatasetValidationError(
            f"{where}.difficulty must be one of {DIFFICULTIES}, got {case.get('difficulty')!r}")
    if case.get("qualification") not in QUALIFICATIONS:
        raise DatasetValidationError(
            f"{where}.qualification must be one of {QUALIFICATIONS}, "
            f"got {case.get('qualification')!r}")
    if case.get("expected_result") not in ce.BENCHMARK_OUTCOMES:
        raise DatasetValidationError(
            f"{where}.expected_result must be one of capability_evolution.BENCHMARK_OUTCOMES "
            f"{ce.BENCHMARK_OUTCOMES}, got {case.get('expected_result')!r}")

    coverage = case.get("project_coverage")
    if not isinstance(coverage, list) or not coverage or not all(
            isinstance(x, str) and x.strip() for x in coverage):
        raise DatasetValidationError(
            f"{where}.project_coverage must be a non-empty list of non-empty strings "
            "(which protocol/project this case covers)")

    if not str(case.get("fixture_ref") or "").strip():
        raise DatasetValidationError(
            f"{where}.fixture_ref must name the isolated fixture project this case runs against")
    stages = case.get("stages")
    if not isinstance(stages, list) or not stages or not all(
            isinstance(s, str) and s.strip() for s in stages):
        raise DatasetValidationError(f"{where}.stages must be a non-empty list of stage names")

    mutation = case.get("mutation")
    if not isinstance(mutation, list) or not mutation:
        raise DatasetValidationError(
            f"{where}.mutation must be a non-empty list of "
            "{'path': <relative path>, 'content': <text>} entries -- the declarative, "
            "auditable form capability_evolution._apply_mutation() verifies. A callable "
            "mutation is not accepted here: a stored dataset case must be data.")
    for j, entry in enumerate(mutation):
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not entry.get("path").strip() or not isinstance(entry.get("content"), str)):
            raise DatasetValidationError(
                f"{where}.mutation[{j}] must be {{'path': <relative path>, 'content': <text>}}")
        if Path(entry["path"]).is_absolute() or ".." in Path(entry["path"]).parts:
            raise DatasetValidationError(
                f"{where}.mutation[{j}].path {entry['path']!r} must be a relative path inside "
                "the treatment arm")


def validate_dataset(dataset: Any) -> None:
    """Every section 226 field, on the dataset and on every case."""
    if not isinstance(dataset, dict):
        raise DatasetValidationError(f"a dataset must be an object, got {type(dataset).__name__}")
    for field in DATASET_REQUIRED_FIELDS:
        if field not in dataset:
            raise DatasetValidationError(f"dataset is missing {field!r}")
    _safe_id(dataset.get("dataset_id"), "dataset_id")
    version = dataset.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DatasetValidationError(
            f"dataset version must be an integer >= 1, got {version!r}")
    for field in ("description", "owner", "source", "provenance"):
        if not str(dataset.get(field) or "").strip():
            raise DatasetValidationError(f"dataset {field} must be a non-empty string")

    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise DatasetValidationError("a dataset version must carry at least one case")
    seen = set()
    for i, case in enumerate(cases):
        validate_case(case, index=i)
        cid = case["case_id"]
        if cid in seen:
            raise DatasetValidationError(f"duplicate case_id {cid!r} in the same dataset version")
        seen.add(cid)


# ---------------------------------------------------------------------------
# The versioned registry


def list_versions(root, dataset_id: str) -> List[int]:
    """Every registered version of `dataset_id`, ascending."""
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
    # At least one REGISTERED version, not merely a versions/ directory: an
    # interrupted register leaves the directory behind, and a dataset with no
    # version is not a dataset any caller can load.
    out = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        try:
            if list_versions(root, p.name):
                out.append(p.name)
        except DatasetValidationError:
            continue  # a directory whose name is not a safe dataset id
    return sorted(out)


def load_dataset(root, dataset_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    """Read one stored dataset version. `version=None` reads the latest."""
    if version is None:
        version = latest_version(root, dataset_id)
        if version is None:
            raise DatasetNotFoundError(
                f"no versions of dataset {dataset_id!r} are registered under "
                f"{dataset_dir(root, dataset_id)}")
    path = version_path(root, dataset_id, version)
    if not path.is_file():
        raise DatasetNotFoundError(f"dataset {dataset_id!r} has no version {version} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def register_dataset_version(root, dataset: Dict[str, Any], *,
                             by: str = "benchmark-dataset") -> Dict[str, Any]:
    """Register ONE immutable dataset version, or refuse.

    Three refusals, and each exists because the alternative silently destroys the
    meaning of a version number:
      * this version already exists with DIFFERENT content -> bump instead;
      * this version is behind an already-registered one -> a dataset only moves
        forward, and back-dating would let a later result cite an earlier corpus;
      * this version's cases are identical to the previous version's -> a bump
        that changes no case is not a new dataset, and an eval "against v2" would
        then be indistinguishable from one against v1.
    Re-registering the SAME version with byte-identical cases is idempotent.
    """
    validate_dataset(dataset)
    dataset_id = dataset["dataset_id"]
    version = int(dataset["version"])
    digest = dataset_content_digest(dataset["cases"])

    path = version_path(root, dataset_id, version)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        # The stored version's own integrity is checked FIRST. Without this, a
        # drifted version file could be "re-registered" as an idempotent no-op:
        # its recorded content_digest still matches the dataset being offered,
        # while the cases on disk no longer do, and the drift would be blessed
        # instead of reported.
        actual = dataset_content_digest(existing.get("cases") or [])
        if actual != existing.get("content_digest"):
            raise DatasetVersionConflictError(
                f"{dataset_id} v{version} on disk is {INTEGRITY_DRIFT}: its cases hash to "
                f"{actual[:12]} but the stored version records "
                f"{str(existing.get('content_digest'))[:12]}. Restore it, or register the "
                "edited corpus as a new version -- registering over it would bless the drift."
            )
        if existing.get("content_digest") == digest:
            return existing
        raise DatasetVersionConflictError(
            f"{dataset_id} v{version} is already registered with content digest "
            f"{str(existing.get('content_digest'))[:12]}, and the dataset offered hashes to "
            f"{digest[:12]}. A registered version is immutable: bump to "
            f"v{(latest_version(root, dataset_id) or version) + 1} instead of editing it."
        )

    previous = latest_version(root, dataset_id)
    if previous is not None:
        if version <= previous:
            raise DatasetVersionConflictError(
                f"{dataset_id} is already at v{previous}; a dataset version only moves "
                f"forward, and v{version} would back-date the corpus"
            )
        prior = load_dataset(root, dataset_id, previous)
        if prior.get("content_digest") == digest:
            raise DatasetVersionConflictError(
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
    """Recompute a stored version's digest off disk and compare it to the stored
    one. This is what catches a case edited in place without a version bump."""
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
    """What one version bump actually changed, by case content digest."""
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
# Train/test leakage


def record_tuning_use(root, dataset_id: str, case_id: str, *,
                      subject_id: str, subject_version: str, used_for: str,
                      version: Optional[int] = None,
                      by: str = "benchmark-dataset") -> Dict[str, Any]:
    """Record that ONE case was used to TUNE one subject version.

    Appended to a ledger rather than written onto the case, because a registered
    version is immutable and a tuning record must not be able to look like a case
    edit. The entry carries the case's CONTENT digest, which is what leakage is
    matched on later.
    """
    stored = load_dataset(root, dataset_id, version)
    case = next((c for c in stored.get("cases") or [] if c.get("case_id") == case_id), None)
    if case is None:
        raise DatasetNotFoundError(
            f"dataset {dataset_id} v{stored.get('version')} has no case {case_id!r}")
    if not str(subject_id or "").strip() or not str(subject_version or "").strip():
        raise DatasetValidationError(
            "a tuning use must name the subject_id and subject_version it tuned; "
            "leakage is a claim about a specific version of a specific agent/skill")
    if not str(used_for or "").strip():
        raise DatasetValidationError(
            "a tuning use must say what the case was used for; an unexplained tuning "
            "record cannot be reviewed")
    entry = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": stored.get("version"),
        "case_id": case_id,
        # Both, deliberately: the QUESTION digest is what leakage is matched on
        # later, and the RECORD digest says which stored form of the case the
        # tuning actually saw.
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
    """Which cases of this dataset version were used to tune THIS subject version.

    Matched on the case's QUESTION digest (CASE_SUBSTANCE_FIELDS) across the
    WHOLE ledger, i.e. across every version of the dataset -- a case carried
    forward into v2 keeps the leakage it acquired in v1 even if it was renamed or
    re-owned, and a case whose setup, stages or expected result changed does not
    inherit it.

    `related_tuning_use_case_ids` is the softer signal, reported and never folded
    into the score: the same case tuned a DIFFERENT version of the same subject.
    That is a reviewer's judgment call, not this module's.
    """
    stored = load_dataset(root, dataset_id, version)
    cases = stored.get("cases") or []
    ledger = read_tuning_ledger(root, dataset_id)

    exact = {}
    related = {}
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
# The eval runner (capability_evolution's isolated-fixture machinery, reused)


def default_fixture_resolver(fixtures_root):
    """Resolve `fixture_ref` as a path relative to `fixtures_root`.

    A resolver is a seam rather than a path field on the case so a dataset stays
    portable: the same corpus can be evaluated on a machine that keeps its
    fixtures somewhere else, without editing (and so re-digesting) a case.
    """
    base = Path(fixtures_root).resolve()

    def resolve(fixture_ref: str) -> Path:
        candidate = (base / str(fixture_ref)).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            raise BenchmarkDatasetError(
                f"fixture_ref {fixture_ref!r} resolves to {candidate}, outside "
                f"the fixtures root {base}")
        return candidate

    return resolve


def _environment(root: Path) -> Dict[str, Any]:
    """Section 226's "benchmark results must identify ... environment", read
    rather than declared. The git SHA comes from `change_impact.resolve_sha()`,
    the same read-only git front door the regression-selection chain uses."""
    from .change_impact import resolve_sha

    return {
        "harness_root": str(root),
        "harness_git_sha": resolve_sha(root, "HEAD"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }


def _pseudo_candidate(dataset_id: str, version: int, case: Dict[str, Any]) -> Dict[str, Any]:
    """The record-shaped input `_execute_shadow_run()` takes.

    NOT a capability-evolution candidate and never persisted as one: it makes no
    `transition()`, is never written to the candidates blackboard, and its id is
    outside `mint_candidate_id()`'s `CEC-<hex>` namespace so it can never collide
    with a real one. It exists only to name the workspace and to carry the case's
    own description into the run record.
    """
    return {
        "candidate_id": f"BENCHMARK-EVAL-{dataset_id}-v{version}",
        "affected_capability": f"benchmark case {case['case_id']}",
        "benchmark_plan": f"dataset {dataset_id} v{version}, case {case['case_id']}",
        "experiment_plan": str(case.get("provenance") or ""),
        "acceptance_criteria": [f"expected_result == {case['expected_result']}"],
    }


def run_benchmark_eval(root, dataset_id: str, *, subject: Dict[str, Any],
                       fixture_resolver,
                       harness_factory=None,
                       version: Optional[int] = None,
                       run_id: Optional[str] = None,
                       by: str = "benchmark-dataset") -> Dict[str, Any]:
    """Run EVERY case of one dataset version against one subject, and record it.

    Each case is executed by `capability_evolution._prepare_shadow_run()` and
    `_execute_shadow_run()` -- the SAME isolated two-arm runner
    `run_controlled_experiment()` uses, with the same workspace containment, the
    same fixture fingerprint-before-and-after, the same real `DVHarness.
    run_stage()` in each arm and the same `control_plane.describe_stage()`
    measurement. `allow_execution_stages` is hard-wired False: a benchmark corpus
    must never be able to drive a real build or regression submission.

    `subject` identifies WHAT is being evaluated (`subject_id`, `subject_version`,
    `subject_kind`); `harness_factory` is HOW it runs, the same injected seam
    `run_controlled_experiment()` takes. Two subject versions differ by supplying
    two different factories.

    The run's `status` is judged over the HELD-OUT cases only -- the ones this
    subject version was never tuned on -- and a run whose every case was used for
    tuning is INADMISSIBLE rather than scored, which is section 226's "do not
    evaluate a capability only on examples used to tune it".

    Persists nothing outside `<root>/.dv-harness/benchmark_datasets/<id>/` and
    the shadow-run workspaces under `<root>/.dv-harness/experiments/`. Makes no
    governance transition, mints no candidate, approves nothing.
    """
    root = Path(root).resolve()
    stored = load_dataset(root, dataset_id, version)
    dsv = int(stored["version"])
    cases = list(stored.get("cases") or [])

    subject_id = str((subject or {}).get("subject_id") or "").strip()
    subject_version = str((subject or {}).get("subject_version") or "").strip()
    if not subject_id or not subject_version:
        raise DatasetValidationError(
            "an eval must identify the subject_id and subject_version under evaluation; "
            "section 226 requires a benchmark result to identify the Agent/Skill version")

    integrity = verify_dataset_integrity(root, dataset_id, dsv)
    if integrity["status"] != INTEGRITY_OK:
        raise DatasetVersionConflictError(
            f"{dataset_id} v{dsv} is {integrity['status']}: {integrity['detail']}; "
            "a result measured against a drifted corpus cites a version that no longer "
            "describes what was run")

    leakage = leakage_report(root, dataset_id, subject_id=subject_id,
                             subject_version=subject_version, version=dsv)
    leaked = set(leakage["leaked_case_ids"])

    started_at = _now()
    run_id = run_id or "BEV-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
        _sha256_text(f"{dataset_id}|{dsv}|{subject_id}|{subject_version}|{started_at}")[:8])

    results: List[Dict[str, Any]] = []
    for case in cases:
        results.append(_run_one_case(
            root, stored, case, run_id=run_id, harness_factory=harness_factory,
            fixture_resolver=fixture_resolver, leaked=case["case_id"] in leaked))

    summary = _summarize(results)
    if leakage["status"] == LEAKAGE_FULL:
        status = RUN_INADMISSIBLE
    elif summary["held_out_total"] == 0:
        status = RUN_NOT_AVAILABLE
    elif summary["held_out_matched"] == summary["held_out_total"]:
        status = RUN_MET
    else:
        status = RUN_NOT_MET

    record = {
        "schema_version": SCHEMA_VERSION,
        "produced_by": BENCHMARK_EVAL_PRODUCER,
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
        "cases": results,
        "summary": summary,
        "leakage": {k: v for k, v in leakage.items() if k != "leaked_detail"},
        "status": status,
        "acceptance_criteria_machine_evaluated": True,
    }
    path = eval_runs_dir(root, dataset_id) / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    record["record_path"] = str(path)
    return record


def _run_one_case(root: Path, stored: Dict[str, Any], case: Dict[str, Any], *,
                  run_id: str, harness_factory, fixture_resolver,
                  leaked: bool) -> Dict[str, Any]:
    """One case, through capability_evolution's own shadow-run machinery."""
    dataset_id = stored["dataset_id"]
    dsv = int(stored["version"])
    base = {
        "case_id": case["case_id"],
        "case_record_digest": case_record_digest(case),
        "case_question_digest": case_question_digest(case),
        "difficulty": case.get("difficulty"),
        "qualification": case.get("qualification"),
        "protocol": case.get("protocol"),
        "known_ambiguity": case.get("known_ambiguity", ""),
        "expected_result": case["expected_result"],
        "used_for_tuning": bool(leaked),
        "stages": list(case.get("stages") or []),
    }
    pseudo = _pseudo_candidate(dataset_id, dsv, case)
    case_run_id = "BEV-{}-{}".format(
        _safe_id(case["case_id"], "case_id")[:24],
        _sha256_text(f"{run_id}|{case['case_id']}|{_now()}")[:10])

    def errored(exc: BaseException) -> Dict[str, Any]:
        return {**base, "observed_result": None, "outcome": CASE_ERRORED,
                "error": f"{type(exc).__name__}: {exc}",
                "run_id": case_run_id, "record_path": None, "workspace": None}

    # PREPARATION refusals describe the CASE -- an unresolvable fixture_ref, a
    # fixture that is not a directory, a workspace id already used. They are a
    # defect in the corpus, recorded as an ERRORED case (never a match) so the
    # rest of the eval still runs and the reason survives in the record.
    try:
        fixture = fixture_resolver(case["fixture_ref"])
        fixture, stages, workspace, case_run_id = ce._prepare_shadow_run(
            root, pseudo, fixture_project=fixture, stages=list(case["stages"]),
            run_id=case_run_id)
    except Exception as exc:  # noqa: BLE001 -- recorded, never silently dropped
        return errored(exc)

    # EXECUTION refusals describe the RUN's trustworthiness -- the source fixture
    # changed while the case ran, a mutation wrote outside the treatment copy, a
    # stage that would have reached the execution layer. Those are never
    # downgraded to a failed case: the whole eval stops, because a measurement
    # taken without isolation is one nobody should read.
    try:
        record, record_path, comparison, _changed = ce._execute_shadow_run(
            root, pseudo,
            fixture=fixture, stages=stages, workspace=workspace, run_id=case_run_id,
            run_kind=CASE_RUN_KIND, produced_by=BENCHMARK_EVAL_PRODUCER,
            mutation=list(case["mutation"]),
            user_goal=f"benchmark dataset {dataset_id} v{dsv} case {case['case_id']}",
            harness_factory=harness_factory,
            # Hard-wired, never a parameter: a stored benchmark corpus must never
            # be able to reach the execution layer and spend farm resources.
            allow_execution_stages=False,
            started_at=_now())
    except ce.ExperimentIsolationError as exc:
        raise BenchmarkEvalIsolationError(
            f"case {case['case_id']} of {dataset_id} v{dsv} could not be run in "
            f"isolation: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 -- recorded, never silently dropped
        return errored(exc)

    observed = comparison["outcome"]
    return {
        **base,
        "observed_result": observed,
        "outcome": CASE_MATCHED if observed == case["expected_result"] else CASE_MISMATCHED,
        "error": None,
        "run_id": case_run_id,
        "record_path": str(record_path),
        "workspace": str(workspace),
        "delta": comparison["delta"],
        "regression_safety": record.get("regression_safety"),
        "measured_at": record.get("measured_at"),
    }


def _summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    held = [r for r in results if not r.get("used_for_tuning")]

    def rate(matched: int, total: int) -> Optional[float]:
        return round(matched / total, 4) if total else None

    matched = sum(1 for r in results if r["outcome"] == CASE_MATCHED)
    held_matched = sum(1 for r in held if r["outcome"] == CASE_MATCHED)
    return {
        "total": len(results),
        "matched": matched,
        "mismatched": sum(1 for r in results if r["outcome"] == CASE_MISMATCHED),
        "errored": sum(1 for r in results if r["outcome"] == CASE_ERRORED),
        "match_rate": rate(matched, len(results)),
        "held_out_total": len(held),
        "held_out_matched": held_matched,
        "held_out_match_rate": rate(held_matched, len(held)),
        "mismatched_case_ids": sorted(r["case_id"] for r in results
                                      if r["outcome"] != CASE_MATCHED),
    }


def read_eval_runs(root, dataset_id: str) -> List[Dict[str, Any]]:
    """Every recorded eval run for a dataset, oldest first."""
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
    s, lk = record["summary"], record["leakage"]
    lines = [
        f"benchmark eval {record['run_id']}: {record['status']}",
        f"  dataset       {record['dataset_id']} v{record['dataset_version']} "
        f"(digest {str(record.get('dataset_content_digest'))[:12]})",
        f"  subject       {record['subject']['subject_id']} "
        f"@{record['subject']['subject_version']} ({record['subject']['subject_kind']})",
        f"  environment   python {record['environment']['python_version']}, "
        f"git {str(record['environment'].get('harness_git_sha'))[:12]}",
        f"  cases         {s['matched']}/{s['total']} matched "
        f"({s['mismatched']} mismatched, {s['errored']} errored)",
        f"  held out      {s['held_out_matched']}/{s['held_out_total']} matched "
        f"(leakage {lk['status']}, {lk['leaked_count']} case(s) used for tuning)",
    ]
    for case in record["cases"]:
        flag = " [TUNED-ON]" if case.get("used_for_tuning") else ""
        lines.append(f"    {case['outcome']:<11} {case['case_id']}{flag}  "
                     f"expected={case['expected_result']} observed={case.get('observed_result')}"
                     + (f"  {case['error']}" if case.get("error") else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (shared by `dv-harness benchmark-dataset` and `python -m ...`)


def execute_verb(verb: str, *, root, dataset_id: Optional[str] = None,
                 json_file: Optional[str] = None, version: Optional[int] = None,
                 old_version: Optional[int] = None, new_version: Optional[int] = None,
                 case_id: Optional[str] = None, subject_id: Optional[str] = None,
                 subject_version: Optional[str] = None, used_for: Optional[str] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation. Returns (text, exit_code): 0 fine, 1 a real finding
    (content drift, leakage present, a recorded run that was NOT_MET), 2 nothing
    to report or a usage error.

    There is deliberately no `eval` verb -- see the module docstring.
    """
    root = Path(root)

    if verb == "register":
        if not json_file:
            return ("benchmark-dataset register requires --json-file <dataset.json>", 2)
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
                    f"NOT_AVAILABLE: no benchmark datasets under {datasets_dir(root)}"), 2
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
        lines = [f"{len(rows)} benchmark dataset(s):"]
        for r in rows:
            lines.append(f"  {r['dataset_id']}  versions={r['versions']}  "
                         f"latest=v{r['latest_version']} ({r['case_count']} cases, "
                         f"digest {str(r['content_digest'])[:12]}, owner {r['owner']})")
        return "\n".join(lines), 0

    if not dataset_id:
        return (f"benchmark-dataset {verb} requires --dataset-id", 2)

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
            lines.append(f"  v{r['version']}  {r['status']}  "
                         f"{r['case_count']} case(s)"
                         + (f"  {r['detail']}" if r.get("detail") else ""))
        return "\n".join(lines), code

    if verb == "diff":
        if old_version is None or new_version is None:
            return "benchmark-dataset diff requires --old-version and --new-version", 2
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
            return ("benchmark-dataset record-tuning-use requires --case-id, --subject-id, "
                    "--subject-version and --used-for", 2)
        entry = record_tuning_use(root, dataset_id, case_id, subject_id=subject_id,
                                  subject_version=subject_version, used_for=used_for,
                                  version=version)
        return (json.dumps(entry, indent=2, sort_keys=True) if as_json else
                f"recorded tuning use: {entry['case_id']} "
                f"(question digest {entry['case_question_digest'][:12]}) "
                f"tuned {entry['subject_id']}@{entry['subject_version']}"), 0

    if verb == "leakage":
        if not (subject_id and subject_version):
            return "benchmark-dataset leakage requires --subject-id and --subject-version", 2
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
            f"  related use {report['related_tuning_use_case_ids']}",
        ]), code)

    if verb == "runs":
        runs = read_eval_runs(root, dataset_id)
        if not runs:
            return f"NOT_AVAILABLE: no recorded eval runs for {dataset_id!r}", 2
        if as_json:
            return json.dumps(runs, indent=2), (
                1 if any(r.get("status") != RUN_MET for r in runs) else 0)
        lines = [f"{len(runs)} eval run(s) for {dataset_id}:"]
        for r in runs:
            s = r.get("summary") or {}
            lines.append(f"  {r.get('run_id')}  v{r.get('dataset_version')}  "
                         f"{r.get('subject', {}).get('subject_id')}"
                         f"@{r.get('subject', {}).get('subject_version')}  "
                         f"{r.get('status')}  "
                         f"held_out={s.get('held_out_matched')}/{s.get('held_out_total')}")
        return "\n".join(lines), (1 if any(r.get("status") != RUN_MET for r in runs) else 0)

    return f"unknown benchmark-dataset verb {verb!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.benchmark_dataset",
        description="Spec section 226 agent/skill benchmark dataset governance: a versioned, "
                    "content-addressed eval corpus with per-case expected outcomes, integrity "
                    "verification, version diffing and train/test leakage tracking. Registers "
                    "and inspects; running an eval is a Python call (see the module docstring).")
    ap.add_argument("verb", choices=("register", "list", "verify", "diff",
                                      "record-tuning-use", "leakage", "runs"))
    ap.add_argument("--root", default=".", help="Project root.")
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--json-file", default=None, help="register: the dataset version JSON file.")
    ap.add_argument("--version", type=int, default=None,
                    help="Operate on this dataset version (default: the latest).")
    ap.add_argument("--old-version", type=int, default=None, help="diff: the earlier version.")
    ap.add_argument("--new-version", type=int, default=None, help="diff: the later version.")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--subject-id", default=None, help="The agent/skill being evaluated or tuned.")
    ap.add_argument("--subject-version", default=None)
    ap.add_argument("--used-for", default=None,
                    help="record-tuning-use: what the case was used to tune.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.verb, root=a.root, dataset_id=a.dataset_id, json_file=a.json_file,
            version=a.version, old_version=a.old_version, new_version=a.new_version,
            case_id=a.case_id, subject_id=a.subject_id, subject_version=a.subject_version,
            used_for=a.used_for, as_json=a.json)
    except BenchmarkDatasetError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
