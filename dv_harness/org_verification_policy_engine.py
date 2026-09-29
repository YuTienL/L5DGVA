"""Organizational Verification Policy Engine (CLAUDE.md sections 135-137, vi_meta_governance/ovpe).

An org-declarable, EXECUTABLE verification-policy rules engine with a documented,
tested precedence order -- distinct from `autonomy_levels.py`, which is a
citation-checked INDEX of what already enforces LEVEL C (production-promotion)
actions in this repo; it holds no state, evaluates no condition, and resolves no
conflict. This module is the opposite kind of thing: it is itself the mechanism
an org/project pair would point at to declare and evaluate general verification
policy rules. (`autonomy_levels.LEVEL_C_ENFORCEMENT["changing organizational
verification policy"]` documents who may write ORGANIZATIONAL MEMORY via
`memory_router.promote_to_organizational()` -- a different, narrower question
than "evaluate this org's declared verification-policy rules against this
project's facts", which is what this module does. Confirmed by direct reading
before building: `memory_router.py` has no condition/precedence/policy-rule
concept at all.)

A policy is DATA, never Python code -- `dv_harness/schemas/
org_verification_policy.schema.json` is the schema this module validates
against and was already present in this repo before this module was built (a
prior pass declared the contract; this module is the executor named in that
schema's own `description` field). A policy states a `condition` (a three-valued
True/False/UNRESOLVABLE boolean expression over project facts) and an
`action_if_matched` (BLOCK/WARN/ALLOW) for a named `governs` topic, with a
`scope` (org/project) and `severity` (MANDATORY/ADVISORY).

Evidence Truth Rule, applied to condition evaluation: a fact this engine cannot
resolve (the fact path is absent from the supplied facts, or the declared
comparison cannot be applied to the value found -- e.g. `lt` against a string)
evaluates to UNRESOLVABLE, never silently coerced to True or False. `exists`/
`not_exists` are the only two operators that can never be UNRESOLVABLE, because
they ask about presence itself rather than a value's shape.

Worst-wins composite gate, per this project's house style: a single BLOCK
outranks everything else for the overall verdict; short of that, an unresolved
policy conflict or an unresolvable MANDATORY/ADVISORY condition on any topic
outranks a clean WARN/ALLOW picture (`ENGINE_UNRESOLVED`, never silently folded
into a clean pass); short of that, a WARN outranks a clean ALLOW-only picture.

Two matched policies sharing one `governs` value with different
`action_if_matched` values are a real conflict, resolved by `ORG_POLICY_
PRECEDENCE_ORDER` or reported unresolved -- never silently averaged, and never
resolved by which policy happened to load last. The order, in this exact
sequence, per the schema's own field descriptions:

  1. scope_with_override -- `scope: "org"` outranks `scope: "project"`, UNLESS
     the org policy declares `overridable_by_project: true`, in which case it
     explicitly yields to a matching project-scope policy on the same
     `governs` topic (ranked BELOW every project policy on that topic, not
     above it -- the schema's own words).
  2. severity -- `MANDATORY` outranks `ADVISORY`, once scope is tied.
  3. precedence -- an explicit numeric precedence, higher wins, once scope and
     severity are tied. Undeclared is 0, never treated as an unfair advantage
     or disadvantage nobody chose (the schema's own words, restated as code).
  4. still tied -- reported `UNRESOLVED_CONFLICT`, naming every tied policy.
     Never resolved by insertion order, alphabetical policy_id, or any other
     unstated rule.

Deliberately bounded, and stated rather than implied closed. (1) It reads no
project file itself and derives no fact of its own -- `facts` is a plain
caller-supplied mapping, exactly the same "accept the real fact set as a
generic parameter" discipline several sibling modules in this project already
apply to their own domains. Wiring a project's real evidence (env.manifest.json
layers, a waiver ledger, a golden-scenario freshness verdict, ...) into that
mapping is a caller's job. (2) It decides, approves and arbitrates nothing
beyond its own three-valued evaluation and worst-wins fold: no build, job,
approval, or stage gate is touched, and there is deliberately no `STAGE_GATES`
entry and no `dv-harness` CLI verb -- `cli.py`/`gates.py` were left untouched
per this task's own house-style rule 8 (several other same-session modules made
the identical disclosed choice); the front door is `python -m
dv_harness.org_verification_policy_engine`. (3) An `UNRESOLVED_CONFLICT` or an
`UNRESOLVABLE_EVIDENCE` topic never silently becomes ALLOW -- it is reported
under `ENGINE_UNRESOLVED` (a human decision is owed), never conflated with a
genuinely clean `ENGINE_CLEAR`. (4) A schema-invalid policy document, a leaf
condition missing a required `value` for an op that needs one, a duplicate
`policy_id`, or an unresolvable operator all raise a named error at load/build
time rather than silently degrading a malformed document into a policy that
never fires.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).parent / "schemas" / "org_verification_policy.schema.json"

# The one honest "we could not resolve this" sentinel a condition evaluation
# may return, alongside the ordinary Python bools True/False.
UNRESOLVABLE = "UNRESOLVABLE"

SCOPE_VALUES = ("org", "project")
SEVERITY_VALUES = ("MANDATORY", "ADVISORY")
ACTION_VALUES = ("BLOCK", "WARN", "ALLOW")
CONDITION_OPS = (
    "eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "contains",
    "exists", "not_exists",
)
_OPS_NOT_NEEDING_VALUE = ("exists", "not_exists")

# The documented, tested precedence order -- see the module docstring for the
# meaning of each step. Never re-ordered without updating both the docstring
# and `_compare_policies()` together.
ORG_POLICY_PRECEDENCE_ORDER = (
    "scope_with_override",
    "severity",
    "precedence",
)

# Per-topic finding statuses (distinct from ACTION_VALUES: a topic's *finding*
# about how it was decided, not the action a matched policy declares).
TOPIC_RESOLVED = "RESOLVED"
TOPIC_UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
TOPIC_UNRESOLVABLE_EVIDENCE = "UNRESOLVABLE_EVIDENCE"

# Overall engine verdict, worst-wins over every governed topic.
ENGINE_CLEAR = "ENGINE_CLEAR"
ENGINE_WARNING = "ENGINE_WARNING"
ENGINE_UNRESOLVED = "ENGINE_UNRESOLVED"
ENGINE_BLOCKED = "ENGINE_BLOCKED"
ENGINE_VERDICTS = (ENGINE_CLEAR, ENGINE_WARNING, ENGINE_UNRESOLVED, ENGINE_BLOCKED)


class OrgVerificationPolicyError(Exception):
    """Base error for this module."""


class PolicyDocumentValidationError(OrgVerificationPolicyError):
    """A policy document failed schema validation, or a structural rule this
    module enforces beyond the schema's own reach (leaf-condition value
    presence, unique policy_id)."""


class PolicyConditionError(OrgVerificationPolicyError):
    """A condition tree names an operator/shape this module does not
    recognise -- a caller-usage/document-authoring error, raised loudly rather
    than silently evaluated as UNRESOLVABLE, which would hide a typo in the
    policy document behind a normal-looking honest-absence status."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's action/engine-verdict vocabularies must share no token
    with `dv_harness.models.Status`, the same discipline several sibling
    modules already apply to their own domain vocabularies -- a policy action
    or an engine verdict must never be confusable with a DV stage-gate
    verification verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocab = set(ACTION_VALUES) | set(ENGINE_VERDICTS) | {UNRESOLVABLE}
    collision = verdicts.intersection(vocab)
    if collision:
        raise OrgVerificationPolicyError(
            f"org_verification_policy_engine vocabulary collides with "
            f"dv_harness.models.Status on {sorted(collision)} -- a policy "
            "action or engine verdict must never be confusable with a "
            "verification stage-gate verdict"
        )


