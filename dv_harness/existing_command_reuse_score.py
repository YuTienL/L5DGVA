"""dv_harness/existing_command_reuse_score.py -- ranks existing DE command.txt
commands against a new vPlan-driven need, so a generator/author asks "can an
existing command already do this" before writing a new one.

THE GAP THIS CLOSES
-------------------
`.claude/skills/CORE/command-inventory/SKILL.md` already treats existing DE
command.txt as a "reusable capability baseline" and requires a
`.dv-workflow/command_inventory.csv` inventory (COMMAND_ID / PROTOCOL /
COMMAND / PARAMETERS / SOURCE / USER_SCOPE / HANDLER / VIP_SEQUENCE / STATUS /
CONFIDENCE), but nothing in this repo actually RANKS that inventory against a
new need -- the skill says "reuse it" in prose and leaves the comparison to
whoever is authoring the new command.txt. This module is that comparison.

It is deliberately NOT `dv_harness/de_command_style_learning.py` (a
concurrently-built module in this same batch that LEARNS DE command-naming
STYLE from real command.txt files and would emit `DECommandRegistryIR`-shaped
records). This module never imports it and never assumes its exact field
names -- `existing_commands` is accepted as a plain list of dicts, read
through the alias-tolerant `_get()` helper below so it works equally against
that module's eventual `DECommandRegistryIR` shape, against
`subsystem_command_contract.py`'s SYS-8 contract shape (the closest existing
per-command record this repo has:
`command_name`/`command_category`/`arguments`/`target_agent`/`target_vip`/
`target_sequence`/`source_command_file`), and against a literal
`command_inventory.csv`-derived dict (`COMMAND`/`PARAMETERS`/`SOURCE`/
`HANDLER`/`VIP_SEQUENCE`). Whichever shape a caller actually has, the fields
this module does not recognise are simply not used for scoring -- never
guessed at.

FOUR RANKING DIMENSIONS, PER THE TASK
--------------------------------------
1. **Semantic-name match** -- a deterministic LEXICAL token-overlap (Jaccard)
   score over normalised identifier/description tokens. This is explicitly
   NOT an embedding/ML semantic model: no such model exists anywhere in this
   codebase, and inventing one here would be exactly the kind of
   unverifiable machinery the Evidence Truth Rule forbids. "Semantic" is
   satisfied by comparing what the name/description/category actually SAY,
   not by a black-box similarity number nobody could audit.
2. **Argument-shape compatibility** -- position-aligned comparison of
   argument ROLES (ADDRESS/VALUE/DESTINATION/OTHER, the same vocabulary
   `subsystem_command_contract.schema.json`'s `arguments[].role` already
   uses) when structured, or of raw parameter tokens when only a flat
   `PARAMETERS` string/list is available (a weaker, explicitly-labelled form
   of the same comparison).
3. **Branch-ownership compatibility** -- `block` / `branch_a*` / `branch_fw`
   / `branch_b*`, the canonical vocabulary from
   `.claude/skills/CORE/pattern-architecture/SKILL.md` and
   `.claude/skills/CORE/branch-mapper/SKILL.md` (read before writing this
   module, per the task instructions). These four layers do genuinely
   different things (SoC-global one-shot prologue / per-port DUT+PHY init /
   per-port FW service loop / per-port VIP-driven test body), so a command
   whose declared branch layer DISAGREES with the need's is not a weaker
   match -- it is architecturally the wrong kind of command, and is
   EXCLUDED from ranking entirely rather than merely scored low. A
   non-canonical branch label (e.g. `BranchA0` with no underscore) is still
   resolved to its family so the Engineering Discipline Rules'
   "legacy/pre-v8 naming ... found during any review must be flagged and
   corrected" rule has something to flag, rather than being silently
   dropped as unrecognised.
4. **Real historical PASS evidence** -- read-only from `evidence_db.py`'s
   `regression_verdict_history` table (the same table
   `trend_analysis.detect_pattern_regressions()` and
   `golden_scenario.evaluate_freshness()` already read), keyed by whichever
   of the candidate's own declared `pattern` / `command_name` / the stem of
   `source_command_file` actually has recorded rows. NEVER invented: a
   candidate with no recorded history reports `NO_RECORDED_HISTORY`, not a
   pass rate of 0 or 1, and contributes zero to the composite score exactly
   the same way a candidate that recorded 0 real passes does -- the
   numbers coincide, but the machine-readable `status` and the
   human-readable reason never do.

NO_REUSE_CANDIDATE, NOT A FORCED LOW-CONFIDENCE PICK
-----------------------------------------------------
A candidate must clear TWO independent bars before it is ever returned as a
usable match: (a) `composite_score >= MIN_PLAUSIBLE_SCORE`, and (b) real,
non-zero evidence on at least one of the two OBSERVABLE dimensions (semantic
name overlap or argument-shape overlap) -- branch-family agreement or
historical-evidence presence ALONE is not enough, because dozens of unrelated
commands can share one branch family, and because contributing zero to the
score from "no recorded history" must never be read as supporting evidence.
When no existing command clears both bars, `evaluate_reuse()` reports
`NO_REUSE_CANDIDATE` with a real, named reason -- it never falls back to
"least bad" candidate, which would look like a finding to a caller that only
reads `top_candidate`.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It does not write a command.txt, does not decide anything, does not run a
build/regression/LSF job, and there is deliberately no stage gate -- a gate
that passed because "some command scored above a number" would encourage
picking the reuse candidate instead of checking it. It also never trusts a
candidate's own self-declared `STATUS`/`CONFIDENCE` (a `command_inventory.csv`
discovery-confidence column, or any similar self-attested field) as evidence
of test PASS history -- those are carried through verbatim as
`declared_status`/`declared_confidence` for a human's information only; the
ONLY thing that counts as historical PASS evidence is a real
`regression_verdict_history` row read from `evidence_db.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .inference import CONFIDENCE_LEVELS as _INFERENCE_CONFIDENCE_LEVELS

# `requirement_contract.py` / `confidence_calibration.py` already reuse
# inference.py's HIGH/MEDIUM/LOW vocabulary for a differently-scored notion of
# confidence than score_confidence() itself computes -- this module does the
# same, for its own composite reuse score. Asserted at import so a future
# change to that vocabulary is caught here rather than silently diverging.
assert list(_INFERENCE_CONFIDENCE_LEVELS) == ["HIGH", "MEDIUM", "LOW"], (
    "inference.CONFIDENCE_LEVELS changed shape; existing_command_reuse_score.py's "
    "confidence tiers assume exactly [HIGH, MEDIUM, LOW]")

SCHEMA_VERSION = "1.0"

REUSE_CANDIDATES_FOUND = "REUSE_CANDIDATES_FOUND"
NO_REUSE_CANDIDATE = "NO_REUSE_CANDIDATE"

#: Composite-score weights. Sum to 1.0, asserted below -- a weight change
#: must be a deliberate edit here, never a silent rebalance.
WEIGHT_NAME = 0.40
WEIGHT_ARGS = 0.25
WEIGHT_BRANCH = 0.20
WEIGHT_HISTORY = 0.15
assert abs((WEIGHT_NAME + WEIGHT_ARGS + WEIGHT_BRANCH + WEIGHT_HISTORY) - 1.0) < 1e-9

#: Confidence-tier bands over the composite score.
HIGH_THRESHOLD = 0.65
MEDIUM_THRESHOLD = 0.35

#: The plausibility floor a candidate must clear on the composite score
#: itself -- see module docstring's "NO_REUSE_CANDIDATE, NOT A FORCED
#: LOW-CONFIDENCE PICK".
MIN_PLAUSIBLE_SCORE = 0.20

#: Canonical branch-ownership families, per pattern-architecture/SKILL.md and
#: branch-mapper/SKILL.md -- read before writing this module, per the task
#: instructions. `block` and `branch_fw` carry no per-port index; `branch_a*`
#: and `branch_b*` do.
BRANCH_FAMILIES = ("block", "branch_fw", "branch_a", "branch_b")

_CANONICAL_BRANCH_RE = re.compile(r"^(block|branch_fw|branch_a|branch_b)(\d*)$")
_LEGACY_BRANCH_RE = re.compile(r"^(block|branchfw|brancha\d*|branchb\d*)$")


class ReuseScoreError(Exception):
    """Base for every refusal in this module."""


class NeedValidationError(ReuseScoreError):
    """`need` is not a usable dict."""


# --- field-alias normalisation ----------------------------------------------
#
# `existing_commands` entries may arrive shaped like `subsystem_command_
# contract.py`'s SYS-8 record (lowercase, e.g. `command_name`), like a literal
# `.dv-workflow/command_inventory.csv` row turned into a dict (uppercase CSV
# columns, e.g. `COMMAND`), or like whatever `de_command_style_learning.py`'s
# eventual `DECommandRegistryIR` actually spells them -- this module imports
# none of those modules and instead reads through a fixed alias table, so it
# degrades gracefully (missing concept -> None/UNKNOWN) rather than crashing
# or guessing a field name.

_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "command_name": ("command_name", "COMMAND", "command", "NAME", "name"),
    "command_id": ("command_id", "COMMAND_ID", "id", "ID"),
    "protocol": ("protocol", "PROTOCOL"),
    "command_category": ("command_category", "COMMAND_CATEGORY", "category", "CATEGORY"),
    "arguments": ("arguments", "PARAMETERS", "parameters", "args"),
    "source_command_file": ("source_command_file", "SOURCE", "source", "source_file"),
    "target_agent": ("target_agent", "HANDLER", "handler"),
    "target_sequence": ("target_sequence", "VIP_SEQUENCE", "vip_sequence"),
    "target_vip": ("target_vip", "VIP", "vip"),
    "branch_layer": ("branch_layer", "branch_role", "layer", "BRANCH_LAYER", "branch", "BRANCH"),
    "pattern": ("pattern", "PATTERN", "source_pattern", "historical_pattern"),
    "description": ("description", "DESCRIPTION"),
    "keywords": ("keywords", "KEYWORDS"),
    "declared_status": ("status", "STATUS", "user_scope", "USER_SCOPE"),
    "declared_confidence": ("confidence", "CONFIDENCE"),
}


def _get(d: dict, concept: str, default=None):
    if not isinstance(d, dict):
        return default
    for key in _FIELD_ALIASES.get(concept, (concept,)):
        if key in d and d[key] not in (None, ""):
            return d[key]
    return default


# --- semantic-name match (lexical token overlap) ----------------------------

_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_NEED_TEXT_KEYS = ("description", "DESCRIPTION", "summary", "SUMMARY",
                   "operation", "OPERATION", "intent", "INTENT",
                   "title", "TITLE", "name", "NAME")
_CANDIDATE_TEXT_KEYS = ("command_name", "COMMAND", "command_id", "COMMAND_ID",
                        "command_category", "COMMAND_CATEGORY", "category", "CATEGORY",
                        "target_sequence", "VIP_SEQUENCE", "target_vip", "VIP",
                        "description", "DESCRIPTION")


def _tokenize(text: Any) -> set:
    if not text:
        return set()
    s = _CAMEL_BOUNDARY_RE.sub("_", str(text))
    return {p.lower() for p in _TOKEN_SPLIT_RE.split(s) if p}


def _collect_text(d: dict, keys: Sequence[str]) -> str:
    if not isinstance(d, dict):
        return ""
    return " ".join(str(d[k]) for k in keys if d.get(k))


def _collect_keywords(d: dict) -> set:
    if not isinstance(d, dict):
        return set()
    for key in ("keywords", "KEYWORDS"):
        v = d.get(key)
        if isinstance(v, (list, tuple)):
            return {str(x).strip().lower() for x in v if str(x).strip()}
    return set()


def semantic_name_match(need: dict, candidate: dict) -> dict:
    """Deterministic Jaccard token-overlap score in [0, 1]. `status` is
    `NO_TEXT_TO_COMPARE` when either side has no usable text/keywords at all
    (score 0.0, but for a different, honestly-distinct reason than genuine
    zero overlap)."""
    need_tokens = _tokenize(_collect_text(need, _NEED_TEXT_KEYS)) | _collect_keywords(need)
    cand_tokens = _tokenize(_collect_text(candidate, _CANDIDATE_TEXT_KEYS)) | _collect_keywords(candidate)
    if not need_tokens or not cand_tokens:
        return {"score": 0.0, "status": "NO_TEXT_TO_COMPARE",
                "need_tokens": sorted(need_tokens), "candidate_tokens": sorted(cand_tokens),
                "overlap": []}
    overlap = need_tokens & cand_tokens
    union = need_tokens | cand_tokens
    score = round(len(overlap) / len(union), 4) if union else 0.0
    status = "LEXICAL_OVERLAP" if overlap else "NO_LEXICAL_OVERLAP"
    return {"score": score, "status": status,
            "need_tokens": sorted(need_tokens), "candidate_tokens": sorted(cand_tokens),
            "overlap": sorted(overlap)}


# --- argument-shape compatibility --------------------------------------------


def _normalize_arguments(value: Any) -> Optional[List[str]]:
    """Turns whatever shape an `arguments`/`PARAMETERS` field arrives in into
    an ordered list of upper-cased role/param tokens, or `None` when nothing
    usable was supplied (distinct from an explicit empty list, which means
    "declared to take no arguments")."""
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\s]+", value) if p.strip()]
        return [p.upper() for p in parts]
    if isinstance(value, (list, tuple)):
        if not value:
            return []
        if all(isinstance(v, dict) for v in value):
            def _pos(d):
                p = d.get("position")
                return p if isinstance(p, int) else 0
            ordered = sorted(value, key=_pos)
            roles = []
            for d in ordered:
                role = d.get("role") or d.get("ROLE") or d.get("name") or d.get("NAME")
                roles.append(str(role).upper() if role else "OTHER")
            return roles
        return [str(v).strip().upper() for v in value if str(v).strip()]
    return None


def argument_shape_compatibility(need_args_raw: Any, candidate_args_raw: Any) -> dict:
    """Position-aligned role/token comparison. `status` distinguishes a real
    comparison (`COMPARED`) from the three ways it could not be made -- never
    silently treated the same as a genuine mismatch."""
    need_roles = _normalize_arguments(need_args_raw)
    cand_roles = _normalize_arguments(candidate_args_raw)
    if need_roles is None and cand_roles is None:
        return {"status": "UNKNOWN_BOTH", "score": 0.0, "need_roles": None, "candidate_roles": None}
    if need_roles is None:
        return {"status": "UNKNOWN_NEED_ARGS", "score": 0.0, "need_roles": None,
                "candidate_roles": cand_roles}
    if cand_roles is None:
        return {"status": "UNKNOWN_CANDIDATE_ARGS", "score": 0.0, "need_roles": need_roles,
                "candidate_roles": None}
    if not need_roles or not cand_roles:
        matched_both_empty = (not need_roles and not cand_roles)
        return {"status": "COMPARED", "score": 1.0 if matched_both_empty else 0.0,
                "need_roles": need_roles, "candidate_roles": cand_roles}
    max_len = max(len(need_roles), len(cand_roles))
    matches = sum(1 for i in range(min(len(need_roles), len(cand_roles)))
                  if need_roles[i] == cand_roles[i])
    return {"status": "COMPARED", "score": round(matches / max_len, 4),
            "need_roles": need_roles, "candidate_roles": cand_roles}


# --- branch-ownership compatibility ------------------------------------------


def normalize_branch_label(label: Any) -> Tuple[Optional[str], Optional[str]]:
    """Resolves a branch label to one of `BRANCH_FAMILIES`, plus a naming flag.

    Returns `(family, flag)`:
      * `(None, None)`             -- no label supplied at all.
      * `(family, None)`           -- canonical `block`/`branch_fw`/
                                       `branch_a[N]`/`branch_b[N]` naming.
      * `(family, "LEGACY_NON_CANONICAL_NAMING")` -- recognisable but not the
        canonical underscore/lowercase form (e.g. `BranchA0`, `branch-b2`) --
        per the Engineering Discipline Rules' "legacy/pre-v8 naming ... found
        during any review must be flagged and corrected, not silently left in
        place", this is resolved for comparison AND flagged, never one or
        the other.
      * `(None, "UNRECOGNIZED_BRANCH_LABEL")` -- a label was supplied but
        matches no known branch-layer naming at all.
    """
    if not label:
        return None, None
    s = str(label).strip()
    m = _CANONICAL_BRANCH_RE.match(s.lower())
    if m:
        return m.group(1), None
    collapsed = re.sub(r"[\s_-]", "", s.lower())
    lm = _LEGACY_BRANCH_RE.match(collapsed)
    if lm:
        token = lm.group(1)
        if token == "block":
            return "block", "LEGACY_NON_CANONICAL_NAMING"
        if token == "branchfw":
            return "branch_fw", "LEGACY_NON_CANONICAL_NAMING"
        if token.startswith("brancha"):
            return "branch_a", "LEGACY_NON_CANONICAL_NAMING"
        return "branch_b", "LEGACY_NON_CANONICAL_NAMING"
    return None, "UNRECOGNIZED_BRANCH_LABEL"


def branch_compatibility(need_branch_layer: Any, candidate_branch_layer: Any) -> dict:
    """`result` is `MATCH` (same family -- block/branch_a/branch_fw/branch_b
    genuinely do different jobs per pattern-architecture/SKILL.md, so same
    family is required, not merely similar), `MISMATCH` (different known
    families -- excluded from ranking by the caller, see module docstring),
    or `UNKNOWN` (either side's branch layer could not be determined --
    scored neutrally, never assumed compatible)."""
    need_family, need_flag = normalize_branch_label(need_branch_layer)
    cand_family, cand_flag = normalize_branch_label(candidate_branch_layer)
    flags = [f for f in (need_flag, cand_flag) if f]
    if need_family is None or cand_family is None:
        result, score = "UNKNOWN", 0.0
    elif need_family == cand_family:
        result, score = "MATCH", 1.0
    else:
        result, score = "MISMATCH", 0.0
    return {"result": result, "score": score, "need_family": need_family,
            "candidate_family": cand_family, "flags": flags}


# --- real historical PASS evidence (evidence_db.py, read-only) --------------


def _candidate_history_keys(candidate: dict) -> List[str]:
    """Candidate-declared identifiers to try, in priority order, against
    `regression_verdict_history.pattern` -- an explicit `pattern` field first
    (the candidate's own claim of which regression pattern exercises it),
    then its `command_name`, then the filename stem of its
    `source_command_file`. Never invented: a candidate declaring none of
    these simply has no key to look history up by."""
    keys: List[str] = []

    def add(v):
        s = str(v).strip() if v not in (None, "") else ""
        if s and s not in keys:
            keys.append(s)

    add(_get(candidate, "pattern"))
    add(_get(candidate, "command_name"))
    source_file = _get(candidate, "source_command_file")
    if source_file:
        add(Path(str(source_file)).stem)
    return keys


def query_command_history(store, keys: Sequence[str]) -> dict:
    """Reads `regression_verdict_history` (evidence_db.py, real, read-only)
    for the first of `keys` that has any recorded rows. NEVER computes a
    pass rate from zero rows -- `pass_rate` is present ONLY under
    `status == "RECORDED"`."""
    if store is None:
        return {"status": "NOT_AVAILABLE",
                "reason": "no evidence database available to this evaluation",
                "keys_checked": list(keys)}
    if not keys:
        return {"status": "NO_RECORDED_HISTORY", "keys_checked": [],
                "reason": "candidate declared no pattern/command_name/source_command_file "
                          "to key an evidence lookup on"}
    for key in keys:
        rows = store.query(
            "SELECT verdict_passed, job_id, git_sha, recorded_at "
            "FROM regression_verdict_history WHERE pattern = ? ORDER BY recorded_at DESC",
            [key],
        )
        if rows:
            total = len(rows)
            passed = sum(1 for r in rows if r[0])
            latest = rows[0]
            return {
                "status": "RECORDED",
                "matched_key": key,
                "keys_checked": list(keys),
                "total_runs": total,
                "pass_count": passed,
                "fail_count": total - passed,
                "pass_rate": round(passed / total, 4),
                "latest_verdict_passed": bool(latest[0]),
                "latest_job_id": latest[1],
                "latest_git_sha": latest[2],
                "evidence": [
                    f"regression_verdict_history: pattern={key} passed={bool(r[0])} "
                    f"job_id={r[1]} git_sha={r[2]} recorded_at={r[3]}"
                    for r in rows[:10]
                ],
            }
    return {"status": "NO_RECORDED_HISTORY", "keys_checked": list(keys),
            "reason": f"no regression_verdict_history rows for any of {list(keys)!r}"}


def _open_evidence_store(*, store=None, root=None, db_path=None):
    """Returns `(store_or_None, owns_it)`. Never constructs an
    `EvidenceStore` that would create a database on disk -- a caller asking
    "what is the reuse evidence for this need" must never conjure an empty
    evidence database into existence."""
    if store is not None:
        return store, False
    if root is None and db_path is None:
        return None, False
    from . import evidence_db
    path = Path(db_path) if db_path else evidence_db.default_db_path(Path(root))
    if not Path(path).exists():
        return None, False
    return evidence_db.EvidenceStore(path, read_only=True), True


# --- composite scoring --------------------------------------------------------


def _confidence_tier(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def score_candidate(need: dict, candidate: dict, branch: dict, store) -> dict:
    """Scores one branch-compatible candidate. `branch` is the already-
    computed `branch_compatibility()` result (never `MISMATCH` -- the caller
    excludes those before reaching here)."""
    name = semantic_name_match(need, candidate)
    args = argument_shape_compatibility(_get(need, "arguments"), _get(candidate, "arguments"))
    history = query_command_history(store, _candidate_history_keys(candidate))
    history_score = history.get("pass_rate")
    if history_score is None:
        history_score = 0.0
    composite = round(
        WEIGHT_NAME * name["score"] + WEIGHT_ARGS * args["score"]
        + WEIGHT_BRANCH * branch["score"] + WEIGHT_HISTORY * history_score,
        4,
    )
    return {
        "command_name": _get(candidate, "command_name") or "UNKNOWN",
        "command_id": _get(candidate, "command_id"),
        "protocol": _get(candidate, "protocol"),
        "source_command_file": _get(candidate, "source_command_file"),
        "declared_status": _get(candidate, "declared_status"),
        "declared_confidence": _get(candidate, "declared_confidence"),
        "composite_score": composite,
        "confidence": _confidence_tier(composite),
        "semantic_name_match": name,
        "argument_shape_compatibility": args,
        "branch_ownership_compatibility": branch,
        "historical_pass_evidence": history,
    }


def _need_has_any_signal(need: dict) -> bool:
    text_tokens = _tokenize(_collect_text(need, _NEED_TEXT_KEYS)) | _collect_keywords(need)
    return bool(text_tokens or _get(need, "arguments") not in (None, "")
                or _get(need, "branch_layer"))


def evaluate_reuse(need: dict, existing_commands: Sequence[dict], *,
                    store=None, root=None, db_path=None) -> dict:
    """The full ranking. `need` is a plain dict describing the vPlan-driven
    operation (recognised concepts: `description`/`summary`/`operation`/
    `intent`/`title`/`name`, `keywords`, `arguments`, `branch_layer`).
    `existing_commands` is a plain list of dicts (see module docstring for
    the shapes this reads through `_get()`'s alias table). `store` is an
    already-open `evidence_db.EvidenceStore` (test/caller-injected seam,
    never closed by this function); otherwise `root`/`db_path` open one
    read-only for the duration of this call, or leave historical evidence
    `NOT_AVAILABLE` when there is nothing to open.

    Returns a report dict; see module docstring for the NO_REUSE_CANDIDATE
    rule. Runs no build/regression/job and writes nothing."""
    if not isinstance(need, dict):
        raise NeedValidationError("need must be a dict describing the vPlan-driven operation")
    evaluated_at = datetime.now(timezone.utc).isoformat()
    base = {"schema_version": SCHEMA_VERSION, "need": need, "evaluated_at": evaluated_at,
            "candidates": [], "below_floor_candidates": [], "excluded_branch_mismatch": [],
            "top_candidate": None}

    if not existing_commands:
        return {**base, "status": NO_REUSE_CANDIDATE,
                "reason": "NO_EXISTING_COMMANDS_SUPPLIED: existing_commands is empty"}
    if not _need_has_any_signal(need):
        return {**base, "status": NO_REUSE_CANDIDATE,
                "reason": "INSUFFICIENT_NEED_DESCRIPTION: the need supplied no description/"
                          "summary/operation/intent/title/name/keywords, no arguments and no "
                          "branch_layer -- nothing here to compare an existing command against"}

    opened_store, owns_store = _open_evidence_store(store=store, root=root, db_path=db_path)
    try:
        excluded: List[dict] = []
        scored: List[dict] = []
        for candidate in existing_commands:
            if not isinstance(candidate, dict):
                excluded.append({"candidate": repr(candidate), "reason": "CANDIDATE_NOT_A_DICT"})
                continue
            branch = branch_compatibility(_get(need, "branch_layer"), _get(candidate, "branch_layer"))
            if branch["result"] == "MISMATCH":
                excluded.append({
                    "command_name": _get(candidate, "command_name") or "UNKNOWN",
                    "reason": "BRANCH_OWNERSHIP_MISMATCH",
                    "need_branch_family": branch["need_family"],
                    "candidate_branch_family": branch["candidate_family"],
                    "flags": branch["flags"],
                })
                continue
            scored.append(score_candidate(need, candidate, branch, opened_store))
    finally:
        if owns_store and opened_store is not None:
            opened_store.close()

    def _is_plausible(c: dict) -> bool:
        return (c["composite_score"] >= MIN_PLAUSIBLE_SCORE
                and (c["semantic_name_match"]["score"] > 0.0
                     or c["argument_shape_compatibility"]["score"] > 0.0))

    plausible = [c for c in scored if _is_plausible(c)]
    below_floor = [c for c in scored if not _is_plausible(c)]
    plausible.sort(key=lambda c: (
        -c["composite_score"],
        -(c["historical_pass_evidence"].get("total_runs") or 0),
        c["command_name"] or "",
    ))

    if not plausible:
        return {**base, "status": NO_REUSE_CANDIDATE,
                "below_floor_candidates": below_floor, "excluded_branch_mismatch": excluded,
                "reason": (
                    "NO_PLAUSIBLE_MATCH: no branch-compatible existing command cleared the "
                    f"plausibility floor (composite_score >= {MIN_PLAUSIBLE_SCORE} AND real "
                    "name or argument overlap) -- forcing a top pick here would be an unearned "
                    "guess, not a finding")}

    return {**base, "status": REUSE_CANDIDATES_FOUND, "candidates": plausible,
            "below_floor_candidates": below_floor, "excluded_branch_mismatch": excluded,
            "top_candidate": plausible[0]}


# --- rendering / CLI ----------------------------------------------------------


def format_reuse_report(report: dict) -> str:
    lines = [f"EXISTING COMMAND REUSE SCORE: {report.get('status')}"]
    if report.get("status") == NO_REUSE_CANDIDATE:
        lines.append(f"  {report.get('reason')}")
        return "\n".join(lines)
    lines.append(f"  {len(report.get('candidates') or [])} plausible candidate(s), "
                 f"{len(report.get('below_floor_candidates') or [])} below the plausibility floor, "
                 f"{len(report.get('excluded_branch_mismatch') or [])} excluded (branch mismatch)")
    for c in report.get("candidates") or []:
        lines.append("")
        lines.append(f"  [{c['confidence']}] {c['command_name']}  score={c['composite_score']}")
        lines.append(f"      name_match={c['semantic_name_match']['score']} "
                     f"({c['semantic_name_match']['status']})  "
                     f"args={c['argument_shape_compatibility']['score']} "
                     f"({c['argument_shape_compatibility']['status']})  "
                     f"branch={c['branch_ownership_compatibility']['result']}")
        hist = c["historical_pass_evidence"]
        if hist.get("status") == "RECORDED":
            lines.append(f"      history: {hist['pass_count']}/{hist['total_runs']} PASS "
                         f"(pattern={hist['matched_key']})")
        else:
            lines.append(f"      history: {hist.get('status')} ({hist.get('reason', '')})")
    return "\n".join(lines)


def execute_verb(*, need: dict, existing_commands: Sequence[dict], root: Optional[str] = None,
                  db_path: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.existing_command_reuse_score`.
    Returns (text, exit_code): 0 REUSE_CANDIDATES_FOUND, 1 NO_REUSE_CANDIDATE,
    2 a malformed `need`. Runs nothing, writes nothing."""
    import json as _json
    try:
        report = evaluate_reuse(need, existing_commands, root=root, db_path=db_path)
    except NeedValidationError as e:
        return f"NeedValidationError: {e}", 2
    text = _json.dumps(report, indent=2) if as_json else format_reuse_report(report)
    code = 0 if report["status"] == REUSE_CANDIDATES_FOUND else 1
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.existing_command_reuse_score",
        description="Ranks existing DE command.txt commands (a plain JSON list of dicts) "
                    "against a new vPlan-driven need (a plain JSON dict) by semantic-name "
                    "match, argument-shape compatibility, branch-ownership compatibility, and "
                    "real evidence_db.py regression history. Runs nothing.")
    ap.add_argument("--need-file", required=True, help="JSON file: the need dict.")
    ap.add_argument("--commands-file", required=True,
                    help="JSON file: a list of existing-command dicts.")
    ap.add_argument("--root", default=None,
                    help="Project root (for the read-only evidence_db lookup).")
    ap.add_argument("--db", default=None, help="Evidence database path override.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    need = _json.loads(Path(a.need_file).read_text(encoding="utf-8"))
    commands = _json.loads(Path(a.commands_file).read_text(encoding="utf-8"))
    text, code = execute_verb(need=need, existing_commands=commands, root=a.root,
                              db_path=a.db, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
