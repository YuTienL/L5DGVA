r"""dv_harness/schema_compat.py -- JSON Schema compatibility classifier
(2026-09-06, PC-1).

GAP THIS CLOSES (re-verified this session): this repo owns 24 JSON Schemas
under `dv_harness/schemas/` and eight of the modules that write them declare a
module-level `SCHEMA_VERSION`, but NOTHING anywhere could answer "is this
schema edit safe for documents that already exist on disk?".
`grep -rn "schema_compat\|BACKWARD_COMPATIBLE"` matched no module and no
schema; the only `backward_compatibility` in the tree is
`system_command_plan.assess_backward_compatibility()`, which is about whether
an existing `command.txt` still runs -- a different artifact, a different
question, deliberately left alone here.

The real prior art this follows the SHAPE of (and does not duplicate) is
`env_manifest.py`'s schema 1.0 -> 1.1 bump. That bump added REQUIRED keys, and
CLAUDE.md records the consequence as a deliberate decision: "Schema 1.1 is a
breaking bump and deliberately so ... a stale 1.0 manifest fails
load_env_manifest() loudly". That judgment was made by a human reading a diff.
This module makes the same judgment mechanically, and makes it checkable in CI.

COMPATIBILITY DIRECTION, stated once. A new schema version is
BACKWARD_COMPATIBLE iff every document that validates against the OLD schema
still validates against the NEW one -- "the artifacts already on disk still
load". That is exactly the direction the env_manifest precedent cares about,
and it is a falsifiable statement rather than a vibe: a single document that
passes old and fails new refutes it.

WHY THIS IS NOT A DIFF HEURISTIC. A textual/structural diff can say "the
`required` array grew"; it cannot say what that means, and it silently says
nothing at all about the keyword it has never heard of. Two mechanisms keep
this module honest about that:

  1. EVERY KEYWORD IS EITHER MODELLED OR REPORTED. `_KEYWORD_RULES` names the
     assertion keywords whose narrowing/widening semantics are actually
     implemented here. Any other keyword in schema position whose value
     changed produces an `UNMODELED_KEYWORD_CHANGED` finding with verdict
     UNKNOWN. `pattern` and `format` are modelled as UNKNOWN-on-change ON
     PURPOSE: deciding whether one regex's language contains another's is not
     something this module does, and pretending otherwise is precisely the
     failure mode the gap describes. UNKNOWN is a real third verdict with its
     own exit code -- it never collapses into "compatible".

  2. A BREAKING VERDICT CARRIES A WITNESS THAT REAL `jsonschema` VALIDATED.
     For each candidate-breaking finding this module builds a document, then
     runs `jsonschema.Draft202012Validator` for real against BOTH schemas and
     keeps it only if it genuinely passes old and genuinely fails new
     (`witness_status: PROVEN`). The static rule proposes; the real validator
     disposes. Documents are built the same way: `_synthesize()` drafts from
     the schema's own keywords, `_sample_matching()` produces strings from the
     AST Python's own `re` parser returns, and `_repair()` then fixes whatever
     is left against the REAL validator's errors -- which is how constraints
     that apply only conditionally (`question.schema.json` pins `owner` per
     `domain` through an `allOf` of `if`/`then`) get satisfied without this
     module growing a constraint solver. When that still cannot reach the
     change site the finding is KEPT and marked `NOT_CONSTRUCTED` --
     fail-closed, the same "expand, never quietly shrink" direction
     `change_impact.py` takes.

  And the check runs in the other direction too. Every classification also
  validates real documents -- a synthesized minimal instance of the old schema,
  plus any caller-supplied corpus file -- against both schemas, and one that
  passes old and fails new overrides the static conclusion:
    * after a BACKWARD_COMPATIBLE static verdict it is
      `STATIC_RULES_INCOMPLETE`, a bug report against this module's own rule
      table, which forces BREAKING rather than defending the rules;
    * after an UNKNOWN one it is `UNDECIDED_CHANGE_PROVEN_BREAKING` -- the
      rules did not fail, they honestly declined, and a document settled it.

  A KNOWN HOLE, stated rather than implied closed. Dropping `patternProperties`
  reads as "one fewer assertion" to the static rules, but under
  `additionalProperties: false` those pattern keys were the only thing making
  the matching members legal, so removing it REJECTS documents. Closing that
  properly means reasoning about a regex's key-space against
  `additionalProperties` -- the same regex containment this module refuses to
  fake -- so it stays open, and `test_a_corpus_document_that_breaks_refutes_a_
  compatible_static_verdict` pins it as the live demonstration that the
  empirical layer catches what the rules miss. No repo schema uses
  `patternProperties` today.

WHAT IT DOES NOT DO. It does not migrate documents, does not edit schemas, and
does not decide whether a breaking change is ALLOWED -- env_manifest's bump was
breaking and correct. It reports, and `classify_repo_schema_changes()` adds the
one rule the precedent supports: a BREAKING edit to a schema whose owning
module declares a `SCHEMA_VERSION` must come with a bump of that constant
(`BREAKING_WITHOUT_VERSION_BUMP`), because a breaking schema whose version
still reads 1.0 leaves every reader with no way to tell the two contracts
apart.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

VERDICT_COMPATIBLE = "BACKWARD_COMPATIBLE"
VERDICT_BREAKING = "BREAKING"
VERDICT_UNKNOWN = "UNKNOWN"

#: Worst-first. `_worst()` folds a set of per-finding verdicts with this order.
VERDICT_ORDER = (VERDICT_BREAKING, VERDICT_UNKNOWN, VERDICT_COMPATIBLE)

SCHEMAS_DIR = "dv_harness/schemas"

#: The probe key used to test whether a closed object rejects extra members.
#: Named after this module so a witness document found in a log is traceable.
PROBE_KEY = "__schema_compat_probe__"


class SchemaCompatError(ValueError):
    """A schema could not be read, parsed, or validated well enough to compare.

    Raised rather than returning an UNKNOWN verdict, for the same fail-closed
    reason `env_manifest.EnvManifestValidationError` exists: "I could not read
    the schema" and "I read both schemas and cannot decide" are different
    facts, and a caller that cannot tell them apart will treat a typo'd path as
    an interesting analysis result.
    """


# --------------------------------------------------------------------------
# keyword semantics
# --------------------------------------------------------------------------

#: Keywords that carry no assertion: changing them can never invalidate a
#: document. Everything here is an annotation or an identifier.
_ANNOTATION_KEYWORDS = frozenset({
    "$schema", "$id", "$anchor", "$dynamicAnchor", "$comment", "$vocabulary",
    "title", "description", "default", "examples", "deprecated",
    "readOnly", "writeOnly",
})

#: Reached through `$ref`, never compared positionally: comparing `$defs`
#: entry-by-entry would double-report every change and would also report
#: changes to definitions nothing references any more.
_CONTAINER_KEYWORDS = frozenset({"$defs", "definitions"})

#: Lower bounds. Absent means the stated default, so "added minItems: 1" and
#: "raised minItems 0 -> 1" are the same narrowing and are reported alike.
_MIN_KEYWORDS = {
    "minLength": 0, "minItems": 0, "minProperties": 0, "minContains": 1,
    "minimum": -math.inf, "exclusiveMinimum": -math.inf,
}
#: Upper bounds. Absent means unbounded.
_MAX_KEYWORDS = {
    "maxLength": math.inf, "maxItems": math.inf, "maxProperties": math.inf,
    "maxContains": math.inf, "maximum": math.inf, "exclusiveMaximum": math.inf,
}

#: Applicators whose narrowing/widening this module does NOT decide. A change
#: to any of them is UNKNOWN unless the two values are deep-equal. `oneOf` is
#: here rather than with `anyOf` because WIDENING a `oneOf` branch can itself
#: break a document -- it may start matching two branches and fail the "exactly
#: one" rule -- so the usual "wider is safer" reasoning does not hold for it.
_OPAQUE_APPLICATORS = frozenset({
    "not", "if", "then", "else", "oneOf", "propertyNames", "contains",
    "patternProperties", "prefixItems", "dependentSchemas",
    "unevaluatedItems", "unevaluatedProperties", "$dynamicRef",
})

#: Regex/format-language keywords. Deciding containment between two regexes is
#: not implemented here and is not guessed at either.
_UNDECIDED_ON_CHANGE = frozenset({"pattern", "format", "contentEncoding",
                                  "contentMediaType", "multipleOf"})

#: The full set of keywords with an implemented rule. Anything in schema
#: position outside this set becomes UNMODELED_KEYWORD_CHANGED.
_KEYWORD_RULES = (
    _ANNOTATION_KEYWORDS | _CONTAINER_KEYWORDS | _OPAQUE_APPLICATORS
    | _UNDECIDED_ON_CHANGE | frozenset(_MIN_KEYWORDS) | frozenset(_MAX_KEYWORDS)
    | frozenset({"$ref", "type", "enum", "const", "required", "properties",
                 "additionalProperties", "items", "allOf", "anyOf",
                 "uniqueItems", "dependentRequired"})
)

_JSON_TYPES = ("null", "boolean", "integer", "number", "string", "array", "object")


def modelled_keywords() -> frozenset:
    """The keywords whose compatibility semantics are actually implemented.

    Exposed so a test can assert the repo's own schemas use nothing outside it
    -- the day a schema starts using `patternProperties` assertively, that test
    is the thing that says so.
    """
    return _KEYWORD_RULES


def _worst(verdicts: Sequence[str]) -> str:
    for v in VERDICT_ORDER:
        if v in verdicts:
            return v
    return VERDICT_COMPATIBLE


def _type_set(schema: Mapping[str, Any]) -> Optional[frozenset]:
    """`type` normalized to a set, or None for "any type accepted"."""
    t = schema.get("type")
    if t is None:
        return None
    return frozenset([t] if isinstance(t, str) else t)


def _type_covered(t: str, new_types: frozenset) -> bool:
    """Is a document of JSON type `t` still accepted by `new_types`?

    `integer` is a subset of `number` in JSON Schema, so widening
    integer -> number keeps every old document valid while narrowing
    number -> integer does not. Nothing else in the type vocabulary nests.
    """
    return t in new_types or (t == "integer" and "number" in new_types)


def _collect_refs(node: Any, out: Optional[set] = None) -> set:
    out = set() if out is None else out
    if isinstance(node, Mapping):
        if isinstance(node.get("$ref"), str):
            out.add(node["$ref"])
        for value in node.values():
            _collect_refs(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, out)
    return out


def _is_permissive(schema: Any) -> bool:
    """True for a subschema that asserts nothing (`true`, `{}`, annotations
    only). Used to tell "a property definition was added" (which constrains a
    previously-free-form member) from "a documented but unconstrained property
    was added" (which does not)."""
    if schema is True:
        return True
    if not isinstance(schema, Mapping):
        return False
    return all(k in _ANNOTATION_KEYWORDS or k in _CONTAINER_KEYWORDS for k in schema)


