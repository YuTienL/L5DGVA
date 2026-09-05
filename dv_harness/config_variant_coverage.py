"""dv_harness/config_variant_coverage.py -- combinatorial CONFIGURATION
variant selection (spec section 232, "CONFIGURATION VARIANT EXPLOSION
CONTROL"), 2026-09-06.

GAP THIS CLOSES. Section 232 lists a real configuration space (protocol
generation, speed, lane width, data width, compile defines, feature modes,
SKU, clock mode, subsystem combinations, VIP configuration), says "avoid
blind Cartesian-product regression", and names `pairwise/covering
combinations` as one of the evidence-grounded selection methods. Nothing in
this repo answered that question. `grep -rn "pairwise\\|covering_array\\|
combinatorial" --include=*.py .` matched only unrelated things:
`system_topology_analysis._pairwise_overlap()` (do two ADDRESS REGIONS
intersect), `system_command_plan`'s pairwise ESCALATION QUESTION split, and
`source_authority`'s pairwise CONFLICT questions. None of them is a covering
array over a configuration space.

WHAT THIS IS NOT, and why it is not an extension of them. `change_impact.py`
and `regression_tiers.py` answer "WHICH TESTS do we run" -- a selection over
a named universe of patterns driven by a real git diff and a traceability
registry. This module answers the orthogonal question "WHICH CONFIGURATIONS
do we run them in" -- a selection over a COMBINATORIAL space that has no
enumerated universe, only dimensions and legal values. Neither module has any
notion of a configuration dimension, so there was nothing to extend; the two
answers compose (test set x config set) at the caller, and this module
deliberately does not perform that composition (see LIMITS).

THE ALGORITHM IS A REAL, CITED ONE, NOT A HEURISTIC. `generate_covering_array()`
implements **IPOG (In-Parameter-Order-General)** -- Lei, Kacker, Kuhn, Okun and
Lawrence, "IPOG: A General Strategy for T-Way Software Testing", ECBS 2007;
the generalisation to arbitrary strength t of Tai and Lei's IPO (2002), and
the algorithm NIST's ACTS tool is built on. It was chosen over the
alternatives for reasons that matter here:
  - It is DETERMINISTIC (no random restarts), so the same config space always
    produces the same plan and a plan is diffable/reviewable -- the same
    property `env_manifest.save_env_manifest()` insists on.
  - It generalises to any strength t >= 2 with one implementation, so
    3-way coverage of a genuinely interaction-heavy subspace does not need a
    second mechanism. The default is t=2 (pairwise) because that is what
    section 232 names and what the empirical NIST interaction-fault data
    supports as the cost/benefit knee.
  - Its horizontal/vertical extension structure accepts SEEDED rows, which is
    exactly what section 232's "critical configurations must not be removed
    merely to reduce compute" requires: declared critical combinations are
    seeded as rows BEFORE generation and can never be dropped by it.

IPOG as implemented here, in its own terms:
  1. Order dimensions by descending value count (the standard IPOG ordering
     heuristic; ties broken by name so the order is deterministic).
  2. Seed every declared critical combination, completed to a full legal
     configuration.
  3. Build the base: every legal value combination of the first t dimensions
     not already covered by a seeded row.
  4. For each remaining dimension P, in order:
     HORIZONTAL EXTENSION -- give every existing row a value for P, choosing
     the value that newly covers the most target t-tuples involving P.
     VERTICAL EXTENSION -- for each t-tuple involving P still uncovered,
     fold it into an existing row whose relevant cells are unassigned or
     already equal, else add a new row.
  5. Complete every remaining unassigned cell to a legal value.

CONSTRAINTS ARE REAL, AND HANDLED SOUNDLY RATHER THAN OPTIMISTICALLY. A
`forbid` clause is a partial assignment that may not appear in any emitted
configuration (gen5 x1 does not exist; a compile define that contradicts a
feature mode). Validity is enforced at every assignment, target t-tuples that
themselves contain a forbidden clause are excluded from the target set up
front, and -- because a heuristic under constraints can still paint itself
into a corner -- a final REPAIR pass runs the independent verifier and, for
every still-uncovered tuple, performs a real backtracking search for a legal
full configuration containing it. Only a tuple for which that exhaustive
search proves no legal completion exists is reported, by name, as
UNREACHABLE_UNDER_CONSTRAINTS. The module therefore never reports full
coverage it did not achieve, and never silently drops a pair.

`verify_coverage()` is deliberately a SEPARATE, independent recomputation
from first principles (enumerate every legal t-tuple, scan the emitted rows)
rather than a read-back of the generator's own bookkeeping. It is what the
test suite holds the generator to, and what `config-variants verify` checks
a HAND-WRITTEN or externally-produced combination list with.

CLI: `dv-harness config-variants plan|verify --space <file> [--strength N]`,
or `python -m dv_harness.config_variant_coverage` -- one shared
`execute_verb()` implementation, the same convention `power-intent` /
`golden-scenario` use. Exit 0 full coverage, 1 a real coverage finding
(uncovered or unreachable tuples, a missing critical combination), 2
NOT_AVAILABLE / usage error.

LIMITS, disclosed rather than implied closed:
  1. It SELECTS; it decides nothing else. It runs no build, submits no job,
     touches no LSF, and has no stage gate -- a gate that passed on a config
     plan nobody ran would be worse than none. The plan is an input to a
     human's or a caller's regression decision.
  2. It does not compose with test selection. Which tests to run in each
     selected configuration is `change_impact.select_regression()`'s answer,
     and cross-multiplying the two is a cost decision this module does not
     own.
  3. Section 232's other listed selection methods -- requirement-driven,
     historical-risk and change-impact combinations -- enter ONLY as declared
     `critical_combinations` supplied by the caller with a real reason
     string. This module does not mine requirements, failure history or a git
     diff to invent them; a combination is critical because real evidence
     said so, not because this module guessed.
  4. Equivalence-class reduction is the AUTHOR's act, not this module's:
     collapsing 64 legal data widths to {8, 32, 512} happens when the
     dimension's legal values are declared. Nothing here decides that two
     values are equivalent, because that is a protocol-behaviour claim that
     needs primary evidence.
  5. Values must be JSON scalars (str/int/float/bool/None). A structured
     value is rejected rather than stringified, because two different objects
     with the same repr are not the same configuration.
  6. `legal_cross_product_size` is exactly counted only when the raw cross
     product is at or below `MAX_EXACT_ENUMERATION`; above that it reports
     UNCOUNTED with the real reason instead of a number nobody computed.
"""
from __future__ import annotations