# ---------------------------------------------------------------------------
# Schema loading / validation
# ---------------------------------------------------------------------------

def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_against_schema(document: dict) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise PolicyDocumentValidationError(
            "jsonschema package is not installed; cannot validate the policy "
            "document. Install it rather than skipping validation."
        ) from exc
    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        lines = [
            f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        ]
        raise PolicyDocumentValidationError(
            "org_verification_policy.schema.json validation failed:\n" + "\n".join(lines)
        )


def _check_condition_structure(condition: Any, *, policy_id: str) -> None:
    """Structural rules the JSON Schema cannot express: a leaf condition whose
    op needs a `value` must supply one. Raised loudly rather than silently
    evaluated as UNRESOLVABLE at run time, so a document typo is caught once,
    at load time, rather than on every future evaluation."""
    if not isinstance(condition, dict):
        raise PolicyDocumentValidationError(
            f"policy {policy_id!r}: condition node must be an object, got {type(condition).__name__}"
        )
    if "all_of" in condition:
        for sub in condition["all_of"]:
            _check_condition_structure(sub, policy_id=policy_id)
        return
    if "any_of" in condition:
        for sub in condition["any_of"]:
            _check_condition_structure(sub, policy_id=policy_id)
        return
    if "not" in condition:
        _check_condition_structure(condition["not"], policy_id=policy_id)
        return
    # leaf
    op = condition.get("op")
    if op not in CONDITION_OPS:
        raise PolicyDocumentValidationError(
            f"policy {policy_id!r}: unrecognized condition op {op!r}"
        )
    if op not in _OPS_NOT_NEEDING_VALUE and "value" not in condition:
        raise PolicyDocumentValidationError(
            f"policy {policy_id!r}: leaf condition op {op!r} on fact "
            f"{condition.get('fact')!r} requires a 'value', none supplied"
        )


