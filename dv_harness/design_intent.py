"""dv_harness/design_intent.py -- rows 9 and 11 of the asset-processing
table: the two document-distillation artifacts and their real consumers.

  row 9  DUT controller doc -> intent.md (state machine, modes, legal
         drop/backpressure conditions) -> scoreboard's ordering and
         exemption conditions.
  row 11 IP user guide / digital+analog doc -> constraints.md (timing,
         electrical limits, untestable items) -> exemption list.

Both were entirely absent: no intent.md, no constraints.md, no schema, no
consumer. `exemptions.py` existed but had no connection to any distilled
constraints document.

THE STRUCTURE-FIRST DESIGN, and why the markdown is generated rather than
authored. A hand-written `intent.md` is prose: a human can read it, but a
scoreboard cannot consume it, and the two drift apart the first time someone
edits one and not the other. So the SOURCE OF TRUTH here is a structured
YAML/JSON file validated against `dut_intent.schema.json` /
`constraints.schema.json`, and the `.md` is RENDERED from it. The markdown
stays the thing a human reads; the structure stays the thing code consumes;
they cannot disagree.

WHY EVERY CONDITION REQUIRES A `basis` CITATION. This is the part of these
schemas that carries real safety weight. A "legal drop condition" is, in
effect, an instruction to the scoreboard to NOT report a dropped packet. If
an agent may write one from general protocol knowledge, it can silently
license the exact failure the scoreboard exists to catch -- a false PASS
manufactured by an invented exemption. Requiring `document` + `section` on
every condition means an uncited condition cannot even validate. This module
transcribes and validates; it never authors intent.

The constraints -> exemptions bridge is deliberately built on
`exemptions.py`'s existing record contract rather than a parallel store, so
an untestable item lands in the same expiring, owned, reviewable list as
every other deliberate exemption -- `valid_until` and `owner` are required
here precisely because exemptions.schema.json requires them and has no
"no expiry" escape hatch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"
_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
INTENT_SCHEMA_PATH = _SCHEMA_DIR / "dut_intent.schema.json"
CONSTRAINTS_SCHEMA_PATH = _SCHEMA_DIR / "constraints.schema.json"


class DesignIntentValidationError(ValueError):
    """A dut_intent or constraints document fails validation. Raised rather
    than returned, matching the fail-closed discipline of every other
    schema-backed artifact in this package -- a scoreboard must never be
    configured from a document that did not validate."""


def _validate(doc: dict, schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise DesignIntentValidationError(
            f"jsonschema package is not installed; cannot validate against {schema_path.name}. "
            "Install it rather than skipping validation."
        ) from exc
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # FormatChecker is attached for the same reason exemptions.py attaches it:
    # `format: date` on valid_until is inert without it, so an impossible date
    # like 2026-02-30 would validate and only fail later at date parsing.
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise DesignIntentValidationError(f"{schema_path.name} validation failed:\n" + "\n".join(lines))


def validate_intent(doc: dict) -> None:
    """Validate against dut_intent.schema.json, then check referential
    integrity the schema cannot express: every state-machine transition must
    name states that actually exist. A transition to an undeclared state
    usually means a state was dropped while transcribing, and silently
    accepting it would leave the scoreboard modelling a machine the DUT
    document never described."""
    _validate(doc, INTENT_SCHEMA_PATH)
    states = {s["name"] for s in doc["state_machine"]["states"]}
    for i, tr in enumerate(doc["state_machine"]["transitions"]):
        for end in ("from", "to"):
            if tr[end] not in states:
                raise DesignIntentValidationError(
                    f"state_machine.transitions[{i}].{end} = {tr[end]!r} is not a declared state "
                    f"(declared: {sorted(states)}). A transition naming an undeclared state usually "
                    "means a state was dropped while transcribing the controller document."
                )


def validate_constraints(doc: dict) -> None:
    """Validate against constraints.schema.json, then check the one
    cross-field rule the schema cannot: a numeric timing/electrical bound
    must carry a unit. A bare `max: 5` is not a constraint -- 5 ns and 5 us
    differ by three orders of magnitude, and guessing which was meant is
    exactly the kind of silent fabrication these artifacts exist to
    prevent."""
    _validate(doc, CONSTRAINTS_SCHEMA_PATH)
    for group in ("timing_constraints", "electrical_limits"):
        for i, entry in enumerate(doc.get(group, [])):
            has_bound = any(entry.get(k) is not None for k in ("min", "typ", "max"))
            if has_bound and not entry.get("unit"):
                raise DesignIntentValidationError(
                    f"{group}[{i}] ({entry['id']}) declares a numeric bound but no `unit`. "
                    "A bound without a unit is not a constraint."
                )


def _load_structured(path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    if str(path).lower().endswith((".yaml", ".yml")):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def load_intent(path) -> dict:
    doc = _load_structured(path)
    validate_intent(doc)
    return doc


def load_constraints(path) -> dict:
    doc = _load_structured(path)
    validate_constraints(doc)
    return doc


# ---------------------------------------------------------------------------
# row 9 consumers: scoreboard ordering + exemption conditions
# ---------------------------------------------------------------------------

def ordering_rule_for(doc: dict, scope: str) -> Optional[dict]:
    """The documented ordering guarantee for `scope`, or None when the DUT
    document states none.

    None is meaningful and must NOT be read as "unordered": an absent rule
    means the document does not say, which is a question for a human, not a
    licence for the scoreboard to relax its comparison. `scoreboard_compare_mode()`
    below makes that explicit rather than leaving each caller to decide."""
    for rule in doc.get("ordering_rules", []):
        if rule["scope"] == scope:
            return rule
    return None


def scoreboard_compare_mode(doc: dict, scope: str) -> dict:
    """Translate the documented ordering guarantee into the comparison mode a
    scoreboard should use for `scope`.

    An undocumented scope returns mode `UNKNOWN` with `safe_default` set to
    the STRICTER choice (in-order), because relaxing a comparison on an
    undocumented guarantee is the direction that hides real bugs: an
    unordered compare silently accepts a genuine reordering defect."""
    rule = ordering_rule_for(doc, scope)
    if rule is None:
        return {
            "scope": scope, "mode": "UNKNOWN", "safe_default": "strict_in_order",
            "rationale": (
                f"the DUT controller document declares no ordering guarantee for scope {scope!r}. "
                "Comparing as a bag on an undocumented guarantee would silently accept a real "
                "reordering defect, so the strict comparison is the safe default -- and the gap "
                "should go to a human rather than being resolved by assumption."
            ),
            "basis": None,
        }
    return {
        "scope": scope, "mode": rule["guarantee"], "safe_default": rule["guarantee"],
        "rationale": rule.get("notes") or f"documented guarantee for scope {scope!r}",
        "basis": rule["basis"],
    }


def legal_drop_conditions(doc: dict, mode: Optional[str] = None) -> list:
    """Documented conditions under which a dropped transaction is legal,
    optionally filtered to an operating `mode`. A condition whose `mode` is
    null applies in every mode."""
    return [c for c in doc.get("legal_drop_conditions", [])
            if mode is None or c.get("mode") in (None, mode)]


def backpressure_conditions(doc: dict, mode: Optional[str] = None) -> list:
    """Documented conditions under which backpressure/stalling is legal.
    These relax TIMING expectations only -- a stalled transaction must still
    arrive intact, so a scoreboard must never use one to excuse a content
    mismatch."""
    return [c for c in doc.get("backpressure_conditions", [])
            if mode is None or c.get("mode") in (None, mode)]


def is_drop_legal(doc: dict, condition_id: str, mode: Optional[str] = None) -> bool:
    """Whether `condition_id` is a real, documented legal-drop condition for
    `mode`. A scoreboard calls this before suppressing a missing-transaction
    mismatch, so suppression is always traceable to a cited document section
    rather than to a hardcoded exception in checker code."""
    return any(c["id"] == condition_id for c in legal_drop_conditions(doc, mode=mode))


# ---------------------------------------------------------------------------
# row 11 consumer: the exemption list
# ---------------------------------------------------------------------------

def untestable_items_as_exemptions(doc: dict) -> list:
    """Convert every `untestable_items` entry into a record conforming to
    exemptions.schema.json (`id`, `check_id`, `reason`, `basis_document`,
    `owner`, `valid_until`).

    This is row 11's "-> exemption list" consumer, built on `exemptions.py`'s
    existing contract rather than a parallel store, so an untestable item
    becomes a tracked, expiring, owned exemption that
    `exemptions.check_expiry()`/`build_review_queue()` will surface for
    re-review -- instead of a sentence in a document nobody re-reads.

    `basis_document` is composed from the citation so the resulting exemption
    still points at the real user-guide section, satisfying the "never
    re-litigate why this is off from a code comment or word of mouth"
    purpose the exemptions schema was written for."""
    out = []
    for item in doc.get("untestable_items", []):
        basis = item["basis"]
        cite = f"{basis['document']} §{basis['section']}"
        if basis.get("version"):
            cite += f" (v{basis['version']})"
        if basis.get("page"):
            cite += f", p.{basis['page']}"
        out.append({
            "id": item["id"],
            "check_id": item["check_id"],
            "reason": f"{item['reason']} [untestable: {item['category']}]",
            "basis_document": cite,
            "owner": item["owner"],
            "valid_until": item["valid_until"],
        })
    return out


def write_exemptions_from_constraints(doc: dict, exemptions_path) -> list:
    """Add every untestable item to a real exemptions.yaml through
    `exemptions.add_exemption()` -- the existing, schema-validating entry
    point -- rather than writing the file directly here. An item whose id is
    already present is skipped, so re-running after a constraints update is
    idempotent and never duplicates an exemption."""
    from . import exemptions as _exemptions

    path = Path(exemptions_path)
    existing = {e["id"] for e in _exemptions.list_exemptions(path)} if path.exists() else set()
    added = []
    for entry in untestable_items_as_exemptions(doc):
        if entry["id"] in existing:
            continue
        _exemptions.add_exemption(path, entry)
        added.append(entry)
    return added


# ---------------------------------------------------------------------------
# renderers: intent.md and constraints.md
# ---------------------------------------------------------------------------

def _cite(basis: Optional[dict]) -> str:
    if not basis:
        return "_(uncited)_"
    out = f"{basis['document']} §{basis['section']}"
    if basis.get("version"):
        out += f" (v{basis['version']})"
    if basis.get("page"):
        out += f", p.{basis['page']}"
    return out


_GENERATED_BANNER = (
    "> GENERATED by `dv_harness/design_intent.py`. Do not hand-edit: edit the structured\n"
    "> source document and regenerate, so the prose a human reads and the structure the\n"
    "> scoreboard consumes cannot drift apart.\n"
)


def render_intent_markdown(doc: dict) -> str:
    """Render docs/intent.md from a validated dut_intent document."""
    sm = doc["state_machine"]
    lines = [f"# DUT Intent -- {doc['dut_name']}", "", _GENERATED_BANNER,
             f"Source: {_cite(doc['source'])}", "",
             "## Operating modes", ""]
    if doc["modes"]:
        lines += ["| Mode | Description | Basis |", "| --- | --- | --- |"]
        lines += [f"| `{m['name']}` | {m['description']} | {_cite(m['basis'])} |" for m in doc["modes"]]
    else:
        lines.append("_The controller document defines no distinct operating modes._")
    lines += ["", "## State machine", ""]
    lines += ["| State | Initial | Description |", "| --- | --- | --- |"]
    lines += [f"| `{s['name']}` | {'yes' if s.get('is_initial') else ''} | {s.get('description','')} |"
              for s in sm["states"]]
    lines += ["", "| From | To | Trigger | Basis |", "| --- | --- | --- | --- |"]
    lines += [f"| `{t['from']}` | `{t['to']}` | {t['trigger']} | {_cite(t.get('basis'))} |"
              for t in sm["transitions"]]

    lines += ["", "## Legal drop conditions", "",
              "A scoreboard may suppress a missing-transaction mismatch ONLY when one of these",
              "documented conditions holds. Each is checkable via",
              "`design_intent.is_drop_legal(doc, condition_id, mode)`.", ""]
    lines += _condition_table(doc["legal_drop_conditions"])
    lines += ["", "## Backpressure conditions", "",
              "These relax TIMING expectations only. A stalled transaction must still arrive",
              "intact -- none of these may be used to excuse a content mismatch.", ""]
    lines += _condition_table(doc["backpressure_conditions"])

    lines += ["", "## Ordering rules", "",
              "| Scope | Guarantee | Basis | Notes |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['scope']} | `{r['guarantee']}` | {_cite(r['basis'])} | {r.get('notes','')} |"
              for r in doc["ordering_rules"]]
    lines += ["",
              "A scope absent from this table resolves to `UNKNOWN` via",
              "`design_intent.scoreboard_compare_mode()`, whose safe default is the STRICTER",
              "in-order comparison -- an undocumented guarantee is a question for a human, never",
              "a licence to relax the check.", ""]
    return "\n".join(lines).rstrip() + "\n"


def _condition_table(conditions: list) -> list:
    if not conditions:
        return ["_None documented._"]
    rows = ["| ID | Applies when | Mode | Description | Basis |", "| --- | --- | --- | --- | --- |"]
    rows += [f"| `{c['id']}` | {c['applies_when']} | {c.get('mode') or 'all'} | "
             f"{c['description']} | {_cite(c['basis'])} |" for c in conditions]
    return rows


def render_constraints_markdown(doc: dict) -> str:
    """Render docs/constraints.md from a validated constraints document."""
    lines = [f"# Constraints -- {doc['ip_name']}", "", _GENERATED_BANNER,
             f"Source: {_cite(doc['source'])}", "", "## Timing constraints", ""]
    lines += _limit_table(doc["timing_constraints"], typ=True)
    lines += ["", "## Electrical limits", ""]
    lines += _limit_table(doc["electrical_limits"], typ=False)
    lines += ["", "## Untestable items", "",
              "Each row below is converted into a real, expiring, owned exemption record by",
              "`design_intent.write_exemptions_from_constraints()`, landing in the same",
              "`exemptions.yaml` that `dv-harness exemptions check` reviews. An untestable item",
              "is therefore never just a sentence in a document -- it has an owner and a review",
              "date, and it expires.", ""]
    if doc["untestable_items"]:
        lines += ["| ID | Check exempted | Category | Reason | Owner | Review by | Basis |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [f"| `{i['id']}` | `{i['check_id']}` | {i['category']} | {i['reason']} | "
                  f"{i['owner']} | {i['valid_until']} | {_cite(i['basis'])} |"
                  for i in doc["untestable_items"]]
    else:
        lines.append("_None documented._")
    return "\n".join(lines).rstrip() + "\n"


def _limit_table(entries: list, *, typ: bool) -> list:
    if not entries:
        return ["_None documented._"]
    head = "| ID | Parameter | Min | " + ("Typ | " if typ else "") + "Max | Unit | Description | Basis |"
    sep = "| --- | --- | --- | " + ("--- | " if typ else "") + "--- | --- | --- | --- |"
    rows = [head, sep]
    for e in entries:
        fmt = lambda v: "" if v is None else str(v)  # noqa: E731
        mid = f"{fmt(e.get('typ'))} | " if typ else ""
        rows.append(
            f"| `{e['id']}` | `{e['parameter']}` | {fmt(e.get('min'))} | {mid}"
            f"{fmt(e.get('max'))} | {e.get('unit') or ''} | {e['description']} | {_cite(e['basis'])} |"
        )
    return rows


def write_intent(doc: dict, out_dir) -> Path:
    """Write `docs/intent.md`, the exact tier-3 path CLAUDE.md's context
    budget names."""
    out = Path(out_dir) / "docs"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "intent.md"
    path.write_text(render_intent_markdown(doc), encoding="utf-8")
    return path


def write_constraints(doc: dict, out_dir) -> Path:
    """Write `docs/constraints.md`."""
    out = Path(out_dir) / "docs"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "constraints.md"
    path.write_text(render_constraints_markdown(doc), encoding="utf-8")
    return path
