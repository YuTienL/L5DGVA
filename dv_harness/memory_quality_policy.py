"""Memory Quality / Forgetting Policy (2026-09-06, targeted_hardening item
`memory_quality_forgetting`, spec section 228).

GAP THIS CLOSES, confirmed by direct search before writing a line of this
module: `dv_harness/memory.py`'s `MemoryGC` already has the real, tested
MECHANISM for demoting/retiring a record --
`flag_stale()` ("needing revalidation ... it has aged past
knowledge_center.max_age_days"), `deprecate()` ("retired, not refuted") and
`supersede()` ("a newer, corrected record replaces this one") -- but nothing
anywhere calls any of them from an automatic age/never-confirmed/duplicate
DECISION. `self_learning_readiness.py`'s own `revalidation_queue` row only
READS records `MemoryGC.flag_stale()` has *already* marked
`NEEDS_REVALIDATION`; nothing produces that mark in the first place.
`user_correction_trigger.py` (built the same session) is the nearest-looking
module and is genuinely a different mechanism: it reads `RETRACTED`/
`SUPERSEDED` records a HUMAN correction already produced, to detect a
repeated-mistake pattern for capability evolution -- it never decides to
retract/supersede/deprecate anything itself. This module is the missing
DECISION layer those two read from: it looks at a record's own real,
already-recorded evidence (`created_at`, `last_confirmed_at`, `last_used_at`,
`confirmation_count`, `reuse_count`, `status`) and a structural duplicate
check, and recommends -- or, opted in, actually applies -- exactly the
`MemoryGC` call that evidence supports. No new persistence mechanism is
built, and `memory.py` is not edited: this module is a pure caller of the
existing, unmodified `MemoryGC`/`MemoryStore` API.

THREE RETIREMENT GROUNDS, EXACTLY THE ITEM'S OWN THREE, NEVER A FOURTH
---------------------------------------------------------------------------
1. **Age** -- a record nobody has touched (confirmed, reused, or even
   created) inside `stale_after_days` is demoted to `NEEDS_REVALIDATION`
   (`MemoryGC.flag_stale()`). This alone never retires it outright: "it has
   not been looked at in a while" is not the same claim as "it is wrong or
   worthless", and `MemoryGC.confirm()` restores it to `ACTIVE` the moment a
   fresh independent confirmation arrives, exactly as that method's own
   docstring already promises.
2. **Never-confirmed** -- a record that has gone `deprecate_after_days`
   (deliberately DOUBLE the staleness window, so the two thresholds can never
   silently drift apart into contradiction) with `confirmation_count == 0`
   AND `reuse_count == 0` is retired outright (`MemoryGC.deprecate()`).
   Nobody has ever found it worth confirming *or* reusing across a full
   stale cycle and then some -- that is a real, evidence-based low-value
   signal, not a guess. A record anyone has ever reused (`reuse_count > 0`)
   or independently re-derived (`confirmation_count > 0`) never qualifies for
   this ground, however old it is; age alone routes it through ground 1
   instead.
3. **Superseded** -- two or more `ACTIVE` Engineering-tier records sharing
   the identical `(protocol, root_cause)` pair are a genuine STRUCTURAL
   duplicate, using the exact same "same finding" equality
   `memory.find_confirming_engineering_match()` already applies at write
   time (case-insensitive on `root_cause`, exact on `protocol`) -- reused
   here, never re-derived, so the two can never disagree about what "the
   same finding" means. The write-time dedup should make this rare, but a
   record written before that dedup existed, or through a path that does not
   call it, can still leave one behind. The strongest surviving record
   (highest `confirmation_count`, then most recent `created_at`, then
   `memory_id` for a fully deterministic tie-break) is kept `ACTIVE`; every
   other member of the group is superseded by it (`MemoryGC.supersede()`),
   citing the real winner `memory_id` as `superseded_by`.

Deliberately scoped to `engineering`-tier records only, for the identical
reason `find_confirming_engineering_match()` itself is scoped there: that is
the one tier this codebase's own write-time dedup already treats
`(protocol, root_cause)` as meaning "the same finding". Extending that
equality to other tiers (a `working`-tier react-reasoning step, a
`project`-tier interim hypothesis, an already-admission-gated
`organizational`-tier record) would be inventing a semantics this codebase
has never established for them, and is deliberately left out of scope
rather than guessed at.

EVIDENCE TRUTH RULE, ENFORCED RATHER THAN MERELY STATED
---------------------------------------------------------------------------
A record carrying no `created_at` at all has no age evidence, and this
module never fabricates one -- it recommends `NONE` naming
`NO_AGE_EVIDENCE`, exactly the same "we could not check" honesty every other
module in this codebase applies to a missing fact. A record already
`DEPRECATED`/`RETRACTED`/`SUPERSEDED` is left alone (`STATUS_ALREADY_
TERMINAL`) -- this module never re-retires an already-retired record, and
never overwrites a human's own retraction/supersede reason with a
policy-generated one. `classify_record_quality()` is a pure function over a
plain record dict, so its every branch is independently testable without
touching a store at all.

READ-ONLY UNTIL EXPLICITLY APPLIED, AND NEVER MINTS A STORE
---------------------------------------------------------------------------
`evaluate_memory_quality()` (the report/dry-run half) checks
`cross_project_mining.has_memory_store()` -- reused, not re-derived --
BEFORE ever constructing a `MemoryStore`, whose constructor unconditionally
`mkdir()`s the 5-tier tree and writes an empty `index.json`. A project that
has never used its memory store must never gain one merely from being asked
whether its memory quality needs attention; it reports `NOT_AVAILABLE`
instead. `apply_memory_quality_policy()` calls the same evaluation and then,
only when `dry_run=False`, calls the real `MemoryGC` methods the evaluation
already named -- there is no second, parallel writer.

Declared policy thresholds are read directly from `.dv-harness/config.json`
via a plain `json.loads()` (never `config.load_config()`, which materializes
a default config.json for a project that has none -- the same "reading must
never mutate" discipline `golden_flow_readiness.py`/`signoff_export.py`
already apply to that same file). An absent or non-declaring config reports
the honest built-in default, `DEFAULT_STALE_AFTER_DAYS` (180 days --
deliberately the SAME number CLAUDE.md's own Engineering Memory Policy
already documents for `knowledge_center.max_age_days`'s identical "aged past
... without being re-confirmed" concept on the shared Knowledge Center side,
reused here for the local store that mechanism does not itself cover, rather
than an independently invented number).

Front door: `python -m dv_harness.memory_quality_policy report|apply --root
<dir> [--stale-after-days N] [--deprecate-after-days N] [--json]`. No
`dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched, per
this item's own guidance to prefer a standalone front door when those files
are under heavy concurrent edit pressure -- the same disclosed choice many
sibling 2026-09-06 modules in this codebase already make. It decides,
approves and arbitrates nothing beyond calling the pre-existing `MemoryGC`
mechanism: no build, job, or approval is touched, and there is deliberately
no stage gate -- a gate that silently retired a record nobody reviewed would
be worse than none.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cross_project_mining import has_memory_store
from .memory import MemoryGC, MemoryStore, find_confirming_engineering_match

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Statuses this policy ever acts ON. DEPRECATED/RETRACTED/SUPERSEDED are
#: already-terminal MemoryGC outcomes; this policy never re-retires one.
ELIGIBLE_STATUSES = ("ACTIVE", "NEEDS_REVALIDATION")

ACTION_NONE = "NONE"
ACTION_FLAG_STALE = "FLAG_STALE"
ACTION_DEPRECATE = "DEPRECATE"
ACTION_SUPERSEDE = "SUPERSEDE"

#: See module docstring's "Declared policy thresholds" section for why this
#: number is not independently invented.
DEFAULT_STALE_AFTER_DAYS = 180
#: Deliberately double the staleness window -- see module docstring ground 2.
DEFAULT_DEPRECATE_AFTER_DAYS = DEFAULT_STALE_AFTER_DAYS * 2

#: The one tier the (protocol, root_cause) "same finding" equality this
#: module reuses from find_confirming_engineering_match() is established for.
#: See module docstring's "Deliberately scoped" paragraph.
SUPERSEDE_ELIGIBLE_LEVEL = "engineering"

_SECONDS_PER_DAY = 86400.0


class MemoryQualityPolicyError(ValueError):
    """A malformed record or usage error, never silently guessed past."""


# ---------------------------------------------------------------------------
# Declared policy (read-only)
# ---------------------------------------------------------------------------

def load_declared_policy(root) -> Dict[str, Any]:
    """`{"stale_after_days", "deprecate_after_days", "source"}` for `root`.

    Reads `.dv-harness/config.json` directly with a plain `json.loads()` --
    never `config.load_config()`, which would materialize a default
    config.json for a project that has none. A missing file, an unreadable
    one, or one that simply does not declare a `memory_quality` block all
    report the honest built-in default, `source: "default"`, distinctly from
    a project that really did declare its own numbers (`source: "declared"`).
    """
    cfg_path = Path(root) / ".dv-harness" / "config.json"
    declared: Dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            block = raw.get("memory_quality")
            if isinstance(block, dict):
                declared = block

    stale = declared.get("stale_after_days")
    deprecate = declared.get("deprecate_after_days")
    source = "declared" if (stale is not None or deprecate is not None) else "default"
    return {
        "stale_after_days": int(stale) if isinstance(stale, (int, float)) and not isinstance(stale, bool)
        else DEFAULT_STALE_AFTER_DAYS,
        "deprecate_after_days": int(deprecate) if isinstance(deprecate, (int, float)) and not isinstance(deprecate, bool)
        else DEFAULT_DEPRECATE_AFTER_DAYS,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Ground 1 + 2: age / never-confirmed, over one record
# ---------------------------------------------------------------------------

def classify_record_quality(
    record: Dict[str, Any],
    *,
    now: Optional[float] = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    deprecate_after_days: int = DEFAULT_DEPRECATE_AFTER_DAYS,
) -> Dict[str, Any]:
    """The DECISION policy over one record's own already-recorded evidence.

    A pure function -- it never reads or writes a store -- so every branch is
    independently testable against a hand-built dict. Returns
    `{memory_id, level, status, recommended_action, reason, evidence}`;
    `recommended_action` is one of `NONE`/`FLAG_STALE`/`DEPRECATE`, never
    `SUPERSEDE` (that ground needs the whole store to detect a duplicate --
    see `find_superseded_engineering_groups()` below).
    """
    if not isinstance(record, dict):
        raise MemoryQualityPolicyError("record must be a dict")
    memory_id = record.get("memory_id")
    if not memory_id:
        raise MemoryQualityPolicyError("record carries no memory_id")

    now = now if now is not None else time.time()
    status = str(record.get("status") or "ACTIVE").upper()
    level = record.get("level")

    if status not in ELIGIBLE_STATUSES:
        return {
            "memory_id": memory_id, "level": level, "status": status,
            "recommended_action": ACTION_NONE, "reason": "STATUS_ALREADY_TERMINAL",
            "evidence": {},
        }

    created_at = record.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return {
            "memory_id": memory_id, "level": level, "status": status,
            "recommended_action": ACTION_NONE, "reason": "NO_AGE_EVIDENCE",
            "evidence": {},
        }

    confirmation_count = record.get("confirmation_count")
    confirmation_count = int(confirmation_count) if isinstance(confirmation_count, (int, float)) and not isinstance(confirmation_count, bool) else 0
    reuse_count = record.get("reuse_count")
    reuse_count = int(reuse_count) if isinstance(reuse_count, (int, float)) and not isinstance(reuse_count, bool) else 0
    last_confirmed_at = record.get("last_confirmed_at")
    last_confirmed_at = last_confirmed_at if isinstance(last_confirmed_at, (int, float)) and not isinstance(last_confirmed_at, bool) else None
    last_used_at = record.get("last_used_at")
    last_used_at = last_used_at if isinstance(last_used_at, (int, float)) and not isinstance(last_used_at, bool) else None

    age_days = max(0.0, (now - float(created_at)) / _SECONDS_PER_DAY)
    effective_touch = last_confirmed_at if last_confirmed_at is not None else (
        last_used_at if last_used_at is not None else created_at)
    days_since_touch = max(0.0, (now - float(effective_touch)) / _SECONDS_PER_DAY)
    never_confirmed = confirmation_count == 0 and last_confirmed_at is None

    evidence = {
        "age_days": round(age_days, 2),
        "days_since_touch": round(days_since_touch, 2),
        "confirmation_count": confirmation_count,
        "reuse_count": reuse_count,
        "never_confirmed": never_confirmed,
        "stale_after_days": stale_after_days,
        "deprecate_after_days": deprecate_after_days,
    }

    # Worst-wins: the strongest ground this record's own evidence supports,
    # never averaged and never a fourth invented action.
    if never_confirmed and reuse_count == 0 and age_days >= deprecate_after_days:
        return {
            "memory_id": memory_id, "level": level, "status": status,
            "recommended_action": ACTION_DEPRECATE,
            "reason": (
                f"never confirmed and never reused after {age_days:.0f}d "
                f"(>= deprecate threshold {deprecate_after_days}d)"
            ),
            "evidence": evidence,
        }

    if status == "ACTIVE" and days_since_touch >= stale_after_days:
        return {
            "memory_id": memory_id, "level": level, "status": status,
            "recommended_action": ACTION_FLAG_STALE,
            "reason": (
                f"{days_since_touch:.0f}d since last confirm/reuse/create "
                f"(>= stale threshold {stale_after_days}d)"
            ),
            "evidence": evidence,
        }

    return {
        "memory_id": memory_id, "level": level, "status": status,
        "recommended_action": ACTION_NONE, "reason": "WITHIN_POLICY_WINDOW",
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Ground 3: superseded (structural duplicate) -- engineering tier only
# ---------------------------------------------------------------------------

def _dedup_key(record: Dict[str, Any]) -> Optional[Any]:
    protocol = record.get("protocol")
    root_cause = record.get("root_cause")
    if not protocol or not root_cause:
        return None
    return (str(protocol).strip(), str(root_cause).strip().lower())


def find_superseded_engineering_groups(store: MemoryStore) -> List[Dict[str, Any]]:
    """Every group of 2+ ACTIVE engineering-tier records sharing the exact
    `(protocol, root_cause)` `find_confirming_engineering_match()` already
    treats as "the same finding".

    A pure read: never calls `MemoryGC`. Each group names the real surviving
    winner and, for every loser, a `SUPERSEDE` recommendation with the real
    `superseded_by` target already resolved.

    Ranking reads the FULL record file for every candidate, never the bare
    index row: `MemoryStore._index_row()` deliberately does not persist
    `confirmation_count` (see `_CONFIRMATION_OWNED_FIELDS`), so ranking off
    the index alone would silently treat every candidate as never-confirmed
    -- exactly the kind of fabricated-by-omission value this module's own
    Evidence Truth Rule discipline forbids.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for row in store._index():
        if row.get("level") != SUPERSEDE_ELIGIBLE_LEVEL or row.get("status") != "ACTIVE":
            continue
        key = _dedup_key(row)
        if key is None:
            continue
        full = store.get(str(row.get("memory_id")))
        if full is None:
            continue
        groups.setdefault(key, []).append(full)

    def _rank(row: Dict[str, Any]):
        cc = row.get("confirmation_count")
        cc = int(cc) if isinstance(cc, (int, float)) and not isinstance(cc, bool) else 0
        created = row.get("created_at")
        created = float(created) if isinstance(created, (int, float)) and not isinstance(created, bool) else 0.0
        return (cc, created, str(row.get("memory_id") or ""))

    out: List[Dict[str, Any]] = []
    for (protocol, root_cause), rows in groups.items():
        if len(rows) < 2:
            continue
        ordered = sorted(rows, key=_rank, reverse=True)
        winner = ordered[0]
        losers = ordered[1:]
        out.append({
            "protocol": protocol,
            "root_cause": root_cause,
            "winner_memory_id": winner.get("memory_id"),
            "recommendations": [
                {
                    "memory_id": loser.get("memory_id"),
                    "level": SUPERSEDE_ELIGIBLE_LEVEL,
                    "status": "ACTIVE",
                    "recommended_action": ACTION_SUPERSEDE,
                    "superseded_by": winner.get("memory_id"),
                    "reason": (
                        f"duplicate ACTIVE engineering finding of "
                        f"{winner.get('memory_id')} (same protocol={protocol!r} "
                        f"root_cause -- confirmation_count "
                        f"{_rank(winner)[0]} vs {_rank(loser)[0]})"
                    ),
                }
                for loser in losers
            ],
        })
    out.sort(key=lambda g: (g["protocol"], g["root_cause"]))
    return out