import itertools
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

#: The algorithm, cited in the emitted plan itself so a reviewer of the
#: artifact never has to take "pairwise" on trust.
ALGORITHM = "IPOG"
ALGORITHM_REFERENCE = (
    "Lei, Kacker, Kuhn, Okun, Lawrence, 'IPOG: A General Strategy for T-Way "
    "Software Testing', IEEE ECBS 2007 (the strength-t generalisation of "
    "Tai & Lei's In-Parameter-Order, 2002; the algorithm behind NIST ACTS)"
)

#: Above this raw cross-product size the LEGAL combination count is reported
#: as UNCOUNTED rather than enumerated. The raw (illegal-inclusive) size is
#: always exact -- it is a product, not an enumeration.
MAX_EXACT_ENUMERATION = 200_000

#: Node ceiling for one backtracking completion search. Real config spaces
#: are small (tens of dimensions, single-digit value counts); this exists so
#: a pathologically constrained space fails loudly instead of hanging.
MAX_COMPLETION_NODES = 200_000

#: Where a generated plan is written by default. A sibling of
#: `change_impact.COMPUTED_SELECTION_PARTS` because it is the same kind of
#: artifact (a computed, reviewable regression-scoping input) -- not the same
#: file, because it answers a different question.
CONFIG_VARIANT_PLAN_PARTS = (".dv-harness", "regression", "config_variant_plan.json")

STATUS_FULL = "FULL_COVERAGE"
STATUS_FULL_EXCEPT_UNREACHABLE = "FULL_EXCEPT_UNREACHABLE"
STATUS_PARTIAL = "PARTIAL_COVERAGE"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

_UNSET = object()


class ConfigSpaceError(ValueError):
    """A configuration space that cannot be honoured as written: an unknown
    dimension, a value outside a dimension's legal values, a duplicate
    dimension, a non-scalar value, or a declared critical combination that
    the space's own constraints forbid. Every one of these is a contradiction
    in the caller's own declaration and is surfaced, never silently
    resolved."""


def _now() -> str:
    """Same UTC-ISO stamp `regression_tiers._now()`/`control_plane.now()`
    already use -- duplicated as a 2-line local helper, for the same reason
    regression_tiers does, so this module stays importable by a gate
    subprocess without pulling the engine in."""
    return datetime.now(timezone.utc).isoformat()


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


# --------------------------------------------------------------------------
# the space
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigDimension:
    """One named configuration dimension and its LEGAL values. `source` is
    free-form provenance ("PCIe base spec 5.0 sec 4.2", "env.manifest.json
    vip_config.speed_modes") carried through into the plan so a reviewer can
    ask where a value list came from."""

    name: str
    values: Tuple[Any, ...]
    source: str = ""

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ConfigSpaceError("a configuration dimension needs a non-empty name")
        if not self.values:
            raise ConfigSpaceError(f"dimension {self.name!r} declares no legal values")
        for v in self.values:
            if not _is_scalar(v):
                raise ConfigSpaceError(
                    f"dimension {self.name!r} value {v!r} is not a JSON scalar; "
                    "structured values are refused rather than stringified")
        if len(set(self.values)) != len(self.values):
            raise ConfigSpaceError(f"dimension {self.name!r} declares a duplicate value")


@dataclass(frozen=True)
class Constraint:
    """A FORBIDDEN partial assignment. `forbid` maps dimension -> the value
    (or any of the values) that, when they all hold at once, make a
    configuration illegal. `reason` is required-in-spirit and carried into
    the plan: a constraint with no stated reason is a constraint nobody can
    review."""

    forbid: Mapping[str, Tuple[Any, ...]]
    reason: str = ""

    def matches(self, assignment: Mapping[str, Any]) -> bool:
        """True when EVERY dimension the constraint names is assigned and
        holds one of the forbidden values. A partial assignment that has not
        yet assigned one of them is not (yet) illegal."""
        for dim, vals in self.forbid.items():
            if dim not in assignment:
                return False
            if assignment[dim] not in vals:
                return False
        return True

    def to_dict(self) -> dict:
        return {"forbid": {d: (list(v) if len(v) != 1 else v[0]) for d, v in self.forbid.items()},
                "reason": self.reason}