def validate_policy_document(document: dict) -> None:
    """Validate `document` against org_verification_policy.schema.json PLUS
    this module's own structural rules (leaf-condition value presence, unique
    policy_id). Raises PolicyDocumentValidationError on any violation."""
    _validate_against_schema(document)
    seen_ids: Dict[str, int] = {}
    for idx, raw_policy in enumerate(document.get("policies", [])):
        policy_id = raw_policy.get("policy_id", f"<index {idx}>")
        if policy_id in seen_ids:
            raise PolicyDocumentValidationError(
                f"duplicate policy_id {policy_id!r} at indices "
                f"{seen_ids[policy_id]} and {idx} -- policy_id must be unique "
                "within a policy document"
            )
        seen_ids[policy_id] = idx
        _check_condition_structure(raw_policy.get("condition"), policy_id=policy_id)


def load_policy_document(path: Union[str, Path]) -> dict:
    """Read, schema-validate and structurally validate a policy document from
    disk. Raises PolicyDocumentValidationError on any violation."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_policy_document(document)
    return document


# ---------------------------------------------------------------------------
# Policy record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Policy:
    policy_id: str
    scope: str
    severity: str
    governs: str
    condition: dict
    action_if_matched: str
    reason: str
    title: Optional[str] = None
    precedence: int = 0
    overridable_by_project: bool = False
    citation: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Policy":
        if raw.get("scope") not in SCOPE_VALUES:
            raise PolicyDocumentValidationError(
                f"policy {raw.get('policy_id')!r}: scope must be one of {SCOPE_VALUES}, "
                f"got {raw.get('scope')!r}"
            )
        if raw.get("severity") not in SEVERITY_VALUES:
            raise PolicyDocumentValidationError(
                f"policy {raw.get('policy_id')!r}: severity must be one of "
                f"{SEVERITY_VALUES}, got {raw.get('severity')!r}"
            )
        if raw.get("action_if_matched") not in ACTION_VALUES:
            raise PolicyDocumentValidationError(
                f"policy {raw.get('policy_id')!r}: action_if_matched must be one of "
                f"{ACTION_VALUES}, got {raw.get('action_if_matched')!r}"
            )
        return cls(
            policy_id=raw["policy_id"],
            scope=raw["scope"],
            severity=raw["severity"],
            governs=raw["governs"],
            condition=raw["condition"],
            action_if_matched=raw["action_if_matched"],
            reason=raw["reason"],
            title=raw.get("title"),
            precedence=int(raw.get("precedence", 0) or 0),
            overridable_by_project=bool(raw.get("overridable_by_project", False)),
            citation=raw.get("citation"),
        )


def load_policies(document: dict) -> List[Policy]:
    """Build `Policy` records from an already-validated policy document."""
    return [Policy.from_dict(p) for p in document.get("policies", [])]


# ---------------------------------------------------------------------------
# Three-valued condition evaluation
# ---------------------------------------------------------------------------

def _lookup_fact(facts: Any, dotted_path: str) -> Tuple[bool, Any]:
    """Resolve a dotted fact path against `facts`. Returns (found, value).
    `found is False` whenever any segment of the path is missing -- the ONLY
    way a leaf condition's fact is honestly absent."""
    current = facts
    for segment in dotted_path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False, None
    return True, current