# --------------------------------------------------------------------------
# $ref resolution -- real resolution via `referencing`, never string matching
# --------------------------------------------------------------------------

class _Resolver:
    """Resolves `$ref` against one schema document using the real
    `referencing` registry that `jsonschema` itself uses, so a ref is followed
    the way the validator would follow it rather than by pattern-matching the
    pointer text."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        try:
            from referencing import Registry, Resource
            from referencing.jsonschema import DRAFT202012
        except ImportError as exc:  # pragma: no cover - real dependency here
            raise SchemaCompatError(
                "the `referencing` package (a jsonschema dependency) is not "
                "installed; cannot resolve $ref. Install it rather than "
                "falling back to comparing $ref strings."
            ) from exc
        self._document = document
        self._base = document.get("$id") or "urn:dv-harness:schema-compat:root"
        resource = Resource.from_contents(document, default_specification=DRAFT202012)
        self._resolver = Registry().with_resource(self._base, resource).resolver(self._base)

    def resolve(self, ref: str) -> Mapping[str, Any]:
        try:
            return self._resolver.lookup(ref).contents
        except Exception as exc:  # referencing raises several unresolvable kinds
            raise SchemaCompatError(f"unresolvable $ref {ref!r}: {exc}") from exc


def _deref(schema: Any, resolver: _Resolver, seen: Optional[set] = None) -> Any:
    """Follow `$ref` (transitively) to the subschema it names.

    A sibling-keyword `$ref` (2020-12 allows `{"$ref": ..., "minLength": 2}`)
    is merged with its siblings rather than replacing them, which is what a
    2020-12 validator does.
    """
    seen = seen or set()
    while isinstance(schema, Mapping) and "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            return schema  # recursive definition; stop rather than loop
        seen.add(ref)
        target = resolver.resolve(ref)
        siblings = {k: v for k, v in schema.items() if k != "$ref"}
        if not siblings:
            schema = target
        else:
            merged = dict(target)
            merged.update(siblings)
            schema = merged
    return schema


# --------------------------------------------------------------------------
# instance synthesis (best effort) -- every product is validated for real
# --------------------------------------------------------------------------

class _Unsynthesizable(Exception):
    pass


#: Candidate values per `format`, so a schema with a required `date-time` field
#: still yields a witness instead of silently losing one. `_format_sample()`
#: picks the first candidate the REAL `jsonschema` FormatChecker accepts, so a
#: candidate that is merely plausible is discarded rather than shipped; a format
#: with no entry stays unsynthesizable rather than being filled with a guess.
_FORMAT_SAMPLES = {
    "date": ("2026-09-06",),
    "date-time": ("2026-09-06T00:00:00Z", "2026-09-06T00:00:00+00:00"),
    "time": ("00:00:00Z", "00:00:00+00:00", "00:00:00"),
    "duration": ("P1D",),
    "email": ("probe@example.com",),
    "idn-email": ("probe@example.com",),
    "hostname": ("example.com",),
    "idn-hostname": ("example.com",),
    "ipv4": ("192.0.2.1",),
    "ipv6": ("2001:db8::1",),
    "uri": ("https://example.com/probe",),
    "uri-reference": ("probe",),
    "iri": ("https://example.com/probe",),
    "iri-reference": ("probe",),
    "uuid": ("00000000-0000-4000-8000-000000000000",),
    "json-pointer": ("/probe",),
    "relative-json-pointer": ("0/probe",),
    "regex": ("^probe$",),
}


def _conforms(value: str, fmt: str) -> bool:
    """Does the REAL jsonschema FormatChecker accept this value for `fmt`?"""
    import jsonschema
    return jsonschema.FormatChecker().conforms(value, fmt)


def _try(fn, *args):
    """Run a synthesis helper, returning None instead of raising, so a caller
    can rank several candidate sources without nesting try blocks."""
    try:
        return fn(*args)
    except _Unsynthesizable:
        return None


def _format_sample(fmt: str) -> str:
    candidates = _FORMAT_SAMPLES.get(fmt)
    if not candidates:
        raise _Unsynthesizable(f"no sample for format {fmt!r}")
    for candidate in candidates:
        if _conforms(candidate, fmt):
            return candidate
    raise _Unsynthesizable(f"no candidate satisfies format {fmt!r}")


# --- producing a string in a regex's language, via Python's own parser ------

def _re_parser():
    """Python's real regex parser. `re._parser` since 3.11, `sre_parse`
    before -- and nothing hand-rolled either way."""
    try:
        from re import _parser  # type: ignore[attr-defined]
        return _parser
    except ImportError:  # pragma: no cover - Python < 3.11
        import sre_parse
        return sre_parse


def _emit_re(node_seq, depth: int = 0) -> str:
    """Emit ONE string from a parsed regex, walking the AST Python's own
    `re` parser produced.

    This is not a regex implementation and does not claim to be: it handles the
    constructs this repo's schemas actually use (literals, character classes,
    counted and unbounded repeats, alternation, groups, anchors) and refuses
    everything else. Whatever it emits is checked against the real `re` engine
    before it is used, so a wrong walk costs a witness rather than producing a
    false one -- the same proposer/disposer split the whole module runs on.
    """
    if depth > 12:
        raise _Unsynthesizable("regex nests deeper than the emit limit")
    out = []
    for op, av in node_seq:
        name = str(op).lower()
        if name == "literal":
            out.append(chr(av))
        elif name == "in":
            out.append(_emit_re_class(av))
        elif name == "any":
            out.append("x")
        elif name == "at":
            continue  # ^ / $ / \b contribute no characters
        elif name in ("max_repeat", "min_repeat"):
            low, high, sub = av
            count = low if low else min(1, high)
            unit = _emit_re(sub, depth + 1)
            out.append(unit * count)
        elif name == "subpattern":
            out.append(_emit_re(av[-1], depth + 1))
        elif name == "branch":
            out.append(_emit_re(av[1][0], depth + 1))
        elif name == "atomic_group":
            out.append(_emit_re(av, depth + 1))
        else:
            raise _Unsynthesizable(f"regex construct {name!r} is not emitted here")
    return "".join(out)


def _emit_re_class(items) -> str:
    """One character from a parsed `[...]` class."""
    negated = any(str(op).lower() == "negate" for op, _ in items)
    if negated:
        for candidate in "abcdefghijklmnopqrstuvwxyz0123456789":
            if not _class_contains(items, candidate):
                return candidate
        raise _Unsynthesizable("negated character class excludes every candidate")
    for op, av in items:
        name = str(op).lower()
        if name == "literal":
            return chr(av)
        if name == "range":
            return chr(av[0])
        if name == "category":
            category = str(av).lower()
            if "digit" in category and "not" not in category:
                return "0"
            if "word" in category and "not" not in category:
                return "a"
            if "space" in category and "not" not in category:
                return " "
            raise _Unsynthesizable(f"character category {category!r} is not emitted here")
    raise _Unsynthesizable("empty character class")


def _class_contains(items, ch: str) -> bool:
    for op, av in items:
        name = str(op).lower()
        if name == "literal" and chr(av) == ch:
            return True
        if name == "range" and av[0] <= ord(ch) <= av[1]:
            return True
        if name == "category":
            category = str(av).lower()
            if "digit" in category and ch.isdigit():
                return True
            if "word" in category and (ch.isalnum() or ch == "_"):
                return True
            if "space" in category and ch.isspace():
                return True
    return False


def _sample_matching(pattern: str) -> str:
    """A string in `pattern`'s language, verified with the real `re` engine.

    JSON Schema's `pattern` is a SEARCH, not a full match, which is what the
    final check uses -- the same semantics `jsonschema` itself applies.
    """
    try:
        tree = _re_parser().parse(pattern)
    except Exception as exc:  # a pattern Python itself will not parse
        raise _Unsynthesizable(f"cannot parse pattern {pattern!r}: {exc}") from exc
    sample = _emit_re(tree)
    try:
        if re.search(pattern, sample) is None:
            raise _Unsynthesizable(f"emitted {sample!r} does not match {pattern!r}")
    except re.error as exc:  # pragma: no cover - parse already succeeded
        raise _Unsynthesizable(f"bad pattern {pattern!r}: {exc}") from exc
    return sample


def _synthesize(schema: Any, resolver: _Resolver, materialize: Sequence[str],
                depth: int = 0) -> Any:
    """Build a document that is INTENDED to satisfy `schema`.

    Best effort by design: the caller validates the result with real
    `jsonschema` before using it, so a synthesis rule that is subtly wrong
    costs a lost witness, never a false claim. `materialize` is the remaining
    instance-path to the change site; optional properties along it are filled
    in so the witness actually reaches the keyword under test.
    """
    if depth > 24:
        raise _Unsynthesizable("schema nests deeper than the synthesis limit")
    schema = _deref(schema, resolver)
    if schema is True or schema == {}:
        return {}
    if schema is False:
        raise _Unsynthesizable("false schema accepts nothing")
    if not isinstance(schema, Mapping):
        raise _Unsynthesizable(f"not a schema: {type(schema).__name__}")

    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "enum" in schema:
        if not schema["enum"]:
            raise _Unsynthesizable("empty enum")
        return copy.deepcopy(schema["enum"][0])
    if "allOf" in schema and len(schema["allOf"]) == 1 and len(schema) <= 2:
        return _synthesize(schema["allOf"][0], resolver, materialize, depth + 1)

    types = _type_set(schema)
    if types is None:
        types = frozenset({"object"}) if "properties" in schema or "required" in schema \
            else frozenset({"string"})

    if "object" in types:
        return _synthesize_object(schema, resolver, materialize, depth)
    if "array" in types:
        return _synthesize_array(schema, resolver, materialize, depth)
    if materialize:
        raise _Unsynthesizable("change site sits below a scalar")
    if "string" in types:
        pattern, fmt = schema.get("pattern"), schema.get("format")
        if pattern and fmt:
            # Both assert at once (exemptions.schema.json's `valid_until` is
            # `format: date` AND `^\d{4}-\d{2}-\d{2}$`), and satisfying one is
            # not satisfying the other -- the pattern's zero-filled sample is
            # not a real date. Try each source and keep whichever passes BOTH.
            value = None
            for candidate in (_try(_sample_matching, pattern),) + _FORMAT_SAMPLES.get(fmt, ()):
                if candidate is not None and re.search(pattern, candidate) \
                        and _conforms(candidate, fmt):
                    value = candidate
                    break
            if value is None:
                raise _Unsynthesizable(
                    f"no sample satisfies both pattern {pattern!r} and format {fmt!r}")
        elif pattern:
            value = _sample_matching(pattern)
        elif fmt:
            value = _format_sample(fmt)
        else:
            value = ""
        low, high = int(schema.get("minLength", 0)), schema.get("maxLength")
        if len(value) < low:
            if "pattern" in schema or "format" in schema:
                raise _Unsynthesizable("pattern/format sample is shorter than minLength")
            value = "x" * low
        if high is not None and len(value) > high:
            raise _Unsynthesizable("pattern/format sample is longer than maxLength")
        return value
    if "integer" in types or "number" in types:
        low = schema.get("minimum")
        if low is None and "exclusiveMinimum" in schema:
            low = schema["exclusiveMinimum"] + 1
        value = 0 if low is None else low
        high = schema.get("maximum")
        if high is not None and value > high:
            value = high
        return int(value) if "integer" in types else value
    if "boolean" in types:
        return False
    if "null" in types:
        return None
    raise _Unsynthesizable(f"no synthesis rule for type(s) {sorted(types)}")


def _synthesize_object(schema: Mapping[str, Any], resolver: _Resolver,
                       materialize: Sequence[str], depth: int) -> Dict[str, Any]:
    props = schema.get("properties") or {}
    wanted = list(schema.get("required") or [])
    if materialize and materialize[0] not in wanted:
        wanted.append(materialize[0])
    out: Dict[str, Any] = {}
    for key in wanted:
        sub = props.get(key)
        rest: Sequence[str] = materialize[1:] if materialize and key == materialize[0] else ()
        if sub is None:
            if rest:
                raise _Unsynthesizable(f"no definition for materialized key {key!r}")
            ap = schema.get("additionalProperties", True)
            if ap is False:
                raise _Unsynthesizable(f"required key {key!r} the schema also forbids")
            sub = ap if isinstance(ap, Mapping) else {}
        out[key] = _synthesize(sub, resolver, rest, depth + 1)
    return out


def _synthesize_array(schema: Mapping[str, Any], resolver: _Resolver,
                      materialize: Sequence[str], depth: int) -> List[Any]:
    count = max(int(schema.get("minItems", 0)), 1 if materialize else 0)
    if count == 0:
        return []
    item_schema = schema.get("items")
    if item_schema is None:
        if materialize:
            raise _Unsynthesizable("array has no `items` to materialize through")
        item_schema = {}
    rest: Sequence[str] = materialize[1:] if materialize else ()
    first = _synthesize(item_schema, resolver, rest, depth + 1)
    return [first] + [copy.deepcopy(_synthesize(item_schema, resolver, (), depth + 1))
                      for _ in range(count - 1)]


def _get_parent(doc: Any, path: Sequence[str]) -> Tuple[Any, str]:
    """Walk to the container holding `path`'s last token."""
    node = doc
    for token in path[:-1]:
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, Mapping):
            node = node[token]
        else:
            raise KeyError(token)
    return node, path[-1]