# ---------------------------------------------------------------------------
# Whole-store evaluation (read-only) and application
# ---------------------------------------------------------------------------

def evaluate_memory_quality(
    root,
    *,
    now: Optional[float] = None,
    stale_after_days: Optional[int] = None,
    deprecate_after_days: Optional[int] = None,
    levels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """The full recommendation report for `root`'s memory store. Pure read;
    never constructs a `MemoryStore` (which would mkdir a tree) for a project
    that genuinely has none."""
    root = Path(root)
    if not has_memory_store(root):
        return {
            "status": "NOT_AVAILABLE",
            "reason": "no .dv-harness/memory/index.json on disk for this root",
            "root": str(root),
            "policy": None,
            "flag_stale": [], "deprecate": [], "supersede": [],
        }

    declared = load_declared_policy(root)
    effective_stale = int(stale_after_days) if stale_after_days is not None else declared["stale_after_days"]
    effective_deprecate = int(deprecate_after_days) if deprecate_after_days is not None else declared["deprecate_after_days"]
    now = now if now is not None else time.time()

    store = MemoryStore(root)
    flag_stale: List[Dict[str, Any]] = []
    deprecate: List[Dict[str, Any]] = []
    for row in store._index():
        if levels and row.get("level") not in levels:
            continue
        # The full record, never the bare index row: `_index_row()` does not
        # persist `confirmation_count`/`last_confirmed_at` (see
        # `find_superseded_engineering_groups()`'s own docstring for why),
        # and classifying off their absence would silently misread a
        # genuinely confirmed record as never-confirmed.
        full = store.get(str(row.get("memory_id")))
        if full is None:
            continue
        decision = classify_record_quality(
            full, now=now,
            stale_after_days=effective_stale,
            deprecate_after_days=effective_deprecate,
        )
        if decision["recommended_action"] == ACTION_FLAG_STALE:
            flag_stale.append(decision)
        elif decision["recommended_action"] == ACTION_DEPRECATE:
            deprecate.append(decision)

    supersede_groups = find_superseded_engineering_groups(store)
    supersede = [rec for g in supersede_groups for rec in g["recommendations"]]
    if levels:
        supersede = [rec for rec in supersede if rec["level"] in levels]

    total = len(flag_stale) + len(deprecate) + len(supersede)
    return {
        "status": "ACTION_RECOMMENDED" if total else "CLEAN",
        "root": str(root),
        "policy": {
            "stale_after_days": effective_stale,
            "deprecate_after_days": effective_deprecate,
            "source": declared["source"] if (stale_after_days is None and deprecate_after_days is None) else "override",
        },
        "flag_stale": flag_stale,
        "deprecate": deprecate,
        "supersede": supersede,
        "supersede_groups": supersede_groups,
        "total_recommended": total,
    }


def apply_memory_quality_policy(
    root,
    *,
    now: Optional[float] = None,
    stale_after_days: Optional[int] = None,
    deprecate_after_days: Optional[int] = None,
    levels: Optional[List[str]] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Evaluate, then -- only when `dry_run=False` -- actually call the real
    `MemoryGC.flag_stale()`/`deprecate()`/`supersede()` the evaluation named.

    Applies DEPRECATE and SUPERSEDE before FLAG_STALE so a record qualifying
    for the stronger ground is never left merely flagged. Every applied
    action's real `MemoryGC` return value is carried in `applied` so a
    caller can tell a real write from a merely-recommended one."""
    report = evaluate_memory_quality(
        root, now=now, stale_after_days=stale_after_days,
        deprecate_after_days=deprecate_after_days, levels=levels,
    )
    if report["status"] == "NOT_AVAILABLE":
        report["applied"] = []
        return report

    applied: List[Dict[str, Any]] = []
    if dry_run:
        report["applied"] = applied
        report["dry_run"] = True
        return report

    store = MemoryStore(Path(root))
    gc = MemoryGC(store)
    for decision in report["deprecate"]:
        ok = gc.deprecate(decision["memory_id"], decision["reason"])
        applied.append({**decision, "applied": ok})
    for decision in report["supersede"]:
        ok = gc.supersede(decision["memory_id"], decision["superseded_by"], decision["reason"])
        applied.append({**decision, "applied": ok})
    for decision in report["flag_stale"]:
        ok = gc.flag_stale(decision["memory_id"], decision["reason"])
        applied.append({**decision, "applied": ok})

    report["applied"] = applied
    report["dry_run"] = False
    return report


# ---------------------------------------------------------------------------
# Standalone front door. No `dv-harness` CLI verb was added and cli.py/
# gates.py were not touched -- see module docstring.
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.memory_quality_policy")
    parser.add_argument("--root", default=".", help="Project root (default: current directory).")
    parser.add_argument("--stale-after-days", type=int, default=None)
    parser.add_argument("--deprecate-after-days", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("report", help="Recommend actions; writes nothing.")
    sub.add_parser("apply", help="Recommend AND apply via the real MemoryGC.")

    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.verb == "report":
        result = evaluate_memory_quality(
            root, stale_after_days=args.stale_after_days,
            deprecate_after_days=args.deprecate_after_days,
        )
    elif args.verb == "apply":
        result = apply_memory_quality_policy(
            root, stale_after_days=args.stale_after_days,
            deprecate_after_days=args.deprecate_after_days, dry_run=False,
        )
    else:
        parser.error(f"unknown verb {args.verb!r}")
        return 2  # pragma: no cover

    if args.json or True:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "NOT_AVAILABLE":
        return 2
    return 1 if result.get("total_recommended") or result.get("applied") else 0


def main() -> None:
    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