def evaluate_condition(condition: dict, facts: dict) -> Union[bool, str]:
    """Evaluate one condition node against `facts`, three-valued:
    True / False / UNRESOLVABLE (the module-level `UNRESOLVABLE` sentinel).

    all_of: True iff every sub-condition is True; False iff any sub-condition
    is False (checked before UNRESOLVABLE, since a real False is decisive
    regardless of what else could not be resolved); else UNRESOLVABLE.
    any_of: the mirror -- True iff any sub is True; False iff every sub is
    False; else UNRESOLVABLE.
    not: inverts True/False; UNRESOLVABLE stays UNRESOLVABLE.
    leaf: `exists`/`not_exists` are always decidable (they ask about presence
    itself). Every other op is UNRESOLVABLE when the fact is absent, or when
    the declared comparison cannot be applied to the value found (a TypeError
    from comparing incompatible types, e.g. `lt` against a string) -- never a
    silently coerced/guessed result.
    """
    if "all_of" in condition:
        results = [evaluate_condition(sub, facts) for sub in condition["all_of"]]
        if any(r is False for r in results):
            return False
        if any(r == UNRESOLVABLE for r in results):
            return UNRESOLVABLE
        return True

    if "any_of" in condition:
        results = [evaluate_condition(sub, facts) for sub in condition["any_of"]]
        if any(r is True for r in results):
            return True
        if any(r == UNRESOLVABLE for r in results):
            return UNRESOLVABLE
        return False

    if "not" in condition:
        inner = evaluate_condition(condition["not"], facts)
        if inner == UNRESOLVABLE:
            return UNRESOLVABLE
        return not inner

    # leaf condition
    op = condition.get("op")
    if op not in CONDITION_OPS:
        raise PolicyConditionError(f"unrecognized condition op {op!r}")

    found, value = _lookup_fact(facts, condition["fact"])

    if op == "exists":
        return found
    if op == "not_exists":
        return not found

    if not found:
        return UNRESOLVABLE

    if "value" not in condition:
        # Should already have been rejected by validate_policy_document(); a
        # caller building a condition tree by hand without validating first
        # gets an honest UNRESOLVABLE rather than a KeyError.
        return UNRESOLVABLE

    target = condition["value"]
    try:
        if op == "eq":
            return value == target
        if op == "ne":
            return value != target
        if op == "lt":
            return value < target
        if op == "lte":
            return value <= target
        if op == "gt":
            return value > target
        if op == "gte":
            return value >= target
        if op == "in":
            return value in target
        if op == "not_in":
            return value not in target
        if op == "contains":
            return target in value
    except TypeError:
        return UNRESOLVABLE

    raise PolicyConditionError(f"unrecognized condition op {op!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Precedence resolution
# ---------------------------------------------------------------------------

def _compare_policies(a: Policy, b: Policy) -> int:
    """Return -1 if `a` outranks `b`, 1 if `b` outranks `a`, 0 if tied after
    every step of ORG_POLICY_PRECEDENCE_ORDER (an unresolved conflict)."""
    # 1. scope_with_override
    if a.scope != b.scope:
        if a.scope == "org":
            # a is org, b is project.
            return -1 if not a.overridable_by_project else 1
        else:
            # a is project, b is org.
            return -1 if b.overridable_by_project else 1

    # 2. severity
    if a.severity != b.severity:
        return -1 if a.severity == "MANDATORY" else 1

    # 3. precedence (undeclared already normalized to 0 by Policy.from_dict)
    if a.precedence != b.precedence:
        return -1 if a.precedence > b.precedence else 1

    # 4. still tied
    return 0


@dataclass
class ConflictResolution:
    resolved: bool
    winner: Optional[Policy]
    tied: List[Policy] = field(default_factory=list)


def resolve_conflict(matched_policies: List[Policy]) -> ConflictResolution:
    """Resolve a real action conflict among `matched_policies` (>= 2 matched
    policies for one `governs` topic declaring >= 2 distinct actions) via
    ORG_POLICY_PRECEDENCE_ORDER. Returns the winner when one policy strictly
    outranks every other; reports every tied policy, unresolved, otherwise --
    never picked by insertion order or any other unstated rule."""
    ordered = sorted(matched_policies, key=cmp_to_key(_compare_policies))
    best = ordered[0]
    tied_with_best = [p for p in ordered if _compare_policies(best, p) == 0]
    if len(tied_with_best) == 1:
        return ConflictResolution(resolved=True, winner=best)
    # More than one policy is tied with the best. If they happen to agree on
    # the action anyway, there is no real conflict left to resolve.
    if len({p.action_if_matched for p in tied_with_best}) == 1:
        return ConflictResolution(resolved=True, winner=best)
    return ConflictResolution(resolved=False, winner=None, tied=tied_with_best)


# ---------------------------------------------------------------------------
# Engine: evaluate a whole policy set against a fact set
# ---------------------------------------------------------------------------

@dataclass
class TopicResult:
    governs: str
    status: str  # TOPIC_RESOLVED / TOPIC_UNRESOLVED_CONFLICT / TOPIC_UNRESOLVABLE_EVIDENCE
    action: Optional[str] = None
    winner_policy_id: Optional[str] = None
    matched_policy_ids: List[str] = field(default_factory=list)
    unresolvable_policy_ids: List[str] = field(default_factory=list)
    tied_policy_ids: List[str] = field(default_factory=list)
    conflict: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "governs": self.governs,
            "status": self.status,
            "action": self.action,
            "winner_policy_id": self.winner_policy_id,
            "matched_policy_ids": self.matched_policy_ids,
            "unresolvable_policy_ids": self.unresolvable_policy_ids,
            "tied_policy_ids": self.tied_policy_ids,
            "conflict": self.conflict,
            "reason": self.reason,
        }