def _instance(schema: Mapping[str, Any], resolver: _Resolver,
              materialize: Sequence[str] = ()) -> Any:
    """A document that REALLY validates against `schema`.

    `_synthesize` walks the schema's own keywords, which is enough for most of
    it but cannot see constraints that only apply conditionally --
    `question.schema.json` pins `owner` by an `allOf` of `if`/`then` blocks per
    `domain`, and `research_evidence_card.schema.json` requires
    `supporting_evidence` to be non-empty only for a FACT. Rather than growing
    a constraint solver, the draft is handed to the REAL validator and repaired
    from the errors it reports, which is the only opinion that counts anyway.
    """
    return _repair(_synthesize(schema, resolver, materialize), schema, resolver)


def _repair(doc: Any, schema: Mapping[str, Any], resolver: _Resolver,
            rounds: int = 8) -> Any:
    """Fix a draft against real validator errors until it validates, or give up.

    Bounded and fail-closed: if the loop stops making progress the document is
    NOT returned, because a witness that does not validate against the old
    schema proves nothing at all.
    """
    validator = _validator(schema)
    for _ in range(rounds):
        errors = sorted(validator.iter_errors(doc), key=lambda e: len(list(e.path)))
        if not errors:
            return doc
        repaired = None
        for error in errors:
            repaired = _repair_one(doc, error, resolver)
            if repaired is not None:
                break
        if repaired is None:
            break
        doc = repaired
    if validator.is_valid(doc):
        return doc
    raise _Unsynthesizable(
        "could not build a document this schema accepts; "
        f"first remaining error: {next(iter(validator.iter_errors(doc))).message}")


