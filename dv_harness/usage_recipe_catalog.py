"""dv_harness/usage_recipe_catalog.py -- named, documented USAGE RECIPES
assembled over `programming_sequence_ir.py`'s real per-sequence facts, 2026-09-06.

WHAT THIS IS
------------
`programming_sequence_ir.py` (see its own module docstring and CLAUDE.md
"Programming Sequence IR" section) models ONE `ProgrammingSequenceIR` -- an
ordered list of register write/read/wait steps -- and validates its ordering
against register facts. Nothing in that module (or anywhere else in this
repo) assembles several DOCUMENTED, PURPOSE-CITED, ordered step subsets into
a distinct, higher-level artifact: a "recipe" a DV engineer or a generated
user guide can hand someone -- "here is how to bring the link up: steps 0-3
of usb3_link_bringup, per programming-guide section 4.2" -- as opposed to raw
per-sequence step facts with no documented WHY attached. That is the gap this
module closes.

A `UsageRecipe` is exactly what the task names: an ORDERED SET of
`programming_sequence_ir.ProgrammingSequenceStep` objects, plus its own
documented `purpose` (what the recipe accomplishes) and `citation` (the real
source the recipe's existence and step selection is grounded in -- a
programming-guide section, an RTL comment, or the sequence document itself).
Both are REQUIRED, non-empty, and never defaulted -- see EVIDENCE TRUTH RULE
below.

REUSE OVER REINVENT -- NOTHING HERE RE-DERIVES A STEP OR A CHECK
-------------------------------------------------------------------
This module imports `programming_sequence_ir.py` directly (both modules are
mine in this batch -- there is no concurrent-ownership concern, unlike this
module's own duck-typed treatment of `register_excel_extract.py`) and reuses,
never reimplements:

  * `ProgrammingSequenceStep` / `ProgrammingSequenceIR` / `RegisterFact` --
    a recipe's steps ARE that module's real dataclass instances, not a
    parallel step shape.
  * `programming_sequence_ir_from_dict()` -- `usage_recipe_from_dict()`
    builds a recipe's steps by handing its raw `steps` list to THIS function
    (wrapped as a throwaway one-field document), so the real index-
    contiguity check, the real action/register-presence checks, and the real
    phase-uppercasing all run exactly once, in the one place that already
    owns them.
  * `validate_step_ordering()` -- `validate_recipe_ordering()` below builds a
    `ProgrammingSequenceIR` from a recipe's own steps and calls straight into
    it. The phase-order / access-type / dependency-ordering / documented-
    illegal-sequence checks are NOT re-implemented here at any grain -- a
    recipe's ordering is exactly as valid or invalid as the equivalent
    `ProgrammingSequenceIR` `programming_sequence_ir.py` would report, by
    construction, because it IS that check running over the recipe's steps.
  * `load_illegal_sequence_catalog()` / `IllegalSequencePattern` -- passed
    straight through to `validate_step_ordering()` unchanged.

The ONLY new mechanism this module adds is the ASSEMBLY of named,
purpose-cited step sets (from raw dicts, or by slicing an existing real
`ProgrammingSequenceIR`) and the multi-recipe CATALOG operations over them
(lookup, register cross-reference, and a worst-wins catalog-wide ordering
rollup) -- exactly the "distinct, higher-level artifact... over that
module's per-sequence facts" the task names, never a parallel step-ordering
validator.

TWO WAYS TO ASSEMBLE A RECIPE
------------------------------
1. `usage_recipe_from_dict(raw)` -- a recipe authored directly as its own
   document (`{"recipe_id", "purpose", "citation", "steps": [...]}`), the
   `steps` list shaped exactly like a `ProgrammingSequenceIR` document's own
   `steps`.
2. `usage_recipe_from_sequence_slice(ir, recipe_id, purpose, citation,
   step_indices)` -- assembled from a caller-selected, ORDER-PRESERVING
   subset of an EXISTING real `ProgrammingSequenceIR`'s own steps (real
   per-sequence facts `programming_sequence_ir.py` already carries), by
   `step.index`. `step_indices` must be strictly ascending -- a recipe that
   reordered its source sequence's steps would misrepresent what the
   sequence actually does, and this module never re-orders content it did
   not author. Because a subsequence of a phase-monotonic sequence is itself
   phase-monotonic, a recipe sliced this way from a sequence that already
   passes `validate_step_ordering()`'s phase check inherits that property for
   free -- nothing here re-derives it. Dependency ordering does NOT carry the
   same free guarantee: a slice that drops an earlier step a later, kept
   step's `depends_on` relied on can honestly re-surface
   `DEPENDENCY_NOT_YET_SATISFIED` when re-validated, exactly as it should --
   see the module's own test for a worked example.

EVIDENCE TRUTH RULE, applied to recipe ASSEMBLY specifically
--------------------------------------------------------------
A recipe with no `purpose`, no `citation`, or zero steps documents nothing
real and is refused at construction (`UsageRecipeError`), never silently
built with an empty/placeholder purpose or citation -- mirroring
`programming_sequence_ir.IllegalSequencePattern`'s identical "an uncited
claim cannot be accepted" discipline for its own `evidence` field. Ordering
VALIDATION (as opposed to assembly) keeps `programming_sequence_ir.py`'s own
honest-absence contract completely unchanged: no register facts supplied
still reports `NOT_AVAILABLE` (never a fabricated ORDER_VALID), because
`validate_recipe_ordering()` calls that module's real function and returns
its real status untouched, just annotated with the recipe's own metadata.

WORST-WINS COMPOSITE ROLLUP (multiple recipes, one verdict)
----------------------------------------------------------------
`validate_catalog_ordering()` validates every recipe in a catalog against the
SAME register facts and rolls the per-recipe statuses up into ONE overall
status using worst-wins, never averaging or counting a majority clean:
a single `ORDER_INVALID` recipe fails the whole rollup
(`RECIPE_CATALOG_ORDER_INVALID`) regardless of how many other recipes are
clean; short of that, a single recipe reporting `NOT_AVAILABLE`/
`NOT_APPLICABLE` (evidence honestly absent or nothing to check for at least
one recipe) still blocks an honest ALL_VALID claim
(`RECIPE_CATALOG_INCOMPLETE_EVIDENCE`); only when every recipe reports
`ORDER_VALID` does the rollup report `RECIPE_CATALOG_ALL_VALID`. See
`_rollup_catalog_status()`.

DELIBERATELY BOUNDED
---------------------
This module assembles and validates ORDERING of documented recipes -- it does
not decide WHICH steps of a real sequence deserve to become a recipe (that is
a caller/human documentation judgment, never guessed here) and it mines no
golden-reference environment (USB_UVM_Handoff / uvm_syoscb / ATB) for recipe
content; every recipe's steps and citation come from whatever the caller
actually supplies. It has no `gates.py`/`cli.py` wiring yet (file-safety
scope for this batch, matching `programming_sequence_ir.py`'s own identical
disclosed choice): the front door is
`python -m dv_harness.usage_recipe_catalog catalog --recipes <file> [--json]`
and
`python -m dv_harness.usage_recipe_catalog validate --recipes <file>
[--recipe-id <id>] [--facts <file>] [--catalog <file>] [--json]`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import programming_sequence_ir as psir

SCHEMA_VERSION = "1.0"

# Catalog-listing status vocabulary (describing WHAT recipes exist, never
# their ordering validity -- see STATUS_RECIPE_CATALOG_* below for that).
STATUS_CATALOG_AVAILABLE = "CATALOG_AVAILABLE"
STATUS_CATALOG_EMPTY = "CATALOG_EMPTY"

# Single-recipe lookup-miss status (never silently returned as "the first
# recipe" or an empty-but-successful report).
STATUS_RECIPE_NOT_FOUND = "RECIPE_NOT_FOUND"

# Catalog-wide, worst-wins ORDERING rollup status vocabulary -- deliberately
# distinct tokens from `programming_sequence_ir.py`'s own per-sequence
# STATUS_ORDER_*/STATUS_NOT_AVAILABLE/STATUS_NOT_APPLICABLE (those still
# appear, unmodified, inside this rollup's own `per_recipe` detail), and from
# `models.Status` (see `assert_no_verification_verdict_vocabulary()` below).
STATUS_RECIPE_CATALOG_ALL_VALID = "RECIPE_CATALOG_ALL_VALID"
STATUS_RECIPE_CATALOG_ORDER_INVALID = "RECIPE_CATALOG_ORDER_INVALID"
STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE = "RECIPE_CATALOG_INCOMPLETE_EVIDENCE"
STATUS_RECIPE_CATALOG_EMPTY = "RECIPE_CATALOG_EMPTY"


class UsageRecipeError(ValueError):
    """A usage-recipe document, slice request, or catalog is malformed --
    raised rather than silently coerced, so a caller can never validate or
    report on a recipe that was never actually well-formed (missing purpose,
    missing citation, zero steps, non-ascending slice indices, a duplicated
    recipe_id, ...)."""


@dataclass
class UsageRecipe:
    """A named, documented, ordered set of `ProgrammingSequenceStep`s --
    exactly the artifact the task names: steps + purpose + citation.

    Built ONLY through `usage_recipe_from_dict()` or
    `usage_recipe_from_sequence_slice()` in normal use, which enforce
    `recipe_id`/`purpose`/`citation` non-empty and `steps` non-empty; this
    dataclass itself performs no validation (the same "validation lives at
    the parsing boundary, not the dataclass" convention
    `programming_sequence_ir.RegisterFact`/`ProgrammingSequenceStep` already
    use), so a test constructing one directly for a narrow assertion is not
    forced through the full parsing path."""
    recipe_id: str
    purpose: str
    citation: str
    steps: List[psir.ProgrammingSequenceStep] = field(default_factory=list)
    source_sequence_name: Optional[str] = None
    rationale: Optional[str] = None
    applies_to: Optional[str] = None


# ---------------------------------------------------------------------------
# Construction / parsing
# ---------------------------------------------------------------------------

def _require_nonempty_str(value, field_name: str, *, where: str) -> str:
    if not value or not isinstance(value, str):
        raise UsageRecipeError(f"{where} requires a non-empty {field_name!r}, got {value!r}")
    return value


def usage_recipe_from_dict(raw: dict) -> UsageRecipe:
    """Build one `UsageRecipe` from a plain dict:
    `{"recipe_id", "purpose", "citation", "steps": [...], "source_sequence_name",
    "rationale", "applies_to"}`. `steps` is shaped exactly like a
    `ProgrammingSequenceIR` document's own `steps` list and is parsed by
    handing it straight to `programming_sequence_ir.programming_sequence_ir_from_dict()`
    (REUSE, not reimplementation -- see module docstring) wrapped as a
    throwaway `{"name": recipe_id, "steps": steps}` document purely to reuse
    that function's real step/index validation; only the resulting `.steps`
    is kept.

    Raises `UsageRecipeError` on a missing/empty `recipe_id`, `purpose`, or
    `citation`, on a missing/empty `steps` list, or on any step-shape defect
    `programming_sequence_ir_from_dict()` itself would reject."""
    if not isinstance(raw, dict):
        raise UsageRecipeError(f"usage recipe entry is not a dict: {raw!r}")
    recipe_id = raw.get("recipe_id")
    _require_nonempty_str(recipe_id, "recipe_id", where="usage recipe entry")
    purpose = raw.get("purpose")
    _require_nonempty_str(purpose, "purpose", where=f"usage recipe {recipe_id!r}")
    citation = raw.get("citation")
    if not citation or not isinstance(citation, str):
        raise UsageRecipeError(
            f"usage recipe {recipe_id!r} requires a non-empty 'citation' (a programming-guide "
            "section, an RTL comment, a register description, or the source sequence this "
            "recipe was assembled from) -- an uncited recipe cannot be accepted per the "
            "Evidence Truth Rule")
    raw_steps = raw.get("steps")
    if not raw_steps:
        raise UsageRecipeError(
            f"usage recipe {recipe_id!r} requires a non-empty 'steps' list -- a recipe "
            "documenting zero steps documents no usage at all")
    try:
        inner_ir = psir.programming_sequence_ir_from_dict({"name": recipe_id, "steps": raw_steps})
    except psir.ProgrammingSequenceIRError as e:
        raise UsageRecipeError(f"usage recipe {recipe_id!r} has malformed steps: {e}") from e

    return UsageRecipe(
        recipe_id=recipe_id, purpose=purpose, citation=citation, steps=inner_ir.steps,
        source_sequence_name=raw.get("source_sequence_name"),
        rationale=raw.get("rationale"), applies_to=raw.get("applies_to"),
    )


def usage_recipe_from_sequence_slice(
    ir: psir.ProgrammingSequenceIR,
    recipe_id: str,
    purpose: str,
    citation: str,
    step_indices: Sequence[int],
    *,
    rationale: Optional[str] = None,
    applies_to: Optional[str] = None,
) -> UsageRecipe:
    """Assemble a `UsageRecipe` from a caller-selected, ORDER-PRESERVING
    subset of an EXISTING real `ProgrammingSequenceIR`'s own steps, addressed
    by each step's real `.index` -- the "higher-level artifact... over that
    module's per-sequence facts" operation the task names. `step_indices`
    must be non-empty and strictly ascending (a recipe reordering its source
    sequence's steps would misrepresent what the sequence actually does) and
    every index must name a real step present in `ir.steps`. Raises
    `UsageRecipeError` otherwise, and on a missing/empty `recipe_id`,
    `purpose`, or `citation` (same Evidence Truth Rule as
    `usage_recipe_from_dict()`)."""
    _require_nonempty_str(recipe_id, "recipe_id", where="sequence-slice recipe")
    _require_nonempty_str(purpose, "purpose", where=f"usage recipe {recipe_id!r}")
    _require_nonempty_str(citation, "citation", where=f"usage recipe {recipe_id!r}")
    if not step_indices:
        raise UsageRecipeError(
            f"usage recipe {recipe_id!r} requires a non-empty 'step_indices' list -- a recipe "
            "documenting zero steps documents no usage at all")
    indices = list(step_indices)
    for prev, cur in zip(indices, indices[1:]):
        if cur <= prev:
            raise UsageRecipeError(
                f"usage recipe {recipe_id!r} step_indices must be strictly ascending, preserving "
                f"source sequence {ir.name!r}'s own step order; got {indices!r}")

    by_index = {s.index: s for s in ir.steps}
    missing = [i for i in indices if i not in by_index]
    if missing:
        raise UsageRecipeError(
            f"usage recipe {recipe_id!r} references step index/indices {missing!r} not present "
            f"in sequence {ir.name!r} (which has steps {sorted(by_index)!r})")

    return UsageRecipe(
        recipe_id=recipe_id, purpose=purpose, citation=citation,
        steps=[by_index[i] for i in indices], source_sequence_name=ir.name,
        rationale=rationale, applies_to=applies_to,
    )


def usage_recipe_catalog_from_dicts(raw_recipes: Optional[Sequence[dict]]) -> List[UsageRecipe]:
    """Build a list of `UsageRecipe` from plain dicts (e.g. loaded JSON).
    `None`/`[]` both come back as `[]`. Raises `UsageRecipeError` on any
    malformed entry (see `usage_recipe_from_dict()`) or on two entries
    reusing one `recipe_id` -- a catalog is a project's own documented
    knowledge base, and a duplicated id would make "which recipe" ambiguous,
    the same discipline `programming_sequence_ir.load_illegal_sequence_catalog()`
    already applies to its own `pattern_id`."""
    if not raw_recipes:
        return []
    out: List[UsageRecipe] = []
    seen_ids: set = set()
    for i, raw in enumerate(raw_recipes):
        try:
            recipe = usage_recipe_from_dict(raw)
        except UsageRecipeError as e:
            raise UsageRecipeError(f"usage recipe catalog entry {i}: {e}") from e
        if recipe.recipe_id in seen_ids:
            raise UsageRecipeError(
                f"usage recipe catalog entry {i} reuses recipe_id {recipe.recipe_id!r}, already "
                "declared earlier in this catalog")
        seen_ids.add(recipe.recipe_id)
        out.append(recipe)
    return out


# ---------------------------------------------------------------------------
# Catalog: multi-recipe lookup, cross-reference, reporting
# ---------------------------------------------------------------------------

@dataclass
class UsageRecipeCatalog:
    """A named, queryable collection of `UsageRecipe`s. Built once via
    `build()`, then queried as many times as needed."""
    recipes_by_id: Dict[str, UsageRecipe]

    @classmethod
    def build(cls, recipes: Sequence[UsageRecipe]) -> "UsageRecipeCatalog":
        by_id: Dict[str, UsageRecipe] = {}
        for r in recipes:
            if r.recipe_id in by_id:
                raise UsageRecipeError(
                    f"duplicate recipe_id {r.recipe_id!r} passed to UsageRecipeCatalog.build()")
            by_id[r.recipe_id] = r
        return cls(recipes_by_id=by_id)

    @property
    def recipe_ids(self) -> List[str]:
        return sorted(self.recipes_by_id)

    @property
    def recipe_count(self) -> int:
        return len(self.recipes_by_id)

    def get(self, recipe_id: str) -> Optional[UsageRecipe]:
        """`None` for an unknown recipe_id -- never the first/nearest recipe
        substituted for a lookup miss."""
        return self.recipes_by_id.get(recipe_id)

    def recipes_touching_register(self, register_name: str) -> List[str]:
        """Every recipe whose steps reference `register_name` at least once
        -- a real cross-recipe query no single `ProgrammingSequenceIR` could
        answer on its own, since a sequence knows nothing about any OTHER
        sequence's recipes."""
        return sorted(
            rid for rid, r in self.recipes_by_id.items()
            if any(s.register == register_name for s in r.steps)
        )

    def to_catalog_report(self) -> dict:
        """The honest, report-shaped listing of this catalog's contents --
        `CATALOG_EMPTY` naming that reason rather than a vacuous empty-but-
        "available" report when no recipes were supplied at all."""
        if not self.recipes_by_id:
            return {"schema_version": SCHEMA_VERSION, "status": STATUS_CATALOG_EMPTY,
                    "recipe_count": 0, "recipes": [],
                    "reason": "no usage recipes supplied -- nothing to report"}
        recipes = []
        for rid in self.recipe_ids:
            r = self.recipes_by_id[rid]
            recipes.append({
                "recipe_id": r.recipe_id, "purpose": r.purpose, "citation": r.citation,
                "source_sequence_name": r.source_sequence_name,
                "applies_to": r.applies_to, "step_count": len(r.steps),
                "phases_used": sorted({s.phase for s in r.steps}),
                "registers_touched": sorted({s.register for s in r.steps if s.register}),
            })
        return {"schema_version": SCHEMA_VERSION, "status": STATUS_CATALOG_AVAILABLE,
                "recipe_count": len(recipes), "recipes": recipes}


# ---------------------------------------------------------------------------
# Ordering validation -- pure delegation to programming_sequence_ir.py
# ---------------------------------------------------------------------------

def validate_recipe_ordering(
    recipe: UsageRecipe,
    register_facts: Optional[Sequence[psir.RegisterFact]],
    *,
    illegal_sequence_catalog: Optional[Sequence[psir.IllegalSequencePattern]] = None,
) -> dict:
    """Validate one recipe's step ordering by building a
    `programming_sequence_ir.ProgrammingSequenceIR` from its own steps and
    calling `programming_sequence_ir.validate_step_ordering()` directly --
    the real phase/access-type/dependency/illegal-sequence checks run
    unmodified; this function adds nothing but the recipe's own `recipe_id`/
    `purpose`/`citation` onto the returned report. In particular, no
    register facts supplied still reports `programming_sequence_ir.STATUS_NOT_AVAILABLE`
    unchanged -- this module never turns that honest absence into a
    fabricated ORDER_VALID."""
    ir = psir.ProgrammingSequenceIR(name=recipe.recipe_id, steps=list(recipe.steps))
    report = psir.validate_step_ordering(ir, register_facts,
                                          illegal_sequence_catalog=illegal_sequence_catalog)
    report["recipe_id"] = recipe.recipe_id
    report["purpose"] = recipe.purpose
    report["citation"] = recipe.citation
    return report


def _rollup_catalog_status(per_recipe_statuses: Sequence[str]) -> str:
    """Worst-wins composite over a set of per-recipe
    `programming_sequence_ir.py` statuses -- never averaged, never a simple
    majority. Priority (worst first): any `ORDER_INVALID` fails the whole
    rollup outright; short of that, any `NOT_AVAILABLE`/`NOT_APPLICABLE`
    (evidence honestly absent, or nothing to check, for at least one recipe)
    still blocks an honest ALL_VALID claim; only when every status is
    `ORDER_VALID` does the rollup report ALL_VALID. An empty input reports
    `RECIPE_CATALOG_EMPTY` rather than a vacuous ALL_VALID."""
    statuses = set(per_recipe_statuses)
    if not statuses:
        return STATUS_RECIPE_CATALOG_EMPTY
    if psir.STATUS_ORDER_INVALID in statuses:
        return STATUS_RECIPE_CATALOG_ORDER_INVALID
    if psir.STATUS_NOT_AVAILABLE in statuses or psir.STATUS_NOT_APPLICABLE in statuses:
        return STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE
    return STATUS_RECIPE_CATALOG_ALL_VALID


def validate_catalog_ordering(
    catalog: UsageRecipeCatalog,
    register_facts: Optional[Sequence[psir.RegisterFact]],
    *,
    illegal_sequence_catalog: Optional[Sequence[psir.IllegalSequencePattern]] = None,
) -> dict:
    """Validate every recipe in `catalog` against the SAME `register_facts`
    (and optional illegal-sequence catalog) and roll the per-recipe statuses
    up into one worst-wins overall status via `_rollup_catalog_status()`. The
    full per-recipe detail (each one's real `programming_sequence_ir.py`
    report, findings included) is always returned under `per_recipe`, keyed
    by `recipe_id` -- the rollup never hides which recipe(s) caused a
    non-ALL_VALID result."""
    per_recipe: Dict[str, dict] = {}
    for rid in catalog.recipe_ids:
        per_recipe[rid] = validate_recipe_ordering(
            catalog.recipes_by_id[rid], register_facts,
            illegal_sequence_catalog=illegal_sequence_catalog)
    overall = _rollup_catalog_status([r["status"] for r in per_recipe.values()])
    return {"schema_version": SCHEMA_VERSION, "status": overall,
            "recipe_count": len(per_recipe), "per_recipe": per_recipe}


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's status vocabulary must share no token with
    `models.Status` -- the same guarantee `programming_sequence_ir.py` (and
    `dependency_supply_chain.py`/`capability_evolution.py`/
    `verification_strategy.py`/`subsystem_maturity_gate.py`) each hold for
    their own vocabularies."""
    from .models import Status

    verdicts = {s.value for s in Status}
    own = {STATUS_CATALOG_AVAILABLE, STATUS_CATALOG_EMPTY, STATUS_RECIPE_NOT_FOUND,
           STATUS_RECIPE_CATALOG_ALL_VALID, STATUS_RECIPE_CATALOG_ORDER_INVALID,
           STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE, STATUS_RECIPE_CATALOG_EMPTY}
    overlap = own & verdicts
    if overlap:
        raise AssertionError(
            f"usage_recipe_catalog vocabulary collides with models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Ad hoc entry point
# ---------------------------------------------------------------------------

_RECIPE_EXIT_CODE_BY_STATUS = {
    psir.STATUS_ORDER_VALID: 0, psir.STATUS_ORDER_INVALID: 1,
    psir.STATUS_NOT_AVAILABLE: 2, psir.STATUS_NOT_APPLICABLE: 2,
}
_CATALOG_ORDERING_EXIT_CODE_BY_STATUS = {
    STATUS_RECIPE_CATALOG_ALL_VALID: 0, STATUS_RECIPE_CATALOG_ORDER_INVALID: 1,
    STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE: 2, STATUS_RECIPE_CATALOG_EMPTY: 2,
}


def _load_recipes(recipes_json: str) -> List[UsageRecipe]:
    raw = json.loads(Path(recipes_json).read_text(encoding="utf-8"))
    return usage_recipe_catalog_from_dicts(raw)


def execute_verb(verb: str, *, recipes_json: Optional[str] = None,
                  facts_json: Optional[str] = None, catalog_json: Optional[str] = None,
                  recipe_id: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for
    `python -m dv_harness.usage_recipe_catalog catalog --recipes <file> [--json]`
    and
    `... validate --recipes <file> [--recipe-id <id>] [--facts <file>] [--catalog <file>] [--json]`.
    Returns (text, exit_code). Reads only; runs/submits/approves nothing.

    `catalog`: 0 CATALOG_AVAILABLE, 2 CATALOG_EMPTY/malformed input.
    `validate` (single `--recipe-id`): 0 ORDER_VALID, 1 ORDER_INVALID,
    2 NOT_AVAILABLE/NOT_APPLICABLE/RECIPE_NOT_FOUND/malformed input.
    `validate` (whole catalog, no `--recipe-id`): 0 RECIPE_CATALOG_ALL_VALID,
    1 RECIPE_CATALOG_ORDER_INVALID, 2 RECIPE_CATALOG_INCOMPLETE_EVIDENCE/
    RECIPE_CATALOG_EMPTY/malformed input."""
    if verb == "catalog":
        if not recipes_json:
            return "catalog requires --recipes", 2
        try:
            recipes = _load_recipes(recipes_json)
        except UsageRecipeError as e:
            return f"UsageRecipeError: {e}", 2
        except (OSError, json.JSONDecodeError) as e:
            return f"failed to load input: {e}", 2

        report = UsageRecipeCatalog.build(recipes).to_catalog_report()
        code = 0 if report["status"] == STATUS_CATALOG_AVAILABLE else 2
        if as_json:
            return json.dumps(report, indent=2), code
        lines = [f"usage recipe catalog: {report['status']}",
                 f"  recipe_count={report['recipe_count']}"]
        if report.get("reason"):
            lines.append(f"  reason: {report['reason']}")
        for r in report.get("recipes", []):
            lines.append(f"  - {r['recipe_id']}: {r['step_count']} steps -- {r['purpose']} "
                         f"(citation: {r['citation']})")
        return "\n".join(lines), code

    if verb == "validate":
        if not recipes_json:
            return "validate requires --recipes", 2
        try:
            recipes = _load_recipes(recipes_json)
            facts_raw = json.loads(Path(facts_json).read_text(encoding="utf-8")) if facts_json else []
            facts = psir.register_facts_from_dicts(facts_raw)
            catalog_raw = json.loads(Path(catalog_json).read_text(encoding="utf-8")) if catalog_json else []
            illegal_catalog = psir.load_illegal_sequence_catalog(catalog_raw)
        except (UsageRecipeError, psir.ProgrammingSequenceIRError) as e:
            return f"{type(e).__name__}: {e}", 2
        except (OSError, json.JSONDecodeError) as e:
            return f"failed to load input: {e}", 2

        cat = UsageRecipeCatalog.build(recipes)

        if recipe_id:
            recipe = cat.get(recipe_id)
            if recipe is None:
                text = (f"recipe {recipe_id!r}: {STATUS_RECIPE_NOT_FOUND} -- not present in the "
                        f"supplied catalog (known recipe_ids: {cat.recipe_ids!r})")
                if as_json:
                    return json.dumps({"schema_version": SCHEMA_VERSION,
                                        "status": STATUS_RECIPE_NOT_FOUND,
                                        "recipe_id": recipe_id, "known_recipe_ids": cat.recipe_ids},
                                       indent=2), 2
                return text, 2

            report = validate_recipe_ordering(recipe, facts, illegal_sequence_catalog=illegal_catalog)
            code = _RECIPE_EXIT_CODE_BY_STATUS[report["status"]]
            if as_json:
                return json.dumps(report, indent=2), code
            lines = [f"recipe {report['recipe_id']!r}: {report['status']}",
                     f"  purpose: {report['purpose']}", f"  citation: {report['citation']}"]
            if report.get("reason"):
                lines.append(f"  reason: {report['reason']}")
            for f in report["findings"]:
                lines.append(f"  [{f['severity']}] {f['code']} (step {f['step_index']}): {f['message']}")
            return "\n".join(lines), code

        report = validate_catalog_ordering(cat, facts, illegal_sequence_catalog=illegal_catalog)
        code = _CATALOG_ORDERING_EXIT_CODE_BY_STATUS[report["status"]]
        if as_json:
            return json.dumps(report, indent=2), code
        lines = [f"usage recipe catalog validation: {report['status']}",
                 f"  recipe_count={report['recipe_count']}"]
        for rid, r in report["per_recipe"].items():
            lines.append(f"  - {rid}: {r['status']}")
        return "\n".join(lines), code

    return f"unknown usage-recipe-catalog verb {verb!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.usage_recipe_catalog",
        description="Assemble/list a catalog of documented usage recipes (named, ordered "
                    "programming_sequence_ir.py steps + purpose + citation) and validate their "
                    "step ordering against a duck-typed register-facts list by delegating to "
                    "programming_sequence_ir.validate_step_ordering(). Reads only; "
                    "runs/submits/approves nothing.")
    ap.add_argument("verb", choices=("catalog", "validate"))
    ap.add_argument("--recipes", default=None, dest="recipes_json",
                    help="Usage recipe catalog JSON: a list of {recipe_id, purpose, citation, "
                         "steps, source_sequence_name, rationale, applies_to} dicts.")
    ap.add_argument("--facts", default=None, dest="facts_json",
                    help="Register facts JSON (as programming_sequence_ir.py's --facts). "
                         "Optional for 'validate'; omitting it reports NOT_AVAILABLE per recipe.")
    ap.add_argument("--catalog", default=None, dest="catalog_json",
                    help="Illegal sequence catalog JSON (as programming_sequence_ir.py's "
                         "--catalog). Optional, 'validate' only.")
    ap.add_argument("--recipe-id", default=None, dest="recipe_id",
                    help="Validate only this one recipe (default: validate every recipe in "
                         "--recipes and report the worst-wins rollup). 'validate' only.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, recipes_json=a.recipes_json, facts_json=a.facts_json,
                              catalog_json=a.catalog_json, recipe_id=a.recipe_id, as_json=a.as_json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