@dataclass
class EngineResult:
    overall_status: str
    per_policy: List[dict]
    topics: List[TopicResult]

    def to_dict(self) -> dict:
        return {
            "overall_status": self.overall_status,
            "per_policy": self.per_policy,
            "topics": [t.to_dict() for t in self.topics],
        }


def evaluate_policies(
    policies: List[Union[Policy, dict]], facts: dict
) -> EngineResult:
    """Evaluate every policy's condition against `facts`, group matched/
    unresolvable policies by their `governs` topic, resolve any real action
    conflict per topic via ORG_POLICY_PRECEDENCE_ORDER, and fold every topic's
    outcome into one worst-wins overall verdict (see module docstring)."""
    parsed: List[Policy] = [
        p if isinstance(p, Policy) else Policy.from_dict(p) for p in policies
    ]

    per_policy: List[dict] = []
    matched_by_topic: Dict[str, List[Policy]] = {}
    unresolvable_by_topic: Dict[str, List[Policy]] = {}

    for p in parsed:
        result = evaluate_condition(p.condition, facts)
        per_policy.append(
            {
                "policy_id": p.policy_id,
                "governs": p.governs,
                "condition_result": result if result != UNRESOLVABLE else UNRESOLVABLE,
                "matched": result is True,
            }
        )
        if result is True:
            matched_by_topic.setdefault(p.governs, []).append(p)
        elif result == UNRESOLVABLE:
            unresolvable_by_topic.setdefault(p.governs, []).append(p)

    every_governs = set(matched_by_topic) | set(unresolvable_by_topic)
    topic_results: List[TopicResult] = []

    for governs in sorted(every_governs):
        matched = matched_by_topic.get(governs, [])
        unresolvable = unresolvable_by_topic.get(governs, [])

        if matched:
            distinct_actions = {p.action_if_matched for p in matched}
            if len(distinct_actions) == 1:
                topic_results.append(
                    TopicResult(
                        governs=governs,
                        status=TOPIC_RESOLVED,
                        action=matched[0].action_if_matched,
                        matched_policy_ids=[p.policy_id for p in matched],
                        conflict=len(matched) > 1,
                        reason=(
                            "every matched policy on this topic agrees on the "
                            "same action"
                            if len(matched) > 1
                            else matched[0].reason
                        ),
                    )
                )
                continue
            resolution = resolve_conflict(matched)
            if resolution.resolved:
                topic_results.append(
                    TopicResult(
                        governs=governs,
                        status=TOPIC_RESOLVED,
                        action=resolution.winner.action_if_matched,
                        winner_policy_id=resolution.winner.policy_id,
                        matched_policy_ids=[p.policy_id for p in matched],
                        conflict=True,
                        reason=(
                            f"resolved by ORG_POLICY_PRECEDENCE_ORDER: "
                            f"{resolution.winner.policy_id!r} outranks the other "
                            f"matched, differently-acting polic{'y' if len(matched) == 2 else 'ies'} "
                            f"on this topic"
                        ),
                    )
                )
            else:
                topic_results.append(
                    TopicResult(
                        governs=governs,
                        status=TOPIC_UNRESOLVED_CONFLICT,
                        matched_policy_ids=[p.policy_id for p in matched],
                        tied_policy_ids=[p.policy_id for p in resolution.tied],
                        conflict=True,
                        reason=(
                            "matched policies declare different actions and remain "
                            "tied through every step of ORG_POLICY_PRECEDENCE_ORDER "
                            f"-- tied policy_ids: {[p.policy_id for p in resolution.tied]!r}"
                        ),
                    )
                )
        elif unresolvable:
            topic_results.append(
                TopicResult(
                    governs=governs,
                    status=TOPIC_UNRESOLVABLE_EVIDENCE,
                    unresolvable_policy_ids=[p.policy_id for p in unresolvable],
                    reason=(
                        "no policy on this topic matched, and at least one policy's "
                        "condition could not be resolved from the supplied facts -- "
                        f"unresolvable policy_ids: {[p.policy_id for p in unresolvable]!r}"
                    ),
                )
            )
        # else: neither matched nor unresolvable is unreachable (a governs
        # value only enters `every_governs` because it appears in one of the
        # two dicts), kept only for readability.

    if any(t.status == TOPIC_RESOLVED and t.action == "BLOCK" for t in topic_results):
        overall = ENGINE_BLOCKED
    elif any(
        t.status in (TOPIC_UNRESOLVED_CONFLICT, TOPIC_UNRESOLVABLE_EVIDENCE)
        for t in topic_results
    ):
        overall = ENGINE_UNRESOLVED
    elif any(t.status == TOPIC_RESOLVED and t.action == "WARN" for t in topic_results):
        overall = ENGINE_WARNING
    else:
        overall = ENGINE_CLEAR

    return EngineResult(overall_status=overall, per_policy=per_policy, topics=topic_results)