def _repair_one(doc: Any, error, resolver: _Resolver) -> Optional[Any]:
    """Apply the one repair this validation error asks for, or None if the
    error names a constraint with no repair rule here."""
    path = [str(p) for p in error.path]
    keyword, expected = error.validator, error.validator_value
    try:
        if keyword == "const":
            return _apply(doc, path, "set", copy.deepcopy(expected)) if path else expected
        if keyword == "enum":
            if not expected:
                return None
            value = copy.deepcopy(expected[0])
            return _apply(doc, path, "set", value) if path else value
        if keyword == "required":
            target = _get_at(doc, path)
            props = error.schema.get("properties") or {}
            out = doc
            for key in expected:
                if key in target:
                    continue
                out = _apply(out, path + [key],
                             "set", _synthesize(props.get(key, {}), resolver, ()))
            return out if out is not doc else None
        if keyword == "minItems":
            array = list(_get_at(doc, path))
            item_schema = error.schema.get("items", {})
            while len(array) < expected:
                array.append(_synthesize(item_schema, resolver, ()))
            return _apply(doc, path, "set", array) if path else array
        if keyword == "minLength":
            return _apply(doc, path, "set", "x" * int(expected)) if path else "x" * int(expected)
        if keyword in ("anyOf", "oneOf"):
            for branch in expected:
                value = _try(_synthesize, branch, resolver, ())
                if value is None:
                    continue
                return _apply(doc, path, "set", value) if path else value
            return None
        if keyword == "type":
            types = [expected] if isinstance(expected, str) else list(expected)
            value = _sample_of_type(types[0])
            return _apply(doc, path, "set", value) if path else value
    except (_Unsynthesizable, KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _get_at(doc: Any, path: Sequence[str]) -> Any:
    node = doc
    for token in path:
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def _apply(doc: Any, path: Sequence[str], op: str, value: Any = None) -> Any:
    """Apply one witness mutation. Returns the mutated copy."""
    doc = copy.deepcopy(doc)
    if not path:
        if op == "add_key":
            doc[value] = "probe"
            return doc
        raise KeyError("empty path")
    parent, last = _get_parent(doc, path)
    if isinstance(parent, list):
        idx = int(last)
        if op == "set":
            parent[idx] = value
        else:
            raise KeyError(op)
        return doc
    if op == "set":
        parent[last] = value
    elif op == "delete":
        parent.pop(last, None)
    elif op == "add_key":
        target = parent.get(last)
        if not isinstance(target, dict):
            raise KeyError(last)
        target[value] = "probe"
    else:
        raise KeyError(op)
    return doc


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

def _finding(code: str, verdict: str, schema_path: str,
             instance_path: Sequence[str], detail: str,
             mutations: Sequence[Tuple[str, Any]] = ()) -> Dict[str, Any]:
    return {
        "code": code,
        "verdict": verdict,
        "schema_path": schema_path,
        "instance_path": "/".join(instance_path),
        "detail": detail,
        "_instance_tokens": list(instance_path),
        "_mutations": list(mutations),
    }


#: Values tried at a change site when no targeted witness value is obvious.
#: They exist so a "the new schema constrains a member the old one left free"
#: finding can still be PROVEN rather than shipped as an unbacked claim.
_PROBE_VALUES = ("probe", 0, -1, 1.5, True, None, [], {}, [1, 2, 3], {"k": "v"})


# --------------------------------------------------------------------------
# the comparison itself
# --------------------------------------------------------------------------

class _Comparison:
    def __init__(self, old_root: Mapping[str, Any], new_root: Mapping[str, Any]) -> None:
        self.old_resolver = _Resolver(old_root)
        self.new_resolver = _Resolver(new_root)
        self.findings: List[Dict[str, Any]] = []
        self._seen: set = set()

    def run(self, old: Any, new: Any) -> None:
        self._compare(old, new, "#", [])

    # -- helpers ----------------------------------------------------------
    def _emit(self, *args, **kwargs) -> None:
        self.findings.append(_finding(*args, **kwargs))

    def _same(self, old: Any, new: Any) -> bool:
        """Are these two subschema values interchangeable?

        Plain `==` is not enough, and this is not hypothetical: `init_seq`'s
        `steps.items` is the byte-identical `{"$ref": "#/$defs/step"}` in both
        versions of the schema while `$defs/step` itself is what changed. An
        `==` shortcut there reports a retyped required field as
        BACKWARD_COMPATIBLE. Two nodes count as unchanged only when they are
        equal AND every `$ref` reachable from them resolves to the same
        subschema in BOTH documents -- which is also why an unchanged schema
        full of `$ref`s still compares clean against itself.
        """
        return old == new and self._refs_agree(old, set())

    def _refs_agree(self, node: Any, seen: set) -> bool:
        for ref in sorted(_collect_refs(node)):
            if ref in seen:
                continue
            seen.add(ref)
            try:
                old_target = self.old_resolver.resolve(ref)
                new_target = self.new_resolver.resolve(ref)
            except SchemaCompatError:
                return False  # let the real comparison surface the failure
            if old_target != new_target or not self._refs_agree(old_target, seen):
                return False
        return True

    def _compare(self, old: Any, new: Any, spath: str, ipath: List[str]) -> None:
        key = (id(old), id(new), spath)
        if key in self._seen:
            return
        self._seen.add(key)

        old = _deref(old, self.old_resolver)
        new = _deref(new, self.new_resolver)

        if old is False:
            return  # nothing validated before; nothing can be lost
        if new is False and old is not False:
            self._emit("SUBSCHEMA_CLOSED", VERDICT_BREAKING, spath, ipath,
                       "the subschema now rejects every document")
            return
        if old is True:
            old = {}
        if new is True:
            new = {}
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            self._emit("UNMODELED_KEYWORD_CHANGED", VERDICT_UNKNOWN, spath, ipath,
                       "subschema is not an object; cannot compare")
            return
        if self._same(old, new):
            return

        self._compare_type(old, new, spath, ipath)
        self._compare_enum_const(old, new, spath, ipath)
        self._compare_required(old, new, spath, ipath)
        self._compare_bounds(old, new, spath, ipath)
        self._compare_unique_items(old, new, spath, ipath)
        self._compare_properties(old, new, spath, ipath)
        self._compare_additional_properties(old, new, spath, ipath)
        self._compare_items(old, new, spath, ipath)
        self._compare_all_of(old, new, spath, ipath)
        self._compare_any_of(old, new, spath, ipath)
        self._compare_dependent_required(old, new, spath, ipath)
        self._compare_undecided(old, new, spath, ipath)
        self._compare_opaque(old, new, spath, ipath)
        self._report_unmodelled(old, new, spath, ipath)

    # -- per-keyword rules -------------------------------------------------
    def _compare_type(self, old, new, spath, ipath) -> None:
        old_types, new_types = _type_set(old), _type_set(new)
        if new_types is None:
            return  # any type accepted now: strictly wider
        if old_types is None:
            old_types = frozenset(_JSON_TYPES)
        lost = sorted(t for t in old_types if not _type_covered(t, new_types))
        if lost:
            self._emit("TYPE_NARROWED", VERDICT_BREAKING, spath, ipath,
                       f"type(s) {lost} accepted before are rejected now "
                       f"(now {sorted(new_types)})",
                       mutations=[("set", _sample_of_type(t)) for t in lost])

    def _compare_enum_const(self, old, new, spath, ipath) -> None:
        if "const" in new and old.get("const") != new["const"]:
            if "const" in old:
                self._emit("CONST_CHANGED", VERDICT_BREAKING, spath, ipath,
                           f"const {old['const']!r} -> {new['const']!r}",
                           mutations=[("set", old["const"])])
            else:
                allowed = old.get("enum")
                muts = [("set", v) for v in (allowed or []) if v != new["const"]] or \
                       [("set", v) for v in _PROBE_VALUES if v != new["const"]]
                self._emit("CONST_ADDED", VERDICT_BREAKING, spath, ipath,
                           f"const {new['const']!r} pins a value that was previously free",
                           mutations=muts)
        if "enum" in new:
            if "enum" not in old:
                self._emit("ENUM_ADDED", VERDICT_BREAKING, spath, ipath,
                           f"enum {new['enum']!r} restricts a previously unrestricted value",
                           mutations=[("set", v) for v in _PROBE_VALUES
                                      if v not in new["enum"]])
            else:
                removed = [v for v in old["enum"] if v not in new["enum"]]
                if removed:
                    self._emit("ENUM_VALUE_REMOVED", VERDICT_BREAKING, spath, ipath,
                               f"enum value(s) {removed!r} are no longer accepted",
                               mutations=[("set", v) for v in removed])

    def _compare_required(self, old, new, spath, ipath) -> None:
        added = [k for k in (new.get("required") or []) if k not in (old.get("required") or [])]
        if added:
            self._emit("REQUIRED_KEY_ADDED", VERDICT_BREAKING, spath, ipath,
                       f"key(s) {sorted(added)} are now REQUIRED; documents written "
                       f"against the old schema do not carry them",
                       mutations=[("delete_child", k) for k in sorted(added)])

    def _compare_bounds(self, old, new, spath, ipath) -> None:
        for kw, default in _MIN_KEYWORDS.items():
            o, n = old.get(kw, default), new.get(kw, default)
            if n > o:
                self._emit("BOUND_TIGHTENED", VERDICT_BREAKING, spath, ipath,
                           f"{kw} raised {o} -> {n}",
                           mutations=_bound_mutations(kw, o, n, raised=True))
        for kw, default in _MAX_KEYWORDS.items():
            o, n = old.get(kw, default), new.get(kw, default)
            if n < o:
                self._emit("BOUND_TIGHTENED", VERDICT_BREAKING, spath, ipath,
                           f"{kw} lowered {o} -> {n}",
                           mutations=_bound_mutations(kw, o, n, raised=False))

    def _compare_unique_items(self, old, new, spath, ipath) -> None:
        if new.get("uniqueItems") and not old.get("uniqueItems"):
            self._emit("BOUND_TIGHTENED", VERDICT_BREAKING, spath, ipath,
                       "uniqueItems turned on; arrays with repeats are rejected now",
                       mutations=[("set", ["dup", "dup"]), ("set", [0, 0]),
                                  ("duplicate_first", None)])

    def _compare_properties(self, old, new, spath, ipath) -> None:
        old_props = old.get("properties") or {}
        new_props = new.get("properties") or {}
        for key in sorted(set(old_props) & set(new_props)):
            self._compare(old_props[key], new_props[key],
                          f"{spath}/properties/{key}", ipath + [key])
        for key in sorted(set(new_props) - set(old_props)):
            self._property_added(old, new_props[key], key, spath, ipath)
        for key in sorted(set(old_props) - set(new_props)):
            self._property_removed(old_props[key], new, key, spath, ipath)

    def _property_added(self, old, new_sub, key, spath, ipath) -> None:
        """A property definition the old schema did not have.

        Harmless when the old schema forbade the member outright or when the
        new definition asserts nothing. It is BREAKING when the old schema let
        the member be anything and the new one constrains it -- a real class of
        change a `required`-only diff reader misses entirely.
        """
        if _is_permissive(new_sub):
            return
        old_ap = old.get("additionalProperties", True)
        if old_ap is False:
            return  # old documents could not carry this key at all
        sub_path = f"{spath}/properties/{key}"
        if isinstance(old_ap, Mapping):
            # The member was already constrained, by the old additionalProperties
            # schema. Whether the new definition is narrower is the same question
            # as any other subschema comparison.
            self._compare(old_ap, new_sub, sub_path, ipath + [key])
            return
        self._emit("PROPERTY_CONSTRAINED", VERDICT_BREAKING, sub_path, ipath + [key],
                   f"{key!r} was an unconstrained additional property and is now "
                   f"constrained",
                   mutations=[("set_absent", v) for v in _PROBE_VALUES])

    def _property_removed(self, old_sub, new, key, spath, ipath) -> None:
        new_ap = new.get("additionalProperties", True)
        sub_path = f"{spath}/properties/{key}"
        if new_ap is False:
            self._emit("PROPERTY_REMOVED_AND_CLOSED", VERDICT_BREAKING, sub_path,
                       ipath + [key],
                       f"{key!r} was dropped from a schema that forbids additional "
                       f"properties; documents carrying it are rejected now",
                       mutations=[("materialize", None)])
        elif isinstance(new_ap, Mapping):
            self._compare(old_sub, new_ap, sub_path, ipath + [key])

    def _compare_additional_properties(self, old, new, spath, ipath) -> None:
        o = old.get("additionalProperties", True)
        n = new.get("additionalProperties", True)
        if self._same(o, n):
            return
        sub = f"{spath}/additionalProperties"
        if n is False and o is not False:
            self._emit("ADDITIONAL_PROPERTIES_CLOSED", VERDICT_BREAKING, sub, ipath,
                       "additionalProperties is now false; documents with extra "
                       "members are rejected",
                       mutations=[("add_key", PROBE_KEY)])
        elif o is not False and n is not True:
            self._compare(o, n, sub, ipath + [PROBE_KEY])

    def _compare_items(self, old, new, spath, ipath) -> None:
        o, n = old.get("items"), new.get("items")
        if n is None or self._same(o, n):
            return
        self._compare(o if o is not None else True, n, f"{spath}/items", ipath + ["0"])

    def _compare_all_of(self, old, new, spath, ipath) -> None:
        o, n = old.get("allOf"), new.get("allOf")
        if self._same(o, n):
            return
        o, n = o or [], n or []
        if len(o) == len(n):
            # Conjunction of pairwise-wider members is itself wider, so a
            # positional walk is sound at equal length.
            for i, (a, b) in enumerate(zip(o, n)):
                self._compare(a, b, f"{spath}/allOf/{i}", ipath)
        elif n and all(any(self._same(m, om) for om in o) for m in n):
            return  # members only removed: the conjunction got weaker
        else:
            self._emit("COMPOSITION_CHANGED", VERDICT_UNKNOWN, f"{spath}/allOf", ipath,
                       f"allOf membership changed ({len(o)} -> {len(n)} branches); "
                       f"branch containment is not decided here")

    def _compare_any_of(self, old, new, spath, ipath) -> None:
        o, n = old.get("anyOf"), new.get("anyOf")
        if self._same(o, n):
            return
        o, n = o or [], n or []
        if o and all(any(self._same(om, m) for m in n) for om in o):
            return  # every old branch survives; the union only grew
        self._emit("COMPOSITION_CHANGED", VERDICT_UNKNOWN, f"{spath}/anyOf", ipath,
                   "anyOf branches changed; union containment is not decided here")

    def _compare_dependent_required(self, old, new, spath, ipath) -> None:
        o = old.get("dependentRequired") or {}
        n = new.get("dependentRequired") or {}
        if o == n:
            return
        for key, req in sorted(n.items()):
            added = [r for r in req if r not in (o.get(key) or [])]
            if added:
                self._emit("REQUIRED_KEY_ADDED", VERDICT_BREAKING,
                           f"{spath}/dependentRequired/{key}", ipath,
                           f"{sorted(added)} became required whenever {key!r} is present")

    def _compare_undecided(self, old, new, spath, ipath) -> None:
        for kw in sorted(_UNDECIDED_ON_CHANGE):
            o, n = old.get(kw), new.get(kw)
            if n is None or self._same(o, n):
                continue  # unchanged, or the constraint was dropped entirely
            self._emit("CONSTRAINT_LANGUAGE_CHANGED", VERDICT_UNKNOWN,
                       f"{spath}/{kw}", ipath,
                       f"{kw} changed ({o!r} -> {n!r}); this module does not decide "
                       f"containment between two {kw} values")

    def _compare_opaque(self, old, new, spath, ipath) -> None:
        for kw in sorted(_OPAQUE_APPLICATORS):
            o, n = old.get(kw), new.get(kw)
            if self._same(o, n):
                continue
            if n is None:
                continue  # applicator removed: strictly fewer assertions
            self._emit("COMPOSITION_CHANGED", VERDICT_UNKNOWN, f"{spath}/{kw}", ipath,
                       f"{kw} changed; this module does not decide whether the new "
                       f"applicator accepts everything the old one did")

    def _report_unmodelled(self, old, new, spath, ipath) -> None:
        """The honesty backstop: a keyword with no rule here is never assumed
        harmless just because nothing in the rule table fired on it."""
        for kw in sorted(set(old) | set(new)):
            if kw in _KEYWORD_RULES:
                continue
            if self._same(old.get(kw), new.get(kw)):
                continue
            self._emit("UNMODELED_KEYWORD_CHANGED", VERDICT_UNKNOWN,
                       f"{spath}/{kw}", ipath,
                       f"keyword {kw!r} changed and has no compatibility rule in "
                       f"schema_compat.modelled_keywords()")


def _sample_of_type(t: str) -> Any:
    return {"null": None, "boolean": True, "integer": 1, "number": 1.5,
            "string": "probe", "array": [], "object": {}}[t]


def _bound_mutations(kw: str, old_edge: Any, new_edge: Any,
                     *, raised: bool) -> List[Tuple[str, Any]]:
    """A witness sitting in the band the new bound gave up.

    For a raised lower bound the band's edge is the OLD minimum (still allowed
    then, too small now); for a lowered upper bound it is one past the NEW
    maximum (still allowed then, too big now). Size-flavoured keywords are
    expressed as a `resize` of a synthesized value rather than a literal, so
    the witness keeps whatever shape the old schema required of it -- an array
    of the right ELEMENT type, not a list of strings that never validated.
    """
    edge = old_edge if raised else new_edge
    if edge in (math.inf, -math.inf):
        # No finite edge on the side that moved, so the witness value is one
        # step inside the new bound instead.
        other = new_edge if raised else new_edge
        if other in (math.inf, -math.inf):
            return []
        edge = other - 1 if raised else other + 1
        if kw in ("minLength", "minItems", "minProperties", "minContains",
                  "maxLength", "maxItems", "maxProperties", "maxContains"):
            edge = max(int(edge), 0)
    if kw in ("minLength", "maxLength", "minItems", "maxItems",
              "minProperties", "maxProperties", "minContains", "maxContains"):
        size = int(edge) if raised else int(edge) + 1
        return [("resize", max(size, 0))]
    if kw == "exclusiveMinimum":
        return [("set", new_edge)]
    if kw == "exclusiveMaximum":
        return [("set", new_edge)]
    if kw == "minimum":
        return [("set", edge), ("set", new_edge - 1)]
    if kw == "maximum":
        return [("set", edge), ("set", new_edge + 1)]
    return [("set", edge)]


def _resize(value: Any, size: int) -> Any:
    """Grow/shrink a synthesized value to exactly `size`, keeping its type and
    -- for arrays -- the element shape the old schema produced."""
    if isinstance(value, str):
        return (value * max(size, 1))[:size] if size else ""
    if isinstance(value, list):
        if len(value) >= size:
            return value[:size]
        if not value:
            raise _Unsynthesizable("cannot grow an array with no element to copy")
        out = list(value)
        while len(out) < size:
            out.append(copy.deepcopy(value[0]))
        return out
    if isinstance(value, dict):
        if len(value) >= size:
            return dict(list(value.items())[:size])
        out = dict(value)
        while len(out) < size:
            out[f"{PROBE_KEY}{len(out)}"] = "probe"
        return out
    raise _Unsynthesizable(f"cannot resize a {type(value).__name__}")


# --------------------------------------------------------------------------
# witness proving -- real jsonschema validation of a real document
# --------------------------------------------------------------------------

def _validator(schema: Mapping[str, Any]):
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - real dependency here
        raise SchemaCompatError(
            "jsonschema package is not installed; cannot prove a compatibility "
            "verdict against real validation. Install it rather than shipping "
            "static verdicts as if they had been checked."
        ) from exc
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def _prove(finding: Dict[str, Any], old_schema: Mapping[str, Any],
           new_schema: Mapping[str, Any], old_valid, new_valid) -> None:
    """Turn a static BREAKING claim into a proven one, or mark it unproven.

    A finding is PROVEN only when a document this module actually built passes
    the real old validator and fails the real new one. Nothing here downgrades
    a BREAKING verdict on failure to prove it: the classifier stays
    conservative, and says so in `witness_status`.
    """
    if finding["verdict"] != VERDICT_BREAKING:
        finding["witness_status"] = "NOT_APPLICABLE"
        return
    tokens = finding["_instance_tokens"]
    resolver = _Resolver(old_schema)
    candidates: List[Any] = []
    for op, value in finding["_mutations"] or [("set", v) for v in _PROBE_VALUES]:
        try:
            if op == "delete_child":
                # The added-required key: build a document that legitimately
                # omits it, which is what every pre-existing document does.
                # Only the CONTAINING object is materialized -- a newly-required
                # key usually has no definition in the old schema at all, and
                # under `additionalProperties: false` it could not even be
                # written there.
                base = _instance(old_schema, resolver, tokens)
                candidates.append(_apply(base, tokens + [value], "delete"))
            elif op == "materialize":
                # The change site's mere PRESENCE is the break (a property the
                # new schema dropped from a closed object).
                candidates.append(_instance(old_schema, resolver, tokens))
            elif op == "set_absent":
                # The old schema has no definition for this member -- it rode in
                # on additionalProperties -- so materialize its PARENT and put
                # the value there directly.
                base = _instance(old_schema, resolver, tokens[:-1])
                candidates.append(_apply(base, tokens, "set", value))
            elif op == "add_key":
                base = _instance(old_schema, resolver, tokens)
                candidates.append(_apply(base, tokens, "add_key", value))
            elif op == "resize":
                base = _instance(old_schema, resolver, tokens)
                resized = _resize(_get_at(base, tokens), value)
                candidates.append(_apply(base, tokens, "set", resized) if tokens else resized)
            elif op == "duplicate_first":
                base = _instance(old_schema, resolver, tokens + ["0"])
                arr = _get_parent(base, tokens + ["0"])[0]
                if isinstance(arr, list) and arr:
                    candidates.append(_apply(base, tokens, "set",
                                             [arr[0], copy.deepcopy(arr[0])]))
            else:
                base = _instance(old_schema, resolver, tokens)
                candidates.append(_apply(base, tokens, "set", value) if tokens else value)
        except (_Unsynthesizable, KeyError, IndexError, TypeError, ValueError,
                SchemaCompatError):
            continue
    for doc in candidates:
        if old_valid(doc) and not new_valid(doc):
            finding["witness_status"] = "PROVEN"
            finding["witness"] = doc
            return
    finding["witness_status"] = "NOT_CONSTRUCTED"


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def classify_schema_change(old_schema: Mapping[str, Any],
                           new_schema: Mapping[str, Any],
                           *, corpus: Optional[Sequence[Any]] = None,
                           prove: bool = True) -> Dict[str, Any]:
    """Classify `old_schema` -> `new_schema` as BACKWARD_COMPATIBLE / BREAKING
    / UNKNOWN, where BACKWARD_COMPATIBLE means every document valid under the
    old schema is still valid under the new one.

    `corpus` is real documents (existing artifacts on disk, fixtures) to check
    the verdict against. Any corpus document that passes old and fails new is
    reported as a proven break -- and, if the static pass had concluded
    compatible, as a STATIC_RULES_INCOMPLETE bug against this module.
    """
    if not isinstance(old_schema, Mapping) or not isinstance(new_schema, Mapping):
        raise SchemaCompatError("both schemas must be JSON objects")

    comparison = _Comparison(old_schema, new_schema)
    comparison.run(old_schema, new_schema)
    findings = comparison.findings

    old_v, new_v = _validator(old_schema), _validator(new_schema)
    old_valid, new_valid = old_v.is_valid, new_v.is_valid

    if prove:
        for f in findings:
            _prove(f, old_schema, new_schema, old_valid, new_valid)
    else:
        for f in findings:
            f["witness_status"] = "NOT_CHECKED"

    static_verdict = _worst([f["verdict"] for f in findings])

    # Empirical cross-check. A minimal instance of the old schema is the
    # cheapest real document available; caller corpus documents are the
    # authoritative ones.
    checked: List[Any] = list(corpus or [])
    try:
        checked.append(_instance(old_schema, _Resolver(old_schema)))
    except (_Unsynthesizable, SchemaCompatError):
        pass
    empirical_breaks = 0
    for doc in checked:
        if not (old_valid(doc) and not new_valid(doc)):
            continue
        empirical_breaks += 1
        if static_verdict == VERDICT_BREAKING:
            continue  # already known; the first document is finding enough
        why = "; ".join(e.message for e in sorted(new_v.iter_errors(doc),
                                                  key=lambda e: list(e.path))[:3])
        if static_verdict == VERDICT_UNKNOWN:
            # The static pass honestly declined (a changed `pattern`, an opaque
            # applicator). A real document settles what it could not.
            code, detail = "UNDECIDED_CHANGE_PROVEN_BREAKING", (
                "a change this module does not decide statically is settled by a "
                f"real document: it passes the old schema and fails the new one: {why}")
        else:
            # The static pass affirmatively said COMPATIBLE and was wrong. That
            # is a bug in the rule table, reported as one rather than defended.
            code, detail = "STATIC_RULES_INCOMPLETE", (
                "a real document passes the old schema and fails the new one, but "
                "the static rules classified this change as BACKWARD_COMPATIBLE -- "
                f"the rule table is incomplete for this edit: {why}")
        findings.append(_finding(code, VERDICT_BREAKING, "#", [], detail))
        findings[-1]["witness_status"] = "PROVEN"
        findings[-1]["witness"] = doc
        static_verdict = VERDICT_BREAKING

    for f in findings:
        f.pop("_instance_tokens", None)
        f.pop("_mutations", None)

    return {
        "classifier_schema_version": SCHEMA_VERSION,
        "verdict": static_verdict,
        "findings": findings,
        "counts": {
            "breaking": sum(1 for f in findings if f["verdict"] == VERDICT_BREAKING),
            "unknown": sum(1 for f in findings if f["verdict"] == VERDICT_UNKNOWN),
            "proven": sum(1 for f in findings if f.get("witness_status") == "PROVEN"),
        },
        "documents_checked": len(checked),
        "documents_broken": empirical_breaks,
    }


def _load_schema_file(path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SchemaCompatError(f"cannot read schema {path}: {exc}") from exc


def compare_schema_files(old_path, new_path, *,
                         corpus_paths: Sequence[Any] = ()) -> Dict[str, Any]:
    """Classify two schema files on disk."""
    corpus = []
    for p in corpus_paths:
        try:
            corpus.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise SchemaCompatError(f"cannot read corpus document {p}: {exc}") from exc
    result = classify_schema_change(_load_schema_file(Path(old_path)),
                                    _load_schema_file(Path(new_path)),
                                    corpus=corpus)
    result["old"] = str(old_path)
    result["new"] = str(new_path)
    return result


# --------------------------------------------------------------------------
# repo mode: what did this branch do to the project's own schemas?
# --------------------------------------------------------------------------

_SCHEMA_VERSION_RE = re.compile(r'^SCHEMA_VERSION\s*=\s*["\']([^"\']+)["\']', re.M)


def _git(root: Path, args: Sequence[str], timeout: int = 30) -> Tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(root)] + list(args),
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SchemaCompatError(f"git {' '.join(args)} failed: {exc}") from exc
    return p.returncode, p.stdout


def changed_schema_files(root: Path, base_rev: str) -> List[str]:
    """Schema files under dv_harness/schemas/ that differ between `base_rev`
    and the working tree."""
    code, out = _git(root, ["diff", "--name-only", base_rev, "--", SCHEMAS_DIR])
    if code != 0:
        raise SchemaCompatError(f"cannot diff against {base_rev!r}; is it a valid revision?")
    return sorted(line.strip() for line in out.splitlines()
                  if line.strip().endswith(".schema.json"))


def read_blob_at_rev(root: Path, relpath: str, rev: str) -> Optional[str]:
    """File content at a revision, or None when the path did not exist there."""
    code, out = _git(root, ["show", f"{rev}:{relpath}"])
    return out if code == 0 else None


def owning_modules_for_schema(root: Path, schema_filename: str) -> List[str]:
    """Modules under dv_harness/ that name this schema file AND declare their
    own SCHEMA_VERSION.

    Discovered by reading the source rather than from a hand-maintained table,
    so a new schema/module pair is covered the day it lands.
    """
    owners = []
    for py in sorted(Path(root, "dv_harness").glob("*.py")):
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable source file
            continue
        if schema_filename in text and _SCHEMA_VERSION_RE.search(text):
            owners.append(f"dv_harness/{py.name}")
    return owners


def classify_repo_schema_changes(root: Path, base_rev: str,
                                 *, prove: bool = True) -> Dict[str, Any]:
    """Classify every change this branch made to the project's own schemas, and
    check the env_manifest precedent: a BREAKING schema whose owning module
    declares a SCHEMA_VERSION must bump it."""
    root = Path(root)
    results = []
    for relpath in changed_schema_files(root, base_rev):
        blob = read_blob_at_rev(root, relpath, base_rev)
        target = root / relpath
        if blob is None:
            results.append({"schema": relpath, "verdict": VERDICT_COMPATIBLE,
                            "findings": [], "reason": "new schema file; nothing to break",
                            "counts": {"breaking": 0, "unknown": 0, "proven": 0}})
            continue
        if not target.exists():
            results.append({"schema": relpath, "verdict": VERDICT_BREAKING,
                            "counts": {"breaking": 1, "unknown": 0, "proven": 0},
                            "findings": [{"code": "SCHEMA_DELETED", "verdict": VERDICT_BREAKING,
                                          "schema_path": "#", "instance_path": "",
                                          "witness_status": "NOT_APPLICABLE",
                                          "detail": "the schema file was removed; every "
                                                    "document written against it is now "
                                                    "unvalidatable"}]})
            continue
        try:
            old = json.loads(blob)
        except ValueError as exc:
            raise SchemaCompatError(f"{relpath}@{base_rev} is not valid JSON: {exc}") from exc
        result = classify_schema_change(old, _load_schema_file(target), prove=prove)
        result["schema"] = relpath
        result["findings"].extend(
            _version_bump_findings(root, relpath, base_rev, result["verdict"]))
        result["verdict"] = _worst([result["verdict"]]
                                   + [f["verdict"] for f in result["findings"]])
        result["counts"]["breaking"] = sum(
            1 for f in result["findings"] if f["verdict"] == VERDICT_BREAKING)
        results.append(result)

    return {
        "classifier_schema_version": SCHEMA_VERSION,
        "base_rev": base_rev,
        "verdict": _worst([r["verdict"] for r in results]),
        "schemas": results,
        "schemas_changed": len(results),
    }


def _version_bump_findings(root: Path, relpath: str, base_rev: str,
                           verdict: str) -> List[Dict[str, Any]]:
    """env_manifest's 1.0 -> 1.1 rule, enforced: breaking edit => version bump.

    Reported for UNKNOWN too, at UNKNOWN severity -- an edit nobody can prove
    safe is not a reason to skip the bump.
    """
    if verdict == VERDICT_COMPATIBLE:
        return []
    findings = []
    for module in owning_modules_for_schema(root, Path(relpath).name):
        new_text = (root / module).read_text(encoding="utf-8")
        old_text = read_blob_at_rev(root, module, base_rev)
        new_m = _SCHEMA_VERSION_RE.search(new_text)
        old_m = _SCHEMA_VERSION_RE.search(old_text or "")
        if not new_m or not old_m:
            continue
        if new_m.group(1) == old_m.group(1):
            findings.append({
                "code": "BREAKING_WITHOUT_VERSION_BUMP",
                "verdict": verdict,
                "schema_path": "#", "instance_path": "",
                "witness_status": "NOT_APPLICABLE",
                "detail": f"{module} still declares SCHEMA_VERSION "
                          f"{new_m.group(1)!r} after a {verdict} change to "
                          f"{relpath}; readers cannot tell the two contracts apart "
                          f"(env_manifest.py bumped 1.0 -> 1.1 for exactly this)",
            })
    return findings


# --------------------------------------------------------------------------
# verb
# --------------------------------------------------------------------------

def _render(result: Dict[str, Any]) -> str:
    lines = []
    if "schemas" in result:
        lines.append(f"schema-compat: {result['verdict']} "
                     f"({result['schemas_changed']} schema(s) changed since "
                     f"{result['base_rev']})")
        for r in result["schemas"]:
            note = f" -- {r['reason']}" if r.get("reason") else ""
            lines.append(f"  {r['schema']}: {r['verdict']}{note}")
            for f in r.get("findings", []):
                lines.append(f"    [{f['verdict']}] {f['code']} at {f['schema_path']}"
                             f" ({f.get('witness_status', '-')}): {f['detail']}")
    else:
        lines.append(f"schema-compat: {result['verdict']} "
                     f"({result['counts']['breaking']} breaking, "
                     f"{result['counts']['unknown']} unknown, "
                     f"{result['counts']['proven']} proven by real validation; "
                     f"{result['documents_broken']}/{result['documents_checked']} "
                     f"checked document(s) broken)")
        for f in result["findings"]:
            lines.append(f"  [{f['verdict']}] {f['code']} at {f['schema_path']}"
                         f" ({f.get('witness_status', '-')}): {f['detail']}")
    return "\n".join(lines)


def execute_verb(*, old: Optional[str] = None, new: Optional[str] = None,
                 base: Optional[str] = None, root: Optional[str] = None,
                 corpus: Sequence[str] = (), as_json: bool = False) -> Tuple[str, int]:
    """Exit codes: 0 BACKWARD_COMPATIBLE, 1 BREAKING, 2 NOT_AVAILABLE (nothing
    comparable / a schema could not be read), 3 UNKNOWN.

    UNKNOWN gets its own non-zero code deliberately: "this module could not
    decide" must never be reported to a caller with the same exit status as
    "this change is safe".
    """
    try:
        if base:
            result = classify_repo_schema_changes(Path(root or "."), base)
            if result["schemas_changed"] == 0:
                payload = {"status": "NOT_AVAILABLE", "verdict": None,
                           "reason": f"no schema under {SCHEMAS_DIR} changed since {base}"}
                return (json.dumps(payload, indent=2) if as_json
                        else f"schema-compat: NOT_AVAILABLE -- {payload['reason']}"), 2
        elif old and new:
            result = compare_schema_files(old, new, corpus_paths=corpus)
        else:
            return ("schema-compat: NOT_AVAILABLE -- supply either --base REV or "
                    "both --old and --new"), 2
    except SchemaCompatError as exc:
        payload = {"status": "NOT_AVAILABLE", "verdict": None, "reason": str(exc)}
        return (json.dumps(payload, indent=2) if as_json
                else f"schema-compat: NOT_AVAILABLE -- {exc}"), 2

    code = {VERDICT_COMPATIBLE: 0, VERDICT_BREAKING: 1, VERDICT_UNKNOWN: 3}[result["verdict"]]
    return (json.dumps(result, indent=2, default=str) if as_json else _render(result)), code


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.schema_compat",
        description="Classify a JSON Schema change as BACKWARD_COMPATIBLE / "
                    "BREAKING / UNKNOWN, where compatible means every document "
                    "valid under the old schema is still valid under the new one.")
    ap.add_argument("--old", help="the previous schema file")
    ap.add_argument("--new", help="the new schema file")
    ap.add_argument("--base", help="git revision to compare this working tree's "
                                   f"{SCHEMAS_DIR}/*.schema.json against")
    ap.add_argument("--root", default=".", help="repository root for --base")
    ap.add_argument("--corpus", nargs="*", default=[],
                    help="real documents to check the verdict against")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    text, code = execute_verb(old=a.old, new=a.new, base=a.base, root=a.root,
                              corpus=a.corpus, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