@dataclass(frozen=True)
class CriticalCombination:
    """A configuration that MUST appear in the plan, whatever the covering
    array would otherwise select -- section 232's "Critical configurations
    must not be removed merely to reduce compute", as enforced code. The
    assignment may be PARTIAL (pin gen5 x16 and let the rest be chosen);
    completion to a full legal configuration is a real backtracking search,
    not a default-value fill."""

    assignment: Mapping[str, Any]
    reason: str = ""

    def to_dict(self) -> dict:
        return {"assignment": dict(self.assignment), "reason": self.reason}


@dataclass
class ConfigSpace:
    space_id: str
    dimensions: Tuple[ConfigDimension, ...]
    constraints: Tuple[Constraint, ...] = ()
    critical_combinations: Tuple[CriticalCombination, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        names = [d.name for d in self.dimensions]
        if not names:
            raise ConfigSpaceError("a configuration space needs at least one dimension")
        if len(set(names)) != len(names):
            raise ConfigSpaceError("duplicate dimension name in configuration space")
        by_name = {d.name: d for d in self.dimensions}
        for c in self.constraints:
            if not c.forbid:
                raise ConfigSpaceError("a constraint must forbid at least one dimension value")
            for dim, vals in c.forbid.items():
                if dim not in by_name:
                    raise ConfigSpaceError(
                        f"constraint names unknown dimension {dim!r}")
                for v in vals:
                    if v not in by_name[dim].values:
                        raise ConfigSpaceError(
                            f"constraint on {dim!r} names value {v!r}, which is not one of "
                            f"its legal values {list(by_name[dim].values)!r}")
        for crit in self.critical_combinations:
            if not crit.assignment:
                raise ConfigSpaceError("a critical combination must assign at least one dimension")
            for dim, v in crit.assignment.items():
                if dim not in by_name:
                    raise ConfigSpaceError(
                        f"critical combination names unknown dimension {dim!r}")
                if v not in by_name[dim].values:
                    raise ConfigSpaceError(
                        f"critical combination assigns {dim!r}={v!r}, which is not one of its "
                        f"legal values {list(by_name[dim].values)!r}")
            if not self.is_valid(crit.assignment):
                raise ConfigSpaceError(
                    f"critical combination {dict(crit.assignment)!r} is forbidden by this space's "
                    "own constraints -- a contradiction in the declaration, not something this "
                    "module may resolve by dropping either side")

    @property
    def dimension_names(self) -> Tuple[str, ...]:
        return tuple(d.name for d in self.dimensions)

    def dimension(self, name: str) -> ConfigDimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise ConfigSpaceError(f"unknown dimension {name!r}")

    def is_valid(self, assignment: Mapping[str, Any]) -> bool:
        """A partial or full assignment is valid unless some constraint's
        forbidden clause is entirely present in it."""
        for c in self.constraints:
            if c.matches(assignment):
                return False
        return True

    def violated_constraint(self, assignment: Mapping[str, Any]) -> Optional[Constraint]:
        for c in self.constraints:
            if c.matches(assignment):
                return c
        return None

    def full_cross_product_size(self) -> int:
        """The blind Cartesian product size -- the number section 232 exists
        to avoid running. Exact: it is a product, not an enumeration."""
        size = 1
        for d in self.dimensions:
            size *= len(d.values)
        return size

    def legal_cross_product_size(self) -> Tuple[Optional[int], str]:
        """(count, reason). Exactly enumerated only up to
        MAX_EXACT_ENUMERATION; above that the count is None with a real
        reason rather than a number nobody computed."""
        raw = self.full_cross_product_size()
        if raw > MAX_EXACT_ENUMERATION:
            return None, (f"UNCOUNTED: raw cross product {raw} exceeds "
                          f"MAX_EXACT_ENUMERATION={MAX_EXACT_ENUMERATION}")
        if not self.constraints:
            return raw, "no constraints declared: every cross-product point is legal"
        names = self.dimension_names
        count = 0
        for combo in itertools.product(*[d.values for d in self.dimensions]):
            if self.is_valid(dict(zip(names, combo))):
                count += 1
        return count, "exactly enumerated"

    def to_dict(self) -> dict:
        return {
            "space_id": self.space_id,
            "description": self.description,
            "dimensions": [{"name": d.name, "values": list(d.values), "source": d.source}
                           for d in self.dimensions],
            "constraints": [c.to_dict() for c in self.constraints],
            "critical_combinations": [c.to_dict() for c in self.critical_combinations],
        }


def _coerce_forbid(raw: Mapping[str, Any]) -> Dict[str, Tuple[Any, ...]]:
    out: Dict[str, Tuple[Any, ...]] = {}
    for dim, val in raw.items():
        if isinstance(val, (list, tuple)):
            vals = tuple(val)
            if not vals:
                raise ConfigSpaceError(f"constraint on {dim!r} forbids an empty value list")
        else:
            vals = (val,)
        for v in vals:
            if not _is_scalar(v):
                raise ConfigSpaceError(f"constraint on {dim!r} names a non-scalar value {v!r}")
        out[str(dim)] = vals
    return out


def config_space_from_dict(data: Mapping[str, Any]) -> ConfigSpace:
    """Load a configuration space from its JSON shape. Every structural
    problem raises ConfigSpaceError naming the offending declaration; nothing
    is silently defaulted, because a mistyped dimension name that quietly
    became a new dimension would produce a plan that covers the wrong
    space."""
    if not isinstance(data, Mapping):
        raise ConfigSpaceError("configuration space must be a JSON object")
    dims_raw = data.get("dimensions")
    if not isinstance(dims_raw, list) or not dims_raw:
        raise ConfigSpaceError("configuration space needs a non-empty 'dimensions' list")
    dims: List[ConfigDimension] = []
    for entry in dims_raw:
        if not isinstance(entry, Mapping):
            raise ConfigSpaceError(f"dimension entry {entry!r} is not an object")
        values = entry.get("values")
        if not isinstance(values, list):
            raise ConfigSpaceError(
                f"dimension {entry.get('name')!r} needs a 'values' list of legal values")
        dims.append(ConfigDimension(name=str(entry.get("name", "")).strip(),
                                    values=tuple(values),
                                    source=str(entry.get("source", ""))))
    cons: List[Constraint] = []
    for entry in data.get("constraints", []) or []:
        if not isinstance(entry, Mapping):
            raise ConfigSpaceError(f"constraint entry {entry!r} is not an object")
        forbid = entry.get("forbid")
        if not isinstance(forbid, Mapping) or not forbid:
            raise ConfigSpaceError("a constraint needs a non-empty 'forbid' object")
        cons.append(Constraint(forbid=_coerce_forbid(forbid),
                               reason=str(entry.get("reason", ""))))
    crits: List[CriticalCombination] = []
    for entry in data.get("critical_combinations", []) or []:
        if not isinstance(entry, Mapping):
            raise ConfigSpaceError(f"critical combination entry {entry!r} is not an object")
        assignment = entry.get("assignment")
        if not isinstance(assignment, Mapping) or not assignment:
            raise ConfigSpaceError("a critical combination needs a non-empty 'assignment' object")
        crits.append(CriticalCombination(assignment=dict(assignment),
                                         reason=str(entry.get("reason", ""))))
    return ConfigSpace(space_id=str(data.get("space_id", "") or "unnamed_config_space"),
                       dimensions=tuple(dims), constraints=tuple(cons),
                       critical_combinations=tuple(crits),
                       description=str(data.get("description", "")))


def load_config_space(path: Any) -> ConfigSpace:
    p = Path(path)
    if not p.exists():
        raise ConfigSpaceError(f"configuration space file does not exist: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigSpaceError(f"configuration space {p} is not valid JSON: {e}") from None
    return config_space_from_dict(data)


# --------------------------------------------------------------------------
# target t-tuples
# --------------------------------------------------------------------------

#: A target tuple is a sorted tuple of (dimension_name, value) pairs over t
#: DISTINCT dimensions. Sorted by dimension name so one interaction has one
#: canonical representation regardless of how it was produced.
TargetTuple = Tuple[Tuple[str, Any], ...]


def target_tuples(space: ConfigSpace, strength: int = 2) -> Tuple[List[TargetTuple], List[dict]]:
    """Every t-way interaction this space is REQUIRED to cover, plus the ones
    excluded because the interaction itself is forbidden by a constraint.
    Returns (targets, excluded) where each excluded entry names the tuple and
    the constraint that excluded it -- an excluded pair is reported, never
    silently absent from the arithmetic."""
    if strength < 1:
        raise ConfigSpaceError("strength must be at least 1")
    if strength > len(space.dimensions):
        raise ConfigSpaceError(
            f"strength {strength} exceeds the {len(space.dimensions)} declared dimension(s)")
    targets: List[TargetTuple] = []
    excluded: List[dict] = []
    for dim_combo in itertools.combinations(space.dimensions, strength):
        for value_combo in itertools.product(*[d.values for d in dim_combo]):
            assignment = {d.name: v for d, v in zip(dim_combo, value_combo)}
            tup = _as_tuple(assignment)
            violated = space.violated_constraint(assignment)
            if violated is not None:
                excluded.append({"tuple": _tuple_to_dict(tup),
                                 "excluded_by_constraint": violated.to_dict()})
                continue
            targets.append(tup)
    return targets, excluded


def _as_tuple(assignment: Mapping[str, Any]) -> TargetTuple:
    return tuple(sorted(((str(k), v) for k, v in assignment.items()), key=lambda kv: kv[0]))


def _tuple_to_dict(tup: TargetTuple) -> Dict[str, Any]:
    return {k: v for k, v in tup}


def _tuples_of(assignment: Mapping[str, Any], strength: int) -> Iterable[TargetTuple]:
    items = sorted(((str(k), v) for k, v in assignment.items()), key=lambda kv: kv[0])
    if len(items) < strength:
        return ()
    return itertools.combinations(items, strength)


# --------------------------------------------------------------------------
# completion (real backtracking search under constraints)
# --------------------------------------------------------------------------

def complete_assignment(space: ConfigSpace, partial: Mapping[str, Any],
                        *, max_nodes: int = MAX_COMPLETION_NODES) -> Optional[Dict[str, Any]]:
    """Extend `partial` to a FULL legal configuration, or return None when no
    such configuration exists. A real depth-first backtracking search with
    constraint checking at every assignment -- not a default-value fill,
    which would silently emit illegal configurations under any non-trivial
    constraint set.

    Deterministic: dimensions are visited in declaration order and values in
    declared order, so the same partial always completes the same way and a
    plan stays diffable."""
    for dim, v in partial.items():
        if v not in space.dimension(str(dim)).values:
            raise ConfigSpaceError(f"assignment {dim!r}={v!r} is not a legal value")
    if not space.is_valid(partial):
        return None
    unassigned = [d for d in space.dimensions if d.name not in partial]
    if not unassigned:
        return dict(partial)
    current = dict(partial)
    nodes = 0

    def walk(idx: int) -> bool:
        nonlocal nodes
        if idx == len(unassigned):
            return True
        dim = unassigned[idx]
        for value in dim.values:
            nodes += 1
            if nodes > max_nodes:
                raise ConfigSpaceError(
                    f"completion search exceeded {max_nodes} nodes for {dict(partial)!r}; "
                    "this configuration space is too constrained for a bounded search")
            current[dim.name] = value
            if space.is_valid(current) and walk(idx + 1):
                return True
            del current[dim.name]
        return False

    return dict(current) if walk(0) else None


# --------------------------------------------------------------------------
# IPOG
# --------------------------------------------------------------------------

def _ordered_dimensions(space: ConfigSpace) -> List[ConfigDimension]:
    """IPOG's standard ordering heuristic: most values first (it makes the
    unavoidable base block as large as it has to be exactly once, at the
    front), ties broken by name so the order -- and therefore the plan -- is
    deterministic."""
    return sorted(space.dimensions, key=lambda d: (-len(d.values), d.name))


def generate_covering_array(space: ConfigSpace, strength: int = 2,
                            *, max_nodes: int = MAX_COMPLETION_NODES) -> List[Dict[str, Any]]:
    """IPOG. Returns a list of FULL, LEGAL configurations covering every
    reachable t-way interaction of `space`, with every declared critical
    combination present. See this module's docstring for the citation and the
    step-by-step correspondence to the published algorithm."""
    targets, _excluded = target_tuples(space, strength)
    target_set = set(targets)
    covered: set = set()
    dims = _ordered_dimensions(space)
    names = [d.name for d in dims]
    t = strength

    def mark(assignment: Mapping[str, Any]) -> None:
        for tup in _tuples_of(assignment, t):
            if tup in target_set:
                covered.add(tup)

    # --- step 2: seed the critical combinations, completed to full legal rows
    tests: List[Dict[str, Any]] = []
    critical_row_indexes: List[int] = []
    for crit in space.critical_combinations:
        full = complete_assignment(space, crit.assignment, max_nodes=max_nodes)
        if full is None:
            raise ConfigSpaceError(
                f"critical combination {dict(crit.assignment)!r} has no legal completion under "
                "this space's constraints -- surfaced rather than dropped, because section 232 "
                "forbids removing a critical configuration to make the arithmetic work")
        critical_row_indexes.append(len(tests))
        tests.append(full)
        mark(full)

    # --- step 3: the base block over the first t dimensions
    base_dims = dims[:t]
    for value_combo in itertools.product(*[d.values for d in base_dims]):
        assignment = {d.name: v for d, v in zip(base_dims, value_combo)}
        tup = _as_tuple(assignment)
        if tup not in target_set or tup in covered:
            continue
        tests.append(dict(assignment))
        mark(assignment)

    # --- step 4: horizontal + vertical extension, one dimension at a time
    for idx in range(t, len(dims)):
        param = dims[idx]
        prefix = names[:idx]

        # HORIZONTAL: every existing row gets a value for `param`.
        for row in tests:
            if param.name in row:
                continue  # a seeded critical row already fixes this dimension
            best_value = _UNSET
            best_gain = -1
            best_new: List[TargetTuple] = []
            for value in param.values:
                candidate = dict(row)
                candidate[param.name] = value
                if not space.is_valid(candidate):
                    continue
                new = [tup for tup in _tuples_of(candidate, t)
                       if (param.name, value) in tup and tup in target_set and tup not in covered]
                if len(new) > best_gain:
                    best_gain, best_value, best_new = len(new), value, new
            if best_value is _UNSET:
                continue  # no legal value given this row's prefix; left to completion
            row[param.name] = best_value
            covered.update(best_new)

        # VERTICAL: cover what horizontal extension could not.
        remaining = [tup for tup in targets
                     if tup not in covered
                     and any(k == param.name for k, _ in tup)
                     and all(k == param.name or k in prefix for k, _ in tup)]
        for tup in remaining:
            if tup in covered:
                continue
            want = _tuple_to_dict(tup)
            placed = False
            for row in tests:
                if any(row.get(k, _UNSET) not in (_UNSET, v) for k, v in want.items()):
                    continue
                candidate = dict(row)
                candidate.update(want)
                if not space.is_valid(candidate):
                    continue
                row.update(want)
                mark(row)
                placed = True
                break
            if not placed:
                if not space.is_valid(want):
                    continue
                tests.append(dict(want))
                mark(want)

    # --- step 5: complete every partially-assigned row to a full legal one
    completed: List[Dict[str, Any]] = []
    critical_rows = [tests[i] for i in critical_row_indexes]
    for row in tests:
        if len(row) == len(dims):
            completed.append(row)
            continue
        full = complete_assignment(space, row, max_nodes=max_nodes)
        if full is None:
            # Only reachable under constraints: the partial row painted
            # itself into a corner. Drop it here; the repair pass below
            # re-covers whatever it was carrying, or proves it unreachable.
            continue
        completed.append(full)

    # --- REPAIR: an independent recount over the COMPLETED rows (a dropped
    # or completed row may cover more or less than the bookkeeping above
    # believed), then a real exhaustive search for each remaining miss.
    still = _uncovered(target_set, completed, t)
    for tup in sorted(still, key=repr):
        full = complete_assignment(space, _tuple_to_dict(tup), max_nodes=max_nodes)
        if full is not None:
            completed.append(full)

    completed = _prune_redundant(space, completed, target_set, t, critical_rows)
    return completed


def _uncovered(target_set: set, rows: Sequence[Mapping[str, Any]], strength: int) -> set:
    seen: set = set()
    for row in rows:
        for tup in _tuples_of(row, strength):
            if tup in target_set:
                seen.add(tup)
    return target_set - seen


def _prune_redundant(space: ConfigSpace, rows: List[Dict[str, Any]], target_set: set,
                     strength: int, critical_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Drop any row whose entire t-tuple contribution is covered by the rows
    kept -- the standard covering-array post-pass. A row that IS a declared
    critical combination is never a candidate for removal, whatever the
    arithmetic says (section 232's own rule)."""
    critical_keys = {_as_tuple(r) for r in critical_rows}
    contributions = [set(tup for tup in _tuples_of(r, strength) if tup in target_set) for r in rows]
    keep = [True] * len(rows)
    # Rows contributing most first, so a removal decision is made against the
    # strongest survivors -- deterministic, index as the tie-break.
    order = sorted(range(len(rows)), key=lambda i: (-len(contributions[i]), i))
    for i in order:
        if _as_tuple(rows[i]) in critical_keys:
            continue
        others: set = set()
        for j in range(len(rows)):
            if j != i and keep[j]:
                others |= contributions[j]
        if contributions[i] <= others:
            keep[i] = False
    return [r for r, k in zip(rows, keep) if k]


# --------------------------------------------------------------------------
# independent verification
# --------------------------------------------------------------------------

def verify_coverage(space: ConfigSpace, combinations: Sequence[Mapping[str, Any]],
                    strength: int = 2) -> dict:
    """Recompute, from first principles, whether `combinations` covers every
    reachable t-way interaction of `space`. Deliberately independent of the
    generator's bookkeeping: it re-enumerates the target set and rescans the
    rows, so it can be pointed at a hand-written or externally-produced
    combination list and is what the test suite holds the generator to.

    Reports illegal and incomplete rows too: a "covering" set containing a
    configuration the space forbids is not a valid answer."""
    targets, excluded = target_tuples(space, strength)
    target_set = set(targets)
    dim_names = set(space.dimension_names)

    illegal: List[dict] = []
    incomplete: List[dict] = []
    seen: set = set()
    for i, row in enumerate(combinations):
        missing = sorted(dim_names - set(row))
        unknown = sorted(set(row) - dim_names)
        if missing or unknown:
            incomplete.append({"index": i, "row": dict(row),
                               "unassigned_dimensions": missing,
                               "unknown_dimensions": unknown})
        bad_value = None
        for k, v in row.items():
            if k in dim_names and v not in space.dimension(k).values:
                bad_value = {"dimension": k, "value": v}
                break
        violated = space.violated_constraint(row)
        if violated is not None or bad_value is not None:
            entry: Dict[str, Any] = {"index": i, "row": dict(row)}
            if violated is not None:
                entry["violates"] = violated.to_dict()
            if bad_value is not None:
                entry["illegal_value"] = bad_value
            illegal.append(entry)
        for tup in _tuples_of(row, strength):
            if tup in target_set:
                seen.add(tup)

    uncovered = sorted(target_set - seen, key=repr)

    unreachable: List[dict] = []
    genuinely_uncovered: List[dict] = []
    for tup in uncovered:
        # An uncovered tuple is only excusable when NO legal configuration
        # containing it exists -- proven by a real exhaustive search, not
        # assumed.
        if complete_assignment(space, _tuple_to_dict(tup)) is None:
            unreachable.append({"tuple": _tuple_to_dict(tup),
                                "reason": "UNREACHABLE_UNDER_CONSTRAINTS: no legal full "
                                          "configuration contains this interaction"})
        else:
            genuinely_uncovered.append({"tuple": _tuple_to_dict(tup)})

    if genuinely_uncovered or illegal or incomplete:
        status = STATUS_PARTIAL
    elif unreachable:
        status = STATUS_FULL_EXCEPT_UNREACHABLE
    else:
        status = STATUS_FULL

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "strength": strength,
        "target_tuple_count": len(targets),
        "covered_tuple_count": len(seen),
        "uncovered_tuple_count": len(genuinely_uncovered),
        "uncovered_tuples": genuinely_uncovered,
        "unreachable_tuples": unreachable,
        "excluded_by_constraint_count": len(excluded),
        "excluded_by_constraint": excluded,
        "illegal_combinations": illegal,
        "incomplete_combinations": incomplete,
        "combination_count": len(combinations),
    }


def critical_combination_status(space: ConfigSpace,
                                combinations: Sequence[Mapping[str, Any]]) -> dict:
    """Section 232's "critical configurations must not be removed merely to
    reduce compute", checked against the emitted plan rather than trusted of
    the generator. A critical combination is PRESENT when some emitted
    configuration agrees with it on every dimension it pins."""
    present: List[dict] = []
    missing: List[dict] = []
    for crit in space.critical_combinations:
        hit = None
        for i, row in enumerate(combinations):
            if all(row.get(k, _UNSET) == v for k, v in crit.assignment.items()):
                hit = i
                break
        entry = crit.to_dict()
        if hit is None:
            missing.append(entry)
        else:
            present.append({**entry, "combination_index": hit})
    return {"declared": len(space.critical_combinations),
            "present": len(present), "missing_count": len(missing),
            "present_combinations": present, "missing_combinations": missing}


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

def build_plan(space: ConfigSpace, strength: int = 2) -> dict:
    """Generate, then INDEPENDENTLY verify, then report. The verification is
    part of producing the plan rather than an optional extra, so a plan
    artifact can never claim coverage the verifier did not confirm."""
    combos = generate_covering_array(space, strength)
    coverage = verify_coverage(space, combos, strength)
    criticals = critical_combination_status(space, combos)
    if criticals["missing_count"]:
        # Unreachable in practice (criticals are seeded and never pruned) --
        # asserted anyway, because silently emitting a plan that dropped a
        # critical configuration is the exact failure section 232 names.
        raise ConfigSpaceError(
            "generated plan is missing declared critical combination(s): "
            f"{criticals['missing_combinations']!r}")
    raw = space.full_cross_product_size()
    legal, legal_reason = space.legal_cross_product_size()
    baseline = legal if legal is not None else raw
    status = coverage["status"]
    return {
        "schema_version": SCHEMA_VERSION,
        "space_id": space.space_id,
        "description": space.description,
        "algorithm": ALGORITHM,
        "algorithm_reference": ALGORITHM_REFERENCE,
        "strength": strength,
        "status": status,
        "dimension_count": len(space.dimensions),
        "dimensions": [{"name": d.name, "value_count": len(d.values),
                        "values": list(d.values), "source": d.source}
                       for d in space.dimensions],
        "constraint_count": len(space.constraints),
        "constraints": [c.to_dict() for c in space.constraints],
        "full_cross_product_size": raw,
        "legal_cross_product_size": legal,
        "legal_cross_product_reason": legal_reason,
        "selected_combination_count": len(combos),
        "reduction_ratio": round(1.0 - (len(combos) / baseline), 6) if baseline else 0.0,
        "reduction_baseline": "legal_cross_product" if legal is not None else "full_cross_product",
        "coverage": coverage,
        "critical_combinations": criticals,
        "combinations": combos,
        "generated_at": _now(),
    }


def format_plan(plan: Mapping[str, Any]) -> str:
    cov = plan.get("coverage", {})
    shape = ", ".join("{}x{}".format(d["name"], d["value_count"])
                      for d in plan.get("dimensions", []))
    lines = [
        f"config variant plan: {plan.get('space_id')}  [{plan.get('status')}]",
        f"  algorithm            : {plan.get('algorithm')} (strength t={plan.get('strength')})",
        f"                         {plan.get('algorithm_reference')}",
        f"  dimensions           : {plan.get('dimension_count')} ({shape})",
        f"  full cross product   : {plan.get('full_cross_product_size')}",
        f"  legal cross product  : {plan.get('legal_cross_product_size')} "
        f"({plan.get('legal_cross_product_reason')})",
        f"  selected             : {plan.get('selected_combination_count')} configuration(s)",
        f"  reduction            : {plan.get('reduction_ratio')} vs {plan.get('reduction_baseline')}",
        f"  {plan.get('strength')}-way interactions   : {cov.get('covered_tuple_count')}/"
        f"{cov.get('target_tuple_count')} covered, "
        f"{cov.get('uncovered_tuple_count')} uncovered, "
        f"{len(cov.get('unreachable_tuples', []))} unreachable under constraints, "
        f"{cov.get('excluded_by_constraint_count')} excluded as forbidden",
    ]
    crit = plan.get("critical_combinations", {})
    lines.append(f"  critical combinations: {crit.get('present')}/{crit.get('declared')} present")
    for entry in cov.get("unreachable_tuples", []):
        lines.append(f"    UNREACHABLE_UNDER_CONSTRAINTS {entry['tuple']}")
    for entry in cov.get("uncovered_tuples", []):
        lines.append(f"    UNCOVERED {entry['tuple']}")
    for entry in cov.get("illegal_combinations", []):
        lines.append(f"    ILLEGAL_COMBINATION[{entry['index']}] {entry['row']}")
    for entry in cov.get("incomplete_combinations", []):
        lines.append(f"    INCOMPLETE_COMBINATION[{entry['index']}] "
                     f"unassigned={entry['unassigned_dimensions']} "
                     f"unknown={entry['unknown_dimensions']}")
    lines.append("  NOTE: this plan SELECTS configurations only. It runs no build, submits no "
                 "job, and gates nothing.")
    return "\n".join(lines)


def plan_path(root: Any) -> Path:
    return Path(root).joinpath(*CONFIG_VARIANT_PLAN_PARTS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Same write-temp-then-replace convention `change_impact._atomic_write_json()`
    uses, so a crashed run never leaves a half-written plan on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_plan(root: Any, plan: Mapping[str, Any], *, path: Any = None) -> Path:
    out = Path(path) if path else plan_path(root)
    _atomic_write_json(out, dict(plan))
    return out


# --------------------------------------------------------------------------
# CLI (shared by `dv-harness config-variants` and `python -m ...`)
# --------------------------------------------------------------------------

_EXIT_BY_STATUS = {
    STATUS_FULL: 0,
    STATUS_FULL_EXCEPT_UNREACHABLE: 0,
    STATUS_PARTIAL: 1,
    STATUS_NOT_AVAILABLE: 2,
}


def execute_verb(verb: str, *, root: Any = ".", space_path: Optional[str] = None,
                 strength: int = 2, combinations_path: Optional[str] = None,
                 out_path: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness config-variants <verb>` and
    `python -m dv_harness.config_variant_coverage <verb>`. Returns
    (text, exit_code): 0 full coverage (unreachable-under-constraints
    interactions reported but not a failure -- they are a property of the
    space, not of the plan), 1 a real coverage finding, 2 NOT_AVAILABLE or a
    usage error. Selects only: runs, builds and submits nothing."""
    if not space_path:
        return ("config-variants requires --space <config_space.json>", 2)
    space = load_config_space(space_path)

    if verb == "plan":
        plan = build_plan(space, strength)
        written = None
        if out_path:
            written = write_plan(root, plan, path=out_path)
        text = json.dumps(plan, indent=2) if as_json else format_plan(plan)
        if written is not None and not as_json:
            text += f"\n  written to           : {written}"
        return text, _EXIT_BY_STATUS.get(plan["status"], 2)

    if verb == "verify":
        if not combinations_path:
            return ("config-variants verify requires --combinations <file.json> (a JSON list of "
                    "configurations, or a plan file with a 'combinations' key)", 2)
        raw = json.loads(Path(combinations_path).read_text(encoding="utf-8"))
        if isinstance(raw, Mapping):
            raw = raw.get("combinations", [])
        if not isinstance(raw, list):
            return (f"{combinations_path}: expected a JSON list of configurations", 2)
        report = verify_coverage(space, raw, strength)
        report["critical_combinations"] = critical_combination_status(space, raw)
        if report["critical_combinations"]["missing_count"]:
            report["status"] = STATUS_PARTIAL
        if as_json:
            return json.dumps(report, indent=2), _EXIT_BY_STATUS.get(report["status"], 2)
        crit = report["critical_combinations"]
        lines = [
            f"config variant coverage: {space.space_id}  [{report['status']}]",
            f"  strength             : t={strength}",
            f"  combinations checked : {report['combination_count']}",
            f"  {strength}-way interactions   : {report['covered_tuple_count']}/"
            f"{report['target_tuple_count']} covered, "
            f"{report['uncovered_tuple_count']} uncovered, "
            f"{len(report['unreachable_tuples'])} unreachable under constraints",
            f"  critical combinations: {crit['present']}/{crit['declared']} present",
        ]
        for entry in report["uncovered_tuples"]:
            lines.append(f"    UNCOVERED {entry['tuple']}")
        for entry in report["unreachable_tuples"]:
            lines.append(f"    UNREACHABLE_UNDER_CONSTRAINTS {entry['tuple']}")
        for entry in report["illegal_combinations"]:
            lines.append(f"    ILLEGAL_COMBINATION[{entry['index']}] {entry['row']}")
        for entry in report["incomplete_combinations"]:
            lines.append(f"    INCOMPLETE_COMBINATION[{entry['index']}] "
                         f"unassigned={entry['unassigned_dimensions']} "
                         f"unknown={entry['unknown_dimensions']}")
        for entry in crit["missing_combinations"]:
            lines.append(f"    MISSING_CRITICAL_COMBINATION {entry['assignment']}")
        return "\n".join(lines), _EXIT_BY_STATUS.get(report["status"], 2)

    return (f"unknown config-variants verb {verb!r}", 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.config_variant_coverage",
        description="Spec section 232 configuration variant explosion control: generate a "
                    "reduced t-way (default pairwise) covering set of configurations from a "
                    "declared config space, instead of a blind Cartesian product. Real IPOG "
                    "(Lei et al. 2007), constraint-aware, with declared critical combinations "
                    "never dropped. Selects only -- runs and submits nothing.")
    ap.add_argument("verb", choices=("plan", "verify"))
    ap.add_argument("--space", required=True, help="Configuration space JSON file.")
    ap.add_argument("--strength", type=int, default=2,
                    help="Interaction strength t (default 2 = pairwise).")
    ap.add_argument("--combinations", default=None,
                    help="verify: JSON list of configurations (or a plan file) to check.")
    ap.add_argument("--out", default=None, help="plan: also write the plan JSON to this path.")
    ap.add_argument("--root", default=".", help="Project root (used for the default plan path).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.verb, root=a.root, space_path=a.space, strength=a.strength,
                                  combinations_path=a.combinations, out_path=a.out,
                                  as_json=a.json)
    except ConfigSpaceError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