def evaluate_policy_document(document: dict, facts: dict) -> EngineResult:
    """Validate `document`, build its policies, and evaluate them against
    `facts` in one call."""
    validate_policy_document(document)
    return evaluate_policies(load_policies(document), facts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_engine_report(result: EngineResult) -> str:
    from .connectivity import render_markdown_table

    lines = [f"Overall status: {result.overall_status}", ""]
    columns = [
        ("governs", "Topic"),
        ("status", "Status"),
        ("action", "Action"),
        ("winner_policy_id", "Winner"),
        ("conflict", "Conflict"),
        ("reason", "Reason"),
    ]
    rows = [
        {
            "governs": t.governs,
            "status": t.status,
            "action": t.action or "",
            "winner_policy_id": t.winner_policy_id or "",
            "conflict": "yes" if t.conflict else "no",
            "reason": t.reason,
        }
        for t in result.topics
    ]
    lines.append(render_markdown_table(columns, rows))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI / python -m front door
# ---------------------------------------------------------------------------

_EXIT_BY_VERDICT = {
    ENGINE_CLEAR: 0,
    ENGINE_WARNING: 3,
    ENGINE_UNRESOLVED: 2,
    ENGINE_BLOCKED: 1,
}


def execute_verb(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="org_verification_policy_engine")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_validate = sub.add_parser("validate", help="validate a policy document")
    p_validate.add_argument("--policies", required=True)

    p_eval = sub.add_parser("evaluate", help="evaluate a policy document against facts")
    p_eval.add_argument("--policies", required=True)
    p_eval.add_argument("--facts", required=True)
    p_eval.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "validate":
        try:
            load_policy_document(args.policies)
        except OrgVerificationPolicyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("policy document is valid")
        return 0

    if args.verb == "evaluate":
        try:
            document = load_policy_document(args.policies)
            facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
            result = evaluate_policies(load_policies(document), facts)
        except OrgVerificationPolicyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        else:
            print(render_engine_report(result))
        return _EXIT_BY_VERDICT[result.overall_status]

    return 2  # pragma: no cover - argparse enforces a valid verb


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin wrapper
    return execute_verb(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
